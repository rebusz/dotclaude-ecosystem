from __future__ import annotations

import unittest
from pathlib import Path

import write_segregation_manifest as manifest


class TestWriteSegregationManifest(unittest.TestCase):
    def _valid_manifest(self):
        return {
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
                    "path_glob": "tsignal/{runtime,interlock}/**",
                    "class": "operator-only",
                    "owner": "Tsignal operator",
                    "reason": "broker/order path modules",
                    "rollback_expectation": "remove generated ACL delta only",
                },
                {
                    "id": "tsu-design-docs",
                    "repo": "D:/APPS/TSU",
                    "path_glob": "design/**",
                    "class": "write-allowed-for-agents",
                    "owner": "TSU planning workflow",
                    "reason": "docs are safe write targets",
                    "rollback_expectation": "preserve normal repo write behavior",
                },
            ],
        }

    def test_validate_manifest_accepts_required_shape(self):
        data = self._valid_manifest()

        summary = manifest.validate_manifest(data, source=Path("manifest.json"))

        self.assertEqual(summary["entry_count"], 3)
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

    def test_build_acl_dry_run_plan_requires_identity(self):
        with self.assertRaises(ValueError) as caught:
            manifest.build_acl_dry_run_plan(
                self._valid_manifest(),
                source=Path("manifest.json"),
                agent_identity=" ",
            )

        self.assertIn("--agent-identity must be non-empty", str(caught.exception))

    def test_build_acl_dry_run_plan_never_applies_acl_and_expands_braces(self):
        plan = manifest.build_acl_dry_run_plan(
            self._valid_manifest(),
            source=Path("manifest.json"),
            agent_identity="LOCAL\\CodexAgent",
        )

        self.assertFalse(plan["applies_acl"])
        self.assertTrue(plan["requires_operator_go_before_apply"])
        trading = next(entry for entry in plan["entries"] if entry["id"] == "tsignal-trading")
        self.assertEqual(len(trading["expanded_targets"]), 2)
        self.assertIn(
            'icacls "D:\\APPS\\Tsignal 5.0\\tsignal\\runtime" /deny "LOCAL\\CodexAgent:(W)" /T',
            trading["apply_commands"],
        )
        self.assertIn(
            'icacls "D:\\APPS\\Tsignal 5.0\\tsignal\\interlock" /remove:d "LOCAL\\CodexAgent" /T',
            trading["rollback_commands"],
        )
        docs = next(entry for entry in plan["entries"] if entry["id"] == "tsu-design-docs")
        self.assertTrue(docs["no_op"])
        self.assertEqual(docs["apply_commands"], [])


if __name__ == "__main__":
    unittest.main()
