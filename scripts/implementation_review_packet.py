#!/usr/bin/env python3
"""Build a deterministic implementation-review packet from a Git diff.

The packet is intentionally provider-neutral: every external reviewer receives
the exact base/head range, validation evidence, and diff, while GitHub-aware
lanes also receive the repository and draft-PR URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

from secret_patterns import find_high_confidence, is_sensitive_path


DEFAULT_MAX_DIFF_CHARS = 180_000
PACKET_SCHEMA_VERSION = "implementation-review/v1"


class PacketError(RuntimeError):
    """Raised when the requested Git review surface cannot be resolved."""


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise PacketError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout.strip()


def _resolve_commit(repo: Path, value: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{value}^{{commit}}")


def _github_url_from_remote(remote: str) -> str:
    remote = remote.strip()
    match = re.fullmatch(r"git@github\.com:(.+?)(?:\.git)?", remote)
    if match:
        return f"https://github.com/{match.group(1).removesuffix('.git')}"
    match = re.fullmatch(r"ssh://git@github\.com/(.+?)(?:\.git)?", remote)
    if match:
        return f"https://github.com/{match.group(1).removesuffix('.git')}"
    if remote.startswith("https://github.com/"):
        return remote.removesuffix(".git")
    return remote


def _changed_paths(name_status: str) -> list[str]:
    paths: list[str] = []
    for line in name_status.splitlines():
        fields = line.split("\t")
        paths.extend(field.replace("\\", "/") for field in fields[1:])
    return paths


def _reject_sensitive_content(name_status: str, diff: str) -> None:
    sensitive_paths = [path for path in _changed_paths(name_status) if is_sensitive_path(path)]
    if sensitive_paths:
        raise PacketError(
            "refusing external review packet for sensitive path(s): "
            + ", ".join(sensitive_paths)
        )
    _reject_secret_text(diff)


def _reject_secret_text(text: str) -> None:
    """Fail closed on any high-confidence secret shape, wherever it appears.

    The patterns come from `secret_patterns`, shared with every other detector
    in the repo. This gate used to carry its own four patterns and missed every
    modern LLM key, `github_pat_` tokens, JWTs and connection strings (audit F5).
    """
    found = find_high_confidence(text)
    if found:
        raise PacketError(
            "refusing external review packet: high-confidence secret pattern(s): "
            + ", ".join(found)
        )


def _repo_label(repo: Path, github_repo: str) -> str:
    if github_repo.startswith("https://github.com/"):
        return github_repo.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    return repo.name


def build_packet(
    *,
    repo: Path,
    start_sha: str,
    end_sha: str,
    mode: str,
    risk: str,
    plan_path: str = "",
    pr_url: str = "",
    github_repo: str = "",
    validation: str = "",
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS,
    external_publication_approved: bool = False,
) -> str:
    repo = repo.resolve()
    if not (repo / ".git").exists():
        raise PacketError(f"not a Git checkout: {repo}")

    start = _resolve_commit(repo, start_sha)
    end = _resolve_commit(repo, end_sha)
    if start == end:
        raise PacketError("review range is empty: start_sha equals end_sha")

    names = _git(repo, "diff", "--name-status", "--find-renames", start, end)
    stat = _git(repo, "diff", "--stat", "--find-renames", start, end)
    diff = _git(
        repo,
        "diff",
        "--no-ext-diff",
        "--find-renames",
        "--find-copies",
        start,
        end,
    )
    if not names or not diff:
        raise PacketError(f"review range has no changed files: {start}..{end}")
    _reject_sensitive_content(names, diff)
    if risk in {"R2", "R3"} and not external_publication_approved:
        raise PacketError(
            f"{risk} requires explicit operator approval for external publication"
        )

    if not github_repo:
        try:
            github_repo = _github_url_from_remote(_git(repo, "remote", "get-url", "origin"))
        except PacketError:
            github_repo = ""

    original_chars = len(diff)
    diff_sha256 = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    truncated = original_chars > max_diff_chars
    if truncated:
        diff = diff[:max_diff_chars].rsplit("\n", 1)[0]
        diff += (
            "\n\n[DIFF TRUNCATED IN PACKET — inspect the exact draft PR / commit range "
            "before returning a verdict.]"
        )

    validation = validation.strip() or "Not supplied — reviewer must treat validation as unverified."
    plan_path = plan_path.strip() or "(none supplied)"
    pr_url = pr_url.strip() or "(not available)"
    github_repo = github_repo.strip() or "(not available)"
    changed_count = len([line for line in names.splitlines() if line.strip()])

    packet = f"""# External Implementation Review Packet

## Review contract

Review the exact implementation range below. Prioritize correctness, safety,
robustness, regression risk, and agreement with the named plan. Report only:

- `SHIP-BLOCKING`: must be fixed before merge.
- `FIX-LATER`: valid non-blocking issue.
- `NO FINDINGS`: only when the supplied evidence supports it.

Do not review the repository default branch in place of the exact head SHA or
draft PR. Cite file paths and changed lines for every finding.

### Required reviewer output

End your response with the following attestation. `REVIEWED_HEAD` is already
pinned; copy it exactly. Select one concrete value for each remaining field.
A verdict without this completed reviewer output cannot clear the gate:

```text
REVIEWED_HEAD: {end}
REVIEW_SOURCE: draft-pr OR transmitted-packet
TRANSMISSION_COMPLETE: yes OR no OR unknown
```

## Identity

- Mode: `{mode}`
- Risk class: `{risk}`
- Packet schema: `{PACKET_SCHEMA_VERSION}`
- Repository label: `{_repo_label(repo, github_repo)}`
- GitHub repository: {github_repo}
- Draft PR: {pr_url}
- Base SHA: `{start}`
- Head SHA: `{end}`
- Plan: `{plan_path}`
- Changed files: {changed_count}
- Diff characters: {original_chars}
- Full diff SHA-256: `{diff_sha256}`
- Local packet diff truncated: {str(truncated).lower()}
- Transmission completeness: unverified by packet generator

## Validation evidence

{validation}

## Changed files

```text
{names}
```

## Diff stat

```text
{stat}
```

## Exact diff

```diff
{diff}
```
"""
    # Scan the packet as it will be published, not just the diff. Validation
    # evidence arrives from `--validation`/`--validation-file` -- pytest output,
    # CI logs, env dumps -- and was interpolated verbatim with no scan at all,
    # walking straight past the one gate documented as failing closed (audit F3).
    _reject_secret_text(packet)
    return packet


def _default_output(repo: Path, end_sha: str) -> Path:
    safe_repo = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo.name).strip("-") or "repo"
    root = Path(tempfile.gettempdir()) / "implementation-review-packets"
    return root / f"{safe_repo}-{end_sha[:12]}.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--start-sha", required=True)
    parser.add_argument("--end-sha", default="HEAD")
    parser.add_argument("--mode", choices=["IMPLEMENT", "EXECUTOR"], required=True)
    parser.add_argument("--risk", choices=["R0", "R1", "R2", "R3"], required=True)
    parser.add_argument("--plan-path", default="")
    parser.add_argument("--pr-url", default="")
    parser.add_argument("--github-repo", default="")
    parser.add_argument("--validation", default="")
    parser.add_argument("--validation-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-diff-chars", type=int, default=DEFAULT_MAX_DIFF_CHARS)
    parser.add_argument(
        "--external-publication-approved",
        action="store_true",
        help="Required for R2/R3 after the operator approved sending the diff to external reviewers.",
    )
    args = parser.parse_args(argv)

    if args.max_diff_chars < 1:
        parser.error("--max-diff-chars must be positive")
    validation = args.validation
    if args.validation_file:
        validation = args.validation_file.read_text(encoding="utf-8", errors="replace")

    try:
        end = _resolve_commit(args.repo.resolve(), args.end_sha)
        packet = build_packet(
            repo=args.repo,
            start_sha=args.start_sha,
            end_sha=end,
            mode=args.mode,
            risk=args.risk,
            plan_path=args.plan_path,
            pr_url=args.pr_url,
            github_repo=args.github_repo,
            validation=validation,
            max_diff_chars=args.max_diff_chars,
            external_publication_approved=args.external_publication_approved,
        )
    except (OSError, PacketError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")

    output = (args.output or _default_output(args.repo.resolve(), end)).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(packet)
        temp_output = Path(handle.name)
    temp_output.replace(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
