#!/usr/bin/env bash
set -euo pipefail
set -a; source .env; set +a

for k in TAVILY_API_KEY DEEPSEEK_API_KEY TUSHARE_TOKEN; do
  v=${!k-}
  [ -n "$v" ] && [ ${#v} -ge 20 ] || { echo "Missing/short $k"; exit 1; }
done

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
env | grep -E '^(TAVILY_API_KEY|DEEPSEEK_API_KEY|TUSHARE_TOKEN)='
env | grep -Ei 'proxy' || echo "Proxy cleared"
