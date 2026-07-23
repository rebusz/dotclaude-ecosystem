"""Closed profile registry and code-owned read-only runtime probe allowlist."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from truthdeck_model import STAGE_ORDER, Stage, canonical_json

REGISTRY_SCHEMA = "truthdeck.registry.v1"


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ProbeSpec:
    probe_id: str
    argv_template: tuple[str, ...]
    schema_version: str
    read_only: bool
    status_path: tuple[str, ...]
    ready_values: tuple[str, ...]
    sample_path: tuple[str, ...] | None = None
    build_path: tuple[str, ...] | None = None
    allowed_repo_ids: tuple[str, ...] = ()
    tool_sha256: str = ""


PROBES = {
    "tsu.remote_preflight.v1": ProbeSpec(
        "tsu.remote_preflight.v1",
        (sys.executable, "{repo}/tools/tsu_remote_preflight.py", "--repo-root", "{repo}", "--json"),
        "tsu_remote_preflight.v1", True, ("status",), ("ready_for_operator_connect",),
        allowed_repo_ids=("rebusz/tsu",),
        tool_sha256="e151b9f38ba0d5f138502a6bd0dc4e11b491d39e3411e9688b5a55e220282db6",
    ),
    "tsu.next_gate_status.v1": ProbeSpec(
        "tsu.next_gate_status.v1",
        (sys.executable, "{repo}/tools/tsu_next_gate_status.py", "--repo-root", "{repo}", "--json"),
        "tsu_next_gate_status.v1", True, ("status",), ("ready_for_operator_review",),
        allowed_repo_ids=("rebusz/tsu",),
        tool_sha256="b213b5f263f52d76accc41362b6f72ae28aeae8940392cb169aaf46cf58c5c34",
    ),
    "tsignal.dod_deck.v1": ProbeSpec(
        "tsignal.dod_deck.v1",
        (sys.executable, "{repo}/scripts/dod_deck.py", "run", "--repo", "{repo}", "--truthdeck"),
        "tsignal_dod_deck.v1", True, ("status",), ("ok",),
        sample_path=("sample_count",), build_path=("build",),
        allowed_repo_ids=("rebusz/tsignal",),
        tool_sha256="9da10fa1c29f3689c43b4d07da98dfc3020260767519a3a54467125ae85cab3d",
    ),
}


def load_registry(path: Path) -> tuple[dict[str, Any], str]:
    raw_bytes = path.resolve(strict=True).read_bytes()
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise RegistryError("registry is not valid JSON") from exc
    validate_registry(raw)
    return raw, hashlib.sha256(canonical_json(raw)).hexdigest()


def validate_registry(raw: Any) -> None:
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "defaults", "profiles", "task_aliases"}:
        raise RegistryError("registry must contain only schema_version, defaults, profiles, task_aliases")
    if raw["schema_version"] != REGISTRY_SCHEMA:
        raise RegistryError("unsupported registry schema")
    defaults = _object(raw["defaults"], "defaults")
    _closed(defaults, {"base_ref", "command_timeout_s", "total_deadline_s", "max_output_bytes"}, "defaults")
    if not isinstance(defaults["base_ref"], str) or not defaults["base_ref"]:
        raise RegistryError("default base_ref must be a non-empty string")
    for key in ("command_timeout_s", "total_deadline_s"):
        if type(defaults[key]) not in {int, float} or not 0 < float(defaults[key]) <= 60:
            raise RegistryError(f"default {key} must be within (0, 60]")
    if type(defaults["max_output_bytes"]) is not int or not 1024 <= defaults["max_output_bytes"] <= 10_485_760:
        raise RegistryError("default max_output_bytes must be within [1024, 10485760]")
    if not isinstance(raw["profiles"], dict) or not raw["profiles"]:
        raise RegistryError("profiles must be a non-empty object")
    allowed_collectors = {"git", "plan", "github", "review", "handoff", "runtime", "artifact", "installation"}
    for name, value in raw["profiles"].items():
        profile = _object(value, f"profile {name}")
        _closed(profile, {"repo_names", "collectors", "runtime_applicable", "runtime_probe_ids", "required_stages", "required_checks"}, f"profile {name}")
        for key in ("repo_names", "collectors", "runtime_probe_ids", "required_stages", "required_checks"):
            if not isinstance(profile[key], list) or not all(isinstance(item, str) for item in profile[key]):
                raise RegistryError(f"profile {name} {key} must be an array of strings")
        if type(profile["runtime_applicable"]) is not bool:
            raise RegistryError(f"profile {name} runtime_applicable must be boolean")
        if not set(profile["collectors"]).issubset(allowed_collectors):
            raise RegistryError(f"profile {name} contains unknown collector")
        if not set(profile["runtime_probe_ids"]).issubset(PROBES):
            raise RegistryError(f"profile {name} contains non-code-owned probe")
        if not all(PROBES[x].read_only for x in profile["runtime_probe_ids"]):
            raise RegistryError(f"profile {name} contains mutating probe")
        try:
            tuple(Stage(x) for x in profile["required_stages"])
        except ValueError as exc:
            raise RegistryError(f"profile {name} contains unknown stage") from exc
    if not isinstance(raw["task_aliases"], dict):
        raise RegistryError("task_aliases must be an object")
    for alias_name, alias_value in raw["task_aliases"].items():
        if not isinstance(alias_name, str) or not alias_name:
            raise RegistryError("task alias names must be non-empty strings")
        alias = _object(alias_value, f"task alias {alias_name}")
        if not set(alias).issubset({"repos", "plan", "handoff", "handoff_sha256", "profile"}):
            raise RegistryError(f"task alias {alias_name} has invalid keys")
        if not isinstance(alias.get("repos"), list) or not alias["repos"] or not all(
                isinstance(item, str) and Path(item).is_absolute() for item in alias["repos"]):
            raise RegistryError(f"task alias {alias_name} repos must be non-empty absolute paths")
        for key in ("plan", "handoff"):
            if key in alias and (not isinstance(alias[key], str) or not Path(alias[key]).is_absolute()):
                raise RegistryError(f"task alias {alias_name} {key} must be an absolute path")
        if ("handoff" in alias) != ("handoff_sha256" in alias):
            raise RegistryError(f"task alias {alias_name} handoff and handoff_sha256 must appear together")
        digest = alias.get("handoff_sha256")
        if digest is not None and (not isinstance(digest, str) or len(digest) != 64
                                   or any(char not in "0123456789abcdef" for char in digest)):
            raise RegistryError(f"task alias {alias_name} handoff_sha256 must be lowercase SHA-256")
        if "profile" in alias and alias["profile"] not in raw["profiles"]:
            raise RegistryError(f"task alias {alias_name} has unknown profile")


def resolve_task_alias(registry: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    try:
        return registry["task_aliases"][name]
    except KeyError as exc:
        raise RegistryError(f"unknown task alias: {name}") from exc


def resolve_profile(registry: Mapping[str, Any], repo: Path, explicit: str | None = None,
                    repo_id: str | None = None) -> tuple[str, Mapping[str, Any]]:
    profiles = registry["profiles"]
    if explicit:
        if explicit not in profiles:
            raise RegistryError(f"unknown profile: {explicit}")
        _verify_profile_identity(explicit, repo_id)
        return explicit, profiles[explicit]
    name = repo.resolve().name.lower()
    for profile_id, profile in profiles.items():
        if name in {str(x).lower() for x in profile["repo_names"]}:
            _verify_profile_identity(profile_id, repo_id)
            return profile_id, profile
    return "generic", profiles["generic"]


def apply_narrowing(profile: Mapping[str, Any], policy_path: Path | None) -> dict[str, Any]:
    result = dict(profile)
    if policy_path is None or not policy_path.exists():
        return result
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not set(raw).issubset({"collectors", "runtime_probe_ids", "required_stages"}):
        raise RegistryError("repo policy contains widening or unknown fields")
    for key in ("collectors", "runtime_probe_ids"):
        if key in raw:
            requested = set(raw[key])
            current = set(profile[key])
            if not requested.issubset(current):
                raise RegistryError(f"repo policy may only narrow {key}")
            result[key] = [x for x in profile[key] if x in requested]
    if "required_stages" in raw:
        requested = tuple(Stage(x) for x in raw["required_stages"])
        result["required_stages"] = [x.value for x in STAGE_ORDER if x in set(map(Stage, profile["required_stages"])) | set(requested)]
    return result


def expand_probe(spec: ProbeSpec, repo: Path, repo_id: str) -> tuple[str, ...]:
    if repo_id.lower() not in spec.allowed_repo_ids:
        raise RegistryError(f"probe {spec.probe_id} is not allowed for repository {repo_id}")
    root = repo.resolve(strict=True)
    argv = tuple(part.replace("{repo}", str(root)) for part in spec.argv_template)
    for part in argv:
        if "{" in part or "}" in part or "*" in part or "?" in part:
            raise RegistryError("unresolved or glob probe argument")
    tool = Path(argv[1]).resolve(strict=True)
    if root not in tool.parents:
        raise RegistryError("probe tool escapes repository")
    if hashlib.sha256(tool.read_bytes()).hexdigest() != spec.tool_sha256:
        raise RegistryError(f"probe source digest mismatch for {spec.probe_id}")
    return argv


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RegistryError(f"{label} must be an object")
    return value


def _closed(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise RegistryError(f"{label} has invalid keys")


def _verify_profile_identity(profile_id: str, repo_id: str | None) -> None:
    expected = {
        "dotclaude-ecosystem": "rebusz/dotclaude-ecosystem",
        "tsu": "rebusz/tsu",
        "tsignal-5.0": "rebusz/tsignal",
    }.get(profile_id)
    if expected and (repo_id or "").lower() != expected:
        raise RegistryError(f"profile {profile_id} is bound to {expected}, not {repo_id or 'unknown'}")
