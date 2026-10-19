"""Actual shared Conductor transactions, using only temporary stores."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.conductor_model import HostResourcePool
from scripts.conductor_resources import HostResourceManager, ResourceAdmissionError, ResourceBusyError
from scripts.conductor_store import ConductorStore


def request(manager, name, purpose=None, **kwargs):
    purpose = purpose or manager.resource_key.replace(":", "_")
    return manager.request(purpose=purpose, attempt_id=name, agent_instance="codex:orchestrator",
                           idempotency_key="request:" + name, **kwargs)


@pytest.mark.parametrize("source", ["chatgpt", "perplexity", "cursor", "antigravity", "zai", "claude"])
def test_three_plus_one_survives_distinct_clients_restart_and_uses_same_queue(tmp_path, source):
    managers = [HostResourceManager(ConductorStore(root_dir=tmp_path), f"provider:{source}")
                for _ in range(4)]
    admitted = [request(manager, f"job-{index}") for index, manager in enumerate(managers)]
    assert [row["state"] for row in admitted] == ["ACTIVE", "ACTIVE", "ACTIVE", "QUEUED"]
    restarted = HostResourceManager(ConductorStore(root_dir=tmp_path), f"provider:{source}")
    assert request(restarted, "job-3")["request_id"] == admitted[3]["request_id"]
    promoted = restarted.release(admitted[0]["request_id"], reason="NATIVE_TERMINAL_CONFIRMED")
    assert promoted["promoted"]["request_id"] == admitted[3]["request_id"]
    replay = request(restarted, "job-3")
    assert replay["state"] == "ACTIVE" and replay["idempotent_replay"] is True
    assert len(restarted.store.list_resource_requests(resource_key=f"provider:{source}")) == 4


def test_concurrent_clients_cannot_split_cap_between_cdp_and_native(tmp_path):
    ConductorStore(root_dir=tmp_path)
    managers = [HostResourceManager(ConductorStore(root_dir=tmp_path),
                                   "cdp:chatgpt" if i % 2 else "provider:chatgpt")
                for i in range(12)]
    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda pair: request(pair[1], f"job-{pair[0]}"), enumerate(managers)))
    assert sum(row["state"] == "ACTIVE" for row in results) == 3
    assert sum(row["state"] == "QUEUED" for row in results) == 9


def test_agy_gemini_share_source_and_keep_gemini_platform_capacity_one(tmp_path):
    store = ConductorStore(root_dir=tmp_path)
    agy = HostResourceManager(store, "provider:antigravity")
    gemini = HostResourceManager(store, "cdp:gemini")
    first = request(gemini, "gemini-1")
    second = request(gemini, "gemini-2")
    assert first["state"] == "ACTIVE" and second["state"] == "QUEUED"
    assert request(agy, "agy-1")["state"] == "ACTIVE"
    assert request(agy, "agy-2")["state"] == "ACTIVE"
    fourth = request(agy, "agy-3")
    assert fourth["state"] == "QUEUED"
    gemini.release(first["request_id"])
    assert request(gemini, "gemini-2")["state"] == "ACTIVE"
    assert request(agy, "agy-3")["state"] == "QUEUED"
    assert store.get_resource_pool("cdp:gemini").capacity == 1


def test_release_promotes_waiting_sibling_pool(tmp_path):
    store = ConductorStore(root_dir=tmp_path)
    cdp = HostResourceManager(store, "cdp:perplexity")
    local = HostResourceManager(store, "provider:perplexity")
    held = [request(cdp, f"held-{i}") for i in range(3)]
    queued = request(local, "local")
    assert queued["state"] == "QUEUED"
    result = cdp.release(held[0]["request_id"], reason="NATIVE_TERMINAL_CONFIRMED")
    assert result["promoted"]["request_id"] == queued["request_id"]
    assert request(local, "local")["state"] == "ACTIVE"


def test_unknown_owner_expired_and_uncertain_attempts_remain_counted(tmp_path):
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, "provider:cursor")
    held = [request(manager, f"held-{i}") for i in range(3)]
    with store._connection() as conn:
        conn.execute("UPDATE host_resource_leases SET expires_at_utc='2000-01-01T00:00:00+00:00'")
    manager.mark_uncertain(held[0]["request_id"], attempt_id="held-0",
                           agent_instance="codex:orchestrator", reason="SUBMIT_UNCONFIRMED")
    with pytest.raises(ResourceAdmissionError, match="RECOVERY_REQUIRED_RELEASE_REFUSED"):
        manager.release(held[0]["request_id"])
    assert request(manager, "fourth")["state"] == "QUEUED"
    # Unknown PID is not proof of owner exit and expiry cannot free a slot.
    manager.reconcile()
    assert request(manager, "fifth")["state"] == "QUEUED"
    assert request(HostResourceManager(store, "provider:claude"), "independent")["state"] == "ACTIVE"


def test_identity_and_source_aliases_cannot_bypass_the_cap(tmp_path):
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store, "provider:claude")
    first = request(manager, "held")
    with pytest.raises(ResourceAdmissionError, match="IDENTITY_MISMATCH"):
        manager.mark_uncertain(first["request_id"], attempt_id="foreign", agent_instance="codex:orchestrator",
                               reason="SUBMIT_UNCONFIRMED")
    with pytest.raises(ResourceAdmissionError, match="IDEMPOTENCY_CONFLICT"):
        request(HostResourceManager(store, "provider:cursor"), "held")
    with pytest.raises(ValueError, match="actual source"):
        request(manager, "wrong-purpose", purpose="provider_cursor")
    with pytest.raises(ValueError, match="unknown resource key"):
        HostResourceManager(store, "provider:claude-opus")
    with pytest.raises(ValueError, match="unknown resource key"):
        HostResourceManager(store, "provider:codex")


def test_platform_pool_raise_or_inheritance_cannot_evade_source_limit(tmp_path):
    store = ConductorStore(root_dir=tmp_path)
    cdp = HostResourceManager(store, "cdp:chatgpt")
    store.save_resource_pool(HostResourcePool(resource_key="cdp:chatgpt", capacity=9))
    held = [request(cdp, f"held-{i}") for i in range(3)]
    assert request(cdp, "fourth")["state"] == "QUEUED"
    with pytest.raises(ResourceBusyError, match="PROVIDER_SOURCE_BUSY"):
        request(cdp, "inherited", parent_lease_id=held[0]["lease_id"])


def test_cli_admission_and_uncertainty_use_real_temp_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path))
    cli = str(Path(__file__).resolve().parents[1] / "conductorctl.py")
    args = [sys.executable, cli, "resource-request", "--purpose", "provider_zai",
            "--attempt-id", "cli-one", "--agent-instance", "codex:orchestrator",
            "--idempotency-key", "cli-one"]
    launched = subprocess.run(args, check=True, capture_output=True, text=True)
    result = json.loads(launched.stdout)["result"]
    assert result["state"] == "ACTIVE" and result["idempotent_replay"] is False
    marked = subprocess.run([sys.executable, cli, "resource-uncertain", "--request-id", result["request_id"],
                             "--attempt-id", "cli-one", "--agent-instance", "codex:orchestrator",
                             "--reason", "SUBMIT_UNCONFIRMED"], check=True, capture_output=True, text=True)
    assert json.loads(marked.stdout)["result"]["state"] == "RECOVERY_REQUIRED"
    released = subprocess.run([sys.executable, cli, "resource-release", "--request-id", result["request_id"]],
                              capture_output=True, text=True)
    # The installed older CLI reports legacy failures in its receipt even
    # when the process exits zero. The durable refusal is authoritative.
    assert json.loads(released.stdout)["status"] == "ERROR"
    assert "RECOVERY_REQUIRED_RELEASE_REFUSED" in released.stdout
    assert ConductorStore(root_dir=tmp_path).get_resource_request(result["request_id"]).state.value == "RECOVERY_REQUIRED"
