"""Installer-managed Claude hook block for ~/.claude/settings.json.

Wires the ecosystem's canonical hook block (templates/hooks.manifest.json) into the
operator's global Claude settings, records ownership in a sidecar manifest, and reports
whether the managed block is present/absent/drifted -- scoped strictly to settings.json.

It never claims a hook is absent from the running merged configuration (hooks resolve
from seven sources); every negative verdict is scoped to settings.json and refers the
operator to `/hooks` for the authoritative merged view. See
design/plans/2026-08-04_installer_managed_hook_block_r2.md (Invariant 5).

Merge is at handler granularity (Matrix B1): a foreign handler sharing a matcher group
with a managed one is preserved in place. Validation precedes any disk mutation (B4);
dry-run is the default. The settings/sidecar pair is crash-recoverable (B3).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "dceco.hooks.manifest.v1"
SIDECAR_SCHEMA = "dceco.hooks.install.v1"

# Code-owned allowlist of Claude Code hook events (Matrix B7). A manifest entry on any
# other event is rejected at load time -- a hook wired to a non-existent event never
# fires while status would otherwise read OK.
KNOWN_EVENTS = frozenset({
    "SessionStart", "SessionEnd", "PreToolUse", "PostToolUse",
    "UserPromptSubmit", "Notification", "Stop", "SubagentStop", "PreCompact",
})

# Tool names that a PostToolUse/PreToolUse matcher token may reference (Matrix B7).
KNOWN_TOOLS = frozenset({
    "Task", "Bash", "Glob", "Grep", "Read", "Edit", "Write", "NotebookEdit",
    "WebFetch", "WebSearch", "TodoWrite",
})
_TOOL_MATCH_EVENTS = frozenset({"PreToolUse", "PostToolUse"})

BACKUP_KEEP = 10  # retention: last N settings.json backups
HOOKS_REFERENCE = "run `/hooks` for the authoritative merged view across all sources"


class HookInstallError(ValueError):
    """Raised for any fail-closed condition (bad manifest, unresolved path, parse error)."""


@dataclass(frozen=True)
class ManifestEntry:
    event: str
    matcher: str
    script: str
    interpreter: str
    timeout: int | None


@dataclass
class EntryVerdict:
    event: str
    matcher: str
    script: str
    verdict: str
    detail: str = ""


@dataclass
class StatusReport:
    entries: list[EntryVerdict] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)
    manifest_drift: bool = False
    janitor_task_present: str = "UNKNOWN"  # OK | STALE_OR_FAILING | ABSENT | NOT_APPLICABLE
    overall: str = "OK"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SIDECAR_SCHEMA,
            "overall": self.overall,
            "entries": [
                {"event": e.event, "matcher": e.matcher, "script": e.script,
                 "verdict": e.verdict, "detail": e.detail}
                for e in self.entries
            ],
            "collisions": self.collisions,
            "unclassified": self.unclassified,
            "manifest_drift": self.manifest_drift,
            "janitor_task_present": self.janitor_task_present,
            "reference": HOOKS_REFERENCE,
        }


# ── path / interpreter / manifest ────────────────────────────────────────────

def resolve_checkout(explicit: Path | None) -> Path:
    """`--checkout` wins; else walk up from this file to a dir holding BOTH .git and
    templates/hooks.manifest.json (Matrix B4)."""
    if explicit is not None:
        root = explicit.resolve()
        if not (root / "templates" / "hooks.manifest.json").is_file():
            raise HookInstallError(f"--checkout {root} has no templates/hooks.manifest.json")
        _reject_unsafe_root(root)
        return root
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists() and (parent / "templates" / "hooks.manifest.json").is_file():
            _reject_unsafe_root(parent)
            return parent
    raise HookInstallError("could not resolve the ecosystem checkout root from __file__")


def _reject_unsafe_root(root: Path) -> None:
    if any(ch in str(root) for ch in '"\'`$'):
        raise HookInstallError(f"checkout root contains unsafe characters: {root}")


def resolve_interpreter() -> str:
    """Windows -> the `py` launcher; POSIX -> `python3`. Verified resolvable."""
    candidate = "py" if os.name == "nt" else "python3"
    if shutil.which(candidate) is None:
        # Fall back to whatever launched us, but still fail closed if nothing resolves.
        alt = Path(sys.executable).name
        if shutil.which(alt) is None and not Path(sys.executable).exists():
            raise HookInstallError(f"interpreter {candidate!r} does not resolve on PATH")
        return alt
    return candidate


def load_manifest(checkout: Path) -> list[ManifestEntry]:
    path = checkout / "templates" / "hooks.manifest.json"
    try:
        raw = json.loads(path.read_bytes())
    except FileNotFoundError as exc:
        raise HookInstallError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise HookInstallError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != MANIFEST_SCHEMA:
        raise HookInstallError(f"manifest schema must be {MANIFEST_SCHEMA}")
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise HookInstallError("manifest entries must be a non-empty array")
    entries: list[ManifestEntry] = []
    for item in entries_raw:
        if not isinstance(item, dict):
            raise HookInstallError("manifest entry must be an object")
        event = item.get("event")
        matcher = item.get("matcher")
        script = item.get("script")
        interp = item.get("interpreter", "python")
        timeout = item.get("timeout")
        if event not in KNOWN_EVENTS:
            raise HookInstallError(f"unknown hook event: {event!r}")
        if not isinstance(matcher, str) or not matcher:
            raise HookInstallError(f"entry for {event} has an empty matcher")
        if not isinstance(script, str) or "/" in script or "\\" in script or not script.endswith(".py"):
            raise HookInstallError(f"entry script must be a bare .py basename: {script!r}")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            raise HookInstallError(f"entry timeout must be a positive int: {timeout!r}")
        if event in _TOOL_MATCH_EVENTS:
            for tok in matcher.split("|"):
                if tok != "*" and tok not in KNOWN_TOOLS:
                    raise HookInstallError(f"{event} matcher references unknown tool: {tok!r}")
        entries.append(ManifestEntry(event, matcher, script, interp, timeout))
    return entries


def manifest_sha256(checkout: Path) -> str:
    import hashlib
    return hashlib.sha256((checkout / "templates" / "hooks.manifest.json").read_bytes()).hexdigest()


# ── rendering / classification ───────────────────────────────────────────────

def render_command(interpreter: str, checkout: Path, script: str) -> str:
    """Deterministic across OS (Matrix B5): posix path, one quoting rule."""
    posix = (checkout / "scripts" / script).as_posix()
    return f'{interpreter} "{posix}"'


def managed_basenames(entries: list[ManifestEntry]) -> set[str]:
    return {e.script for e in entries}


def _command_path_token(command: str) -> str | None:
    """Quote-aware extraction of the script path token. Returns None if the command
    cannot be confidently tokenized (Matrix B2 -> UNCLASSIFIED)."""
    if not isinstance(command, str) or not command.strip():
        return None
    if '"' in command:
        first = command.index('"')
        rest = command.find('"', first + 1)
        if rest == -1:
            return None  # unbalanced quote
        return command[first + 1:rest]
    parts = command.split()
    if len(parts) < 2:
        return None
    return parts[-1]


def classify_handler(command: str, checkout: Path, home: Path,
                     managed: set[str]) -> tuple[str, str | None]:
    """Return (kind, basename): 'managed' | 'collision' | 'foreign' | 'unclassified'."""
    token = _command_path_token(command)
    if token is None:
        return ("unclassified", None)
    base = Path(token.replace("\\", "/")).name
    if base not in managed:
        return ("foreign", None)
    # basename matches a managed script: only ours if rooted in an allowlisted legacy root.
    legacy_roots = [(checkout / "scripts"), (home / ".claude" / "scripts")]
    try:
        resolved = Path(token.replace("\\", "/"))
        for root in legacy_roots:
            root_posix = root.as_posix().lower()
            if resolved.as_posix().lower() == (root.as_posix() + "/" + base).lower() or \
               resolved.as_posix().lower().startswith(root_posix + "/"):
                return ("managed", base)
    except (OSError, ValueError):
        return ("collision", base)
    return ("collision", base)


# ── merge (handler granularity, Matrix B1) ───────────────────────────────────

def _canonical_group(entry: ManifestEntry, interpreter: str, checkout: Path) -> dict[str, Any]:
    handler: dict[str, Any] = {"type": "command", "command": render_command(interpreter, checkout, entry.script)}
    if entry.timeout is not None:
        handler["timeout"] = entry.timeout
    return {"matcher": entry.matcher, "hooks": [handler]}


def merge_hooks(settings: dict[str, Any], entries: list[ManifestEntry],
                interpreter: str, checkout: Path, home: Path) -> dict[str, Any]:
    """Return a new settings dict with the managed block reconciled at handler granularity.

    Removes only individual command handlers whose resolved basename matches a managed
    script (rooted in an allowlisted legacy root). Foreign siblings are preserved in
    place; a group is dropped only when its hooks array becomes empty. Canonical groups
    are then appended. Non-hook keys and all foreign handlers are preserved verbatim.
    """
    managed = managed_basenames(entries)
    managed_events = {e.event for e in entries}
    result = json.loads(json.dumps(settings))  # deep copy, structural
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HookInstallError("settings.json 'hooks' is not an object")

    for event in managed_events:
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise HookInstallError(f"settings.json hooks.{event} is not an array")
        kept_groups: list[dict[str, Any]] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept_groups.append(group)  # malformed foreign group: preserve verbatim
                continue
            kept_handlers = []
            for handler in group["hooks"]:
                cmd = handler.get("command", "") if isinstance(handler, dict) else ""
                kind, _ = classify_handler(cmd, checkout, home, managed)
                if kind == "managed":
                    continue  # drop; will be re-inserted canonically
                kept_handlers.append(handler)  # foreign / collision / unclassified: keep in place
            if kept_handlers:
                new_group = dict(group)
                new_group["hooks"] = kept_handlers
                kept_groups.append(new_group)
            # else: group emptied by removing our handlers -> drop it
        # append canonical managed groups for this event
        for entry in entries:
            if entry.event == event:
                kept_groups.append(_canonical_group(entry, interpreter, checkout))
        hooks[event] = kept_groups
    return result


def compute_collisions(settings: dict[str, Any], entries: list[ManifestEntry],
                       checkout: Path, home: Path) -> tuple[list[str], list[str]]:
    """Scan managed events for COLLISION (basename match outside allowlisted roots) and
    UNCLASSIFIED (untokenizable) handlers, so they are surfaced, never silently mutated."""
    managed = managed_basenames(entries)
    managed_events = {e.event for e in entries}
    collisions: list[str] = []
    unclassified: list[str] = []
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return collisions, unclassified
    for event in managed_events:
        for group in hooks.get(event, []) or []:
            if not isinstance(group, dict):
                continue
            for handler in group.get("hooks", []) or []:
                cmd = handler.get("command", "") if isinstance(handler, dict) else ""
                kind, base = classify_handler(cmd, checkout, home, managed)
                if kind == "collision":
                    collisions.append(f"{event}: {cmd}")
                elif kind == "unclassified":
                    unclassified.append(f"{event}: {cmd!r}")
    return collisions, unclassified


# ── atomic io / backup / sidecar ─────────────────────────────────────────────

def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".hooks-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)
    # Directory fsync is a POSIX durability step; Windows cannot open a directory fd.
    if os.name != "nt":
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_settings(settings_path: Path, home: Path) -> Path:
    backups = home / ".claude" / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    dest = backups / f"settings.json.{_utc_stamp()}"
    data = settings_path.read_bytes() if settings_path.exists() else b"{}"
    atomic_write_bytes(dest, data)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    _rotate_backups(backups)
    return dest


def _rotate_backups(backups: Path) -> None:
    items = sorted(backups.glob("settings.json.*"))
    for stale in items[:-BACKUP_KEEP]:
        try:
            stale.unlink()
        except OSError:
            pass


def sidecar_path(home: Path) -> Path:
    return home / ".claude" / "hooks-install-manifest.json"


def read_sidecar(home: Path) -> dict[str, Any] | None:
    path = sidecar_path(home)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_bytes())
    except (json.JSONDecodeError, OSError):
        return None


def write_sidecar(home: Path, payload: dict[str, Any]) -> None:
    atomic_write_bytes(sidecar_path(home), (json.dumps(payload, indent=2) + "\n").encode("utf-8"))


# ── settings load ────────────────────────────────────────────────────────────

def load_settings(settings_path: Path) -> dict[str, Any]:
    if not settings_path.exists():
        return {}
    raw = settings_path.read_bytes()
    if not raw.strip():
        return {}  # 0-byte / whitespace-only -> treat as {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HookInstallError(f"settings.json is not valid JSON ({settings_path}): {exc}") from exc
    if not isinstance(value, dict):
        raise HookInstallError("settings.json top-level value is not an object")
    return value


# ── install / uninstall ──────────────────────────────────────────────────────

def _validated_context(home: Path, checkout: Path | None) -> tuple[Path, list[ManifestEntry], str]:
    root = resolve_checkout(checkout)
    entries = load_manifest(root)
    interpreter = resolve_interpreter()
    missing = [e.script for e in entries
               if not (root / "scripts" / e.script).is_file()]
    if missing:
        raise HookInstallError(f"managed scripts missing at {root/'scripts'}: {', '.join(sorted(set(missing)))}")
    return root, entries, interpreter


def install(*, home: Path, checkout: Path | None, apply: bool) -> dict[str, Any]:
    settings_path = home / ".claude" / "settings.json"
    # (1-3) validate everything before any disk mutation (Matrix B4)
    root, entries, interpreter = _validated_context(home, checkout)
    before = load_settings(settings_path)
    # (5) compute merge in memory
    after = merge_hooks(before, entries, interpreter, root, home)
    collisions, unclassified = compute_collisions(before, entries, root, home)
    diff = _diff(before, after)
    if not apply:
        return {"mode": "dry-run", "checkout": str(root), "interpreter": interpreter,
                "changes": diff, "collisions": collisions, "unclassified": unclassified,
                "wrote_backup": False}
    # No-op apply (Matrix B4): block already canonical and sidecar healthy -> no backup, no write.
    existing_sidecar = read_sidecar(home)
    unchanged = (after == before) and settings_path.exists()
    healthy_sidecar = bool(existing_sidecar) and existing_sidecar.get("state") == "installed" \
        and existing_sidecar.get("manifest_sha256") == manifest_sha256(root)
    if unchanged and healthy_sidecar:
        return {"mode": "applied-noop", "checkout": str(root), "interpreter": interpreter,
                "changes": diff, "collisions": collisions, "unclassified": unclassified,
                "wrote_backup": False}
    # (6) apply: backup -> sidecar pending -> settings -> sidecar installed (Matrix B3)
    backup = backup_settings(settings_path, home)
    rendered = [{"event": e.event, "matcher": e.matcher,
                 "command": render_command(interpreter, root, e.script)} for e in entries]
    pending = {"schema_version": SIDECAR_SCHEMA, "state": "pending",
               "checkout_root": root.as_posix(), "interpreter": interpreter,
               "installed_at_utc": datetime.now(timezone.utc).isoformat(),
               "manifest_sha256": manifest_sha256(root),
               "entries": rendered, "settings_backup": str(backup)}
    write_sidecar(home, pending)
    atomic_write_bytes(settings_path, (json.dumps(after, indent=2) + "\n").encode("utf-8"))
    installed = dict(pending, state="installed")
    write_sidecar(home, installed)
    return {"mode": "applied", "checkout": str(root), "interpreter": interpreter,
            "changes": diff, "collisions": collisions, "unclassified": unclassified,
            "settings_backup": str(backup), "wrote_backup": True}


def uninstall(*, home: Path, apply: bool) -> dict[str, Any]:
    settings_path = home / ".claude" / "settings.json"
    sidecar = read_sidecar(home)
    if not sidecar or not sidecar.get("entries"):
        return {"mode": "noop", "reason": "no sidecar manifest; nothing owned"}
    before = load_settings(settings_path)
    owned = {(e["event"], e["command"]) for e in sidecar["entries"]}
    expected = len(sidecar["entries"])  # handler count, not the deduped tuple set
    after = json.loads(json.dumps(before))
    hooks = after.get("hooks", {})
    removed, partial = 0, False
    if isinstance(hooks, dict):
        for event in list(hooks.keys()):
            kept_groups = []
            for group in hooks.get(event, []) or []:
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    kept_groups.append(group)
                    continue
                kept = []
                for handler in group["hooks"]:
                    cmd = handler.get("command", "") if isinstance(handler, dict) else ""
                    if (event, cmd) in owned:
                        removed += 1
                    else:
                        kept.append(handler)
                if kept:
                    ng = dict(group)
                    ng["hooks"] = kept
                    kept_groups.append(ng)
            if kept_groups:
                hooks[event] = kept_groups
            else:
                hooks.pop(event, None)
    if removed < expected:
        partial = True
    if not apply:
        return {"mode": "dry-run", "would_remove": removed, "owned": expected,
                "partial": partial}
    if removed:
        atomic_write_bytes(settings_path, (json.dumps(after, indent=2) + "\n").encode("utf-8"))
    try:
        sidecar_path(home).unlink()
    except OSError:
        pass
    result = {"mode": "PARTIAL_UNINSTALL" if partial else "applied",
              "removed": removed, "owned": expected}
    if partial:
        result["backup"] = sidecar.get("settings_backup")
    return result


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    def flat(s: dict[str, Any]) -> set[tuple[str, str, str]]:
        out = set()
        for event, groups in (s.get("hooks", {}) or {}).items():
            for g in groups or []:
                if not isinstance(g, dict):
                    continue
                for h in g.get("hooks", []) or []:
                    if isinstance(h, dict):
                        out.add((event, g.get("matcher", ""), h.get("command", "")))
        return out
    b, a = flat(before), flat(after)
    return {"added": sorted("|".join(x) for x in a - b),
            "removed": sorted("|".join(x) for x in b - a)}


# ── status / doctor ──────────────────────────────────────────────────────────

JANITOR_TASK_NAME = "TsignalGitHygiene"


def janitor_task_status(task_name: str = JANITOR_TASK_NAME) -> str:
    """Liveness, not mere registration (Matrix required condition): a task can exist while
    disabled or failing. POSIX -> NOT_APPLICABLE. Windows -> query schtasks LastTaskResult."""
    if os.name != "nt":
        return "NOT_APPLICABLE"
    try:
        proc = subprocess_run_csv(task_name)
    except Exception:  # noqa: BLE001 - liveness probe must never raise into the caller
        return "ABSENT"
    if proc is None:
        return "ABSENT"
    status_text, last_result = proc
    if status_text.strip().lower() == "disabled":
        return "STALE_OR_FAILING"
    # LastTaskResult 0x0 (success) or 0x41301 (currently running) are healthy.
    if last_result not in ("0", "267009", "0x0", "0x41301", ""):
        return "STALE_OR_FAILING"
    return "OK"


def subprocess_run_csv(task_name: str) -> tuple[str, str] | None:
    import csv
    import io
    import subprocess
    proc = subprocess.run(["schtasks", "/query", "/tn", task_name, "/fo", "CSV", "/v"],
                          capture_output=True, text=True, timeout=15)
    if proc.returncode != 0:
        return None
    rows = list(csv.DictReader(io.StringIO(proc.stdout)))
    if not rows:
        return None
    row = rows[0]
    return (row.get("Status", ""), row.get("Last Result", ""))


def status(*, home: Path, checkout: Path | None, check_janitor: bool = False) -> StatusReport:
    report = StatusReport()
    settings_path = home / ".claude" / "settings.json"
    try:
        root = resolve_checkout(checkout)
        entries = load_manifest(root)
        interpreter = resolve_interpreter()
    except HookInstallError as exc:
        report.overall = "SOURCE_MANIFEST_UNREADABLE"
        report.entries.append(EntryVerdict("", "", "", "SOURCE_MANIFEST_UNREADABLE", str(exc)))
        return report
    try:
        settings = load_settings(settings_path)
    except HookInstallError as exc:
        report.overall = "SOURCE_MANIFEST_UNREADABLE"
        report.entries.append(EntryVerdict("", "", "", "SOURCE_MANIFEST_UNREADABLE", str(exc)))
        return report

    sidecar = read_sidecar(home)
    actual = _actual_managed(settings, entries, root, home)  # (event, matcher, command) multiset
    report.collisions, report.unclassified = compute_collisions(settings, entries, root, home)

    if sidecar is not None and sidecar.get("state") == "pending":
        report.overall = "INCOMPLETE_INSTALL"
    if sidecar is not None:
        report.manifest_drift = sidecar.get("manifest_sha256") not in (None, manifest_sha256(root))

    any_present = bool(actual)
    for entry in entries:
        expected_cmd = render_command(interpreter, root, entry.script)
        key = (entry.event, entry.matcher, expected_cmd)
        script_exists = (root / "scripts" / entry.script).is_file()
        if not script_exists:
            report.entries.append(EntryVerdict(entry.event, entry.matcher, entry.script,
                                               "UNRESOLVED_PATH", f"script missing at {root/'scripts'}"))
            continue
        if key in actual:
            actual.remove(key)
            verdict = "OK" if sidecar is not None else "UNVERIFIED_PRESENT"
            report.entries.append(EntryVerdict(entry.event, entry.matcher, entry.script, verdict))
        else:
            if not any_present and sidecar is None:
                report.entries.append(EntryVerdict(entry.event, entry.matcher, entry.script,
                                                   "NEVER_INSTALLED"))
            else:
                report.entries.append(EntryVerdict(
                    entry.event, entry.matcher, entry.script, "MISSING",
                    f"managed block absent in {settings_path.name} ({HOOKS_REFERENCE})"))
    # any managed-classified handler left over is drift (wrong matcher/command/dup)
    for (event, matcher, cmd) in sorted(actual):
        report.entries.append(EntryVerdict(event, matcher, "?", "DRIFTED", cmd))

    if check_janitor:
        report.janitor_task_present = janitor_task_status()

    report.overall = _rollup(report)
    return report


def _actual_managed(settings: dict[str, Any], entries: list[ManifestEntry],
                    checkout: Path, home: Path) -> list[tuple[str, str, str]]:
    managed = managed_basenames(entries)
    managed_events = {e.event for e in entries}
    out: list[tuple[str, str, str]] = []
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return out
    for event in managed_events:
        for group in hooks.get(event, []) or []:
            if not isinstance(group, dict):
                continue
            matcher = group.get("matcher", "")
            for handler in group.get("hooks", []) or []:
                cmd = handler.get("command", "") if isinstance(handler, dict) else ""
                kind, _ = classify_handler(cmd, checkout, home, managed)
                if kind == "managed":
                    out.append((event, matcher, cmd))
    return out


_BLOCK_INVALIDATING = {"MISSING", "DRIFTED", "UNRESOLVED_PATH", "NEVER_INSTALLED",
                       "INCOMPLETE_INSTALL", "COLLISION", "SOURCE_MANIFEST_UNREADABLE"}


def _rollup(report: StatusReport) -> str:
    if report.overall == "INCOMPLETE_INSTALL":
        return "INCOMPLETE_INSTALL"
    verdicts = {e.verdict for e in report.entries}
    if report.collisions:
        verdicts.add("COLLISION")
    for bad in ("SOURCE_MANIFEST_UNREADABLE", "INCOMPLETE_INSTALL", "UNRESOLVED_PATH",
                "DRIFTED", "MISSING", "NEVER_INSTALLED", "COLLISION"):
        if bad in verdicts:
            return bad
    if "UNVERIFIED_PRESENT" in verdicts:
        return "UNVERIFIED_PRESENT"
    return "OK"


def block_invalidated(report: StatusReport) -> bool:
    """True when the janitor should alarm (Matrix B6)."""
    return report.overall in _BLOCK_INVALIDATING or bool(report.collisions)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _render_human(report: StatusReport) -> str:
    lines = [f"overall: {report.overall}   ({HOOKS_REFERENCE})",
             "note: verifies ~/.claude/settings.json, not the running session; "
             "hook changes take effect in new sessions."]
    for e in report.entries:
        tag = f"{e.event}/{e.matcher}/{e.script}"
        lines.append(f"  [{e.verdict:<20}] {tag}" + (f"  -- {e.detail}" if e.detail else ""))
    for c in report.collisions:
        lines.append(f"  [COLLISION           ] {c}")
    for u in report.unclassified:
        lines.append(f"  [UNCLASSIFIED        ] {u}")
    if report.janitor_task_present != "UNKNOWN":
        lines.append(f"  janitor_task: {report.janitor_task_present}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hooks_install.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "uninstall"):
        p = sub.add_parser(name)
        p.add_argument("--apply", action="store_true", help="mutate settings.json (default: dry-run)")
        p.add_argument("--home", type=Path, default=Path.home())
        if name == "install":
            p.add_argument("--checkout", type=Path, default=None)
    for name in ("status", "doctor"):
        p = sub.add_parser(name)
        p.add_argument("--home", type=Path, default=Path.home())
        p.add_argument("--checkout", type=Path, default=None)
        p.add_argument("--json", action="store_true")
    sub.add_parser("version")
    args = parser.parse_args(argv)

    try:
        if args.command in ("status", "doctor"):
            report = status(home=args.home, checkout=args.checkout,
                            check_janitor=(args.command == "doctor"))
            print(json.dumps(report.to_dict(), indent=2) if args.json else _render_human(report))
            return 0 if report.overall in ("OK", "UNVERIFIED_PRESENT") else 3
        if args.command == "install":
            result = install(home=args.home, checkout=args.checkout, apply=args.apply)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "uninstall":
            result = uninstall(home=args.home, apply=args.apply)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "version":
            print(json.dumps({"schema": SIDECAR_SCHEMA, "manifest_schema": MANIFEST_SCHEMA}))
            return 0
    except HookInstallError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
