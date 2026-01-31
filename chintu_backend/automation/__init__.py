"""
Automation module for Chintu AI Assistant.
Provides scheduled workflows, cross-app data flow, and parallel task execution.
"""

from .scheduled_tasks import ScheduledTask, get_scheduler
from .parallel_executor import ParallelExecutor, get_parallel_executor
from .cross_app import DataTransfer, get_data_transfer
from .automation_capabilities import register_automation_capabilities

__all__ = [
    "ScheduledTask",
    "get_scheduler",
    "ParallelExecutor", 
    "get_parallel_executor",
    "DataTransfer",
    "get_data_transfer",
    "register_automation_capabilities",
]
