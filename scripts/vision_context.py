#!/usr/bin/env python3
"""Best-effort vision preamble and completion logging for plan-bound modes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from _catalog_common import parse_yaml_block

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOME = Path.home() / ".claude"
INDEX_PATH = HOME / ".vision_index.json"
CATALOG_SCRIPT = HOME / "scripts" / "vision_catalog.py"
FAIL_QUEUE = HOME / ".vision_log_failed.jsonl"
DIAG_LOG = HOME / ".vision_context.log"
SCHEMA_VERSION = 1
STALE_SECONDS = 24 * 60 * 60
AUTO_LOG_BEGIN = "<!-- BEGIN AUTO-LOG"
AUTO_LOG_END = "<!-- END AUTO-LOG -->"
INJECTION_MARKERS = ("<|", "[INST]", "</system>", "<<SYS>>")


@dataclass
class VisionState:
    slug: str
    path: Path
    title: str
    why: str
    dod: list[str]
    progress: dict
    next_plan: str


def canonical_path(path: Path) -> str:
    return path.resolve().as_posix()


def _plan_slug(path: Path) -> str:
    stem = path.stem
    if len(stem) > 11 and stem[:10].count("-") == 2 and stem[10] in ("_", "-"):
        return stem[11:]
    return stem


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _section_lines(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == f"## {heading}".lower():
            start = i + 1
            break
    if start is None:
        return []
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return [line.rstrip() for line in lines[start:end]]


def _clean_line(line: str, limit: int = 200) -> str:
    for marker in INJECTION_MARKERS:
        if marker in line:
            return ""
    cleaned = " ".join(line.strip().lstrip("-*0123456789.[]xX ").split())
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3].rstrip() + "..."
    return cleaned


def _first_why(text: str) -> str:
    for line in _section_lines(text, "Why"):
        cleaned = _clean_line(line)
        if cleaned:
            return cleaned
    return ""


def _dod(text: str) -> list[str]:
    bullets: list[str] = []
    for line in _section_lines(text, "Definition of Done"):
        if line.strip().startswith(("-", "*")):
            cleaned = _clean_line(line)
            if cleaned:
                bullets.append(cleaned)
        if len(bullets) >= 3:
            break
    return bullets


def _load_state(slug: str, item: dict) -> VisionState | None:
    try:
        path = Path(item["path"])
        if not path.exists():
            return None
        raw = parse_yaml_block(path)
        if not raw:
            return None
        text = _read_text(path)
        return VisionState(
            slug=slug,
            path=path,
            title=str(raw.get("title") or item.get("title") or slug),
            why=_first_why(text),
            dod=_dod(text),
            progress=dict(item.get("progress") or {}),
            next_plan=str(item.get("next_plan") or "none"),
        )
    except Exception:
        return None


def resolve_vision(slug: str, index_path: Path = INDEX_PATH) -> VisionState | None:
    """O(1) index lookup. Returns None on any error. Never raises."""
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION:
            return None
        item = data.get("visions", {}).get(slug)
        if not item:
            return None
        return _load_state(slug, item)
    except Exception:
        return None


def emit_preamble(state: VisionState | None) -> str:
    """Pure formatter. Returns an empty string if state is None."""
    if state is None:
        return ""
    progress = state.progress or {}
    shipped = progress.get("shipped", 0)
    total = progress.get("total", 0)
    lines = [f"\U0001f3af Vision: {state.title}"]
    if state.why:
        lines.append(f"   Why: {state.why}")
    for bullet in state.dod[:3]:
        lines.append(f"   DoD: {bullet}")
    lines.append(f"   Progress: {shipped}/{total} plans ({shipped} shipped, {total} total) · Next: {state.next_plan or 'none'}")
    return "\n".join(lines[:6])


def _acquire_lock(lock_path: Path, timeout_s: float = 5.0) -> int | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            time.sleep(0.05)
    return None


def _ensure_auto_log(text: str) -> str:
    if AUTO_LOG_BEGIN in text and AUTO_LOG_END in text:
        return text
    suffix = "\n\n<!-- BEGIN AUTO-LOG - managed by vision_context.py --log -->\n<!-- END AUTO-LOG -->\n"
    return text.rstrip() + suffix


def _append_inside_auto_log(text: str, line: str) -> str:
    text = _ensure_auto_log(text)
    end = text.index(AUTO_LOG_END)
    before = text[:end].rstrip()
    after = text[end:]
    return f"{before}\n{line}\n{after}"


def log_completion(slug: str, entry_tsv: str, vision_file: Path) -> bool:
    """Append a TSV completion entry inside AUTO-LOG markers. Never raises."""
    lock_path = vision_file.with_suffix(vision_file.suffix + ".lock")
    fd = None
    try:
        fd = _acquire_lock(lock_path)
        if fd is None:
            return False
        os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        timestamp = datetime.now().isoformat(timespec="seconds")
        line = f"\t{timestamp}\t{entry_tsv.strip()}"
        text = _read_text(vision_file) if vision_file.exists() else ""
        updated = _append_inside_auto_log(text, line)
        tmp = vision_file.with_suffix(f"{vision_file.suffix}.tmp.{os.getpid()}")
        tmp.write_text(updated, encoding="utf-8", newline="\n")
        os.replace(tmp, vision_file)
        return True
    except OSError as exc:
        print(f"vision_context: log write failed for {slug}: {exc}", file=sys.stderr)
        return True
    except Exception as exc:
        print(f"vision_context: log failed for {slug}: {exc}", file=sys.stderr)
        return True
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _append_fail_queue(slug: str, entry_tsv: str) -> None:
    try:
        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "slug": slug,
            "entry_tsv": entry_tsv.strip(),
        }
        with FAIL_QUEUE.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"vision_context: fail-queue write failed: {exc}", file=sys.stderr)


def _append_diag(plan: str, slug: str, result: str, started: float) -> None:
    try:
        DIAG_LOG.parent.mkdir(parents=True, exist_ok=True)
        latency = int((time.monotonic() - started) * 1000)
        line = (
            f"{datetime.now().isoformat(timespec='seconds')}\t"
            f"plan={plan or 'none'}\tvision={slug or 'none'}\t"
            f"result={result}\tlatency_ms={latency}"
        )
        existing = []
        if DIAG_LOG.exists():
            existing = DIAG_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-999:]
        DIAG_LOG.write_text("\n".join(existing + [line]) + "\n", encoding="utf-8", newline="\n")
    except Exception:
        pass


def _run_catalog_sync(blocking: bool) -> None:
    try:
        if blocking:
            subprocess.run([sys.executable, str(CATALOG_SCRIPT)], check=False, stdout=subprocess.DEVNULL)
        else:
            subprocess.Popen(
                [sys.executable, str(CATALOG_SCRIPT)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except Exception:
        pass


def _ensure_index() -> None:
    if not INDEX_PATH.exists():
        _run_catalog_sync(blocking=True)
        return
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION:
            _run_catalog_sync(blocking=True)
            return
    except Exception:
        _run_catalog_sync(blocking=True)
        return
    try:
        if time.time() - INDEX_PATH.stat().st_mtime > STALE_SECONDS:
            _run_catalog_sync(blocking=False)
    except OSError:
        pass


def _slug_from_plan(plan_path: Path) -> str:
    raw = parse_yaml_block(plan_path)
    return str(raw.get("vision", "")).strip()


def main() -> None:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description="Emit vision context or log completion.")
    parser.add_argument("--plan", help="Plan markdown path")
    parser.add_argument("--log", nargs=2, metavar=("SLUG", "ENTRY_TSV"))
    args = parser.parse_args()

    plan_slug = ""
    slug = ""
    result = "skipped"
    try:
        if args.log:
            slug, entry_tsv = args.log
            _ensure_index()
            state = resolve_vision(slug, INDEX_PATH)
            if state is None:
                _append_fail_queue(slug, entry_tsv)
                result = "unresolved"
            elif log_completion(slug, entry_tsv, state.path):
                result = "resolved"
            else:
                _append_fail_queue(slug, entry_tsv)
                result = "lock_timeout"
            return

        if not args.plan:
            return
        plan_path = Path(args.plan)
        plan_slug = _plan_slug(plan_path)
        slug = _slug_from_plan(plan_path)
        if not slug:
            result = "skipped"
            return
        _ensure_index()
        state = resolve_vision(slug, INDEX_PATH)
        if state is None:
            try:
                data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
                if slug not in data.get("visions", {}):
                    print(f"Vision: {slug} - unresolved (no matching vision file)")
                    result = "unresolved"
                else:
                    print(f"Vision: {slug} - unavailable (parse error)")
                    result = "unavailable"
            except Exception:
                print(f"Vision: {slug} - unavailable (parse error)")
                result = "unavailable"
            return
        print(emit_preamble(state))
        result = "resolved"
    except Exception as exc:
        print(f"vision_context: degraded ({exc})", file=sys.stderr)
    finally:
        _append_diag(plan_slug, slug, result, started)
        sys.exit(0)


if __name__ == "__main__":
    main()
