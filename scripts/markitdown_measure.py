#!/usr/bin/env python3
"""Measure MarkItDown raw-vs-markdown token delta on explicit artifacts."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOKENIZER_VERSION = "@anthropic-ai/tokenizer@0.0.4"
TOKENIZER_CACHE = Path.home() / ".cache" / "dotclaude-tokenizer"

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rough_tokens(text: str) -> int:
    # Explicit fallback only. This is not the ship gate metric.
    return max(1, len(text.encode("utf-8")) // 4)


def count_anthropic_tokens(text: str) -> tuple[int, str]:
    """Return (token_count, tokenizer_name). Falls back only when Node/npm fail."""
    script = """
const fs = require('fs');
const { countTokens } = require('@anthropic-ai/tokenizer');
const text = fs.readFileSync(process.argv[1], 'utf8');
console.log(countTokens(text));
"""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "input.txt"
        path.write_text(text, encoding="utf-8")
        npm = "npm.cmd" if os.name == "nt" else "npm"
        node = "node.exe" if os.name == "nt" else "node"
        if not (TOKENIZER_CACHE / "node_modules" / "@anthropic-ai" / "tokenizer").exists():
            TOKENIZER_CACHE.mkdir(parents=True, exist_ok=True)
            try:
                install = subprocess.run(
                    [npm, "install", "--no-save", TOKENIZER_VERSION],
                    cwd=TOKENIZER_CACHE,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except FileNotFoundError:
                return _rough_tokens(text), "fallback-bytes-div-4"
            if install.returncode != 0:
                return _rough_tokens(text), "fallback-bytes-div-4"
        try:
            cp = subprocess.run(
                [node, "-e", script, str(path)],
                cwd=TOKENIZER_CACHE,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return _rough_tokens(text), "fallback-bytes-div-4"
    if cp.returncode == 0:
        try:
            return int(cp.stdout.strip()), "@anthropic-ai/tokenizer@0.0.4"
        except ValueError:
            pass
    return _rough_tokens(text), "fallback-bytes-div-4"


def convert_to_markdown(path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise RuntimeError(
            "markitdown is not installed; run `python -m pip install \"markitdown[pdf,xlsx]==0.1.6\"`"
        ) from exc
    result = MarkItDown().convert(path)
    return result.text_content or ""


def measure_file(path: Path, expected_terms: list[str]) -> dict[str, Any]:
    raw_bytes = path.read_bytes()
    raw_text = raw_bytes.decode("utf-8", errors="replace")
    markdown = convert_to_markdown(path)
    raw_tokens, raw_tokenizer = count_anthropic_tokens(raw_text)
    markdown_tokens, markdown_tokenizer = count_anthropic_tokens(markdown)
    delta = markdown_tokens - raw_tokens
    pct = None if raw_tokens == 0 else round((delta / raw_tokens) * 100, 2)
    retained_terms = {term: term.lower() in markdown.lower() for term in expected_terms}
    return {
        "path": str(path),
        "suffix": path.suffix.lower(),
        "raw_bytes": len(raw_bytes),
        "markdown_bytes": len(markdown.encode("utf-8")),
        "raw_tokens": raw_tokens,
        "markdown_tokens": markdown_tokens,
        "token_delta": delta,
        "token_delta_pct": pct,
        "tokenizer": raw_tokenizer if raw_tokenizer == markdown_tokenizer else f"{raw_tokenizer}/{markdown_tokenizer}",
        "markdown_preview": markdown[:500],
        "fidelity_check": {
            "markdown_non_empty": bool(markdown.strip()),
            "contains_source_stem": path.stem.lower() in markdown.lower(),
            "expected_terms": retained_terms,
            "expected_terms_ok": all(retained_terms.values()) if retained_terms else None,
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure MarkItDown token delta")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--expect-term", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    missing = [p for p in args.files if not p.exists()]
    if missing:
        for path in missing:
            print(f"missing file: {path}", file=sys.stderr)
        return 2
    report = {
        "schema_version": 1,
        "generated_at": _now(),
        "note": args.note,
        "files": [measure_file(path, args.expect_term) for path in args.files],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
