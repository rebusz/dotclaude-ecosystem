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
    read_storage_status,
    read_store_diagnostics,
    read_store_status,
)
from scripts.conductor_truthdeck import check_truthctl_version  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TruthDeck Conductor CTL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Show Conductor status summary")
    p_status.add_argument("--json", action="store_true", help="Output raw JSON")

    # doctor
    p_doctor = subparsers.add_parser("doctor", help="Run Conductor system diagnostics")
    p_doctor.add_argument("--json", action="store_true", help="Output raw JSON")

    p_resource_status = subparsers.add_parser("resource-status", help="Show host resource admission status")
    p_resource_status.add_argument("--json", action="store_true", help="Output raw JSON")

    p_resource_request = subparsers.add_parser("resource-request", help="Request host resource capacity")
    p_resource_request.add_argument("--purpose", choices=["pytest_full", "pytest_heavy", "playwright", "cdp_provider"], required=True)
    p_resource_request.add_argument("--attempt-id", required=True)
    p_resource_request.add_argument("--agent-instance", required=True)
    p_resource_request.add_argument("--priority", type=int, default=50)
    p_resource_request.add_argument("--idempotency-key")
    p_resource_request.add_argument("--parent-lease-id")

    p_resource_heartbeat = subparsers.add_parser("resource-heartbeat", help="Heartbeat a host resource lease")
    p_resource_heartbeat.add_argument("--lease-id", required=True)
    p_resource_heartbeat.add_argument("--sequence", type=int, required=True)

    p_resource_release = subparsers.add_parser("resource-release", help="Release a host resource request")
    p_resource_release.add_argument("--request-id", required=True)

    p_resource_reconcile = subparsers.add_parser("resource-reconcile", help="Reconcile expired host resource leases")
    p_resource_reconcile.add_argument("--dry-run", action="store_true")

    p_pytest = subparsers.add_parser("pytest", help="Run bounded pytest through host admission")
    p_pytest.add_argument("--python", "--python-executable", dest="python_executable", required=True)
    p_pytest.add_argument("--repo", "--cwd", dest="cwd", required=True)
    p_pytest.add_argument("--attempt-id", required=True)
    p_pytest.add_argument("--agent-instance", required=True)
    p_pytest.add_argument("--heavy", action="store_true", help="Promote a focused invocation to the heavy lease gate")
    p_pytest.add_argument("pytest_args", nargs=argparse.REMAINDER)

    # enqueue
    p_enq = subparsers.add_parser("enqueue", help="Enqueue a WorkItem")
    p_enq.add_argument("--title", required=True)
    p_enq.add_argument("--repo-id", required=True)
    p_enq.add_argument("--repo-path", required=True)
    p_enq.add_argument("--plan-path", required=True)
    p_enq.add_argument("--risk-class", choices=["R0", "R1", "R2", "R3"], default="R1")
    p_enq.add_argument("--workflow", choices=["fwf", "fwp"], default="fwf")
    p_enq.add_argument("--priority", type=int, default=50)
    p_enq.add_argument("--context-digest-sha256", default="", help="Digest of the bound CONTEXT.md packet")

    # authorize
    p_auth = subparsers.add_parser("authorize", help="Authorize R2/R3 WorkItem")
    p_auth.add_argument("--work-item-id", required=True)
    p_auth.add_argument("--context-digest-sha256", default="", help="Optional digest of the bound CONTEXT.md packet")

    # reconcile
    p_rec = subparsers.add_parser("reconcile", help="Reconcile expired leases and dead processes")
    p_rec.add_argument("--dry-run", action="store_true")

    # export
    p_exp = subparsers.add_parser("export", help="Export JSONL event ledger")
    p_exp.add_argument("--output", required=True)

    args = parser.parse_args(argv)

    if args.command == "status":
        result = read_store_status()
        result["storage"] = read_storage_status()
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

    if args.command == "doctor":
        info = read_store_diagnostics()
        truthctl = check_truthctl_version()
        info.update({"storage": read_storage_status(), "truthctl": truthctl})
        info["doctor_status"] = "PASS" if truthctl["ok"] else "BLOCKED"
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print("Conductor Doctor Diagnostics:")
            for k, v in info.items():
                print(f"  {k}: {v}")
        return 0 if truthctl["ok"] else 1

    if args.command == "authorize":
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
            context_digest_sha256=args.context_digest_sha256 or None,
        )
        print(json.dumps(result, indent=2))
        return 0

    store = ConductorStore()
    processor = ConductorCommandProcessor(store=store)

    if args.command == "resource-status":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="resource_status",
            payload={},
            idempotency_key=f"idemp_resource_status_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        print(json.dumps(receipt.result if args.json else receipt.to_dict(), indent=2))
        return 0

    elif args.command == "resource-request":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="resource_request",
            payload={
                "purpose": args.purpose,
                "attempt_id": args.attempt_id,
                "agent_instance": args.agent_instance,
                "priority": args.priority,
                "idempotency_key": args.idempotency_key,
                "parent_lease_id": args.parent_lease_id,
            },
            idempotency_key=f"idemp_resource_request_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0

    elif args.command == "resource-heartbeat":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="resource_heartbeat",
            payload={"lease_id": args.lease_id, "sequence": args.sequence},
            idempotency_key=f"idemp_resource_heartbeat_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0

    elif args.command == "resource-release":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="resource_release",
            payload={"request_id": args.request_id},
            idempotency_key=f"idemp_resource_release_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0

    elif args.command == "resource-reconcile":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="resource_reconcile",
            payload={"dry_run": args.dry_run},
            idempotency_key=f"idemp_resource_reconcile_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0

    elif args.command == "pytest":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="pytest",
            payload={
                "python_executable": args.python_executable,
                "cwd": args.cwd,
                "attempt_id": args.attempt_id,
                "agent_instance": args.agent_instance,
                "pytest_args": args.pytest_args,
                "force_heavy": args.heavy,
            },
            idempotency_key=f"idemp_pytest_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0

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
                "context_digest_sha256": args.context_digest_sha256,
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
        return 0

    elif args.command == "export":
        out_path = store.export_jsonl(args.output)
        print(f"Exported event ledger to {out_path}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
