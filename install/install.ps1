# dotclaude-ecosystem installer (Windows)
# Idempotent: safe to re-run.
#
#   .\install.ps1           install / refresh every managed artifact
#   .\install.ps1 -Check    compare installed copies against the repo and exit
#                           non-zero on drift. Writes nothing.
#
# One manifest drives both modes, so -Check can never fall out of step with
# what install actually copies.

param([switch]$Check)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ClaudeHome = Join-Path $env:USERPROFILE ".claude"
$CodexHome = Join-Path $env:USERPROFILE ".codex"
$GeminiHome = Join-Path $env:USERPROFILE ".gemini\config"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

# ---------------------------------------------------------------- manifest
# Skills read by Claude Code.
$BundledSkills = @("master-agent", "executor", "distill-repo", "ponytail-on-demand", "run-model-team", "coderpxC")
# Skills read by the Codex CLI.
$CodexSkills = @("master-agent", "executor", "ponytail-on-demand", "run-model-team", "coderpxG")
# Skills read by the Antigravity (agy) CLI. Separate root from ~/.claude/skills.
$AgySkills = @("fwa", "coderpxA")
# Workflow commands. One source, two runtimes: Claude reads ~/.claude/commands,
# Codex reads ~/.codex/prompts. Before this manifest existed they had no source
# at all and drifted silently.
$Commands = @("fwf", "fwp")
# Skill directories retired by a rename. Kept as .bak instead of deleted so a
# rollback is a move, not a restore.
$RetiredSkillDirs = @(
    (Join-Path $ClaudeHome "skills\coderpx"),
    (Join-Path $GeminiHome "skills\coderpx")
)

function Get-ManifestPairs {
    $pairs = @()
    foreach ($skill in $BundledSkills) {
        $pairs += @{ Src = (Join-Path $RepoRoot "skills\$skill"); Dst = (Join-Path $ClaudeHome "skills\$skill"); Kind = "dir"; Label = "claude/skills/$skill" }
    }
    if (Test-Path $CodexHome) {
        foreach ($skill in $CodexSkills) {
            $pairs += @{ Src = (Join-Path $RepoRoot "skills\$skill"); Dst = (Join-Path $CodexHome "skills\$skill"); Kind = "dir"; Label = "codex/skills/$skill" }
        }
        foreach ($cmd in $Commands) {
            $pairs += @{ Src = (Join-Path $RepoRoot "commands\$cmd.md"); Dst = (Join-Path $CodexHome "prompts\$cmd.md"); Kind = "file"; Label = "codex/prompts/$cmd.md" }
        }
        $pairs += @{ Src = (Join-Path $RepoRoot "agy-skills\fwa\SKILL.md"); Dst = (Join-Path $CodexHome "prompts\fwa.md"); Kind = "file"; Label = "codex/prompts/fwa.md" }
    }
    if (Test-Path $GeminiHome) {
        foreach ($skill in $AgySkills) {
            $pairs += @{ Src = (Join-Path $RepoRoot "agy-skills\$skill"); Dst = (Join-Path $GeminiHome "skills\$skill"); Kind = "dir"; Label = "agy/skills/$skill" }
        }
    }
    foreach ($cmd in $Commands) {
        $pairs += @{ Src = (Join-Path $RepoRoot "commands\$cmd.md"); Dst = (Join-Path $ClaudeHome "commands\$cmd.md"); Kind = "file"; Label = "claude/commands/$cmd.md" }
    }
    return $pairs
}

# Build artifacts and our own backups are not drift. Without this filter the
# report is dominated by __pycache__ and .bak.<stamp> noise and nobody reads it.
function Test-IgnoredPath([string]$rel) {
    if ($rel -match '(^|\\)__pycache__(\\|$)') { return $true }
    if ($rel -match '\.pyc$') { return $true }
    if ($rel -match '\.bak\.\d') { return $true }
    if ($rel -match '\.retired\.\d') { return $true }
    if ($rel -match '(^|\\)\.git(\\|$)') { return $true }
    return $false
}

function Get-TreeHashes([string]$root) {
    $map = @{}
    if (-not (Test-Path $root)) { return $map }
    $item = Get-Item $root
    if (-not $item.PSIsContainer) {
        $map[""] = (Get-FileHash -Path $root -Algorithm SHA256).Hash
        return $map
    }
    foreach ($f in Get-ChildItem -Path $root -Recurse -File) {
        $rel = $f.FullName.Substring($item.FullName.Length).TrimStart('\')
        if (Test-IgnoredPath $rel) { continue }
        $map[$rel] = (Get-FileHash -Path $f.FullName -Algorithm SHA256).Hash
    }
    return $map
}

# ---------------------------------------------------------------- check mode
if ($Check) {
    Write-Host "=== dotclaude-ecosystem installer -- CHECK (no writes) ===" -ForegroundColor Cyan
    Write-Host "Source : $RepoRoot"
    Write-Host ""
    $drift = @()
    foreach ($pair in (Get-ManifestPairs)) {
        if (-not (Test-Path $pair.Src)) {
            $drift += "MISSING SOURCE  $($pair.Label)  ($($pair.Src))"
            continue
        }
        if (-not (Test-Path $pair.Dst)) {
            $drift += "NOT INSTALLED   $($pair.Label)"
            continue
        }
        $srcMap = Get-TreeHashes $pair.Src
        $dstMap = Get-TreeHashes $pair.Dst
        foreach ($key in $srcMap.Keys) {
            if (-not $dstMap.ContainsKey($key)) {
                $drift += "MISSING FILE    $($pair.Label)/$key"
            } elseif ($dstMap[$key] -ne $srcMap[$key]) {
                $drift += "DRIFT           $($pair.Label)/$key"
            }
        }
        foreach ($key in $dstMap.Keys) {
            if (-not $srcMap.ContainsKey($key)) {
                $drift += "EXTRA FILE      $($pair.Label)/$key"
            }
        }
    }
    foreach ($stale in $RetiredSkillDirs) {
        if (Test-Path $stale) { $drift += "RETIRED PRESENT $stale (run install to move it aside)" }
    }
    if ($drift.Count -eq 0) {
        Write-Host "No drift: every managed artifact matches the repo." -ForegroundColor Green
        exit 0
    }
    foreach ($d in $drift) { Write-Host "  $d" -ForegroundColor Red }
    Write-Host ""
    Write-Host "$($drift.Count) drift item(s). Re-run .\install.ps1 to refresh, or land the installed change in the repo." -ForegroundColor Yellow
    exit 1
}

# ---------------------------------------------------------------- install
Write-Host "=== dotclaude-ecosystem installer ===" -ForegroundColor Cyan
Write-Host "Source : $RepoRoot"
Write-Host "Target : $ClaudeHome"
Write-Host ""

# Backup existing
if (Test-Path $ClaudeHome) {
    $backup = "$ClaudeHome.bak.$Stamp"
    Write-Host "[1/7] Backup ~/.claude -> $backup" -ForegroundColor Yellow
    Copy-Item -Path $ClaudeHome -Destination $backup -Recurse -Force
} else {
    Write-Host "[1/7] No existing ~/.claude to back up" -ForegroundColor Green
    New-Item -ItemType Directory -Force -Path $ClaudeHome | Out-Null
}

# Scripts
Write-Host "[2/7] Copy scripts -> ~/.claude/scripts/" -ForegroundColor Cyan
$ScriptsSrc = Join-Path $RepoRoot "scripts"
$ScriptsDst = Join-Path $ClaudeHome "scripts"
New-Item -ItemType Directory -Force -Path $ScriptsDst | Out-Null
Copy-Item -Path "$ScriptsSrc\*.py" -Destination $ScriptsDst -Force

# Skills, commands and agy skills, all from the one manifest
Write-Host "[3/7] Copy skills and commands (manifest-driven)" -ForegroundColor Cyan
foreach ($pair in (Get-ManifestPairs)) {
    if (-not (Test-Path $pair.Src)) {
        Write-Host "  skip (no source): $($pair.Label)" -ForegroundColor Yellow
        continue
    }
    if ($pair.Kind -eq "dir") {
        if (Test-Path $pair.Dst) {
            Copy-Item -Path $pair.Dst -Destination "$($pair.Dst).bak.$Stamp" -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path $pair.Dst | Out-Null
        Copy-Item -Path "$($pair.Src)\*" -Destination $pair.Dst -Recurse -Force
    } else {
        $parent = Split-Path -Parent $pair.Dst
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        if (Test-Path $pair.Dst) {
            Copy-Item -Path $pair.Dst -Destination "$($pair.Dst).bak.$Stamp" -Force
        }
        Copy-Item -Path $pair.Src -Destination $pair.Dst -Force
    }
    Write-Host "  $($pair.Label)" -ForegroundColor Green
}

# Retire directories replaced by a rename. Moved aside, never deleted.
foreach ($stale in $RetiredSkillDirs) {
    if (Test-Path $stale) {
        Move-Item -Path $stale -Destination "$stale.retired.$Stamp" -Force
        Write-Host "  retired $stale -> $stale.retired.$Stamp" -ForegroundColor Yellow
    }
}

# settings.json -- wire the managed hook block (handler-granular merge, dry-run first)
Write-Host "[4/7] Wire managed hooks into ~/.claude/settings.json" -ForegroundColor Cyan
$HooksInstaller = Join-Path $RepoRoot "scripts\hooks_install.py"
& py $HooksInstaller install --checkout $RepoRoot            # dry-run diff
& py $HooksInstaller install --checkout $RepoRoot --apply    # merge managed block, foreign hooks preserved
Write-Host "  managed hook block wired (run: py $HooksInstaller doctor)" -ForegroundColor Green

# CLAUDE.md
Write-Host "[5/7] Install CLAUDE.md template" -ForegroundColor Cyan
$ClaudeMdTpl = Join-Path $RepoRoot "templates\CLAUDE.md.template"
$ClaudeMdDst = Join-Path $ClaudeHome "CLAUDE.md"
if (Test-Path $ClaudeMdDst) {
    Write-Host "  existing CLAUDE.md found -- leaving in place; template at $ClaudeMdDst.from-template" -ForegroundColor Yellow
    Copy-Item -Path $ClaudeMdTpl -Destination "$ClaudeMdDst.from-template" -Force
} else {
    Copy-Item -Path $ClaudeMdTpl -Destination $ClaudeMdDst -Force
    Write-Host "  installed fresh CLAUDE.md" -ForegroundColor Green
}

# Codex AGENTS.md (optional)
Write-Host "[6/7] Codex AGENTS.md (optional)" -ForegroundColor Cyan
if (Test-Path $CodexHome) {
    $AgentsTpl = Join-Path $RepoRoot "templates\AGENTS.md.template"
    $AgentsDst = Join-Path $CodexHome "AGENTS.md"
    if (Test-Path $AgentsDst) {
        Write-Host "  existing ~/.codex/AGENTS.md found -- appending Plan Lifecycle Hooks section if missing"
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
    Write-Host "  ~/.codex not found -- skipping" -ForegroundColor Gray
}

# Initial empty memory/idea-box if missing
Write-Host "[7/7] Seed memory / idea box if missing" -ForegroundColor Cyan
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
Write-Host "  6. Verify no drift: .\install\install.ps1 -Check"
