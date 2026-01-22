
import pytest
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from chintu.automation.scheduled_tasks import get_scheduler, Scheduler, ScheduledTask, ScheduleType
from chintu.automation.parallel_executor import get_parallel_executor, ParallelExecutor
from chintu.agents.task_planner import get_task_planner
from chintu.agents.workflow_engine import get_workflow_engine
from chintu.core.help_capabilities import handle_help
from chintu.core.capabilities import get_registry

class TestAutomationFixes:
    
    def setup_method(self):
        # Reset singletons if possible or mock them
        pass

    def test_scheduler_callback_execution(self):
        """Test that scheduler executes callback when task triggers."""
        scheduler = Scheduler()
        mock_callback = MagicMock()
        scheduler.set_callback(mock_callback)
        
        # Create a task that is due
        task = scheduler.schedule(
            name="Test Task",
            workflow="test workflow",
            schedule_type=ScheduleType.ONCE,
            schedule_time="00:00" # Time doesn't matter for manual trigger check
        )
        
        # Manually force execution to verify callback logic
        scheduler._execute_task(task)
        
        mock_callback.assert_called_once_with("test workflow")

    def test_task_planner_imports(self):
        """Test that TaskPlanner calls the correct model router methods."""
        planner = get_task_planner()
        
        # Mock ModelRouter.get_router
        with patch('chintu.core.model_router.get_router') as mock_get_router:
            mock_router = MagicMock()
            mock_router.route_and_execute.return_value = ('[{"action": "search", "description": "test"}]', "local")
            mock_get_router.return_value = mock_router
            
            plan = planner.plan("research AI")
            
            # Verify it called route_and_execute (based on my code read)
            # If the code was broken as user said, this might fail or show it calls something else
            mock_router.route_and_execute.assert_called()
            assert len(plan.steps) > 0
            
    def test_parallel_executor_handler(self):
        """Test ParallelExecutor uses the command handler."""
        executor = ParallelExecutor()
        mock_handler = MagicMock()
        mock_handler.return_value = "Success"
        executor.set_command_handler(mock_handler)
        
        task = executor.submit("Background Test", "run this")
        
        # Wait for thread
        time.sleep(0.5)
        
        mock_handler.assert_called_with("run this")
        assert task.result == "Success"

    def test_status_command_exists(self):
        """Test that status capability is registered and works."""
        from chintu.core.help_capabilities import register_help_capabilities
        
        # Ensure registered
        register_help_capabilities()
        registry = get_registry()
        
        # Check registration
        status_cap = registry.get("status")
        
        # NOTE: This is expected to FAIL until we implement it
        if not status_cap:
            pytest.fail("Status capability not registered")
            
        # Check handler
        result = status_cap.handler("status", {})
        assert result.success
        assert "**Status**:" in result.message or "Status:" in result.message

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
