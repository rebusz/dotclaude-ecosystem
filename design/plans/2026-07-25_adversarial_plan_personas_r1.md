---
title: Adversarial Personas for Plan Review
date: 2026-07-25
status: deferred
status_detail: split-from-session-lifecycle-core
risk: R1
phase: plan
repos: [dotclaude-ecosystem]
tags: [agent-tooling, plan-review, personas, autoplan]
related:
  - design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md
---

# Adversarial Personas for Plan Review

## Status

**Deferred, not abandoned.** Split out of the session lifecycle plan on 2026-07-25 by
operator decision. It improves plan-review quality and has nothing to do with session
lifecycle.

## The diagnosis this rests on

The ecosystem does not lack personas. It has roughly twenty, one hardwired into each gstack
skill: `cso` is a Chief Security Officer who has testified before boards, `canary` is a
Release Reliability Engineer, `design-review` is a senior product designer with no tolerance
for AI-generated-looking interfaces. Those are strong and they work.

Two real gaps sit underneath that:

1. **`master-agent` runs one persona across twelve modes.** "Principal Systems Architect"
   speaks for ARCHITECT, DEBUG, QUANT, CONTRACT, and POSTMORTEM alike. A debugger should be
   paranoid and narrow; a quant should be a statistician who assumes the edge already decayed.
   They currently sound identical.
2. **`grill-me` has no persona at all.** `grill-me/SKILL.md` is seven lines delegating to
   `/grilling`, and `grilling/SKILL.md` contains no "You are a..." line anywhere. Grilling
   without a persona is the form without the teeth.

## What it would do

Extend the existing `personas` array in `autoplan_review_workflow.js` - the fan-out mechanism
already exists and already runs CEO, design, eng, and DX reviewers as separate subagents - with
three **audit lenses**, and let the agent select which are relevant to the plan under review
rather than running all of them.

| Persona | The question it forces |
|---|---|
| `bad-actor` | who pushes this across the R3 boundary, the broker path, or the Tsignal/LAB seam |
| `operator-0931` | the market just opened, what is on screen, what is one click away, what is missing |
| `auditor-post-hoc` | can this decision be replayed and reconstructed in a month |

The key property, taken from the source that suggested it: a persona is an **audit lens applied
to a plan**, not a speaking voice. The agent picks which apply and reports per-persona findings
plus any plan text they force. A persona that changes only the report and not the plan has done
nothing.

Separately, and cheaply: give `master-agent` a per-mode persona line instead of one global one,
and give `/grilling` three selectable postures chosen by the plan's risk class rather than at
random - VC sceptic for R0/R1 and new ideas, staff-engineer failure-mode for R2/R3 and
contracts, operator-at-the-screen for cockpit and UI work.

## Prerequisite that is not yet satisfied

`autoplan_review_workflow.js` **is not under version control.** It lives only in
`~/.claude/scripts/` and is one of the eleven scripts still absent from
`dotclaude-ecosystem/scripts/`. Editing it in place produces a change that exists on one
machine and does not survive a reinstall. Bring it into the repository first.

## Inherited finding

The `operator-0931` persona anchors to a single market open. The operator trades instruments
with different sessions - futures pre-market, options, equities - so a persona hardcoded to one
open will be proposed for repositories and hours where it is irrelevant. This was dismissed
during the Stage 2 audit as "prompt text, tuned at use", which answered "is this a gating
defect" (no) and skipped "does the gate cover this class" (also no). The slice gate checks
persona **selection**, not persona **quality**. Either widen the gate or parameterise the
persona.

## Approval gate

This document records deferred scope. It authorizes nothing. Run through `/fwf` or `/fwp`
before implementation.
