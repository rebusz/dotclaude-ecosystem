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
    DEFAULT_LEASE_TTL_SECONDS,
    HostResourceManager,
    ResourceAdmissionError,
    ResourceBusyError,
    classify_pytest_invocation,
)
from scripts.conductor_store import ConductorStore
from scripts.conductor_model import HostResourceRequestState


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


def _wedge(manager: HostResourceManager, *, purpose: str = "cdp_provider") -> dict:
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
    parent = manager.request(purpose="cdp_provider", attempt_id="at-parent", agent_instance="inst-parent")
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
