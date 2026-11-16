#!/usr/bin/env bash
set -euo pipefail
HOST=62.217.183.111
APP_DIR=/opt/order-elite

cd "$APP_DIR/frontend"
npm install
npm run build

cd "$APP_DIR/backend"
test -f .env
if [[ ! -x .venv/bin/uvicorn ]]; then
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q -U pip
  pip install -q -r requirements.txt
fi
mkdir -p data/max_personal data/telegram_user data/attachments

DEPLOY_USER="${DEPLOY_USER:-deploy}"
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  DEPLOY_USER=root
fi
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

cp "$APP_DIR/scripts/order-elite.service" /etc/systemd/system/order-elite.service
if [[ "$DEPLOY_USER" != "deploy" ]]; then
  sed -i "s/^User=deploy$/User=${DEPLOY_USER}/; s/^Group=deploy$/Group=${DEPLOY_USER}/" \
    /etc/systemd/system/order-elite.service
fi

cp "$APP_DIR/scripts/nginx-order-elite.http.conf" /etc/nginx/sites-available/order-elite

rm -f /etc/nginx/sites-enabled/default
ln -sfn /etc/nginx/sites-available/order-elite /etc/nginx/sites-enabled/order-elite
nginx -t
systemctl daemon-reload
systemctl enable --now order-elite
systemctl restart order-elite
systemctl reload nginx
sleep 3
curl -sf http://127.0.0.1/health
echo
bash "$APP_DIR/scripts/wait-max-personal.sh" || true
curl -sf -o /dev/null -w "UI:%{http_code}\n" http://127.0.0.1/
systemctl --no-pager --full status order-elite | sed -n "1,18p"
echo "DEPLOY_OK http://${HOST}/"
echo "Runtime user: ${DEPLOY_USER}"