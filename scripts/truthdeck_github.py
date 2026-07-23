"""One-call, strict GitHub PR/CI evidence collector."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from truthdeck_collectors import CollectorError, CollectorResult, run_bounded
from truthdeck_model import CollectorRun, make_fact

FIELDS = "number,isDraft,state,mergedAt,mergeCommit,headRefOid,baseRefOid,statusCheckRollup,url"


def collect_github(repo: Path, *, pr: int, observed_at_utc: str, deadline: float, repo_id: str) -> CollectorResult:
    started = time.monotonic()
    version = run_bounded(("gh", "--version"), cwd=repo, deadline=deadline)
    result = run_bounded(("gh", "pr", "view", str(pr), "--json", FIELDS), cwd=repo, deadline=deadline)
    if result.returncode:
        raise CollectorError(f"gh pr view failed: {result.stderr[:200]}")
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CollectorError("gh returned invalid JSON") from exc
    required = set(FIELDS.split(","))
    if not isinstance(raw, dict) or set(raw) != required:
        raise CollectorError(f"gh schema mismatch: {sorted(set(raw) if isinstance(raw, dict) else [])}")
    head = _required_str(raw, "headRefOid")
    checks = raw["statusCheckRollup"]
    if not isinstance(checks, list):
        raise CollectorError("statusCheckRollup must be an array")
    passed = bool(checks) and all(_check_passed(item) for item in checks)
    merged = bool(raw["mergedAt"]) and raw["state"] == "MERGED"
    locator = f"github:pr/{int(raw['number'])}"
    facts = (
        make_fact("pr.head", head, source_type="github", source_locator=locator, observed_at_utc=observed_at_utc, repo_id=repo_id),
        make_fact("ci.head", head, source_type="github", source_locator=locator, observed_at_utc=observed_at_utc, repo_id=repo_id),
        make_fact("ci.passed", passed, source_type="github", source_locator=locator, observed_at_utc=observed_at_utc, repo_id=repo_id),
        make_fact("pr.merged", merged, source_type="github", source_locator=locator, observed_at_utc=observed_at_utc, repo_id=repo_id),
    )
    diagnostics = (version.stdout.splitlines()[0][:120],)
    return CollectorResult("github", facts, CollectorRun("github", "1", int((time.monotonic() - started) * 1000), 0, diagnostics=diagnostics, repo_id=repo_id))


def _required_str(raw: dict[str, Any], key: str) -> str:
    if not isinstance(raw.get(key), str) or not raw[key]:
        raise CollectorError(f"gh field {key} is missing")
    return raw[key]


def _check_passed(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    conclusion = str(item.get("conclusion") or "").upper()
    state = str(item.get("state") or "").upper()
    return conclusion in {"SUCCESS", "NEUTRAL", "SKIPPED"} or state == "SUCCESS"
