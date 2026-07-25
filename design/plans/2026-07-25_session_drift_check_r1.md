---
title: Mid-Session Drift Check
date: 2026-07-25
status: deferred
status_detail: split-from-session-lifecycle-core-carries-an-unresolved-contradiction
risk: R1
phase: plan
repos: [dotclaude-ecosystem]
tags: [agent-tooling, hooks, session-lifecycle, drift]
related:
  - design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md
---

# Mid-Session Drift Check

## Status

**Deferred, not abandoned.** Split out of the session lifecycle plan on 2026-07-25 by
operator decision, after the Kimi K3 frontier lane argued that plan was three features
wearing one coat and that this was the weakest third carrying the highest risk.

It is deferred rather than dropped because the need is real: the operator asked for it
directly, and a long session genuinely does drift from its stated goal. But it does not
belong in a plan whose thesis is "intent survives compaction, close is verified", and it
cannot be implemented as currently specified.

## What it would do

Periodically, mid-session, ask the agent three questions and let it act or answer in one
line:

1. Is the declared goal still the goal?
2. Has a second, independent workstream appeared that deserves its own session?
3. Is it time to write a handoff and start fresh?

Advisory only. Never `decision: "block"`. The session plan file written by the lifecycle
core (`session.plan.v1`) is both the read source and the write target, so a changed goal
is recorded rather than merely mentioned.

## The blocking contradiction

**This must be resolved before any implementation begins.** Two findings applied during the
parent plan's Stage 2 audit cannot both hold:

- **A1** forbids the drift check from reading tool-result payloads. The reason is sound:
  `PostToolBatch` delivers `tool_calls[].tool_output`, and a check that scans those payloads
  for context inherits exactly the injection class the 2026-07-25 hotfix (`ad12cf2`) exists
  to close. A file containing the word `drift`, or a log line containing `ultracode`, would
  be enough.
- **A2** sets the throttle floor at "at least 25,000 characters of context elapsed since the
  last check."

`PostToolBatch` carries no cumulative context metric. The only source for a character count
is the tool payloads A1 forbids, or the transcript JSONL, which is written asynchronously and
lags the live turn by an unbounded amount - so on a fast session the most drift-relevant
turns are precisely the ones missing.

Both fixes were reviewed as separate findings and neither reviewer noticed they collide.

**Candidate resolution** (not yet decided): drop the character floor entirely and throttle on
the two observables a `PostToolBatch` hook actually has - batch count and elapsed wall time.
That keeps A1 intact and makes the throttle implementable. It also makes the throttle blunter,
which may be acceptable given the check is advisory.

## Other inherited risks

- **Its own pre-mortem named it the most likely failure.** A drift check that fires too often
  trains the operator to ignore it, and an ignored nudge is worse than no nudge because it
  costs tokens on every fire.
- **It adds an always-on event surface** to an ecosystem whose motivating incident was a hook
  injecting 13.5 KB unrequested. `PostToolBatch` fires after every batch of parallel tool
  calls; in the session that produced this plan that would have been roughly twelve times.
- **"Should this be a separate lane?" is one step from wanting a channel between lanes.**
  That step belongs to TruthDeck Conductor R2, not here. The question may be asked; the
  channel may not be built.

## Prerequisite

The session lifecycle core must land first. This plan reads and writes
`session_plan_<id>.json` through `session_state.py`, and has no state of its own.

## Approval gate

This document records deferred scope. It authorizes nothing.

Before implementation: resolve the A1/A2 contradiction, then run the plan through `/fwf`
or `/fwp`.
