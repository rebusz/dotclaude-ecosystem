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


PROBES = {
    "tsu.remote_preflight.v1": ProbeSpec(
        "tsu.remote_preflight.v1",
        (sys.executable, "{repo}/tools/tsu_remote_preflight.py", "--repo-root", "{repo}", "--json"),
        "tsu_remote_preflight.v1", True, ("status",), ("ready_for_operator_connect",),
    ),
    "tsu.next_gate_status.v1": ProbeSpec(
        "tsu.next_gate_status.v1",
        (sys.executable, "{repo}/tools/tsu_next_gate_status.py", "--repo-root", "{repo}", "--json"),
        "tsu_next_gate_status.v1", True, ("status",), ("PASS", "READY", "ready"),
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
    if not isinstance(raw["profiles"], dict) or not raw["profiles"]:
        raise RegistryError("profiles must be a non-empty object")
    allowed_collectors = {"git", "plan", "github", "review", "handoff", "runtime", "artifact"}
    for name, value in raw["profiles"].items():
        profile = _object(value, f"profile {name}")
        _closed(profile, {"repo_names", "collectors", "runtime_applicable", "runtime_probe_ids", "required_stages"}, f"profile {name}")
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


def resolve_profile(registry: Mapping[str, Any], repo: Path, explicit: str | None = None) -> tuple[str, Mapping[str, Any]]:
    profiles = registry["profiles"]
    if explicit:
        if explicit not in profiles:
            raise RegistryError(f"unknown profile: {explicit}")
        return explicit, profiles[explicit]
    name = repo.resolve().name.lower()
    for profile_id, profile in profiles.items():
        if name in {str(x).lower() for x in profile["repo_names"]}:
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


def expand_probe(spec: ProbeSpec, repo: Path) -> tuple[str, ...]:
    root = repo.resolve(strict=True)
    argv = tuple(part.replace("{repo}", str(root)) for part in spec.argv_template)
    for part in argv:
        if "{" in part or "}" in part or "*" in part or "?" in part:
            raise RegistryError("unresolved or glob probe argument")
    tool = Path(argv[1]).resolve(strict=True)
    if root not in tool.parents:
        raise RegistryError("probe tool escapes repository")
    return argv


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RegistryError(f"{label} must be an object")
    return value


def _closed(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise RegistryError(f"{label} has invalid keys")
