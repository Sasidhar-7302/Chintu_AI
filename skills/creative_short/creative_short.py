import textwrap
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.brain.llm.model_router import generate_strategy


def _safe_print(text: str) -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(text)
    except UnicodeEncodeError:
        payload = (str(text or "") + "\n").encode("utf-8", errors="replace")
        try:
            sys.stdout.buffer.write(payload)
        except Exception:
            print(str(text or "").encode("ascii", errors="replace").decode("ascii"))


def _normalize_short_script(raw: str) -> str:
    text = str(raw or "").strip()
    low = text.lower()
    if "12gb" not in low:
        text = "12GB VRAM is enough for most practical AI builds.\n\n" + text
        low = text.lower()
    if "vram" not in low:
        text = text + "\n\nKeep VRAM usage optimized with quantized models and batching."
        low = text.lower()

    cta_tokens = ["follow", "subscribe", "like", "check out", "see you next"]
    if not any(token in low for token in cta_tokens):
        text = text + "\n\nCTA: Follow for practical AI setup tips, and subscribe for the next short."
    return text


def main() -> None:
    prompt = textwrap.dedent(
        """
        Write a 60-second YouTube Short script (with stage directions) titled
        "Why 12GB VRAM is enough for AI." Keep it funny, sharp, and persona-driven.
        Reference modern GPU workloads and reassure viewers that 12GB is plenty
        affordability-friendly, then end with a witty CTA.
        """
    ).strip()
    _safe_print("=== Creative Short ===")
    try:
        response = generate_strategy(prompt, temperature=0.65)
    except Exception as exc:
        response = (
            "[Hook] Your GPU has 12GB VRAM? Relax, you're not underpowered, you're under-marketed.\n"
            "[Beat] Most local AI workflows use quantized models, smart batching, and offload tricks.\n"
            "[Joke] 24GB is awesome, but 12GB is the practical overachiever that still pays rent.\n"
            "[Proof] Coding copilots, RAG pipelines, and vision-light automations run fine with tuned settings.\n"
            "[Closer] Before buying a bigger GPU, optimize first. Your wallet deserves a cooldown too.\n"
            "[CTA] Follow for practical AI builds that work on real budgets.\n"
            f"(LLM fallback reason: {exc})"
        )
    response = _normalize_short_script(response)
    _safe_print(response)


if __name__ == "__main__":
    main()
