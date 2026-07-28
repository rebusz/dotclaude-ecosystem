# WatchF Claude Overlay

## Entry Points

- `python watchf_app.py` - main application backend
- `python -m pytest` - test suite

## Code Intelligence & Design

- Use `code-review-graph` tools when inspecting code structure or impact radius (`.claude/refs/graph-tools.md`).
- Read `DESIGN.md` before making UI/visual changes to `watchf-gui/`.
- Post-edit doc rule: After every edit to `design/plans/`, `design/audits/`, `design/visions/` - immediately `git add + git commit + git push`.

## Load On Demand

- `.claude/refs/status.md` - build status and subsystem guide
- `IDEA_BOX.md` - feature backlog and development ideas
- Skill routing: office-hours (brainstorm), investigate (bugs), ship (deploy), review (diff review).
