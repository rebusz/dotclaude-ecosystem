# Tsignal Codex Overlay

## Entry Points

- The canonical backend is `python tsignal_bot.py --headless`, normally owned by EcosystemControl. The default PySide shell is retired; preserve its separate retirement scope.
- `python -m pytest` is the reliable Python validation entrypoint.
- For frontend work, respect the strict GUI port `6175` and validate browser-visible behavior when applicable.

## Codex Implementation Notes

- Keep Tsignal work scoped and validation-backed; do not clean unrelated dirty files.
- Stage only files intentionally changed for the current task.
- Never treat advisory bridge data as execution authority.
- React GUI work belongs under `tsignal-gui/`; do not implement new user-facing cockpit features in PySide6.
