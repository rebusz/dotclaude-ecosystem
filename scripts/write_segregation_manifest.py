from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ALLOWED_CLASSES = {
    "live-brain-only",
    "operator-only",
    "read-only-for-agents",
    "write-allowed-for-agents",
}

REQUIRED_ENTRY_FIELDS = {
    "id",
    "repo",
    "path_glob",
    "class",
    "owner",
    "reason",
    "rollback_expectation",
}

SECTION37_APPLY_GO_TOKENS = {
    "GO Section 3.7 R2/R3 apply pilot",
    "GO §3.7 R2/R3 apply pilot",
}

DEFAULT_PREAPPLY_BRANCHES = {
    "D:/APPS/TSU": "## master...origin/master",
    "D:/APPS/Tsignal 5.0": "## main...origin/main",
}


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: manifest must be a JSON object")
    return data


def validate_manifest(data: dict[str, Any], *, source: Path) -> dict[str, Any]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if data.get("kind") != "mechanical_write_segregation_path_manifest":
        errors.append("kind must be mechanical_write_segregation_path_manifest")
    if data.get("applies_acl") is not False:
        errors.append("applies_acl must be false for this R1 manifest")

    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries must be a non-empty list")
        entries = []

    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{index}] must be an object")
            continue
        missing = sorted(REQUIRED_ENTRY_FIELDS - set(entry))
        if missing:
            errors.append(f"entries[{index}] missing fields: {', '.join(missing)}")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            errors.append(f"entries[{index}].id must be non-empty text")
        elif entry_id in seen_ids:
            errors.append(f"duplicate entry id: {entry_id}")
        else:
            seen_ids.add(entry_id)
        if entry.get("class") not in ALLOWED_CLASSES:
            errors.append(f"entries[{index}].class must be one of: {', '.join(sorted(ALLOWED_CLASSES))}")
        for key in ("repo", "path_glob", "owner", "reason", "rollback_expectation"):
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"entries[{index}].{key} must be non-empty text")

    repos = {entry.get("repo") for entry in entries if isinstance(entry, dict)}
    for required_repo in ("D:/APPS/TSU", "D:/APPS/Tsignal 5.0"):
        if required_repo not in repos:
            errors.append(f"missing repo entries for {required_repo}")

    if errors:
        raise ValueError(f"{source}: " + "; ".join(errors))
    return {
        "entry_count": len(entries),
        "classes": sorted({entry["class"] for entry in entries}),
        "repos": sorted(repos),
    }


def _expand_braces(pattern: str) -> list[str]:
    start = pattern.find("{")
    if start == -1:
        return [pattern]
    end = pattern.find("}", start)
    if end == -1:
        return [pattern]
    prefix = pattern[:start]
    suffix = pattern[end + 1 :]
    expanded: list[str] = []
    for option in pattern[start + 1 : end].split(","):
        for tail in _expand_braces(suffix):
            expanded.append(f"{prefix}{option}{tail}")
    return expanded


def _command_path(repo: str, path_glob: str) -> tuple[str, bool]:
    recursive = path_glob.endswith("/**")
    normalized = path_glob[:-3] if recursive else path_glob
    full_path = f"{repo.rstrip('/')}/{normalized.lstrip('/')}"
    return full_path.replace("/", "\\"), recursive


def build_acl_dry_run_plan(
    data: dict[str, Any],
    *,
    source: Path,
    agent_identity: str,
) -> dict[str, Any]:
    if not agent_identity.strip():
        raise ValueError("--agent-identity must be non-empty")
    validate_manifest(data, source=source)

    plan_entries: list[dict[str, Any]] = []
    for entry in data["entries"]:
        expanded_targets = []
        apply_commands = []
        rollback_commands = []
        for expanded_glob in _expand_braces(entry["path_glob"]):
            command_path, recursive = _command_path(entry["repo"], expanded_glob)
            recursive_arg = " /T" if recursive else ""
            expanded_targets.append({"path": command_path, "recursive": recursive})
            if entry["class"] != "write-allowed-for-agents":
                apply_commands.append(f'icacls "{command_path}" /deny "{agent_identity}:(W)"{recursive_arg}')
                rollback_commands.append(f'icacls "{command_path}" /remove:d "{agent_identity}"{recursive_arg}')
        plan_entries.append(
            {
                "id": entry["id"],
                "class": entry["class"],
                "owner": entry["owner"],
                "reason": entry["reason"],
                "expanded_targets": expanded_targets,
                "apply_commands": apply_commands,
                "rollback_commands": rollback_commands,
                "no_op": entry["class"] == "write-allowed-for-agents",
            }
        )

    return {
        "kind": "mechanical_write_segregation_acl_dry_run",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_manifest": str(source),
        "agent_identity": agent_identity,
        "applies_acl": False,
        "requires_operator_go_before_apply": True,
        "warning": "Dry-run artifact only. Do not execute apply_commands without explicit R2/R3 operator GO and a refreshed quiesced-state manifest.",
        "entries": plan_entries,
    }


def validate_acl_dry_run_plan(
    data: dict[str, Any],
    *,
    source: Path,
    manifest_data: dict[str, Any] | None = None,
    manifest_source: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if data.get("kind") != "mechanical_write_segregation_acl_dry_run":
        errors.append("kind must be mechanical_write_segregation_acl_dry_run")
    if data.get("applies_acl") is not False:
        errors.append("applies_acl must be false for dry-run artifacts")
    if data.get("requires_operator_go_before_apply") is not True:
        errors.append("requires_operator_go_before_apply must be true")

    agent_identity = data.get("agent_identity")
    if not isinstance(agent_identity, str) or not agent_identity.strip():
        errors.append("agent_identity must be non-empty text")
        agent_identity = ""

    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries must be a non-empty list")
        entries = []

    manifest_entries_by_id: dict[str, dict[str, Any]] = {}
    if manifest_data is not None:
        try:
            validate_manifest(manifest_data, source=manifest_source or Path("<manifest>"))
        except ValueError as exc:
            errors.append(f"source manifest invalid: {exc}")
        else:
            manifest_entries_by_id = {entry["id"]: entry for entry in manifest_data["entries"]}

    seen_ids: set[str] = set()
    non_noop_count = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{index}] must be an object")
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            errors.append(f"entries[{index}].id must be non-empty text")
            entry_id = f"<invalid-{index}>"
        elif entry_id in seen_ids:
            errors.append(f"duplicate entry id: {entry_id}")
        else:
            seen_ids.add(entry_id)

        entry_class = entry.get("class")
        if entry_class not in ALLOWED_CLASSES:
            errors.append(f"entries[{index}].class must be one of: {', '.join(sorted(ALLOWED_CLASSES))}")
        manifest_entry = manifest_entries_by_id.get(entry_id)
        if manifest_entries_by_id and manifest_entry is None:
            errors.append(f"entries[{index}].id not found in source manifest: {entry_id}")
        if manifest_entry and entry_class != manifest_entry.get("class"):
            errors.append(f"entries[{index}].class does not match source manifest for {entry_id}")

        no_op = entry.get("no_op")
        if not isinstance(no_op, bool):
            errors.append(f"entries[{index}].no_op must be boolean")
            no_op = False

        apply_commands = entry.get("apply_commands")
        rollback_commands = entry.get("rollback_commands")
        expanded_targets = entry.get("expanded_targets")
        if not isinstance(apply_commands, list):
            errors.append(f"entries[{index}].apply_commands must be a list")
            apply_commands = []
        if not isinstance(rollback_commands, list):
            errors.append(f"entries[{index}].rollback_commands must be a list")
            rollback_commands = []
        if not isinstance(expanded_targets, list) or not expanded_targets:
            errors.append(f"entries[{index}].expanded_targets must be a non-empty list")

        if no_op:
            if apply_commands or rollback_commands:
                errors.append(f"entries[{index}] no_op entries must not contain ACL commands")
            if entry_class != "write-allowed-for-agents":
                errors.append(f"entries[{index}] no_op is only valid for write-allowed-for-agents")
            continue

        non_noop_count += 1
        if not apply_commands:
            errors.append(f"entries[{index}] non-noop entry is missing apply_commands")
        if not rollback_commands:
            errors.append(f"entries[{index}] non-noop entry is missing rollback_commands")
        if len(apply_commands) != len(rollback_commands):
            errors.append(f"entries[{index}] apply_commands and rollback_commands length mismatch")

        for command in apply_commands:
            if not isinstance(command, str):
                errors.append(f"entries[{index}] apply command must be text")
                continue
            if not command.startswith('icacls "') or " /deny " not in command:
                errors.append(f"entries[{index}] apply command must be an icacls /deny command")
            if f'"{agent_identity}:(W)"' not in command:
                errors.append(f"entries[{index}] apply command must deny the dry-run agent identity")
            if " /grant " in command or " /remove" in command:
                errors.append(f"entries[{index}] apply command contains a non-apply ACL operation")

        for command in rollback_commands:
            if not isinstance(command, str):
                errors.append(f"entries[{index}] rollback command must be text")
                continue
            if not command.startswith('icacls "') or " /remove:d " not in command:
                errors.append(f"entries[{index}] rollback command must be an icacls /remove:d command")
            if f'"{agent_identity}"' not in command:
                errors.append(f"entries[{index}] rollback command must remove the dry-run agent identity")
            if " /deny " in command or " /grant " in command:
                errors.append(f"entries[{index}] rollback command contains a non-rollback ACL operation")

    if manifest_entries_by_id:
        missing_from_dry_run = sorted(set(manifest_entries_by_id) - seen_ids)
        if missing_from_dry_run:
            errors.append("dry-run missing source manifest entries: " + ", ".join(missing_from_dry_run))

    if errors:
        raise ValueError(f"{source}: " + "; ".join(errors))
    return {
        "entry_count": len(entries),
        "non_noop_count": non_noop_count,
        "agent_identity": agent_identity,
        "manifest_checked": manifest_data is not None,
    }


def _packet_missing_commands(dry_run_data: dict[str, Any], packet_text: str) -> list[str]:
    missing: list[str] = []
    for entry in dry_run_data.get("entries", []):
        if not isinstance(entry, dict):
            continue
        for command in entry.get("apply_commands", []) + entry.get("rollback_commands", []):
            if isinstance(command, str) and command not in packet_text:
                missing.append(command)
    return missing


def _git_status(repo: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "-C", str(repo), "status", "--short", "--branch"],
        capture_output=True,
        check=False,
        text=True,
    )
    output = completed.stdout.strip().splitlines()
    branch = output[0] if output else ""
    dirty_lines = [line for line in output[1:] if line.strip()]
    return {
        "repo": str(repo),
        "exit_code": completed.returncode,
        "branch": branch,
        "dirty_lines": dirty_lines,
        "stderr": completed.stderr.strip(),
    }


def _dirty_lines_not_allowed(dirty_lines: list[str], allowed_dirty: list[str]) -> list[str]:
    not_allowed = []
    for line in dirty_lines:
        if not any(fragment and fragment in line for fragment in allowed_dirty):
            not_allowed.append(line)
    return not_allowed


def _repo_key(repo: Path) -> str:
    return str(repo).replace("\\", "/").rstrip("/").lower()


def _parse_repo_mapping(values: list[str] | None, *, option: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"{option} must use <repo>=<value>: {value}")
        repo, mapped = value.split("=", 1)
        if not repo.strip() or not mapped.strip():
            raise ValueError(f"{option} must use non-empty <repo>=<value>: {value}")
        parsed[_repo_key(Path(repo.strip()))] = mapped.strip()
    return parsed


def _branch_allowed(repo: Path, branch: str, required_branches: dict[str, str], allowed_branches: dict[str, str]) -> bool:
    key = _repo_key(repo)
    if key in allowed_branches:
        return branch == allowed_branches[key]
    required = required_branches.get(key)
    return required is None or branch == required


def build_preapply_check(
    *,
    manifest_path: Path,
    dry_run_path: Path,
    packet_path: Path,
    repo_paths: list[Path],
    allowed_dirty: list[str],
    required_branches: dict[str, str],
    allowed_branches: dict[str, str],
    operator_go_token: str | None,
) -> dict[str, Any]:
    reasons: list[str] = []

    manifest_data = load_manifest(manifest_path)
    dry_run_data = load_manifest(dry_run_path)
    dry_run_summary = validate_acl_dry_run_plan(
        dry_run_data,
        source=dry_run_path,
        manifest_data=manifest_data,
        manifest_source=manifest_path,
    )

    packet_text = packet_path.read_text(encoding="utf-8")
    missing_commands = _packet_missing_commands(dry_run_data, packet_text)
    if missing_commands:
        reasons.append(f"packet is missing {len(missing_commands)} dry-run commands")

    repo_statuses = []
    repo_state_ok = True
    for repo in repo_paths:
        status = _git_status(repo)
        status["unaccepted_dirty_lines"] = _dirty_lines_not_allowed(status["dirty_lines"], allowed_dirty)
        status["branch_allowed"] = _branch_allowed(repo, status["branch"], required_branches, allowed_branches)
        status["required_branch"] = required_branches.get(_repo_key(repo))
        status["allowed_branch_override"] = allowed_branches.get(_repo_key(repo))
        if status["exit_code"] != 0:
            repo_state_ok = False
            reasons.append(f"git status failed for {repo}")
        if not status["branch_allowed"]:
            repo_state_ok = False
            reasons.append(f"{repo} is on an unaccepted branch")
        if status["unaccepted_dirty_lines"]:
            repo_state_ok = False
            reasons.append(f"{repo} has unaccepted dirty state")
        repo_statuses.append(status)

    operator_go_accepted = (operator_go_token or "").strip() in SECTION37_APPLY_GO_TOKENS
    if not operator_go_accepted:
        reasons.append("missing explicit Section 3.7 R2/R3 apply pilot GO token")

    ok_without_go = not missing_commands and repo_state_ok
    ready_to_apply = ok_without_go and operator_go_accepted
    return {
        "ok_without_go": ok_without_go,
        "ready_to_apply": ready_to_apply,
        "operator_go_accepted": operator_go_accepted,
        "accepted_go_tokens": sorted(SECTION37_APPLY_GO_TOKENS),
        "dry_run": dry_run_summary,
        "packet": {
            "path": str(packet_path),
            "missing_command_count": len(missing_commands),
        },
        "repo_statuses": repo_statuses,
        "reasons": reasons,
    }


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        summary = validate_manifest(load_manifest(args.manifest), source=args.manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **summary}, indent=2, sort_keys=True))
    return 0


def cmd_dry_run_acl(args: argparse.Namespace) -> int:
    try:
        data = build_acl_dry_run_plan(
            load_manifest(args.manifest),
            source=args.manifest,
            agent_identity=args.agent_identity,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text, end="")
    return 0


def cmd_validate_dry_run(args: argparse.Namespace) -> int:
    try:
        manifest_data = load_manifest(args.manifest) if args.manifest else None
        summary = validate_acl_dry_run_plan(
            load_manifest(args.dry_run),
            source=args.dry_run,
            manifest_data=manifest_data,
            manifest_source=args.manifest,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **summary}, indent=2, sort_keys=True))
    return 0


def cmd_preapply_check(args: argparse.Namespace) -> int:
    repo_paths = args.repo or [
        Path(__file__).resolve().parent.parent,
        Path("D:/APPS/TSU"),
        Path("D:/APPS/Tsignal 5.0"),
    ]
    try:
        required_branches = {_repo_key(Path(__file__).resolve().parent.parent): "## main...origin/main"}
        required_branches.update({_repo_key(Path(repo)): branch for repo, branch in DEFAULT_PREAPPLY_BRANCHES.items()})
        required_branches.update(_parse_repo_mapping(args.require_branch, option="--require-branch"))
        summary = build_preapply_check(
            manifest_path=args.manifest,
            dry_run_path=args.dry_run,
            packet_path=args.packet,
            repo_paths=repo_paths,
            allowed_dirty=args.allow_dirty or [],
            required_branches=required_branches,
            allowed_branches=_parse_repo_mapping(args.allow_branch, option="--allow-branch"),
            operator_go_token=args.operator_go_token,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok_without_go"] else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate mechanical write-segregation path manifests")
    sub = parser.add_subparsers(dest="cmd", required=True)
    validate = sub.add_parser("validate", help="Validate a path manifest without applying ACLs")
    validate.add_argument("manifest", type=Path)
    dry_run = sub.add_parser("dry-run-acl", help="Generate ACL apply/rollback commands without executing them")
    dry_run.add_argument("manifest", type=Path)
    dry_run.add_argument("--agent-identity", required=True)
    dry_run.add_argument("--output", type=Path)
    validate_dry_run = sub.add_parser("validate-dry-run", help="Validate an ACL dry-run artifact without applying ACLs")
    validate_dry_run.add_argument("dry_run", type=Path)
    validate_dry_run.add_argument("--manifest", type=Path)
    preapply = sub.add_parser("preapply-check", help="Check Section 3.7 pre-apply gates without applying ACLs")
    preapply.add_argument("--manifest", type=Path, required=True)
    preapply.add_argument("--dry-run", type=Path, required=True)
    preapply.add_argument("--packet", type=Path, required=True)
    preapply.add_argument("--repo", action="append", type=Path)
    preapply.add_argument("--allow-dirty", action="append")
    preapply.add_argument("--require-branch", action="append", help="Require <repo>=<git status branch line>")
    preapply.add_argument("--allow-branch", action="append", help="Accept <repo>=<git status branch line> instead of the default branch")
    preapply.add_argument("--operator-go-token")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.cmd == "validate":
        return cmd_validate(args)
    if args.cmd == "dry-run-acl":
        return cmd_dry_run_acl(args)
    if args.cmd == "validate-dry-run":
        return cmd_validate_dry_run(args)
    if args.cmd == "preapply-check":
        return cmd_preapply_check(args)
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
