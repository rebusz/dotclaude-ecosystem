# Idea Box - dotclaude-ecosystem

## New Modules

- ✅ **DONE (2026-08-04, PR #69 → `7cae806`)** — shipped as
  `design/plans/2026-08-04_installer_managed_hook_block_r2.md` (`scripts/hooks_install.py` +
  `templates/hooks.manifest.json` + a guarded `git_hygiene.py` detector + `hooks-ci.yml`). The
  bootstraps now call the installer; the orphaned `settings.json.template` is retired. History kept
  below for context.
- [P2][M] **Installer-managed `settings.json` hook block.** Installers copy `scripts/*.py`, so
  modules ship; the `settings.json` hook entries do not, so every machine wires hooks by hand and
  nothing detects a machine that never did. That is the one failure mode where the system is
  structurally incapable of reporting its own death: modules present, hooks absent, operator
  believes it is live, nothing runs and nothing complains.
  Deferred three times, each for a different reason worth keeping:
  CEO Finding 9 (2026-07-25) accepted it rather than widen an R1 plan into settings-file
  ownership; Stage 2 finding A9 tried to detect it from inside `session_router.py`; Stage 2b
  finding K3 proved that circular, since the router is delivered *by* the hook it is checking.
  The eng review (Stage 3, 2026-07-25) routed detection into `/curator`, which runs whether or
  not hooks are wired - but only when someone thinks to ask. The underlying cause is untouched.
  Land after `2026-07-25_session_lifecycle_and_hook_hardening_r1.md` so the hook set being wired
  is stable. Full reasoning: that plan's CEO Finding 9, Stage 2b K3, and Eng Review issue 2.
- [P2][M] **Conductor operator GUI** — bramki `host:heavy`, procesy, kolejka, recovery. Trigger: 2026-08-27 CoderPX `HOST_RESOURCE_BUSY` przy `active_units=0` (CCTV `LEASE_EXPIRED`).
- Plan: `design/plans/2026-08-27_conductor_operator_gui_r1.md` (draft-awaiting-go, R2). Lokalne okno Tk, port-free, read-only; projekcja Conductora, bez drugiej władzy admission. Implementacja dopiero po `GO CONDUCTOR GATE PANEL R2`. Handoff źródłowy: `design/handoffs/2026-08-27_conductor_operator_gui_plan_handoff.md`.
