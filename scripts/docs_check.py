"""Docs integrity checks for Chintu.

Checks:
- Every non-template Markdown doc under docs/ is referenced from docs/INDEX.md.
- Markdown links to local files resolve (best-effort).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
INDEX_PATH = DOCS_DIR / "INDEX.md"


def _posix(path: Path) -> str:
    return str(path.as_posix())


def _iter_markdown_files() -> Iterable[Path]:
    for path in DOCS_DIR.rglob("*.md"):
        rel = path.relative_to(DOCS_DIR)
        # templates are internal scaffolds, not required to be indexed.
        if rel.parts and rel.parts[0].lower() == "templates":
            continue
        yield path


def _extract_index_text() -> str:
    try:
        return INDEX_PATH.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        raise RuntimeError(f"Failed to read {INDEX_PATH}: {exc}") from exc


def _check_all_docs_indexed(index_text: str, docs: List[Path]) -> List[str]:
    missing: List[str] = []
    hay = index_text.replace("\\", "/")
    for path in docs:
        rel = path.relative_to(REPO_ROOT)
        rel_str = _posix(rel)
        if rel_str not in hay:
            missing.append(rel_str)
    return missing


_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _check_local_links(docs: List[Path]) -> List[str]:
    broken: List[str] = []
    for doc in docs:
        text = doc.read_text(encoding="utf-8", errors="ignore")
        for raw_target in _MD_LINK_RE.findall(text):
            target = (raw_target or "").strip()
            if not target:
                continue
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            # Strip anchors and query strings.
            target = target.split("#", 1)[0].split("?", 1)[0].strip()
            if not target:
                continue
            # Resolve relative to doc location first, then repo root.
            cand = (doc.parent / target).resolve()
            if cand.exists():
                continue
            cand2 = (REPO_ROOT / target).resolve()
            if cand2.exists():
                continue
            broken.append(f"{doc.relative_to(REPO_ROOT).as_posix()}: {raw_target}")
    return broken


def _check_titles(docs: List[Path]) -> List[str]:
    bad: List[str] = []
    for doc in docs:
        lines = doc.read_text(encoding="utf-8", errors="ignore").splitlines()
        first = ""
        for ln in lines:
            line = ln.lstrip("\ufeff").strip()
            if line:
                first = line
                break
        if not first.startswith("# "):
            bad.append(str(doc.relative_to(REPO_ROOT).as_posix()))
    return bad


def main() -> int:
    if not DOCS_DIR.exists():
        print(f"[FAIL] docs directory missing: {DOCS_DIR}")
        return 2
    if not INDEX_PATH.exists():
        print(f"[FAIL] missing docs index: {INDEX_PATH}")
        return 2

    docs = sorted(list(_iter_markdown_files()))
    index_text = _extract_index_text()

    missing = _check_all_docs_indexed(index_text, [d for d in docs if d != INDEX_PATH])
    broken = _check_local_links(docs)
    bad_titles = _check_titles(docs)

    ok = True
    if missing:
        ok = False
        print("[FAIL] docs/INDEX.md is missing references to:")
        for item in missing:
            print(f"  - {item}")
    if broken:
        ok = False
        print("[FAIL] broken local links:")
        for item in broken[:80]:
            print(f"  - {item}")
        if len(broken) > 80:
            print(f"  - ... and {len(broken) - 80} more")
    if bad_titles:
        ok = False
        print("[FAIL] docs missing a top-level '# Title' heading:")
        for item in bad_titles:
            print(f"  - {item}")

    if ok:
        print(f"[OK] docs_check passed ({len(docs)} markdown files).")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
