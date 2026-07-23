#!/usr/bin/env python3
"""Synchronize the shared CI library to one explicitly named, opted-in repo.

This tool never discovers repositories, edits workflows, changes branch protection,
or activates selected test mode. Missing/invalid adapters leave the target untouched.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from ci_model import (
    CONTRACT_VERSION,
    SYNC_MANIFEST_SCHEMA,
    ContractError,
    canonical_json_bytes,
    contract_hash,
    validate_adapter,
)

SOURCE_ROOT = Path(__file__).resolve().parent
PACKAGE_FILES = ("__init__.py", "schemas.py", "policy.py", "preflight.py")
TARGET_PACKAGE = Path(".ci/_shared/ci_model")
TARGET_MANIFEST = Path(".ci/_shared/ci_model.sync.json")
EXIT_DRIFT = 2
EXIT_POLICY = 10


def _run_git(repo: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise ContractError(f"git {' '.join(args)} timed out") from exc
    if completed.returncode != 0:
        raise ContractError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _under_repo(repo: Path, raw: str) -> Path:
    candidate = Path(raw)
    resolved = (
        candidate.resolve() if candidate.is_absolute() else (repo / candidate).resolve()
    )
    try:
        resolved.relative_to(repo)
    except ValueError as exc:
        raise ContractError(f"path escapes target repository: {raw}") from exc
    return resolved


def _remote_identity(remote: str) -> str:
    value = remote.rstrip("/").removesuffix(".git").replace("\\", "/")
    if "://" in value:
        parts = value.split("/")
        return "/".join(parts[-2:])
    if ":" in value:
        value = value.split(":", 1)[1]
    return "/".join(value.split("/")[-2:])


def _source_payloads(adapter_sha: str) -> dict[Path, bytes]:
    payloads: dict[Path, bytes] = {}
    file_hashes: dict[str, str] = {}
    for name in PACKAGE_FILES:
        source = SOURCE_ROOT / "ci_model" / name
        raw = source.read_bytes()
        destination = TARGET_PACKAGE / name
        payloads[destination] = raw
        file_hashes[destination.as_posix()] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema_version": SYNC_MANIFEST_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "adapter_sha256": adapter_sha,
        "files": file_hashes,
    }
    manifest["manifest_sha256"] = contract_hash(manifest)
    payloads[TARGET_MANIFEST] = canonical_json_bytes(manifest) + b"\n"
    return payloads


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def sync_repo(
    repo: Path, adapter_path: Path, *, write: bool, show_diff: bool
) -> list[str]:
    repo = repo.resolve()
    if (
        _run_git(repo, "rev-parse", "--show-toplevel").replace("\\", "/").lower()
        != str(repo).replace("\\", "/").lower()
    ):
        raise ContractError("--repo must be the exact Git worktree root")
    adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
    if not isinstance(adapter, dict):
        raise ContractError("adapter must contain a JSON object")
    adapter_sha = validate_adapter(adapter)
    remote_identity = _remote_identity(_run_git(repo, "remote", "get-url", "origin"))
    if adapter["repository"].lower() != remote_identity.lower():
        raise ContractError(
            f"adapter repository {adapter['repository']!r} does not match origin {remote_identity!r}"
        )
    drift: list[str] = []
    for relative, expected in _source_payloads(adapter_sha).items():
        target = repo / relative
        resolved_target = target.resolve()
        try:
            resolved_target.relative_to(repo)
        except ValueError as exc:
            raise ContractError(
                f"generated target escapes repository: {relative.as_posix()}"
            ) from exc
        actual = target.read_bytes() if target.exists() else b""
        if actual == expected:
            continue
        drift.append(relative.as_posix())
        if show_diff:
            print(
                "".join(
                    difflib.unified_diff(
                        actual.decode("utf-8", errors="replace").splitlines(True),
                        expected.decode("utf-8").splitlines(True),
                        fromfile=f"a/{relative.as_posix()}",
                        tofile=f"b/{relative.as_posix()}",
                    )
                )
            )
        if write:
            _atomic_write(target, expected)
    return drift


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", required=True, help="one explicit opted-in Git worktree"
    )
    parser.add_argument(
        "--adapter",
        default=".ci/ci-model.json",
        help="adapter JSON path inside --repo",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="check drift (default)")
    action.add_argument(
        "--write", action="store_true", help="write shared files atomically"
    )
    parser.add_argument(
        "--diff", action="store_true", help="show proposed unified diff"
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repo = Path(args.repo).resolve()
        adapter = _under_repo(repo, args.adapter)
        drift = sync_repo(repo, adapter, write=args.write, show_diff=args.diff)
        mode = "WRITE" if args.write else "CHECK"
        if drift:
            print(f"CI MODEL SYNC {mode}: {'UPDATED' if args.write else 'DRIFT'}")
            for path in drift:
                print(f"- {path}")
            return 0 if args.write else EXIT_DRIFT
        print(f"CI MODEL SYNC {mode}: CLEAN")
        return 0
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print("CI MODEL SYNC: STOP", file=sys.stderr)
        print(f"problem: {exc}", file=sys.stderr)
        return EXIT_POLICY


if __name__ == "__main__":
    raise SystemExit(run())
