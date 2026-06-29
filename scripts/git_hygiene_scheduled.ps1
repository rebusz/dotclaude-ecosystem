<#
  git_hygiene_scheduled.ps1 - daily SAFE (dry-run) git-hygiene report.

  Registered as Windows Scheduled Task "TsignalGitHygiene". This wrapper NEVER
  reaps - it runs git_hygiene.py in dry-run only and records the report. Actual
  cleanup stays a deliberate manual step:
      py "$env:USERPROFILE\.claude\scripts\git_hygiene.py" --repo "<repo>" --apply

  Surfaces, per run: reapable branch/worktree inventory + a primary-off-main /
  unpushed-R3 drift ALARM.

  Output:
    ~\.claude\state\git_hygiene\report-latest_<repo>.txt   (overwritten each run)
    ~\.claude\state\git_hygiene\summary.log                (one appended line/run)

  Rollback (remove the automation entirely):
      schtasks /Delete /TN TsignalGitHygiene /F
#>
$ErrorActionPreference = 'SilentlyContinue'
# Never block on a credential prompt under Task Scheduler (no console) - any git
# op that would prompt fails fast instead of hanging the task (-> 0xC000013A).
$env:GIT_TERMINAL_PROMPT = '0'
$script   = Join-Path $env:USERPROFILE '.claude\scripts\git_hygiene.py'
$ideaDigest = Join-Path $env:USERPROFILE '.claude\scripts\idea_digest.py'
$workflowTriggerFile = 'D:\dotclaude\dotclaude-ecosystem\design\workflow_os_revisit_triggers.json'
$stateDir = Join-Path $env:USERPROFILE '.claude\state\git_hygiene'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

# Repos this automaton watches. Add more paths here as the ecosystem grows.
$repos = @('D:\APPS\Tsignal 5.0')

foreach ($repo in $repos) {
    if (-not (Test-Path $repo)) { continue }
    $tag    = ($repo -replace '[:\\ ]', '_')
    # NOTE: no --fetch here. A scheduled, console-less `git fetch` over https can
    # hang/credential-prompt and kill the task; local origin/* refs are refreshed
    # by normal interactive pulls and are fresh enough for a daily nudge. Run the
    # manual reaper with --fetch when you want network-current data.
    $report = & py $script --repo $repo 2>&1 | Out-String

    Set-Content -Path (Join-Path $stateDir ("report-latest_{0}.txt" -f $tag)) `
                -Value $report -Encoding UTF8

    $totalsLine = ($report -split "`n" | Select-String -Pattern 'TOTALS:' | Select-Object -First 1)
    $totals = if ($totalsLine) { $totalsLine.ToString().Trim() } else { 'TOTALS: (none)' }
    $alarm  = if ($report -match '(?m)^\s*!\s') { 'ALARM' } else { 'ok' }
    $stamp  = Get-Date -Format 'yyyy-MM-dd HH:mm'

    Add-Content -Path (Join-Path $stateDir 'summary.log') `
                -Value ("{0} [{1}] {2} :: {3}" -f $stamp, $alarm, $repo, $totals) `
                -Encoding UTF8
}

if ((Test-Path $ideaDigest) -and (Test-Path $workflowTriggerFile)) {
    $triggerReport = & py $ideaDigest workflow-triggers --file $workflowTriggerFile 2>&1 | Out-String
    Set-Content -Path (Join-Path $stateDir 'workflow-os-triggers-latest.txt') `
                -Value $triggerReport -Encoding UTF8

    $triggerTotalsLine = ($triggerReport -split "`n" | Select-String -Pattern '^TOTALS:' | Select-Object -First 1)
    $triggerTotals = if ($triggerTotalsLine) { $triggerTotalsLine.ToString().Trim() } else { 'TOTALS: (none)' }
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
    Add-Content -Path (Join-Path $stateDir 'summary.log') `
                -Value ("{0} [workflow-os] triggers :: {1}" -f $stamp, $triggerTotals) `
                -Encoding UTF8
}
