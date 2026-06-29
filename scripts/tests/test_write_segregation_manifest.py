from __future__ import annotations

import unittest
from pathlib import Path

import write_segregation_manifest as manifest


class TestWriteSegregationManifest(unittest.TestCase):
    def test_validate_manifest_accepts_required_shape(self):
        data = {
            "schema_version": 1,
            "kind": "mechanical_write_segregation_path_manifest",
            "applies_acl": False,
            "entries": [
                {
                    "id": "tsu-live-state",
                    "repo": "D:/APPS/TSU",
                    "path_glob": "data/live_state*.db*",
                    "class": "live-brain-only",
                    "owner": "TSU live brain",
                    "reason": "SQLite/WAL live state",
                    "rollback_expectation": "remove generated ACL delta only",
                },
                {
                    "id": "tsignal-trading",
                    "repo": "D:/APPS/Tsignal 5.0",
                    "path_glob": "tsignal/trading/**",
                    "class": "operator-only",
                    "owner": "Tsignal operator",
                    "reason": "broker/order path modules",
                    "rollback_expectation": "remove generated ACL delta only",
                },
            ],
        }

        summary = manifest.validate_manifest(data, source=Path("manifest.json"))

        self.assertEqual(summary["entry_count"], 2)
        self.assertEqual(summary["repos"], ["D:/APPS/TSU", "D:/APPS/Tsignal 5.0"])

    def test_validate_manifest_rejects_apply_acl_manifest(self):
        data = {
            "schema_version": 1,
            "kind": "mechanical_write_segregation_path_manifest",
            "applies_acl": True,
            "entries": [],
        }

        with self.assertRaises(ValueError) as caught:
            manifest.validate_manifest(data, source=Path("manifest.json"))

        self.assertIn("applies_acl must be false", str(caught.exception))

    def test_validate_manifest_rejects_unknown_class(self):
        data = {
            "schema_version": 1,
            "kind": "mechanical_write_segregation_path_manifest",
            "applies_acl": False,
            "entries": [
                {
                    "id": "tsu-live-state",
                    "repo": "D:/APPS/TSU",
                    "path_glob": "data/live_state*.db*",
                    "class": "deny-all",
                    "owner": "TSU live brain",
                    "reason": "SQLite/WAL live state",
                    "rollback_expectation": "remove generated ACL delta only",
                },
                {
                    "id": "tsignal-trading",
                    "repo": "D:/APPS/Tsignal 5.0",
                    "path_glob": "tsignal/trading/**",
                    "class": "operator-only",
                    "owner": "Tsignal operator",
                    "reason": "broker/order path modules",
                    "rollback_expectation": "remove generated ACL delta only",
                },
            ],
        }

        with self.assertRaises(ValueError) as caught:
            manifest.validate_manifest(data, source=Path("manifest.json"))

        self.assertIn("class must be one of", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
