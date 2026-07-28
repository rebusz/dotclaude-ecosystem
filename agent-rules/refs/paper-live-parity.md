# Paper/Live Parity Contract

Trigger: any change to execution, broker connectivity, order path, arming,
flatten, or account selection in a trading repo. Loaded on demand from the
Risk Classes section of `agent-rules/core.md`.

## Why this exists

Until 2026-07-28 the shared rules said "LLM agents never touch broker API or
order path". The intent was to protect real money. The effect was the opposite
of protection: agents built and validated everything on paper and detoured
around the live path, so the two surfaces drifted apart. Paper went green while
live stayed broken — bringing up a live IBKR account cost the operator days and
still failed. A rule that guards CODE produces untested live code. The gate
belongs on the TRIGGER (real-money submit/arm), not on the editor.

## The contract

1. **One path, two configurations.** Paper and live run the SAME execution code.
   Account id, port, credentials, entitlements and enablement are DATA loaded
   from config/env — never `if paper: ... else: ...` in an execution lane.
2. **Divergence is a ship-blocker.** A new `*_paper_only` / `*_practice_only`
   symbol, a live-only special case, or an execution change tested only on paper
   fails review. Fix the shared path instead of forking it.
3. **Differences that are legitimate** (a broker genuinely behaving differently
   in paper, e.g. absent fills or unsupported order types) are declared in ONE
   documented adapter seam with a named reason — not scattered inline branches.
4. **Live read is free.** Connecting to a real account for read-only work —
   auth, connectivity, entitlement checks, position/order/account readback,
   reconciliation diagnosis — needs no extra approval. Diagnosing live is
   expected, not exceptional.
5. **The trigger is gated.** Order submit/modify/cancel, arming automation, and
   flipping enablement flags on REAL-MONEY or TOPSTEP COMBINE accounts require
   explicit just-in-time operator GO. Paper/practice submits are free.
6. **Emergency-off and flatten are parity-critical.** They must work identically
   on both surfaces and default ON. A kill path proven only on paper is not
   proven.

## DoD for an execution slice

- Targeted tests drive the REAL shared path, including the failure/rollback
  branch — not a mock that skips the broker call.
- Paper validation: run it.
- Live parity evidence: a read-only readback against the live account when one
  is reachable (connection, account resolution, positions/orders round-trip),
  or an explicit `NO_SAMPLE: <reason>` line when it is not.
- Report names both surfaces. "Works on paper" alone is an incomplete DoD.

## What did NOT change

- Real-money and Combine submits/arming still need operator GO, per trigger.
- Advisory planes (WatchF, LAB, Obsidian Flow, Discord, OpusF) still never write
  live decision/order state; that boundary is about DATA FLOW, not about which
  files an agent may edit — see `agent-rules/refs/data-flow-seam.md`.
- R3 care (plan, blast radius, rollback, targeted validation) still applies to
  every execution change. Access is granted; discipline is not waived.
