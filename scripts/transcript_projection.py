#!/usr/bin/env python3
"""Project host transcript records into policy-free lifecycle evidence items."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectedItem:
    kind: str
    timestamp: str | None = None
    text: str | None = None
    tool_id: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    exit_code: int | None = None
    output: str | None = None


@dataclass(frozen=True)
class PairedToolEvidence:
    tool_id: str
    tool_name: str
    arguments: dict[str, Any]
    exit_code: int
    output: str


_CLAUDE_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_PATCH_PATH_RE = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (.+)$|^\*\*\* Move to: (.+)$",
    re.MULTILINE,
)


def _timestamp(record: dict[str, Any]) -> str | None:
    for key in ("timestamp", "created_at", "createdAt"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _text_item(
    content: object,
    *,
    block_type: str,
    timestamp: str | None,
    plain_strings: bool = False,
) -> tuple[ProjectedItem, ...]:
    if plain_strings and isinstance(content, str):
        content = [content]
    if not isinstance(content, list):
        return ()
    parts = [
        block if isinstance(block, str) else block["text"]
        for block in content
        if (
            plain_strings
            and isinstance(block, str)
            or (
                isinstance(block, dict)
                and block.get("type") == block_type
                and isinstance(block.get("text"), str)
            )
        )
    ]
    if not parts:
        return ()
    return (
        ProjectedItem(
            kind="assistant_text",
            timestamp=timestamp,
            text="\n".join(parts).strip(),
        ),
    )


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def project_record(record: dict[str, Any]) -> tuple[ProjectedItem, ...]:
    """Return structural evidence only; callers retain policy and redaction."""

    timestamp = _timestamp(record)
    if record.get("type") == "assistant":
        message = record.get("message")
        if not isinstance(message, dict):
            return ()
        content = message.get("content")
        items = list(
            _text_item(
                content,
                block_type="text",
                timestamp=timestamp,
                plain_strings=True,
            )
        )
        if not isinstance(content, list):
            return tuple(items)
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_id = block.get("id")
            tool_name = block.get("name")
            arguments = block.get("input")
            if (
                (tool_id is None or (isinstance(tool_id, str) and tool_id))
                and isinstance(tool_name, str)
                and tool_name
                and isinstance(arguments, dict)
            ):
                items.append(
                    ProjectedItem(
                        kind="tool_call",
                        timestamp=timestamp,
                        tool_id=tool_id,
                        tool_name=tool_name,
                        arguments=arguments,
                    )
                )
        return tuple(items)
    if record.get("type") == "user":
        value = record.get("toolUseResult")
        if not isinstance(value, dict):
            value = record.get("tool_use_result")
        if not isinstance(value, dict):
            return ()
        exit_code = value.get("exitCode")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            exit_code = value.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            return ()
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            return ()
        tool_ids = {
            block.get("tool_use_id") or block.get("toolUseId")
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_result"
        }
        if len(tool_ids) != 1:
            return ()
        tool_id = next(iter(tool_ids))
        if not isinstance(tool_id, str) or not tool_id:
            return ()
        output = "\n".join(_strings(value))[:8000]
        return (
            ProjectedItem(
                kind="tool_result",
                timestamp=timestamp,
                tool_id=tool_id,
                exit_code=exit_code,
                output=output,
            ),
        )
    if record.get("type") != "response_item":
        return ()
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return ()
    payload_type = payload.get("type")
    if payload_type == "message" and payload.get("role") == "assistant":
        return _text_item(
            payload.get("content"),
            block_type="output_text",
            timestamp=timestamp,
        )
    if payload_type == "function_call":
        tool_id = payload.get("call_id")
        tool_name = payload.get("name")
        raw_arguments = payload.get("arguments")
        if (
            not isinstance(tool_id, str)
            or not tool_id
            or not isinstance(tool_name, str)
            or not tool_name
            or not isinstance(raw_arguments, str)
        ):
            return ()
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return ()
        if not isinstance(arguments, dict):
            return ()
        return (
            ProjectedItem(
                kind="tool_call",
                timestamp=timestamp,
                tool_id=tool_id,
                tool_name=tool_name,
                arguments=arguments,
            ),
        )
    if payload_type == "custom_tool_call":
        tool_id = payload.get("call_id")
        tool_name = payload.get("name")
        raw_input = payload.get("input")
        if (
            not isinstance(tool_id, str)
            or not tool_id
            or not isinstance(tool_name, str)
            or not tool_name
            or not isinstance(raw_input, str)
        ):
            return ()
        return (
            ProjectedItem(
                kind="tool_call",
                timestamp=timestamp,
                tool_id=tool_id,
                tool_name=tool_name,
                arguments={"input": raw_input},
            ),
        )
    if payload_type == "function_call_output":
        tool_id = payload.get("call_id")
        raw_output = payload.get("output")
        if (
            not isinstance(tool_id, str)
            or not tool_id
            or not isinstance(raw_output, str)
        ):
            return ()
        match = re.search(r"(?m)^Exit code:\s*(-?\d+)\s*$", raw_output)
        if match is None:
            return ()
        marker = "\nOutput:\n"
        output = raw_output.rsplit(marker, 1)[-1] if marker in raw_output else raw_output
        return (
            ProjectedItem(
                kind="tool_result",
                timestamp=timestamp,
                tool_id=tool_id,
                exit_code=int(match.group(1)),
                output=output[:8000],
            ),
        )
    return ()


def pair_tool_evidence(
    items: tuple[ProjectedItem, ...] | list[ProjectedItem],
) -> tuple[PairedToolEvidence, ...]:
    """Pair only unique calls and results sharing one exact non-empty ID."""

    calls: dict[str, list[ProjectedItem]] = {}
    results: dict[str, list[ProjectedItem]] = {}
    result_order: list[str] = []
    for item in items:
        if not item.tool_id:
            continue
        if item.kind == "tool_call":
            calls.setdefault(item.tool_id, []).append(item)
        elif item.kind == "tool_result":
            results.setdefault(item.tool_id, []).append(item)
            result_order.append(item.tool_id)

    paired: list[PairedToolEvidence] = []
    for tool_id in dict.fromkeys(result_order):
        matching_calls = calls.get(tool_id, [])
        matching_results = results.get(tool_id, [])
        if len(matching_calls) != 1 or len(matching_results) != 1:
            continue
        call = matching_calls[0]
        result = matching_results[0]
        if (
            not call.tool_name
            or call.arguments is None
            or result.exit_code is None
            or result.output is None
        ):
            continue
        paired.append(
            PairedToolEvidence(
                tool_id=tool_id,
                tool_name=call.tool_name,
                arguments=call.arguments,
                exit_code=result.exit_code,
                output=result.output,
            )
        )
    return tuple(paired)


def projection_complete(record: dict[str, Any]) -> bool:
    """Report malformed evidence-bearing Codex records as incomplete coverage."""

    if record.get("type") != "response_item":
        return True
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return False
    payload_type = payload.get("type")
    if payload_type in {
        "function_call",
        "function_call_output",
        "custom_tool_call",
    }:
        return bool(project_record(record))
    if isinstance(payload_type, str) and payload_type.startswith("custom_tool_"):
        return False
    if payload_type == "message" and payload.get("role") == "assistant":
        return isinstance(payload.get("content"), list)
    return True


def write_path_candidates(item: ProjectedItem) -> tuple[str, ...]:
    """Return untrusted path strings from allowlisted structural write calls."""

    if item.kind != "tool_call" or item.arguments is None:
        return ()
    if item.tool_name in _CLAUDE_WRITE_TOOLS:
        raw_path = (
            item.arguments.get("file_path")
            or item.arguments.get("path")
            or item.arguments.get("notebook_path")
        )
        return (raw_path,) if isinstance(raw_path, str) and raw_path else ()
    if item.tool_name != "apply_patch":
        return ()
    patch = item.arguments.get("input") or item.arguments.get("patch")
    if not isinstance(patch, str):
        return ()
    paths = [
        first or second
        for first, second in _PATCH_PATH_RE.findall(patch)
        if first or second
    ]
    return tuple(dict.fromkeys(path.strip() for path in paths if path.strip()))
