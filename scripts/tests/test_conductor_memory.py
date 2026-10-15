"""Admission and ownership round trips, with fake telemetry and destructive handles."""

import json
import math
import os
import subprocess
import sys
from types import SimpleNamespace

import psutil
import pytest

from scripts import conductor_processes, conductor_resources
from scripts.conductor_resources import HostResourceManager, ResourceBusyError, ResourceAdmissionError
from scripts.conductor_store import ConductorStore


@pytest.fixture
def manager(tmp_path):
    return HostResourceManager(ConductorStore(tmp_path / "store"))


def memory(monkeypatch, gib):
    monkeypatch.setattr(conductor_resources.psutil, "virtual_memory",
                        lambda: SimpleNamespace(available=gib * 2**30, total=64 * 2**30))


def test_ram_pressure_hysteresis_survives_restart(manager, monkeypatch):
    memory(monkeypatch, 5)
    first = manager.request(purpose="pytest_full", attempt_id="first", agent_instance="owner")
    assert first["state"] == "QUEUED" and first["reason_code"] == "RAM_PRESSURE"
    restarted = HostResourceManager(ConductorStore(manager.store.root_dir))
    memory(monkeypatch, 7.5)
    assert restarted.memory_status()["paused"]
    memory(monkeypatch, 9)
    assert restarted.memory_status()["admitted"]


def test_released_request_keeps_lane_budget_until_terminal(manager, monkeypatch):
    memory(monkeypatch, 12)
    admitted = manager.request(purpose="pytest_full", attempt_id="lane", agent_instance="owner", memory_budget_gib=7)
    lane_id = admitted["request_id"]
    with manager.store._connection() as conn:
        conn.execute(
            """
            INSERT INTO process_lanes
                (lane_id, owner_id, owner_pid, owner_start_time, owner_session_id,
                 owner_username, worktree, command_sha256, request_id, state,
                 deadline, heartbeat, budget_gib, launch_provenance, launch_origin)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (lane_id, "owner", os.getpid(), 0, 0, "test", str(manager.store.root_dir),
             "deadbeef", lane_id, "RUNNING", 0, 0, 7, "test", "interactive"),
        )
    manager.release(lane_id)
    restarted = HostResourceManager(ConductorStore(manager.store.root_dir))
    memory(monkeypatch, 12)
    status = restarted.status()
    assert status["active_units"] == 0
    assert status["recovery_required"] == 0
    assert restarted.memory_status()["reserved_gib"] == 7
    assert restarted.memory_status()["reason"] == "RAM_BUDGET_RESERVED"
    with restarted.store._connection() as conn:
        conn.execute("UPDATE process_lanes SET state='TERMINAL' WHERE lane_id=?", (lane_id,))
    assert restarted.memory_status()["reserved_gib"] == 0
    assert restarted.memory_status()["reason"] == "RAM_ADMITTED"


def test_reservations_are_shared_across_source_pools(manager, monkeypatch):
    memory(monkeypatch, 9)
    first = manager.request(purpose="pytest_full", attempt_id="one", agent_instance="owner", memory_budget_gib=2)
    assert first["state"] == "ACTIVE"
    cdp = HostResourceManager(manager.store, "cdp:chatgpt")
    second = cdp.request(purpose="cdp_chatgpt", attempt_id="two", agent_instance="other", memory_budget_gib=2)
    assert second["state"] == "QUEUED"
    assert second["reason_code"] == "RAM_BUDGET_RESERVED"
    # CDP is still independent of the host:heavy slot when RAM recovers.
    memory(monkeypatch, 12)
    third = cdp.request(purpose="cdp_chatgpt", attempt_id="three", agent_instance="third", memory_budget_gib=2)
    assert third["state"] == "ACTIVE"
    assert manager.status()["requests"][0]["memory_budget_gib"] == 2


def test_promotion_obeys_ram_and_named_priority(manager, monkeypatch):
    held = manager.request(purpose="pytest_full", attempt_id="held", agent_instance="owner")
    for priority in ("runtime", "bos", "cctv", "options"):
        manager.request(purpose="pytest_full", attempt_id=priority, agent_instance="owner", lane_priority=priority)
    memory(monkeypatch, 4)
    assert manager.release(held["request_id"])["promoted"] is None
    memory(monkeypatch, 12)
    with manager.store._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        promoted = manager._promote_locked(conn, actor="test")
    assert manager.store.get_resource_request(promoted["request_id"]).attempt_id == "options"


@pytest.mark.parametrize("value", [0, -1, math.nan, math.inf, True])
def test_invalid_budget_never_creates_request(manager, value):
    with pytest.raises(ValueError):
        manager.request(purpose="pytest_full", attempt_id="bad", agent_instance="owner", memory_budget_gib=value)
    assert manager.store.list_resource_requests() == []


def test_missing_telemetry_blocks_and_retains_active_owner(manager, monkeypatch):
    active = manager.request(purpose="pytest_full", attempt_id="active", agent_instance="owner")
    def denied():
        raise OSError("telemetry unavailable")
    monkeypatch.setattr(conductor_resources.psutil, "virtual_memory", denied)
    assert manager.memory_status()["reason"] == "RAM_TELEMETRY_UNKNOWN"
    assert manager.store.get_resource_request(active["request_id"]).state.value == "ACTIVE"


def test_registry_roundtrip_does_not_persist_arguments(manager, tmp_path):
    command = [sys.executable, "-m", "pytest", "secret-not-persisted"]
    tags = manager._begin_lane(command=command, cwd=tmp_path, lane_id="lane", owner_id="owner",
                               request_id=None, timeout_seconds=30, budget_gib=1)
    assert tags["CONDUCTOR_LANE_ID"] == "lane"
    manager._record_process("lane", psutil.Process(os.getpid()), command)
    restarted = ConductorStore(manager.store.root_dir)
    records = restarted.list_process_records()
    assert records[0]["pid"] == os.getpid()
    assert records[0]["owner_id"] == "owner"
    assert records[0]["session_id"] is not None
    assert "secret-not-persisted" not in json.dumps(records)
    assert records[0]["state"] == "RUNNING"
    manager._finish_lane("lane", quiescent=False)
    assert restarted.list_process_records()[0]["state"] == "RECOVERY_REQUIRED"
    assert manager.memory_status()["reserved_gib"] == 1


def test_focused_pytest_is_memory_gated_before_spawn(manager, monkeypatch, tmp_path):
    memory(monkeypatch, 1)
    monkeypatch.setattr(conductor_processes, "ContainedProcess", lambda *a, **k: pytest.fail("spawned under pressure"))
    with pytest.raises(ResourceBusyError, match="RAM_PRESSURE"):
        manager.run_bounded_pytest(python_executable=sys.executable, pytest_args=["test_one.py"],
                                   cwd=tmp_path, attempt_id="test", agent_instance="owner")


def test_launch_registers_suspended_process_before_resume(manager, monkeypatch, tmp_path):
    order = []
    fake_pid = 4321

    class Observed:
        pid = fake_pid

        def create_time(self):
            return 1.0

        def ppid(self):
            return os.getppid()

        def username(self):
            return "test"

    from scripts import conductor_reaper

    monkeypatch.setattr(conductor_resources.psutil, "Process", lambda pid: Observed())
    monkeypatch.setattr(conductor_reaper, "process_session_id", lambda pid: 0)

    class Child:
        def __init__(self, command, *, cwd, env, stdout, stderr, on_suspended=None, on_started=None, **kwargs):
            self.process = SimpleNamespace(pid=fake_pid, returncode=0)
            self.pid = fake_pid
            if on_suspended is not None:
                on_suspended(self.process)
                order.append("suspended")
            if on_started is not None:
                on_started(self.process)
                order.append("started")

        def poll(self):
            return 0

        def close(self):
            return True

        def member_pids(self):
            return []

    monkeypatch.setattr(conductor_processes, "ContainedProcess", Child)
    manager.run_bounded_command([sys.executable, "-c", "pass"], cwd=tmp_path,
                                lane_id="pre-register", owner_id="owner")
    assert order == ["suspended", "started"]
    with manager.store._connection() as conn:
        assert conn.execute("SELECT pid FROM process_registry WHERE pid=?", (fake_pid,)).fetchone() is not None


def test_bounded_wall_timeout_uses_retained_fake_handle(manager, monkeypatch, tmp_path):
    calls = []
    class Child:
        def __init__(self, *args, **kwargs):
            self.process = SimpleNamespace(returncode=None)
            self.pid = 123
            assert kwargs["env"]["CONDUCTOR_LANE_ID"] == "wall"
        def poll(self):
            return self.process.returncode
        def wait(self, timeout):
            calls.append(timeout)
            raise subprocess.TimeoutExpired("fake", timeout)
        def close(self):
            self.process.returncode = 124
            return True
        def member_pids(self):
            return []
    monkeypatch.setattr(conductor_processes, "ContainedProcess", Child)
    result = manager.run_bounded_command([sys.executable, "-c", "pass"], cwd=tmp_path,
                                         lane_id="wall", owner_id="owner", timeout_seconds=0.005)
    assert result["status"] == "TIMEOUT" and result["quiescent"]
    assert all(value <= .005 for value in calls)
    assert manager.memory_status()["reserved_gib"] == 0


def test_cleanup_failure_keeps_reservation(manager, monkeypatch, tmp_path):
    class Child:
        def __init__(self, *args, **kwargs):
            self.process = SimpleNamespace(returncode=0)
        def poll(self):
            return 0
        def close(self):
            return False
    monkeypatch.setattr(conductor_processes, "ContainedProcess", Child)
    result = manager.run_bounded_command([sys.executable, "-c", "pass"], cwd=tmp_path,
                                         lane_id="ambiguous", owner_id="owner")
    assert result["status"] == "RECOVERY_REQUIRED"
    assert manager.memory_status()["reserved_gib"] == 1


def test_per_test_watchdog_is_unconditional_and_cancels(monkeypatch):
    from scripts import conductor_pytest_plugin as plugin
    events = []
    class Timer:
        def __init__(self, seconds, callback, args):
            events.append((seconds, callback, args))
        def start(self): events.append("start")
        def cancel(self): events.append("cancel")
    monkeypatch.setattr(plugin.threading, "Timer", Timer)
    monkeypatch.setenv("CONDUCTOR_TEST_TIMEOUT_SECONDS", ".1")
    protocol = plugin.pytest_runtest_protocol(SimpleNamespace(nodeid="test::one"), None)
    next(protocol)
    with pytest.raises(StopIteration):
        next(protocol)
    assert events[-2:] == ["start", "cancel"]


def test_watchdog_timeout_records_node_and_exits_its_interpreter(monkeypatch, capsys):
    from scripts import conductor_pytest_plugin as plugin
    exits = []
    monkeypatch.setattr(plugin.os, "_exit", exits.append)
    plugin._expired("test_timeout.py::test_slow")
    assert exits == [124]
    assert "CONDUCTOR_TEST_TIMEOUT: test_timeout.py::test_slow" in capsys.readouterr().err


def test_ini_cannot_disable_conductor_timer(manager, tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -p no:conductor_pytest_plugin\n", encoding="utf-8")
    test_file = tmp_path / "test_timer_enabled.py"
    test_file.write_text("def test_plugin(pytestconfig):\n    assert pytestconfig.pluginmanager.hasplugin('conductor_pytest_plugin')\n", encoding="utf-8")
    result = manager.run_bounded_pytest(python_executable=sys.executable, pytest_args=[str(test_file)],
                                       cwd=tmp_path, attempt_id="ini-timer", agent_instance="owner", timeout_seconds=60)
    assert result["status"] == "PASSED", result


def test_capture_file_failure_releases_budget_without_starting_payload(manager, monkeypatch, tmp_path):
    monkeypatch.setattr(conductor_resources.tempfile, "TemporaryFile", lambda: (_ for _ in ()).throw(OSError("denied")))
    monkeypatch.setattr(conductor_processes, "ContainedProcess", lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(OSError, match="denied"):
        manager.run_bounded_command([sys.executable, "-c", "pass"], cwd=tmp_path, lane_id="no-capture", owner_id="owner")
    assert manager.memory_status()["reserved_gib"] == 0


def test_inaccessible_owner_never_becomes_dead_or_attested(manager, monkeypatch):
    admitted = manager.request(purpose="pytest_full", attempt_id="denied", agent_instance="owner")
    with manager.store._connection() as conn:
        conn.execute("UPDATE host_resource_leases SET process_pid=123,process_start_time=100 WHERE lease_id=?",
                     (admitted["lease_id"],))
    manager._mark_recovery(admitted["request_id"], reason="TEST_UNCERTAIN")
    monkeypatch.setattr(conductor_resources.psutil, "Process", lambda pid: (_ for _ in ()).throw(psutil.AccessDenied(pid)))
    for attest in (False, True):
        with pytest.raises(ResourceAdmissionError, match="OWNER_LIVENESS_UNPROVEN"):
            manager.recover(admitted["request_id"], operator_attestation=attest, reason="cannot override denied owner")
    assert manager.store.get_resource_request(admitted["request_id"]).state.value == "RECOVERY_REQUIRED"


def test_memory_telemetry_override_is_explicit_not_from_environment(manager, monkeypatch):
    memory(monkeypatch, 3)
    monkeypatch.setenv("TDCONDUCTOR_TEST_MEMORY_GIB", "100")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "fake::test")
    status = manager.memory_status()
    assert status["paused"] and not status["admitted"]  # observed 3 GiB, not a forged env value
    explicit = HostResourceManager(
        manager.store,
        memory_telemetry_override_gib=100,
    )
    assert explicit.memory_status()["available_gib"] == 100


def _insert_unbound_lane(manager, lane_id, state, deadline, *, owner_pid=None, owner_start_time=None):
    owner = psutil.Process(os.getpid())
    with manager.store._connection() as conn:
        conn.execute(
            """
            INSERT INTO process_lanes
                (lane_id, owner_id, owner_pid, owner_start_time, owner_session_id,
                 owner_username, worktree, command_sha256, request_id, state,
                 deadline, heartbeat, budget_gib, launch_provenance, launch_origin)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (lane_id, "owner", owner_pid if owner_pid is not None else owner.pid,
             owner_start_time if owner_start_time is not None else owner.create_time(),
             0, "test", str(manager.store.root_dir),
             "deadbeef", None, state, deadline, 0, 9, "test", "interactive"),
        )


def test_alive_owner_unbound_lane_keeps_reserving_after_deadline(manager, monkeypatch):
    import time

    memory(monkeypatch, 14)
    _insert_unbound_lane(manager, "live", "RUNNING", time.time() + 600)
    assert not manager.memory_status(required_gib=1)["admitted"]  # 9 GiB reserved
    with manager.store._connection() as conn:
        conn.execute("UPDATE process_lanes SET deadline=? WHERE lane_id='live'", (time.time() - 3600,))
    assert not manager.memory_status(required_gib=1)["admitted"]  # owner still alive; budget stays reserved


def test_crashed_owner_unbound_lane_enters_recovery_and_keeps_reserving(manager, monkeypatch):
    import time

    memory(monkeypatch, 14)
    _insert_unbound_lane(manager, "stale", "RUNNING", time.time() - 3600, owner_pid=999_999_999, owner_start_time=1.0)
    assert not manager.memory_status(required_gib=1)["admitted"]
    with manager.store._connection() as conn:
        row = conn.execute("SELECT state FROM process_lanes WHERE lane_id='stale'").fetchone()
    assert row["state"] == "RECOVERY_REQUIRED"


def test_recovery_required_unbound_lane_keeps_reserving_past_deadline(manager, monkeypatch):
    import time

    memory(monkeypatch, 14)
    _insert_unbound_lane(manager, "stuck", "RECOVERY_REQUIRED", time.time() - 3600)
    assert not manager.memory_status(required_gib=1)["admitted"]


def test_leader_lock_fails_closed_without_psutil(tmp_path, monkeypatch):
    from scripts import conductor_store

    store = ConductorStore(tmp_path / "leader")
    monkeypatch.setattr(conductor_store, "psutil", None)
    assert store.acquire_leader_lock() is False
