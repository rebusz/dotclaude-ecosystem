"""End-to-end CLI and read-only surface regressions for TruthDeck Conductor."""

from __future__ import annotations

import io
import hashlib
import json
import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest

from scripts import conductorctl
from scripts.conductor_mcp import handle_mcp_tool_call
from scripts.conductor_model import CommandEnvelope, WorkItemState
from scripts.conductor_commands import ConductorCommandProcessor
from scripts.conductor_store import (
    ConductorStore,
    read_resource_live_snapshot,
    read_store_status,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _tree_snapshot(root: pathlib.Path) -> dict[str, tuple[int, int, str]]:
    return {
        str(path.relative_to(root)): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class _TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def _enqueue_r2(root: pathlib.Path) -> tuple[ConductorStore, str]:
    store = ConductorStore(root_dir=root)
    processor = ConductorCommandProcessor(store)
    receipt = processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_cli_enq",
            command_type="enqueue",
            payload={
                "idempotency_key": "cli-r2",
                "title": "CLI R2",
                "repo_id": "repo",
                "repo_path": "D:/repo",
                "plan_path": "design/plans/test.md",
                "risk_class": "R2",
                "workflow": "fwf",
                "requested_terminal_stage": "merged",
                "job_kind": "engineering_plan_lifecycle",
                "created_by": "operator",
            },
            idempotency_key="cli-r2-enqueue",
        )
    )
    return store, receipt.result["work_item_id"]


@pytest.mark.parametrize("command", ["status", "doctor", "resource-live"])
def test_cli_read_only_commands_do_not_create_home(tmp_path: pathlib.Path, command: str):
    conductor_home = tmp_path / f"{command}-absent"
    env = os.environ.copy()
    env["TDCONDUCTOR_DIR"] = str(conductor_home)
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "conductorctl.py"), command, "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (completed.returncode == 0 if command == "status" else completed.returncode in {0, 1}), completed.stderr
    assert json.loads(completed.stdout)
    assert not conductor_home.exists()


def test_mcp_read_tools_do_not_create_home(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    conductor_home = tmp_path / "mcp-absent"
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(conductor_home))
    status = handle_mcp_tool_call("conductor_status", {})
    missing = handle_mcp_tool_call("conductor_get_work_item", {"work_item_id": "missing"})
    unknown = handle_mcp_tool_call("unknown_tool", {})
    assert status["store_state"] == "ABSENT"
    assert "error" in missing
    assert "error" in unknown
    assert not conductor_home.exists()


def test_status_and_doctor_do_not_write_existing_store(tmp_path: pathlib.Path):
    conductor_home = tmp_path / "existing"
    store = ConductorStore(root_dir=conductor_home)
    assert store.acquire_leader_lock()
    before_status = read_store_status(conductor_home)
    before_tree = _tree_snapshot(conductor_home)
    env = os.environ.copy()
    env["TDCONDUCTOR_DIR"] = str(conductor_home)

    for command in ("status", "doctor", "resource-live"):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "conductorctl.py"), command, "--json"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert (completed.returncode == 0 if command == "status" else completed.returncode in {0, 1}), completed.stderr
        assert json.loads(completed.stdout)

    after_status = read_store_status(conductor_home)
    assert _tree_snapshot(conductor_home) == before_tree
    assert after_status == before_status


def test_read_only_status_sees_uncheckpointed_wal_without_touching_source(tmp_path: pathlib.Path):
    conductor_home = tmp_path / "wal-live"
    conductor_home.mkdir()
    db_path = conductor_home / "conductor.db"
    writer = sqlite3.connect(db_path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE work_items (state TEXT NOT NULL)")
        writer.execute(
            "CREATE TABLE leader_locks (lock_name TEXT PRIMARY KEY, leader_id TEXT, pid INTEGER, process_start_time REAL)"
        )
        writer.execute("INSERT INTO work_items (state) VALUES ('QUEUED')")
        writer.commit()
        before_tree = _tree_snapshot(conductor_home)

        status = read_store_status(conductor_home)

        assert status["store_state"] == "AVAILABLE"
        assert status["total_work_items"] == 1
        assert status["state_summary"] == {"QUEUED": 1}
        assert _tree_snapshot(conductor_home) == before_tree
    finally:
        writer.close()


def test_read_only_resource_live_sees_uncheckpointed_wal_without_touching_source(tmp_path: pathlib.Path):
    conductor_home = tmp_path / "wal-resource-live"
    conductor_home.mkdir()
    db_path = conductor_home / "conductor.db"
    writer = sqlite3.connect(db_path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            """
            CREATE TABLE host_resource_pools (
                resource_key TEXT PRIMARY KEY,
                capacity INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                schema_version TEXT NOT NULL
            )
            """
        )
        writer.execute(
            """
            CREATE TABLE host_resource_requests (
                request_id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE NOT NULL,
                resource_key TEXT NOT NULL,
                purpose TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                agent_instance TEXT NOT NULL,
                state TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 50,
                parent_lease_id TEXT,
                command_sha256 TEXT NOT NULL DEFAULT '',
                created_at_utc TEXT NOT NULL,
                released_at_utc TEXT,
                reason_code TEXT,
                schema_version TEXT NOT NULL
            )
            """
        )
        writer.execute(
            """
            CREATE TABLE host_resource_leases (
                lease_id TEXT PRIMARY KEY,
                request_id TEXT UNIQUE NOT NULL,
                resource_key TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                agent_instance TEXT NOT NULL,
                heartbeat_sequence INTEGER NOT NULL,
                expires_at_utc TEXT NOT NULL,
                last_heartbeat_utc TEXT NOT NULL,
                process_pid INTEGER,
                process_start_time REAL,
                schema_version TEXT NOT NULL
            )
            """
        )
        writer.execute(
            "INSERT INTO host_resource_pools VALUES ('host:heavy', 1, 1, 'conductor.resource-pool.v1')"
        )
        writer.execute(
            """
            INSERT INTO host_resource_requests VALUES (
                'rr_wal01', 'idemp_wal01', 'host:heavy', 'pytest_full', 'at-wal',
                'agent-wal', 'QUEUED', 50, NULL, '', '2026-08-28T10:00:00Z', NULL,
                'HOST_RESOURCE_BUSY', 'conductor.resource-request.v1'
            )
            """
        )
        writer.commit()
        before_tree = _tree_snapshot(conductor_home)

        live = read_resource_live_snapshot(resource_key="host:heavy", root_dir=conductor_home)

        assert live["pool_present"] is True
        assert live["capacity"] == 1
        assert live["enabled"] is True
        assert live["live_counts"]["QUEUED"] == 1
        assert len(live["queue"]) == 1
        assert live["queue"][0]["request_id"] == "rr_wal01"
        assert _tree_snapshot(conductor_home) == before_tree
    finally:
        writer.close()


def test_redirected_authorization_fails_before_store_creation(tmp_path: pathlib.Path):
    conductor_home = tmp_path / "redirected-auth"
    env = os.environ.copy()
    env["TDCONDUCTOR_DIR"] = str(conductor_home)
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "conductorctl.py"),
            "authorize",
            "--work-item-id",
            "wi_forged",
        ],
        cwd=tmp_path,
        env=env,
        input="GO wi_forged\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 1
    assert "attached interactive console tty" in completed.stderr.lower()
    assert not conductor_home.exists()


def test_attached_tty_exact_confirmation_grants_authorization(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    conductor_home = tmp_path / "interactive-auth"
    store, work_item_id = _enqueue_r2(conductor_home)
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(conductor_home))
    monkeypatch.setattr(sys, "stdin", _TTY(f"GO {work_item_id}\n"))
    output = _TTY()
    monkeypatch.setattr(sys, "stdout", output)

    exit_code = conductorctl.main(["authorize", "--work-item-id", work_item_id])

    assert exit_code == 0
    assert json.loads(output.getvalue().split(": ", 1)[1])["status"] == "AUTHORIZED"
    assert store.get_authorization(work_item_id) is not None
    assert store.get_work_item(work_item_id).state == WorkItemState.READY


def test_attached_tty_wrong_confirmation_does_not_grant(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    conductor_home = tmp_path / "interactive-reject"
    store, work_item_id = _enqueue_r2(conductor_home)
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(conductor_home))
    monkeypatch.setattr(sys, "stdin", _TTY("GO wrong-item\n"))
    monkeypatch.setattr(sys, "stdout", _TTY())
    monkeypatch.setattr(sys, "stderr", _TTY())

    exit_code = conductorctl.main(["authorize", "--work-item-id", work_item_id])

    assert exit_code == 1
    assert store.get_authorization(work_item_id) is None
    assert store.get_work_item(work_item_id).state == WorkItemState.QUEUED


def test_resource_live_all_and_doctor_leave_tree_byte_identical_with_four_pools(
    tmp_path: pathlib.Path,
):
    """READ-ONLY test:
    resource-live --all and doctor leave tree byte-identical with four pools,
    and create no home when run against absent dir.
    """
    conductor_home = tmp_path / "four-pools-read-only"
    store = ConductorStore(root_dir=conductor_home)

    env = os.environ.copy()
    env["TDCONDUCTOR_DIR"] = str(conductor_home)

    snapshot_before = _tree_snapshot(conductor_home)

    # 1. resource-live --all
    completed1 = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "conductorctl.py"), "resource-live", "--all", "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed1.returncode == 0, completed1.stderr
    res1 = json.loads(completed1.stdout)
    assert len(res1) >= 4
    assert _tree_snapshot(conductor_home) == snapshot_before

    # 2. doctor
    completed2 = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "conductorctl.py"), "doctor", "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed2.returncode == 0, completed2.stderr
    assert _tree_snapshot(conductor_home) == snapshot_before

    # 3. Absent home check
    absent_home = tmp_path / "resource-live-all-absent"
    env_absent = os.environ.copy()
    env_absent["TDCONDUCTOR_DIR"] = str(absent_home)
    completed_absent = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "conductorctl.py"), "resource-live", "--all", "--json"],
        cwd=tmp_path,
        env=env_absent,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed_absent.returncode == 0, completed_absent.stderr
    assert not absent_home.exists()
