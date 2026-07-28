#!/usr/bin/env python3
"""Tests for policy-free Claude and Codex transcript record projection."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import transcript_projection as projection  # noqa: E402


class TestTranscriptProjection(unittest.TestCase):
    def test_claude_legacy_plain_text_shapes_remain_projected(self):
        string_record = {
            "type": "assistant",
            "message": {"content": "plain assistant text"},
        }
        list_record = {
            "type": "assistant",
            "message": {
                "content": [
                    "first",
                    {"type": "text", "text": "second"},
                ]
            },
        }

        self.assertEqual(
            projection.project_record(string_record)[0].text,
            "plain assistant text",
        )
        self.assertEqual(
            projection.project_record(list_record)[0].text,
            "first\nsecond",
        )

    def test_claude_shared_result_with_multiple_ids_is_not_paired(self):
        record = {
            "type": "user",
            "toolUseResult": {"exitCode": 0, "output": "1 passed"},
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "call-1"},
                    {"type": "tool_result", "tool_use_id": "call-2"},
                ]
            },
        }
        calls = [
            projection.ProjectedItem(
                kind="tool_call",
                tool_id=tool_id,
                tool_name="Bash",
                arguments={"command": f"pytest {tool_id}"},
            )
            for tool_id in ("call-1", "call-2")
        ]

        items = [*calls, *projection.project_record(record)]

        self.assertEqual(projection.pair_tool_evidence(items), ())

    def test_codex_assistant_output_text_projects_without_policy(self):
        record = {
            "timestamp": "2026-07-27T17:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "Implemented adapter.py."},
                    {"type": "output_text", "text": "6 tests passed."},
                ],
            },
        }

        items = projection.project_record(record)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "assistant_text")
        self.assertEqual(
            items[0].text,
            "Implemented adapter.py.\n6 tests passed.",
        )
        self.assertEqual(items[0].timestamp, "2026-07-27T17:00:00Z")
        self.assertIsNone(items[0].tool_id)

    def test_claude_assistant_text_projects_with_the_same_item_shape(self):
        record = {
            "timestamp": "2026-07-27T17:01:00Z",
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Implemented adapter.py."},
                    {"type": "text", "text": "6 tests passed."},
                ]
            },
        }

        items = projection.project_record(record)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "assistant_text")
        self.assertEqual(
            items[0].text,
            "Implemented adapter.py.\n6 tests passed.",
        )
        self.assertEqual(items[0].timestamp, "2026-07-27T17:01:00Z")

    def test_codex_function_call_and_result_project_exact_id_and_exit(self):
        call = {
            "timestamp": "2026-07-27T17:02:00Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "call_id": "call-safe-1",
                "arguments": '{"command":"python -m pytest -q tests/test_x.py"}',
            },
        }
        result = {
            "timestamp": "2026-07-27T17:02:01Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-safe-1",
                "output": "Exit code: 0\nWall time: 0.4 seconds\nOutput:\n6 passed",
            },
        }

        call_items = projection.project_record(call)
        result_items = projection.project_record(result)

        self.assertEqual(len(call_items), 1)
        self.assertEqual(call_items[0].kind, "tool_call")
        self.assertEqual(call_items[0].tool_id, "call-safe-1")
        self.assertEqual(call_items[0].tool_name, "shell_command")
        self.assertEqual(
            call_items[0].arguments,
            {"command": "python -m pytest -q tests/test_x.py"},
        )
        self.assertEqual(len(result_items), 1)
        self.assertEqual(result_items[0].kind, "tool_result")
        self.assertEqual(result_items[0].tool_id, "call-safe-1")
        self.assertEqual(result_items[0].exit_code, 0)
        self.assertEqual(result_items[0].output, "6 passed")

    def test_codex_custom_tool_call_projects_apply_patch_input(self):
        patch = (
            "*** Begin Patch\n"
            "*** Add File: src/new.py\n"
            "+print('safe')\n"
            "*** End Patch\n"
        )
        record = {
            "timestamp": "2026-07-27T17:02:00Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "call_id": "call-patch-1",
                "input": patch,
            },
        }

        items = projection.project_record(record)

        self.assertEqual(
            items,
            (
                projection.ProjectedItem(
                    kind="tool_call",
                    timestamp="2026-07-27T17:02:00Z",
                    tool_id="call-patch-1",
                    tool_name="apply_patch",
                    arguments={"input": patch},
                ),
            ),
        )
        self.assertTrue(projection.projection_complete(record))
        self.assertEqual(
            projection.write_path_candidates(items[0]),
            ("src/new.py",),
        )

    def test_malformed_codex_custom_tool_call_is_incomplete(self):
        record = {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "call_id": "call-patch-1",
                "input": {"patch": "not-structural"},
            },
        }

        self.assertEqual(projection.project_record(record), ())
        self.assertFalse(projection.projection_complete(record))

    def test_codex_custom_tool_output_shapes_are_complete(self):
        legacy = {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-patch-1",
                "output": (
                    '{"output":"Success","metadata":{"exit_code":0,'
                    '"duration_seconds":0.0}}'
                ),
            },
        }
        current = {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-exec-1",
                "output": [
                    {
                        "type": "input_text",
                        "text": "Script completed\nExit code: 0\n",
                    }
                ],
            },
        }

        self.assertTrue(projection.projection_complete(legacy))
        self.assertTrue(projection.projection_complete(current))

    def test_malformed_codex_custom_tool_output_is_incomplete(self):
        malformed = {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-patch-1",
                "output": [{"type": "image", "text": 123}],
            },
        }

        self.assertFalse(projection.projection_complete(malformed))

    def test_claude_tool_use_and_result_keep_existing_semantics(self):
        call = {
            "timestamp": "2026-07-27T17:03:00Z",
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-safe-1",
                        "name": "Bash",
                        "input": {"command": "python -m pytest -q"},
                    }
                ]
            },
        }
        result = {
            "timestamp": "2026-07-27T17:03:01Z",
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-safe-1",
                        "content": "5 passed",
                    }
                ]
            },
            "toolUseResult": {"exitCode": 0, "stdout": "5 passed"},
        }

        call_items = projection.project_record(call)
        result_items = projection.project_record(result)

        self.assertEqual(
            call_items,
            (
                projection.ProjectedItem(
                    kind="tool_call",
                    timestamp="2026-07-27T17:03:00Z",
                    tool_id="tool-safe-1",
                    tool_name="Bash",
                    arguments={"command": "python -m pytest -q"},
                ),
            ),
        )
        self.assertEqual(result_items[0].kind, "tool_result")
        self.assertEqual(result_items[0].tool_id, "tool-safe-1")
        self.assertEqual(result_items[0].exit_code, 0)
        self.assertIn("5 passed", result_items[0].output or "")

    def test_duplicate_call_id_drops_all_evidence_for_that_id(self):
        call = projection.ProjectedItem(
            kind="tool_call",
            tool_id="duplicate-id",
            tool_name="shell_command",
            arguments={"command": "python -m pytest -q"},
        )
        result = projection.ProjectedItem(
            kind="tool_result",
            tool_id="duplicate-id",
            exit_code=0,
            output="99 passed",
        )

        paired = projection.pair_tool_evidence((call, call, result))

        self.assertEqual(paired, ())


if __name__ == "__main__":
    unittest.main()
