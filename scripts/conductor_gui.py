#!/usr/bin/env python3
"""Conductor Gate Panel - read-only operator GUI for host:heavy.

Port-free, single-writer WAL reader via read-only snapshot.
Runs change-check ticks on a worker thread using _file_signature.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import queue
import subprocess
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
COLOR_CLEAR = "#7CB88A"      # Green
COLOR_CLEAR_BG = "#202229"
COLOR_CLEAR_FG = "#7CB88A"

COLOR_OCCUPIED = "#E0B85B"   # Amber
COLOR_OCCUPIED_BG = "#202229"
COLOR_OCCUPIED_FG = "#E0B85B"

COLOR_FENCED = "#D56A6A"     # Red
COLOR_FENCED_BG = "#202229"
COLOR_FENCED_FG = "#D56A6A"

COLOR_DISABLED = "#D56A6A"   # Dark Red
COLOR_ANOMALY = "#D4A574"    # Dark Pink/Red
COLOR_DEGRADED = "#76A8C7"   # Purple
COLOR_DEGRADED_BG = "#202229"
COLOR_DEGRADED_FG = "#76A8C7"

COLOR_NEUTRAL_BG = "#0F0F12"
COLOR_CARD_BG = "#17181D"
COLOR_BORDER = "#343741"
def _conductorctl_command() -> tuple:
    """Resolve the installer-owned conductorctl, never a PATH guess.

    Mirrors the resolution the CCTV supervisor uses: the install manifest names
    the canonical interpreter and script, so the GUI runs the same binary the
    rest of the ecosystem does rather than whatever happens to be on PATH.
    """
    manifest = pathlib.Path.home() / ".conductor" / "install-manifest.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        command = (raw.get("canonical_commands") or {}).get("conductorctl")
    except (OSError, ValueError):
        command = None
    if isinstance(command, list) and len(command) == 2 and all(command):
        return tuple(command)
    raise RuntimeError(f"conductorctl not resolvable from {manifest}")


COLOR_TEXT = "#F4EFE7"
COLOR_MUTED = "#A9A39A"
COLOR_STALE = "#E0B85B"

FONT_FAMILY_UI = "Inter" if sys.platform == "win32" else "Inter"
FONT_FAMILY_MONO = "JetBrains Mono" if sys.platform == "win32" else "JetBrains Mono"


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


class PoolStrip:
    """One-line-per-pool overview across the top of the panel.

    Exists because of a real incident on 2026-08-29: `cdp:perplexity` sat fenced
    for 28 hours by two dead CoderPX processes and nothing surfaced it. The panel
    shows one pool per section, so a fenced pool below the fold is invisible, and
    `conductorctl resource-status` without --resource-key only reports
    host:heavy. The operator found it by scrolling. This strip makes every pool's
    state readable without scrolling and without a command.
    """

    ORDER = ("host:heavy", "cdp:perplexity", "cdp:chatgpt", "cdp:gemini", "cdp:tv")

    def __init__(self, parent: tk.Widget) -> None:
        self.frame = tk.Frame(parent, bg=COLOR_NEUTRAL_BG)
        self.frame.pack(fill=tk.X, padx=8, pady=(8, 4))
        self._chips: Dict[str, Dict[str, tk.Widget]] = {}
        self._last_sig: Optional[str] = None

    @staticmethod
    def _state_of(snap: Dict[str, Any]) -> tuple:
        """(colour, one-line label). Fenced outranks held; held outranks free."""
        fenced = snap.get("fenced") or []
        holder = snap.get("holder")
        capacity = snap.get("capacity", 1) or 1
        waiting = len(snap.get("queue") or [])
        if fenced:
            return COLOR_FENCED, f"{len(fenced)} fenced"
        if holder:
            extra = f", {waiting} waiting" if waiting else ""
            return COLOR_OCCUPIED, f"held{extra}"
        return COLOR_CLEAR, f"{capacity}/{capacity} free"

    def render(self, gates: Dict[str, Any]) -> None:
        keys = [k for k in self.ORDER if k in gates] + [k for k in gates if k not in self.ORDER]
        sig = repr([(k, self._state_of(gates[k])) for k in keys])
        if sig == self._last_sig:
            return  # layout stability: never redraw an unchanged strip
        self._last_sig = sig

        for child in self.frame.winfo_children():
            child.destroy()
        self._chips.clear()

        for col, key in enumerate(keys):
            colour, label = self._state_of(gates[key])
            chip = tk.Frame(
                self.frame, bg=COLOR_CARD_BG,
                highlightbackground=colour if colour == COLOR_FENCED else COLOR_BORDER,
                highlightthickness=1,
            )
            chip.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
            self.frame.grid_columnconfigure(col, weight=1, uniform="pool")

            head = tk.Frame(chip, bg=COLOR_CARD_BG)
            head.pack(fill=tk.X, padx=8, pady=(6, 0))
            dot = tk.Canvas(head, width=8, height=8, bg=COLOR_CARD_BG, highlightthickness=0)
            dot.pack(side=tk.LEFT, pady=(4, 0))
            dot.create_oval(0, 0, 7, 7, fill=colour, outline=colour)
            tk.Label(
                head, text=key, font=(FONT_FAMILY_MONO, 9, "bold"),
                bg=COLOR_CARD_BG, fg=COLOR_TEXT, anchor="w",
            ).pack(side=tk.LEFT, padx=(6, 0))
            tk.Label(
                chip, text=label, font=(FONT_FAMILY_UI, 8),
                bg=COLOR_CARD_BG, fg=COLOR_MUTED, anchor="w",
            ).pack(fill=tk.X, padx=8, pady=(0, 6))
            self._chips[key] = {"chip": chip}


class PoolSectionView:
    """View component for a single resource pool section in ConductorGatePanel."""

    def __init__(self, parent: tk.Widget, resource_key: str, panel: ConductorGatePanel):
        self.parent = parent
        self.resource_key = resource_key
        self.panel = panel

        self.section_frame = tk.Frame(parent, bg=COLOR_NEUTRAL_BG)
        self.section_frame.pack(fill=tk.X, padx=12, pady=(6, 4))

        # 1. VERDICT BANNER
        self.banner_frame = tk.Frame(self.section_frame, bg="#17181D", bd=1, relief=tk.SOLID)
        self.banner_frame.pack(fill=tk.X, pady=(0, 4))

        self.aspect_bar = tk.Frame(self.banner_frame, bg=COLOR_CLEAR, width=10)
        self.aspect_bar.pack(side=tk.LEFT, fill=tk.Y)

        self.banner_content = tk.Frame(self.banner_frame, bg="#17181D", padx=12, pady=8)
        self.banner_content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.verdict_headline = tk.Label(
            self.banner_content,
            text=f"[{self.resource_key.upper()}] CHECKING GATE STATUS...",
            font=(FONT_FAMILY_UI, 11, "bold"),
            bg="#17181D",
            fg=COLOR_TEXT,
            anchor="w",
        )
        self.verdict_headline.pack(fill=tk.X)

        self.verdict_subtext = tk.Label(
            self.banner_content,
            text=f"Scoped to pool {self.resource_key}",
            font=(FONT_FAMILY_UI, 9),
            bg="#17181D",
            fg=COLOR_MUTED,
            anchor="w",
        )
        self.verdict_subtext.pack(fill=tk.X, pady=(2, 0))

        self.stale_marker_label = tk.Label(
            self.banner_content,
            text="",
            font=(FONT_FAMILY_UI, 9, "bold"),
            bg="#17181D",
            fg=COLOR_STALE,
            anchor="w",
        )

        # 2. CARDS CONTAINER (Holder / Blockers)
        self.cards_container = tk.Frame(self.section_frame, bg=COLOR_NEUTRAL_BG)
        self.cards_container.pack(fill=tk.X, pady=2)

        # 3. QUEUE CONTAINER
        self.queue_container = tk.Frame(self.section_frame, bg=COLOR_NEUTRAL_BG)
        self.queue_container.pack(fill=tk.BOTH, expand=True, pady=2)

        self.queue_header_frame = tk.Frame(self.queue_container, bg=COLOR_NEUTRAL_BG)
        self.queue_header_frame.pack(fill=tk.X, pady=(0, 2))

        self.queue_title = tk.Label(
            self.queue_header_frame,
            text=f"RESOURCE QUEUE ({self.resource_key})",
            font=(FONT_FAMILY_UI, 9, "bold"),
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

        cols = ("pos", "request_id", "agent", "purpose", "reason", "wait")
        self.queue_tree = ttk.Treeview(
            self.queue_container,
            columns=cols,
            show="headings",
            height=3,
            selectmode="none",
        )
        self.queue_tree.heading("pos", text="#")
        self.queue_tree.heading("request_id", text="Request ID")
        self.queue_tree.heading("agent", text="Agent Instance")
        self.queue_tree.heading("purpose", text="Purpose")
        self.queue_tree.heading("reason", text="Reason Code")
        self.queue_tree.heading("wait", text="Waiting")

        self.queue_tree.column("pos", width=30, stretch=False, anchor="center")
        self.queue_tree.column("request_id", width=140, stretch=False)
        self.queue_tree.column("agent", width=160, stretch=True)
        self.queue_tree.column("purpose", width=110, stretch=False)
        self.queue_tree.column("reason", width=130, stretch=False)
        self.queue_tree.column("wait", width=80, stretch=False, anchor="e")
        self.queue_tree.pack(fill=tk.X, expand=True)

        self.quarantine_frame = tk.Frame(self.queue_container, bg="#202229", bd=1, relief=tk.SOLID, padx=8, pady=4)
        self.quarantine_label = tk.Label(
            self.quarantine_frame,
            text="",
            font=(FONT_FAMILY_UI, 8, "bold"),
            bg="#202229",
            fg="#E0B85B",
            anchor="w",
        )
        self.quarantine_label.pack(fill=tk.X)

    def apply_snapshot(self, gate_snapshot: Dict[str, Any], is_stale: bool = False) -> None:
        verdict_res = evaluate_gate_verdict(
            gate_snapshot,
            repo_path=self.panel.root_dir.parent if self.panel.root_dir else None,
        )
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
        headline_text = f"[{self.resource_key.upper()}] {verdict_res.headline.upper()}"
        self.verdict_headline.configure(text=headline_text, fg=COLOR_TEXT)
        self.verdict_subtext.configure(text=verdict_res.subtext, fg=COLOR_MUTED)

        if is_stale:
            self.stale_marker_label.configure(text="[STALE - retrying snapshot]")
            self.stale_marker_label.pack(fill=tk.X, pady=(2, 0))
        else:
            self.stale_marker_label.pack_forget()

        queue_items = gate_snapshot.get("queue", [])
        quarantined_items = gate_snapshot.get("quarantined", [])

        # Rebuilding the cards means destroying and recreating every widget, which
        # reads as a full-panel flash on each tick. The DB signature changes far
        # more often than what is actually displayed (heartbeat rows alone move
        # it), so gate the rebuild on the RENDERED content instead.
        content_sig = repr((
            verdict_res.headline,
            verdict_res.subtext,
            gate_snapshot.get("holder"),
            gate_snapshot.get("fenced"),
            gate_snapshot.get("inherited"),
            gate_snapshot.get("capacity"),
            queue_items,
            quarantined_items,
        ))
        if content_sig != getattr(self, "_last_content_sig", None):
            self._last_content_sig = content_sig
            self._render_cards(verdict_res, gate_snapshot)
            if not queue_items and not quarantined_items:
                self.queue_container.pack_forget()
            else:
                self.queue_container.pack(fill=tk.BOTH, expand=True, pady=2)
                self._render_queue(queue_items, quarantined_items)

    def _clear_cards(self) -> None:
        for child in self.cards_container.winfo_children():
            child.destroy()

    def _render_cards(self, verdict_res: GateVerdictResult, gate_snapshot: Dict[str, Any]) -> None:
        self._clear_cards()
        verdict = verdict_res.verdict
        holder = gate_snapshot.get("holder")
        holders = gate_snapshot.get("holders", ([holder] if holder else []))
        fenced_list = gate_snapshot.get("fenced", [])
        inherited_list = gate_snapshot.get("inherited", [])

        if verdict == GateVerdict.OCCUPIED.value and holders:
            for h in holders:
                self._render_holder_card(h, inherited_list, capacity=gate_snapshot.get("capacity", 1))
        elif verdict == GateVerdict.FENCED.value and fenced_list:
            for idx, fenced_item in enumerate(fenced_list):
                self._render_blocker_card(fenced_item, inherited_list, idx, len(fenced_list), capacity=gate_snapshot.get("capacity", 1))

    def _render_holder_card(self, holder: Dict[str, Any], inherited: List[Dict[str, Any]], capacity: int = 1) -> None:
        card = tk.Frame(self.cards_container, bg=COLOR_CARD_BG, bd=1, relief=tk.SOLID, padx=12, pady=8)
        card.pack(fill=tk.X, pady=2)

        header_row = tk.Frame(card, bg=COLOR_CARD_BG)
        header_row.pack(fill=tk.X, pady=(0, 4))

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

        pill_u = tk.Frame(header_row, bg="#eeeeee", bd=1, relief=tk.SOLID)
        pill_u.pack(side=tk.LEFT, padx=4)
        tk.Label(
            pill_u,
            text=f"1 of {capacity} units",
            font=(FONT_FAMILY_UI, 8),
            bg="#eeeeee",
            fg=COLOR_TEXT,
            padx=4,
            pady=1,
        ).pack()

        slot_key = holder.get("slot_key")
        if slot_key:
            pill_sk = tk.Frame(header_row, bg="#e8eaf6", bd=1, relief=tk.SOLID)
            pill_sk.pack(side=tk.LEFT, padx=4)
            tk.Label(
                pill_sk,
                text=f"slot: {slot_key}",
                font=(FONT_FAMILY_MONO, 8),
                bg="#e8eaf6",
                fg="#1a237e",
                padx=4,
                pady=1,
            ).pack()

        grid = tk.Frame(card, bg=COLOR_CARD_BG)
        grid.pack(fill=tk.X, pady=(0, 4))

        agent = holder.get("agent_instance", "unknown")
        purpose = holder.get("purpose", "")
        attempt = holder.get("attempt_id", "")
        lease_id = holder.get("lease_id", "none") or "none"
        heartbeat_seq = holder.get("heartbeat_sequence", "none")
        hb_last = holder.get("last_heartbeat_utc", "") or ""
        created = holder.get("created_at_utc", "") or ""
        expires = holder.get("expires_at_utc", "") or ""

        pid = holder.get("process_pid")
        proc_start = holder.get("process_start_time")
        proc_obs = observe_process_liveness(pid, proc_start)

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        elapsed_str = ""
        if created:
            try:
                c_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                elapsed_str = f"({format_duration((now_dt - c_dt).total_seconds())})"
            except Exception:
                pass

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
        ).pack(fill=tk.X, pady=(2, 0))

    def _render_blocker_card(
        self,
        fenced_item: Dict[str, Any],
        inherited: List[Dict[str, Any]],
        index: int,
        total_fences: int,
        capacity: int = 1,
    ) -> None:
        card = tk.Frame(self.cards_container, bg=COLOR_CARD_BG, bd=1, relief=tk.SOLID, padx=12, pady=8)
        card.pack(fill=tk.X, pady=4)

        header_row = tk.Frame(card, bg=COLOR_CARD_BG)
        header_row.pack(fill=tk.X, pady=(0, 4))

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

        grid = tk.Frame(card, bg=COLOR_CARD_BG)
        grid.pack(fill=tk.X, pady=(0, 4))

        agent = fenced_item.get("agent_instance", "unknown")
        purpose = fenced_item.get("purpose", "")
        attempt = fenced_item.get("attempt_id", "")
        priority = fenced_item.get("priority", 50)
        lease_id = fenced_item.get("lease_id", "none") or "none"
        heartbeat_seq = fenced_item.get("heartbeat_sequence", "none")
        hb_last = fenced_item.get("last_heartbeat_utc", "") or ""
        created = fenced_item.get("created_at_utc", "") or ""
        expires = fenced_item.get("expires_at_utc", "") or ""

        pid = fenced_item.get("process_pid")
        proc_start = fenced_item.get("process_start_time")
        proc_obs = observe_process_liveness(pid, proc_start)

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
            [("purpose", purpose), ("units", f"1 of {capacity}")],
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

        adjudication = adjudicate_recovery(
            fenced_request=fenced_item,
            inherited_children=inherited,
            repo_path=self.panel.root_dir.parent if self.panel.root_dir else None,
        )

        explainer_frame = tk.Frame(card, bg="#202229", bd=1, relief=tk.SOLID, padx=8, pady=6)
        explainer_frame.pack(fill=tk.X, pady=(4, 0))

        tk.Label(
            explainer_frame,
            text="Refusal explainer:",
            font=(FONT_FAMILY_UI, 8, "bold"),
            bg="#202229",
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
            bg="#202229",
            fg=COLOR_MUTED,
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(2, 4))

        tk.Label(
            explainer_frame,
            text=action_prompt,
            font=(FONT_FAMILY_UI, 8, "bold"),
            bg="#202229",
            fg=COLOR_TEXT,
            anchor="w",
        ).pack(fill=tk.X, pady=(2, 4))

        cmd = adjudication.command
        if cmd:
            cmd_row = tk.Frame(explainer_frame, bg="#202229")
            cmd_row.pack(fill=tk.X, pady=(2, 0))

            cmd_entry = tk.Entry(
                cmd_row,
                font=(FONT_FAMILY_MONO, 8),
                bg="#17181D",
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
                bg="#343741",
                fg=COLOR_TEXT,
                relief=tk.FLAT,
                padx=10,
                pady=2,
            )
            copy_btn.configure(command=lambda b=copy_btn, c=cmd: self.panel.copy_to_clipboard(c, b))
            copy_btn.pack(side=tk.RIGHT)

            # A copyable command is not an answer to "the gate is fenced, now
            # what". Recovery is an operator ATTESTATION, so the button asks for
            # it explicitly rather than running silently.
            recover_btn = tk.Button(
                cmd_row,
                text="RECOVER",
                font=(FONT_FAMILY_UI, 8, "bold"),
                bg="#D56A6A",
                fg="#17181D",
                relief=tk.FLAT,
                padx=10,
                pady=2,
            )
            recover_btn.configure(
                command=lambda b=recover_btn, rid=req_id, adj=adjudication: self.panel.recover_request(rid, adj, b)
            )
            recover_btn.pack(side=tk.RIGHT, padx=(0, 6))

    def _render_queue(self, queue_items: List[Dict[str, Any]], quarantined_items: List[Dict[str, Any]]) -> None:
        q_count = len(queue_items)
        self.queue_subtitle.configure(text=f"{q_count} waiting, admission order")

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
            self.queue_tree.insert("", tk.END, values=("", f"+{q_count - cap} more", "...", "...", "...", "..."))

        if quarantined_items:
            self.quarantine_label.configure(
                text=f"⚠ {len(quarantined_items)} QUARANTINED request(s) present: {', '.join(q.get('request_id','') for q in quarantined_items)}"
            )
            self.quarantine_frame.pack(fill=tk.X, pady=(4, 0))
        else:
            self.quarantine_frame.pack_forget()


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

        self.pool_sections: Dict[str, PoolSectionView] = {}

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

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Every pool at a glance, above the per-pool sections.
        self.pool_strip = PoolStrip(self)

        # Top scrollable / vertical container for pool sections
        self.pools_container = tk.Frame(self, bg=COLOR_NEUTRAL_BG)
        self.pools_container.pack(fill=tk.BOTH, expand=True)

        # Default 4 pools
        default_pools = ("host:heavy", "cdp:perplexity", "cdp:chatgpt", "cdp:gemini", "cdp:tv")
        for p in default_pools:
            self.pool_sections[p] = PoolSectionView(self.pools_container, resource_key=p, panel=self)

        # Primary section aliases for backward compatibility with single-pool introspection
        primary = self.pool_sections.get(self.resource_key) or self.pool_sections["host:heavy"]
        self.banner_frame = primary.banner_frame
        self.aspect_bar = primary.aspect_bar
        self.banner_content = primary.banner_content
        self.verdict_headline = primary.verdict_headline
        self.verdict_subtext = primary.verdict_subtext
        self.stale_marker_label = primary.stale_marker_label
        self.cards_container = primary.cards_container
        self.queue_container = primary.queue_container
        self.queue_header_frame = primary.queue_header_frame
        self.queue_title = primary.queue_title
        self.queue_subtitle = primary.queue_subtitle
        self.queue_tree = primary.queue_tree
        self.quarantine_frame = primary.quarantine_frame
        self.quarantine_label = primary.quarantine_label

        # 4. HISTORY DRAWER (Collapsible)
        self.history_outer = tk.Frame(self, bg=COLOR_NEUTRAL_BG)
        self.history_outer.pack(fill=tk.X, padx=12, pady=4)

        self.history_toggle_btn = tk.Button(
            self.history_outer,
            text="▶ Terminal History (closed)",
            font=(FONT_FAMILY_UI, 9, "bold"),
            bg="#f0f0f0",
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            anchor="w",
            padx=8,
            pady=4,
            command=self.toggle_history,
        )
        self.history_toggle_btn.pack(fill=tk.X)

        self.history_drawer = tk.Frame(self.history_outer, bg="#17181D", bd=1, relief=tk.SOLID)

        self.history_header_frame = tk.Frame(self.history_drawer, bg="#17181D", padx=8, pady=4)
        self.history_header_frame.pack(fill=tk.X)

        self.history_subtitle = tk.Label(
            self.history_header_frame,
            text="",
            font=(FONT_FAMILY_UI, 9),
            bg="#17181D",
            fg=COLOR_MUTED,
        )
        self.history_subtitle.pack(side=tk.LEFT)

        h_cols = ("req_id", "agent", "purpose", "reason", "held", "released")
        self.history_tree = ttk.Treeview(
            self.history_drawer,
            columns=h_cols,
            show="headings",
            height=4,
            selectmode="none",
        )
        self.history_tree.heading("req_id", text="Request ID")
        self.history_tree.heading("agent", text="Agent Instance")
        self.history_tree.heading("purpose", text="Purpose")
        self.history_tree.heading("reason", text="Terminal Reason")
        self.history_tree.heading("held", text="Held Duration")
        self.history_tree.heading("released", text="Released (UTC)")

        self.history_tree.column("req_id", width=140, stretch=False)
        self.history_tree.column("agent", width=160, stretch=True)
        self.history_tree.column("purpose", width=110, stretch=False)
        self.history_tree.column("reason", width=150, stretch=False)
        self.history_tree.column("held", width=90, stretch=False, anchor="e")
        self.history_tree.column("released", width=150, stretch=False)
        self.history_tree.pack(fill=tk.X, expand=True, padx=8, pady=(0, 4))

        self.history_load_more_btn = tk.Button(
            self.history_drawer,
            text="Load 50 more...",
            font=(FONT_FAMILY_UI, 8),
            bg="#eeeeee",
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            padx=8,
            pady=2,
            command=lambda: self.load_history_page(reset=False),
        )

        # 5. FOOTER STRIP
        self.footer_frame = tk.Frame(self, bg="#17181D", bd=1, relief=tk.SOLID, padx=8, pady=4)
        self.footer_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(4, 8))

        self.footer_leader_lamp = tk.Label(
            self.footer_frame,
            text="●",
            font=(FONT_FAMILY_UI, 10, "bold"),
            bg="#17181D",
            fg="#7CB88A",
        )
        self.footer_leader_lamp.pack(side=tk.LEFT, padx=(2, 4))

        self.footer_leader_text = tk.Label(
            self.footer_frame,
            text="leader active",
            font=(FONT_FAMILY_UI, 8),
            bg="#17181D",
            fg=COLOR_TEXT,
        )
        self.footer_leader_text.pack(side=tk.LEFT, padx=(0, 8))

        self.footer_store_text = tk.Label(
            self.footer_frame,
            text="store AVAILABLE",
            font=(FONT_FAMILY_UI, 8),
            bg="#17181D",
            fg=COLOR_TEXT,
        )
        self.footer_store_text.pack(side=tk.LEFT, padx=(0, 8))

        self.footer_workitems_text = tk.Label(
            self.footer_frame,
            text="work items 0",
            font=(FONT_FAMILY_UI, 8),
            bg="#17181D",
            fg=COLOR_TEXT,
        )
        self.footer_workitems_text.pack(side=tk.LEFT, padx=(0, 8))

        self.footer_receipts_text = tk.Label(
            self.footer_frame,
            text="receipts - / 256 MB",
            font=(FONT_FAMILY_UI, 8),
            bg="#17181D",
            fg=COLOR_TEXT,
        )
        self.footer_receipts_text.pack(side=tk.LEFT, padx=(0, 8))

        self.footer_timing_text = tk.Label(
            self.footer_frame,
            text="read 0 ms, no receipt written",
            font=(FONT_FAMILY_UI, 8),
            bg="#17181D",
            fg=COLOR_MUTED,
        )
        self.footer_timing_text.pack(side=tk.RIGHT, padx=4)

    def apply_degraded(self, headline: str, subtext: str) -> None:
        """Render degraded banner across sections on fatal read error or schema mismatch."""
        for section in self.pool_sections.values():
            section.aspect_bar.configure(bg=COLOR_ANOMALY)
            section.verdict_headline.configure(text=headline.upper(), fg=COLOR_TEXT)
            section.verdict_subtext.configure(text=subtext, fg=COLOR_TEXT)
            section._clear_cards()
            section.queue_container.pack_forget()

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
        gates_dict = frame.get("gates")

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

        # Multi-pool update
        if not gates_dict:
            target_key = gate_snapshot.get("resource_key", self.resource_key)
            gates_dict = {target_key: gate_snapshot}

        self.pool_strip.render(gates_dict)

        for p_key, p_snap in gates_dict.items():
            if p_key not in self.pool_sections:
                self.pool_sections[p_key] = PoolSectionView(self.pools_container, resource_key=p_key, panel=self)
            self.pool_sections[p_key].apply_snapshot(p_snap, is_stale=is_stale)

        primary_snap = gates_dict.get(self.resource_key) or gate_snapshot
        self._last_verdict_result = evaluate_gate_verdict(
            primary_snap,
            repo_path=self.root_dir.parent if self.root_dir else None,
        )

        self._render_footer(store_status, storage, read_ms, is_stale)

    def copy_to_clipboard(self, text: str, button: Optional[tk.Button] = None) -> None:
        """Copy command string to clipboard (local UI action only, no store access)."""
        self.master.clipboard_clear()
        self.master.clipboard_append(text)
        if button:
            orig_text = button.cget("text")
            button.configure(text="COPIED!", bg="#c8e6c9")
            self.master.after(1500, lambda: button.configure(text=orig_text, bg="#343741"))

    def recover_request(self, request_id: str, adjudication: Any, button: Any) -> None:
        """Clear a RECOVERY_REQUIRED fence after an explicit operator attestation.

        The panel is otherwise read-only. This is the one mutation, and it stays
        an operator act: Conductor refuses resource-recover unless the caller
        attests the owner is gone, so the dialog states exactly what is being
        attested and to which request before anything runs. A recorded process
        that is still alive is refused by Conductor regardless of this dialog.
        """
        from tkinter import messagebox, simpledialog

        detail = getattr(adjudication, "recover_code", "") or "RECOVERY_REQUIRED"
        message = "\n".join([
            f"Request:  {request_id}",
            f"Refusal:  {detail}",
            "",
            "You are attesting that the process holding this lease no longer exists.",
            "Verify it first (Get-Process on the recorded PID, or the agent's own logs).",
            "",
            "Proceed?",
        ])
        confirmed = messagebox.askyesno(
            "Attest that the owner is gone",
            message,
            icon="warning",
            default="no",
        )
        if not confirmed:
            return
        reason = simpledialog.askstring(
            "Reason (recorded in the receipt)",
            "Why is the owner known to be gone?",
            initialvalue="operator verified the owner process is absent",
        )
        if not reason or not reason.strip():
            return

        cmd = list(_conductorctl_command()) + [
            "resource-recover",
            "--request-id", request_id,
            "--attest-owner-gone",
            "--reason", reason.strip(),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60, check=False,
            )
        except Exception as exc:
            messagebox.showerror("Recover failed", f"{type(exc).__name__}: {exc}")
            return

        if proc.returncode == 0:
            button.configure(text="RECOVERED", bg="#7CB88A")
            # Force the next tick to redraw: the content gate would otherwise
            # hold the stale card until the DB signature happens to move.
            for section in getattr(self, "pool_sections", {}).values() or ():
                section._last_content_sig = None
            if self.worker:
                self.worker.resume()
        else:
            messagebox.showerror(
                "Conductor refused",
                (proc.stderr or proc.stdout or "no output").strip()[:800],
            )

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
            self.footer_leader_lamp.configure(text="●", fg="#7CB88A")
            self.footer_leader_text.configure(text=f"leader active {leader_id} pid {leader_pid}")
        else:
            self.footer_leader_lamp.configure(text="*", fg="#E0B85B")
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
