"""Append-only, concurrent-safe TruthDeck snapshot storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

from truthdeck_model import Snapshot, canonical_json, snapshot_from_dict, snapshot_to_dict


def state_root() -> Path:
    return Path.home() / ".truthdeck"


def store_snapshot(snapshot: Snapshot, *, root: Path | None = None) -> tuple[Path, str]:
    root = (root or state_root()).resolve()
    slug = _scope_slug(snapshot.scope.repos)
    folder = root / "snapshots" / slug
    folder.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(snapshot_to_dict(snapshot)) + b"\n"
    digest = hashlib.sha256(payload).hexdigest()
    stamp = snapshot.observed_at_utc.replace(":", "").replace("-", "")
    final = folder / f"{stamp}-{snapshot.snapshot_id}-{os.getpid()}-{next(tempfile._get_candidate_names())}.json"
    _atomic_write_new(final, payload)
    snapshot_from_dict(json.loads(_read_bytes_retry(final)))
    pointer = {"schema_version": "truthdeck.latest.v1", "target": final.name, "sha256": digest}
    _atomic_replace(folder / "latest.json", canonical_json(pointer) + b"\n")
    read_latest(root=root, scope_repos=snapshot.scope.repos)
    return final, digest


def read_snapshot(path: Path) -> Snapshot:
    return snapshot_from_dict(json.loads(path.read_text(encoding="utf-8")))


def read_latest(*, root: Path | None = None, scope_repos: tuple[str, ...]) -> tuple[Snapshot, Path]:
    folder = (root or state_root()).resolve() / "snapshots" / _scope_slug(scope_repos)
    pointer_path = folder / "latest.json"
    pointer = json.loads(_read_bytes_retry(pointer_path))
    if set(pointer) != {"schema_version", "target", "sha256"} or pointer["schema_version"] != "truthdeck.latest.v1":
        raise ValueError("invalid latest pointer")
    target = (folder / str(pointer["target"])).resolve()
    if target.parent != folder.resolve():
        raise ValueError("latest pointer escapes snapshot folder")
    payload = _read_bytes_retry(target)
    if hashlib.sha256(payload).hexdigest() != pointer["sha256"]:
        raise ValueError("latest pointer digest mismatch")
    return snapshot_from_dict(json.loads(payload)), target


def write_explicit(path: Path, payload: bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_replace(path, payload)


def _atomic_write_new(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(path)
    _write_and_sync(path, payload, exclusive=True)


def _atomic_replace(path: Path, payload: bytes) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_retry(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _write_and_sync(path: Path, payload: bytes, *, exclusive: bool) -> None:
    mode = "xb" if exclusive else "wb"
    with path.open(mode) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _scope_slug(repos: tuple[str, ...]) -> str:
    raw = "--".join(repos) or "global"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-.").lower()
    return (slug[:80] or "global")


def _read_bytes_retry(path: Path) -> bytes:
    for attempt in range(20):
        try:
            return path.read_bytes()
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.01)
    raise AssertionError("unreachable")


def _replace_retry(source: Path, target: Path) -> None:
    for attempt in range(50):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.01)
