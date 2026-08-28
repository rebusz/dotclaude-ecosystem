"""Unit tests for ConductorStore persistence, SQLite WAL, atomic inbox/receipts, and leader lock."""

import os
import pathlib
import psutil
import sqlite3
import pytest

from scripts.conductor_model import (
    CommandEnvelope,
    HostResourceLease,
    HostResourcePool,
    HostResourceRequest,
    HostResourceRequestState,
    Receipt,
    ReasonCode,
    WorkItem,
    WorkItemState,
)
from scripts.conductor_store import (
    ConductorStore,
    GateVerdict,
    GateVerdictResult,
    RecoveryAdjudication,
    STORAGE_QUOTAS_BYTES,
    read_host_resource_status,
    adjudicate_recovery,
    build_recovery_command,
    evaluate_gate_verdict,
    format_duration,
    read_gate_frame,
    read_resource_live_snapshot,
    read_storage_status,
    read_store_diagnostics,
    read_store_status,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]


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

def test_read_resource_live_snapshot_absent(tmp_path: pathlib.Path):
    absent_dir = tmp_path / "absent-dir"
    snapshot = read_resource_live_snapshot(resource_key="host:heavy", root_dir=absent_dir)
    assert snapshot["pool_present"] is False
    assert snapshot["capacity"] == 0
    assert snapshot["enabled"] is False
    assert snapshot["live_counts"] == {
        "ACTIVE": 0,
        "INHERITED": 0,
        "QUEUED": 0,
        "RECOVERY_REQUIRED": 0,
        "QUARANTINED": 0,
    }
    assert snapshot["terminal_count"] == 0
    assert snapshot["holder"] is None
    assert snapshot["inherited"] == []
    assert snapshot["queue"] == []
    assert snapshot["fenced"] == []
    assert snapshot["quarantined"] == []
    assert not absent_dir.exists()


def test_read_resource_live_snapshot_terminal_count_no_released_rows(tmp_path: pathlib.Path):
    store = ConductorStore(root_dir=tmp_path)
    store.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=True))

    # Save 229 RELEASED requests
    for i in range(229):
        store.save_resource_request(
            HostResourceRequest(
                request_id=f"rr_rel_{i:06d}",
                idempotency_key=f"idemp_rel_{i}",
                resource_key="host:heavy",
                purpose="pytest_full",
                attempt_id=f"att_rel_{i}",
                agent_instance=f"agent_rel_{i}",
                state=HostResourceRequestState.RELEASED,
                created_at_utc="2026-08-27T10:00:00Z",
                released_at_utc="2026-08-27T10:10:00Z",
                reason_code="RELEASED",
            )
        )

    # Save 1 ACTIVE request + lease
    active_req = HostResourceRequest(
        request_id="rr_active0001",
        idempotency_key="idemp_act",
        resource_key="host:heavy",
        purpose="pytest_full",
        attempt_id="att_act",
        agent_instance="agent_act",
        state=HostResourceRequestState.ACTIVE,
        created_at_utc="2026-08-27T12:00:00Z",
    )
    store.save_resource_request(active_req)
    store.save_resource_lease(
        HostResourceLease(
            lease_id="hrl_act0000001",
            request_id="rr_active0001",
            resource_key="host:heavy",
            attempt_id="att_act",
            agent_instance="agent_act",
            heartbeat_sequence=1,
            expires_at_utc="2026-08-27T12:10:00Z",
            last_heartbeat_utc="2026-08-27T12:00:00Z",
            process_pid=12345,
            process_start_time=1000.0,
        )
    )

    # Save 2 QUEUED requests
    for i in range(2):
        store.save_resource_request(
            HostResourceRequest(
                request_id=f"rr_queue_{i:05d}",
                idempotency_key=f"idemp_q_{i}",
                resource_key="host:heavy",
                purpose="pytest_full",
                attempt_id=f"att_q_{i}",
                agent_instance=f"agent_q_{i}",
                state=HostResourceRequestState.QUEUED,
                priority=50 + i * 10,
                created_at_utc=f"2026-08-27T12:0{i+1}:00Z",
            )
        )

    # Save 1 RECOVERY_REQUIRED request + lease
    store.save_resource_request(
        HostResourceRequest(
            request_id="rr_fenced0001",
            idempotency_key="idemp_fence",
            resource_key="host:heavy",
            purpose="cdp_provider",
            attempt_id="att_fence",
            agent_instance="agent_fence",
            state=HostResourceRequestState.RECOVERY_REQUIRED,
            created_at_utc="2026-08-27T11:00:00Z",
            reason_code="LEASE_EXPIRED",
        )
    )
    store.save_resource_lease(
        HostResourceLease(
            lease_id="hrl_fen0000001",
            request_id="rr_fenced0001",
            resource_key="host:heavy",
            attempt_id="att_fence",
            agent_instance="agent_fence",
            heartbeat_sequence=1,
            expires_at_utc="2026-08-27T11:05:00Z",
            last_heartbeat_utc="2026-08-27T11:00:00Z",
        )
    )

    # Save 1 QUARANTINED request
    store.save_resource_request(
        HostResourceRequest(
            request_id="rr_quar000001",
            idempotency_key="idemp_quar",
            resource_key="host:heavy",
            purpose="cdp_provider",
            attempt_id="att_quar",
            agent_instance="agent_quar",
            state=HostResourceRequestState.QUARANTINED,
            created_at_utc="2026-08-27T11:30:00Z",
            reason_code="INHERITED_CHILD_BUSY",
        )
    )

    snapshot = read_resource_live_snapshot(resource_key="host:heavy", root_dir=tmp_path)
    assert snapshot["terminal_count"] == 229
    assert snapshot["live_counts"]["ACTIVE"] == 1
    assert snapshot["live_counts"]["QUEUED"] == 2
    assert snapshot["live_counts"]["RECOVERY_REQUIRED"] == 1
    assert snapshot["live_counts"]["QUARANTINED"] == 1
    assert snapshot["live_counts"]["INHERITED"] == 0

    assert snapshot["holder"] is not None
    assert snapshot["holder"]["request_id"] == "rr_active0001"
    assert snapshot["holder"]["lease_id"] == "hrl_act0000001"
    assert len(snapshot["queue"]) == 2
    assert len(snapshot["fenced"]) == 1
    assert snapshot["fenced"][0]["request_id"] == "rr_fenced0001"
    assert snapshot["fenced"][0]["lease_id"] == "hrl_fen0000001"
    assert len(snapshot["quarantined"]) == 1

    # Verify NO RELEASED rows appear anywhere in live request lists
    for req in [snapshot["holder"], *snapshot["queue"], *snapshot["fenced"], *snapshot["quarantined"]]:
        assert req["state"] != "RELEASED"
        assert not req["request_id"].startswith("rr_rel_")


def test_read_resource_live_snapshot_never_calls_storage_status(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    ConductorStore(root_dir=tmp_path)
    def bomb(*args, **kwargs):
        raise AssertionError("storage_status called by read_resource_live_snapshot!")
    monkeypatch.setattr("scripts.conductor_store.read_storage_status", bomb)
    monkeypatch.setattr(ConductorStore, "storage_status", bomb)

    snapshot = read_resource_live_snapshot(resource_key="host:heavy", root_dir=tmp_path)
    assert snapshot["resource_key"] == "host:heavy"


def test_read_gate_frame_single_snapshot(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    import shutil
    store = ConductorStore(root_dir=tmp_path)
    store.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=True))
    assert store.acquire_leader_lock()

    # Checkpoint WAL so only db_path is copied (no WAL file present)
    with store._connection() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    copy_count = 0
    real_copy2 = shutil.copy2

    def counting_copy2(src, dst, *args, **kwargs):
        nonlocal copy_count
        copy_count += 1
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", counting_copy2)

    frame = read_gate_frame(resource_key="host:heavy", root_dir=tmp_path)
    assert copy_count == 1
    assert "store" in frame and "gate" in frame
    assert frame["store"]["store_state"] == "AVAILABLE"
    assert frame["store"]["leader_active"] is True
    assert frame["gate"]["pool_present"] is True
    assert frame["gate"]["capacity"] == 1


def test_queue_order_equals_promotion_order(tmp_path: pathlib.Path):
    import random
    store = ConductorStore(root_dir=tmp_path)
    store.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=True))

    priorities = [10, 50, 50, 80, 100]
    random.seed(42)
    for i, prio in enumerate(priorities):
        store.save_resource_request(
            HostResourceRequest(
                request_id=f"rr_order_{i:04d}",
                idempotency_key=f"idemp_ord_{i}",
                resource_key="host:heavy",
                purpose="pytest_full",
                attempt_id=f"att_ord_{i}",
                agent_instance=f"agent_ord_{i}",
                state=HostResourceRequestState.QUEUED,
                priority=prio,
                created_at_utc=f"2026-08-28T10:{10-i:02d}:00Z",
            )
        )

    snapshot = read_resource_live_snapshot(resource_key="host:heavy", root_dir=tmp_path)
    queue_from_snapshot = [r["request_id"] for r in snapshot["queue"]]

    # Compare with scheduler promotion order
    from scripts.conductor_resources import HostResourceManager
    manager = HostResourceManager(store)
    expected_order = [r.request_id for r in store.list_resource_requests(states=["QUEUED"])]
    assert queue_from_snapshot == expected_order


def test_status_compatibility_keys_and_types(tmp_path: pathlib.Path):
    from scripts.conductor_resources import HostResourceManager
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store)

    req = manager.request(purpose="pytest_full", attempt_id="at-1", agent_instance="ag-1")
    req2 = manager.request(purpose="pytest_full", attempt_id="at-2", agent_instance="ag-2")

    live = read_resource_live_snapshot(resource_key="host:heavy", root_dir=tmp_path)
    status = manager.status()

    assert live["resource_key"] == status["resource_key"]
    assert live["capacity"] == status["capacity"]
    assert live["enabled"] == status["enabled"]
    assert live["live_counts"]["ACTIVE"] == status["active_units"]
    assert live["live_counts"]["QUEUED"] == status["queued"]
    assert live["live_counts"]["RECOVERY_REQUIRED"] == status["recovery_required"]
    assert live["terminal_count"] == status["state_counts"].get("RELEASED", 0)
    assert isinstance(live["live_counts"], dict)
    assert isinstance(live["terminal_count"], int)
    assert isinstance(live["queue"], list)


def test_format_duration_clamping_and_formatting():
    assert format_duration(-10) == "<1m"
    assert format_duration(0) == "<1m"
    assert format_duration(45) == "<1m"
    assert format_duration(59.9) == "<1m"
    assert format_duration(60) == "1m"
    assert format_duration(125) == "2m"
    assert format_duration(3599) == "59m"
    assert format_duration(3600) == "1h 00m"
    assert format_duration(3660) == "1h 01m"
    assert format_duration(16920) == "4h 42m"


def test_recovery_command_builder_scenarios(tmp_path: pathlib.Path):
    # Scenario 1: null pid
    fenced_null_pid = {
        "request_id": "rr_55a2d45ff178",
        "agent_instance": "tsignal-cctv:79584",
        "process_pid": None,
        "process_start_time": None,
    }
    adj1 = adjudicate_recovery(fenced_null_pid, repo_path=tmp_path)
    assert adj1.release_refusal_code == "RECOVERY_REQUIRED_RELEASE_REFUSED"
    assert adj1.recover_code == "OWNER_LIVENESS_UNPROVEN"
    assert adj1.liveness_status == "OWNER_UNRECORDED"
    assert adj1.command is not None
    assert "--attest-owner-gone --reason '<why>'" in adj1.command
    assert "resource-release" not in adj1.command
    assert build_recovery_command(fenced_null_pid, repo_path=tmp_path) == adj1.command

    # Scenario 2: dead recorded pid
    fenced_dead_pid = {
        "request_id": "rr_123456abcdef",
        "agent_instance": "agent_dead",
        "process_pid": 999999,
        "process_start_time": 100.0,
    }
    adj2 = adjudicate_recovery(fenced_dead_pid, repo_path=tmp_path)
    assert adj2.release_refusal_code == "RECOVERY_REQUIRED_RELEASE_REFUSED"
    assert adj2.recover_code == "RECOVERY_OWNER_GONE"
    assert adj2.liveness_status == "OWNER_PROCESS_GONE"
    assert adj2.command is not None
    assert "--attest-owner-gone" not in adj2.command
    assert "resource-recover --request-id rr_123456abcdef" in adj2.command

    # Scenario 3: alive recorded pid
    import os
    fenced_alive_pid = {
        "request_id": "rr_000000000003",
        "agent_instance": "agent_alive",
        "process_pid": os.getpid(),
        "process_start_time": psutil.Process(os.getpid()).create_time(),
    }
    adj3 = adjudicate_recovery(fenced_alive_pid, repo_path=tmp_path)
    assert adj3.release_refusal_code == "RECOVERY_REQUIRED_RELEASE_REFUSED"
    assert adj3.recover_code == "OWNER_PROCESS_ALIVE"
    assert adj3.liveness_status == "OWNER_PROCESS_ALIVE"
    assert adj3.command is None
    assert build_recovery_command(fenced_alive_pid, repo_path=tmp_path) is None

    # Scenario 4: surviving inherited child
    fenced_with_child = {
        "request_id": "rr_000000000004",
        "lease_id": "hrl_parent0001",
        "process_pid": None,
    }
    inherited_children = [
        {
            "request_id": "rr_000000000005",
            "parent_lease_id": "hrl_parent0001",
            "state": "INHERITED",
        }
    ]
    adj4 = adjudicate_recovery(fenced_with_child, inherited_children=inherited_children, repo_path=tmp_path)
    assert adj4.release_refusal_code == "RECOVERY_REQUIRED_RELEASE_REFUSED"
    assert adj4.recover_code == "INHERITED_CHILD_ACTIVE"
    assert adj4.inherited_child_id == "rr_000000000005"
    assert adj4.command is None

    # Scenario 5: invalid request_id regex
    for bad_id in ["rr_bad", "rr_12345; rm -rf", "req_55a2d45ff178", "rr_55A2D45FF178"]:
        adj_bad = adjudicate_recovery({"request_id": bad_id}, repo_path=tmp_path)
        assert adj_bad.command is None
        assert adj_bad.recover_code == "INVALID_REQUEST_ID"


def test_recovery_command_builder_powershell_execution(tmp_path: pathlib.Path):
    import subprocess
    import sys
    from datetime import datetime, timezone, timedelta
    from scripts import conductorctl
    from scripts.conductor_resources import DEFAULT_LEASE_TTL_SECONDS, HostResourceManager

    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store)
    wedged = manager.request(purpose="cdp_provider", attempt_id="at-ps", agent_instance="tsignal-cctv:79584")
    manager.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60))

    fenced_req = store.get_resource_request(wedged["request_id"]).to_dict()
    lease = store.get_resource_lease_by_request(wedged["request_id"]) if hasattr(store, "get_resource_lease_by_request") else None
    if not lease:
        leases = [l for l in store.list_resource_leases() if l.request_id == wedged["request_id"]]
        lease = leases[0] if leases else None
    fenced_req["lease"] = lease.to_dict() if lease else None

    # Build command string
    raw_cmd = build_recovery_command(fenced_req, repo_path=ROOT)
    assert raw_cmd is not None
    assert "--attest-owner-gone --reason '<why>'" in raw_cmd

    # Fill placeholder for execution
    filled_cmd = raw_cmd.replace("'<why>'", "'operator manual recovery test'")

    env = os.environ.copy()
    env["TDCONDUCTOR_DIR"] = str(tmp_path)

    # Execute directly via powershell
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", filled_cmd],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr

    # Verify request is released and recovered in DB
    updated = store.get_resource_request(wedged["request_id"])
    assert updated.state == HostResourceRequestState.RELEASED
    assert updated.reason_code == "RECOVERY_ATTESTED"
