#!/usr/bin/env python3
"""Dispatch a Sol-supervised model team with explicit local provider contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


ROLE_CONFIG = {
    "sol": {
        "model": "gpt-5.6-sol",
        "reasoning": "high",
        "service_tier": "default",
        "sandbox": "read-only",
    },
}

CURSOR_DISABLED_UNTIL = "2026-09-08"
DEFAULT_ANTIGRAVITY_MODEL = os.environ.get(
    "MODEL_TEAM_ANTIGRAVITY_MODEL", "gemini-3.7-flash-high"
)
DEFAULT_OX_MODEL = os.environ.get(
    "MODEL_TEAM_OX_MODEL", "opencode/x-preview-f-free"
)
DEFAULT_FABLE_MODEL = os.environ.get("MODEL_TEAM_FABLE_MODEL", "fable")
DEFAULT_QWEN_MODEL = os.environ.get(
    "MODEL_TEAM_QWEN_MODEL", "unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL"
)
QWEN_BASE_URL = os.environ.get(
    "MODEL_TEAM_QWEN_BASE_URL", "http://127.0.0.1:8080"
).rstrip("/")

WATCHF_ROOT = Path(os.environ.get("MODEL_TEAM_WATCHF_ROOT", "D:/APPS/WatchF"))
WATCHF_PYTHON = Path(
    os.environ.get(
        "MODEL_TEAM_WATCHF_PYTHON",
        str(WATCHF_ROOT / ".venv/Scripts/python.exe"),
    )
)
CHATGPT_CDP_DRIVER = Path(
    os.environ.get(
        "MODEL_TEAM_CHATGPT_CDP_DRIVER",
        str(WATCHF_ROOT / "scripts/cdp_chatgpt_code.py"),
    )
)
CHATGPT_CDP_PROBE = Path(
    os.environ.get(
        "MODEL_TEAM_CHATGPT_CDP_PROBE",
        str(WATCHF_ROOT / "scripts/chatgpt_cdp_live_probe.py"),
    )
)
PERPLEXITY_DRIVER = Path(
    os.environ.get(
        "MODEL_TEAM_PERPLEXITY_DRIVER",
        str(WATCHF_ROOT / "scripts/coderpx.py"),
    )
)
PERPLEXITY_PROBE_DRIVER = Path(
    os.environ.get(
        "MODEL_TEAM_PERPLEXITY_PROBE_DRIVER",
        str(PERPLEXITY_DRIVER),
    )
)

DIRECT_WRITE_ROLES = ("chatgpt", "ox", "antigravity")
ADVISORY_ROLES = ("qwen", "perplexity", "fable")
DISPATCH_ROLES = DIRECT_WRITE_ROLES + ADVISORY_ROLES
READY_STATUSES = {"READY", "READY_CDP", "READY_CLI"}
FABLE_TASK_KINDS = {"architecture", "quant", "design"}


class DispatchError(RuntimeError):
    """The requested role cannot be dispatched safely."""


def _executable(name: str) -> str | None:
    override = os.environ.get(f"MODEL_TEAM_{name.upper()}_EXE")
    if override:
        return override
    home = Path.home()
    if os.name == "nt" and name == "codex":
        local_bin = home / "AppData/Local/OpenAI/Codex/bin"
        native = sorted(
            local_bin.glob("*/codex.exe"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if native:
            return str(native[0])
        npm_native = (
            home
            / "AppData/Roaming/npm/node_modules/@openai/codex/node_modules"
            / "@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe"
        )
        if npm_native.is_file():
            return str(npm_native)
        candidate = shutil.which("codex.exe")
        if candidate and "WindowsApps" not in candidate:
            return candidate
        return None
    if os.name == "nt" and name == "antigravity":
        candidate = shutil.which("agy")
        if candidate:
            return candidate
        agy = home / "AppData/Local/agy/bin/agy.exe"
        return str(agy) if agy.is_file() else None
    if os.name == "nt" and name == "opencode":
        cmd = home / "AppData/Roaming/npm/opencode.cmd"
        if cmd.is_file():
            return str(cmd)
    if os.name == "nt" and name == "claude":
        native = home / ".local/bin/claude.exe"
        if native.is_file():
            return str(native)
    return shutil.which(name)


def _command_prefix(executable: str) -> list[str]:
    lowered = executable.lower()
    if os.name == "nt" and lowered.endswith(".ps1"):
        powershell = shutil.which("powershell.exe") or "powershell.exe"
        return [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", executable]
    if os.name == "nt" and (lowered.endswith(".cmd") or lowered.endswith(".bat")):
        cmd = shutil.which("cmd.exe") or "cmd.exe"
        return [cmd, "/d", "/c", executable]
    return [executable]


def _capture(
    command: list[str],
    *,
    timeout_s: int,
    input_text: str | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd) if cwd else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DispatchError(str(exc)) from exc


def _git(repo: Path, *args: str) -> str:
    completed = _capture(
        ["git", "-C", str(repo), *args],
        timeout_s=60,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DispatchError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _repo_root(repo: Path) -> Path:
    if not repo.exists():
        raise DispatchError(f"repository does not exist: {repo}")
    return Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()


def _primary_worktree(repo: Path) -> Path:
    listing = _git(repo, "worktree", "list", "--porcelain")
    for line in listing.splitlines():
        if line.startswith("worktree "):
            return Path(line.removeprefix("worktree ")).resolve()
    raise DispatchError("git worktree list returned no worktree")


def _require_implementation_worktree(repo: Path, role: str) -> None:
    if repo == _primary_worktree(repo):
        raise DispatchError(
            f"{role} requires an isolated non-primary git worktree; create one first"
        )


def _version_probe(name: str) -> dict[str, object]:
    executable = _executable(name)
    if not executable:
        return {"status": "BLOCKED_NOT_FOUND", "executable": None}
    try:
        completed = _capture(_command_prefix(executable) + ["--version"], timeout_s=20)
    except DispatchError as exc:
        return {
            "status": "BLOCKED_PROBE_FAILED",
            "executable": executable,
            "detail": str(exc),
        }
    detail = (completed.stdout or completed.stderr).strip()[:500]
    return {
        "status": "READY" if completed.returncode == 0 else "BLOCKED_PROBE_FAILED",
        "executable": executable,
        "detail": detail or f"exit {completed.returncode}",
    }


def _chatgpt_probe(*, deep: bool) -> dict[str, object]:
    cli = _executable("chatgpt")
    base: dict[str, object] = {
        "transport": "cdp",
        "driver": str(CHATGPT_CDP_DRIVER),
        "cli_detected": cli,
    }
    missing = [
        str(path)
        for path in (WATCHF_PYTHON, CHATGPT_CDP_DRIVER, CHATGPT_CDP_PROBE)
        if not path.is_file()
    ]
    if missing:
        return dict(base, status="BLOCKED_NOT_FOUND", detail=f"missing: {missing}")
    if not deep:
        return dict(base, status="UNVERIFIED_CDP")
    try:
        completed = _capture(
            [
                str(WATCHF_PYTHON),
                str(CHATGPT_CDP_PROBE),
                "--role",
                "chrome_gpt",
                "--count",
                "0",
            ],
            timeout_s=90,
            cwd=WATCHF_ROOT,
        )
    except DispatchError as exc:
        return dict(base, status="BLOCKED_PROBE_FAILED", detail=str(exc))
    combined = f"{completed.stdout}\n{completed.stderr}".strip()
    decision = next(
        (
            line.removeprefix("- Decision: ").strip()
            for line in combined.splitlines()
            if line.startswith("- Decision: ")
        ),
        "",
    )
    ready = completed.returncode == 0 and decision.startswith(("READY", "PASS"))
    status = "READY_CDP" if ready else "BLOCKED_CDP"
    return dict(base, status=status, detail=combined[-1000:])


def _ox_probe(*, deep: bool) -> dict[str, object]:
    executable = _executable("opencode")
    if not executable:
        return {"status": "BLOCKED_NOT_FOUND", "model": DEFAULT_OX_MODEL}
    if not deep:
        return {
            "status": "UNVERIFIED_MODEL",
            "executable": executable,
            "model": DEFAULT_OX_MODEL,
        }
    try:
        completed = _capture(
            _command_prefix(executable) + ["models"],
            timeout_s=60,
        )
    except DispatchError as exc:
        return {
            "status": "BLOCKED_PROBE_FAILED",
            "executable": executable,
            "model": DEFAULT_OX_MODEL,
            "detail": str(exc),
        }
    combined = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        status = "BLOCKED_PROBE_FAILED"
    elif DEFAULT_OX_MODEL not in combined:
        status = "BLOCKED_MODEL_MISSING"
    else:
        status = "READY"
    return {
        "status": status,
        "executable": executable,
        "model": DEFAULT_OX_MODEL,
        "detail": combined.strip()[-1000:],
    }


def _antigravity_probe(*, deep: bool) -> dict[str, object]:
    executable = _executable("antigravity")
    if not executable:
        return {
            "status": "BLOCKED_NOT_FOUND",
            "model": DEFAULT_ANTIGRAVITY_MODEL,
        }
    if not deep:
        return {
            "status": "UNVERIFIED_MODEL",
            "executable": executable,
            "model": DEFAULT_ANTIGRAVITY_MODEL,
        }
    try:
        completed = _capture([executable, "models"], timeout_s=60)
    except DispatchError as exc:
        return {
            "status": "BLOCKED_PROBE_FAILED",
            "executable": executable,
            "model": DEFAULT_ANTIGRAVITY_MODEL,
            "detail": str(exc),
        }
    combined = f"{completed.stdout}\n{completed.stderr}"
    lowered = combined.lower()
    if "access is denied" in lowered or "permission denied" in lowered:
        status = "BLOCKED_PROFILE_ACCESS"
    elif "please sign in" in lowered or "not logged in" in lowered:
        status = "BLOCKED_AUTH"
    elif completed.returncode != 0:
        status = "BLOCKED_PROBE_FAILED"
    elif DEFAULT_ANTIGRAVITY_MODEL not in combined:
        status = "BLOCKED_MODEL_MISSING"
    else:
        status = "READY"
    return {
        "status": status,
        "executable": executable,
        "model": DEFAULT_ANTIGRAVITY_MODEL,
        "detail": combined.strip()[-1000:],
    }


def _http_json(
    url: str,
    *,
    timeout_s: int,
    payload: dict[str, object] | None = None,
) -> object:
    data = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        body = response.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


def _qwen_model_ids() -> list[str]:
    payload = _http_json(f"{QWEN_BASE_URL}/v1/models", timeout_s=10)
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [
        str(item.get("id"))
        for item in data
        if isinstance(item, dict) and item.get("id")
    ]


def _qwen_probe(*, deep: bool) -> dict[str, object]:
    base = {
        "endpoint": QWEN_BASE_URL,
        "model": DEFAULT_QWEN_MODEL,
        "capability": "no-tools-codegen",
    }
    if not deep:
        return dict(base, status="UNVERIFIED_ENDPOINT")
    try:
        health = _http_json(f"{QWEN_BASE_URL}/health", timeout_s=5)
        model_ids = _qwen_model_ids()
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return dict(base, status="BLOCKED_OFFLINE", detail=str(exc))
    if not any("qwen3.8" in model.lower() for model in model_ids):
        return dict(
            base,
            status="BLOCKED_MODEL_MISSING",
            detail={"health": health, "models": model_ids},
        )
    return dict(
        base,
        status="READY",
        resolved_model=next(
            model for model in model_ids if "qwen3.8" in model.lower()
        ),
        detail=health,
    )


def _perplexity_probe(*, deep: bool) -> dict[str, object]:
    base = {
        "transport": "cdp",
        "driver": str(PERPLEXITY_DRIVER),
        "role": "chrome_ppl",
    }
    if (
        not WATCHF_PYTHON.is_file()
        or not PERPLEXITY_DRIVER.is_file()
        or not PERPLEXITY_PROBE_DRIVER.is_file()
    ):
        return dict(base, status="BLOCKED_NOT_FOUND")
    if not deep:
        return dict(base, status="UNVERIFIED_CDP")
    try:
        completed = _capture(
            [
                str(WATCHF_PYTHON),
                str(PERPLEXITY_PROBE_DRIVER),
                "--probe-models",
            ],
            timeout_s=120,
            cwd=WATCHF_ROOT,
        )
    except DispatchError as exc:
        return dict(base, status="BLOCKED_PROBE_FAILED", detail=str(exc))
    combined = f"{completed.stdout}\n{completed.stderr}".strip()
    return dict(
        base,
        status="READY_CDP" if completed.returncode == 0 else "BLOCKED_CDP",
        detail=combined[-2000:],
    )


def _fable_probe(*, deep: bool) -> dict[str, object]:
    executable = _executable("claude")
    if not executable:
        return {
            "status": "BLOCKED_NOT_FOUND",
            "model": DEFAULT_FABLE_MODEL,
        }
    version = _version_probe("claude")
    if version["status"] != "READY":
        return dict(version, model=DEFAULT_FABLE_MODEL)
    return {
        "status": "JIT_CRITICAL_ONLY",
        "executable": executable,
        "model": DEFAULT_FABLE_MODEL,
        "detail": (
            f"{version.get('detail', '')}; model call intentionally deferred"
            if deep
            else version.get("detail", "")
        ),
    }


def doctor(*, deep: bool = False) -> int:
    codex = _version_probe("codex")
    git = _version_probe("git")
    supervisor_model = os.environ.get(
        "MODEL_TEAM_SUPERVISOR_MODEL",
        ROLE_CONFIG.get("supervisor", {}).get("model", "gpt-6-astra"),
    )
    supervisor = {
        "status": codex["status"],
        "executable": codex.get("executable"),
        "model": supervisor_model,
        "detail": codex.get("detail", ""),
    }
    lanes = {
        "supervisor": supervisor,
        "sol": dict(codex, model=ROLE_CONFIG["sol"]["model"]),
        "luna": {
            "status": codex["status"],
            "executable": codex.get("executable"),
            "model": "gpt-5.6-luna",
            "role": "routine_local_ops",
            "detail": "optional local worker",
        },
        "chatgpt": _chatgpt_probe(deep=deep),
        "ox": _ox_probe(deep=deep),
        "antigravity": _antigravity_probe(deep=deep),
        "qwen": _qwen_probe(deep=deep),
        "perplexity": _perplexity_probe(deep=deep),
        "fable": _fable_probe(deep=deep),
        "cursor": {
            "status": "DISABLED_OPERATOR",
            "disabled_until": CURSOR_DISABLED_UNTIL,
            "detail": "fresh explicit operator re-enable required after this date",
        },
    }
    core_ready = codex["status"] == "READY" and git["status"] == "READY"
    ready_writers = [
        role
        for role in DIRECT_WRITE_ROLES
        if lanes[role]["status"] in READY_STATUSES
    ]
    ready_advisors = [
        role
        for role in ADVISORY_ROLES
        if lanes[role]["status"] in READY_STATUSES
    ]
    all_primary_ready = all(
        lanes[role]["status"] in READY_STATUSES
        for role in ("chatgpt", "ox", "antigravity")
    )
    if core_ready and all_primary_ready:
        overall = "READY"
    elif core_ready and ready_writers:
        overall = "DEGRADED"
    else:
        overall = "BLOCKED"
    print(
        json.dumps(
            {
                "overall": overall,
                "deep": deep,
                "git": git,
                "ready_writers": ready_writers,
                "ready_advisors": ready_advisors,
                "retired_roles": ["kimi"],
                "lanes": lanes,
            },
            indent=2,
            # Provider diagnostics can contain Polish text; escaped JSON stays
            # printable on Windows consoles that still use legacy code pages.
            ensure_ascii=True,
        )
    )
    return 0 if overall != "BLOCKED" else 1


def _antigravity_command(prompt: str, timeout_s: int) -> list[str]:
    executable = _executable("antigravity")
    if not executable:
        raise DispatchError("Antigravity CLI not found")
    log_path = Path(tempfile.gettempdir()) / f"model-team-agy-{os.getpid()}.log"
    return [
        executable,
        "--log-file",
        str(log_path),
        "--model",
        DEFAULT_ANTIGRAVITY_MODEL,
        "--effort",
        "high",
        "--mode",
        "accept-edits",
        "--sandbox",
        "--output-format",
        "stream-json",
        "--print-timeout",
        f"{timeout_s}s",
        "--print",
        prompt,
    ]


def _ox_command(repo: Path, prompt_file: Path) -> list[str]:
    executable = _executable("opencode")
    if not executable:
        raise DispatchError("OpenCode CLI not found")
    return _command_prefix(executable) + [
        "run",
        "--model",
        DEFAULT_OX_MODEL,
        "--auto",
        "--title",
        f"model-team-{prompt_file.stem}",
        "--dir",
        str(repo),
    ]


def _chatgpt_command(args: argparse.Namespace, repo: Path, out: Path) -> list[str]:
    if not args.target_file:
        raise DispatchError("chatgpt requires --target-file")
    if not CHATGPT_CDP_DRIVER.is_file() or not WATCHF_PYTHON.is_file():
        raise DispatchError("ChatGPT CDP driver or WatchF Python is missing")
    command = [
        str(WATCHF_PYTHON),
        str(CHATGPT_CDP_DRIVER),
        "--prompt-file",
        str(args.prompt_file.resolve()),
        "--write",
        args.target_file,
        "--repo-root",
        str(repo),
        "--require-single",
        "--out",
        str(out),
    ]
    for current in args.include_current:
        command.extend(["--include-current", current])
    if args.provider_model:
        command.extend(["--model", args.provider_model])
    return command


def _perplexity_command(
    args: argparse.Namespace,
    out: Path,
) -> tuple[list[str], Path]:
    if not args.provider_model:
        raise DispatchError("perplexity requires --provider-model from live picker")
    if not WATCHF_PYTHON.is_file() or not PERPLEXITY_DRIVER.is_file():
        raise DispatchError("Perplexity CDP driver or WatchF Python is missing")
    metadata_path = out.with_suffix(out.suffix + ".meta.json")
    command = [
        str(WATCHF_PYTHON),
        str(PERPLEXITY_DRIVER),
        str(args.prompt_file.resolve()),
        "--model",
        args.provider_model,
        "--output",
        str(out),
        "--response-timeout-s",
        str(args.timeout_s),
    ]
    return command, metadata_path


def _require_coderpx_packet(prompt: str) -> None:
    required = (
        "=== CODERPX PACKET ===",
        "Schema: coderpx.packet.v2",
        "=== END PACKET ===",
    )
    missing = [marker for marker in required if marker not in prompt]
    if missing:
        raise DispatchError(
            "perplexity requires a rendered coderpx.packet.v2 packet; "
            f"missing: {missing}"
        )


def _validate_coderpx_result(
    metadata: dict[str, object],
    *,
    packet_path: Path,
    response_path: Path,
    requested_model: str,
) -> None:
    try:
        manifest_response_path = Path(str(metadata["response_path"])).resolve()
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise DispatchError("CoderPX manifest response_path is invalid") from exc
    response_sha256 = hashlib.sha256(response_path.read_bytes()).hexdigest()
    packet_sha256 = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    requested_label = str(metadata.get("requested_model_label") or "").strip()
    verified_model = str(metadata.get("verified_model") or "").strip()
    valid = (
        metadata.get("schema") == "coderpx.result.v1"
        and metadata.get("status") == "SUCCESS"
        and metadata.get("exit_code") == 0
        and manifest_response_path == response_path.resolve()
        and metadata.get("response_sha256") == response_sha256
        and metadata.get("packet_sha256") == packet_sha256
        and metadata.get("requested_model_fragment") == requested_model
        and bool(requested_label)
        and bool(verified_model)
        and requested_label.lower() in verified_model.lower()
    )
    if not valid:
        raise DispatchError("CoderPX success manifest contract failed")


def _fable_command(prompt: str) -> list[str]:
    executable = _executable("claude")
    if not executable:
        raise DispatchError("Claude CLI not found")
    return [
        executable,
        "--safe-mode",
        "--model",
        DEFAULT_FABLE_MODEL,
        "--effort",
        "max",
        "--permission-mode",
        "plan",
        "--tools",
        "",
        "--no-session-persistence",
        "--output-format",
        "json",
        "-p",
        prompt,
    ]


def _validate_antigravity_output(text: str) -> None:
    events: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DispatchError("antigravity returned non-JSON stream output") from exc
        if isinstance(value, dict):
            events.append(value)
    rendered = json.dumps(events, ensure_ascii=False).lower()
    if (
        DEFAULT_ANTIGRAVITY_MODEL.lower() not in rendered
        and "gemini 3.7 flash" not in rendered
    ):
        raise DispatchError(
            "Antigravity output did not prove Gemini 3.7 Flash identity"
        )
    result_event = next(
        (event for event in reversed(events) if event.get("event") == "result"),
        None,
    )
    result = result_event.get("result") if result_event else None
    if not isinstance(result, dict) or result.get("status") != "SUCCESS":
        raise DispatchError("Antigravity returned no successful final result")


def _validate_fable_output(text: str) -> None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DispatchError("Fable returned non-JSON output") from exc
    rendered = json.dumps(value, ensure_ascii=False).lower()
    if "fable" not in rendered and "claude-fable-5" not in rendered:
        raise DispatchError("Fable output did not prove Fable model identity")


def _qwen_ask(prompt: str, *, timeout_s: int) -> tuple[str, str]:
    try:
        model_ids = _qwen_model_ids()
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise DispatchError(f"Qwen is offline: {exc}") from exc
    model = next(
        (candidate for candidate in model_ids if "qwen3.8" in candidate.lower()),
        None,
    )
    if not model:
        raise DispatchError(f"Qwen3.8 model missing from local server: {model_ids}")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a bounded offline code-generation adviser. "
                    "Do not claim to edit files, run tests, call tools, commit, push, "
                    "merge, or affect runtime. Return a concrete draft for another "
                    "worktree writer to verify."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 8192,
    }
    try:
        response = _http_json(
            f"{QWEN_BASE_URL}/v1/chat/completions",
            timeout_s=timeout_s,
            payload=payload,
        )
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise DispatchError(f"Qwen request failed: {exc}") from exc
    if not isinstance(response, dict):
        raise DispatchError("Qwen returned a non-object response")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise DispatchError(f"Qwen returned no choices: {response}")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise DispatchError("Qwen returned empty content")
    return model, content.strip()


def run_role(args: argparse.Namespace) -> int:
    repo = _repo_root(args.repo.resolve())
    prompt_file = args.prompt_file.resolve()
    if not prompt_file.is_file():
        raise DispatchError(f"prompt file does not exist: {prompt_file}")
    prompt = prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise DispatchError("prompt file is empty")
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.role in DIRECT_WRITE_ROLES:
        _require_implementation_worktree(repo, args.role)
    if args.role == "perplexity":
        _require_coderpx_packet(prompt)
        if args.task_kind in {"code", "tests", "integration"}:
            _require_implementation_worktree(repo, args.role)
    if args.role == "fable":
        if not args.critical or args.task_kind not in FABLE_TASK_KINDS:
            raise DispatchError(
                "fable requires --critical and --task-kind architecture|quant|design"
            )

    artifact_dir: Path | None = None
    stdin: str | None = None
    if args.role == "qwen":
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "role": "qwen",
                        "repo": str(repo),
                        "out": str(out),
                        "endpoint": f"{QWEN_BASE_URL}/v1/chat/completions",
                        "model": DEFAULT_QWEN_MODEL,
                        "capability": "no-tools-codegen",
                    },
                    indent=2,
                )
            )
            return 0
        model, result = _qwen_ask(prompt, timeout_s=args.timeout_s)
        out.write_text(f"model: {model}\n\n{result}\n", encoding="utf-8")
        return 0
    if args.role == "antigravity":
        command = _antigravity_command(prompt, args.timeout_s)
    elif args.role == "ox":
        command = _ox_command(repo, prompt_file)
        stdin = prompt
    elif args.role == "chatgpt":
        command = _chatgpt_command(args, repo, out)
    elif args.role == "perplexity":
        command, artifact_dir = _perplexity_command(args, out)
    elif args.role == "fable":
        command = _fable_command(prompt)
    else:
        raise DispatchError(f"unsupported role: {args.role}")

    if args.dry_run:
        print(
            json.dumps(
                {
                    "role": args.role,
                    "repo": str(repo),
                    "out": str(out),
                    "command": command,
                    "prompt_transport": "stdin" if stdin is not None else "argument/file",
                    "artifact_dir": str(artifact_dir) if artifact_dir else None,
                },
                indent=2,
            )
        )
        return 0

    outer_timeout_s = args.timeout_s + 120 if args.role == "perplexity" else args.timeout_s
    try:
        completed = _capture(
            command,
            timeout_s=outer_timeout_s,
            input_text=stdin,
            cwd=repo if args.role not in {"chatgpt", "perplexity"} else WATCHF_ROOT,
        )
    except DispatchError:
        if args.role == "perplexity":
            print(
                json.dumps(
                    {
                        "status": "NO_RESULT",
                        "role": "perplexity",
                        "exit_code": 70,
                        "response_path": str(out),
                        "metadata_path": str(artifact_dir),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
        raise
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-3000:]
        if args.role == "perplexity":
            print(
                json.dumps(
                    {
                        "status": "NO_RESULT",
                        "role": "perplexity",
                        "exit_code": completed.returncode,
                        "response_path": str(out),
                        "metadata_path": str(artifact_dir),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
        if detail:
            print(detail, file=sys.stderr)
        return completed.returncode

    if args.role == "chatgpt":
        if not out.is_file():
            raise DispatchError("ChatGPT CDP driver returned success without result JSON")
    elif args.role == "perplexity":
        if not out.is_file() or artifact_dir is None or not artifact_dir.is_file():
            raise DispatchError("CoderPX returned success without response and metadata")
        try:
            metadata = json.loads(artifact_dir.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DispatchError("CoderPX metadata is invalid JSON") from exc
        if not isinstance(metadata, dict):
            raise DispatchError("CoderPX metadata must be a JSON object")
        _validate_coderpx_result(
            metadata,
            packet_path=prompt_file,
            response_path=out,
            requested_model=args.provider_model,
        )
        print(
            json.dumps(
                {
                    "status": "RESULT",
                    "role": "perplexity",
                    "exit_code": 0,
                    "response_path": str(out),
                    "metadata_path": str(artifact_dir),
                    "verified_model": metadata.get("verified_model"),
                },
                indent=2,
            )
        )
    else:
        output = completed.stdout or ""
        if args.role == "antigravity":
            _validate_antigravity_output(output)
        elif args.role == "fable":
            _validate_fable_output(output)
        out.write_text(output, encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser(
        "doctor", help="check executables, endpoints, auth, and exact models"
    )
    doctor_parser.add_argument(
        "--deep", action="store_true", help="run non-mutating provider preflights"
    )

    run = subparsers.add_parser("run", help="dispatch one fixed model role")
    run.add_argument("--role", choices=DISPATCH_ROLES, required=True)
    run.add_argument("--repo", type=Path, required=True)
    run.add_argument("--prompt-file", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--timeout-s", type=int, default=900)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument(
        "--target-file",
        help="repo-relative single target file for the ChatGPT CDP writer",
    )
    run.add_argument(
        "--include-current",
        action="append",
        default=[],
        help="repo-relative file to embed for ChatGPT CDP (repeatable)",
    )
    run.add_argument(
        "--provider-model",
        help="ChatGPT label or live Perplexity picker fragment",
    )
    run.add_argument(
        "--task-kind",
        choices=(
            "code",
            "tests",
            "integration",
            "architecture",
            "quant",
            "design",
            "research",
            "review",
        ),
        default="code",
    )
    run.add_argument(
        "--critical",
        action="store_true",
        help="required for critical-only Fable architecture/quant/design advice",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return doctor(deep=args.deep) if args.command == "doctor" else run_role(args)
    except DispatchError as exc:
        print(f"model-team FAILED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
