# Installs the skill into the three places the harnesses read, backing up old copies first.
#   .\install.ps1              install for real
#   .\install.ps1 -DryRun      show what would happen
#   .\install.ps1 -HomeDir X   use X instead of %USERPROFILE% (for testing)
param([switch]$DryRun, [string]$HomeDir = $env:USERPROFILE)
$ErrorActionPreference = "Stop"
$src = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not (Test-Path (Join-Path $src "SKILL.md"))) { throw "SKILL.md not found in $src" }
$name = "agent-orchestration"
$targets = @(
  (Join-Path $HomeDir ".claude\skills\$name"),          # Claude Code
  (Join-Path $HomeDir ".agents\skills\$name"),          # Codex CLI, Windsurf/Devin, portable location
  (Join-Path $HomeDir ".gemini\config\skills\$name")    # Antigravity CLI (agy)
)
$backupRoot = Join-Path $HomeDir ".agent-orchestration-backups"
$state = Join-Path $HomeDir ".agent-orchestration"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Warning "python was not found on PATH. agent_run.py, route.py and discover.py need Python 3 (stdlib only)."
}

foreach ($t in $targets) {
  if (Test-Path $t) {
    $tag = ($t.Substring($HomeDir.Length) -replace '[^A-Za-z0-9]+','_').Trim('_')
    $b = Join-Path $backupRoot "$tag-$stamp"
    Write-Host "backup  $t -> $b"
    if (-not $DryRun) {
      New-Item -ItemType Directory -Force $backupRoot | Out-Null
      Copy-Item $t $b -Recurse -Force
    }
  }
  Write-Host "install $t"
  if (-not $DryRun) {
    New-Item -ItemType Directory -Force $t | Out-Null
    # Use /MIR so even if the target directory is a shell's current working directory on Windows, contents sync cleanly
    robocopy $src $t /MIR /XD install tests __pycache__ .orch .git /XF *.pyc .gitignore LICENSE /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) for $t" }
  }
}
Write-Host "state   $state"
if (-not $DryRun) { New-Item -ItemType Directory -Force $state | Out-Null }
Write-Host "Done. Restart Claude Code, Codex and agy so they reload the skill."
$global:LASTEXITCODE = 0
