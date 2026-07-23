"""Execution adapter for the fixed, read-only runtime probe allowlist."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from truthdeck_collectors import CollectorError, CollectorResult, run_bounded
from truthdeck_model import CollectorRun, FactState, make_fact
from truthdeck_profiles import PROBES, expand_probe


def collect_runtime(repo: Path, *, probe_id: str | None, observed_at_utc: str,
                    deadline: float, repo_id: str, ttl_s: int = 60,
                    runtime_applicable: bool = True) -> CollectorResult:
    started = time.monotonic()
    applicable = make_fact("runtime.applicable", runtime_applicable, source_type="profile",
                           source_locator="registry", observed_at_utc=observed_at_utc, repo_id=repo_id)
    if not runtime_applicable:
        return CollectorResult("runtime", (applicable,), CollectorRun("runtime", "1", 0, 0, repo_id=repo_id))
    if not probe_id:
        unavailable = (
            applicable,
            make_fact("runtime.ready", None, state=FactState.UNAVAILABLE, source_type="runtime",
                      source_locator="no-registered-probe", observed_at_utc=observed_at_utc, repo_id=repo_id),
            make_fact("runtime.sample_count", None, state=FactState.UNAVAILABLE, source_type="runtime",
                      source_locator="no-registered-probe", observed_at_utc=observed_at_utc, repo_id=repo_id),
        )
        return CollectorResult("runtime", unavailable, CollectorRun("runtime", "1", 0, None, diagnostics=("no registered read-only probe",), repo_id=repo_id))
    if probe_id not in PROBES:
        raise CollectorError("unknown runtime probe")
    spec = PROBES[probe_id]
    result = run_bounded(expand_probe(spec, repo), cwd=repo, deadline=deadline)
    if result.returncode:
        raise CollectorError(f"runtime probe failed: {result.stderr[:200]}")
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CollectorError("runtime probe did not emit JSON") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != spec.schema_version:
        raise CollectorError("runtime probe schema mismatch")
    status = _nested(raw, spec.status_path)
    sample = _nested(raw, spec.sample_path) if spec.sample_path else 1
    ready = str(status) in spec.ready_values
    fresh_until = (datetime.fromisoformat(observed_at_utc.replace("Z", "+00:00")).astimezone(UTC) + timedelta(seconds=ttl_s)).isoformat().replace("+00:00", "Z")
    locator = f"runtime:{probe_id}"
    facts = (
        applicable,
        make_fact("runtime.ready", ready, source_type="runtime", source_locator=locator,
                  observed_at_utc=observed_at_utc, fresh_until_utc=fresh_until, repo_id=repo_id, evidence=raw),
        make_fact("runtime.sample_count", int(sample), source_type="runtime", source_locator=locator,
                  observed_at_utc=observed_at_utc, fresh_until_utc=fresh_until, repo_id=repo_id, evidence=raw),
    )
    return CollectorResult("runtime", facts, CollectorRun("runtime", "1", int((time.monotonic() - started) * 1000), result.returncode, repo_id=repo_id))


def _nested(raw, path):
    value = raw
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise CollectorError(f"runtime probe missing {'.'.join(path)}")
        value = value[key]
    return value
