"""Stale QUEUED requests: ghost waiters are reclaimed by the stale-slot sweep."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import psutil
import pytest

from scripts.conductor_resources import HostResourceManager
from scripts.conductor_store import ConductorStore


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.delenv("TDCONDUCTOR_STALE_SLOT_TTL_S", raising=False)
    monkeypatch.delenv("TDCONDUCTOR_STALE_QUEUED_UNRECORDED_TTL_S", raising=False)
    return HostResourceManager(ConductorStore(root_dir=tmp_path))


def _dead_identity() -> tuple[int, float]:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    start = psutil.Process(proc.pid).create_time()
    proc.wait()
    return proc.pid, start


def _setup(manager, queued_attempt="ghost"):
    holder = manager.request(purpose="pytest_full", attempt_id="holder", agent_instance="h")
    ghost = manager.request(purpose="pytest_full", attempt_id=queued_attempt, agent_instance="g")
    assert holder["state"] == "ACTIVE"
    assert ghost["state"] == "QUEUED"
    return holder, ghost


def _age(manager, request_id, seconds, *, pid=None, start=None):
    old = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    with manager.store._connection() as conn:
        conn.execute(
            "UPDATE host_resource_requests SET created_at_utc = ?, owner_process_pid = ?, "
            "owner_process_start_time = ?, owner_last_seen_at_utc = NULL WHERE request_id = ?",
            (old, pid, start, request_id),
        )
        conn.execute(
            "UPDATE host_resource_events SET recorded_at_utc = ? WHERE request_id = ?",
            (old, request_id),
        )


def _row(manager, request_id):
    with manager.store._connection() as conn:
        return dict(conn.execute(
            "SELECT * FROM host_resource_requests WHERE request_id = ?", (request_id,)
        ).fetchone())


def _release_event(manager, request_id):
    with manager.store._connection() as conn:
        row = conn.execute(
            "SELECT details_json FROM host_resource_events WHERE request_id = ? "
            "AND reason_code = 'STALE_SLOT_AUTO_RELEASED'",
            (request_id,),
        ).fetchone()
    return json.loads(row["details_json"]) if row else None


def test_old_queued_with_dead_recorded_owner_is_released(manager):
    holder, ghost = _setup(manager)
    pid, start = _dead_identity()
    _age(manager, ghost["request_id"], 1000, pid=pid, start=start)

    result = manager.sweep_stale_slots()

    assert ghost["request_id"] in result["swept_request_ids"]
    assert holder["request_id"] not in result["swept_request_ids"]
    row = _row(manager, ghost["request_id"])
    assert row["state"] == "RELEASED"
    assert row["reason_code"] == "STALE_SLOT_AUTO_RELEASED"
    details = _release_event(manager, ghost["request_id"])
    assert details["evidence"] in {"OWNER_DEAD"}
    receipt = [r for r in result["receipts"] if r.result["request_id"] == ghost["request_id"]][0]
    assert receipt.result["reason"] == "STALE_SLOT_AUTO_RELEASED"
    assert receipt.result["evidence"] == "OWNER_DEAD"
    assert _row(manager, holder["request_id"])["state"] == "ACTIVE"


def test_dead_owner_queued_younger_than_ttl_is_kept(manager):
    _, ghost = _setup(manager)
    pid, start = _dead_identity()
    _age(manager, ghost["request_id"], 60, pid=pid, start=start)
    manager.sweep_stale_slots()
    assert _row(manager, ghost["request_id"])["state"] == "QUEUED"


def test_unrecorded_queued_uses_long_cutoff(manager):
    _, ghost = _setup(manager)
    _age(manager, ghost["request_id"], 3600)  # 1 h: past 15 min, under 4 h
    manager.sweep_stale_slots()
    assert _row(manager, ghost["request_id"])["state"] == "QUEUED"

    _age(manager, ghost["request_id"], 5 * 3600)
    result = manager.sweep_stale_slots()
    assert ghost["request_id"] in result["swept_request_ids"]
    assert _row(manager, ghost["request_id"])["state"] == "RELEASED"
    details = _release_event(manager, ghost["request_id"])
    assert details["evidence"] == "OWNER_UNRECORDED"
    assert details["warning"] == "OWNER_UNRECORDED_RECLAIM"
    receipt = [r for r in result["receipts"] if r.result["request_id"] == ghost["request_id"]][0]
    assert receipt.result["warning"] == "OWNER_UNRECORDED_RECLAIM"


def test_unrecorded_queued_cutoff_env_zero_disables(manager, monkeypatch):
    monkeypatch.setenv("TDCONDUCTOR_STALE_QUEUED_UNRECORDED_TTL_S", "0")
    _, ghost = _setup(manager)
    _age(manager, ghost["request_id"], 30 * 24 * 3600)
    manager.sweep_stale_slots()
    assert _row(manager, ghost["request_id"])["state"] == "QUEUED"


def test_queued_with_live_recorded_owner_is_kept_at_any_age(manager):
    _, ghost = _setup(manager)
    pid = os.getpid()
    _age(manager, ghost["request_id"], 30 * 24 * 3600, pid=pid, start=psutil.Process(pid).create_time())
    result = manager.sweep_stale_slots()
    assert ghost["request_id"] not in result["swept_request_ids"]
    assert _row(manager, ghost["request_id"])["state"] == "QUEUED"


def test_swept_ghost_head_is_not_promoted_next_real_waiter_is(manager):
    holder, ghost = _setup(manager)
    real = manager.request(purpose="pytest_full", attempt_id="real", agent_instance="r")
    assert real["state"] == "QUEUED"
    pid, start = _dead_identity()
    _age(manager, ghost["request_id"], 1000, pid=pid, start=start)
    # The real waiter has a live recorded owner.
    live = os.getpid()
    with manager.store._connection() as conn:
        conn.execute(
            "UPDATE host_resource_requests SET owner_process_pid = ?, owner_process_start_time = ? "
            "WHERE request_id = ?",
            (live, psutil.Process(live).create_time(), real["request_id"]),
        )

    manager.sweep_stale_slots()
    assert _row(manager, ghost["request_id"])["state"] == "RELEASED"
    assert _row(manager, holder["request_id"])["state"] == "ACTIVE"
    assert _row(manager, real["request_id"])["state"] == "QUEUED"

    manager.release(holder["request_id"])

    assert _row(manager, ghost["request_id"])["state"] == "RELEASED"
    assert _row(manager, real["request_id"])["state"] == "ACTIVE"
