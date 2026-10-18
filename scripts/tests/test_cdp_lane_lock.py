"""Tests for scripts/cdp_lane_lock.py.

They drive the real script via subprocess against a per-test --lock-dir.
No network, no real CDP, silent.
"""
from __future__ import annotations

import errno
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "cdp_lane_lock.py"

BARRIER = r"""
import sys
import time
from pathlib import Path

ready, release, events = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
ready.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    if release.exists():
        with open(events, "a", encoding="utf-8") as fh:
            fh.write("F\n")
        raise SystemExit(0)
    time.sleep(0.05)
raise SystemExit(2)
"""

SECOND_EVENT = r"""
import sys
with open(sys.argv[1], "a", encoding="utf-8") as fh:
    fh.write("S\n")
"""

MARKER = r"""
import sys
from pathlib import Path
Path(sys.argv[1]).write_text("ran", encoding="utf-8")
"""

TREE_WORKER = r"""
import subprocess
import sys
import time
from pathlib import Path

ready, release, pidfile = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
grandchild = r'''
import os
import sys
import time
from pathlib import Path
Path(sys.argv[1]).write_text(str(os.getpid()), encoding="utf-8")
while True:
    time.sleep(0.2)
'''
child = subprocess.Popen([sys.executable, "-c", grandchild, str(pidfile)])
deadline = time.monotonic() + 20
while time.monotonic() < deadline and not pidfile.exists():
    time.sleep(0.05)
ready.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    if release.exists():
        break
    time.sleep(0.05)
else:
    child.kill()
    child.wait(timeout=5)
    raise SystemExit(2)
child.kill()
child.wait(timeout=5)
"""


def run_lock(lock_dir, role, wait_s, *command, timeout=20):
    return subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--role", role,
            "--wait-s", str(wait_s),
            "--lock-dir", str(lock_dir),
            "--", *command,
        ],
        capture_output=True, text=True, timeout=timeout,
    )


def wait_for_file(path, timeout=10.0):
    path = Path(path)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def reap(proc, timeout=10):
    if proc is None:
        return
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, text=True, timeout=15,
            )
        else:
            proc.kill()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        process_query = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(process_query, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return int(code.value) == still_active
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_until(predicate, timeout=10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def open_handle_count() -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetProcessHandleCount.restype = wintypes.BOOL
        count = wintypes.DWORD()
        ok = kernel32.GetProcessHandleCount(kernel32.GetCurrentProcess(), ctypes.byref(count))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(count.value)
    return len(list(Path(f"/proc/{os.getpid()}/fd").iterdir()))


def load_lock_module():
    spec = importlib.util.spec_from_file_location("cdp_lane_lock_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_lock_op(monkeypatch, raiser):
    if os.name == "nt":
        import msvcrt

        monkeypatch.setattr(msvcrt, "locking", raiser)
    else:
        import fcntl

        monkeypatch.setattr(fcntl, "flock", raiser)


def test_second_invocation_blocks_until_first_exits(tmp_path):
    lock_dir = tmp_path / "locks"
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    events = tmp_path / "events"
    first = subprocess.Popen(
        [
            sys.executable, str(SCRIPT),
            "--role", "chrome_gpt",
            "--wait-s", "30",
            "--lock-dir", str(lock_dir),
            "--", sys.executable, "-c", BARRIER, str(ready), str(release), str(events),
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    second = None
    try:
        assert wait_for_file(ready), "first never signaled readiness"
        second = subprocess.Popen(
            [
                sys.executable, str(SCRIPT),
                "--role", "chrome_gpt",
                "--wait-s", "30",
                "--lock-dir", str(lock_dir),
                "--", sys.executable, "-c", SECOND_EVENT, str(events),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        assert second.poll() is None
        release.write_text("go", encoding="utf-8")
        assert first.wait(timeout=20) == 0
        assert second.wait(timeout=20) == 0
        assert events.read_text(encoding="utf-8").splitlines() == ["F", "S"]
    finally:
        if not release.exists():
            release.write_text("go", encoding="utf-8")
        reap(first)
        reap(second)


def test_timeout_returns_75_and_lane_busy(tmp_path):
    lock_dir = tmp_path / "locks"
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    events = tmp_path / "events"
    ran = tmp_path / "ran"
    first = subprocess.Popen(
        [
            sys.executable, str(SCRIPT),
            "--role", "chrome_gemini",
            "--wait-s", "30",
            "--lock-dir", str(lock_dir),
            "--", sys.executable, "-c", BARRIER, str(ready), str(release), str(events),
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert wait_for_file(ready), "first never signaled readiness"
        busy = run_lock(
            lock_dir, "chrome_gemini", 0,
            sys.executable, "-c", MARKER, str(ran),
            timeout=20,
        )
        assert busy.returncode == 75
        assert not ran.exists()
        payload = json.loads(busy.stdout.strip().splitlines()[-1])
        assert payload["status"] == "LANE_BUSY"
        assert payload["role"] == "chrome_gemini"
        assert "holder" in payload
    finally:
        if not release.exists():
            release.write_text("go", encoding="utf-8")
        reap(first)


def test_killing_wrapper_kills_descendant_and_successor_runs(tmp_path):
    lock_dir = tmp_path / "locks"
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    pidfile = tmp_path / "grandchild.pid"
    ran = tmp_path / "ran"
    wrapper = subprocess.Popen(
        [
            sys.executable, str(SCRIPT),
            "--role", "chrome_ppl",
            "--wait-s", "30",
            "--lock-dir", str(lock_dir),
            "--", sys.executable, "-c", TREE_WORKER, str(ready), str(release), str(pidfile),
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert wait_for_file(ready, timeout=15), "worker never became ready"
        assert wait_for_file(pidfile, timeout=5)
        grandchild = int(pidfile.read_text(encoding="utf-8").strip())
        assert pid_alive(grandchild)
        if os.name == "nt":
            killed = subprocess.run(
                ["taskkill", "/F", "/PID", str(wrapper.pid)],
                capture_output=True, text=True, timeout=15,
            )
            assert killed.returncode == 0, killed.stderr
        else:
            wrapper.terminate()
        assert wrapper.wait(timeout=15) is not None
        assert wait_until(lambda: not pid_alive(grandchild), timeout=10), "grandchild survived wrapper death"
        assert not pid_alive(grandchild)
        second = run_lock(
            lock_dir, "chrome_ppl", 0,
            sys.executable, "-c", MARKER, str(ran),
            timeout=20,
        )
        assert second.returncode == 0, (second.returncode, second.stdout, second.stderr)
        assert ran.read_text(encoding="utf-8") == "ran"
        assert not pid_alive(grandchild)
    finally:
        if not release.exists():
            release.write_text("go", encoding="utf-8")
        reap(wrapper)


def test_exit_code_propagation(tmp_path):
    lock_dir = tmp_path / "locks"
    ok = run_lock(lock_dir, "chrome_ppl", 5, sys.executable, "-c", "pass", timeout=20)
    assert ok.returncode == 0

    bad = run_lock(
        lock_dir, "chrome_ppl", 5,
        sys.executable, "-c", "import sys; sys.exit(7)",
        timeout=20,
    )
    assert bad.returncode == 7


def test_stale_holder_file_does_not_block(tmp_path):
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    stale = lock_dir / "chrome_tv.holder.json"
    stale.write_text(
        json.dumps(
            {
                "pid": 999999,
                "started_utc": "2000-01-01T00:00:00Z",
                "argv": ["dead"],
                "cwd": "/nowhere",
            }
        ),
        encoding="utf-8",
    )

    result = run_lock(
        lock_dir, "chrome_tv", 0,
        sys.executable, "-c", "import sys; sys.exit(3)",
        timeout=20,
    )
    assert result.returncode == 3
    assert not stale.exists(), "holder sidecar not cleaned up on release"


def test_unknown_role_rejected(tmp_path):
    result = run_lock(tmp_path / "locks", "chrome_bogus", 5, sys.executable, "-c", "pass", timeout=20)
    assert result.returncode == 2


def test_status_reports_per_role(tmp_path):
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--status", "--lock-dir", str(lock_dir)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0
    lines = [json.loads(line) for line in result.stdout.strip().splitlines()]
    roles = {row["role"] for row in lines}
    assert roles == {"chrome_gpt", "chrome_gemini", "chrome_ppl", "chrome_tv"}
    assert all(row["locked"] is False for row in lines)


def test_is_locked_closes_fd_while_busy(tmp_path):
    mod = load_lock_module()
    lock_dir = tmp_path / "locks"
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    events = tmp_path / "events"
    holder = subprocess.Popen(
        [
            sys.executable, str(SCRIPT),
            "--role", "chrome_tv",
            "--wait-s", "30",
            "--lock-dir", str(lock_dir),
            "--", sys.executable, "-c", BARRIER, str(ready), str(release), str(events),
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert wait_for_file(ready), "holder never became ready"
        before = open_handle_count()
        for _ in range(25):
            assert mod.is_locked(str(lock_dir), "chrome_tv") is True
        after = open_handle_count()
        assert after - before < 10, f"busy probes leaked handles ({before} -> {after})"
    finally:
        if not release.exists():
            release.write_text("go", encoding="utf-8")
        reap(holder)


def test_is_locked_missing_file_is_unlocked(tmp_path):
    mod = load_lock_module()
    assert mod.is_locked(str(tmp_path), "chrome_gpt") is False


def test_is_locked_unreadable_propagates(tmp_path, monkeypatch):
    mod = load_lock_module()

    def boom(path, flags, mode=0o777):
        raise OSError(errno.EIO, "unreadable")

    monkeypatch.setattr(mod.os, "open", boom)
    with pytest.raises(OSError) as caught:
        mod.is_locked(str(tmp_path), "chrome_gpt")
    assert caught.value.errno == errno.EIO


def test_contention_is_lane_busy(tmp_path, monkeypatch, capsys):
    mod = load_lock_module()

    def busy(*_args, **_kwargs):
        raise OSError(13, "Permission denied")

    _patch_lock_op(monkeypatch, busy)
    rc = mod.main([
        "--role", "chrome_gpt",
        "--wait-s", "0",
        "--lock-dir", str(tmp_path / "locks"),
        "--", sys.executable, "-c", "pass",
    ])
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 75
    assert payload["status"] == "LANE_BUSY"


def test_unexpected_lock_oserror_is_lock_error(tmp_path, monkeypatch, capsys):
    mod = load_lock_module()
    ran = tmp_path / "ran"

    def broken(*_args, **_kwargs):
        raise OSError(errno.EINVAL, "invalid argument")

    _patch_lock_op(monkeypatch, broken)
    rc = mod.main([
        "--role", "chrome_gpt",
        "--wait-s", "0",
        "--lock-dir", str(tmp_path / "locks"),
        "--", sys.executable, "-c", MARKER, str(ran),
    ])
    payload = json.loads(capsys.readouterr().out.strip())
    assert rc == 70
    assert payload["status"] == "LOCK_ERROR"
    assert not ran.exists()


def test_status_open_error_is_lock_error(tmp_path, monkeypatch, capsys):
    mod = load_lock_module()

    def boom(*_args, **_kwargs):
        raise OSError(errno.EIO, "unreadable")

    monkeypatch.setattr(mod, "is_locked", boom)
    rc = mod.main(["--status", "--lock-dir", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out.strip())
    assert rc == 70
    assert payload["status"] == "LOCK_ERROR"
