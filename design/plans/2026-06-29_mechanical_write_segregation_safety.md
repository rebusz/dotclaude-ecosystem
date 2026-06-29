# Mechanical Write-Segregation Safety Plan

**Grade:** R0 plan only. Implementation is R2/R3 and requires a separate explicit operator GO.
**Date:** 2026-06-29
**Parent plan:** `design/plans/2026-06-27_global_agent_workflow_os.md`, matrix amendment section 3.7.
**Scope:** OS-level write-deny design for coding/advisory agents around live trading config, runtime, strategy, and order-path files in `D:/APPS/TSU` and `D:/APPS/Tsignal 5.0`.

## Why

The Workflow OS plan's advisory boundary is correct but not sufficient by itself. The real leak is physical write capability: a coding agent with broad filesystem access can edit trading-adjacent files directly, bypassing provenance, validation, shadow, and signed operator GO.

This plan turns that boundary into a mechanical guard. It does not change live runtime behavior, broker APIs, order logic, strategy logic, or permissions yet.

## Non-Goals

- No broker API access.
- No order-path changes.
- No permission changes in this R0 slice.
- No per-repo `sync --write --repo` fan-out.
- No live process restart.
- No attempt to make advisory artifacts readable by the live brain.

## Proposed Control

1. Create a dedicated agent execution identity or launcher profile for coding/advisory sessions.
2. Deny write access for that identity to the live trading write surface:
   - order-path code and config,
   - strategy activation/config files,
   - runtime state and persistence files,
   - broker/session credential material,
   - live journal write locations unless explicitly read-only mirrored.
3. Preserve read access where needed for audits and reviews.
4. Route any advisory-to-live promotion through the existing gated seam:
   - candidate store,
   - validation gate,
   - shadow,
   - signed operator GO,
   - live brain owns live state.
5. Enforce `plane` and `risk_class` at capability load time before any skill or tool runs in a write-capable context.

## Candidate Write-Deny Surface

Final path inventory must be produced from live repo truth immediately before implementation. The likely starting set is:

- `D:/APPS/TSU`
  - runtime state directories,
  - order and broker integration modules,
  - strategy activation/config manifests,
  - SQLite/WAL live persistence paths,
  - journal writer destinations.
- `D:/APPS/Tsignal 5.0`
  - broker/order modules,
  - strategy runtime configs,
  - live persistence and journal outputs,
  - credential/session material.

The implementation plan must map each path to one of:

- `read-only-for-agents`,
- `write-allowed-for-agents`,
- `operator-only`,
- `live-brain-only`.

## Rollout Slices

1. **Inventory-only (R1):** generate a reviewed path manifest without changing permissions.
2. **Dry-run ACL plan (R1/R2):** emit exact ACL deltas and rollback commands, no writes.
3. **Pilot write-deny (R2/R3):** apply to a disposable agent identity or test directory first.
4. **Trading repo apply (R3):** operator GO, validated rollback, and proof that live runtime still starts while coding agents cannot write denied paths.

## Validation Contract

Before any real permission change:

- `git status` clean/understood for `D:/APPS/TSU`, `D:/APPS/Tsignal 5.0`, and `D:/dotclaude/dotclaude-ecosystem`.
- Path manifest reviewed against current repo truth.
- ACL dry-run artifact contains both apply and rollback commands.
- A write probe proves denied writes fail for the agent identity.
- A read probe proves allowed audit reads still work.
- TSU/Tsignal targeted validation commands are listed but not run against live money without operator GO.

After any real permission change:

- Write-deny probe fails closed on denied paths.
- Allowed dev/docs paths remain writable.
- Live runtime owner can still write required state.
- Rollback command has been tested on a harmless path.

## Review Gate

This plan must receive an engineering review before an implementation slice. The implementation slice must be re-stamped R2/R3 and cannot be executed from a bare "go"; it needs explicit operator GO naming the write-deny apply step.
