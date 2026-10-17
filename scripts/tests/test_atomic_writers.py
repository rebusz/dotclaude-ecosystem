"""The catalog/vision writers never leave `<file>.tmp.<pid>` behind on failure
(Slice F item 4: six PLANS.md.tmp.* orphans had piled up in ~/.claude)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

WRITERS = [
    ("plan_catalog", "write_output"),
    ("plan_context_updater", "_atomic_write"),
    ("sync_ecosystem_context", "_atomic_write"),
    ("vision", "_atomic_write"),
    ("vision_catalog", "_write_text_atomic"),
]


@pytest.mark.parametrize("module,func", WRITERS)
def test_a_failed_replace_leaves_no_temp_file(tmp_path: Path, module: str, func: str) -> None:
    target = tmp_path / "PLANS.md"
    target.mkdir()  # os.replace(file, directory) fails on every platform
    write = getattr(importlib.import_module(module), func)
    try:
        write(target, "content")
    except OSError:
        pass  # vision_catalog reports PermissionError and returns; the others raise
    assert [p.name for p in tmp_path.iterdir()] == ["PLANS.md"]


@pytest.mark.parametrize("module,func", WRITERS)
def test_a_successful_write_lands_the_content(tmp_path: Path, module: str, func: str) -> None:
    target = tmp_path / "PLANS.md"
    getattr(importlib.import_module(module), func)(target, "content\n")
    assert target.read_text(encoding="utf-8") == "content\n"
    assert [p.name for p in tmp_path.iterdir()] == ["PLANS.md"]
