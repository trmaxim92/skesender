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

cat > /etc/systemd/system/order-elite.service <<'UNIT'
[Unit]
Description=SkySender API
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/order-elite/backend
Environment=PATH=/opt/order-elite/backend/.venv/bin:/usr/bin
ExecStart=/opt/order-elite/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/nginx/sites-available/order-elite <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    root /opt/order-elite/frontend/dist;
    index index.html;

    client_max_body_size 50m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINX

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
curl -sf -o /dev/null -w "UI:%{http_code}\n" http://127.0.0.1/
systemctl --no-pager --full status order-elite | sed -n "1,18p"
echo "DEPLOY_OK http://${HOST}/"