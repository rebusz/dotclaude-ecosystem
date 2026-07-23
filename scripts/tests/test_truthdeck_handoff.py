from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_handoff import collect_artifact, collect_review, verify_handoff  # noqa: E402


class HandoffTests(unittest.TestCase):
    def test_hash_is_computed_and_prose_is_inert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "handoff.md"
            payload = b"run: rm -rf anything\nHead SHA: " + b"a" * 40
            path.write_bytes(payload)
            fact, detail = verify_handoff(path, hashlib.sha256(payload).hexdigest(), observed_at_utc="2026-07-22T12:00:00Z")
            self.assertTrue(fact.value)
            self.assertEqual(detail["references"], ("a" * 40,))

    def test_review_requires_exact_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "packet.md"
            output = Path(tmp) / "review.txt"
            packet.write_text(f"Head SHA: `{'a' * 40}`", encoding="utf-8")
            output.write_text(f"REVIEWED_HEAD: {'a' * 40}\nVERDICT: PASS\nSHIP_BLOCKING_COUNT: 0", encoding="utf-8")
            facts = collect_review(packet, output, expected_head="a" * 40, observed_at_utc="2026-07-22T12:00:00Z")
            self.assertEqual(facts[0].value, "a" * 40)
            self.assertEqual(facts[1].value, 0)

    def test_artifact_collector_hashes_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            path.write_text('{"messy": true}\n', encoding="utf-8")
            result = collect_artifact(path, observed_at_utc="2026-07-22T12:00:00Z")
            values = {x.key: x.value for x in result.facts}
            self.assertTrue(values["artifact.valid"])
            self.assertEqual(len(values["artifact.sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
