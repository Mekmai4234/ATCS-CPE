#!/usr/bin/env bash
# Reconnects Cloudflare WARP (new exit IP) when the worker logs a YouTube HTTP 429.
# Runs on the HOST every 30 s via systemd; the worker container gets no extra rights.
#   bash deploy/warp-watchdog.sh install    # once, as root
#   bash deploy/warp-watchdog.sh uninstall
#   bash deploy/warp-watchdog.sh            # one check (what the timer runs)
set -euo pipefail

STATE_DIR=/var/lib/warp-watchdog
COOLDOWN_SECONDS=${WARP_WATCHDOG_COOLDOWN:-300}
PATTERN='error_code=youtube_rate_limited'
WARP="warp-cli --accept-tos"

install_units() {
  local script
  script=$(readlink -f "$0")
  cat > /etc/systemd/system/warp-watchdog.service <<EOF
[Unit]
Description=Reconnect WARP when YouTube rate-limits caption requests
After=docker.service warp-svc.service

[Service]
Type=oneshot
ExecStart=/usr/bin/env bash $script
EOF
  cat > /etc/systemd/system/warp-watchdog.timer <<'EOF'
[Unit]
Description=Check worker logs for YouTube 429 every 30 seconds

[Timer]
OnBootSec=60
OnUnitActiveSec=30
AccuracySec=1

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now warp-watchdog.timer
  echo "Installed. Logs: journalctl -u warp-watchdog -f"
}

uninstall_units() {
  systemctl disable --now warp-watchdog.timer 2>/dev/null || true
  rm -f /etc/systemd/system/warp-watchdog.{service,timer}
  systemctl daemon-reload
  echo "Removed."
}

warp_on() {
  curl -s --max-time 15 -x http://127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace \
    | grep -q '^warp=on'
}

reconnect() {
  $WARP disconnect >/dev/null
  $WARP connect >/dev/null
  for _ in $(seq 1 20); do
    $WARP status | grep -q 'Connected' && break
    sleep 1
  done
  if warp_on; then
    echo "reconnected: warp=on"
  else
    echo "WARNING: reconnect finished but warp is not on; check: $WARP status" >&2
  fi
}

check() {
  mkdir -p "$STATE_DIR"
  exec 9>"$STATE_DIR/lock"
  flock -n 9 || exit 0 # previous check still running

  local now since container hits last
  now=$(date +%s)
  since=$(cat "$STATE_DIR/last-check" 2>/dev/null || echo $((now - 30)))
  echo "$now" > "$STATE_DIR/last-check"

  container=$(docker ps -q --filter label=com.docker.compose.service=worker | head -n1)
  [ -n "$container" ] || exit 0

  hits=$(docker logs --since "$since" --until "$now" "$container" 2>&1 | grep -c "$PATTERN" || true)
  [ "$hits" -gt 0 ] || exit 0

  last=$(cat "$STATE_DIR/last-reconnect" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$COOLDOWN_SECONDS" ]; then
    echo "429 x$hits, in cooldown ($((now - last))s since last reconnect); skipping"
    exit 0
  fi

  echo "429 x$hits in worker logs; reconnecting WARP for a new exit IP"
  echo "$now" > "$STATE_DIR/last-reconnect"
  reconnect
}

case "${1:-check}" in
  install) install_units ;;
  uninstall) uninstall_units ;;
  check) check ;;
  *) echo "usage: $0 [install|uninstall|check]" >&2; exit 2 ;;
esac
