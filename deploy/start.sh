#!/usr/bin/env bash
# RunPod / Linux GPU container bootstrap + launch for the Srikandi extractor PoC.
#
# Idempotent: safe to re-run. Installs any missing deps, pulls the model once,
# then hands off (foreground) to supervisord which keeps redis + ollama + api +
# worker (+ optional cloudflared tunnel) alive with auto-restart.
#
# Usage (after SSH into the pod, from the repo root):
#   export API_KEY="$(openssl rand -hex 32)"   # REQUIRED for a public deploy
#   # optional — stable hostname instead of a random trycloudflare URL:
#   export CLOUDFLARE_TUNNEL_TOKEN=...
#   bash deploy/start.sh
#
# Run it inside tmux/screen when driving via SSH, since it stays in the foreground.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
export APP_DIR

export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b-instruct-q4_K_M}"
export ENABLE_TUNNEL="${ENABLE_TUNNEL:-false}"   # RunPod proxy is the default endpoint; set true to use cloudflared
export ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-*}"
REDIS_DIR="${REDIS_DIR:-/var/lib/extractor-redis}"
export REDIS_DIR

log() { echo "[start] $*"; }

# --- 1. system packages -------------------------------------------------------
if ! command -v redis-server >/dev/null 2>&1 || ! command -v supervisord >/dev/null 2>&1; then
  log "installing system packages (redis-server, supervisor, curl, zstd)..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq redis-server supervisor curl ca-certificates zstd
fi
# zstd guard (separate + idempotent): the ollama installer hard-requires it for
# extraction. Checked unconditionally so a re-run on a pod that already has
# redis/supervisord (skipping the block above) still gets zstd.
if ! command -v zstd >/dev/null 2>&1; then
  log "installing zstd (required by the ollama installer)..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq zstd
fi
mkdir -p "$REDIS_DIR" /var/log/extractor

# --- 2. uv + python deps ------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  log "installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
log "syncing python deps (uv sync --no-dev)..."
uv sync --no-dev

# --- 3. ollama + model --------------------------------------------------------
if ! command -v ollama >/dev/null 2>&1; then
  log "installing ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi
# Bring ollama up briefly just to pull the model if it's missing; supervisord
# owns the long-lived ollama process afterwards.
log "checking model ${OLLAMA_MODEL}..."
nohup ollama serve >/tmp/ollama-bootstrap.log 2>&1 &
_OLLAMA_PID=$!
for _ in $(seq 1 30); do curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
if ! ollama list | grep -qF "$OLLAMA_MODEL"; then
  log "pulling ${OLLAMA_MODEL} (first time, ~4.7GB — mount a persistent volume at OLLAMA_MODELS to keep it)..."
  ollama pull "$OLLAMA_MODEL"
fi
kill "$_OLLAMA_PID" 2>/dev/null || true
wait "$_OLLAMA_PID" 2>/dev/null || true
sleep 1   # let :11434 free up before supervisord rebinds it

# --- 4. cloudflared (optional) ------------------------------------------------
if [ "$ENABLE_TUNNEL" = "true" ] && ! command -v cloudflared >/dev/null 2>&1; then
  log "installing cloudflared..."
  case "$(uname -m)" in
    x86_64) cfarch=amd64 ;;
    aarch64|arm64) cfarch=arm64 ;;
    *) cfarch=amd64 ;;
  esac
  curl -fsSL -o /usr/local/bin/cloudflared \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${cfarch}"
  chmod +x /usr/local/bin/cloudflared
fi

# --- 5. guardrail -------------------------------------------------------------
if [ -z "${API_KEY:-}" ]; then
  log "WARNING: API_KEY is not set — the public endpoint will be UNAUTHENTICATED."
fi

# --- 6. launch supervised process tree (foreground) ---------------------------
log "starting supervisord: redis, ollama, api, worker$([ "$ENABLE_TUNNEL" = "true" ] && echo ', cloudflared')"
exec supervisord -n -c "$APP_DIR/deploy/supervisord.conf"
