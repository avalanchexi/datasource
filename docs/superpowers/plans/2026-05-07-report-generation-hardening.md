# Report Generation Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the report generation runtime entrypoints and Stage2.5 manual input path so DNS/runtime failures fail early and manual补数 follows the policy rules reliably.

**Architecture:** Add a shared shell bootstrap at `scripts/runtime_env.sh` and make both `run_clean.sh` and `run_preflight.sh` source it. Keep business pipeline behavior unchanged; add a manual JSON template, focused tests, and short docs updates around the existing Stage1 -> Stage2 -> Stage2.5 -> Stage3 -> Stage4 flow.

**Tech Stack:** Bash, Python stdlib, pytest, existing datasource Stage scripts and documentation.

---

## File Structure

- Create `scripts/runtime_env.sh`: sourceable shell helper that owns repo-root detection, `.env` loading, proxy clearing, Python environment selection, and `PYTHONPATH` normalization.
- Modify `run_clean.sh`: reduce to command validation, source `scripts/runtime_env.sh`, then `exec` the requested command with normalized environment.
- Modify `run_preflight.sh`: source `scripts/runtime_env.sh`, validate required keys, run DNS and HTTPS reachability checks without business API calls.
- Modify `.env.example`: replace the real-looking TuShare token with a placeholder, add optional `EXA_API_KEY`, and remove `PYTHONPATH=.` as an active setting.
- Create `data/runs/templates/manual_template.json`: human-copyable Stage2.5 manual schema with safe examples and policy notes.
- Modify `AGENTS.md`: document the shared runtime, DNS hard fail, manual template, industrial `yoy_month`, `is_estimated`, and BDI secondary constraints.
- Modify `CLAUDE.md`: add the same high-frequency reminders in the quick reference only. This file may already be dirty; inspect and merge without reverting existing user edits.
- Create `tests/test_runtime_env.py`: shell helper unit tests using temporary repos and fake PATH commands.
- Modify `tests/test_run_clean.py`: adjust helper copying for `scripts/runtime_env.sh`, add line-ending and empty `.venv` tests.
- Create `tests/test_run_preflight.py`: fake DNS/curl tests that do not touch the network.
- Create `tests/test_manual_template.py`: template schema and policy guard tests.

## Task 1: Add Runtime Bootstrap Helper

**Files:**
- Create: `scripts/runtime_env.sh`
- Create: `tests/test_runtime_env.py`

- [ ] **Step 1: Write failing tests for shared runtime behavior**

Create `tests/test_runtime_env.py` with this content:

```python
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional


def _write_runtime(root: Path) -> None:
    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    source = Path("scripts/runtime_env.sh")
    if source.exists():
        body = source.read_text(encoding="utf-8").replace("\r\n", "\n")
    else:
        body = "#!/usr/bin/env bash\nreturn 1\n"
    (scripts / "runtime_env.sh").write_text(body, encoding="utf-8")


def _write_env(root: Path) -> None:
    (root / ".env").write_text(
        "TUSHARE_TOKEN=xxxxxxxxxxxxxxxxxxxx\n"
        "TAVILY_API_KEY=yyyyyyyyyyyyyyyyyyyy\n"
        "DEEPSEEK_API_KEY=zzzzzzzzzzzzzzzzzzzz\n"
        "PYTHONPATH=custom_path\n",
        encoding="utf-8",
    )


def _write_fake_uname(root: Path, system_name: str) -> Path:
    fake_bin = root / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    (fake_bin / "uname").write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"${1:-}\" = \"-s\" ]; then\n"
        f"  printf '%s\\n' {shlex.quote(system_name)}\n"
        "else\n"
        f"  printf '%s\\n' {shlex.quote(system_name)}\n"
        "fi\n",
        encoding="utf-8",
    )
    (fake_bin / "uname").chmod(0o755)
    return fake_bin


def _write_fake_python(root: Path, name: str = "python3") -> Path:
    fake_bin = root / "py-bin"
    fake_bin.mkdir(exist_ok=True)
    (fake_bin / name).write_text(
        "#!/usr/bin/env bash\nprintf 'fake-python\\n'\n",
        encoding="utf-8",
    )
    (fake_bin / name).chmod(0o755)
    return fake_bin


def _run_source(
    root: Path,
    script: str,
    *,
    env: Optional[dict] = None,
    path_prefix: Optional[str] = None,
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    merged.pop("ALLOW_SYSTEM_PYTHON", None)
    merged.update(env or {})
    command = (
        "set -euo pipefail; "
        "source scripts/runtime_env.sh; "
        f"{script}"
    )
    if path_prefix:
        command = f"PATH={shlex.quote(path_prefix)}:\"$PATH\"; export PATH; {command}"
    return subprocess.run(
        ["bash", "-c", command],
        cwd=root,
        env=merged,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_runtime_env_missing_env_fails(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)

    result = _run_source(root, "printf 'should-not-run\\n'", env={"ALLOW_SYSTEM_PYTHON": "1"})

    assert result.returncode != 0
    assert "Missing .env" in result.stdout
    assert "should-not-run" not in result.stdout


def test_runtime_env_uses_linux_venv_first(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text(
        "export RUNTIME_ACTIVATE=linux\n",
        encoding="utf-8",
    )

    result = _run_source(root, "printf '%s\\n' \"$RUNTIME_ACTIVATE\"")

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == "linux"


def test_runtime_env_uses_windows_venv_only_on_windows_bash(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    fake_uname = _write_fake_uname(root, "MINGW64_NT-10.0")
    scripts_dir = root / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "activate").write_text(
        "export RUNTIME_ACTIVATE=windows\n",
        encoding="utf-8",
    )

    result = _run_source(
        root,
        "printf '%s\\n' \"$RUNTIME_ACTIVATE\"",
        path_prefix=str(fake_uname),
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == "windows"


def test_runtime_env_empty_venv_is_hard_failure(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    (root / ".venv").mkdir()

    result = _run_source(
        root,
        "printf 'should-not-run\\n'",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
    )

    assert result.returncode != 0
    assert ".venv exists but no usable activate script found" in result.stdout
    assert "should-not-run" not in result.stdout


def test_runtime_env_system_fallback_prefers_python3_and_sets_pythonpath(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    fake_python = _write_fake_python(root, "python3")

    result = _run_source(
        root,
        "printf '%s|%s\\n' \"$DATASOURCE_PYTHON\" \"$PYTHONPATH\"",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
        path_prefix=str(fake_python),
    )

    assert result.returncode == 0, result.stdout
    last = result.stdout.strip().splitlines()[-1]
    assert last.startswith("python3|")
    assert "./src" in last
    assert "custom_path" in last


def test_runtime_env_without_venv_requires_explicit_fallback(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)

    result = _run_source(root, "printf 'should-not-run\\n'")

    assert result.returncode != 0
    assert "Missing virtual environment" in result.stdout
    assert "ALLOW_SYSTEM_PYTHON=1" in result.stdout
    assert "should-not-run" not in result.stdout
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
ALLOW_SYSTEM_PYTHON=1 python3 -m pytest tests/test_runtime_env.py -q
```

Expected: failures because `scripts/runtime_env.sh` does not exist and the temporary copied helper returns non-zero.

- [ ] **Step 3: Implement `scripts/runtime_env.sh`**

Create `scripts/runtime_env.sh` with this content:

```bash
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
if [ -f ".venv/bin/activate" ]; then
  VENV_ACTIVATE=".venv/bin/activate"
elif [ "$IS_WINDOWS_NATIVE_BASH" = "1" ] && [ -f ".venv/Scripts/activate" ]; then
  VENV_ACTIVATE=".venv/Scripts/activate"
elif [ -d ".venv" ]; then
  echo "[ERROR] .venv exists but no usable activate script found"
  echo "[ERROR] Recreate it with: python -m venv .venv"
  return 1 2>/dev/null || exit 1
fi

if [ -n "$VENV_ACTIVATE" ]; then
  # shellcheck disable=SC1090
  source "$VENV_ACTIVATE"
  DATASOURCE_PYTHON="${DATASOURCE_PYTHON:-python}"
elif [ "${ALLOW_SYSTEM_PYTHON:-}" = "1" ]; then
  echo "[WARNING] Missing virtual environment; using current system Python because ALLOW_SYSTEM_PYTHON=1"
  if command -v python3 >/dev/null 2>&1; then
    DATASOURCE_PYTHON="python3"
  elif command -v python >/dev/null 2>&1; then
    DATASOURCE_PYTHON="python"
  else
    echo "[ERROR] No python3 or python command found for system fallback"
    return 1 2>/dev/null || exit 1
  fi
else
  echo "[ERROR] Missing virtual environment. Run: python -m venv .venv"
  echo "[ERROR] To use current system Python explicitly, set ALLOW_SYSTEM_PYTHON=1"
  return 1 2>/dev/null || exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

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
```

- [ ] **Step 4: Run runtime helper tests**

Run:

```bash
ALLOW_SYSTEM_PYTHON=1 python3 -m pytest tests/test_runtime_env.py -q
```

Expected: all tests in `tests/test_runtime_env.py` pass.

- [ ] **Step 5: Commit runtime helper**

Run:

```bash
git add scripts/runtime_env.sh tests/test_runtime_env.py
git commit -m "feat: add shared runtime bootstrap"
```

Expected: commit succeeds with only `scripts/runtime_env.sh` and `tests/test_runtime_env.py`.

## Task 2: Refactor `run_clean.sh` Onto Shared Runtime

**Files:**
- Modify: `run_clean.sh`
- Modify: `tests/test_run_clean.py`

- [ ] **Step 1: Add failing `run_clean.sh` tests**

Modify `tests/test_run_clean.py`:

Add this helper after `_copy_runner` imports and replace `_copy_runner` with the version below:

```python
def _copy_runner(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    scripts = root / "scripts"
    scripts.mkdir()
    runner = Path("run_clean.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    runtime = Path("scripts/runtime_env.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    (root / "run_clean.sh").write_bytes(runner.encode("utf-8"))
    (scripts / "runtime_env.sh").write_bytes(runtime.encode("utf-8"))
    (root / ".env").write_bytes(
        b"TUSHARE_TOKEN=x\nTAVILY_API_KEY=y\nDEEPSEEK_API_KEY=z\n"
    )
    return root
```

Add these tests near the top of the file:

```python
def test_run_clean_script_uses_lf_line_endings() -> None:
    body = Path("run_clean.sh").read_bytes()
    assert b"\r\n" not in body


def test_empty_venv_directory_fails_even_with_system_fallback(tmp_path: Path) -> None:
    root = _copy_runner(tmp_path)
    (root / ".venv").mkdir()

    result = _run(
        root,
        "printf",
        "should not run\n",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
    )

    assert result.returncode == 1
    assert ".venv exists but no usable activate script found" in result.stdout
    assert "should not run" not in result.stdout
```

- [ ] **Step 2: Run tests and verify failures**

Run:

```bash
ALLOW_SYSTEM_PYTHON=1 python3 -m pytest tests/test_run_clean.py -q
```

Expected: `test_run_clean_script_uses_lf_line_endings` fails while `run_clean.sh` still has CRLF line endings, and the empty `.venv` behavior fails until `run_clean.sh` uses `scripts/runtime_env.sh`.

- [ ] **Step 3: Replace `run_clean.sh` with shared-runtime implementation**

Replace `run_clean.sh` with this LF-only content:

```bash
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

exec env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  PYTHONPATH="$PYTHONPATH" "$@"
```

Ensure the file has LF endings:

```bash
python3 - <<'PY'
from pathlib import Path
p = Path("run_clean.sh")
p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n"))
PY
```

- [ ] **Step 4: Run `run_clean` tests**

Run:

```bash
ALLOW_SYSTEM_PYTHON=1 python3 -m pytest tests/test_runtime_env.py tests/test_run_clean.py -q
```

Expected: all runtime and run_clean tests pass.

- [ ] **Step 5: Commit `run_clean` refactor**

Run:

```bash
git add run_clean.sh tests/test_run_clean.py
git commit -m "fix: share runtime setup in run_clean"
```

Expected: commit succeeds with `run_clean.sh` and `tests/test_run_clean.py`.

## Task 3: Harden `run_preflight.sh`

**Files:**
- Modify: `run_preflight.sh`
- Create: `tests/test_run_preflight.py`

- [ ] **Step 1: Write failing preflight tests**

Create `tests/test_run_preflight.py` with this content:

```python
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional


VALID_ENV = (
    "TUSHARE_TOKEN=xxxxxxxxxxxxxxxxxxxx\n"
    "TAVILY_API_KEY=yyyyyyyyyyyyyyyyyyyy\n"
    "DEEPSEEK_API_KEY=zzzzzzzzzzzzzzzzzzzz\n"
)


def _copy_preflight(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    scripts = root / "scripts"
    scripts.mkdir()
    (root / "run_preflight.sh").write_text(
        Path("run_preflight.sh").read_text(encoding="utf-8").replace("\r\n", "\n"),
        encoding="utf-8",
    )
    (scripts / "runtime_env.sh").write_text(
        Path("scripts/runtime_env.sh").read_text(encoding="utf-8").replace("\r\n", "\n"),
        encoding="utf-8",
    )
    return root


def _write_fake_command(root: Path, name: str, body: str) -> Path:
    fake_bin = root / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    path = fake_bin / name
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return fake_bin


def _run_preflight(
    root: Path,
    *,
    env: Optional[dict] = None,
    path_prefix: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    merged.update({"ALLOW_SYSTEM_PYTHON": "1"})
    merged.update(env or {})
    command = "bash run_preflight.sh"
    if path_prefix is not None:
        command = f"PATH={shlex.quote(str(path_prefix))}:\"$PATH\"; export PATH; {command}"
    return subprocess.run(
        ["bash", "-c", command],
        cwd=root,
        env=merged,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_preflight_missing_env_fails(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)

    result = _run_preflight(root)

    assert result.returncode != 0
    assert "Missing .env" in result.stdout


def test_preflight_short_key_fails(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(
        "TUSHARE_TOKEN=short\n"
        "TAVILY_API_KEY=yyyyyyyyyyyyyyyyyyyy\n"
        "DEEPSEEK_API_KEY=zzzzzzzzzzzzzzzzzzzz\n",
        encoding="utf-8",
    )

    result = _run_preflight(root)

    assert result.returncode != 0
    assert "Missing/short TUSHARE_TOKEN" in result.stdout


def test_preflight_dns_failure_is_hard_fail(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(VALID_ENV, encoding="utf-8")
    fake_bin = _write_fake_command(
        root,
        "getent",
        "printf 'dns failed for %s\\n' \"$*\" >&2\nexit 2\n",
    )

    result = _run_preflight(root, path_prefix=fake_bin)

    assert result.returncode != 0
    assert "DNS check failed" in result.stdout
    assert "api.tavily.com" in result.stdout


def test_preflight_https_failure_is_hard_fail(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(VALID_ENV, encoding="utf-8")
    fake_bin = _write_fake_command(
        root,
        "getent",
        "printf '127.0.0.1 %s\\n' \"${@: -1}\"\n",
    )
    _write_fake_command(root, "curl", "printf '000'\nexit 0\n")

    result = _run_preflight(root, path_prefix=fake_bin)

    assert result.returncode != 0
    assert "HTTPS check failed" in result.stdout
    assert "https://api.tavily.com" in result.stdout


def test_preflight_accepts_non_2xx_http_response(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(VALID_ENV, encoding="utf-8")
    fake_bin = _write_fake_command(
        root,
        "getent",
        "printf '127.0.0.1 %s\\n' \"${@: -1}\"\n",
    )
    _write_fake_command(root, "curl", "printf '405'\nexit 0\n")

    result = _run_preflight(root, path_prefix=fake_bin)

    assert result.returncode == 0, result.stdout
    assert "[OK] DNS api.tavily.com" in result.stdout
    assert "[OK] HTTPS https://api.tavily.com" in result.stdout
    assert "Proxy cleared" in result.stdout
```

- [ ] **Step 2: Run tests and verify failures**

Run:

```bash
ALLOW_SYSTEM_PYTHON=1 python3 -m pytest tests/test_run_preflight.py -q
```

Expected: tests fail because `run_preflight.sh` does not source `scripts/runtime_env.sh` and does not perform DNS/HTTPS checks.

- [ ] **Step 3: Implement preflight checks**

Replace `run_preflight.sh` with this content:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# shellcheck disable=SC1091
source scripts/runtime_env.sh

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
print(parsed.netloc or parsed.path)
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
    code="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 8 "$url" || printf '000')"
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
  if [ "$code" = "000" ]; then
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
```

- [ ] **Step 4: Run preflight tests**

Run:

```bash
ALLOW_SYSTEM_PYTHON=1 python3 -m pytest tests/test_runtime_env.py tests/test_run_preflight.py -q
```

Expected: all runtime and preflight tests pass.

- [ ] **Step 5: Commit preflight hardening**

Run:

```bash
git add run_preflight.sh tests/test_run_preflight.py
git commit -m "fix: fail early on preflight connectivity"
```

Expected: commit succeeds with `run_preflight.sh` and `tests/test_run_preflight.py`.

## Task 4: Add Stage2.5 Manual Template

**Files:**
- Create: `data/runs/templates/manual_template.json`
- Create: `tests/test_manual_template.py`

- [ ] **Step 1: Write failing template tests**

Create `tests/test_manual_template.py` with this content:

```python
import json
from pathlib import Path
from typing import Any, Iterable


TEMPLATE = Path("data/runs/templates/manual_template.json")


def _walk_values(value: Any) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def test_manual_template_is_valid_json() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert "_rules" in payload


def test_manual_template_has_industrial_yoy_month_shape() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    industrial = payload["macro_indicators"]["industrial"]
    assert industrial["current_value"] == industrial["yoy_month"]
    assert industrial["value_type"] == "yoy_month"
    assert "1-2月" in industrial["_note"]


def test_manual_template_bdi_mentions_secondary_constraints() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    text = json.dumps(payload["macro_indicators"]["bdi"], ensure_ascii=False)
    for token in ("trusted_domains", "max_age_days", "value_range", "unit_keywords"):
        assert token in text


def test_manual_template_numeric_examples_have_url_evidence() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    missing = []
    numeric_fields = {
        "current_value",
        "current_price",
        "current_rate",
        "current_yield",
        "recent_5d",
        "total_120d",
    }
    for item in _walk_values(payload):
        if any(isinstance(item.get(field), (int, float)) for field in numeric_fields):
            evidence = " ".join(
                str(item.get(field) or "")
                for field in ("source_url", "source", "note", "_note")
            )
            if "http://" not in evidence and "https://" not in evidence:
                missing.append(item)
    assert missing == []


def test_manual_template_official_examples_are_not_estimated() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    official_paths = [
        payload["macro_indicators"]["industrial"],
        payload["forex"][0],
        payload["commodities"][0],
    ]
    for item in official_paths:
        assert item["is_estimated"] is False
```

- [ ] **Step 2: Run template tests and verify failure**

Run:

```bash
ALLOW_SYSTEM_PYTHON=1 python3 -m pytest tests/test_manual_template.py -q
```

Expected: tests fail because `data/runs/templates/manual_template.json` does not exist.

- [ ] **Step 3: Create manual template**

Create `data/runs/templates/manual_template.json` with this content:

```json
{
  "_rules": {
    "purpose": "Copy category entries from this file into data/runs/${DATE_NH}/websearch_results_manual.json, then run scripts/stage2_5_injector.py.",
    "source_url": "Every numeric manual value must include a single source_url string, or a URL in source/note.",
    "is_estimated": "Official published values, official midpoint rates, exchange values, and index vendor values should use is_estimated=false. Use true only for spread estimates, formulas, proxy series, extrapolation, or other approximations.",
    "allow_estimated": "--allow-estimated is not a global bypass. It only allows policy allowlist estimated keys to participate; compare_gaps, stale_redlist, and policy gate still apply.",
    "bdi_estimated_allow_conditions": "BDI is allowlisted only when config/policy_rules.yaml secondary constraints pass: trusted_domains, max_age_days, value_range, unit_keywords."
  },
  "macro_indicators": {
    "industrial": {
      "_note": "工业增加值如果使用国家统计局 1-2月 累计同比作为流水线 current value, still set value_type=yoy_month and yoy_month explicitly, otherwise the injector may classify it as yoy_ytd and current_value will be missing. Source: https://www.stats.gov.cn/",
      "indicator_name": "工业增加值",
      "current_value": 6.3,
      "yoy_month": 6.3,
      "value_type": "yoy_month",
      "previous_value": 5.9,
      "change_rate": 6.78,
      "unit": "%",
      "date": "2026-02",
      "report_period": "2026-02",
      "source": "国家统计局",
      "source_url": "https://www.stats.gov.cn/",
      "is_estimated": false
    },
    "bdi": {
      "_note": "If is_estimated=true, BDI must satisfy bdi_estimated_allow_conditions: trusted_domains, max_age_days<=2, value_range, and unit_keywords. Example source: https://www.investing.com/indices/baltic-dry",
      "_rules": {
        "trusted_domains": [
          "balticexchange.com",
          "tradingeconomics.com",
          "investing.com",
          "eastmoney.com"
        ],
        "max_age_days": 2,
        "value_range": [
          200.0,
          10000.0
        ],
        "unit_keywords": [
          "点",
          "point",
          "points"
        ]
      },
      "indicator_name": "BDI",
      "current_value": 2730,
      "previous_value": 2650,
      "change_rate": 3.02,
      "unit": "points",
      "date": "2026-05-06",
      "source": "Investing.com",
      "source_url": "https://www.investing.com/indices/baltic-dry",
      "is_estimated": true,
      "estimation_method": "trusted recent market page"
    }
  },
  "forex": [
    {
      "pair": "USDCNY",
      "name": "USD/CNY在岸",
      "current_rate": 7.248,
      "unit": "CNY",
      "date": "2026-05-07",
      "source": "CFETS/PBOC official quote",
      "source_url": "https://www.chinamoney.com.cn/",
      "is_estimated": false
    }
  ],
  "bonds": [
    {
      "symbol": "CN10Y_CDB",
      "name": "10年期国开债收益率",
      "current_yield": 2.25,
      "unit": "%",
      "date": "2026-05-07",
      "source": "manual spread estimate with source evidence",
      "source_url": "https://yield.chinabond.com.cn/",
      "is_estimated": true,
      "estimation_method": "CN10Y plus observed CDB spread"
    }
  ],
  "commodities": [
    {
      "symbol": "BCOM",
      "name": "Bloomberg Commodity Index",
      "current_price": 101.5,
      "unit": "points",
      "date": "2026-05-07",
      "source": "Bloomberg index page",
      "source_url": "https://www.bloomberg.com/quote/BCOM:IND",
      "is_estimated": false
    }
  ],
  "fund_flow": {
    "northbound": {
      "_note": "Use official or trusted current flow source. Do not use AKShare direct final values. Source example: https://data.eastmoney.com/hsgt/index.html",
      "recent_5d": 85.6,
      "total_120d": 1250.0,
      "trend": "流入",
      "source": "Stage2.5 manual",
      "source_url": "https://data.eastmoney.com/hsgt/index.html",
      "is_estimated": false
    },
    "southbound": {
      "_note": "Use official or trusted current flow source. Source example: https://data.eastmoney.com/hsgt/index.html",
      "recent_5d": 42.1,
      "total_120d": 980.0,
      "trend": "流入",
      "source": "Stage2.5 manual",
      "source_url": "https://data.eastmoney.com/hsgt/index.html",
      "is_estimated": false
    },
    "etf": {
      "_note": "ETF manual values must state whether they are news net-flow or TuShare total-size delta. Source example: https://data.eastmoney.com/etf/",
      "recent_5d": 63.2,
      "total_120d": 1500.0,
      "trend": "流入",
      "source": "Stage2.5 manual",
      "source_url": "https://data.eastmoney.com/etf/",
      "metric_basis": "news_net_flow",
      "is_estimated": false
    }
  }
}
```

- [ ] **Step 4: Run template tests**

Run:

```bash
ALLOW_SYSTEM_PYTHON=1 python3 -m pytest tests/test_manual_template.py -q
```

Expected: all template tests pass.

- [ ] **Step 5: Commit manual template**

Run:

```bash
git add data/runs/templates/manual_template.json tests/test_manual_template.py
git commit -m "docs: add stage2 manual template"
```

Expected: commit succeeds with the template and tests.

## Task 5: Update `.env.example` and Operational Docs

**Files:**
- Modify: `.env.example`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Inspect existing user changes**

Run:

```bash
git status --short
git diff -- CLAUDE.md AGENTS.md .env.example
```

Expected: review existing local changes. If `CLAUDE.md` is already modified, preserve its current content and apply only the additions below.

- [ ] **Step 2: Update `.env.example`**

Edit `.env.example` so the relevant sections read:

```dotenv
# TuShare API Token
TUSHARE_TOKEN=your-tushare-token

# Rate limiting settings
AKSHARE_RATE_LIMIT=10
TUSHARE_RATE_LIMIT=5

# Cache settings
CACHE_ENABLED=true
CACHE_TTL=300

# Proxy (optional; leave empty to disable. run_clean.sh/run_preflight.sh clear active proxy variables for direct connectivity)
HTTP_PROXY=
HTTPS_PROXY=
NO_PROXY=localhost,127.0.0.1

# Stage2 Tavily / DeepSeek
TAVILY_API_KEY=your-tavily-key
DEEPSEEK_API_KEY=your-deepseek-key
DEEPSEEK_MODEL=deepseek-v4-pro

# Optional Exa fallback. Disabled unless EXA_API_KEY is set and Stage2 opt-in flag/env is enabled.
EXA_API_KEY=

# PYTHONPATH is set by scripts/runtime_env.sh via run_clean.sh/run_preflight.sh.
# STAGE2_SEARCH_BACKEND 已弃用，请用 CLI 参数 --fund-flow-backend / --extraction-backend
```

- [ ] **Step 3: Update `AGENTS.md`**

Apply these exact documentation additions in the matching existing sections:

In `Setup & Health Check`, after the `run_preflight.sh` command description, add:

```markdown
`run_preflight.sh` 会复用 `scripts/runtime_env.sh`，统一加载 `.env`、选择 `.venv` 或显式系统 Python fallback、清理代理并设置 `PYTHONPATH=./src`。Preflight 会检查 `api.tavily.com`、`api.deepseek.com`、`api.tushare.pro` 的 DNS 与 HTTPS 基础连通性；任一失败均为运行环境 hard fail，不进入 Stage1/Stage2。
```

In Stage2.5 manual injection, add:

```markdown
- 手工补数优先从 `data/runs/templates/manual_template.json` 复制对应 category 示例到当日 `websearch_results_manual.json`，再替换数值、日期和 `source_url`。
- 官方发布值、官方中间价、交易所/指数商实时值默认 `is_estimated=false`；只有利差估算、公式推导、代理序列、外推或明确近似值才写 `is_estimated=true`。
- `macro_indicators.industrial` 若使用“1-2月累计同比”等来源作为流水线当前值，必须显式写 `value_type: "yoy_month"` 和 `yoy_month`，否则会被识别为 `yoy_ytd` 并导致 `current_value` 缺失。
- `bdi` 即使在 `estimated_allowlist_keys` 内，仍受 `bdi_estimated_allow_conditions` 约束：`trusted_domains`、`max_age_days`、`value_range`、`unit_keywords` 均需通过。
```

In Troubleshooting, add rows:

```markdown
| Preflight DNS 失败 | DNS/WSL/容器网络不可达 | 修复 `/etc/resolv.conf` 或宿主网络后重跑 `bash run_preflight.sh`；不要启动 Stage2 |
| `.venv` 目录存在但不可用 | 空目录或 Windows/Linux venv 混用 | 删除并重建 `.venv`，或在无 `.venv` 时显式 `ALLOW_SYSTEM_PYTHON=1` 使用系统 Python |
| `industrial current_value is missing` | manual JSON 中“累计”文本触发 `yoy_ytd`，但未显式 `yoy_month` | 按模板补 `value_type: "yoy_month"`、`yoy_month`、`current_value` 后重跑 Stage2.5 |
```

- [ ] **Step 4: Update `CLAUDE.md`**

Add this quick reminder near the existing quick-start/preflight area:

```markdown
- `run_preflight.sh` 与 `run_clean.sh` 共享 `scripts/runtime_env.sh`；`.env` 是密钥/配置，`.venv` 是依赖环境，不合并。空 `.venv` 视为坏环境，需重建或删除后显式 `ALLOW_SYSTEM_PYTHON=1`。
- DNS/HTTPS preflight 失败是运行环境 hard fail，不启动 Stage2，不重跑 Tavily。
```

Add this reminder near the Stage2.5/Operational Pitfalls area:

```markdown
- Stage2.5 manual 从 `data/runs/templates/manual_template.json` 复制起步；官方值默认 `is_estimated=false`。
- `industrial` 使用“1-2月累计同比”时必须显式 `value_type: yoy_month` 和 `yoy_month`。
- `bdi` 的 estimated allowlist 还有二级约束：`trusted_domains/max_age_days/value_range/unit_keywords`。
```

- [ ] **Step 5: Review doc diffs**

Run:

```bash
git diff -- .env.example AGENTS.md CLAUDE.md
```

Expected: diffs are limited to the runtime/preflight/manual-template guidance and `.env.example` cleanup. Existing unrelated `CLAUDE.md` changes are preserved.

- [ ] **Step 6: Commit docs**

Run:

```bash
git add .env.example AGENTS.md CLAUDE.md
git commit -m "docs: document runtime preflight workflow"
```

Expected: commit succeeds. If `CLAUDE.md` contains unrelated pre-existing user edits, pause and ask before committing that file.

## Task 6: Final Verification

**Files:**
- Verify only; no planned file edits.

- [ ] **Step 1: Run focused tests**

Run:

```bash
ALLOW_SYSTEM_PYTHON=1 python3 -m pytest tests/test_runtime_env.py tests/test_run_clean.py tests/test_run_preflight.py tests/test_manual_template.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Check shell line endings**

Run:

```bash
file run_clean.sh run_preflight.sh scripts/runtime_env.sh
```

Expected: none of the three files report `CRLF line terminators`.

- [ ] **Step 3: Run real preflight when credentials are available**

Run:

```bash
bash run_preflight.sh
```

Expected on a configured machine: DNS checks for Tavily, DeepSeek, and TuShare are `[OK]`; HTTPS checks are `[OK]` with non-`000` HTTP codes; proxy variables are cleared. If the repo has an empty `.venv`, expected result is a hard fail explaining `.venv exists but no usable activate script found`; fix by recreating `.venv` or deleting it and using `ALLOW_SYSTEM_PYTHON=1`.

- [ ] **Step 4: Verify git state**

Run:

```bash
git status --short
git log --oneline -6
```

Expected: only unrelated pre-existing user files remain uncommitted. New implementation commits are visible in the log.

- [ ] **Step 5: Final implementation summary**

Report:

```text
Implemented shared runtime bootstrap, preflight DNS/HTTPS hard fail, run_clean LF/runtime refactor, Stage2.5 manual template, and docs. Focused tests pass: tests/test_runtime_env.py, tests/test_run_clean.py, tests/test_run_preflight.py, tests/test_manual_template.py.
```

## Self-Review

Spec coverage:

- Runtime bootstrap: Task 1 and Task 2.
- DNS/HTTPS hard fail: Task 3.
- `.env.example` cleanup: Task 5.
- Manual template with industrial/is_estimated/BDI rules: Task 4.
- `AGENTS.md`/`CLAUDE.md` docs: Task 5.
- Focused verification: Task 6.

Placeholder scan:

- No `TBD`, `TODO`, or unspecified implementation steps remain.
- All code-modifying steps include concrete file contents or exact snippets.
- Test commands include expected outcomes.

Type and name consistency:

- Shared helper exports `DATASOURCE_PYTHON`, `DATASOURCE_RUNTIME_DIR`, and `PYTHONPATH`.
- `run_preflight.sh` invokes `$DATASOURCE_PYTHON`, matching the helper.
- Tests reference the same paths and variable names defined in the tasks.
