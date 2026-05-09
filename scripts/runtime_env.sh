#!/usr/bin/env bash

DATASOURCE_RUNTIME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DATASOURCE_RUNTIME_DIR"

if [ ! -f ".env" ]; then
  echo "[ERROR] Missing .env. Copy from .env.example first."
  return 1 2>/dev/null || exit 1
fi

BASH_PLATFORM="$(uname -s 2>/dev/null || echo unknown)"
IS_WINDOWS_NATIVE_BASH=0
case "$BASH_PLATFORM" in
  MINGW*|MSYS*|CYGWIN*) IS_WINDOWS_NATIVE_BASH=1 ;;
esac

VENV_ACTIVATE=""
VENV_PYTHON=""
DATASOURCE_SELECTED_PYTHON=""
if [ -f ".venv/bin/activate" ]; then
  VENV_ACTIVATE=".venv/bin/activate"
  VENV_PYTHON="$DATASOURCE_RUNTIME_DIR/.venv/bin/python"
elif [ "$IS_WINDOWS_NATIVE_BASH" = "1" ] && [ -f ".venv/Scripts/activate" ]; then
  VENV_ACTIVATE=".venv/Scripts/activate"
  if [ -x ".venv/Scripts/python.exe" ]; then
    VENV_PYTHON="$DATASOURCE_RUNTIME_DIR/.venv/Scripts/python.exe"
  elif [ -x ".venv/Scripts/python" ]; then
    VENV_PYTHON="$DATASOURCE_RUNTIME_DIR/.venv/Scripts/python"
  fi
elif [ -d ".venv" ]; then
  if [ -n "$(find ".venv" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
    echo "[ERROR] .venv exists but no usable activate script found"
    echo "[ERROR] Recreate it with: python -m venv .venv"
    return 1 2>/dev/null || exit 1
  fi
fi

if [ -n "$VENV_ACTIVATE" ]; then
  if [ -z "$VENV_PYTHON" ] || [ ! -x "$VENV_PYTHON" ]; then
    echo "[ERROR] .venv exists but no usable Python interpreter found"
    echo "[ERROR] Recreate it with: python -m venv .venv"
    return 1 2>/dev/null || exit 1
  fi
  # shellcheck disable=SC1090
  source "$VENV_ACTIVATE"
  DATASOURCE_SELECTED_PYTHON="$VENV_PYTHON"
elif [ "${ALLOW_SYSTEM_PYTHON:-}" = "1" ]; then
  echo "[WARNING] Missing virtual environment; using current system Python because ALLOW_SYSTEM_PYTHON=1"
  if command -v python3 >/dev/null 2>&1; then
    DATASOURCE_SELECTED_PYTHON="python3"
  elif command -v python >/dev/null 2>&1; then
    DATASOURCE_SELECTED_PYTHON="python"
  else
    echo "[ERROR] No python3 or python command found for system fallback"
    return 1 2>/dev/null || exit 1
  fi
else
  echo "[ERROR] Missing virtual environment. Run: python -m venv .venv"
  echo "[ERROR] To use current system Python explicitly, set ALLOW_SYSTEM_PYTHON=1"
  return 1 2>/dev/null || exit 1
fi

DATASOURCE_ALLEXPORT_WAS_SET=0
case "$-" in
  *a*) DATASOURCE_ALLEXPORT_WAS_SET=1 ;;
esac

set -a
# shellcheck disable=SC1091
source .env
if [ "$DATASOURCE_ALLEXPORT_WAS_SET" = "1" ]; then
  set -a
else
  set +a
fi

DATASOURCE_PYTHON="$DATASOURCE_SELECTED_PYTHON"

# Keep no_proxy/NO_PROXY, clear active proxy variables for direct connectivity.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

EXISTING_PY_PATH="${PYTHONPATH:-}"
if [ -n "$EXISTING_PY_PATH" ]; then
  case ":$EXISTING_PY_PATH:" in
    *":./src:"*|*":src:"*) PYTHONPATH="$EXISTING_PY_PATH" ;;
    *) PYTHONPATH="./src:$EXISTING_PY_PATH" ;;
  esac
else
  PYTHONPATH="./src"
fi

export DATASOURCE_RUNTIME_DIR
export DATASOURCE_PYTHON
export PYTHONPATH

unset DATASOURCE_SELECTED_PYTHON
unset DATASOURCE_ALLEXPORT_WAS_SET
