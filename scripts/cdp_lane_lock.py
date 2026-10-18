#!/usr/bin/env python3
"""cdp_lane_lock.py — per-role lane lock for shared CDP Chrome roles.

Waiters poll independently every ``POLL_S`` seconds and race for the lock.
Admission is unordered and starvation is possible: a later arrival can
acquire a freed lock while an older waiter is still asleep.

The default lock directory is one account's home
(``~/.claude/state/cdp_lane_locks``). Only processes that share that
directory coordinate. Different accounts, or launch environments that
resolve different homes, do not share a lock. ``--lock-dir`` overrides
the directory (tests use an isolated one).

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
import errno
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

ROLES = ("chrome_gpt", "chrome_gemini", "chrome_ppl", "chrome_tv")
POLL_S = 2.0
BUSY_EXIT = 75
USAGE_EXIT = 2
LOCK_ERROR_EXIT = 70
_WIN_LOCK_VIOLATION = 33

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.SetHandleInformation.restype = wintypes.BOOL
    _kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID,
    ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _HANDLE_FLAG_INHERIT = 0x00000001


class _Term(BaseException):
    """SIGTERM observed while a command tree is owned."""


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


def _is_contention(exc: OSError) -> bool:
    """True only for lock-contention failures, not operational OS errors."""
    winerror = getattr(exc, "winerror", None)
    if winerror == _WIN_LOCK_VIOLATION:
        return True
    if os.name == "nt" and exc.errno == 13:
        return True
    return exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)


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
    except OSError as exc:
        if _is_contention(exc):
            return False
        raise


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


def _close_fd(fd: int) -> None:
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
    """Probe the OS lock without creating the lock file.

    A missing lock file is not locked. Any other open failure propagates.
    The descriptor is closed on every path; the byte-range lock is released
    only when this probe itself acquired it.
    """
    try:
        fd = os.open(lock_path(lock_dir, role), os.O_RDWR)
    except OSError as exc:
        if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
            return False
        raise
    acquired = False
    try:
        acquired = _try_acquire(fd)
        return not acquired
    finally:
        if acquired:
            _release(fd)
        else:
            _close_fd(fd)


def print_status(lock_dir: str) -> int:
    rows = []
    for role in ROLES:
        locked = is_locked(lock_dir, role)
        holder = read_holder(lock_dir, role) if locked else None
        rows.append({"role": role, "locked": locked, "holder": holder})
    for row in rows:
        print(json.dumps(row))
    return 0


def emit_busy(role: str, holder) -> int:
    print(json.dumps({"status": "LANE_BUSY", "role": role, "holder": holder}))
    return BUSY_EXIT


def emit_lock_error() -> int:
    print(json.dumps({"status": "LOCK_ERROR"}))
    return LOCK_ERROR_EXIT


def split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1:]
    return argv, []


def _win_raise(what: str) -> None:
    err = ctypes.get_last_error()
    if err:
        raise ctypes.WinError(err)
    raise OSError(0, what + " failed")


def _create_kill_on_close_job():
    # Non-inheritable so a child cannot keep the job alive after the wrapper dies.
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        _win_raise("CreateJobObjectW")
    _kernel32.SetHandleInformation(handle, _HANDLE_FLAG_INHERIT, 0)
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = _kernel32.SetInformationJobObject(
        handle,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        _kernel32.CloseHandle(handle)
        _win_raise("SetInformationJobObject")
    return handle


def _job_active_processes(handle) -> int:
    info = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    ok = _kernel32.QueryInformationJobObject(
        handle,
        _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
        None,
    )
    if not ok:
        return 0
    return int(info.ActiveProcesses)


class _CommandTree:
    """Owns the wrapped command and its descendants.

    On Windows the child is placed in a job with
    ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` so process-handle rundown on
    wrapper termination kills the tree. ``subprocess.Popen`` cannot pass
    ``CREATE_SUSPENDED`` (it is not a ``Popen`` creation flag), so
    ``AssignProcessToJobObject`` runs immediately after ``Popen`` returns.
    There is a tiny window between process creation and assignment; user
    code has usually not run yet. After assignment, wrapper death cannot
    leave a grandchild running.

    On POSIX the child is started in a new session. Every exit path,
    including KeyboardInterrupt and the SIGTERM handler, signals that
    process group before the caller releases the lock.
    """

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.job = None
        self.pgid: int | None = None

    def start(self, command: list[str]) -> None:
        if os.name == "nt":
            self.job = _create_kill_on_close_job()
            try:
                # CREATE_SUSPENDED is not available via Popen; assign immediately
                # after create. See class docstring for the tiny window.
                self.proc = subprocess.Popen(command, shell=False)
                assigned = _kernel32.AssignProcessToJobObject(self.job, int(self.proc._handle))
                if not assigned:
                    _win_raise("AssignProcessToJobObject")
            except Exception:
                self.terminate_then_kill()
                raise
            return
        self.proc = subprocess.Popen(command, shell=False, start_new_session=True)
        self.pgid = self.proc.pid

    def wait(self) -> int:
        if self.proc is None:
            raise OSError(0, "command was not started")
        return self.proc.wait()

    def _group_alive(self) -> bool:
        if self.pgid is None or self.pgid <= 0:
            return False
        try:
            os.killpg(self.pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False

    def _tree_alive(self) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            return True
        if os.name == "nt":
            return self.job is not None and _job_active_processes(self.job) > 0
        return self._group_alive()

    def _signal_tree(self, kill: bool) -> None:
        if os.name == "nt":
            if self.proc is not None and self.proc.poll() is None:
                try:
                    if kill:
                        self.proc.kill()
                    else:
                        self.proc.terminate()
                except OSError:
                    pass
            if kill and self.job is not None:
                _kernel32.TerminateJobObject(self.job, 1)
            return
        if self.pgid is None or self.pgid <= 0:
            return
        sig = signal.SIGKILL if kill else signal.SIGTERM
        try:
            os.killpg(self.pgid, sig)
        except ProcessLookupError:
            return
        except OSError:
            if self.proc is not None and self.proc.poll() is None:
                try:
                    if kill:
                        self.proc.kill()
                    else:
                        self.proc.terminate()
                except OSError:
                    pass

    def _wait_tree(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        if self.proc is not None and self.proc.poll() is None:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                self.proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass
        while time.monotonic() < deadline and self._tree_alive():
            time.sleep(0.05)

    def _close_job(self) -> None:
        if os.name != "nt" or self.job is None:
            return
        handle = self.job
        self.job = None
        # Closing the last handle also kills survivors (KILL_ON_JOB_CLOSE)
        # before the caller drops the lane lock.
        _kernel32.CloseHandle(handle)

    def terminate_then_kill(self) -> None:
        """SIGTERM/terminate the tree, then SIGKILL/TerminateJobObject it."""
        self._signal_tree(kill=False)
        self._wait_tree(2.0)
        if self._tree_alive():
            self._signal_tree(kill=True)
            self._wait_tree(5.0)
        self._close_job()


def _supervise(command: list[str]) -> int:
    tree = _CommandTree()

    def _on_term(signum, frame):
        tree.terminate_then_kill()
        raise _Term()

    previous = signal.signal(signal.SIGTERM, _on_term)
    try:
        try:
            tree.start(command)
            return tree.wait()
        except FileNotFoundError:
            print(json.dumps({"status": "CMD_NOT_FOUND", "argv0": command[0]}))
            return 127
        except KeyboardInterrupt:
            tree.terminate_then_kill()
            return 130
        except _Term:
            tree.terminate_then_kill()
            return 143
        except OSError:
            tree.terminate_then_kill()
            return emit_lock_error()
    finally:
        # Reap descendants before the caller unlocks, on every exit path.
        tree.terminate_then_kill()
        signal.signal(signal.SIGTERM, previous)


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
        try:
            return print_status(lock_dir)
        except OSError:
            return emit_lock_error()

    if args.role is None:
        parser.error("--role is required")
    if not command:
        parser.error("no command given after --")

    os.makedirs(lock_dir, exist_ok=True)
    lpath = lock_path(lock_dir, args.role)

    fd = None
    held = False
    wrote_holder = False
    try:
        try:
            fd = os.open(lpath, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return emit_lock_error()
        _write_byte_if_empty(fd)

        # Unordered polling: there is no waiter queue.
        deadline = time.monotonic() + max(0.0, args.wait_s)
        while True:
            try:
                held = _try_acquire(fd)
            except OSError:
                return emit_lock_error()
            if held:
                break
            if time.monotonic() >= deadline:
                return emit_busy(args.role, read_holder(lock_dir, args.role))
            remaining = deadline - time.monotonic()
            time.sleep(min(POLL_S, max(0.0, remaining)))

        write_holder(lock_dir, args.role, command)
        wrote_holder = True
        return _supervise(command)
    finally:
        if wrote_holder:
            remove_holder(lock_dir, args.role)
        if fd is not None:
            if held:
                _release(fd)
            else:
                _close_fd(fd)


if __name__ == "__main__":
    sys.exit(main())
