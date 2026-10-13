# Read-only degraded diagnostic inventory. No command lines, environments or
# credentials are read; missing identity metadata can only produce KEEP.
$ErrorActionPreference = 'Stop'
$reportRoot = $PSScriptRoot
$rows = @(Get-Process | ForEach-Object {
    $proc = $_
    $row = [ordered]@{
        pid = $proc.Id
        name = $proc.ProcessName
        start_time = $null
        parent_pid = $null
        session_id = $null
        username = $null
        command_sha256 = $null
        rss_bytes = $null
        protected_reason = $null
        inspection_error = 'NATIVE_INVENTORY_IDENTITY_INCOMPLETE'
    }
    try { $row.rss_bytes = $proc.WorkingSet64 } catch {}
    try { $row.session_id = $proc.SessionId } catch {}
    try { $row.start_time = ([DateTimeOffset]$proc.StartTime.ToUniversalTime()).ToUnixTimeMilliseconds() / 1000.0 } catch {}
    [pscustomobject]$row
})
$memory = $null
$memoryError = $null
try {
    $systemMemory = Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 10
    $memory = @{
        total_gib = $systemMemory.TotalVisibleMemorySize / 1048576.0
        available_gib = $systemMemory.FreePhysicalMemory / 1048576.0
    }
} catch { $memoryError = $_.Exception.GetType().Name }
$snapshot = @{
    generated_at = [DateTimeOffset]::UtcNow.ToString('o')
    collector = 'PowerShell Get-Process; incomplete identity; no actuation'
    complete = $false
    collection_error = 'PSUTIL_UNAVAILABLE_NATIVE_INVENTORY_PARTIAL'
    controller_pid = $PID
    controller_session = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
    memory = $memory
    memory_error = $memoryError
    rows = $rows
}
$snapshot | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reportRoot 'native-process-snapshot.json') -Encoding UTF8
Write-Output ('Observed processes: ' + $rows.Count)
