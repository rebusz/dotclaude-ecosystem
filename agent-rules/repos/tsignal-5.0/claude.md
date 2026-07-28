# Tsignal Claude Overlay

## Judgment Defaults

- Write code that reads like the surrounding code — match its comment density,
  naming, and idiom. Prefer editing existing modules over adding files; three
  similar lines beat a speculative helper.
- `__slots__` on hot-path dataclasses (`Bar`, `TickData`). Qt signals/slots for
  cross-thread coordination, `threading.Lock` for shared state.
- Alpha engines follow `class XxxEngine` with `evaluate(bars, context) -> dict`.
  Config belongs in `config.py`, not scattered magic numbers.

## Environment Gotchas

These are the things the repo cannot tell you by itself.

- **Heavy assets are junctioned out.** `data/`, `AI/`, and
  `scratch/bench/models/` are NTFS junctions into `D:\APPS\Tsignal_ASSETS`
  (~78 GB: the live SQLite DB, llama.cpp binaries, GGUF models). Never `git add`
  them. A fresh clone needs the junctions recreated or `TSIGNAL_APPS_ROOT` set —
  see `config/brokers.py:_resolve_apps_root`.
- **venv is Python 3.12** (`.venv\Scripts\python.exe`); anything pinning
  `py -3.11` fails on this machine.
- **`tsignal_bot.py` pre-imports pandas + dateutil BEFORE PySide6** to dodge a
  shiboken6 6.11.1 crash in the `six.moves` lazy importer. Do not reorder them.
- **`ib_async>=2.0.0`** is pinned in requirements.txt.
- **The live bot runs from the MAIN checkout**, never your worktree — a fix is
  not live until it lands on `main` and the process restarts.
- **The suite is order-randomized and timing-flaky** (`pytest-randomly`): a
  single red test is a re-run before it is a regression. `python -m pytest` is
  the entry point; `python tsignal_bot.py --headless` starts the backend.

## Load On Demand

- `tsignal-*` skills own the deep procedures — order-path change control,
  restart/readback and stranded state, custody/exit integrity, IBKR ports and
  client ids, runtime config readback, build/validate, surge failure
  archaeology, signal-verifier cost control, live-boundary/advisory inputs.
  Invoke them instead of rediscovering their contents.
- `.claude/refs/stable-modules.md` (R3-gated modules), `.claude/refs/testing.md`,
  `.claude/refs/current-state.md`, `ARCHITECTURE.md`, `LESSONS_LEARNED.md`.
  `IDEA_BOX.md` when asked "what next".
- Plans in `design/plans/` carry `## Status: Active` /
  `## Status: Superseded-by: <path>` / `## Status: Abandoned (reason: ...)`.
  Check status before executing; superseded or abandoned plans run only on
  explicit operator force.
- After non-trivial implementation: Verify -> Cycle-Review -> Compound
  (`/verify` proves the touched seam, `/cycle-review` checks boundaries and
  evidence, `/compound` captures non-obvious learnings).

## Git

- Main branch `main`; commit style `fix: lowercase description`; targeted
  validation before commit.
