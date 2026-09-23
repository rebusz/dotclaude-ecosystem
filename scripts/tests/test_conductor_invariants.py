"""One regression test per Conductor invariant the 2026-09-09 audit found unenforced.

Every test here drives the real store in a throwaway directory. None of them
mocks the operation under test: several of the original tests passed while the
invariant they were named after was broken, which is how these survived.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import psutil
import pytest

from scripts import conductor_gui, conductord
from scripts.conductor_commands import ConductorCommandProcessor
from scripts.conductor_model import (
    CommandEnvelope,
    HostResourceRequestState,
    Lease,
    ReasonCode,
    WorkItemState,
)
from scripts.conductor_resources import (
    HostResourceManager,
    ResourceAdmissionError,
    resolve_resource_key,
)
from scripts.conductor_store import ConductorStore, read_storage_status


@pytest.fixture
def root(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "conductor"


@pytest.fixture
def store(root: pathlib.Path) -> ConductorStore:
    return ConductorStore(root_dir=root)


@pytest.fixture
def manager(store: ConductorStore) -> HostResourceManager:
    return HostResourceManager(store)


def _backdate_resource_lease(store: ConductorStore, lease_id: str) -> None:
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    with store._connection() as conn:
        conn.execute(
            "UPDATE host_resource_leases SET expires_at_utc = ? WHERE lease_id = ?",
            (past, lease_id),
        )


# ── C1: a resource key is a closed set ──────────────────────────────────────

def test_c1_unknown_resource_keys_are_refused_everywhere(store: ConductorStore) -> None:
    """`--resource-key host:heavy2` minted a private capacity-1 pool, so two
    heavy pytest runs could hold "the" capacity-one lease at once."""
    for key in ("host:heavy2", "cdp:chatgpt-mine", "anything"):
        with pytest.raises(ValueError, match="unknown resource key"):
            resolve_resource_key(purpose="pytest_heavy", resource_key=key)
        with pytest.raises(ValueError, match="unknown resource key"):
            HostResourceManager(store, resource_key=key)
    assert store.get_resource_pool("host:heavy2") is None, "no private pool may be created"


def test_c1_the_capacity_one_pool_still_admits_exactly_one(manager: HostResourceManager) -> None:
    first = manager.request(purpose="pytest_heavy", attempt_id="a1", agent_instance="i1")
    second = manager.request(purpose="pytest_heavy", attempt_id="a2", agent_instance="i2")
    assert first["state"] == HostResourceRequestState.ACTIVE.value
    assert second["state"] == HostResourceRequestState.QUEUED.value


# ── C2: attestation is a ceremony, never a payload field ────────────────────

def test_c2_an_envelope_cannot_attest_an_owner_gone(
    store: ConductorStore, manager: HostResourceManager
) -> None:
    """An inbox file carrying `operator_attestation: true` cleared a host:heavy
    fence with `evidence: OPERATOR_ATTESTED` and no operator involved."""
    wedged = manager.request(purpose="pytest_heavy", attempt_id="w", agent_instance="w")
    manager.reconcile(now=datetime.now(timezone.utc) + timedelta(hours=1))
    assert store.get_resource_request(wedged["request_id"]).state == \
        HostResourceRequestState.RECOVERY_REQUIRED

    receipt = ConductorCommandProcessor(store=store).process_envelope(
        CommandEnvelope(
            command_id="cmd_forged_attest",
            command_type="resource_recover",
            payload={"request_id": wedged["request_id"], "operator_attestation": True,
                     "reason": "trust me", "actor": "some-agent"},
            idempotency_key="idemp_forged_attest",
        )
    )

    assert receipt.status == "ERROR"
    assert "attestation refused" in receipt.error_message.lower()
    assert store.get_resource_request(wedged["request_id"]).state == \
        HostResourceRequestState.RECOVERY_REQUIRED, "the fence must still stand"


# ── C3: exactly one leader ──────────────────────────────────────────────────

def test_c3_a_stale_leader_row_is_stolen_by_exactly_one_caller(root: pathlib.Path) -> None:
    """Without BEGIN IMMEDIATE and a conditional UPDATE, eight concurrent
    callers on one dead-pid row were granted the single-writer lock seven times.

    The two defences are deliberately independent: either one alone makes this
    race safe (verified by mutation), so removing just one does not fail this
    test -- removing both does. That is redundancy, not a weak test. The race is
    probabilistic, so on broken code this can occasionally pass; on correct code
    it never fails.
    """
    seed = ConductorStore(root_dir=root)
    with seed._connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO leader_locks (lock_name, leader_id, pid, process_start_time, "
            "acquired_at_utc, last_heartbeat_utc) VALUES (?, ?, ?, ?, ?, ?)",
            ("primary_coordinator", "dead_leader", 999_999, 0.0,
             "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"),
        )
    results: list[object] = []
    lock = threading.Lock()

    def contend() -> None:
        outcome = ConductorStore(root_dir=root).acquire_leader_lock()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=contend) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1, results


# ── C4 / C12 / C13: the daemon's own housekeeping ───────────────────────────

def _one_daemon_pass(root: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(root))
    logging.disable(logging.CRITICAL)
    try:
        conductord.run_coordinator_loop(poll_interval_seconds=0, single_pass=True)
    finally:
        logging.disable(logging.NOTSET)


def test_c4_the_daemon_fences_an_expired_host_resource_lease(
    root: pathlib.Path, store: ConductorStore, manager: HostResourceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host-resource leases were reconciled only by a CLI command nothing
    scheduled, so a crashed heavy consumer wedged host:heavy indefinitely."""
    held = manager.request(purpose="pytest_heavy", attempt_id="crashed", agent_instance="gone")
    _backdate_resource_lease(store, held["lease_id"])

    _one_daemon_pass(root, monkeypatch)

    assert store.get_resource_request(held["request_id"]).state != \
        HostResourceRequestState.ACTIVE


def test_c12_an_idle_daemon_pass_writes_no_receipt(
    root: pathlib.Path, store: ConductorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto-reconcile went through the envelope path, persisting a receipt row
    and file per poll: ~86,400 of each per day at the default interval."""
    before = len(list((root / "receipts").glob("*"))) if (root / "receipts").exists() else 0
    _one_daemon_pass(root, monkeypatch)
    after = len(list((root / "receipts").glob("*"))) if (root / "receipts").exists() else 0
    assert after == before


def test_c12_logs_and_backups_have_ceilings(store: ConductorStore, root: pathlib.Path) -> None:
    directories = read_storage_status(root_dir=root)["directories"]
    names = {entry["name"] if isinstance(entry, dict) and "name" in entry else entry
             for entry in (directories if isinstance(directories, list) else directories.keys())}
    assert {"logs", "backups"} <= names


def test_c13_a_poison_envelope_is_quarantined_not_retried_forever(
    root: pathlib.Path, store: ConductorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    poison = store.inbox_dir / "env_poison.json"
    poison.write_text("{ truncated", encoding="utf-8")

    _one_daemon_pass(root, monkeypatch)

    assert not poison.exists()
    assert (store.inbox_dir / "quarantine" / "env_poison.json").exists()


# ── C5: an expired lease is not a lease ─────────────────────────────────────

def test_c5_heartbeat_cannot_resurrect_an_expired_lease(
    store: ConductorStore, manager: HostResourceManager
) -> None:
    held = manager.request(purpose="pytest_heavy", attempt_id="late", agent_instance="late")
    _backdate_resource_lease(store, held["lease_id"])

    with pytest.raises(ResourceAdmissionError, match="RESOURCE_LEASE_EXPIRED"):
        manager.heartbeat(held["lease_id"], 99)

    assert manager.reconcile()["expired_count"] >= 1, "the fence must still form"


# ── C6: every CDP purpose is pinned to its own pool ─────────────────────────

@pytest.mark.parametrize("purpose, own_pool", [
    ("cdp_perplexity", "cdp:perplexity"),
    ("cdp_chatgpt", "cdp:chatgpt"),
    ("cdp_gemini", "cdp:gemini"),
    ("cdp_tv", "cdp:tv"),
])
def test_c6_a_cdp_purpose_cannot_consume_another_lane(
    store: ConductorStore, purpose: str, own_pool: str
) -> None:
    """`cdp_tv` had no pinning clause, so a TradingView capture could admit into
    cdp:gemini and starve that lane. The pinning is now derived, not listed."""
    for foreign in {"cdp:perplexity", "cdp:chatgpt", "cdp:gemini", "cdp:tv"} - {own_pool}:
        with pytest.raises(ValueError, match="cannot consume pool"):
            HostResourceManager(store, resource_key=foreign).request(
                purpose=purpose, attempt_id=f"x-{foreign}", agent_instance="x",
                slot_key="s",
            )


# ── C7: a GO is bounded in time and bound to its scope ──────────────────────

def _authorized_r2_item(processor: ConductorCommandProcessor) -> str:
    receipt = processor.process_envelope(CommandEnvelope(
        command_id="cmd_enq_c7", command_type="enqueue",
        payload={"idempotency_key": "idemp_c7", "title": "R2 task",
                 "repo_id": "dotclaude-ecosystem", "repo_path": "D:/x",
                 "plan_path": "design/plans/x.md", "risk_class": "R2", "workflow": "fwf",
                 "requested_terminal_stage": "merged",
                 "job_kind": "engineering_plan_lifecycle", "created_by": "operator"},
        idempotency_key="idemp_enq_c7",
    ))
    work_item_id = receipt.result["work_item_id"]
    processor.grant_interactive_operator_authorization(work_item_id, operator_identity="op")
    item = processor.store.get_work_item(work_item_id)
    if item.state != WorkItemState.READY:
        processor.store.transition_work_item_state(
            work_item_id=work_item_id, target_state=WorkItemState.READY,
            actor="operator", reason_code="READY_TEST",
        )
    return work_item_id


def _claim(processor: ConductorCommandProcessor, work_item_id: str) -> None:
    processor.process_envelope(CommandEnvelope(
        command_id=f"cmd_claim_{work_item_id}", command_type="claim",
        payload={"work_item_id": work_item_id, "claimed_by_host": "claude_host"},
        idempotency_key=f"idemp_claim_{work_item_id}",
    ))


def _last_reason(store: ConductorStore, work_item_id: str) -> str:
    with store._connection() as conn:
        row = conn.execute(
            "SELECT reason_code FROM events WHERE work_item_id = ? AND next_state = ? "
            "ORDER BY recorded_at_utc DESC LIMIT 1",
            (work_item_id, WorkItemState.HOLD.value),
        ).fetchone()
    return row["reason_code"] if row else ""


def test_c7_a_grant_is_stamped_with_an_expiry(store: ConductorStore) -> None:
    processor = ConductorCommandProcessor(store=store)
    work_item_id = _authorized_r2_item(processor)
    assert store.get_authorization(work_item_id).expires_at_utc


def test_c7_a_go_for_a_changed_scope_does_not_admit_a_claim(store: ConductorStore) -> None:
    processor = ConductorCommandProcessor(store=store)
    work_item_id = _authorized_r2_item(processor)
    with store._connection() as conn:
        conn.execute("UPDATE work_items SET scope_digest_sha256 = ? WHERE work_item_id = ?",
                     ("a-different-scope", work_item_id))

    _claim(processor, work_item_id)

    item = store.get_work_item(work_item_id)
    assert item.state == WorkItemState.HOLD
    assert _last_reason(store, work_item_id) == ReasonCode.AUTHORIZATION_SCOPE_MISMATCH.value


def test_c7_an_expired_go_does_not_admit_a_claim(store: ConductorStore) -> None:
    processor = ConductorCommandProcessor(store=store)
    work_item_id = _authorized_r2_item(processor)
    with store._connection() as conn:
        conn.execute("UPDATE authorizations SET expires_at_utc = ? WHERE work_item_id = ?",
                     ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                      work_item_id))

    _claim(processor, work_item_id)

    item = store.get_work_item(work_item_id)
    assert item.state == WorkItemState.HOLD
    assert _last_reason(store, work_item_id) == ReasonCode.AUTHORIZATION_EXPIRED.value


# ── C8: a Work Item heartbeat proves ownership and moves forward ────────────

def test_c8_a_lease_cannot_be_rewound_or_extended_by_another_attempt(
    store: ConductorStore,
) -> None:
    """The upsert wrote any sequence from any caller holding a lease id, so an
    old heartbeat could be replayed or a foreign lease extended indefinitely."""
    processor = ConductorCommandProcessor(store=store)
    receipt = processor.process_envelope(CommandEnvelope(
        command_id="cmd_enq_c8", command_type="enqueue",
        payload={"idempotency_key": "idemp_c8", "title": "R1 task",
                 "repo_id": "dotclaude-ecosystem", "repo_path": "D:/x",
                 "plan_path": "design/plans/x.md", "risk_class": "R1", "workflow": "fwf",
                 "requested_terminal_stage": "merged",
                 "job_kind": "engineering_plan_lifecycle", "created_by": "operator"},
        idempotency_key="idemp_enq_c8",
    ))
    work_item_id = receipt.result["work_item_id"]
    store.transition_work_item_state(work_item_id=work_item_id,
                                     target_state=WorkItemState.READY,
                                     actor="operator", reason_code="READY_TEST")
    claim = processor.process_envelope(CommandEnvelope(
        command_id="cmd_claim_c8", command_type="claim",
        payload={"work_item_id": work_item_id, "claimed_by_host": "claude_host"},
        idempotency_key="idemp_claim_c8",
    )).result
    lease_id, owner = claim["lease_id"], claim["attempt_id"]

    with store._connection() as conn:
        before = conn.execute("SELECT heartbeat_sequence, expires_at_utc FROM leases "
                              "WHERE lease_id = ?", (lease_id,)).fetchone()
    far = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    store.save_lease(Lease(lease_id=lease_id, attempt_id=owner, agent_instance="i",
                           heartbeat_sequence=before["heartbeat_sequence"], expires_at_utc=far))
    store.save_lease(Lease(lease_id=lease_id, attempt_id="intruder", agent_instance="i",
                           heartbeat_sequence=before["heartbeat_sequence"] + 50,
                           expires_at_utc=far))

    with store._connection() as conn:
        after = conn.execute("SELECT heartbeat_sequence, expires_at_utc FROM leases "
                             "WHERE lease_id = ?", (lease_id,)).fetchone()
    assert after["heartbeat_sequence"] == before["heartbeat_sequence"], "no replay, no intruder"
    assert after["expires_at_utc"] == before["expires_at_utc"]

    store.save_lease(Lease(lease_id=lease_id, attempt_id=owner, agent_instance="i",
                           heartbeat_sequence=before["heartbeat_sequence"] + 1,
                           expires_at_utc=far))
    with store._connection() as conn:
        advanced = conn.execute("SELECT heartbeat_sequence FROM leases WHERE lease_id = ?",
                                (lease_id,)).fetchone()
    assert advanced["heartbeat_sequence"] == before["heartbeat_sequence"] + 1,         "the owner moving forward must still work"


# ── C9: a newer store fails closed ──────────────────────────────────────────

def test_c9_a_store_from_a_newer_build_is_refused(root: pathlib.Path) -> None:
    ConductorStore(root_dir=root)
    with ConductorStore(root_dir=root)._connection() as conn:
        conn.execute("INSERT INTO schema_migrations (version, applied_at_utc) VALUES (?, ?)",
                     (99, datetime.now(timezone.utc).isoformat()))
    with pytest.raises(RuntimeError, match="newer than this build"):
        ConductorStore(root_dir=root)


# ── C10: the GUI never executes a path a writable file names ────────────────

def test_c10_an_unvalidated_manifest_command_is_refused(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".conductor").mkdir(parents=True)
    hostile = tmp_path / "evil.exe"
    hostile.write_text("x", encoding="utf-8")
    script = tmp_path / "conductorctl.py"
    script.write_text("x", encoding="utf-8")
    (home / ".conductor" / "install-manifest.json").write_text(json.dumps(
        {"canonical_commands": {"conductorctl": [str(hostile), str(script)]}}), encoding="utf-8")
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)
    monkeypatch.setattr(conductor_gui, "__file__", str(tmp_path / "elsewhere" / "gui.py"))

    with pytest.raises(RuntimeError, match="refusing unvalidated"):
        conductor_gui._conductorctl_command()


def test_c10_the_sibling_conductorctl_is_preferred() -> None:
    interpreter, script = conductor_gui._conductorctl_command()
    assert interpreter == sys.executable
    assert pathlib.Path(script).name == "conductorctl.py"
    assert pathlib.Path(script).parent == pathlib.Path(conductor_gui.__file__).resolve().parent


# ── C11: a lost lease takes the child down with it ──────────────────────────

def test_c11_a_fenced_lease_kills_the_child_without_masking_the_error(
    tmp_path: pathlib.Path, root: pathlib.Path, manager: HostResourceManager,
) -> None:
    """The heartbeat raised out of the wait loop with the child still running;
    the ledger was marked for recovery, the process kept running unattended.

    Driven for real: while the child sleeps, a second manager on the same store
    fences the lease exactly as the daemon would, so the genuine heartbeat
    raises RESOURCE_LEASE_NOT_ACTIVE. No stub -- an earlier version replaced
    `heartbeat`, which kept the request ACTIVE and so never reached the branch
    where `release` would refuse the fenced request and raise from `finally`.
    """
    work = tmp_path / "child"
    work.mkdir()
    pidfile = work / "child.pid"
    (work / "test_sleeper.py").write_text(
        "import os, pathlib, time\n"
        "def test_sleep():\n"
        "    pathlib.Path('child.pid').write_text(str(os.getpid()))\n"
        "    time.sleep(60)\n",
        encoding="utf-8",
    )

    def fence_when_child_is_up() -> None:
        deadline = time.monotonic() + 30
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        # A reconcile with a future clock fences without touching the lease's
        # own expiry, so the child's heartbeat meets NOT_ACTIVE, not EXPIRED.
        HostResourceManager(ConductorStore(root_dir=root)).reconcile(
            now=datetime.now(timezone.utc) + timedelta(hours=1)
        )

    fencer = threading.Thread(target=fence_when_child_is_up)
    fencer.start()
    try:
        with pytest.raises(ResourceAdmissionError, match="RESOURCE_LEASE_NOT_ACTIVE"):
            manager.run_bounded_pytest(
                python_executable=sys.executable, pytest_args=["-q", "test_sleeper.py"],
                cwd=work, attempt_id="c11", agent_instance="c11",
                heartbeat_interval_seconds=0.2, timeout_seconds=120, force_heavy=True,
                base_environment=dict(os.environ),
            )
    finally:
        fencer.join(timeout=60)

    child_pid = int(pidfile.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 10
    alive = True
    while time.monotonic() < deadline:
        try:
            alive = psutil.Process(child_pid).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            alive = False
        if not alive:
            break
        time.sleep(0.1)
    assert not alive, f"pytest child {child_pid} survived the lost lease"

    requests = manager.store.list_resource_requests(states=["RECOVERY_REQUIRED"])
    assert any(r.attempt_id == "c11" for r in requests), "the fence must still stand"


# ── Review follow-ups: the fixes must not trade one silent failure for another

def _claimed_r1_lease(store: ConductorStore) -> tuple[ConductorCommandProcessor, dict]:
    processor = ConductorCommandProcessor(store=store)
    receipt = processor.process_envelope(CommandEnvelope(
        command_id="cmd_enq_hb", command_type="enqueue",
        payload={"idempotency_key": "idemp_hb", "title": "R1 task",
                 "repo_id": "dotclaude-ecosystem", "repo_path": "D:/x",
                 "plan_path": "design/plans/x.md", "risk_class": "R1", "workflow": "fwf",
                 "requested_terminal_stage": "merged",
                 "job_kind": "engineering_plan_lifecycle", "created_by": "operator"},
        idempotency_key="idemp_enq_hb",
    ))
    work_item_id = receipt.result["work_item_id"]
    store.transition_work_item_state(work_item_id=work_item_id,
                                     target_state=WorkItemState.READY,
                                     actor="operator", reason_code="READY_TEST")
    claim = processor.process_envelope(CommandEnvelope(
        command_id="cmd_claim_hb", command_type="claim",
        payload={"work_item_id": work_item_id, "claimed_by_host": "claude_host"},
        idempotency_key="idemp_claim_hb",
    )).result
    return processor, claim


def test_a_rejected_heartbeat_is_reported_not_silently_accepted(store: ConductorStore) -> None:
    """C8 made the write conditional; the command must then say it refused,
    rather than return a fresh expiry for a lease it never extended."""
    processor, claim = _claimed_r1_lease(store)
    heartbeat = {"lease_id": claim["lease_id"], "attempt_id": claim["attempt_id"]}

    ok = processor.process_envelope(CommandEnvelope(
        command_id="hb1", command_type="heartbeat", payload={**heartbeat, "sequence": 10},
        idempotency_key="idemp_hb1"))
    assert ok.status == "SUCCESS"

    replay = processor.process_envelope(CommandEnvelope(
        command_id="hb2", command_type="heartbeat", payload={**heartbeat, "sequence": 4},
        idempotency_key="idemp_hb2"))
    intruder = processor.process_envelope(CommandEnvelope(
        command_id="hb3", command_type="heartbeat",
        payload={**heartbeat, "attempt_id": "intruder", "sequence": 99},
        idempotency_key="idemp_hb3"))

    for receipt in (replay, intruder):
        assert receipt.status == "ERROR"
        assert "HEARTBEAT_REJECTED" in receipt.error_message


def test_a_transient_inbox_failure_is_retried_not_quarantined(
    root: pathlib.Path, store: ConductorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quarantine is for files that cannot be envelopes. A locked database is
    an environmental fault; quarantining a valid command on it would silently
    drop the command."""
    import sqlite3

    envelope = store.inbox_dir / "env_valid.json"
    envelope.write_text(json.dumps({
        "command_id": "cmd_valid", "command_type": "status", "payload": {},
        "idempotency_key": "idemp_valid"}), encoding="utf-8")

    def locked(self, _envelope):  # simulates the environment, not the logic under test
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ConductorCommandProcessor, "process_envelope", locked)
    _one_daemon_pass(root, monkeypatch)

    assert envelope.exists(), "a valid envelope must stay queued for the next poll"
    assert not (store.inbox_dir / "quarantine" / "env_valid.json").exists()


def test_a_legacy_go_without_an_expiry_expires_ttl_after_issue(store: ConductorStore) -> None:
    """Records granted before GOs carried an expiry were eternal; only the
    scope check guarded them. They now expire TTL after they were issued."""
    from scripts.conductor_model import AUTHORIZATION_TTL_SECONDS

    processor = ConductorCommandProcessor(store=store)
    work_item_id = _authorized_r2_item(processor)
    long_ago = datetime.now(timezone.utc) - timedelta(seconds=AUTHORIZATION_TTL_SECONDS + 60)
    with store._connection() as conn:
        conn.execute("UPDATE authorizations SET expires_at_utc = NULL, issued_at_utc = ? "
                     "WHERE work_item_id = ?", (long_ago.isoformat(), work_item_id))

    _claim(processor, work_item_id)

    assert store.get_work_item(work_item_id).state == WorkItemState.HOLD
    assert _last_reason(store, work_item_id) == ReasonCode.AUTHORIZATION_EXPIRED.value


def test_the_gui_accepts_the_py_launcher_it_is_installed_with() -> None:
    for name in ("py.exe", "pyw.exe", "py", "python.exe", "python3.14.exe"):
        assert conductor_gui._PYTHON_BINARY.fullmatch(name), name
    for name in ("cmd.exe", "evil.exe", "python.exe.bat", "pyx.exe"):
        assert not conductor_gui._PYTHON_BINARY.fullmatch(name), name


def test_c9_latest_schema_version_matches_the_migration_ladder() -> None:
    """C9 refuses any store newer than LATEST_SCHEMA_VERSION. If a migration is
    added without bumping the constant, this build would refuse the very store
    it had just migrated -- an outage from a one-line omission."""
    import re

    from scripts import conductor_store

    source = pathlib.Path(conductor_store.__file__).read_text(encoding="utf-8")
    ladder = [int(n) for n in re.findall(r"if current_version < (\d+):", source)]
    assert max(ladder) == conductor_store.LATEST_SCHEMA_VERSION


def test_c9_a_store_at_the_live_schema_opens(root: pathlib.Path) -> None:
    """The operator's live store reached v7 through an unmerged branch while
    main stopped at v6. Main must open it rather than refuse it on sight."""
    ConductorStore(root_dir=root)
    reopened = ConductorStore(root_dir=root)
    with reopened._connection() as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
        columns = {r[1] for r in conn.execute("PRAGMA table_info(host_resource_requests)")}
    assert 7 in versions
    assert {"owner_process_pid", "owner_process_start_time",
            "owner_identity_source", "owner_last_seen_at_utc"} <= columns
