# dotclaude-ecosystem installer (Windows)
# Idempotent: safe to re-run.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ClaudeHome = Join-Path $env:USERPROFILE ".claude"
$CodexHome = Join-Path $env:USERPROFILE ".codex"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

Write-Host "=== dotclaude-ecosystem installer ===" -ForegroundColor Cyan
Write-Host "Source : $RepoRoot"
Write-Host "Target : $ClaudeHome"
Write-Host ""

# Backup existing
if (Test-Path $ClaudeHome) {
    $backup = "$ClaudeHome.bak.$Stamp"
    Write-Host "[1/6] Backup ~/.claude -> $backup" -ForegroundColor Yellow
    Copy-Item -Path $ClaudeHome -Destination $backup -Recurse -Force
} else {
    Write-Host "[1/6] No existing ~/.claude to back up" -ForegroundColor Green
    New-Item -ItemType Directory -Force -Path $ClaudeHome | Out-Null
}

# Scripts
Write-Host "[2/6] Copy scripts -> ~/.claude/scripts/" -ForegroundColor Cyan
$ScriptsSrc = Join-Path $RepoRoot "scripts"
$ScriptsDst = Join-Path $ClaudeHome "scripts"
New-Item -ItemType Directory -Force -Path $ScriptsDst | Out-Null
Copy-Item -Path "$ScriptsSrc\*.py" -Destination $ScriptsDst -Force

# Skills
Write-Host "[3/6] Copy skills -> ~/.claude/skills/" -ForegroundColor Cyan
foreach ($skill in @("master-agent", "executor")) {
    $src = Join-Path $RepoRoot "skills\$skill"
    $dst = Join-Path $ClaudeHome "skills\$skill"
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item -Path "$src\*" -Destination $dst -Recurse -Force
}

# settings.json — merge hooks
Write-Host "[4/6] Merge hooks into ~/.claude/settings.json" -ForegroundColor Cyan
$SettingsTpl = Join-Path $RepoRoot "templates\settings.json.template"
$SettingsDst = Join-Path $ClaudeHome "settings.json"
if (Test-Path $SettingsDst) {
    Write-Host "  existing settings.json found — manual merge required, see install_notes.md" -ForegroundColor Yellow
    Copy-Item -Path $SettingsTpl -Destination "$SettingsDst.from-template" -Force
} else {
    Copy-Item -Path $SettingsTpl -Destination $SettingsDst -Force
    Write-Host "  installed fresh settings.json" -ForegroundColor Green
}

# CLAUDE.md
Write-Host "[5/6] Install CLAUDE.md template" -ForegroundColor Cyan
$ClaudeMdTpl = Join-Path $RepoRoot "templates\CLAUDE.md.template"
$ClaudeMdDst = Join-Path $ClaudeHome "CLAUDE.md"
if (Test-Path $ClaudeMdDst) {
    Write-Host "  existing CLAUDE.md found — leaving in place; template at $ClaudeMdDst.from-template" -ForegroundColor Yellow
    Copy-Item -Path $ClaudeMdTpl -Destination "$ClaudeMdDst.from-template" -Force
} else {
    Copy-Item -Path $ClaudeMdTpl -Destination $ClaudeMdDst -Force
    Write-Host "  installed fresh CLAUDE.md" -ForegroundColor Green
}

# Codex AGENTS.md (optional)
Write-Host "[6/6] Codex AGENTS.md (optional)" -ForegroundColor Cyan
if (Test-Path $CodexHome) {
    $AgentsTpl = Join-Path $RepoRoot "templates\AGENTS.md.template"
    $AgentsDst = Join-Path $CodexHome "AGENTS.md"
    if (Test-Path $AgentsDst) {
        Write-Host "  existing ~/.codex/AGENTS.md found — appending Plan Lifecycle Hooks section if missing"
        $existing = Get-Content $AgentsDst -Raw
        if ($existing -notmatch "Plan Lifecycle Hooks") {
            $append = Get-Content $AgentsTpl -Raw
            Add-Content -Path $AgentsDst -Value "`n$append"
            Write-Host "  appended" -ForegroundColor Green
        } else {
            Write-Host "  already present" -ForegroundColor Green
        }
    } else {
        Copy-Item -Path $AgentsTpl -Destination $AgentsDst -Force
        Write-Host "  installed fresh AGENTS.md" -ForegroundColor Green
    }
} else {
    Write-Host "  ~/.codex not found — skipping" -ForegroundColor Gray
}

# Initial empty memory/idea-box if missing
foreach ($f in @("MEMORY.md", "ECOSYSTEM_IDEA_BOX.md")) {
    $p = Join-Path $ClaudeHome $f
    if (-not (Test-Path $p)) {
        "# $($f -replace '\.md','')`n`n_Auto-managed. Add entries via natural-language requests to AI._" | Out-File -FilePath $p -Encoding utf8
    }
}

Write-Host ""
Write-Host "=== Install complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Review ~/.claude/CLAUDE.md and personalize the ecosystem table"
Write-Host "  2. Review ~/.claude/settings.json hooks"
Write-Host "  3. (Optional) Set up your private context repo for AI tool sharing"
Write-Host "  4. Run: python ~/.claude/scripts/plan_catalog.py to generate PLANS.md"
Write-Host "  5. Run: python ~/.claude/scripts/vision_catalog.py to generate VISIONS.md"
