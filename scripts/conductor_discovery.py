"""Read-only candidate discovery across plans, handoffs, and operational monitors for TruthDeck Conductor.

Discovers possible work without automatically authorizing R2/R3 execution.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import pathlib
from typing import Any, Dict, List, Union



class ConductorDiscovery:
    """Discovers candidate WorkItems from repository plans and handoffs."""

    def __init__(self, repo_root: Union[str, pathlib.Path]):
        self.repo_root = pathlib.Path(repo_root).expanduser().resolve()
        self.plans_dir = self.repo_root / "design" / "plans"

    def discover_plan_candidates(self) -> List[Dict[str, Any]]:
        """Discover candidate plans in design/plans/."""
        candidates = []
        if not self.plans_dir.exists():
            return candidates

        for plan_file in self.plans_dir.glob("*.md"):
            try:
                content = plan_file.read_text(encoding="utf-8")
                frontmatter = self._parse_yaml_frontmatter(content)
                risk = frontmatter.get("risk", "R1")
                workflow = "fwf" if "fwf" in frontmatter.get("tags", []) else "fwp"

                rel_path = str(plan_file.relative_to(self.repo_root)).replace("\\", "/")
                idempotency_key = f"plan_{plan_file.stem}"

                candidates.append(
                    {
                        "idempotency_key": idempotency_key,
                        "title": frontmatter.get("title", plan_file.stem),
                        "repo_id": self.repo_root.name,
                        "repo_path": str(self.repo_root),
                        "plan_path": rel_path,
                        "risk_class": risk if risk in {"R0", "R1", "R2", "R3"} else "R1",
                        "workflow": workflow,
                        "requested_terminal_stage": "merged",
                        "job_kind": "engineering_plan_lifecycle",
                        "priority": 50 if risk in {"R0", "R1"} else 70,
                        "authority_requirement": "standing_r2_go" if risk in {"R2", "R3"} else "none",
                        "source": "plan_discovery",
                    }
                )
            except Exception:
                continue

        return candidates

    def _parse_yaml_frontmatter(self, content: str) -> Dict[str, Any]:
        """Simple regex-based YAML frontmatter parser."""
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}
        yaml_text = parts[1]
        data = {}
        for line in yaml_text.splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key, val = line.split(":", 1)
                data[key.strip()] = val.strip().strip("'\"")
        return data
