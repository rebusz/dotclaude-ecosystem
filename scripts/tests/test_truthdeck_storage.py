from __future__ import annotations

import concurrent.futures
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from test_truthdeck_model import TruthDeckModelTests  # noqa: E402
from truthdeck_storage import read_latest, store_snapshot  # noqa: E402


class TruthDeckStorageTests(unittest.TestCase):
    def test_concurrent_identical_writers_keep_artifacts_and_valid_pointer(self) -> None:
        snapshot = TruthDeckModelTests().build()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: store_snapshot(snapshot, root=root), range(2)))
            self.assertNotEqual(results[0][0], results[1][0])
            self.assertTrue(all(path.exists() for path, _ in results))
            loaded, target = read_latest(root=root, scope_repos=("repo",))
            self.assertEqual(loaded.snapshot_id, snapshot.snapshot_id)
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
