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
_datasource_clear_active_proxies() {
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
}

if [ -f ".venv/.datasource_bootstrap_failed" ]; then
  echo "[ERROR] .venv has a failed bootstrap stamp: .venv/.datasource_bootstrap_failed"
  echo "[ERROR] Fix the cause, then remove .venv/.datasource_bootstrap_failed, or remove/recreate .venv"
  return 1 2>/dev/null || exit 1
fi

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
  if [ -z "$(find ".venv" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
    if [ "${DATASOURCE_AUTO_VENV:-}" = "1" ]; then
      if [ ! -r "scripts/bootstrap_venv.sh" ]; then
        echo "[ERROR] DATASOURCE_AUTO_VENV=1 requested but scripts/bootstrap_venv.sh is not readable"
        return 1 2>/dev/null || exit 1
      fi
      _datasource_clear_active_proxies
      if ! bash scripts/bootstrap_venv.sh; then
        return 1 2>/dev/null || exit 1
      fi
      if [ -f ".venv/bin/activate" ]; then
        VENV_ACTIVATE=".venv/bin/activate"
        VENV_PYTHON="$DATASOURCE_RUNTIME_DIR/.venv/bin/python"
      else
        echo "[ERROR] DATASOURCE_AUTO_VENV=1 bootstrap did not create .venv/bin/activate"
        return 1 2>/dev/null || exit 1
      fi
    fi
  else
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
  echo "[ERROR] To auto-bootstrap an empty .venv in Ubuntu/Claude Code, set DATASOURCE_AUTO_VENV=1"
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
_datasource_clear_active_proxies

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
unset -f _datasource_clear_active_proxies
