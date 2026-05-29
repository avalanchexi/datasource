#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 2

status="OK"
reason=""

platform="$(uname -s 2>/dev/null || printf 'unknown')"
case "$platform" in
  MINGW*|MSYS*|CYGWIN*) is_windows_native_bash=1 ;;
  *) is_windows_native_bash=0 ;;
esac

repo_path="$(pwd -P 2>/dev/null || pwd)"
wsl_repo_path="$repo_path"
case "$wsl_repo_path" in
  /[a-zA-Z]/*)
    drive="${wsl_repo_path:1:1}"
    rest="${wsl_repo_path:2}"
    drive="$(printf '%s' "$drive" | tr '[:upper:]' '[:lower:]')"
    wsl_repo_path="/mnt/${drive}${rest}"
    ;;
esac
wsl_repo_path_quoted="'$(printf '%s' "$wsl_repo_path" | sed "s/'/'\\\\''/g")'"

if [ -f ".venv/bin/activate" ]; then
  venv_layout="linux"
  python_path="$ROOT_DIR/.venv/bin/python"
elif [ -f ".venv/Scripts/activate" ]; then
  venv_layout="windows"
  if [ -x ".venv/Scripts/python.exe" ]; then
    python_path="$ROOT_DIR/.venv/Scripts/python.exe"
  else
    python_path="$ROOT_DIR/.venv/Scripts/python"
  fi
elif [ -d ".venv" ]; then
  venv_layout="broken"
  python_path=""
else
  venv_layout="missing"
  python_path=""
fi

if [ "$is_windows_native_bash" = "1" ] && [ "$venv_layout" = "linux" ]; then
  status="USE_WSL"
  reason="Windows native bash is active but .venv uses Linux/WSL layout"
elif [ "$is_windows_native_bash" = "1" ]; then
  case "$repo_path" in
    /mnt/*)
      status="USE_WSL"
      reason="Repository path looks like WSL but current shell is Windows native bash"
      ;;
  esac
fi

if [ "$status" = "OK" ]; then
  case "$venv_layout" in
    windows)
      if [ "$platform" = "Linux" ]; then
        status="BROKEN_ENV"
        reason="Windows venv layout is not usable under Linux/WSL"
      elif [ -z "$python_path" ] || [ ! -x "$python_path" ]; then
        status="BROKEN_ENV"
        reason="Selected venv Python is not executable: $python_path"
      elif ! python_exec="$("$python_path" -c "import sys; print(sys.executable)" 2>&1)"; then
        status="BROKEN_ENV"
        reason="Selected venv Python failed: $python_exec"
      fi
      ;;
    linux)
      if [ -z "$python_path" ] || [ ! -x "$python_path" ]; then
        status="BROKEN_ENV"
        reason="Selected venv Python is not executable: $python_path"
      elif ! python_exec="$("$python_path" -c "import sys; print(sys.executable)" 2>&1)"; then
        status="BROKEN_ENV"
        reason="Selected venv Python failed: $python_exec"
      fi
      ;;
    missing)
      status="BROKEN_ENV"
      reason="Missing .venv; create it before running the pipeline"
      ;;
    broken)
      status="BROKEN_ENV"
      reason=".venv exists but no usable activate script was found"
      ;;
  esac
fi

printf '[%s] env_probe\n' "$status"
printf 'platform=%s\n' "$platform"
printf 'repo_path=%s\n' "$repo_path"
printf 'venv_layout=%s\n' "$venv_layout"
if [ -n "${python_path:-}" ]; then
  printf 'python=%s\n' "$python_path"
fi
if [ -n "$reason" ]; then
  printf 'reason=%s\n' "$reason"
fi

case "$status" in
  OK)
    printf 'next=bash run_preflight.sh\n'
    exit 0
    ;;
  USE_WSL)
    printf 'next=C:\\Windows\\System32\\bash.exe -lc "cd %s && bash run_preflight.sh"\n' "$wsl_repo_path_quoted"
    exit 3
    ;;
  *)
    printf 'next=fix local venv or execution channel, then rerun bash scripts/env_probe.sh\n'
    exit 2
    ;;
esac
