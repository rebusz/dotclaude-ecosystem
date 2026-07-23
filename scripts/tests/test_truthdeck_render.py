from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from test_truthdeck_model import TruthDeckModelTests  # noqa: E402
from truthdeck_render import MAX_MARKDOWN, render_diff, render_snapshot  # noqa: E402


class TruthDeckRenderTests(unittest.TestCase):
    def test_render_is_bounded_and_diff_is_deterministic(self) -> None:
        snapshot = TruthDeckModelTests().build()
        self.assertLessEqual(len(render_snapshot(snapshot)), MAX_MARKDOWN)
        self.assertIn("none", render_diff(snapshot, snapshot))


if __name__ == "__main__":
    unittest.main()
