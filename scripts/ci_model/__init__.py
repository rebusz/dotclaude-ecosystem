"""Shared, opt-in CI operating-model contracts."""

from .policy import build_preflight, normalize_path, validate_adapter
from .schemas import (
    ADAPTER_SCHEMA,
    CONTRACT_VERSION,
    PREFLIGHT_SCHEMA,
    SYNC_MANIFEST_SCHEMA,
    ContractError,
    canonical_json_bytes,
    contract_hash,
)

__all__ = [
    "ADAPTER_SCHEMA",
    "CONTRACT_VERSION",
    "PREFLIGHT_SCHEMA",
    "SYNC_MANIFEST_SCHEMA",
    "ContractError",
    "build_preflight",
    "canonical_json_bytes",
    "contract_hash",
    "normalize_path",
    "validate_adapter",
]
