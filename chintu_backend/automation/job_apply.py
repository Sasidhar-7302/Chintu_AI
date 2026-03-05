"""
Job application automation for Chintu AI.
Uses browser automation to search, evaluate, and apply to jobs with confirmation gates.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from chintu_backend.core.config import get_config
from chintu_backend.automation.browser.browser_controller import get_browser_controller

logger = logging.getLogger(__name__)


@dataclass
class JobMatch:
    title: str
    company: str
    url: str
    location: str
    decision: str
    reason: str
    salary: Optional[str] = None
    keywords: List[str] = None


class JobApplicationStore:
    def __init__(self):
        config = get_config()
        self.base_dir = config.data_dir / "jobs"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.applied_path = self.base_dir / "applied.jsonl"

    def log_application(self, record: Dict[str, Any]) -> None:
        record = dict(record)
        record.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
        with self.applied_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    def list_applications(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.applied_path.exists():
            return []
        lines = self.applied_path.read_text(encoding="utf-8").splitlines()
        lines = lines[-limit:] if limit else lines
        out = []
        for line in lines:
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out


class ResumeManager:
    def __init__(self):
        config = get_config()
        self.base_path = Path(getattr(config, "resume_tex_path", "")) if getattr(config, "resume_tex_path", "") else None
        self.output_dir = config.data_dir / "resume_versions"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def prepare_version(self, notes: Optional[str] = None) -> Optional[Path]:
        if not self.base_path or not self.base_path.exists():
            try:
                from chintu_backend.brain.learning import get_learning_engine
                get_learning_engine().record_gap("Resume LaTeX path missing for job apply.", {})
            except Exception:
                pass
            return None
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = self.output_dir / f"resume_{stamp}.tex"
        content = self.base_path.read_text(encoding="utf-8", errors="ignore")
        if notes:
            content = f"% Notes:\n% {notes}\n\n" + content
        out_path.write_text(content, encoding="utf-8")
        return out_path

    def apply_tailor_notes(self, resume_path: Path, jd_summary: str, keywords: List[str]) -> Path:
        content = resume_path.read_text(encoding="utf-8", errors="ignore")
        marker_start = "% AUTO_TAILOR_START"
        marker_end = "% AUTO_TAILOR_END"
        block = [
            marker_start,
            "% Job-tailored summary",
            f"% JD_SUMMARY: {jd_summary[:400]}",
            f"% KEYWORDS: {', '.join(keywords[:20])}",
            marker_end,
            "",
        ]
        block_text = "\n".join(block)
        if marker_start in content and marker_end in content:
            before = content.split(marker_start)[0]
            after = content.split(marker_end)[-1]
            content = before + block_text + after
        else:
            content = block_text + content
        resume_path.write_text(content, encoding="utf-8")
        return resume_path

    def compile_pdf(self, resume_path: Path) -> Optional[Path]:
        config = get_config()
        if not getattr(config, "resume_compile_enabled", False):
            return None
        compiler = getattr(config, "resume_compile_command", "pdflatex")
        try:
            import subprocess
            subprocess.run(
                [compiler, "-interaction=nonstopmode", str(resume_path)],
                cwd=str(resume_path.parent),
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            pdf_path = resume_path.with_suffix(".pdf")
            if pdf_path.exists():
                return pdf_path
        except Exception:
            return None
        return None


class JobApplyManager:
    def __init__(self):
        self.config = get_config()
        self.browser = get_browser_controller(headless=False, profile_name="job_apply")
        self.store = JobApplicationStore()
        self.resume = ResumeManager()

    def _extract_years_required(self, text: str) -> Optional[int]:
        matches = re.findall(r"(\\d+)\\s*\\+?\\s*years", text.lower())
        if not matches:
            return None
        try:
            return max(int(m) for m in matches)
        except Exception:
            return None

    def _requires_citizenship(self, text: str) -> bool:
        lower = text.lower()
        return any(term in lower for term in ["citizenship", "clearance", "security clearance", "us citizen", "gc required"])

    def _extract_salary(self, text: str) -> Optional[str]:
        match = re.search(r"\\$\\s*([0-9]{2,3}(?:,\\d{3})?)(?:\\s*-\\s*\\$?\\s*([0-9]{2,3}(?:,\\d{3})?))?", text)
        if not match:
            return None
        return match.group(0)

    def _extract_keywords(self, text: str) -> List[str]:
        base = [
            "python", "java", "golang", "node", "react", "aws", "gcp", "azure",
            "docker", "kubernetes", "sql", "postgres", "mongodb", "terraform",
            "ml", "ai", "llm", "typescript"
        ]
        hits = []
        lower = text.lower()
        for kw in base:
            if kw in lower:
                hits.append(kw)
        return hits

    def _basic_filter(self, jd_text: str, max_years: int = 3) -> Tuple[bool, str]:
        if getattr(self.config, "job_apply_require_no_citizenship", True) and self._requires_citizenship(jd_text):
            return False, "Citizenship/clearance required"
        years = self._extract_years_required(jd_text)
        if years is not None and years > max_years:
            return False, f"Requires {years}+ years"
        if getattr(self.config, "job_apply_min_salary", None):
            salary = self._extract_salary(jd_text) or ""
            if not salary:
                return False, "Salary not listed"
        if getattr(self.config, "job_apply_require_remote", False) and "remote" not in jd_text.lower():
            return False, "Remote required"
        if getattr(self.config, "job_apply_require_hybrid", False) and "hybrid" not in jd_text.lower():
            return False, "Hybrid required"
        block = [b.lower() for b in getattr(self.config, "job_apply_block_keywords", [])]
        for kw in block:
            if kw and kw in jd_text.lower():
                return False, f"Blocked keyword: {kw}"
        return True, "Meets base filters"

    def search_jobs(self, query: str, location: str, site: str = "linkedin.com/jobs") -> List[str]:
        if not query:
            return []
        q = f"site:{site} {query} {location}".strip()
        info = self.browser.search_google(q)
        # naive extraction of links from the page
        links = []
        try:
            page = self.browser._page
            for a in page.query_selector_all("a"):
                href = a.get_attribute("href") or ""
                if "http" in href and "linkedin.com/jobs" in href:
                    links.append(href.split("?")[0])
        except Exception:
            pass
        # de-dupe
        out = []
        for link in links:
            if link not in out:
                out.append(link)
        return out[:10]

    def evaluate_job(self, url: str, max_years: int = 3) -> JobMatch:
        info = self.browser.open_url(url, wait_for="domcontentloaded")
        jd_text = self.browser.get_page_content(max_length=4000)
        ok, reason = self._basic_filter(jd_text, max_years=max_years)
        keywords = self._extract_keywords(jd_text)
        salary = self._extract_salary(jd_text)
        title = info.title or "Job"
        return JobMatch(
            title=title,
            company="",
            url=url,
            location="",
            decision="apply" if ok else "skip",
            reason=reason,
            salary=salary,
            keywords=keywords,
        )

    def open_apply_flow(self, url: str) -> bool:
        self.browser.open_url(url, wait_for="domcontentloaded")
        # Try to click common apply buttons
        for label in ("Easy Apply", "Apply", "Apply Now", "Quick Apply"):
            try:
                if self.browser.click_link(label):
                    return True
            except Exception:
                continue
        return False

    def try_submit(self) -> bool:
        """Attempt to click a submit button on the current page."""
        for label in ("Submit application", "Submit", "Send application", "Apply"):
            try:
                if self.browser.click_link(label):
                    return True
            except Exception:
                continue
        return False

    def record_application(self, job: JobMatch, resume_path: Optional[Path], status: str = "applied"):
        self.store.log_application({
            "title": job.title,
            "company": job.company,
            "url": job.url,
            "location": job.location,
            "decision": job.decision,
            "reason": job.reason,
            "salary": job.salary,
            "keywords": job.keywords or [],
            "resume_path": str(resume_path) if resume_path else None,
            "status": status,
        })
