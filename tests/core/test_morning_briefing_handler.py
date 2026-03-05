"""
Regression tests for morning briefing handler stability and follow-up context.
"""

import re

from chintu_backend.automation import automation_capabilities as ac


class _FakePrefs:
    news_categories = ["tech", "finance", "healthcare"]
    news_category_weights = {"tech": 1.0, "finance": 1.0, "healthcare": 1.0}


class _FakePrefManager:
    preferences = _FakePrefs()


class _FakeCalendar:
    is_authenticated = False


class _FakeTaskManager:
    def get_tasks_due_today(self):
        return []


class _FakeUpdater:
    def __init__(self, count: int):
        self._count = count

    def build_daily_digest(self, total=20, categories=None, weights=None):
        items = []
        for idx in range(int(self._count)):
            items.append(
                {
                    "title": f"Headline {idx + 1}",
                    "category": "tech" if idx % 3 == 0 else ("finance" if idx % 3 == 1 else "healthcare"),
                    "summary": f"Summary for item {idx + 1}",
                    "source": "Example Source",
                    "url": f"https://example.com/{idx + 1}",
                }
            )
        return {"digest_id": "digest_test_123", "items": items}


def _setup_common_monkeypatch(monkeypatch, *, digest_count: int = 20):
    monkeypatch.setattr(
        "chintu_backend.brain.memory.preferences.get_preference_manager",
        lambda: _FakePrefManager(),
    )
    monkeypatch.setattr(
        "chintu_backend.brain.knowledge.knowledge_updater.get_knowledge_updater",
        lambda: _FakeUpdater(digest_count),
    )
    monkeypatch.setattr(
        "chintu_backend.integrations.google_calendar.get_calendar",
        lambda: _FakeCalendar(),
    )
    monkeypatch.setattr(
        "chintu_backend.tasks.task_manager.get_task_manager",
        lambda: _FakeTaskManager(),
    )
    monkeypatch.setattr(ac, "_save_cached_morning_briefing_items", lambda _items: None)
    monkeypatch.setattr(ac, "_render_morning_briefing_feedback_ui", lambda _items: None)


def test_morning_briefing_handler_exists():
    assert hasattr(ac, "handle_morning_briefing")
    assert callable(ac.handle_morning_briefing)


def test_morning_briefing_outputs_headline_only_with_exact_count(monkeypatch):
    _setup_common_monkeypatch(monkeypatch, digest_count=20)

    result = ac.handle_morning_briefing(
        "Good morning, give me my daily briefing",
        {"_validated_params": ac.MorningBriefingSchema(headlines=20)},
    )

    assert result.success is True
    assert "[Top 20 Headlines]" in result.message
    numbered = [line for line in result.message.splitlines() if re.match(r"^\d{2}\. \[", line.strip())]
    assert len(numbered) == 20
    assert "https://" not in result.message
    assert "http://" not in result.message


def test_morning_briefing_follow_up_context_survives_next_turn(monkeypatch):
    _setup_common_monkeypatch(monkeypatch, digest_count=5)

    first = ac.handle_morning_briefing(
        "daily briefing",
        {"_validated_params": ac.MorningBriefingSchema(headlines=5)},
    )
    assert first.success is True

    second = ac.handle_morning_briefing_detail("read more about #1", {})
    assert second.success is True
    assert "could not load recent briefing headlines" not in second.message.lower()
