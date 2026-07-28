#!/usr/bin/env python3
"""Tests for atomic user-level Codex lifecycle activation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
_ROOT = _SCRIPTS.parent
sys.path.insert(0, str(_SCRIPTS))

import install_codex_session_lifecycle as installer  # noqa: E402


def _git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(path), "init", "-b", "main"],
        capture_output=True,
        text=True,
        check=True,
    )


def _registry_template(path: Path, repo: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "session.registry.v1",
                "repositories": [
                    {
                        "name": "repo",
                        "root": str(repo),
                        "plan_paths": ["design/plans"],
                        "vision_paths": [],
                        "idea_paths": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class TestCodexLifecycleInstaller(unittest.TestCase):
    def test_registry_validation_rejects_missing_paths_and_duplicate_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            validation_path = root / "registry.json"
            base_entry = {
                "name": "repo",
                "root": str(repo),
                "plan_paths": ["design/missing"],
                "vision_paths": [],
                "idea_paths": [],
            }
            payload = {
                "schema_version": "session.registry.v1",
                "repositories": [base_entry],
            }
            validation_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "path does not exist"):
                installer._validate_registry(
                    validation_path,
                    payload,
                    state_dir=root / "state",
                )

            duplicate = {
                **base_entry,
                "name": "duplicate",
                "plan_paths": ["design/plans"],
            }
            payload["repositories"] = [
                {**base_entry, "plan_paths": ["design/plans"]},
                duplicate,
            ]
            validation_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate registry root"):
                installer._validate_registry(
                    validation_path,
                    payload,
                    state_dir=root / "state",
                )

    def test_registry_merge_refuses_malformed_existing_entry(self):
        template = {
            "schema_version": "session.registry.v1",
            "repositories": [],
        }
        existing = {
            "schema_version": "session.registry.v1",
            "repositories": ["operator-entry"],
        }

        with self.assertRaisesRegex(ValueError, "invalid entry"):
            installer._merge_registry(existing, template)

    def test_install_refuses_concurrent_hook_change_before_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            registry_path = root / "home" / ".claude" / "session_registry.json"
            hooks_path.parent.mkdir(parents=True)
            hooks_path.write_text('{"hooks":{}}', encoding="utf-8")
            operator_change = b'{"description":"concurrent operator change","hooks":{}}\n'
            real_validate = installer._validate_registry

            def change_after_read(*args: object, **kwargs: object) -> None:
                real_validate(*args, **kwargs)
                hooks_path.write_bytes(operator_change)

            with (
                mock.patch.object(
                    installer,
                    "_validate_registry",
                    side_effect=change_after_read,
                ),
                self.assertRaisesRegex(RuntimeError, "target changed.*hooks"),
            ):
                installer.install(
                    hooks_path=hooks_path,
                    registry_path=registry_path,
                    hooks_template_path=(
                        _ROOT / "templates" / "codex_hooks.json.template"
                    ),
                    registry_template_path=registry_template,
                    adapter_path=_SCRIPTS / "codex_session_adapter.py",
                    python_executable=Path(sys.executable),
                    backup_root=root / "backups",
                    codex_version="codex-cli 0.145.0",
                )

            self.assertEqual(hooks_path.read_bytes(), operator_change)
            self.assertFalse(registry_path.exists())

    def test_rollback_rejects_manifest_target_outside_configured_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            registry_path = root / "home" / ".claude" / "session_registry.json"
            backup_root = root / "backups"
            result = installer.install(
                hooks_path=hooks_path,
                registry_path=registry_path,
                hooks_template_path=_ROOT / "templates" / "codex_hooks.json.template",
                registry_template_path=registry_template,
                adapter_path=_SCRIPTS / "codex_session_adapter.py",
                python_executable=Path(sys.executable),
                backup_root=backup_root,
                codex_version="codex-cli 0.145.0",
            )
            self.assertIsNotNone(result.manifest_path)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            manifest["targets"]["hooks"]["path"] = str(root / "victim.txt")
            result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "does not match configured path: hooks",
            ):
                installer.rollback(
                    result.manifest_path,
                    allowed_backup_root=backup_root,
                    expected_targets={
                        "hooks": hooks_path,
                        "registry": registry_path,
                    },
                )

    def test_codex_hook_preflight_requires_stable_feature(self):
        installer._require_stable_hooks("hooks  stable  true\n")

        with self.assertRaisesRegex(RuntimeError, "stable hooks"):
            installer._require_stable_hooks("hooks  under development  false\n")

    def test_windows_codex_preflight_uses_cmd_launcher(self):
        with mock.patch.object(
            installer.shutil,
            "which",
            return_value="C:/npm/codex.cmd",
        ) as which_mock:
            executable = installer._codex_executable(platform_name="nt")

        self.assertEqual(executable, "C:/npm/codex.cmd")
        which_mock.assert_called_once_with("codex.cmd")

    def test_windows_hook_command_quotes_shell_metacharacter_paths(self):
        command = installer._windows_command(
            Path("C:/runtime&tools/python.exe"),
            Path("D:/repo's&whoami/scripts/codex_session_adapter.py"),
        )

        self.assertEqual(
            command,
            (
                "& 'C:\\runtime&tools\\python.exe' "
                "'D:\\repo''s&whoami\\scripts\\codex_session_adapter.py'"
            ),
        )

    def test_owned_handler_recognizes_powershell_single_quoted_adapter(self):
        handler = {
            "type": "command",
            "commandWindows": (
                "& 'C:\\old\\python.exe' "
                "'C:\\old\\codex_session_adapter.py'"
            ),
        }

        self.assertTrue(
            installer._handler_is_owned(
                handler,
                command="different command",
                adapter_filename="codex_session_adapter.py",
            )
        )

    @unittest.skipUnless(sys.platform == "win32", "requires Windows PowerShell")
    def test_windows_hook_command_executes_in_powershell(self):
        command = installer._windows_command(
            Path(sys.executable),
            _SCRIPTS / "codex_session_adapter.py",
        )
        payload = {
            "hook_event_name": "SessionStart",
            "session_id": "powershell-smoke",
            "transcript_path": None,
            "cwd": str(_ROOT),
        }

        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "{}")

    def test_rollback_refuses_to_overwrite_post_install_operator_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            registry_path = root / "home" / ".claude" / "session_registry.json"

            result = installer.install(
                hooks_path=hooks_path,
                registry_path=registry_path,
                hooks_template_path=_ROOT / "templates" / "codex_hooks.json.template",
                registry_template_path=registry_template,
                adapter_path=_SCRIPTS / "codex_session_adapter.py",
                python_executable=Path(sys.executable),
                backup_root=root / "backups",
                codex_version="codex-cli 0.145.0",
            )
            operator_change = b'{"description":"operator changed this"}\n'
            hooks_path.write_bytes(operator_change)

            with self.assertRaisesRegex(
                ValueError,
                "installed target changed since activation: hooks",
            ):
                installer.rollback(result.manifest_path)

            self.assertEqual(hooks_path.read_bytes(), operator_change)
            self.assertTrue(registry_path.is_file())

    def test_fresh_install_rollback_removes_new_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            registry_path = root / "home" / ".claude" / "session_registry.json"

            result = installer.install(
                hooks_path=hooks_path,
                registry_path=registry_path,
                hooks_template_path=_ROOT / "templates" / "codex_hooks.json.template",
                registry_template_path=registry_template,
                adapter_path=_SCRIPTS / "codex_session_adapter.py",
                python_executable=Path(sys.executable),
                backup_root=root / "backups",
                codex_version="codex-cli 0.145.0",
            )

            self.assertIsNotNone(result.manifest_path)
            installer.rollback(result.manifest_path)

            self.assertFalse(hooks_path.exists())
            self.assertFalse(registry_path.exists())

    def test_cli_rollback_uses_manifest_without_install_arguments(self):
        manifest = Path("C:/tmp/install_manifest.json")
        with (
            mock.patch.object(sys, "argv", ["installer", "--rollback", str(manifest)]),
            mock.patch.object(installer, "rollback") as rollback_mock,
        ):
            exit_code = installer.main()

        self.assertEqual(exit_code, 0)
        rollback_mock.assert_called_once_with(
            manifest,
            allowed_backup_root=Path.home() / ".codex" / "backups",
            expected_targets={
                "hooks": Path.home() / ".codex" / "hooks.json",
                "registry": Path.home() / ".claude" / "session_registry.json",
            },
        )

    def test_manifest_rollback_restores_exact_preinstall_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            registry_path = root / "home" / ".claude" / "session_registry.json"
            hooks_path.parent.mkdir(parents=True)
            registry_path.parent.mkdir(parents=True)
            hooks_before = b'{"description":"operator","hooks":{}}\n'
            registry_before = registry_template.read_bytes()
            hooks_path.write_bytes(hooks_before)
            registry_path.write_bytes(registry_before)

            result = installer.install(
                hooks_path=hooks_path,
                registry_path=registry_path,
                hooks_template_path=_ROOT / "templates" / "codex_hooks.json.template",
                registry_template_path=registry_template,
                adapter_path=_SCRIPTS / "codex_session_adapter.py",
                python_executable=Path(sys.executable),
                backup_root=root / "backups",
                codex_version="codex-cli 0.145.0",
            )
            self.assertNotEqual(hooks_path.read_bytes(), hooks_before)

            self.assertIsNotNone(result.manifest_path)
            installer.rollback(result.manifest_path)

            self.assertEqual(hooks_path.read_bytes(), hooks_before)
            self.assertEqual(registry_path.read_bytes(), registry_before)

    def test_second_target_failure_restores_both_exact_preinstall_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            registry_path = root / "home" / ".claude" / "session_registry.json"
            hooks_path.parent.mkdir(parents=True)
            registry_path.parent.mkdir(parents=True)
            hooks_before = b'{"description":"operator","hooks":{}}\n'
            registry_before = registry_template.read_bytes()
            hooks_path.write_bytes(hooks_before)
            registry_path.write_bytes(registry_before)
            real_atomic_write = installer.atomic_write_bytes

            def fail_registry(path: Path, payload: bytes) -> None:
                if path == registry_path:
                    raise OSError("simulated disk failure")
                real_atomic_write(path, payload)

            with (
                mock.patch.object(
                    installer,
                    "atomic_write_bytes",
                    side_effect=fail_registry,
                ),
                self.assertRaises(OSError),
            ):
                installer.install(
                    hooks_path=hooks_path,
                    registry_path=registry_path,
                    hooks_template_path=(
                        _ROOT / "templates" / "codex_hooks.json.template"
                    ),
                    registry_template_path=registry_template,
                    adapter_path=_SCRIPTS / "codex_session_adapter.py",
                    python_executable=Path(sys.executable),
                    backup_root=root / "backups",
                    codex_version="codex-cli 0.145.0",
                )

            self.assertEqual(hooks_path.read_bytes(), hooks_before)
            self.assertEqual(registry_path.read_bytes(), registry_before)

    def test_interrupt_between_target_writes_restores_fresh_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            registry_path = root / "home" / ".claude" / "session_registry.json"
            real_atomic_write = installer.atomic_write_bytes

            def interrupt_registry(path: Path, payload: bytes) -> None:
                if path == registry_path:
                    raise KeyboardInterrupt
                real_atomic_write(path, payload)

            with (
                mock.patch.object(
                    installer,
                    "atomic_write_bytes",
                    side_effect=interrupt_registry,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                installer.install(
                    hooks_path=hooks_path,
                    registry_path=registry_path,
                    hooks_template_path=(
                        _ROOT / "templates" / "codex_hooks.json.template"
                    ),
                    registry_template_path=registry_template,
                    adapter_path=_SCRIPTS / "codex_session_adapter.py",
                    python_executable=Path(sys.executable),
                    backup_root=root / "backups",
                    codex_version="codex-cli 0.145.0",
                )

            self.assertFalse(hooks_path.exists())
            self.assertFalse(registry_path.exists())

    def test_fresh_install_writes_rendered_hook_and_validated_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo with spaces"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            registry_path = root / "home" / ".claude" / "session_registry.json"
            adapter_path = _SCRIPTS / "codex_session_adapter.py"

            result = installer.install(
                hooks_path=hooks_path,
                registry_path=registry_path,
                hooks_template_path=_ROOT / "templates" / "codex_hooks.json.template",
                registry_template_path=registry_template,
                adapter_path=adapter_path,
                python_executable=Path(sys.executable),
                backup_root=root / "backups",
                codex_version="codex-cli 0.145.0",
            )

            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            start = hooks["hooks"]["SessionStart"][0]
            end = hooks["hooks"]["SessionEnd"][0]
            command = start["hooks"][0]["commandWindows"]
            self.assertIn(str(Path(sys.executable).resolve()), command)
            self.assertIn(str(adapter_path.resolve()), command)
            self.assertEqual(start["matcher"], "startup|resume|clear|compact")
            self.assertEqual(start["hooks"][0]["timeout"], 2)
            self.assertEqual(end["hooks"][0]["timeout"], 3)
            self.assertEqual(
                json.loads(registry_path.read_text(encoding="utf-8")),
                json.loads(registry_template.read_text(encoding="utf-8")),
            )
            self.assertTrue(result.changed)
            self.assertTrue(result.manifest_path.is_file())

    def test_install_preserves_unknown_hooks_and_repeat_is_semantic_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            hooks_path.parent.mkdir(parents=True)
            unknown_start = {
                "matcher": "startup",
                "hooks": [
                    {
                        "type": "command",
                        "command": "code-review-graph status",
                        "timeout": 10,
                    }
                ],
            }
            hooks_path.write_text(
                json.dumps(
                    {
                        "description": "operator hooks",
                        "hooks": {
                            "SessionStart": [unknown_start],
                            "PostToolUse": [
                                {
                                    "matcher": "Edit",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "graph update",
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            registry_path = root / "home" / ".claude" / "session_registry.json"
            kwargs = {
                "hooks_path": hooks_path,
                "registry_path": registry_path,
                "hooks_template_path": (
                    _ROOT / "templates" / "codex_hooks.json.template"
                ),
                "registry_template_path": registry_template,
                "adapter_path": _SCRIPTS / "codex_session_adapter.py",
                "python_executable": Path(sys.executable),
                "backup_root": root / "backups",
                "codex_version": "codex-cli 0.145.0",
            }

            first = installer.install(**kwargs)
            first_bytes = hooks_path.read_bytes()
            real_atomic_write = installer.atomic_write_bytes
            with mock.patch.object(
                installer,
                "atomic_write_bytes",
                wraps=real_atomic_write,
            ) as write_mock:
                second = installer.install(**kwargs)

            hooks = json.loads(first_bytes)
            self.assertEqual(hooks["description"], "operator hooks")
            self.assertIn(unknown_start, hooks["hooks"]["SessionStart"])
            self.assertIn("PostToolUse", hooks["hooks"])
            self.assertTrue(first.changed)
            self.assertFalse(second.changed)
            target_writes = [
                call
                for call in write_mock.call_args_list
                if call.args[0] in {hooks_path, registry_path}
            ]
            self.assertEqual(target_writes, [])
            self.assertEqual(hooks_path.read_bytes(), first_bytes)

    def test_install_replaces_owned_hook_when_adapter_location_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _git_repo(repo)
            (repo / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            hooks_path.parent.mkdir(parents=True)
            old_handler = {
                "type": "command",
                "commandWindows": (
                    '"C:\\old\\python.exe" '
                    '"C:\\old\\codex_session_adapter.py"'
                ),
            }
            operator_handler = {
                "type": "command",
                "commandWindows": "security-audit.cmd",
            }
            hooks_path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "SessionStart": [
                                {"matcher": "startup", "hooks": [old_handler, operator_handler]}
                            ],
                            "SessionEnd": [{"hooks": [old_handler, operator_handler]}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            registry_path = root / "home" / ".claude" / "session_registry.json"

            installer.install(
                hooks_path=hooks_path,
                registry_path=registry_path,
                hooks_template_path=_ROOT / "templates" / "codex_hooks.json.template",
                registry_template_path=registry_template,
                adapter_path=_SCRIPTS / "codex_session_adapter.py",
                python_executable=Path(sys.executable),
                backup_root=root / "backups",
                codex_version="codex-cli 0.145.0",
            )

            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]
            for event in ("SessionStart", "SessionEnd"):
                commands = [
                    handler.get("commandWindows", "")
                    for group in hooks[event]
                    for handler in group["hooks"]
                ]
                self.assertEqual(
                    sum("codex_session_adapter.py" in command for command in commands),
                    1,
                )
                self.assertNotIn(str(Path("C:/old")), "\n".join(commands))
                self.assertIn("security-audit.cmd", commands)

    def test_registry_merge_preserves_unknown_repo_and_deduplicates_template_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            other = root / "other"
            for path in (repo, other):
                _git_repo(path)
                (path / "design" / "plans").mkdir(parents=True)
            registry_template = root / "registry.template.json"
            _registry_template(registry_template, repo)
            hooks_path = root / "home" / ".codex" / "hooks.json"
            registry_path = root / "home" / ".claude" / "session_registry.json"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                json.dumps(
                    {
                        "schema_version": "session.registry.v1",
                        "repositories": [
                            {
                                "name": "stale-name",
                                "root": str(repo),
                                "plan_paths": [],
                                "vision_paths": [],
                                "idea_paths": [],
                            },
                            {
                                "name": "operator-other",
                                "root": str(other),
                                "plan_paths": ["design/plans"],
                                "vision_paths": [],
                                "idea_paths": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            installer.install(
                hooks_path=hooks_path,
                registry_path=registry_path,
                hooks_template_path=_ROOT / "templates" / "codex_hooks.json.template",
                registry_template_path=registry_template,
                adapter_path=_SCRIPTS / "codex_session_adapter.py",
                python_executable=Path(sys.executable),
                backup_root=root / "backups",
                codex_version="codex-cli 0.145.0",
            )

            repositories = json.loads(
                registry_path.read_text(encoding="utf-8")
            )["repositories"]
            self.assertEqual(len(repositories), 2)
            by_name = {entry["name"]: entry for entry in repositories}
            self.assertEqual(by_name["repo"]["plan_paths"], ["design/plans"])
            self.assertEqual(
                by_name["operator-other"]["root"],
                str(other),
            )


if __name__ == "__main__":
    unittest.main()
