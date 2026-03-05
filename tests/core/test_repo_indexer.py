from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from chintu_backend.coding import repo_indexer as ri


class _FakeCollection:
    def __init__(self) -> None:
        self._rows: List[Dict[str, Any]] = []

    def add(self, *, ids: List[str], documents: List[str], metadatas: List[Dict[str, Any]]) -> None:
        for idx, doc in enumerate(documents):
            self._rows.append(
                {
                    "id": str(ids[idx]),
                    "document": str(doc),
                    "metadata": dict(metadatas[idx]),
                }
            )

    def delete(self, *, where: Dict[str, Any]) -> None:
        def _match(row: Dict[str, Any]) -> bool:
            meta = row.get("metadata", {})
            for key, value in (where or {}).items():
                if meta.get(key) != value:
                    return False
            return True

        self._rows = [row for row in self._rows if not _match(row)]

    def count(self) -> int:
        return len(self._rows)

    def query(self, *, query_texts: List[str], n_results: int, where: Dict[str, Any] | None = None) -> Dict[str, Any]:
        query = str((query_texts or [""])[0] or "").lower()
        tokens = {token for token in query.split() if token}

        def _where_ok(row: Dict[str, Any]) -> bool:
            if not where:
                return True
            meta = row.get("metadata", {})
            for key, value in where.items():
                if meta.get(key) != value:
                    return False
            return True

        scored: List[Dict[str, Any]] = []
        for row in self._rows:
            if not _where_ok(row):
                continue
            text_tokens = {token for token in str(row.get("document", "")).lower().split() if token}
            overlap = len(tokens.intersection(text_tokens))
            distance = 1.0 / float(overlap + 1)
            scored.append(
                {
                    "distance": distance,
                    "id": row["id"],
                    "document": row["document"],
                    "metadata": row["metadata"],
                }
            )

        scored.sort(key=lambda item: item["distance"])
        top = scored[: max(1, int(n_results or 1))]
        return {
            "documents": [[item["document"] for item in top]],
            "metadatas": [[item["metadata"] for item in top]],
            "distances": [[item["distance"] for item in top]],
            "ids": [[item["id"] for item in top]],
        }


@dataclass
class _StubConfig:
    data_dir: Path
    repo_index_collection_name: str = "repo_index_v1"
    repo_index_include_untracked: bool = True
    repo_index_max_file_bytes: int = 2 * 1024 * 1024
    repo_index_chunk_chars: int = 2400
    repo_index_chunk_overlap_chars: int = 200
    repo_index_allowed_extensions: List[str] = None
    repo_index_secret_patterns: List[str] = None
    repo_index_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.repo_index_allowed_extensions is None:
            self.repo_index_allowed_extensions = [".py", ".md", ".txt"]
        if self.repo_index_secret_patterns is None:
            self.repo_index_secret_patterns = [".env", "token", "secret", ".key", ".pem"]
        if self.repo_index_dir is None:
            self.repo_index_dir = self.data_dir / "repo_index"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_repo_indexer_build_search_and_incremental(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    cfg = _StubConfig(data_dir=data_dir)

    _write(repo / "src" / "model_router.py", "class ModelRouter:\n    pass\n")
    _write(repo / "src" / "handler.py", "def handle_payment():\n    return 'ok'\n")
    _write(
        repo / "chintu_backend" / "interfaces" / "mcp" / "server.py",
        "def call_tool(name, args):\n    return name\n",
    )
    _write(repo / ".env", "API_TOKEN=abc123\n")
    (repo / "big.txt").write_bytes(b"x" * (2 * 1024 * 1024 + 100))

    monkeypatch.setattr(ri, "get_config", lambda: cfg)
    monkeypatch.setattr(ri.RepoIndexer, "_create_collection", lambda self: _FakeCollection())

    indexer = ri.RepoIndexer(root_path=repo)
    first = indexer.build(incremental=True)

    assert first["files_indexed"] >= 3
    assert first["files_skipped"] >= 2
    assert first["chunks_added"] >= 3
    assert indexer.status()["files_indexed"] >= 3

    hits = indexer.search("where is class ModelRouter defined", k=5, ext=".py")
    assert hits
    assert any(str(row.get("rel_path", "")).endswith("src/model_router.py") for row in hits)

    mcp_hits = indexer.search(
        "find call_tool wiring",
        k=5,
        path_prefix="chintu_backend/interfaces/mcp",
        ext=".py",
    )
    assert mcp_hits
    assert any(
        str(row.get("rel_path", "")).endswith("chintu_backend/interfaces/mcp/server.py")
        for row in mcp_hits
    )

    second = indexer.build(incremental=True)
    assert second["files_unchanged"] >= 3
    assert second["files_indexed"] == 0

    _write(repo / "src" / "handler.py", "def handle_payment():\n    return 'updated'\n")
    third = indexer.build(incremental=True)
    assert third["files_updated"] >= 1
    assert third["files_indexed"] >= 1

    state_path = cfg.repo_index_dir / ".state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert "src/handler.py" in payload
    assert ".env" not in payload


def test_repo_indexer_prunes_deleted_files(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    cfg = _StubConfig(data_dir=data_dir)
    _write(repo / "src" / "gone.py", "class DeleteMe:\n    pass\n")

    monkeypatch.setattr(ri, "get_config", lambda: cfg)
    monkeypatch.setattr(ri.RepoIndexer, "_create_collection", lambda self: _FakeCollection())

    indexer = ri.RepoIndexer(root_path=repo)
    first = indexer.build(incremental=True)
    assert first["files_indexed"] == 1

    (repo / "src" / "gone.py").unlink()
    second = indexer.build(incremental=True)
    assert second["files_removed"] >= 1
    assert not any(
        str(row.get("rel_path", "")).endswith("src/gone.py")
        for row in indexer.search("DeleteMe", k=10, ext=".py")
    )
