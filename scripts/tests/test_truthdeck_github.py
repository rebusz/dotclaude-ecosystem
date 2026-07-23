from __future__ import annotations

import unittest

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_github import _check_passed, _required_checks_pass  # noqa: E402


class GithubCollectorTests(unittest.TestCase):
    def test_empty_or_unknown_check_never_passes(self) -> None:
        self.assertFalse(_check_passed({}))
        self.assertTrue(_check_passed({"conclusion": "SUCCESS"}))
        self.assertTrue(_check_passed({"conclusion": "SKIPPED"}))
        self.assertFalse(_check_passed({"conclusion": "FAILURE"}))

    def test_only_named_required_checks_can_pass_ci(self) -> None:
        checks = [{"name": "unrelated", "conclusion": "SUCCESS"}]
        self.assertFalse(_required_checks_pass(checks, ("truthdeck",)))
        checks.append({"name": "truthdeck", "conclusion": "SUCCESS"})
        self.assertTrue(_required_checks_pass(checks, ("truthdeck",)))


if __name__ == "__main__":
    unittest.main()
