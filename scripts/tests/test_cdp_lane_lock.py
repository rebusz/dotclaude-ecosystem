"""Tests for scripts/cdp_lane_lock.py.

They drive the real script via subprocess against a per-test --lock-dir.
No network, no real CDP, silent.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "cdp_lane_lock.py"


def run_lock(lock_dir, role, wait_s, *command):
    return subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--role", role,
            "--wait-s", str(wait_s),
            "--lock-dir", str(lock_dir),
            "--", *command,
        ],
        capture_output=True, text=True,
    )


def wait_for_holder(lock_dir, role, timeout=10.0):
    path = Path(lock_dir) / (role + ".holder.json")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def test_second_invocation_blocks_until_first_exits(tmp_path):
    lock_dir = tmp_path / "locks"
    first = subprocess.Popen(
        [
            sys.executable, str(SCRIPT),
            "--role", "chrome_gpt",
            "--wait-s", "30",
            "--lock-dir", str(lock_dir),
            "--", sys.executable, "-c", "import time; time.sleep(2)",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert wait_for_holder(lock_dir, "chrome_gpt"), "first never took the lock"

    t1 = time.monotonic()
    second = run_lock(lock_dir, "chrome_gpt", 30, sys.executable, "-c", "pass")
    t2 = time.monotonic()
    first_rc = first.wait(timeout=30)

    assert first_rc == 0
    assert second.returncode == 0
    assert t2 - t1 >= 1.0, f"second did not wait for the first (waited {t2 - t1:.2f}s)"


def test_timeout_returns_75_and_lane_busy(tmp_path):
    lock_dir = tmp_path / "locks"
    first = subprocess.Popen(
        [
            sys.executable, str(SCRIPT),
            "--role", "chrome_gemini",
            "--wait-s", "30",
            "--lock-dir", str(lock_dir),
            "--", sys.executable, "-c", "import time; time.sleep(2)",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert wait_for_holder(lock_dir, "chrome_gemini"), "first never took the lock"

    busy = run_lock(lock_dir, "chrome_gemini", 0, sys.executable, "-c", "pass")
    first.wait(timeout=30)

    assert busy.returncode == 75
    payload = json.loads(busy.stdout.strip().splitlines()[-1])
    assert payload["status"] == "LANE_BUSY"
    assert payload["role"] == "chrome_gemini"
    assert "holder" in payload


def test_exit_code_propagation(tmp_path):
    lock_dir = tmp_path / "locks"
    ok = run_lock(lock_dir, "chrome_ppl", 5, sys.executable, "-c", "pass")
    assert ok.returncode == 0

    bad = run_lock(lock_dir, "chrome_ppl", 5, sys.executable, "-c", "import sys; sys.exit(7)")
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

    result = run_lock(lock_dir, "chrome_tv", 0, sys.executable, "-c", "import sys; sys.exit(3)")
    assert result.returncode == 3
    assert not stale.exists(), "holder sidecar not cleaned up on release"


def test_unknown_role_rejected(tmp_path):
    result = run_lock(tmp_path / "locks", "chrome_bogus", 5, sys.executable, "-c", "pass")
    assert result.returncode == 2


def test_status_reports_per_role(tmp_path):
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--status", "--lock-dir", str(lock_dir)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    lines = [json.loads(line) for line in result.stdout.strip().splitlines()]
    roles = {row["role"] for row in lines}
    assert roles == {"chrome_gpt", "chrome_gemini", "chrome_ppl", "chrome_tv"}
    assert all(row["locked"] is False for row in lines)
