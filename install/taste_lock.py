#!/usr/bin/env python3
"""Validate skills/taste-skill.lock.json and print one field for the installers.

The taste installers feed lockfile values to `git clone`, `git checkout`,
`npx`, and `rm -rf` / `Remove-Item -Recurse -Force`. Unvalidated, a lockfile
edit could turn the source into a git option (`--upload-pack=...`), or a skill
name into `../../..` for the recursive delete (audit P2-19). Both installers
call this one validator instead of each parsing the JSON themselves, so the
rules cannot drift between the shell and PowerShell copies.

Usage:
    python taste_lock.py <lockfile> source|commit|cli
    python taste_lock.py <lockfile> installed|agents     # one per line
Exit 2 with a message on stderr when the lockfile is invalid.
"""
from __future__ import annotations

import json
import re
import sys

_SOURCE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?(\.git)?$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
# npm package spec with an exact version: no ranges, no tags, no URLs.
_CLI = re.compile(r"^[a-z0-9][a-z0-9._-]*@\d+\.\d+\.\d+$")


class LockError(ValueError):
    pass


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        lock = json.load(handle)
    if not isinstance(lock, dict):
        raise LockError("lockfile is not a JSON object")
    checks = (("source", _SOURCE), ("pinned_commit", _COMMIT), ("cli_package", _CLI))
    for key, pattern in checks:
        value = lock.get(key)
        if not isinstance(value, str) or not pattern.match(value):
            raise LockError(f"{key} is missing or not an allowed value: {value!r}")
    for key in ("installed", "agents"):
        names = lock.get(key)
        if not isinstance(names, list) or not names:
            raise LockError(f"{key} must be a non-empty list")
        for name in names:
            if not isinstance(name, str) or not _NAME.match(name):
                raise LockError(f"{key} entry is not a plain name: {name!r}")
    return lock


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        lock = load(argv[1])
    except (OSError, json.JSONDecodeError, LockError) as exc:
        print(f"taste lockfile rejected: {exc}", file=sys.stderr)
        return 2
    field = argv[2]
    scalar = {"source": "source", "commit": "pinned_commit", "cli": "cli_package"}
    if field in scalar:
        print(lock[scalar[field]])
    elif field in ("installed", "agents"):
        print("\n".join(lock[field]))
    else:
        print(f"unknown field: {field}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
