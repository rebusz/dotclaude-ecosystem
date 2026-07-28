# Tsignal 5.0 Shared Rules

## What This Is

Live-trading system for US index futures (MNQ/MES) and SPY/QQQ options. Runtime
stability outranks every other concern. Tsignal is the execution authority;
WatchF, TsignalLAB, Obsidian Flow, Discord, and OpusF are advisory — they never
write live decision or order state.

## Execution Access And The Live Gate

- **Agents implement, fix, and test the whole execution surface** — broker
  adapters, order path, arming, flatten, reconciliation — on every account type.
  Refusing an execution task on "agents cannot touch the order path" grounds is
  itself a defect; the historical FB-04 phrasing is retired.
- **Paper and live are ONE code path.** Account, port, credentials, and
  enablement are configuration data. A `*_paper_only` / `*_practice_only` fork,
  a live-only special case, or an execution change validated only on paper is a
  ship-blocker. Legitimate broker-side differences live in one declared adapter
  seam with a named reason. Contract and slice DoD ->
  `agent-rules/refs/paper-live-parity.md`.
- **Live read is free**: connect to IBKR live or Topstep Combine read-only for
  auth, entitlement, connectivity, and position/order readback whenever it helps
  diagnosis.
- **The trigger is gated**: submitting/modifying/cancelling orders, arming
  automation, or flipping enablement on REAL-MONEY (incl. Questrade) or TOPSTEP
  COMBINE accounts requires explicit just-in-time operator GO. Paper and
  practice submits are free.
- Emergency-off and flatten must behave identically on both surfaces and default
  ON.
- R3 discipline still applies to every execution change: plan, blast radius,
  rollback, targeted tests that drive the real path including its failure branch.

## Retired PySide Shell — Do Not Open

`tsignal/ui/main_window.py`, and the window `python tsignal_bot.py` opens
without `--headless`, are a retired compatibility shell — not the product GUI.
Never launch, test, screenshot, or cite it as runtime/GUI evidence, and never
infer that a task mentioning "GUI" means it. The canonical backend entry point
is `python tsignal_bot.py --headless` (normally owned by EcosystemControl); the
only product GUI is React under `tsignal-gui/` at `http://127.0.0.1:6175`. No
general GUI/runtime/R3 GO authorizes opening the shell — only an operator-
authored retirement task may touch its widget code, and even that does not
authorize opening the window. Do not test or modify the React GUI unless the
operator puts frontend work in scope.

## Ports Are Contracts

- `D:/APPS/_shared/PORTS.md` first. React GUI `6175`, HTTP/API/webhooks `6101`,
  WebSocket `6102`, manual-levels webhook `6103`.
- Legacy `5173`, `5174`, `5178`, `5179`, `9001`, `9002` are dead.
- Never let Vite auto-select a port; Tsignal must fail loudly when `6175` is
  occupied.

## Runtime Invariants

- No blocking I/O in tick callbacks; no network work on the GUI thread (async or
  a thread pool); no `shared_memory` without profiler evidence.
- SQLite WAL is the write master — cloud/network is never the live path.
  Persistence files use atomic write-temp-rename.
- Bridge events carry idempotency key, schema version, timestamp, and
  provenance.
- Live decision changes still need operator approval.
- Never commit `.env`, credentials, or tokens.

## Delegated Landing (all platforms)

Applies to every implementing agent — Codex, Cursor, Cline, Kimi, Antigravity,
Claude subagents — and is mirrored into `AGENTS.md` and `.clinerules` because
those platforms do not read this file.

- R2/R3 code (order path, broker submit/arming, runtime, persistence,
  live-decision) lands via DRAFT PR + review gate: never direct-push to `main`,
  never self-merge. Direct-push is for R0 docs and CI-ignored paths only.
- Tests drive the REAL code path including the failure/rollback branch — no
  mocked event loop skipping the broker submit, no fixture faking
  restart-adoption, no test against a disabled path. Persistence/restart DoD is
  a round-trip.
- Report "done" only when committed AND pushed, naming branch/PR/SHA plus any
  PENDING/NO_SAMPLE DoD.

Full contract: `design/plans/DELEGATED_R3_EXECUTION_PROTOCOL.md`; grounded in
the 2026-07-24 S2a/T3/T4 direct-push incidents (S2a shipped two ship-blockers →
emergency-off #669).
