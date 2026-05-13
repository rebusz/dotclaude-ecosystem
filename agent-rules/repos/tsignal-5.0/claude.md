# Tsignal Claude Overlay

## Entry Points

- `python tsignal_bot.py` starts the main app; use `--headless` for no GUI.
- `python -m pytest` is the reliable test entrypoint.

## Code Conventions

- Prefer editing existing modules over adding new files.
- Avoid premature abstractions; three similar lines are better than a speculative helper.
- Use `__slots__` on hot-path dataclasses such as `Bar` and `TickData`.
- Alpha pattern: `class XxxEngine` with `evaluate(bars, context) -> dict`.
- Config belongs in `config.py`; avoid scattered magic numbers.
- Use Qt signals/slots for cross-thread coordination and `threading.Lock` for shared state.
- Never commit `.env`, credentials, tokens, or INFO-level secrets.

## Reference Files

- `.claude/refs/stable-modules.md` for R3-gated modules.
- `.claude/refs/testing.md` for test guidance.
- `.claude/refs/current-state.md` for current state.
- `ARCHITECTURE.md` for detailed design.
- `LESSONS_LEARNED.md` for compound engineering knowledge.
- `IDEA_BOX.md` when asked "what next" or about development direction.

## Compound Loop

- After non-trivial implementation, run Verify -> Cycle-Review -> Compound.
- `/verify` proves the touched seam works before claiming completion.
- `/cycle-review` scans frozen boundaries, R-class compliance, test evidence, and structure.
- `/compound` captures non-obvious learnings.

## Plan Supersession

- Plans in `design/plans/` must carry a `## Status` header near the top.
- Valid forms: `## Status: Active`, `## Status: Superseded-by: design/plans/<filename>.md`, or `## Status: Abandoned (reason: <one-line reason>)`.
- Executor and audit work must check status before acting.
- Superseded or abandoned plans must not be executed unless the operator explicitly forces it.

## Git

- Main branch: `main`.
- Commit style: `fix: lowercase description`.
- Run targeted validation before commit.
