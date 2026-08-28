"""Command envelope processor and business logic for TruthDeck Conductor.

Processes versioned command envelopes from inbox and returns structured receipts.
Enforces authorization provenance boundaries and fail-closed security invariants.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from scripts.conductor_model import (
    Attempt,
    AuthorizationRecord,
    CommandEnvelope,
    EvidenceCheckpoint,
    Lease,
    Claim,
    Receipt,
    ReasonCode,
    WorkItem,
    WorkItemState,
)
from scripts.conductor_store import ConductorStore
from scripts.conductor_resources import HostResourceManager, resolve_resource_key


class ConductorCommandProcessor:
    """Processes command envelopes against a ConductorStore instance."""

    def __init__(self, store: ConductorStore):
        self.store = store
        self.resources = HostResourceManager(store=store)

    def process_envelope(self, envelope: CommandEnvelope, envelope_source: str = "direct") -> Receipt:
        """Process a command envelope with idempotency protection and source provenance verification."""
        existing_receipt = self.store.get_receipt(envelope.idempotency_key)
        if existing_receipt:
            return existing_receipt

        try:
            if envelope.command_type == "authorize":
                raise ValueError(
                    "Authorization refused: command envelopes cannot grant operator GO; "
                    "use the attached-TTY conductorctl authorize ceremony"
                )

            handler_name = f"_handle_{envelope.command_type}"
            handler = getattr(self, handler_name, None)
            if not handler:
                receipt = Receipt(
                    receipt_id=f"rcp_{uuid.uuid4().hex[:12]}",
                    command_id=envelope.command_id,
                    idempotency_key=envelope.idempotency_key,
                    status="REJECTED",
                    error_message=f"Unknown command type: {envelope.command_type}",
                )
                self.store.save_receipt(receipt)
                return receipt

            result = handler(envelope.payload)
            receipt = Receipt(
                receipt_id=f"rcp_{uuid.uuid4().hex[:12]}",
                command_id=envelope.command_id,
                idempotency_key=envelope.idempotency_key,
                status="SUCCESS",
                result=result,
            )
            self.store.save_receipt(receipt)
            return receipt

        except Exception as err:
            receipt = Receipt(
                receipt_id=f"rcp_{uuid.uuid4().hex[:12]}",
                command_id=envelope.command_id,
                idempotency_key=envelope.idempotency_key,
                status="ERROR",
                error_message=str(err),
            )
            self.store.save_receipt(receipt)
            return receipt

    def _handle_enqueue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Enqueue a WorkItem."""
        item = WorkItem.from_dict(payload)
        existing = self.store.get_work_item_by_idempotency_key(item.idempotency_key)
        if existing:
            return {"work_item_id": existing.work_item_id, "status": "ALREADY_EXISTS", "state": existing.state.value}

        store_item = WorkItem(
            work_item_id=item.work_item_id,
            idempotency_key=item.idempotency_key,
            title=item.title,
            repo_id=item.repo_id,
            repo_path=item.repo_path,
            plan_path=item.plan_path,
            risk_class=item.risk_class,
            workflow=item.workflow,
            requested_terminal_stage=item.requested_terminal_stage,
            job_kind=item.job_kind,
            priority=item.priority,
            dependency_ids=item.dependency_ids,
            authority_requirement=item.authority_requirement,
            execution_budget=item.execution_budget,
            scope_digest_sha256=item.scope_digest_sha256,
            context_digest_sha256=item.context_digest_sha256,
            state=WorkItemState.DISCOVERED,
            created_by=item.created_by,
        )

        self.store.save_work_item(store_item)
        self.store.transition_work_item_state(
            work_item_id=store_item.work_item_id,
            target_state=WorkItemState.QUEUED,
            actor=item.created_by,
            reason_code=ReasonCode.ADMISSION_OPERATOR_ENQUEUE.value,
        )

        return {"work_item_id": store_item.work_item_id, "status": "QUEUED", "state": WorkItemState.QUEUED.value}

    def grant_interactive_operator_authorization(
        self,
        work_item_id: str,
        *,
        operator_identity: str,
        context_digest_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Grant GO after the dedicated CLI has completed its attached-TTY ceremony.

        This seam is intentionally not reachable from command envelopes, MCP tools,
        inbox files, environment variables, or Host Adapter assignments.
        """
        item = self.store.get_work_item(work_item_id)
        if not item:
            raise ValueError(f"WorkItem {work_item_id} not found")

        if context_digest_sha256 is not None and context_digest_sha256 != item.context_digest_sha256:
            raise ValueError("Authorization refused: CONTEXT.md digest mismatch")

        auth_record = AuthorizationRecord(
            authorization_id=f"auth_{uuid.uuid4().hex[:12]}",
            work_item_id=work_item_id,
            scope_digest_sha256=item.scope_digest_sha256,
            risk_class=item.risk_class,
            authorized_workflow=item.workflow,
            permitted_terminal_stage=item.requested_terminal_stage,
            operator_identity=operator_identity,
            interactive_provenance_proven=True,
        )

        self.store.save_authorization(auth_record)

        if item.state in {WorkItemState.QUEUED, WorkItemState.HOLD}:
            self.store.transition_work_item_state(
                work_item_id=work_item_id,
                target_state=WorkItemState.READY,
                actor=auth_record.operator_identity,
                reason_code="AUTHORIZATION_GRANTED",
            )

        return {"authorization_id": auth_record.authorization_id, "status": "AUTHORIZED", "work_item_id": work_item_id}

    def _handle_claim(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Claim an eligible WorkItem and create an Attempt/Claim/Lease."""
        work_item_id = payload["work_item_id"]
        claimed_by_host = payload["claimed_by_host"]
        agent_instance = payload.get("agent_instance", f"inst_{uuid.uuid4().hex[:8]}")
        worktree_path = payload.get("worktree_path", "")
        branch_name = payload.get("branch_name", "main")
        base_head_sha = payload.get("base_head_sha", "")

        item = self.store.get_work_item(work_item_id)
        if not item:
            raise ValueError(f"WorkItem {work_item_id} not found")

        if item.state != WorkItemState.READY:
            raise ValueError(f"WorkItem {work_item_id} is in state {item.state.value}, not READY")

        # R2/R3 authorization check
        if item.risk_class in {"R2", "R3"}:
            auth = self.store.get_authorization(work_item_id)
            if not auth or not auth.interactive_provenance_proven:
                self.store.transition_work_item_state(
                    work_item_id=work_item_id,
                    target_state=WorkItemState.HOLD,
                    actor=claimed_by_host,
                    reason_code=ReasonCode.AUTHORIZATION_MISSING.value,
                )
                raise ValueError(f"WorkItem {work_item_id} requires operator R2/R3 authorization")

        attempt_id = f"at_{uuid.uuid4().hex[:12]}"
        claim_id = f"clm_{uuid.uuid4().hex[:12]}"
        lease_id = f"lse_{uuid.uuid4().hex[:12]}"

        attempt = Attempt(
            attempt_id=attempt_id,
            work_item_id=work_item_id,
            attempt_number=1,
            agent_host=claimed_by_host,
            agent_instance=agent_instance,
            adapter_version="1.0.0",
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_head_sha=base_head_sha,
            dispatch_idempotency_key=f"disp_{uuid.uuid4().hex[:12]}",
            status="IN_PROGRESS",
        )

        claim = Claim(
            claim_id=claim_id,
            work_item_id=work_item_id,
            attempt_id=attempt_id,
            claimed_by_host=claimed_by_host,
            lease_ttl_seconds=300,
        )

        expires_dt = datetime.now(timezone.utc) + timedelta(seconds=300)
        lease = Lease(
            lease_id=lease_id,
            attempt_id=attempt_id,
            agent_instance=agent_instance,
            heartbeat_sequence=1,
            expires_at_utc=expires_dt.isoformat(),
        )

        self.store.save_attempt(attempt)
        self.store.save_claim(claim)
        self.store.save_lease(lease)

        self.store.transition_work_item_state(
            work_item_id=work_item_id,
            target_state=WorkItemState.CLAIMED,
            actor=claimed_by_host,
            reason_code="WORK_ITEM_CLAIMED",
            attempt_id=attempt_id,
        )

        return {
            "work_item_id": work_item_id,
            "attempt_id": attempt_id,
            "claim_id": claim_id,
            "lease_id": lease_id,
            "status": "CLAIMED",
        }

    def _handle_heartbeat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extend lease heartbeat monotonic sequence."""
        lease_id = payload["lease_id"]
        attempt_id = payload["attempt_id"]
        sequence = payload["sequence"]
        ttl_seconds = payload.get("ttl_seconds", 300)

        now_dt = datetime.now(timezone.utc)
        expires_dt = now_dt + timedelta(seconds=ttl_seconds)

        lease = Lease(
            lease_id=lease_id,
            attempt_id=attempt_id,
            agent_instance=payload.get("agent_instance", "default_instance"),
            heartbeat_sequence=sequence,
            expires_at_utc=expires_dt.isoformat(),
            last_heartbeat_utc=now_dt.isoformat(),
        )

        self.store.save_lease(lease)
        return {"lease_id": lease_id, "heartbeat_sequence": sequence, "expires_at_utc": lease.expires_at_utc}

    def _handle_resource_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Admit or queue one named host resource consumer."""
        target_resource_key = resolve_resource_key(
            purpose=payload.get("purpose"),
            role=payload.get("role"),
            resource_key=payload.get("resource_key"),
        )
        manager = HostResourceManager(self.store, resource_key=target_resource_key)
        return manager.request(
            purpose=payload["purpose"],
            attempt_id=payload["attempt_id"],
            agent_instance=payload["agent_instance"],
            slot_key=payload.get("slot_key", ""),
            idempotency_key=payload.get("idempotency_key"),
            command_sha256=payload.get("command_sha256", ""),
            priority=int(payload.get("priority", 50)),
            parent_lease_id=payload.get("parent_lease_id"),
            environment=payload.get("environment"),
            lease_ttl_seconds=int(payload.get("lease_ttl_seconds", 300)),
            actor=payload.get("actor", "resource-command"),
        )

    def _handle_resource_heartbeat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.resources.heartbeat(
            payload["lease_id"],
            int(payload["sequence"]),
            lease_ttl_seconds=int(payload.get("lease_ttl_seconds", 300)),
        )

    def _handle_resource_release(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.resources.release(
            payload["request_id"],
            actor=payload.get("actor", "resource-command"),
            reason=payload.get("reason", "RESOURCE_RELEASED"),
        )

    def _handle_resource_recover(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Clear one RECOVERY_REQUIRED request once its owner is proven gone."""
        return self.resources.recover(
            payload["request_id"],
            operator_attestation=bool(payload.get("operator_attestation", False)),
            reason=payload.get("reason", ""),
            actor=payload.get("actor", "resource-command"),
        )

    def _handle_resource_reconcile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.resources.reconcile(dry_run=bool(payload.get("dry_run", False)))

    def _handle_resource_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.resources.status()

    def _handle_pytest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run the fixed Python-module pytest adapter through host admission."""
        return self.resources.run_bounded_pytest(
            python_executable=payload["python_executable"],
            pytest_args=payload.get("pytest_args", []),
            cwd=payload["cwd"],
            attempt_id=payload["attempt_id"],
            agent_instance=payload["agent_instance"],
            idempotency_key=payload.get("idempotency_key"),
            parent_lease_id=payload.get("parent_lease_id"),
            timeout_seconds=float(payload.get("timeout_seconds", 7200)),
            heartbeat_interval_seconds=float(payload.get("heartbeat_interval_seconds", 30)),
            base_environment=payload.get("environment"),
            force_heavy=bool(payload.get("force_heavy", False)),
        )

    def _handle_checkpoint(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Record an EvidenceCheckpoint."""
        checkpoint = EvidenceCheckpoint(
            checkpoint_id=f"chk_{uuid.uuid4().hex[:12]}",
            work_item_id=payload["work_item_id"],
            attempt_id=payload.get("attempt_id"),
            boundary=payload["boundary"],
            snapshot_path=payload["snapshot_path"],
            snapshot_sha256=payload["snapshot_sha256"],
            snapshot_id=payload["snapshot_id"],
            required_gate=payload.get("required_gate", "pre_dispatch"),
            observed_gate_state=payload.get("observed_gate_state", "PASS"),
            observed_head=payload.get("observed_head"),
        )
        self.store.save_checkpoint(checkpoint)
        return {"checkpoint_id": checkpoint.checkpoint_id, "status": "RECORDED"}

    def _handle_complete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Transition WorkItem to COMPLETED."""
        work_item_id = payload["work_item_id"]
        attempt_id = payload.get("attempt_id")
        actor = payload.get("actor", "host")

        self.store.transition_work_item_state(
            work_item_id=work_item_id,
            target_state=WorkItemState.COMPLETED,
            actor=actor,
            reason_code="WORK_ITEM_COMPLETED",
            attempt_id=attempt_id,
            details=payload.get("details"),
        )

        return {"work_item_id": work_item_id, "status": "COMPLETED"}

    def _handle_cancel(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Cancel a WorkItem."""
        work_item_id = payload["work_item_id"]
        actor = payload.get("actor", "operator")

        item = self.store.get_work_item(work_item_id)
        if not item:
            raise ValueError(f"WorkItem {work_item_id} not found")

        self.store.transition_work_item_state(
            work_item_id=work_item_id,
            target_state=WorkItemState.CANCELLED,
            actor=actor,
            reason_code=ReasonCode.OPERATOR_CANCELLED.value,
        )

        return {"work_item_id": work_item_id, "status": "CANCELLED"}

    def _handle_reconcile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Reconcile expired leases and dead coordinators (liveness requirement D1)."""
        dry_run = payload.get("dry_run", False)
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        expired_count = 0
        reconciled_items = []

        with self.store._connection() as conn:
            cur = conn.execute(
                """
                SELECT l.*, a.work_item_id, w.state as item_state
                FROM leases l
                JOIN attempts a ON l.attempt_id = a.attempt_id
                JOIN work_items w ON a.work_item_id = w.work_item_id
                WHERE l.expires_at_utc < ? AND w.state IN ('CLAIMED', 'DISPATCHING', 'RUNNING')
                """,
                (now_iso,),
            )
            rows = cur.fetchall()

            for row in rows:
                expired_count += 1
                work_item_id = row["work_item_id"]
                attempt_id = row["attempt_id"]
                reconciled_items.append(work_item_id)

                if not dry_run:
                    self.store.transition_work_item_state(
                        work_item_id=work_item_id,
                        target_state=WorkItemState.RECOVERY_REQUIRED,
                        actor="reconciler",
                        reason_code=ReasonCode.LEASE_EXPIRED.value,
                        attempt_id=attempt_id,
                    )

        return {"expired_count": expired_count, "reconciled_items": reconciled_items, "dry_run": dry_run}

    def _handle_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return status overview."""
        work_items = self.store.list_work_items()
        summary: Dict[str, int] = {}
        for item in work_items:
            st = item.state.value
            summary[st] = summary.get(st, 0) + 1

        return {
            "leader_id": self.store.leader_id,
            "db_path": str(self.store.db_path),
            "total_work_items": len(work_items),
            "state_summary": summary,
            "storage": self.store.storage_status(),
        }
