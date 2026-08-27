"""Unit tests for ConductorStore persistence, SQLite WAL, atomic inbox/receipts, and leader lock."""

import pathlib
import sqlite3
import pytest

from scripts.conductor_model import (
    CommandEnvelope,
    HostResourceRequest,
    HostResourceRequestState,
    Receipt,
    ReasonCode,
    WorkItem,
    WorkItemState,
)
from scripts.conductor_store import (
    ConductorStore,
    STORAGE_QUOTAS_BYTES,
    read_host_resource_status,
    read_storage_status,
    read_store_diagnostics,
    read_store_status,
)


@pytest.fixture
def store(tmp_path: pathlib.Path) -> ConductorStore:
    return ConductorStore(root_dir=tmp_path)


def test_store_directory_creation(tmp_path: pathlib.Path):
    ConductorStore(root_dir=tmp_path)
    assert (tmp_path / "inbox").exists()
    assert (tmp_path / "receipts").exists()
    assert (tmp_path / "conductor.db").exists()


def test_read_only_store_seams_do_not_create_missing_root(tmp_path: pathlib.Path):
    root = tmp_path / "absent-conductor"
    status = read_store_status(root)
    diagnostics = read_store_diagnostics(root)
    storage = read_storage_status(root)

    assert status["store_state"] == "ABSENT"
    assert diagnostics["root_exists"] is False
    assert storage["retention_mode"] == "REPORT_ONLY"
    assert not root.exists()


def test_storage_status_reports_growth_and_fail_closed_quota(store: ConductorStore, monkeypatch: pytest.MonkeyPatch):
    (store.inbox_dir / "env_sample.json").write_bytes(b"1234")
    status = store.storage_status()
    assert status["status"] == "PASS"
    assert status["retention_mode"] == "REPORT_ONLY"
    assert status["directories"]["inbox"]["files"] == 1
    assert status["directories"]["inbox"]["bytes"] == 4
    assert status["directories"]["inbox"]["ceiling_bytes"] > 4

    monkeypatch.setitem(STORAGE_QUOTAS_BYTES, "inbox", 3)
    blocked = store.storage_status()
    assert blocked["status"] == "BLOCKED"
    assert blocked["directories"]["inbox"]["over_quota"] is True


def test_context_digest_migration_replays_v2_work_item(tmp_path: pathlib.Path):
    """A v2 database gains the H8 column without losing materialized state."""
    db_path = tmp_path / "conductor.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES (1, '2026-01-01T00:00:00Z');
        INSERT INTO schema_migrations VALUES (2, '2026-01-01T00:00:01Z');
        CREATE TABLE work_items (
            work_item_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL, repo_id TEXT NOT NULL, repo_path TEXT NOT NULL,
            plan_path TEXT NOT NULL, risk_class TEXT NOT NULL, workflow TEXT NOT NULL,
            requested_terminal_stage TEXT NOT NULL, job_kind TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 50, dependency_ids_json TEXT NOT NULL,
            authority_requirement TEXT NOT NULL, execution_budget_json TEXT NOT NULL,
            scope_digest_sha256 TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL, schema_version TEXT NOT NULL
        );
        CREATE TABLE host_resource_requests (
            request_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
            resource_key TEXT NOT NULL, purpose TEXT NOT NULL, attempt_id TEXT NOT NULL,
            agent_instance TEXT NOT NULL, state TEXT NOT NULL, parent_lease_id TEXT,
            command_sha256 TEXT NOT NULL DEFAULT '', created_at_utc TEXT NOT NULL,
            released_at_utc TEXT, reason_code TEXT, schema_version TEXT NOT NULL
        );
        INSERT INTO host_resource_requests VALUES (
            'rr_v2', 'rr-key-v2', 'host:heavy', 'pytest_full', 'attempt-v2', 'agent-v2',
            'QUEUED', NULL, '', '2026-01-01T00:00:03Z', NULL, 'HOST_RESOURCE_BUSY',
            'conductor.resource-request.v1'
        );
        INSERT INTO work_items VALUES (
            'wi_v2', 'key_v2', 'v2 item', 'repo', 'D:/repo', 'plan.md', 'R2', 'fwf',
            'merged', 'engineering_plan_lifecycle', 50, '[]', 'standing_r2_go',
            '{"max_attempts":1,"max_wall_seconds":7200,"max_cost_usd":null}',
            'scope-v2', 'QUEUED', '2026-01-01T00:00:02Z', 'test', 'conductor.work-item.v1'
        );
        """
    )
    conn.commit()
    conn.close()

    migrated = ConductorStore(root_dir=tmp_path)
    item = migrated.get_work_item("wi_v2")
    assert item is not None
    assert item.state == WorkItemState.QUEUED
    assert item.scope_digest_sha256 == "scope-v2"
    assert item.context_digest_sha256 == ""
    request = migrated.list_resource_requests()[0]
    assert request.request_id == "rr_v2"
    assert request.priority == 50


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
        context_digest_sha256="ctx-test-digest",
    )

    store.save_work_item(item)
    fetched = store.get_work_item("wi_test_1")
    assert fetched is not None
    assert fetched.title == "Test Task"
    assert fetched.context_digest_sha256 == "ctx-test-digest"
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


def test_resource_request_persistence_preserves_priority(store: ConductorStore):
    request = HostResourceRequest(
        request_id="rr_priority",
        idempotency_key="rr_priority_key",
        resource_key="host:heavy",
        purpose="pytest_heavy",
        attempt_id="attempt-priority",
        agent_instance="agent-priority",
        state=HostResourceRequestState.QUEUED,
        priority=900,
    )
    store.save_resource_request(request)

    fetched = store.get_resource_request(request.request_id)
    assert fetched is not None
    assert fetched.priority == 900


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


def test_read_host_resource_status_absent(tmp_path: pathlib.Path):
    absent_root = tmp_path / "absent-conductor"
    status = read_host_resource_status(absent_root)
    assert status["resource_key"] == "host:heavy"
    assert status["pool_exists"] is False
    assert status["capacity"] == 0
    assert status["enabled"] is False
    assert status["active_units"] == 0
    assert status["recovery_required"] == 0
    assert status["total_live_requests"] == 0
    assert not absent_root.exists()


def test_read_host_resource_status_live_states_and_no_released(store: ConductorStore):
    # Create requests across all states including RELEASED
    states = [
        HostResourceRequestState.ACTIVE,
        HostResourceRequestState.INHERITED,
        HostResourceRequestState.QUEUED,
        HostResourceRequestState.RECOVERY_REQUIRED,
        HostResourceRequestState.QUARANTINED,
        HostResourceRequestState.RELEASED,
    ]
    for idx, st in enumerate(states):
        req = HostResourceRequest(
            request_id=f"rr_state_{idx}",
            idempotency_key=f"idemp_state_{idx}",
            resource_key="host:heavy",
            purpose="pytest_full",
            attempt_id=f"att_{idx}",
            agent_instance="inst",
            state=st,
        )
        store.save_resource_request(req)

    status = read_host_resource_status(store.root_dir)
    assert status["pool_exists"] is True
    assert status["capacity"] == 1
    assert status["enabled"] is True
    assert status["active_units"] == 1
    assert status["active"] == 1
    assert status["inherited"] == 1
    assert status["queued"] == 1
    assert status["recovery_required"] == 1
    assert status["quarantined"] == 1
    assert status["total_live_requests"] == 5
    # Helper must NOT return RELEASED rows in counts/state_counts
    assert "RELEASED" not in status["counts"]
    assert "RELEASED" not in status["state_counts"]


def test_read_host_resource_status_disabled_and_absent_pool(store: ConductorStore):
    with store._connection() as conn:
        conn.execute("UPDATE host_resource_pools SET enabled = 0 WHERE resource_key = 'host:heavy'")
    disabled = read_host_resource_status(store.root_dir)
    assert disabled["pool_exists"] is True
    assert disabled["enabled"] is False

    with store._connection() as conn:
        conn.execute("DELETE FROM host_resource_pools WHERE resource_key = 'host:heavy'")
    absent_pool = read_host_resource_status(store.root_dir)
    assert absent_pool["pool_exists"] is False
    assert absent_pool["enabled"] is False
    assert absent_pool["capacity"] == 0

