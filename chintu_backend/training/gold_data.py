"""
Gold Data Manager for Chintu AI Assistant.

Manages approved interaction data for future fine-tuning.
Features:
- Log all interactions to pending file
- Approve/reject interactions for training
- Export approved data as JSONL for LoRA fine-tuning
- Statistics on interaction quality
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Iterator
from datetime import datetime, timezone
import threading
import os

logger = logging.getLogger(__name__)


@dataclass
class Interaction:
    """A single interaction for training data."""
    timestamp: str                          # ISO datetime
    user_input: str                         # What the user said
    assistant_response: str                 # What Chintu responded
    capability_used: Optional[str] = None   # Capability that handled it
    model_used: Optional[str] = None        # LLM model used
    is_approved: bool = False               # Approved as gold data
    approval_timestamp: Optional[str] = None
    tags: List[str] = field(default_factory=list)  # Custom tags
    rating: Optional[int] = None            # 1-5 quality rating
    
    def to_training_format(self) -> dict:
        """Convert to training JSONL format."""
        return {
            "instruction": self.user_input,
            "output": self.assistant_response,
            "metadata": {
                "capability": self.capability_used,
                "model": self.model_used,
                "tags": self.tags,
                "rating": self.rating,
            }
        }
    
    def to_chat_format(self) -> dict:
        """Convert to chat completion JSONL format."""
        return {
            "messages": [
                {"role": "user", "content": self.user_input},
                {"role": "assistant", "content": self.assistant_response}
            ]
        }


class GoldDataManager:
    """
    Manages gold-standard training data.
    
    Workflow:
    1. All interactions logged to pending file
    2. User reviews and approves/rejects
    3. Approved data exported for fine-tuning
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        """
        Initialize the gold data manager.
        
        Args:
            data_dir: Directory for storing interaction data
        """
        if data_dir is None:
            # Default to ~/.chintu/training/
            data_dir = Path.home() / ".chintu" / "training"
        
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        
        self._pending_file = self._data_dir / "pending_interactions.jsonl"
        self._approved_file = self._data_dir / "gold_interactions.jsonl"
        self._rejected_file = self._data_dir / "rejected_interactions.jsonl"
        
        self._lock = threading.Lock()
        
        logger.info(f"GoldDataManager initialized at {self._data_dir}")
    
    def _write_jsonl(self, filepath: Path, data: dict):
        """Append a JSON line to a file."""
        with self._lock:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
    
    def _read_jsonl(self, filepath: Path) -> Iterator[dict]:
        """Read JSON lines from a file."""
        if not filepath.exists():
            return
        
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    
    def log_interaction(self, 
                        user_input: str, 
                        assistant_response: str,
                        capability_used: Optional[str] = None,
                        model_used: Optional[str] = None,
                        tags: Optional[List[str]] = None,
                        approved: bool = False,
                        rating: Optional[int] = None):
        """
        Log a new interaction for potential approval.
        
        Args:
            user_input: What the user said
            assistant_response: What Chintu responded
            capability_used: Capability that handled it
            model_used: LLM model used
            tags: Optional tags for categorization
        """
        interaction = Interaction(
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            user_input=user_input,
            assistant_response=assistant_response,
            capability_used=capability_used,
            model_used=model_used,
            tags=tags or []
        )
        if approved:
            interaction.is_approved = True
            interaction.approval_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            interaction.rating = int(rating if rating is not None else 4)
            self._write_jsonl(self._approved_file, asdict(interaction))
        else:
            self._write_jsonl(self._pending_file, asdict(interaction))
        logger.debug(f"Logged interaction: {user_input[:50]}...")
    
    def get_pending(self, limit: int = 20, offset: int = 0) -> List[Interaction]:
        """
        Get pending interactions for review.
        
        Args:
            limit: Max number to return
            offset: Number to skip
            
        Returns:
            List of Interaction objects
        """
        interactions = []
        
        for i, data in enumerate(self._read_jsonl(self._pending_file)):
            if i < offset:
                continue
            if len(interactions) >= limit:
                break
            
            try:
                interactions.append(Interaction(**data))
            except TypeError:
                continue
        
        return interactions
    
    def get_pending_count(self) -> int:
        """Get count of pending interactions."""
        count = 0
        for _ in self._read_jsonl(self._pending_file):
            count += 1
        return count
    
    def approve(self, timestamp: str, rating: int = 5, tags: Optional[List[str]] = None) -> bool:
        """
        Approve an interaction as gold data.
        
        Args:
            timestamp: Timestamp of interaction to approve
            rating: Quality rating 1-5
            tags: Optional additional tags
            
        Returns:
            True if approved successfully
        """
        # Find and remove from pending
        pending = list(self._read_jsonl(self._pending_file))
        found = None
        remaining = []
        
        for data in pending:
            if data.get("timestamp") == timestamp:
                found = data
            else:
                remaining.append(data)
        
        if not found:
            logger.warning(f"Interaction not found: {timestamp}")
            return False
        
        # Update and write to approved
        found["is_approved"] = True
        found["approval_timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        found["rating"] = rating
        if tags:
            found["tags"] = found.get("tags", []) + tags
        
        self._write_jsonl(self._approved_file, found)
        
        # Rewrite pending without this interaction
        self._rewrite_jsonl(self._pending_file, remaining)
        
        logger.info(f"Approved interaction: {timestamp}")
        return True
    
    def reject(self, timestamp: str, reason: Optional[str] = None) -> bool:
        """
        Reject an interaction.
        
        Args:
            timestamp: Timestamp of interaction to reject
            reason: Optional rejection reason
            
        Returns:
            True if rejected successfully
        """
        # Find and remove from pending
        pending = list(self._read_jsonl(self._pending_file))
        found = None
        remaining = []
        
        for data in pending:
            if data.get("timestamp") == timestamp:
                found = data
            else:
                remaining.append(data)
        
        if not found:
            return False
        
        # Write to rejected file
        found["rejection_reason"] = reason
        found["rejection_timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._write_jsonl(self._rejected_file, found)
        
        # Rewrite pending
        self._rewrite_jsonl(self._pending_file, remaining)
        
        logger.info(f"Rejected interaction: {timestamp}")
        return True
    
    def _rewrite_jsonl(self, filepath: Path, data_list: List[dict]):
        """Rewrite a JSONL file with new data."""
        with self._lock:
            with open(filepath, "w", encoding="utf-8") as f:
                for data in data_list:
                    f.write(json.dumps(data, ensure_ascii=False) + "\n")
    
    def get_approved(self, limit: int = 100) -> List[Interaction]:
        """Get approved interactions."""
        interactions = []
        for data in self._read_jsonl(self._approved_file):
            if len(interactions) >= limit:
                break
            try:
                interactions.append(Interaction(**data))
            except TypeError:
                continue
        return interactions
    
    def get_approved_count(self) -> int:
        """Get count of approved interactions."""
        count = 0
        for _ in self._read_jsonl(self._approved_file):
            count += 1
        return count
    
    def export_jsonl(self, 
                     output_path: Path, 
                     format: str = "instruction",
                     min_rating: int = 1) -> int:
        """
        Export approved data for training.
        
        Args:
            output_path: Where to write the JSONL file
            format: "instruction" or "chat"
            min_rating: Minimum rating to include
            
        Returns:
            Number of interactions exported
        """
        count = 0
        
        with open(output_path, "w", encoding="utf-8") as f:
            for data in self._read_jsonl(self._approved_file):
                rating = data.get("rating", 5)
                if rating < min_rating:
                    continue
                
                try:
                    interaction = Interaction(**data)
                    
                    if format == "chat":
                        export_data = interaction.to_chat_format()
                    else:
                        export_data = interaction.to_training_format()
                    
                    f.write(json.dumps(export_data, ensure_ascii=False) + "\n")
                    count += 1
                except (TypeError, KeyError):
                    continue
        
        logger.info(f"Exported {count} interactions to {output_path}")
        return count
    
    def get_stats(self) -> dict:
        """Get statistics on training data."""
        pending = self.get_pending_count()
        approved = self.get_approved_count()
        
        # Count by capability
        capability_counts = {}
        model_counts = {}
        
        for data in self._read_jsonl(self._approved_file):
            cap = data.get("capability_used", "unknown")
            model = data.get("model_used", "unknown")
            capability_counts[cap] = capability_counts.get(cap, 0) + 1
            model_counts[model] = model_counts.get(model, 0) + 1
        
        return {
            "pending_count": pending,
            "approved_count": approved,
            "top_capabilities": dict(sorted(capability_counts.items(), 
                                           key=lambda x: x[1], reverse=True)[:5]),
            "models_used": model_counts,
            "data_directory": str(self._data_dir),
        }
    
    def clear_pending(self):
        """Clear all pending interactions."""
        with self._lock:
            if self._pending_file.exists():
                self._pending_file.unlink()
        logger.info("Cleared pending interactions")


# Global instance
_gold_data_manager: Optional[GoldDataManager] = None


def get_gold_data_manager() -> GoldDataManager:
    """Get or create the global gold data manager."""
    global _gold_data_manager
    if _gold_data_manager is None:
        _gold_data_manager = GoldDataManager()
    return _gold_data_manager


def reset_gold_data_manager():
    """Reset the global gold data manager (for testing)."""
    global _gold_data_manager
    _gold_data_manager = None
