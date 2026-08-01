#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-62.217.183.111}"
APP_DIR=/opt/order-elite
REPO=https://github.com/trmaxim92/skesender.git

export DEBIAN_FRONTEND=noninteractive

echo "==> packages"
apt-get update -qq
apt-get install -y -qq nginx postgresql postgresql-contrib python3-venv python3-pip curl ca-certificates gnupg
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -qq nodejs
fi

echo "==> clone from GitHub"
if [[ -d "$APP_DIR/.git" ]]; then
  cd "$APP_DIR"
  git fetch --depth 1 origin main
  git reset --hard origin/main
else
  rm -rf "$APP_DIR"
  git clone --depth 1 "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"
echo "COMMIT=$(git rev-parse --short HEAD)"

SECRET=$(openssl rand -hex 32)
DB_PASS=$(openssl rand -hex 16)

echo "==> postgres"
systemctl enable --now postgresql
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'orderelite') THEN
    CREATE ROLE orderelite LOGIN PASSWORD '${DB_PASS}';
  ELSE
    ALTER ROLE orderelite WITH PASSWORD '${DB_PASS}';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE orderelite OWNER orderelite'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'orderelite')\gexec
GRANT ALL PRIVILEGES ON DATABASE orderelite TO orderelite;
\c orderelite
GRANT ALL ON SCHEMA public TO orderelite;
SQL

echo "==> backend .env"
cat > "$APP_DIR/backend/.env" <<EOF
APP_NAME=Order Elite
DEBUG=false
SECRET_KEY=${SECRET}
DATABASE_URL=postgresql+asyncpg://orderelite:${DB_PASS}@127.0.0.1:5432/orderelite
ACCESS_TOKEN_EXPIRE_MINUTES=10080
CORS_ORIGINS=http://${HOST},http://127.0.0.1
SEED_ADMIN_EMAIL=admin@order-elite.local
SEED_ADMIN_PASSWORD=ChangeMeNow1!
SEED_ADMIN_NAME=Admin
SEED_MAX_BOT_TOKEN=
MAX_API_BASE=https://platform-api2.max.ru
MAX_API_VERIFY_SSL=false
MAX_PERSONAL_DATA_DIR=./data/max_personal
TELEGRAM_API_ID=26368063
TELEGRAM_API_HASH=e16c6d63c89cf3a8bc15d6f6b118e55b
TELEGRAM_USER_DATA_DIR=./data/telegram_user
TELEGRAM_PROXY=
EOF
chmod 600 "$APP_DIR/backend/.env"
umask 077
printf '%s\n' "$DB_PASS" > /root/order-elite-db-pass.txt

echo "==> python venv"
cd "$APP_DIR/backend"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt
mkdir -p data/max_personal data/telegram_user data/attachments

echo "==> frontend build"
cd "$APP_DIR/frontend"
npm install
npm run build

echo "==> systemd"
cat > /etc/systemd/system/order-elite.service <<'UNIT'
[Unit]
Description=Order Elite API
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

echo "==> nginx"
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

sleep 2
curl -sf http://127.0.0.1/health || curl -sf http://127.0.0.1:8000/health
echo
systemctl --no-pager --full status order-elite | head -20
echo "DEPLOY_OK http://${HOST}/"
echo "Admin: admin@order-elite.local / ChangeMeNow1!"
