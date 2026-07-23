"""Dependency-free contracts for the shared CI operating model."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

ADAPTER_SCHEMA = "ci_model_adapter_v1"
PREFLIGHT_SCHEMA = "ci_model_preflight_v1"
SYNC_MANIFEST_SCHEMA = "ci_model_sync_manifest_v1"
CONTRACT_VERSION = "1.0"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """A shared CI contract is missing, unsupported, or internally inconsistent."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def contract_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def require_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    missing = sorted(expected - value.keys())
    extra = sorted(value.keys() - expected)
    if missing or extra:
        detail: list[str] = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if extra:
            detail.append("extra=" + ",".join(extra))
        raise ContractError(f"{label} keys invalid ({'; '.join(detail)})")


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def require_string_list(
    value: Any, label: str, *, allow_empty: bool = False
) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item for item in value)
        or value != sorted(set(value))
    ):
        raise ContractError(f"{label} must be a sorted unique string list")
    return list(value)


def validate_version_range(value: Mapping[str, Any]) -> None:
    require_exact_keys(value, {"min", "max"}, "shared_contract")
    minimum = require_string(value["min"], "shared_contract.min")
    maximum = require_string(value["max"], "shared_contract.max")
    try:
        min_major, min_minor = (int(part) for part in minimum.split(".", 1))
        max_major, max_minor = (int(part) for part in maximum.split(".", 1))
        own_major, own_minor = (int(part) for part in CONTRACT_VERSION.split(".", 1))
    except ValueError as exc:
        raise ContractError("shared contract versions must be MAJOR.MINOR") from exc
    if min_major != own_major or max_major != own_major:
        raise ContractError("unsupported shared contract major")
    if (min_minor, max_minor) != tuple(sorted((min_minor, max_minor))):
        raise ContractError("shared contract version range is reversed")
    if not min_minor <= own_minor <= max_minor:
        raise ContractError("shared contract version range excludes this tool")
