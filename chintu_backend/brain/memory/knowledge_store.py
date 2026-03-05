"""Knowledge Store: Manages the file-based 'Brain' of Chintu."""

import os
import yaml
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime

logger = logging.getLogger(__name__)

class KnowledgeStore:
    """
    Manages structured knowledge in a file-system hierarchy.
    
    Structure:
    data_dir/
      knowledge/
        {category}/  (e.g., "machine_learning", "history")
          {topic}/   (e.g., "neural_networks", "world_war_2")
             index.md
             chapter_1.md
    """

    def __init__(self, data_dir: Union[str, Path]):
        self.root_dir = Path(data_dir) / "knowledge"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"KnowledgeStore initialized at {self.root_dir}")

    def save_document(
        self, 
        category: str, 
        topic: str, 
        filename: str, 
        content: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> Path:
        """
        Save a markdown document with YAML frontmatter.
        
        Args:
            category: High-level grouping (e.g., "technology")
            topic: Specific subject (e.g., "python")
            filename: File name (e.g., "basics.md")
            content: Markdown content
            metadata: key-value pairs for frontmatter
        """
        safe_cat = self._sanitize(category)
        safe_topic = self._sanitize(topic)
        safe_name = self._sanitize_filename(filename)
        
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        dir_path = self.root_dir / safe_cat / safe_topic
        dir_path.mkdir(parents=True, exist_ok=True)
        
        file_path = dir_path / safe_name
        
        full_content = self._build_markdown(content, metadata or {})
        
        try:
            file_path.write_text(full_content, encoding="utf-8")
            logger.info(f"Saved knowledge: {file_path}")
            # Optional: index into hybrid memory for RAG
            try:
                from chintu_backend.core.config import get_config
                from chintu_backend.brain.memory.hybrid_memory import get_hybrid_memory
                config = get_config()
                if getattr(config, "memory_enabled", True):
                    memory = get_hybrid_memory()
                    if memory:
                        mem_meta = {
                            "category": "knowledge",
                            "topic": safe_topic,
                            "source": "knowledge_store",
                            "file": safe_name,
                        }
                        if metadata:
                            mem_meta.update(metadata)
                        memory.add_knowledge_document(content=content, metadata=mem_meta)
            except Exception:
                pass
            return file_path
        except Exception as e:
            logger.error(f"Failed to save knowledge document {file_path}: {e}")
            raise

    def read_document(self, category: str, topic: str, filename: str) -> Dict[str, Any]:
        """Read a document and parse frontmatter."""
        path = self.root_dir / self._sanitize(category) / self._sanitize(topic) / filename
        if not path.exists() and not filename.endswith(".md"):
            path = path.with_suffix(".md")
            
        if not path.exists():
            return None
            
        text = path.read_text(encoding="utf-8")
        return self._parse_markdown(text)

    def list_categories(self) -> List[str]:
        """List all knowledge categories."""
        if not self.root_dir.exists():
            return []
        return [d.name for d in self.root_dir.iterdir() if d.is_dir()]

    def list_topics(self, category: str) -> List[str]:
        """List topics within a category."""
        cat_dir = self.root_dir / self._sanitize(category)
        if not cat_dir.exists():
            return []
        return [d.name for d in cat_dir.iterdir() if d.is_dir()]

    def _build_markdown(self, content: str, metadata: Dict[str, Any]) -> str:
        """Add YAML frontmatter to content."""
        meta_copy = metadata.copy()
        meta_copy["last_updated"] = datetime.now().isoformat()
        
        # Simple YAML dump (avoiding complex dependencies if possible, but PyYAML is standard)
        yaml_str = yaml.dump(meta_copy, default_flow_style=False, sort_keys=False).strip()
        
        return f"---\n{yaml_str}\n---\n\n{content}"

    def _parse_markdown(self, text: str) -> Dict[str, Any]:
        """Parse frontmatter and content."""
        # Regex for frontmatter
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if match:
            yaml_str = match.group(1)
            content = match.group(2)
            try:
                metadata = yaml.safe_load(yaml_str)
                return {"metadata": metadata, "content": content.strip()}
            except Exception:
                pass
        
        return {"metadata": {}, "content": text}

    def _sanitize(self, name: str) -> str:
        """Sanitize directory names."""
        return re.sub(r'[^\w\-]', '_', name.lower().strip())

    def _sanitize_filename(self, name: str) -> str:
        return re.sub(r'[^\w\-\.]', '_', name.lower().strip())
