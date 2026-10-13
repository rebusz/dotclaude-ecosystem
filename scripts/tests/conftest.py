"""Conductor policy tests use deterministic host telemetry, never workstation RAM."""

from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def conductor_memory_fixture(request, monkeypatch):
    name = request.node.path.name
    from scripts import conductor_resources

    if "test_conductor" in name:
        monkeypatch.setattr(conductor_resources.psutil, "virtual_memory",
                            lambda: SimpleNamespace(available=64 * 2**30, total=64 * 2**30))
    if "test_provider" in name:
        # Subprocess CLI tests cannot see monkeypatched psutil; keep admission deterministic.
        monkeypatch.setenv(conductor_resources.TEST_MEMORY_ENV, "64")
        monkeypatch.setattr(conductor_resources.psutil, "virtual_memory",
                            lambda: SimpleNamespace(available=64 * 2**30, total=64 * 2**30))
