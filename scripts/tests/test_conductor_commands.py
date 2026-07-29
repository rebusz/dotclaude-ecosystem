"""Unit tests for ConductorCommandProcessor."""

from datetime import datetime, timedelta, timezone
import json
import pathlib
import time
import pytest

from scripts.conductor_commands import ConductorCommandProcessor
from scripts.conductor_model import CommandEnvelope, WorkItemState
from scripts.conductor_store import ConductorStore


@pytest.fixture
def processor(tmp_path: pathlib.Path) -> ConductorCommandProcessor:
    store = ConductorStore(root_dir=tmp_path)
    return ConductorCommandProcessor(store=store)


def test_enqueue_and_authorize_interactive_provenance(processor: ConductorCommandProcessor):
    # Enqueue
    enqueue_cmd = CommandEnvelope(
        command_id="cmd_enq_1",
        command_type="enqueue",
        payload={
            "idempotency_key": "idemp_r2_task",
            "title": "R2 Task",
            "repo_id": "dotclaude-ecosystem",
            "repo_path": "D:/dotclaude/dotclaude-ecosystem",
            "plan_path": "design/plans/test.md",
            "risk_class": "R2",
            "workflow": "fwf",
            "requested_terminal_stage": "merged",
            "job_kind": "engineering_plan_lifecycle",
            "created_by": "operator",
        },
        idempotency_key="idemp_enq_1",
    )

    rcp_enq = processor.process_envelope(enqueue_cmd)
    assert rcp_enq.status == "SUCCESS"
    work_item_id = rcp_enq.result["work_item_id"]

    # 1. Inbox envelope forgery attempt (Must be rejected)
    auth_inbox_cmd = CommandEnvelope(
        command_id="cmd_auth_inbox",
        command_type="authorize",
        payload={
            "work_item_id": work_item_id,
            "interactive_provenance_proven": True,
            "channel": "interactive_console",
        },
        idempotency_key="idemp_auth_inbox",
    )
    rcp_inbox = processor.process_envelope(auth_inbox_cmd, envelope_source="inbox_file")
    assert rcp_inbox.status == "ERROR"
    assert "refused" in rcp_inbox.error_message.lower()

    # 2. Direct call without session token lock (Must be rejected)
    auth_no_token = CommandEnvelope(
        command_id="cmd_auth_no_tok",
        command_type="authorize",
        payload={
            "work_item_id": work_item_id,
            "interactive_provenance_proven": True,
            "channel": "interactive_console",
            "session_token": "fake_token",
        },
        idempotency_key="idemp_auth_no_tok",
    )
    rcp_no_tok = processor.process_envelope(auth_no_token, envelope_source="direct")
    assert rcp_no_tok.status == "ERROR"
    assert "refused" in rcp_no_tok.error_message.lower()

    # 3. Direct call with valid single-use session token
    session_token = "tok_valid_123"
    token_path = processor.store.locks_dir / "interactive_session.token"
    token_path.write_text(json.dumps({"token": session_token, "created_at_timestamp": time.time()}), encoding="utf-8")

    auth_good_cmd = CommandEnvelope(
        command_id="cmd_auth_good",
        command_type="authorize",
        payload={
            "work_item_id": work_item_id,
            "interactive_provenance_proven": True,
            "channel": "interactive_console",
            "session_token": session_token,
            "operator_identity": "operator",
        },
        idempotency_key="idemp_auth_good",
    )
    rcp_good = processor.process_envelope(auth_good_cmd, envelope_source="direct")
    assert rcp_good.status == "SUCCESS"
    assert rcp_good.result["status"] == "AUTHORIZED"

    # Token file must be consumed (deleted) after single use
    assert not token_path.exists()

    item = processor.store.get_work_item(work_item_id)
    assert item.state == WorkItemState.READY


def test_claim_and_complete(processor: ConductorCommandProcessor):
    # Enqueue + Authorize R1 task
    enqueue_cmd = CommandEnvelope(
        command_id="cmd_enq_r1",
        command_type="enqueue",
        payload={
            "idempotency_key": "idemp_r1_task",
            "title": "R1 Task",
            "repo_id": "dotclaude-ecosystem",
            "repo_path": "D:/dotclaude/dotclaude-ecosystem",
            "plan_path": "design/plans/test.md",
            "risk_class": "R1",
            "workflow": "fwf",
            "requested_terminal_stage": "merged",
            "job_kind": "engineering_plan_lifecycle",
        },
        idempotency_key="idemp_enq_r1",
    )
    rcp_enq = processor.process_envelope(enqueue_cmd)
    work_item_id = rcp_enq.result["work_item_id"]

    # Directly transition R1 task to READY
    processor.store.transition_work_item_state(
        work_item_id=work_item_id,
        target_state=WorkItemState.READY,
        actor="operator",
        reason_code="READY_TEST",
    )

    # Claim
    claim_cmd = CommandEnvelope(
        command_id="cmd_claim_1",
        command_type="claim",
        payload={"work_item_id": work_item_id, "claimed_by_host": "claude_host"},
        idempotency_key="idemp_claim_1",
    )
    rcp_claim = processor.process_envelope(claim_cmd)
    assert rcp_claim.status == "SUCCESS"

    attempt_id = rcp_claim.result["attempt_id"]

    # Transition to DISPATCHING then RUNNING
    processor.store.transition_work_item_state(
        work_item_id=work_item_id,
        target_state=WorkItemState.DISPATCHING,
        actor="claude_host",
        reason_code="DISPATCH_START",
        attempt_id=attempt_id,
    )
    processor.store.transition_work_item_state(
        work_item_id=work_item_id,
        target_state=WorkItemState.RUNNING,
        actor="claude_host",
        reason_code="DISPATCH_RUNNING",
        attempt_id=attempt_id,
    )

    # Complete
    complete_cmd = CommandEnvelope(
        command_id="cmd_comp_1",
        command_type="complete",
        payload={"work_item_id": work_item_id, "attempt_id": attempt_id},
        idempotency_key="idemp_comp_1",
    )
    rcp_comp = processor.process_envelope(complete_cmd)
    assert rcp_comp.status == "SUCCESS"

    item = processor.store.get_work_item(work_item_id)
    assert item.state == WorkItemState.COMPLETED


def test_reconcile_expired_lease_liveness(processor: ConductorCommandProcessor):
    """Test decision D1: expired lease reaches RECOVERY_REQUIRED via reconcile."""
    # Enqueue + Ready + Claim
    enqueue_cmd = CommandEnvelope(
        command_id="cmd_enq_exp",
        command_type="enqueue",
        payload={
            "idempotency_key": "idemp_exp_task",
            "title": "Expired Task",
            "repo_id": "dotclaude-ecosystem",
            "repo_path": "D:/dotclaude/dotclaude-ecosystem",
            "plan_path": "design/plans/test.md",
            "risk_class": "R1",
            "workflow": "fwf",
            "requested_terminal_stage": "merged",
            "job_kind": "engineering_plan_lifecycle",
        },
        idempotency_key="idemp_enq_exp",
    )
    rcp_enq = processor.process_envelope(enqueue_cmd)
    work_item_id = rcp_enq.result["work_item_id"]

    processor.store.transition_work_item_state(
        work_item_id=work_item_id,
        target_state=WorkItemState.READY,
        actor="operator",
        reason_code="READY_TEST",
    )

    claim_cmd = CommandEnvelope(
        command_id="cmd_claim_exp",
        command_type="claim",
        payload={"work_item_id": work_item_id, "claimed_by_host": "claude_host"},
        idempotency_key="idemp_claim_exp",
    )
    rcp_claim = processor.process_envelope(claim_cmd)
    lease_id = rcp_claim.result["lease_id"]

    # Force lease expiration in DB
    past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with processor.store._connection() as conn:
        conn.execute("UPDATE leases SET expires_at_utc = ? WHERE lease_id = ?", (past_iso, lease_id))

    # Reconcile
    reconcile_cmd = CommandEnvelope(
        command_id="cmd_rec_1",
        command_type="reconcile",
        payload={"dry_run": False},
        idempotency_key="idemp_rec_1",
    )
    rcp_rec = processor.process_envelope(reconcile_cmd)
    assert rcp_rec.status == "SUCCESS"
    assert rcp_rec.result["expired_count"] == 1

    item = processor.store.get_work_item(work_item_id)
    assert item.state == WorkItemState.RECOVERY_REQUIRED
