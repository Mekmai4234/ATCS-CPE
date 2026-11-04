# Server deployment

Production HTTPS deployment of Video Buddy on a single Linux server (Ubuntu 24.04).
It layers `compose.server.yaml` over `07_testing_deployment/compose.transcript.yaml`;
Caddy obtains a Let's Encrypt certificate for `PUBLIC_HOST` automatically.

| File | Purpose |
|---|---|
| `deploy.sh` | Build + start, or `status` / `logs` / `down` (never removes volumes) |
| `compose.server.yaml` | Production overlay: auth on, secure cookies, ports 80/443, Caddy |
| `Caddyfile.server` | Static web app + `/api` reverse proxy, security headers |
| `setup-warp.sh` | One-time Cloudflare WARP caption proxy (see below) |

## Prerequisites

- DNS A record for `PUBLIC_HOST` points to this server (`deploy.sh` checks it).
- `MiniProject/.env.local` (git-ignored) contains at least `PUBLIC_HOST`,
  `GEMINI_API_KEY`, `GOOGLE_CLIENT_ID`.
- Gemini Free Tier policy at `runtime/free-tier-20261026/gemini-free-policy.json`
  (renewal: `07_testing_deployment/LOCAL_STACK.md`).

## Deploy / update

```bash
git pull
./deploy/deploy.sh          # build + start
./deploy/deploy.sh status   # containers and health
```

## Caption proxy (YouTube IP block)

YouTube blocks caption requests from most cloud/VPS IPs, so imports fail with
`youtube_access_blocked` ("YouTube จำกัดการเข้าถึงคลิปจากระบบนี้"). Caption requests
(only those) go through a local Cloudflare WARP proxy:

1. Once per server, as root: `bash deploy/setup-warp.sh`
   - installs `cloudflare-warp` from Cloudflare's apt repo, plus `socat`
   - sets WARP to **proxy mode before connecting**: host routing, SSH and the
     website keep the server IP
   - adds `warp-docker-bridge.service`, exposing the proxy to containers only at
     `172.17.0.1:40001` (docker0, not the internet); both services start on boot
   - prints `warp=on` for SOCKS5 and HTTP when it works
2. Add to `.env.local`: `YOUTUBE_PROXY_URL=http://172.17.0.1:40001`
3. `./deploy/deploy.sh`

Troubleshooting: `warp-cli status`, `systemctl status warp-svc warp-docker-bridge`.
If both are healthy and imports are still blocked, YouTube is blocking WARP's IPs
too: point `YOUTUBE_PROXY_URL` at a residential/home proxy, or use
`YOUTUBE_WEBSHARE_USERNAME` / `YOUTUBE_WEBSHARE_PASSWORD`
(see `03_video_ingestion/README.md`). No code change is needed.
