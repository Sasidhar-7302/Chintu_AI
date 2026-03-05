from __future__ import annotations

from types import SimpleNamespace

from chintu_backend.policy.action_risk import detect_action_categories
from chintu_backend.policy.capability_contracts import CapabilityContract, RiskLevel
from chintu_backend.policy.unified_resolver import ResolverDecision, UnifiedPolicyResolver
from chintu_backend.security.payment_guard import detect_payment_signal


def test_payment_guard_detects_checkout_phrases() -> None:
    assert detect_payment_signal("click confirm purchase").matched is True
    assert detect_payment_signal("please confirm order").matched is True
    assert detect_payment_signal("submit payment").matched is True


def test_action_risk_labels_payment_category() -> None:
    categories = detect_action_categories(
        "browser_act_ref",
        "click confirm purchase on checkout page",
        {"_request_text": "click confirm purchase on checkout page"},
    )
    assert "payment" in categories


def test_unified_policy_hard_blocks_payment_actions() -> None:
    config = SimpleNamespace(
        security_runtime_profile="balanced",
        workspace_untrusted_channels=[],
        action_approval_reuse_enabled=False,
        security_payment_hard_block=True,
        security_publish_confirmation_required=True,
        security_destructive_confirmation_required=True,
    )
    resolver = UnifiedPolicyResolver(config)
    contract = CapabilityContract(
        risk_level=RiskLevel.MEDIUM,
        requires_confirmation=False,
        side_effects=["browser_click"],
    )

    outcome = resolver.resolve(
        capability_name="click_link",
        contract=contract,
        context={"_request_text": "click confirm purchase"},
    )

    assert outcome.decision == ResolverDecision.deny
    assert "payment" in outcome.categories
    assert outcome.risk_level == RiskLevel.CRITICAL


def test_browser_payment_click_is_denied(monkeypatch) -> None:
    from chintu_backend.automation.browser import browser_capabilities
    from chintu_backend.automation.browser import browser_controller

    class _DummyController:
        is_open = False

    monkeypatch.setattr(browser_controller, "get_browser_controller", lambda **_kwargs: _DummyController())
    result = browser_capabilities.handle_click_link("click confirm purchase", {})
    assert result.success is False
    assert "blocked by policy" in result.message.lower()


def test_browser_act_ref_payment_is_denied(monkeypatch) -> None:
    from chintu_backend.automation.browser import browser_capabilities
    from chintu_backend.automation.browser import browser_controller

    class _DummyController:
        is_open = False

    monkeypatch.setattr(browser_controller, "get_browser_controller", lambda **_kwargs: _DummyController())
    result = browser_capabilities.handle_browser_act_ref(
        "click confirm order",
        {"_validated_params": {"ref": "btn-confirm-order", "action": "click"}},
    )
    assert result.success is False
    assert "blocked by policy" in result.message.lower()
