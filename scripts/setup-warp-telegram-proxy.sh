#!/usr/bin/env bash
# Local SOCKS5 via Cloudflare WARP on the SkySender (RU) host.
# Prefer a dedicated EU VPS (setup-telegram-proxy.sh) when available.
# Usage: bash setup-warp-telegram-proxy.sh
set -euo pipefail

PORT="${WARP_PROXY_PORT:-40000}"

if ! command -v warp-cli >/dev/null 2>&1; then
  curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
  . /etc/os-release
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ ${VERSION_CODENAME} main" \
    > /etc/apt/sources.list.d/cloudflare-client.list
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq cloudflare-warp
fi

systemctl enable --now warp-svc
sleep 2
warp-cli --accept-tos registration new 2>/dev/null || true
warp-cli --accept-tos mode proxy
warp-cli --accept-tos proxy port "${PORT}"
warp-cli --accept-tos connect
sleep 2
warp-cli --accept-tos status

echo
echo "TELEGRAM_PROXY=socks5://127.0.0.1:${PORT}"
echo "Write this to backend/.env and restart order-elite."
