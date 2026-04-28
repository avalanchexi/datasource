#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ $# -eq 0 ]; then
  echo "Usage: bash run_clean.sh <command> [args...]"
  echo "Example: bash run_clean.sh python scripts/stage2_unified_enhancer.py --help"
  exit 1
fi

VENV_ACTIVATE=""
if [ -f ".venv/bin/activate" ]; then
  VENV_ACTIVATE=".venv/bin/activate"
elif [ -f ".venv/Scripts/activate" ]; then
  VENV_ACTIVATE=".venv/Scripts/activate"
fi

if [ -z "$VENV_ACTIVATE" ] && [ "${ALLOW_SYSTEM_PYTHON:-}" != "1" ]; then
  echo "[ERROR] Missing virtual environment. Run: python -m venv .venv"
  echo "[ERROR] To use current system Python explicitly, set ALLOW_SYSTEM_PYTHON=1"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "[ERROR] Missing .env. Copy from .env.example first."
  exit 1
fi

if [ -n "$VENV_ACTIVATE" ]; then
  source "$VENV_ACTIVATE"
else
  echo "[WARNING] Missing virtual environment; using current system Python because ALLOW_SYSTEM_PYTHON=1"
fi

set -a
source .env
set +a

# Keep no_proxy/NO_PROXY, clear active proxy variables for direct connectivity.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

EXISTING_PY_PATH="${PYTHONPATH:-}"
if [ -n "$EXISTING_PY_PATH" ]; then
  case ":$EXISTING_PY_PATH:" in
    *":./src:"*|*":src:"*) PY_PATH="$EXISTING_PY_PATH" ;;
    *) PY_PATH="./src:$EXISTING_PY_PATH" ;;
  esac
else
  PY_PATH="./src"
fi

exec env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  PYTHONPATH="$PY_PATH" "$@"
