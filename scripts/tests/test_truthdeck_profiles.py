from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_profiles import RegistryError, apply_narrowing, load_registry, resolve_profile  # noqa: E402


class ProfileTests(unittest.TestCase):
    def test_shipped_registry_is_valid_and_tsignal_has_dod_deck_probe(self) -> None:
        registry, digest = load_registry(ROOT / "templates" / "truthdeck.registry.json.template")
        self.assertEqual(len(digest), 64)
        self.assertEqual(registry["profiles"]["tsignal-5.0"]["runtime_probe_ids"], ["tsignal.dod_deck.v1"])

    def test_user_registry_cannot_add_argv_or_unknown_probe(self) -> None:
        raw = json.loads((ROOT / "templates" / "truthdeck.registry.json.template").read_text(encoding="utf-8"))
        raw["profiles"]["generic"]["runtime_probe_ids"] = ["evil.argv"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(RegistryError):
                load_registry(path)

    def test_repo_policy_cannot_widen_collectors(self) -> None:
        profile = {"collectors": ["git"], "runtime_probe_ids": [], "required_stages": ["planned"]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".truthdeck-policy.json"
            path.write_text('{"collectors":["git","runtime"]}', encoding="utf-8")
            with self.assertRaises(RegistryError):
                apply_narrowing(profile, path)

    def test_explicit_runtime_profile_is_bound_to_canonical_repo(self) -> None:
        registry, _ = load_registry(ROOT / "templates" / "truthdeck.registry.json.template")
        with self.assertRaises(RegistryError):
            resolve_profile(registry, ROOT, "tsu", "attacker/repo")

    def test_task_alias_paths_and_hash_are_strict(self) -> None:
        raw = json.loads((ROOT / "templates" / "truthdeck.registry.json.template").read_text(encoding="utf-8"))
        raw["task_aliases"]["bad"] = {"repos": ["relative/repo"]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(RegistryError):
                load_registry(path)


if __name__ == "__main__":
    unittest.main()
