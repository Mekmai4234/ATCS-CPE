#!/usr/bin/env bash
# Build and start Video Buddy on this server with HTTPS on PUBLIC_HOST.
#   ./deploy/deploy.sh          build + start (or update after git pull)
#   ./deploy/deploy.sh status   show containers and health
#   ./deploy/deploy.sh logs     follow logs
#   ./deploy/deploy.sh down     stop (data volume is kept)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ENV_FILE="$ROOT/.env.local"
POLICY="$ROOT/runtime/free-tier-20261026/gemini-free-policy.json"
DC=(docker compose --env-file "$ENV_FILE"
    -f 07_testing_deployment/compose.transcript.yaml
    -f deploy/compose.server.yaml)

case "${1:-up}" in
  status) "${DC[@]}" ps; exit ;;
  logs)   "${DC[@]}" logs -f --tail 100; exit ;;
  down)   "${DC[@]}" down; exit ;;   # never add -v
  up) ;;
  *) echo "usage: $0 [up|status|logs|down]"; exit 2 ;;
esac

fail() { echo "ERROR: $*" >&2; exit 1; }
[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE"
val() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"'"'"; }

for k in PUBLIC_HOST GEMINI_API_KEY GOOGLE_CLIENT_ID; do
  [ -n "$(val "$k")" ] || fail "$k is empty in .env.local"
done
HOST="$(val PUBLIC_HOST)"
[ -f "$POLICY" ] || fail "missing Gemini policy file: $POLICY"
chmod 644 "$POLICY"; chmod 755 "$(dirname "$POLICY")"

SERVER_IP="$(curl -s -4 --max-time 5 ifconfig.me || true)"
DNS_IP="$(getent ahostsv4 "$HOST" | awk 'NR==1{print $1}' || true)"
if [ "$DNS_IP" != "$SERVER_IP" ]; then
  fail "DNS for $HOST points to '${DNS_IP:-nothing}', expected $SERVER_IP. Fix the A record first (HTTPS certificate issuance needs it)."
fi

docker volume inspect video-buddy_state >/dev/null 2>&1 || docker volume create video-buddy_state
"${DC[@]}" build
"${DC[@]}" up -d --remove-orphans
"${DC[@]}" ps
echo "Deployed: https://$HOST"
