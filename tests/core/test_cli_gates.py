from __future__ import annotations

from types import SimpleNamespace

from chintu_backend import cli


def test_gates_cmd_phase29_forwards_flags(monkeypatch):
    calls = []

    def _fake(script_name, extra_args=None):
        calls.append((script_name, list(extra_args or [])))
        return 0

    monkeypatch.setattr(cli, "_run_gate_script", _fake)
    args = SimpleNamespace(subcommand="phase29", skip_workflow_benchmark=True, skip_eval_gate=True)
    rc = cli.gates_cmd(args)
    assert rc == 0
    assert calls == [("phase29_autonomy_integration_gate.py", ["--skip-workflow-benchmark", "--skip-eval-gate"])]


def test_gates_cmd_phase18_forwards_skip_flag(monkeypatch):
    calls = []

    def _fake(script_name, extra_args=None):
        calls.append((script_name, list(extra_args or [])))
        return 0

    monkeypatch.setattr(cli, "_run_gate_script", _fake)
    args = SimpleNamespace(subcommand="phase18", skip_flutter_tests=True)
    rc = cli.gates_cmd(args)
    assert rc == 0
    assert calls == [("phase18_ui_vnext_gate.py", ["--skip-flutter-tests"])]


def test_gates_cmd_all_returns_nonzero_when_any_gate_fails(monkeypatch):
    sequence = {
        "phase17_maintainability_gate.py": 0,
        "phase18_ui_vnext_gate.py": 0,
        "phase19_workflow_pack_benchmark.py": 1,
        "phase27_persona_specialist_gate.py": 0,
        "phase28_telegram_control_plane_gate.py": 0,
        "phase29_autonomy_integration_gate.py": 0,
        "deployment_preflight_gate.py": 0,
        "release_readiness_gate.py": 0,
    }

    def _fake(script_name, extra_args=None):
        return sequence.get(script_name, 1)

    monkeypatch.setattr(cli, "_run_gate_script", _fake)
    args = SimpleNamespace(
        subcommand="all",
        top_n=10,
        skip_flutter_tests=False,
        skip_workflow_benchmark=False,
        skip_eval_gate=False,
    )
    rc = cli.gates_cmd(args)
    assert rc == 1


def test_gates_cmd_all_invokes_preflight_and_release(monkeypatch):
    calls = []

    def _fake(script_name, extra_args=None):
        calls.append(script_name)
        return 0

    monkeypatch.setattr(cli, "_run_gate_script", _fake)
    rc = cli.gates_cmd(
        SimpleNamespace(
            subcommand="all",
            top_n=10,
            skip_flutter_tests=False,
            skip_workflow_benchmark=False,
            skip_eval_gate=False,
        )
    )
    assert rc == 0
    assert "deployment_preflight_gate.py" in calls
    assert "release_readiness_gate.py" in calls


def test_gates_cmd_phase27_and_phase28(monkeypatch):
    calls = []

    def _fake(script_name, extra_args=None):
        calls.append((script_name, list(extra_args or [])))
        return 0

    monkeypatch.setattr(cli, "_run_gate_script", _fake)
    rc27 = cli.gates_cmd(SimpleNamespace(subcommand="phase27"))
    rc28 = cli.gates_cmd(SimpleNamespace(subcommand="phase28"))
    assert rc27 == 0
    assert rc28 == 0
    assert calls == [
        ("phase27_persona_specialist_gate.py", []),
        ("phase28_telegram_control_plane_gate.py", []),
    ]


def test_gates_cmd_ci_forwards_skip_flag(monkeypatch):
    calls = []

    def _fake(script_name, extra_args=None):
        calls.append((script_name, list(extra_args or [])))
        return 0

    monkeypatch.setattr(cli, "_run_gate_script", _fake)
    rc = cli.gates_cmd(SimpleNamespace(subcommand="ci", skip_flutter_tests=True))
    assert rc == 0
    assert calls == [("ci_quality_gate.py", ["--skip-flutter-tests"])]


def test_gates_cmd_release_forwards_smoke_flag(monkeypatch):
    calls = []

    def _fake(script_name, extra_args=None):
        calls.append((script_name, list(extra_args or [])))
        return 0

    monkeypatch.setattr(cli, "_run_gate_script", _fake)
    rc = cli.gates_cmd(SimpleNamespace(subcommand="release", run_package_smoke=True))
    assert rc == 0
    assert calls == [("release_readiness_gate.py", ["--run-package-smoke"])]


def test_gates_cmd_preflight_forwards_flags(monkeypatch):
    calls = []

    def _fake(script_name, extra_args=None):
        calls.append((script_name, list(extra_args or [])))
        return 0

    monkeypatch.setattr(cli, "_run_gate_script", _fake)
    rc = cli.gates_cmd(
        SimpleNamespace(
            subcommand="preflight",
            run_doctor=True,
            run_docker_check=True,
            strict_docker=True,
        )
    )
    assert rc == 0
    assert calls == [
        ("deployment_preflight_gate.py", ["--run-doctor", "--run-docker-check", "--strict-docker"])
    ]
