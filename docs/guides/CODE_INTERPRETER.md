# Code Interpreter

Chintu's `code_interpreter` executes Python safely for math/logic/data tasks.

## What Changed

- Iterative self-repair: failed scripts are retried with error-aware fixes.
- Structured run metadata: attempts, script artifact path, and errors are returned.
- Safer execution path: shell execution is disabled in `safe_exec`.
- Learning on failure:
  - Records a learning gap.
  - Optionally captures web-learning context.
  - Optionally drafts a skill proposal for future reuse (approval-gated).

## Key Config Flags

- `CODE_INTERPRETER_MAX_ATTEMPTS` (default `3`)
- `CODE_INTERPRETER_TIMEOUT_SECONDS` (default `30`)
- `LEARNING_AUTO_WEB_ON_GAP` (default `true`)
- `LEARNING_AUTO_PROPOSE_SKILL_ON_GAP` (default `true`)

## Example Requests

- "Calculate the 100th Fibonacci number."
- "What day was January 1, 2010?"
- "Compare these numbers and return median + standard deviation."

