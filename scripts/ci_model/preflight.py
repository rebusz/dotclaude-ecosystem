"""CLI for deterministic, side-effect-free shared CI preflight evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .policy import build_preflight
from .schemas import ContractError, canonical_json_bytes

EXIT_POLICY = 10
EXIT_UNKNOWN = 60


def _inside(root: Path, raw: str) -> Path:
    candidate = Path(raw)
    resolved = (
        candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    )
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"path escapes repository: {raw}") from exc
    return resolved


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--changes", required=True)
    parser.add_argument("--risk", required=True, choices=("R0", "R1", "R2", "R3"))
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument(
        "--graph-status",
        required=True,
        choices=("fresh", "stale", "missing", "corrupt"),
    )
    parser.add_argument("--json-out")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repo = Path(args.repo).resolve()
        if not (repo / ".git").exists():
            raise ContractError("--repo is not a Git checkout")
        adapter_path = _inside(repo, args.adapter)
        changes_path = _inside(repo, args.changes)
        adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
        changes = json.loads(changes_path.read_text(encoding="utf-8"))
        if not isinstance(adapter, dict) or not isinstance(changes, list):
            raise ContractError("adapter must be an object and changes must be a list")
        result = build_preflight(
            adapter=adapter,
            changes=changes,
            risk_class=args.risk,
            base_sha=args.base,
            head_sha=args.head,
            graph_status=args.graph_status,
        )
        rendered = canonical_json_bytes(result) + b"\n"
        if args.json_out:
            output = _inside(repo, args.json_out)
            artifact_root = (repo / adapter["artifact_root"]).resolve()
            try:
                output.relative_to(artifact_root)
            except ValueError as exc:
                raise ContractError(
                    f"--json-out must remain under {adapter['artifact_root']}"
                ) from exc
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(f".{output.name}.tmp")
            temporary.write_bytes(rendered)
            temporary.replace(output)
        print(
            f"CI MODEL PREFLIGHT: {result['escalation'].upper()} "
            f"tests={len(result['selected_tests'])} "
            f"sha256={result['preflight_sha256']}"
        )
        return 0
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print("CI MODEL PREFLIGHT: STOP", file=sys.stderr)
        print(f"problem: {exc}", file=sys.stderr)
        return EXIT_POLICY
    except Exception as exc:  # defensive CLI boundary
        print("CI MODEL PREFLIGHT: STOP", file=sys.stderr)
        print(f"problem: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN


if __name__ == "__main__":
    raise SystemExit(run())
