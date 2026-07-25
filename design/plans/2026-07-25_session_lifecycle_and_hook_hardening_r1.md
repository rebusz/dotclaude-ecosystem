---
title: Session Lifecycle Core - Compaction Survival and Verified Close
date: 2026-07-25
status: draft
status_detail: cut-to-core-2026-07-25-awaiting-fwp-stage-3
risk: R1
phase: plan
repos: [dotclaude-ecosystem]
tags: [agent-tooling, hooks, session-lifecycle, compaction, handoff, evidence]
related:
  - design/plans/2026-07-22_truthdeck_agent_evidence_control_plane_r1.md
  - design/plans/2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md
  - design/plans/2026-07-21_global_fwf_fwp_contract_reset.md
  - design/plans/2026-06-27_global_agent_workflow_os.md
---

# Session Lifecycle Core - Compaction Survival and Verified Close

## Executive decision

Give a Claude Code session a **declared intent that survives compaction**, and give its
close a **verified verdict instead of a self-report**.

Two questions are currently unanswered by any tool in the ecosystem:

> What is this session actually trying to do, and are we still doing it?

> The agent says it fixed X. Did it?

TruthDeck answers what is true about *repository and runtime state*. It does not answer
either of the above. `/fwf` and `/fwp` own the engineering lifecycle of a *plan*, not the
lifecycle of a *session*. This plan fills that gap with two hooks, one session-scoped
scratch file, and one skill, all advisory.

**Plan-writing authorization:** granted by the operator on 2026-07-25 after a `/grill-me`
interview (seven decisions recorded below).
**Implementation authorization:** not implied. The operator selected `/fwp` for review.

## Consequence, downside, reversibility

- **Proposed action:** add SessionStart and SessionEnd hooks; add a per-session scratch file; add `/curator`; add a repo
  registry. The drift check, `/sweep`, and the persona work were cut to their own plans.
- **Plausible downside if wrong:** the hooks run on every session in every repository, so a
  defect degrades all work everywhere, not one project. A wrong curator verdict makes
  honest handoffs look dishonest.
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
3. At close, claims made during the session are confronted with repository evidence before
   anything is called done, and the outcome is persisted where the operator will meet it.

Goals about mid-session steering and abandoned-work discovery were in the original draft
and left with the scope cut; see `## Scope cut`.

### Collision verdict

`plan_context_loader.py` detects only repositories directly under `D:/APPS`, so it cannot
catalog this repository. This is a known limitation recorded in both TruthDeck plans. A
bounded fallback read of `design/plans/` was used instead. Three collisions were found.

| Proposed item | Collides with | Verdict |
|---|---|---|
| A curator that verifies claims | `2026-07-22_truthdeck_agent_evidence_control_plane_r1.md`, **shipped**. It already owns gate evaluation, fail-closed semantics, and `verify-handoff`. Its pre-mortem names "second source of truth" as failure mode 1 | **Reshape.** `/curator` consumes `truthctl`; it never re-implements a gate or mints a second evidence authority |
| A `Monitor`-based event bus between worktree lanes | `2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md` (draft) owns cross-repo agent coordination. Shipped TruthDeck R1 non-goals include "no always-on daemon, HTTP service, **event bus**" | **Dropped from this plan.** The correct path to lane coordination is running Conductor through `/fwf`, not building a competing bus |
| A `/fwd` design workflow command | `2026-07-21_global_fwf_fwp_contract_reset.md`: "No compatibility aliases, soak/shadow phase, or **third workflow command**" | **Dropped as a command.** The design chain becomes a routing rule inside S2 |

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
context injection. That defect is closed: the hotfix landed as `ad12cf2` before this plan
entered review, which is why it is no longer a slice here.

This plan addresses a second, slower failure: session intent lives only in the
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
- **12 of 36 scripts in `~/.claude/scripts` were absent from `dotclaude-ecosystem/scripts`**.
  `answer_footer.py` was brought under version control by the hotfix; the remaining eleven
  are untouched by this plan after the scope cut. Fixes to them still exist on one machine
  only and do not survive a reinstall. Recorded so the gap is not mistaken for coverage.
- `plan_keyword_detector.py` is tracked and byte-identical between repo and install.
- TruthDeck is installed with CLI and MCP registered on both Claude and Codex.

### Reuse map

| Existing surface | Use here | Must not become |
|---|---|---|
| `truthctl` snapshot/gates/verify-handoff | curator's evidence layer | re-implemented in the curator |
| `plan_context_loader.py`, `steer_context.py` | fact sources for the router | duplicated policy |
| `_catalog_common.py` | frontmatter parsing for plan scanning | new parser |
| `IDEA_BOX.md` via `plan_context_loader` | router surfaces open ideas | second backlog |
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
              +---------+---------+
              |                   |
              v                   v
        SessionEnd            /curator
        writes verdict        fresh truthctl gates
        + reaps               + claim check
              |                   |
              |                   v
              |          handoff, every claim marked
              |          VERIFIED / REFUTED / UNVERIFIED
              v
      verdict file (SessionEnd output is IGNORED by the
      harness, so the verdict is persisted, never announced)
              |
              +--> surfaced by the NEXT SessionStart in this repo
              +--> rendered on demand by /curator

Two hooks only: SessionStart and SessionEnd.

Forbidden edges:
  session_plan  --X--> any gate, any authority, any commit message
  hook          --X--> decision:"block" / continue:false
  pasted text   --X--> trigger match
  PreCompact    --X--> additionalContext   (the event has no such field)
  SessionEnd    --X--> anything the operator can see in-session
  this plan     --X--> cross-session channel  (that is Conductor)
```

## Scope cut - 2026-07-25, operator decision

After the Kimi K3 CLI frontier lane (see `Stage 2b`), the operator cut this plan to its
core and split the rest. The plan now answers exactly the two questions in the executive
decision and nothing else.

**Retained:** session state module, repo registry, SessionStart router, SessionEnd verdict,
reaper, `/curator`.

**Split into their own plans**, each independently motivated and each free to go through its
own workflow later:

| Was | Now | Why it left |
|---|---|---|
| S2 drift check on `PostToolBatch` | `2026-07-25_session_drift_check_r1.md` | Adds an always-on event surface to an ecosystem whose motivating incident was a hook injecting 13.5 KB unrequested. Its own pre-mortem names its noise as the most likely failure. It also carries the unresolved A1-vs-A2 contradiction. |
| S5 `/sweep` | `2026-07-25_sweep_abandoned_work_r1.md` | Repository hygiene, unrelated to session lifecycle. |
| S6 adversarial personas | `2026-07-25_adversarial_plan_personas_r1.md` | Plan-review quality, unrelated to session lifecycle. |

**Dissolved entirely:** the old S0 ("bring touched scripts under version control"). It existed
only to track untracked scripts before editing them. `answer_footer.py` was tracked by the
hotfix `ad12cf2`; `repo_hygiene_nudge.py`, `memory_size_guard.py`, and
`autoplan_review_workflow.js` are touched only by the split-out plans and travel with them.
The cut removed the slice rather than shrinking it.

**Resulting shape:** two hooks instead of four, four modules plus one skill instead of seven
modules. `PreCompact` and `PostToolBatch` are both gone from this plan - the first because it
cannot carry the payload the plan asked of it, the second because it left with the drift check.

## Implementation slices

Slices are ordered so that each one is independently shippable and independently
removable.

### S1 - Session state and repo registry

**Files:** `scripts/session_state.py`, `scripts/session_registry.py`,
`templates/session_registry.json.template`, `scripts/tests/test_session_state.py`.

`session_state.py` owns the three operations every consumer needs and nobody reimplements:
resolve the registry, read-and-validate the scratch file, write it atomically. Writes go to a
same-directory temp file then `os.replace`, so a process killed mid-write leaves the previous
good file intact - the Windows failure mode where a terminated subprocess has not released its
handle degrades to "previous plan still readable", never to "plan lost".

The scratch file carries `schema_version: "session.plan.v1"`. An unrecognised version is
treated as absent **and** appends `UNRECOGNIZED_VERSION` to `hook_errors.log`, so a stale
install on a second machine is discoverable instead of looking identical to a first run.

The registry names repositories that get a full run and their plan/vision/idea paths. It
covers `dotclaude-ecosystem`, which `plan_context_loader.py` cannot detect.

**Gate:** validation rejects malformed, truncated, and wrong-version files without raising;
concurrent writers never produce a partial file; a registry miss resolves cleanly to the
minimal branch.

### S2 - SessionStart router

**Files:** `scripts/session_router.py`, `scripts/tests/test_session_router.py`.

One hook, five matchers, three behaviours:

| `source` | Behaviour |
|---|---|
| `startup` | full run: facts + instruction to write the scratch file; sets `sessionTitle` |
| `clear` | same as `startup` |
| **`compact`** | **re-injects the existing scratch file** - this is the compaction-survival path |
| `resume` | reads the existing file, never clobbers it |
| `fork` | reads the existing file, never clobbers it |

**Compaction survival lives here, not in `PreCompact`.** `PreCompact` has exactly one output
channel, `decision: "block"`, plus the universal fields; it has no `additionalContext` and
therefore cannot re-inject anything. `SessionStart` has `additionalContext` and its matcher set
includes `compact`, so the re-injection happens on the near side of the boundary instead of the
far side. This corrects the plan's original claim that `PreCompact` was "the single
highest-value moment"; the moment is real, the hook was wrong.

The full run emits repository, branch, HEAD, dirty state, trunk divergence, active plans,
open `IDEA_BOX` entries, the most recent unconsumed handoff, **any unconsumed SessionEnd
verdict from the previous session in this repository**, and a proposed skill chain from a
routing table that includes the design chain settled in D5. Outside the registry: one line.

The router also performs an **opportunistic bounded reap** (see S3) because `SessionStart` is
the only event guaranteed to fire.

**Gate:** each of the five sources behaves as tabled; a compacted session recovers its goal;
`resume` proves no clobber; an unregistered repository costs zero injected tokens; the title
matches the convention.

### S3 - SessionEnd verdict and reaper

**Files:** `scripts/session_lifecycle.py`, `scripts/state_reaper.py`,
`scripts/tests/test_session_lifecycle.py`, `scripts/tests/test_state_reaper.py`.

**Verdict delivery is the hard part and the original plan had none.** `SessionEnd` output is
ignored by the harness - exit code and JSON alike - so a verdict emitted there is invisible at
the only moment it matters. The verdict is therefore **persisted, not announced**: `SessionEnd`
writes it beside the scratch file, and it reaches the operator by two paths that can actually
speak - the next `SessionStart` in that repository surfaces it (S2), and `/curator` renders it
on demand (S4).

Verdict rules, reduced to the three that actually decide anything:

| Condition | Verdict |
|---|---|
| merged into trunk, worktree clean, no open items | `ARCHIVE-OK` |
| merged into trunk, anything else outstanding | `HANDOFF` |
| not merged | `CHECKPOINT` |

Context consumption is **reported** in the verdict for the operator's judgement and decides
nothing. The earlier four-row table had two rows that both yielded `CHECKPOINT`, parading a
variable that never changed the outcome.

`state_reaper.py` deletes `turn_counter_*`, `session_plan_*`, and stale verdict files. It
excludes its own `session_id`, anything modified inside the retention window, and any session
the harness reports as live. **Age is never sufficient authority to delete.**

**The reaper cannot rely on `SessionEnd`.** A killed session, an IDE crash, or a closed
terminal never fires it - and on Windows that is the ordinary exit, which is precisely why
1,944 `turn_counter_*` files accumulated in the first place. A janitor triggered only by clean
exits cannot clean up after unclean ones. The reaper therefore runs from **both** `SessionEnd`
and, bounded and throttled, from `SessionStart`.

**Gate:** the 1,944-file backlog is cleared; a live session's files survive a concurrent
reap; verdicts are correct across merged-clean, merged-dirty, and unmerged fixtures; a
session killed without `SessionEnd` is still reaped on the next `SessionStart`.

### S4 - `/curator`

**Files:** `skills/curator/SKILL.md`, `scripts/curator_claims.py`, tests and fixtures.

Two layers.

**State**, delegated to `truthctl`. The curator runs a **fresh** `truthctl snapshot
--no-store` at close rather than consuming a cached one, and any gate whose evidence head
differs from current `HEAD` renders `UNVERIFIED`, never `VERIFIED`. Reproducing a stale gate
result verbatim would be silent misinformation - the exact failure the curator exists to
prevent.

**Claims**, new. Extract concrete assertions from the session transcript ("fixed X", "tests
passed", "committed Y") and confront each with repository evidence: `git log`, `git diff`,
recorded exit codes, file mtimes. Every claim emits `VERIFIED`, `REFUTED`, or `UNVERIFIED`.
The handoff is always written; unverified claims appear as unverified.

Redaction walks the **parsed structure**, not lines. A session transcript is nested JSONL -
message objects containing content arrays containing tool-result blocks - and flat-string
regexes would miss a secret nested one level down. The patterns come from
`terminal_evidence.py`; its line-oriented driver does not.

`/curator` also renders any persisted SessionEnd verdict, which is one of the two delivery
paths that replaced the channel `SessionEnd` does not have.

**Gate:** a fixture session claiming an unmade fix yields `REFUTED`; a genuine fix yields
`VERIFIED`; an unrunnable check or a stale snapshot yields `UNVERIFIED` and never `VERIFIED`;
a secret nested inside a tool-result content array does not survive redaction.

### S5 - Exact-head review and landing

- run focused and full `scripts/tests`, scoped `ruff`, `compileall`, `git diff --check`;
- record measured token cost and wall time of every SessionStart branch and of `/curator`;
- produce the implementation review packet;
- obtain exact-head review through the operator-selected `/fwp`;
- fix ship-blocking findings, batch one push, ready the PR once, merge;
- fast-forward the operator checkout;
- enable hooks in `settings.json` **as the final step**, one event at a time, verifying
  after each that a session still starts, compacts, and ends cleanly.

## Test plan

Trigger-provenance and pricing scenarios are **not** listed here. They shipped with the
hotfix and live in `scripts/tests/test_hook_trigger_provenance.py`; repeating them as
pending work would misrepresent what is left to build.

| Scenario | Expected |
|---|---|
| Session starts in a registered repo | full injection, title set, scratch file created |
| Session starts outside the registry | one line, no scratch file, zero injected context |
| Session starts in a directory that is not a repo | one line, no raise |
| **`SessionStart` with `source: compact`** | **goal re-injected with `updated_at` visible** |
| `SessionStart` with `source: resume` or `fork` | existing scratch file read, never clobbered |
| Scratch file has unrecognised `schema_version` | treated as absent **and** `UNRECOGNIZED_VERSION` logged |
| Scratch file malformed or truncated | treated as absent, no raise |
| Write killed mid-flight (Windows handle held) | previous good file still readable |
| Session ends merged and clean | `ARCHIVE-OK` persisted |
| Session ends merged with open items | `HANDOFF` persisted plus draft |
| Session ends unmerged | `CHECKPOINT`; context reported, not decisive |
| **Unconsumed verdict exists** | **surfaced by the next `SessionStart` in that repo** |
| **Session killed, `SessionEnd` never fires** | **still reaped on the next `SessionStart`** |
| Reaper run | only owned prefixes removed; live session's files survive |
| Curator on a session claiming an unmade fix | `REFUTED` |
| Curator when `truthctl` is unavailable | `UNVERIFIED`, never `VERIFIED` |
| **Curator when the snapshot head differs from `HEAD`** | **`UNVERIFIED`, never reproduced as `VERIFIED`** |
| **Secret nested in a tool-result content array** | **redacted before the model window is built** |
| Every hook script raises an exception | session unaffected, failure recorded to a log |
| Both hooks removed from settings | ecosystem behaves exactly as before this plan |

### Validation commands

```powershell
python -m pytest -q scripts/tests/test_session_state.py scripts/tests/test_session_router.py scripts/tests/test_session_lifecycle.py scripts/tests/test_state_reaper.py scripts/tests/test_curator_claims.py
python -m pytest -q scripts/tests
python -m ruff check <new and touched files>
python -m compileall -q <new modules>
git diff --check
```

A test counts as passed only when the exit code is zero **and** the expected target
actually ran.

## Token budget

The hooks are a permanent tax on every session, so budgets are acceptance criteria.

- SessionStart, full run: <= 2,000 characters injected; p95 wall time <= 400 ms;
- SessionStart, compact re-injection: <= 1,500 characters (the scratch file plus its
  `updated_at` stamp, so a stale plan reads as stale);
- SessionStart, outside the registry: <= 120 characters; p95 wall time <= 150 ms;
- SessionStart opportunistic reap: <= 200 files per invocation, <= 150 ms, never blocking;
- **curator claim extraction: <= 20,000 characters of redacted transcript window
  (the most recent turns), one model call per invocation, no retry on timeout.**
  This is the plan's only model call and therefore the only place a cost ceiling has to
  be stated rather than inherited;
- hook wall time: <= 2 seconds each, fail-open on timeout.

The drift check's throttle numbers left with the drift check. They are recorded in
`2026-07-25_session_drift_check_r1.md` together with the contradiction that has to be
resolved before that plan can be implemented at all.

**Hook execution model** (previously unstated, flagged independently by three lanes):
Claude Code runs hooks **synchronously** as subprocesses with a per-hook timeout. Every
hook in this plan is therefore on the session's hot path, which is why the wall-time
budgets above are acceptance criteria and not guidance. No hook performs network I/O.

For scale, the incident that motivated slice 1 injected 13.5 KB unrequested. Any slice that
breaches its budget is not shipped until it fits.

## Rollback and emergency off

1. Remove the two hook entries from `settings.json`. This is the kill switch, and it is
   sufficient on its own; every capability here is delivered through a hook.
2. Delete `~/.claude/state/session_plan_*`. Nothing else reads them.
3. Revert the merged commits to restore `plan_keyword_detector.py` and the footer.
4. `/curator` is invoked explicitly and is inert when not called.

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
- [ ] `/curator` takes a fresh snapshot, never reproduces a stale gate as `VERIFIED`, and
      marks every session claim `VERIFIED`, `REFUTED`, or `UNVERIFIED`.
- [ ] Redaction traverses nested transcript structure, not lines.
- [ ] The SessionEnd verdict is persisted and reaches the operator by at least one of the
      two delivery paths, because `SessionEnd` itself cannot speak.
- [ ] A session killed without `SessionEnd` is still reaped.
- [ ] Session titles follow the convention automatically at start.
- [ ] Every token budget above is measured, recorded, and met.
- [ ] Removing the two hook entries restores pre-plan behavior exactly.
- [ ] Exact-head review, CI, merge, and operator checkout sync are complete.

## Author pre-mortem

1. **The curator cries wolf.** A `REFUTED` on a genuine fix destroys trust immediately.
   Mitigated by a three-state verdict with an explicit `UNVERIFIED` middle, so the curator
   is never forced to guess between done and not done.
2. **The scratch file becomes a shadow plan.** Mitigated by invariant 1, by the file name,
   by excluding it from every gate, and by the reaper.
3. **Hook stack interaction.** Ten hook entries across four events is the real complexity,
   and it is the one thing local tests cannot fully cover. Mitigated by enabling events one
   at a time in S5 and by requiring each to be independently removable. The scope cut halved
   this plan's contribution to it.
4. **Registry drift.** A new repository silently gets no router. Accepted; the failure is
   visible and harmless, and autodetection was rejected in D7 as a worse trade.
5. **Scope creep toward Conductor.** Any "should this be a separate lane" feature is one
   step from wanting a channel between lanes. That step is out of scope here and belongs to
   Conductor R2. It left with the drift check.
6. **The plan re-grows.** Three features were cut today. The pressure to fold them back in
   because they are "nearly done" is the failure that produced the original eight-slice
   shape. Each returns through its own plan or not at all.

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

## Stage 2 Audit Synthesis - `/fwp` paid panel

Run: `design/audits/2026-07-25_2026-07-25_session_lifecycle_and_hook_hardening_r1/`
Topology: R1 audit, `--mode paid --synthesizer claude`.

### Panel completeness - read this before weighing anything below

| Lane | Source | Returned | Usable |
|---|---|---|---|
| GPT Pro current | `gpt_cdp` | **no - `captcha_detected`** | - |
| Perplexity Best | `perplexity_cdp` | yes, 120 s | **yes** |
| Perplexity Sonar 2 | `perplexity_cdp` | yes, 57 s | no - truncated input |
| Perplexity Kimi K2.6 | `perplexity_cdp` | yes, 54 s | no - truncated input |
| Gemini current | `gemini_cdp` | yes | partial |
| DeepSeek V4 Pro, Mistral Medium 3.5, MiniMax M3, Seed 1.6 | OpenRouter paid | yes | partial |

Two failures compound here and neither may be papered over:

1. **The opposite-frontier lane did not run.** With `--synthesizer claude`, the GPT CDP
   lane exists specifically so a non-Claude frontier model grades work a Claude agent
   produced. It returned `captcha_detected`. The captcha was not bypassed - doing so is
   prohibited and would not have produced trustworthy evidence anyway. **This panel
   therefore contains no independent frontier reviewer.**
2. **Two of three Perplexity lanes audited a truncated plan.** Sonar 2 opens with "Given
   the heavy compaction"; Kimi K2.6 states "roughly 60-70% of the body was compacted
   away" and quotes a sentence cut mid-word at "SessionSta". Their findings are dominated
   by absence claims about sections that are present in the plan - architecture diagram,
   token budget numbers, implementation slices, the D1-D7 decision table, the Reddit-paste
   regression test. Those are artifacts of a mutilated input, not defects in the plan.

**Effective panel: one fully-informed lane plus partial corroboration.** Confidence in
this stage is **low-to-moderate**, not the moderate-to-high a complete R1 panel would
carry. Recorded rather than smoothed over.

### Applied - consensus and unique-valid findings

Each entry states the plan heading, the change, and the reason, per the synthesis contract.

**A1 (P1, `Why now` / Invariant 5 / S2 / Test plan) - close the PostToolBatch injection
surface.** The 2026-07-25 hotfix closed trigger injection through `UserPromptSubmit`, where
the vector was pasted prompt text. `PostToolBatch` delivers `tool_calls[].tool_output`, and
a drift check that reads "what has happened since the last check" would naturally read it -
inheriting the exact defect class slice 1 exists to close. A file containing the word
`drift`, or a log line containing `ultracode`, would be enough. **Change:** `session_drift.py`
derives its context from the scratch file and from operator-authored turn text only; it
never scans tool-result payloads. A regression test mirroring the hotfix fixture is required:
tool output containing a trigger must not fire anything. *Best, unique, architecturally
valid - and the single most valuable finding this panel produced.*

**A2 (P1, `Token budget`) - define the drift throttle.** The plan said "at most once per N
batches" and never defined N, while the Definition of Done gates on "measured firing rate
within budget". An acceptance criterion whose budget is undefined cannot be evaluated, and
the pre-mortem names drift-check noise as the most likely failure. **Change:** applied
above - 8 batches AND 25,000 characters, both floors required.

**A3 (P1, `Architecture` / S3) - log a clean version miss.** Finding 1.1 made unrecognised
`schema_version` fall to "no plan". That is correct behaviour and invisible telemetry: a
stale install on a second machine degrades silently and looks identical to a first run.
**Change:** a version mismatch appends `UNRECOGNIZED_VERSION` to `hook_errors.log`. The
session still degrades gracefully; the degradation is now discoverable.

**A4 (P2, `Token budget` / S4) - ceiling the curator's model call.** The budget table
covered every injection path and omitted the one explicit model call the plan introduces.
A 200-turn session yields hundreds of KB of JSONL; "bounded window" without a number is
unbounded. **Change:** applied above - 20,000 characters, one call, no retry.

**A5 (P2, `Token budget` / S3) - replace the undefined CHECKPOINT threshold.** "Large
context" appeared in no table and no test. **Change:** applied above - the verdict is
decided by merge state and open items; context percentage is reported, never decisive.

**A6 (P2, S4 / reuse map) - a stale TruthDeck snapshot must not be reproduced as truth.**
The error map covered `truthctl` absent. It did not cover `truthctl` present with a snapshot
whose head has moved. Reproducing a stale gate result "verbatim" is silent misinformation -
the precise failure the curator exists to prevent. **Change:** the curator re-runs
`truthctl snapshot --no-store` at close rather than consuming a cached one, and any gate
whose evidence head differs from current `HEAD` is rendered `UNVERIFIED`, never `VERIFIED`.

**A7 (P2, Security Finding 3.1) - redaction must traverse structure, not lines.**
`terminal_evidence.py` redacts flat terminal output. A session transcript is nested JSONL:
message objects containing content arrays containing tool-result blocks. Flat-string regexes
would miss secrets nested one level down - a boundary mismatch on the plan's
highest-sensitivity path. **Change:** the curator walks the parsed structure and redacts at
every string leaf before assembling the window, reusing the patterns from
`terminal_evidence.py` but not its line-oriented driver.

**A8 (P2, S2 / S3, Windows-specific) - a killed hook must not lose the checkpoint.** On
Windows, terminating a subprocess mid-write does not guarantee the file handle is released;
the next write hits `PermissionError`, which the error map routes to "treat as no plan" -
silently discarding the session's intent. **Change:** scratch writes go to a same-directory
temp file and `os.replace` (the pattern already used by `terminal_evidence.py` and
`answer_footer.py`), so a killed write leaves the previous good file intact; a
`PermissionError` on read retries once before degrading.

**A9 (P2, S1 / Deployment) - the router self-diagnoses missing wiring.** CEO Finding 9
accepted that `settings.json` entries are hand-wired and undetected. The asymmetry that
leaves is real: a machine with modules installed but hooks unwired runs zero hooks and says
nothing, while the operator believes the system is live. **Change:** `session_router.py`
checks that all four expected hook entries are present and logs one line naming any that are
absent. Self-diagnosis inside existing module scope, no installer ownership required.

**A10 (P3, S5) - define the `/sweep` value threshold.** "Findings above a value threshold"
is satisfied equally by always-append and never-append. **Change:** a finding is appended
only when it names a concrete artifact (file path, plan slice, or `IDEA_BOX` slug) and is
older than 14 days; everything else goes to the report only.

### Corroborated - already resolved before the panel ran

**Degraded mode needs an observable signal.** Sonar 2 and Kimi K2.6 raised this
independently despite their truncated inputs, and it matches CEO Finding 8 (fail open toward
the session, fail loud toward `hook_errors.log`). Three lanes converging on a resolved
finding is confirmation the resolution was the right shape.

**Hook execution model was genuinely unstated.** All three Perplexity lanes flagged it, and
unlike their other absence claims this one was not a truncation artifact - the plan really
never said whether hooks are synchronous. Now stated explicitly in `Token budget`.

### Discarded, with reasons

| Finding | Source | Why discarded |
|---|---|---|
| Architecture section missing / must be restored | Kimi P1, Sonar P1 | Present in full; truncation artifact |
| Token budget has no numeric criteria | Sonar P2, Kimi P2 | Present in full; truncation artifact |
| Implementation slices have zero detail | Kimi P1, Sonar P2 | S0-S7 present with files and gates; truncation artifact |
| Reddit-paste scenario has no test | Kimi P2 | Test exists and shipped in `test_hook_trigger_provenance.py` |
| D1-D7 decision table omitted | Kimi P2 | Present in full; truncation artifact |
| "Verified verdict at close" has no design | Sonar P1 | Conflates the SessionEnd verdict with the curator; both specified |
| Invariant 1 contradicts survive-compaction | Sonar P2 | No conflict: scratch-not-truth is about *authority*, not durability |
| Windows paths invalid in containers | Kimi P3 | Windows-first is a declared ecosystem boundary, not a defect |
| `answer_footer` pricing test ownership unclear | Best P3 | Stale: hotfix merged as `ad12cf2` with tests before this panel ran |
| Two sessions in one directory clobber each other | Best P2 | `session_id` is unique per session; per-session filenames already separate them |
| `operator-0931` persona assumes one market open | Best P3 | Persona is prompt text, tuned at use; not a gating defect |

## Stage 2b - CLI frontier lanes

The Stage 2 CDP panel had no independent frontier reviewer: the GPT Pro lane returned
`captcha_detected`, and the captcha was not bypassed. The operator directed a retry through
the **CLI** lanes instead, which reach the same model families without a browser.

Two changes made these lanes worth more than the ones they replaced. Both were run with
`--repo` rather than a pasted prompt, so each model read the **full plan from the working
tree** - removing the truncation that reduced two of three Perplexity lanes to noise. And
both were pointed adversarially at the prior reviews' own conclusions, not just at the plan.

| Lane | Runner | Sandbox | Result |
|---|---|---|---|
| `21_kimi_cli_k3` | `auditkimi_cli.py`, kimi 0.27.0 | throwaway worktree | **returned** |
| `22_codex_cli_gpt` | `auditcodex_cli.py`, codex-cli 0.145.0 | OS read-only | **failed - upstream sandbox hang** |

**Codex lane, resolved 2026-07-25 17:22.** The lane did not time out and did not error; it hung,
and the cause is upstream of this repo. A later invocation of the same lane was still alive 55
minutes after launch, and the process tree shows where: `codex` itself had consumed 7.4 s of CPU
and was idle, waiting on its child `codex-windows-sandbox-setup`, which had consumed **2,395 s of
CPU in 55 minutes of wall clock** - roughly 72% of one core, spinning rather than blocking. Both
were terminated by operator decision.

Two things follow, neither of which is a finding about this plan:

- **`--health-check` does not exercise the failing path.** It calls `call_codex_cli` with
  `repo=None`, which builds argv with `--skip-git-repo-check` and **no `--cd`**. The hang occurs
  on repo-scoped runs, which is the only way the lane is ever used for an audit. `healthy: true`
  was therefore never evidence that the lane works, and the handoff's reading of it as "runtime
  hang rather than a configuration problem" was right for the wrong reason.
- **`subprocess.run(timeout=...)` did not reap the tree.** The process outlived its 900 s budget
  by forty minutes. On Windows the timeout kills the direct child; a grandchild holding the
  inherited stdout/stderr handles keeps the post-kill `communicate()` drain blocked, which is why
  the runner never wrote its `codex exec timed out` error and `.codex_run.log` is 0 bytes.

**Operator decision, 2026-07-25:** proceed to Stage 3 on the Kimi lane and the CDP panel. The
lane defect belongs to `D:/APPS/_shared/audit`, not to this plan, and is recorded there rather
than blocking the review. Stage 2b therefore closes with one frontier lane, not two - stated
plainly because a panel that silently reports "8 of 9" is the failure mode this plan's own
`Panel completeness` section exists to prevent.

### Kimi K3 - two mechanism errors that both prior reviews missed

Kimi verified its load-bearing claims against the live hooks reference before writing, and
both were confirmed independently against the same document.

**K1 (P1) - `PreCompact` cannot emit context.** Its only output fields are `decision: "block"`,
`reason`, and the universal set. It has **no `additionalContext`**. The plan built S3 on it,
called it "the single highest-value moment for the whole plan", and priced a 1,500-character
re-injection through a channel that does not exist. The correct event is `SessionStart` with
`source: compact`, which does have `additionalContext` and which this plan's own Finding 4.1
had already wired into the router. **Applied:** compaction survival moved to the router;
`PreCompact` removed from the plan entirely. The moment was real; the hook was wrong.

**K2 (P1) - the `SessionEnd` verdict had no delivery channel.** `SessionEnd` output is ignored
by the harness, exit code and JSON alike. A three-state verdict emitted there would be
invisible at the only moment it matters, which is the whole of headline goal 2. **Applied:**
the verdict is persisted rather than announced, and reaches the operator by the next
`SessionStart` in that repository or on demand through `/curator` - two paths that can
actually speak.

**K3 (P1) - A9's self-diagnosis was circular.** `session_router.py` is delivered *by* the
`SessionStart` hook. The failure A9 was written to catch - modules installed, hooks unwired,
operator believes the system is live - is exactly the state in which the router never runs and
logs nothing. It detects partial wiring only. **Applied:** the check moves to the installer or
a status command, something that runs whether or not hooks are wired.

**K4 (P1) - A1 and A2 contradicted each other.** A1 forbade the drift check from reading
tool-result payloads; A2's throttle required a 25,000-character context floor that only those
payloads could supply. Both were applied in the same pass as separate findings and neither
reviewer noticed the collision. **Resolved by the scope cut:** the drift check left, and the
contradiction travels with it as the blocking item in its own plan.

**K5 (P2) - the plan had not been reconciled with its own review record.** Finding 5.1
collapsed two modules and 5.2 added one, but the slice list and validation commands still
named the old files. An implementer following the slices would have built modules the review
record says no longer exist. **Applied:** slices and validation commands rewritten.

**K6 (P2) - three plans wearing one coat.** Surfaced to the operator as a scope decision
rather than absorbed. **Operator cut the plan to core on 2026-07-25**; see `## Scope cut`.

**K7 (P3, applied) - the reaper had no guaranteed trigger.** It ran from `SessionEnd`, which a
killed session never fires - and on Windows that is the ordinary exit, which is precisely how
1,944 `turn_counter_*` files accumulated. A janitor that only runs after clean exits cannot
clean up after unclean ones. **Applied:** the reaper also runs bounded and throttled from
`SessionStart`.

**K8 (P3, applied) - the verdict table had dead rows.** Two of four rows both yielded
`CHECKPOINT`, parading a "context used" column that changed no outcome. **Applied:** reduced
to three rules with context reported and never decisive.

**K9 (P3, applied) - S0's file list was stale and its copy direction undefined.** Applied by
dissolution: the scope cut removed S0 entirely.

**K10 (P2, recorded as debt, not fixed).** The hotfix smoke test reported the operator's own
two-word "co dalej?" emitting **12,490 bytes**. That number was presented as proof the fix
worked. It is also proof the fix addressed *provenance* and not *volume*: trivial operator
text still triggers an injection of the same order as the 13.5 KB incident this work exists to
react to. Neither the CEO review nor the CDP panel asked why that is acceptable, and the
Definition of Done tests provenance only. **Not fixed here** - it belongs to
`plan_keyword_detector.py` and `steer_context.py`, not to this plan - but recorded so it is not
lost.

**Runner defect found in passing.** `auditkimi_cli.py` wrote its output file, then crashed on
`print(run.text)` with `UnicodeEncodeError` under cp1252. Any review containing a non-ASCII
character breaks that lane's stdout echo on Windows. The review itself was intact.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | issues_found | mode: HOLD_SCOPE, 11 findings, 1 critical gap, all resolved |
| Audit Panel (CDP) | `/fwp` Stage 2 (paid) | Multi-model challenge | 1 | issues_found | 9 lanes, 8 returned, frontier lane failed `captcha_detected`; 10 applied, 11 discarded |
| Frontier CLI (Kimi K3) | `auditkimi_cli.py` | Independent frontier, full plan | 1 | issues_found | 10 findings; 2 mechanism errors, 1 self-contradiction, 1 scope cut, 1 debt |
| Frontier CLI (Codex GPT) | `auditcodex_cli.py` | Opposite-frontier check | 0 | **pending** | launched, no output at time of writing |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 0 | - | pending Stage 3 |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | - | not applicable, no UI scope |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | - | not run |

- **CROSS-MODEL:** the CDP panel and the CLI frontier lane disagree sharply in value, and the
  reason is input fidelity rather than model quality. Lanes whose input arrived compacted
  produced absence claims about sections that were present; the lane given `--repo` access
  read the plan and found two errors that invalidated a slice. **Corrected 2026-07-25:** an
  earlier draft of this report blamed a 30 KB truncation in `auditf.py`. That is wrong.
  `auditf.py` reads the plan with a plain `read_text()` and truncates nothing, and no
  truncation exists anywhere in `_shared/audit`. The degradation happened downstream, in the
  Perplexity web product the CDP lanes drive - Kimi K2.6 described its input as "compacted
  away", not truncated. The harness sends the whole plan; the browser-side consumer does not
  honour it. The exact downstream mechanism is not pinned down, only our harness ruled out.
- **VERDICT:** CEO CLEARED + AUDIT APPLIED + FRONTIER APPLIED. Plan cut to core by operator
  decision; two hooks, four modules, one skill. Eng review required.

**UNRESOLVED DECISIONS:**
- The Codex CLI frontier lane has not returned. Fold its findings in when it does, or proceed
  to Stage 3 on the strength of the Kimi lane alone.
- CDP web-UI lanes silently degrade long plan input, which cost two of three Perplexity lanes
  in this run. The cause is downstream of `_shared/audit`, so it cannot be fixed by editing the
  runner; the available lever is lane selection - prefer CLI lanes for plans past a size the
  web UI mishandles. Out of scope here, recorded so the next panel does not repeat it.
