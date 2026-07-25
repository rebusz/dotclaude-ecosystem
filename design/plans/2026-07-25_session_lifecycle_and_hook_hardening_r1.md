---
title: Session Lifecycle Router, Curator, and Hook Hardening
date: 2026-07-25
status: draft
status_detail: grilled-and-agreed-awaiting-fwp-review
risk: R1
phase: plan
repos: [dotclaude-ecosystem]
tags: [agent-tooling, hooks, session-lifecycle, handoff, evidence, personas]
related:
  - design/plans/2026-07-22_truthdeck_agent_evidence_control_plane_r1.md
  - design/plans/2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md
  - design/plans/2026-07-21_global_fwf_fwp_contract_reset.md
  - design/plans/2026-06-27_global_agent_workflow_os.md
---

# Session Lifecycle Router, Curator, and Hook Hardening

## Executive decision

Give a Claude Code session a **declared intent that survives compaction**, and give its
close a **verified verdict instead of a self-report**.

Two questions are currently unanswered by any tool in the ecosystem:

> What is this session actually trying to do, and are we still doing it?

> The agent says it fixed X. Did it?

TruthDeck answers what is true about *repository and runtime state*. It does not answer
either of the above. `/fwf` and `/fwp` own the engineering lifecycle of a *plan*, not the
lifecycle of a *session*. This plan fills that gap with four hooks, one session-scoped
scratch file, and two skills, all advisory.

**Plan-writing authorization:** granted by the operator on 2026-07-25 after a `/grill-me`
interview (seven decisions recorded below).
**Implementation authorization:** not implied. The operator selected `/fwp` for review.

## Consequence, downside, reversibility

- **Proposed action:** harden one existing hook against injected triggers; add SessionStart,
  PostToolBatch, PreCompact, and SessionEnd hooks; add a per-session scratch file; add
  `/curator` and `/sweep`; extend `autoplan` personas; add a repo registry.
- **Plausible downside if wrong:** the hooks run on every session in every repository, so a
  defect degrades all work everywhere, not one project. A noisy drift-check trains the
  operator to ignore it. A wrong curator verdict makes honest handoffs look dishonest.
  The scratch file could be mistaken for a second plan authority.
- **Reversibility:** fully reversible. Remove hook entries from `settings.json`, delete
  `~/.claude/state/session_plan_*`, revert the commits. No application repository, runtime,
  or trading path is touched.
- **Risk grade:** **R1.** No runtime mutation, no persistence contract inside an application
  repository, no broker or order path, no deployment.

**Blast-radius exception.** Although the class is R1, the hook surface is ecosystem-wide.
This plan therefore adopts R2-grade rollback discipline: a single documented kill switch,
an emergency-off path, and a slice order in which every hook is independently removable.

## Phase 0 - restatement and collision verdict

### Goal

1. A session declares its goal, skill chain, persona, and risk class at start, on disk.
2. That declaration survives compaction and is re-injected afterwards.
3. Mid-session, the agent is periodically asked whether the plan still holds, whether a
   second lane should be split off, and whether it is time to hand off.
4. At close, claims made during the session are confronted with repository evidence before
   anything is called done.
5. Abandoned work is discoverable.
6. Plans are audited through explicitly named adversarial personas.

### Collision verdict

`plan_context_loader.py` detects only repositories directly under `D:/APPS`, so it cannot
catalog this repository. This is a known limitation recorded in both TruthDeck plans. A
bounded fallback read of `design/plans/` was used instead. Three collisions were found.

| Proposed item | Collides with | Verdict |
|---|---|---|
| A curator that verifies claims | `2026-07-22_truthdeck_agent_evidence_control_plane_r1.md`, **shipped**. It already owns gate evaluation, fail-closed semantics, and `verify-handoff`. Its pre-mortem names "second source of truth" as failure mode 1 | **Reshape.** `/curator` consumes `truthctl`; it never re-implements a gate or mints a second evidence authority |
| A `Monitor`-based event bus between worktree lanes | `2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md` (draft) owns cross-repo agent coordination. Shipped TruthDeck R1 non-goals include "no always-on daemon, HTTP service, **event bus**" | **Dropped from this plan.** The correct path to lane coordination is running Conductor through `/fwf`, not building a competing bus |
| A `/fwd` design workflow command | `2026-07-21_global_fwf_fwp_contract_reset.md`: "No compatibility aliases, soak/shadow phase, or **third workflow command**" | **Dropped as a command.** The design chain becomes a routing rule inside S1 |

**Verdict: CREATE NEW PLAN, LINK PREDECESSORS.** Do not amend or supersede TruthDeck R1,
Conductor R2, or the workflow contract reset.

`PONYTAIL: NOT USED - no concrete simplification candidate.` The plan is already the
reduced form; three of ten candidate items were removed during the collision check.

>> PHASE 0 COMPLETE

## Why now

On 2026-07-25 the operator pasted a public Reddit thread into a session as reference
material. Two things fired that the operator did not ask for:

1. `plan_keyword_detector.py` matched `\bdrift\b` inside a quoted third-party comment
   ("tracking structural drift over long sessions") and injected a full steering brief,
   measured at **13.5 KB**, into a turn about something else.
2. The literal token `ultracode` appeared inside another quoted comment, and the harness
   reported the turn as opted into multi-agent orchestration.

Neither instruction came from the operator. Both came from pasted third-party text. The
detector reads `data["prompt"]` and applies its regexes to the whole string with no
distinction between what the operator wrote and what the operator quoted. Any pasted log,
issue body, audit report, or model transcript can therefore trigger a mode change or a
context injection. This is the first slice.

The remaining slices address a second, slower failure: session intent lives only in the
context window, so compaction destroys it, and session outcome is a self-report that
nothing checks.

## Current-state evidence

Baseline at plan creation:

- `dotclaude-ecosystem` `main == origin/main`, worktree clean.
- `settings.json` registers **8 hook entries** across 3 events: `PostToolUse` (4, two
  duplicate matcher pairs that could be one `Write|Edit` matcher each), `Stop` (3),
  `UserPromptSubmit` (1). **Zero** hooks on `SessionStart`, `SessionEnd`, `PreCompact`,
  `PostCompact`, `PostToolBatch`, `SubagentStop`, `StopFailure`, or `PreToolUse`.
- Claude Code supports 31 hook events; the surface used is 3.
- `~/.claude/state/` holds **1953 files, of which 1944 are `turn_counter_<session_id>`**
  written by `answer_footer.py`. Nothing reaps them.
- `answer_footer.py` `_PRICING` contains keys up to `claude-opus-4-7`. The active model is
  `claude-opus-5`, which misses the table and silently falls back to
  `_DEFAULT_PRICING = (3.0, 15.0, 3.75, 0.30)`, the Sonnet rate. Reported session cost is
  understated roughly fivefold on every turn.
- **12 of 36 scripts in `~/.claude/scripts` are absent from `dotclaude-ecosystem/scripts`**,
  including three this plan modifies: `answer_footer.py`, `repo_hygiene_nudge.py`,
  `memory_size_guard.py`, plus `autoplan_review_workflow.js`. Fixes to those files
  currently exist only on one machine and do not survive a reinstall.
- `plan_keyword_detector.py` is tracked and byte-identical between repo and install.
- TruthDeck is installed with CLI and MCP registered on both Claude and Codex.

### Reuse map

| Existing surface | Use here | Must not become |
|---|---|---|
| `truthctl` snapshot/gates/verify-handoff | curator's evidence layer | re-implemented in the curator |
| `plan_context_loader.py`, `steer_context.py` | fact sources for the router | duplicated policy |
| `git_hygiene.py` read paths | `/sweep` repository observation | cleanup authority |
| `_catalog_common.py` | frontmatter parsing for plan scanning | new parser |
| `autoplan_review_workflow.js` `personas` array | persona extension point | new review pipeline |
| `IDEA_BOX.md` + `plan_context_updater --resolved-ideas` | `/sweep` output and loop closure | second backlog |
| `settings.json` hooks | the whole delivery mechanism | model-side convention |

## Frozen product contract

### Invariants

1. **The session plan is scratch, not truth.** `session_plan_<session_id>.json` records
   intent for one session. It never overrides `PLANS.md`, a repository plan, a vision, or a
   TruthDeck fact, and no gate may read it as evidence.
2. **Hooks assemble facts; the model exercises judgment.** A Python hook may collect
   repository state and emit it. It may not decide a session goal, choose a persona, or
   author a chain. Those are model outputs written back to the scratch file.
3. **Advisory only. No hook in this plan may return `decision: "block"` or
   `continue: false`.** This preserves the posture TruthDeck adopted deliberately: observe
   and report, never seize authority over the session.
4. **Verdicts fail closed; actions stay advisory.** The curator marks an unverified claim as
   unverified. It never refuses to write the handoff, and never upgrades an unknown to done.
5. **Triggers must originate with the operator.** Prompt-scanning hooks match only against
   operator-authored text, never quoted, fenced, or pasted content.
6. **Every hook is independently removable.** Deleting one `settings.json` entry degrades
   one capability and breaks nothing else.
7. **Bounded and reaped.** Every file this plan creates has a size bound and a documented
   reaper. No new unbounded directory.
8. **No new public workflow command.** `/fwf` and `/fwp` remain the only two.
9. **No live coupling.** Nothing here reads or writes trading runtime, broker paths, order
   state, or the Tsignal/LAB seam.

### Explicit non-goals

- No event bus, daemon, queue, socket, port, or cross-session channel. That is Conductor.
- No second evidence authority. Gate semantics stay in TruthDeck.
- No third workflow command, and no design workflow with its own risk gate or review stage.
- No automatic archiving of a session, filing of a GitHub issue, commit, push, PR
  transition, merge, branch deletion, or worktree deletion.
- No blocking hook, no forced compaction, no forced handoff.
- No model call inside a hook process. Hooks are deterministic Python.
- No change to `/fwf`, `/fwp`, risk routing, or the standing-GO contract.

## Recorded decisions (from the 2026-07-25 grill)

| # | Decision | Chosen |
|---|---|---|
| D1 | Plan shape | Split: defects as a separate hotfix branch, features as this plan |
| D2 | Where session intent lives | File on disk under `~/.claude/state/`, per session |
| D3 | Hook authority | Advisory plus throttle. Never blocks |
| D4 | Curator scope | TruthDeck gates **plus** claim extraction from the session transcript |
| D5 | Design chain | Routing rule inside the router. No `/fwd` command |
| D6 | `/sweep` output | `IDEA_BOX.md`. GitHub issues only on explicit operator request |
| D7 | Router reach | Repo registry: full run in registered repositories, one line elsewhere |

## Architecture

```text
SessionStart ---> session_router.py (facts only)
                        |
                        | additionalContext + sessionTitle
                        v
                  model writes intent
                        |
                        v
         ~/.claude/state/session_plan_<id>.json
          { goal, chain[], persona, risk, repo,
            start_sha, checkpoints[], claims[] }
                        |
        +---------------+---------------+----------------+
        |               |               |                |
        v               v               v                v
  PostToolBatch     PreCompact       SessionEnd       /curator
  drift check       re-inject        verdict +        truthctl gates
  (throttled,       after compact    reaper           + claim check
   advisory)                                                |
                                                            v
                                                   handoff with every
                                                   claim marked verified
                                                   or unverified

Forbidden edges:
  session_plan --X--> any gate, any authority, any commit message
  hook          --X--> decision:"block" / continue:false
  pasted text   --X--> trigger match
  this plan     --X--> cross-session channel  (that is Conductor)
```

## Implementation slices

Slices are ordered so that each one is independently shippable and independently
removable. S0 is a prerequisite for anything that edits an untracked script.

### S0 - Bring touched scripts under version control

**Files:** `scripts/answer_footer.py`, `scripts/repo_hygiene_nudge.py`,
`scripts/memory_size_guard.py`, `scripts/autoplan_review_workflow.js`,
`install/` manifest updates.

Copy the four untracked files from `~/.claude/scripts` into canonical `scripts/`, verify
byte identity after copy, and add them to the installer manifest. No behavior change.

The remaining eight untracked scripts (`multi_audit_free.py`, `of_*.js`, `tsu_*.py`,
`verify_a1_recall.js`) are **out of scope** and recorded here so their absence is not
mistaken for coverage.

**Gate:** `diff` proves byte identity; installer status reports zero drift.

### S1 - Repo registry and SessionStart router

**Files:** `scripts/session_registry.py`, `scripts/session_router.py`,
`templates/session_registry.json.template`, `scripts/tests/test_session_router.py`.

The registry names repositories that get a full run, each with its plan/vision/idea paths.
It also covers `dotclaude-ecosystem`, which `plan_context_loader.py` cannot detect.

Full run emits, via `additionalContext`:

- repository, branch, HEAD, dirty state, divergence from trunk;
- active plans and open `IDEA_BOX` entries (bounded, reusing existing loaders);
- the most recent unconsumed handoff, if any;
- a proposed skill chain from a routing table;
- an instruction to write `session_plan_<id>.json`.

It also returns `sessionTitle` in the documented `<Repo> <DD MON> [chip] <topic>` shape.
This retires the cross-session renaming duty currently described in global rules, which
exists only because a session cannot rename itself.

Outside the registry: one line with repository and branch, no injection.

The routing table includes the **design chain** (D5): when the repository has a frontend
surface and the request is visual, propose `design-consultation` ->  `design-shotgun` ->
`image-to-code` or `design-html` -> taste overlay -> `design-review`, and hand code to
`/fwf`. It is a suggestion, never a gate.

**Gate:** registered and unregistered repositories both behave as specified; injected
payload stays under budget; title matches the convention; a repository absent from the
registry costs zero injected tokens.

### S2 - Drift check on PostToolBatch

**Files:** `scripts/session_drift.py`, tests.

Throttled by batch count and elapsed context. Reads the scratch file and emits a short
`additionalContext`: the declared goal, what has happened since the last check, and three
questions - is the plan still right, should a second lane be split off, is it time to hand
off. Advisory. Never blocks.

`PostToolBatch` fires after **every** batch of parallel tool calls. In the session that
produced this plan that would have been roughly twelve times. Throttling is a correctness
requirement, not tuning.

**Gate:** measured firing rate over a recorded real session stays within budget; a
disabled or failing check never interrupts a turn.

### S3 - PreCompact and SessionEnd

**Files:** `scripts/session_precompact.py`, `scripts/session_end.py`,
`scripts/state_reaper.py`, tests.

`PreCompact` writes the current scratch file and emits it so the goal survives the
compaction boundary. This is the single highest-value moment for the whole plan: it is the
only point where the system knows in advance that context is about to be destroyed.

`SessionEnd` computes one of three verdicts - `ARCHIVE-OK`, `HANDOFF`, `CHECKPOINT` - from
branch merge state, worktree cleanliness, and unresolved items in the scratch file. It
reports; it never archives.

`state_reaper.py` deletes `turn_counter_*` and `session_plan_*` for sessions older than a
retention window. It runs from `SessionEnd` and is separately invocable. It deletes only
files matching its own owned prefixes.

**Gate:** a forced compaction preserves the goal; the reaper removes the 1944-file backlog
and touches nothing it does not own; verdicts are correct on fixture repositories covering
merged-clean, merged-dirty, and unmerged states.

### S4 - `/curator`

**Files:** `skills/curator/SKILL.md`, `scripts/curator_claims.py`, tests and fixtures.

Two layers:

1. **State**, delegated to `truthctl snapshot --require ...`. Gate results, reason codes,
   and the snapshot path are reproduced verbatim. No gate logic is written here.
2. **Claims**, new. Extract concrete assertions from the session transcript JSONL ("fixed
   X", "tests passed", "committed Y") and confront each with repository evidence: `git log`,
   `git diff`, recorded exit codes, file mtimes.

Every claim is emitted as `VERIFIED`, `REFUTED`, or `UNVERIFIED`. The handoff is always
written; unverified claims appear as unverified. This is the "fail closed on summaries"
rule made mechanical.

Claim extraction requires judgment, so it is a model step reading a bounded transcript
window, not a regex. Its cost is paid once per session close.

**Gate:** a fixture session claiming a fix that was never made yields `REFUTED`; a genuine
fix yields `VERIFIED`; an unrunnable check yields `UNVERIFIED` and never `VERIFIED`.

### S5 - `/sweep`

**Files:** `skills/sweep/SKILL.md`, `scripts/sweep_scan.py`, tests.

Scans a repository for abandoned work: plans whose slices are unchecked while their
frontmatter says active, `TODO`/`FIXME` older than a threshold, scaffolding without a
caller, `IDEA_BOX` entries referencing files that no longer exist.

Findings above a value threshold are appended to repository-local `IDEA_BOX.md` as slugged
entries, which closes the loop through the existing
`plan_context_updater --resolved-ideas`. A GitHub issue is created **only** when the
operator asks for a specific finding, per D6.

**Gate:** the scan is read-only, proven by before/after `git status`; appended entries are
consumable by `plan_context_updater`; no issue is created without an explicit request.

### S6 - Adversarial personas in `autoplan`

**Files:** `scripts/autoplan_review_workflow.js` (tracked by S0), persona prompt files,
`skills/master-agent/SKILL.md` documentation update.

Extend the existing `personas` array with three audit lenses:

| Persona | Question it forces |
|---|---|
| `bad-actor` | who pushes this across the R3 boundary, the broker path, or the Tsignal/LAB seam |
| `operator-0931` | market just opened, what is on screen, what is one click away, what is missing |
| `auditor-post-hoc` | can this decision be replayed and reconstructed in a month |

The agent selects which lenses are relevant to the plan under review rather than running
all of them, and reports per-persona findings plus any plan changes they force.

**Gate:** a plan touching the order boundary selects `bad-actor`; a documentation plan
selects none and says so; persona output changes the plan text, not only the report.

### S7 - Exact-head review and landing

- run focused and full `scripts/tests`, scoped `ruff`, `compileall`, `git diff --check`;
- record measured token cost of the SessionStart injection and the drift check;
- produce the implementation review packet;
- obtain exact-head review through the operator-selected `/fwp`;
- fix ship-blocking findings, batch one push, ready the PR once, merge;
- fast-forward the operator checkout;
- enable hooks in `settings.json` **as the final step**, one event at a time, verifying
  after each that a session still starts, compacts, and ends cleanly.

## Test plan

| Scenario | Expected |
|---|---|
| Operator writes "drift" in their own sentence | steering fires |
| Operator pastes a document containing "drift" in a quote | steering does **not** fire |
| Pasted text contains `ultracode` | no orchestration opt-in |
| Fenced code block contains a trigger word | no fire |
| Unknown model id in the footer | cost marked uncertain, never Sonnet-priced silently |
| `claude-opus-5` session | Opus rates applied |
| Session starts in a registered repo | full injection, title set, scratch file created |
| Session starts outside the registry | one line, no scratch file, zero injected context |
| Forced compaction mid-session | goal re-injected, chain intact |
| Session ends merged and clean | `ARCHIVE-OK` |
| Session ends merged with open items | `HANDOFF` plus draft |
| Session ends unmerged with large context | `CHECKPOINT` |
| Reaper run | only owned prefixes removed, others untouched |
| Curator on a session claiming an unmade fix | `REFUTED` |
| Curator when `truthctl` is unavailable | `UNVERIFIED`, never `VERIFIED`, nonzero status |
| `/sweep` on a clean repo | no findings, no writes, `git status` unchanged |
| Every hook script raises an exception | session unaffected, failure recorded to a log |
| All four hooks removed from settings | ecosystem behaves exactly as before this plan |

### Validation commands

```powershell
python -m pytest -q scripts/tests/test_session_router.py scripts/tests/test_session_drift.py scripts/tests/test_session_end.py scripts/tests/test_state_reaper.py scripts/tests/test_curator_claims.py scripts/tests/test_sweep_scan.py scripts/tests/test_plan_keyword_detector.py
python -m pytest -q scripts/tests
python -m ruff check <new and touched files>
python -m compileall -q <new modules>
git diff --check
```

A test counts as passed only when the exit code is zero **and** the expected target
actually ran.

## Token budget

The hooks are a permanent tax on every session, so budgets are acceptance criteria.

- SessionStart full run: <= 2,000 characters injected; p95 wall time <= 400 ms;
- SessionStart outside the registry: <= 120 characters; p95 wall time <= 150 ms;
- drift check: <= 600 characters injected. **Throttle: fires when at least 8 tool
  batches AND at least 25,000 characters of context have elapsed since the last
  check — whichever condition is satisfied later gates the fire, so both floors
  must be crossed.** Never more than once per 8 batches regardless of context growth;
- PreCompact re-injection: <= 1,500 characters;
- **curator claim extraction: <= 20,000 characters of redacted transcript window
  (the most recent turns), one model call per session close, no retry on timeout.**
  This is the plan's only model call inside a hook path and therefore the only
  place a cost ceiling has to be stated rather than inherited;
- hook wall time: <= 2 seconds each, fail-open on timeout.

**SessionEnd verdict thresholds** (previously "large context", which no implementation
could resolve deterministically):

| Merged into trunk | Worktree clean | Open items in scratch | Context used | Verdict |
|---|---|---|---|---|
| yes | yes | none | any | `ARCHIVE-OK` |
| yes | yes or dirty | any | any | `HANDOFF` |
| no | any | any | >= 60% of window | `CHECKPOINT` |
| no | any | any | < 60% of window | `CHECKPOINT` |

Unmerged always yields `CHECKPOINT`; the context figure is reported in the verdict for
the operator's judgement but does not change it. This removes the undefined
"large context" cutoff entirely rather than assigning it an arbitrary number.

**Hook execution model** (previously unstated, flagged independently by three lanes):
Claude Code runs hooks **synchronously** as subprocesses with a per-hook timeout. Every
hook in this plan is therefore on the session's hot path, which is why the wall-time
budgets above are acceptance criteria and not guidance. No hook performs network I/O.

For scale, the incident that motivated slice 1 injected 13.5 KB unrequested. Any slice that
breaches its budget is not shipped until it fits.

## Rollback and emergency off

1. Remove the four hook entries from `settings.json`. This is the kill switch, and it is
   sufficient on its own; every capability here is delivered through a hook.
2. Delete `~/.claude/state/session_plan_*`. Nothing else reads them.
3. Revert the merged commits to restore `plan_keyword_detector.py` and the footer.
4. `/curator` and `/sweep` are invoked explicitly and are inert when not called.

Rollback deletes no repository content, no `IDEA_BOX` entry, no TruthDeck snapshot, no
branch, and no worktree.

Per the global ship-on default, hooks land **enabled**. There is no soak phase and no
disabled flag. The kill switch above is the documented emergency-off.

## Definition of Done

- [ ] Trigger matching ignores quoted, fenced, and pasted content, proven by a regression
      test built from the 2026-07-25 incident.
- [ ] Model pricing covers the Claude 5 family and never silently falls back to a cheaper
      table.
- [ ] The four previously untracked scripts are canonical in this repository.
- [ ] Session intent is written to disk, survives compaction, and is re-injected.
- [ ] Drift, split-lane, and handoff prompts reach the agent mid-session, throttled.
- [ ] No hook in this plan can block a turn or end a session.
- [ ] `SessionEnd` produces a three-way verdict and never archives on its own.
- [ ] `turn_counter_*` backlog is reaped and cannot grow unbounded again.
- [ ] `/curator` reports TruthDeck gates verbatim and marks every session claim
      `VERIFIED`, `REFUTED`, or `UNVERIFIED`.
- [ ] `/sweep` is read-only and writes findings only to `IDEA_BOX.md`.
- [ ] `autoplan` runs adversarial personas selected per plan and their findings change plan
      text.
- [ ] Session titles follow the convention automatically at start.
- [ ] Every token budget above is measured, recorded, and met.
- [ ] Removing the four hook entries restores pre-plan behavior exactly.
- [ ] Exact-head review, CI, merge, and operator checkout sync are complete.

## Author pre-mortem

1. **The drift check becomes noise.** Most likely failure. Mitigated by throttling, a hard
   character budget, and a measured firing rate from a real session before enabling.
2. **The curator cries wolf.** A `REFUTED` on a genuine fix destroys trust immediately.
   Mitigated by a three-state verdict with an explicit `UNVERIFIED` middle, so the curator
   is never forced to guess between done and not done.
3. **The scratch file becomes a shadow plan.** Mitigated by invariant 1, by the file name,
   by excluding it from every gate, and by the reaper.
4. **Hook stack interaction.** Twelve hooks across seven events is the real complexity, and
   it is the one thing local tests cannot fully cover. Mitigated by enabling events one at
   a time in S7 and by requiring each to be independently removable.
5. **Registry drift.** A new repository silently gets no router. Accepted; the failure is
   visible and harmless, and autodetection was rejected in D7 as a worse trade.
6. **Scope creep toward Conductor.** The drift check asking "should this be a separate
   lane" is one step from wanting a channel between lanes. That step is explicitly out of
   scope and belongs to Conductor R2.

## Approval gate

This document authorizes planning only.

```text
/fwp D:/dotclaude/dotclaude-ecosystem/design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md
```

The hotfix branch covering `plan_keyword_detector.py` and `answer_footer.py` is tracked
separately as R1 defect repair and does not wait on this review.

**Hotfix status:** landed as `ad12cf2` (PR #50, squash-merged 2026-07-25), installed to
`~/.claude/scripts`, smoke-tested in both directions (pasted trigger emits 0 bytes; the
operator's own "co dalej?" emits 12,490).

## CEO Review Record - Stage 1 `/fwp`

Review date: 2026-07-25. Mode: **HOLD SCOPE**.

Mode rationale: the plan's scope was set by an operator `/grill-me` interview the same
day, which recorded seven explicit decisions (D1-D7 above) and cut three of ten candidate
items during the collision check. The `/fwp` R1 contract assigns product and mechanical
questions in this stage to the agent under conservative scope control. Expanding scope
here would re-litigate decisions the operator closed hours earlier, so no expansion
ceremony ran and no CEO plan document was written (both are EXPANSION-mode artifacts).

### System audit

- `main == origin/main == ad12cf2`; worktree clean.
- One pre-existing stash (`park generated operator playbook pdf`) untouched, same stash
  already noted in the TruthDeck R1 plan.
- Full suite green at review baseline: `191 passed, 2 subtests passed`.
- No `TODO`/`FIXME`/`HACK` markers in `scripts/`, `skills/`, or `agent-rules/` (two hits in
  `idea_digest.py` are string literals naming a section, not markers).
- Repo has no `TODOS.md`; deferred work lives in `design/` and per-repo `IDEA_BOX.md`.
- Hot files over 30 days are workflow-OS audit/handoff docs and `agent-rules/core.md` -
  this plan touches none of them, so there is no recurring-problem-area smell to inherit.
- No design doc from `/office-hours` for this branch; the grill transcript is the
  equivalent input and is recorded as D1-D7.

### Section verdicts

**1. Architecture - 3 findings.**

*Finding 1.1 (GAP, resolved).* `session_plan_<id>.json` had no schema version. Every other
artifact in this ecosystem is versioned (`truthdeck.snapshot.v1`, `conductor.work-item.v1`,
the OpusF bridge payloads). An unversioned file read by four separate hooks breaks silently
the first time its shape changes. **Resolved:** the file carries
`"schema_version": "session.plan.v1"`; a reader that does not recognise the version treats
the file as absent rather than guessing.

*Finding 1.2 (GAP, resolved).* The model writes the scratch file, but nothing said what
happens when it writes malformed JSON or omits a field. **Resolved:** every reader
validates and fails open - a malformed or partial file is treated as "no session plan",
never as an empty plan, and never raises into the session.

*Finding 1.3 (GAP, resolved).* PreCompact re-injection could re-inject a **stale** goal.
The plan said the model writes the file at session start but never said when it updates it,
so a session whose direction changed mid-run would have its original goal re-injected after
compaction - actively misleading, worse than injecting nothing. **Resolved:** the drift
check (S2) is the write path as well as the read path; when it fires and the model reports a
changed goal, it rewrites the file. PreCompact re-injects with the `updated_at` stamp
visible so a stale plan is legible as stale.

**2. Error and rescue map - 1 CRITICAL GAP, resolved.**

| Codepath | Failure | Exception | Rescued | Action | Operator sees |
|---|---|---|---|---|---|
| any hook reading scratch | malformed JSON | `json.JSONDecodeError` | Y | treat as no plan | nothing |
| any hook reading scratch | file locked by another session | `PermissionError`/`OSError` | Y | treat as no plan | nothing |
| `session_end` verdict | git call hangs | `subprocess.TimeoutExpired` | Y | verdict `UNKNOWN` | verdict says unknown |
| `curator` | `truthctl` absent | `FileNotFoundError` | Y | all claims `UNVERIFIED` | explicit, in handoff |
| `curator` | transcript unreadable | `OSError` | Y | claims `UNVERIFIED` | explicit |
| `state_reaper` | file vanished mid-scan | `FileNotFoundError` | Y | skip, continue | nothing |
| `session_router` | registry malformed | `json.JSONDecodeError` | Y | one-line mode | one line, not silence |

*Finding 2.1 (**CRITICAL GAP**, resolved).* The reaper was specified as deleting
`turn_counter_*` and `session_plan_*` "for sessions older than a retention window". Age is
not liveness. This session has run for hours; another session's `SessionEnd` firing
mid-run would have reaped its live scratch file and turn counter. **Resolved:** the reaper
excludes (a) its own `session_id`, (b) any session whose files were modified inside the
retention window, and (c) any `session_plan_*` whose `session_id` appears in the harness's
live-session list when that list is obtainable. Age alone never authorises a delete.

**3. Security - 2 findings, both resolved.**

*Finding 3.1 (GAP, resolved. Likelihood Medium, Impact High).* The curator reads the
session transcript JSONL. That transcript holds everything the session touched - pasted
credentials, `.env` contents echoed by a tool, environment dumps - and the curator feeds a
bounded window of it to a model. That is a **new egress path for secrets** that the plan did
not name. **Resolved:** the curator redacts before the window is assembled, reusing
`terminal_evidence.py`'s redaction helpers rather than inventing a second one, and never
persists raw transcript text into the handoff.

*Finding 3.2 (GAP, resolved. Likelihood Medium, Impact Medium).* `/sweep` writes findings
derived from repository content into `IDEA_BOX.md`, and `plan_context_loader.py` injects
`IDEA_BOX.md` into future sessions. A `TODO` comment containing an injection payload would
therefore reach a future session's context by a laundered route. **This is the same defect
class the plan's own slice 1 exists to close** - closing injection at the prompt while
opening it at the idea box would be self-defeating. **Resolved:** `/sweep` writes findings
as quoted, escaped, length-bounded text, and records the source `file:line` rather than
copying prose verbatim.

**4. Data flow and interaction edge cases - 2 gaps, resolved.**

*Finding 4.1 (resolved).* `SessionStart` fires with `source: resume` as well as `startup`.
As specified, a resumed session would overwrite its own scratch file and lose the goal it
was resuming. **Resolved:** on `resume`, `compact`, and `fork`, the router reads the existing
file and does not clobber it; only `startup` and `clear` create one.

*Finding 4.2 (resolved).* `SessionStart` in a directory that is not a git repository was
unspecified. **Resolved:** registry lookup miss and "not a repo" both fall to the same
one-line branch; neither raises.

Shadow paths for the scratch file: **nil** (no file) -> hooks behave as pre-plan; **empty**
(zero-length) -> same as nil; **error** (unreadable) -> same as nil, plus a line in the hook
error log. All three collapse to one behaviour deliberately, so there is one path to test.

**5. Code quality - 2 findings, resolved.**

*Finding 5.1 (resolved).* The slice list named eight new modules. The complexity check fires
above two new services. Six are genuinely separate hook entrypoints, but `session_precompact`
and `session_end` share their read path and differ only in trigger. **Resolved:** they
collapse into one `session_lifecycle.py` with two entrypoints, taking the module count to
seven.

*Finding 5.2 (DRY, resolved).* Four hooks independently need "resolve the registry", "read
and validate the scratch file", and "write the scratch file atomically". Left unstated, each
would reimplement it. **Resolved:** one `session_state.py` owns those three operations; the
hooks import it. Atomic writes reuse the temp-file-then-`os.replace` pattern already
established in `terminal_evidence.py` and `answer_footer.py`.

**6. Tests - 3 gaps, resolved.** The plan's matrix covered trigger provenance, pricing,
verdicts, and budgets. Missing and now added: (a) two concurrent sessions where one reaps
while the other is live (guards Finding 2.1); (b) malformed and truncated scratch files
(guards 1.2); (c) `SessionStart` with `source: resume` proving no clobber (guards 4.1). The
pyramid stays unit-heavy with no external services, no clock dependence, and no ordering
dependence, so flakiness risk is low.

**7. Performance - 1 finding, resolved.** Token budgets were specified; wall time was not.
On Windows, Python interpreter startup alone is roughly 150-250 ms, and `SessionStart` sits
in front of every session in every repo. **Resolved:** `SessionStart` carries a p95 budget of
400 ms in the registered case and 150 ms outside the registry, measured and recorded in S7
alongside the token numbers. The existing 2 s ceiling stays as the fail-open timeout, not as
the target.

**8. Observability - 1 finding, resolved.** The plan said hooks fail open. The existing
`plan_keyword_detector.py` carries the opposite principle in its own comments: a broken steer
path must be visibly dead, never silent. Both are right for different audiences. **Resolved:**
fail open toward the *session* (never break a turn) and fail loud toward *disk* - every
swallowed exception appends one bounded line to `~/.claude/state/hook_errors.log`, so a hook
that has been quietly dead for a week is discoverable. Retention for that log is the reaper's
job.

**9. Deployment - 1 risk flagged, accepted.** The installers copy `scripts/*.py`, so the
modules ship. The `settings.json` hook entries do **not** ship - they are hand-edited user
config outside version control. Enabling is therefore a manual step on every machine, and
there is no drift detection between "modules installed" and "hooks wired". Accepted for this
plan and recorded rather than solved: an installer-managed hook block is its own change, and
folding it in here would widen an R1 plan into settings-file ownership.

**10. Long-term trajectory.** Reversibility **5/5** - removing four `settings.json` entries
restores prior behaviour completely, and nothing else in the ecosystem takes a dependency on
the scratch file. Debt introduced: seven modules, one state file family, one log file. Path
dependency is low; the one real risk is the scratch file accreting readers until it becomes
the shadow plan the pre-mortem names, which invariant 1 and the reaper together bound.

**11. Design and UX - SKIPPED.** The plan ships no user interface. S7's design chain is a
routing rule that *proposes* existing design skills; it renders nothing itself.

### Outside voice

The `/fwp` Stage 2 fan-out (`auditf.py --mode paid --synthesizer claude`) **is** this
workflow's outside voice, and it runs against this same plan immediately after this stage
with an opposite-frontier reviewer plus the Perplexity, Gemini, and Kimi CDP lanes. Running
the skill's own single-model Codex pass in addition would duplicate that function at extra
cost with a narrower panel. Skipped deliberately, recorded here so the omission is legible.

### Failure modes registry

| Codepath | Failure mode | Rescued | Test | Operator sees | Logged |
|---|---|---|---|---|---|
| reaper vs live session | live scratch file deleted | yes | required | nothing (correct) | yes |
| PreCompact | stale goal re-injected | yes | required | `updated_at` stamp | yes |
| curator | secret reaches model window | yes | required | nothing (redacted) | no (by design) |
| `/sweep` | injected text laundered via IDEA_BOX | yes | required | quoted + bounded | yes |
| SessionStart on resume | scratch file clobbered | yes | required | nothing (correct) | yes |
| any hook | unhandled exception | yes | required | nothing in session | yes, `hook_errors.log` |

No row remains with rescued=no, test=no, and a silent operator impact.

### Verdict

**PROCEED.** Eleven findings across sections 1-8, of which one was critical (the reaper
deleting live-session state). All eleven are resolved inside the existing scope; none
required expansion, and none contradicts D1-D7. One deployment risk is accepted and
recorded rather than solved. Slice count moves from seven to eight with `session_state.py`
added and `session_precompact`/`session_end` collapsed.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | issues_found | mode: HOLD_SCOPE, 11 findings, 1 critical gap, all resolved |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | - | superseded by `/fwp` Stage 2 panel |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 0 | - | pending Stage 3 |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | - | not applicable, no UI scope |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | - | not run |

- **VERDICT:** CEO CLEARED (HOLD SCOPE, all findings resolved in scope) - eng review required.

NO UNRESOLVED DECISIONS
