---
description: Paid full workflow for R1/R2/R3 plans with one fixed review roster.
argument-hint: "<absolute-or-repo-relative-plan.md>"
---

# `/fwp` — unified paid full workflow

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
| R1 | `fuse.py --mode paid` |
| R2 | `fuse.py --mode paid` |
| R3 | `fuse.py --mode paid` |

Risk controls the questions and standing GO, never the model roster.

## Stage 1 — `plan-ceo-review`

Invoke `plan-ceo-review`. R1/R2 questions are agent-resolved from repository and
operator truth. For R3, ask the operator only product/risk/irreversible questions
that materially change the result. KILL/DEFER ends the workflow.

## Stage 2 — unified audit

Run from the plan repository root:

`D:/APPS/WatchF/.venv/Scripts/python.exe D:/APPS/_shared/audit/fuse.py --mode paid --synthesizer <claude|gpt> "@<plan>"`

Use `gpt` in Codex and `claude` in Claude Code only as final-judge provenance.
The runner always launches the same fixed non-OpenRouter panel:

- ChatGPT CDP: the strongest available ChatGPT tier, with a single verified
  pre-submit fallback. Measured 2026-09-01: **`Pro` is a MODEL beside GPT-5.6
  Sol, not an effort of Sol**, and effort is a four-position slider whose top is
  Extra High. So this reads: model `Pro` first, and on verified pre-submit
  failure model `GPT-5.6 Sol` at Extra High. Never claim a model or an effort
  that was not read back from the UI.
- Antigravity CLI: `gemini-3.7-flash-high` in read-only plan+sandbox mode; failure falls
  back inside the same logical lane to Gemini CDP pinned to Gemini 3.7 Flash.
- Perplexity CDP: GLM 5.3, Kimi 3, Grok 4.6, Sonnet 5, GPT Terra.

Claude CLI, Codex CLI, standalone GLM CLI, and nested CLI tournament synthesis
are forbidden in this workflow. Free versus paid changes only the OpenRouter
basket. Never bypass or cap lanes.

**Supply repository context when the repo is connector-exposed.** `fuse.py`
accepts `--github-repo` and `--repo-label`, and both default to `None`, so a
plan otherwise travels as pasted composer text and is silently truncated on a
large plan — measured on a 37,626-character plan, where one lane reported a
section that "cuts off" and two of five picker models never answered. Pass them
when the plan commit is **pushed** and the repo is one the operator connected
(Tsignal, TsignalLAB, WatchF, TSU). Connector exposure is a per-repo operator
decision; `apps-shared` is not on that list, so it still travels inline.

A lane that skipped its primary attempt must say why. If the Antigravity lane
reports only a Gemini CDP error, check whether `agy` was skipped for exceeding
the argv guard — that reason belongs in the failed-lane artifact.

Read `synthesis_prompt.md`, perform the final judge step, apply consensus P1/P2
and unique valid findings inside frozen boundaries, and record every failed lane.

## Stage 3 — `plan-eng-review`, and stamp every slice

Invoke `plan-eng-review`; resolve engineering questions from repo/graph/runtime
truth and write ownership, dependency order, failures, tests, rollback, and slices.
Stop only for a genuine scope expansion or a safety boundary requiring new authority.

**Every slice leaves this stage carrying a `stamp v2` block.** The stamp is the
only channel between this workflow and the executors; an unstamped slice is
refused downstream on R2/R3. Write it directly under the slice heading, inside a
plain fence:

```
### Slice S3 — cctv admission routing
lane: chatgpt_cdp          # local | chatgpt_cdp | coderpx (alias: ppl) | glm | qwen | cursor
executor: A                # A | G — which local runtime runs /fwa and verifies
review: chatgpt_cdp+coderpx # chatgpt_cdp | coderpx | chatgpt_cdp+coderpx | cross
model: GLM 5.3             # optional, only for lane: coderpx
mode: file                 # file | patch (patch above PATCH_SIZE_GATE_BYTES)
reason: concurrency + Conductor lease semantics
files: tsignal/services/cctv_feed_supervisor.py
```

Route by difficulty, not by convenience. `chatgpt_cdp` for concurrency,
lease/CAS lifecycle, restart-adoption, R3 order-path work, and any slice whose
failure branch a real test must drive; `coderpx` for ordinary bounded slices,
plans, reviews and grills; `local` when the change is small and the executor
already holds the context. `review:` must never name the lane and model that
will produce the diff.

Stage 3 is not finished until this exits 0:

`python D:/APPS/_shared/dispatch/dispatch.py plan "<plan>" --executor A --worktree "<abs .claude/worktrees path>" --dry-run`

It validates every stamp, refuses two slices that name the same file, and emits
the lane surface without spending quota. Fix the plan until it passes.

Full contract, defaults and refusals: `D:/APPS/_shared/coderpx/DISPATCHERS.md`.

## Stage 4 — standing implementation gate

- R1 continues automatically.
- R2/R3 requires one operator GO unless this invocation already carries a valid
  standing GO for the exact scope. It covers implementation, in-scope fixes,
  exact-head review, PR, CI, merge, and checkout sync.

It never covers broker submit/modify/cancel, real-money/Combine arming,
production deploy, destructive action, or scope expansion.

## Stage 5 — implementation, dispatched rather than typed

**You do not type the implementation.** Hand each approved slice to the
executor its stamp names, in dependency order:

`python D:/APPS/_shared/dispatch/dispatch.py plan "<plan>" --executor A --worktree "<abs .claude/worktrees path>"`

The dispatcher honours each stamp, walks the outward chain when a lane fails,
caps rounds at two per slice, and records a receipt per slice. Executor `A` is
Antigravity, `G` is Codex; fall to `G` only when `A` is unavailable.

Your job in this stage is to **verify**, not to produce: read the actual
`git diff` and run the slice's real test command. A narrative claim that a
change was made is not a change, and a green run that never executed the
intended path is not evidence.

Keep it in-session only when one of these holds, and say which in one line:
the change is under ~20 lines and the file is already in context; it spans more
files than a packet can honestly describe; or two outward rounds went red. Any
in-session slice is recorded in the ledger with dispatcher `C`.

Conductor holds `host:heavy` at capacity one, so let the Stage 2 lease go
before dispatching here. Preserve dirty-tree and repo ownership boundaries, and
keep the plan readback current. Do not stop merely because code has been written.

## Stage 6 — `review`, outward

Review runs on the lane the slice's `review:` stamp names, against the actual
diff at the exact head. **It never runs on the runtime or the model that
produced the diff**, and for R2/R3 it does not run in-session at all — grading
your own work is the failure this stage exists to prevent.

The local `review` skill is the fallback for R0/R1 `cross` when no second
runtime is available, and never for a diff you authored.

Fix every in-scope ship blocker, rerun validation, publish the corrected head,
and review again. A stale or unavailable review is not PASS. A lane that will
not answer after its two rounds is walked down the chain, not retried.

## Stage 7 — land and report

Complete branch -> validation -> commit -> draft PR -> Ready once -> CI -> merge
-> fast-forward operator checkout. Run `plan_context_updater.py` and report risk,
lane evidence, amendments, tests/exit codes, review, exact SHAs/PRs, and remaining gate.

## Invariants

- `/fwf` and `/fwp` are the only public full workflows.
- `fuse.py` is the only Stage 2 runner for R1/R2/R3.
- The fixed non-OpenRouter roster is client/risk invariant.
- No preset, compatibility route, CLI frontier lane, or silent fallback exists.
- Every slice leaves Stage 3 stamped, and Stage 3 is not done until
  `dispatch.py plan … --dry-run` exits 0.
- Implementation is dispatched, not typed. The in-session exception is narrow,
  must be stated in one line, and is recorded in the ledger as dispatcher `C`.
- Review never runs on the runtime or the model that produced the diff.
- Two rounds per slice. A lane that will not answer is walked down the chain,
  never retried a third time.
- An identity that was not read back is not an identity. `verified_model` and
  `verified_effort` come from the provider's UI, never from the request.
- The report ends with the ownership ledger, generated by `dispatch.py ledger`
  rather than typed.
