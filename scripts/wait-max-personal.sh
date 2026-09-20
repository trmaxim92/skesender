#!/usr/bin/env bash
# Wait until personal MAX channels with saved sessions are ready to send.
# Uses GET /health → max_personal (HTTP stays 200 while channels are still connecting).
set -euo pipefail

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
TIMEOUT_SEC="${TIMEOUT_SEC:-90}"
SLEEP_SEC="${SLEEP_SEC:-3}"

deadline=$((SECONDS + TIMEOUT_SEC))
last=""

echo "==> wait max_personal ready (timeout=${TIMEOUT_SEC}s) via ${HEALTH_URL}"

while (( SECONDS < deadline )); do
  if ! body="$(curl -sf --max-time 8 "$HEALTH_URL")"; then
    echo "  health unreachable, retry…"
    sleep "$SLEEP_SEC"
    continue
  fi
  last="$body"
  if printf '%s' "$body" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
mp = payload.get("max_personal") or {}
expected = int(mp.get("expected") or 0)
ready = int(mp.get("ready") or 0)
ok = bool(mp.get("ok"))
pending = mp.get("pending") or []
print(f"  max_personal ready={ready}/{expected} ok={ok}")
for row in pending[:8]:
    rid = row.get("id")
    name = row.get("name")
    db = row.get("db_status")
    rt = row.get("runtime")
    print(f"    pending id={rid} name={name!r} db={db} runtime={rt}")
raise SystemExit(0 if ok else 1)
'; then
    echo "MAX_PERSONAL_OK"
    exit 0
  fi
  sleep "$SLEEP_SEC"
done

echo "MAX_PERSONAL_TIMEOUT after ${TIMEOUT_SEC}s"
if [[ -n "$last" ]]; then
  echo "$last" | python3 -m json.tool 2>/dev/null || echo "$last"
fi
exit 1
