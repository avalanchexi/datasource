#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ $# -eq 0 ]; then
  echo "Usage: bash run_clean.sh <command> [args...]"
  echo "Example: bash run_clean.sh python scripts/stage2_unified_enhancer.py --help"
  exit 1
fi

# shellcheck disable=SC1091
source scripts/runtime_env.sh

if [ "${1:-}" = "python" ]; then
  set -- "$DATASOURCE_PYTHON" "${@:2}"
fi

exec env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  PYTHONPATH="$PYTHONPATH" "$@"
