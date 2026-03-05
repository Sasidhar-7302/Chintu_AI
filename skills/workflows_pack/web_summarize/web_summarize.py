from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from chintu_backend.core.config import get_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_url(request_text: str, explicit_url: str) -> Optional[str]:
    url = str(explicit_url or "").strip()
    if url:
        return url
    match = re.search(r"https?://[^\s]+", str(request_text or ""))
    if not match:
        return None
    return str(match.group(0)).rstrip(").,;\"'")


def _fetch_text(url: str) -> str:
    req = urlrequest.Request(
        url,
        headers={"User-Agent": "Chintu-WorkflowSummarizer/1.0"},
        method="GET",
    )
    with urlrequest.urlopen(req, timeout=20) as response:
        raw = response.read(2 * 1024 * 1024).decode("utf-8", errors="ignore")

    text = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _summarize_text(text: str, max_sentences: int = 6) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return "No readable content found."
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    selected = []
    char_budget = 1400
    used = 0
    for sentence in sentences:
        part = sentence.strip()
        if not part:
            continue
        if used + len(part) > char_budget:
            break
        selected.append(part)
        used += len(part)
        if len(selected) >= max_sentences:
            break
    if not selected:
        selected = [cleaned[: min(900, len(cleaned))]]
    return "\n".join(f"- {line}" for line in selected)


def _safe_slug(url: str) -> str:
    parsed = urlparse(url)
    base = f"{parsed.netloc}{parsed.path}"
    token = "".join(ch if ch.isalnum() else "_" for ch in base).strip("_")
    return token[:80] or "page"


def run(request_text: str, url: str = "") -> Dict[str, str]:
    resolved = _extract_url(request_text, url)
    if not resolved:
        raise ValueError("No URL found. Usage: /summarize https://example.com")

    text = _fetch_text(resolved)
    summary = _summarize_text(text)

    cfg = get_config()
    out_dir = Path(getattr(cfg, "workflows_dir", cfg.data_dir / "workflows")) / "web_summaries"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_slug(resolved)}.md"

    lines = [
        "# Web Summary",
        "",
        f"- URL: {resolved}",
        f"- Generated UTC: {_utc_now()}",
        "",
        "## Summary",
        summary,
        "",
        "## Source Excerpt",
        str(text[:1200]).strip(),
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "workflow": "web_summarize",
        "url": resolved,
        "summary_path": str(out_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a web page into Markdown.")
    parser.add_argument("--request", default="")
    parser.add_argument("--url", default="")
    args = parser.parse_args()
    try:
        payload = run(request_text=args.request, url=args.url)
        print(json.dumps(payload, ensure_ascii=True))
        return 0
    except (urlerror.URLError, TimeoutError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
