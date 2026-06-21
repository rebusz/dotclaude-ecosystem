#!/usr/bin/env python3
"""Regenerate docs/SKILLS_INDEX.md.

The per-agent sections are read LIVE from each agent's skill dir (name + description
pulled from every SKILL.md frontmatter). The curated sections (mode system, fusion,
built-in commands, document skills) are maintained inline in CURATED below.

Run after installing/removing skills:  python scripts/skills_index.py
"""
from __future__ import annotations
import re
from pathlib import Path

HOME = Path.home()
ECO = Path(__file__).resolve().parent.parent
OUT = ECO / "docs" / "SKILLS_INDEX.md"

# (heading, dir) — order matters; canonical store first.
AGENT_DIRS = [
    ("Global — wszystkie agenty (`~/.agents/skills`)", HOME / ".agents" / "skills"),
    ("Claude Code (`~/.claude/skills`)", HOME / ".claude" / "skills"),
    ("Codex (`~/.codex/skills`)", HOME / ".codex" / "skills"),
    ("Cursor (`~/.cursor/skills-cursor`)", HOME / ".cursor" / "skills-cursor"),
]

CURATED = """\
## 2. System "mode" (master-agent) — `mode <X> task ...` / `tryb <X>`
- **Core:** OPERATOR, ARCHITECT, IMPLEMENT, DEBUG, INVESTIGATE, AUDIT, AUDIT_AI, REVIEW, TEST, CONTRACT, INTEGRATE, QUANT, POSTMORTEM
- **Ops:** SHIP, QA, CSO, OFFICE-HOURS, AUTOPLAN, RETRO, CAREFUL, LEARN
- **gstack aliasy:** /review /ship /qa /investigate /cso /retro /learn /office-hours /autoplan /careful /plan-ceo-review /plan-eng-review /executor

## 3. Multi-model audyt & fusion
- `/fusion` — presety cheap / breadth / quality / matrix / matrixP
- `mode auditF` (free lanes) - `mode auditP` (paid) - auditQ/auditAI (aliasy)

## 4. Planowanie, research, pamiec
- whatnext - plans - deep-research - executor
- claude-mem: make-plan - do - mem-search - smart-explore - timeline-report

## 5. Claude Code — wbudowane workflow commands
code-review - simplify - verify - run - init - review - security-review - loop - schedule - update-config - keybindings-help - fewer-permission-prompts - claude-api

## 6. Dokumenty / kreatywne (anthropic-skills)
docx - pdf - pptx - xlsx - algorithmic-art - skill-creator - consolidate-memory - setup-cowork

> Komendy z dialogiem terminala (/permissions, /config, /agents, /doctor, /hooks) dzialaja tylko w interaktywnym `claude`, nie w sesji nieinteraktywnej.
"""


def parse_skill(skill_md: Path):
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"^---\s*\n(.*?)\n---", text, re.S | re.M)
    block = m.group(1) if m else text[:2000]
    name = None
    nm = re.search(r"^name:\s*(.+)$", block, re.M)
    if nm:
        name = nm.group(1).strip().strip('"').strip("'")
    desc = ""
    dm = re.search(r"^description:\s*(.*)$", block, re.M)
    if dm:
        d = dm.group(1).strip()
        if d in ("", "|", ">", "|-", ">-", "|+", ">+"):  # block scalar -> gather indented lines
            collected = []
            for line in block[dm.end():].splitlines():
                if line and not line[0].isspace():  # next top-level key
                    break
                if line.strip():
                    collected.append(line.strip())
            d = " ".join(collected)
        desc = d.strip().strip('"').strip("'")
    if not name:
        name = skill_md.parent.name
    if desc:
        desc = re.split(r"(?<=[.!?])\s", desc)[0]
        if len(desc) > 160:
            desc = desc[:157].rstrip() + "..."
    return name, desc


def scan(dir_path: Path):
    rows = []
    if not dir_path.is_dir():
        return rows
    for child in sorted(dir_path.iterdir()):
        if child.name.startswith("."):
            continue
        skill_md = child / "SKILL.md"
        if skill_md.is_file():
            parsed = parse_skill(skill_md)
            if parsed:
                rows.append(parsed)
    return rows


def main():
    parts = [
        "# Skills & Commands Index\n",
        "_Auto-generowane przez `scripts/skills_index.py` — sekcje per-agent czytane na zywo z katalogow "
        "skilli; sekcje 2-6 kuratorowane w skrypcie. Nie edytuj recznie sekcji 1._\n",
        "## 1. Skille per-agent (z katalogow)\n",
    ]
    total = 0
    for title, d in AGENT_DIRS:
        rows = scan(d)
        total += len(rows)
        parts.append(f"### {title} — {len(rows)}")
        if not rows:
            parts.append("_(brak / agent niezainstalowany)_\n")
            continue
        for name, desc in rows:
            parts.append(f"- `{name}` — {desc}" if desc else f"- `{name}`")
        parts.append("")
    parts.append(CURATED)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({total} skill entries across {len(AGENT_DIRS)} agent dirs)")


if __name__ == "__main__":
    main()
