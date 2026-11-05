#!/usr/bin/env python3
"""Operator-only signed TTL override (R6).

Grant needs a real TTY on stdin and stdout plus the exact word GO. Argv, env,
files, and MCP cannot grant it. Revoke and status need a TTY too. Import creates no files.
"""

from __future__ import annotations

import argparse
import hmac
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hook_stdio  # noqa: E402 - sibling import; UTF-8 stdin seam
from dispatch_guard_common import (  # noqa: E402
    OVERRIDE_FILE,
    load_or_create_key,
    override_active,
    state_dir,
    write_override,
)

_TTY_MESSAGE = "lane_authorize: operator-only, needs a real terminal"
_MAX_TTL_MINUTES = 480
_GO = "GO"


def main(argv: list[str] | None = None) -> int:
    """Grant, revoke, or report. A missing TTY exits 2 and writes nothing."""
    if not _operator_tty():
        print(_TTY_MESSAGE, file=sys.stderr)
        return 2
    args = _parser().parse_args(argv)
    if args.status and args.revoke:
        print("lane_authorize: --status and --revoke cannot be combined", file=sys.stderr)
        return 2
    if args.status:
        return _status()
    if args.revoke:
        return _revoke()
    if not args.interactive:
        print("lane_authorize: --interactive is required to grant an override", file=sys.stderr)
        return 2
    return _grant(args.scope, args.ttl_minutes)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operator-only dispatch override authorisation.")
    parser.add_argument("--interactive", action="store_true", help="Prompt for GO, then write the token.")
    parser.add_argument("--scope", choices=("workers", "hooks_off"), default="workers")
    parser.add_argument("--ttl-minutes", type=_ttl_minutes, default=60, help="Lifetime in minutes (1..480).")
    parser.add_argument("--revoke", action="store_true", help="Delete the override token.")
    parser.add_argument("--status", action="store_true", help="Print the current override.")
    return parser


def _ttl_minutes(value: str) -> int:
    try:
        minutes = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--ttl-minutes must be an integer") from exc
    if not 1 <= minutes <= _MAX_TTL_MINUTES:
        raise argparse.ArgumentTypeError(f"--ttl-minutes must be from 1 to {_MAX_TTL_MINUTES}")
    return minutes


def _operator_tty() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def _grant(scope: str, ttl_minutes: int) -> int:
    print(f"scope={scope} ttl_minutes={ttl_minutes}\nType exactly GO:", flush=True)
    try:
        line = _read_line()
    except OSError as exc:
        return _fail(exc)
    if not _is_exact_go(line):
        print("lane_authorize: confirmation was not exactly GO", file=sys.stderr)
        return 1
    try:
        if not load_or_create_key(create=True):
            raise RuntimeError("override key is missing")
        path = write_override(scope, ttl_minutes * 60)
        exp = int(json.loads(path.read_text(encoding="utf-8"))["exp"])
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        return _fail(exc)
    stamp = datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"authorised scope={scope} exp={exp} expires={stamp}")
    return 0


def _revoke() -> int:
    path = state_dir() / OVERRIDE_FILE
    try:
        path.unlink()
    except FileNotFoundError:
        print("no override file")
        return 0
    except OSError as exc:
        return _fail(exc)
    print(f"revoked {path}")
    return 0


def _status() -> int:
    path = state_dir() / OVERRIDE_FILE
    workers = override_active("workers")
    hooks_off = override_active("hooks_off")
    if not path.is_file():
        print("override: none")
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        return _fail(exc)
    print(
        f"override: scope={raw.get('scope')} exp={raw.get('exp')} "
        f"workers_active={str(workers).lower()} hooks_off_active={str(hooks_off).lower()}"
    )
    return 0


def _read_line() -> str:
    """Read one stdin line as UTF-8, using the hook_stdio buffer seam."""
    hook_stdio.force_utf8_stdio()
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin.readline()
    return buffer.readline().decode("utf-8", errors="replace")


def _is_exact_go(line: str) -> bool:
    token = line.rstrip("\r\n")
    return len(token) == len(_GO) and hmac.compare_digest(token, _GO)


def _fail(exc: BaseException) -> int:
    print(f"lane_authorize: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
