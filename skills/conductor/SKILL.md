---
name: conductor
description: TruthDeck Conductor local cross-repository work queue coordinator and dispatch engine.
---

# TruthDeck Conductor Operator Skill

TruthDeck Conductor is a port-free, single-writer local work queue coordinator for managing cross-repository agent tasks, host capabilities, and execution leases.

## Commands

- `python scripts/conductorctl.py status`: View current queue status and active leader PID.
- `python scripts/conductorctl.py doctor`: Run system diagnostics and host doctor probe.
- `python scripts/conductorctl.py enqueue --title "Task" --repo-id repo --repo-path /path --plan-path plan.md`: Enqueue a WorkItem.
- `python scripts/conductorctl.py authorize --work-item-id wi_123 --interactive`: Grant interactive operator authorization for R2/R3 tasks.
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
2. **Interactive Operator GO Provenance (D1/M1):** Operator authorization for R2/R3 tasks MUST originate from an interactive prompt session (`interactive_provenance_proven = True`). Non-interactive channels (argv, env vars, inbox envelope) CANNOT bypass operator GO.
3. **Fail-Closed Leases:** WorkItems claimed by host agents require heartbeat renewals within TTL (default 300s). Expired leases automatically transition to `RECOVERY_REQUIRED`.
