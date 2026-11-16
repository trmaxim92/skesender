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

echo "==> clone from GitHub (owner deploy if present)"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
if id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR"
else
  DEPLOY_USER=root
  mkdir -p "$APP_DIR"
fi
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
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

echo "==> Russian Trusted CA (MAX platform-api2 / Минцифры)"
bash "$APP_DIR/scripts/install-russian-ca.sh" || true

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
APP_NAME=SkySender
DEBUG=false
SECRET_KEY=${SECRET}
DATABASE_URL=postgresql+asyncpg://orderelite:${DB_PASS}@127.0.0.1:5432/orderelite
ACCESS_TOKEN_EXPIRE_MINUTES=1440
CORS_ORIGINS=http://${HOST},http://127.0.0.1
SEED_ADMIN_EMAIL=admin@order-elite.local
SEED_ADMIN_PASSWORD=ChangeMeNow1!
SEED_ADMIN_NAME=Admin
SEED_MAX_BOT_TOKEN=
MAX_API_BASE=https://platform-api2.max.ru
MAX_API_VERIFY_SSL=true
MAX_PERSONAL_DATA_DIR=./data/max_personal
TELEGRAM_API_ID=26368063
TELEGRAM_API_HASH=e16c6d63c89cf3a8bc15d6f6b118e55b
TELEGRAM_USER_DATA_DIR=./data/telegram_user
# socks5://user:pass@EU_HOST:1080  or  socks5://127.0.0.1:40000 (WARP)
TELEGRAM_PROXY=
EOF
chmod 600 "$APP_DIR/backend/.env"
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/backend/.env"
umask 077
PASS_FILE="/home/${DEPLOY_USER}/order-elite-db-pass.txt"
if [[ "$DEPLOY_USER" == "root" ]]; then
  PASS_FILE=/root/order-elite-db-pass.txt
fi
printf '%s\n' "$DB_PASS" > "$PASS_FILE"
chmod 600 "$PASS_FILE"
chown "$DEPLOY_USER:$DEPLOY_USER" "$PASS_FILE"

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

echo "==> ownership for runtime user"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

echo "==> systemd (User=${DEPLOY_USER})"
cp "$APP_DIR/scripts/order-elite.service" /etc/systemd/system/order-elite.service
if [[ "$DEPLOY_USER" != "deploy" ]]; then
  sed -i "s/^User=deploy$/User=${DEPLOY_USER}/; s/^Group=deploy$/Group=${DEPLOY_USER}/" \
    /etc/systemd/system/order-elite.service
fi

echo "==> nginx"
cp "$APP_DIR/scripts/nginx-order-elite.http.conf" /etc/nginx/sites-available/order-elite

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
bash "$APP_DIR/scripts/wait-max-personal.sh" || true
systemctl --no-pager --full status order-elite | head -20
echo "DEPLOY_OK http://${HOST}/"
echo "Admin: admin@order-elite.local / ChangeMeNow1!"
echo "Runtime user: ${DEPLOY_USER}"
