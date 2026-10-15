"""Containment lifecycle tests; every process, handle and signal is simulated."""

from __future__ import annotations

import ctypes
import io
import subprocess
from types import SimpleNamespace

import pytest

from scripts import conductor_processes as processes


class FakeHandle:
    def __init__(self, events):
        self.events = events

    def __int__(self):
        return 1234

    def Close(self):
        self.events.append("close-process")


class FakeProcess:
    pid = 456

    def __init__(self, events, **kwargs):
        self.events = events
        self.returncode = None
        self._handle = FakeHandle(events)
        self.stdin = None
        self.stdout = io.StringIO("output") if kwargs.get("stdout") == subprocess.PIPE else None
        self.stderr = io.StringIO("error") if kwargs.get("stderr") == subprocess.PIPE else None
        self.wait_error = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.events.append("wait")
        if self.wait_error:
            raise self.wait_error
        if self.returncode is None:
            self.returncode = 1
        return self.returncode

    def communicate(self, timeout=None):
        self.events.append(("communicate", timeout))
        return "output", "error"

    def kill(self):
        self.events.append("kill-child")

    def terminate(self):
        self.events.append("terminate-child")


class FakeApi:
    def __init__(self, events):
        self.events = events
        self.fail = None
        self.active = 1
        self.stuck = False

    def event(self, name):
        self.events.append(name)
        if name == self.fail:
            raise OSError(name)

    def create_job(self):
        self.event("create-job")
        return 101

    def configure_job(self, job):
        assert job == 101
        self.event("configure-job")

    def assign(self, job, process):
        assert job == 101
        assert int(process._handle) == 1234
        self.event("assign")

    def open_initial_thread(self, process):
        self.event("open-thread")
        return 202

    def resume(self, thread, process):
        assert thread == 202
        self.event("resume")

    def active_processes(self, job):
        self.event("query-active")
        return self.active

    def member_pids(self, job):
        assert job == 101
        self.event("membership")
        return [456, 457]

    def terminate(self, job):
        assert job == 101
        self.event("terminate-job")
        if not self.stuck:
            self.active = 0

    def close_handle(self, handle):
        self.event("close-thread" if handle == 202 else "close-job")


@pytest.fixture
def windows(monkeypatch):
    events = []
    api = FakeApi(events)
    created = []
    calls = []

    def popen(command, **kwargs):
        events.append("spawn")
        calls.append((command, kwargs))
        process = FakeProcess(events, **kwargs)
        created.append(process)
        return process

    monkeypatch.setattr(processes, "_WINDOWS", True)
    monkeypatch.setattr(processes, "_WindowsApi", lambda: api)
    monkeypatch.setattr(processes.subprocess, "Popen", popen)
    monkeypatch.setattr(processes, "_CLEANUP_SECONDS", 0)
    return SimpleNamespace(events=events, api=api, created=created, calls=calls)


def launch(**kwargs):
    return processes.ContainedProcess(
        ["python", "-m", "pytest"], cwd="owned", env={"CONDUCTOR_LANE_ID": "lane-1"},
        stdout=kwargs.pop("stdout", subprocess.PIPE), stderr=subprocess.PIPE, **kwargs,
    )


def test_windows_assigns_and_registers_before_payload_resume(windows):
    child = launch(on_started=lambda process: windows.events.append("registered"))
    assert windows.events == ["create-job", "configure-job", "spawn", "assign", "open-thread",
                              "registered", "resume", "close-thread"]
    command, kwargs = windows.calls[0]
    assert command == ["python", "-m", "pytest"]
    assert kwargs == {
        "cwd": "owned", "env": {"CONDUCTOR_LANE_ID": "lane-1"}, "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8", "errors": "replace",
        "shell": False, "close_fds": True, "creationflags": 4,
    }
    assert child.pid == 456
    assert child.process is windows.created[0]
    assert child.close() is True


def test_suspended_registration_runs_before_job_assignment(windows):
    launch(on_suspended=lambda process: windows.events.append("suspended"))
    assert windows.events.index("suspended") < windows.events.index("assign")


def test_normal_completion_cleans_descendants_and_checks_job_before_close(windows):
    child = launch()
    child.process.returncode = 0
    windows.api.active = 3  # leader exited, descendants remain
    assert child.close() is True
    assert child.returncode == 0
    assert windows.events[-6:] == ["query-active", "terminate-job", "wait", "query-active",
                                  "close-job", "close-process"]
    previous_events = list(windows.events)
    assert child.close() is True
    child.kill()
    assert windows.events == previous_events


def test_empty_job_never_signals_any_process(windows):
    child = launch()
    child.process.returncode = 0
    windows.api.active = 0
    assert child.close() is True
    assert "terminate-job" not in windows.events
    assert "kill-child" not in windows.events


def test_membership_comes_only_from_owned_job_and_closed_cleanup_proof(windows):
    child = launch()
    assert child.member_pids() == [456, 457]
    assert child.close() is True
    assert child.member_pids() == []


def test_failed_cleanup_does_not_claim_empty_membership(windows):
    child = launch()
    windows.api.fail = "query-active"
    assert child.close() is False
    with pytest.raises(OSError, match="without terminal proof"):
        child.member_pids()


@pytest.mark.parametrize("failure", ["configure-job", "assign", "open-thread", "resume", "close-thread"])
def test_setup_failures_roll_back_only_owned_handles(windows, failure):
    windows.api.fail = failure
    with pytest.raises(processes.ContainmentError) as raised:
        launch()
    error = raised.value
    assert error.cleanup_confirmed is (failure != "close-thread")
    assert "close-job" in windows.events
    if failure == "configure-job":
        assert windows.created == []
    elif failure == "assign":
        assert "kill-child" in windows.events
        assert "resume" not in windows.events
    elif failure == "open-thread":
        assert "resume" not in windows.events
    assert error.process is (windows.created[0] if windows.created else None)


def test_registration_failure_never_resumes_and_preserves_failed_attempt(windows):
    def registration(process):
        windows.events.append("registration-failed")
        raise RuntimeError("store refused")

    with pytest.raises(processes.ContainmentError) as raised:
        launch(on_started=registration)
    assert "resume" not in windows.events
    assert "terminate-job" in windows.events
    assert raised.value.cleanup_confirmed is True
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_popen_failure_closes_job_without_claiming_a_child(windows, monkeypatch):
    def failure(*args, **kwargs):
        raise OSError("CreateProcess failed")

    monkeypatch.setattr(processes.subprocess, "Popen", failure)
    with pytest.raises(processes.ContainmentError) as raised:
        launch()
    assert raised.value.process is None
    assert raised.value.cleanup_confirmed is True
    assert windows.events == ["create-job", "configure-job", "close-job"]


@pytest.mark.parametrize("failure", ["terminate-job", "query-active", "close-job", "wait", "stuck"])
def test_cleanup_uncertainty_is_not_released_or_retried(windows, failure):
    child = launch()
    if failure == "wait":
        child.process.wait_error = subprocess.TimeoutExpired("fake", 1)
    elif failure == "stuck":
        windows.api.stuck = True
    else:
        windows.api.fail = failure
    assert child.close() is False
    assert "close-job" in windows.events
    previous_events = list(windows.events)
    assert child.close() is False
    assert windows.events == previous_events


def test_registration_failure_with_ambiguous_cleanup_exposes_retained_custody(windows):
    windows.api.fail = "terminate-job"

    def registration(process):
        raise RuntimeError("failed registration")

    with pytest.raises(processes.ContainmentError) as raised:
        launch(on_started=registration)
    assert raised.value.cleanup_confirmed is False
    assert raised.value.process is windows.created[0]
    assert raised.value.contained_process.cleanup_errors == ["OSError"]


def test_stream_files_remain_caller_owned_and_pipes_are_closed(windows):
    caller_file = io.StringIO()
    child = launch(stdout=caller_file)
    assert child.communicate(timeout=2) == ("output", "error")
    assert child.poll() is None
    assert child.close() is True
    assert caller_file.closed is False
    assert child.process.stderr.closed is True


class NativeFunction:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


def kernel(**overrides):
    functions = {
        "CreateJobObjectW": lambda *args: 101,
        "SetInformationJobObject": lambda *args: 1,
        "AssignProcessToJobObject": lambda *args: 1,
        "QueryInformationJobObject": lambda *args: 1,
        "TerminateJobObject": lambda *args: 1,
        "CloseHandle": lambda *args: 1,
        "OpenThread": lambda *args: 202,
        "GetProcessIdOfThread": lambda *args: 456,
        "ResumeThread": lambda *args: 1,
    }
    functions.update(overrides)
    return SimpleNamespace(**{name: NativeFunction(fn) for name, fn in functions.items()})


def test_native_job_configuration_disables_breakaway_and_reads_accounting():
    observed = {}

    def configure(job, information_class, pointer, size):
        limits = ctypes.cast(pointer, ctypes.POINTER(processes._ExtendedLimit)).contents
        observed.update(job=job, information_class=information_class, size=size,
                        flags=limits.BasicLimitInformation.LimitFlags)
        return 1

    def query(job, information_class, pointer, size, returned):
        assert information_class == 1
        ctypes.cast(pointer, ctypes.POINTER(processes._Accounting)).contents.ActiveProcesses = 2
        return 1

    api = processes._WindowsApi(kernel(SetInformationJobObject=configure, QueryInformationJobObject=query))
    job = api.create_job()
    api.configure_job(job)
    assert observed == {"job": 101, "information_class": 9,
                        "size": ctypes.sizeof(processes._ExtendedLimit), "flags": 0x2000}
    assert api.active_processes(job) == 2


def test_native_membership_expands_partial_snapshots():
    sizes = []

    def query(job, information_class, pointer, size, returned):
        assert information_class == 3
        sizes.append(size)
        header = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))
        header[0] = 40
        header[1] = 32 if len(sizes) == 1 else 40
        if len(sizes) > 1:
            pids = ctypes.cast(ctypes.addressof(pointer._obj) + 8, ctypes.POINTER(ctypes.c_size_t))
            for index in range(40):
                pids[index] = index + 400
        return 1

    api = processes._WindowsApi(kernel(QueryInformationJobObject=query))
    assert api.member_pids(101) == list(range(400, 440))
    assert len(sizes) == 2
    assert sizes[1] > sizes[0]


def test_native_membership_refuses_unbounded_growth():
    def query(job, information_class, pointer, size, returned):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))[0] = 999999
        return 1

    api = processes._WindowsApi(kernel(QueryInformationJobObject=query))
    with pytest.raises(OSError, match="bounded snapshot capacity"):
        api.member_pids(101)


@pytest.mark.parametrize("thread_ids", [[], [1, 2]])
def test_native_resume_requires_one_suspended_thread(monkeypatch, thread_ids):
    api = processes._WindowsApi(kernel())
    monkeypatch.setattr(processes.psutil, "Process", lambda pid: SimpleNamespace(
        threads=lambda: [SimpleNamespace(id=tid) for tid in thread_ids]))
    with pytest.raises(OSError, match="exactly one"):
        api.open_initial_thread(FakeProcess([]))


@pytest.mark.parametrize("previous_count", [0, 2, 0xFFFFFFFF])
def test_native_resume_requires_exact_initial_suspend_count(previous_count):
    api = processes._WindowsApi(kernel(ResumeThread=lambda thread: previous_count))
    with pytest.raises(OSError, match="unexpected suspend count"):
        api.resume(202, FakeProcess([]))


def test_native_thread_identity_change_never_resumes():
    events = []
    api = processes._WindowsApi(kernel(GetProcessIdOfThread=lambda thread: 999,
                                      ResumeThread=lambda thread: events.append("resumed")))
    with pytest.raises(OSError, match="ownership changed"):
        api.resume(202, FakeProcess([]))
    assert events == []


def test_native_open_and_resume_owned_thread(monkeypatch):
    events = []
    api = processes._WindowsApi(kernel(OpenThread=lambda access, inherit, tid: events.append(
        (access, inherit, tid)) or 202))
    monkeypatch.setattr(processes.psutil, "Process", lambda pid: SimpleNamespace(
        threads=lambda: [SimpleNamespace(id=111)]))
    child = FakeProcess([])
    assert api.open_initial_thread(child) == 202
    api.resume(202, child)
    assert events == [(0x802, False, 111)]


@pytest.fixture
def posix(windows, monkeypatch):
    monkeypatch.setattr(processes, "_WINDOWS", False)
    monkeypatch.setattr(processes.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 12.5))
    monkeypatch.setattr(processes.os, "getpgid", lambda pid: pid, raising=False)
    signals = []
    state = {"exists": True}

    def killpg(pgid, sig):
        assert pgid == 456
        signals.append(sig)
        if not state["exists"]:
            raise ProcessLookupError()
        if sig:
            state["exists"] = False

    monkeypatch.setattr(processes.os, "killpg", killpg, raising=False)
    return SimpleNamespace(windows=windows, signals=signals, state=state)


def test_posix_uses_session_and_retained_leader_for_cleanup(posix):
    child = launch()
    assert posix.windows.calls[0][1]["start_new_session"] is True
    assert "creationflags" not in posix.windows.calls[0][1]
    assert child.close() is True
    assert posix.signals == [0, processes._SIGKILL, 0]


def test_posix_membership_only_reports_owned_unreaped_leader(posix):
    child = launch()
    assert child.member_pids() == [456]
    child.process.returncode = 0
    assert child.member_pids() == []


def test_posix_reaped_leader_with_surviving_group_fails_closed(posix):
    child = launch()
    child.process.returncode = 0
    assert child.close() is False
    assert posix.signals == [0]


def test_posix_completed_empty_group_confirms_cleanup(posix):
    child = launch()
    child.process.returncode = 0
    posix.state["exists"] = False
    assert child.close() is True
    assert posix.signals == [0, 0]


def test_posix_reused_leader_identity_is_not_signalled(posix, monkeypatch):
    child = launch()
    monkeypatch.setattr(processes.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 99))
    assert child.close() is False
    assert posix.signals == [0]
