# Tokencost Decision: Native Logger Default

**Date:** 2026-06-29
**Parent plan:** `design/plans/2026-06-27_global_agent_workflow_os.md` section 6b.
**Decision:** Do not adopt the tokencost proxy as a default. Use the native logger path first.

## Rationale

The plan's default was already conservative: tokencost proxy adoption requires an analytics-only/routing-off mode and a prompt-preview-free or token-count-only persistence mode. Without those two proofs, a proxy creates three bad properties:

- a global routing intercept risk,
- secret-at-rest risk in `tracker.db` prompt previews,
- audit ambiguity if smart routing silently downgrades models.

The implemented native path is `scripts/session_cost_probe.py`. It records:

- global Claude/Codex kernel file metrics,
- managed-kernel presence checks,
- `sync_agent_rules.py --check` status,
- optional allowlisted usage/cost fields from an explicit JSON input.

It deliberately does not capture prompt previews.

## Current Evidence

- Baseline written: `design/baselines/workflow_os_a1_baseline.json`.
- Probe check passes against that baseline.
- This satisfies the Slice 0b decision gate without placing a proxy in front of Claude Code or Codex.

## Revisit Gate

Tokencost can be reconsidered only if a future review proves:

1. analytics-only mode with routing disabled,
2. prompt previews disabled or truncated to token counts only,
3. storage path is gitignored and excluded from backups,
4. mixed-session total-cost reduction is at least 15 percent with no quality regression.
