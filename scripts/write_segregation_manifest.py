from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate mechanical write-segregation path manifests")
    sub = parser.add_subparsers(dest="cmd", required=True)
    validate = sub.add_parser("validate", help="Validate a path manifest without applying ACLs")
    validate.add_argument("manifest", type=Path)
    dry_run = sub.add_parser("dry-run-acl", help="Generate ACL apply/rollback commands without executing them")
    dry_run.add_argument("manifest", type=Path)
    dry_run.add_argument("--agent-identity", required=True)
    dry_run.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.cmd == "validate":
        return cmd_validate(args)
    if args.cmd == "dry-run-acl":
        return cmd_dry_run_acl(args)
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
