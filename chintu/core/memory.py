"""
Memory Manager for Chintu Assistant.
Handles long-term memory using Vector Database (ChromaDB) and User Profile management.
"""

import os
import json
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    import chromadb
    from chromadb.utils import embedding_functions
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False

logger = logging.getLogger(__name__)

class MemoryManager:
    """Manages long-term memory and user context."""

    def __init__(self, persistence_path: str = "memory_store"):
        self.persistence_path = persistence_path
        self.profile_path = os.path.join(persistence_path, "user_profile.json")
        self.client = None
        self.collection = None
        
        # Create directory if not exists
        if not os.path.exists(persistence_path):
            os.makedirs(persistence_path, exist_ok=True)
            
        self._init_db()
        self._init_profile()

    def _init_db(self):
        """Initialize ChromaDB client."""
        if not HAS_CHROMA:
            logger.warning("ChromaDB not installed. Memory features disabled.")
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
            logger.error(f"Failed to initialize ChromaDB: {e}")
            self.client = None

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
            logger.debug(f"Saved memory: {text[:50]}...")
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")

    def retrieve_context(self, query: str, n_results: int = None) -> str:
        """Retrieve relevant context for a query."""
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
            
            return "\n".join(context_parts)
        except Exception as e:
            logger.error(f"Failed to retrieve context: {e}")
            return ""

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
