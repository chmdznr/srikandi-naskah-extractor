#!/usr/bin/env bash
# Redeploy after a code change: pull latest (if a git repo), re-sync deps, and
# restart ONLY api + worker. Redis stays up; ollama keeps the model in VRAM.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
export PATH="$HOME/.local/bin:$PATH"
CTL="supervisorctl -c $APP_DIR/deploy/supervisord.conf"

if [ -d .git ]; then
  echo "[redeploy] git pull..."
  git pull --ff-only
else
  echo "[redeploy] not a git repo here — assuming code was rsync'd. Skipping pull."
fi

echo "[redeploy] uv sync --no-dev..."
uv sync --no-dev

echo "[redeploy] restarting api + worker..."
$CTL restart api worker
$CTL status
