import textwrap
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.brain.llm.model_router import generate_strategy


TASKS = [
    "Daily briefing (calendar + Hacker News AI)",
    "Hardware health check + Brain model routing",
    "Downloads organizer preview",
    "Pip module installer + rerun target script",
    "SSD price comparison (Amazon vs Newegg)",
    "LangGraph agentic research for memory",
    "Visa Bot memory recall + to-do formatting",
    "Creative 60-second script about 12GB VRAM",
    "OS focus protocol (windows, volume, Spotify, VSCode)",
]


def output_plan(api_response: str) -> None:
    print("=== Agentic Planner ===")
    print(api_response)


def main() -> None:
    tasks_str = " | ".join(TASKS)
    prompt = textwrap.dedent(
        f"""
        Act as Chintu's local planner. The following tasks must run end-to-end; choose the best skill trigger
        for each task, note dependencies, and propose the sequencing. Include any missing capability and
        how to construct it (e.g., new skill markdown or scripts). Respond with step-by-step plan referencing the skill names:
        {tasks_str}
        Always highlight the final step that executes each skill and how Chintu will confirm success.
        """
    ).strip()
    try:
        response = generate_strategy(prompt, temperature=0.5)
    except Exception as exc:
        response = f"Planner failed: {exc}"
    output_plan(response)


if __name__ == "__main__":
    main()
