# Mechanical Write-Segregation Path Inventory

Date: 2026-06-29
Risk: R1 inventory-only
Parent plan: `design/plans/2026-06-29_mechanical_write_segregation_safety.md`

## Scope And Boundary

This is the first rollout slice from the mechanical write-segregation plan: inventory-only, no ACL writes, no repo writes under `D:/APPS/TSU` or `D:/APPS/Tsignal 5.0`, no process restarts, no broker/order-path access.

The purpose is to identify candidate path classes for a later dry-run ACL plan. This inventory is not an implementation plan and must be refreshed from live repo truth immediately before any R2/R3 permission change.

## Evidence Read

- `code-review-graph status --repo D:\APPS\TSU`
  - graph present: 2233 nodes, 34079 edges, 94 files
  - built on branch `master`, commit `240c1ed65731`
- `code-review-graph status --repo "D:\APPS\Tsignal 5.0"`
  - graph present: 2230461 nodes, 14523796 edges, 189642 files
  - warning: graph built on `main`, current checkout is `codex/pwr-trade-outcome-export-truth`; use current filesystem truth for this inventory
- `git -C D:\APPS\TSU status --short --branch`
  - branch `master...origin/master`
  - dirty: `design/tsu/plans/2026-06-29_tsu_brain_input_pipeline_master_plan.md`
- `git -C "D:\APPS\Tsignal 5.0" status --short --branch`
  - branch `codex/pwr-trade-outcome-export-truth...origin/codex/pwr-trade-outcome-export-truth`
  - dirty: `tsignal/ui/settings.json`
  - untracked: `design/calibration_proposals/2026-06-28_support_tag_bonus.md`, `design/plans/2026-06-29_unified_flat3_engine_tod_preset_plan.md`
- `Get-Content D:\APPS\TSU\AGENTS.md`
- `Get-Content "D:\APPS\Tsignal 5.0\AGENTS.md"`
- targeted `rg --files` path scans for broker, order, approve, journal, live, state, manifest, strategy, risk, lease, custody, ProjectX, IBKR, gateway, env, SQLite/WAL, data, config, runtime, supervisor, execution, and market-data terms
- shallow `Get-ChildItem` scans of `D:\APPS\TSU\data` and `D:\APPS\Tsignal 5.0\data`

## TSU Candidate Classes

| Path pattern | Initial class | Why |
| --- | --- | --- |
| `D:/APPS/TSU/.env` | `operator-only` | Credential and runtime environment material. Do not allow coding-agent writes. |
| `D:/APPS/TSU/data/live_state*.db*` | `live-brain-only` | SQLite/WAL live state; AGENTS states SQLite WAL is write master. |
| `D:/APPS/TSU/data/journal*/**` | `live-brain-only` | Journal destinations; AGENTS requires a single writer and disk I/O off the event loop. |
| `D:/APPS/TSU/data/interlock/**` | `live-brain-only` | Account/interlock lock files, including ProjectX account locks. |
| `D:/APPS/TSU/data/diagnostics/order_path.jsonl` | `live-brain-only` | Order-path diagnostics evidence; do not let advisory writes blur provenance. |
| `D:/APPS/TSU/data/bridge/**` | `operator-only` pending finer split | Bridge data must keep idempotency, schema version, timestamp, provenance. Later manifest should split advisory inboxes from live-owned outputs. |
| `D:/APPS/TSU/src/tsu/broker/**` | `operator-only` for agent writes | Broker adapters, ownership, custody, fake/live ports, ProjectX, IBKR. Requires explicit operator review before writes. |
| `D:/APPS/TSU/src/tsu/approve/**` | `operator-only` | Approval envelope, inbox, applier. Promotion seam authority lives here. |
| `D:/APPS/TSU/src/tsu/core/journal.py` | `operator-only` | Journal writer implementation. |
| `D:/APPS/TSU/src/tsu/core/live_state.py` | `operator-only` | Live state DB writer/reader implementation. |
| `D:/APPS/TSU/src/tsu/core/manifest.py` | `operator-only` | Runtime manifest authority and timing constants. |
| `D:/APPS/TSU/src/tsu/supervisor/**` | `operator-only` | Supervisor process and lock/health handling. |
| `D:/APPS/TSU/src/tsu/interlock/**` | `operator-only` | ProjectX boot/interlock gate code. |
| `D:/APPS/TSU/src/tsu/lanes/**` | `operator-only` | Lane runtime, approval gate, custody, swing order attachment. |
| `D:/APPS/TSU/src/tsu/risk/**` | `operator-only` | Risk governor, envelopes, leases. |
| `D:/APPS/TSU/src/tsu/strategy/**` | `operator-only` by default | Strategy/confidence/ledger/sizing are decision-path adjacent. Allow only plan-reviewed, non-live branches. |
| `D:/APPS/TSU/tsu-gui/src/components/*Broker*` and `*ConfigWrite*` | `operator-only` | GUI controls that can affect broker session or config-write routes. |
| `D:/APPS/TSU/design/**` | `write-allowed-for-agents` with review | Planning/audit/handoff docs are safe write targets unless a specific plan marks them frozen. |
| `D:/APPS/TSU/tests/**` | `write-allowed-for-agents` with review | Test edits are allowed for non-live work, but fixtures under broker/live paths should be reviewed. |

## Tsignal 5.0 Candidate Classes

| Path pattern | Initial class | Why |
| --- | --- | --- |
| `D:/APPS/Tsignal 5.0/.env` | `operator-only` | Credential and runtime environment material. |
| `D:/APPS/Tsignal 5.0/active_accounts.json` | `operator-only` | Active account selection/state material. |
| `D:/APPS/Tsignal 5.0/config/**` | `operator-only` pending finer split | Runtime/broker config; final manifest must classify individual files. |
| `D:/APPS/Tsignal 5.0/data/*.db*` | `live-brain-only` | SQLite/WAL state including `tsignal_state.db*`, `opusf_state.db`, `questrade_positions.db`, and basket/router state stores. |
| `D:/APPS/Tsignal 5.0/data/interlock/**` | `live-brain-only` | Account interlock locks. |
| `D:/APPS/Tsignal 5.0/data/bridge/executor/**` | `live-brain-only` | Executor diagnostics, lineage, and lifecycle state. |
| `D:/APPS/Tsignal 5.0/data/bridge/tsignal/**` | `live-brain-only` | Tsignal-owned bridge heartbeat/orchestrator/runtime outputs. |
| `D:/APPS/Tsignal 5.0/data/bridge/questrade/**` | `live-brain-only` | Broker-adjacent bridge surface. |
| `D:/APPS/Tsignal 5.0/data/bridge/watchf/**` | `read-only-for-agents` or `operator-only` | Advisory WatchF snapshots; writes should come from owning producer, not generic coding agents. |
| `D:/APPS/Tsignal 5.0/data/logs/**` | `live-brain-only` for runtime logs | Avoid advisory agents mutating runtime evidence. |
| `D:/APPS/Tsignal 5.0/tsignal_bot.py` and `tsignal_headless.py` | `operator-only` | Main live app entrypoints. |
| `D:/APPS/Tsignal 5.0/tsignal_webhook_handler.py` | `operator-only` | Webhook intake path. |
| `D:/APPS/Tsignal 5.0/tsignal_order_panel.py` and `tsignal_settings.py` | `operator-only` | Order/config UI surfaces. |
| `D:/APPS/Tsignal 5.0/tsignal/trading/**` | `operator-only` | Broker/order/risk/position/pure-signal execution modules. |
| `D:/APPS/Tsignal 5.0/tsignal/feed/questrade_*` | `operator-only` | Broker feed/auth paths. |
| `D:/APPS/Tsignal 5.0/tsignal/runtime/**` | `live-brain-only` or `operator-only` pending finer split | Runtime control/state path. |
| `D:/APPS/Tsignal 5.0/tsignal/interlock/**` | `operator-only` | Interlock code. |
| `D:/APPS/Tsignal 5.0/tsignal/ui/settings.json` | `operator-only` | Currently dirty in operator checkout; do not stage or overwrite. |
| `D:/APPS/Tsignal 5.0/tsignal-gui/src/app/components/order-entry*` | `operator-only` | Order entry UI. |
| `D:/APPS/Tsignal 5.0/tsignal-gui/src/app/panels/qt-rapid/*Order*` | `operator-only` | Order confirmation/table UI. |
| `D:/APPS/Tsignal 5.0/design/**` | `write-allowed-for-agents` with review | Planning/audit docs, except currently untracked operator files must not be touched. |
| `D:/APPS/Tsignal 5.0/tests/**` | `write-allowed-for-agents` with review | Tests are valid implementation surfaces, but live/broker integration tests require risk re-stamp. |
| `D:/APPS/Tsignal 5.0/data/`, `AI/`, `scratch/bench/models/` junction-backed assets | `operator-only` | Tsignal AGENTS says these are heavy assets/live DB/llama.cpp/GGUF junctions; do not allow generic agent writes. |

## Required Follow-Up Before ACL Dry-Run

1. Re-run this inventory from a quiesced state; both trading repos are currently dirty.
2. Resolve graph drift for Tsignal 5.0 or rely on a fresh targeted file scan; the current graph warns branch mismatch.
3. Review the first machine-readable path manifest at `design/security/write_segregation_path_manifest.json`; refresh it from quiesced repo truth before any dry-run ACL command generation.
4. Split `data/bridge/**` by producer ownership before denying writes; bridge directories are mixed advisory/live surfaces.
5. Confirm the exact Windows identity or launcher profile that represents coding/advisory agents.
6. Generate dry-run ACL apply and rollback commands only after the path manifest is reviewed.

## Current Gate

Implementation remains gated. The next allowed step is a dry-run manifest/ACL plan (R1/R2) that emits commands but does not apply them. Any real write-deny pilot or trading-repo apply is R2/R3 and needs explicit operator GO naming that apply step.
