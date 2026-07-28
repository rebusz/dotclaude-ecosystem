# WatchF Codex Overlay

## Entry Points

- `python watchf_app.py` - run application
- `python -m pytest` - run unit tests

## Codex Implementation Notes

- WatchF is advisory-only; never send direct broker orders from WatchF.
- Respect port binding contract (`7175` GUI, `7176` WS, `6101` Tsignal).
- Stage only files intentionally changed; avoid touching unrelated modified files in the worktree.
