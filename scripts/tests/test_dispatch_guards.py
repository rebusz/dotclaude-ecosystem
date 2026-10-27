#!/usr/bin/env python3
"""Replay tests for the dispatch-enforcement hooks.

Each guard's decide() is driven in-process, and each hook script is also run
as a subprocess with JSON on stdin. State stays under pytest tmp_path via
DISPATCH_GUARD_STATE_DIR. Override tests configure a plain key file via
DISPATCH_GUARD_ALLOW_PLAIN_KEY_FILE=1 and DISPATCH_GUARD_KEY_FILE so they
never touch DPAPI. The DPAPI round-trip is skipped off Windows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

import claude_worker_guard  # noqa: E402
import dispatch_bash_guard  # noqa: E402
import dispatch_edit_guard  # noqa: E402
import dispatch_guard_common  # noqa: E402
import dispatch_read_guard  # noqa: E402
import dispatch_tier_marker  # noqa: E402

_TEST_KEY = "ab" * 32
_COORDINATOR = dispatch_guard_common.COORDINATOR_LINE
_COMPOUND = (
    'S="C:/tmp/scratch"; cd D:/APPS/_worktrees/x; '
    'codex exec -m gpt-6-luna -s workspace-write '
    '"$(cat \\"$S/b.txt\\")" < /dev/null'
)
_CDP = (
    "D:/APPS/WatchF/.venv/Scripts/python.exe "
    "D:/APPS/WatchF/scripts/cdp_gemini_oneshot.py "
    '--model "Gemini 4 Argon" --prompt-file p --out o'
)
_OPUS_PROMPTS = (
    "Review the diff and report defects in the guard logic.",
    "Read the module and summarise how the budget is charged.",
    "Quant the slippage model and report the error bands.",
)


def _env(state: Path, **extra: str) -> dict[str, str]:
    mapping = {"DISPATCH_GUARD_STATE_DIR": str(state)}
    mapping.update(extra)
    return mapping


def _override_env(state: Path, **extra: str) -> dict[str, str]:
    key_file = state / "test_override.key"
    if not key_file.exists():
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(bytes.fromhex(_TEST_KEY))
    mapping = {
        "DISPATCH_GUARD_STATE_DIR": str(state),
        "DISPATCH_GUARD_ALLOW_PLAIN_KEY_FILE": "1",
        "DISPATCH_GUARD_KEY_FILE": str(key_file),
    }
    mapping.update(extra)
    return mapping


def _hook(
    tool_name: str,
    tool_input: dict,
    *,
    session_id: str = "sess-1",
    agent_id: str | None = None,
    cwd: str = "D:/APPS/_worktrees/x",
    event: str = "PreToolUse",
    tool_use_id: str = "toolu_synthetic",
) -> dict:
    body: dict = {
        "session_id": session_id,
        "transcript_path": "C:/tmp/synthetic-transcript.jsonl",
        "cwd": cwd,
        "hook_event_name": event,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": tool_use_id,
    }
    if agent_id:
        body["agent_id"] = agent_id
    return body


def _agent(model: str | None, prompt: str, **extra: object) -> dict:
    tool_input: dict = {
        "description": "synthetic worker",
        "subagent_type": "general-purpose",
        "prompt": prompt,
        "run_in_background": False,
    }
    if model is not None:
        tool_input["model"] = model
    agent_id = extra.pop("agent_id", None)
    session_id = str(extra.pop("session_id", "sess-1"))
    return _hook(
        "Agent",
        tool_input,
        session_id=session_id,
        agent_id=agent_id if isinstance(agent_id, str) else None,
    )


def _start_session(model: str | None, prompt: str) -> dict:
    tool_input: dict = {
        "initiation": "user_asked",
        "title": "synthetic session",
        "name": "worker",
        "context": "fresh",
        "cwd": "D:/APPS/WatchF",
        "prompt": prompt,
        "background": "relay only",
        "use_worktree": True,
    }
    if model is not None:
        tool_input["model"] = model
    return _hook("mcp__ccd_session__start_session", tool_input, cwd="D:/APPS/WatchF")


def _reason(result: dict | None) -> str:
    assert result is not None
    return result["hookSpecificOutput"]["permissionDecisionReason"]


def _corrected(result: dict | None) -> dict:
    reason = _reason(result)
    marker = "Corrected call: "
    assert marker in reason
    return json.loads(reason.split(marker, 1)[1])


def _lines(count: int) -> str:
    return "\n".join(f"row {index}" for index in range(count))


def _run_hook(
    script: str,
    stdin: bytes,
    state: Path,
    args: list[str] | None = None,
    extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env["DISPATCH_GUARD_STATE_DIR"] = str(state)
    for name in (
        "DISPATCH_GUARD_TIER",
        "DISPATCH_GUARD_TEST_KEY",
        "DISPATCH_GUARD_KEY_FILE",
        "DISPATCH_GUARD_ALLOW_PLAIN_KEY_FILE",
    ):
        env.pop(name, None)
    if extra:
        env.update(extra)
    return subprocess.run(
        [sys.executable, str(_SCRIPTS / script), *(args or [])],
        input=stdin,
        capture_output=True,
        env=env,
        check=False,
    )


def _stdout_json(proc: subprocess.CompletedProcess[bytes]) -> dict:
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return json.loads(proc.stdout.decode("utf-8"))


def _git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr.decode("utf-8", "replace"))


# --- claude_worker_guard ---------------------------------------------------


@pytest.mark.parametrize("prompt", _OPUS_PROMPTS)
def test_agent_opus_prompt_variants_are_denied(tmp_path: Path, prompt: str) -> None:
    result = claude_worker_guard.decide(_agent("opus", prompt), _env(tmp_path))
    assert result is not None
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "opus" in _reason(result).lower()
    hint = _corrected(result)
    assert hint["model"] == "sonnet"
    assert hint["prompt"].startswith(_COORDINATOR)
    assert prompt in hint["prompt"]


def test_agent_without_model_is_denied(tmp_path: Path) -> None:
    result = claude_worker_guard.decide(_agent(None, "Review the patch."), _env(tmp_path))
    assert "missing or empty" in _reason(result)
    assert _corrected(result)["model"] == "sonnet"


def test_agent_fable_is_denied(tmp_path: Path) -> None:
    result = claude_worker_guard.decide(_agent("fable", "Review the patch."), _env(tmp_path))
    assert "fable" in _reason(result).lower()


def test_sonnet_without_coordinator_line_is_denied(tmp_path: Path) -> None:
    result = claude_worker_guard.decide(_agent("sonnet", "do the work"), _env(tmp_path))
    assert "tier-2 coordinator" in _reason(result).lower()
    assert _corrected(result)["prompt"].startswith(_COORDINATOR)


def test_sonnet_with_coordinator_line_is_allowed(tmp_path: Path) -> None:
    assert claude_worker_guard.decide(_agent("sonnet", _COORDINATOR), _env(tmp_path)) is None


def test_haiku_with_coordinator_line_is_allowed(tmp_path: Path) -> None:
    assert claude_worker_guard.decide(_agent("haiku", _COORDINATOR), _env(tmp_path)) is None


def test_subagent_spawn_is_denied_for_depth(tmp_path: Path) -> None:
    payload = _agent("sonnet", _COORDINATOR, agent_id="agent-child")
    result = claude_worker_guard.decide(payload, _env(tmp_path))
    assert "max agent depth is 1" in _reason(result)
    assert _corrected(result)["model"] == "sonnet"


def test_start_session_sonnet_with_line_is_allowed(tmp_path: Path) -> None:
    payload = _start_session("claude-sonnet-5-5", _COORDINATOR)
    assert claude_worker_guard.decide(payload, _env(tmp_path)) is None


def test_start_session_without_model_is_denied(tmp_path: Path) -> None:
    result = claude_worker_guard.decide(_start_session(None, _COORDINATOR), _env(tmp_path))
    assert "missing or empty" in _reason(result)


def test_start_session_opus_is_denied(tmp_path: Path) -> None:
    result = claude_worker_guard.decide(
        _start_session("claude-opus-5", _COORDINATOR), _env(tmp_path)
    )
    assert "opus" in _reason(result).lower()
    assert _corrected(result)["model"] == "sonnet"


def test_workers_override_allows_opus(tmp_path: Path) -> None:
    env = _override_env(tmp_path)
    dispatch_guard_common.write_override("workers", 120, env)
    assert dispatch_guard_common.override_active("workers", env) is True
    assert claude_worker_guard.decide(_agent("opus", "Review the patch."), env) is None


def test_claude_worker_guard_subprocess_denies_opus(tmp_path: Path) -> None:
    proc = _run_hook(
        "claude_worker_guard.py",
        json.dumps(_agent("opus", _OPUS_PROMPTS[0])).encode(),
        tmp_path,
    )
    body = _stdout_json(proc)
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Corrected call:" in body["hookSpecificOutput"]["permissionDecisionReason"]


# --- dispatch_bash_guard ---------------------------------------------------


def test_split_statements_respects_quotes_and_drops_heredoc_bodies() -> None:
    quoted = 'echo "a; b && c || d | e" && echo tail'
    assert dispatch_bash_guard.split_statements(quoted) == [
        'echo "a; b && c || d | e"',
        "echo tail",
    ]
    assert dispatch_bash_guard.split_statements("echo 'x; y && z'") == ["echo 'x; y && z'"]
    heredoc = "cat > x.md <<'EOF'\ncodex exec -m\nEOF\n"
    assert dispatch_bash_guard.split_statements(heredoc) == ["cat > x.md <<'EOF'"]
    unquoted = "cat > x.md <<EOF\ncodex exec -m\nEOF\n"
    assert all("codex exec" not in part for part in dispatch_bash_guard.split_statements(unquoted))
    dashed = "cat <<-'EOF'\n\tcodex exec\nEOF\n"
    assert all("codex exec" not in part for part in dispatch_bash_guard.split_statements(dashed))
    herestring = "Write-Host @'\ncodex exec -m\n'@"
    assert all("codex exec" not in part for part in dispatch_bash_guard.split_statements(herestring))
    assert dispatch_bash_guard.split_statements("echo x 2>&1") == ["echo x 2>&1"]
    assert dispatch_bash_guard.split_statements("echo a & echo b") == ["echo a", "echo b"]


def _bash(command: str, tool_name: str = "Bash") -> dict:
    return _hook(tool_name, {"command": command})


def test_compound_codex_exec_is_denied(tmp_path: Path) -> None:
    parts = dispatch_bash_guard.split_statements(_COMPOUND)
    assert any(part.lstrip().startswith("codex ") for part in parts)
    result = dispatch_bash_guard.decide(_bash(_COMPOUND), _env(tmp_path))
    assert "R2" in _reason(result)
    assert "codex exec" in _reason(result)
    assert "dispatch.py" in _reason(result)


def test_glm_cmd_is_denied(tmp_path: Path) -> None:
    command = 'glm.cmd -p "x" --permission-mode acceptEdits'
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R2" in _reason(result)
    assert "glm.cmd" in _reason(result)


def test_cursor_agent_cmd_is_denied(tmp_path: Path) -> None:
    result = dispatch_bash_guard.decide(_bash('cursor-agent.cmd -p "x"'), _env(tmp_path))
    assert "R2" in _reason(result)


def test_cdp_gemini_oneshot_is_denied_unless_probe(tmp_path: Path) -> None:
    env = _env(tmp_path)
    denied = dispatch_bash_guard.decide(_bash(_CDP), env)
    assert "R2" in _reason(denied)
    assert "cdp_gemini_oneshot.py" in _reason(denied)
    probe_cmd = (
        "D:/APPS/WatchF/.venv/Scripts/python.exe "
        "D:/APPS/WatchF/scripts/cdp_gemini_oneshot.py --probe"
    )
    assert dispatch_bash_guard.decide(_bash(probe_cmd), env) is None


def test_dispatch_py_lane_and_packet_are_allowed(tmp_path: Path) -> None:
    env = _env(tmp_path)
    lane = "python D:/APPS/_shared/dispatch/dispatch.py lane review --brief b.md"
    packet = "python D:/APPS/_shared/dispatch/dispatch.py pkt.md --local --worktree W"
    assert dispatch_bash_guard.decide(_bash(lane), env) is None
    assert dispatch_bash_guard.decide(_bash(packet), env) is None


def test_grep_mention_of_codex_exec_is_allowed(tmp_path: Path) -> None:
    command = 'grep -n "codex exec" notes.txt'
    assert dispatch_bash_guard.decide(_bash(command), _env(tmp_path)) is None


def test_heredoc_body_mentioning_codex_is_allowed(tmp_path: Path) -> None:
    command = "cat > x.md <<'EOF'\ncodex exec -m\nEOF\n"
    assert dispatch_bash_guard.decide(_bash(command), _env(tmp_path)) is None


def test_redirect_to_lane_health_is_denied(tmp_path: Path) -> None:
    command = "echo x > C:/Users/dszub/.claude/state/lane_health.json"
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R3" in _reason(result)
    assert "lane_health.json" in _reason(result)


def test_redirect_to_allow_claude_workers_is_denied(tmp_path: Path) -> None:
    command = "echo x > ~/.claude/state/allow_claude_workers"
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R3" in _reason(result)
    assert "allow_claude_workers" in _reason(result)


def test_sed_inplace_source_is_denied(tmp_path: Path) -> None:
    result = dispatch_bash_guard.decide(_bash("sed -i s/a/b/ foo.py"), _env(tmp_path))
    assert "R3" in _reason(result)
    assert "foo.py" in _reason(result)


def test_cp_source_is_denied(tmp_path: Path) -> None:
    result = dispatch_bash_guard.decide(_bash("cp a.py b.py"), _env(tmp_path))
    assert "R3" in _reason(result)
    assert "b.py" in _reason(result)


def test_git_commit_mentioning_codex_is_allowed(tmp_path: Path) -> None:
    command = 'git commit -m "mention codex exec"'
    assert dispatch_bash_guard.decide(_bash(command), _env(tmp_path)) is None


def test_lane_repair_without_queue_file_is_denied(tmp_path: Path) -> None:
    command = "codex exec --lane-repair repair42"
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    text = _reason(result)
    assert "repair42" in text
    assert "unknown" in text


def test_lane_repair_with_queue_file_is_allowed(tmp_path: Path) -> None:
    queue = tmp_path / "lane_queue"
    queue.mkdir()
    (queue / "repair42.json").write_text(
        json.dumps({"kind": "lane_repair", "status": "queued"}),
        encoding="utf-8",
    )
    command = "codex exec --lane-repair repair42"
    assert dispatch_bash_guard.decide(_bash(command), _env(tmp_path)) is None


def test_powershell_glm_call_is_denied(tmp_path: Path) -> None:
    command = "& 'C:/Users/dszub/.local/bin/glm.cmd' -p x"
    result = dispatch_bash_guard.decide(_bash(command, "PowerShell"), _env(tmp_path))
    assert "R2" in _reason(result)
    assert "glm.cmd" in _reason(result)


def test_dispatch_bash_guard_subprocess_denies_compound_codex(tmp_path: Path) -> None:
    proc = _run_hook(
        "dispatch_bash_guard.py",
        json.dumps(_bash(_COMPOUND)).encode(),
        tmp_path,
    )
    body = _stdout_json(proc)
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "R2" in body["hookSpecificOutput"]["permissionDecisionReason"]


# --- dispatch_read_guard ---------------------------------------------------


def test_supervisor_read_of_python_source_is_denied(tmp_path: Path) -> None:
    payload = _hook("Read", {"file_path": str(tmp_path / "foo.py")}, cwd=str(tmp_path))
    result = dispatch_read_guard.decide(payload, _env(tmp_path))
    assert "source reads go to `lane diagnose`" in _reason(result)


def test_supervisor_read_of_design_markdown_is_allowed(tmp_path: Path) -> None:
    path = tmp_path / "design" / "plans" / "x.md"
    path.parent.mkdir(parents=True)
    path.write_text("plan\n", encoding="utf-8")
    payload = _hook("Read", {"file_path": str(path)}, cwd=str(tmp_path))
    assert dispatch_read_guard.decide(payload, _env(tmp_path)) is None


def test_supervisor_read_of_50kb_text_without_limit_is_denied(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_bytes(b"x" * (50 * 1024))
    payload = _hook("Read", {"file_path": str(path)}, cwd=str(tmp_path))
    result = dispatch_read_guard.decide(payload, _env(tmp_path))
    assert "40 KB" in _reason(result)


def test_supervisor_cumulative_read_cap_denies(tmp_path: Path) -> None:
    path = tmp_path / "cap.txt"
    path.write_bytes(b"y" * (40 * 1024))
    env = _env(tmp_path / "state")
    payload = _hook(
        "Read",
        {"file_path": str(path)},
        cwd=str(tmp_path),
        session_id="supervisor-read",
    )
    for _ in range(3):
        assert dispatch_read_guard.decide(payload, env) is None
    result = dispatch_read_guard.decide(payload, env)
    assert "read budget exhausted" in _reason(result)


def test_tier2_read_cap_is_larger_than_supervisor(tmp_path: Path) -> None:
    path = tmp_path / "cap.txt"
    path.write_bytes(b"y" * (40 * 1024))
    env = _env(tmp_path / "state")
    payload = _hook(
        "Read",
        {"file_path": str(path)},
        cwd=str(tmp_path),
        agent_id="reader",
    )
    for _ in range(4):
        assert dispatch_read_guard.decide(payload, env) is None
    used = dispatch_guard_common.get_counter("read_bytes", "reader", env)
    assert used > dispatch_guard_common.SUPERVISOR_READ_CAP
    assert used <= dispatch_guard_common.TIER2_READ_CAP


def test_supervisor_grep_type_py_is_denied(tmp_path: Path) -> None:
    payload = _hook("Grep", {"pattern": "def ", "type": "py"}, cwd=str(tmp_path))
    result = dispatch_read_guard.decide(payload, _env(tmp_path))
    assert "source reads go to `lane diagnose`" in _reason(result)


def test_post_accounting_adds_grep_bytes_and_not_read_bytes(tmp_path: Path) -> None:
    env = _env(tmp_path)
    response = {"hit": "alpha"}
    grep_post = _hook(
        "Grep",
        {"pattern": "a", "path": str(tmp_path / "notes.txt")},
        event="PostToolUse",
        session_id="acct",
    )
    grep_post["tool_response"] = response
    assert dispatch_read_guard.decide_post(grep_post, env) is None
    key = "session:acct"
    assert dispatch_guard_common.get_counter("read_bytes", key, env) == len(json.dumps(response))
    read_post = _hook("Read", {"file_path": str(tmp_path / "notes.txt")}, event="PostToolUse", session_id="acct")
    read_post["tool_response"] = "should not be charged"
    assert dispatch_read_guard.decide_post(read_post, env) is None
    assert dispatch_guard_common.get_counter("read_bytes", key, env) == len(json.dumps(response))


def test_post_big_output_warns(tmp_path: Path) -> None:
    env = _env(tmp_path)
    payload = _hook(
        "Grep",
        {"pattern": "a", "path": str(tmp_path / "notes.txt")},
        event="PostToolUse",
        session_id="big",
    )
    payload["tool_response"] = "z" * (dispatch_guard_common.BIG_OUTPUT_WARN + 80)
    result = dispatch_read_guard.decide_post(payload, env)
    assert result is not None
    context = result["hookSpecificOutput"]["additionalContext"]
    assert "Large output:" in context
    assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_post_over_cap_says_stop_reading(tmp_path: Path) -> None:
    env = _env(tmp_path)
    key = "session:stop"
    dispatch_guard_common.bump_counter(
        "read_bytes", key, dispatch_guard_common.SUPERVISOR_READ_CAP, env
    )
    payload = _hook(
        "Bash",
        {"command": "echo hi"},
        event="PostToolUse",
        session_id="stop",
    )
    payload["tool_response"] = {"n": 1}
    result = dispatch_read_guard.decide_post(payload, env)
    assert result is not None
    assert "STOP reading: send this to `lane diagnose`" in result["hookSpecificOutput"]["additionalContext"]


def test_dispatch_read_guard_subprocess_denies_source(tmp_path: Path) -> None:
    payload = _hook("Read", {"file_path": str(tmp_path / "foo.py")}, cwd=str(tmp_path))
    proc = _run_hook("dispatch_read_guard.py", json.dumps(payload).encode(), tmp_path)
    body = _stdout_json(proc)
    assert "source reads go to `lane diagnose`" in body["hookSpecificOutput"]["permissionDecisionReason"]


# --- dispatch_edit_guard ---------------------------------------------------


def test_supervisor_edit_of_python_is_denied(tmp_path: Path) -> None:
    state = tmp_path / "state"
    work = tmp_path / "work"
    work.mkdir()
    payload = _hook(
        "Edit",
        {"file_path": str(work / "x.py"), "old_string": "a", "new_string": "b"},
        cwd=str(work),
    )
    result = dispatch_edit_guard.decide(payload, _env(state))
    assert "the supervisor does not write source" in _reason(result)


def test_supervisor_edit_of_markdown_is_allowed(tmp_path: Path) -> None:
    state = tmp_path / "state"
    work = tmp_path / "work"
    work.mkdir()
    payload = _hook(
        "Edit",
        {"file_path": str(work / "notes.md"), "old_string": "a", "new_string": _lines(40)},
        cwd=str(work),
    )
    assert dispatch_edit_guard.decide(payload, _env(state)) is None


def test_tier2_edit_of_15_lines_then_10_is_denied(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dispatch-test@example.com")
    _git(repo, "config", "user.name", "Dispatch Test")
    _git(repo, "config", "core.autocrlf", "false")
    target = repo / "x.py"
    target.write_text("old\n", encoding="utf-8")
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-m", "init")

    env = _env(state)
    path = str(target)

    def edit(count: int, tool_use_id: str) -> dict:
        return _hook(
            "Edit",
            {"file_path": path, "old_string": "old", "new_string": _lines(count)},
            cwd=str(repo),
            agent_id="tier-edit",
            tool_use_id=tool_use_id,
        )

    assert dispatch_edit_guard.decide(edit(15, "tu-15"), env) is None
    result = dispatch_edit_guard.decide(edit(10, "tu-10"), env)
    assert "Tier-2 edit cap" in _reason(result)
    assert dispatch_guard_common.get_counter("edit_lines", "tier-edit", env) == 15


def test_tier2_write_of_30_line_python_is_denied(tmp_path: Path) -> None:
    state = tmp_path / "state"
    work = tmp_path / "work"
    work.mkdir()
    env = _env(state)
    payload = _hook(
        "Write",
        {"file_path": str(work / "big.py"), "content": _lines(30)},
        cwd=str(work),
        agent_id="writer",
    )
    result = dispatch_edit_guard.decide(payload, env)
    assert "Tier-2 edit cap" in _reason(result)
    assert dispatch_guard_common.get_counter("edit_lines", "writer", env) == 0


def test_tier2_non_source_edits_are_not_counted(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dispatch-test@example.com")
    _git(repo, "config", "user.name", "Dispatch Test")
    _git(repo, "config", "core.autocrlf", "false")
    target = repo / "x.py"
    target.write_text("old\n", encoding="utf-8")
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-m", "init")

    env = _env(state)
    markdown = _hook(
        "Edit",
        {"file_path": str(repo / "notes.md"), "old_string": "a", "new_string": _lines(100)},
        cwd=str(repo),
        agent_id="tier-md",
    )
    assert dispatch_edit_guard.decide(markdown, env) is None
    assert dispatch_guard_common.get_counter("edit_lines", "tier-md", env) == 0
    source = _hook(
        "Edit",
        {"file_path": str(target), "old_string": "old", "new_string": _lines(15)},
        cwd=str(repo),
        agent_id="tier-md",
        tool_use_id="tu-src",
    )
    assert dispatch_edit_guard.decide(source, env) is None
    assert dispatch_guard_common.get_counter("edit_lines", "tier-md", env) == 15


def test_post_hook_net_diff_over_20_lines_blocks_and_sets_flag(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dispatch-test@example.com")
    _git(repo, "config", "user.name", "Dispatch Test")
    _git(repo, "config", "core.autocrlf", "false")
    target = repo / "mod.py"
    target.write_bytes(b"value = 1\n")
    _git(repo, "add", "mod.py")
    _git(repo, "commit", "-m", "init")
    revised = ["value = 1"] + [f"extra_{index} = {index}" for index in range(30)]
    target.write_bytes(("\n".join(revised) + "\n").encode())
    payload = _hook(
        "Edit",
        {"file_path": str(target), "old_string": "value = 1", "new_string": "value = 1"},
        cwd=str(repo),
        event="PostToolUse",
        agent_id="worker-post",
        tool_use_id="toolu_post",
    )
    proc = _run_hook("dispatch_edit_guard.py", json.dumps(payload).encode(), state, ["--post"])
    body = _stdout_json(proc)
    assert body["decision"] == "block"
    assert body["reason"] == (
        "net source diff over 20 lines: stop editing, dispatch the rest to `lane impl`"
    )
    assert dispatch_guard_common.has_flag(
        "edit_cap_exceeded", "worker-post", _env(state)
    )


def test_dispatch_edit_guard_subprocess_denies_supervisor_source(tmp_path: Path) -> None:
    state = tmp_path / "state"
    work = tmp_path / "work"
    work.mkdir()
    payload = _hook(
        "Edit",
        {"file_path": str(work / "x.py"), "old_string": "a", "new_string": "b"},
        cwd=str(work),
    )
    proc = _run_hook("dispatch_edit_guard.py", json.dumps(payload).encode(), state)
    body = _stdout_json(proc)
    assert "the supervisor does not write source" in body["hookSpecificOutput"]["permissionDecisionReason"]


# --- fail closed -----------------------------------------------------------


@pytest.mark.parametrize(
    ("script", "args", "kind"),
    [
        ("claude_worker_guard.py", [], "deny"),
        ("dispatch_bash_guard.py", [], "deny"),
        ("dispatch_read_guard.py", [], "deny"),
        ("dispatch_read_guard.py", ["--post"], "block"),
        ("dispatch_edit_guard.py", [], "deny"),
        ("dispatch_edit_guard.py", ["--post"], "block"),
    ],
)
def test_invalid_json_fails_closed(tmp_path: Path, script: str, args: list[str], kind: str) -> None:
    proc = _run_hook(script, b"not-json", tmp_path, args)
    body = _stdout_json(proc)
    if kind == "block":
        assert body["decision"] == "block"
        text = body["reason"]
    else:
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
        text = body["hookSpecificOutput"]["permissionDecisionReason"]
    assert script in text or Path(script).name in text
    assert "Guarded tool call blocked (fail closed)" in text


def test_run_guarded_denies_when_decide_raises(capsys: pytest.CaptureFixture[str]) -> None:
    def boom() -> None:
        raise RuntimeError("boom")

    assert dispatch_guard_common.run_guarded("claude_worker_guard.py", boom) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "claude_worker_guard.py crashed: RuntimeError: boom" in (
        body["hookSpecificOutput"]["permissionDecisionReason"]
    )


def test_run_guarded_post_blocks_when_decide_raises(capsys: pytest.CaptureFixture[str]) -> None:
    def boom() -> None:
        raise ValueError("bad")

    assert dispatch_guard_common.run_guarded("scripts/dispatch_read_guard.py", boom, "PostToolUse") == 0
    body = json.loads(capsys.readouterr().out)
    assert body["decision"] == "block"
    assert "scripts/dispatch_read_guard.py crashed: ValueError: bad" in body["reason"]


def test_tier_marker_invalid_json_fails_open(tmp_path: Path) -> None:
    # The marker spec is fail-open: it never denies, and a bad payload is logged
    # to stderr. Tool guards above are the fail-closed path.
    proc = _run_hook("dispatch_tier_marker.py", b"not-json", tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.strip() == b""
    assert b"dispatch_tier_marker.py" in proc.stderr
    assert b"ValueError" in proc.stderr


def test_importing_guards_creates_no_state(tmp_path: Path) -> None:
    state = tmp_path / "unused"
    code = (
        "import claude_worker_guard, dispatch_bash_guard, dispatch_read_guard, "
        "dispatch_edit_guard, dispatch_tier_marker, lane_authorize, dispatch_guard_common"
    )
    env = os.environ.copy()
    env["DISPATCH_GUARD_STATE_DIR"] = str(state)
    env["PYTHONPATH"] = str(_SCRIPTS) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, check=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert not state.exists()


# --- override --------------------------------------------------------------


def test_write_override_is_active_until_it_expires(tmp_path: Path) -> None:
    env = _override_env(tmp_path)
    path = dispatch_guard_common.write_override("workers", 120, env)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert dispatch_guard_common.override_active("workers", env, now=raw["exp"] - 1) is True
    assert dispatch_guard_common.override_active("workers", env, now=raw["exp"] + 1) is False


def test_forged_signature_is_inactive(tmp_path: Path) -> None:
    env = _override_env(tmp_path)
    path = dispatch_guard_common.write_override("workers", 120, env)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["sig"] = "0" * len(raw["sig"])
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert dispatch_guard_common.override_active("workers", env) is False


def test_workers_scope_does_not_lift_hooks_off_rules(tmp_path: Path) -> None:
    env = _override_env(tmp_path)
    dispatch_guard_common.write_override("workers", 120, env)
    assert dispatch_guard_common.override_active("workers", env) is True
    assert dispatch_guard_common.override_active("hooks_off", env) is False
    result = dispatch_bash_guard.decide(_bash("codex exec hi"), env)
    assert "R2" in _reason(result)


def test_hooks_off_lifts_a_direct_launch(tmp_path: Path) -> None:
    env = _override_env(tmp_path)
    dispatch_guard_common.write_override("hooks_off", 120, env)
    assert dispatch_bash_guard.decide(_bash("codex exec hi"), env) is None


def test_plain_allow_claude_workers_file_does_nothing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "allow_claude_workers").write_text("1\n", encoding="utf-8")
    assert dispatch_guard_common.override_active("workers", env) is False
    result = claude_worker_guard.decide(_agent("opus", "Review the patch."), env)
    assert result is not None
    assert "opus" in _reason(result).lower()


def test_lane_authorize_without_tty_exits_2_and_writes_nothing(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["DISPATCH_GUARD_STATE_DIR"] = str(tmp_path)
    for name in ("DISPATCH_GUARD_TIER", "DISPATCH_GUARD_TEST_KEY", "DISPATCH_GUARD_KEY_FILE"):
        env.pop(name, None)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "lane_authorize.py"), "--interactive", "--scope", "workers"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert b"lane_authorize: operator-only, needs a real terminal" in proc.stderr
    assert not (tmp_path / "dispatch_override.json").exists()
    assert list(tmp_path.iterdir()) == []


def test_workers_override_subprocess_allows_opus(tmp_path: Path) -> None:
    env = _override_env(tmp_path)
    dispatch_guard_common.write_override("workers", 120, env)
    proc = _run_hook(
        "claude_worker_guard.py",
        json.dumps(_agent("opus", "Review the patch.")).encode(),
        tmp_path,
        extra={
            "DISPATCH_GUARD_ALLOW_PLAIN_KEY_FILE": "1",
            "DISPATCH_GUARD_KEY_FILE": env["DISPATCH_GUARD_KEY_FILE"],
        },
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.strip() == b""


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_round_trip() -> None:
    blob = dispatch_guard_common.dpapi_protect(b"secret-key-material")
    assert dispatch_guard_common.dpapi_unprotect(blob) == b"secret-key-material"


# --- tier marker -----------------------------------------------------------


def test_coordinator_prompt_marks_session_as_tier2(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dispatch-test@example.com")
    _git(repo, "config", "user.name", "Dispatch Test")
    _git(repo, "config", "core.autocrlf", "false")
    target = repo / "x.py"
    target.write_text("a\n", encoding="utf-8")
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-m", "init")

    env = _env(state)
    assert dispatch_tier_marker.decide({"session_id": "sess-mark", "prompt": _COORDINATOR}, env) is None
    assert dispatch_guard_common.is_tier2({"session_id": "sess-mark"}, env) is True
    assert dispatch_guard_common.is_tier2({"session_id": "other"}, env) is False
    later = _agent("sonnet", _COORDINATOR, session_id="sess-mark")
    assert "agent_id" not in later
    result = claude_worker_guard.decide(later, env)
    assert "max agent depth is 1" in _reason(result)
    edit = _hook(
        "Edit",
        {"file_path": str(target), "old_string": "a", "new_string": "b"},
        cwd=str(repo),
        session_id="sess-mark",
        tool_use_id="tu-coord",
    )
    assert dispatch_edit_guard.decide(edit, env) is None


def test_prompt_without_coordinator_line_does_not_mark(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert dispatch_tier_marker.decide({"session_id": "sess-plain", "prompt": "hello"}, env) is None
    assert dispatch_guard_common.is_tier2({"session_id": "sess-plain"}, env) is False


def test_tier_marker_subprocess_marks_session(tmp_path: Path) -> None:
    payload = {"session_id": "sess-e2e", "prompt": "  TIER-2   COORDINATOR for the lane handoff"}
    proc = _run_hook("dispatch_tier_marker.py", json.dumps(payload).encode(), tmp_path)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.strip() == b""
    stored = json.loads((tmp_path / "tier2_sessions.json").read_text(encoding="utf-8"))
    assert "sess-e2e" in stored
    assert dispatch_guard_common.is_tier2({"session_id": "sess-e2e"}, _env(tmp_path)) is True


# --- Review Round 1 Bypass Regressions & Invariants ------------------------


def test_cmd_c_codex_exec_is_denied(tmp_path: Path) -> None:
    result = dispatch_bash_guard.decide(_bash("cmd /c codex exec hello"), _env(tmp_path))
    assert "R2" in _reason(result)
    assert "codex" in _reason(result)


def test_bash_c_codex_exec_is_denied(tmp_path: Path) -> None:
    result = dispatch_bash_guard.decide(_bash('bash -c "codex exec hello"'), _env(tmp_path))
    assert "R2" in _reason(result)
    assert "codex" in _reason(result)


def test_python_c_writing_source_file_is_denied(tmp_path: Path) -> None:
    command = 'python -c "open(\'src/app.py\', \'w\').write(\'hello\')"'
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R3" in _reason(result)
    assert "source-file mutation" in _reason(result)


def test_python_x_utf8_cdp_script_is_denied(tmp_path: Path) -> None:
    command = "python -X utf8 scripts/cdp_chatgpt_code.py --brief b.md"
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R2" in _reason(result)
    assert "cdp_chatgpt_code.py" in _reason(result)


def test_invoke_expression_codex_exec_is_denied(tmp_path: Path) -> None:
    command = 'Invoke-Expression "codex exec hello"'
    result = dispatch_bash_guard.decide(_bash(command, "PowerShell"), _env(tmp_path))
    assert "R2" in _reason(result)
    assert "codex" in _reason(result)


def test_powershell_call_operator_codex_path_is_denied(tmp_path: Path) -> None:
    command = r"& C:\Tools\codex.exe exec hello"
    result = dispatch_bash_guard.decide(_bash(command, "PowerShell"), _env(tmp_path))
    assert "R2" in _reason(result)
    assert "codex.exe" in _reason(result)


def test_start_process_codex_is_denied(tmp_path: Path) -> None:
    command = 'Start-Process -WorkingDirectory C:/repo -FilePath codex.cmd -ArgumentList "exec hi"'
    result = dispatch_bash_guard.decide(_bash(command, "PowerShell"), _env(tmp_path))
    assert "R2" in _reason(result)
    assert "codex.cmd" in _reason(result)


def test_codex_exec_dash_dash_help_is_denied(tmp_path: Path) -> None:
    command = 'codex exec -- "--help"'
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R2" in _reason(result)
    assert "codex exec" in _reason(result)


def test_git_status_redirect_to_source_is_denied(tmp_path: Path) -> None:
    command = "git status > src/main.py"
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R3" in _reason(result)
    assert "main.py" in _reason(result)


def test_redirect_to_claude_settings_is_denied(tmp_path: Path) -> None:
    command = "echo hi > .claude/settings.json"
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R3" in _reason(result)
    assert "settings.json" in _reason(result)


def test_cp_to_source_dir_is_denied(tmp_path: Path) -> None:
    command = "cp /tmp/main.py src/"
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R3" in _reason(result)


def test_mv_source_file_is_denied(tmp_path: Path) -> None:
    command = "mv src/main.py notes.md"
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R3" in _reason(result)
    assert "main.py" in _reason(result)


def test_sed_inplace_wildcard_source_is_denied(tmp_path: Path) -> None:
    command = "sed -i s/foo/bar/ src/*"
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R3" in _reason(result)


def test_supervisor_grep_source_dir_and_bash_cat_source_are_denied(tmp_path: Path) -> None:
    state = tmp_path / "state"
    env = _env(state)
    # Supervisor Grep of directory
    grep_payload = _hook("Grep", {"path": "src", "pattern": "def"}, session_id="sup")
    grep_res = dispatch_read_guard.decide(grep_payload, env)
    assert grep_res is not None
    assert "source reads go to `lane diagnose`" in _reason(grep_res)

    # Supervisor Bash cat src/main.py
    cat_payload = _hook("Bash", {"command": "cat src/main.py"}, session_id="sup")
    cat_res = dispatch_bash_guard.decide(cat_payload, env)
    assert cat_res is not None
    assert "lane diagnose" in _reason(cat_res).lower()


def test_write_claude_settings_denied_for_supervisor_and_tier2(tmp_path: Path) -> None:
    state = tmp_path / "state"
    env = _env(state)
    sup_payload = _hook("Write", {"file_path": ".claude/settings.json", "content": "{}"}, session_id="sup")
    sup_res = dispatch_edit_guard.decide(sup_payload, env)
    assert "cannot edit protected path" in _reason(sup_res)

    t2_payload = _hook("Write", {"file_path": ".claude/settings.json", "content": "{}"}, agent_id="t2_worker")
    t2_res = dispatch_edit_guard.decide(t2_payload, env)
    assert "cannot edit protected path" in _reason(t2_res)


def test_python_c_override_minting_denied(tmp_path: Path) -> None:
    command = (
        'python -c "open(\'dispatch_override.json\', \'w\').write('
        'write_override(\'workers\', 100))"'
    )
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert "R3" in _reason(result)
    assert "guarded-path mutation" in _reason(result)


def test_tier2_edit_replace_all_charged_by_occurrences(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dispatch-test@example.com")
    _git(repo, "config", "user.name", "Dispatch Test")
    _git(repo, "config", "core.autocrlf", "false")
    target = repo / "module.py"
    # 100 lines, 25 occurrences of "TARGET_VAR = 1"
    lines = ["TARGET_VAR = 1" if i % 4 == 0 else f"other_{i} = {i}" for i in range(100)]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _git(repo, "add", "module.py")
    _git(repo, "commit", "-m", "init")

    env = _env(state)
    # replace_all=True: 25 occurrences * 1 line = 25 lines > 20 line cap -> DENIED
    payload_all = _hook(
        "Edit",
        {
            "file_path": str(target),
            "old_string": "TARGET_VAR = 1",
            "new_string": "TARGET_VAR = 2",
            "replace_all": True,
        },
        cwd=str(repo),
        agent_id="tier2_worker",
        tool_use_id="tu_replace_all",
    )
    res_all = dispatch_edit_guard.decide(payload_all, env)
    assert res_all is not None
    assert "Tier-2 edit cap" in _reason(res_all)

    # replace_all=False: 1 occurrence * 1 line = 1 line <= 20 line cap -> ALLOWED
    payload_one = _hook(
        "Edit",
        {
            "file_path": str(target),
            "old_string": "TARGET_VAR = 1",
            "new_string": "TARGET_VAR = 2",
            "replace_all": False,
        },
        cwd=str(repo),
        agent_id="tier2_worker",
        tool_use_id="tu_replace_one",
    )
    assert dispatch_edit_guard.decide(payload_one, env) is None


def test_untracked_or_unreadable_source_file_edit_denied_by_tier2(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dispatch-test@example.com")
    _git(repo, "config", "user.name", "Dispatch Test")
    _git(repo, "config", "core.autocrlf", "false")
    env = _env(state)

    # 1. Untracked source file
    untracked = repo / "untracked.py"
    untracked.write_text("a = 1\n", encoding="utf-8")
    payload_untracked = _hook(
        "Edit",
        {"file_path": str(untracked), "old_string": "a = 1", "new_string": "a = 2"},
        cwd=str(repo),
        agent_id="tier2_worker",
    )
    res_untracked = dispatch_edit_guard.decide(payload_untracked, env)
    assert "cannot edit untracked source file" in _reason(res_untracked)

    # 2. Unreadable / nonexistent source file
    missing = repo / "missing.py"
    payload_missing = _hook(
        "Edit",
        {"file_path": str(missing), "old_string": "a", "new_string": "b"},
        cwd=str(repo),
        agent_id="tier2_worker",
    )
    res_missing = dispatch_edit_guard.decide(payload_missing, env)
    assert "untracked source file" in _reason(res_missing) or "source file not found" in _reason(res_missing)


def test_atomic_reserve_bytes_concurrent_processes(tmp_path: Path) -> None:
    state = tmp_path / "state"
    worker_script = tmp_path / "reserve_worker.py"
    worker_script.write_text(
        "import os, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import dispatch_guard_common\n"
        "ok = dispatch_guard_common.reserve_bytes('c_test', 'key', 10, 15)\n"
        "print('SUCCESS' if ok else 'EXCEEDED')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["DISPATCH_GUARD_STATE_DIR"] = str(state)
    p1 = subprocess.Popen(
        [sys.executable, str(worker_script), str(_SCRIPTS)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    p2 = subprocess.Popen(
        [sys.executable, str(worker_script), str(_SCRIPTS)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out1, err1 = p1.communicate(timeout=10)
    out2, err2 = p2.communicate(timeout=10)
    assert p1.returncode == 0, err1.decode("utf-8", "replace")
    assert p2.returncode == 0, err2.decode("utf-8", "replace")
    results = sorted([out1.decode("utf-8").strip(), out2.decode("utf-8").strip()])
    assert results == ["EXCEEDED", "SUCCESS"]
    assert dispatch_guard_common.get_counter("c_test", "key", _env(state)) == 10


def test_user_prompt_submit_crash_emits_decision_block(capsys: pytest.CaptureFixture[str]) -> None:
    def boom() -> None:
        raise RuntimeError("prompt crash")

    assert dispatch_guard_common.run_guarded("dispatch_tier_marker.py", boom, "UserPromptSubmit") == 0
    body = json.loads(capsys.readouterr().out)
    assert body["decision"] == "block"
    assert "dispatch_tier_marker.py crashed: RuntimeError: prompt crash" in body["reason"]


def test_corrupt_tier2_sessions_json_treats_caller_as_tier2(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "tier2_sessions.json").write_text("{corrupt: json", encoding="utf-8")
    # Corrupt registry state must fail closed without granting Tier-2 powers.
    assert dispatch_guard_common.is_tier2({"session_id": "sess-unknown"}, env) is False


def test_tier_marker_failure_writes_tier2_pending_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    env = _env(state)

    def fail_mark(session_id: str, e: object = None) -> None:
        raise OSError("disk locked")

    monkeypatch.setattr(dispatch_tier_marker, "mark_tier2_session", fail_mark)
    payload = {"session_id": "sess-pending-test", "prompt": _COORDINATOR}
    assert dispatch_tier_marker.decide(payload, env) is None
    pending_file = state / "tier2_pending" / "sess-pending-test"
    assert pending_file.is_file()
    assert dispatch_guard_common.is_tier2({"session_id": "sess-pending-test"}, env) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "git status",
        "rg codex .",
        "pytest -q",
        "python -m pytest -q",
        "echo x > notes.md",
        "Set-Content notes.md main.py",
    ],
)
def test_legitimate_commands_are_allowed(tmp_path: Path, cmd: str) -> None:
    state = tmp_path / "state"
    work = tmp_path / "work"
    work.mkdir()
    tool_name = "PowerShell" if "Set-Content" in cmd else "Bash"
    # rg codex . is allowed for Tier-2 coordinators (and in scratchpad for supervisor)
    agent_id = "tier2_worker" if "rg " in cmd else None
    payload = _hook(tool_name, {"command": cmd}, cwd=str(work), agent_id=agent_id)
    assert dispatch_bash_guard.decide(payload, _env(state)) is None


# --- Review Round 2 bypass regressions ------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "python -c \"import dispatch_guard_common; dispatch_guard_common.write_override('workers', 60)\"",
        'RESULT=$(codex exec hi)',
        'X=`codex exec hi`',
        '(codex exec hi)',
        'printf x; bash run.sh',
        'echo codex exec hi | bash',
        'pwsh -File r.ps1',
        'f(){ codex exec hi; }; f',
    ],
)
def test_round2_shell_bypasses_are_denied(tmp_path: Path, command: str) -> None:
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert result is not None


def test_powershell_group_codex_is_denied(tmp_path: Path) -> None:
    result = dispatch_bash_guard.decide(
        _bash("& { codex exec hi }", "PowerShell"), _env(tmp_path)
    )
    assert "R2" in _reason(result)


@pytest.mark.parametrize(
    "command",
    [
        'git config alias.ck "!codex exec hi"',
        "git checkout -- src/main.py",
        "git show HEAD:src/app.py",
        "git grep codex -- src/main.py",
    ],
)
def test_round2_git_execution_or_source_access_is_denied(
    tmp_path: Path, command: str,
) -> None:
    result = dispatch_bash_guard.decide(_bash(command), _env(tmp_path))
    assert result is not None


def test_source_script_mutation_and_scratch_escape_are_denied(tmp_path: Path) -> None:
    result = dispatch_bash_guard.decide(_bash("echo x > tmp/app.py"), _env(tmp_path))
    assert "R3" in _reason(result)


def test_round2_read_allowlist_is_anchored(tmp_path: Path) -> None:
    state = tmp_path / "state"
    env = _env(state)
    source = "D:/APPS/Tsignal/src/state/engine.py"
    result = dispatch_read_guard.decide(
        _hook("Read", {"file_path": source}, session_id="supervisor"), env
    )
    assert "source reads go to `lane diagnose`" in _reason(result)

    allowed = dispatch_read_guard.decide(
        _hook("Read", {"file_path": "D:/state-dir/readme.md"}, session_id="supervisor"), env
    )
    assert allowed is None


def test_corrupt_tier_registry_does_not_grant_tier2(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "tier2_sessions.json").write_text("{corrupt", encoding="utf-8")
    env = _env(state)
    supervisor = {"session_id": "sess-corrupt"}
    assert dispatch_guard_common.is_tier2(supervisor, env) is False

    read = dispatch_read_guard.decide(
        _hook("Read", {"file_path": "src/main.py"}, session_id="sess-corrupt"), env
    )
    assert "tier registry corrupt" in _reason(read)
    edit = dispatch_edit_guard.decide(
        _hook("Edit", {"file_path": "src/main.py", "old_string": "a", "new_string": "b"},
              session_id="sess-corrupt"), env
    )
    assert "tier registry corrupt" in _reason(edit)
    spawn = claude_worker_guard.decide(_agent("sonnet", _COORDINATOR, session_id="sess-corrupt"), env)
    assert "tier registry corrupt" in _reason(spawn)


@pytest.mark.parametrize(
    "command",
    ["git status", "git diff", "git commit -m ok", "rg codex .", "pytest -q", "echo x > notes.md"],
)
def test_round2_legitimate_commands_remain_allowed(tmp_path: Path, command: str) -> None:
    work = tmp_path / "work"
    work.mkdir()
    payload = _hook("Bash", {"command": command}, cwd=str(work))
    assert dispatch_bash_guard.decide(payload, _env(tmp_path / "state")) is None
