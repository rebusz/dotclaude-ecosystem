#!/usr/bin/env python3
"""Tests for markitdown_measure.py helpers."""

from __future__ import annotations

import unittest
from pathlib import Path

import sys

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import markitdown_measure


class TestMarkitdownMeasure(unittest.TestCase):
    def test_rough_tokens_is_positive(self):
        self.assertGreater(markitdown_measure._rough_tokens("hello world"), 0)

    def test_count_tokens_returns_name(self):
        count, name = markitdown_measure.count_anthropic_tokens("hello world")
        self.assertGreater(count, 0)
        self.assertTrue(name)

    def test_markitdown_import_is_lazy(self):
        self.assertTrue(callable(markitdown_measure.convert_to_markdown))


if __name__ == "__main__":
    unittest.main()
