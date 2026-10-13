"""Mandatory per-test watchdog for Conductor's fixed ``python -m pytest`` path.

Includes setup and teardown. The parent owns the Job/group and global deadline;
this timer exits only its own pytest interpreter. No external dependency beyond
pytest, no marker that can turn the watchdog off.
"""

import math
import os
import sys
import threading

import pytest


def _timeout_seconds():
    value = float(os.environ.get("CONDUCTOR_TEST_TIMEOUT_SECONDS", "300"))
    if not math.isfinite(value) or value <= 0:
        raise pytest.UsageError("Conductor per-test timeout must be finite and positive")
    return value


def _expired(nodeid):
    sys.stderr.write(f"\nCONDUCTOR_TEST_TIMEOUT: {nodeid}\n")
    sys.stderr.flush()
    os._exit(124)


def pytest_configure(config):
    _timeout_seconds()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    timer = threading.Timer(_timeout_seconds(), _expired, args=(item.nodeid,))
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()
