#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

NO_INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --no-install)
      NO_INSTALL=1
      ;;
    *)
      echo "[ERROR] Unknown argument: $arg"
      exit 2
      ;;
  esac
done

STAMP=".venv/.datasource_bootstrapped"
FAILED=".venv/.datasource_bootstrap_failed"
VENV_PYTHON=".venv/bin/python"

_timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

_hash_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  else
    python3 - "$path" <<'PY'
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
  fi
}

_write_stamp() {
  local python_version
  python_version="$("$VENV_PYTHON" --version 2>&1)"

  mkdir -p ".venv"
  {
    printf 'timestamp=%s\n' "$(_timestamp)"
    printf 'python=%s\n' "$REPO_ROOT/$VENV_PYTHON"
    printf 'python_version=%s\n' "$python_version"
    if [ -f "requirements.txt" ]; then
      printf 'requirements_sha256=%s\n' "$(_hash_file "requirements.txt")"
    fi
    if [ -f "setup.py" ]; then
      printf 'setup_py_mtime=%s\n' "$(stat -c '%Y' "setup.py")"
    fi
  } > "$STAMP"
  rm -f "$FAILED"
}

_fail() {
  local message="$1"
  mkdir -p ".venv"
  {
    printf 'timestamp=%s\n' "$(_timestamp)"
    printf 'reason=%s\n' "$message"
  } > "$FAILED"
  echo "[ERROR] bootstrap failed: $message"
  exit 1
}

_venv_has_entries() {
  [ -n "$(find ".venv" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]
}

if [ -f "$FAILED" ]; then
  _fail "previous bootstrap failed; remove .venv or rerun after fixing the cause"
fi

if [ -d ".venv" ] && _venv_has_entries && [ ! -x "$VENV_PYTHON" ]; then
  _fail ".venv exists but is not a usable Linux virtualenv; remove .venv and recreate it"
fi

if [ ! -x "$VENV_PYTHON" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    _fail "python3 command not found"
  fi
  if ! python3 -m venv .venv; then
    _fail "python3 -m venv .venv failed"
  fi
fi

if [ ! -x "$VENV_PYTHON" ]; then
  _fail ".venv/bin/python was not created"
fi

if [ "$NO_INSTALL" != "1" ]; then
  if [ -f "requirements.txt" ]; then
    if ! "$VENV_PYTHON" -m pip install -r requirements.txt; then
      _fail "pip install -r requirements.txt failed"
    fi
  fi
  if ! "$VENV_PYTHON" -m pip install -e .; then
    _fail "pip install -e . failed"
  fi
  if [ "${DATASOURCE_INSTALL_DEV:-}" = "1" ]; then
    if ! "$VENV_PYTHON" -m pip install -e ".[dev]"; then
      _fail "pip install -e .[dev] failed"
    fi
  fi
fi

_write_stamp
echo "[OK] .venv bootstrap complete"
