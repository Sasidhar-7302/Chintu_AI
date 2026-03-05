# Documentation Style Guide

## Goals
- Keep docs executable: include commands, paths, and expected artifacts.
- Prefer determinism: document exact inputs and outputs where possible.
- Make navigation easy: every doc must be listed in `docs/INDEX.md`.

## Voice and Structure
- Use direct, technical language. Avoid marketing tone.
- Start each doc with a single `# Title` line.
- Use `##` sections for scanability.
- Prefer short paragraphs and bullet lists.

## Commands and Paths
- Wrap commands, env vars, identifiers, and paths in backticks.
- For Windows commands, prefer PowerShell examples.
- If a command has side effects, state them explicitly.

## Linking
- Use repo-relative paths (example: `docs/TESTING.md`).
- Do not use absolute filesystem paths in docs unless required for an OS setting.
- If you add a new doc, add it to `docs/INDEX.md` in the Quick Navigation list.

## Evidence and Artifacts
- If a workflow produces artifacts, list them under an "Expected Artifacts" section.
- For benchmarks, document where evidence is written and how it is verified.

## Change Discipline
- Update docs in the same change as code behavior changes.
- Run `python scripts/docs_check.py` before pushing.

