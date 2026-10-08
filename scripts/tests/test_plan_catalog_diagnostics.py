"""Temporary-root catalog controls. No installed/global catalog is touched.

The timeout control uses one real native interpreter child (not a provider).
Root must admit that bounded descendant as part of local qualification.
"""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import plan_catalog as catalog
import plan_context_updater as updater
from _catalog_common import parse_yaml_block


class CatalogDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.plans = self.base / "repo/design/plans"
        self.plans.mkdir(parents=True)

    def plan(self, name, text):
        path = self.plans / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def parse_counted(self, path):
        original = Path.read_text
        reads = []

        def observed(target, *args, **kwargs):
            if target == path:
                reads.append(kwargs.copy())
            return original(target, *args, **kwargs)

        with mock.patch.object(Path, "read_text", observed):
            entry = catalog.parse_plan_frontmatter(path)
        return entry, reads

    def test_actual_source_origin(self):
        self.assertEqual(Path(catalog.__file__).resolve(), SCRIPTS / "plan_catalog.py")
        self.assertEqual(Path(updater.__file__).resolve(), SCRIPTS / "plan_context_updater.py")

    def test_joint_body_fallback_reads_once(self):
        path = self.plan("untitled.md", "# **Actual** [Plan](x)\n**Date**: 2026-10-02\n")
        entry, reads = self.parse_counted(path)
        self.assertEqual(entry["title"], "Actual Plan")
        self.assertEqual(entry["date"], "2026-10-02")
        self.assertFalse(entry["has_frontmatter"])
        self.assertEqual(reads, [{"encoding": "utf-8-sig", "errors": "replace"}])

    def test_complete_metadata_does_not_read_fallback_body(self):
        path = self.plan("2026-09-01_other.md", "---\ntitle: Header\ndate: 2026-10-01\nstatus: draft\n---\n# Ignored\n**Date**: 2026-08-01\n")
        entry, reads = self.parse_counted(path)
        self.assertEqual((entry["title"], entry["date"], entry["status"]), ("Header", "2026-10-01", "draft"))
        self.assertEqual(reads, [])

    def test_filename_before_body_date_and_single_missing_fallback(self):
        path = self.plan("2026-09-03_missing.md", "# Body title\n**Date**: 2026-01-01\n")
        entry, reads = self.parse_counted(path)
        self.assertEqual((entry["title"], entry["date"]), ("Body title", "2026-09-03"))
        self.assertEqual(len(reads), 1)
        path = self.plan("header-title.md", "---\ntitle: Header\n---\n**Date**: 2026-09-04\n")
        entry, reads = self.parse_counted(path)
        self.assertEqual((entry["title"], entry["date"]), ("Header", "2026-09-04"))
        self.assertEqual(len(reads), 1)

    def test_empty_fallback_preserves_slug_and_mtime(self):
        path = self.plan("Empty Plan.md", "plain text\n")
        os.utime(path, (1700000000, 1700000000))
        entry, reads = self.parse_counted(path)
        self.assertEqual(entry["title"], "empty-plan")
        self.assertEqual(entry["date"], catalog.datetime.fromtimestamp(1700000000).strftime("%Y-%m-%d"))
        self.assertEqual(len(reads), 1)

    def test_bom_crlf_and_invalid_utf8_keep_strict_header(self):
        path = self.plans / "bom.md"
        path.write_bytes(b"\xef\xbb\xbf---\r\ntitle: Header\r\ndate: 2026-10-03\r\n---\r\n# Body\r\n")
        entry, reads = self.parse_counted(path)
        self.assertEqual((entry["title"], entry["date"]), ("Header", "2026-10-03"))
        self.assertTrue(entry["has_frontmatter"])
        self.assertEqual(reads, [])
        path = self.plans / "invalid.md"
        path.write_bytes(b"---\ntitle: Bad\xff\n---\n# Actual body\n**Date**: 2026-10-04\n")
        with self.assertLogs(level="WARNING") as logs:
            entry, reads = self.parse_counted(path)
        self.assertFalse(entry["has_frontmatter"])
        self.assertEqual((entry["title"], entry["date"]), ("Actual body", "2026-10-04"))
        self.assertEqual(len(reads), 1)
        self.assertTrue(any("encoding error" in line for line in logs.output))

    def test_exact_header_bound_and_invalid_status_warning(self):
        for count in (100, 101):
            with self.subTest(content_lines=count):
                path = self.plan(f"bound{count}.md", "---\n" + "title: Header\n" + "unused: x\n" * (count - 1) + "---\n# Body\n")
                if count == 100:
                    self.assertEqual(parse_yaml_block(path)["title"], "Header")
                else:
                    with self.assertLogs(level="WARNING") as logs:
                        self.assertEqual(parse_yaml_block(path), {})
                    self.assertTrue(any("100 content lines" in line for line in logs.output))
        path = self.plan("2026-10-01_status.md", "---\ntitle: Header\nstatus: impossible\n---\n")
        with self.assertLogs(level="WARNING") as logs:
            entry = catalog.parse_plan_frontmatter(path)
        self.assertEqual(entry["status"], "unknown")
        self.assertTrue(any("invalid status" in line for line in logs.output))

    def test_real_recursive_discovery_exclusions_and_phase_counts(self):
        self.plan("2026-10-01_top.md", "---\ntitle: Top\nstatus: draft\n---\n")
        nested = self.plans / "nested"
        nested.mkdir()
        (nested / "2026-10-02_child.md").write_text("# Child\n", encoding="utf-8")
        ignored = self.plans / "node_modules"
        ignored.mkdir()
        (ignored / "ignored.md").write_text("# Excluded\n", encoding="utf-8")
        audit = self.base / "other/design/audits/deep"
        audit.mkdir(parents=True)
        (audit / "2026-10-03_report.md").write_text("# Audit\n", encoding="utf-8")
        stderr = io.StringIO()
        with mock.patch.object(catalog, "BASE", str(self.base)), contextlib.redirect_stderr(stderr):
            content = catalog.generate()
        self.assertIn("2 plans, 1 audits across 2 repos", content)
        self.assertIn("[Top]", content)
        self.assertIn("[Child]", content)
        self.assertIn("[Audit]", content)
        self.assertNotIn("Excluded", content)
        for phase in ("discovery_start", "discovery_done", "walk_start", "walk_done", "parse_start", "parse_done", "render_start", "render_done"):
            self.assertIn("phase=" + phase, stderr.getvalue())
        self.assertIn("files=3", stderr.getvalue())
        self.assertIn("scanned=3 entries=3 warnings=0", stderr.getvalue())
        self.assertNotIn("wrote ", stderr.getvalue())

    def test_parallel_scan_preserves_order_and_continues_after_disappeared_file(self):
        for index in range(275):
            self.plan(f"2026-10-01_{index:03}.md", f"# Plan {index:03}\n")
        paths = catalog.walk_repos(catalog.discover_repos(str(self.base)))
        vanished = paths[130]
        original_walk = catalog.walk_repos

        def disappear(repos):
            found = original_walk(repos)
            vanished.unlink()
            return found

        stderr = io.StringIO()
        with mock.patch.object(catalog, "BASE", str(self.base)), mock.patch.object(catalog, "walk_repos", disappear), contextlib.redirect_stderr(stderr), self.assertLogs(level="WARNING") as logs:
            content = catalog.generate()
        self.assertIn("274 plans, 0 audits across 1 repos", content)
        expected_titles = ["[Plan " + path.stem.rsplit("_", 1)[1] + "]" for path in paths if path != vanished]
        positions = [content.index(title) for title in expected_titles]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("[Plan " + vanished.stem.rsplit("_", 1)[1] + "]", content)
        self.assertEqual(sum("skipping" in line for line in logs.output), 1)
        self.assertIn("scanned=275 entries=274 warnings=1", stderr.getvalue())

    def test_publication_failure_preserves_last_valid_and_never_claims_wrote(self):
        output = self.base / "PLANS.md"
        output.write_text("last valid", encoding="utf-8")
        stderr = io.StringIO()
        with mock.patch.object(catalog.os, "replace", side_effect=OSError("owned replacement fault")), contextlib.redirect_stderr(stderr):
            with self.assertRaisesRegex(OSError, "owned replacement fault"):
                catalog.write_output(output, "new catalog")
        self.assertEqual(output.read_text(encoding="utf-8"), "last valid")
        self.assertIn("publication_start", stderr.getvalue())
        self.assertNotIn("publication_done", stderr.getvalue())
        self.assertNotIn("wrote ", stderr.getvalue())
        real_replace = os.replace
        observed = []

        def replace(source, target):
            observed.append(stderr.getvalue())
            return real_replace(source, target)

        stderr = io.StringIO()
        with mock.patch.object(catalog.os, "replace", replace), contextlib.redirect_stderr(stderr):
            catalog.write_output(output, "new catalog")
        self.assertEqual(output.read_text(encoding="utf-8"), "new catalog")
        self.assertEqual(len(observed), 1)
        self.assertNotIn("wrote ", observed[0])
        self.assertIn("publication_done", stderr.getvalue())
        self.assertIn("wrote ", stderr.getvalue())

    def test_real_timeout_retains_partial_streams_and_outer_best_effort(self):
        scripts = self.base / "scripts"
        scripts.mkdir()
        (scripts / "plan_catalog.py").write_text(
            "import sys,time\nprint('owned stdout partial',flush=True)\nprint('phase=parse_start owned stderr partial',file=sys.stderr,flush=True)\ntime.sleep(10)\n", encoding="utf-8")
        (scripts / "vision_catalog.py").write_text("print('owned vision complete',flush=True)\n", encoding="utf-8")
        plan = self.plan("2026-10-01_run.md", "# Actual plan\n")
        real_run = updater.subprocess.run
        calls = []

        def bounded_native(argv, **kwargs):
            self.assertEqual(argv[0], "python")
            self.assertEqual(kwargs["timeout"], 60)
            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["text"])
            calls.append(Path(argv[1]).name)
            # Test-only deadline/interpreter leaf: genuine run/TimeoutExpired,
            # exact production argv/deadline checked above. Native child only,
            # so subprocess.run's kill+wait owns the timed-out process itself.
            return real_run([sys._base_executable, "-B", argv[1]], capture_output=True,
                            text=True, timeout=1, shell=False)

        stdout = io.StringIO()
        with mock.patch.object(updater, "SCRIPTS", scripts), mock.patch.object(updater.subprocess, "run", bounded_native), mock.patch.object(sys, "argv", ["plan_context_updater.py", "--plan", str(plan)]), contextlib.redirect_stdout(stdout):
            result = updater.main()
        self.assertEqual(result, 0)
        self.assertEqual(calls, ["plan_catalog.py", "vision_catalog.py"])
        self.assertIn("PLANS.md regen: FAIL", stdout.getvalue())
        self.assertIn("owned stdout partial", stdout.getvalue())
        self.assertIn("phase=parse_start owned stderr partial", stdout.getvalue())
        self.assertIn("VISIONS.md regen: OK", stdout.getvalue())
        self.assertIn("plan has no `vision:` frontmatter", stdout.getvalue())

    def test_timeout_diagnostic_tail_handles_bytes_and_is_bounded(self):
        details = updater._catalog_diagnostics(b"x" * 10000 + b"LASTOUT", "y" * 10000 + "LASTERR")
        self.assertIn("LASTOUT", details)
        self.assertIn("LASTERR", details)
        self.assertLess(len(details), 4300)


if __name__ == "__main__":
    unittest.main()
