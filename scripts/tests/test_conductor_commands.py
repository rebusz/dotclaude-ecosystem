"""Unit tests for ConductorCommandProcessor."""

from datetime import datetime, timedelta, timezone
import pathlib
from unittest.mock import patch

import pytest

from scripts.conductor_commands import ConductorCommandProcessor
from scripts.conductor_model import CommandEnvelope, WorkItemState
from scripts.conductor_store import ConductorStore


@pytest.fixture
def processor(tmp_path: pathlib.Path) -> ConductorCommandProcessor:
    store = ConductorStore(root_dir=tmp_path)
    return ConductorCommandProcessor(store=store)


def test_authorization_envelopes_cannot_forge_operator_go(processor: ConductorCommandProcessor):
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

    # This loop used to pass envelope_source=("direct"|"inbox_file"|
    # "agent_assignment") and read as proof that provenance was enforced per
    # source. The parameter was never read: the refusal is source-independent,
    # so the test passed identically with it deleted (audit T1). It is now
    # deleted, and the loop asserts the property that actually holds -- every
    # envelope carrying a forged interactive grant is refused, whatever it
    # claims about itself.
    for index, forged_claim in enumerate(("interactive_console", "inbox_file", "mcp")):
        auth_cmd = CommandEnvelope(
            command_id=f"cmd_auth_{index}",
            command_type="authorize",
            payload={
                "work_item_id": work_item_id,
                "interactive_provenance_proven": True,
                "channel": forged_claim,
                "session_token": "attacker-controlled",
                "operator_identity": "forged",
            },
            idempotency_key=f"idemp_auth_{index}",
        )
        receipt = processor.process_envelope(auth_cmd)
        assert receipt.status == "ERROR"
        assert "command envelopes cannot grant operator go" in receipt.error_message.lower()
    assert processor.store.get_authorization(work_item_id) is None
    item = processor.store.get_work_item(work_item_id)
    assert item.state == WorkItemState.QUEUED


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
        payload={
            "work_item_id": work_item_id,
            "attempt_id": attempt_id,
            "lease_generation": rcp_claim.result.get("lease_generation", 1),
        },
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


def test_reaped_owner_publish_rejected_outcome_stays_unknown(processor: ConductorCommandProcessor):
    # (H2) Stale reaped owner loses right to publish: publish is rejected and outcome stays UNKNOWN
    from scripts.conductor_resources import HostResourceManager, DEFAULT_LEASE_TTL_SECONDS

    enqueue_cmd = CommandEnvelope(
        command_id="cmd_enq_reaped",
        command_type="enqueue",
        payload={
            "idempotency_key": "idemp_reaped_task",
            "title": "Reaped Task",
            "repo_id": "dotclaude-ecosystem",
            "repo_path": "D:/dotclaude/dotclaude-ecosystem",
            "plan_path": "design/plans/test.md",
            "risk_class": "R1",
            "workflow": "fwf",
            "requested_terminal_stage": "merged",
            "job_kind": "engineering_plan_lifecycle",
        },
        idempotency_key="idemp_enq_reaped",
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
        command_id="cmd_claim_reaped",
        command_type="claim",
        payload={"work_item_id": work_item_id, "claimed_by_host": "claude_host"},
        idempotency_key="idemp_claim_reaped",
    )
    rcp_claim = processor.process_envelope(claim_cmd)
    attempt_id = rcp_claim.result["attempt_id"]

    # Transition to RUNNING
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

    # Request capacity on host:heavy
    manager = HostResourceManager(processor.store, resource_key="host:heavy")
    req = manager.request(
        purpose="pytest_heavy",
        attempt_id=attempt_id,
        agent_instance="claude_host",
    )
    assert req["state"] == "ACTIVE"

    # Slot is abandoned and reaped after TTL
    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 1000)
    sweep_res = manager.sweep_stale_slots(now=future)
    assert sweep_res["swept_count"] == 1

    # Verify attempt status was set to UNKNOWN
    with processor.store._connection() as conn:
        att = conn.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        assert att["status"] == "UNKNOWN"
        assert att["reason_code"] == "STALE_SLOT_AUTO_RELEASED"

    # Reaped agent attempts to publish via complete
    complete_cmd = CommandEnvelope(
        command_id="cmd_comp_reaped",
        command_type="complete",
        payload={
            "work_item_id": work_item_id,
            "attempt_id": attempt_id,
            "lease_generation": rcp_claim.result.get("lease_generation", 1),
        },
        idempotency_key="idemp_comp_reaped",
    )
    rcp_comp = processor.process_envelope(complete_cmd)
    assert rcp_comp.status == "ERROR"
    assert "REAPED_LEASE_REJECTED" in rcp_comp.error_message

    # WorkItem was not completed and remains in RECOVERY_REQUIRED
    item = processor.store.get_work_item(work_item_id)
    assert item.state == WorkItemState.RECOVERY_REQUIRED

    # Attempt outcome stays UNKNOWN
    with processor.store._connection() as conn:
        att_after = conn.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        assert att_after["status"] == "UNKNOWN"
        lease = conn.execute("SELECT 1 FROM leases WHERE attempt_id = ?", (attempt_id,)).fetchone()
        assert lease is None


def _enqueue_claim_running(processor: ConductorCommandProcessor, idemp: str) -> tuple[str, str, str, int]:
    rcp_enq = processor.process_envelope(
        CommandEnvelope(
            command_id=f"cmd_enq_{idemp}",
            command_type="enqueue",
            payload={
                "idempotency_key": f"idemp_task_{idemp}",
                "title": "Task",
                "repo_id": "dotclaude-ecosystem",
                "repo_path": "D:/dotclaude/dotclaude-ecosystem",
                "plan_path": "design/plans/test.md",
                "risk_class": "R1",
                "workflow": "fwf",
                "requested_terminal_stage": "merged",
                "job_kind": "engineering_plan_lifecycle",
            },
            idempotency_key=f"idemp_enq_{idemp}",
        )
    )
    work_item_id = rcp_enq.result["work_item_id"]
    processor.store.transition_work_item_state(
        work_item_id=work_item_id,
        target_state=WorkItemState.READY,
        actor="operator",
        reason_code="READY_TEST",
    )
    rcp_claim = processor.process_envelope(
        CommandEnvelope(
            command_id=f"cmd_claim_{idemp}",
            command_type="claim",
            payload={"work_item_id": work_item_id, "claimed_by_host": "claude_host"},
            idempotency_key=f"idemp_claim_{idemp}",
        )
    )
    attempt_id = rcp_claim.result["attempt_id"]
    lease_generation = int(rcp_claim.result.get("lease_generation", 1))
    for state, reason in (
        (WorkItemState.DISPATCHING, "DISPATCH_START"),
        (WorkItemState.RUNNING, "DISPATCH_RUNNING"),
    ):
        processor.store.transition_work_item_state(
            work_item_id=work_item_id,
            target_state=state,
            actor="claude_host",
            reason_code=reason,
            attempt_id=attempt_id,
        )
    return work_item_id, attempt_id, rcp_claim.result["lease_id"], lease_generation


def test_complete_requires_attempt_id_and_lease_generation(processor: ConductorCommandProcessor):
    work_item_id, attempt_id, _, lease_generation = _enqueue_claim_running(processor, "ids")
    missing_id = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_comp_no_attempt",
            command_type="complete",
            payload={"work_item_id": work_item_id, "lease_generation": lease_generation},
            idempotency_key="idemp_comp_no_attempt",
        )
    )
    assert missing_id.status == "ERROR"
    assert "ATTEMPT_IDENTITY_REQUIRED" in missing_id.error_message

    missing_gen = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_comp_no_gen",
            command_type="complete",
            payload={"work_item_id": work_item_id, "attempt_id": attempt_id},
            idempotency_key="idemp_comp_no_gen",
        )
    )
    assert missing_gen.status == "ERROR"
    assert "ATTEMPT_IDENTITY_REQUIRED" in missing_gen.error_message


def test_complete_rejects_cross_work_item_attempt(processor: ConductorCommandProcessor):
    wi_a, attempt_a, _, gen_a = _enqueue_claim_running(processor, "wi_a")
    wi_b, attempt_b, _, _gen_b = _enqueue_claim_running(processor, "wi_b")
    cross = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_comp_cross",
            command_type="complete",
            payload={
                "work_item_id": wi_a,
                "attempt_id": attempt_b,
                "lease_generation": _gen_b,
            },
            idempotency_key="idemp_comp_cross",
        )
    )
    assert cross.status == "ERROR"
    assert "REAPED_LEASE_REJECTED" in cross.error_message
    assert processor.store.get_work_item(wi_a).state == WorkItemState.RUNNING


def test_post_reap_completion_checkpoint_and_heartbeat_rejected(processor: ConductorCommandProcessor):
    from scripts.conductor_resources import HostResourceManager, DEFAULT_LEASE_TTL_SECONDS

    work_item_id, attempt_id, lease_id, lease_generation = _enqueue_claim_running(
        processor, "interleave"
    )
    manager = HostResourceManager(processor.store, resource_key="host:heavy")
    manager.request(purpose="pytest_heavy", attempt_id=attempt_id, agent_instance="claude_host")
    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 1000)
    manager.sweep_stale_slots(now=future)

    complete = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_comp_interleave",
            command_type="complete",
            payload={
                "work_item_id": work_item_id,
                "attempt_id": attempt_id,
                "lease_generation": lease_generation,
            },
            idempotency_key="idemp_comp_interleave",
        )
    )
    assert complete.status == "ERROR"
    assert "REAPED_LEASE_REJECTED" in complete.error_message

    checkpoint = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_chk_interleave",
            command_type="checkpoint",
            payload={
                "work_item_id": work_item_id,
                "attempt_id": attempt_id,
                "lease_generation": lease_generation,
                "boundary": "pre_dispatch",
                "snapshot_path": "/tmp/snap",
                "snapshot_sha256": "abc",
                "snapshot_id": "snap1",
            },
            idempotency_key="idemp_chk_interleave",
        )
    )
    assert checkpoint.status == "ERROR"
    assert "REAPED_LEASE_REJECTED" in checkpoint.error_message

    heartbeat = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_hb_interleave",
            command_type="heartbeat",
            payload={
                "lease_id": lease_id,
                "attempt_id": attempt_id,
                "lease_generation": lease_generation,
                "sequence": 5,
            },
            idempotency_key="idemp_hb_interleave",
        )
    )
    assert heartbeat.status == "ERROR"
    assert "REAPED_LEASE_REJECTED" in heartbeat.error_message or "HEARTBEAT_REJECTED" in heartbeat.error_message

    with processor.store._connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM leases WHERE attempt_id = ?", (attempt_id,)
        ).fetchone() is None


def test_interleaved_reap_blocks_worker_writes_in_one_transaction(processor: ConductorCommandProcessor):
    from scripts.conductor_resources import HostResourceManager, DEFAULT_LEASE_TTL_SECONDS

    work_item_id, attempt_id, lease_id, lease_generation = _enqueue_claim_running(
        processor, "intra"
    )
    manager = HostResourceManager(processor.store, resource_key="host:heavy")
    manager.request(purpose="pytest_heavy", attempt_id=attempt_id, agent_instance="claude_host")
    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 1000)

    def _reap_between_check_and_write(point, conn, **kwargs):
        manager._sweep_stale_slots_locked(
            conn, now=future, actor="test-interleave", include_active=True
        )
        conn.commit()

    processor.store._mutation_interleave_hook = _reap_between_check_and_write

    complete = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_comp_intra",
            command_type="complete",
            payload={
                "work_item_id": work_item_id,
                "attempt_id": attempt_id,
                "lease_generation": lease_generation,
            },
            idempotency_key="idemp_comp_intra",
        )
    )
    assert complete.status == "ERROR"
    assert "REAPED_LEASE_REJECTED" in complete.error_message

    checkpoint = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_chk_intra",
            command_type="checkpoint",
            payload={
                "work_item_id": work_item_id,
                "attempt_id": attempt_id,
                "lease_generation": lease_generation,
                "boundary": "pre_dispatch",
                "snapshot_path": "/tmp/snap",
                "snapshot_sha256": "abc",
                "snapshot_id": "snap1",
            },
            idempotency_key="idemp_chk_intra",
        )
    )
    assert checkpoint.status == "ERROR"
    assert "REAPED_LEASE_REJECTED" in checkpoint.error_message

    heartbeat = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_hb_intra",
            command_type="heartbeat",
            payload={
                "lease_id": lease_id,
                "attempt_id": attempt_id,
                "lease_generation": lease_generation,
                "sequence": 5,
            },
            idempotency_key="idemp_hb_intra",
        )
    )
    assert heartbeat.status == "ERROR"
    assert (
        "REAPED_LEASE_REJECTED" in heartbeat.error_message
        or "HEARTBEAT_REJECTED" in heartbeat.error_message
    )

    processor.store._mutation_interleave_hook = None

    with processor.store._connection() as conn:
        att = conn.execute(
            "SELECT status, reason_code FROM attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        assert att["status"] == "UNKNOWN"
        assert conn.execute(
            "SELECT 1 FROM leases WHERE attempt_id = ?", (attempt_id,)
        ).fetchone() is None
        req_row = conn.execute(
            """
            SELECT request_id FROM host_resource_requests
            WHERE attempt_id = ? AND reason_code = 'STALE_SLOT_AUTO_RELEASED'
            """,
            (attempt_id,),
        ).fetchone()
        assert req_row is not None
        assert conn.execute(
            "SELECT 1 FROM receipts WHERE idempotency_key = ?",
            (f"stale_slot_auto_release_{req_row['request_id']}",),
        ).fetchone() is not None


def test_superseded_attempt_worker_writes_rejected_after_replacement_claim(
    processor: ConductorCommandProcessor,
):
    from scripts.conductor_resources import HostResourceManager

    wi_a, attempt_a, lease_id_a, gen_a = _enqueue_claim_running(processor, "owner_a")
    manager = HostResourceManager(processor.store, resource_key="host:heavy")
    manager.request(purpose="pytest_heavy", attempt_id=attempt_a, agent_instance="claude_host")

    lease_id = lease_id_a
    past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with processor.store._connection() as conn:
        conn.execute("UPDATE leases SET expires_at_utc = ? WHERE lease_id = ?", (past_iso, lease_id))

    processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_rec_replace",
            command_type="reconcile",
            payload={"dry_run": False},
            idempotency_key="idemp_rec_replace",
        )
    )
    processor.store.transition_work_item_state(
        work_item_id=wi_a,
        target_state=WorkItemState.READY,
        actor="operator",
        reason_code="READY_AFTER_RECOVERY",
    )

    claim_b = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_claim_owner_b",
            command_type="claim",
            payload={"work_item_id": wi_a, "claimed_by_host": "claude_host"},
            idempotency_key="idemp_claim_owner_b",
        )
    )
    attempt_b = claim_b.result["attempt_id"]
    gen_b = int(claim_b.result.get("lease_generation", 1))
    for state, reason in (
        (WorkItemState.DISPATCHING, "DISPATCH_START"),
        (WorkItemState.RUNNING, "DISPATCH_RUNNING"),
    ):
        processor.store.transition_work_item_state(
            work_item_id=wi_a,
            target_state=state,
            actor="claude_host",
            reason_code=reason,
            attempt_id=attempt_b,
        )

    complete = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_comp_old_owner",
            command_type="complete",
            payload={
                "work_item_id": wi_a,
                "attempt_id": attempt_a,
                "lease_generation": gen_a,
            },
            idempotency_key="idemp_comp_old_owner",
        )
    )
    assert complete.status == "ERROR"
    assert "REAPED_LEASE_REJECTED" in complete.error_message

    checkpoint = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_chk_old_owner",
            command_type="checkpoint",
            payload={
                "work_item_id": wi_a,
                "attempt_id": attempt_a,
                "lease_generation": gen_a,
                "boundary": "pre_dispatch",
                "snapshot_path": "/tmp/snap",
                "snapshot_sha256": "abc",
                "snapshot_id": "snap1",
            },
            idempotency_key="idemp_chk_old_owner",
        )
    )
    assert checkpoint.status == "ERROR"
    assert "REAPED_LEASE_REJECTED" in checkpoint.error_message

    heartbeat = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_hb_old_owner",
            command_type="heartbeat",
            payload={
                "lease_id": lease_id_a,
                "attempt_id": attempt_a,
                "lease_generation": gen_a,
                "sequence": 5,
            },
            idempotency_key="idemp_hb_old_owner",
        )
    )
    assert heartbeat.status == "ERROR"
    assert processor.store.get_work_item(wi_a).state == WorkItemState.RUNNING
    with processor.store._connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM leases WHERE attempt_id = ?", (attempt_b,)
        ).fetchone() is not None
