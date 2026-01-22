"""
Chintu Training Module.

Provides functionality for:
- Logging interactions for future fine-tuning
- Approving "gold" interactions
- Exporting training data in JSONL format
"""

from .gold_data import GoldDataManager, Interaction, get_gold_data_manager

__all__ = [
    "GoldDataManager",
    "Interaction", 
    "get_gold_data_manager",
]
