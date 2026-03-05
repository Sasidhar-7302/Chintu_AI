from __future__ import annotations

from pathlib import Path

from chintu_backend.core.persona_registry import PersonaRegistry, PersonaSpec


def test_persona_registry_selects_coding_for_code_prompt():
    registry = PersonaRegistry(enabled=True, specs=None)
    selected = registry.select(text="Please debug this Python API exception and refactor it.", intent="coding")
    assert selected.name == "coding"
    assert selected.fallback_to_default is False


def test_persona_registry_selects_finance_for_market_prompt():
    registry = PersonaRegistry(enabled=True, specs=None)
    selected = registry.select(text="Analyze my ETF portfolio and rebalance risk profile.", intent="research")
    assert selected.name == "finance"
    assert selected.fallback_to_default is False


def test_persona_registry_falls_back_when_adapter_missing(tmp_path):
    missing = Path(tmp_path / "missing_adapter")
    registry = PersonaRegistry(
        enabled=True,
        specs=[
            PersonaSpec(name="default", playbook="general"),
            PersonaSpec(name="coding", adapter_path=str(missing), playbook="code"),
        ],
    )
    selected = registry.select(text="Fix this bug in my Python code.", intent="coding")
    assert selected.name == "default"
    assert selected.requested == "coding"
    assert selected.fallback_to_default is True
