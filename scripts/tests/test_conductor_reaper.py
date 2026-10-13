"""Process policy tests: all tables, process handles and actuation are fake."""

from copy import deepcopy
import ctypes
import json
import os
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import conductor_reaper as reaper


NOW = 2000.0
CONTEXT = dict(owner_id="owner-a", session_id=3, username="DESKTOP\\dawid", now=NOW, controller_pid=90)


def process(pid=20, **updates):
    row = dict(pid=pid, start_time=1000.0, parent_pid=10, session_id=3,
               username="DESKTOP\\dawid", command_sha256=reaper.command_sha256(["python", "-m", "pytest"]),
               rss_bytes=2 * reaper.GIB, name="python.exe", protected_reason=None, inspection_error=None)
    row.update(updates)
    return row


def record(**updates):
    row = dict(lane_id="lane-a", owner_id="owner-a", owner_pid=10, owner_start_time=900.0,
               owner_session_id=3, owner_username="DESKTOP\\dawid", pid=20, start_time=1000.0,
               parent_pid=10, session_id=3, username="DESKTOP\\dawid", worktree="D:/work/owned",
               command_sha256=reaper.command_sha256(["python", "-m", "pytest"]), state="TERMINAL",
               deadline=1900.0, heartbeat=1800.0, request_id=None, request_state=None,
               launch_provenance="conductor", launch_origin="interactive")
    row.update(updates)
    return row


def table(*rows, complete=True):
    return reaper.ProcessTable([process(90, parent_pid=0), *rows], complete=complete)


def report_for(rec=None, proc=None, **context):
    return reaper.build_report([record() if rec is None else rec], table(process() if proc is None else proc),
                               **(CONTEXT | context))


def target(report, pid=20):
    return next(row for row in report["rows"] if row["pid"] == pid)


class ClassificationTests(unittest.TestCase):
    def test_terminal_and_expired_lanes_require_dead_owner(self):
        for rec in (record(), record(state="RUNNING", deadline=NOW - 1)):
            with self.subTest(state=rec["state"]):
                result = target(report_for(rec))
                self.assertEqual(result["action"], "WOULD_KILL")
                self.assertEqual(result["rss_gib"], 2.0)
        self.assertEqual(target(report_for(record(state="RUNNING", deadline=NOW + 1)))["reason"], "LANE_NOT_STALE")

    def test_owner_alive_inaccessible_and_reused(self):
        scenarios = [
            (process(10, start_time=900.0), "OWNER_STILL_ALIVE"),
            (process(10, start_time=900.0, inspection_error="AccessDenied"), "OWNER_LIVENESS_UNKNOWN"),
            (process(10, start_time=800.0), "OWNER_IDENTITY_CONFLICT"),
            (process(10, start_time=1500.0), "TERMINAL_LANE_OWNER_GONE"),
        ]
        for owner, reason in scenarios:
            with self.subTest(reason=reason):
                result = reaper.build_report([record()], table(process(), owner), **CONTEXT)
                self.assertEqual(target(result)["reason"], reason)

    def test_incomplete_or_plain_table_cannot_prove_owner_absence(self):
        for snapshot in (table(process(), complete=False), list(table(process()))):
            with self.subTest(type=type(snapshot).__name__):
                result = reaper.build_report([record()], snapshot, **CONTEXT)
                self.assertEqual(target(result)["reason"], "PROCESS_TABLE_INCOMPLETE")

    def test_pid_reuse_and_command_change_are_kept(self):
        for update, reason in [
            ({"start_time": 1001.0}, "PID_REUSED"),
            ({"command_sha256": "a" * 64}, "COMMAND_IDENTITY_MISMATCH"),
            ({"parent_pid": 11}, "PARENT_IDENTITY_MISMATCH"),
        ]:
            with self.subTest(reason=reason):
                self.assertEqual(target(report_for(proc=process(**update)))["reason"], reason)

    def test_no_registry_and_no_positive_launch_provenance(self):
        result = reaper.build_report([], table(process()), **CONTEXT)
        self.assertEqual(target(result)["reason"], "UNREGISTERED")
        for update in ({"launch_origin": "unknown"}, {"launch_origin": "scheduled"}, {"launch_provenance": None}):
            with self.subTest(update=update):
                self.assertEqual(target(report_for(record(**update)))["reason"], "LAUNCH_PROVENANCE_UNKNOWN")

    def test_other_owner_session_and_user(self):
        for rec, proc in [
            (record(owner_id="owner-b"), process()),
            (record(), process(session_id=4)),
            (record(), process(username="OTHER\\user")),
            (record(owner_session_id=4), process()),
            (record(session_id=4), process()),
            (record(owner_username="OTHER\\user"), process()),
        ]:
            with self.subTest(rec=rec["owner_id"], session=proc["session_id"]):
                self.assertEqual(target(report_for(rec, proc))["action"], "KEEP")

    def test_uncertain_attempts_and_missing_request_state_are_kept(self):
        for update in (
            {"state": "RECOVERY_REQUIRED"}, {"state": "STARTING"},
            {"request_state": "SUBMIT_UNCONFIRMED"}, {"request_state": "RECOVERY_REQUIRED"},
            {"state": "UNKNOWN"}, {"request_id": "request-without-state"},
        ):
            with self.subTest(update=update):
                self.assertEqual(target(report_for(record(**update)))["action"], "KEEP")

    def test_missing_or_invalid_metadata_are_kept(self):
        for field in ("start_time", "parent_pid", "session_id", "username", "command_sha256", "rss_bytes", "name"):
            with self.subTest(field=field):
                self.assertEqual(target(report_for(proc=process(**{field: None})))["action"], "KEEP")
        for update in ({"inspection_error": "AccessDenied"}, {"rss_bytes": -1}, {"start_time": float("nan")}):
            with self.subTest(update=update):
                self.assertEqual(target(report_for(proc=process(**update)))["action"], "KEEP")
        for update in ({"heartbeat": None}, {"deadline": None}, {"heartbeat": NOW + 1}, {"owner_start_time": None}, {"worktree": ""}):
            with self.subTest(update=update):
                self.assertEqual(target(report_for(record(**update)))["action"], "KEEP")

    def test_system_session_zero_and_controller_ancestors(self):
        for update in ({"session_id": 0}, {"username": "NT AUTHORITY\\SYSTEM"}, {"username": "root"}):
            with self.subTest(update=update):
                self.assertEqual(target(report_for(proc=process(**update)))["reason"], "SYSTEM_OR_SESSION_ZERO")
        snapshot = reaper.ProcessTable([process(90, parent_pid=20), process()], complete=True)
        result = reaper.build_report([record()], snapshot, **CONTEXT)
        self.assertEqual(target(result)["reason"], "CONTROLLER_OR_ANCESTOR")

    def test_missing_controller_cannot_prove_protected_ancestors(self):
        result = reaper.build_report([record()], reaper.ProcessTable([process()], complete=True), **CONTEXT)
        self.assertEqual(target(result)["reason"], "CONTROLLER_ANCESTRY_UNKNOWN")

    def test_controller_ancestry_gaps_reuse_and_cycles_are_unknown(self):
        for controller, ancestor in (
            (process(90, parent_pid=80), process(70, parent_pid=0)),
            (process(90, parent_pid=80), process(80, parent_pid=0, start_time=1100.0)),
            (process(90, parent_pid=80), process(80, parent_pid=90)),
            (process(90, parent_pid=80), process(80, parent_pid=0, inspection_error="AccessDenied")),
        ):
            with self.subTest(ancestor=ancestor):
                snapshot = reaper.ProcessTable([controller, ancestor, process()], complete=True)
                result = reaper.build_report([record()], snapshot, **CONTEXT)
                self.assertEqual(target(result)["reason"], "CONTROLLER_ANCESTRY_UNKNOWN")

    def test_inconsistent_registry_clocks_are_kept(self):
        for update in ({"heartbeat": 999.0}, {"deadline": 999.0}, {"owner_start_time": 1001.0}):
            with self.subTest(update=update):
                self.assertEqual(target(report_for(record(**update)))["reason"], "REGISTRY_CLOCK_UNKNOWN")

    def test_hard_denylist_and_protected_worktree(self):
        protected = ["TSIGNAL_BOT.py", "live-bot.py", "TWS.exe", "IBGateway.exe", "ib", "CCTV_supervisor.py",
                     "tools.channel_reader_cv", "WatchF/daemon.py", "TsignalLAB/daemon.py", "LAB_daemon.py",
                     "scheduled-task.py", "--scheduled", "C:/Users/x/.cursor/projects/foo",
                     "D:/s1a-ledger-20261010-01a10bd5/test.py", "C:/Users/x/.devspace/worktree"]
        for command in protected:
            with self.subTest(command=command):
                reason = reaper.protected_reason([command])
                self.assertIsNotNone(reason)
                self.assertEqual(target(report_for(proc=process(protected_reason=reason)))["action"], "KEEP")
        result = report_for(record(worktree="D:/s1a-ledger-20261010-01a10bd5"))
        self.assertEqual(target(result)["reason"], "PROTECTED_DEVSPACE")

    def test_scheduler_ancestor_is_kept_even_with_interactive_registry(self):
        scheduled = process(10, start_time=1500.0, protected_reason="PROTECTED_SCHEDULED_TASK")
        result = reaper.build_report([record()], table(process(), scheduled), **CONTEXT)
        self.assertEqual(target(result)["reason"], "PROTECTED_ANCESTRY")

    def test_unidentified_descendant_blocks_parent_and_propagates(self):
        records = [record(), record(pid=30, parent_pid=20)]
        result = reaper.build_report(records, table(process(), process(30, parent_pid=20), process(40, parent_pid=30)), **CONTEXT)
        self.assertEqual(target(result)["reason"], "DESCENDANT_OWNERSHIP_UNKNOWN")
        self.assertEqual(target(result, 30)["reason"], "DESCENDANT_OWNERSHIP_UNKNOWN")
        self.assertEqual(target(result, 40)["reason"], "UNREGISTERED")

    def test_unknown_parentage_blocks_candidate(self):
        result = reaper.build_report([record()], table(process(), process(45, parent_pid=None)), **CONTEXT)
        self.assertEqual(target(result)["reason"], "DESCENDANT_OWNERSHIP_UNKNOWN")

    def test_duplicate_registry_identity_and_duplicate_process_pid_fail_closed(self):
        result = reaper.build_report([record(), record()], table(process()), **CONTEXT)
        self.assertEqual(target(result)["reason"], "REGISTRY_IDENTITY_CONFLICT")
        result = reaper.build_report([record()], table(process(), process()), **CONTEXT)
        self.assertEqual(target(result)["action"], "KEEP")

    def test_output_does_not_copy_raw_registry_secrets(self):
        rec = record(environment={"TOKEN": "private-value"}, command_line="secret-command", token="private-token")
        result = report_for(rec)
        serialized = json.dumps(result)
        markdown = reaper.render_markdown(result)
        for secret in ("private-value", "secret-command", "private-token"):
            self.assertNotIn(secret, serialized + markdown)
        self.assertIn("WOULD_KILL", markdown)
        self.assertEqual(result["summary"]["would_free_rss_gib"], 2.0)

    def test_summary_accounts_for_kept_unknown_and_candidate_rss(self):
        result = reaper.build_report([record()], table(process(), process(30, rss_bytes=None)), **CONTEXT)
        summary = result["summary"]
        self.assertEqual((summary["would_kill"], summary["keep"], summary["rss_unknown_count"]), (1, 2, 1))
        self.assertEqual((summary["would_free_rss_gib"], summary["keep_rss_gib"]), (2.0, 2.0))
        self.assertEqual(sum(group["count"] for group in summary["by_reason"].values()), 3)

    def test_missing_psutil_is_explicit_and_classifier_remains_usable(self):
        with patch.object(reaper, "psutil", None):
            snapshot = reaper.collect_process_table()
            self.assertFalse(snapshot.complete)
            self.assertEqual(snapshot.error, "PSUTIL_UNAVAILABLE")
            self.assertEqual(reaper.launch_origin(), "unknown")
            result = reaper.build_report([], snapshot, **CONTEXT)
            self.assertEqual(result["collection_error"], "PSUTIL_UNAVAILABLE")
            self.assertEqual(target(report_for())["action"], "WOULD_KILL")


class SessionIdTests(unittest.TestCase):
    def test_current_process_session_is_positive(self):
        import os

        session = reaper.process_session_id(os.getpid())
        self.assertGreaterEqual(session, 0)

    def test_invalid_pid_raises(self):
        with self.assertRaises(OSError):
            reaper.process_session_id(0)

    def test_winapi_uses_stdcall_kernel32(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        import ctypes
        from ctypes import wintypes

        pid = os.getpid()
        session = wintypes.DWORD()
        self.assertTrue(
            ctypes.windll.kernel32.ProcessIdToSessionId(wintypes.DWORD(pid), ctypes.byref(session))
        )
        self.assertEqual(reaper.process_session_id(pid), int(session.value))


class CollectorTests(unittest.TestCase):
    def fake_psutil(self, processes):
        return SimpleNamespace(pids=Mock(return_value=list(processes)),
                               Process=Mock(side_effect=lambda pid: processes[pid]), Error=RuntimeError)

    def fake_process(self, pid=20, *, name="python.exe", parent=0, created=1000.0):
        return SimpleNamespace(pid=pid, create_time=Mock(return_value=created), ppid=Mock(return_value=parent),
                               username=Mock(return_value="DESKTOP\\dawid"), name=Mock(return_value=name),
                               memory_info=Mock(return_value=SimpleNamespace(rss=1234)),
                               cmdline=Mock(return_value=["python", "--token", "DO-NOT-OUTPUT"]),
                               cwd=Mock(return_value="D:/work/owned"), terminal=Mock(return_value=None),
                               environ=Mock(side_effect=AssertionError("must never read environment")))

    def test_collection_hashes_arguments_and_never_reads_environment(self):
        proc = self.fake_process()
        fake = self.fake_psutil({20: proc})
        with patch.object(reaper, "psutil", fake), patch.object(reaper, "process_session_id", return_value=3):
            result = reaper.collect_process_table()
        self.assertTrue(result.complete)
        self.assertEqual(result[0]["command_sha256"], reaper.command_sha256(["python", "--token", "DO-NOT-OUTPUT"]))
        self.assertNotIn("DO-NOT-OUTPUT", json.dumps(result))
        proc.environ.assert_not_called()

    def test_collection_access_denied_does_not_leak_exception_text(self):
        proc = self.fake_process()
        proc.cmdline.side_effect = PermissionError("secret-argument")
        with patch.object(reaper, "psutil", self.fake_psutil({20: proc})), patch.object(reaper, "process_session_id", return_value=3):
            result = reaper.collect_process_table()
        self.assertEqual(result[0]["inspection_error"], "PermissionError")
        self.assertNotIn("secret-argument", json.dumps(result))

    def test_collection_detects_creation_identity_change(self):
        proc = self.fake_process()
        proc.create_time.side_effect = [1000.0, 1001.0]
        with patch.object(reaper, "psutil", self.fake_psutil({20: proc})), patch.object(reaper, "process_session_id", return_value=3):
            result = reaper.collect_process_table()
        self.assertEqual(result[0]["inspection_error"], "PID_REUSED_DURING_INSPECTION")

    def test_launch_origin_requires_known_interactive_non_scheduler_ancestry(self):
        for parent_name, expected in (("explorer.exe", "interactive"), ("svchost.exe", "scheduled"), ("python.exe", "unknown")):
            with self.subTest(parent=parent_name):
                processes = {20: self.fake_process(parent=10), 10: self.fake_process(10, name=parent_name, created=900.0)}
                with patch.object(reaper, "psutil", self.fake_psutil(processes)), patch.object(reaper, "process_session_id", return_value=3), patch.object(reaper, "os", SimpleNamespace(name="nt")):
                    self.assertEqual(reaper.launch_origin(20), expected)

    def test_launch_origin_reused_or_inaccessible_parent_is_unknown(self):
        proc = self.fake_process(parent=10)
        parent = self.fake_process(10, name="explorer.exe", created=1500.0)
        with patch.object(reaper, "psutil", self.fake_psutil({20: proc, 10: parent})), patch.object(reaper, "process_session_id", return_value=3), patch.object(reaper, "os", SimpleNamespace(name="nt")):
            self.assertEqual(reaper.launch_origin(20), "unknown")
            parent.create_time.side_effect = PermissionError()
            self.assertEqual(reaper.launch_origin(20), "unknown")


class ActuationTests(unittest.TestCase):
    def test_later_registry_failure_preserves_prior_action_and_stops(self):
        records = [record(), record(pid=30)]
        reads = Mock(side_effect=[records, records, sqlite3.OperationalError("private-path")])
        with patch.object(reaper, "_terminate_windows_identity") as terminate:
            result = reaper.execute_reap(reads, collect=lambda: table(process(), process(30)), kill=True, **CONTEXT)
        terminate.assert_called_once()
        self.assertEqual(result["actuation"][0]["status"], "TERMINATION_REQUESTED")
        self.assertTrue(result["actuation_incomplete"])
        self.assertEqual(result["actuation_error"], "OperationalError")
        self.assertNotIn("private-path", json.dumps(result))
        self.assertIn("TERMINATION_REQUESTED", reaper.render_markdown(result))

    def test_failed_handle_close_never_erases_successful_termination(self):
        from ctypes import wintypes

        ticks = (11644473600 + 1000) * 10_000_000

        def write_time(handle, created, exited, system, user):
            result = ctypes.cast(created, ctypes.POINTER(wintypes.FILETIME)).contents
            result.dwLowDateTime = ticks & 0xFFFFFFFF
            result.dwHighDateTime = ticks >> 32
            return True

        kernel = SimpleNamespace(OpenProcess=Mock(return_value=123), GetProcessTimes=Mock(side_effect=write_time),
                                 TerminateProcess=Mock(return_value=True), CloseHandle=Mock(return_value=False))
        with patch.object(reaper, "os", SimpleNamespace(name="nt")), patch.object(ctypes, "WinDLL", return_value=kernel, create=True):
            result = reaper.execute_reap(lambda: [record(), record(pid=30)],
                                         collect=lambda: table(process(), process(30)), kill=True, **CONTEXT)
        kernel.TerminateProcess.assert_called_once_with(123, 1)
        self.assertEqual(result["actuation"][0]["status"], "TERMINATION_REQUESTED_CLEANUP_UNCONFIRMED")
        self.assertTrue(result["actuation_incomplete"])

    def test_default_is_read_only_and_does_not_actuate(self):
        with patch.object(reaper, "_terminate_windows_identity") as terminate:
            result = reaper.execute_reap(lambda: [record()], collect=lambda: table(process()), **CONTEXT)
        terminate.assert_not_called()
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["actuation"], [])

    def test_registry_and_process_table_are_refreshed_before_each_simulated_action(self):
        reads = Mock(side_effect=[[record()], [record(state="RECOVERY_REQUIRED")]])
        snapshot = Mock(side_effect=[table(process()), table(process())])
        with patch.object(reaper, "_terminate_windows_identity") as terminate:
            result = reaper.execute_reap(reads, collect=snapshot, kill=True, **CONTEXT)
        terminate.assert_not_called()
        self.assertEqual(reads.call_count, 2)
        self.assertEqual(snapshot.call_count, 2)
        self.assertEqual(result["actuation"][0]["status"], "KEPT")

    def test_reused_pid_between_report_and_action_is_not_terminated(self):
        snapshot = Mock(side_effect=[table(process()), table(process(start_time=1001.0))])
        with patch.object(reaper, "_terminate_windows_identity") as terminate:
            reaper.execute_reap(lambda: [record()], collect=snapshot, kill=True, **CONTEXT)
        terminate.assert_not_called()

    def test_simulated_qualified_action_and_refusal_preserve_truthful_outcome(self):
        for error, expected in ((None, "TERMINATION_REQUESTED"), (reaper.ReapRefused("PID_REUSED_AT_ACTUATION"), "KEPT")):
            with self.subTest(expected=expected), patch.object(reaper, "_terminate_windows_identity", side_effect=error) as terminate:
                result = reaper.execute_reap(lambda: [record()], collect=lambda: table(process()), kill=True, **CONTEXT)
            terminate.assert_called_once()
            self.assertEqual(result["actuation"][0]["status"], expected)

    def test_candidate_children_actuate_before_parent_without_recursive_kill(self):
        records = [record(pid=5, parent_pid=20), record()]
        snapshot = table(process(5, parent_pid=20), process())
        with patch.object(reaper, "_terminate_windows_identity") as terminate:
            reaper.execute_reap(lambda: deepcopy(records), collect=lambda: snapshot, kill=True, **CONTEXT)
        self.assertEqual([call.args[0]["pid"] for call in terminate.call_args_list], [5, 20])

    def test_non_windows_actuator_has_no_unsafe_fallback(self):
        with patch.object(reaper, "os", SimpleNamespace(name="posix")):
            with self.assertRaisesRegex(reaper.ReapRefused, "UNSUPPORTED_PLATFORM"):
                reaper._terminate_windows_identity(process())

    def test_windows_pinned_handle_rechecks_start_time_before_simulated_termination(self):
        from ctypes import wintypes

        for actual_time, permitted in ((1000, True), (1001, False)):
            with self.subTest(actual_time=actual_time):
                ticks = (11644473600 + actual_time) * 10_000_000

                def write_time(handle, created, exited, system, user):
                    result = ctypes.cast(created, ctypes.POINTER(wintypes.FILETIME)).contents
                    result.dwLowDateTime = ticks & 0xFFFFFFFF
                    result.dwHighDateTime = ticks >> 32
                    return True

                kernel = SimpleNamespace(OpenProcess=Mock(return_value=123), GetProcessTimes=Mock(side_effect=write_time),
                                         TerminateProcess=Mock(return_value=True), CloseHandle=Mock(return_value=True))
                with patch.object(reaper, "os", SimpleNamespace(name="nt")), patch.object(ctypes, "WinDLL", return_value=kernel, create=True):
                    if permitted:
                        reaper._terminate_windows_identity(process())
                        kernel.TerminateProcess.assert_called_once_with(123, 1)
                    else:
                        with self.assertRaisesRegex(reaper.ReapRefused, "PID_REUSED_AT_ACTUATION"):
                            reaper._terminate_windows_identity(process())
                        kernel.TerminateProcess.assert_not_called()
                kernel.CloseHandle.assert_called_once_with(123)


if __name__ == "__main__":
    unittest.main()
