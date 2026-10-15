"""OS containment for a single owned Conductor launch.

Policy, admission and durable ownership live in conductor_resources/store. This
module owns only handles it creates; it never discovers or adopts other jobs.
Call ``close`` on every exit path and retain the reservation when it returns
False. ``process`` is the retained Popen, not authority to signal by process name.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import psutil


_WINDOWS = os.name == "nt"
_CREATE_SUSPENDED = 0x00000004
_KILL_ON_JOB_CLOSE = 0x00002000
_CLEANUP_SECONDS = 5.0
_SIGKILL = getattr(signal, "SIGKILL", 9)


class ContainmentError(RuntimeError):
    """Launch failed; callers must preserve custody unless cleanup is proven."""

    def __init__(self, message: str, contained_process: ContainedProcess):
        super().__init__(message)
        self.contained_process = contained_process
        self.process = contained_process.process
        self.cleanup_confirmed = contained_process.cleanup_confirmed


class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


class _WindowsApi:
    """Small documented Kernel32 surface; no global subprocess monkeypatches."""

    def __init__(self, kernel: Any = None):
        self.kernel = kernel if kernel is not None else ctypes.WinDLL("kernel32", use_last_error=True)
        handle, dword, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
        signatures = {
            "CreateJobObjectW": ([handle, ctypes.c_wchar_p], handle),
            "SetInformationJobObject": ([handle, ctypes.c_int32, handle, dword], boolean),
            "AssignProcessToJobObject": ([handle, handle], boolean),
            "QueryInformationJobObject": ([handle, ctypes.c_int32, handle, dword, handle], boolean),
            "TerminateJobObject": ([handle, dword], boolean),
            "CloseHandle": ([handle], boolean),
            "OpenThread": ([dword, boolean, dword], handle),
            "GetProcessIdOfThread": ([handle], dword),
            "ResumeThread": ([handle], dword),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes = args
            function.restype = result

    @staticmethod
    def _check(result: Any, operation: str) -> Any:
        if not result:
            code = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
            raise OSError(code, f"{operation} failed")
        return result

    def create_job(self) -> int:
        return self._check(self.kernel.CreateJobObjectW(None, None), "CreateJobObjectW")

    def configure_job(self, job: int) -> None:
        limits = _ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        self._check(self.kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)),
                    "SetInformationJobObject")

    def assign(self, job: int, process: subprocess.Popen[str]) -> None:
        self._check(self.kernel.AssignProcessToJobObject(job, int(process._handle)),  # type: ignore[attr-defined]
                    "AssignProcessToJobObject")

    def open_initial_thread(self, process: subprocess.Popen[str]) -> int:
        # Popen closes CreateProcess's initial thread handle. The child is still
        # suspended, so require exactly one thread and pin it with OpenThread.
        threads = psutil.Process(process.pid).threads()
        if len(threads) != 1:
            raise OSError("suspended child does not have exactly one initial thread")
        return self._check(self.kernel.OpenThread(0x0002 | 0x0800, False, threads[0].id), "OpenThread")

    def resume(self, thread: int, process: subprocess.Popen[str]) -> None:
        if self.kernel.GetProcessIdOfThread(thread) != process.pid:
            raise OSError("initial thread ownership changed")
        previous_count = self.kernel.ResumeThread(thread)
        if previous_count != 1:
            raise OSError(f"ResumeThread returned unexpected suspend count {previous_count}")

    def active_processes(self, job: int) -> int:
        accounting = _Accounting()
        self._check(self.kernel.QueryInformationJobObject(
            job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None), "QueryInformationJobObject")
        return accounting.ActiveProcesses

    def member_pids(self, job: int) -> list[int]:
        capacity = 32
        for _ in range(5):
            class ProcessIds(ctypes.Structure):
                _fields_ = [
                    ("assigned", ctypes.c_uint32), ("returned", ctypes.c_uint32),
                    ("pids", ctypes.c_size_t * capacity),
                ]

            members = ProcessIds()
            result = self.kernel.QueryInformationJobObject(
                job, 3, ctypes.byref(members), ctypes.sizeof(members), None)
            error = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
            if result and members.returned <= capacity and members.returned == members.assigned:
                return [int(pid) for pid in members.pids[:members.returned]]
            if not result and error != 234:  # ERROR_MORE_DATA
                self._check(result, "QueryInformationJobObject membership")
            capacity = max(capacity * 2, int(members.assigned))
            if capacity > 65536:
                break
        raise OSError("Job membership exceeded bounded snapshot capacity")

    def terminate(self, job: int) -> None:
        self._check(self.kernel.TerminateJobObject(job, 1), "TerminateJobObject")

    def close_handle(self, handle: int) -> None:
        self._check(self.kernel.CloseHandle(handle), "CloseHandle")


class ContainedProcess:
    """Retained child plus Job Object (Windows) or owned process group (POSIX).

    Windows payload execution begins only after ``on_started`` returns. The
    callback must synchronously commit registration or raise. It must not resume,
    wait for, signal, or replace the child. POSIX starts a new session but cannot
    suspend atomically with Popen, so its registration callback is post-spawn.
    Callers may read ``process`` metadata, but must use this object's lifetime API.
    Caller-supplied stdout/stderr files remain owned by the caller.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | os.PathLike[str],
        env: Mapping[str, str],
        stdout: Any,
        stderr: Any,
        on_started: Callable[[subprocess.Popen[str]], None] | None = None,
        on_suspended: Callable[[subprocess.Popen[str]], None] | None = None,
    ):
        if isinstance(command, (str, bytes)) or not command:
            raise ValueError("command must be a nonempty argument sequence")
        self.process: subprocess.Popen[str] | None = None
        self.cleanup_confirmed = False
        self.cleanup_errors: list[str] = []
        self._windows = _WINDOWS
        self._api: _WindowsApi | None = None
        self._job: int | None = None
        self._thread: int | None = None
        self._assigned = False
        self._closed = False
        self._posix_start_time: float | None = None
        try:
            if self._windows:
                self._api = _WindowsApi()
                self._job = self._api.create_job()
                self._api.configure_job(self._job)
            self.process = subprocess.Popen(
                list(command), cwd=os.fspath(cwd), env=dict(env), stdout=stdout, stderr=stderr,
                text=True, encoding="utf-8", errors="replace", shell=False, close_fds=True,
                **({"creationflags": _CREATE_SUSPENDED} if self._windows else {"start_new_session": True}),
            )
            if self._windows:
                if on_suspended is not None:
                    on_suspended(self.process)
                self._api.assign(self._job, self.process)
                self._assigned = True
                self._thread = self._api.open_initial_thread(self.process)
            else:
                self._posix_start_time = psutil.Process(self.process.pid).create_time()
            if on_started is not None:
                on_started(self.process)
            if self._windows:
                self._api.resume(self._thread, self.process)
                self._api.close_handle(self._thread)
                self._thread = None
        except BaseException as exc:
            self.close()
            error = ContainmentError(f"contained launch failed ({type(exc).__name__})", self)
            raise error from exc

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def returncode(self) -> int | None:
        return self.process.returncode

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def communicate(self, timeout: float | None = None) -> tuple[str | None, str | None]:
        return self.process.communicate(timeout=timeout)

    def member_pids(self) -> list[int]:
        """Positive ownership snapshot, never an alternative liveness authority.

        PIDs may exit immediately after this call: the registry must independently
        capture birth identity and verify membership again before recording them.
        """
        if self._closed:
            if self.cleanup_confirmed:
                return []
            raise OSError("containment closed without terminal proof")
        if self._windows:
            if not self._assigned:
                raise OSError("child has not been assigned to the owned Job")
            return self._api.member_pids(self._job)
        if (self.process.returncode is None
                and self._posix_start_time == psutil.Process(self.pid).create_time()
                and os.getpgid(self.pid) == self.pid):
            return [self.pid]
        return []

    def _signal_group(self, sig: int) -> None:
        if self.process.returncode is not None:
            # POSIX has no pinned group handle. A reaped leader's PGID could be
            # recycled: report uncertainty instead of risking a different group.
            raise OSError("cannot signal group after its retained leader was reaped")
        if (self._posix_start_time is None
                or psutil.Process(self.pid).create_time() != self._posix_start_time
                or os.getpgid(self.pid) != self.pid):
            raise OSError("owned process group identity unavailable")
        os.killpg(self.pid, sig)

    def terminate(self) -> None:
        if self._closed:
            return
        if self._windows:
            if self._assigned:
                self._api.terminate(self._job)
            elif self.process is not None:
                # Failed assignment leaves our retained, never-resumed child.
                self.process.terminate()
        else:
            self._signal_group(signal.SIGTERM)

    def kill(self) -> None:
        if self._windows:
            self.terminate()
        elif not self._closed:
            self._signal_group(_SIGKILL)

    def _group_exists(self) -> bool:
        try:
            os.killpg(self.pid, 0)
        except ProcessLookupError:
            return False
        return True

    def _close_windows(self, deadline: float) -> bool:
        terminal = self.process is None
        if self._assigned:
            # Even normal parent completion must clean up remaining children.
            if self._api.active_processes(self._job):
                self._api.terminate(self._job)
            if self.process is not None:
                self.process.wait(timeout=max(0.001, deadline - time.monotonic()))
            while self._api.active_processes(self._job):
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.01)
            terminal = True
        elif self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=max(0.001, deadline - time.monotonic()))
            terminal = True
        return terminal

    def _close_posix(self, deadline: float) -> bool:
        if self.process is None:
            return True
        # Signal before wait/poll reaps the owned leader and loses the group
        # anchor. No external process table substitutes for the retained Popen.
        if self._group_exists():
            self._signal_group(_SIGKILL)
        self.process.wait(timeout=max(0.001, deadline - time.monotonic()))
        while self._group_exists():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def close(self) -> bool:
        """Bounded cleanup; True requires terminal tree and closed owned handles.

        A failed close remains failed on subsequent calls: callers must preserve
        recovery custody. Closing the Job handle is a final kill-on-close safety
        net, not evidence that termination completed.
        """
        if self._closed:
            return self.cleanup_confirmed
        terminal = False
        try:
            deadline = time.monotonic() + _CLEANUP_SECONDS
            terminal = self._close_windows(deadline) if self._windows else self._close_posix(deadline)
        except BaseException as exc:
            self.cleanup_errors.append(type(exc).__name__)
        finally:
            for name in ("_thread", "_job"):
                handle = getattr(self, name)
                if handle is not None:
                    try:
                        self._api.close_handle(handle)
                        setattr(self, name, None)
                    except BaseException as exc:
                        self.cleanup_errors.append(f"{name}:{type(exc).__name__}")
            if terminal and self.process is not None:
                # Only streams Popen created are present here; passed files are
                # not assigned to Popen.stdout/stderr and remain caller-owned.
                for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError as exc:
                            self.cleanup_errors.append(f"stream:{type(exc).__name__}")
                if self._windows:
                    try:
                        self.process._handle.Close()  # type: ignore[attr-defined]
                    except OSError as exc:
                        self.cleanup_errors.append(f"process:{type(exc).__name__}")
            self._closed = True
            self.cleanup_confirmed = terminal and not self.cleanup_errors
        return self.cleanup_confirmed
