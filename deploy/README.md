# Deploy kit — RunPod (container) one-command bring-up

Brings up the whole extractor stack inside a single RunPod GPU pod and exposes a
stable HTTPS endpoint for the FE on another server.

```
start.sh ── installs deps + pulls model, then exec's ──▶ supervisord
                                                          ├─ redis
                                                          ├─ ollama   (qwen2.5:7b)
                                                          ├─ api      (uvicorn :8000)
                                                          ├─ worker   (rq)
                                                          └─ cloudflared (stable HTTPS)
```

## 1. First-time bring-up (SSH into the pod)

```bash
# from the repo root, inside tmux/screen (start.sh stays in the foreground):
cp deploy/.env.example deploy/.env      # then edit: set API_KEY (openssl rand -hex 32)
set -a; . deploy/.env; set +a
bash deploy/start.sh
```

`start.sh` is idempotent — re-run it any time. It installs redis/supervisor/uv/
ollama/cloudflared only if missing, pulls the model only if absent, then launches
the supervised process tree.

## 2. Exposing the API to the FE — two options

> **This PoC uses Option B (RunPod proxy)** — `ENABLE_TUNNEL=false` and port `8000`
> exposed on the pod. Option A (cloudflared) stays available for a stable hostname later.

**A. Cloudflared (stable across pod recreate).**
- Quick test: leave `CLOUDFLARE_TUNNEL_TOKEN` empty → a random
  `https://<random>.trycloudflare.com` URL is printed to
  `/var/log/extractor/cloudflared.log`. Zero setup; URL changes on restart.
- Stable: in **Cloudflare Zero Trust → Networks → Tunnels**, create a Named Tunnel,
  route a public hostname (e.g. `extractor-poc.example`) to `http://localhost:8000`,
  paste its token into `CLOUDFLARE_TUNNEL_TOKEN`. The FE then points at that
  hostname permanently, regardless of which pod is behind it.

**B. RunPod HTTP proxy (no cloudflared).** Set `ENABLE_TUNNEL=false`, and in the pod
config add `8000` to **Expose HTTP Ports** → `https://<podID>-8000.proxy.runpod.net`.
Simplest, but the URL changes every pod recreate.

## 3. How the FE calls it

```
POST  https://<endpoint>/jobs       header  X-API-Key: <API_KEY>   (multipart file → {id})
GET   https://<endpoint>/jobs/{id}  header  X-API-Key: <API_KEY>   (poll until status=finished)
GET   https://<endpoint>/health     (open, no key — for healthchecks)
```

The async/polling shape keeps every HTTP call short, so it stays under RunPod's
100s proxy timeout even on long documents.

## 4. Redeploy after a code change

```bash
bash deploy/redeploy.sh        # git pull (if repo) + uv sync + restart api & worker only
```

Redis and the in-VRAM model are untouched, so this is a few seconds.

## 5. Operate

```bash
supervisorctl -c deploy/supervisord.conf status
supervisorctl -c deploy/supervisord.conf restart api worker
tail -f /var/log/extractor/worker.log
```

## Notes / gotchas
- **Persist the model:** set `OLLAMA_MODELS` to a path on a RunPod **network volume**
  (often `/workspace/...`) so the 4.7GB pull survives pod recreate.
- **Auth:** unset `API_KEY` = auth disabled (start.sh warns loudly). Always set it
  before exposing publicly.
- **Don't expose Ollama:** only port 8000 (the API) faces the tunnel/proxy. Never
  publish 11434.
- **Container, not VM:** GPU is already passed through (no `nvidia-container-toolkit`
  needed); `docker-compose.gpu.yml` is for the VM path (Vultr/Cudo/Biznet) instead.
