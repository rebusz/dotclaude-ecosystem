# Terminal Evidence Wrapper

`scripts/terminal_evidence.py` runs noisy commands, stores full stdout/stderr in
an artifact, and prints a bounded JSON summary for chat or handoff use.

Default artifacts go under `%TEMP%\terminal-evidence`, not the current repo.
Use `--artifact-dir` only when the output is safe to retain there.

## Examples

```powershell
python "C:\Users\dszub\.claude\scripts\terminal_evidence.py" --label pytest-unit -- python -m pytest tests/test_x.py -q
```

```powershell
python "C:\Users\dszub\.claude\scripts\terminal_evidence.py" --label npm-build -- npm run build
```

```powershell
python "C:\Users\dszub\.claude\scripts\terminal_evidence.py" --label git-diff-check -- git diff --check
```

## Summary Contract

The wrapper prints JSON with:

- command label, risk class, cwd, redacted command;
- exit code, elapsed seconds, timeout flag;
- stdout/stderr line and byte counts;
- failures, warnings, repeated error groups, bounded tail;
- raw artifact path and sidecar summary path.

The wrapper returns the wrapped command's exit code. Timeouts return `124`.

## Safety

Summaries redact common secret patterns. Raw artifacts are full-fidelity by
design, so do not run env dumps, credential reads, broker/account payload dumps,
or session journals through this wrapper unless the output has been reviewed and
redacted. Likely env dump commands are refused by default; `--allow-sensitive`
exists only for deliberate reviewed use.
