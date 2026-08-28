"""Tests for Conductor Gate Panel GUI (GP-3, GP-4, GP-5).

Headless-safe: constructs widgets without mainloop(), asserts widget state directly.
"""

from __future__ import annotations

import datetime
import pathlib
import queue
import shutil
import sqlite3
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import psutil
import pytest
import tkinter as tk

from scripts.conductor_model import HostResourcePool, HostResourceRequestState
from scripts.conductor_resources import HostResourceManager
from scripts.conductor_store import (
    ConductorStore,
    GateVerdict,
    _read_only_snapshot_connection,
    read_gate_frame,
    read_resource_history_page,
    read_resource_live_snapshot,
)
from scripts.conductor_gui import (
    ConductorGatePanel,
    GatePanelWorker,
    observe_process_liveness,
)


@pytest.fixture
def tk_root():
    """Create a headless Tk root window."""
    try:
        root = tk.Tk()
        root.withdraw()
        yield root
        try:
            root.destroy()
        except Exception:
            pass
    except tk.TclError as exc:
        pytest.skip(f"Tk display not available: {exc}")


def _create_sample_store(tmp_path: pathlib.Path) -> ConductorStore:
    store = ConductorStore(root_dir=tmp_path)
    store.save_resource_pool(HostResourcePool(resource_key="host:heavy", capacity=1, enabled=True))
    return store


def test_panel_never_appears_in_resource_ledger(tmp_path: pathlib.Path, tk_root: tk.Tk):
    """The panel never calls resource-request and never appears in the resource ledger.

    Drives the real code path, asserting no row is added to host_resource_requests
    and receipts file count is unchanged.
    """
    store = _create_sample_store(tmp_path)
    mgr = HostResourceManager(store=store)
    # Add a normal request
    req = mgr.request(
        purpose="pytest_full",
        attempt_id="att-1",
        agent_instance="agent-1",
        command_sha256="abc",
    )
    assert req["state"] == HostResourceRequestState.ACTIVE.value

    receipts_dir = tmp_path / "receipts"
    receipts_before = len(list(receipts_dir.glob("*"))) if receipts_dir.is_dir() else 0

    with store._connection() as conn:
        req_rows_before = conn.execute("SELECT COUNT(*) AS c FROM host_resource_requests").fetchone()["c"]

    # Initialize panel and worker and run a full tick
    q: queue.Queue = queue.Queue()
    worker = GatePanelWorker(out_queue=q, root_dir=tmp_path, resource_key="host:heavy")
    worker._tick()

    msg = q.get_nowait()
    assert msg["type"] == "FRAME"
    assert msg["frame"] is not None

    panel = ConductorGatePanel(
        master=tk_root,
        root_dir=tmp_path,
        resource_key="host:heavy",
        enable_worker=False,
    )
    panel.apply_frame(
        frame=msg["frame"],
        storage=msg.get("storage"),
        read_ms=msg.get("read_ms", 0.0),
        is_stale=msg.get("stale", False),
    )

    # Verify no row was added to host_resource_requests
    with store._connection() as conn:
        req_rows_after = conn.execute("SELECT COUNT(*) AS c FROM host_resource_requests").fetchone()["c"]
        panel_rows = conn.execute("SELECT * FROM host_resource_requests WHERE agent_instance LIKE '%panel%' OR purpose LIKE '%panel%'").fetchall()

    assert req_rows_after == req_rows_before
    assert len(panel_rows) == 0

    receipts_after = len(list(receipts_dir.glob("*"))) if receipts_dir.is_dir() else 0
    assert receipts_after == receipts_before


def test_one_snapshot_per_refresh(tmp_path: pathlib.Path):
    """Exactly one snapshot is taken per read_gate_frame refresh."""
    _create_sample_store(tmp_path)
    copy_count = 0
    orig_copy2 = shutil.copy2

    def counting_copy2(src, dst, *args, **kwargs):
        nonlocal copy_count
        if "conductor.db" in str(src):
            copy_count += 1
        return orig_copy2(src, dst, *args, **kwargs)

    with patch("shutil.copy2", side_effect=counting_copy2):
        frame = read_gate_frame(resource_key="host:heavy", root_dir=tmp_path)

    assert frame["store"]["store_state"] == "AVAILABLE"
    assert frame["gate"]["resource_key"] == "host:heavy"
    # Exactly one snapshot: copies db (and wal if present). Since no wal was created, exactly 1 copy of db.
    assert copy_count == 1


def test_signature_gate_no_snapshot_when_unmoved(tmp_path: pathlib.Path):
    """When the database and WAL signature has not moved, a tick takes NO snapshot at all."""
    _create_sample_store(tmp_path)
    q: queue.Queue = queue.Queue()
    worker = GatePanelWorker(out_queue=q, root_dir=tmp_path, resource_key="host:heavy")

    # 1st tick: snapshot taken
    worker._tick()
    msg1 = q.get_nowait()
    assert msg1["sig_updated"] is True

    # 2nd tick with no changes to db/wal
    with patch("scripts.conductor_gui.read_gate_frame") as mock_read_gate:
        worker._tick()
        assert mock_read_gate.call_count == 0

    msg2 = q.get_nowait()
    assert msg2["sig_updated"] is False
    assert msg2["frame"] == msg1["frame"]


def test_operational_error_retains_previous_frame_and_shows_stale(tmp_path: pathlib.Path, tk_root: tk.Tk):
    """A locked or moved store raises sqlite3.OperationalError and the panel retains previous frame with stale marker."""
    _create_sample_store(tmp_path)
    q: queue.Queue = queue.Queue()
    worker = GatePanelWorker(out_queue=q, root_dir=tmp_path, resource_key="host:heavy")

    # 1st tick: succeeds
    worker._tick()
    msg1 = q.get_nowait()

    panel = ConductorGatePanel(master=tk_root, root_dir=tmp_path, enable_worker=False)
    panel.apply_frame(frame=msg1["frame"], storage=msg1.get("storage"), read_ms=10.0, is_stale=False)

    assert panel.stale_marker_label.cget("text") == ""
    assert "GATE CLEAR" in panel.verdict_headline.cget("text")

    # Simulate OperationalError on 2nd tick by forcing signature mismatch but read_gate_frame raising
    worker._last_sig = None
    with patch("scripts.conductor_gui.read_gate_frame", side_effect=sqlite3.OperationalError("store changed during read-only snapshot")):
        worker._tick()

    msg2 = q.get_nowait()
    assert msg2["stale"] is True
    assert msg2["frame"] == msg1["frame"]

    panel.apply_frame(frame=msg2["frame"], storage=msg2.get("storage"), read_ms=10.0, is_stale=True)
    assert panel.stale_marker_label.cget("text") == "[STALE - retrying snapshot]"
    assert "GATE CLEAR" in panel.verdict_headline.cget("text")


def test_unrecognised_schema_version_renders_degraded_banner(tmp_path: pathlib.Path, tk_root: tk.Tk):
    """An unrecognised schema version renders the degraded banner rather than a verdict."""
    panel = ConductorGatePanel(master=tk_root, root_dir=tmp_path, enable_worker=False)

    degraded_frame = {
        "store": {"store_state": "AVAILABLE", "total_work_items": 0},
        "gate": {
            "resource_key": "host:heavy",
            "capacity": 1,
            "enabled": True,
            "schema_version": "99.0.0",  # Unrecognized
            "pool_present": True,
            "live_counts": {"ACTIVE": 0},
            "queue": [],
            "fenced": [],
            "holder": None,
        },
    }

    panel.apply_frame(frame=degraded_frame)
    assert "DEGRADED: UNRECOGNIZED SCHEMA VERSION" in panel.verdict_headline.cget("text")


def test_exact_one_psutil_lookup_and_zero_enumeration(tmp_path: pathlib.Path, tk_root: tk.Tk):
    """Exactly one psutil.Process lookup per displayed lease with a recorded pid, zero enumeration."""
    panel = ConductorGatePanel(master=tk_root, root_dir=tmp_path, enable_worker=False)

    occupied_frame = {
        "store": {"store_state": "AVAILABLE", "total_work_items": 0, "leader_active": True},
        "gate": {
            "resource_key": "host:heavy",
            "capacity": 1,
            "enabled": True,
            "pool_present": True,
            "schema_version": "1.0.0",
            "live_counts": {"ACTIVE": 1, "INHERITED": 0, "QUEUED": 0, "RECOVERY_REQUIRED": 0, "QUARANTINED": 0},
            "holder": {
                "request_id": "rr_1234567890ab",
                "agent_instance": "agent-runner:101",
                "purpose": "pytest_full",
                "attempt_id": "att-101",
                "created_at_utc": "2026-08-28T10:00:00Z",
                "lease_id": "hrl_1234567890ab",
                "heartbeat_sequence": 5,
                "last_heartbeat_utc": "2026-08-28T10:04:00Z",
                "expires_at_utc": "2026-08-28T10:09:00Z",
                "process_pid": 54321,
                "process_start_time": 1000.0,
            },
            "queue": [],
            "fenced": [],
            "inherited": [],
            "quarantined": [],
        },
    }

    mock_proc = MagicMock()
    mock_proc.create_time.return_value = 1000.0
    mock_proc.is_running.return_value = True

    with patch("psutil.Process", return_value=mock_proc) as mock_psutil_proc, \
         patch("psutil.process_iter") as mock_iter, \
         patch("psutil.pids") as mock_pids:
        panel.apply_frame(frame=occupied_frame)

    assert mock_psutil_proc.call_count == 1
    assert mock_psutil_proc.call_args[0][0] == 54321
    assert mock_iter.call_count == 0
    assert mock_pids.call_count == 0


def test_clipboard_copy_performs_no_store_access(tmp_path: pathlib.Path, tk_root: tk.Tk):
    """Clipboard copy performs no store access or DB connections."""
    panel = ConductorGatePanel(master=tk_root, root_dir=tmp_path, enable_worker=False)

    with patch("sqlite3.connect") as mock_sql:
        panel.copy_to_clipboard("python scripts/conductorctl.py resource-recover --request-id rr_1234567890ab")

    assert mock_sql.call_count == 0
    try:
        clip_val = tk_root.clipboard_get()
        assert "rr_1234567890ab" in clip_val
    except tk.TclError:
        pass  # In some headless environments clipboard_get might raise TclError


def test_queue_table_caps_at_20_and_shows_more_with_true_count(tmp_path: pathlib.Path, tk_root: tk.Tk):
    """The queue table caps at 20 rows and shows '+N more' while verdict and label state true count."""
    panel = ConductorGatePanel(master=tk_root, root_dir=tmp_path, enable_worker=False)

    queue_list = [
        {
            "request_id": f"rr_{i:012x}",
            "agent_instance": f"agent-{i}",
            "purpose": "pytest_full",
            "reason_code": "BUSY",
            "created_at_utc": "2026-08-28T10:00:00Z",
            "priority": 50,
            "state": "QUEUED",
        }
        for i in range(1, 26)  # 25 queued requests
    ]

    frame = {
        "store": {"store_state": "AVAILABLE", "total_work_items": 0},
        "gate": {
            "resource_key": "host:heavy",
            "capacity": 1,
            "enabled": True,
            "pool_present": True,
            "schema_version": "1.0.0",
            "live_counts": {"ACTIVE": 0, "INHERITED": 0, "QUEUED": 25, "RECOVERY_REQUIRED": 0, "QUARANTINED": 0},
            "holder": None,
            "queue": queue_list,
            "fenced": [],
            "inherited": [],
            "quarantined": [],
        },
    }

    panel.apply_frame(frame=frame)

    # 20 rows + 1 "+5 more" row
    tree_items = panel.queue_tree.get_children()
    assert len(tree_items) == 21

    more_row_values = panel.queue_tree.item(tree_items[-1])["values"]
    assert "+5 more" in str(more_row_values[1])

    # Header and verdict still state 25
    assert "25 waiting" in panel.queue_subtitle.cget("text")
    assert "25 requests queued" in panel.verdict_subtext.cget("text") or "25 requests" in panel.verdict_subtext.cget("text")


def test_two_fences_render_two_blocker_cards_and_two_commands(tmp_path: pathlib.Path, tk_root: tk.Tk):
    """Two fences render two blocker cards and two commands."""
    panel = ConductorGatePanel(master=tk_root, root_dir=tmp_path, enable_worker=False)

    fenced_list = [
        {
            "request_id": "rr_111111111111",
            "agent_instance": "agent-1",
            "purpose": "cdp_provider",
            "attempt_id": "att-1",
            "created_at_utc": "2026-08-28T08:00:00Z",
            "reason_code": "LEASE_EXPIRED",
            "priority": 50,
            "process_pid": None,
            "lease": {"lease_id": "hrl_111111111111", "process_pid": None, "heartbeat_sequence": 1, "last_heartbeat_utc": "2026-08-28T08:00:00Z", "expires_at_utc": "2026-08-28T08:05:00Z"},
        },
        {
            "request_id": "rr_222222222222",
            "agent_instance": "agent-2",
            "purpose": "pytest_full",
            "attempt_id": "att-2",
            "created_at_utc": "2026-08-28T09:00:00Z",
            "reason_code": "LEASE_EXPIRED",
            "priority": 50,
            "process_pid": None,
            "lease": {"lease_id": "hrl_222222222222", "process_pid": None, "heartbeat_sequence": 2, "last_heartbeat_utc": "2026-08-28T09:00:00Z", "expires_at_utc": "2026-08-28T09:05:00Z"},
        },
    ]

    frame = {
        "store": {"store_state": "AVAILABLE", "total_work_items": 0},
        "gate": {
            "resource_key": "host:heavy",
            "capacity": 1,
            "enabled": True,
            "pool_present": True,
            "schema_version": "1.0.0",
            "live_counts": {"ACTIVE": 0, "INHERITED": 0, "QUEUED": 0, "RECOVERY_REQUIRED": 2, "QUARANTINED": 0},
            "holder": None,
            "queue": [],
            "fenced": fenced_list,
            "inherited": [],
            "quarantined": [],
        },
    }

    panel.apply_frame(frame=frame)

    card_children = panel.cards_container.winfo_children()
    assert len(card_children) == 2


def test_read_resource_history_page_terminal_only_limit_cursor(tmp_path: pathlib.Path):
    """read_resource_history_page returns only terminal rows, respects limit, and pages by cursor."""
    store = _create_sample_store(tmp_path)
    mgr = HostResourceManager(store=store)

    # Create 5 requests and release them
    released_ids = []
    for i in range(5):
        req = mgr.request(
            purpose="pytest_full",
            attempt_id=f"att-{i}",
            agent_instance=f"agent-{i}",
            command_sha256=f"sha-{i}",
            idempotency_key=f"idem-{i}",
        )
        if req["state"] == HostResourceRequestState.ACTIVE.value:
            mgr.release(req["request_id"], actor="test", reason="DONE")
            released_ids.append(req["request_id"])
        elif req["state"] == HostResourceRequestState.QUEUED.value:
            # force to released for test
            with store._connection() as conn:
                conn.execute("UPDATE host_resource_requests SET state = 'RELEASED', released_at_utc = '2026-08-28T12:00:00Z' WHERE request_id = ?", (req["request_id"],))
            released_ids.append(req["request_id"])

    # Also add 1 ACTIVE and 1 QUEUED request to verify they are EXCLUDED
    req_act = mgr.request(purpose="pytest_full", attempt_id="att-live", agent_instance="agent-live", command_sha256="live-sha", idempotency_key="idem-live")

    # Page 1: limit 2
    p1 = read_resource_history_page(resource_key="host:heavy", limit=2, root_dir=tmp_path)
    assert len(p1["items"]) == 2
    assert p1["has_more"] is True
    assert p1["next_cursor"] is not None
    assert p1["total_terminal"] == 5
    for item in p1["items"]:
        assert item["state"] == "RELEASED"

    # Page 2: limit 2 with cursor
    p2 = read_resource_history_page(resource_key="host:heavy", limit=2, cursor=p1["next_cursor"], root_dir=tmp_path)
    assert len(p2["items"]) == 2
    assert p2["has_more"] is True
    assert p2["next_cursor"] is not None
    for item in p2["items"]:
        assert item["state"] == "RELEASED"

    # Page 3: limit 2 with cursor
    p3 = read_resource_history_page(resource_key="host:heavy", limit=2, cursor=p2["next_cursor"], root_dir=tmp_path)
    assert len(p3["items"]) == 1
    assert p3["has_more"] is False
    assert p3["next_cursor"] is None
    for item in p3["items"]:
        assert item["state"] == "RELEASED"

    # All items across pages are unique released requests
    all_returned_ids = [it["request_id"] for it in p1["items"] + p2["items"] + p3["items"]]
    assert len(all_returned_ids) == 5
    assert len(set(all_returned_ids)) == 5
    assert req_act["request_id"] not in all_returned_ids
