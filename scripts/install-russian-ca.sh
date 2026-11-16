#!/usr/bin/env bash
# Install Минцифры (Russian Trusted) CA into the system trust store.
# Required for MAX Bot API: https://platform-api2.max.ru
set -euo pipefail

DEST=/usr/local/share/ca-certificates/russian
mkdir -p "$DEST"

curl -fsSL -o "$DEST/russian_trusted_root_ca.crt" \
  https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
curl -fsSL -o "$DEST/russian_trusted_sub_ca.crt" \
  https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt

update-ca-certificates

echo "Installed Russian Trusted CA. OpenSSL check:"
openssl s_client -connect platform-api2.max.ru:443 -servername platform-api2.max.ru </dev/null 2>/dev/null \
  | grep -F "Verify return code" || true
