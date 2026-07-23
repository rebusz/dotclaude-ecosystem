from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import sync_ci_policy  # noqa: E402
from ci_model import ContractError, build_preflight, validate_adapter  # noqa: E402
from ci_model import preflight as preflight_cli  # noqa: E402


def adapter(*, candidate_mode: str = "selected") -> dict:
    return {
        "schema_version": "ci_model_adapter_v1",
        "repository": "owner/repo",
        "owners": ["platform"],
        "shared_contract": {"min": "1.0", "max": "1.0"},
        "commands": {
            "t0": "python -m ruff check .",
            "local": "python -m pytest -q tests/test_ci_policy.py",
            "ci": 'python -m pytest -q -m "not integration"',
            "collect": "python -m pytest --collect-only -q",
        },
        "artifact_root": "scratch/ci",
        "platforms": {
            "os": ["ubuntu", "windows"],
            "python": ["3.12"],
            "node": [],
            "runtime": ["github-hosted"],
        },
        "critical_rules": [
            {
                "id": "docs",
                "class": "t0-only",
                "escalation": "focused",
                "patterns": ["docs/**"],
                "tests": [],
            },
            {
                "id": "production",
                "class": "production",
                "escalation": "focused",
                "patterns": ["src/**"],
                "tests": ["tests/test_core.py"],
            },
            {
                "id": "workflow",
                "class": "test-infrastructure",
                "escalation": "full",
                "patterns": [".github/**"],
                "tests": ["tests/test_ci_policy.py"],
            },
        ],
        "mandatory_bundles": {
            "R0": [],
            "R1": ["ci"],
            "R2": ["ci"],
            "R3": ["ci", "safety"],
        },
        "bundles": {
            "ci": ["tests/test_ci_policy.py"],
            "safety": ["tests/test_safety.py"],
        },
        "risk_to_tiers": {
            "R0": ["T0"],
            "R1": ["T0", "T1", "T3"],
            "R2": ["T0", "T1", "T2", "T3", "T4"],
            "R3": ["T0", "T1", "T2", "T3", "T4"],
        },
        "exact_base_ttl_seconds": 86400,
        "scheduled_full_health": {
            "schedule_utc": "17 10 * * *",
            "command": 'python -m pytest -q -m "not integration"',
        },
        "dependency_pins": {"requirements.txt": "sha256:fixture"},
        "required_check": "pytest (Python 3.12, ubuntu)",
        "candidate_mode": candidate_mode,
        "activation": {
            "verdict": "PASS" if candidate_mode == "selected" else "HOLD",
            "evidence_sha256": "e" * 64,
            "reviewed_head_sha": "f" * 40,
        },
        "cost": {
            "rate": 0.006,
            "currency": "USD",
            "source": "https://docs.github.com/billing",
            "effective_date": "2026-07-22",
        },
        "rollback_to_full": "python tools/set_ci_mode.py full",
    }


def change(path: str = "src/core.py", status: str = "M") -> dict:
    return {"path": path, "status": status, "sha256": "a" * 64}


class AdapterTests(unittest.TestCase):
    def test_valid_adapter_is_hash_bound(self) -> None:
        self.assertRegex(validate_adapter(adapter()), r"^[0-9a-f]{64}$")

    def test_unsupported_shared_major_fails_closed(self) -> None:
        value = adapter()
        value["shared_contract"] = {"min": "2.0", "max": "2.0"}
        with self.assertRaisesRegex(ContractError, "unsupported shared contract major"):
            validate_adapter(value)

    def test_selected_mode_requires_pass_evidence(self) -> None:
        value = adapter()
        value["activation"]["verdict"] = "HOLD"
        with self.assertRaisesRegex(ContractError, "requires PASS activation"):
            validate_adapter(value)

    def test_unknown_surface_and_full_mode_cannot_select_narrowly(self) -> None:
        result = build_preflight(
            adapter=adapter(),
            changes=[change("new-area/core.py")],
            risk_class="R2",
            base_sha="1" * 40,
            head_sha="2" * 40,
            graph_status="fresh",
        )
        self.assertEqual(result["escalation"], "full")
        self.assertEqual(result["unknown_surfaces"], ["new-area/core.py"])

        full = build_preflight(
            adapter=adapter(candidate_mode="full"),
            changes=[change()],
            risk_class="R2",
            base_sha="1" * 40,
            head_sha="2" * 40,
            graph_status="fresh",
        )
        self.assertEqual(full["escalation"], "full")
        self.assertEqual(full["command"], full_adapter_ci_command())

    def test_missing_graph_widens_without_removing_rule_tests(self) -> None:
        result = build_preflight(
            adapter=adapter(),
            changes=[change()],
            risk_class="R1",
            base_sha="1" * 40,
            head_sha="2" * 40,
            graph_status="missing",
        )
        self.assertEqual(result["escalation"], "wide")
        self.assertEqual(result["command"], full_adapter_ci_command())
        nodeids = [item["nodeid"] for item in result["selected_tests"]]
        self.assertEqual(nodeids, ["tests/test_ci_policy.py", "tests/test_core.py"])

    def test_docs_only_diff_uses_t0_without_test_basket(self) -> None:
        result = build_preflight(
            adapter=adapter(),
            changes=[change("docs/runbook.md")],
            risk_class="R3",
            base_sha="1" * 40,
            head_sha="2" * 40,
            graph_status="missing",
        )
        self.assertTrue(result["t0_only"])
        self.assertEqual(result["selected_tests"], [])
        self.assertEqual(result["command"], "python -m ruff check .")


def full_adapter_ci_command() -> str:
    return 'python -m pytest -q -m "not integration"'


class SyncTests(unittest.TestCase):
    def _git(self, repo: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return completed.stdout.strip()

    def test_explicit_sync_is_idempotent_and_never_edits_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            self._git(repo, "init")
            self._git(
                repo, "remote", "add", "origin", "https://github.com/owner/repo.git"
            )
            adapter_path = repo / ".ci/ci-model.json"
            adapter_path.parent.mkdir()
            adapter_path.write_text(json.dumps(adapter()), encoding="utf-8")

            drift = sync_ci_policy.sync_repo(
                repo, adapter_path, write=False, show_diff=False
            )
            self.assertIn(".ci/_shared/ci_model/policy.py", drift)
            self.assertFalse((repo / ".ci/_shared").exists())
            sync_ci_policy.sync_repo(repo, adapter_path, write=True, show_diff=False)
            self.assertEqual(
                sync_ci_policy.sync_repo(
                    repo, adapter_path, write=False, show_diff=False
                ),
                [],
            )
            self.assertFalse((repo / ".github/workflows").exists())

    def test_remote_identity_mismatch_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            self._git(repo, "init")
            self._git(
                repo, "remote", "add", "origin", "https://github.com/wrong/repo.git"
            )
            adapter_path = repo / ".ci/ci-model.json"
            adapter_path.parent.mkdir()
            value = copy.deepcopy(adapter())
            adapter_path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(ContractError, "does not match origin"):
                sync_ci_policy.sync_repo(
                    repo, adapter_path, write=True, show_diff=False
                )
            self.assertFalse((repo / ".ci/_shared").exists())


class PreflightCliTests(unittest.TestCase):
    def test_output_is_restricted_to_adapter_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            (repo / ".ci").mkdir()
            (repo / ".ci/ci-model.json").write_text(
                json.dumps(adapter()), encoding="utf-8"
            )
            (repo / ".ci/changes.json").write_text(
                json.dumps([change()]), encoding="utf-8"
            )
            common = [
                "--repo",
                str(repo),
                "--adapter",
                ".ci/ci-model.json",
                "--changes",
                ".ci/changes.json",
                "--risk",
                "R2",
                "--base",
                "1" * 40,
                "--head",
                "2" * 40,
                "--graph-status",
                "missing",
            ]

            self.assertEqual(
                preflight_cli.run([*common, "--json-out", "preflight.json"]), 10
            )
            self.assertFalse((repo / "preflight.json").exists())
            self.assertEqual(
                preflight_cli.run([*common, "--json-out", "scratch/ci/preflight.json"]),
                0,
            )
            self.assertTrue((repo / "scratch/ci/preflight.json").exists())


if __name__ == "__main__":
    unittest.main()
