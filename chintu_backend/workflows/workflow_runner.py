"""Deterministic workflow runner inspired by Lobster."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from chintu_backend.core.capabilities import ActionResult, get_registry
from chintu_backend.core.config import get_config
from chintu_backend.automation.skills.skill_registry import SkillRegistry, _is_skill_available, slugify


@dataclass
class WorkflowStep:
    id: str
    command: str
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None
    stdin: Optional[Any] = None
    approval: Optional[Any] = None
    condition: Optional[Any] = None
    requires_env: Optional[List[str]] = None
    requires_bin: Optional[List[str]] = None
    setup: Optional[str] = None


@dataclass
class WorkflowFile:
    name: Optional[str] = None
    description: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None
    steps: List[WorkflowStep] = field(default_factory=list)


@dataclass
class WorkflowStepResult:
    id: str
    stdout: Optional[str] = None
    json: Optional[Any] = None
    approved: Optional[bool] = None
    skipped: Optional[bool] = None


@dataclass
class WorkflowApprovalRequest:
    prompt: str
    items: List[Any]
    preview: Optional[str] = None
    resume_token: Optional[str] = None


@dataclass
class WorkflowRunResult:
    status: str
    output: List[Any] = field(default_factory=list)
    requires_approval: Optional[WorkflowApprovalRequest] = None
    message: Optional[str] = None
    resume_token: Optional[str] = None
    missing: Optional[Dict[str, Any]] = None


class WorkflowRunner:
    def __init__(self) -> None:
        self.config = get_config()
        self._skill_cache: Optional[Dict[str, Any]] = None

    def run_file(
        self: "WorkflowRunner",
        file_path: str,
        args: Optional[Dict[str, Any]] = None,
        resume_token: Optional[str] = None,
        approved: Optional[bool] = None,
        mode: str = "tool",
    ) -> WorkflowRunResult:
        resume_state = None
        if resume_token:
            resume_state = _load_resume_state(self.config, resume_token)
        workflow = _load_workflow_file(file_path if not resume_state else resume_state["file_path"])
        provided_args = args if args is not None else (resume_state.get("args") if resume_state else None)
        resolved_args = _resolve_args(workflow.args, provided_args)
        results: Dict[str, WorkflowStepResult] = resume_state.get("steps", {}) if resume_state else {}
        start_index = resume_state.get("resume_at", 0) if resume_state else 0
        outputs: List[Dict[str, Any]] = []

        if resume_state and resume_state.get("approval_step_id") and approved is not None:
            step_id = resume_state["approval_step_id"]
            previous = results.get(step_id, WorkflowStepResult(id=step_id))
            previous.approved = bool(approved)
            results[step_id] = previous

        last_step_id: Optional[str] = None

        for idx in range(start_index, len(workflow.steps)):
            step = workflow.steps[idx]

            if not _evaluate_condition(step.condition, results):
                results[step.id] = WorkflowStepResult(id=step.id, skipped=True)
                continue

            command = _resolve_template(step.command, resolved_args, results)
            stdin_value = _resolve_stdin(step.stdin, resolved_args, results)
            env = _merge_env(workflow.env, step.env, resolved_args, results)
            cwd = _resolve_cwd(step.cwd or workflow.cwd, resolved_args, results)

            missing_env, missing_bin = _check_requirements(step, env)
            if missing_env or missing_bin:
                _render_missing_credentials(step, missing_env)
                message = _build_requirement_message(step, missing_env, missing_bin)
                resume_token = _save_resume_state(
                    self.config,
                    file_path if not resume_state else resume_state["file_path"],
                    idx,
                    results,
                    resolved_args,
                    approval_step_id=None,
                )
                return WorkflowRunResult(
                    status="needs_setup",
                    message=message,
                    resume_token=resume_token,
                    missing={"env": missing_env, "bin": missing_bin, "step": step.id},
                )

            exec_result = self._execute_command(command, stdin_value, env, cwd, mode)

            if isinstance(exec_result, ActionResult):
                if exec_result.requires_confirmation:
                    _clear_pending_confirmation()
                    approval = _build_approval_request(step, exec_result.message)
                    resume_token = _save_resume_state(
                        self.config,
                        file_path if not resume_state else resume_state["file_path"],
                        idx + 1,
                        results,
                        resolved_args,
                        approval_step_id=step.id,
                    )
                    approval.resume_token = resume_token
                    return WorkflowRunResult(status="needs_approval", requires_approval=approval)

                stdout = exec_result.message
                json_data = exec_result.data if isinstance(exec_result.data, (dict, list)) else _try_parse_json(stdout)
            else:
                stdout = exec_result.get("stdout")
                json_data = exec_result.get("json")

            results[step.id] = WorkflowStepResult(id=step.id, stdout=stdout, json=json_data)
            outputs.append({"step": step.id, "stdout": stdout, "json": json_data})
            last_step_id = step.id

            if _is_approval_step(step.approval):
                approval = _build_approval_request(step, stdout)
                resume_token = _save_resume_state(
                    self.config,
                    file_path if not resume_state else resume_state["file_path"],
                    idx + 1,
                    results,
                    resolved_args,
                    approval_step_id=step.id,
                )
                approval.resume_token = resume_token
                return WorkflowRunResult(status="needs_approval", requires_approval=approval)

        output = _to_output_items(results.get(last_step_id)) if last_step_id else []
        if outputs:
            return WorkflowRunResult(status="ok", output=outputs)
        return WorkflowRunResult(status="ok", output=output)

    def resume(self: "WorkflowRunner", token: str, approved: Optional[bool], mode: str = "tool") -> WorkflowRunResult:
        return self.run_file(file_path="", resume_token=token, approved=approved, mode=mode)

    def _execute_command(
        self,
        command: str,
        stdin_value: Optional[str],
        env: Dict[str, str],
        cwd: Optional[str],
        mode: str,
    ) -> Any:
        if not command or not isinstance(command, str):
            raise ValueError("Workflow command must be a string")

        cmd_type, name, raw_args = _parse_command(command)
        if cmd_type == "capability":
            registry = get_registry()
            cap = registry.get(name)
            if not cap:
                raise ValueError(f"Unknown capability: {name}")
            ctx = {"_workflow": True, "_workflow_mode": mode}
            result = registry.execute(cap, command, ctx)
            if result.requires_confirmation:
                return result
            if not result.success:
                raise RuntimeError(result.message)
            return result

        if cmd_type == "skill":
            spec = self._get_skill_spec(name)
            if not spec:
                raise ValueError(f"Unknown skill: {name}")
            if not _is_skill_available(spec):
                raise ValueError(f"Skill requirements not met: {name}")
            if not self.config.skills_enabled:
                raise ValueError("Skills are disabled. Enable CHINTU_SKILLS_ENABLED.")
            if spec.kind == "shell" and not self.config.skills_allow_shell:
                raise ValueError("Shell skills are disabled. Enable CHINTU_SKILLS_ALLOW_SHELL.")

            missing_env = [key for key in spec.requires_env if not (os.getenv(key) or env.get(key))]
            if missing_env:
                try:
                    from chintu_backend.ui import get_a2ui_service

                    get_a2ui_service().render_credential_prompt(
                        keys=missing_env,
                        title="Connect Required Credentials",
                        description="Workflow needs these credentials to continue.",
                        view_id=f"credentials:workflow:{slugify(name)}",
                        source=f"workflow:{slugify(name)}",
                    )
                except Exception:
                    pass
                missing = ", ".join(missing_env)
                raise ValueError(f"Missing required credentials: {missing}")

            params = _extract_skill_args(spec.args, raw_args)
            cmd = spec.command.format(**params)
            return _run_shell(cmd, stdin_value, env, cwd)

        if cmd_type == "shell":
            if not self.config.skills_allow_shell:
                raise ValueError("Shell execution blocked. Enable CHINTU_SKILLS_ALLOW_SHELL.")
            command_text = name if not raw_args else f"{name} {raw_args}"
            return _run_shell(command_text, stdin_value, env, cwd)

        raise ValueError(f"Unsupported command type: {cmd_type}")

    def _get_skill_spec(self, name: str):
        if self._skill_cache is None:
            registry = SkillRegistry()
            sources = [
                (self.config.skills_bundled_dir, "bundled"),
                (self.config.skills_learned_dir, "learned"),
                (self.config.skills_user_dir, "user"),
                (self.config.skills_dir, "workspace"),
            ]
            registry.load_sources([(p, label) for p, label in sources if p])
            self._skill_cache = registry._skills
        return self._skill_cache.get(slugify(name))


def _parse_command(command: str) -> Tuple[str, str, str]:
    stripped = command.strip()
    for prefix, kind in (("skill:", "skill"), ("capability:", "capability"), ("shell:", "shell")):
        if stripped.lower().startswith(prefix):
            remainder = stripped[len(prefix):].strip()
            name, args = _split_command(remainder)
            return kind, name, args

    name, args = _split_command(stripped)
    if get_registry().get(name):
        return "capability", name, args

    return "shell", stripped, ""


def _split_command(command: str) -> Tuple[str, str]:
    parts = command.split(maxsplit=1)
    if not parts:
        return "", ""
    name = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    return name, args


def _extract_skill_args(arg_names: Iterable[str], raw_args: str) -> Dict[str, str]:
    params: Dict[str, str] = {}
    names = list(arg_names or [])
    if not names:
        return params

    lowered = raw_args.lower()
    for arg in names:
        marker = f"{arg}="
        if marker in lowered:
            idx = lowered.index(marker)
            raw = raw_args[idx + len(marker):].strip()
            params[arg] = raw.split()[0]

    if len(names) == 1 and names[0] not in params:
        params[names[0]] = raw_args

    return params


def _run_shell(command: str, stdin_value: Optional[str], env: Dict[str, str], cwd: Optional[str]) -> Dict[str, Any]:
    import subprocess
    import shlex

    merged_env = os.environ.copy()
    merged_env.update({k: str(v) for k, v in (env or {}).items() if v is not None})

    # Security: avoid shell=True to prevent injection. Require explicit executable.
    if any(op in command for op in ["|", "&", ";", ">", "<"]):
        raise RuntimeError("Shell operators are disabled. Use explicit executables without pipes/redirection.")

    try:
        args = shlex.split(command, posix=os.name != "nt")
    except Exception:
        args = [command]

    result = subprocess.run(
        args,
        shell=False,
        text=True,
        input=stdin_value or "",
        capture_output=True,
        env=merged_env,
        cwd=cwd or os.getcwd(),
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Shell command failed")
    stdout = result.stdout.strip()
    return {"stdout": stdout, "json": _try_parse_json(stdout)}


def _clear_pending_confirmation() -> None:
    try:
        get_registry().cancel_pending()
    except Exception:
        pass


def _load_workflow_file(path: str) -> WorkflowFile:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Workflow file not found: {path}")

    text = file_path.read_text(encoding="utf-8")
    ext = file_path.suffix.lower()
    if ext in (".yml", ".yaml", ".lobster"):
        try:
            import yaml
        except Exception as exc:
            raise RuntimeError("YAML workflows require PyYAML installed") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    if not isinstance(data, dict):
        raise ValueError("Workflow file must be a JSON/YAML object")

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Workflow file requires a non-empty steps array")

    workflow = WorkflowFile(
        name=data.get("name"),
        description=data.get("description"),
        args=data.get("args"),
        env=data.get("env"),
        cwd=data.get("cwd"),
        steps=[_parse_step(step) for step in steps],
    )

    seen = set()
    for step in workflow.steps:
        if step.id in seen:
            raise ValueError(f"Duplicate workflow step id: {step.id}")
        seen.add(step.id)

    return workflow


def _parse_step(step: Any) -> WorkflowStep:
    if not isinstance(step, dict):
        raise ValueError("Workflow step must be an object")
    step_id = step.get("id")
    command = step.get("command")
    if not step_id or not isinstance(step_id, str):
        raise ValueError("Workflow step requires an id")
    if not command or not isinstance(command, str):
        raise ValueError(f"Workflow step {step_id} requires a command string")
    return WorkflowStep(
        id=step_id,
        command=command,
        env=step.get("env"),
        cwd=step.get("cwd"),
        stdin=step.get("stdin"),
        approval=step.get("approval"),
        condition=step.get("condition") or step.get("when"),
        requires_env=_normalize_list(step.get("requires_env") or step.get("requires-env")),
        requires_bin=_normalize_list(step.get("requires_bin") or step.get("requires-bin")),
        setup=_first_string(step.get("setup") or step.get("instructions")),
    )


def _resolve_args(arg_defs: Optional[Dict[str, Any]], provided: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    if isinstance(arg_defs, dict):
        for key, value in arg_defs.items():
            if isinstance(value, dict) and "default" in value:
                resolved[key] = value.get("default")
            elif value is not None and not isinstance(value, dict):
                resolved[key] = value
    if provided:
        resolved.update(provided)
    return resolved


def _normalize_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
        return items or None
    return None


def _first_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _resolve_template(text: str, args: Dict[str, Any], results: Dict[str, WorkflowStepResult]) -> str:
    if not text:
        return ""

    text = re.sub(r"\$\{([A-Za-z0-9_-]+)\}", lambda m: str(args.get(m.group(1), m.group(0))), text)

    def replace_step(match: re.Match) -> str:
        step_id = match.group(1)
        field = match.group(2)
        step = results.get(step_id)
        if not step:
            return match.group(0)
        if field == "stdout":
            return step.stdout or ""
        if field == "json":
            return json.dumps(step.json) if step.json is not None else ""
        if field == "approved":
            return "true" if step.approved else "false"
        return match.group(0)

    text = re.sub(r"\$([A-Za-z0-9_-]+)\.(stdout|json|approved)", replace_step, text)
    return text


def _resolve_stdin(stdin: Any, args: Dict[str, Any], results: Dict[str, WorkflowStepResult]) -> Optional[str]:
    if stdin is None:
        return None
    if isinstance(stdin, str):
        trimmed = stdin.strip()
        step_ref = re.match(r"^\$([A-Za-z0-9_-]+)\.(stdout|json)$", trimmed)
        if step_ref:
            step = results.get(step_ref.group(1))
            if not step:
                raise ValueError(f"Unknown step reference: {trimmed}")
            return step.stdout if step_ref.group(2) == "stdout" else json.dumps(step.json)
        return _resolve_template(trimmed, args, results)
    return json.dumps(stdin)


def _merge_env(
    workflow_env: Optional[Dict[str, str]],
    step_env: Optional[Dict[str, str]],
    args: Dict[str, Any],
    results: Dict[str, WorkflowStepResult],
) -> Dict[str, str]:
    env: Dict[str, str] = {}

    def apply(source: Optional[Dict[str, str]]) -> None:
        if not isinstance(source, dict):
            return
        for key, value in source.items():
            if value is None:
                continue
            env[key] = _resolve_template(str(value), args, results)

    apply(workflow_env)
    apply(step_env)
    return env


def _resolve_cwd(
    cwd: Optional[str],
    args: Dict[str, Any],
    results: Dict[str, WorkflowStepResult],
) -> Optional[str]:
    if not cwd:
        return None
    return _resolve_template(str(cwd), args, results)


def _evaluate_condition(condition: Any, results: Dict[str, WorkflowStepResult]) -> bool:
    if condition is None:
        return True
    if isinstance(condition, bool):
        return condition
    if not isinstance(condition, str):
        raise ValueError("Unsupported condition type")

    trimmed = condition.strip().lower()
    if trimmed == "true":
        return True
    if trimmed == "false":
        return False

    match = re.match(r"^\$([A-Za-z0-9_-]+)\.(approved|skipped)$", trimmed)
    if not match:
        raise ValueError(f"Unsupported condition: {condition}")

    step = results.get(match.group(1))
    if not step:
        return False

    if match.group(2) == "approved":
        return step.approved is True
    return step.skipped is True


def _check_requirements(step: WorkflowStep, env: Dict[str, str]) -> Tuple[List[str], List[str]]:
    missing_env: List[str] = []
    missing_bin: List[str] = []

    for key in step.requires_env or []:
        if not (os.getenv(key) or env.get(key)):
            missing_env.append(key)

    for bin_name in step.requires_bin or []:
        if shutil.which(bin_name) is None:
            missing_bin.append(bin_name)

    return missing_env, missing_bin


def _render_missing_credentials(step: WorkflowStep, missing_env: List[str]) -> None:
    if not missing_env:
        return
    try:
        from chintu_backend.ui import get_a2ui_service

        description = step.setup or "Provide the required credentials so this workflow can continue."
        get_a2ui_service().render_credential_prompt(
            keys=missing_env,
            title="Workflow needs credentials",
            description=description,
            view_id=f"credentials:workflow:{slugify(step.id)}",
            source=f"workflow:{slugify(step.id)}",
        )
    except Exception:
        pass


def _build_requirement_message(
    step: WorkflowStep,
    missing_env: List[str],
    missing_bin: List[str],
) -> str:
    lines = ["Workflow needs setup before continuing."]
    if missing_env:
        lines.append(f"Missing credentials: {', '.join(missing_env)}.")
        lines.append("Add them in the prompt and then resume the workflow.")
    if missing_bin:
        lines.append(f"Missing tools: {', '.join(missing_bin)}.")
        lines.append("Install the tool(s) and ensure they are on PATH, then resume.")
    if step.setup:
        lines.append(step.setup)
    return "\n".join(lines)


def _is_approval_step(approval: Any) -> bool:
    if approval is True:
        return True
    if isinstance(approval, str) and approval.lower() == "required":
        return True
    if isinstance(approval, str) and approval.strip():
        return True
    return False


def _build_approval_request(step: WorkflowStep, stdout: Optional[str]) -> WorkflowApprovalRequest:
    if isinstance(step.approval, str) and step.approval.strip():
        prompt = step.approval.strip()
    else:
        prompt = f"Approve {step.id}?"
    preview = stdout[:2000] if stdout else None
    return WorkflowApprovalRequest(prompt=prompt, items=[], preview=preview)


def _try_parse_json(text: Optional[str]) -> Optional[Any]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _to_output_items(result: Optional[WorkflowStepResult]) -> List[Any]:
    if not result:
        return []
    if result.json is not None:
        return result.json if isinstance(result.json, list) else [result.json]
    if result.stdout:
        return [result.stdout]
    return []


def _state_dir(config) -> Path:
    path = config.data_dir / "workflow_state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _signing_key_path(config) -> Path:
    return config.data_dir / "workflow_secret.key"


def _get_signing_key(config) -> bytes:
    path = _signing_key_path(config)
    if path.exists():
        return path.read_bytes()
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    return key


def _encode_token(payload: Dict[str, Any], config) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=")
    sig = hmac.new(_get_signing_key(config), payload_b64, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=")
    return payload_b64.decode("utf-8") + "." + sig_b64.decode("utf-8")


def _decode_token(token: str, config) -> Dict[str, Any]:
    if not token or "." not in token:
        raise ValueError("Invalid resume token")
    payload_b64, sig_b64 = token.split(".", 1)
    payload_bytes = _b64_decode(payload_b64)
    expected_sig = hmac.new(_get_signing_key(config), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected_sig, _b64_decode(sig_b64)):
        raise ValueError("Invalid resume token signature")
    data = json.loads(payload_bytes.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid resume token")
    if data.get("v") != 1:
        raise ValueError("Unsupported resume token version")
    return data


def _b64_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _save_resume_state(
    config,
    file_path: str,
    resume_at: int,
    steps: Dict[str, WorkflowStepResult],
    args: Dict[str, Any],
    approval_step_id: Optional[str] = None,
) -> str:
    state_key = secrets.token_urlsafe(16)
    payload = {
        "file_path": str(file_path),
        "resume_at": int(resume_at),
        "steps": {k: v.__dict__ for k, v in steps.items()},
        "args": args,
        "approval_step_id": approval_step_id,
    }
    path = _state_dir(config) / f"{state_key}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    token = _encode_token({"v": 1, "state_key": state_key}, config)
    return token


def _load_resume_state(config, token: str) -> Dict[str, Any]:
    payload = _decode_token(token, config)
    state_key = payload.get("state_key")
    if not state_key:
        raise ValueError("Invalid resume token payload")
    path = _state_dir(config) / f"{state_key}.json"
    if not path.exists():
        raise FileNotFoundError("Workflow resume state not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid resume state")
    steps_raw = data.get("steps", {})
    steps: Dict[str, WorkflowStepResult] = {}
    if isinstance(steps_raw, dict):
        for key, value in steps_raw.items():
            if isinstance(value, dict):
                steps[key] = WorkflowStepResult(**value)
    data["steps"] = steps
    return data


def get_workflow_runner() -> WorkflowRunner:
    return WorkflowRunner()


def resume_requires_approval(token: str) -> bool:
    config = get_config()
    state = _load_resume_state(config, token)
    return bool(state.get("approval_step_id"))
