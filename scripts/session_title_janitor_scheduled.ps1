# Session-title janitor runner.
#
# 2026-08-03 root cause: the old gate refused to run whenever ANY process named
# `claude` existed. That matches the CLI (`AppData\Roaming\Claude\claude-code\
# *\claude.exe`, `.local\bin\claude.exe`) as well as the desktop app, and the
# operator runs both around the clock — so the janitor logged `SKIP: CCD
# running` every 15 min for 9 days and stamped nothing.
#
# The "disk is only authoritative while the app is closed" premise was too
# broad. Measured on 2026-08-03: 469 of 519 store files had not been rewritten
# in over 7 days, and 167 titles already carry the janitor's `<DD MON>` stamp
# with mtimes from 07-17..07-25 — i.e. writes to IDLE sessions persist
# indefinitely. Only sessions CCD currently holds hot get flushed back over
# (2026-07-25: 13 of 21 reverted within minutes — those were the live ones).
#
# So: always run, and let `--skip-active-hours` protect the hot sessions. When
# the desktop app is genuinely down nothing can revert, so sweep everything.
#
# Registered as Windows task `ClaudeSessionTitleJanitor`. Canonical copy lives in
# dotclaude-ecosystem/scripts/.

$ErrorActionPreference = 'Stop'

$stateDir = Join-Path $env:USERPROFILE '.claude\state\session_title_janitor'
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
$log = Join-Path $stateDir 'runs.log'

function Write-Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
}

# Only the MSIX desktop app caches titles in memory. The CLI does not, and must
# never gate this run — conflating the two is what stalled the janitor for 9 days.
$desktop = @(Get-Process -Name 'claude' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like '*\WindowsApps\*' })

if ($desktop.Count -gt 0) {
    # App is up: skip sessions it may be holding hot, stamp the cold remainder.
    $skipHours = 6
} else {
    # App is down: disk is fully authoritative, sweep everything.
    $skipHours = 0
}

$py = Join-Path $env:USERPROFILE '.claude\.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$script = Join-Path $env:USERPROFILE '.claude\scripts\session_title_janitor.py'
if (-not (Test-Path $script)) {
    Write-Log "ERROR: janitor script missing at $script"
    exit 1
}

$env:PYTHONIOENCODING = 'utf-8'
$out = & $py $script --apply --skip-active-hours $skipHours 2>&1
$code = $LASTEXITCODE

# Preserve the real exit code and the summary line — never report a clean run
# when the janitor failed.
$summary = ($out | Where-Object { $_ -match 'sessions checked' } | Select-Object -Last 1)
if ($code -ne 0) {
    Write-Log "FAIL exit=$code :: $($out -join ' | ')"
    exit $code
}
Write-Log "OK (desktop=$($desktop.Count) skipHours=$skipHours) :: $summary"
exit 0
