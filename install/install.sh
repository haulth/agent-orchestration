#!/usr/bin/env bash
# Installs the skill into the three places the harnesses read, backing up old copies first.
#   ./install.sh [--dry-run] [--home DIR]
set -euo pipefail
DRY=0; HOME_DIR="$HOME"
while [ $# -gt 0 ]; do case "$1" in --dry-run) DRY=1;; --home) HOME_DIR="$2"; shift;; *) echo "unknown arg $1"; exit 2;; esac; shift; done
SRC="$(cd "$(dirname "$0")/.." && pwd)"; NAME=agent-orchestration
[ -f "$SRC/SKILL.md" ] || { echo "SKILL.md not found in $SRC"; exit 1; }
STAMP="$(date +%Y%m%d-%H%M%S)"; BK="$HOME_DIR/.agent-orchestration-backups"
command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || echo "warning: python not found; the scripts need Python 3 (stdlib only)"
for T in "$HOME_DIR/.claude/skills/$NAME" "$HOME_DIR/.agents/skills/$NAME" "$HOME_DIR/.gemini/config/skills/$NAME"; do
  if [ -e "$T" ]; then
    B="$BK/$(echo "${T#$HOME_DIR}" | sed 's/[^A-Za-z0-9]\+/_/g; s/^_//; s/_$//')-$STAMP"; echo "backup  $T -> $B"
    [ $DRY = 1 ] || { mkdir -p "$BK"; cp -R "$T" "$B"; rm -rf "$T"; }
  fi
  echo "install $T"
  if [ $DRY = 0 ]; then
    mkdir -p "$T"
    (cd "$SRC" && tar --exclude=./install --exclude=./tests --exclude=__pycache__ --exclude=.orch --exclude=.git -cf - .) | (cd "$T" && tar -xf -)
  fi
done
[ $DRY = 1 ] || mkdir -p "$HOME_DIR/.agent-orchestration"
echo "Done. Restart Claude Code, Codex and agy so they reload the skill."
