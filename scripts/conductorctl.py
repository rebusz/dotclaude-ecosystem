"""Command-line interface for TruthDeck Conductor.

Exposes status, enqueue, authorize, claim, heartbeat, checkpoint, complete, cancel, reconcile, export, and doctor.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import argparse
import hmac
import json
import pathlib
import sys
import uuid

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.conductor_commands import ConductorCommandProcessor  # noqa: E402
from scripts.conductor_model import CommandEnvelope  # noqa: E402
from scripts.conductor_store import (  # noqa: E402
    ConductorStore,
    read_store_diagnostics,
    read_store_status,
)


def main(argv: list[str] | None = None) -> int:
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

    # reconcile
    p_rec = subparsers.add_parser("reconcile", help="Reconcile expired leases and dead processes")
    p_rec.add_argument("--dry-run", action="store_true")

    # export
    p_exp = subparsers.add_parser("export", help="Export JSONL event ledger")
    p_exp.add_argument("--output", required=True)

    args = parser.parse_args(argv)

    if args.command == "status":
        result = read_store_status()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("TruthDeck Conductor Status:")
            print(f"  Store State: {result.get('store_state')}")
            print(f"  Leader ID: {result.get('leader_id')}")
            print(f"  DB Path: {result.get('db_path')}")
            print(f"  Total Work Items: {result.get('total_work_items')}")
            print(f"  Summary: {json.dumps(result.get('state_summary'))}")
        return 0

    elif args.command == "doctor":
        info = read_store_diagnostics()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print("Conductor Doctor Diagnostics:")
            for k, v in info.items():
                print(f"  {k}: {v}")
        return 0

    elif args.command == "authorize":
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("Error: authorization requires an attached interactive console TTY", file=sys.stderr)
            return 1
        expected = f"GO {args.work_item_id}"
        confirmation = input(f"Type {expected} to authorize this exact WorkItem: ")
        if not hmac.compare_digest(confirmation.strip(), expected):
            print("Error: exact interactive GO confirmation was not entered", file=sys.stderr)
            return 1
        store = ConductorStore()
        processor = ConductorCommandProcessor(store=store)
        result = processor.grant_interactive_operator_authorization(
            args.work_item_id,
            operator_identity="operator_cli",
        )
        print(json.dumps(result, indent=2))
        return 0

    store = ConductorStore()
    processor = ConductorCommandProcessor(store=store)

    if args.command == "enqueue":
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
