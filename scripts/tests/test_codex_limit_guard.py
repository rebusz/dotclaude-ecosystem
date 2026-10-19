"""Tests for scripts/codex_limit_guard.py (unit + real-subprocess CLI). Silent, no network."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "codex_limit_guard.py"
_spec = importlib.util.spec_from_file_location("codex_limit_guard", SCRIPT)
guard = importlib.util.module_from_spec(_spec)
sys.modules["codex_limit_guard"] = guard
_spec.loader.exec_module(guard)

NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in guard.ALLOW_ENVS:
        monkeypatch.delenv(name, raising=False)
    guard.reset_cache_for_tests()
    yield
    guard.reset_cache_for_tests()


def _rollout(sessions: Path, name: str, *events: dict, mtime: float | None = None) -> Path:
    day = sessions / "2026" / "10" / "19"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-{name}.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _limits(used: float, resets_at: float = NOW + 86400, balance: str = "57295.95") -> dict:
    return {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "limit_id": "codex",
                "primary": {"used_percent": used, "window_minutes": 10080, "resets_at": resets_at},
                "credits": {"has_credits": True, "balance": balance},
            },
        },
    }


def test_exhausted_weekly_limit_is_refused_with_the_named_reason(tmp_path: Path) -> None:
    _rollout(tmp_path, "a", {"type": "x"}, _limits(100.0))
    refusal = guard.codex_limit_refusal(now=NOW, sessions=tmp_path)
    assert refusal is not None and refusal.startswith("codex_weekly_limit_exhausted_credits_would_be_spent")
    assert "used_percent=100" in refusal and "credit_balance=57295.95" in refusal


def test_below_the_limit_is_allowed(tmp_path: Path) -> None:
    _rollout(tmp_path, "a", _limits(63.2))
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None


def test_a_rolled_over_window_is_allowed(tmp_path: Path) -> None:
    _rollout(tmp_path, "a", _limits(100.0, resets_at=NOW - 10))
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None


@pytest.mark.parametrize("env", ["DOTCLAUDE_ALLOW_CODEX_CREDITS", "WATCHF_ALLOW_CODEX_CREDITS"])
def test_explicit_operator_opt_in_allows_spending_credits(tmp_path: Path, monkeypatch, env: str) -> None:
    _rollout(tmp_path, "a", _limits(100.0))
    monkeypatch.setenv(env, "1")
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None


def test_newest_rollout_wins_and_the_last_event_in_it_wins(tmp_path: Path) -> None:
    _rollout(tmp_path, "old", _limits(100.0), mtime=NOW - 5000)
    _rollout(tmp_path, "new", _limits(100.0), _limits(40.0), mtime=NOW - 10)
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None


def test_unknown_state_is_allowed_not_refused(tmp_path: Path) -> None:
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None
    _rollout(tmp_path, "a", {"type": "no limits here"})
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None
    (tmp_path / "2026" / "10" / "19" / "rollout-b.jsonl").write_text("not json {", encoding="utf-8")
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None


def test_a_cut_first_tail_line_does_not_hide_the_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guard, "_TAIL_BYTES", 600)
    _rollout(tmp_path, "a", {"padding": "x" * 3000}, _limits(100.0))
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is not None


def test_secondary_window_exhaustion_and_a_reached_flag_also_refuse(tmp_path: Path) -> None:
    secondary = _limits(10.0)
    secondary["payload"]["rate_limits"]["secondary"] = {"used_percent": 100.0, "resets_at": NOW + 3600}
    _rollout(tmp_path, "a", secondary)
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is not None
    reached = _limits(99.0)
    reached["payload"]["rate_limits"]["rate_limit_reached_type"] = "primary"
    (tmp_path / "2026" / "10" / "19" / "rollout-a.jsonl").unlink()
    _rollout(tmp_path, "b", reached)
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is not None


def test_only_the_newest_day_directories_are_listed(tmp_path: Path) -> None:
    old = tmp_path / "2025" / "01" / "01"
    old.mkdir(parents=True)
    (old / "rollout-old.jsonl").write_text(json.dumps(_limits(100.0)) + "\n", encoding="utf-8")
    _rollout(tmp_path, "new", _limits(5.0))
    assert [p.name for p in guard._newest_rollouts(tmp_path, limit=1)] == ["rollout-new.jsonl"]
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None


# ---- real-subprocess CLI tests ----

def _run(args: list[str], codex_home: Path, extra_env: dict | None = None):
    env = {k: v for k, v in os.environ.items() if k not in guard.ALLOW_ENVS}
    env["CODEX_HOME"] = str(codex_home)
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60)


def _future_limits(used: float) -> dict:
    return _limits(used, resets_at=time.time() + 3600)


def _marker_cmd(marker: Path, code: int = 0) -> list[str]:
    body = f"import pathlib,sys; pathlib.Path({str(marker)!r}).write_text('ran'); sys.exit({code})"
    return ["--", sys.executable, "-c", body]


def test_cli_check_refused_at_100(tmp_path: Path) -> None:
    _rollout(tmp_path / "sessions", "a", _future_limits(100.0))
    res = _run(["--check"], tmp_path)
    assert res.returncode == 75
    out = json.loads(res.stdout.strip())
    assert out["allowed"] is False and out["reason"].startswith(guard.REFUSAL)


def test_cli_check_allowed_at_40(tmp_path: Path) -> None:
    _rollout(tmp_path / "sessions", "a", _future_limits(40.0))
    res = _run(["--check"], tmp_path)
    assert res.returncode == 0
    assert json.loads(res.stdout.strip()) == {"allowed": True, "reason": None}


def test_cli_exec_refused_does_not_run_command(tmp_path: Path) -> None:
    _rollout(tmp_path / "sessions", "a", _future_limits(100.0))
    marker = tmp_path / "marker.txt"
    res = _run(_marker_cmd(marker), tmp_path)
    assert res.returncode == 75
    assert guard.REFUSAL in res.stderr
    assert not marker.exists()


def test_cli_exec_allowed_runs_and_propagates_exit_code(tmp_path: Path) -> None:
    _rollout(tmp_path / "sessions", "a", _future_limits(40.0))
    marker = tmp_path / "marker.txt"
    res = _run(_marker_cmd(marker, code=7), tmp_path)
    assert res.returncode == 7
    assert marker.read_text() == "ran"


@pytest.mark.parametrize("env", ["DOTCLAUDE_ALLOW_CODEX_CREDITS", "WATCHF_ALLOW_CODEX_CREDITS"])
def test_cli_env_opt_in_allows(tmp_path: Path, env: str) -> None:
    _rollout(tmp_path / "sessions", "a", _future_limits(100.0))
    marker = tmp_path / "marker.txt"
    res = _run(_marker_cmd(marker), tmp_path, {env: "1"})
    assert res.returncode == 0
    assert marker.read_text() == "ran"


def test_cli_unknown_state_allows(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    res = _run(_marker_cmd(marker), tmp_path)
    assert res.returncode == 0 and marker.exists()
    assert _run(["--check"], tmp_path).returncode == 0


def test_a_stale_reached_flag_after_the_window_rolled_over_does_not_refuse_forever(tmp_path: Path) -> None:
    """A refused run never writes a fresher rollout, so an old 'reached' flag
    from an expired window must not keep refusing (self-deadlock)."""
    stale = _limits(100.0, resets_at=NOW - 10)
    stale["payload"]["rate_limits"]["rate_limit_reached_type"] = "weekly"
    _rollout(tmp_path, "a", stale)
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None


def test_a_boolean_resets_at_is_not_treated_as_an_expired_window(tmp_path: Path) -> None:
    event = _limits(100.0, resets_at=False)  # type: ignore[arg-type]
    _rollout(tmp_path, "a", event)
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is not None


def test_reached_flag_from_a_live_secondary_refuses_even_when_primary_rolled_over(tmp_path: Path) -> None:
    event = _limits(10.0, resets_at=NOW - 10)
    event["payload"]["rate_limits"]["secondary"] = {"used_percent": 60.0, "resets_at": NOW + 3600}
    event["payload"]["rate_limits"]["rate_limit_reached_type"] = "secondary"
    _rollout(tmp_path, "a", event)
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is not None


def test_reached_flag_from_a_rolled_over_secondary_does_not_refuse_a_healthy_primary(tmp_path: Path) -> None:
    event = _limits(10.0, resets_at=NOW - 10)
    event["payload"]["rate_limits"]["secondary"] = {"used_percent": 100.0, "resets_at": NOW - 5}
    event["payload"]["rate_limits"]["rate_limit_reached_type"] = "secondary"
    _rollout(tmp_path, "a", event)
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None


def test_malformed_non_dict_windows_never_crash_the_guard(tmp_path: Path) -> None:
    event = _limits(10.0)
    event["payload"]["rate_limits"]["primary"] = "garbage"
    event["payload"]["rate_limits"]["rate_limit_reached_type"] = "primary"
    _rollout(tmp_path, "a", event)
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is None


def test_an_out_of_range_resets_at_still_yields_a_refusal_not_a_crash(tmp_path: Path) -> None:
    _rollout(tmp_path, "a", _limits(100.0, resets_at=1e20))
    assert guard.codex_limit_refusal(now=NOW, sessions=tmp_path) is not None
