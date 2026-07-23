"""Execution adapter for the fixed, read-only runtime probe allowlist."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from truthdeck_collectors import CollectorError, CollectorResult, run_bounded
from truthdeck_model import CollectorRun, FactState, make_fact
from truthdeck_profiles import PROBES, expand_probe


def collect_runtime(repo: Path, *, probe_ids: tuple[str, ...], observed_at_utc: str,
                    deadline: float, repo_id: str, ttl_s: int = 60,
                    runtime_applicable: bool = True, expected_build: str | None = None,
                    command_timeout_s: float = 5.0, max_output_bytes: int = 1_048_576) -> CollectorResult:
    started = time.monotonic()
    applicable = make_fact("runtime.applicable", runtime_applicable, source_type="profile",
                           source_locator="registry", observed_at_utc=observed_at_utc, repo_id=repo_id)
    if not runtime_applicable:
        return CollectorResult("runtime", (applicable,), CollectorRun("runtime", "1", 0, 0, repo_id=repo_id))
    expected = make_fact("runtime.expected_build", expected_build, state=FactState.OBSERVED if expected_build else FactState.UNAVAILABLE,
                         source_type="profile", source_locator="scope-head", observed_at_utc=observed_at_utc, repo_id=repo_id)
    if not probe_ids:
        unavailable = (
            applicable, expected,
            make_fact("runtime.build", None, state=FactState.UNAVAILABLE, source_type="runtime",
                      source_locator="no-registered-probe", observed_at_utc=observed_at_utc, repo_id=repo_id),
            make_fact("runtime.ready", None, state=FactState.UNAVAILABLE, source_type="runtime",
                      source_locator="no-registered-probe", observed_at_utc=observed_at_utc, repo_id=repo_id),
            make_fact("runtime.sample_count", None, state=FactState.UNAVAILABLE, source_type="runtime",
                      source_locator="no-registered-probe", observed_at_utc=observed_at_utc, repo_id=repo_id),
        )
        return CollectorResult("runtime", unavailable, CollectorRun("runtime", "1", 0, None, diagnostics=("no registered read-only probe",), repo_id=repo_id))
    payloads = []
    statuses = []
    samples = []
    builds = []
    elapsed = 0
    for probe_id in sorted(probe_ids):
        if probe_id not in PROBES:
            raise CollectorError("unknown runtime probe")
        spec = PROBES[probe_id]
        result = run_bounded(expand_probe(spec, repo, repo_id), cwd=repo,
                             deadline=min(deadline, time.monotonic() + command_timeout_s),
                             max_output_bytes=max_output_bytes)
        elapsed += result.elapsed_ms
        if result.returncode:
            raise CollectorError(f"runtime probe failed: {result.stderr[:200]}")
        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CollectorError("runtime probe did not emit JSON") from exc
        if not isinstance(raw, dict) or raw.get("schema_version") != spec.schema_version:
            raise CollectorError("runtime probe schema mismatch")
        payloads.append(raw)
        statuses.append(str(_nested(raw, spec.status_path)) in spec.ready_values)
        samples.append(int(_nested(raw, spec.sample_path)) if spec.sample_path else 1)
        if spec.build_path:
            builds.append(str(_nested(raw, spec.build_path)))
    ready = all(statuses)
    sample = sum(samples)
    build = builds[0] if builds and len(set(builds)) == 1 else None
    fresh_until = (datetime.fromisoformat(observed_at_utc.replace("Z", "+00:00")).astimezone(UTC) + timedelta(seconds=ttl_s)).isoformat().replace("+00:00", "Z")
    locator = "runtime:" + ",".join(sorted(probe_ids))
    facts = (
        applicable, expected,
        make_fact("runtime.build", str(build) if build is not None else None,
                  state=FactState.OBSERVED if build is not None else FactState.UNAVAILABLE,
                  source_type="runtime", source_locator=locator, observed_at_utc=observed_at_utc,
                  fresh_until_utc=fresh_until, repo_id=repo_id, evidence=payloads),
        make_fact("runtime.ready", ready, source_type="runtime", source_locator=locator,
                  observed_at_utc=observed_at_utc, fresh_until_utc=fresh_until, repo_id=repo_id, evidence=payloads),
        make_fact("runtime.sample_count", int(sample), source_type="runtime", source_locator=locator,
                  observed_at_utc=observed_at_utc, fresh_until_utc=fresh_until, repo_id=repo_id, evidence=payloads),
    )
    return CollectorResult("runtime", facts, CollectorRun("runtime", "1", max(elapsed, int((time.monotonic() - started) * 1000)), 0, repo_id=repo_id))


def _nested(raw, path):
    value = raw
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise CollectorError(f"runtime probe missing {'.'.join(path)}")
        value = value[key]
    return value
