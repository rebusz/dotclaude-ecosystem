"""Trusted migration of historical uncertainty; temporary Conductor state only."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.conductor_resources import HostResourceManager, ResourceAdmissionError, provider_source_capacity
from scripts.conductor_store import ConductorStore


def manager(root, source="cursor"):
    return HostResourceManager(ConductorStore(root_dir=root), "provider:" + source)


def retain(owner, key="original-family", **changes):
    args = dict(observation_key=key, original_owner="original-session:turn",
                evidence_ref="protected:attempt-receipt.json", evidence_sha256="a" * 64,
                actor="migration:observer")
    args.update(changes)
    return owner.retain_observed_attempt(**args)


def request(owner, name):
    return owner.request(purpose=owner.resource_key.replace(":", "_"), attempt_id=name,
                         agent_instance="new-owner", idempotency_key="request:" + name)


def test_unbound_hold_has_no_native_identity_or_lease_and_counts_globally(tmp_path):
    owner = manager(tmp_path)
    held = retain(owner)
    replay = retain(manager(tmp_path))
    assert held["state"] == "RECOVERY_REQUIRED" and held["lease_id"] is None
    assert replay["request_id"] == held["request_id"] and replay["idempotent_replay"]
    row = owner.store.get_resource_request(held["request_id"])
    assert row.attempt_id.startswith("unbound-observation:")
    assert row.agent_instance == "original-session:turn"
    with owner.store._connection() as db:
        events = db.execute("SELECT details_json FROM host_resource_events WHERE request_id=?",
                            (held["request_id"],)).fetchall()
    assert len(events) == 1
    assert json.loads(events[0][0])["native_attempt_id"] is None
    for index in range(2):
        assert request(manager(tmp_path), f"new-{index}")["state"] == "ACTIVE"
    assert request(manager(tmp_path), "fourth")["state"] == "QUEUED"
    with pytest.raises(ResourceAdmissionError, match="RETAINED_OBSERVATION_DRIFT"):
        retain(owner, native_attempt_id="unverified-candidate")


@pytest.mark.parametrize("released", [False, True])
def test_existing_request_is_refenced_in_place_and_never_double_counted(tmp_path, released):
    owner = manager(tmp_path, "perplexity")
    cdp = HostResourceManager(owner.store, "cdp:perplexity")
    original = cdp.request(purpose="cdp_perplexity", attempt_id="native-original",
                           agent_instance="original-session:turn", idempotency_key="original-submit")
    if released:
        cdp.release(original["request_id"], reason="OLD_WRAPPER_RELEASED_ON_TIMEOUT")
    before = owner.store.get_resource_request(original["request_id"])
    held = retain(owner, native_attempt_id="native-original", existing_request_id=original["request_id"])
    assert held["request_id"] == original["request_id"]
    assert held["lease_id"] == original["lease_id"]
    after = owner.store.get_resource_request(original["request_id"])
    assert after.state.value == "RECOVERY_REQUIRED"
    for field in ("attempt_id", "agent_instance", "idempotency_key", "released_at_utc", "resource_key"):
        assert getattr(after, field) == getattr(before, field)
    assert len(owner.store.list_resource_requests()) == 1
    # A second evidence observation about the same original is not another slot.
    retain(owner, key="second-observation", native_attempt_id="native-original")
    assert len(owner.store.list_resource_requests()) == 1
    # The re-fenced original holds one slot; the rest of the perplexity budget admits.
    for index in range(provider_source_capacity("perplexity") - 1):
        assert request(owner, f"new-{index}")["state"] == "ACTIVE"
    assert request(owner, "new-over")["state"] == "QUEUED"


def test_foreign_binding_and_unverified_identity_cannot_reclassify_request(tmp_path):
    owner = manager(tmp_path)
    original = request(owner, "original")
    with pytest.raises(ValueError, match="verified attempt"):
        retain(owner, existing_request_id=original["request_id"])
    with pytest.raises(ResourceAdmissionError, match="IDENTITY_MISMATCH"):
        retain(owner, native_attempt_id="foreign", existing_request_id=original["request_id"])
    assert owner.store.get_resource_request(original["request_id"]).state.value == "ACTIVE"
    with pytest.raises(ValueError, match="SHA256"):
        retain(owner, evidence_sha256="unknown")
    assert len(owner.store.list_resource_requests()) == 1


def test_concurrent_replays_create_one_observed_hold(tmp_path):
    owners = [manager(tmp_path) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(retain, owners))
    assert len({result["request_id"] for result in results}) == 1
    assert len(owners[0].store.list_resource_requests()) == 1


def test_two_original_unbound_attempts_hold_two_slots_without_guessing_ids(tmp_path):
    owner = manager(tmp_path)
    first = retain(owner, key="family-policy")
    second = retain(owner, key="older-s8", evidence_ref="protected:s8-receipt.json", evidence_sha256="b" * 64)
    assert first["request_id"] != second["request_id"]
    assert request(owner, "new-one")["state"] == "ACTIVE"
    assert request(owner, "new-two")["state"] == "QUEUED"
    assert request(manager(tmp_path, "claude"), "independent")["state"] == "ACTIVE"


def test_import_can_exceed_capacity_without_erasing_or_releasing_history(tmp_path):
    owner = manager(tmp_path)
    for index in range(4):
        assert retain(owner, key=f"historical-{index}")["state"] == "RECOVERY_REQUIRED"
    assert len(owner.store.list_resource_requests()) == 4
    assert request(owner, "new")["state"] == "QUEUED"


def test_dead_wrapper_is_not_native_terminal_evidence(tmp_path, monkeypatch):
    owner = manager(tmp_path)
    held = retain(owner)
    monkeypatch.setattr(owner, "_owner_liveness", lambda *_: (True, "OWNER_PROCESS_GONE"))
    with pytest.raises(ResourceAdmissionError, match="RETAINED_PROVIDER_TERMINAL_UNPROVEN"):
        owner.recover(held["request_id"])
    with pytest.raises(ResourceAdmissionError, match="RECOVERY_REQUIRED_RELEASE_REFUSED"):
        owner.release(held["request_id"])
    recovered = owner.recover(held["request_id"], operator_attestation=True,
                              reason="owner-qualified native terminal receipt")
    assert recovered["status"] == "RECOVERED" and recovered["attested"] is True
    assert recovered["evidence"] == "OPERATOR_PROVIDER_TERMINAL_ATTESTED"
    # Replaying old import evidence cannot re-fence a qualified resolved hold.
    assert retain(owner)["state"] == "RELEASED"


def test_actual_cli_registration_reuses_original_request(tmp_path, monkeypatch):
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path))
    cli = str(Path(__file__).resolve().parents[1] / "conductorctl.py")
    args = [sys.executable, cli, "resource-retain-observed", "--source", "cursor",
            "--observation-key", "native-unbound", "--original-owner", "original-session:turn",
            "--evidence-ref", "protected:receipt.json", "--evidence-sha256", "a" * 64,
            "--actor", "migration:observer"]
    result = json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout)["result"]
    replay = json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout)["result"]
    assert result["state"] == "RECOVERY_REQUIRED" and result["lease_id"] is None
    assert replay["request_id"] == result["request_id"] and replay["idempotent_replay"] is True


def test_owner_mismatch_cannot_refence_or_promote_released_original(tmp_path):
    owner = manager(tmp_path, "perplexity")
    original = request(owner, "native-original")
    owner.release(original["request_id"], reason="OLD_WRAPPER_RELEASE")
    before = owner.store.get_resource_request(original["request_id"])
    with pytest.raises(ResourceAdmissionError, match="IDENTITY_MISMATCH"):
        retain(owner, native_attempt_id="native-original", existing_request_id=original["request_id"],
               original_owner="wrong-scope-owner")
    assert owner.store.get_resource_request(original["request_id"]) == before
    # Valid registration fences the exact row; it never grants queued work.
    for index in range(provider_source_capacity("perplexity")):
        request(owner, f"occupied-{index}")
    queued = request(owner, "waiting")
    retain(owner, native_attempt_id="native-original", existing_request_id=original["request_id"],
           original_owner="new-owner")
    assert owner.store.get_resource_request(queued["request_id"]).state.value == "QUEUED"


@pytest.mark.parametrize("source", ["cursor", "perplexity"])
def test_new_uncertain_remote_work_requires_terminal_attestation(tmp_path, monkeypatch, source):
    owner = manager(tmp_path, source)
    original = request(owner, "native-original")
    owner.mark_uncertain(original["request_id"], attempt_id="native-original",
                         agent_instance="new-owner", reason="arbitrary transport failure")
    monkeypatch.setattr(owner, "_owner_liveness", lambda *_: (True, "OWNER_PROCESS_GONE"))
    with pytest.raises(ResourceAdmissionError, match="RETAINED_PROVIDER_TERMINAL_UNPROVEN"):
        owner.recover(original["request_id"])
    assert owner.store.get_resource_request(original["request_id"]).state.value == "RECOVERY_REQUIRED"
    recovered = owner.recover(original["request_id"], operator_attestation=True,
                              reason="verified provider terminal receipt")
    assert recovered["evidence"] == "OPERATOR_PROVIDER_TERMINAL_ATTESTED"
