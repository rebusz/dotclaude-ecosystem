<#
  lane_poll_scheduled.ps1 - scheduled lane probe, drain and status.

  Registered as Windows Scheduled Task "TsignalLanePoll" (every 15 minutes).
  Each run, in order, with a 5-minute timeout per command:
      py D:/APPS/_shared/dispatch/dispatch.py lane probe --all
      py D:/APPS/_shared/dispatch/dispatch.py lane drain
      py D:/APPS/_shared/dispatch/dispatch.py lane status
  The status text is appended to ~\.claude\state\lane_poll.log (last 200 lines kept).

  Single-instance mutex. The script makes no network calls of its own, never
  opens a window, and never plays a sound. A normal poll run always exits 0.
  -Register and -Unregister exit 1 when they fail.

  -Register creates or replaces the current-user task (no admin, hidden
  window). It tries an S4U logon (no stored password; runs with or without
  an interactive session) and, if that fails, an Interactive logon principal.
  A second -Register leaves one task. -Unregister removes it. With neither
  switch, run once.

  Rollback:
      powershell -NoProfile -File lane_poll_scheduled.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [switch]$Register,
    [switch]$Unregister
)

$ErrorActionPreference = 'Continue'
$TaskName = 'TsignalLanePoll'
$Dispatch = 'D:/APPS/_shared/dispatch/dispatch.py'
$CommandTimeoutMs = 300000
$ScriptPath = $PSCommandPath
if (-not $ScriptPath) {
    $ScriptPath = $MyInvocation.MyCommand.Path
}

function Write-LanePollLog {
    param([string]$Entry)
    try {
        $dir = Join-Path $env:USERPROFILE '.claude\state'
        if (-not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        $path = Join-Path $dir 'lane_poll.log'
        Add-Content -LiteralPath $path -Value $Entry -Encoding UTF8
        $lines = @(Get-Content -LiteralPath $path -ErrorAction SilentlyContinue)
        if ($lines.Length -gt 200) {
            $kept = @($lines | Select-Object -Last 200)
            Set-Content -LiteralPath $path -Value $kept -Encoding UTF8
        }
    } catch {
    }
}

function Lock-LanePoll {
    try {
        $dir = Join-Path $env:USERPROFILE '.claude\state'
        if (-not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        $path = Join-Path $dir 'lane_poll.lock'
        return [System.IO.File]::Open(
            $path,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None)
    } catch {
        return $null
    }
}

function Invoke-LaneCommand {
    param([string]$Arguments)
    $step = @{
        ExitCode = 1
        Text     = ''
        TimedOut = $false
    }
    $proc = $null
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = 'py'
        $psi.Arguments = $Arguments
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        if ($env:USERPROFILE) {
            $psi.WorkingDirectory = $env:USERPROFILE
        }
        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo = $psi
        $started = $false
        try {
            $started = $proc.Start()
        } catch {
            $step.Text = $_.Exception.Message
            return $step
        }
        if (-not $started) {
            $step.Text = 'py did not start'
            return $step
        }
        $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
        $stderrTask = $proc.StandardError.ReadToEndAsync()
        $exited = $false
        try {
            $exited = $proc.WaitForExit($CommandTimeoutMs)
        } catch {
            $exited = $false
        }
        if (-not $exited) {
            $step.TimedOut = $true
            $prev = $ErrorActionPreference
            $ErrorActionPreference = 'SilentlyContinue'
            & taskkill.exe /F /T /PID $proc.Id | Out-Null
            $ErrorActionPreference = $prev
            try {
                $exited = $proc.WaitForExit(5000)
            } catch {
                $exited = $false
            }
            if (-not $exited) {
                try { $proc.Kill() } catch {}
                try { [void]$proc.WaitForExit(2000) } catch {}
            }
        }
        $stdout = ''
        $stderr = ''
        try {
            if ($stdoutTask.Wait(5000)) {
                $stdout = [string]$stdoutTask.Result
            }
        } catch {
            $stdout = ''
        }
        try {
            if ($stderrTask.Wait(5000)) {
                $stderr = [string]$stderrTask.Result
            }
        } catch {
            $stderr = ''
        }
        if ($stdout -and $stderr) {
            $step.Text = $stdout.TrimEnd() + "`n" + $stderr.TrimEnd()
        } elseif ($stdout) {
            $step.Text = $stdout.TrimEnd()
        } else {
            $step.Text = $stderr.TrimEnd()
        }
        if (-not $step.TimedOut) {
            try {
                $step.ExitCode = [int]$proc.ExitCode
            } catch {
                $step.ExitCode = 1
            }
        }
    } finally {
        if ($proc) {
            try { $proc.Dispose() } catch {}
        }
    }
    return $step
}

function Format-StepCode {
    param($Step)
    if ($Step.TimedOut) {
        return 'timeout'
    }
    return [string]$Step.ExitCode
}

function Invoke-LanePoll {
    $lockStream = $null
    $mutex = $null
    $acquired = $false
    try {
        $lockStream = Lock-LanePoll
        if (-not $lockStream) {
            return
        }
        # Local namespace needs no admin privilege. The lock file above is what
        # keeps a session-0 task from overlapping an interactive run.
        $mutex = New-Object System.Threading.Mutex($false, 'Local\TsignalLanePoll')
        try {
            $acquired = $mutex.WaitOne(0)
        } catch [System.Threading.AbandonedMutexException] {
            $acquired = $true
        }
        if (-not $acquired) {
            return
        }
        $env:GIT_TERMINAL_PROMPT = '0'
        $env:PYTHONIOENCODING = 'utf-8'
        $quoted = '"{0}"' -f $Dispatch
        $probe = Invoke-LaneCommand -Arguments ($quoted + ' lane probe --all')
        $drain = Invoke-LaneCommand -Arguments ($quoted + ' lane drain')
        $status = Invoke-LaneCommand -Arguments ($quoted + ' lane status')
        $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $header = '{0}  probe={1} drain={2} status={3}' -f $stamp, (Format-StepCode $probe), (Format-StepCode $drain), (Format-StepCode $status)
        $entry = $header
        if ($status.Text) {
            $entry = $header + "`n" + $status.Text
        }
        Write-LanePollLog -Entry $entry
    } catch {
        try {
            $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
            Write-LanePollLog -Entry ('{0}  FAIL {1}' -f $stamp, $_.Exception.Message)
        } catch {
        }
    } finally {
        if ($mutex) {
            if ($acquired) {
                try { [void]$mutex.ReleaseMutex() } catch {}
            }
            try { $mutex.Dispose() } catch {}
        }
        if ($lockStream) {
            try { $lockStream.Dispose() } catch {}
        }
    }
}

function Register-LanePollTask {
    if (-not $ScriptPath) {
        throw 'script path is empty'
    }
    $userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $argLine = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $ScriptPath
    $action = New-ScheduledTaskAction -Execute $powershellExe -Argument $argLine -WorkingDirectory $env:USERPROFILE
    $startAt = (Get-Date).AddMinutes(1)
    # 9999 days is the scheduler maximum, so the 15-minute repeat does not expire.
    $trigger = New-ScheduledTaskTrigger -Once -At $startAt -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 9999)
    $trigger.Repetition.StopAtDurationEnd = $false
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -DontStopOnIdleEnd
    $description = 'Probe lanes, drain queued jobs, append lane status. Hidden window, no elevation.'
    try {
        # S4U: current user, no stored password, RunLevel Limited (no elevation).
        # Runs whether or not a logon session is open. Hidden window via -WindowStyle Hidden.
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType S4U -RunLevel Limited -ErrorAction Stop
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -Description $description -ErrorAction Stop | Out-Null
    } catch {
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited -ErrorAction Stop
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -Description $description -ErrorAction Stop | Out-Null
    }
}

function Unregister-LanePollTask {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Output 'no scheduled task TsignalLanePoll'
        return
    }
    $existing | Unregister-ScheduledTask -Confirm:$false -ErrorAction Stop
    Write-Output 'unregistered scheduled task TsignalLanePoll'
}

try {
    if ($Unregister) {
        try {
            Unregister-LanePollTask
        } catch {
            Write-Output ('unregister failed: {0}' -f $_.Exception.Message)
            exit 1
        }
        exit 0
    }
    if ($Register) {
        try {
            Register-LanePollTask
            Write-Output 'registered scheduled task TsignalLanePoll'
        } catch {
            Write-Output ('register failed: {0}' -f $_.Exception.Message)
            exit 1
        }
        exit 0
    }
    Invoke-LanePoll
} catch {
}
exit 0
