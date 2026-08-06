---
title: Worktree Task-Close Lifecycle Containment
date: 2026-08-06
status: in-progress
status_detail: s2-local-validation-complete-review-pending
risk: R1
phase: implementation
repos: [dotclaude-ecosystem]
tags: [worktrees, session-lifecycle, custody, disk-hygiene]
related:
  - design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md
  - design/plans/2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md
---

# Worktree Task-Close Lifecycle Containment

## Decision

Create a linked lifecycle slice. Do not reopen the shipped session-lifecycle
plan and do not make the report-only `git_hygiene.py` janitor an implicit
deleter. The existing hook already binds a session to an exact worktree, but
`SessionEnd` currently reaps only lifecycle state files. This slice records an
exact worktree terminal disposition at session close and supplies a separate,
hash-gated apply path for later cleanup.

## Why / current evidence

- `D:\APPS` currently contains 809 registered worktrees; Tsignal alone has 497
  worktrees and 710 local branches.
- Tsignal grew from 98 worktrees on 2026-07-06 to 463 on 2026-08-04.
- The last hygiene report preserved 443/463 worktrees and found 250 design
  documents whose only carrier was an unmerged local branch.
- Creation automation exists, but task close does not persist ownership,
  disposition, or a deletion-safe receipt.
- A daily full scan is expensive and cannot stop continued creation.

## Scope and boundaries

Risk is R1 because the default path is advisory local tooling. No broker,
trading runtime, application persistence, or live-decision state is touched.

The default hook path is **record-only** and fail-open. It never removes a
worktree or branch. Physical removal is destructive and requires all of:

1. a terminal receipt whose disposition is eligible;
2. a fresh snapshot matching the receipt's repo, path, HEAD, branch, clean,
   unlocked, non-primary, and merged/detached facts;
3. the exact authorization `GO WORKTREE APPLY <receipt-sha256>`;
4. an explicit CLI `apply` invocation outside the target worktree.

Dirty, untracked, locked, primary, unknown, or unmerged worktrees are always
preserved. A clean unmerged branch may lose only its checkout after a separate
custody/handoff feature lands; this slice classifies it but does not remove it.

## Terminal dispositions

| Disposition | Meaning | Default action |
|---|---|---|
| `PRESERVE_PRIMARY` | canonical primary checkout | preserve |
| `DIRTY_CUSTODY` | tracked or untracked work exists | preserve + manifest |
| `LOCKED_CUSTODY` | worktree is locked | preserve + owner review |
| `COMMITTED_UNMERGED_CUSTODY` | clean branch not contained in base | preserve + handoff |
| `DETACHED_UNMERGED_CUSTODY` | clean detached checkout not contained in base | preserve + handoff |
| `ELIGIBLE_MERGED_REMOVE` | clean, unlocked, non-primary branch contained in base | receipt only |
| `ELIGIBLE_DETACHED_REMOVE` | clean, unlocked, non-primary detached checkout contained in base | receipt only |
| `UNKNOWN_PRESERVE` | any fact could not be proven | preserve |

## Implementation slices

### S0 - bounded registry and close receipt

- Add a deterministic worktree classifier and atomic bounded records under
  `~/.claude/state/worktree_lifecycle/`.
- Record session owner/start facts after the existing write-once binding.
- Record terminal disposition after the existing SessionEnd evidence verdict.
- Include a canonical JSON SHA-256 over the immutable receipt payload.
- Never fail or block the host hook if worktree capture fails.

### S1 - exact apply path

- Add `inspect` and `apply` CLI commands.
- `apply` revalidates all facts and refuses stale, dirty, locked, primary,
  unknown, or unmerged targets.
- Remove only the exact worktree from the receipt. Delete a named local branch
  only via `git branch -d` after worktree removal; detached targets have no
  branch deletion.
- Persist before/after commands and a mutation receipt.

### S2 - deployment and runtime acceptance

- Focused unit tests and full lifecycle regression tests pass.
- Existing installer-managed adapters import the new sibling module from the
  same canonical checkout; no second deployed copy or drift surface is added.
- A disposable linked worktree proves start record, terminal receipt, stale
  refusal, and one exact-gated eligible removal.

### S3 - creation canonicalization and weekly audit

- Add a separate bounded creator using a configured per-repo worktree root.
- Route new Codex/Claude/Cursor implementation worktrees through it where the
  host exposes a supported creation seam.
- Replace the daily 06:30 full scan with a weekly off-hours incremental audit
  only after seven days of registry evidence and a declared wall-time budget.

## Definition of done

- Every registered terminal session writes one bounded worktree disposition.
- No hook-triggered code removes a worktree or branch.
- `apply` refuses every unsafe/stale case and accepts only an exact hash-gated,
  freshly revalidated eligible target.
- No primary, dirty, untracked, locked, unknown, or unmerged work is removed.
- A disposable live acceptance proves the real linked-worktree path.
- New terminal tasks leave zero eligible checkout after gated close cleanup.
- Counts trend down for seven days and the weekly audit stays outside market
  hours and within its I/O budget.

## Rollback

Remove the two fail-open recorder calls and the deployed module. Existing
session binding, verdict, router output, and hook schemas remain unchanged.
Recorded JSON files are advisory receipts and may be archived after rollback.

## Current gate

S0/S1 implementation and S2 local validation are complete. Focused lifecycle
regression: `78 passed, 12 subtests passed`; Ruff and compileall are clean. A
real disposable linked-worktree acceptance is included in that suite: the
receipt classified one merged branch,
refused implicit authority, and the exact token removed only the temporary
target and its merged branch while persisting a mutation receipt.

No registered user worktree has been removed. Review, draft PR, and exact-head
evidence remain before installer activation or any user-worktree cleanup.

The recorder uses a direct current-checkout git-dir probe rather than scanning
the full worktree registry. On the 497-worktree Tsignal repo the full list took
about 969 ms, while the bounded direct probe took 52.8 ms against a 350 ms hook
budget.
