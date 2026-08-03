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

# Everything below is wrapped so a crash still LANDS IN THE LOG. A silent
# exit-1 is indistinguishable from "the task never fired" in the monitoring
# report — which is exactly how the 2026-08-03 14:46 failure presented.
try {
    # Only the MSIX desktop app caches titles in memory. The CLI does not, and
    # must never gate this run — conflating the two stalled the janitor for 9
    # days. Probe `.Path` defensively: the task runs with a Limited token and a
    # process it cannot open throws, which under `Stop` kills the whole script
    # before the first log line ever gets written.
    $desktop = 0
    $unknown = 0
    foreach ($p in @(Get-Process -Name 'claude' -ErrorAction SilentlyContinue)) {
        $path = $null
        try { $path = $p.Path } catch { $path = $null }
        if (-not $path) { $unknown++ }
        elseif ($path -like '*\WindowsApps\*') { $desktop++ }
    }

    if ($desktop -gt 0 -or $unknown -gt 0) {
        # App is up — or a process we could not identify might be it. Skip the
        # sessions it may hold hot and stamp the cold remainder.
        $skipHours = 6
    } else {
        # No desktop app at all: disk is fully authoritative, sweep everything.
        $skipHours = 0
    }

    # Resolve the interpreter explicitly. The old `python` fallback took
    # whatever PATH offered first, and under the task's environment that is the
    # Store alias `...\WindowsApps\python.exe` — an MSIX-packaged interpreter
    # whose AppData reads are redirected into its own LocalCache, so the
    # session store reads as EMPTY and the run dies with "no session store
    # found" while the same command works by hand (2026-08-03 14:58).
    $py = $null
    foreach ($cand in @(
        (Join-Path $env:USERPROFILE '.claude\.venv\Scripts\python.exe'),
        'C:\Python314\python.exe',
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        'C:\Python311\python.exe'
    )) {
        if ($cand -and (Test-Path $cand)) { $py = $cand; break }
    }
    if (-not $py) {
        $py = Get-Command python -All -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notlike '*\WindowsApps\*' } |
            Select-Object -First 1 -ExpandProperty Source
    }
    if (-not $py) {
        Write-Log 'ERROR: no usable python interpreter (Store alias rejected)'
        exit 1
    }

    $script = Join-Path $env:USERPROFILE '.claude\scripts\session_title_janitor.py'
    if (-not (Test-Path $script)) {
        Write-Log "ERROR: janitor script missing at $script"
        exit 1
    }

    $env:PYTHONIOENCODING = 'utf-8'
    # PS 5.1 wraps a native command's stderr into an ErrorRecord, which under
    # `Stop` terminates the run before the exit code is ever inspected. Capture
    # stderr without letting it hijack control flow.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $out = & $py $script --apply --skip-active-hours $skipHours 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEap

    # Preserve the real exit code and the summary line — never report a clean
    # run when the janitor failed.
    $summary = ($out | Where-Object { $_ -match 'sessions checked' } | Select-Object -Last 1)
    if ($code -ne 0) {
        # Capture what THIS context actually sees. The task and a hand-run
        # shell disagreed about whether the session store exists, and without
        # this the log only repeats python's complaint.
        $storeRoot = Join-Path $env:APPDATA 'Claude\claude-code-sessions'
        $seen = @(Get-ChildItem -Path $storeRoot -Recurse -Filter 'local_*.json' `
            -ErrorAction SilentlyContinue).Count
        Write-Log ("FAIL exit=$code py=$py appdata=$env:APPDATA " +
                   "rootExists=$(Test-Path $storeRoot) psSees=$seen :: $($out -join ' | ')")
        exit $code
    }
    Write-Log "OK (desktop=$desktop unknown=$unknown skipHours=$skipHours) :: $summary"
    exit 0
}
catch {
    Write-Log "FAIL (unhandled) :: $($_.Exception.Message)"
    exit 1
}
