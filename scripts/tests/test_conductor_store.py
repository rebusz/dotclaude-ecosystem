"""Unit tests for ConductorStore persistence, SQLite WAL, atomic inbox/receipts, and leader lock."""

import pathlib
import pytest

from scripts.conductor_model import (
    CommandEnvelope,
    Receipt,
    ReasonCode,
    WorkItem,
    WorkItemState,
)
from scripts.conductor_store import ConductorStore


@pytest.fixture
def store(tmp_path: pathlib.Path) -> ConductorStore:
    return ConductorStore(root_dir=tmp_path)


def test_store_directory_creation(tmp_path: pathlib.Path):
    ConductorStore(root_dir=tmp_path)
    assert (tmp_path / "inbox").exists()
    assert (tmp_path / "receipts").exists()
    assert (tmp_path / "conductor.db").exists()


def test_leader_lock(store: ConductorStore):
    # Primary lock acquisition
    assert store.acquire_leader_lock("test_lock")
    # Renewal by same leader
    assert store.acquire_leader_lock("test_lock")

    # Second store instance trying to acquire same lock
    store2 = ConductorStore(root_dir=store.root_dir)
    assert not store2.acquire_leader_lock("test_lock")


def test_work_item_persistence(store: ConductorStore):
    item = WorkItem(
        work_item_id="wi_test_1",
        idempotency_key="key_test_1",
        title="Test Task",
        repo_id="dotclaude-ecosystem",
        repo_path="D:/dotclaude/dotclaude-ecosystem",
        plan_path="design/plans/test.md",
        risk_class="R2",
        workflow="fwf",
        requested_terminal_stage="merged",
        job_kind="engineering_plan_lifecycle",
    )

    store.save_work_item(item)
    fetched = store.get_work_item("wi_test_1")
    assert fetched is not None
    assert fetched.title == "Test Task"
    assert fetched.state == WorkItemState.DISCOVERED

    # State transition
    updated = store.transition_work_item_state(
        work_item_id="wi_test_1",
        target_state=WorkItemState.QUEUED,
        actor="operator",
        reason_code=ReasonCode.ADMISSION_OPERATOR_ENQUEUE.value,
    )
    assert updated.state == WorkItemState.QUEUED

    fetched_queued = store.get_work_item("wi_test_1")
    assert fetched_queued.state == WorkItemState.QUEUED


def test_inbox_and_receipt_atomic_protocol(store: ConductorStore):
    cmd = CommandEnvelope(
        command_id="cmd_001",
        command_type="enqueue",
        payload={"title": "Atomic Item"},
        idempotency_key="idempotency_cmd_001",
    )

    inbox_file = store.put_inbox_envelope(cmd)
    assert inbox_file.exists()

    envelopes = store.poll_inbox_envelopes()
    assert len(envelopes) == 1
    assert envelopes[0] == inbox_file

    receipt = Receipt(
        receipt_id="rcp_001",
        command_id="cmd_001",
        idempotency_key="idempotency_cmd_001",
        status="SUCCESS",
        result={"work_item_id": "wi_001"},
    )
    receipt_file = store.save_receipt(receipt)
    assert receipt_file.exists()

    fetched_receipt = store.get_receipt("idempotency_cmd_001")
    assert fetched_receipt is not None
    assert fetched_receipt.status == "SUCCESS"


def test_export_jsonl(store: ConductorStore, tmp_path: pathlib.Path):
    item = WorkItem(
        work_item_id="wi_export",
        idempotency_key="key_export",
        title="Export Task",
        repo_id="dotclaude-ecosystem",
        repo_path="D:/dotclaude/dotclaude-ecosystem",
        plan_path="design/plans/export.md",
        risk_class="R1",
        workflow="fwf",
        requested_terminal_stage="merged",
        job_kind="engineering_plan_lifecycle",
    )
    store.save_work_item(item)

    export_path = tmp_path / "export.jsonl"
    out_path = store.export_jsonl(export_path)
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "wi_export" in content
