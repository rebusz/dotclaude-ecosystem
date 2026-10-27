#!/usr/bin/env python3
"""Shared helpers for the dispatch-enforcement hooks. Stdlib only; import creates no files."""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import hook_stdio

COORDINATOR_LINE = (
    "You are a Tier-2 coordinator: all code, tests, reviews and diagnosis "
    "go through `dispatch.py lane`; you only relay, commit and glue."
)
SOURCE_EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
SUPERVISOR_READ_CAP = 150 * 1024
TIER2_READ_CAP = 400 * 1024
SINGLE_READ_CAP = 40 * 1024
TIER2_EDIT_LINE_CAP = 20
BIG_OUTPUT_WARN = 30 * 1024
STATE_ENV = "DISPATCH_GUARD_STATE_DIR"
OVERRIDE_FILE = "dispatch_override.json"
KEY_FILE_ENV = "DISPATCH_GUARD_KEY_FILE"

_TEST_KEY_ENV = "DISPATCH_GUARD_TEST_KEY"
_TIER_ENV = "DISPATCH_GUARD_TIER"
_COUNTERS_FILE = "dispatch_counters.json"
_TIER2_FILE = "tier2_sessions.json"
_FLAGS_DIR = "dispatch_flags"
_LANE_QUEUE_DIR = "lane_queue"
_LOCK_STALE_S = 30.0
_LOCK_WAIT_S = 5.0
_TTL_MIN_S = 60
_TTL_MAX_S = 28800
_CRYPTPROTECT_UI_FORBIDDEN = 0x01
_OVERRIDE_SCOPES = frozenset({"workers", "hooks_off"})
_DONE_JOB_STATUSES = frozenset({"done", "cancelled"})
_ALLOW_SUFFIXES = (".log", ".md", ".json")
_ALLOW_DIR_MARKERS = (
    "/design/",
    "/handoffs/",
    "/memory/",
    "/receipts/",
    "/verdicts/",
    "/lane_receipts/",
    "/lane_queue/",
    "/scratchpad/",
    "/.claude/state/",
    "/.claude/projects/",
)
_DPAPI: tuple[ctypes.WinDLL, ctypes.WinDLL] | None = None

GUARDED_PATH_PATTERNS = [
    re.compile(re.escape(piece), re.IGNORECASE)
    for piece in (
        "/.claude/hooks/",
        "/.claude/settings",
        "allow_claude_workers",
        "dispatch_override",
        "lane_health.json",
        "/lane_queue/",
        "override.key",
    )
]
GUARDED_PATH_PATTERNS.append(
    re.compile(
        r"scripts/(dispatch_[a-z_]*guard|claude_worker_guard|lane_authorize|"
        r"dispatch_guard_common|dispatch_tier_marker)\.py",
        re.IGNORECASE,
    )
)

def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env

def state_dir(env: Mapping[str, str] | None = None) -> Path:
    raw = _env(env).get(STATE_ENV)
    path = Path(raw) if raw else Path.home() / ".claude" / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path

def read_payload() -> dict:
    text = hook_stdio.read_stdin_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("payload is not a JSON object")
    return data

def deny(reason: str, event: str = "PreToolUse") -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }

def context(text: str, event: str = "PreToolUse") -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": text,
        }
    }

def block(reason: str) -> dict:
    return {"decision": "block", "reason": reason}

def run_guarded(
    hook_file: str,
    fn: Callable[[], dict | None],
    event: str = "PreToolUse",
) -> int:
    try:
        result = fn()
    except Exception as exc:
        reason = (
            f"{hook_file} crashed: {type(exc).__name__}: {exc}. "
            "Guarded tool call blocked (fail closed). "
            "Operator emergency-off: python scripts/lane_authorize.py "
            "--interactive --scope hooks_off"
        )
        result = block(reason) if event == "PostToolUse" else deny(reason, event)
    if result is not None:
        hook_stdio.force_utf8_stdio()
        print(json.dumps(result), flush=True)
    return 0

def agent_key(payload: dict) -> str:
    agent_id = payload.get("agent_id")
    if agent_id:
        return str(agent_id)
    return "session:" + str(payload.get("session_id") or "")

def _tier2_ids(env: Mapping[str, str] | None) -> set[str]:
    path = state_dir(env) / _TIER2_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return set()
    if not isinstance(raw, list):
        return set()
    return {item for item in raw if isinstance(item, str) and item}

def is_tier2(payload: dict, env: Mapping[str, str] | None = None) -> bool:
    forced = _env(env).get(_TIER_ENV)
    if forced == "supervisor":
        return False
    if payload.get("agent_id"):
        return True
    if forced == "tier2":
        return True
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return False
    return session_id in _tier2_ids(env)

def mark_tier2_session(session_id: str, env: Mapping[str, str] | None = None) -> None:
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id must be a non-empty string")
    path = state_dir(env) / _TIER2_FILE
    lock = _lock_for(path)
    fd, token = _acquire_lock(lock)
    try:
        ids = _tier2_ids(env)
        ids.add(session_id)
        body = json.dumps(sorted(ids), ensure_ascii=False).encode("utf-8") + b"\n"
        _atomic_replace(path, body)
    finally:
        _release_lock(fd, lock, token)

def norm_path(p: str) -> str:
    return str(Path(os.path.expandvars(p)).expanduser()).replace("\\", "/")

def is_source_path(p: str) -> bool:
    return Path(p).suffix.lower() in SOURCE_EXTS

def is_allowlisted_read(p: str) -> bool:
    normal = norm_path(p).lower()
    if any(marker in normal for marker in _ALLOW_DIR_MARKERS):
        return True
    return Path(normal).suffix in _ALLOW_SUFFIXES

class _DATA_BLOB(ctypes.Structure):
    _fields_ = (
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    )

def _dpapi_libs() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    global _DPAPI
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")
    if _DPAPI is not None:
        return _DPAPI
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_p = ctypes.POINTER(_DATA_BLOB)
    void = ctypes.c_void_p
    dword = ctypes.c_uint32
    crypt32.CryptProtectData.argtypes = [
        blob_p, ctypes.c_wchar_p, blob_p, void, void, dword, blob_p,
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int
    crypt32.CryptUnprotectData.argtypes = [
        blob_p, ctypes.POINTER(ctypes.c_wchar_p), blob_p, void, void, dword, blob_p,
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [void]
    kernel32.LocalFree.restype = void
    _DPAPI = (crypt32, kernel32)
    return _DPAPI

def _blob_from(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer

def _copy_and_free(blob: _DATA_BLOB, kernel32: ctypes.WinDLL) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        address = ctypes.cast(blob.pbData, ctypes.c_void_p).value
        if address:
            kernel32.LocalFree(address)

def _crypt(data: bytes, *, protect: bool) -> bytes:
    crypt32, kernel32 = _dpapi_libs()
    blob_in, _hold = _blob_from(data)
    blob_out = _DATA_BLOB()
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = call(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return _copy_and_free(blob_out, kernel32)

def dpapi_protect(data: bytes) -> bytes:
    return _crypt(data, protect=True)

def dpapi_unprotect(blob: bytes) -> bytes:
    return _crypt(blob, protect=False)

def _key_file(env: Mapping[str, str] | None) -> Path:
    mapping = _env(env)
    override = mapping.get(KEY_FILE_ENV)
    if override:
        return Path(override)
    local = mapping.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home()
    return base / "TsignalDispatch" / "override.key.dpapi"

def load_or_create_key(
    create: bool = False, env: Mapping[str, str] | None = None,
) -> bytes | None:
    mapping = _env(env)
    test_key = mapping.get(_TEST_KEY_ENV, "").strip()
    if test_key:
        return bytes.fromhex(test_key)
    path = _key_file(env)
    if path.is_file():
        return dpapi_unprotect(path.read_bytes())
    if not create:
        return None
    key = secrets.token_bytes(32)
    protected = dpapi_protect(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        return dpapi_unprotect(path.read_bytes())
    try:
        os.write(fd, protected)
    finally:
        os.close(fd)
    return key

def sign_token(key: bytes, scope: str, exp: int, nonce: str) -> str:
    message = f"{scope}|{exp}|{nonce}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()

def write_override(
    scope: str, ttl_s: int, env: Mapping[str, str] | None = None,
) -> Path:
    if scope not in _OVERRIDE_SCOPES:
        raise ValueError("scope must be 'workers' or 'hooks_off'")
    ttl = int(ttl_s)
    if ttl < _TTL_MIN_S:
        ttl = _TTL_MIN_S
    elif ttl > _TTL_MAX_S:
        ttl = _TTL_MAX_S
    key = load_or_create_key(create=False, env=env)
    if not key:
        raise RuntimeError("override key is missing")
    nonce = secrets.token_hex(16)
    exp = int(time.time()) + ttl
    body = {
        "scope": scope,
        "exp": exp,
        "nonce": nonce,
        "sig": sign_token(key, scope, exp, nonce),
    }
    path = state_dir(env) / OVERRIDE_FILE
    payload = json.dumps(body, separators=(",", ":")).encode("utf-8") + b"\n"
    lock = _lock_for(path)
    fd, token = _acquire_lock(lock)
    try:
        _atomic_replace(path, payload)
    finally:
        _release_lock(fd, lock, token)
    return path

def override_active(
    scope: str,
    env: Mapping[str, str] | None = None,
    now: float | None = None,
) -> bool:
    try:
        path = state_dir(env) / OVERRIDE_FILE
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return False
        token_scope = raw.get("scope")
        exp = raw.get("exp")
        nonce = raw.get("nonce")
        sig = raw.get("sig")
        if not isinstance(token_scope, str) or token_scope not in _OVERRIDE_SCOPES:
            return False
        if type(exp) is not int or not isinstance(nonce, str) or not isinstance(sig, str):
            return False
        if token_scope != scope and token_scope != "hooks_off":
            return False
        current = time.time() if now is None else float(now)
        if not exp > current:
            return False
        key = load_or_create_key(create=False, env=env)
        if not key:
            return False
        expected = sign_token(key, token_scope, exp, nonce)
        if len(expected) != len(sig):
            return False
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False

def _lock_for(path: Path) -> Path:
    return path.with_name(path.name + ".lock")

def _lock_is_stale(lock_path: Path) -> bool:
    try:
        modified = lock_path.stat().st_mtime
    except FileNotFoundError:
        return False
    return (time.time() - modified) >= _LOCK_STALE_S

def _try_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        return

def _acquire_lock(lock_path: Path) -> tuple[int, bytes]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}:{time.time_ns()}:{secrets.token_hex(8)}".encode("ascii")
    deadline = time.monotonic() + _LOCK_WAIT_S
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        except (FileExistsError, PermissionError):
            if _lock_is_stale(lock_path):
                _try_unlink(lock_path)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock {lock_path.name}")
            time.sleep(0.02)
            continue
        try:
            os.write(fd, token)
        except OSError:
            os.close(fd)
            _try_unlink(lock_path)
            raise
        return fd, token

def _release_lock(fd: int, lock_path: Path, token: bytes) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        if lock_path.read_bytes() != token:
            return
    except OSError:
        return
    _try_unlink(lock_path)

def _atomic_replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent),
    )
    try:
        os.write(fd, payload)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp_name, path)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(tmp_name):
            _try_unlink(Path(tmp_name))

def _read_object(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return raw

def bump_counter(
    name: str, key: str, delta: int, env: Mapping[str, str] | None = None,
) -> int:
    if isinstance(delta, bool) or not isinstance(delta, int):
        raise TypeError("delta must be an int")
    path = state_dir(env) / _COUNTERS_FILE
    lock = _lock_for(path)
    fd, token = _acquire_lock(lock)
    try:
        data = _read_object(path)
        bucket = data.get(name)
        if not isinstance(bucket, dict):
            bucket = {}
        current = bucket.get(key, 0)
        if type(current) is not int:
            current = 0
        if delta == 0:
            return current
        total = current + delta
        bucket[key] = total
        data[name] = bucket
        payload = json.dumps(data, separators=(",", ":")).encode("utf-8") + b"\n"
        _atomic_replace(path, payload)
        return total
    finally:
        _release_lock(fd, lock, token)

def get_counter(name: str, key: str, env: Mapping[str, str] | None = None) -> int:
    return bump_counter(name, key, 0, env)

def _flag_path(name: str, key: str, env: Mapping[str, str] | None) -> Path:
    digest = hashlib.sha256(f"{name}\0{key}".encode("utf-8")).hexdigest()[:16]
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:40] or "flag"
    safe_key = re.sub(r"[^A-Za-z0-9._-]+", "_", key)[:40]
    return state_dir(env) / _FLAGS_DIR / f"{safe_name}__{safe_key}__{digest}"

def set_flag(name: str, key: str, env: Mapping[str, str] | None = None) -> None:
    path = _flag_path(name, key, env)
    lock = _lock_for(path)
    fd, token = _acquire_lock(lock)
    try:
        _atomic_replace(path, b"1\n")
    finally:
        _release_lock(fd, lock, token)

def has_flag(name: str, key: str, env: Mapping[str, str] | None = None) -> bool:
    return _flag_path(name, key, env).is_file()

def lane_repair_job_exists(job_id: str, env: Mapping[str, str] | None = None) -> bool:
    try:
        if not isinstance(job_id, str) or not job_id or job_id in {".", ".."}:
            return False
        if Path(job_id).name != job_id or ":" in job_id:
            return False
        path = state_dir(env) / _LANE_QUEUE_DIR / f"{job_id}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("kind") != "lane_repair":
            return False
        return raw.get("status") not in _DONE_JOB_STATUSES
    except Exception:
        return False
