from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_runtime import collect_runtime  # noqa: E402


class RuntimeTests(unittest.TestCase):
    def test_applicable_profile_without_safe_probe_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_runtime(Path(tmp), probe_id=None, observed_at_utc="2026-07-22T12:00:00Z",
                                     deadline=time.monotonic() + 1, repo_id="tsignal", runtime_applicable=True)
        facts = {x.key: x for x in result.facts}
        self.assertTrue(facts["runtime.applicable"].value)
        self.assertEqual(facts["runtime.ready"].state.value, "unavailable")


if __name__ == "__main__":
    unittest.main()
