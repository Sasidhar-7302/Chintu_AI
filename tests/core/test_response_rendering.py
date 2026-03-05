"""Tests for shared response rendering helpers."""

from chintu_backend.core.response_rendering import (
    sanitize_for_tts,
    build_dual_view_response,
    ensure_readable_completion,
)


def test_sanitize_for_tts_removes_links_paths_and_markup_noise():
    raw = (
        "=== Daily Briefing ===\n"
        "1. [Tech] New chip launch - Source - Source (2h ago)\n"
        "Saved to C:\\Users\\demo\\Desktop\\report.md\n"
        "https://example.com/story\n"
    )
    spoken = sanitize_for_tts(raw)
    low = spoken.lower()
    assert "http://" not in low
    assert "https://" not in low
    assert "c:\\users" not in low
    assert "daily briefing" in low


def test_sanitize_for_tts_removes_emails_and_secret_like_tokens():
    raw = (
        "Contact: chintu.ai2026@gmail.com\n"
        "Token: ATATT3xFfGF0jRBK3YKYpKbh2qCpcBf40iO1qn7mV5h5HHRTMDCyOgBGEJ_jlzsxwK3p\n"
        "Status: setup complete."
    )
    spoken = sanitize_for_tts(raw)
    low = spoken.lower()
    assert "@gmail.com" not in low
    assert "atatt3xffgf0jrbk3yky" not in low
    assert "setup complete" in low


def test_build_dual_view_response_keeps_full_text_but_sanitizes_speech():
    raw = "File saved to C:\\Users\\demo\\Desktop\\out.txt\nSee https://example.com"
    views = build_dual_view_response(raw)
    assert views["text_view"] == raw
    assert "https://" not in views["speech_view"].lower()
    assert "c:\\users" not in views["speech_view"].lower()


def test_ensure_readable_completion_adds_hint_on_long_cut_text():
    cut = "Python and JavaScript both have strengths, but JavaScript shines for front-end scope and async patterns while Python excels in data and AI workflows and the best choice depends on your team and project constraints so start with clear priorities and keep your stack focused"
    out = ensure_readable_completion(cut)
    assert out.endswith("Say 'continue' if you want the rest.")


def test_ensure_readable_completion_keeps_complete_sentence_unchanged():
    msg = "Python is excellent for automation. JavaScript is excellent for interactive web interfaces."
    out = ensure_readable_completion(msg)
    assert out == msg


def test_ensure_readable_completion_handles_python_js_partial_tail():
    truncated = (
        "Python is great for data and automation, while JavaScript dominates front-end apps. "
        "For scope and async behavior, JavaSc"
    )
    out = ensure_readable_completion(truncated)
    assert out.endswith("Say 'continue' if you want the rest.")


def test_ensure_readable_completion_handles_research_partial_tail():
    truncated = (
        "LangGraph lets us orchestrate planner, executor, and verifier loops with durable state. "
        "For instance, when faced with a novel situation, C"
    )
    out = ensure_readable_completion(truncated)
    assert out.endswith("Say 'continue' if you want the rest.")
