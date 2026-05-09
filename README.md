# dotclaude-ecosystem

A reusable system for managing **plans, visions, idea boxes, and AI memory** across multiple repositories — with automatic context injection for Claude Code, Codex CLI, and other MCP-aware AI tools.

## What this gives you

- **Plan Lifecycle Hooks** — every time you invoke `mode architect`, `/plan-ceo-review`, `/autoplan`, or `/executor`, AI auto-loads the relevant vision Why/DoD/progress + repo IDEA_BOX + global PLANS.md, then auto-updates them after work completes
- **Vision system** — strategic goals live in `<repo>/design/visions/<slug>.md`, plans attach upward via frontmatter `vision: <slug>`, auto-tracked progress
- **Plan catalog** — cross-repo index of all plans with status (draft / in-progress / shipped / abandoned)
- **IDEA_BOX system** — per-repo backlog + global ecosystem-wide cross-cutting items, ranked digest tooling
- **Auto-commit hook** for design docs — protects against context-loss data destruction (root-cause incident: 55k-char plan never landed on disk)
- **AUDIT_AI / AUDIT_Q** — multi-model plan audit pipelines (5 premium models or 4 free models)

## Files

```
scripts/                              ← Python tooling (drop into ~/.claude/scripts/)
  plan_context_loader.py              ← PRE-step: vision + IDEA_BOX + PLANS.md preamble
  plan_context_updater.py             ← POST-step: catalog regen + vision auto-log
  plan_keyword_detector.py            ← UserPromptSubmit hook for trigger words
  plan_catalog.py                     ← generates ~/.claude/PLANS.md
  vision_catalog.py                   ← generates ~/.claude/VISIONS.md
  vision.py                           ← /vision CLI (list, show, new, attach, sync)
  vision_context.py                   ← preamble + completion log for vision-attached plans
  idea_digest.py                      ← cross-repo IDEA_BOX digest, ranked P1→P3
  autocommit_design_docs.py           ← PostToolUse hook for design/ Write+Edit+push
  sync_ecosystem_context.py           ← sync sanitized snapshot to private context repo
  _catalog_common.py                  ← shared helpers

skills/
  master-agent/SKILL.md               ← mode architect, mode implement, etc.
  executor/SKILL.md                   ← /executor with EPILOG_PAYLOAD contract

templates/
  CLAUDE.md.template                  ← global instructions (Plan Lifecycle Hooks contract)
  AGENTS.md.template                  ← Codex CLI / VS Code Codex extension equivalent
  settings.json.template              ← hooks (PostToolUse, UserPromptSubmit, Stop)

install/
  install.ps1                         ← Windows bootstrap
  install.sh                          ← POSIX bootstrap

docs/
  PLAN_LIFECYCLE_HOOKS.md             ← how the auto loader/updater contract works
  VISION_SYSTEM.md                    ← strategic layer over plans
  IDEA_BOX_SYSTEM.md                  ← per-repo + global backlog
  INSTALL.md                          ← step-by-step setup
```

## Install

### Windows

```powershell
git clone https://github.com/dszub/dotclaude-ecosystem.git
cd dotclaude-ecosystem
.\install\install.ps1
```

### POSIX (Linux / macOS)

```bash
git clone https://github.com/dszub/dotclaude-ecosystem.git
cd dotclaude-ecosystem
bash install/install.sh
```

The installer:
1. Backs up your existing `~/.claude/` and `~/.codex/` (if present)
2. Copies scripts into `~/.claude/scripts/`
3. Copies skills into `~/.claude/skills/master-agent/` and `~/.claude/skills/executor/`
4. Merges hooks into `~/.claude/settings.json` (preserves your existing config)
5. Appends Plan Lifecycle Hooks section to `~/.codex/AGENTS.md` (if Codex installed)
6. Initializes empty `~/.claude/MEMORY.md` and `~/.claude/ECOSYSTEM_IDEA_BOX.md` if missing

## Customization

`templates/CLAUDE.md.template` is a starting point — you'll want to add your own:
- Repository list (your `d:/APPS/<repo>/` or equivalent)
- Frozen boundaries / risk classes specific to your domain
- Personal preferences (commit message style, test framework, etc.)

The Plan Lifecycle Hooks contract section should stay verbatim — that's the system contract.

## Philosophy

- **Plans live in repos**, not in `~/.gstack/projects/`. Source of truth is git history.
- **Memory is auto-saved**, not manually managed. The system observes, you correct via natural language.
- **Visions are strategic**, plans are tactical, idea boxes are buffer. Three layers, three purposes.
- **Ship-on by default** — new features land enabled, no soak periods, no dry-run gating.
- **Context is precious** — auto-commit + push every design doc the moment it's written. Don't trust transient state.

## License

MIT. See `LICENSE`.
