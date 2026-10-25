# Installs the skill into the four places the harnesses read, backing up old copies first.
#   .\install.ps1              install for real
#   .\install.ps1 -DryRun      show what would happen
#   .\install.ps1 -HomeDir X   use X instead of %USERPROFILE% (for testing)
param([switch]$DryRun, [string]$HomeDir = $env:USERPROFILE)
$ErrorActionPreference = "Stop"
$HomeDir = $HomeDir.TrimEnd('\', '/')
$src = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not (Test-Path (Join-Path $src "SKILL.md"))) { throw "SKILL.md not found in $src" }
$name = "agent-orchestration"
$targets = @(
  (Join-Path $HomeDir ".claude\skills\$name"),          # Claude Code
  (Join-Path $HomeDir ".agents\skills\$name"),          # Codex CLI, Cursor, Windsurf, portable Agent Skills root
  (Join-Path $HomeDir ".codex\skills\$name"),           # Codex CLI legacy/native root
  (Join-Path $HomeDir ".gemini\config\skills\$name")    # Antigravity CLI (agy)
)
$backupRoot = Join-Path $HomeDir ".agent-orchestration-backups"
$state = Join-Path $HomeDir ".agent-orchestration"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

$pyCmd = $null
foreach ($cand in @("python", "py", "python3")) {
  if (Get-Command $cand -ErrorAction SilentlyContinue) {
    $argsCheck = if ($cand -eq "py") { @("-3", "-c", "import sys; assert sys.version_info >= (3,8)") } else { @("-c", "import sys; assert sys.version_info >= (3,8)") }
    & $cand @argsCheck 2>$null
    if ($LASTEXITCODE -eq 0) { $pyCmd = $cand; break }
  }
}
if (-not $pyCmd) {
  Write-Warning "Working Python >= 3.8 was not found on PATH. agent_run.py, route.py, anatomy.py and discover.py need Python 3 (stdlib only)."
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
    robocopy $src $t /MIR /XD tests node_modules __pycache__ .orch .sandbox-skills .git /XF *.pyc .gitignore package-lock.json /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) for $t" }
  }
}
Write-Host "state   $state"
if (-not $DryRun) {
  New-Item -ItemType Directory -Force $state | Out-Null
  if ($pyCmd) {
    $disc = Join-Path $targets[1] "scripts\discover.py"
    if (Test-Path $disc) {
      if ($pyCmd -eq "py") { & py -3 $disc --quick 2>$null | Out-Null }
      else { & $pyCmd $disc --quick 2>$null | Out-Null }
    }
  }
}
Write-Host "Done. Restart Claude Code, Codex and agy so they reload the skill."
$global:LASTEXITCODE = 0
