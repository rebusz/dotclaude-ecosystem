"""Bounded subprocess and collector orchestration primitives."""

from __future__ import annotations

import concurrent.futures
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from truthdeck_model import CollectorRun, Fact, ReasonCode
from truthdeck_model import make_fact

ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE")


class CollectorError(RuntimeError):
    reason = ReasonCode.COLLECTOR_INTERNAL_ERROR


class CollectorTimeout(CollectorError):
    reason = ReasonCode.COLLECTOR_TIMEOUT


class CollectorOutputLimit(CollectorError):
    reason = ReasonCode.COLLECTOR_OUTPUT_LIMIT


@dataclass(frozen=True)
class Policy:
    command_timeout_s: float = 5.0
    total_deadline_s: float = 10.0
    max_output_bytes: int = 1_048_576
    max_workers: int = 4


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    elapsed_ms: int


@dataclass(frozen=True)
class CollectorResult:
    collector_id: str
    facts: tuple[Fact, ...]
    run: CollectorRun


Collector = Callable[[float], CollectorResult]


def run_bounded(argv: Iterable[str], *, cwd: Path, deadline: float,
                max_output_bytes: int = 1_048_576, env_extra: Mapping[str, str] | None = None) -> CommandResult:
    args = tuple(str(x) for x in argv)
    if not args or any("\x00" in x for x in args):
        raise CollectorError("invalid argv")
    cwd = cwd.resolve(strict=True)
    env = {key: os.environ[key] for key in ENV_ALLOWLIST if key in os.environ}
    if env_extra:
        env.update({str(k): str(v) for k, v in env_extra.items()})
    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    stdout = bytearray()
    stderr = bytearray()
    output_limit = threading.Event()
    output_lock = threading.Lock()

    def consume(stream, target: bytearray) -> None:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            with output_lock:
                target.extend(chunk)
                if len(stdout) + len(stderr) > max_output_bytes:
                    output_limit.set()
                    return

    try:
        process = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        readers = (
            threading.Thread(target=consume, args=(process.stdout, stdout), daemon=True),
            threading.Thread(target=consume, args=(process.stderr, stderr), daemon=True),
        )
        for reader in readers:
            reader.start()
        while process.poll() is None:
            if output_limit.is_set():
                _stop(process)
                break
            if time.monotonic() >= deadline:
                _stop(process)
                raise CollectorTimeout("collector deadline exceeded")
            time.sleep(0.01)
        for reader in readers:
            reader.join(timeout=0.5)
        if len(stdout) + len(stderr) > max_output_bytes:
            raise CollectorOutputLimit(f"collector output exceeded {max_output_bytes} bytes")
        return CommandResult(args, int(process.returncode), bytes(stdout).decode("utf-8", "replace"),
                             bytes(stderr).decode("utf-8", "replace"), int((time.monotonic() - started) * 1000))
    finally:
        if process is not None and process.poll() is None:
            _stop(process)


def read_bounded(path: Path, *, deadline: float, max_bytes: int) -> bytes:
    resolved = path.resolve(strict=True)
    if resolved.stat().st_size > max_bytes:
        raise CollectorOutputLimit(f"evidence file exceeded {max_bytes} bytes")
    payload = bytearray()
    with resolved.open("rb") as handle:
        while chunk := handle.read(min(65_536, max_bytes + 1 - len(payload))):
            payload.extend(chunk)
            if len(payload) > max_bytes:
                raise CollectorOutputLimit(f"evidence file exceeded {max_bytes} bytes")
            if time.monotonic() >= deadline:
                raise CollectorTimeout("evidence read deadline exceeded")
    return bytes(payload)


def collect_concurrently(collectors: Mapping[str, Collector], *, policy: Policy,
                         deadline: float | None = None) -> tuple[CollectorResult, ...]:
    deadline = deadline if deadline is not None else time.monotonic() + policy.total_deadline_s
    results: list[CollectorResult] = []
    workers = min(max(1, policy.max_workers), 4, max(1, len(collectors)))
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {pool.submit(collector, deadline): collector_id for collector_id, collector in collectors.items()}
        for future, collector_id in sorted(futures.items(), key=lambda item: item[1]):
            remaining = max(0.0, deadline - time.monotonic())
            try:
                results.append(future.result(timeout=remaining))
            except concurrent.futures.TimeoutError:
                results.append(CollectorResult(
                    collector_id, (), CollectorRun(collector_id, "1", int(policy.total_deadline_s * 1000),
                                                    None, True, (ReasonCode.COLLECTOR_TIMEOUT.value,)),
                ))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return tuple(sorted(results, key=lambda x: (x.run.repo_id or "", x.collector_id)))


def collect_plan(path: Path, *, observed_at_utc: str, repo_id: str, deadline: float | None = None,
                 max_output_bytes: int = 1_048_576) -> CollectorResult:
    """Parse only the small canonical frontmatter contract; prose is never authority."""
    started = time.monotonic()
    text = read_bounded(path, deadline=deadline or time.monotonic() + 5,
                        max_bytes=max_output_bytes).decode("utf-8").replace("\r\n", "\n")
    frontmatter: dict[str, str] = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            for line in text[4:end].splitlines():
                if ":" in line and not line[:1].isspace():
                    key, value = line.split(":", 1)
                    frontmatter[key.strip()] = value.strip().strip("\"'")
    risk = frontmatter.get("risk", "")
    status = frontmatter.get("status", "")
    parseable = risk in {"R0", "R1", "R2", "R3"} and bool(status)
    blocked = status.lower() in {"blocked", "cancelled", "canceled"}
    locator = f"plan:{path.name}"
    facts = (
        make_fact("plan.parseable", parseable, source_type="plan", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id),
        make_fact("plan.risk", risk or "UNKNOWN", source_type="plan", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id),
        make_fact("plan.blocked", blocked, source_type="plan", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id),
    )
    return CollectorResult("plan", facts, CollectorRun("plan", "1", int((time.monotonic() - started) * 1000), 0, repo_id=repo_id))


def _stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=0.5)
