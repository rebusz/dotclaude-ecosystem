#!/usr/bin/env python3
"""cdp_lane_lock.py — machine-wide FIFO-ish lane lock for shared CDP Chrome roles.

Several concurrent agent sessions drive one shared Chrome per role via
``cdp_chatgpt_code.py`` / ``cdp_gemini_oneshot.py`` / ``coderpx.py``. Parallel
submits to the same role collide (``setup_blocked``). This wraps any command in
an exclusive, cross-process lock keyed by role, outside WatchF.

The OS lock is the truth; the ``<role>.holder.json`` sidecar is advisory only
(a stale holder file with a dead pid never blocks — only the real lock does).

Usage:
  python scripts/cdp_lane_lock.py --role chrome_gpt -- <command...>
  python scripts/cdp_lane_lock.py --role chrome_gpt --wait-s 3600 --lock-dir DIR -- <command...>
  python scripts/cdp_lane_lock.py --status
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

ROLES = ("chrome_gpt", "chrome_gemini", "chrome_ppl", "chrome_tv")
POLL_S = 2.0
BUSY_EXIT = 75
USAGE_EXIT = 2


def default_lock_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude", "state", "cdp_lane_locks")


def lock_path(lock_dir: str, role: str) -> str:
    return os.path.join(lock_dir, role + ".lock")


def holder_path(lock_dir: str, role: str) -> str:
    return os.path.join(lock_dir, role + ".holder.json")


def _write_byte_if_empty(fd: int) -> None:
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"L")
    except OSError:
        pass


def _try_acquire(fd: int) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _release(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def read_holder(lock_dir: str, role: str):
    try:
        with open(holder_path(lock_dir, role), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_holder(lock_dir: str, role: str, command: list[str]) -> None:
    payload = {
        "pid": os.getpid(),
        "started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "argv": list(command[:3]),
        "cwd": os.getcwd(),
    }
    try:
        with open(holder_path(lock_dir, role), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError:
        pass


def remove_holder(lock_dir: str, role: str) -> None:
    try:
        os.remove(holder_path(lock_dir, role))
    except OSError:
        pass


def is_locked(lock_dir: str, role: str) -> bool:
    """Probe the OS lock without creating the lock file as a side effect."""
    try:
        fd = os.open(lock_path(lock_dir, role), os.O_RDWR)
    except OSError:
        return False
    try:
        if _try_acquire(fd):
            _release(fd)
            return False
        return True
    except OSError:
        return True


def print_status(lock_dir: str) -> int:
    for role in ROLES:
        locked = is_locked(lock_dir, role)
        holder = read_holder(lock_dir, role) if locked else None
        print(json.dumps({"role": role, "locked": locked, "holder": holder}))
    return 0


def emit_busy(role: str, holder) -> int:
    print(json.dumps({"status": "LANE_BUSY", "role": role, "holder": holder}))
    return BUSY_EXIT


def split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1:]
    return argv, []


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pre, command = split_argv(argv)

    parser = argparse.ArgumentParser(
        prog="cdp_lane_lock.py",
        description="Exclusive per-role lock wrapping a CDP-lane command.",
    )
    parser.add_argument("--role", choices=ROLES)
    parser.add_argument("--wait-s", type=float, default=3600.0)
    parser.add_argument("--lock-dir", default=default_lock_dir())
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(pre)

    lock_dir = args.lock_dir
    if args.status:
        if args.role is not None:
            parser.error("--status cannot be combined with --role")
        return print_status(lock_dir)

    if args.role is None:
        parser.error("--role is required")
    if not command:
        parser.error("no command given after --")

    os.makedirs(lock_dir, exist_ok=True)
    lpath = lock_path(lock_dir, args.role)

    fd = os.open(lpath, os.O_RDWR | os.O_CREAT, 0o644)
    _write_byte_if_empty(fd)

    deadline = time.monotonic() + max(0.0, args.wait_s)
    while True:
        if _try_acquire(fd):
            break
        if time.monotonic() >= deadline:
            _release(fd)
            return emit_busy(args.role, read_holder(lock_dir, args.role))
        remaining = deadline - time.monotonic()
        time.sleep(min(POLL_S, max(0.0, remaining)))

    write_holder(lock_dir, args.role, command)
    try:
        try:
            proc = subprocess.run(command, shell=False)
            return proc.returncode
        except FileNotFoundError:
            print(json.dumps({"status": "CMD_NOT_FOUND", "argv0": command[0]}))
            return 127
    finally:
        remove_holder(lock_dir, args.role)
        _release(fd)


if __name__ == "__main__":
    sys.exit(main())
