"""Incremental repository indexer backed by ChromaDB."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class HashEmbeddingFunction:
    """Lightweight deterministic embedding function (no model downloads)."""

    def __init__(self, dimensions: int = 256):
        self.dimensions = max(32, int(dimensions))

    def __call__(self, input: Iterable[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for item in input:
            text = str(item or "")
            tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
            vec = [0.0] * self.dimensions
            if not tokens:
                vectors.append(vec)
                continue
            for token in tokens:
                digest = hashlib.sha1(token.encode("utf-8", errors="ignore")).digest()
                idx = int.from_bytes(digest[:4], "big", signed=False) % self.dimensions
                vec[idx] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            vectors.append([v / norm for v in vec])
        return vectors

    # Chroma compatibility helpers for versions that call embed_documents/embed_query.
    def embed_documents(self, texts: Iterable[str]) -> List[List[float]]:
        return self.__call__(texts)

    def embed_query(self, text: str) -> List[float]:
        return self.__call__([text])[0]


class RepoIndexer:
    """Build and query an incremental index of a local repository."""

    FALLBACK_EXCLUDE_DIRS = {
        ".git",
        "venv",
        "node_modules",
        ".tmp",
        "logs",
        "generated_reports",
        "data",
        "__pycache__",
        ".pytest_cache",
    }

    FALLBACK_NAME_ALLOWLIST = {
        "dockerfile",
        "makefile",
        "readme",
        "license",
        "pyproject.toml",
        "requirements.txt",
    }

    def __init__(
        self,
        *,
        root_path: Optional[Path] = None,
        collection_name: Optional[str] = None,
        include_untracked: Optional[bool] = None,
        embedding_function: Optional[Any] = None,
    ) -> None:
        config = get_config()
        self.config = config
        self.root_path = Path(root_path or Path.cwd()).expanduser().resolve()
        self.index_dir = Path(
            getattr(config, "repo_index_dir", None) or (config.data_dir / "repo_index")
        ).expanduser().resolve()
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.index_dir / ".state.json"
        self.collection_name = (
            str(collection_name or getattr(config, "repo_index_collection_name", "repo_index_v1")).strip()
            or "repo_index_v1"
        )
        self.include_untracked = bool(
            getattr(config, "repo_index_include_untracked", True)
            if include_untracked is None
            else include_untracked
        )
        self.max_file_bytes = int(getattr(config, "repo_index_max_file_bytes", 2 * 1024 * 1024) or (2 * 1024 * 1024))
        self.chunk_chars = int(getattr(config, "repo_index_chunk_chars", 2400) or 2400)
        self.chunk_overlap_chars = int(getattr(config, "repo_index_chunk_overlap_chars", 200) or 200)
        self.allowed_extensions = {
            str(ext or "").strip().lower()
            for ext in list(getattr(config, "repo_index_allowed_extensions", []) or [])
            if str(ext or "").strip()
        }
        if not self.allowed_extensions:
            self.allowed_extensions = {".py", ".md", ".txt", ".json", ".yaml", ".yml"}
        self.secret_patterns = [
            str(item or "").strip().lower()
            for item in list(getattr(config, "repo_index_secret_patterns", []) or [])
            if str(item or "").strip()
        ]
        if not self.secret_patterns:
            self.secret_patterns = [".env", ".pem", ".key", "token", "secret", "private"]
        self.embedding_function = embedding_function or HashEmbeddingFunction()
        self.collection = self._create_collection()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build(self, incremental: bool = True) -> Dict[str, Any]:
        started = time.perf_counter()
        previous_state = self._load_state()
        next_state: Dict[str, Dict[str, Any]] = {}
        discovered = self._discover_files()

        stats: Dict[str, Any] = {
            "root_path": str(self.root_path),
            "index_dir": str(self.index_dir),
            "collection": self.collection_name,
            "incremental": bool(incremental),
            "files_discovered": len(discovered),
            "files_indexed": 0,
            "files_updated": 0,
            "files_unchanged": 0,
            "files_removed": 0,
            "files_pruned_by_policy": 0,
            "files_skipped": 0,
            "chunks_added": 0,
            "errors": 0,
        }

        for rel_path in discovered:
            abs_path = (self.root_path / rel_path).resolve()
            if not abs_path.exists() or not abs_path.is_file():
                continue

            skip_reason = self._should_skip_file(abs_path, rel_path)
            if skip_reason:
                stats["files_skipped"] += 1
                if rel_path in previous_state:
                    self._delete_file_chunks(rel_path)
                    stats["files_pruned_by_policy"] += 1
                continue

            try:
                raw = abs_path.read_bytes()
            except Exception:
                stats["errors"] += 1
                continue

            content_hash = hashlib.sha256(raw).hexdigest()
            mtime = float(abs_path.stat().st_mtime)
            prev = previous_state.get(rel_path)
            unchanged = bool(
                incremental
                and prev
                and str(prev.get("content_hash", "")) == content_hash
                and float(prev.get("mtime", 0.0)) == mtime
            )
            if unchanged:
                stats["files_unchanged"] += 1
                next_state[rel_path] = {
                    "mtime": mtime,
                    "content_hash": content_hash,
                    "chunk_count": int(prev.get("chunk_count", 0)),
                }
                continue

            try:
                self._delete_file_chunks(rel_path)
                text = raw.decode("utf-8", errors="ignore")
                chunks = self._chunk_text(text)
                if chunks:
                    self._add_chunks(
                        abs_path=abs_path,
                        rel_path=rel_path,
                        chunks=chunks,
                        content_hash=content_hash,
                        mtime=mtime,
                    )
                next_state[rel_path] = {
                    "mtime": mtime,
                    "content_hash": content_hash,
                    "chunk_count": len(chunks),
                }
                stats["files_indexed"] += 1
                stats["files_updated"] += 1 if prev else 0
                stats["chunks_added"] += len(chunks)
            except Exception as exc:
                logger.debug("Repo index build failed for %s: %s", rel_path, exc)
                stats["errors"] += 1

        removed = set(previous_state.keys()) - set(next_state.keys())
        for rel_path in sorted(removed):
            try:
                self._delete_file_chunks(rel_path)
                stats["files_removed"] += 1
            except Exception:
                stats["errors"] += 1

        self._save_state(next_state)
        try:
            stats["total_chunks"] = int(self.collection.count())
        except Exception:
            stats["total_chunks"] = -1
        stats["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
        return stats

    def search(
        self,
        query: str,
        k: int = 8,
        path_prefix: Optional[str] = None,
        ext: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not str(query or "").strip():
            return []
        limit = max(1, int(k or 8))
        ext_filter = str(ext or "").strip().lower()
        if ext_filter and not ext_filter.startswith("."):
            ext_filter = "." + ext_filter
        prefix_filter = str(path_prefix or "").strip().replace("\\", "/").lower()
        query_tokens = self._query_tokens(query)

        query_count = max(limit * 6, 20)
        result = self.collection.query(
            query_texts=[str(query)],
            n_results=query_count,
            where={"source": "repo_index"},
        )

        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]

        rows: List[Dict[str, Any]] = []
        for idx in range(min(len(docs), len(metas))):
            meta = metas[idx] if isinstance(metas[idx], dict) else {}
            rel_path = str(meta.get("rel_path") or "")
            rel_norm = rel_path.replace("\\", "/").lower()
            row_ext = str(meta.get("ext") or "").lower()
            if prefix_filter and not rel_norm.startswith(prefix_filter):
                continue
            if ext_filter and row_ext != ext_filter:
                continue
            distance = distances[idx] if idx < len(distances) else None
            score = None
            if isinstance(distance, (int, float)):
                score = round(1.0 / (1.0 + float(distance)), 6)
            lexical = self._lexical_score(query_tokens, str(docs[idx] or ""), rel_path)
            rows.append(
                {
                    "id": str(ids[idx]) if idx < len(ids) else "",
                    "path": str(meta.get("path") or ""),
                    "rel_path": rel_path,
                    "ext": row_ext,
                    "chunk_index": int(meta.get("chunk_index", 0) or 0),
                    "mtime": float(meta.get("mtime", 0.0) or 0.0),
                    "score": score,
                    "distance": float(distance) if isinstance(distance, (int, float)) else None,
                    "lexical_score": int(lexical),
                    "content": str(docs[idx] or ""),
                }
            )
        rows.sort(
            key=lambda row: (
                int(row.get("lexical_score", 0) or 0),
                float(row.get("score") or 0.0),
            ),
            reverse=True,
        )
        rows = rows[:limit]

        best_lexical = int(rows[0].get("lexical_score", 0) or 0) if rows else 0
        if best_lexical <= 0 or len(rows) < limit:
            extra = self._lexical_file_search(
                query=query,
                tokens=query_tokens,
                k=limit,
                path_prefix=prefix_filter,
                ext=ext_filter,
            )
            seen = {str(row.get("id") or "") for row in rows}
            for row in extra:
                if len(rows) >= limit:
                    break
                row_id = str(row.get("id") or "")
                if row_id in seen:
                    continue
                seen.add(row_id)
                rows.append(row)
        return rows[:limit]

    def status(self) -> Dict[str, Any]:
        state = self._load_state()
        try:
            chunk_count = int(self.collection.count())
        except Exception:
            chunk_count = -1
        return {
            "root_path": str(self.root_path),
            "index_dir": str(self.index_dir),
            "collection": self.collection_name,
            "files_indexed": len(state),
            "chunks_indexed": chunk_count,
            "state_path": str(self.state_path),
        }

    # ------------------------------------------------------------------
    # Collection/state helpers
    # ------------------------------------------------------------------
    def _create_collection(self):
        try:
            import chromadb  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"chromadb is required for repo indexing: {exc}") from exc
        client = chromadb.PersistentClient(path=str(self.index_dir))
        return client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
            metadata={"source": "repo_index"},
        )

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        if not self.state_path.exists():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        state: Dict[str, Dict[str, Any]] = {}
        for rel_path, entry in payload.items():
            if not isinstance(entry, dict):
                continue
            state[str(rel_path)] = {
                "mtime": float(entry.get("mtime", 0.0) or 0.0),
                "content_hash": str(entry.get("content_hash", "") or ""),
                "chunk_count": int(entry.get("chunk_count", 0) or 0),
            }
        return state

    def _save_state(self, state: Dict[str, Dict[str, Any]]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, indent=2, ensure_ascii=True)
        self.state_path.write_text(payload, encoding="utf-8")

    # ------------------------------------------------------------------
    # Discovery/filtering
    # ------------------------------------------------------------------
    def _discover_files(self) -> List[str]:
        git_files = self._discover_files_git()
        if git_files is not None:
            return sorted(set(git_files))
        return sorted(set(self._discover_files_walk()))

    def _discover_files_git(self) -> Optional[List[str]]:
        if not (self.root_path / ".git").exists():
            return None
        if not shutil_which("git"):
            return None
        try:
            inside = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=str(self.root_path),
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if inside.returncode != 0:
                return None
        except Exception:
            return None

        rel_paths: List[str] = []
        rel_paths.extend(self._run_git_ls(["git", "ls-files", "-z"]))
        if self.include_untracked:
            rel_paths.extend(self._run_git_ls(["git", "ls-files", "--others", "--exclude-standard", "-z"]))
        return [p for p in rel_paths if p]

    def _run_git_ls(self, command: List[str]) -> List[str]:
        try:
            proc = subprocess.run(
                command,
                cwd=str(self.root_path),
                capture_output=True,
                timeout=15,
                check=False,
            )
            if proc.returncode != 0:
                return []
            output = proc.stdout.decode("utf-8", errors="ignore")
            items = [token for token in output.split("\x00") if token]
            return [str(Path(item)).replace("\\", "/") for item in items]
        except Exception:
            return []

    def _discover_files_walk(self) -> List[str]:
        rel_paths: List[str] = []
        for current_root, dir_names, file_names in os.walk(self.root_path):
            dir_names[:] = [d for d in dir_names if d not in self.FALLBACK_EXCLUDE_DIRS]
            base = Path(current_root)
            for file_name in file_names:
                path = base / file_name
                try:
                    rel = path.relative_to(self.root_path)
                except Exception:
                    continue
                rel_paths.append(str(rel).replace("\\", "/"))
        return rel_paths

    def _should_skip_file(self, abs_path: Path, rel_path: str) -> Optional[str]:
        rel_low = str(rel_path or "").replace("\\", "/").lower()
        name_low = abs_path.name.lower()
        if any(part in self.FALLBACK_EXCLUDE_DIRS for part in Path(rel_low).parts):
            return "excluded_dir"
        if any(pattern and pattern in rel_low for pattern in self.secret_patterns):
            return "secret_pattern"
        try:
            size = abs_path.stat().st_size
        except Exception:
            return "stat_error"
        if size > self.max_file_bytes:
            return "too_large"

        ext = abs_path.suffix.lower()
        allow_name = name_low in self.FALLBACK_NAME_ALLOWLIST
        if not allow_name and ext not in self.allowed_extensions:
            return "ext_not_allowed"

        try:
            head = abs_path.read_bytes()[:4096]
        except Exception:
            return "read_error"
        if b"\x00" in head:
            return "binary"
        return None

    # ------------------------------------------------------------------
    # Chunking and writes
    # ------------------------------------------------------------------
    def _chunk_text(self, text: str) -> List[str]:
        content = str(text or "").strip()
        if not content:
            return []
        lines = content.splitlines()
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0

        def flush() -> None:
            nonlocal current, current_len
            if not current:
                return
            chunk = "\n".join(current).strip()
            if chunk:
                chunks.append(chunk)
            if self.chunk_overlap_chars > 0 and chunk:
                overlap = chunk[-self.chunk_overlap_chars :]
                current = [overlap]
                current_len = len(overlap)
            else:
                current = []
                current_len = 0

        for line in lines:
            line = str(line)
            line_len = len(line) + 1
            if current and (current_len + line_len) > self.chunk_chars:
                flush()
            current.append(line)
            current_len += line_len
        flush()
        return chunks

    def _add_chunks(
        self,
        *,
        abs_path: Path,
        rel_path: str,
        chunks: List[str],
        content_hash: str,
        mtime: float,
    ) -> None:
        if not chunks:
            return
        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []
        ext = abs_path.suffix.lower()
        for idx, chunk in enumerate(chunks):
            key = f"{rel_path}:{idx}:{content_hash[:16]}"
            uid = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()
            ids.append(f"repoidx:{uid}")
            docs.append(chunk)
            metas.append(
                {
                    "path": str(abs_path),
                    "rel_path": str(rel_path),
                    "ext": ext,
                    "chunk_index": int(idx),
                    "content_hash": str(content_hash),
                    "mtime": float(mtime),
                    "source": "repo_index",
                }
            )
        self.collection.add(ids=ids, documents=docs, metadatas=metas)

    def _delete_file_chunks(self, rel_path: str) -> None:
        try:
            self.collection.delete(where={"source": "repo_index", "rel_path": str(rel_path)})
        except Exception:
            return

    # ------------------------------------------------------------------
    # Lexical fallback search
    # ------------------------------------------------------------------
    @staticmethod
    def _query_tokens(query: str) -> List[str]:
        raw_tokens = [token for token in re.findall(r"[A-Za-z0-9_]+", str(query or "")) if token]
        tokens: List[str] = []
        for raw in raw_tokens:
            low = raw.lower()
            if low and low not in tokens:
                tokens.append(low)
            if "_" in low:
                for part in [p for p in low.split("_") if p]:
                    if part not in tokens:
                        tokens.append(part)
            camel_parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw).split()
            if len(camel_parts) > 1:
                for part in camel_parts:
                    piece = part.lower().strip()
                    if piece and piece not in tokens:
                        tokens.append(piece)
        return tokens[:24]

    @staticmethod
    def _lexical_score(tokens: List[str], text: str, rel_path: str) -> int:
        if not tokens:
            return 0
        hay = f"{str(rel_path or '').lower()} {str(text or '').lower()}"
        score = 0
        for token in tokens:
            if token in hay:
                score += 1
        return score

    @staticmethod
    def _snippet_for_tokens(text: str, tokens: List[str], max_chars: int = 260) -> str:
        body = str(text or "")
        if not body:
            return ""
        low = body.lower()
        hit = -1
        for token in tokens:
            hit = low.find(token)
            if hit >= 0:
                break
        if hit < 0:
            return body[:max_chars].strip()
        start = max(0, hit - 60)
        end = min(len(body), hit + max_chars)
        return body[start:end].strip()

    def _lexical_file_search(
        self,
        *,
        query: str,
        tokens: List[str],
        k: int,
        path_prefix: str,
        ext: str,
    ) -> List[Dict[str, Any]]:
        state = self._load_state()
        rows: List[Dict[str, Any]] = []
        scanned = 0
        max_files = 320
        for rel_path in state.keys():
            rel_norm = str(rel_path).replace("\\", "/").lower()
            if path_prefix and not rel_norm.startswith(path_prefix):
                continue
            if ext:
                suffix = Path(rel_path).suffix.lower()
                if suffix != ext:
                    continue
            abs_path = (self.root_path / rel_path).resolve()
            if not abs_path.exists() or not abs_path.is_file():
                continue
            scanned += 1
            if scanned > max_files:
                break
            try:
                text = abs_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            lexical = self._lexical_score(tokens, text, rel_path)
            if lexical <= 0:
                continue
            snippet = self._snippet_for_tokens(text, tokens)
            item_key = f"lexical:{rel_path}:{query}"
            uid = hashlib.sha1(item_key.encode("utf-8", errors="ignore")).hexdigest()
            rows.append(
                {
                    "id": f"repoidx:{uid}",
                    "path": str(abs_path),
                    "rel_path": str(rel_path),
                    "ext": str(abs_path.suffix.lower()),
                    "chunk_index": 0,
                    "mtime": float(abs_path.stat().st_mtime),
                    "score": round(min(0.999, float(lexical) / max(1.0, len(tokens))), 6),
                    "distance": None,
                    "lexical_score": int(lexical),
                    "content": snippet,
                }
            )
        rows.sort(
            key=lambda row: (
                int(row.get("lexical_score", 0) or 0),
                float(row.get("mtime", 0.0) or 0.0),
            ),
            reverse=True,
        )
        return rows[: max(1, int(k))]


def shutil_which(binary: str) -> Optional[str]:
    """Small local helper to avoid importing shutil in hot paths."""
    path = os.environ.get("PATH", "")
    exts = [""]
    if os.name == "nt":
        pathext = os.environ.get("PATHEXT", ".EXE;.BAT;.CMD;.COM")
        exts = [ext.lower() for ext in pathext.split(";") if ext]
    for entry in path.split(os.pathsep):
        if not entry:
            continue
        base = Path(entry)
        candidate = base / binary
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
        if os.name == "nt":
            for ext in exts:
                alt = base / f"{binary}{ext}"
                if alt.exists() and os.access(alt, os.X_OK):
                    return str(alt)
    return None
