"""Tests for sandbox CSV cleaning + chart generation capability."""

from pathlib import Path
from types import SimpleNamespace

from chintu_backend.automation import automation_capabilities as ac


def test_extract_dataset_path_from_text_variants():
    text = "Use 'sales_2025.csv' and run in sandbox."
    assert ac._extract_dataset_path_from_text(text) == "sales_2025.csv"

    text2 = "Dataset is reports/monthly-data.csv, generate chart."
    assert ac._extract_dataset_path_from_text(text2) == "reports/monthly-data.csv"


def test_resolve_dataset_prefers_downloads(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    desktop = tmp_path / "Desktop"
    workspace = tmp_path / "workspace"
    downloads.mkdir(parents=True)
    desktop.mkdir(parents=True)
    workspace.mkdir(parents=True)
    target = downloads / "sales_2025.csv"
    target.write_text("date,sales\n2025-01-01,100\n", encoding="utf-8")

    path = ac._resolve_dataset_path(
        "sales_2025.csv",
        {
            "_user_downloads_dir": str(downloads),
            "_user_desktop_dir": str(desktop),
            "workspace_dir": str(workspace),
        },
    )
    assert path is not None
    assert path.resolve() == target.resolve()


def test_handle_sandbox_data_task_success(tmp_path: Path, monkeypatch):
    downloads = tmp_path / "Downloads"
    desktop = tmp_path / "Desktop"
    workspace = tmp_path / "workspace"
    downloads.mkdir(parents=True)
    desktop.mkdir(parents=True)
    workspace.mkdir(parents=True)
    (downloads / "sales_2025.csv").write_text(
        "date,sales,region\n2025-01-01,100,North\n2025-01-02,,South\n",
        encoding="utf-8",
    )

    class _FakeManager:
        def run_shell(
            self,
            command,
            *,
            action_kind,
            context,
            cwd,
            requested_placement,
            allow_network,
            timeout_seconds,
        ):
            assert "pip install" in command
            assert "run_data_task.py" in command
            assert action_kind == "code"
            assert requested_placement == "sandbox"
            assert allow_network is True

            cwd_path = Path(cwd)
            (cwd_path / "sales_2025_trend.png").write_bytes(b"fakepng")
            (cwd_path / "sales_2025_cleaned.csv").write_text("date,sales,region\n2025-01-01,100,North\n", encoding="utf-8")
            receipt = cwd_path / "receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                success=True,
                exit_code=0,
                stdout='{"nulls_before":1,"nulls_after":0}',
                stderr="",
                receipt_path=receipt,
                placement=SimpleNamespace(value="sandbox"),
            )

    monkeypatch.setattr("chintu_backend.workspace.get_workspace_manager", lambda: _FakeManager())

    result = ac.handle_sandbox_data_task(
        "I have a messy dataset called sales_2025.csv in my Downloads. "
        "Write a Python script to clean the null values, generate a matplotlib trend chart, "
        "and save the chart to my Desktop. Do not run the code on my main OS - execute it in the sandbox.",
        {
            "workspace_dir": str(workspace),
            "_user_downloads_dir": str(downloads),
            "_user_desktop_dir": str(desktop),
            "session_id": "test-session",
        },
    )

    assert result.success is True
    assert "Sandbox data task completed." in result.message
    assert (desktop / "sales_2025_trend.png").exists()
    assert (desktop / "sales_2025_cleaned.csv").exists()
    assert result.capability_name == "sandbox_data_task"


def test_handle_sandbox_data_task_missing_file(tmp_path: Path):
    result = ac.handle_sandbox_data_task(
        "Clean sales_2025.csv in sandbox and create trend chart.",
        {
            "workspace_dir": str(tmp_path / "workspace"),
            "_user_downloads_dir": str(tmp_path / "Downloads"),
            "_user_desktop_dir": str(tmp_path / "Desktop"),
            "session_id": "test-session",
        },
    )
    assert result.success is False
    assert "Could not find dataset" in result.message


def test_handle_sandbox_data_task_short_alias_prompt(tmp_path: Path, monkeypatch):
    downloads = tmp_path / "Downloads"
    desktop = tmp_path / "Desktop"
    workspace = tmp_path / "workspace"
    downloads.mkdir(parents=True)
    desktop.mkdir(parents=True)
    workspace.mkdir(parents=True)
    (downloads / "sales_2025.csv").write_text(
        "date,sales\n2025-01-01,100\n2025-01-02,\n",
        encoding="utf-8",
    )

    class _FakeManager:
        def run_shell(
            self,
            command,
            *,
            action_kind,
            context,
            cwd,
            requested_placement,
            allow_network,
            timeout_seconds,
        ):
            cwd_path = Path(cwd)
            (cwd_path / "sales_2025_trend.png").write_bytes(b"fakepng")
            (cwd_path / "sales_2025_cleaned.csv").write_text("date,sales\n2025-01-01,100\n", encoding="utf-8")
            receipt = cwd_path / "receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                success=True,
                exit_code=0,
                stdout='{"nulls_before":1,"nulls_after":0}',
                stderr="",
                receipt_path=receipt,
                placement=SimpleNamespace(value="sandbox"),
            )

    monkeypatch.setattr("chintu_backend.workspace.get_workspace_manager", lambda: _FakeManager())

    result = ac.handle_sandbox_data_task(
        "Analyze sales_2025.csv in sandbox",
        {
            "workspace_dir": str(workspace),
            "_user_downloads_dir": str(downloads),
            "_user_desktop_dir": str(desktop),
            "session_id": "test-session",
        },
    )

    assert result.success is True
    assert result.capability_name == "sandbox_data_task"
    assert (desktop / "sales_2025_trend.png").exists()
