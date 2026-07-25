---
title: /sweep - Abandoned Work Discovery
date: 2026-07-25
status: deferred
status_detail: split-from-session-lifecycle-core
risk: R1
phase: plan
repos: [dotclaude-ecosystem]
tags: [agent-tooling, repo-hygiene, idea-box]
related:
  - design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md
---

# `/sweep` - Abandoned Work Discovery

## Status

**Deferred, not abandoned.** Split out of the session lifecycle plan on 2026-07-25 by
operator decision. It is repository hygiene, not session lifecycle; the two were bundled
because the same grill surfaced them on the same day, which is not a reason to ship them
together.

## The gap it fills

`git_hygiene.py` finds **branch drift** - branches that have wandered far from trunk. Nothing
finds **scope drift**: a plan in `design/plans/` that stopped at slice 3 of 7, a `TODO` from
March, scaffolding with no caller, an `IDEA_BOX` entry pointing at a file that no longer
exists. `IDEA_BOX.md` catches ideas; nothing catches orphans.

## What it would do

Scan a repository read-only and report abandoned work:

- plans whose frontmatter says active while their slice checkboxes say otherwise;
- `TODO`/`FIXME` older than a threshold;
- scaffolding with no caller;
- `IDEA_BOX` entries referencing paths that no longer exist.

Findings that name a **concrete artifact** - a file path, a plan slice, or an `IDEA_BOX` slug -
and are older than 14 days are appended to the repository's `IDEA_BOX.md` as slugged entries.
That closes the loop through the existing `plan_context_updater --resolved-ideas`, which
already marks entries DONE when the work lands. Everything else goes to the report only.

A GitHub issue is created **only** when the operator asks for a specific finding. Per decision
D6 in the parent plan, an agent creating public artifacts unprompted is not acceptable: a false
positive would live in the repository's issue history permanently.

## Inherited findings that must be fixed before implementation

**The gate contradicts the slice.** The parent plan's gate read "the scan is read-only, proven
by before/after `git status`" for a slice whose entire function is appending to a tracked
`IDEA_BOX.md`. As written that gate can only pass on a repository with zero findings - which is
the only case the test matrix listed, so the contradiction would have survived testing. Restate
as: **no writes outside `IDEA_BOX.md`**, proven by a before/after diff scoped to everything else.

**Second-order injection.** Findings are derived from repository content, and `IDEA_BOX.md` is
read by `plan_context_loader.py` and injected into future sessions. A `TODO` comment containing
an injection payload would therefore reach a future session's context by a laundered route -
the same defect class the 2026-07-25 hotfix closed at the prompt. Findings are written as
quoted, escaped, length-bounded text recording the source `file:line`, never as copied prose.

## Approval gate

This document records deferred scope. It authorizes nothing. Run through `/fwf` or `/fwp`
before implementation.
