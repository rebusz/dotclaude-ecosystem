"""Command-line interface for TruthDeck Conductor.

Exposes status, enqueue, authorize, claim, heartbeat, checkpoint, complete, cancel, reconcile, export, and doctor.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import pathlib
import sys
import uuid

import psutil

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.conductor_commands import ConductorCommandProcessor  # noqa: E402
from scripts.conductor_model import CommandEnvelope  # noqa: E402
from scripts.conductor_resources import resolve_resource_key  # noqa: E402
from scripts.conductor_store import (  # noqa: E402
    ConductorStore,
    read_all_pools_live,
    read_host_resource_status,
    read_resource_live_snapshot,
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

    p_resource_live = subparsers.add_parser(
        "resource-live",
        help="Show live host resource admission status without writing receipts",
    )
    p_resource_live.add_argument(
        "--resource-key",
        default="host:heavy",
        help="Resource key (default: host:heavy)",
    )
    p_resource_live.add_argument(
        "--all",
        action="store_true",
        help="Show live status for all resource pools",
    )
    p_resource_live.add_argument("--json", action="store_true", help="Output raw JSON")

    p_resource_status = subparsers.add_parser("resource-status", help="Show host resource admission status")
    p_resource_status.add_argument("--json", action="store_true", help="Output raw JSON")

    p_resource_request = subparsers.add_parser("resource-request", help="Request host resource capacity")
    p_resource_request.add_argument(
        "--purpose",
        choices=[
            "pytest_full",
            "pytest_heavy",
            "pytest_focused",
            "playwright",
            "cdp_provider",
            "cdp_perplexity",
            "cdp_chatgpt",
            "cdp_gemini",
        ],
        required=True,
    )
    p_resource_request.add_argument("--attempt-id", required=True)
    p_resource_request.add_argument("--agent-instance", required=True)
    p_resource_request.add_argument("--priority", type=int, default=50)
    p_resource_request.add_argument("--idempotency-key")
    p_resource_request.add_argument("--parent-lease-id")
    p_resource_request.add_argument(
        "--resource-key",
        default=None,
        help="Resource pool key (default: host:heavy or derived from role/purpose)",
    )
    p_resource_request.add_argument(
        "--slot-key",
        default="",
        help="Optional slot key (e.g. model name for per-model exclusivity)",
    )
    p_resource_request.add_argument(
        "--role",
        default=None,
        help="CDP role (chrome_ppl, chrome_gpt, chrome_gemini)",
    )
    p_resource_request.add_argument("--owner-pid", type=int, default=None, help="Explicit owner process PID")
    p_resource_request.add_argument("--owner-start-time", type=float, default=None, help="Explicit owner process start time")

    p_resource_heartbeat = subparsers.add_parser("resource-heartbeat", help="Heartbeat a host resource lease")
    p_resource_heartbeat.add_argument("--lease-id", required=True)
    p_resource_heartbeat.add_argument("--sequence", type=int, required=True)

    p_resource_release = subparsers.add_parser("resource-release", help="Release a host resource request")
    p_resource_release.add_argument("--request-id", required=True)

    p_resource_recover = subparsers.add_parser(
        "resource-recover",
        help="Clear a RECOVERY_REQUIRED host resource request once its owner is proven gone",
    )
    p_resource_recover.add_argument("--request-id", required=True)
    p_resource_recover.add_argument(
        "--attest-owner-gone",
        action="store_true",
        help="Attest that the owner process is dead when Conductor has no child pid recorded",
    )
    p_resource_recover.add_argument(
        "--reason",
        default="",
        help="Why the owner is known to be gone (required with --attest-owner-gone)",
    )

    p_resource_reconcile = subparsers.add_parser("resource-reconcile", help="Reconcile expired host resource leases")
    p_resource_reconcile.add_argument("--resource-key", default=None, help="Specific pool key to reconcile")
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
        storage = read_storage_status()
        resource = read_host_resource_status()
        all_pools = read_all_pools_live()
        info.update({"storage": storage, "truthctl": truthctl, "resource": resource, "resources": all_pools})
        gate_blocked = (
            not resource.get("pool_exists")
            or not resource.get("enabled")
            or resource.get("recovery_required", 0) > 0
            or any(
                (not p.get("pool_present") or not p.get("enabled") or len(p.get("fenced", [])) > 0)
                for p in all_pools.values()
            )
        )
        if not truthctl.get("ok"):
            info["doctor_status"] = "BLOCKED"
        elif info.get("store_state") == "ABSENT":
            # Conductor is not initialised on this host. `doctor` is the command
            # an operator runs to discover exactly that, so it reports the fact
            # and exits 0. Nothing can be wedged in a store that does not exist.
            info["doctor_status"] = "ABSENT"
        elif gate_blocked:
            info["doctor_status"] = "BLOCKED"
        elif storage.get("status") == "BLOCKED":
            info["doctor_status"] = "BLOCKED"
        else:
            info["doctor_status"] = "PASS"
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print("Conductor Doctor Diagnostics:")
            for k, v in info.items():
                print(f"  {k}: {v}")
        # A wedged gate, a disabled pool, exhausted storage, or a bad truthctl
        # version all exit non-zero so a script gating on `doctor` fails closed.
        # Before 2026-08-27 this returned 0 for everything except truthctl, which
        # is why a five-hour RECOVERY_REQUIRED fence went unnoticed.
        return 0 if info["doctor_status"] in {"PASS", "ABSENT"} else 1

    if args.command == "resource-live":
        if args.all:
            results = read_all_pools_live()
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                for key, res in results.items():
                    print(f"Conductor Host Resource Live Status ({key}):")
                    print(f"  Pool Present: {res.get('pool_present')}")
                    print(f"  Capacity: {res.get('capacity')}")
                    print(f"  Enabled: {res.get('enabled')}")
                    print(f"  Live Counts: {json.dumps(res.get('live_counts'))}")
                    print(f"  Terminal Count: {res.get('terminal_count')}")
                    holder = res.get("holder")
                    holder_id = holder.get("request_id") if holder else "None"
                    print(f"  Holder: {holder_id}")
                    print(f"  Queue Depth: {len(res.get('queue', []))}")
                    print(f"  Fenced Count: {len(res.get('fenced', []))}")
                    print(f"  Quarantined Count: {len(res.get('quarantined', []))}")
                    print()
            return 0
        result = read_resource_live_snapshot(resource_key=args.resource_key)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Conductor Host Resource Live Status ({result.get('resource_key')}):")
            print(f"  Pool Present: {result.get('pool_present')}")
            print(f"  Capacity: {result.get('capacity')}")
            print(f"  Enabled: {result.get('enabled')}")
            print(f"  Live Counts: {json.dumps(result.get('live_counts'))}")
            print(f"  Terminal Count: {result.get('terminal_count')}")
            holder = result.get("holder")
            holder_id = holder.get("request_id") if holder else "None"
            print(f"  Holder: {holder_id}")
            print(f"  Queue Depth: {len(result.get('queue', []))}")
            print(f"  Fenced Count: {len(result.get('fenced', []))}")
            print(f"  Quarantined Count: {len(result.get('quarantined', []))}")
        return 0

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
        target_resource_key = resolve_resource_key(
            purpose=args.purpose,
            role=args.role,
            resource_key=args.resource_key,
        )
        owner_pid = getattr(args, "owner_pid", None)
        owner_start = getattr(args, "owner_start_time", None)
        owner_source = "UNRECORDED"
        if owner_pid is not None:
            owner_source = "EXPLICIT_VALIDATED"
        else:
            try:
                parent = psutil.Process(os.getpid()).parent()
                if parent:
                    owner_pid = parent.pid
                    owner_start = parent.create_time()
                    owner_source = "CALLER_PARENT"
            except (OSError, psutil.Error):
                pass

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
                "resource_key": target_resource_key,
                "slot_key": args.slot_key or "",
                "role": args.role,
                "owner_process_pid": owner_pid,
                "owner_process_start_time": owner_start,
                "owner_identity_source": owner_source,
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

    elif args.command == "resource-recover":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="resource_recover",
            payload={
                "request_id": args.request_id,
                "operator_attestation": args.attest_owner_gone,
                "reason": args.reason,
                "actor": "operator_cli",
            },
            idempotency_key=f"idemp_resource_recover_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0 if receipt.status == "SUCCESS" else 1

    elif args.command == "resource-reconcile":
        envelope = CommandEnvelope(
            command_id=f"cmd_{uuid.uuid4().hex[:12]}",
            command_type="resource_reconcile",
            payload={"dry_run": args.dry_run, "resource_key": getattr(args, "resource_key", None)},
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
