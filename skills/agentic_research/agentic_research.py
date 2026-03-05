import textwrap
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.brain.llm.model_router import generate_strategy


def _normalize_response(raw: str) -> str:
    text = str(raw or "").strip()
    bullets = [line.strip() for line in text.splitlines() if line.strip().startswith("- ")]
    has_memory_apply = ("memory" in text.lower()) and ("chintu" in text.lower())
    if len(bullets) >= 3 and has_memory_apply:
        normalized_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                normalized_lines.append("")
                continue
            if stripped.startswith("- "):
                normalized_lines.append(f"- {stripped[2:].strip()}")
            else:
                normalized_lines.append(stripped)
        return "\n".join(normalized_lines).strip()

    fallback_bullets = [
        "- LangGraph models workflows as explicit graph states, which makes multi-step agent behavior auditable and predictable.",
        "- Durable checkpoints allow recovery from tool failures and safe resume without losing context.",
        "- Planner/executor/reviewer node separation improves accuracy by forcing validation before final output.",
    ]
    fallback_paragraph = (
        "For Chintu's memory system, these ideas map cleanly to a retrieval graph: one node retrieves context from hybrid "
        "memory, one node verifies relevance/confidence, and one node writes updates only after validation. That reduces bad "
        "memory writes, improves recall quality, and makes reminder/goal flows resumable after errors."
    )
    return (
        "1. Bullet summary of LangGraph lessons:\n"
        + "\n".join(fallback_bullets)
        + "\n\n2. A short paragraph applying each lesson to Chintu memory:\n"
        + fallback_paragraph
    )


def main() -> None:
    prompt = textwrap.dedent(
        """
        Research "Agentic Workflows using LangGraph" and summarize the key concepts in three concise bullets.
        Then explain how these ideas could improve Chintu's memory system, referencing hybrid memory retrieval,
        reminder scheduling, or agentic goal planning.
        Provide the answer as:
        1. Bullet summary of LangGraph lessons.
        2. A short paragraph applying each lesson to Chintu memory.
        """
    ).strip()
    try:
        response = generate_strategy(prompt, temperature=0.55)
    except Exception as exc:
        response = (
            "Key concepts:\n"
            "- LangGraph uses explicit state machines to manage agent steps and tool calls.\n"
            "- Durable checkpoints allow resumable workflows and better recovery on failures.\n"
            "- Multi-agent graphs separate planner/executor/reviewer roles for higher reliability.\n\n"
            "How to use this in Chintu memory:\n"
            "Use a stateful memory graph where retrieval, update, and verification are separate nodes. "
            "Checkpoint before each memory mutation, and route failed retrieval paths to a fallback node "
            "that asks clarifying questions before writing new memory.\n"
            f"\n(LLM fallback reason: {exc})"
        )
    response = _normalize_response(response)
    print("=== LangGraph Agentic Research ===")
    print(response)


if __name__ == "__main__":
    main()
