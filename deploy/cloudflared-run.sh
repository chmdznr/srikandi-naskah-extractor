#!/usr/bin/env bash
# Picks the cloudflared mode from the environment:
#   CLOUDFLARE_TUNNEL_TOKEN set -> NAMED tunnel: stable hostname routed via the
#                                  Cloudflare Zero Trust dashboard (ingress ->
#                                  http://localhost:8000). Survives pod recreate.
#   token unset                 -> QUICK tunnel: a random https://*.trycloudflare.com
#                                  URL printed to this log. Zero setup, but the URL
#                                  changes every restart.
#
# Set DRY_RUN=1 to print the chosen command instead of executing it (for testing).
set -euo pipefail

PORT="${API_PORT:-8000}"
RUN=(exec)
[ -n "${DRY_RUN:-}" ] && RUN=(echo "DRYRUN:")

if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
  echo "[cloudflared] NAMED tunnel — stable hostname (configured in CF Zero Trust)"
  "${RUN[@]}" cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN"
else
  echo "[cloudflared] QUICK tunnel — watch this log for the https://<random>.trycloudflare.com URL"
  "${RUN[@]}" cloudflared tunnel --no-autoupdate --url "http://localhost:${PORT}"
fi
