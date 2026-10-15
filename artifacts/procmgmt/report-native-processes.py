"""Run the actual reaper classifier on the degraded, read-only native snapshot."""

import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import conductor_reaper as reaper  # noqa: E402

folder = pathlib.Path(__file__).resolve().parent
snapshot = json.loads((folder / "native-process-snapshot.json").read_text(encoding="utf-8-sig"))
try:
    records, registry_status = reaper.read_registry(pathlib.Path.home() / ".conductor")
except (OSError, sqlite3.Error) as exc:
    records, registry_status = [], "REGISTRY_UNREADABLE_" + type(exc).__name__
for row in snapshot["rows"]:
    row["protected_reason"] = reaper.protected_reason(name=row["name"])
table = reaper.ProcessTable(snapshot["rows"], complete=False, error=snapshot["collection_error"])
report = reaper.build_report(
    records, table, owner_id="conductor-procmgmt-astra-20261013",
    session_id=snapshot["controller_session"], username=None,
    controller_pid=snapshot["controller_pid"], now=snapshot["generated_at"],
)
report.update(registry_status=registry_status, collector=snapshot["collector"],
              memory=snapshot["memory"], memory_error=snapshot["memory_error"], actuation=[])
python_rows = [row for row in report["rows"] if (row["name"] or "").lower().startswith(("python", "pytest"))]
report["python_summary"] = {
    "processes": len(python_rows),
    "would_kill": sum(row["action"] == "WOULD_KILL" for row in python_rows),
    "keep": sum(row["action"] == "KEEP" for row in python_rows),
    "rss_gib": round(sum(row["rss_gib"] or 0 for row in python_rows), 6),
}
(folder / "process-dry-run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
(folder / "process-dry-run.md").write_text(reaper.render_markdown(report), encoding="utf-8")
print(json.dumps({"mode": report["mode"], "registry_status": registry_status,
                  "summary": report["summary"], "python_summary": report["python_summary"],
                  "memory": report["memory"], "collection_error": report["collection_error"]}))
