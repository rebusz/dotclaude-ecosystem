#requires -Version 5.1
<#
.SYNOPSIS
  Reproducible / wipe-recovery installer for the curated taste-skill set.
  Reads skills/taste-skill.lock.json, clones the pinned commit, installs via the
  Vercel skills CLI (copy mode, global), then copies into Codex/Cursor native dirs
  (the CLI copy-mode does not populate those reliably).
.NOTES
  Idempotent. Safe to re-run. Pin lives in the lockfile, not here.
#>
[CmdletBinding()]
param(
  [string]$EcoRoot = (Split-Path $PSScriptRoot -Parent)
)
$ErrorActionPreference = 'Stop'

$lockPath = Join-Path $EcoRoot 'skills/taste-skill.lock.json'
if (-not (Test-Path $lockPath)) { throw "Lockfile not found: $lockPath" }
$lock = Get-Content $lockPath -Raw | ConvertFrom-Json

$home_ = $env:USERPROFILE
$vendor = Join-Path $EcoRoot 'vendor/taste-skill'

Write-Host "taste-skill restore -> commit $($lock.pinned_commit)"

# 1. Clone + pin
if (Test-Path $vendor) { Remove-Item $vendor -Recurse -Force }
git clone $lock.source $vendor | Out-Null
git -C $vendor checkout $lock.pinned_commit | Out-Null

# 2. CLI install (copy, global) for the registered agents
$skillArgs = @(); foreach ($s in $lock.installed) { $skillArgs += @('--skill', $s) }
$agentArgs = @(); foreach ($a in $lock.agents)    { $agentArgs += @('-a', $a) }
& npx --yes skills add $vendor @skillArgs @agentArgs --global --copy -y

# 3. Manual copy into Codex + Cursor native dirs (CLI copy-mode gap)
$canonical = Join-Path $home_ '.agents/skills'
$targets = @(
  (Join-Path $home_ '.codex/skills'),
  (Join-Path $home_ '.cursor/skills-cursor')
)
foreach ($dst in $targets) {
  if (-not (Test-Path $dst)) { continue }   # agent not installed -> skip
  foreach ($s in $lock.installed) {
    $src = Join-Path $canonical $s
    if (Test-Path $src) {
      $d = Join-Path $dst $s
      if (Test-Path $d) { Remove-Item $d -Recurse -Force }
      Copy-Item $src $d -Recurse
    }
  }
  Write-Host "  copied $($lock.installed.Count) skills -> $dst"
}

# 4. Redeploy ecosystem-local overlays (house rules) into every agent skill dir
$overlays = @('frontend-house-rules')
$overlayDirs = @(
  (Join-Path $home_ '.claude/skills'),
  (Join-Path $home_ '.agents/skills'),
  (Join-Path $home_ '.codex/skills'),
  (Join-Path $home_ '.cursor/skills-cursor')
)
foreach ($ov in $overlays) {
  $osrc = Join-Path $EcoRoot "skills/$ov"
  if (-not (Test-Path $osrc)) { continue }
  foreach ($od in $overlayDirs) {
    if (-not (Test-Path $od)) { continue }
    $dd = Join-Path $od $ov
    if (Test-Path $dd) { Remove-Item $dd -Recurse -Force }
    Copy-Item $osrc $dd -Recurse
  }
  Write-Host "  deployed overlay $ov"
}
Write-Host "Done. Review skills before use; they run with full agent permissions."
