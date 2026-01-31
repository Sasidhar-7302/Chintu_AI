"""
Workflow Engine for Chintu AI Assistant.
Executes multi-step plans created by the TaskPlanner.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass
from enum import Enum

from .task_planner import Plan, Step, StepType, get_task_planner

logger = logging.getLogger(__name__)


class WorkflowStatus(Enum):
    """Status of a workflow execution."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkflowResult:
    """Result of a workflow execution."""
    success: bool
    steps_completed: int
    steps_total: int
    final_result: str
    errors: List[str]
    duration_seconds: float
    
    def __str__(self) -> str:
        status = "Completed" if self.success else "Failed"
        return f"{status}: {self.steps_completed}/{self.steps_total} steps ({self.duration_seconds:.1f}s)"


class WorkflowEngine:
    """
    Executes workflows step by step.
    Provides progress updates and error handling.
    """
    
    def __init__(self):
        self._step_handlers: Dict[StepType, Callable] = {}
        self._current_plan: Optional[Plan] = None
        self._status = WorkflowStatus.PENDING
        self._progress_callback: Optional[Callable[[str], None]] = None
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Register step handlers."""
        self._step_handlers = {
            StepType.SEARCH: self._execute_search,
            StepType.BROWSE: self._execute_browse,
            StepType.CLICK: self._execute_click,
            StepType.FILL: self._execute_fill,
            StepType.SCREENSHOT: self._execute_screenshot,
            StepType.READ: self._execute_read,
            StepType.EXTRACT: self._execute_extract,
            StepType.REMEMBER: self._execute_remember,
            StepType.NOTIFY: self._execute_notify,
            StepType.WAIT: self._execute_wait,
            StepType.CUSTOM: self._execute_custom,
        }
    
    def set_progress_callback(self, callback: Callable[[str], None]):
        """Set callback for progress updates."""
        self._progress_callback = callback
    
    def _report_progress(self, message: str):
        """Report progress to callback if set."""
        logger.info(f"Workflow: {message}")
        if self._progress_callback:
            self._progress_callback(message)
    
    def execute(self, plan: Plan) -> WorkflowResult:
        """
        Execute a workflow plan.
        
        Args:
            plan: The plan to execute
            
        Returns:
            WorkflowResult with execution details
        """
        start_time = time.time()
        self._current_plan = plan
        self._status = WorkflowStatus.RUNNING
        plan.status = "running"
        
        errors = []
        steps_completed = 0
        final_result = ""
        
        self._report_progress(f"Starting: {plan.goal}")
        
        for step in plan.steps:
            if self._status == WorkflowStatus.CANCELLED:
                break
            
            plan.current_step = step.id
            step.status = "running"
            self._report_progress(f"Step {step.id}: {step.description}")
            
            try:
                result = self._execute_step(step)
                step.status = "completed"
                step.result = result
                steps_completed += 1
                final_result = result  # Last step result is final
                
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                errors.append(f"Step {step.id}: {e}")
                logger.error(f"Step {step.id} failed: {e}")
                
                # Decide whether to continue or abort
                if not self._should_continue_after_error(step, e):
                    self._status = WorkflowStatus.FAILED
                    break
        
        # Determine final status
        duration = time.time() - start_time
        
        if self._status == WorkflowStatus.CANCELLED:
            plan.status = "cancelled"
            success = False
        elif errors:
            plan.status = "failed" if steps_completed == 0 else "partial"
            success = steps_completed > 0
        else:
            plan.status = "completed"
            success = True
            self._status = WorkflowStatus.COMPLETED
        
        self._report_progress(f"Finished: {steps_completed}/{len(plan.steps)} steps")
        
        return WorkflowResult(
            success=success,
            steps_completed=steps_completed,
            steps_total=len(plan.steps),
            final_result=final_result,
            errors=errors,
            duration_seconds=duration
        )
    
    def _should_continue_after_error(self, step: Step, error: Exception) -> bool:
        """Decide whether to continue after a step failure."""
        # For now, continue only for non-critical steps
        critical_actions = {StepType.BROWSE, StepType.FILL}
        return step.action not in critical_actions
    
    def _execute_step(self, step: Step) -> str:
        """Execute a single step."""
        handler = self._step_handlers.get(step.action)
        if not handler:
            raise ValueError(f"No handler for action: {step.action}")
        
        return handler(step)
    
    def cancel(self):
        """Cancel the current workflow."""
        self._status = WorkflowStatus.CANCELLED
        logger.info("Workflow cancelled")
    
    # Step Handlers
    
    def _execute_search(self, step: Step) -> str:
        """Execute a search step."""
        from ..search.web_search import search_web
        
        query = step.parameters.get("query", "")
        if not query:
            raise ValueError("No search query provided")
        
        return search_web(query, max_results=5)
    
    def _execute_browse(self, step: Step) -> str:
        """Execute a browse step."""
        from ..browser.browser_controller import get_browser_controller
        
        url = step.parameters.get("url", "")
        if not url:
            raise ValueError("No URL provided")
        
        controller = get_browser_controller(headless=False)
        page_info = controller.open_url(url)
        return f"Opened: {page_info.title} ({page_info.url})"
    
    def _execute_click(self, step: Step) -> str:
        """Execute a click step."""
        from ..browser.browser_controller import get_browser_controller
        
        text = step.parameters.get("text", "")
        selector = step.parameters.get("selector", "")
        
        if not text and not selector:
            raise ValueError("No click target provided")
        
        controller = get_browser_controller()
        success = controller.click_link(text or selector)
        
        if success:
            return f"Clicked: {text or selector}"
        else:
            raise ValueError(f"Could not find element: {text or selector}")
    
    def _execute_fill(self, step: Step) -> str:
        """Execute a fill step."""
        from ..browser.browser_controller import get_browser_controller
        
        selector = step.parameters.get("selector", "")
        value = step.parameters.get("value", "")
        
        if not selector or not value:
            raise ValueError("Missing selector or value for fill")
        
        controller = get_browser_controller()
        success = controller.fill_input(selector, value)
        
        if success:
            return f"Filled: {selector}"
        else:
            raise ValueError(f"Could not fill: {selector}")
    
    def _execute_screenshot(self, step: Step) -> str:
        """Execute a screenshot step."""
        from ..browser.browser_controller import get_browser_controller
        
        filename = step.parameters.get("filename")
        controller = get_browser_controller()
        filepath = controller.take_screenshot(filename)
        return f"Screenshot saved: {filepath}"
    
    def _execute_read(self, step: Step) -> str:
        """Execute a read page step."""
        from ..browser.browser_controller import get_browser_controller
        
        controller = get_browser_controller()
        if not controller.is_open:
            raise ValueError("No browser page is open")
        
        content = controller.get_page_content(max_length=2000)
        return content
    
    def _execute_extract(self, step: Step) -> str:
        """Execute an extract step."""
        from ..browser.browser_controller import get_browser_controller
        
        selector = step.parameters.get("selector", "body")
        controller = get_browser_controller()
        
        if not controller.is_open:
            raise ValueError("No browser page is open")
        
        # Use page to extract specific content
        try:
            element = controller._page.query_selector(selector)
            if element:
                return element.inner_text()[:1000]
            else:
                return f"No element found for selector: {selector}"
        except Exception as e:
            return f"Extract failed: {e}"
    
    def _execute_remember(self, step: Step) -> str:
        """Execute a remember step."""
        from ..brain.memory.tiered_memory import get_memory_store

        content = step.parameters.get("content", "")
        category = step.parameters.get("category", "workflow")

        if not content:
            raise ValueError("No content to remember")

        memory = get_memory_store()

        # Store based on category
        if category == "fact":
            memory.add_fact(content, metadata={"source": "workflow"})
        elif category == "note":
            memory.add_note(content, metadata={"source": "workflow"})
        else:
            # Default to note for workflow-generated content
            memory.add_note(content, metadata={"source": "workflow", "category": category})

        return f"Saved to memory: {content[:50]}..."
    
    def _execute_notify(self, step: Step) -> str:
        """Execute a notify step."""
        message = step.parameters.get("message", step.description)
        return message
    
    def _execute_wait(self, step: Step) -> str:
        """Execute a wait step."""
        import threading
        seconds = step.parameters.get("seconds", 1)
        threading.Event().wait(min(seconds, 10))  # Interruptible (max 10s)
        return f"Waited {seconds} seconds"
    
    def _execute_custom(self, step: Step) -> str:
        """Execute a custom step (pass-through)."""
        return step.description


# Global instance
_workflow_engine: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    """Get the global workflow engine instance."""
    global _workflow_engine
    if _workflow_engine is None:
        _workflow_engine = WorkflowEngine()
    return _workflow_engine
