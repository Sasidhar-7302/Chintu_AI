import argparse
from pathlib import Path
import shutil


CODE_TEMPLATE = """from pathlib import Path
import shutil


downloads = Path.home() / "Downloads"
documents = Path.home() / "Documents"
installers = Path.home() / "Installers"

documents.mkdir(exist_ok=True)
installers.mkdir(exist_ok=True)

for pdf_file in downloads.glob("*.pdf"):
    shutil.move(str(pdf_file), str(documents / pdf_file.name))

for exe_file in downloads.glob("*.exe"):
    shutil.move(str(exe_file), str(installers / exe_file.name))
"""


def collect_by_extension(root: Path) -> dict[str, list[Path]]:
    pdfs = list(root.glob("*.pdf"))
    exes = list(root.glob("*.exe"))
    return {"pdf": pdfs, "exe": exes}


def ensure_destinations(home: Path) -> dict[str, Path]:
    documents = home / "Documents"
    installers = home / "Installers"
    documents.mkdir(exist_ok=True)
    installers.mkdir(exist_ok=True)
    return {"pdf": documents, "exe": installers}


def move_files(files: list[Path], dest: Path) -> list[Path]:
    moved = []
    for file in files:
        target = dest / file.name
        shutil.move(str(file), str(target))
        moved.append(target)
    return moved


def format_plan(files: dict[str, list[Path]], destinations: dict[str, Path]) -> str:
    lines = []
    for kind, entries in files.items():
        if not entries:
            lines.append(f"No {kind.upper()} files detected.")
            continue
        lines.append(f"{kind.upper()} files ({len(entries)}):")
        for entry in entries:
            target = destinations[kind] / entry.name
            lines.append(f"  - {entry} → {target}")
    return "\n".join(lines)


def should_show_code(request: str) -> bool:
    low = request.lower()
    signals = [
        "show me the code",
        "just show me the code",
        "write the code",
        "dont run",
        "don't run",
        "do not run",
    ]
    return any(signal in low for signal in signals)


def main() -> None:
    parser = argparse.ArgumentParser(description="Organize Downloads folder.")
    parser.add_argument(
        "--request",
        default="",
        help="Original natural-language request to support code-only responses.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually move the files. Without this flag the script only shows the plan.",
    )
    args = parser.parse_args()

    if should_show_code(args.request):
        print("=== Downloads Organizer Code ===")
        print("```python")
        print(CODE_TEMPLATE.rstrip())
        print("```")
        print("")
        print("Dry run only. Save this script and run it manually when ready.")
        return

    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        print("Downloads directory does not exist.")
        return

    files = collect_by_extension(downloads)
    destinations = ensure_destinations(Path.home())
    plan = format_plan(files, destinations)

    print("=== Downloads Organizer ===")
    print(plan)
    if not args.execute:
        print("\nDry run. Add --execute to perform the moves.")
        return

    moved = []
    for kind, entries in files.items():
        if not entries:
            continue
        moved.extend(move_files(entries, destinations[kind]))
    print("\nMoved files:")
    for entry in moved:
        print(f"  - {entry}")


if __name__ == "__main__":
    main()
