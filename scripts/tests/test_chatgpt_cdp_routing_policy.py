from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODEL_TEAM_PATH = ROOT / "skills" / "run-model-team" / "scripts" / "model_team.py"


def _model_team():
    spec = importlib.util.spec_from_file_location("model_team_routing_policy", MODEL_TEAM_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_team_has_no_codex_cli_coding_role() -> None:
    module = _model_team()

    assert "chatgpt" in module.DIRECT_WRITE_ROLES
    assert "luna" not in module.DISPATCH_ROLES
    assert not hasattr(module, "_codex_command")


def test_chatgpt_role_builds_only_the_cdp_driver_command(tmp_path: Path) -> None:
    module = _model_team()
    prompt = tmp_path / "packet.md"
    prompt.write_text("bounded", encoding="utf-8")
    args = type(
        "Args",
        (),
        {
            "target_file": "module.py",
            "prompt_file": prompt,
            "include_current": [],
            "provider_model": "gpt-5.6-sol",
        },
    )()

    command = module._chatgpt_command(args, tmp_path, tmp_path / "result.json")

    assert str(module.CHATGPT_CDP_DRIVER) in command
    assert all("codex" not in str(part).lower() for part in command)


def test_policy_text_requires_chatgpt_cdp_and_names_only_runtime_exception() -> None:
    core = (ROOT / "agent-rules" / "core.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "run-model-team" / "SKILL.md").read_text(encoding="utf-8")

    assert "GPT coding, plan-audit, and implementation-review work uses signed-in" in core
    assert "purpose=latency_critical_runtime" in core
    assert "no Codex CLI fallback" in skill
    assert "--role luna" not in skill
