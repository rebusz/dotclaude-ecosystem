import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import psutil

from scripts.conductor_resources import HostResourceManager
from scripts.conductor_store import ConductorStore
from scripts.conductorctl import main


def _cli_request(
    root: pathlib.Path,
    monkeypatch,
    *,
    attempt_id: str,
    owner_pid: int,
    owner_start_time: float | None = None,
    slot_key: str = "owner-pid-test",
) -> dict:
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(root))
    args = [
        "resource-request",
        "--purpose",
        "cdp_perplexity",
        "--attempt-id",
        attempt_id,
        "--agent-instance",
        "test-owner-pid",
        "--resource-key",
        "cdp:perplexity",
        "--slot-key",
        slot_key,
        "--owner-pid",
        str(owner_pid),
    ]
    if owner_start_time is not None:
        args.extend(["--owner-start-time", str(owner_start_time)])

    assert main(args) == 0
    store = ConductorStore(root_dir=root)
    with store._connection() as conn:
        row = conn.execute(
            "SELECT * FROM host_resource_requests WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
    assert row is not None
    return dict(row)


def _age_active_request(store: ConductorStore, request_id: str) -> None:
    old = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with store._connection() as conn:
        conn.execute(
            "UPDATE host_resource_requests SET created_at_utc = ?, owner_last_seen_at_utc = ? WHERE request_id = ?",
            (old, old, request_id),
        )
        conn.execute(
            "UPDATE host_resource_leases SET expires_at_utc = ?, last_heartbeat_utc = ? WHERE request_id = ?",
            (old, old, request_id),
        )
        conn.execute(
            "UPDATE host_resource_events SET recorded_at_utc = ? WHERE request_id = ?",
            (old, request_id),
        )


def _stale_release_event(store: ConductorStore, request_id: str) -> dict:
    with store._connection() as conn:
        row = conn.execute(
            "SELECT details_json FROM host_resource_events WHERE request_id = ? AND reason_code = 'STALE_SLOT_AUTO_RELEASED'",
            (request_id,),
        ).fetchone()
    assert row is not None
    return json.loads(row["details_json"])


def test_cli_resource_request_help_lists_owner_flags():
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    cli_path = repo_root / "scripts" / "conductorctl.py"
    completed = subprocess.run(
        [sys.executable, str(cli_path), "resource-request", "--help"],
        cwd=repo_root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    owner_lines = [line for line in completed.stdout.splitlines() if "owner" in line]
    assert any("--owner-pid" in line for line in owner_lines)
    assert any("--owner-start-time" in line for line in owner_lines)
    print("\n".join(owner_lines))


def test_cli_resource_request_records_validated_owner_and_lease_identity(tmp_path, monkeypatch, capsys):
    pid = os.getpid()
    start_time = psutil.Process(pid).create_time()

    row = _cli_request(
        tmp_path,
        monkeypatch,
        attempt_id="owner-pid-valid",
        owner_pid=pid,
        owner_start_time=start_time,
    )
    capsys.readouterr()

    assert row["state"] == "ACTIVE"
    assert row["owner_process_pid"] == pid
    assert row["owner_process_start_time"] == start_time
    assert row["owner_identity_source"] == "EXPLICIT_VALIDATED"
    assert row["owner_last_seen_at_utc"]
    store = ConductorStore(root_dir=tmp_path)
    with store._connection() as conn:
        lease = conn.execute(
            "SELECT process_pid, process_start_time FROM host_resource_leases WHERE request_id = ?",
            (row["request_id"],),
        ).fetchone()
    assert lease["process_pid"] == pid
    assert lease["process_start_time"] == start_time


def test_cli_wrong_owner_start_time_is_recorded_unverified_but_admitted(tmp_path, monkeypatch, capsys):
    pid = os.getpid()
    claimed_start = psutil.Process(pid).create_time() + 30.0

    row = _cli_request(
        tmp_path,
        monkeypatch,
        attempt_id="owner-pid-wrong-start",
        owner_pid=pid,
        owner_start_time=claimed_start,
    )
    capsys.readouterr()

    assert row["state"] == "ACTIVE"
    assert row["owner_process_pid"] == pid
    # The OBSERVED identity is stored, never the mismatching claim: a wrong
    # claimed start would later make the sweep read a live owner as a reused pid.
    assert row["owner_process_start_time"] == psutil.Process(pid).create_time()
    assert row["owner_process_start_time"] != claimed_start
    assert row["owner_identity_source"] == "EXPLICIT_UNVERIFIED"


def test_live_owner_with_wrong_claimed_start_is_never_reclaimed_as_dead(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "1")
    pid = os.getpid()
    row = _cli_request(
        tmp_path, monkeypatch, attempt_id="owner-pid-live-wrong-start", owner_pid=pid,
        owner_start_time=psutil.Process(pid).create_time() + 3600.0, slot_key="live-wrong-slot",
    )
    capsys.readouterr()
    store = ConductorStore(root_dir=tmp_path)
    _age_active_request(store, row["request_id"])
    manager = HostResourceManager(store, resource_key="cdp:perplexity")
    sweep = manager.sweep_stale_slots()
    assert row["request_id"] not in sweep["swept_request_ids"]
    assert store.get_resource_request(row["request_id"]).state.value == "ACTIVE"


def test_owner_pid_without_start_time_records_observed_process_identity(tmp_path):
    pid = os.getpid()
    observed_start = psutil.Process(pid).create_time()
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, resource_key="cdp:perplexity")

    admitted = manager.request(
        purpose="cdp_perplexity",
        attempt_id="owner-pid-no-start",
        agent_instance="test-owner-pid",
        owner_pid=pid,
    )

    with store._connection() as conn:
        row = conn.execute(
            "SELECT owner_process_start_time, owner_identity_source FROM host_resource_requests WHERE request_id = ?",
            (admitted["request_id"],),
        ).fetchone()
    assert row["owner_identity_source"] == "EXPLICIT_VALIDATED"
    assert row["owner_process_start_time"] == observed_start


def test_owner_identity_is_recorded_for_queued_and_inherited_requests(tmp_path):
    pid = os.getpid()
    start_time = psutil.Process(pid).create_time()
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, resource_key="cdp:perplexity")
    blocker = manager.request(
        purpose="cdp_perplexity",
        attempt_id="owner-pid-blocker",
        agent_instance="test-owner-pid",
        slot_key="duplicate-slot",
    )

    queued = manager.request(
        purpose="cdp_perplexity",
        attempt_id="owner-pid-queued",
        agent_instance="test-owner-pid",
        slot_key="duplicate-slot",
        owner_pid=pid,
        owner_start_time=start_time,
    )
    inherited = manager.request(
        purpose="cdp_perplexity",
        attempt_id="owner-pid-inherited",
        agent_instance="test-owner-pid",
        parent_lease_id=blocker["lease_id"],
        owner_pid=pid,
        owner_start_time=start_time,
    )

    assert queued["state"] == "QUEUED"
    assert inherited["state"] == "INHERITED"
    with store._connection() as conn:
        rows = conn.execute(
            "SELECT attempt_id, owner_process_pid, owner_identity_source FROM host_resource_requests "
            "WHERE attempt_id IN (?, ?) ORDER BY attempt_id",
            ("owner-pid-queued", "owner-pid-inherited"),
        ).fetchall()
    assert len(rows) == 2
    assert all(row["owner_process_pid"] == pid for row in rows)
    assert all(row["owner_identity_source"] == "EXPLICIT_VALIDATED" for row in rows)


def test_idempotent_replay_does_not_replace_validated_owner(tmp_path):
    pid = os.getpid()
    start_time = psutil.Process(pid).create_time()
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, resource_key="cdp:perplexity")
    first = manager.request(
        purpose="cdp_perplexity",
        attempt_id="owner-pid-idempotent",
        agent_instance="test-owner-pid",
        idempotency_key="owner-pid-idempotency-key",
        owner_pid=pid,
        owner_start_time=start_time,
    )

    replay = manager.request(
        purpose="cdp_perplexity",
        attempt_id="owner-pid-idempotent",
        agent_instance="test-owner-pid",
        idempotency_key="owner-pid-idempotency-key",
        owner_pid=pid + 1,
        owner_start_time=start_time + 30.0,
    )

    assert replay["request_id"] == first["request_id"]
    with store._connection() as conn:
        row = conn.execute(
            "SELECT owner_process_pid, owner_process_start_time, owner_identity_source "
            "FROM host_resource_requests WHERE request_id = ?",
            (first["request_id"],),
        ).fetchone()
    assert row["owner_process_pid"] == pid
    assert row["owner_process_start_time"] == start_time
    assert row["owner_identity_source"] == "EXPLICIT_VALIDATED"


def test_dead_cdp_owner_is_reclaimed_and_same_slot_is_admitted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "1")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        owner_start = psutil.Process(proc.pid).create_time()
        row = _cli_request(
            tmp_path,
            monkeypatch,
            attempt_id="owner-pid-dead",
            owner_pid=proc.pid,
            owner_start_time=owner_start,
            slot_key="same-model-slot",
        )
        capsys.readouterr()
        assert row["state"] == "ACTIVE"
        assert row["owner_identity_source"] == "EXPLICIT_VALIDATED"
    finally:
        proc.kill()
        proc.wait(timeout=10)

    store = ConductorStore(root_dir=tmp_path)
    _age_active_request(store, row["request_id"])
    manager = HostResourceManager(store, resource_key="cdp:perplexity")
    replacement = manager.request(
        purpose="cdp_perplexity",
        attempt_id="owner-pid-dead-replacement",
        agent_instance="test-owner-pid",
        slot_key="same-model-slot",
    )

    assert replacement["state"] == "ACTIVE"
    assert store.get_resource_request(row["request_id"]).state.value == "RELEASED"
    event = _stale_release_event(store, row["request_id"])
    assert event["evidence"] == "OWNER_DEAD"
    assert "warning" not in event
    receipt = store.get_receipt(f"stale_slot_auto_release_{row['request_id']}")
    assert receipt is not None
    assert receipt.result["evidence"] == "OWNER_DEAD"
    assert "warning" not in receipt.result


def test_pid_already_dead_at_request_is_recorded_as_unrecorded_not_trusted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "1")
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_pid = proc.pid
    assert proc.wait(timeout=10) == 0
    row = _cli_request(
        tmp_path, monkeypatch, attempt_id="owner-pid-dead-at-request", owner_pid=dead_pid,
        owner_start_time=1.0, slot_key="dead-at-request-slot",
    )
    capsys.readouterr()
    assert row["state"] == "ACTIVE"
    assert row["owner_process_pid"] is None
    store = ConductorStore(root_dir=tmp_path)
    _age_active_request(store, row["request_id"])
    HostResourceManager(store, resource_key="cdp:perplexity").sweep_stale_slots()
    event = _stale_release_event(store, row["request_id"])
    assert event["evidence"] == "OWNER_UNRECORDED"
    assert event["warning"] == "OWNER_UNRECORDED_RECLAIM"


def test_unrecorded_stale_owner_reclaim_has_warning_and_age(tmp_path, monkeypatch):
    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "1")
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, resource_key="cdp:perplexity")
    request = manager.request(
        purpose="cdp_perplexity",
        attempt_id="owner-pid-unrecorded",
        agent_instance="test-owner-pid",
        slot_key="unrecorded-model-slot",
    )
    _age_active_request(store, request["request_id"])

    sweep = manager.sweep_stale_slots()

    assert request["request_id"] in sweep["swept_request_ids"]
    assert store.get_resource_request(request["request_id"]).state.value == "RELEASED"
    event = _stale_release_event(store, request["request_id"])
    assert event["evidence"] == "OWNER_UNRECORDED"
    assert event["warning"] == "OWNER_UNRECORDED_RECLAIM"
    assert event["age_seconds"] >= 1.0
    receipt = store.get_receipt(f"stale_slot_auto_release_{request['request_id']}")
    assert receipt is not None
    assert receipt.result["warning"] == "OWNER_UNRECORDED_RECLAIM"
    assert receipt.result["age_seconds"] >= 1.0


def test_stale_live_matching_owner_is_not_reclaimed(tmp_path, monkeypatch):
    monkeypatch.setenv("TDCONDUCTOR_STALE_SLOT_TTL_S", "1")
    pid = os.getpid()
    start_time = psutil.Process(pid).create_time()
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, resource_key="cdp:perplexity")
    request = manager.request(
        purpose="cdp_perplexity",
        attempt_id="owner-pid-live",
        agent_instance="test-owner-pid",
        slot_key="live-model-slot",
        owner_pid=pid,
        owner_start_time=start_time,
    )
    _age_active_request(store, request["request_id"])

    sweep = manager.sweep_stale_slots()

    assert sweep["swept_count"] == 0
    assert store.get_resource_request(request["request_id"]).state.value == "ACTIVE"
    assert store.get_receipt(f"stale_slot_auto_release_{request['request_id']}") is None
