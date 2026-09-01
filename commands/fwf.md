---
description: Free full workflow for R1/R2/R3 plans with one fixed review roster.
argument-hint: "<absolute-or-repo-relative-plan.md>"
---

# `/fwf` — unified free full workflow

Run the complete lifecycle for the single plan path in `$ARGUMENTS`. This is the
same workflow in Claude Code and Codex and for every accepted risk class.

## Parse and preflight

1. Accept exactly one plan path. Reject aliases, presets, `close`, and lane-bypass flags.
2. Resolve the plan/repository and run `plan_context_loader.py` before other task action.
3. Read or assign the explicit R1/R2/R3 risk class; R0 does not need this workflow.
4. Read every invoked skill completely and preserve dirty worktree boundaries.

## Fixed routing

| Grade | Stage 2 |
|---|---|
| R1 | `fuse.py --mode free` |
| R2 | `fuse.py --mode free` |
| R3 | `fuse.py --mode free` |

Risk controls the questions and standing GO, never the model roster.

## Stage 1 — `plan-ceo-review`

Invoke `plan-ceo-review`. R1/R2 questions are agent-resolved from repository and
operator truth. For R3, ask the operator only product/risk/irreversible questions
that materially change the result. KILL/DEFER ends the workflow.

## Stage 2 — unified audit

Run from the plan repository root:

`D:/APPS/WatchF/.venv/Scripts/python.exe D:/APPS/_shared/audit/fuse.py --mode free --synthesizer <claude|gpt> "@<plan>"`

Use `gpt` in Codex and `claude` in Claude Code only as final-judge provenance.
The runner always launches the same fixed non-OpenRouter panel:

- ChatGPT CDP: only GPT-5.6 Sol with Pro effort; a single `xhigh`/Extra High
  effort retry on the same model is allowed only after verified pre-submit failure.
- Antigravity CLI: `gemini-3.7-flash-high` in read-only plan+sandbox mode; failure falls
  back inside the same logical lane to Gemini CDP pinned to Gemini 3.7 Flash.
- Perplexity CDP: GLM 5.3, Kimi 3, Grok 4.6, Sonnet 5, GPT Terra.

Claude CLI, Codex CLI, standalone GLM CLI, and nested CLI tournament synthesis
are forbidden in this workflow. Free versus paid changes only the OpenRouter
basket. Supply repository context when supported. Never bypass or cap lanes.

Read `synthesis_prompt.md`, perform the final judge step, apply consensus P1/P2
and unique valid findings inside frozen boundaries, and record every failed lane.

## Stage 3 — `plan-eng-review`

Invoke `plan-eng-review`; resolve engineering questions from repo/graph/runtime
truth and write ownership, dependency order, failures, tests, rollback, and slices.
Stop only for a genuine scope expansion or a safety boundary requiring new authority.

## Stage 4 — standing implementation gate

- R1 continues automatically.
- R2/R3 requires one operator GO unless this invocation already carries a valid
  standing GO for the exact scope. It covers implementation, in-scope fixes,
  exact-head review, PR, CI, merge, and checkout sync.

It never covers broker submit/modify/cancel, real-money/Combine arming,
production deploy, destructive action, or scope expansion.

## Stage 5 — implementation

Implement every approved plan slice in dependency order. Preserve dirty-tree and
repo ownership boundaries, validate each slice proportionately, and keep the
plan/readback current. Do not stop merely because code has been written.

## Stage 6 — `review`

Invoke `review` against the actual diff and exact head according to the review
stamp. Fix every in-scope ship blocker, rerun validation, and review the corrected
head. A stale/unavailable review is not PASS.

## Stage 7 — land and report

Complete branch -> validation -> commit -> draft PR -> Ready once -> CI -> merge
-> fast-forward operator checkout. Run `plan_context_updater.py` and report risk,
lane evidence, amendments, tests/exit codes, review, exact SHAs/PRs, and remaining gate.

## Invariants

- `/fwf` and `/fwp` are the only public full workflows.
- `fuse.py` is the only Stage 2 runner for R1/R2/R3.
- The fixed non-OpenRouter roster is client/risk invariant.
- No preset, compatibility route, CLI frontier lane, or silent fallback exists.
