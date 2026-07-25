# Handoff - Session Lifecycle Core, 2026-07-25

Written because the originating session filled its context. Everything below is committed
and pushed; nothing is in flight.

## Read this first: a correction

The originating session twice asserted that **`auditf.py` truncates plan input at 30 KB**.
**That is false.** It was inferred from the gstack `plan-ceo-review` contract text, not from
the runner, and it was written into a committed plan before being checked.

Verified: `auditf.py` reads the plan with a plain `read_text()`; `grep` for truncation across
all of `_shared/audit/*.py` returns only `response_quality.py`, which *detects* truncated model
answers - the opposite concern. **There is nothing to fix in `auditf.py`.**

The real problem is downstream and is described under "Open problem: CDP lane input fidelity".
Do not go editing the runner.

## State

| | |
|---|---|
| Repo | `D:/dotclaude/dotclaude-ecosystem`, `main`, clean, pushed |
| Landed | `ad12cf2` hotfix (PR #50, squash-merged, **installed and smoke-tested**) |
| Core plan | `design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md` |
| Split plans | `..._session_drift_check_r1.md`, `..._sweep_abandoned_work_r1.md`, `..._adversarial_plan_personas_r1.md` |
| Audit artifacts | `design/audits/2026-07-25_2026-07-25_session_lifecycle_and_hook_hardening_r1/` |

The hotfix is **live**: `plan_keyword_detector.py` and `answer_footer.py` in
`~/.claude/scripts` are byte-identical to the merged versions. Smoke-tested both directions:
a pasted document containing a trigger emits 0 bytes; the operator's own "co dalej?" still
emits 12,490.

## Where `/fwp` stopped

Stages 1 and 2 are complete and recorded inside the plan. **Stage 3 (`plan-eng-review`) has
not run.** Stages 4, 5, 6, 7 follow it.

- **Stage 1, CEO review**, mode `HOLD_SCOPE`: 11 findings, one critical (a reaper that would
  have deleted a live session's state). All resolved in scope.
- **Stage 2, paid CDP panel**: 9 lanes, 8 returned. The GPT Pro frontier lane failed with
  `captcha_detected` and **the captcha was not bypassed** - it will not be. 10 findings
  applied, 11 discarded with reasons.
- **Stage 2b, CLI frontier lanes**: operator-directed retry after the CDP frontier failure.
  Kimi K3 returned and produced the best findings of the whole review. Codex did not (below).

## What must not be re-litigated

- **D1 through D7**, recorded in the plan, came from a `/grill-me` interview with the operator
  on 2026-07-25. They are settled.
- **The scope cut** was an operator decision the same day, after the Kimi lane argued the plan
  was three features in one coat. Retained: session state, registry, SessionStart router,
  SessionEnd verdict, reaper, `/curator`. Split out: drift check, `/sweep`, personas.
- **The three collisions** in Phase 0 (TruthDeck owns evidence, Conductor owns cross-repo
  coordination, the workflow contract forbids a third command) are frozen boundaries. In
  particular: **do not propose an event bus or a channel between sessions.** That is
  Conductor R2's scope and was already dropped once.

## Two mechanism errors that reshaped the plan

Both found by the Kimi K3 CLI lane, both independently confirmed against the live hooks
reference. They matter because two prior review passes missed them: everyone checked budgets,
staleness, and schemas, and nobody checked whether the event could carry the payload.

1. **`PreCompact` has no `additionalContext`.** Its only outputs are `decision: "block"`,
   `reason`, and the universal fields. The plan had built a slice on it and priced a
   1,500-character re-injection through a channel that does not exist. Compaction survival
   now happens at `SessionStart` with `source: compact`, which does have the field.
2. **`SessionEnd` output is ignored by the harness**, exit code and JSON alike. The
   three-state verdict would have been invisible at the only moment it matters. The verdict is
   now persisted and surfaced by the next `SessionStart` in that repository, or on demand
   through `/curator`.

If you touch hook wiring, **check the event's output surface in the hooks reference before
designing anything on it.** That is the lesson, not the two specific bugs.

## Open

### 1. Codex CLI lane never returned

Launched as a background task alongside Kimi. Never wrote its output file; its runner log is
0 bytes. It was given a 900 s timeout and produced nothing well past it. Its shell may still
be alive in the originating session and will die with it.

Output would land at:
`design/audits/2026-07-25_2026-07-25_session_lifecycle_and_hook_hardening_r1/22_codex_cli_gpt.md`

Re-run:

```bash
"D:/APPS/WatchF/.venv/Scripts/python.exe" "D:/APPS/_shared/audit/auditcodex_cli.py" \
  --prompt-file <prompt> --repo "D:/dotclaude/dotclaude-ecosystem" \
  --timeout-s 900 --out "<audit-dir>/22_codex_cli_gpt.md"
```

The lane health-checks clean (`--health-check` returns `healthy: true`), so this is a runtime
hang rather than a configuration problem. **Decide:** re-run it, or take Stage 3 on the
strength of the Kimi lane alone. The plan's `UNRESOLVED DECISIONS` records this.

### 2. Open problem: CDP lane input fidelity

Two of three Perplexity CDP lanes audited a mutilated plan and said so - Sonar 2 opened with
"Given the heavy compaction", Kimi K2.6 said "roughly 60-70% of the body was compacted away"
and quoted a sentence cut mid-word. Their findings were dominated by absence claims about
sections that are present, and all of it was discarded.

**The harness is not at fault** (see the correction at the top). `auditf.py` sends the whole
plan. The degradation happens in the Perplexity web product the CDP lanes drive, which appears
to compact long inputs on its own. The exact downstream mechanism is **not pinned down** - only
our harness has been ruled out.

Why it matters: a plan that carries its own review records grows past whatever that threshold
is. This plan did. **Every future `/fwf` and `/fwp` panel on a mature plan will hit the same
wall**, and the failure is silent - the lane returns confident findings about absent sections
rather than an error.

The available lever is **lane selection**, not runner surgery: CLI lanes given `--repo` read
the file directly and showed none of this. Possible shapes, none decided:

- prefer CLI lanes over CDP lanes once plan size crosses a measured threshold;
- have `auditf.py` measure and record input size per lane so degradation is visible;
- have each lane self-report whether it believes it received the whole input, and fail the
  lane rather than accept absence claims from a lane that did not.

The third is the cheapest and closes the silent-failure property directly.

### 3. Recorded debt, not fixed

The hotfix smoke test reported the operator's own two-word "co dalej?" emitting **12,490
bytes**. That was presented as proof the fix worked. It also shows the fix addressed
*provenance* and not *volume*: trivial operator text still triggers an injection of the same
order as the 13.5 KB incident this work exists to react to. Belongs to
`plan_keyword_detector.py` and `steer_context.py`, not to the lifecycle plan. Recorded as K10
in Stage 2b.

### 4. `auditkimi_cli.py` crashes on non-ASCII output

It writes its `--out` file, then crashes on `print(run.text)` with `UnicodeEncodeError` under
cp1252. Any review containing a non-ASCII character breaks that lane's stdout echo on Windows.
The review file itself is intact, so this is cosmetic unless a caller reads stdout. Evidence
committed as `.kimi_run.log`.

## Next action

Run `/fwp` Stage 3 (`plan-eng-review`) against
`design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md`, after deciding the Codex
lane question above. Stage 3 owns the implementation slices, dependency order, and rollback -
the CEO review deliberately did not amend the slice list beyond the structural cut.
