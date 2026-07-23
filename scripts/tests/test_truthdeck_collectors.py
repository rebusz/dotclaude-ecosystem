from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_collectors import (  # noqa: E402
    CollectorOutputLimit, CollectorTimeout, Policy, collect_concurrently, run_bounded,
)
from truthdeck_model import CollectorRun  # noqa: E402
from truthdeck_collectors import CollectorResult  # noqa: E402


class CollectorTests(unittest.TestCase):
    def test_bounded_command_never_uses_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_bounded((sys.executable, "-c", "print('ok')"), cwd=Path(tmp), deadline=time.monotonic() + 2)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_timeout_terminates_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(CollectorTimeout):
            run_bounded((sys.executable, "-c", "import time; time.sleep(5)"), cwd=Path(tmp), deadline=time.monotonic() + 0.05)

    def test_timeout_terminates_descendant_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "orphan.txt"
            child_code = (
                "import pathlib,time; time.sleep(0.8); "
                f"pathlib.Path({str(marker)!r}).write_text('orphan', encoding='utf-8')"
            )
            parent_code = (
                "import subprocess,sys,time; "
                f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(5)"
            )
            with self.assertRaises(CollectorTimeout):
                run_bounded((sys.executable, "-c", parent_code), cwd=Path(tmp),
                            deadline=time.monotonic() + 0.1)
            time.sleep(1.0)
            self.assertFalse(marker.exists(), "timed-out collector left a live descendant")

    def test_output_limit_terminates_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(CollectorOutputLimit):
            run_bounded((sys.executable, "-c", "print('x'*10000)"), cwd=Path(tmp), deadline=time.monotonic() + 2, max_output_bytes=100)

    def test_concurrent_results_are_sorted(self) -> None:
        def make(name, delay):
            def collect(deadline):
                time.sleep(delay)
                return CollectorResult(name, (), CollectorRun(name, "1", 1))
            return collect
        results = collect_concurrently({"z": make("z", 0), "a": make("a", 0.02)}, policy=Policy(total_deadline_s=1))
        self.assertEqual([x.collector_id for x in results], ["a", "z"])

    def test_timeout_preserves_healthy_result_without_waiting_for_late_worker(self) -> None:
        def healthy(deadline):
            return CollectorResult("git", (), CollectorRun("git", "1", 1))

        def ignores_deadline(deadline):
            time.sleep(0.35)
            return CollectorResult("runtime", (), CollectorRun("runtime", "1", 350))

        started = time.monotonic()
        results = collect_concurrently({"git": healthy, "runtime": ignores_deadline},
                                       policy=Policy(total_deadline_s=0.05))
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(results[0].collector_id, "git")
        timeout = next(x for x in results if x.collector_id == "runtime")
        self.assertTrue(timeout.run.timed_out)


if __name__ == "__main__":
    unittest.main()
