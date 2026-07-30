---
name: conductor
description: TruthDeck Conductor local cross-repository work queue coordinator and dispatch engine.
---

# TruthDeck Conductor Operator Skill

TruthDeck Conductor is a port-free, single-writer local work queue coordinator for managing cross-repository agent tasks, host capabilities, and execution leases.

## Commands

- `python scripts/conductorctl.py status`: View current queue status and active leader PID.
- `python scripts/conductorctl.py doctor`: Run system diagnostics and host doctor probe.
- `python scripts/conductorctl.py resource-status --json`: Read the durable `host:heavy` pool, queue, recovery state, and storage growth.
- `python scripts/conductorctl.py resource-request --purpose pytest_full --attempt-id <id> --agent-instance <id>`: Request the capacity-one heavy lease.
- `python scripts/conductorctl.py pytest --repo <repo> --python <python> --attempt-id <id> --agent-instance <id> -- <pytest args>`: Run only the bounded `<python> -m pytest` adapter (`--heavy` promotes a focused invocation).
- `python scripts/conductorctl.py enqueue --title "Task" --repo-id repo --repo-path /path --plan-path plan.md`: Enqueue a WorkItem.
- `python scripts/conductorctl.py authorize --work-item-id wi_123 --interactive`: From an attached console, type the exact prompted `GO wi_123` phrase to grant R2/R3 authorization.
- `python scripts/conductorctl.py reconcile`: Reconcile expired leases and dead process claims.
- `python scripts/conductorctl.py export --output export.jsonl`: Export durable event ledger.

## Host Capability Classifications

| Host | Cooperative Client | Session Event Lifecycle | Autonomous Dispatch |
| :--- | :--- | :--- | :--- |
| **Claude Code** | PROVEN | PROVEN | PROVEN |
| **Kimi CLI** | PROVEN | PROVEN | PROVEN |
| **Codex** | PROVEN | HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT | HOLD_UNSUPPORTED |
| **Cursor** | PROVEN | PROVEN | HOLD_UNSUPPORTED |
| **Antigravity IDE** | PROVEN | HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT | HOLD_UNSUPPORTED |
| **`agy` CLI** | HOLD_NOT_INSTALLED | HOLD_NOT_INSTALLED | HOLD_NOT_INSTALLED |

## Security & Scoping Rules

1. **Port-Free Architecture:** Conductor communicates exclusively via single-writer SQLite WAL (`~/.conductor/conductor.db`) and atomic inbox file envelopes (`~/.conductor/inbox/`). No open network ports are listened on (`TDCONDUCTOR_*` environment variables).
2. **Interactive Operator GO Provenance (D1/M1):** Operator authorization for R2/R3 tasks MUST originate from an interactive prompt session (`interactive_provenance_proven = True`) with a tty-verified coordinator handshake. Non-interactive channels (argv, env vars, inbox envelope, MCP, or agent assignment) CANNOT bypass operator GO.
3. **Fail-Closed Leases:** WorkItems claimed by host agents require heartbeat renewals within TTL (default 300s). Expired leases automatically transition to `RECOVERY_REQUIRED`; resource leases never auto-retry or release through ambiguity.
4. **Capacity-One Host Gate:** Cooperative heavy pytest, Playwright, and CDP-provider work requests Conductor's durable `host:heavy` lease before launch. A child may inherit one active attempt-scoped `TDCONDUCTOR_LEASE_ID`; a second inherited child, forged/stale token, or overlapping independent request is refused or queued.
5. **Bounded Process Contract:** The pytest adapter launches only `<python> -m pytest <args>` with `shell=False` and a retained `Popen` handle. WMI/CIM/process-list polling, preemption, and arbitrary shell execution are outside the skill.
6. **Storage Readback:** `status --json` exposes numeric ceilings and growth for `artifacts/`, `receipts/`, and `inbox/`; retention is report-only and never performs automatic deletion.
7. **Discovery Cadence:** Host discovery is event-triggered or manually invoked in this MVP; no background polling loop or implicit external rate-limit budget is created.
