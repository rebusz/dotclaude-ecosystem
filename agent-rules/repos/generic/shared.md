# D:/APPS Repo Local Rules

## Scope

- This repo belongs to the local `D:/APPS` ecosystem. Global Claude/Codex behavior comes from the user-level files; this repo file only adds local contracts.
- Before editing, read existing root instructions, active plans, and the nearest design docs for the touched area.
- If the repo has `IDEA_BOX.md`, use it when the user asks "what next" or raises a backlog idea.

## Runtime And Ports

- Before starting, moving, or documenting a local server, read `D:/APPS/_shared/PORTS.md`.
- Do not let dev servers silently auto-select another app's port. If a canonical port is occupied, fail loudly and report the owner.
- Do not start, stop, kill, or restart long-running app/device processes unless the task requires it or the user explicitly asks.

## Dirty Tree And Artifacts

- Never revert unrelated user changes.
- Stage only files intentionally changed for the current task.
- Do not commit local secrets, `.env` files, logs, fixture dumps, generated caches, large media, or machine-local tool state.

## Side-Effect Boundaries

- No live-money, production deploy, paid API fallback, destructive data change, hardware/device control, or external write without explicit approval.
- For hardware, mobile, sensor, map, or physical-world workflows, prefer offline fixtures and dry-run validation before real-device smokes.
- LLM/agent outputs are advisory unless a repo-specific plan explicitly grants a write/action path with validation and rollback.

## Validation

- Use repo-native validation commands. If unknown, inspect `package.json`, `pyproject.toml`, Gradle files, Makefiles, or existing docs first.
- For small docs-only changes, use `git diff --check` as the minimum validation.
- For code changes, run targeted tests for the touched seam and state any broader validation not run.
