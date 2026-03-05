"""
Memory Manager for Chintu Assistant.
Handles long-term memory using Vector Database (ChromaDB) and User Profile management.

Optimizations:
- LRU cache for frequently accessed queries (reduces 910ms -> ~1ms for cached)
- Background pre-warming of embedding model
"""

import os
import json
import logging
import uuid
import hashlib
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import OrderedDict

logger = logging.getLogger(__name__)
HAS_CHROMA = False
_CHROMA_IMPORT_ERROR: Optional[Exception] = None


def _import_chromadb() -> None:
    """Import ChromaDB with a NumPy 2.x compatibility shim fallback."""
    global HAS_CHROMA, _CHROMA_IMPORT_ERROR, chromadb, embedding_functions

    # Keep Chroma telemetry quiet and robust across posthog version differences.
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    try:
        import posthog  # type: ignore

        posthog.disabled = True
        if hasattr(posthog, "capture"):
            posthog.capture = lambda *args, **kwargs: None  # type: ignore[assignment]
    except Exception:
        pass

    try:
        import chromadb  # type: ignore
        from chromadb.utils import embedding_functions  # type: ignore

        HAS_CHROMA = True
        _CHROMA_IMPORT_ERROR = None
        return
    except Exception as exc:
        _CHROMA_IMPORT_ERROR = exc

    # Retry once with a compatibility alias for old Chroma releases on NumPy 2.x.
    try:
        import numpy as _np  # type: ignore

        if not hasattr(_np, "float_"):
            setattr(_np, "float_", _np.float64)

        import chromadb  # type: ignore
        from chromadb.utils import embedding_functions  # type: ignore

        HAS_CHROMA = True
        _CHROMA_IMPORT_ERROR = None
    except Exception as retry_exc:
        HAS_CHROMA = False
        _CHROMA_IMPORT_ERROR = retry_exc


_import_chromadb()


class LRUCache:
    """Simple LRU cache for memory queries."""

    def __init__(self, max_size: int = 100, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict = OrderedDict()
        self._timestamps: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _make_key(self, query: str, n_results: int) -> str:
        """Create cache key from query and params."""
        content = f"{query}:{n_results}"
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, query: str, n_results: int) -> Optional[str]:
        """Get cached result if valid."""
        key = self._make_key(query, n_results)
        with self._lock:
            if key not in self._cache:
                return None

            # Check TTL
            import time
            if time.time() - self._timestamps[key] > self.ttl_seconds:
                del self._cache[key]
                del self._timestamps[key]
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            return self._cache[key]

    def set(self, query: str, n_results: int, result: str):
        """Cache a result."""
        import time
        key = self._make_key(query, n_results)
        with self._lock:
            # Remove oldest if at capacity
            if len(self._cache) >= self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                del self._timestamps[oldest_key]

            self._cache[key] = result
            self._timestamps[key] = time.time()

    def invalidate(self):
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._timestamps.clear()


class MemoryManager:
    """Manages long-term memory and user context."""

    def __init__(self, persistence_path: Optional[str] = None):
        if not persistence_path:
            try:
                from .config import get_config
                config = get_config()
                persistence_path = str(config.memory_store_path or "memory_store")
            except Exception:
                persistence_path = "memory_store"
        redirected = self._read_redirect_path(persistence_path)
        self.persistence_path = redirected or persistence_path
        self.profile_path = os.path.join(self.persistence_path, "user_profile.json")
        self.client = None
        self.collection = None

        # Query cache for performance (reduces 910ms -> ~1ms for repeated queries)
        self._query_cache = LRUCache(max_size=100, ttl_seconds=300)
        self._embedding_warmed = False

        # Create directory if not exists
        if not os.path.exists(persistence_path):
            os.makedirs(persistence_path, exist_ok=True)

        self._init_db()
        self._init_profile()

    def _read_redirect_path(self, base_path: str) -> Optional[str]:
        """Resolve chained redirect paths from prior schema-reset migrations."""
        try:
            current = base_path
            visited = {str(base_path)}
            for _ in range(8):  # Prevent infinite loops on malformed redirects.
                redirect_file = f"{current}.redirect"
                if not os.path.exists(redirect_file):
                    break
                with open(redirect_file, "r", encoding="utf-8") as f:
                    target = f.read().strip()
                if not target:
                    break
                if target in visited:
                    break
                visited.add(target)
                current = target
            if current and current != base_path:
                return current
        except Exception:
            pass
        return None

    def _init_db(self):
        """Initialize ChromaDB client."""
        if not HAS_CHROMA:
            if _CHROMA_IMPORT_ERROR:
                logger.warning("ChromaDB unavailable (%s). Memory features disabled.", _CHROMA_IMPORT_ERROR)
            else:
                logger.warning("ChromaDB unavailable. Memory features disabled.")
            return

        try:
            # Persistent client
            self.client = chromadb.PersistentClient(path=self.persistence_path)
            
            # Use default embeddings (all-MiniLM-L6-v2) - downloads automatically
            self.ef = embedding_functions.DefaultEmbeddingFunction()
            
            # Get or create collection
            self.collection = self.client.get_or_create_collection(
                name="conversation_history",
                embedding_function=self.ef,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"MemoryManager initialized at {self.persistence_path}")
        except Exception as e:
            err_msg = str(e)
            if "no such column" in err_msg or "schema" in err_msg.lower():
                logger.warning(f"ChromaDB schema mismatch detected: {e}. Resetting vector store.")
                if self._reset_chroma_store():
                    try:
                        self.client = chromadb.PersistentClient(path=self.persistence_path)
                        self.ef = embedding_functions.DefaultEmbeddingFunction()
                        self.collection = self.client.get_or_create_collection(
                            name="conversation_history",
                            embedding_function=self.ef,
                            metadata={"hnsw:space": "cosine"}
                        )
                        logger.info(f"MemoryManager reinitialized at {self.persistence_path}")
                        return
                    except Exception as reinit_err:
                        logger.error(f"Failed to reinitialize ChromaDB: {reinit_err}")
            else:
                logger.error(f"Failed to initialize ChromaDB: {e}")
            self.client = None

    def _reset_chroma_store(self) -> bool:
        """Reset ChromaDB persistence directory on schema mismatch."""
        try:
            if not os.path.exists(self.persistence_path):
                return True
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{self.persistence_path}_bak_{timestamp}"
            os.rename(self.persistence_path, backup_path)
            os.makedirs(self.persistence_path, exist_ok=True)
            logger.warning(f"ChromaDB store moved to {backup_path}")
            return True
        except Exception as e:
            if isinstance(e, PermissionError) or "Access is denied" in str(e):
                logger.warning(f"ChromaDB store is locked; using a fresh store instead.")
            else:
                logger.error(f"Failed to reset ChromaDB store: {e}")
            # Fall back to a fresh directory if rename fails (locked DB)
            try:
                base_path = self.persistence_path
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                fresh_path = f"{base_path}_fresh_{timestamp}"
                os.makedirs(fresh_path, exist_ok=True)
                self.persistence_path = fresh_path
                self.profile_path = os.path.join(self.persistence_path, "user_profile.json")
                logger.warning(f"ChromaDB store redirected to {fresh_path}")
                try:
                    redirect_file = f"{base_path}.redirect"
                    with open(redirect_file, "w", encoding="utf-8") as f:
                        f.write(fresh_path)
                except Exception:
                    pass
                return True
            except Exception as inner:
                logger.error(f"Failed to create fresh ChromaDB store: {inner}")
                return False

    def _init_profile(self):
        """Initialize or load user profile."""
        if not os.path.exists(self.profile_path):
            self.profile = {
                "name": "User",
                "preferences": {},
                "known_facts": []
            }
            self._save_profile()
        else:
            try:
                with open(self.profile_path, 'r') as f:
                    self.profile = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load profile: {e}")
                self.profile = {"name": "User", "preferences": {}}

    def _save_profile(self):
        """Save user profile to disk."""
        try:
            with open(self.profile_path, 'w') as f:
                json.dump(self.profile, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save profile: {e}")

    def save_interaction(self, role: str, text: str, metadata: Dict = None):
        """Save a single interaction to vector DB."""
        if not self.collection:
            return

        if not text or not text.strip():
            return

        try:
            # Construct metadata
            meta = {
                "role": role,
                "timestamp": datetime.now().isoformat(),
            }
            if metadata:
                meta.update(metadata)

            # Add to DB
            self.collection.add(
                documents=[text],
                metadatas=[meta],
                ids=[str(uuid.uuid4())]
            )

            # Invalidate cache since we added new data
            self._query_cache.invalidate()

            logger.debug(f"Saved memory: {text[:50]}...")
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")

    def retrieve_context(self, query: str, n_results: int = None) -> str:
        """
        Retrieve relevant context for a query.

        Uses LRU cache for performance optimization (910ms -> ~1ms for cached queries).
        """
        if not self.collection:
            return ""

        # Use config if available, otherwise default
        if n_results is None:
            try:
                from .config import get_config
                config = get_config()
                n_results = getattr(config, 'memory_top_k', 3)
            except Exception:
                n_results = 3

        # Check cache first
        cached = self._query_cache.get(query, n_results)
        if cached is not None:
            logger.debug(f"Cache hit for query: {query[:30]}...")
            return cached

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )

            # Format results
            context_parts = []
            if results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i]
                    role = meta.get("role", "unknown")
                    # Optionally convert timestamp to relative time
                    context_parts.append(f"[{role}]: {doc}")

            result = "\n".join(context_parts)

            # Cache the result
            self._query_cache.set(query, n_results, result)

            return result
        except Exception as e:
            logger.error(f"Failed to retrieve context: {e}")
            return ""

    def prewarm_embeddings(self):
        """
        Pre-warm the embedding model to reduce first-query latency.

        Call this in a background thread during startup.
        """
        if self._embedding_warmed or not self.collection:
            return

        try:
            # Run a dummy query to warm up the embedding model
            logger.info("Pre-warming embedding model...")
            self.collection.query(
                query_texts=["warm up query"],
                n_results=1
            )
            self._embedding_warmed = True
            logger.info("Embedding model pre-warmed successfully")
        except Exception as e:
            logger.warning(f"Failed to pre-warm embeddings: {e}")

    def update_profile(self, key: str, value: Any):
        """Update a specific profile field."""
        self.profile["preferences"][key] = value
        self._save_profile()

    def get_profile_context(self) -> str:
        """Get a string summary of the user profile."""
        name = self.profile.get("name", "User")
        prefs = self.profile.get("preferences", {})

        context = f"User Name: {name}\n"
        if prefs:
            context += "Preferences:\n"
            for k, v in prefs.items():
                context += f"- {k}: {v}\n"
        return context
