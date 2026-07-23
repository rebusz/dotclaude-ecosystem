"""Inert handoff and exact-head reviewer artifact verification."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from truthdeck_model import CollectorRun, FactState, make_fact
from truthdeck_collectors import CollectorResult, run_bounded

SHA_RE = re.compile(r"\b[0-9a-fA-F]{40}\b")


def verify_handoff(path: Path, expected_sha256: str, *, observed_at_utc: str,
                   repo_id: str | None = None, repo: Path | None = None):
    payload = path.resolve(strict=True).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    valid = digest.lower() == expected_sha256.lower()
    text = payload.decode("utf-8", "replace")
    refs = tuple(sorted(set(SHA_RE.findall(text))))
    live = _live_references(repo, text, refs) if repo else {"references_valid": None, "base_fresh": None}
    continuation_state = "BLOCKED" if not valid else "HOLD" if repo and not all(live.values()) else "PASS"
    fact = make_fact("handoff.valid", valid, state=FactState.OBSERVED, source_type="handoff",
                     source_locator=f"handoff:{path.name}", observed_at_utc=observed_at_utc,
                     repo_id=repo_id, evidence={"sha256": digest, "refs": refs})
    return fact, {"sha256": digest, "references": refs, "valid": valid, **live,
                  "authorization": "ASSERTED_UNVERIFIED", "continuation_state": continuation_state}


def collect_artifact(path: Path, *, observed_at_utc: str, repo_id: str | None = None) -> CollectorResult:
    started = time.monotonic()
    resolved = path.resolve(strict=True)
    payload = resolved.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    valid = resolved.suffix.lower() in {".json", ".md", ".txt"} and bool(payload)
    locator = f"artifact:{resolved.name}"
    facts = (
        make_fact("artifact.valid", valid, source_type="artifact", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id, evidence=digest),
        make_fact("artifact.sha256", digest, source_type="artifact", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id),
    )
    return CollectorResult("artifact", facts, CollectorRun("artifact", "1", int((time.monotonic() - started) * 1000), 0, repo_id=repo_id))


def collect_review(packet: Path, reviewer_output: Path, *, expected_head: str,
                   observed_at_utc: str, repo_id: str | None = None):
    packet_text = packet.resolve(strict=True).read_text(encoding="utf-8")
    review_text = reviewer_output.resolve(strict=True).read_text(encoding="utf-8")
    packet_head = _extract(packet_text, r"(?:Head SHA:\s*`?|REVIEWED_HEAD:\s*)([0-9a-fA-F]{40})")
    reviewed_head = _extract(review_text, r"REVIEWED_HEAD:\s*([0-9a-fA-F]{40})")
    if packet_head != expected_head or reviewed_head is None:
        reviewed_head = reviewed_head or packet_head or "missing"
    verdict = _extract_word(review_text, r"VERDICT:\s*(PASS|BLOCKED|FAIL)")
    count = _extract_word(review_text, r"SHIP_BLOCKING_COUNT:\s*(\d+)")
    blocking = int(count) if count is not None else 1
    if verdict != "PASS":
        blocking = max(1, blocking)
    locator = f"review:{reviewer_output.name}"
    return (
        make_fact("review.head", reviewed_head, source_type="review", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id,
                  evidence={"packet_head": packet_head, "reviewed_head": reviewed_head}),
        make_fact("review.blocking_findings", blocking, source_type="review", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id),
    )


def _extract(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1).lower() if match else None


def _extract_word(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _live_references(repo: Path, text: str, refs: tuple[str, ...]) -> dict[str, bool]:
    root = repo.resolve(strict=True)
    deadline = time.monotonic() + 5.0
    references_valid = True
    for ref in refs[:20]:
        result = run_bounded(("git", "-C", str(root), "cat-file", "-e", f"{ref}^{{commit}}"),
                             cwd=root, deadline=deadline)
        references_valid = references_valid and result.returncode == 0
    base = _extract(text, r"Base SHA:\s*`?([0-9a-fA-F]{40})")
    current = run_bounded(("git", "-C", str(root), "rev-parse", "HEAD"), cwd=root, deadline=deadline)
    base_fresh = base is None or (current.returncode == 0 and current.stdout.strip().lower() == base)
    return {"references_valid": references_valid, "base_fresh": base_fresh}
