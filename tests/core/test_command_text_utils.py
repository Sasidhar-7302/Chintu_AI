"""Unit tests for extracted CommandHandler text helpers."""

from chintu_backend.core.command_text_utils import (
    sanitize_internal_response,
    conversation_fallback_response,
    trim_context_to_budget,
    extract_numbered_followup_index,
    extract_compare_indices,
    is_numbered_followup_request,
)


def test_sanitize_internal_response_removes_internal_tags_and_noise():
    raw = (
        "__LLM_ROUTE__\n"
        "Note: Will use local model with limited capability\n"
        "NVIDIA API error: timeout\n"
        "Traceback (most recent call last)\n"
        "File \"x.py\", line 1\n"
        "Error: boom\n"
        "Clean answer line."
    )
    out = sanitize_internal_response(raw)
    low = out.lower()
    assert "__llm_route__" not in low
    assert "note: will use local model" not in low
    assert "nvidia api error" not in low
    assert "traceback" not in low
    assert "clean answer line" in low


def test_sanitize_internal_response_removes_ollama_error_wrapper():
    out = sanitize_internal_response("[Error generating response: HTTPConnectionPool timeout]")
    assert out == ""


def test_conversation_fallback_response_for_haiku_topic():
    out = conversation_fallback_response("write a haiku about coding")
    assert "silent screens at dusk" in out.lower()
    assert "coding" in out.lower()


def test_conversation_fallback_response_for_python_vs_javascript():
    out = conversation_fallback_response("Compare Python vs JavaScript")
    low = out.lower()
    assert "python" in low
    assert "javascript" in low


def test_trim_context_to_budget_keeps_structure():
    text = "A" * 120 + "\n\n" + "B" * 120 + "\n\n" + "C" * 120
    out = trim_context_to_budget(text, 200)
    assert len(out) <= 200
    assert "A" in out


def test_extract_numbered_followup_index_for_hash_and_words():
    assert extract_numbered_followup_index("read more about #3") == 3
    assert extract_numbered_followup_index("compare item two") == 2


def test_extract_compare_indices_supports_vs():
    assert extract_compare_indices("compare #2 vs #5") == (2, 5)
    assert extract_compare_indices("headline 3 versus 4") == (3, 4)


def test_is_numbered_followup_request_detects_valid_pattern():
    assert is_numbered_followup_request("read more about #1") is True
    assert is_numbered_followup_request("hello there") is False
