# Session-title janitor runner.
#
# The CCD app holds session titles in memory and flushes them to disk, so any
# write made while it runs is overwritten (2026-07-25: 13 of 21 renames were
# reverted within minutes). Disk is only authoritative while the app is closed.
#
# CCD ships as an MSIX Store package, so its launcher cannot be wrapped. Instead
# this task polls and stamps dates whenever CCD is NOT running; the next launch
# then reads already-conforming titles.
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

# Fail closed: if CCD is up, do nothing. Writing now would be silently reverted.
$ccd = Get-Process -Name 'claude' -ErrorAction SilentlyContinue
if ($ccd) {
    Write-Log "SKIP: CCD running ($($ccd.Count) processes)"
    exit 0
}

$py = Join-Path $env:USERPROFILE '.claude\.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$script = Join-Path $env:USERPROFILE '.claude\scripts\session_title_janitor.py'
if (-not (Test-Path $script)) {
    Write-Log "ERROR: janitor script missing at $script"
    exit 1
}

$env:PYTHONIOENCODING = 'utf-8'
$out = & $py $script --apply 2>&1
$code = $LASTEXITCODE

# Preserve the real exit code and the summary line — never report a clean run
# when the janitor failed.
$summary = ($out | Where-Object { $_ -match 'sessions checked' } | Select-Object -Last 1)
if ($code -ne 0) {
    Write-Log "FAIL exit=$code :: $($out -join ' | ')"
    exit $code
}
Write-Log "OK :: $summary"
exit 0
