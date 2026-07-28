# WatchF Shared Rules

## What This Is

Stock scanner and market intelligence layer for the Tsignal ecosystem. WatchF discovers opportunities and generates candidates; Tsignal executes them. WatchF is advisory-only towards Tsignal and never writes live execution or order state directly.

## Execution Access And The Live Gate

- **Agents implement, edit, and test all scanner, AI, feed, and bridge code.**
- **Advisory role**: WatchF produces candidate signals only; execution authority stays with Tsignal.
- **Signal approval**: Swing/Long signals require human operator approval; scalp/intra signals can auto-send via bridge envelope.
- Bridge events carry `source`, `schema_version`, and `timestamp_utc`.
- Atomic write-temp-rename for all bridge files (`data/bridge/watchf/`).

## AI & External Services

- AI calls must go through OpenRouter or approved browser/subscription runtimes - never direct Anthropic REST API.
- Trading Edge (TE) session auth is shared with Tsignal (same cookies and credentials; keep in sync).
- CDP fleet management follows active CDP runbooks (`design/plans/2026-07-22_cdp_fleet_job_manager_r2.md`).

## Runtime Invariants

- No blocking I/O on scanner hot paths.
- Canonical ports: React GUI `7175`, WebSocket `7176`, Basket callback `7177`, Tsignal target `6101`, Obsidian Gemma `5100`.
- Do not use legacy WatchF/Vite ports `5174`, `5178`, or `5179`. Do not send bridge traffic to legacy `9001`.
