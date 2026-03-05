from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from chintu_backend.workflows import workflow_runner


def test_shell_command_preserves_arguments(monkeypatch, tmp_path):
    cfg = SimpleNamespace(
        skills_allow_shell=True,
        skills_enabled=True,
        skills_bundled_dir=None,
        skills_learned_dir=None,
        skills_user_dir=None,
        skills_dir=None,
        data_dir=tmp_path,
    )
    monkeypatch.setattr(workflow_runner, "get_config", lambda: cfg)

    script = tmp_path / "emit_arg.py"
    script.write_text(
        "import sys\nprint(sys.argv[1] if len(sys.argv) > 1 else '')\n",
        encoding="utf-8",
    )
    workflow_path = tmp_path / "shell_args_workflow.json"
    workflow = {
        "name": "shell_args",
        "steps": [
            {"id": "execute", "command": f"shell:python {script} hello_arg"},
        ],
    }
    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

    runner = workflow_runner.WorkflowRunner()
    result = runner.run_file(str(workflow_path), args={}, mode="tool")
    assert result.status == "ok"
    assert result.output and isinstance(result.output[0], dict)
    assert result.output[0]["stdout"] == "hello_arg"
