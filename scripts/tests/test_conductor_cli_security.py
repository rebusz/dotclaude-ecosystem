"""End-to-end CLI and read-only surface regressions for TruthDeck Conductor."""

from __future__ import annotations

import io
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
from scripts.conductor_store import ConductorStore

ROOT = pathlib.Path(__file__).resolve().parents[2]


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


@pytest.mark.parametrize("command", ["status", "doctor"])
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
    assert completed.returncode == 0, completed.stderr
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
    before_mtime = store.db_path.stat().st_mtime_ns
    before_receipts = tuple(sorted(store.receipts_dir.iterdir()))
    with sqlite3.connect(store.db_path) as conn:
        before_leaders = conn.execute("SELECT * FROM leader_locks").fetchall()
    env = os.environ.copy()
    env["TDCONDUCTOR_DIR"] = str(conductor_home)

    for command in ("status", "doctor"):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "conductorctl.py"), command, "--json"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr

    with sqlite3.connect(store.db_path) as conn:
        after_leaders = conn.execute("SELECT * FROM leader_locks").fetchall()
    assert store.db_path.stat().st_mtime_ns == before_mtime
    assert tuple(sorted(store.receipts_dir.iterdir())) == before_receipts
    assert after_leaders == before_leaders


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
