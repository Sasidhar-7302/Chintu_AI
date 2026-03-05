"""
Regression tests for memory recall de-duplication in user-facing responses.
"""

from types import SimpleNamespace

from chintu_backend.brain.memory import memory_capabilities as mc


class _FakeMemoryStore:
    def __init__(self, facts):
        self._facts = list(facts)

    def search_facts(self, _query):
        return list(self._facts)

    def get_facts(self, limit=20):
        return list(self._facts)[: int(limit)]


def _bullet_lines(message: str) -> list[str]:
    return [line.strip() for line in str(message or "").splitlines() if line.strip().startswith("- ")]


def test_recall_specific_query_dedupes_duplicate_fact_lines(monkeypatch):
    facts = [
        SimpleNamespace(
            content="I'll remember that: the user's dog's name is Buddy",
            created_at="2026-02-24T01:23:00Z",
        ),
        SimpleNamespace(
            content="the user's dog's name is Buddy",
            created_at="2026-02-24T01:23:00Z",
        ),
        SimpleNamespace(
            content="Your dog's name is Buddy",
            created_at="2026-02-24T01:22:00Z",
        ),
    ]
    monkeypatch.setattr(mc, "get_memory_store", lambda: _FakeMemoryStore(facts))

    result = mc.handle_recall_facts("What is my dog's name?", {})

    assert result.success is True
    bullets = _bullet_lines(result.message)
    assert len(bullets) == 1
    assert "buddy" in bullets[0].lower()


def test_recall_all_memories_dedupes_and_keeps_distinct_items(monkeypatch):
    facts = [
        SimpleNamespace(
            content="I'll remember that: the user's dog's name is Buddy",
            created_at="2026-02-24T01:23:00Z",
        ),
        SimpleNamespace(
            content="the user's dog's name is Buddy",
            created_at="2026-02-24T01:22:00Z",
        ),
        SimpleNamespace(
            content="the user's favorite color is blue",
            created_at="2026-02-24T01:24:00Z",
        ),
    ]
    monkeypatch.setattr(mc, "get_memory_store", lambda: _FakeMemoryStore(facts))

    result = mc.handle_recall_facts("List all my memories", {})

    assert result.success is True
    bullets = _bullet_lines(result.message)
    assert len(bullets) == 2
    message_lower = result.message.lower()
    assert "buddy" in message_lower
    assert "blue" in message_lower
