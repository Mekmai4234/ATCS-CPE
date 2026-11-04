#!/usr/bin/env bash
# Cloudflare WARP in LOCAL PROXY mode only: host routing/SSH/website traffic are untouched.
# Only clients that explicitly use 127.0.0.1:40000 go through WARP.
set -euo pipefail

# 1) Official Cloudflare apt repo + packages
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
  | gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ noble main" \
  > /etc/apt/sources.list.d/cloudflare-client.list
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq cloudflare-warp socat

# 2) Proxy mode MUST be set before connect (default mode would tunnel all traffic, incl. SSH)
warp-cli --accept-tos registration new || true
warp-cli --accept-tos mode proxy
warp-cli --accept-tos proxy port 40000
warp-cli --accept-tos connect
sleep 5
warp-cli --accept-tos status

# 3) Expose the proxy to Docker containers only (docker0 address, not the internet)
cat > /etc/systemd/system/warp-docker-bridge.service <<'EOF'
[Unit]
Description=Expose local WARP proxy to Docker containers on 172.17.0.1:40001
After=docker.service warp-svc.service
Requires=docker.service

[Service]
ExecStart=/usr/bin/socat TCP-LISTEN:40001,bind=172.17.0.1,fork,reuseaddr TCP:127.0.0.1:40000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now warp-docker-bridge.service

# 4) Checks: warp=on means traffic exits via Cloudflare
echo "--- SOCKS5:"; curl -s --max-time 15 -x socks5h://127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace | grep -E '^(ip|warp)=' || echo "socks failed"
echo "--- HTTP CONNECT:"; curl -s --max-time 15 -x http://127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace | grep -E '^(ip|warp)=' || echo "http failed"
