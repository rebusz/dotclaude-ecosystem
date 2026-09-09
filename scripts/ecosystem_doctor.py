#!/usr/bin/env python3
"""One line the operator cannot miss, folded from detectors that already exist.

The 2026-09-09 audit found the same defect in five places: a detector that is
correct, fires, exits non-zero, and reports into a file nobody reads.

  * `hooks_install status` returned exit 3 / `overall: MISSING` while every hook
    was wired twice, half of them from a worktree frozen weeks earlier.
  * `git_hygiene` had been writing `MANAGED HOOKS: COLLISION` into
    ~/.claude/state/git_hygiene/ every day since at least 2026-09-04.
  * 1,601 session verdicts had been produced and 0 ever consumed.
  * Six atomic-write temp files had been orphaned since May.

None of it was wrong. None of it arrived anywhere. This module adds no checks of
its own on purpose -- it calls the existing ones, folds their verdicts, and
returns both a bounded human line and an exit code, so the same signal can reach
a SessionStart context line and a CI job instead of a text file.

Modes
-----
  (default)   one line, <= LINE_BUDGET chars, for the session context
  --report    the same verdicts, one per line, for a terminal
  --json      machine-readable
  --full      additionally run the slow installed-artifact drift check

Exit codes: 0 clean; 2 could not check (no ecosystem deployed here, or the
manifest is unreadable); 3 dirty -- at least one detector is unhappy.

Everything on the default path is bounded by `--budget-s` (default 1.5s) and
reads cached state only, because the SessionStart hook that consumes it has a
5s ceiling. `--full` is for a terminal or CI, never for the hook.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LINE_BUDGET = 200

# A verdict backlog is normal; an unbounded one means the consumer is dead.
# 1,601 unconsumed verdicts is what the audit measured, so the ceiling sits far
# below that and far above a busy week.
VERDICT_BACKLOG_CEILING = 400
# Atomic writes clean up after themselves; a hook killed at its harness timeout
# cannot. A handful is noise, a pile means something is dying repeatedly.
LEAKED_TMP_CEILING = 3
# The janitor is scheduled daily. Twice that is a scheduler that stopped.
JANITOR_STALE_HOURS = 48

_ALARM_LINE = re.compile(r"^\s*!\s")

# Once, at import. Doing this inside the check appended an entry to sys.path on
# every call, which grows without bound in any process that calls it more than
# once and slows every later import.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    checked: bool = True  # False when the check could not run at all

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "checked": self.checked}


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def dirty(self) -> list[Check]:
        return [c for c in self.checks if c.checked and not c.ok]

    @property
    def unchecked(self) -> list[Check]:
        return [c for c in self.checks if not c.checked]

    def exit_code(self) -> int:
        if self.dirty:
            return 3
        if not [c for c in self.checks if c.checked]:
            return 2  # nothing could be verified: do not report "clean"
        return 0

    def line(self) -> str:
        """One bounded line. Names what is wrong, never what is right."""
        if not [c for c in self.checks if c.checked]:
            return "[ecosystem] no checks could run; see: python scripts/ecosystem_doctor.py --report"
        bad = self.dirty
        if not bad:
            return f"[ecosystem] {len(self.checks)} checks clean."
        head = "[ecosystem] NEEDS ATTENTION: "
        tail = " -- python scripts/ecosystem_doctor.py --report"
        room = LINE_BUDGET - len(head) - len(tail)
        parts: list[str] = []
        for check in bad:
            candidate = f"{check.name}={check.detail}"
            if len("; ".join(parts + [candidate])) > room:
                parts.append(f"+{len(bad) - len(parts)} more")
                break
            parts.append(candidate)
        return head + "; ".join(parts) + tail

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code(),
            "line": self.line(),
            "checks": [c.to_dict() for c in self.checks],
        }


def _default_state_dir(home: Path) -> Path:
    """Mirror session_state: the state dir is overridable, home is not."""
    override = os.environ.get("CLAUDE_SESSION_STATE_DIR")
    if override:
        return Path(override).expanduser()
    return home / ".claude" / "state"


def _check_hook_block(home: Path, checkout: Path | None) -> Check:
    """Ask the installer's own status; it already knows and already exits 3."""
    try:
        import hooks_install
    except Exception as exc:  # pragma: no cover - import failure is a deploy signal
        return Check("hooks", False, f"unavailable ({type(exc).__name__})", checked=False)
    # "Not installed into this home" is a different answer from "installed and
    # broken", and only the second is worth waking the operator for. A home with
    # neither a settings.json nor a sidecar has nothing to be wrong with; a home
    # that has either and still lacks the block is the IDEA_BOX failure this
    # whole seam exists to surface, so it must stay a hard fail.
    sidecar = hooks_install.read_sidecar(home)
    if sidecar is None and not (home / ".claude" / "settings.json").exists():
        return Check("hooks", True, "not installed here", checked=False)
    try:
        # The question is whether the INSTALLED block is healthy, so the root
        # the install was wired from is authoritative. Resolving from __file__
        # instead makes every agent worktree report DRIFTED against itself,
        # because the rendered command paths legitimately differ.
        root = checkout
        if root is None:
            recorded = (sidecar or {}).get("checkout_root")
            if isinstance(recorded, str) and (
                Path(recorded) / "templates" / "hooks.manifest.json"
            ).is_file():
                root = Path(recorded)
        if root is None:
            root = _repo_from_file()
        report = hooks_install.status(home=home, checkout=root)
    except Exception as exc:
        return Check("hooks", False, f"status failed ({type(exc).__name__})", checked=False)
    if hooks_install.block_invalidated(report):
        extra = f"+{len(report.collisions)} collisions" if report.collisions else ""
        return Check("hooks", False, f"{report.overall}{extra}")
    return Check("hooks", True, report.overall)


def _check_verdict_backlog(state: Path) -> Check:
    """Count only. Reading the JSON is what makes the reaper's own scan O(N)."""
    if not state.is_dir():
        return Check("verdicts", True, "no state dir", checked=False)
    try:
        count = sum(
            1
            for entry in os.scandir(state)
            if entry.name.startswith("session_verdict_") and entry.name.endswith(".json")
        )
    except OSError as exc:
        return Check("verdicts", False, f"unreadable ({type(exc).__name__})", checked=False)
    if count > VERDICT_BACKLOG_CEILING:
        return Check("verdicts", False, f"{count} unreaped (>{VERDICT_BACKLOG_CEILING})")
    return Check("verdicts", True, str(count))


def _check_leaked_temp(home: Path, state: Path, now: float) -> Check:
    """Atomic writes clean up after themselves; a SIGKILLed hook does not."""
    stale: list[str] = []
    cutoff = now - 86400
    for directory in (home / ".claude", state):
        if not directory.is_dir():
            continue
        try:
            for entry in os.scandir(directory):
                if not entry.is_file(follow_symlinks=False):
                    continue
                if ".tmp" not in entry.name:
                    continue
                try:
                    if entry.stat(follow_symlinks=False).st_mtime < cutoff:
                        stale.append(entry.name)
                except OSError:
                    continue
        except OSError as exc:
            return Check("temp", False, f"unreadable ({type(exc).__name__})", checked=False)
    if len(stale) > LEAKED_TMP_CEILING:
        return Check("temp", False, f"{len(stale)} orphaned .tmp files")
    return Check("temp", True, str(len(stale)))


def _check_janitor(state: Path, now: float) -> Check:
    """Read the janitor's cached report. Never run it -- it scans every worktree."""
    directory = state / "git_hygiene"
    if not directory.is_dir():
        return Check("janitor", True, "not deployed", checked=False)
    try:
        reports = [e for e in os.scandir(directory) if e.name.startswith("report-latest_")]
    except OSError as exc:
        return Check("janitor", False, f"unreadable ({type(exc).__name__})", checked=False)
    if not reports:
        return Check("janitor", True, "no report yet", checked=False)
    newest = max(reports, key=lambda e: e.stat().st_mtime)
    age_h = (now - newest.stat().st_mtime) / 3600
    if age_h > JANITOR_STALE_HOURS:
        return Check("janitor", False, f"report {age_h:.0f}h old (scheduler stopped?)")
    alarms = 0
    for entry in reports:
        try:
            text = Path(entry.path).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        alarms += sum(1 for line in text.splitlines() if _ALARM_LINE.match(line))
    if alarms:
        return Check("janitor", False, f"{alarms} alarms")
    return Check("janitor", True, "0 alarms")


def _check_installed_drift(checkout: Path | None) -> Check:
    """--full only: hashes every installed artifact against the repo."""
    checkout = checkout or _repo_from_file()
    if checkout is None:
        return Check("drift", True, "no checkout", checked=False)
    script = checkout / "install" / "install.ps1"
    if os.name != "nt" or not script.is_file():
        return Check("drift", True, "windows installer only", checked=False)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-File", str(script), "-Check"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Check("drift", False, f"check failed ({type(exc).__name__})", checked=False)
    if result.returncode == 0:
        return Check("drift", True, "none")
    items = sum(1 for line in (result.stdout or "").splitlines() if line.strip().startswith(
        ("MISSING", "DRIFT", "EXTRA", "NOT INSTALLED", "RETIRED", "HOOK BLOCK")))
    return Check("drift", False, f"{items or '?'} items")


def build_report(
    *,
    home: Path,
    state_dir: Path | None = None,
    checkout: Path | None = None,
    full: bool = False,
    now: float | None = None,
    budget_s: float = 1.5,
) -> Report:
    """Run the cheap checks, then the slow one only when asked.

    Checks are ordered by value per millisecond so a spent budget drops the
    least useful one first. A skipped check is `checked=False`, never a silent
    pass: this module exists because silence read as health.
    """
    state = state_dir if state_dir is not None else _default_state_dir(home)
    moment = now if now is not None else time.time()
    deadline = time.monotonic() + max(0.05, budget_s)
    report = Report()
    for name, run in (
        ("hooks", lambda: _check_hook_block(home, checkout)),
        ("verdicts", lambda: _check_verdict_backlog(state)),
        ("temp", lambda: _check_leaked_temp(home, state, moment)),
        ("janitor", lambda: _check_janitor(state, moment)),
    ):
        if time.monotonic() >= deadline:
            report.checks.append(Check(name, True, "skipped: budget", checked=False))
            continue
        try:
            report.checks.append(run())
        except Exception as exc:  # never break a session over a diagnostic
            report.checks.append(Check(name, False, f"raised {type(exc).__name__}", checked=False))
    if full:
        report.checks.append(_check_installed_drift(checkout))
    return report


def _repo_from_file() -> Path | None:
    """The checkout this copy of the script lives in, if it lives in one."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "templates" / "hooks.manifest.json").is_file():
            return parent
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ecosystem_doctor.py", description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--checkout", type=Path, default=None)
    parser.add_argument("--full", action="store_true", help="add the slow drift check")
    parser.add_argument("--report", action="store_true", help="one line per check")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--budget-s", type=float, default=1.5)
    args = parser.parse_args(argv)

    report = build_report(
        home=args.home,
        state_dir=args.state_dir,
        checkout=args.checkout,
        full=args.full,
        budget_s=args.budget_s,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    elif args.report:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        print(f"ecosystem doctor {stamp}")
        for check in report.checks:
            mark = "  ok  " if check.ok else " FAIL "
            if not check.checked:
                mark = " skip "
            print(f"[{mark}] {check.name:<10} {check.detail}")
    else:
        print(report.line())
    return report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
