"""Offline procmgmt artifact contracts (no live actuation)."""

import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_native_snapshot_collector_writes_utf8_without_bom():
    script = ROOT / "artifacts" / "procmgmt" / "collect-native-processes.ps1"
    text = script.read_text(encoding="utf-8")
    assert "UTF8Encoding $false" in text
    assert "Set-Content" not in text or "UTF8NoBOM" in text or "UTF8Encoding $false" in text


def test_existing_native_snapshot_is_strict_json_when_present():
    path = ROOT / "artifacts" / "procmgmt" / "native-process-snapshot.json"
    if not path.is_file():
        return
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    json.loads(raw.decode("utf-8"))
