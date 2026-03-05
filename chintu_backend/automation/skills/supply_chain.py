"""Skill/plugin trust and supply-chain safety checks (Phase 25)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_SECRET_PATTERNS: Sequence[tuple[str, str]] = (
    ("openai_api_key", r"sk-[a-zA-Z0-9]{20,}"),
    ("anthropic_api_key", r"sk-ant-[a-zA-Z0-9\-_]{20,}"),
    ("google_api_key", r"AIza[0-9A-Za-z\-_]{20,}"),
    ("aws_access_key", r"AKIA[0-9A-Z]{16}"),
    ("generic_secret_assignment", r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
)

_EXFIL_PATTERNS: Sequence[tuple[str, str]] = (
    ("curl_post", r"(?i)\bcurl\b[^\n]*\b(-d|--data|--data-binary)\b[^\n]*https?://"),
    ("wget_post", r"(?i)\bwget\b[^\n]*\b(--post-data|--method=post)\b"),
    ("powershell_webrequest", r"(?i)\binvoke-webrequest\b[^\n]*https?://"),
    ("python_requests_post", r"(?i)\brequests\.(post|put|patch)\s*\(\s*['\"]https?://"),
    ("socket_connect", r"(?i)\bsocket\.connect\s*\("),
)

_POSTINSTALL_SCRIPT_KEYS = {"preinstall", "install", "postinstall", "prepare"}


@dataclass
class SkillSupplyChainDecision:
    allowed: bool
    trust_level: str
    reason: str
    requires_explicit_approval: bool
    force_sandbox: bool
    blocked: bool
    provenance: Dict[str, Any] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    receipt_path: str = ""
    scanned_files: List[str] = field(default_factory=list)
    source_label: str = ""
    source_path: str = ""

    def to_metadata(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["checked_at_utc"] = _utc_now_iso()
        return payload


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    return []


def _normalize_repo(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("https://github.com/", "")
    text = text.replace("http://github.com/", "")
    text = text.strip("/")
    return text


def _parse_provenance(metadata: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    for key in ("supply_chain", "provenance", "source"):
        node = metadata.get(key)
        if isinstance(node, dict):
            result = dict(node)
            if "repo" in result:
                result["repo"] = _normalize_repo(str(result.get("repo") or ""))
            if "pinned_ref" not in result:
                result["pinned_ref"] = str(result.get("commit") or result.get("ref") or result.get("tag") or "").strip()
            return result
    repo = _normalize_repo(str(metadata.get("repo") or metadata.get("source_repo") or ""))
    owner = str(metadata.get("owner") or metadata.get("source_owner") or "").strip()
    pinned_ref = str(metadata.get("pinned_ref") or metadata.get("commit") or metadata.get("ref") or "").strip()
    if repo or owner or pinned_ref:
        return {"repo": repo, "owner": owner, "pinned_ref": pinned_ref}
    return {}


def _scan_text_for_issues(text: str) -> Dict[str, List[str]]:
    issues: List[str] = []
    warnings: List[str] = []
    for label, pattern in _SECRET_PATTERNS:
        if re.search(pattern, text):
            issues.append(f"secret pattern detected: {label}")
    for label, pattern in _EXFIL_PATTERNS:
        if re.search(pattern, text):
            issues.append(f"suspicious exfil/network pattern detected: {label}")
    if re.search(r"(?i)\bnpm\s+install\b(?![^\n]*--ignore-scripts)", text):
        warnings.append("npm install without --ignore-scripts detected")
    return {"issues": issues, "warnings": warnings}


def _scan_package_json(path: Path) -> Dict[str, List[str]]:
    issues: List[str] = []
    warnings: List[str] = []
    if not path.exists():
        return {"issues": issues, "warnings": warnings}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"failed to parse package.json: {exc}")
        return {"issues": issues, "warnings": warnings}
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return {"issues": issues, "warnings": warnings}
    for key in _POSTINSTALL_SCRIPT_KEYS:
        script = str(scripts.get(key) or "").strip()
        if script:
            issues.append(f"package.json includes {key} script")
    return {"issues": issues, "warnings": warnings}


def _scan_requirements(path: Path) -> Dict[str, List[str]]:
    issues: List[str] = []
    warnings: List[str] = []
    if not path.exists():
        return {"issues": issues, "warnings": warnings}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        warnings.append(f"failed to read requirements: {exc}")
        return {"issues": issues, "warnings": warnings}
    for line in lines:
        raw = str(line or "").strip()
        if not raw or raw.startswith("#"):
            continue
        low = raw.lower()
        if "git+" in low or "http://" in low or "https://" in low:
            warnings.append(f"unpinned remote dependency in requirements: {raw}")
    return {"issues": issues, "warnings": warnings}


def _collect_scan_targets(skill_path: Path) -> List[Path]:
    targets: List[Path] = [skill_path]
    parent = skill_path.parent
    for ext in ("*.py", "*.sh", "*.ps1", "*.bat", "package.json", "requirements*.txt", "pyproject.toml"):
        for item in parent.glob(ext):
            if item.is_file():
                targets.append(item)
    # Keep scan bounded.
    deduped = []
    seen = set()
    for row in targets:
        key = str(row.resolve()) if row.exists() else str(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= 20:
            break
    return deduped


def _path_sha256(path: Path) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    return hashlib.sha256(data).hexdigest()


def evaluate_skill_supply_chain(
    *,
    spec: Any,
    skill_path: Path,
    source_label: str,
    config=None,
) -> SkillSupplyChainDecision:
    cfg = config or get_config()
    metadata = getattr(spec, "metadata", {}) if spec is not None else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    provenance = _parse_provenance(metadata)

    trusted_labels = {x.lower() for x in _string_list(getattr(cfg, "skills_trusted_source_labels", []))}
    if not trusted_labels:
        trusted_labels = {"bundled", "learned", "workspace"}
    allowlist = {_normalize_repo(x) for x in _string_list(getattr(cfg, "skills_third_party_allowlist", []))}
    enforced = bool(getattr(cfg, "skills_supply_chain_enforced", True))
    require_provenance = bool(getattr(cfg, "skills_third_party_require_provenance", True))
    require_approval = bool(getattr(cfg, "skills_third_party_require_approval", True))
    force_sandbox_untrusted = bool(getattr(cfg, "skills_untrusted_force_sandbox", True))
    block_postinstall = bool(getattr(cfg, "skills_block_postinstall_scripts", True))

    source_norm = str(source_label or "").strip().lower()
    trust_level = "trusted_internal" if source_norm in trusted_labels else "untrusted_external"
    requires_explicit_approval = False
    blocked = False
    reason = "trusted internal source"
    issues: List[str] = []
    warnings: List[str] = []

    repo = _normalize_repo(str(provenance.get("repo") or ""))
    pinned_ref = str(provenance.get("pinned_ref") or "").strip()
    approved = bool(provenance.get("approved") or provenance.get("approval"))

    if trust_level != "trusted_internal":
        reason = "third-party source"
        if require_provenance and (not repo or not pinned_ref):
            issues.append("third-party skill missing provenance (repo + pinned_ref)")
        if repo and allowlist and repo not in allowlist:
            issues.append(f"repo not in allowlist: {repo}")
        if require_approval and not approved:
            requires_explicit_approval = True
            issues.append("third-party skill requires explicit approval before enable")

    scanned_files: List[str] = []
    for target in _collect_scan_targets(skill_path):
        scanned_files.append(str(target))
        if target.name.lower() == "package.json":
            result = _scan_package_json(target)
            if block_postinstall:
                issues.extend(result["issues"])
            else:
                warnings.extend(result["issues"])
            warnings.extend(result["warnings"])
            continue
        if target.name.lower().startswith("requirements"):
            result = _scan_requirements(target)
            issues.extend(result["issues"])
            warnings.extend(result["warnings"])
            continue
        try:
            text = target.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        result = _scan_text_for_issues(text)
        issues.extend(result["issues"])
        warnings.extend(result["warnings"])

    if issues:
        blocked = True
        reason = "blocked by supply-chain policy"
    elif requires_explicit_approval:
        blocked = True
        reason = "waiting for explicit approval"

    if not enforced:
        blocked = False
        reason = "supply-chain enforcement disabled"

    trust_level = "trusted_internal" if source_norm in trusted_labels else ("trusted_external" if repo and repo in allowlist else "untrusted_external")
    force_sandbox = bool(force_sandbox_untrusted and trust_level != "trusted_internal")

    decision = SkillSupplyChainDecision(
        allowed=not blocked,
        trust_level=trust_level,
        reason=reason,
        requires_explicit_approval=requires_explicit_approval,
        force_sandbox=force_sandbox,
        blocked=blocked,
        provenance={
            "repo": repo,
            "pinned_ref": pinned_ref,
            "approved": approved,
            "source_hash": _path_sha256(skill_path),
        },
        issues=sorted(set(issues)),
        warnings=sorted(set(warnings)),
        scanned_files=scanned_files,
        source_label=source_norm,
        source_path=str(skill_path),
    )
    decision.receipt_path = write_supply_chain_receipt(skill_path=skill_path, decision=decision, config=cfg)
    return decision


def write_supply_chain_receipt(*, skill_path: Path, decision: SkillSupplyChainDecision, config=None) -> str:
    cfg = config or get_config()
    receipts_dir = getattr(cfg, "skills_supply_chain_receipts_dir", None)
    if receipts_dir is None:
        receipts_dir = Path(getattr(cfg, "data_dir", Path.cwd())) / "skill_supply_chain" / "receipts"
    receipts_dir = Path(receipts_dir)
    try:
        receipts_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return ""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = re.sub(r"[^a-z0-9_-]+", "-", skill_path.stem.lower()).strip("-") or "skill"
    out_path = receipts_dir / f"{stamp}_{name}.json"
    payload = decision.to_metadata()
    payload["skill_path"] = str(skill_path)
    payload["recorded_at_utc"] = _utc_now_iso()
    try:
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return str(out_path)
    except Exception:
        return ""


def write_skill_execution_receipt(
    *,
    skill_name: str,
    command: str,
    mode: str,
    source_label: str,
    trust_level: str,
    success: bool,
    message: str,
    config=None,
) -> str:
    cfg = config or get_config()
    receipts_dir = getattr(cfg, "skills_supply_chain_receipts_dir", None)
    if receipts_dir is None:
        receipts_dir = Path(getattr(cfg, "data_dir", Path.cwd())) / "skill_supply_chain" / "receipts"
    receipts_dir = Path(receipts_dir)
    try:
        receipts_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return ""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = re.sub(r"[^a-z0-9_-]+", "-", str(skill_name or "skill").lower()).strip("-") or "skill"
    out_path = receipts_dir / f"{stamp}_{name}_execution.json"
    payload = {
        "recorded_at_utc": _utc_now_iso(),
        "skill_name": str(skill_name or ""),
        "mode": str(mode or "local"),
        "source_label": str(source_label or ""),
        "trust_level": str(trust_level or ""),
        "success": bool(success),
        "message": str(message or ""),
        "command": str(command or ""),
    }
    try:
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return str(out_path)
    except Exception:
        return ""

