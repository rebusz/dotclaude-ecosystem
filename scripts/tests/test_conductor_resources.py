"""Real-path tests for HRL-R2 resource admission and the pytest consumer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import os
import pathlib
import subprocess
import sys

import psutil

import pytest

from scripts.conductor_resources import (
    resolve_resource_key,
    DEFAULT_LEASE_TTL_SECONDS,
    HostResourceManager,
    ResourceAdmissionError,
    ResourceBusyError,
    classify_pytest_invocation,
)
from scripts.conductor_store import (
    ConductorStore,
    evaluate_gate_verdict,
    read_resource_live_snapshot,
    GateVerdict,
)
from scripts.conductor_model import (
    HostResourceLease,
    HostResourcePool,
    HostResourceRequest,
    HostResourceRequestState,
)


@pytest.fixture
def manager(tmp_path: pathlib.Path) -> HostResourceManager:
    return HostResourceManager(ConductorStore(root_dir=tmp_path))


def test_capacity_one_queue_and_restart_round_trip(tmp_path: pathlib.Path):
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store)
    first = manager.request(purpose="pytest_full", attempt_id="at-1", agent_instance="inst-1", idempotency_key="r-1")
    second = manager.request(purpose="pytest_heavy", attempt_id="at-2", agent_instance="inst-2", idempotency_key="r-2")

    assert first["state"] == HostResourceRequestState.ACTIVE.value
    assert second["state"] == HostResourceRequestState.QUEUED.value
    assert manager.status()["active_units"] == 1

    restarted = HostResourceManager(ConductorStore(root_dir=tmp_path))
    assert restarted.status()["active_units"] == 1
    promoted = restarted.release(first["request_id"])
    assert promoted["promoted"]["request_id"] == second["request_id"]
    assert restarted.status()["active_units"] == 1


def test_fifty_concurrent_requests_have_one_active_lease(manager: HostResourceManager):
    def request(index: int):
        return manager.request(
            purpose="pytest_heavy",
            attempt_id=f"parallel-{index}",
            agent_instance=f"inst-{index}",
            idempotency_key=f"parallel-key-{index}",
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(request, range(50)))

    assert sum(result["state"] == HostResourceRequestState.ACTIVE.value for result in results) == 1
    assert sum(result["state"] == HostResourceRequestState.QUEUED.value for result in results) == 49
    assert manager.status()["active_units"] == 1


def test_priority_and_stable_creation_order_drive_promotion(manager: HostResourceManager):
    active = manager.request(purpose="pytest_full", attempt_id="active", agent_instance="inst")
    low = manager.request(purpose="pytest_heavy", attempt_id="low", agent_instance="inst", priority=10)
    high = manager.request(purpose="pytest_heavy", attempt_id="high", agent_instance="inst", priority=100)
    promoted = manager.release(active["request_id"])
    assert promoted["promoted"]["request_id"] == high["request_id"]
    manager.release(high["request_id"])
    promoted_low = manager.status()
    assert promoted_low["active_units"] == 1
    assert promoted_low["state_counts"][HostResourceRequestState.ACTIVE.value] == 1
    assert next(item for item in promoted_low["requests"] if item["request_id"] == low["request_id"])["state"] == HostResourceRequestState.ACTIVE.value


def test_reentrant_context_allows_one_child_and_refuses_second(manager: HostResourceManager):
    parent = manager.request(purpose="pytest_full", attempt_id="parent", agent_instance="inst-parent")
    child = manager.request(
        purpose="pytest_heavy",
        attempt_id="child-1",
        agent_instance="inst-parent",
        parent_lease_id=parent["lease_id"],
    )
    assert child["state"] == HostResourceRequestState.INHERITED.value
    assert child["lease_id"] == parent["lease_id"]

    with pytest.raises(ResourceBusyError, match="INHERITED_CHILD_BUSY"):
        manager.request(
            purpose="pytest_heavy",
            attempt_id="child-2",
            agent_instance="inst-parent",
            parent_lease_id=parent["lease_id"],
        )
    assert any(
        request.state == HostResourceRequestState.QUARANTINED
        and request.reason_code == "INHERITED_CHILD_BUSY"
        for request in manager.store.list_resource_requests()
    )

    with pytest.raises(ResourceBusyError, match="INHERITED_CHILD_ACTIVE"):
        manager.release(parent["request_id"])

    manager.release(child["request_id"])
    manager.release(parent["request_id"])


def test_inherited_pytest_keeps_parent_process_identity(manager: HostResourceManager, tmp_path: pathlib.Path):
    parent = manager.request(purpose="pytest_full", attempt_id="parent-process", agent_instance="inst-parent")
    test_file = tmp_path / "test_inherited_resource.py"
    test_file.write_text("def test_inherited():\n    assert True\n", encoding="utf-8")

    result = manager.run_bounded_pytest(
        python_executable=sys.executable,
        pytest_args=[str(test_file)],
        cwd=tmp_path,
        attempt_id="child-process",
        agent_instance="inst-parent",
        parent_lease_id=parent["lease_id"],
        force_heavy=True,
        timeout_seconds=60,
    )
    assert result["status"] == "PASSED"
    lease = manager.store.get_resource_lease(parent["lease_id"])
    assert lease is not None
    assert lease.process_pid is None
    manager.release(parent["request_id"])


def test_forged_and_expired_inherited_tokens_fail_closed(manager: HostResourceManager):
    forged = manager.request(
        purpose="pytest_heavy",
        attempt_id="child",
        agent_instance="inst",
        parent_lease_id="forged",
    )
    assert forged["state"] == HostResourceRequestState.ACTIVE.value
    assert forged["reason_code"] == "INHERITED_LEASE_INVALID"
    manager.release(forged["request_id"])

    parent = manager.request(purpose="pytest_full", attempt_id="parent", agent_instance="inst")
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with manager.store._connection() as conn:
        conn.execute("UPDATE host_resource_leases SET expires_at_utc = ? WHERE lease_id = ?", (past, parent["lease_id"]))
    stale = manager.request(
        purpose="pytest_heavy",
        attempt_id="child",
        agent_instance="inst",
        parent_lease_id=parent["lease_id"],
    )
    assert stale["state"] == HostResourceRequestState.QUEUED.value
    assert stale["reason_code"] == "INHERITED_LEASE_EXPIRED"


def test_heartbeat_order_and_expiry_recovery(manager: HostResourceManager):
    admitted = manager.request(purpose="pytest_full", attempt_id="at", agent_instance="inst")
    manager.heartbeat(admitted["lease_id"], 2)
    with pytest.raises(ValueError, match="HEARTBEAT_OUT_OF_ORDER"):
        manager.heartbeat(admitted["lease_id"], 2)
    result = manager.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=301))
    assert result["expired_count"] == 1
    assert manager.status()["recovery_required"] == 1
    with pytest.raises(ResourceAdmissionError, match="RECOVERY_REQUIRED_RELEASE_REFUSED"):
        manager.release(admitted["request_id"])


def test_real_pytest_success_and_failure_release_capacity(manager: HostResourceManager, tmp_path: pathlib.Path):
    success = manager.run_bounded_pytest(
        python_executable=sys.executable,
        pytest_args=["scripts/tests/test_conductor_model.py", "-q"],
        cwd=pathlib.Path(__file__).parents[2],
        attempt_id="at-success",
        agent_instance="inst",
        timeout_seconds=60,
    )
    assert success["status"] == "PASSED"
    assert success["exit_code"] == 0
    assert manager.status()["active_units"] == 0


def test_duplicate_pytest_idempotency_never_launches_twice(manager: HostResourceManager, tmp_path: pathlib.Path):
    test_file = tmp_path / "test_duplicate_resource.py"
    test_file.write_text("def test_duplicate():\n    assert True\n", encoding="utf-8")
    first = manager.run_bounded_pytest(
        python_executable=sys.executable,
        pytest_args=[str(test_file)],
        cwd=tmp_path,
        attempt_id="at-duplicate",
        agent_instance="inst",
        idempotency_key="duplicate-pytest-key",
        force_heavy=True,
        timeout_seconds=60,
    )
    second = manager.run_bounded_pytest(
        python_executable=sys.executable,
        pytest_args=[str(test_file)],
        cwd=tmp_path,
        attempt_id="at-duplicate",
        agent_instance="inst",
        idempotency_key="duplicate-pytest-key",
        force_heavy=True,
        timeout_seconds=60,
    )
    assert first["status"] == "PASSED"
    assert second["status"] == "ALREADY_TERMINAL"
    assert len(manager.store.list_resource_requests()) == 1

    failure = manager.run_bounded_pytest(
        python_executable=sys.executable,
        pytest_args=[str(tmp_path / "missing_test_file.py"), "-q"],
        cwd=pathlib.Path(__file__).parents[2],
        attempt_id="at-failure",
        agent_instance="inst",
        timeout_seconds=60,
    )
    assert failure["status"] == "FAILED"
    assert failure["exit_code"] != 0
    assert manager.status()["active_units"] == 0


def test_real_pytest_timeout_releases_capacity(manager: HostResourceManager, tmp_path: pathlib.Path):
    slow_test = tmp_path / "test_slow_resource.py"
    slow_test.write_text(
        "import os, time\n"
        "def test_sleep_and_see_lease():\n"
        "    assert os.environ.get('TDCONDUCTOR_LEASE_ID')\n"
        "    time.sleep(2)\n",
        encoding="utf-8",
    )
    result = manager.run_bounded_pytest(
        python_executable=sys.executable,
        pytest_args=[str(slow_test), "-q"],
        cwd=tmp_path,
        attempt_id="at-timeout",
        agent_instance="inst",
        timeout_seconds=0.2,
        heartbeat_interval_seconds=0.05,
        force_heavy=True,
    )
    assert result["status"] == "TIMEOUT"
    assert manager.status()["active_units"] == 0


def test_pytest_classification_is_conservative_and_focused_does_not_consume_slot(
    manager: HostResourceManager, tmp_path: pathlib.Path
):
    (tmp_path / "tests").mkdir()
    assert classify_pytest_invocation([]) == "pytest_full"
    assert classify_pytest_invocation(["tests/test_one.py", "-q"], cwd=tmp_path) == "pytest_focused"
    assert classify_pytest_invocation(["tests"], cwd=tmp_path) == "pytest_full"
    assert classify_pytest_invocation(["-n", "auto", "tests/test_one.py"], cwd=tmp_path) == "pytest_heavy"
    assert classify_pytest_invocation(["-m", "integration", "tests/test_one.py"], cwd=tmp_path) == "pytest_heavy"
    assert classify_pytest_invocation(["--unknown-option", "tests/test_one.py"], cwd=tmp_path) == "pytest_heavy_unknown"

    focused_test = tmp_path / "test_focused_resource.py"
    focused_test.write_text("def test_focused():\n    assert True\n", encoding="utf-8")
    result = manager.run_bounded_pytest(
        python_executable=sys.executable,
        pytest_args=[str(focused_test), "-q"],
        cwd=tmp_path,
        attempt_id="at-focused",
        agent_instance="inst",
        timeout_seconds=60,
    )
    assert result["classification"] == "pytest_focused"
    assert result["status"] == "PASSED"
    assert result["lease_id"] is None
    assert manager.status()["active_units"] == 0
    assert any(
        request.purpose == "pytest_focused" and request.reason_code == "PYTEST_FOCUSED_NO_HEAVY_LEASE"
        for request in manager.store.list_resource_requests()
    )


def test_pytest_adapter_filters_secret_environment_and_rejects_arbitrary_executable(
    manager: HostResourceManager, tmp_path: pathlib.Path
):
    env_test = tmp_path / "test_env_resource.py"
    env_test.write_text(
        "import os\n"
        "def test_env_is_scoped():\n"
        "    assert os.environ.get('HRL_SECRET_TOKEN') is None\n"
        "    assert os.environ.get('TDCONDUCTOR_LEASE_ID')\n",
        encoding="utf-8",
    )
    result = manager.run_bounded_pytest(
        python_executable=sys.executable,
        pytest_args=[str(env_test), "-q"],
        cwd=tmp_path,
        attempt_id="at-env",
        agent_instance="inst",
        base_environment={"HRL_SECRET_TOKEN": "redact-me", "PATH": os.environ.get("PATH", "")},
        timeout_seconds=60,
        force_heavy=True,
    )
    assert result["status"] == "PASSED"

    arbitrary = tmp_path / "python-wrapper.exe"
    arbitrary.write_text("not an interpreter", encoding="utf-8")
    with pytest.raises(ValueError, match="Python interpreter"):
        manager.run_bounded_pytest(
            python_executable=str(arbitrary),
            pytest_args=[str(env_test)],
            cwd=tmp_path,
            attempt_id="at-arbitrary",
            agent_instance="inst",
        )


def _wedge(manager: HostResourceManager, *, purpose: str = "pytest_heavy") -> dict:
    """Drive a real request into RECOVERY_REQUIRED the way expiry does."""
    request = manager.request(purpose=purpose, attempt_id="at-wedge", agent_instance="inst-wedge")
    manager.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60))
    assert manager.status()["recovery_required"] == 1
    return request


def _set_lease_process(manager: HostResourceManager, lease_id: str, pid, start_time) -> None:
    with manager.store._connection() as conn:
        conn.execute(
            "UPDATE host_resource_leases SET process_pid = ?, process_start_time = ? WHERE lease_id = ?",
            (pid, start_time, lease_id),
        )


def _events(manager: HostResourceManager, request_id: str) -> list:
    with manager.store._connection() as conn:
        return conn.execute(
            "SELECT * FROM host_resource_events WHERE request_id = ? ORDER BY recorded_at_utc",
            (request_id,),
        ).fetchall()


def test_release_still_refuses_a_recovery_required_request(manager: HostResourceManager):
    request = _wedge(manager)
    with pytest.raises(ResourceAdmissionError, match="RECOVERY_REQUIRED_RELEASE_REFUSED"):
        manager.release(request["request_id"])
    assert manager.status()["recovery_required"] == 1


def test_recover_refuses_while_the_recorded_owner_is_alive(manager: HostResourceManager):
    request = _wedge(manager)
    _set_lease_process(
        manager, request["lease_id"], os.getpid(), psutil.Process(os.getpid()).create_time()
    )

    with pytest.raises(ResourceAdmissionError, match="OWNER_PROCESS_ALIVE"):
        manager.recover(request["request_id"])
    # Attestation is not an override: a live process outranks an operator claim.
    with pytest.raises(ResourceAdmissionError, match="OWNER_PROCESS_ALIVE"):
        manager.recover(request["request_id"], operator_attestation=True, reason="I say it is dead")
    assert manager.status()["recovery_required"] == 1


def test_recover_refuses_an_unrecorded_owner_without_attestation(manager: HostResourceManager):
    request = _wedge(manager)
    with pytest.raises(ResourceAdmissionError, match="OWNER_LIVENESS_UNPROVEN"):
        manager.recover(request["request_id"])
    with pytest.raises(ValueError, match="requires a reason"):
        manager.recover(request["request_id"], operator_attestation=True, reason="   ")
    assert manager.status()["recovery_required"] == 1


def test_recover_attested_frees_capacity_and_promotes_the_queue(manager: HostResourceManager):
    wedged = _wedge(manager)
    queued = manager.request(purpose="pytest_full", attempt_id="at-queued", agent_instance="inst-queued")
    assert queued["state"] == HostResourceRequestState.QUEUED.value

    result = manager.recover(
        wedged["request_id"],
        operator_attestation=True,
        reason="codex-root-4075 host is gone; no surviving process",
        actor="operator_cli",
    )

    assert result["status"] == "RECOVERED"
    assert result["evidence"] == "OPERATOR_ATTESTED"
    assert result["attested"] is True
    assert result["promoted"]["request_id"] == queued["request_id"]

    status = manager.status()
    assert status["recovery_required"] == 0
    assert status["queued"] == 0
    assert status["active_units"] == 1

    recorded = _events(manager, wedged["request_id"])[-1]
    assert recorded["previous_state"] == HostResourceRequestState.RECOVERY_REQUIRED.value
    assert recorded["next_state"] == HostResourceRequestState.RELEASED.value
    assert recorded["actor_identity"] == "operator_cli"
    details = json.loads(recorded["details_json"])
    assert details["evidence"] == "OPERATOR_ATTESTED"
    assert "codex-root-4075" in details["operator_reason"]


def test_recover_needs_no_attestation_once_the_owner_process_is_gone(manager: HostResourceManager):
    request = _wedge(manager, purpose="pytest_heavy")
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    _set_lease_process(manager, request["lease_id"], dead.pid, None)

    result = manager.recover(request["request_id"])

    assert result["status"] == "RECOVERED"
    assert result["evidence"] == "OWNER_PROCESS_GONE"
    assert result["attested"] is False
    assert manager.status()["recovery_required"] == 0


def test_recover_treats_a_reused_pid_as_a_dead_owner(manager: HostResourceManager):
    request = _wedge(manager)
    # Same pid, a start time that predates it: the original owner is gone and
    # the OS handed the number to somebody else.
    _set_lease_process(manager, request["lease_id"], os.getpid(), 1.0)

    result = manager.recover(request["request_id"])

    assert result["evidence"] == "OWNER_PID_REUSED"
    assert manager.status()["recovery_required"] == 0


def test_recover_refuses_a_request_that_is_not_wedged(manager: HostResourceManager):
    active = manager.request(purpose="pytest_full", attempt_id="at-live", agent_instance="inst-live")
    with pytest.raises(ResourceAdmissionError, match="RESOURCE_REQUEST_NOT_RECOVERABLE"):
        manager.recover(active["request_id"])
    with pytest.raises(ResourceAdmissionError, match="RESOURCE_REQUEST_NOT_FOUND"):
        manager.recover("rr_does_not_exist")


def test_recover_refuses_while_an_inherited_child_still_holds_the_lease(manager: HostResourceManager):
    parent = manager.request(purpose="pytest_heavy", attempt_id="at-parent", agent_instance="inst-parent")
    child = manager.request(
        purpose="pytest_focused",
        attempt_id="at-child",
        agent_instance="inst-child",
        parent_lease_id=parent["lease_id"],
    )
    assert child["state"] == HostResourceRequestState.INHERITED.value
    manager.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60))

    with pytest.raises(ResourceBusyError, match="INHERITED_CHILD_ACTIVE"):
        manager.recover(parent["request_id"], operator_attestation=True, reason="parent host died")
    assert manager.status()["recovery_required"] == 1


def test_verdict_differential_against_admission(tmp_path: pathlib.Path):
    """Differential test: verify evaluate_gate_verdict matches HostResourceManager.request() behavior in every state."""
    # 1. Pool row absent
    store_absent = ConductorStore(root_dir=tmp_path / "absent_pool")
    with store_absent._connection() as conn:
        conn.execute("DELETE FROM host_resource_pools WHERE resource_key = 'host:heavy'")
    snapshot_absent = read_resource_live_snapshot(root_dir=tmp_path / "absent_pool")
    verdict_absent = evaluate_gate_verdict(snapshot_absent)
    assert verdict_absent.verdict == GateVerdict.DISABLED.value

    manager_absent = HostResourceManager.__new__(HostResourceManager)
    manager_absent.store = store_absent
    manager_absent.resource_key = "host:heavy"
    with pytest.raises(ResourceAdmissionError, match="HOST_RESOURCE_DISABLED"):
        manager_absent.request(purpose="pytest_full", attempt_id="at-d1", agent_instance="ag-1")

    # 2. Pool disabled (enabled=False)
    store_dis = ConductorStore(root_dir=tmp_path / "dis_pool")
    store_dis.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=False))
    snapshot_dis = read_resource_live_snapshot(root_dir=tmp_path / "dis_pool")
    verdict_dis = evaluate_gate_verdict(snapshot_dis)
    assert verdict_dis.verdict == GateVerdict.DISABLED.value

    manager_dis = HostResourceManager.__new__(HostResourceManager)
    manager_dis.store = store_dis
    manager_dis.resource_key = "host:heavy"
    with pytest.raises(ResourceAdmissionError, match="HOST_RESOURCE_DISABLED"):
        manager_dis.request(purpose="pytest_full", attempt_id="at-d2", agent_instance="ag-2")

    # 3. Pool disabled with ACTIVE request
    store_dis_act = ConductorStore(root_dir=tmp_path / "dis_act_pool")
    store_dis_act.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=False))
    store_dis_act.save_resource_request(
        HostResourceRequest(
            request_id="rr_act_dis001",
            idempotency_key="idemp_act_dis",
            resource_key="host:heavy",
            purpose="pytest_full",
            attempt_id="at-act-dis",
            agent_instance="ag-act-dis",
            state=HostResourceRequestState.ACTIVE,
        )
    )
    snapshot_dis_act = read_resource_live_snapshot(root_dir=tmp_path / "dis_act_pool")
    verdict_dis_act = evaluate_gate_verdict(snapshot_dis_act)
    assert verdict_dis_act.verdict == GateVerdict.DISABLED.value

    manager_dis_act = HostResourceManager.__new__(HostResourceManager)
    manager_dis_act.store = store_dis_act
    manager_dis_act.resource_key = "host:heavy"
    with pytest.raises(ResourceAdmissionError, match="HOST_RESOURCE_DISABLED"):
        manager_dis_act.request(purpose="pytest_full", attempt_id="at-d3", agent_instance="ag-3")

    # 4. FENCED (RECOVERY_REQUIRED >= 1)
    store_fenced = ConductorStore(root_dir=tmp_path / "fenced_pool")
    manager_fenced = HostResourceManager(store_fenced)
    req_fenced = manager_fenced.request(purpose="pytest_heavy", attempt_id="at-f1", agent_instance="tsignal-cctv:79584")
    manager_fenced.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60))

    snapshot_fenced = read_resource_live_snapshot(root_dir=tmp_path / "fenced_pool")
    verdict_fenced = evaluate_gate_verdict(snapshot_fenced)
    assert verdict_fenced.verdict == GateVerdict.FENCED.value

    # Admission must be queued (not admitted)
    req_after_fence = manager_fenced.request(purpose="pytest_full", attempt_id="at-f2", agent_instance="ag-f2")
    assert req_after_fence["state"] == HostResourceRequestState.QUEUED.value
    assert req_after_fence["reason_code"] == "HOST_RESOURCE_BUSY"

    # 5. OCCUPIED (ACTIVE == 1)
    store_occ = ConductorStore(root_dir=tmp_path / "occ_pool")
    manager_occ = HostResourceManager(store_occ)
    req_active = manager_occ.request(purpose="pytest_full", attempt_id="at-o1", agent_instance="ag-o1")
    assert req_active["state"] == HostResourceRequestState.ACTIVE.value

    snapshot_occ = read_resource_live_snapshot(root_dir=tmp_path / "occ_pool")
    verdict_occ = evaluate_gate_verdict(snapshot_occ)
    assert verdict_occ.verdict == GateVerdict.OCCUPIED.value

    req_after_occ = manager_occ.request(purpose="pytest_heavy", attempt_id="at-o2", agent_instance="ag-o2")
    assert req_after_occ["state"] == HostResourceRequestState.QUEUED.value
    assert req_after_occ["reason_code"] == "HOST_RESOURCE_BUSY"

    # 6. CLEAR (no active, no fenced, queue empty)
    store_clear = ConductorStore(root_dir=tmp_path / "clear_pool")
    manager_clear = HostResourceManager(store_clear)
    snapshot_clear = read_resource_live_snapshot(root_dir=tmp_path / "clear_pool")
    verdict_clear = evaluate_gate_verdict(snapshot_clear)
    assert verdict_clear.verdict == GateVerdict.CLEAR.value

    req_admitted = manager_clear.request(purpose="pytest_full", attempt_id="at-c1", agent_instance="ag-c1")
    assert req_admitted["state"] == HostResourceRequestState.ACTIVE.value
    assert req_admitted["reason_code"] == "HOST_RESOURCE_ADMITTED"
    assert req_admitted["lease_id"] is not None

    # 7. ANOMALY (QUEUED with nothing holding the gate)
    store_anom = ConductorStore(root_dir=tmp_path / "anom_pool")
    store_anom.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=True))
    store_anom.save_resource_request(
        HostResourceRequest(
            request_id="rr_anom000001",
            idempotency_key="idemp_anom",
            resource_key="host:heavy",
            purpose="pytest_full",
            attempt_id="at-anom",
            agent_instance="ag-anom",
            state=HostResourceRequestState.QUEUED,
        )
    )
    snapshot_anom = read_resource_live_snapshot(root_dir=tmp_path / "anom_pool")
    verdict_anom = evaluate_gate_verdict(snapshot_anom)
    assert verdict_anom.verdict == GateVerdict.ANOMALY.value

    manager_anom = HostResourceManager(store_anom)
    req_anom_admit = manager_anom.request(purpose="pytest_full", attempt_id="at-anom2", agent_instance="ag-anom2")
    # Admission admits because no ACTIVE or RECOVERY_REQUIRED blocker exists
    assert req_anom_admit["state"] == HostResourceRequestState.ACTIVE.value

    # 8. INHERITED alone (never holds gate)
    store_inh = ConductorStore(root_dir=tmp_path / "inh_pool")
    store_inh.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=True))
    store_inh.save_resource_request(
        HostResourceRequest(
            request_id="rr_inh0000001",
            idempotency_key="idemp_inh",
            resource_key="host:heavy",
            purpose="pytest_focused",
            attempt_id="at-inh",
            agent_instance="ag-inh",
            state=HostResourceRequestState.INHERITED,
        )
    )
    snapshot_inh = read_resource_live_snapshot(root_dir=tmp_path / "inh_pool")
    verdict_inh = evaluate_gate_verdict(snapshot_inh)
    assert verdict_inh.verdict == GateVerdict.CLEAR.value

    # 9. QUARANTINED alone (never holds gate)
    store_quar = ConductorStore(root_dir=tmp_path / "quar_pool")
    store_quar.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=True))
    store_quar.save_resource_request(
        HostResourceRequest(
            request_id="rr_quar000001",
            idempotency_key="idemp_quar",
            resource_key="host:heavy",
            purpose="cdp_provider",
            attempt_id="at-quar",
            agent_instance="ag-quar",
            state=HostResourceRequestState.QUARANTINED,
            reason_code="INHERITED_CHILD_BUSY",
        )
    )
    snapshot_quar = read_resource_live_snapshot(root_dir=tmp_path / "quar_pool")
    verdict_quar = evaluate_gate_verdict(snapshot_quar)
    assert verdict_quar.verdict == GateVerdict.CLEAR.value


def test_fenced_regression_from_real_readback(tmp_path: pathlib.Path):
    """Captured 2026-08-27 readback: 0 active, 1 RECOVERY_REQUIRED (tsignal-cctv:79584), 6 QUEUED."""
    store = ConductorStore(root_dir=tmp_path)
    store.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=True))

    store.save_resource_request(
        HostResourceRequest(
            request_id="rr_55a2d45ff178",
            idempotency_key="idemp_incident_fenced",
            resource_key="host:heavy",
            purpose="cdp_provider",
            attempt_id="cctv-provider-79584-938a899a374f-15",
            agent_instance="tsignal-cctv:79584",
            state=HostResourceRequestState.RECOVERY_REQUIRED,
            priority=50,
            created_at_utc="2026-08-27T14:12:17Z",
            reason_code="LEASE_EXPIRED",
        )
    )
    store.save_resource_lease(
        HostResourceLease(
            lease_id="hrl_806dfd65ef7a",
            request_id="rr_55a2d45ff178",
            resource_key="host:heavy",
            attempt_id="cctv-provider-79584-938a899a374f-15",
            agent_instance="tsignal-cctv:79584",
            heartbeat_sequence=1,
            expires_at_utc="2026-08-27T14:17:17Z",
            last_heartbeat_utc="2026-08-27T14:12:17Z",
            process_pid=None,
            process_start_time=None,
        )
    )

    queued_specs = [
        ("rr_1d256a6f0a42", "tsignal-cctv:35968", "2026-08-27T16:59:17Z"),
        ("rr_233acfa15e3a", "t4-ops-unblock", "2026-08-27T17:22:34Z"),
        ("rr_a6b580201f52", "tsignal-cctv:90488", "2026-08-27T17:36:32Z"),
        ("rr_6772821c81c5", "tsignal-cctv:94488", "2026-08-27T17:39:12Z"),
        ("rr_9aa91b671651", "tsignal-cctv:128584", "2026-08-27T17:46:54Z"),
        ("rr_f4aae8962cd9", "tsignal-cctv:9076", "2026-08-27T18:39:51Z"),
    ]
    for req_id, agent, created in queued_specs:
        store.save_resource_request(
            HostResourceRequest(
                request_id=req_id,
                idempotency_key=f"idemp_{req_id}",
                resource_key="host:heavy",
                purpose="cdp_provider",
                attempt_id=f"att_{req_id}",
                agent_instance=agent,
                state=HostResourceRequestState.QUEUED,
                priority=50,
                created_at_utc=created,
                reason_code="HOST_RESOURCE_BUSY",
            )
        )

    snapshot = read_resource_live_snapshot(resource_key="host:heavy", root_dir=tmp_path)
    now_dt = datetime(2026, 8, 27, 18, 54, 17, tzinfo=timezone.utc)
    verdict = evaluate_gate_verdict(snapshot, now=now_dt)

    assert verdict.verdict == GateVerdict.FENCED.value
    assert verdict.fenced_count == 1
    assert verdict.queue_count == 6
    assert verdict.blocker is not None
    assert verdict.blocker["request_id"] == "rr_55a2d45ff178"
    assert verdict.blocker["agent_instance"] == "tsignal-cctv:79584"
    assert "tsignal-cctv:79584" in verdict.subtext
    assert "6 requests waiting" in verdict.subtext
    assert len(verdict.commands) == 1
    assert "--attest-owner-gone --reason '<why>'" in verdict.commands[0]


def test_two_concurrent_recovery_required_requests(tmp_path: pathlib.Path):
    store = ConductorStore(root_dir=tmp_path)
    store.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=True))

    store.save_resource_request(
        HostResourceRequest(
            request_id="rr_000000000001",
            idempotency_key="idemp_old",
            resource_key="host:heavy",
            purpose="cdp_provider",
            attempt_id="att-old",
            agent_instance="agent-oldest",
            state=HostResourceRequestState.RECOVERY_REQUIRED,
            created_at_utc="2026-08-28T09:00:00Z",
        )
    )
    store.save_resource_request(
        HostResourceRequest(
            request_id="rr_000000000002",
            idempotency_key="idemp_new",
            resource_key="host:heavy",
            purpose="pytest_full",
            attempt_id="att-new",
            agent_instance="agent-newest",
            state=HostResourceRequestState.RECOVERY_REQUIRED,
            created_at_utc="2026-08-28T10:00:00Z",
        )
    )

    snapshot = read_resource_live_snapshot(resource_key="host:heavy", root_dir=tmp_path)
    verdict = evaluate_gate_verdict(snapshot)

    assert verdict.verdict == GateVerdict.FENCED.value
    assert verdict.fenced_count == 2
    assert verdict.blocker is not None
    assert verdict.blocker["request_id"] == "rr_000000000001"
    assert "agent-oldest" in verdict.subtext
    assert len(verdict.commands) == 2
    assert "Clearing one fence may not open the gate" in verdict.headline


def test_isolation_fenced_cdp_does_not_block_other_pools(tmp_path: pathlib.Path):
    """ISOLATION incident regression test:
    A RECOVERY_REQUIRED fence in cdp:perplexity (tsignal-cctv:79584, LEASE_EXPIRED)
    does NOT block cdp:chatgpt, cdp:gemini, or host:heavy.
    """
    store = ConductorStore(root_dir=tmp_path)
    manager_ppl = HostResourceManager(store, resource_key="cdp:perplexity")
    manager_gpt = HostResourceManager(store, resource_key="cdp:chatgpt")
    manager_gem = HostResourceManager(store, resource_key="cdp:gemini")
    manager_heavy = HostResourceManager(store, resource_key="host:heavy")

    # 1. Drive cdp:perplexity into RECOVERY_REQUIRED with captured 2026-08-27 CCTV shape
    cctv_req = manager_ppl.request(
        purpose="cdp_perplexity",
        attempt_id="cctv-provider-79584-938a899a374f-15",
        agent_instance="tsignal-cctv:79584",
        slot_key="sonar-reasoning",
    )
    assert cctv_req["state"] == HostResourceRequestState.ACTIVE.value
    manager_ppl.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60))

    # Verify cdp:perplexity is fenced
    status_ppl = manager_ppl.status()
    assert status_ppl["recovery_required"] == 1
    snapshot_ppl = read_resource_live_snapshot(resource_key="cdp:perplexity", root_dir=tmp_path)
    verdict_ppl = evaluate_gate_verdict(snapshot_ppl)
    assert verdict_ppl.verdict == GateVerdict.FENCED.value

    # Subsequent request with the same slot_key is blocked
    blocked_ppl = manager_ppl.request(
        purpose="cdp_perplexity",
        attempt_id="att-cctv-next",
        agent_instance="tsignal-cctv:35968",
        slot_key="sonar-reasoning",
        priority=40,
    )
    assert blocked_ppl["state"] == HostResourceRequestState.QUEUED.value
    assert blocked_ppl["reason_code"] == "SLOT_KEY_BUSY"

    # Fill remaining 2 slots of cdp:perplexity (1 fenced + 2 active = 3 capacity)
    k_req = manager_ppl.request(purpose="cdp_perplexity", attempt_id="att-k", agent_instance="ag-k", slot_key="kimi-3")
    s_req = manager_ppl.request(purpose="cdp_perplexity", attempt_id="att-s", agent_instance="ag-s", slot_key="sonnet-5")
    assert k_req["state"] == HostResourceRequestState.ACTIVE.value
    assert s_req["state"] == HostResourceRequestState.ACTIVE.value

    # 4th request on cdp:perplexity queues with HOST_RESOURCE_BUSY
    r4_ppl = manager_ppl.request(purpose="cdp_perplexity", attempt_id="att-r4", agent_instance="ag-r4", slot_key="grok-4.6")
    assert r4_ppl["state"] == HostResourceRequestState.QUEUED.value
    assert r4_ppl["reason_code"] == "HOST_RESOURCE_BUSY"

    # 2. PROVE ISOLATION: cdp:chatgpt, cdp:gemini, and host:heavy admit concurrently
    gpt_req = manager_gpt.request(
        purpose="cdp_chatgpt",
        attempt_id="att-gpt-1",
        agent_instance="agent-gpt-fanout",
        priority=50,
    )
    assert gpt_req["state"] == HostResourceRequestState.ACTIVE.value
    assert gpt_req["lease_id"] is not None

    gem_req = manager_gem.request(
        purpose="cdp_gemini",
        attempt_id="att-gem-1",
        agent_instance="agent-gemini",
        priority=50,
    )
    assert gem_req["state"] == HostResourceRequestState.ACTIVE.value
    assert gem_req["lease_id"] is not None

    heavy_req = manager_heavy.request(
        purpose="pytest_full",
        attempt_id="att-pytest-1",
        agent_instance="agent-ci-runner",
        priority=50,
    )
    assert heavy_req["state"] == HostResourceRequestState.ACTIVE.value
    assert heavy_req["lease_id"] is not None


def test_capacity_cdp_perplexity_three_slots_and_promotion(tmp_path: pathlib.Path):
    """CAPACITY test:
    Three concurrent admits in cdp:perplexity (capacity 3); fourth queues with HOST_RESOURCE_BUSY;
    release of one promotes the queued request.
    """
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, resource_key="cdp:perplexity")

    r1 = manager.request(purpose="cdp_perplexity", attempt_id="at-1", agent_instance="ag-1", slot_key="model-1")
    r2 = manager.request(purpose="cdp_perplexity", attempt_id="at-2", agent_instance="ag-2", slot_key="model-2")
    r3 = manager.request(purpose="cdp_perplexity", attempt_id="at-3", agent_instance="ag-3", slot_key="model-3")

    assert r1["state"] == HostResourceRequestState.ACTIVE.value
    assert r2["state"] == HostResourceRequestState.ACTIVE.value
    assert r3["state"] == HostResourceRequestState.ACTIVE.value

    # 4th request must be queued with HOST_RESOURCE_BUSY
    r4 = manager.request(purpose="cdp_perplexity", attempt_id="at-4", agent_instance="ag-4", slot_key="model-4")
    assert r4["state"] == HostResourceRequestState.QUEUED.value
    assert r4["reason_code"] == "HOST_RESOURCE_BUSY"

    # Release r1 -> r4 is promoted
    rel = manager.release(r1["request_id"])
    assert rel["status"] == "RELEASED"
    assert rel["promoted"] is not None
    assert rel["promoted"]["request_id"] == r4["request_id"]
    assert rel["promoted"]["state"] == HostResourceRequestState.ACTIVE.value


def test_slot_exclusivity_blocks_duplicate_model_even_with_free_capacity(tmp_path: pathlib.Path):
    """SLOT EXCLUSIVITY test:
    With slot_key 'kimi-3' ACTIVE, a second 'kimi-3' request queues with SLOT_KEY_BUSY
    even though pool capacity (3) is not full; 'sonnet-5' and 'grok-4.6' admit concurrently.
    """
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, resource_key="cdp:perplexity")

    # 1st kimi-3 admits (1/3 capacity used)
    kimi1 = manager.request(purpose="cdp_perplexity", attempt_id="at-k1", agent_instance="ag-k1", slot_key="kimi-3")
    assert kimi1["state"] == HostResourceRequestState.ACTIVE.value

    # 2nd kimi-3 is queued with SLOT_KEY_BUSY despite capacity < 3
    kimi2 = manager.request(purpose="cdp_perplexity", attempt_id="at-k2", agent_instance="ag-k2", slot_key="kimi-3")
    assert kimi2["state"] == HostResourceRequestState.QUEUED.value
    assert kimi2["reason_code"] == "SLOT_KEY_BUSY"

    # sonnet-5 admits (2/3 capacity used)
    sonnet = manager.request(purpose="cdp_perplexity", attempt_id="at-s1", agent_instance="ag-s1", slot_key="sonnet-5")
    assert sonnet["state"] == HostResourceRequestState.ACTIVE.value

    # grok-4.6 admits (3/3 capacity used)
    grok = manager.request(purpose="cdp_perplexity", attempt_id="at-g1", agent_instance="ag-g1", slot_key="grok-4.6")
    assert grok["state"] == HostResourceRequestState.ACTIVE.value


def test_promotion_skips_slot_busy_candidate_and_promotes_next_eligible(tmp_path: pathlib.Path):
    """PROMOTION WITH SLOTS test:
    When the queue head is blocked only by slot exclusivity, promotion skips it and promotes
    the next eligible request, keeping the head in queue.
    """
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, resource_key="cdp:perplexity")

    # Occupy all 3 slots
    k1 = manager.request(purpose="cdp_perplexity", attempt_id="at-k1", agent_instance="ag-k1", slot_key="kimi-3")
    s1 = manager.request(purpose="cdp_perplexity", attempt_id="at-s1", agent_instance="ag-s1", slot_key="sonnet-5")
    g1 = manager.request(purpose="cdp_perplexity", attempt_id="at-g1", agent_instance="ag-g1", slot_key="grok-4.6")

    # Queue head (higher priority 80): kimi-3 (blocked by k1 slot)
    k2 = manager.request(purpose="cdp_perplexity", attempt_id="at-k2", agent_instance="ag-k2", slot_key="kimi-3", priority=80)
    assert k2["state"] == HostResourceRequestState.QUEUED.value

    # Queue position 2 (priority 50): terra (slot is free)
    t1 = manager.request(purpose="cdp_perplexity", attempt_id="at-t1", agent_instance="ag-t1", slot_key="terra", priority=50)
    assert t1["state"] == HostResourceRequestState.QUEUED.value

    # Release sonnet-5 (s1). k1 is STILL active with kimi-3.
    rel_s = manager.release(s1["request_id"])
    assert rel_s["promoted"] is not None
    # Promotion must skip k2 (because kimi-3 is still held by k1) and promote t1 (terra)!
    assert rel_s["promoted"]["request_id"] == t1["request_id"]

    # Verify k2 is still QUEUED at the head
    k2_req = store.get_resource_request(k2["request_id"])
    assert k2_req.state == HostResourceRequestState.QUEUED

    # Release k1 (kimi-3). Now k2 is eligible and promoted!
    rel_k = manager.release(k1["request_id"])
    assert rel_k["promoted"] is not None
    assert rel_k["promoted"]["request_id"] == k2["request_id"]


def test_priority_overrides_earlier_queued_request_and_both_admit(tmp_path: pathlib.Path):
    """PRIORITY test:
    A request at priority 80 is promoted ahead of one at priority 50 queued earlier,
    and the priority 50 still eventually admits.
    """
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, resource_key="cdp:perplexity")

    # Fill all 3 units
    a1 = manager.request(purpose="cdp_perplexity", attempt_id="at-a1", agent_instance="ag-a1", slot_key="m1")
    a2 = manager.request(purpose="cdp_perplexity", attempt_id="at-a2", agent_instance="ag-a2", slot_key="m2")
    a3 = manager.request(purpose="cdp_perplexity", attempt_id="at-a3", agent_instance="ag-a3", slot_key="m3")

    # Queue req_low at priority 50 first
    req_low = manager.request(purpose="cdp_perplexity", attempt_id="at-low", agent_instance="ag-low", slot_key="m4", priority=50)
    # Queue req_high at priority 80 second (CoderPX priority)
    req_high = manager.request(purpose="cdp_perplexity", attempt_id="at-high", agent_instance="ag-high", slot_key="m5", priority=80)

    # Release a1: req_high (priority 80) is promoted ahead of req_low (priority 50)
    rel1 = manager.release(a1["request_id"])
    assert rel1["promoted"]["request_id"] == req_high["request_id"]

    # Release a2: req_low (priority 50) is promoted next
    rel2 = manager.release(a2["request_id"])
    assert rel2["promoted"]["request_id"] == req_low["request_id"]


def test_cross_contamination_pytest_on_cdp_and_cdp_on_host_heavy(tmp_path: pathlib.Path):
    """NO CROSS-CONTAMINATION test:
    A pytest purpose never admits into a cdp:* pool; a cdp_provider never consumes host:heavy.
    """
    store = ConductorStore(root_dir=tmp_path)
    manager_heavy = HostResourceManager(store, resource_key="host:heavy")
    manager_cdp = HostResourceManager(store, resource_key="cdp:perplexity")

    # Pytest on cdp:* is refused
    with pytest.raises(ValueError, match="cannot consume CDP pool"):
        manager_cdp.request(purpose="pytest_full", attempt_id="at-cross-1", agent_instance="ag-cross-1")
    with pytest.raises(ValueError, match="cannot consume CDP pool"):
        manager_cdp.request(purpose="pytest_heavy", attempt_id="at-cross-2", agent_instance="ag-cross-2")
    with pytest.raises(ValueError, match="cannot consume CDP pool"):
        manager_cdp.request(purpose="playwright", attempt_id="at-cross-3", agent_instance="ag-cross-3")

    # CDP on host:heavy is refused
    with pytest.raises(ValueError, match="cannot consume 'host:heavy'"):
        manager_heavy.request(purpose="cdp_provider", attempt_id="at-cross-4", agent_instance="ag-cross-4")
    with pytest.raises(ValueError, match="cannot consume 'host:heavy'"):
        manager_heavy.request(purpose="cdp_perplexity", attempt_id="at-cross-5", agent_instance="ag-cross-5")
    with pytest.raises(ValueError, match="cannot consume 'host:heavy'"):
        manager_heavy.request(purpose="cdp_chatgpt", attempt_id="at-cross-6", agent_instance="ag-cross-6")
    with pytest.raises(ValueError, match="cannot consume 'host:heavy'"):
        manager_heavy.request(purpose="cdp_gemini", attempt_id="at-cross-7", agent_instance="ag-cross-7")


def test_per_pool_disable_isolates_only_disabled_pool(tmp_path: pathlib.Path):
    """PER-POOL DISABLE test:
    Disabling cdp:gemini refuses only cdp:gemini; host:heavy, cdp:perplexity, and cdp:chatgpt admit normally.
    """
    store = ConductorStore(root_dir=tmp_path)
    with store._connection() as conn:
        conn.execute("UPDATE host_resource_pools SET enabled = 0 WHERE resource_key = 'cdp:gemini'")

    manager_gem = HostResourceManager(store, resource_key="cdp:gemini")
    with pytest.raises(ResourceAdmissionError, match="HOST_RESOURCE_DISABLED"):
        manager_gem.request(purpose="cdp_gemini", attempt_id="at-dis-gem", agent_instance="ag-dis-gem")

    # Other pools still work
    manager_heavy = HostResourceManager(store, resource_key="host:heavy")
    r_heavy = manager_heavy.request(purpose="pytest_full", attempt_id="at-ok-h", agent_instance="ag-ok-h")
    assert r_heavy["state"] == HostResourceRequestState.ACTIVE.value

    manager_ppl = HostResourceManager(store, resource_key="cdp:perplexity")
    r_ppl = manager_ppl.request(purpose="cdp_perplexity", attempt_id="at-ok-p", agent_instance="ag-ok-p")
    assert r_ppl["state"] == HostResourceRequestState.ACTIVE.value

    manager_gpt = HostResourceManager(store, resource_key="cdp:chatgpt")
    r_gpt = manager_gpt.request(purpose="cdp_chatgpt", attempt_id="at-ok-g", agent_instance="ag-ok-g")
    assert r_gpt["state"] == HostResourceRequestState.ACTIVE.value


def test_cdp_tv_pool_admits_cctv_and_isolates_from_host_heavy(tmp_path: pathlib.Path):
    """CCTV drives chrome_tv, which had no pool when the split first shipped.

    #90 enforced that cdp_* purposes are refused on host:heavy, but seeded only
    cdp:perplexity, cdp:chatgpt and cdp:gemini. CCTV (chrome_tv, port 9225,
    dedicated TV profile) was left with nowhere valid to go and would have
    hard-failed on its next admission request.
    """
    store = ConductorStore(root_dir=tmp_path)
    tv = HostResourceManager(store, resource_key="cdp:tv")
    admitted = tv.request(
        purpose="cdp_provider",
        attempt_id="cctv-provider-1",
        agent_instance="tsignal-cctv:1234",
    )
    assert admitted["state"] == "ACTIVE"

    # A fence on the TV lane must not touch the other pools.
    tv.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60))
    assert tv.status()["recovery_required"] == 1
    for key, purpose in (
        ("host:heavy", "pytest_full"),
        ("cdp:perplexity", "cdp_provider"),
    ):
        other = HostResourceManager(store, resource_key=key)
        result = other.request(purpose=purpose, attempt_id=f"probe-{key}", agent_instance="probe")
        assert result["state"] == "ACTIVE", f"{key} was blocked by a cdp:tv fence"


def test_chrome_tv_role_routes_to_cdp_tv():
    assert resolve_resource_key(role="chrome_tv") == "cdp:tv"
