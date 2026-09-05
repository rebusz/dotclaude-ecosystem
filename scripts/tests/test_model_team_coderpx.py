from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "run-model-team"
    / "scripts"
    / "model_team.py"
)
SPEC = importlib.util.spec_from_file_location("model_team_coderpx", MODULE_PATH)
assert SPEC and SPEC.loader
model_team = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model_team)


def _packet(path: Path) -> Path:
    path.write_text(
        "=== CODERPX PACKET ===\n"
        "Schema: coderpx.packet.v2\n"
        "complete packet\n"
        "=== END PACKET ===\n",
        encoding="utf-8",
    )
    return path


def _args(tmp_path: Path, *, dry_run: bool = False, task_kind: str = "code"):
    argv = [
        "run",
        "--role",
        "perplexity",
        "--repo",
        str(tmp_path / "worktree"),
        "--prompt-file",
        str(_packet(tmp_path / "packet.md")),
        "--out",
        str(tmp_path / "result.md"),
        "--provider-model",
        "Sonar 2",
        "--task-kind",
        task_kind,
    ]
    if dry_run:
        argv.append("--dry-run")
    return model_team.build_parser().parse_args(argv)


def _patch_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    repo = tmp_path / "worktree"
    repo.mkdir()
    monkeypatch.setattr(model_team, "_repo_root", lambda path: repo.resolve())
    monkeypatch.setattr(
        model_team,
        "_primary_worktree",
        lambda path: (tmp_path / "primary").resolve(),
    )
    python_path = tmp_path / "python.exe"
    driver_path = tmp_path / "coderpx.py"
    python_path.write_text("", encoding="utf-8")
    driver_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(model_team, "WATCHF_PYTHON", python_path)
    monkeypatch.setattr(model_team, "PERPLEXITY_DRIVER", driver_path)
    return repo.resolve()


def _success_manifest(args) -> dict[str, object]:
    return {
        "schema": "coderpx.result.v1",
        "status": "SUCCESS",
        "exit_code": 0,
        "packet_sha256": hashlib.sha256(args.prompt_file.read_bytes()).hexdigest(),
        "response_sha256": hashlib.sha256(args.out.read_bytes()).hexdigest(),
        "response_path": str(args.out.resolve()),
        "requested_model_fragment": "Sonar 2",
        "requested_model_label": "Sonar 2",
        "verified_model": "Sonar 2",
    }


def test_perplexity_command_routes_to_coderpx_and_sibling_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_repo(monkeypatch, tmp_path)
    args = _args(tmp_path)
    command, metadata = model_team._perplexity_command(args, args.out.resolve())

    assert command[1].endswith("coderpx.py")
    assert command[command.index("--model") + 1] == "Sonar 2"
    assert command[command.index("--output") + 1].endswith("result.md")
    assert "--only" not in command
    assert metadata.name == "result.md.meta.json"


def test_perplexity_probe_routes_through_coderpx_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_repo(monkeypatch, tmp_path)
    monkeypatch.setattr(model_team, "PERPLEXITY_PROBE_DRIVER", model_team.PERPLEXITY_DRIVER)
    captured: list[list[str]] = []

    def capture(command, **kwargs):
        captured.append(command)
        return subprocess.CompletedProcess(command, 0, '{"count": 1}', "")

    monkeypatch.setattr(model_team, "_capture", capture)
    result = model_team._perplexity_probe(deep=True)

    assert result["status"] == "READY_CDP"
    assert captured[0][1].endswith("coderpx.py")
    assert captured[0][2:] == ["--probe-models"]


def test_perplexity_rejects_non_coderpx_packet() -> None:
    with pytest.raises(model_team.DispatchError, match="coderpx.packet.v2"):
        model_team._require_coderpx_packet("ordinary audit prompt")


def test_implementation_dry_run_requires_isolated_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "worktree"
    repo.mkdir()
    args = _args(tmp_path, dry_run=True)
    monkeypatch.setattr(model_team, "_repo_root", lambda path: repo.resolve())
    monkeypatch.setattr(model_team, "_primary_worktree", lambda path: repo.resolve())

    with pytest.raises(model_team.DispatchError, match="isolated"):
        model_team.run_role(args)


def test_nonzero_coderpx_is_no_result_with_artifact_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_repo(monkeypatch, tmp_path)
    args = _args(tmp_path)
    monkeypatch.setattr(
        model_team,
        "_capture",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 8, "", "quota"),
    )

    rc = model_team.run_role(args)

    assert rc == 8
    stderr = capsys.readouterr().err
    assert '"status": "NO_RESULT"' in stderr
    assert "result.md.meta.json" in stderr


def test_success_requires_manifest_and_ledgers_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_repo(monkeypatch, tmp_path)
    args = _args(tmp_path)

    def capture(command, **kwargs):
        assert kwargs["timeout_s"] == args.timeout_s + 120
        args.out.write_text("answer\n", encoding="utf-8")
        args.out.with_suffix(".md.meta.json").write_text(
            json.dumps(_success_manifest(args)),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "runner-json", "")

    monkeypatch.setattr(model_team, "_capture", capture)
    assert model_team.run_role(args) == 0
    ledger = json.loads(capsys.readouterr().out)
    assert ledger["status"] == "RESULT"
    assert ledger["metadata_path"].endswith("result.md.meta.json")


def test_tampered_response_fails_manifest_read_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_repo(monkeypatch, tmp_path)
    args = _args(tmp_path)

    def capture(command, **kwargs):
        args.out.write_text("answer\n", encoding="utf-8")
        manifest = _success_manifest(args)
        manifest["response_sha256"] = "0" * 64
        args.out.with_suffix(".md.meta.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(model_team, "_capture", capture)
    with pytest.raises(model_team.DispatchError, match="manifest contract"):
        model_team.run_role(args)


def test_outer_timeout_is_ledgered_as_no_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_repo(monkeypatch, tmp_path)
    args = _args(tmp_path)
    monkeypatch.setattr(
        model_team,
        "_capture",
        lambda *a, **k: (_ for _ in ()).throw(model_team.DispatchError("timeout")),
    )

    with pytest.raises(model_team.DispatchError, match="timeout"):
        model_team.run_role(args)

    assert '"status": "NO_RESULT"' in capsys.readouterr().err


def test_success_exit_without_manifest_is_no_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_repo(monkeypatch, tmp_path)
    args = _args(tmp_path)
    monkeypatch.setattr(
        model_team,
        "_capture",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    with pytest.raises(model_team.DispatchError, match="without response and metadata"):
        model_team.run_role(args)


def test_doctor_probes_supervisor_and_luna(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        model_team,
        "_version_probe",
        lambda name: {"status": "READY", "executable": f"/mock/{name}", "detail": "v1.0"},
    )
    monkeypatch.setattr(
        model_team,
        "_chatgpt_probe",
        lambda **kwargs: {"status": "READY_CDP"},
    )
    monkeypatch.setattr(
        model_team,
        "_ox_probe",
        lambda **kwargs: {"status": "READY"},
    )
    monkeypatch.setattr(
        model_team,
        "_antigravity_probe",
        lambda **kwargs: {"status": "READY"},
    )
    monkeypatch.setattr(
        model_team,
        "_qwen_probe",
        lambda **kwargs: {"status": "READY"},
    )
    monkeypatch.setattr(
        model_team,
        "_perplexity_probe",
        lambda **kwargs: {"status": "READY_CDP"},
    )
    monkeypatch.setattr(
        model_team,
        "_fable_probe",
        lambda **kwargs: {"status": "JIT_CRITICAL_ONLY"},
    )
    rc = model_team.doctor()
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall"] == "READY"
    assert "supervisor" in payload["lanes"]
    assert payload["lanes"]["supervisor"]["status"] == "READY"
    assert payload["lanes"]["supervisor"]["model"] == "gpt-6-astra"
    assert "luna" in payload["lanes"]
    assert payload["lanes"]["luna"]["model"] == "gpt-5.6-luna"

