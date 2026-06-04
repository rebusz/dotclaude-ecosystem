# Intent Layer Audit

`scripts/intent_layer_audit.py` checks root `AGENTS.md` / `CLAUDE.md` files for
intent-layer bloat and refs hygiene. It is read-only.

Default thresholds:

- root file review threshold: more than `90` lines;
- manual section review threshold: more than `50` lines outside the managed
  `AGENT-RULES` block;
- `.claude/refs` directory should exist when deeper procedures are needed;
- at least one root file should point to `.claude/refs` when that directory
  exists.

## Example

```powershell
python "C:\Users\dszub\.claude\scripts\intent_layer_audit.py" `
  "D:\APPS\Tsignal 5.0" `
  "D:\APPS\WatchF" `
  "D:\APPS\TsignalLAB" `
  "D:\APPS\Obsidian Flow"
```

Use `--format json` for machine-readable output and `--fail-on-findings` when a
CI-style nonzero exit is useful.

Findings are review prompts, not automatic edit permission. Keep hard safety
invariants in root files; move only stable deep procedures, history dumps, and
stale runbooks behind refs.
