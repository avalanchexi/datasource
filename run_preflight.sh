#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# shellcheck disable=SC1091
source scripts/runtime_env.sh

PREFLIGHT_CONNECT_TIMEOUT="${PREFLIGHT_CONNECT_TIMEOUT:-10}"
PREFLIGHT_MAX_TIME="${PREFLIGHT_MAX_TIME:-15}"

for k in TAVILY_API_KEY DEEPSEEK_API_KEY TUSHARE_TOKEN; do
  v=${!k-}
  if [ -z "$v" ] || [ "${#v}" -lt 20 ]; then
    echo "Missing/short $k"
    exit 1
  fi
done

_url_host() {
  "$DATASOURCE_PYTHON" - "$1" <<'PY'
import sys
from urllib.parse import urlparse
parsed = urlparse(sys.argv[1])
print(parsed.hostname or parsed.netloc or parsed.path)
PY
}

_check_dns() {
  host="$1"
  if command -v getent >/dev/null 2>&1; then
    if getent hosts "$host" >/dev/null; then
      echo "[OK] DNS $host"
      return 0
    fi
  else
    if "$DATASOURCE_PYTHON" - "$host" <<'PY'
import socket
import sys
socket.getaddrinfo(sys.argv[1], 443)
PY
    then
      echo "[OK] DNS $host"
      return 0
    fi
  fi
  echo "[FAIL] DNS check failed: $host"
  return 1
}

_check_https() {
  url="$1"
  code="000"
  if command -v curl >/dev/null 2>&1; then
    if code="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout "$PREFLIGHT_CONNECT_TIMEOUT" --max-time "$PREFLIGHT_MAX_TIME" "$url")"; then
      :
    else
      code="000"
    fi
  else
    code="$("$DATASOURCE_PYTHON" - "$url" <<'PY'
import http.client
import ssl
import sys
from urllib.parse import urlparse

url = sys.argv[1]
parsed = urlparse(url)
try:
    conn = http.client.HTTPSConnection(parsed.netloc, timeout=8, context=ssl.create_default_context())
    conn.request("HEAD", parsed.path or "/")
    resp = conn.getresponse()
    print(resp.status)
except Exception:
    print("000")
PY
)"
  fi
  if [[ ! "$code" =~ ^[0-9][0-9][0-9]$ ]] || [ "$code" = "000" ]; then
    echo "[FAIL] HTTPS check failed: $url"
    return 1
  fi
  echo "[OK] HTTPS $url (HTTP $code)"
}

TAVILY_URL="https://api.tavily.com"
DEEPSEEK_URL="${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"
TUSHARE_URL="https://api.tushare.pro"

_check_dns "$(_url_host "$TAVILY_URL")"
_check_dns "$(_url_host "$DEEPSEEK_URL")"
_check_dns "$(_url_host "$TUSHARE_URL")"

_check_https "$TAVILY_URL"
_check_https "$DEEPSEEK_URL"
_check_https "$TUSHARE_URL"

for k in TAVILY_API_KEY DEEPSEEK_API_KEY TUSHARE_TOKEN; do
  echo "[OK] $k present (${#k} name chars)"
done
echo "[OK] Python: $DATASOURCE_PYTHON"
env | grep -Ei '^(http_proxy|https_proxy|HTTP_PROXY|HTTPS_PROXY)=' || echo "Proxy cleared"
