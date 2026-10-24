#!/usr/bin/env bash
# Installs the skill into the four places the harnesses read, backing up old copies first.
#   ./install.sh [--dry-run] [--home DIR]
set -euo pipefail
DRY=0; HOME_DIR="${HOME%/}"
while [ $# -gt 0 ]; do case "$1" in --dry-run) DRY=1;; --home) HOME_DIR="${2%/}"; shift;; *) echo "unknown arg $1"; exit 2;; esac; shift; done
SRC="$(cd "$(dirname "$0")/.." && pwd)"; NAME=agent-orchestration
[ -f "$SRC/SKILL.md" ] || { echo "SKILL.md not found in $SRC"; exit 1; }
STAMP="$(date +%Y%m%d-%H%M%S)"; BK="$HOME_DIR/.agent-orchestration-backups"
PY=""
for C in python3 python; do
  if command -v "$C" >/dev/null 2>&1 && "$C" -c "import sys; assert sys.version_info >= (3,8)" >/dev/null 2>&1; then
    PY="$C"; break
  fi
done
[ -n "$PY" ] || echo "warning: Python >= 3.8 not found; the scripts need Python 3 (stdlib only)"
for T in "$HOME_DIR/.claude/skills/$NAME" "$HOME_DIR/.agents/skills/$NAME" "$HOME_DIR/.codex/skills/$NAME" "$HOME_DIR/.gemini/config/skills/$NAME"; do
  if [ -e "$T" ]; then
    TAG="$(echo "${T#$HOME_DIR}" | tr -c 'A-Za-z0-9' '_' | sed -E 's/^_+//; s/_+$//')"
    B="$BK/$TAG-$STAMP"; echo "backup  $T -> $B"
    [ $DRY = 1 ] || { mkdir -p "$BK"; cp -R "$T" "$B"; rm -rf "$T"; }
  fi
  echo "install $T"
  if [ $DRY = 0 ]; then
    mkdir -p "$T"
    (cd "$SRC" && tar --exclude='install' --exclude='tests' --exclude='bin' --exclude='node_modules' --exclude='__pycache__' --exclude='.orch' --exclude='.sandbox-skills' --exclude='.git' --exclude='package.json' --exclude='package-lock.json' --exclude='LICENSE' --exclude='.gitignore' --exclude='*.pyc' -cf - .) | (cd "$T" && tar -xf -)
  fi
done
if [ $DRY = 0 ]; then
  mkdir -p "$HOME_DIR/.agent-orchestration"
  if [ -n "$PY" ] && [ -f "$HOME_DIR/.agents/skills/$NAME/scripts/discover.py" ]; then
    "$PY" "$HOME_DIR/.agents/skills/$NAME/scripts/discover.py" --quick >/dev/null 2>&1 || true
  fi
fi
echo "Done. Restart Claude Code, Codex and agy so they reload the skill."
