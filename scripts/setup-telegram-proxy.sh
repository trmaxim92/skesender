#!/usr/bin/env bash
# Install authenticated SOCKS5 (3proxy) for Telegram relay on a foreign VPS.
# Usage: bash setup-telegram-proxy.sh
# Then on SkySender RU host set:
#   TELEGRAM_PROXY=socks5://USER:PASS@THIS_HOST:1080
set -euo pipefail

PORT="${PROXY_PORT:-1080}"
USER_NAME="${PROXY_USER:-tgrelay}"
PASS_WORD="${PROXY_PASS:-}"
if [[ -z "$PASS_WORD" ]]; then
  PASS_WORD="$(openssl rand -base64 18 | tr -d '=+/' | cut -c1-20)"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq 3proxy || {
  echo "3proxy package missing; installing from source is out of scope — use Cloudflare WARP proxy mode on the app host instead."
  exit 1
}

install -d -m 0755 /etc/3proxy
cat > /etc/3proxy/3proxy.cfg <<EOF
nserver 1.1.1.1
nserver 8.8.8.8
nscache 65536
timeouts 1 5 30 60 180 1800 15 60
users ${USER_NAME}:CL:${PASS_WORD}
auth strong
allow ${USER_NAME}
socks -p${PORT}
EOF
chmod 600 /etc/3proxy/3proxy.cfg

cat > /etc/systemd/system/telegram-socks.service <<'UNIT'
[Unit]
Description=SkySender Telegram SOCKS5 relay (3proxy)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/3proxy /etc/3proxy/3proxy.cfg
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

# Open firewall if ufw is active
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q 'Status: active'; then
  ufw allow "${PORT}/tcp" || true
fi

systemctl daemon-reload
systemctl enable --now telegram-socks.service
systemctl --no-pager --full status telegram-socks.service | head -n 15

HOST_IP="$(curl -4 -fsS --connect-timeout 5 https://ifconfig.me || hostname -I | awk '{print $1}')"
echo
echo "TELEGRAM_PROXY=socks5://${USER_NAME}:${PASS_WORD}@${HOST_IP}:${PORT}"
echo "Save this URL in SkySender backend/.env and restart order-elite."
