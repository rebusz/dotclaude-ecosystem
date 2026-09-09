#!/usr/bin/env python3
"""Unit tests for the shared hook stdin reader (audit P1-14).

Seven hook and adapter entry points read a host event from stdin. On a default
Windows Python that stream is cp1252 with errors="surrogateescape", so a UTF-8
payload mojibakes instead of raising — silently, because every hook fails open.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

from hook_stdio import read_stdin_text  # noqa: E402  (sys.path must be set first)


class ReadStdinTextTests(unittest.TestCase):
    def _with_buffer(self, payload: bytes) -> str:
        stdin = mock.Mock()
        stdin.buffer = io.BytesIO(payload)
        with mock.patch.object(sys, "stdin", stdin):
            return read_stdin_text()

    def test_utf8_bytes_decode_to_the_original_text(self) -> None:
        for text in ("nowy moduł", "zrób plan", "日本語", "plain ascii", ""):
            with self.subTest(text=text):
                self.assertEqual(self._with_buffer(text.encode("utf-8")), text)

    def test_cp1252_is_not_consulted_even_for_bytes_it_could_decode(self) -> None:
        # b"\xc5\x82" is a valid cp1252 sequence ("Å‚") and also the UTF-8
        # encoding of "ł". Reading it as cp1252 is exactly the live defect.
        self.assertEqual(self._with_buffer("ł".encode("utf-8")), "ł")

    def test_undecodable_bytes_are_replaced_rather_than_raising(self) -> None:
        self.assertEqual(self._with_buffer(b"\xff"), "�")

    def test_falls_back_to_the_text_stream_when_there_is_no_buffer(self) -> None:
        # io.StringIO has no .buffer; a caller that already decoded for us (and
        # several existing tests) must keep working.
        with mock.patch.object(sys, "stdin", io.StringIO("already text")):
            self.assertEqual(read_stdin_text(), "already text")

    def test_read_errors_propagate_for_the_caller_to_fail_open_on(self) -> None:
        stdin = mock.Mock()
        stdin.buffer.read.side_effect = OSError("broken pipe")
        with mock.patch.object(sys, "stdin", stdin):
            with self.assertRaises(OSError):
                read_stdin_text()


if __name__ == "__main__":
    unittest.main()
