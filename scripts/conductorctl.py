"""Command-line interface for TruthDeck Conductor.

Exposes status, enqueue, authorize, claim, heartbeat, checkpoint, complete, cancel, reconcile, export, and doctor.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import uuid

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.conductor_commands import ConductorCommandProcessor  # noqa: E402
from scripts.conductor_model import CommandEnvelope  # noqa: E402
from scripts.conductor_store import ConductorStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="TruthDeck Conductor CTL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Show Conductor status summary")
    p_status.add_argument("--json", action="store_true", help="Output raw JSON")

    # doctor
    p_doctor = subparsers.add_parser("doctor", help="Run Conductor system diagnostics")
    p_doctor.add_argument("--json", action="store_true", help="Output raw JSON")

    # enqueue
    p_enq = subparsers.add_parser("enqueue", help="Enqueue a WorkItem")
    p_enq.add_argument("--title", required=True)
    p_enq.add_argument("--repo-id", required=True)
    p_enq.add_argument("--repo-path", required=True)
    p_enq.add_argument("--plan-path", required=True)
    p_enq.add_argument("--risk-class", choices=["R0", "R1", "R2", "R3"], default="R1")
    p_enq.add_argument("--workflow", choices=["fwf", "fwp"], default="fwf")
    p_enq.add_argument("--priority", type=int, default=50)

    # authorize
    p_auth = subparsers.add_parser("authorize", help="Authorize R2/R3 WorkItem")
    p_auth.add_argument("--work-item-id", required=True)
    p_auth.add_argument("--interactive", action="store_true", help="Mark interactive operator provenance")

    # reconcile
    p_rec = subparsers.add_parser("reconcile", help="Reconcile expired leases and dead processes")
    p_rec.add_argument("--dry-run", action="store_true")

    # export
    p_exp = subparsers.add_parser("export", help="Export JSONL event ledger")
    p_exp.add_argument("--output", required=True)

    args = parser.parse_args()

    store = ConductorStore()
    processor = ConductorCommandProcessor(store=store)

    if args.command == "status":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="status",
            payload={},
            idempotency_key=f"idemp_status_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        if args.json:
            print(json.dumps(receipt.result, indent=2))
        else:
            print("TruthDeck Conductor Status:")
            print(f"  Leader ID: {receipt.result.get('leader_id')}")
            print(f"  DB Path: {receipt.result.get('db_path')}")
            print(f"  Total Work Items: {receipt.result.get('total_work_items')}")
            print(f"  Summary: {json.dumps(receipt.result.get('state_summary'))}")

    elif args.command == "doctor":
        is_leader = store.acquire_leader_lock("primary_coordinator")
        info = {
            "root_dir": str(store.root_dir),
            "db_path": str(store.db_path),
            "db_exists": store.db_path.exists(),
            "inbox_exists": store.inbox_dir.exists(),
            "receipts_exists": store.receipts_dir.exists(),
            "is_leader": is_leader,
        }
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print("Conductor Doctor Diagnostics:")
            for k, v in info.items():
                print(f"  {k}: {v}")

    elif args.command == "enqueue":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="enqueue",
            payload={
                "idempotency_key": f"key_{uuid.uuid4().hex[:12]}",
                "title": args.title,
                "repo_id": args.repo_id,
                "repo_path": args.repo_path,
                "plan_path": args.plan_path,
                "risk_class": args.risk_class,
                "workflow": args.workflow,
                "requested_terminal_stage": "merged",
                "job_kind": "engineering_plan_lifecycle",
                "priority": args.priority,
                "created_by": "operator_cli",
            },
            idempotency_key=f"idemp_enq_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        print(json.dumps(receipt.to_dict(), indent=2))

    elif args.command == "authorize":
        if args.interactive:
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                print("Error: --interactive authorization requires an attached interactive console TTY", file=sys.stderr)
                sys.exit(1)

            session_token = f"tok_{uuid.uuid4().hex}"
            token_path = store.locks_dir / "interactive_session.token"
            token_data = {
                "token": session_token,
                "created_at_timestamp": time.time(),
                "pid": os.getpid(),
            }
            token_path.write_text(json.dumps(token_data), encoding="utf-8")
            channel = "interactive_console"
        else:
            session_token = None
            channel = "argv"

        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="authorize",
            payload={
                "work_item_id": args.work_item_id,
                "interactive_provenance_proven": args.interactive,
                "channel": channel,
                "session_token": session_token,
                "operator_identity": "operator_cli",
            },
            idempotency_key=f"idemp_auth_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope, envelope_source="direct")
        print(json.dumps(receipt.to_dict(), indent=2))

    elif args.command == "reconcile":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="reconcile",
            payload={"dry_run": args.dry_run},
            idempotency_key=f"idemp_rec_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        print(json.dumps(receipt.to_dict(), indent=2))

    elif args.command == "export":
        out_path = store.export_jsonl(args.output)
        print(f"Exported event ledger to {out_path}")


if __name__ == "__main__":
    main()
