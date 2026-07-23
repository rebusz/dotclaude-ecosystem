from __future__ import annotations

import hashlib
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_profiles import ProbeSpec  # noqa: E402
from truthdeck_runtime import PROBES, collect_runtime  # noqa: E402


class RuntimeTests(unittest.TestCase):
    def test_applicable_profile_without_safe_probe_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_runtime(Path(tmp), probe_ids=(), observed_at_utc="2026-07-22T12:00:00Z",
                                     deadline=time.monotonic() + 1, repo_id="tsignal", runtime_applicable=True)
        facts = {x.key: x for x in result.facts}
        self.assertTrue(facts["runtime.applicable"].value)
        self.assertEqual(facts["runtime.ready"].state.value, "unavailable")

    def test_all_registered_probes_contribute_and_build_is_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            specs = {}
            for index in (1, 2):
                tool = repo / f"probe{index}.py"
                raw = {"schema_version": f"probe.v{index}", "status": "ready", "build": "abc"}
                tool.write_text(f"import json\nprint(json.dumps({raw!r}))\n", encoding="utf-8")
                specs[f"probe.{index}"] = ProbeSpec(
                    f"probe.{index}", (sys.executable, f"{{repo}}/{tool.name}"), f"probe.v{index}",
                    True, ("status",), ("ready",), build_path=("build",),
                    allowed_repo_ids=("local/test",), tool_sha256=hashlib.sha256(tool.read_bytes()).hexdigest(),
                )
            with mock.patch.dict(PROBES, specs, clear=True):
                result = collect_runtime(repo, probe_ids=("probe.2", "probe.1"),
                                         observed_at_utc="2026-07-22T12:00:00Z",
                                         deadline=time.monotonic() + 5, repo_id="local/test",
                                         runtime_applicable=True, expected_build="abc")
            values = {fact.key: fact.value for fact in result.facts}
            self.assertTrue(values["runtime.ready"])
            self.assertEqual(values["runtime.sample_count"], 2)
            self.assertEqual(values["runtime.build"], "abc")


if __name__ == "__main__":
    unittest.main()
