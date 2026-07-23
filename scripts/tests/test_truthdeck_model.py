from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_model import (  # noqa: E402
    FactState, GateResult, GateState, NextAction, Scope, Snapshot,
    SnapshotValidationError, Stage, make_fact, snapshot_from_dict, snapshot_to_dict,
)


class TruthDeckModelTests(unittest.TestCase):
    def build(self, observed: str = "2026-07-22T12:00:00Z") -> Snapshot:
        fact = make_fact("git.head", "abc", source_type="git", source_locator="repo",
                         observed_at_utc=observed)
        return Snapshot(
            observed_at_utc=observed, scope=Scope(("repo",)),
            tool={"version": "1", "policy_digest_sha256": "0" * 64}, facts=(fact,),
            conflicts=(), gates=(GateResult(Stage.IMPLEMENTED, GateState.PASS),),
            next_action=NextAction("ready", "Ready."), boundaries=(), collector_runs=(),
            source_digest_sha256="1" * 64,
        ).with_content_id()

    def test_round_trip_and_semantic_id_ignore_observation_time(self) -> None:
        first = self.build()
        second = self.build("2026-07-22T12:00:01Z")
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(snapshot_from_dict(snapshot_to_dict(first)), first)

    def test_unknown_fact_key_rejected(self) -> None:
        with self.assertRaises(SnapshotValidationError):
            make_fact("agent.claim", True, source_type="chat", source_locator="chat",
                      observed_at_utc="2026-07-22T12:00:00Z")

    def test_fact_type_is_closed(self) -> None:
        with self.assertRaises(SnapshotValidationError):
            make_fact("git.clean", "yes", source_type="git", source_locator="repo",
                      observed_at_utc="2026-07-22T12:00:00Z")

    def test_stale_and_unavailable_may_have_null_value(self) -> None:
        fact = make_fact("runtime.ready", None, state=FactState.UNAVAILABLE,
                         source_type="runtime", source_locator="probe",
                         observed_at_utc="2026-07-22T12:00:00Z")
        self.assertIsNone(fact.value)


if __name__ == "__main__":
    unittest.main()
