# TSU Shared Rules

## What This Is

Trading System Unit (TSU) execution runtime. Stability and safety outrank all other concerns. TSU is the execution authority for its configured markets; external advisory inputs (WatchF, TsignalLAB, Obsidian Flow) never write live decision or order state directly.

## Execution Access And The Live Gate

- **Agents implement, fix, and test the execution surface** - broker adapters, order path, arming, custody verification, emergency exit - across all account types. Refusing an execution task on "agents cannot touch order path" grounds is a defect; code-vs-trigger model applies.
- **Paper and live are ONE code path.** Practice and live account lanes are identical under the execution architecture. Safety rules, guards, presets, sizing policy, lifecycle rules, custody rules, and execution semantics are shared by default. The only allowed difference is broker routing/identity selection: IBKR account login plus port, or ProjectX/Topstep selected account. Any other divergence requires explicit operator approval, tests, documented rationale, and rollback. See `agent-rules/refs/paper-live-parity.md`.
- **Live read is free**: connecting to real accounts read-only for auth, entitlements, connectivity, or position/order readback needs no extra approval.
- **The trigger is gated**: order submit/modify/cancel, arming automation, or flipping enablement flags on REAL-MONEY or TOPSTEP COMBINE accounts requires explicit just-in-time operator GO. Paper and practice submits are free.
- Emergency-off and flatten paths must behave identically on all surfaces and default ON.

## Runtime Invariants

- No blocking I/O on tick callbacks.
- No PySide6/Qt anywhere repo-wide.
- SQLite WAL is the write master; cloud/network is never on the live path.
- Single journal writer; all disk I/O off the event loop.
- Bridge events carry idempotency key, schema version, timestamp, and provenance.
- Atomic write-temp-rename for all persistence files.
- No dynamic imports (`importlib`, `__import__`) repo-wide.
- All timing constants in manifest - no raw literals in code.
