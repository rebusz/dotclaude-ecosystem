#!/usr/bin/env python3
"""Conductor Gate Panel - read-only operator GUI for host:heavy.

Port-free, single-writer WAL reader via read-only snapshot.
Runs change-check ticks on a worker thread using _file_signature.
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import queue
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Union

import psutil
import tkinter as tk
from tkinter import ttk

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Import store and verdict functions from conductor_store
from scripts.conductor_store import (
    GateVerdict,
    GateVerdictResult,
    RecoveryAdjudication,
    adjudicate_recovery,
    evaluate_gate_verdict,
    format_duration,
    get_default_conductor_dir,
    read_gate_frame,
    read_resource_history_page,
    read_storage_status,
    _file_signature,
)

# Semantic Colors
COLOR_CLEAR = "#2e7d32"      # Green
COLOR_CLEAR_BG = "#e8f5e9"
COLOR_CLEAR_FG = "#1b5e20"

COLOR_OCCUPIED = "#f57c00"   # Amber
COLOR_OCCUPIED_BG = "#fff3e0"
COLOR_OCCUPIED_FG = "#e65100"

COLOR_FENCED = "#d32f2f"     # Red
COLOR_FENCED_BG = "#ffebee"
COLOR_FENCED_FG = "#b71c1c"

COLOR_DISABLED = "#c62828"   # Dark Red
COLOR_ANOMALY = "#ad1457"    # Dark Pink/Red
COLOR_DEGRADED = "#6a1b9a"   # Purple
COLOR_DEGRADED_BG = "#f3e5f5"
COLOR_DEGRADED_FG = "#4a148c"

COLOR_NEUTRAL_BG = "#f8f9fa"
COLOR_CARD_BG = "#ffffff"
COLOR_BORDER = "#dcdcdc"
COLOR_TEXT = "#212529"
COLOR_MUTED = "#6c757d"
COLOR_STALE = "#e65100"

FONT_FAMILY_UI = "Segoe UI" if sys.platform == "win32" else "Helvetica"
FONT_FAMILY_MONO = "Consolas" if sys.platform == "win32" else "Courier"


def observe_process_liveness(pid: Optional[int], start_time: Optional[float]) -> str:
    """Adjudicate ONLY the recorded pid, exactly one psutil lookup, zero enumeration."""
    if pid is None:
        return "not recorded, liveness cannot be adjudicated"
    try:
        proc = psutil.Process(int(pid))
        obs_start = proc.create_time()
        if start_time is not None and abs(obs_start - float(start_time)) > 1.0:
            return f"recorded pid {pid} is not running (pid reused)"
        return f"pid {pid}, alive"
    except (OSError, ValueError, psutil.Error):
        return f"recorded pid {pid} is not running"


class GatePanelWorker:
    """Background worker thread for signature-gated snapshot reads."""

    def __init__(
        self,
        out_queue: queue.Queue,
        root_dir: Optional[Union[str, pathlib.Path]] = None,
        resource_key: str = "host:heavy",
        interval_sec: float = 2.0,
    ):
        self.out_queue = out_queue
        self.root_dir = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
        self.resource_key = resource_key
        self.interval_sec = max(0.5, float(interval_sec))
        self.db_path = self.root_dir / "conductor.db"
        self.wal_path = self.root_dir / "conductor.db-wal"

        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._is_paused = False
        self._thread: Optional[threading.Thread] = None

        self._last_sig: Optional[tuple[Any, Any]] = None
        self._last_frame: Optional[Dict[str, Any]] = None
        self._last_storage: Optional[Dict[str, Any]] = None
        self._last_storage_time: float = 0.0
        self._last_read_ms: float = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, name="ConductorGateWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def pause(self) -> None:
        self._is_paused = True

    def resume(self) -> None:
        self._is_paused = False
        self._wake_event.set()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._is_paused:
                self._wake_event.wait(timeout=0.5)
                self._wake_event.clear()
                continue

            try:
                self._tick()
            except Exception as exc:
                self.out_queue.put({
                    "type": "ERROR",
                    "error": str(exc),
                    "timestamp": time.time(),
                })

            self._wake_event.wait(timeout=self.interval_sec)
            self._wake_event.clear()

    def _tick(self) -> None:
        sig_db = _file_signature(self.db_path)
        sig_wal = _file_signature(self.wal_path)
        current_sig = (sig_db, sig_wal)

        frame_updated = False
        is_stale = False
        read_ms = self._last_read_ms

        if current_sig != self._last_sig or self._last_frame is None:
            t0 = time.perf_counter()
            try:
                frame = read_gate_frame(resource_key=self.resource_key, root_dir=self.root_dir)
                read_ms = (time.perf_counter() - t0) * 1000.0
                self._last_frame = frame
                self._last_sig = current_sig
                self._last_read_ms = read_ms
                frame_updated = True
            except Exception as exc:
                # sqlite3.OperationalError or transient copy error -> retain previous frame, mark stale
                if "store changed during read-only snapshot" in str(exc) or "OperationalError" in type(exc).__name__:
                    is_stale = True
                else:
                    raise

        # Storage status on its own 60s timer
        now_mono = time.monotonic()
        if self._last_storage is None or (now_mono - self._last_storage_time >= 60.0):
            try:
                self._last_storage = read_storage_status(root_dir=self.root_dir)
                self._last_storage_time = now_mono
            except Exception:
                pass  # retain last value

        self.out_queue.put({
            "type": "FRAME",
            "frame": self._last_frame,
            "storage": self._last_storage,
            "read_ms": read_ms,
            "stale": is_stale,
            "sig_updated": frame_updated,
            "timestamp": time.time(),
        })


class ConductorGatePanel(tk.Frame):
    """Main Conductor Gate Panel widget container."""

    def __init__(
        self,
        master: tk.Tk,
        root_dir: Optional[Union[str, pathlib.Path]] = None,
        resource_key: str = "host:heavy",
        interval_sec: float = 2.0,
        enable_worker: bool = True,
    ):
        super().__init__(master, bg=COLOR_NEUTRAL_BG)
        self.master = master
        self.root_dir = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
        self.resource_key = resource_key
        self.interval_sec = interval_sec
        self.enable_worker = enable_worker

        self.queue_data: queue.Queue = queue.Queue()
        self.worker: Optional[GatePanelWorker] = None

        self._last_verdict_result: Optional[GateVerdictResult] = None
        self._last_frame_data: Optional[Dict[str, Any]] = None
        self._last_storage_data: Optional[Dict[str, Any]] = None
        self._history_open = False
        self._history_cursor: Optional[str] = None
        self._history_items: List[Dict[str, Any]] = []
        self._history_total: int = 0
        self._history_has_more: bool = False

        self._build_ui()

        if self.enable_worker:
            self.worker = GatePanelWorker(
                out_queue=self.queue_data,
                root_dir=self.root_dir,
                resource_key=self.resource_key,
                interval_sec=self.interval_sec,
            )
            self.worker.start()
            self.master.bind("<Unmap>", self._on_unmap)
            self.master.bind("<Map>", self._on_map)
            self._schedule_poll()

    def _on_unmap(self, event: tk.Event) -> None:
        if event.widget == self.master and self.worker:
            self.worker.pause()

    def _on_map(self, event: tk.Event) -> None:
        if event.widget == self.master and self.worker:
            self.worker.resume()

    def _schedule_poll(self) -> None:
        self.master.after(100, self._poll_queue)

    def _poll_queue(self) -> None:
        updated = False
        latest_msg = None
        while not self.queue_data.empty():
            try:
                latest_msg = self.queue_data.get_nowait()
                updated = True
            except queue.Empty:
                break

        if updated and latest_msg:
            if latest_msg["type"] == "FRAME" and latest_msg.get("frame"):
                self.apply_frame(
                    frame=latest_msg["frame"],
                    storage=latest_msg.get("storage"),
                    read_ms=latest_msg.get("read_ms", 0.0),
                    is_stale=latest_msg.get("stale", False),
                )
            elif latest_msg["type"] == "ERROR":
                self.apply_degraded(
                    headline="ERROR READING STORE",
                    subtext=latest_msg.get("error", "Unknown error"),
                )

        self._schedule_poll()

    def _build_ui(self) -> None:
        self.pack(fill=tk.BOTH, expand=True)

        # Style configuration
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # 1. VERDICT BANNER
        self.banner_frame = tk.Frame(self, bg="#ffffff", bd=1, relief=tk.SOLID)
        self.banner_frame.pack(fill=tk.X, padx=12, pady=(12, 6))

        # Aspect bar (colored frame on left)
        self.aspect_bar = tk.Frame(self.banner_frame, bg=COLOR_CLEAR, width=10)
        self.aspect_bar.pack(side=tk.LEFT, fill=tk.Y)

        # Content frame inside banner
        self.banner_content = tk.Frame(self.banner_frame, bg="#ffffff", padx=12, pady=10)
        self.banner_content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.verdict_headline = tk.Label(
            self.banner_content,
            text="CHECKING GATE STATUS...",
            font=(FONT_FAMILY_UI, 12, "bold"),
            bg="#ffffff",
            fg=COLOR_TEXT,
            anchor="w",
        )
        self.verdict_headline.pack(fill=tk.X)

        self.verdict_subtext = tk.Label(
            self.banner_content,
            text=f"Scoped to pool {self.resource_key}",
            font=(FONT_FAMILY_UI, 9),
            bg="#ffffff",
            fg=COLOR_MUTED,
            anchor="w",
        )
        self.verdict_subtext.pack(fill=tk.X, pady=(2, 0))

        self.stale_marker_label = tk.Label(
            self.banner_content,
            text="",
            font=(FONT_FAMILY_UI, 9, "bold"),
            bg="#ffffff",
            fg=COLOR_STALE,
            anchor="w",
        )

        # 2. CARDS CONTAINER (Holder / Blockers)
        self.cards_container = tk.Frame(self, bg=COLOR_NEUTRAL_BG)
        self.cards_container.pack(fill=tk.X, padx=12, pady=4)

        # 3. QUEUE CONTAINER
        self.queue_container = tk.Frame(self, bg=COLOR_NEUTRAL_BG)
        self.queue_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        self.queue_header_frame = tk.Frame(self.queue_container, bg=COLOR_NEUTRAL_BG)
        self.queue_header_frame.pack(fill=tk.X, pady=(0, 4))

        self.queue_title = tk.Label(
            self.queue_header_frame,
            text="RESOURCE QUEUE",
            font=(FONT_FAMILY_UI, 10, "bold"),
            bg=COLOR_NEUTRAL_BG,
            fg=COLOR_TEXT,
        )
        self.queue_title.pack(side=tk.LEFT)

        self.queue_subtitle = tk.Label(
            self.queue_header_frame,
            text="",
            font=(FONT_FAMILY_UI, 9),
            bg=COLOR_NEUTRAL_BG,
            fg=COLOR_MUTED,
        )
        self.queue_subtitle.pack(side=tk.LEFT, padx=8)

        # Queue Treeview
        tree_frame = tk.Frame(self.queue_container, bg="#ffffff", bd=1, relief=tk.SOLID)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("pos", "request", "agent", "purpose", "reason", "waiting")
        self.queue_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            height=6,
            selectmode="none",
        )
        self.queue_tree.heading("pos", text="#")
        self.queue_tree.heading("request", text="request")
        self.queue_tree.heading("agent", text="agent")
        self.queue_tree.heading("purpose", text="purpose")
        self.queue_tree.heading("reason", text="reason")
        self.queue_tree.heading("waiting", text="waiting")

        self.queue_tree.column("pos", width=40, minwidth=40, stretch=False, anchor="center")
        self.queue_tree.column("request", width=150, minwidth=150, stretch=False, anchor="w")
        self.queue_tree.column("agent", width=180, minwidth=180, stretch=False, anchor="w")
        self.queue_tree.column("purpose", width=140, minwidth=140, stretch=False, anchor="w")
        self.queue_tree.column("reason", width=90, minwidth=90, stretch=False, anchor="center")
        self.queue_tree.column("waiting", width=90, minwidth=90, stretch=False, anchor="e")

        self.queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        q_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=q_scroll.set)
        q_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Quarantined attention frame
        self.quarantine_frame = tk.Frame(self.queue_container, bg="#fff8e1", bd=1, relief=tk.SOLID)
        self.quarantine_label = tk.Label(
            self.quarantine_frame,
            text="",
            font=(FONT_FAMILY_UI, 9, "bold"),
            bg="#fff8e1",
            fg="#b78103",
            padx=8,
            pady=4,
            anchor="w",
        )
        self.quarantine_label.pack(fill=tk.X)

        # 4. HISTORY DRAWER (GP-4)
        self.history_container = tk.Frame(self, bg=COLOR_NEUTRAL_BG)
        self.history_container.pack(fill=tk.X, padx=12, pady=4)

        self.history_toggle_btn = tk.Button(
            self.history_container,
            text="▶ Terminal History (closed)",
            font=(FONT_FAMILY_UI, 9),
            bg="#e0e0e0",
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            padx=8,
            pady=2,
            command=self.toggle_history,
        )
        self.history_toggle_btn.pack(anchor="w")

        self.history_drawer = tk.Frame(self.history_container, bg="#ffffff", bd=1, relief=tk.SOLID)
        # Treeview for history
        hist_cols = ("request", "agent", "purpose", "reason", "released", "held")
        self.history_tree = ttk.Treeview(
            self.history_drawer,
            columns=hist_cols,
            show="headings",
            height=5,
            selectmode="none",
        )
        self.history_tree.heading("request", text="request")
        self.history_tree.heading("agent", text="agent")
        self.history_tree.heading("purpose", text="purpose")
        self.history_tree.heading("reason", text="reason")
        self.history_tree.heading("released", text="released")
        self.history_tree.heading("held", text="held")

        self.history_tree.column("request", width=150, minwidth=150, stretch=False, anchor="w")
        self.history_tree.column("agent", width=180, minwidth=180, stretch=False, anchor="w")
        self.history_tree.column("purpose", width=130, minwidth=130, stretch=False, anchor="w")
        self.history_tree.column("reason", width=120, minwidth=120, stretch=False, anchor="center")
        self.history_tree.column("released", width=150, minwidth=150, stretch=False, anchor="w")
        self.history_tree.column("held", width=80, minwidth=80, stretch=False, anchor="e")

        self.history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        h_scroll = ttk.Scrollbar(self.history_drawer, orient=tk.VERTICAL, command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=h_scroll.set)
        h_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.history_controls = tk.Frame(self.history_drawer, bg="#ffffff")
        self.history_controls.pack(fill=tk.X, padx=8, pady=4)

        self.history_load_more_btn = tk.Button(
            self.history_controls,
            text="Load More",
            font=(FONT_FAMILY_UI, 8),
            command=self.load_more_history,
            state=tk.DISABLED,
        )
        self.history_load_more_btn.pack(side=tk.LEFT)

        self.history_status_lbl = tk.Label(
            self.history_controls,
            text="",
            font=(FONT_FAMILY_UI, 8),
            bg="#ffffff",
            fg=COLOR_MUTED,
        )
        self.history_status_lbl.pack(side=tk.LEFT, padx=8)

        # 5. FOOTER STRIP
        self.footer_frame = tk.Frame(self, bg="#ebebeb", bd=1, relief=tk.SOLID, height=28)
        self.footer_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(4, 10))

        self.footer_leader_lamp = tk.Label(
            self.footer_frame,
            text="●",
            font=(FONT_FAMILY_UI, 9),
            bg="#ebebeb",
            fg="#2e7d32",
        )
        self.footer_leader_lamp.pack(side=tk.LEFT, padx=(8, 2))

        self.footer_leader_text = tk.Label(
            self.footer_frame,
            text="leader: checking...",
            font=(FONT_FAMILY_MONO, 8),
            bg="#ebebeb",
            fg=COLOR_TEXT,
        )
        self.footer_leader_text.pack(side=tk.LEFT, padx=(0, 10))

        self.footer_sep1 = tk.Label(self.footer_frame, text="|", bg="#ebebeb", fg=COLOR_MUTED)
        self.footer_sep1.pack(side=tk.LEFT, padx=4)

        self.footer_store_text = tk.Label(
            self.footer_frame,
            text="store: AVAILABLE",
            font=(FONT_FAMILY_MONO, 8),
            bg="#ebebeb",
            fg=COLOR_TEXT,
        )
        self.footer_store_text.pack(side=tk.LEFT, padx=4)

        self.footer_sep2 = tk.Label(self.footer_frame, text="|", bg="#ebebeb", fg=COLOR_MUTED)
        self.footer_sep2.pack(side=tk.LEFT, padx=4)

        self.footer_workitems_text = tk.Label(
            self.footer_frame,
            text="work items: 0",
            font=(FONT_FAMILY_MONO, 8),
            bg="#ebebeb",
            fg=COLOR_TEXT,
        )
        self.footer_workitems_text.pack(side=tk.LEFT, padx=4)

        self.footer_sep3 = tk.Label(self.footer_frame, text="|", bg="#ebebeb", fg=COLOR_MUTED)
        self.footer_sep3.pack(side=tk.LEFT, padx=4)

        self.footer_receipts_text = tk.Label(
            self.footer_frame,
            text="receipts: - / 256 MB",
            font=(FONT_FAMILY_MONO, 8),
            bg="#ebebeb",
            fg=COLOR_TEXT,
        )
        self.footer_receipts_text.pack(side=tk.LEFT, padx=4)

        self.footer_timing_text = tk.Label(
            self.footer_frame,
            text="read - ms, no receipt written",
            font=(FONT_FAMILY_MONO, 8),
            bg="#ebebeb",
            fg=COLOR_MUTED,
        )
        self.footer_timing_text.pack(side=tk.RIGHT, padx=8)

    def apply_degraded(self, headline: str, subtext: str) -> None:
        """Render explicit degraded banner."""
        self.aspect_bar.configure(bg=COLOR_DEGRADED)
        self.verdict_headline.configure(text=headline, fg=COLOR_DEGRADED_FG)
        self.verdict_subtext.configure(text=subtext, fg=COLOR_TEXT)
        self._clear_cards()
        self.queue_container.pack_forget()

    def apply_frame(
        self,
        frame: Dict[str, Any],
        storage: Optional[Dict[str, Any]] = None,
        read_ms: float = 0.0,
        is_stale: bool = False,
    ) -> None:
        """Apply a fresh gate frame and storage status to the UI."""
        self._last_frame_data = frame
        self._last_storage_data = storage

        store_status = frame.get("store", {})
        gate_snapshot = frame.get("gate", {})

        # Schema version check
        schema_ver = gate_snapshot.get("schema_version")
        if schema_ver is not None and schema_ver != "1.0.0":
            self.apply_degraded(
                headline="DEGRADED: UNRECOGNIZED SCHEMA VERSION",
                subtext=f"Database schema version '{schema_ver}' is not supported by this panel.",
            )
            return

        store_state = store_status.get("store_state", "AVAILABLE")
        if store_state == "CORRUPT_OR_UNREADABLE":
            self.apply_degraded(
                headline="DEGRADED: STORE UNREADABLE OR CORRUPT",
                subtext=f"Cannot read conductor.db: {store_status.get('error', 'unreadable')}",
            )
            return

        # Evaluate verdict
        verdict_res = evaluate_gate_verdict(
            gate_snapshot,
            repo_path=self.root_dir.parent if self.root_dir else None,
        )
        self._last_verdict_result = verdict_res

        # 1. Update Verdict Banner
        verdict = verdict_res.verdict
        if verdict == GateVerdict.CLEAR.value:
            bar_color = COLOR_CLEAR
        elif verdict == GateVerdict.OCCUPIED.value:
            bar_color = COLOR_OCCUPIED
        elif verdict in (GateVerdict.FENCED.value, GateVerdict.DISABLED.value):
            bar_color = COLOR_FENCED
        else:
            bar_color = COLOR_ANOMALY

        self.aspect_bar.configure(bg=bar_color)
        self.verdict_headline.configure(text=verdict_res.headline.upper(), fg=COLOR_TEXT)
        self.verdict_subtext.configure(text=verdict_res.subtext, fg=COLOR_MUTED)

        if is_stale:
            self.stale_marker_label.configure(text="[STALE - retrying snapshot]")
            self.stale_marker_label.pack(fill=tk.X, pady=(2, 0))
        else:
            self.stale_marker_label.pack_forget()

        # 2. Update Cards (Holder / Blockers)
        self._render_cards(verdict_res, gate_snapshot)

        # 3. Update Queue
        queue_items = gate_snapshot.get("queue", [])
        quarantined_items = gate_snapshot.get("quarantined", [])

        if not queue_items and not quarantined_items:
            self.queue_container.pack_forget()
        else:
            self.queue_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
            self._render_queue(queue_items, quarantined_items)

        # 4. Update Footer Strip
        self._render_footer(store_status, storage, read_ms, is_stale)

    def _clear_cards(self) -> None:
        for child in self.cards_container.winfo_children():
            child.destroy()

    def _render_cards(self, verdict_res: GateVerdictResult, gate_snapshot: Dict[str, Any]) -> None:
        self._clear_cards()

        verdict = verdict_res.verdict
        holder = gate_snapshot.get("holder")
        fenced_list = gate_snapshot.get("fenced", [])
        inherited_list = gate_snapshot.get("inherited", [])

        if verdict == GateVerdict.OCCUPIED.value and holder:
            self._render_holder_card(holder, inherited_list)
        elif verdict == GateVerdict.FENCED.value and fenced_list:
            for idx, fenced_item in enumerate(fenced_list):
                self._render_blocker_card(fenced_item, inherited_list, idx, len(fenced_list))
        elif verdict == GateVerdict.CLEAR.value:
            # Empty sections are removed
            pass

    def _render_holder_card(self, holder: Dict[str, Any], inherited: List[Dict[str, Any]]) -> None:
        card = tk.Frame(self.cards_container, bg=COLOR_CARD_BG, bd=1, relief=tk.SOLID, padx=12, pady=10)
        card.pack(fill=tk.X, pady=2)

        header_row = tk.Frame(card, bg=COLOR_CARD_BG)
        header_row.pack(fill=tk.X, pady=(0, 6))

        tk.Label(
            header_row,
            text="HOLDER",
            font=(FONT_FAMILY_UI, 10, "bold"),
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT,
        ).pack(side=tk.LEFT)

        req_id = holder.get("request_id", "")
        tk.Label(
            header_row,
            text=req_id,
            font=(FONT_FAMILY_MONO, 10, "bold"),
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT,
        ).pack(side=tk.LEFT, padx=(12, 6))

        # Pill ACTIVE
        pill_frame = tk.Frame(header_row, bg=COLOR_OCCUPIED_BG, bd=1, relief=tk.SOLID)
        pill_frame.pack(side=tk.LEFT, padx=4)
        tk.Label(
            pill_frame,
            text="ACTIVE",
            font=(FONT_FAMILY_UI, 8, "bold"),
            bg=COLOR_OCCUPIED_BG,
            fg=COLOR_OCCUPIED_FG,
            padx=4,
            pady=1,
        ).pack()

        # Pill 1 of 1 units
        pill_u = tk.Frame(header_row, bg="#eeeeee", bd=1, relief=tk.SOLID)
        pill_u.pack(side=tk.LEFT, padx=4)
        tk.Label(
            pill_u,
            text="1 of 1 units",
            font=(FONT_FAMILY_UI, 8),
            bg="#eeeeee",
            fg=COLOR_TEXT,
            padx=4,
            pady=1,
        ).pack()

        # Grid of attributes
        grid = tk.Frame(card, bg=COLOR_CARD_BG)
        grid.pack(fill=tk.X, pady=(0, 6))

        agent = holder.get("agent_instance", "unknown")
        purpose = holder.get("purpose", "")
        attempt = holder.get("attempt_id", "")
        lease_id = holder.get("lease_id", "none") or "none"
        heartbeat_seq = holder.get("heartbeat_sequence", "none")
        hb_last = holder.get("last_heartbeat_utc", "") or ""
        created = holder.get("created_at_utc", "") or ""
        expires = holder.get("expires_at_utc", "") or ""

        # Process liveness observation
        pid = holder.get("process_pid")
        proc_start = holder.get("process_start_time")
        proc_obs = observe_process_liveness(pid, proc_start)

        # Elapsed
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        elapsed_str = ""
        if created:
            try:
                c_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                elapsed_str = f"({format_duration((now_dt - c_dt).total_seconds())})"
            except Exception:
                pass

        # Inherited count
        inh_str = "none" if not inherited else f"{len(inherited)} active ({', '.join(c.get('request_id','') for c in inherited)})"

        rows = [
            [("agent", agent), ("purpose", purpose)],
            [("attempt", attempt), ("lease", lease_id)],
            [("held since", f"{created} {elapsed_str}".strip()), ("heartbeat", f"seq {heartbeat_seq}, last {hb_last}")],
            [("expires", expires), ("process", proc_obs)],
            [("inherited", inh_str), ("", "")],
        ]

        for r_idx, row_cells in enumerate(rows):
            for c_idx, (k, v) in enumerate(row_cells):
                if not k:
                    continue
                col_offset = c_idx * 2
                tk.Label(
                    grid,
                    text=f"{k}:",
                    font=(FONT_FAMILY_UI, 9, "bold"),
                    bg=COLOR_CARD_BG,
                    fg=COLOR_MUTED,
                    anchor="w",
                ).grid(row=r_idx, column=col_offset, sticky="w", padx=(0, 4), pady=1)
                tk.Label(
                    grid,
                    text=str(v),
                    font=(FONT_FAMILY_MONO, 9),
                    bg=COLOR_CARD_BG,
                    fg=COLOR_TEXT,
                    anchor="w",
                ).grid(row=r_idx, column=col_offset + 1, sticky="w", padx=(0, 20), pady=1)

        tk.Label(
            card,
            text="No action is available or needed. The gate clears when the job releases it, or when the lease expires and reconcile proves the process is gone.",
            font=(FONT_FAMILY_UI, 8),
            bg=COLOR_CARD_BG,
            fg=COLOR_MUTED,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 0))

    def _render_blocker_card(
        self,
        fenced_item: Dict[str, Any],
        inherited: List[Dict[str, Any]],
        index: int,
        total_fences: int,
    ) -> None:
        card = tk.Frame(self.cards_container, bg=COLOR_CARD_BG, bd=1, relief=tk.SOLID, padx=12, pady=10)
        card.pack(fill=tk.X, pady=4)

        header_row = tk.Frame(card, bg=COLOR_CARD_BG)
        header_row.pack(fill=tk.X, pady=(0, 6))

        title_text = "BLOCKER" if total_fences == 1 else f"BLOCKER ({index + 1} of {total_fences})"
        tk.Label(
            header_row,
            text=title_text,
            font=(FONT_FAMILY_UI, 10, "bold"),
            bg=COLOR_CARD_BG,
            fg=COLOR_FENCED_FG,
        ).pack(side=tk.LEFT)

        req_id = fenced_item.get("request_id", "")
        tk.Label(
            header_row,
            text=req_id,
            font=(FONT_FAMILY_MONO, 10, "bold"),
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT,
        ).pack(side=tk.LEFT, padx=(12, 6))

        # Pill RECOVERY_REQUIRED
        pill_rr = tk.Frame(header_row, bg=COLOR_FENCED_BG, bd=1, relief=tk.SOLID)
        pill_rr.pack(side=tk.LEFT, padx=4)
        tk.Label(
            pill_rr,
            text="RECOVERY_REQUIRED",
            font=(FONT_FAMILY_UI, 8, "bold"),
            bg=COLOR_FENCED_BG,
            fg=COLOR_FENCED_FG,
            padx=4,
            pady=1,
        ).pack()

        # Reason code pill
        rc = fenced_item.get("reason_code") or "FENCED"
        pill_rc = tk.Frame(header_row, bg="#eeeeee", bd=1, relief=tk.SOLID)
        pill_rc.pack(side=tk.LEFT, padx=4)
        tk.Label(
            pill_rc,
            text=rc,
            font=(FONT_FAMILY_UI, 8),
            bg="#eeeeee",
            fg=COLOR_TEXT,
            padx=4,
            pady=1,
        ).pack()

        # Grid of attributes
        grid = tk.Frame(card, bg=COLOR_CARD_BG)
        grid.pack(fill=tk.X, pady=(0, 6))

        agent = fenced_item.get("agent_instance", "unknown")
        purpose = fenced_item.get("purpose", "")
        attempt = fenced_item.get("attempt_id", "")
        priority = fenced_item.get("priority", 50)
        lease_id = fenced_item.get("lease_id", "none") or "none"
        heartbeat_seq = fenced_item.get("heartbeat_sequence", "none")
        hb_last = fenced_item.get("last_heartbeat_utc", "") or ""
        created = fenced_item.get("created_at_utc", "") or ""
        expires = fenced_item.get("expires_at_utc", "") or ""

        # Process liveness observation
        pid = fenced_item.get("process_pid")
        proc_start = fenced_item.get("process_start_time")
        proc_obs = observe_process_liveness(pid, proc_start)

        # Elapsed
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        elapsed_str = ""
        if created:
            try:
                c_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                elapsed_str = f"({format_duration((now_dt - c_dt).total_seconds())})"
            except Exception:
                pass

        rows = [
            [("agent", agent), ("priority", priority)],
            [("purpose", purpose), ("units", "1 of 1")],
            [("attempt", attempt), ("lease", lease_id)],
            [("held since", f"{created} {elapsed_str}".strip()), ("heartbeat", f"seq {heartbeat_seq}, last {hb_last}")],
            [("expired", expires), ("process", proc_obs)],
        ]

        for r_idx, row_cells in enumerate(rows):
            for c_idx, (k, v) in enumerate(row_cells):
                col_offset = c_idx * 2
                tk.Label(
                    grid,
                    text=f"{k}:",
                    font=(FONT_FAMILY_UI, 9, "bold"),
                    bg=COLOR_CARD_BG,
                    fg=COLOR_MUTED,
                    anchor="w",
                ).grid(row=r_idx, column=col_offset, sticky="w", padx=(0, 4), pady=1)
                tk.Label(
                    grid,
                    text=str(v),
                    font=(FONT_FAMILY_MONO, 9),
                    bg=COLOR_CARD_BG,
                    fg=COLOR_TEXT,
                    anchor="w",
                ).grid(row=r_idx, column=col_offset + 1, sticky="w", padx=(0, 20), pady=1)

        # Adjudication & Refusal Explainer
        adjudication = adjudicate_recovery(
            fenced_request=fenced_item,
            inherited_children=inherited,
            repo_path=self.root_dir.parent if self.root_dir else None,
        )

        explainer_frame = tk.Frame(card, bg="#fafafa", bd=1, relief=tk.SOLID, padx=8, pady=6)
        explainer_frame.pack(fill=tk.X, pady=(4, 0))

        tk.Label(
            explainer_frame,
            text="Refusal explainer:",
            font=(FONT_FAMILY_UI, 8, "bold"),
            bg="#fafafa",
            fg=COLOR_TEXT,
            anchor="w",
        ).pack(fill=tk.X)

        refusal_p1 = "  - resource-release refuses RECOVERY_REQUIRED_RELEASE_REFUSED, by design"
        if adjudication.recover_code == "OWNER_LIVENESS_UNPROVEN":
            refusal_p2 = "  - resource-recover refuses OWNER_LIVENESS_UNPROVEN, no pid recorded"
            action_prompt = "The gate opens only on operator attestation. Paste into PowerShell:"
        elif adjudication.recover_code == "RECOVERY_OWNER_GONE":
            refusal_p2 = "  - resource-recover will succeed on proof that recorded process is gone"
            action_prompt = "Run in PowerShell to clear this fence:"
        elif adjudication.recover_code == "OWNER_PROCESS_ALIVE":
            refusal_p2 = f"  - resource-recover refuses OWNER_PROCESS_ALIVE, recorded pid {adjudication.pid} is alive"
            action_prompt = "No command offered: the owner process is still running. Terminate it before recovering."
        elif adjudication.recover_code == "INHERITED_CHILD_ACTIVE":
            refusal_p2 = f"  - resource-recover refuses INHERITED_CHILD_ACTIVE, child request {adjudication.inherited_child_id} is active"
            action_prompt = "No command offered: inherited child is active. Release or recover the child first."
        else:
            refusal_p2 = f"  - resource-recover refuses {adjudication.recover_code}"
            action_prompt = "Command unavailable for this state."

        tk.Label(
            explainer_frame,
            text=f"{refusal_p1}\n{refusal_p2}",
            font=(FONT_FAMILY_UI, 8),
            bg="#fafafa",
            fg=COLOR_MUTED,
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(2, 4))

        tk.Label(
            explainer_frame,
            text=action_prompt,
            font=(FONT_FAMILY_UI, 8, "bold"),
            bg="#fafafa",
            fg=COLOR_TEXT,
            anchor="w",
        ).pack(fill=tk.X, pady=(2, 4))

        cmd = adjudication.command
        if cmd:
            cmd_row = tk.Frame(explainer_frame, bg="#fafafa")
            cmd_row.pack(fill=tk.X, pady=(2, 0))

            cmd_entry = tk.Entry(
                cmd_row,
                font=(FONT_FAMILY_MONO, 8),
                bg="#ffffff",
                fg=COLOR_TEXT,
                bd=1,
                relief=tk.SOLID,
            )
            cmd_entry.insert(0, cmd)
            cmd_entry.configure(state="readonly")
            cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

            copy_btn = tk.Button(
                cmd_row,
                text="COPY",
                font=(FONT_FAMILY_UI, 8, "bold"),
                bg="#e0e0e0",
                fg=COLOR_TEXT,
                relief=tk.FLAT,
                padx=10,
                pady=2,
            )
            copy_btn.configure(command=lambda b=copy_btn, c=cmd: self.copy_to_clipboard(c, b))
            copy_btn.pack(side=tk.RIGHT)

    def copy_to_clipboard(self, text: str, button: Optional[tk.Button] = None) -> None:
        """Copy command string to clipboard (local UI action only, no store access)."""
        self.master.clipboard_clear()
        self.master.clipboard_append(text)
        if button:
            orig_text = button.cget("text")
            button.configure(text="COPIED!", bg="#c8e6c9")
            self.master.after(1500, lambda: button.configure(text=orig_text, bg="#e0e0e0"))

    def _render_queue(self, queue_items: List[Dict[str, Any]], quarantined_items: List[Dict[str, Any]]) -> None:
        q_count = len(queue_items)
        self.queue_subtitle.configure(text=f"{q_count} waiting, admission order")

        # Clear existing rows
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        cap = 20
        visible_items = queue_items[:cap]

        for idx, req in enumerate(visible_items):
            created = req.get("created_at_utc", "")
            wait_str = "-"
            if created:
                try:
                    c_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                    wait_str = format_duration((now_dt - c_dt).total_seconds())
                except Exception:
                    pass

            self.queue_tree.insert(
                "",
                tk.END,
                values=(
                    idx + 1,
                    req.get("request_id", ""),
                    req.get("agent_instance", ""),
                    req.get("purpose", ""),
                    req.get("reason_code") or "BUSY",
                    wait_str,
                ),
            )

        if q_count > cap:
            self.queue_tree.insert(
                "",
                tk.END,
                values=(
                    "",
                    f"+{q_count - cap} more",
                    "...",
                    "...",
                    "...",
                    "...",
                ),
            )

        if quarantined_items:
            self.quarantine_label.configure(
                text=f"⚠ {len(quarantined_items)} QUARANTINED request(s) present (attention required, non-blocking): {', '.join(q.get('request_id','') for q in quarantined_items)}"
            )
            self.quarantine_frame.pack(fill=tk.X, pady=(4, 0))
        else:
            self.quarantine_frame.pack_forget()

    def _render_footer(
        self,
        store_status: Dict[str, Any],
        storage_data: Optional[Dict[str, Any]],
        read_ms: float,
        is_stale: bool,
    ) -> None:
        leader_active = store_status.get("leader_active", False)
        leader_id = store_status.get("leader_id") or "none"
        leader_pid = store_status.get("leader_pid") or "-"
        store_state = store_status.get("store_state", "AVAILABLE")
        total_wi = store_status.get("total_work_items", 0)

        if leader_active:
            self.footer_leader_lamp.configure(text="●", fg="#2e7d32")
            self.footer_leader_text.configure(text=f"leader active {leader_id} pid {leader_pid}")
        else:
            self.footer_leader_lamp.configure(text="*", fg="#e65100")
            self.footer_leader_text.configure(text=f"leader inactive {leader_id} pid {leader_pid}")

        self.footer_store_text.configure(text=f"store {store_state}")
        self.footer_workitems_text.configure(text=f"work items {total_wi}")

        receipts_str = "- / 256 MB"
        if storage_data and "directories" in storage_data:
            rec_info = storage_data["directories"].get("receipts", {})
            rec_bytes = rec_info.get("bytes", 0)
            rec_mb = rec_bytes / (1024 * 1024)
            ceil_bytes = rec_info.get("ceiling_bytes", 256 * 1024 * 1024)
            ceil_mb = ceil_bytes / (1024 * 1024)
            receipts_str = f"{rec_mb:.1f} / {ceil_mb:.0f} MB"
        self.footer_receipts_text.configure(text=f"receipts {receipts_str}")

        if is_stale:
            self.footer_timing_text.configure(text="[STALE - retrying]", fg=COLOR_STALE)
        else:
            self.footer_timing_text.configure(text=f"read {read_ms:.0f} ms, no receipt written", fg=COLOR_MUTED)

    # GP-4: History drawer implementation
    def toggle_history(self) -> None:
        self._history_open = not self._history_open
        if self._history_open:
            self.history_toggle_btn.configure(text="▼ Terminal History (open)")
            self.history_drawer.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
            if not self._history_items:
                self.load_history_page(reset=True)
        else:
            self.history_toggle_btn.configure(text="▶ Terminal History (closed)")
            self.history_drawer.pack_forget()

    def load_history_page(self, reset: bool = False) -> None:
        cursor = None if reset else self._history_cursor
        page = read_resource_history_page(
            resource_key=self.resource_key,
            limit=50,
            cursor=cursor,
            root_dir=self.root_dir,
        )

        if reset:
            self._history_items = []
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)

        items = page.get("items", [])
        self._history_items.extend(items)
        self._history_cursor = page.get("next_cursor")
        self._history_has_more = page.get("has_more", False)
        self._history_total = page.get("total_terminal", len(self._history_items))

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        for req in items:
            created = req.get("created_at_utc", "")
            released = req.get("released_at_utc", "")
            held_str = "-"
            if created and released:
                try:
                    c_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                    r_dt = datetime.datetime.fromisoformat(released.replace("Z", "+00:00"))
                    held_str = format_duration((r_dt - c_dt).total_seconds())
                except Exception:
                    pass

            self.history_tree.insert(
                "",
                tk.END,
                values=(
                    req.get("request_id", ""),
                    req.get("agent_instance", ""),
                    req.get("purpose", ""),
                    req.get("reason_code", ""),
                    released,
                    held_str,
                ),
            )

        self.history_load_more_btn.configure(state=tk.NORMAL if self._history_has_more else tk.DISABLED)
        self.history_status_lbl.configure(text=f"Showing {len(self._history_items)} of {self._history_total} terminal requests")

    def load_more_history(self) -> None:
        if self._history_has_more:
            self.load_history_page(reset=False)


def main(argv: Optional[List[str]] = None) -> int:
    """Launcher for Conductor Gate Panel."""
    parser = argparse.ArgumentParser(description="Conductor Gate Panel - read-only operator GUI")
    parser.add_argument("--root", type=str, default=None, help="Root directory for Conductor (~/.conductor)")
    parser.add_argument("--resource-key", type=str, default="host:heavy", help="Resource key (default: host:heavy)")
    parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds (default: 2.0)")
    args = parser.parse_args(argv)

    root = tk.Tk()
    root.title(f"Conductor Gate Panel - {args.resource_key}")
    root.geometry("980x680")
    root.minsize(720, 480)

    panel = ConductorGatePanel(
        master=root,
        root_dir=args.root,
        resource_key=args.resource_key,
        interval_sec=args.interval,
        enable_worker=True,
    )

    def on_closing():
        if panel.worker:
            panel.worker.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_closing()

    return 0


if __name__ == "__main__":
    sys.exit(main())
