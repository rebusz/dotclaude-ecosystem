"""Real installer/SessionStart round trip; policy assertions are not LLM compliance proof."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run(args, *, env=None, cwd=None, stdin=None, expected_exit=0):
    with subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8") as process:
        try:
            stdout, stderr = process.communicate(stdin, timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        assert process.returncode == expected_exit, (process.returncode, stdout, stderr)
        return stdout


@pytest.mark.parametrize("case,clauses", [
    ("terminal_workers", ["MUST complete the authorized scope itself", "without another takeover GO", "Do not exhaust every model/account/timeout"]),
    ("healthy_worker", ["With a healthy qualified worker, delegate"]),
    ("uncertain_submit", ["SUBMIT_UNCONFIRMED", "no takeover, retry, replacement or duplicate completion"]),
    ("foreign_owner", ["live foreign owner/write-set", "Continue authorized disjoint work"]),
    ("tool_denial", ["no tool-refusal bypass", "report the concrete blocking condition"]),
    ("protected_triggers", ["real-money/Combine trigger", "RTH restart", "other applications' orders", "permissions/sandbox change", "independent review"]),
])
def test_injected_policy_boundaries(tmp_path, case, clauses):
    env = dict(os.environ, SUPERVISOR_CONTRACT_PATH=str(ROOT / "templates/supervisor-contract.md"),
               SESSION_ROUTER_NO_PROBE="1", CLAUDE_SESSION_STATE_DIR=str(tmp_path / "state"))
    output = run([sys.executable, str(ROOT / "scripts/session_router.py")], env=env,
                 stdin=json.dumps({"hook_event_name": "SessionStart", "source": "startup",
                                   "session_id": case, "cwd": str(tmp_path)}))
    context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
    for clause in clauses:
        assert clause in context


def test_scoped_install_loader_native_edit_and_test(tmp_path):
    """No provider invocation, permission edit or claim of synthetic model reasoning."""
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("Windows installer requires PowerShell 7")
    home = tmp_path / "home"
    refs = home / ".claude/refs"
    refs.mkdir(parents=True)
    settings = refs.parent / "settings.json"
    settings.write_text('{"permissions":{"sentinel":"unchanged"}}', encoding="utf-8")
    old = refs / "supervisor-contract.md"
    old.write_text("old contract", encoding="utf-8")
    env = dict(os.environ, USERPROFILE=str(home))
    command = [pwsh, "-NoProfile", "-File", str(ROOT / "install/install.ps1"), "-SupervisorContractOnly"]
    run(command, env=env)
    run(command + ["-Check"], env=env)
    assert settings.read_text(encoding="utf-8") == '{"permissions":{"sentinel":"unchanged"}}'
    assert list((home / ".claude/refs.bak").glob("*/supervisor-contract.md"))[0].read_text() == "old contract"
    assert old.read_bytes() == (ROOT / "templates/supervisor-contract.md").read_bytes()
    env.update(SUPERVISOR_CONTRACT_PATH=str(old), SESSION_ROUTER_NO_PROBE="1",
               CLAUDE_SESSION_STATE_DIR=str(tmp_path / "state"))
    output = run([sys.executable, str(ROOT / "scripts/session_router.py")], env=env,
                 stdin=json.dumps({"hook_event_name": "SessionStart", "source": "startup",
                                   "session_id": "native-fixture", "cwd": str(tmp_path)}))
    context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
    assert context.startswith(old.read_text(encoding="utf-8"))
    # Synthetic terminal receipt remains on disk through native completion.
    receipt = tmp_path / "terminal-worker.json"
    receipt.write_text(json.dumps({"attempt_id": "synthetic-1", "status": "FAILED",
                                  "source": "fixture", "actual_model": None,
                                  "reason": "pre-submit unavailable; no provider called"}))
    before = receipt.read_bytes()
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    source = fixture / "answer.py"
    source.write_text("def answer():\n    return 0\n", encoding="utf-8")
    (fixture / "test_answer.py").write_text(
        "import unittest\nfrom answer import answer\nclass AnswerTest(unittest.TestCase):\n"
        "    def test_answer(self):\n        self.assertEqual(answer(), 42)\n", encoding="utf-8")
    run([sys.executable, "-m", "unittest", "discover"], cwd=fixture, expected_exit=1)
    # Execute a real native edit larger than the obsolete 20-line cap, then a real test.
    run([sys.executable, "-c", "from pathlib import Path; Path('answer.py').write_text(''.join('# owned fixture line\\n' for _ in range(21)) + 'def answer():\\n    return 42\\n')"], cwd=fixture)
    run([sys.executable, "-m", "unittest", "discover"], cwd=fixture)
    assert "return 42" in source.read_text()
    assert receipt.read_bytes() == before
