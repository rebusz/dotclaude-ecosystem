"""Real-path tests for HRL-R2 resource admission and the pytest consumer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import os
import pathlib
import sqlite3
import subprocess
import sys

import psutil

import pytest

from scripts.conductor_resources import (
    resolve_resource_key,
    RESOURCE_KEY,
    DEFAULT_LEASE_TTL_SECONDS,
    HostResourceManager,
    ResourceAdmissionError,
    ResourceBusyError,
    classify_pytest_invocation,
    get_stale_slot_ttl_seconds,
    _iso,
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
    """A forged token buys nothing: no inheritance, and no capacity bypass.

    This asserted only that a forged parent_lease_id still reached ACTIVE,
    under a name promising it failed closed — which read as evidence of a
    guarantee the assertion never checked (audit T2). What the code actually
    does, and what matters, is refuse to INHERIT: the request is demoted to a
    normal admission and must then queue behind a busy pool like anyone else.
    """
    forged = manager.request(
        purpose="pytest_heavy",
        attempt_id="child",
        agent_instance="inst",
        parent_lease_id="forged",
    )
    # The pool was free, so a normal admission is ACTIVE — but by admission,
    # not by inheritance, and the ledger says so.
    assert forged["state"] == HostResourceRequestState.ACTIVE.value
    assert forged["reason_code"] == "INHERITED_LEASE_INVALID"

    # The property that matters: with the pool occupied, a forged token cannot
    # walk past capacity-one the way a real inherited child would.
    gatecrasher = manager.request(
        purpose="pytest_heavy",
        attempt_id="child-2",
        agent_instance="inst",
        parent_lease_id="forged",
    )
    assert gatecrasher["state"] == HostResourceRequestState.QUEUED.value
    manager.release(gatecrasher["request_id"])
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
            "SELECT * FROM host_resource_events WHERE request_id = ? ORDER BY rowid",
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
    manager_fenced.request(purpose="pytest_heavy", attempt_id="at-f1", agent_instance="tsignal-cctv:79584")
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
    manager.request(purpose="cdp_perplexity", attempt_id="at-g1", agent_instance="ag-g1", slot_key="grok-4.6")

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
    manager.request(purpose="cdp_perplexity", attempt_id="at-a3", agent_instance="ag-a3", slot_key="m3")

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
    with pytest.raises(ValueError, match="cannot consume 'host:heavy'"):
        manager_heavy.request(purpose="playwright", attempt_id="at-not-heavy", agent_instance="ag-not-heavy")
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


def test_cdp_tv_pool_seeded_when_opening_existing_v5_database(tmp_path: pathlib.Path):
    """The seed must reach a database that already ran migration 5.

    #90 shipped migration 5 with three CDP pools. Seeding cdp:tv inside that
    same `current_version < 5` block made the fix a no-op on every workstation
    already at version 5 - the guard is False, the INSERT never runs, and CCTV
    is left with no pool row. Only fresh tmp_path databases saw the row, which
    is why the rest of this suite could not catch it.

    This drives the real migration path: build a store, roll it back to the
    pre-cdp:tv v5 state, then reopen it with the current code.
    """
    store = ConductorStore(root_dir=tmp_path)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM host_resource_pools WHERE resource_key = 'cdp:tv'")
        conn.execute("DELETE FROM schema_migrations WHERE version >= 6")
        conn.commit()
        remaining = {
            row[0] for row in conn.execute("SELECT resource_key FROM host_resource_pools").fetchall()
        }
        assert "cdp:tv" not in remaining, "arrange failed: v5 state still holds cdp:tv"
        assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 5

    reopened = ConductorStore(root_dir=tmp_path)
    with sqlite3.connect(reopened.db_path) as conn:
        pools = {
            row[0] for row in conn.execute("SELECT resource_key FROM host_resource_pools").fetchall()
        }
    assert "cdp:tv" in pools, "cdp:tv was not seeded into an existing v5 database"

    tv = HostResourceManager(reopened, resource_key="cdp:tv")
    admitted = tv.request(
        purpose="cdp_tv",
        attempt_id="cctv-upgrade-1",
        agent_instance="tsignal-cctv:4321",
    )
    assert admitted["state"] == "ACTIVE"


def test_cdp_tv_purpose_routes_to_cdp_tv_pool():
    """Guards the purpose path; only the role path was asserted before."""
    assert resolve_resource_key(purpose="cdp_tv") == "cdp:tv"
    assert resolve_resource_key(purpose="cdp_tv") != RESOURCE_KEY


def test_focused_pytest_has_no_resource_key_mapping():
    with pytest.raises(ValueError, match="does not acquire a host resource"):
        resolve_resource_key(purpose="pytest_focused")


def test_cdp_tv_purpose_is_refused_on_host_heavy(tmp_path: pathlib.Path):
    """#90's rule - a cdp_* purpose must not be admitted on host:heavy.

    The guard is a `cdp_` prefix match, so cdp_tv is covered without a new
    branch; this pins that it stays covered.
    """
    store = ConductorStore(root_dir=tmp_path)
    heavy = HostResourceManager(store, resource_key="host:heavy")
    with pytest.raises(ValueError, match="cannot consume 'host:heavy'"):
        heavy.request(
            purpose="cdp_tv",
            attempt_id="cctv-wrong-pool",
            agent_instance="tsignal-cctv:9999",
        )


def test_cdp_provider_does_not_fall_through_to_host_heavy():
    """Generic cdp_provider is not a pool; the old default was a trap (DOM-Q1)."""
    with pytest.raises(ValueError, match="host:heavy is not a CDP pool"):
        resolve_resource_key(purpose="cdp_provider")
    with pytest.raises(ValueError, match="host:heavy is not a CDP pool"):
        resolve_resource_key(purpose="cdp_provider", resource_key="host:heavy")


@pytest.mark.parametrize(
    "role,pool",
    [
        ("chrome_gpt", "cdp:chatgpt"),
        ("chrome_ppl", "cdp:perplexity"),
        ("chrome_gemini", "cdp:gemini"),
        ("chrome_tv", "cdp:tv"),
    ],
)
def test_stale_host_heavy_key_yields_to_cdp_role(role: str, pool: str):
    assert (
        resolve_resource_key(purpose="cdp_provider", resource_key="host:heavy", role=role)
        == pool
    )


def test_named_cdp_key_is_kept_for_generic_provider():
    assert resolve_resource_key(purpose="cdp_provider", resource_key="cdp:chatgpt") == "cdp:chatgpt"


def test_occupied_heavy_does_not_block_resolved_cdp_chatgpt(tmp_path: pathlib.Path):
    store = ConductorStore(root_dir=tmp_path)
    heavy = HostResourceManager(store, resource_key="host:heavy")
    heavy.request(purpose="pytest_full", attempt_id="heavy-1", agent_instance="pytest")
    key = resolve_resource_key(purpose="cdp_provider", role="chrome_gpt")
    assert key == "cdp:chatgpt"
    admitted = HostResourceManager(store, resource_key=key).request(
        purpose="cdp_provider",
        attempt_id="fwf-gpt-1",
        agent_instance="codex-dom-q1",
    )
    assert admitted["state"] == "ACTIVE"
    assert admitted["resource_key"] == "cdp:chatgpt"
    assert heavy.status()["active_units"] == 1


# ── Stale Slot TTL Auto-Release Tests (binding 2026-10-17) ───────────────────

def test_stale_slot_recovery_required_older_than_ttl_no_pid_released_with_receipt(manager: HostResourceManager):
    wedged = _wedge(manager)
    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60 + 1000)
    result = manager.reconcile(now=future)
    assert result["stale_released_count"] == 1
    req = manager.store.get_resource_request(wedged["request_id"])
    assert req.state == HostResourceRequestState.RELEASED
    assert req.reason_code == "STALE_SLOT_AUTO_RELEASED"
    receipt = manager.store.get_receipt(f"stale_slot_auto_release_{wedged['request_id']}")
    assert receipt is not None
    assert receipt.status == "SUCCESS"
    assert receipt.result["reason"] == "STALE_SLOT_AUTO_RELEASED"
    assert receipt.result["previous_state"] == "RECOVERY_REQUIRED"
    assert receipt.result["previous_reason_code"] == "LEASE_EXPIRED"


def test_stale_slot_recovery_required_younger_than_ttl_kept(manager: HostResourceManager):
    wedged = _wedge(manager)
    # State change happened at +360s. At +360 + 200s, age is 200s < 900s TTL.
    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60 + 200)
    result = manager.reconcile(now=future)
    assert result["stale_released_count"] == 0
    req = manager.store.get_resource_request(wedged["request_id"])
    assert req.state == HostResourceRequestState.RECOVERY_REQUIRED
    assert manager.store.get_receipt(f"stale_slot_auto_release_{wedged['request_id']}") is None


def test_stale_slot_recovery_required_pid_alive_matching_start_time_kept(manager: HostResourceManager):
    wedged = _wedge(manager)
    pid = os.getpid()
    start_time = psutil.Process(pid).create_time()
    _set_lease_process(manager, wedged["lease_id"], pid, start_time)
    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60 + 1000)
    result = manager.reconcile(now=future)
    assert result["stale_released_count"] == 0
    req = manager.store.get_resource_request(wedged["request_id"])
    assert req.state == HostResourceRequestState.RECOVERY_REQUIRED
    assert manager.store.get_receipt(f"stale_slot_auto_release_{wedged['request_id']}") is None


def test_stale_slot_recovery_required_pid_alive_different_start_time_released(manager: HostResourceManager):
    wedged = _wedge(manager)
    pid = os.getpid()
    start_time = psutil.Process(pid).create_time() - 500.0  # reused pid with different start time
    _set_lease_process(manager, wedged["lease_id"], pid, start_time)
    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60 + 1000)
    result = manager.reconcile(now=future)
    assert result["stale_released_count"] == 1
    req = manager.store.get_resource_request(wedged["request_id"])
    assert req.state == HostResourceRequestState.RELEASED
    assert req.reason_code == "STALE_SLOT_AUTO_RELEASED"
    receipt = manager.store.get_receipt(f"stale_slot_auto_release_{wedged['request_id']}")
    assert receipt is not None
    assert receipt.status == "SUCCESS"


def test_stale_slot_full_pool_with_stale_request_admits_new_request_same_call(manager: HostResourceManager):
    wedged = _wedge(manager)
    assert manager.status()["recovery_required"] == 1
    past_iso = "2026-10-17T00:00:00+00:00"
    with manager.store._connection() as conn:
        conn.execute(
            "UPDATE host_resource_requests SET created_at_utc = ? WHERE request_id = ?",
            (past_iso, wedged["request_id"]),
        )
        conn.execute(
            "UPDATE host_resource_leases SET expires_at_utc = ?, last_heartbeat_utc = ? WHERE lease_id = ?",
            (past_iso, past_iso, wedged["lease_id"]),
        )
        conn.execute(
            "UPDATE host_resource_events SET recorded_at_utc = ? WHERE request_id = ?",
            (past_iso, wedged["request_id"]),
        )
    # Calling request() directly on the full pool:
    # Stale request must be auto-released during admission, admitting the new request in the SAME call.
    new_req = manager.request(purpose="pytest_full", attempt_id="at-fresh", agent_instance="inst-fresh")
    assert new_req["state"] == "ACTIVE"
    old_req = manager.store.get_resource_request(wedged["request_id"])
    assert old_req.state == HostResourceRequestState.RELEASED
    assert old_req.reason_code == "STALE_SLOT_AUTO_RELEASED"


def test_stale_slot_ttl_zero_disables_release(manager: HostResourceManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "0")
    wedged = _wedge(manager)
    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60 + 2000)
    result = manager.reconcile(now=future)
    assert result["stale_released_count"] == 0
    req = manager.store.get_resource_request(wedged["request_id"])
    assert req.state == HostResourceRequestState.RECOVERY_REQUIRED
    assert manager.store.get_receipt(f"stale_slot_auto_release_{wedged['request_id']}") is None


def test_stale_slot_ttl_env_bogus_and_negative_handling(manager: HostResourceManager, monkeypatch: pytest.MonkeyPatch):
    # Finding 6: env tests for 'bogus' -> default 900 and '-1' -> disabled (0)
    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "-1")
    assert get_stale_slot_ttl_seconds() == 0
    wedged_neg = _wedge(manager)
    future_neg = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60 + 2000)
    result_neg = manager.reconcile(now=future_neg)
    assert result_neg["stale_released_count"] == 0
    req_neg = manager.store.get_resource_request(wedged_neg["request_id"])
    assert req_neg.state == HostResourceRequestState.RECOVERY_REQUIRED

    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "bogus")
    assert get_stale_slot_ttl_seconds() == 900
    future_bogus = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60 + 1000)
    result_bogus = manager.reconcile(now=future_bogus)
    assert result_bogus["stale_released_count"] == 1
    req_bogus = manager.store.get_resource_request(wedged_neg["request_id"])
    assert req_bogus.state == HostResourceRequestState.RELEASED


def test_snapshot_sweepable_count_uses_get_stale_slot_ttl_seconds(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    # Finding 5: snapshot/status path uses get_stale_slot_ttl_seconds()
    store = ConductorStore(root_dir=tmp_path)
    mgr = HostResourceManager(store)
    wedged = _wedge(mgr)

    past_iso = "2026-10-17T00:00:00+00:00"
    with mgr.store._connection() as conn:
        conn.execute("UPDATE host_resource_requests SET created_at_utc = ? WHERE request_id = ?", (past_iso, wedged["request_id"]))
        conn.execute("UPDATE host_resource_leases SET expires_at_utc = ?, last_heartbeat_utc = ? WHERE lease_id = ?", (past_iso, past_iso, wedged["lease_id"]))
        conn.execute("UPDATE host_resource_events SET recorded_at_utc = ? WHERE request_id = ?", (past_iso, wedged["request_id"]))

    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "-1")
    snap_neg = read_resource_live_snapshot(root_dir=tmp_path)
    assert snap_neg["sweepable_count"] == 0

    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "bogus")
    snap_bogus = read_resource_live_snapshot(root_dir=tmp_path)
    assert snap_bogus["sweepable_count"] == 1

    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "+900")
    snap_plus = read_resource_live_snapshot(root_dir=tmp_path)
    assert snap_plus["sweepable_count"] == 1


def test_stale_slot_fence_event_uses_reconcile_now(manager: HostResourceManager):
    # Finding 4: fence event uses event_time=now
    req = manager.request(purpose="pytest_heavy", attempt_id="at-fence-clk", agent_instance="clk-test")
    fence_now = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60)
    manager.reconcile(now=fence_now)
    with manager.store._connection() as conn:
        ev = conn.execute(
            "SELECT recorded_at_utc FROM host_resource_events WHERE request_id = ? AND reason_code = 'LEASE_EXPIRED'",
            (req["request_id"],),
        ).fetchone()
    assert ev is not None
    assert ev["recorded_at_utc"] == _iso(fence_now)


def test_stale_slot_age_is_later_of_created_heartbeat_event(manager: HostResourceManager):
    # Finding 3: real-store test where created_at is old but recent heartbeat / event exists -> kept;
    # age is the later of created / last heartbeat / last event.
    now = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    wedged = _wedge(manager)
    req_id = wedged["request_id"]
    lease_id = wedged["lease_id"]

    created_old = _iso(now - timedelta(seconds=2000))       # 2000s old > 900s TTL
    recent_activity = _iso(now - timedelta(seconds=100))    # 100s old < 900s TTL

    # Case A: created is old, but last_heartbeat_utc is recent -> KEPT
    with manager.store._connection() as conn:
        conn.execute("UPDATE host_resource_requests SET created_at_utc = ? WHERE request_id = ?", (created_old, req_id))
        conn.execute("UPDATE host_resource_leases SET last_heartbeat_utc = ? WHERE lease_id = ?", (recent_activity, lease_id))
        conn.execute("UPDATE host_resource_events SET recorded_at_utc = ? WHERE request_id = ?", (created_old, req_id))

    res_a = manager.reconcile(now=now)
    assert res_a["stale_released_count"] == 0
    assert manager.store.get_resource_request(req_id).state == HostResourceRequestState.RECOVERY_REQUIRED

    # Case B: created and heartbeat are old, but host_resource_event is recent -> KEPT
    with manager.store._connection() as conn:
        conn.execute("UPDATE host_resource_leases SET last_heartbeat_utc = ? WHERE lease_id = ?", (created_old, lease_id))
        conn.execute("UPDATE host_resource_events SET recorded_at_utc = ? WHERE request_id = ?", (recent_activity, req_id))

    res_b = manager.reconcile(now=now)
    assert res_b["stale_released_count"] == 0
    assert manager.store.get_resource_request(req_id).state == HostResourceRequestState.RECOVERY_REQUIRED

    # Case C: created, heartbeat, AND event are all old (2000s > 900s) -> RELEASED
    with manager.store._connection() as conn:
        conn.execute("UPDATE host_resource_events SET recorded_at_utc = ? WHERE request_id = ?", (created_old, req_id))

    res_c = manager.reconcile(now=now)
    assert res_c["stale_released_count"] == 1
    assert manager.store.get_resource_request(req_id).state == HostResourceRequestState.RELEASED


def test_stale_slot_owner_liveness_unproven_cases_kept(manager: HostResourceManager, monkeypatch: pytest.MonkeyPatch):
    # Finding 2: PID alive with missing start_time => unproven (keep the slot, do not auto-release);
    # only a hard "no such process" maps to gone; psutil AccessDenied / transient errors => unproven (keep).
    now = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    wedged = _wedge(manager)
    req_id = wedged["request_id"]
    lease_id = wedged["lease_id"]

    old_iso = _iso(now - timedelta(seconds=2000))
    with manager.store._connection() as conn:
        conn.execute("UPDATE host_resource_requests SET created_at_utc = ? WHERE request_id = ?", (old_iso, req_id))
        conn.execute("UPDATE host_resource_leases SET last_heartbeat_utc = ? WHERE lease_id = ?", (old_iso, lease_id))
        conn.execute("UPDATE host_resource_events SET recorded_at_utc = ? WHERE request_id = ?", (old_iso, req_id))

    # Case A: PID alive with start_time=None -> unproven -> KEPT
    live_pid = os.getpid()
    _set_lease_process(manager, lease_id, live_pid, None)
    is_gone, evidence = manager._owner_liveness(live_pid, None)
    assert not is_gone
    assert evidence == "OWNER_LIVENESS_UNPROVEN"

    res_a = manager.reconcile(now=now)
    assert res_a["stale_released_count"] == 0
    assert manager.store.get_resource_request(req_id).state == HostResourceRequestState.RECOVERY_REQUIRED
    # recover() without attestation raises OWNER_LIVENESS_UNPROVEN
    with pytest.raises(ResourceAdmissionError, match="OWNER_LIVENESS_UNPROVEN"):
        manager.recover(req_id)

    # Case B: psutil AccessDenied / transient error -> unproven -> KEPT
    def _mock_proc(*args, **kwargs):
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, "Process", _mock_proc)
    is_gone_ad, evidence_ad = manager._owner_liveness(live_pid, 12345.0)
    assert not is_gone_ad
    assert evidence_ad == "OWNER_LIVENESS_UNPROVEN"

    res_b = manager.reconcile(now=now)
    assert res_b["stale_released_count"] == 0
    assert manager.store.get_resource_request(req_id).state == HostResourceRequestState.RECOVERY_REQUIRED

    # Case C: psutil NoSuchProcess (hard no such process) -> GONE -> RELEASED
    def _mock_no_such_proc(*args, **kwargs):
        raise psutil.NoSuchProcess(pid=999999)

    monkeypatch.setattr(psutil, "Process", _mock_no_such_proc)
    is_gone_gone, evidence_gone = manager._owner_liveness(999999, 12345.0)
    assert is_gone_gone
    assert evidence_gone == "OWNER_PROCESS_GONE"

    res_c = manager.reconcile(now=now)
    assert res_c["stale_released_count"] == 1
    assert manager.store.get_resource_request(req_id).state == HostResourceRequestState.RELEASED


def test_stale_slot_never_auto_releases_inherited_or_parent_with_active_child(manager: HostResourceManager):
    # Finding 1: never auto-release an INHERITED request, or a parent that still has INHERITED children,
    # unless the inheriting worker is proven gone; keep the recover() INHERITED_CHILD_ACTIVE invariant inside the sweeper.
    base_time = datetime.now(timezone.utc)
    parent = manager.request(purpose="pytest_heavy", attempt_id="at-p1", agent_instance="ag-p")
    p_req_id = parent["request_id"]
    p_lease_id = parent["lease_id"]

    # Active parent process keeps the inherited child and parent active
    live_pid = os.getpid()
    live_start = psutil.Process(live_pid).create_time()
    _set_lease_process(manager, p_lease_id, live_pid, live_start)

    child = manager.request(
        purpose="pytest_focused",
        attempt_id="at-c1",
        agent_instance="ag-c",
        parent_lease_id=p_lease_id,
    )
    c_req_id = child["request_id"]
    assert child["state"] == HostResourceRequestState.INHERITED.value

    # Fence parent into RECOVERY_REQUIRED
    fence_time = base_time + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60)
    manager.reconcile(now=fence_time)
    assert manager.store.get_resource_request(p_req_id).state == HostResourceRequestState.RECOVERY_REQUIRED
    assert manager.store.get_resource_request(c_req_id).state == HostResourceRequestState.INHERITED

    # Age past TTL relative to fence time (> 900s)
    future = fence_time + timedelta(seconds=1000)

    # Sweeper runs: NEITHER parent nor child is auto-released because owner is alive
    res = manager.sweep_stale_slots(now=future)
    assert res["swept_count"] == 0
    assert manager.store.get_resource_request(p_req_id).state == HostResourceRequestState.RECOVERY_REQUIRED
    assert manager.store.get_resource_request(c_req_id).state == HostResourceRequestState.INHERITED

    # recover() refuses because child is active
    with pytest.raises(ResourceBusyError, match="INHERITED_CHILD_ACTIVE"):
        manager.recover(p_req_id, operator_attestation=True, reason="manual cleanup attempt")

    # Release child explicitly
    manager.release(c_req_id)
    assert manager.store.get_resource_request(c_req_id).state == HostResourceRequestState.RELEASED

    # Simulate parent owner gone
    _set_lease_process(manager, p_lease_id, None, None)

    # Now sweeper runs again: parent is now auto-released because child is no longer active and owner is gone
    res_after = manager.sweep_stale_slots(now=future)
    assert res_after["swept_count"] == 1
    assert p_req_id in res_after["swept_request_ids"]
    assert manager.store.get_resource_request(p_req_id).state == HostResourceRequestState.RELEASED


def test_crashed_inherited_child_without_pid_released_and_frees_parent(manager: HostResourceManager):
    # (H1) Crashed inherited child without pid gets released and frees the parent
    base_time = datetime.now(timezone.utc)
    parent = manager.request(purpose="pytest_heavy", attempt_id="at-p-crash", agent_instance="ag-p")
    p_req_id = parent["request_id"]
    p_lease_id = parent["lease_id"]

    child = manager.request(
        purpose="pytest_focused",
        attempt_id="at-c-crash",
        agent_instance="ag-c",
        parent_lease_id=p_lease_id,
    )
    c_req_id = child["request_id"]
    assert child["state"] == HostResourceRequestState.INHERITED.value

    # Fence parent into RECOVERY_REQUIRED
    fence_time = base_time + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60)
    manager.reconcile(now=fence_time)
    assert manager.store.get_resource_request(p_req_id).state == HostResourceRequestState.RECOVERY_REQUIRED
    assert manager.store.get_resource_request(c_req_id).state == HostResourceRequestState.INHERITED

    # Age past TTL (> 900s)
    future = fence_time + timedelta(seconds=1000)

    # Sweeper runs: both the crashed inherited child without pid and the parent are auto-released
    res = manager.sweep_stale_slots(now=future)
    assert res["swept_count"] == 2
    assert c_req_id in res["swept_request_ids"]
    assert p_req_id in res["swept_request_ids"]

    assert manager.store.get_resource_request(c_req_id).state == HostResourceRequestState.RELEASED
    assert manager.store.get_resource_request(c_req_id).reason_code == "STALE_SLOT_AUTO_RELEASED"
    assert manager.store.get_resource_request(p_req_id).state == HostResourceRequestState.RELEASED
    assert manager.store.get_resource_request(p_req_id).reason_code == "STALE_SLOT_AUTO_RELEASED"

    # Pool is free: a fresh request succeeds immediately
    fresh = manager.request(purpose="pytest_heavy", attempt_id="at-fresh", agent_instance="ag-fresh")
    assert fresh["state"] == HostResourceRequestState.ACTIVE.value


def test_reconcile_after_20_min_abandonment_releases_immediately(manager: HostResourceManager):
    # (M2) An ACTIVE lease abandoned for 20 minutes without reconciler running releases immediately
    req = manager.request(purpose="pytest_heavy", attempt_id="at-abandon-20", agent_instance="ag-abandon")
    req_id = req["request_id"]
    now_20m = datetime.now(timezone.utc) + timedelta(minutes=20)

    res = manager.reconcile(now=now_20m)
    assert res["stale_released_count"] == 1
    assert req_id in res["stale_request_ids"]

    r = manager.store.get_resource_request(req_id)
    assert r.state == HostResourceRequestState.RELEASED
    assert r.reason_code == "STALE_SLOT_AUTO_RELEASED"

    # Receipt was generated and saved
    rcp = manager.store.get_receipt(f"stale_slot_auto_release_{req_id}")
    assert rcp is not None
    assert rcp.status == "SUCCESS"


def test_reap_invalidates_queued_same_attempt_before_promoting_other(manager: HostResourceManager):
    active = manager.request(purpose="pytest_heavy", attempt_id="at-reap-q-active", agent_instance="ag1")
    queued_same = manager.request(purpose="pytest_heavy", attempt_id="at-reap-q-active", agent_instance="ag1")
    assert active["state"] == HostResourceRequestState.ACTIVE.value
    assert queued_same["state"] == HostResourceRequestState.QUEUED.value

    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 1000)
    sweep = manager.sweep_stale_slots(now=future)
    assert sweep["swept_count"] == 1

    other = manager.request(purpose="pytest_heavy", attempt_id="at-reap-q-other", agent_instance="ag2")
    assert other["state"] == HostResourceRequestState.ACTIVE.value
    assert manager.store.get_resource_request(queued_same["request_id"]).state == HostResourceRequestState.RELEASED


def test_reap_does_not_fence_replacement_attempt_work_item(manager: HostResourceManager):
    from scripts.conductor_commands import ConductorCommandProcessor
    from scripts.conductor_model import CommandEnvelope, WorkItemState

    processor = ConductorCommandProcessor(store=manager.store)
    rcp_enq = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_enq_replace",
            command_type="enqueue",
            payload={
                "idempotency_key": "idemp_replace_wi",
                "title": "Replace",
                "repo_id": "dotclaude-ecosystem",
                "repo_path": "D:/dotclaude/dotclaude-ecosystem",
                "plan_path": "design/plans/test.md",
                "risk_class": "R1",
                "workflow": "fwf",
                "requested_terminal_stage": "merged",
                "job_kind": "engineering_plan_lifecycle",
            },
            idempotency_key="idemp_enq_replace",
        )
    )
    work_item_id = rcp_enq.result["work_item_id"]
    manager.store.transition_work_item_state(
        work_item_id=work_item_id,
        target_state=WorkItemState.READY,
        actor="operator",
        reason_code="READY_TEST",
    )
    claim_a = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_claim_a",
            command_type="claim",
            payload={"work_item_id": work_item_id, "claimed_by_host": "host"},
            idempotency_key="idemp_claim_a",
        )
    )
    attempt_a = claim_a.result["attempt_id"]
    manager.request(purpose="pytest_heavy", attempt_id=attempt_a, agent_instance="host")

    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 1000)
    manager.sweep_stale_slots(now=future)
    manager.store.transition_work_item_state(
        work_item_id=work_item_id,
        target_state=WorkItemState.READY,
        actor="operator",
        reason_code="READY_AFTER_RECOVERY",
    )

    claim_b = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_claim_b",
            command_type="claim",
            payload={"work_item_id": work_item_id, "claimed_by_host": "host"},
            idempotency_key="idemp_claim_b",
        )
    )
    attempt_b = claim_b.result["attempt_id"]
    for state, reason in (
        (WorkItemState.DISPATCHING, "DISPATCH_START"),
        (WorkItemState.RUNNING, "DISPATCH_RUNNING"),
    ):
        manager.store.transition_work_item_state(
            work_item_id=work_item_id,
            target_state=state,
            actor="host",
            reason_code=reason,
            attempt_id=attempt_b,
        )

    manager.sweep_stale_slots(now=future + timedelta(seconds=500))
    item = manager.store.get_work_item(work_item_id)
    assert item.state == WorkItemState.RUNNING
    with manager.store._connection() as conn:
        lease_b = conn.execute("SELECT 1 FROM leases WHERE attempt_id = ?", (attempt_b,)).fetchone()
        assert lease_b is not None


def test_revoked_attempt_cannot_be_readmitted(manager: HostResourceManager):
    req = manager.request(purpose="pytest_heavy", attempt_id="at-revoked", agent_instance="ag-r")
    future = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 1000)
    manager.sweep_stale_slots(now=future)
    with pytest.raises(ResourceAdmissionError, match="ATTEMPT_REVOKED"):
        manager.request(purpose="pytest_heavy", attempt_id="at-revoked", agent_instance="ag-r2")



