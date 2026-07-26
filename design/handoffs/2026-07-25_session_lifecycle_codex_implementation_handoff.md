# Handoff to Codex - implement the session lifecycle core

**Written** 2026-07-25 | **For** Codex CLI (`gpt-5.6-sol`) | **Risk class** R1
**Plan** `design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md`
**Repo** `D:/dotclaude/dotclaude-ecosystem`, `main`, clean, pushed

You already reviewed this plan. Stage 3b in it is your own 16 findings, folded. Ten were
applied, one of yours was refuted with evidence, five are recorded as operator decisions. Read
Stage 3b first - it is the shortest path to what changed and why.

## Read this before you start

**Two open items need the operator, not you.** Both are in `**UNRESOLVED DECISIONS:**` at the
bottom of the plan, and both are yours:

1. **C11** - a `SessionStart` hook cannot compel the model to write the scratch file.
   `additionalContext` is a reminder the harness does not enforce, so "declared intent at
   session start" is best-effort by construction. Do not invent a mechanism that pretends
   otherwise, and do not quietly build as if the write is guaranteed.
2. **C14** - headline goal 2 promises claims are confronted "before anything is called done",
   but `/curator` is optional and `SessionEnd` alone is coarse. The plan does not enforce its
   own headline.

Build everything that does not depend on these. If you reach a decision point that turns on
either, stop and ask rather than choosing for the operator.

## Settled - do not re-litigate

- **D1 through D7**, from the operator's `/grill-me` interview.
- **The scope cut.** Drift check, `/sweep` and adversarial personas left for their own plans.
  Pressure to fold them back in is failure mode 6 of the plan's own pre-mortem.
- **The three Phase 0 collision verdicts.** TruthDeck owns evidence, Conductor owns cross-repo
  coordination, the workflow contract forbids a third command. **Do not propose an event bus or
  any channel between sessions.**
- **The D1 module merge.** You argued against it (C10) and the argument is recorded in the
  plan. It was the operator's call, made with your tradeoff visible. Build the merged shape.
- **The nine invariants and the explicit non-goals** in `## Frozen product contract`.

## What to build

Five modules and one skill. All advisory, no hook may return `decision: "block"` or
`continue: false`, no model call inside a hook process.

| Slice | Owns | Depends on |
|---|---|---|
| S1 | `session_state.py` (registry resolution, read/validate, atomic write), registry template, floor measurement | - |
| S2 | `session_router.py` (SessionStart, 5 sources), full-run measurement, budget assertions | S1 |
| S3 | `session_lifecycle.py` (SessionEnd verdict), `state_reaper.py` | S1 |
| S4 | `skills/curator/SKILL.md`, `curator_claims.py` | S1, S3 |
| S5 | review, landing, hook enablement | S2, S3, S4 |

**Order:** S1 alone first - it is a hard dependency for everything and produces the floor
number S2 needs. Then S2 and S3+S4 can run as two lanes. Then S5.

**Parallelism:** every lane writes into `scripts/` and `scripts/tests/`. Land S1 before either
lane starts so nothing touches `session_state.py` concurrently.

## Task list

`## Implementation Tasks` in the plan carries T1 through T14 with files and verification for
each. T9 through T14 come from your own review and **supersede parts of T1, T4, T5 and T7** -
read those pairs together, and where they conflict, Stage 3b wins.

The five things most likely to be built wrong, all of which you caught:

- `fork` creates a fresh scratch file. It cannot read the parent's - no parent session id
  exists. Never guess by recency.
- `surfaced_at` and `consumed_at` are different events. Only `/curator` writes `consumed_at`,
  and only `consumed_at` makes a verdict reapable.
- The verdict is attributed to the session against `start_sha`. An empty attributable set is
  `NO-OP`, never `ARCHIVE-OK`.
- The reap's cost is **inside** the SessionStart budget. Hook output is processed on process
  exit, so nothing done before exiting is off the hot path.
- `/curator` reads no `settings.json`. Hooks resolve from seven sources; point at `/hooks`.

## Verification

```powershell
python -m pytest -q scripts/tests/test_session_state.py scripts/tests/test_session_router.py scripts/tests/test_session_lifecycle.py scripts/tests/test_state_reaper.py scripts/tests/test_curator_claims.py
python -m pytest -q scripts/tests
python -m ruff check <new and touched files>
python -m compileall -q <new modules>
git diff --check
```

A test counts as passed only when the exit code is zero **and** the expected target actually
ran. Baseline before this work: `191 passed, 2 subtests passed`.

**Any claim about hook behaviour gets checked against
[the hooks reference](https://code.claude.com/docs/en/hooks) before code rests on it.** That
rule exists because this plan has been burned three times by designs built on unverified event
behaviour - twice by the author, once by its own engineering review. Your C1 through C9 are the
third round. Do not make it four.

## Landing

R1, but the hook surface is ecosystem-wide, so the plan adopts R2-grade rollback discipline.

- Branch, do not commit to `main`.
- Draft PR (`gh pr create --draft`); batch pushes; `gh pr ready` exactly once when done.
- Exact-head review gate before merge.
- Squash-merge, then fast-forward the operator's `D:/dotclaude/dotclaude-ecosystem` checkout.
- **Enable the hooks in `settings.json` as the very last step**, one event at a time, verifying
  after each that a session still starts, compacts and ends cleanly.
- Kill switch: remove the two hook entries. That is sufficient on its own.

Standing GO from the audited plan covers implementation, in-scope fixes, review, CI and merge.
Ask again only for scope expansion, an unresolved failure, or anything touching live money,
Combine, broker submit, or a destructive action. None of those are in this plan.

## Invoking the lane

The runner had two defects, both fixed on 2026-07-25 and landed with tests in
`D:/APPS/_shared`. If you drive it yourself:

```bash
"D:/APPS/WatchF/.venv/Scripts/python.exe" "D:/APPS/_shared/audit/auditcodex_cli.py" \
  --prompt-file <prompt> --repo "D:/dotclaude/dotclaude-ecosystem" \
  --timeout-s 900 --out <artifact>
```

Two things that will waste your time if you rediscover them the hard way:
`--ignore-user-config` discards `[windows] sandbox = "elevated"` and the fallback sandbox never
completes - the runner now restores that one key explicitly. And a prompt passed in argv is
truncated at its first newline, silently, with exit 0 - the runner now sends it on stdin. Both
are documented at `D:/APPS/_shared/design/audits/2026-07-25_codex_cli_lane_sandbox_hang.md`.
