"""
Unit tests for Chintu Reliability & Intelligence Enhancements.
Tests Policy Engine, Budget Manager, Degraded Mode, and related components.

NOTE: These tests import directly from specific modules to avoid
dependency chain issues with pydantic_settings in config.py.
"""

import pytest
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPolicyEngine:
    """Tests for ActionPolicyEngine."""
    
    def setup_method(self):
        """Reset policy engine for each test."""
        from chintu_backend.core.policy import reset_policy_engine
        reset_policy_engine()
    
    def test_risk_levels_defined(self):
        """Verify all risk levels are defined."""
        from chintu_backend.core.policy import RiskLevel
        
        assert hasattr(RiskLevel, 'NONE')
        assert hasattr(RiskLevel, 'LOW')
        assert hasattr(RiskLevel, 'MEDIUM')
        assert hasattr(RiskLevel, 'HIGH')
        assert hasattr(RiskLevel, 'CRITICAL')
    
    def test_policy_decisions_defined(self):
        """Verify all policy decisions are defined."""
        from chintu_backend.core.policy import PolicyDecision
        
        assert hasattr(PolicyDecision, 'ALLOW')
        assert hasattr(PolicyDecision, 'REQUIRE_CONFIRMATION')
        assert hasattr(PolicyDecision, 'REQUIRE_PLAN')
        assert hasattr(PolicyDecision, 'DENY')
    
    def test_default_contracts_exist(self):
        """Verify default contracts are defined for key capabilities."""
        from chintu_backend.core.policy import get_policy_engine
        
        engine = get_policy_engine()
        
        # Check key capabilities have contracts
        key_caps = ["open_app", "web_search", "forget", "execute_workflow"]
        for cap in key_caps:
            contract = engine.get_contract(cap)
            assert contract is not None
    
    def test_safe_capability_allowed(self):
        """Verify safe capabilities are allowed."""
        from chintu_backend.core.policy import get_policy_engine, PolicyDecision
        
        engine = get_policy_engine()
        policy = engine.evaluate("help")
        
        assert policy.decision == PolicyDecision.ALLOW
    
    def test_destructive_requires_confirmation(self):
        """Verify destructive capabilities require confirmation."""
        from chintu_backend.core.policy import get_policy_engine, PolicyDecision
        
        engine = get_policy_engine()
        policy = engine.evaluate("forget")
        
        assert policy.decision == PolicyDecision.REQUIRE_CONFIRMATION
    
    def test_offline_denies_web_capability(self):
        """Verify web capabilities are denied when offline."""
        from chintu_backend.core.policy import get_policy_engine, PolicyDecision
        
        engine = get_policy_engine()
        engine.update_system_state(has_internet=False)
        
        policy = engine.evaluate("web_search")
        
        assert policy.decision == PolicyDecision.DENY
        assert "internet" in policy.reason.lower()


class TestBudgetManager:
    """Tests for RateLimitBudgetManager."""
    
    def setup_method(self):
        """Reset budget manager for each test."""
        from chintu_backend.core.budget_manager import reset_budget_manager
        reset_budget_manager()
    
    def test_initial_state(self):
        """Verify initial state allows all providers."""
        from chintu_backend.core.budget_manager import get_budget_manager
        
        manager = get_budget_manager()
        
        assert manager.can_use("groq")
        assert manager.can_use("gemini")
        assert manager.can_use("local")
    
    def test_record_usage(self):
        """Verify usage recording works."""
        from chintu_backend.core.budget_manager import get_budget_manager
        
        manager = get_budget_manager()
        
        # Record some usage
        manager.record_usage("groq", tokens=100)
        manager.record_usage("groq", tokens=200)
        
        stats = manager.get_usage_stats()
        assert stats["providers"]["groq"]["daily_usage"].startswith("2/")
    
    def test_caching(self):
        """Verify response caching works."""
        from chintu_backend.core.budget_manager import get_budget_manager
        
        manager = get_budget_manager()
        
        # Cache a response
        manager.cache_response("what can you do", "I can help with...")
        
        # Retrieve it
        cached = manager.get_cached("what can you do")
        assert cached == "I can help with..."
    
    def test_cache_miss(self):
        """Verify cache miss returns None."""
        from chintu_backend.core.budget_manager import get_budget_manager
        
        manager = get_budget_manager()
        cached = manager.get_cached("something not cached")
        
        assert cached is None
    
    def test_best_provider_selection(self):
        """Verify best provider selection."""
        from chintu_backend.core.budget_manager import get_budget_manager
        
        manager = get_budget_manager()
        
        # With default state, should prefer cloud
        provider = manager.get_best_provider(prefer_cloud=True)
        assert provider in ["groq", "gemini"]
        
        # Without cloud preference, should prefer local
        provider = manager.get_best_provider(prefer_cloud=False)
        assert provider == "local"


class TestDegradedMode:
    """Tests for OfflineDegradedMode."""
    
    def setup_method(self):
        """Reset degraded mode for each test."""
        from chintu_backend.core.degraded_mode import reset_degraded_mode
        reset_degraded_mode()
    
    def test_offline_safe_capabilities(self):
        """Verify offline-safe capabilities are always available."""
        from chintu_backend.core.degraded_mode import get_degraded_mode, SystemMode
        
        manager = get_degraded_mode()
        manager.set_mode(SystemMode.OFFLINE)
        
        # These should still be available
        for cap in ["help", "open_app", "set_reminder", "recall_facts"]:
            status = manager.is_available(cap)
            assert status.available, f"{cap} should be available offline"
    
    def test_internet_required_offline(self):
        """Verify internet-required capabilities unavailable offline."""
        from chintu_backend.core.degraded_mode import get_degraded_mode, SystemMode
        
        manager = get_degraded_mode()
        manager.set_mode(SystemMode.OFFLINE)
        
        # These should be unavailable
        for cap in ["web_search", "browser_search"]:
            status = manager.is_available(cap)
            assert not status.available or status.degraded, f"{cap} should be unavailable/degraded offline"
    
    def test_mode_message(self):
        """Verify mode messages are descriptive."""
        from chintu_backend.core.degraded_mode import get_degraded_mode, SystemMode
        
        manager = get_degraded_mode()
        
        for mode in SystemMode:
            manager.set_mode(mode)
            msg = manager.get_mode_message()
            assert len(msg) > 0


class TestMetrics:
    """Tests for MetricsCollector."""
    
    def setup_method(self):
        """Reset metrics for each test."""
        from chintu_backend.core.metrics import reset_metrics
        reset_metrics()
    
    def test_record_latency(self):
        """Verify latency recording works."""
        from chintu_backend.core.metrics import get_metrics
        
        metrics = get_metrics()
        
        metrics.record_latency("stt", 150.0)
        metrics.record_latency("stt", 200.0)
        metrics.record_latency("stt", 250.0)
        
        avg = metrics.get_avg_latency("stt")
        assert avg == 200.0  # (150+200+250)/3
    
    def test_model_usage(self):
        """Verify model usage tracking."""
        from chintu_backend.core.metrics import get_metrics
        
        metrics = get_metrics()
        
        metrics.record_model_usage("groq", "complex_query")
        metrics.record_model_usage("groq", "general_chat", success=False)
        
        stats = metrics.get_model_stats()
        assert stats["groq"]["total"] == 2
        assert stats["groq"]["success"] == 1
    
    def test_error_tracking(self):
        """Verify error tracking."""
        from chintu_backend.core.metrics import get_metrics
        
        metrics = get_metrics()
        
        metrics.record_error("network")
        metrics.record_error("network")
        metrics.record_error("api_error")
        
        errors = metrics.get_error_stats()
        assert errors["network"] == 2
        assert errors["api_error"] == 1


class TestExecutiveBrain:
    """Tests for ExecutiveBrain."""
    
    def setup_method(self):
        """Reset executive brain for each test."""
        from chintu_backend.core.executive import reset_executive_brain
        reset_executive_brain()
    
    def test_task_analysis(self):
        """Verify task analysis identifies multi-step tasks."""
        from chintu_backend.core.executive import get_executive_brain
        
        brain = get_executive_brain()
        
        # Simple task
        analysis = brain.analyze_task("open chrome")
        assert not analysis["needs_plan"]
        
        # Multi-step task
        analysis = brain.analyze_task("research python best practices and then create a summary")
        assert analysis["needs_plan"]
    
    def test_plan_creation(self):
        """Verify plan creation works."""
        from chintu_backend.core.executive import get_executive_brain, ExecutionPhase
        
        brain = get_executive_brain()
        
        plan = brain.create_plan("test task", [
            {"description": "Step 1", "capability": "web_search"},
            {"description": "Step 2", "capability": "remember_fact"}
        ])
        
        assert plan is not None
        assert len(plan.steps) == 2
        assert brain.get_phase() == ExecutionPhase.CONFIRMING
    
    def test_plan_cancellation(self):
        """Verify plan can be cancelled."""
        from chintu_backend.core.executive import get_executive_brain, ExecutionPhase
        
        brain = get_executive_brain()
        
        brain.create_plan("test task")
        brain.cancel_plan()
        
        assert brain.get_phase() == ExecutionPhase.IDLE
        assert not brain.has_pending_plan()


class TestGoldData:
    """Tests for GoldDataManager."""
    
    def setup_method(self):
        """Create temporary data directory."""
        import tempfile
        self.temp_dir = Path(tempfile.mkdtemp())
    
    def teardown_method(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_log_interaction(self):
        """Verify interaction logging."""
        from chintu_backend.training.gold_data import GoldDataManager
        
        manager = GoldDataManager(self.temp_dir)
        
        manager.log_interaction(
            user_input="hello",
            assistant_response="Hi there!",
            capability_used="conversation",
            model_used="groq"
        )
        
        pending = manager.get_pending()
        assert len(pending) == 1
        assert pending[0].user_input == "hello"
    
    def test_approve_interaction(self):
        """Verify interaction approval."""
        from chintu_backend.training.gold_data import GoldDataManager
        
        manager = GoldDataManager(self.temp_dir)
        
        manager.log_interaction("test input", "test response")
        pending = manager.get_pending()
        timestamp = pending[0].timestamp
        
        result = manager.approve(timestamp, rating=5)
        assert result is True
        
        # Should be moved from pending
        assert manager.get_pending_count() == 0
        assert manager.get_approved_count() == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
