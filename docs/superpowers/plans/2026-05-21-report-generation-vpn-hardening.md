# Report Generation VPN Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the daily report pipeline resilient to Ubuntu/WSL VPN changes, empty `.venv` startup failures, opaque quality gates, and misleading estimated data during Claude Code report generation.

**Architecture:** Add a small runtime bootstrap boundary for venv setup and proxy isolation, then keep downstream data quality strict while making Stage2, Stage2.5, Stage3, Stage4, and reports more diagnosable. Shared helpers live in `src/datasource/utils/` so scripts do not duplicate trust, gate formatting, or summary logic.

**Tech Stack:** Bash, Python 3.10, pytest, httpx, existing Stage1 -> Stage4 scripts, existing `run_clean.sh` runtime entrypoint.

---

## Scope Check

The design spans runtime setup, Stage2 extraction, Stage2.5 injection, gate formatting, report rendering, and docs. This plan keeps it as one implementation plan because each task is independently testable and the work is all in the same report-generation pipeline. Execute tasks in order; later tasks rely on helpers introduced earlier.

## File Structure

- Create `scripts/bootstrap_venv.sh`: self-contained `.venv` creation and dependency installation. It never sources `.env` and never calls external APIs directly.
- Modify `scripts/runtime_env.sh`: detect empty `.venv`, optionally call bootstrap, clear all active proxy vars, preserve strict behavior for bad non-empty venvs.
- Modify `run_clean.sh`: remove `ALL_PROXY/all_proxy` from command environment.
- Modify `run_preflight.sh`: surface direct/proxy network mode and SOCKS dependency checks.
- Modify `src/datasource/adapters/tavily_client.py`: default `httpx.AsyncClient` to `trust_env=False`.
- Create `src/datasource/utils/source_trust.py`: official source and snippet-bound URL evidence checks for Stage2.
- Modify `scripts/stage2_unified_enhancer.py`: proxy environment fast-fail, official source non-estimated normalization, DeepSeek timeout circuit breaker.
- Create `src/datasource/utils/gate_formatting.py`: shared gate error formatter used by Stage3 and Stage4.
- Modify `scripts/stage2_5_injector.py`: structured injection summary, metadata-only update for same-value manual input, clearer fund-flow forced-estimate details, manual previous-value change recalculation.
- Modify `scripts/stage3_pring_analyzer.py`: use `gate_formatting` for blocker output.
- Modify `scripts/stage4_report_generator.py`: use `gate_formatting` for Stage4 quality errors.
- Modify `src/datasource/generators/simple_report.py`: stock index compatibility display, estimated category reminder, low-confidence change display.
- Modify docs and templates: `AGENTS.md`, `CLAUDE.md`, `data/runs/templates/manual_template.json`.
- Tests:
  - Modify `tests/test_runtime_env.py`
  - Create `tests/test_bootstrap_venv.py`
  - Create `tests/test_run_clean_env.py`
  - Create `tests/test_preflight_proxy.py`
  - Create `tests/test_tavily_client.py`
  - Create `tests/test_source_trust.py`
  - Modify `tests/test_stage2_unified.py`
  - Modify `tests/test_websearch_injector.py`
  - Create `tests/test_gate_formatting.py`
  - Modify `tests/test_stage3_guard.py`
  - Modify `tests/test_stage4_docs.py`
  - Modify `tests/test_simple_report_integration.py`

Run all commands from the isolated worktree:

```bash
cd /mnt/d/cursor/datasource/.worktrees/report-generation-vpn-hardening
```

Baseline already verified before this plan:

```bash
bash run_clean.sh python -m pytest -q tests/test_runtime_env.py
# Expected: 16 passed

bash run_clean.sh python -c "from datasource import get_manager; print('OK')"
# Expected: OK
```

### Task 1: Bootstrap Empty `.venv`

**Files:**
- Create: `scripts/bootstrap_venv.sh`
- Create: `tests/test_bootstrap_venv.py`
- Modify: `tests/test_runtime_env.py`
- Modify: `scripts/runtime_env.sh`

- [ ] **Step 1: Write failing bootstrap script tests**

Create `tests/test_bootstrap_venv.py` with:

```python
import os
import subprocess
from pathlib import Path


def _write_fake_python(root: Path) -> Path:
    fake_bin = root / "fake-bin"
    fake_bin.mkdir()
    python = fake_bin / "python3"
    python.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [ \"${1:-}\" = \"-m\" ] && [ \"${2:-}\" = \"venv\" ]; then\n"
        "  mkdir -p \"$3/bin\"\n"
        "  cat > \"$3/bin/python\" <<'SH'\n"
        "#!/usr/bin/env bash\n"
        "printf 'venv-python %s\\n' \"$*\"\n"
        "SH\n"
        "  chmod +x \"$3/bin/python\"\n"
        "  cat > \"$3/bin/activate\" <<'SH'\n"
        "export VIRTUAL_ENV=\"$(pwd)/.venv\"\n"
        "SH\n"
        "  exit 0\n"
        "fi\n"
        "printf 'fake-python %s\\n' \"$*\"\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return fake_bin


def _copy_bootstrap(root: Path) -> Path:
    scripts = root / "scripts"
    scripts.mkdir()
    source = Path("scripts/bootstrap_venv.sh")
    target = scripts / "bootstrap_venv.sh"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    target.chmod(0o755)
    return target


def test_bootstrap_venv_creates_stamp_without_loading_env(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _copy_bootstrap(root)
    (root / "requirements.txt").write_text("", encoding="utf-8")
    (root / "setup.py").write_text("from setuptools import setup\nsetup(name='x')\n", encoding="utf-8")
    fake_bin = _write_fake_python(root)

    result = subprocess.run(
        ["bash", "scripts/bootstrap_venv.sh", "--no-install"],
        cwd=root,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert (root / ".venv" / "bin" / "python").exists()
    assert (root / ".venv" / ".datasource_bootstrapped").exists()
    assert ".env" not in result.stdout


def test_bootstrap_venv_failure_writes_failed_stamp(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _copy_bootstrap(root)
    (root / "requirements.txt").write_text("definitely-missing-package-for-test==0\n", encoding="utf-8")
    (root / "setup.py").write_text("from setuptools import setup\nsetup(name='x')\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/bootstrap_venv.sh"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=120,
    )

    assert result.returncode != 0
    assert (root / ".venv" / ".datasource_bootstrap_failed").exists()
    assert "bootstrap failed" in result.stdout.lower()
```

- [ ] **Step 2: Run bootstrap tests to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_bootstrap_venv.py
```

Expected: FAIL because `scripts/bootstrap_venv.sh` does not exist.

- [ ] **Step 3: Create bootstrap script**

Create `scripts/bootstrap_venv.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

NO_INSTALL=0
if [ "${1:-}" = "--no-install" ]; then
  NO_INSTALL=1
fi

STAMP=".venv/.datasource_bootstrapped"
FAILED=".venv/.datasource_bootstrap_failed"

_hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    python3 - "$1" <<'PY'
import hashlib, pathlib, sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
  fi
}

_write_stamp() {
  {
    printf 'python=%s\n' "$(".venv/bin/python" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || printf unknown)"
    if [ -f requirements.txt ]; then
      printf 'requirements_sha256=%s\n' "$(_hash_file requirements.txt)"
    fi
    if [ -f setup.py ]; then
      printf 'setup_mtime=%s\n' "$(stat -c %Y setup.py 2>/dev/null || stat -f %m setup.py)"
    fi
  } > "$STAMP"
  rm -f "$FAILED"
}

_fail() {
  mkdir -p .venv
  printf 'bootstrap failed at %s\n' "$(date -Iseconds)" > "$FAILED"
  echo "[ERROR] bootstrap failed: $*" >&2
  exit 1
}

if [ -e "$FAILED" ]; then
  echo "[ERROR] Previous venv bootstrap failed. Remove .venv or rerun scripts/bootstrap_venv.sh after fixing the cause." >&2
  exit 1
fi

if [ -d .venv ] && [ -n "$(find .venv -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ] && [ ! -x .venv/bin/python ]; then
  echo "[ERROR] .venv exists but is not a usable Linux virtualenv. Remove it and rerun bootstrap." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  command -v python3 >/dev/null 2>&1 || _fail "python3 not found"
  python3 -m venv .venv || _fail "python3 -m venv .venv"
fi

if [ "$NO_INSTALL" = "0" ]; then
  if [ -f requirements.txt ]; then
    .venv/bin/python -m pip install -r requirements.txt || _fail "pip install -r requirements.txt"
  fi
  .venv/bin/python -m pip install -e . || _fail "pip install -e ."
  if [ "${DATASOURCE_INSTALL_DEV:-}" = "1" ]; then
    .venv/bin/python -m pip install -e ".[dev]" || _fail "pip install -e .[dev]"
  fi
fi

_write_stamp
echo "[OK] .venv bootstrap complete"
```

Make it executable:

```bash
chmod +x scripts/bootstrap_venv.sh
```

- [ ] **Step 4: Run bootstrap tests to verify pass**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_bootstrap_venv.py
```

Expected: PASS.

- [ ] **Step 5: Write failing runtime auto-venv tests**

Append to `tests/test_runtime_env.py`:

```python
def test_runtime_env_empty_venv_auto_bootstraps_when_enabled(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    (root / ".venv").mkdir()
    scripts = root / "scripts"
    (scripts / "bootstrap_venv.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "mkdir -p .venv/bin\n"
        "cat > .venv/bin/activate <<'SH'\n"
        "export RUNTIME_ACTIVATE=auto\n"
        "SH\n"
        "cat > .venv/bin/python <<'SH'\n"
        "#!/usr/bin/env bash\n"
        "printf 'auto-python\\n'\n"
        "SH\n"
        "chmod +x .venv/bin/python\n"
        "printf 'bootstrapped\\n'\n",
        encoding="utf-8",
    )
    (scripts / "bootstrap_venv.sh").chmod(0o755)

    result = _run_source(
        root,
        "printf '%s|%s\\n' \"$RUNTIME_ACTIVATE\" \"$DATASOURCE_PYTHON\"",
        env={"DATASOURCE_AUTO_VENV": "1"},
    )

    assert result.returncode == 0, result.stdout
    assert "bootstrapped" in result.stdout
    assert result.stdout.strip().splitlines()[-1].endswith("|" + _bash_path(str(root / ".venv" / "bin" / "python")))


def test_runtime_env_empty_venv_without_auto_still_requires_fallback(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    (root / ".venv").mkdir()

    result = _run_source(root, "printf 'should-not-run\\n'")

    assert result.returncode != 0
    assert "DATASOURCE_AUTO_VENV=1" in result.stdout
    assert "should-not-run" not in result.stdout
```

- [ ] **Step 6: Run runtime tests to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_runtime_env.py::test_runtime_env_empty_venv_auto_bootstraps_when_enabled tests/test_runtime_env.py::test_runtime_env_empty_venv_without_auto_still_requires_fallback
```

Expected: FAIL because `runtime_env.sh` does not call bootstrap and does not mention `DATASOURCE_AUTO_VENV=1`.

- [ ] **Step 7: Update `scripts/runtime_env.sh` for empty `.venv` auto bootstrap**

In `scripts/runtime_env.sh`, replace the `.venv` detection block from `if [ -f ".venv/bin/activate" ]; then` through the `elif [ -d ".venv" ]; then ... fi` block with:

```bash
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
  if [ -z "$(find ".venv" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
    if [ "${DATASOURCE_AUTO_VENV:-}" = "1" ]; then
      if [ ! -x "scripts/bootstrap_venv.sh" ]; then
        echo "[ERROR] DATASOURCE_AUTO_VENV=1 but scripts/bootstrap_venv.sh is missing or not executable"
        return 1 2>/dev/null || exit 1
      fi
      scripts/bootstrap_venv.sh || return 1 2>/dev/null || exit 1
      if [ -f ".venv/bin/activate" ]; then
        VENV_ACTIVATE=".venv/bin/activate"
        VENV_PYTHON="$DATASOURCE_RUNTIME_DIR/.venv/bin/python"
      fi
    fi
  else
    echo "[ERROR] .venv exists but no usable activate script found"
    echo "[ERROR] Recreate it with: python -m venv .venv"
    return 1 2>/dev/null || exit 1
  fi
fi
```

Then replace the missing venv error block with:

```bash
else
  echo "[ERROR] Missing virtual environment. Run: python -m venv .venv"
  echo "[ERROR] To auto-bootstrap an empty .venv in Ubuntu/Claude Code, set DATASOURCE_AUTO_VENV=1"
  echo "[ERROR] To use current system Python explicitly, set ALLOW_SYSTEM_PYTHON=1"
  return 1 2>/dev/null || exit 1
fi
```

- [ ] **Step 8: Run runtime bootstrap tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_bootstrap_venv.py tests/test_runtime_env.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/bootstrap_venv.sh scripts/runtime_env.sh tests/test_bootstrap_venv.py tests/test_runtime_env.py
git commit -m "fix: bootstrap empty venv for ubuntu agents"
```

### Task 2: Proxy Isolation In Runtime, Run Clean, And Preflight

**Files:**
- Modify: `scripts/runtime_env.sh`
- Modify: `run_clean.sh`
- Modify: `run_preflight.sh`
- Create: `tests/test_run_clean_env.py`
- Create: `tests/test_preflight_proxy.py`
- Modify: `tests/test_runtime_env.py`

- [ ] **Step 1: Extend runtime proxy test**

Modify `test_runtime_env_clears_active_proxies_and_keeps_no_proxy` in `tests/test_runtime_env.py` to print and assert all proxy variables:

```python
result = _run_source(
    root,
    (
        "printf '%s|%s|%s|%s|%s\\n' "
        "\"${http_proxy:-}\" \"${HTTPS_PROXY:-}\" \"${ALL_PROXY:-}\" "
        "\"${all_proxy:-}\" \"${NO_PROXY:-}\""
    ),
    env={
        "ALLOW_SYSTEM_PYTHON": "1",
        "http_proxy": "http://proxy.local:8080",
        "HTTPS_PROXY": "http://secure-proxy.local:8080",
        "ALL_PROXY": "socks5h://127.0.0.1:7890",
        "all_proxy": "socks5h://127.0.0.1:7891",
        "NO_PROXY": "localhost,127.0.0.1",
    },
    path_prefix=str(fake_python),
)

assert result.returncode == 0, result.stdout
assert result.stdout.strip().splitlines()[-1] == "||||localhost,127.0.0.1"
```

- [ ] **Step 2: Run runtime proxy test to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_runtime_env.py::test_runtime_env_clears_active_proxies_and_keeps_no_proxy
```

Expected: FAIL because `ALL_PROXY/all_proxy` are not cleared.

- [ ] **Step 3: Clear all active proxy variables in runtime**

In `scripts/runtime_env.sh`, replace:

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
```

with:

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
```

- [ ] **Step 4: Add `run_clean.sh` environment test**

Create `tests/test_run_clean_env.py`:

```python
import os
import subprocess
from pathlib import Path


def _copy_runtime_files(root: Path) -> None:
    (root / "scripts").mkdir()
    for path in ("scripts/runtime_env.sh", "run_clean.sh"):
        src = Path(path)
        dst = root / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        dst.chmod(0o755)
    (root / ".env").write_text(
        "TUSHARE_TOKEN=xxxxxxxxxxxxxxxxxxxx\n"
        "TAVILY_API_KEY=yyyyyyyyyyyyyyyyyyyy\n"
        "DEEPSEEK_API_KEY=zzzzzzzzzzzzzzzzzzzz\n",
        encoding="utf-8",
    )
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text("export VIRTUAL_ENV=.venv\n", encoding="utf-8")
    (bin_dir / "python").write_text("#!/usr/bin/env bash\nexec python3 \"$@\"\n", encoding="utf-8")
    (bin_dir / "python").chmod(0o755)


def test_run_clean_removes_all_active_proxy_vars(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _copy_runtime_files(root)

    result = subprocess.run(
        [
            "bash",
            "run_clean.sh",
            "bash",
            "-lc",
            "printf '%s|%s|%s|%s|%s\\n' \"${http_proxy:-}\" \"${HTTPS_PROXY:-}\" \"${ALL_PROXY:-}\" \"${all_proxy:-}\" \"${NO_PROXY:-}\"",
        ],
        cwd=root,
        env={
            **os.environ,
            "http_proxy": "http://proxy.local:8080",
            "HTTPS_PROXY": "http://secure-proxy.local:8080",
            "ALL_PROXY": "socks5h://127.0.0.1:7890",
            "all_proxy": "socks5h://127.0.0.1:7891",
            "NO_PROXY": "localhost,127.0.0.1",
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == "||||localhost,127.0.0.1"
```

- [ ] **Step 5: Run run_clean test to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_run_clean_env.py
```

Expected: FAIL because `run_clean.sh` still passes `ALL_PROXY/all_proxy`.

- [ ] **Step 6: Update `run_clean.sh`**

Replace the final `exec env` with:

```bash
exec env \
  -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  -u ALL_PROXY -u all_proxy \
  PYTHONPATH="$PYTHONPATH" "$@"
```

- [ ] **Step 7: Add preflight proxy helper tests**

Create `tests/test_preflight_proxy.py`:

```python
import os
import subprocess
from pathlib import Path


def _copy_preflight(root: Path) -> None:
    (root / "scripts").mkdir()
    for path in ("scripts/runtime_env.sh", "run_preflight.sh"):
        src = Path(path)
        dst = root / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        dst.chmod(0o755)
    (root / ".env").write_text(
        "TUSHARE_TOKEN=xxxxxxxxxxxxxxxxxxxx\n"
        "TAVILY_API_KEY=yyyyyyyyyyyyyyyyyyyy\n"
        "DEEPSEEK_API_KEY=zzzzzzzzzzzzzzzzzzzz\n",
        encoding="utf-8",
    )
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text("export VIRTUAL_ENV=.venv\n", encoding="utf-8")
    (bin_dir / "python").write_text("#!/usr/bin/env bash\npython3 \"$@\"\n", encoding="utf-8")
    (bin_dir / "python").chmod(0o755)


def test_preflight_direct_mode_reports_proxy_cleared(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _copy_preflight(root)

    result = subprocess.run(
        ["bash", "-lc", "source scripts/runtime_env.sh; _report_proxy_state"],
        cwd=root,
        env={**os.environ, "ALL_PROXY": "socks5h://127.0.0.1:7890"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "Network mode: direct" in result.stdout
    assert "Proxy cleared" in result.stdout


def test_preflight_proxy_mode_requires_socksio_for_socks_proxy(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _copy_preflight(root)

    result = subprocess.run(
        [
            "bash",
            "-lc",
            "source scripts/runtime_env.sh; export DATASOURCE_NETWORK_MODE=proxy; export HTTPS_PROXY=socks5h://127.0.0.1:7890; _check_proxy_mode",
        ],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode != 0
    assert "SOCKS proxy requires" in result.stdout
```

- [ ] **Step 8: Run preflight proxy tests to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_preflight_proxy.py
```

Expected: FAIL because `_report_proxy_state` and `_check_proxy_mode` do not exist.

- [ ] **Step 9: Add preflight proxy helpers**

In `run_preflight.sh`, after timeout variable setup, add:

```bash
DATASOURCE_NETWORK_MODE="${DATASOURCE_NETWORK_MODE:-direct}"

_active_proxy_lines() {
  env | grep -Ei '^(http_proxy|https_proxy|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|all_proxy)=' || true
}

_report_proxy_state() {
  echo "[OK] Network mode: $DATASOURCE_NETWORK_MODE"
  if [ -n "$(_active_proxy_lines)" ]; then
    echo "[INFO] Active proxy variables:"
    _active_proxy_lines
  else
    echo "Proxy cleared"
  fi
}

_check_proxy_mode() {
  if [ "$DATASOURCE_NETWORK_MODE" != "proxy" ]; then
    return 0
  fi
  proxy_text="$(_active_proxy_lines)"
  if echo "$proxy_text" | grep -Eiq 'socks5?h?://|socks://'; then
    if ! "$DATASOURCE_PYTHON" - <<'PY'
try:
    import socksio  # noqa: F401
except Exception:
    raise SystemExit(1)
PY
    then
      echo "[FAIL] SOCKS proxy requires socksio/httpx[socks]. Install SOCKS support or use DATASOURCE_NETWORK_MODE=direct."
      return 1
    fi
  fi
}
```

Before DNS checks, call:

```bash
_check_proxy_mode
_report_proxy_state
```

At the end, replace the old proxy output line with no extra output because `_report_proxy_state` already reports it.

- [ ] **Step 10: Run proxy tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_runtime_env.py::test_runtime_env_clears_active_proxies_and_keeps_no_proxy tests/test_run_clean_env.py tests/test_preflight_proxy.py
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add scripts/runtime_env.sh run_clean.sh run_preflight.sh tests/test_runtime_env.py tests/test_run_clean_env.py tests/test_preflight_proxy.py
git commit -m "fix: isolate runtime from vpn proxy variables"
```

### Task 3: Tavily Client `trust_env=False`

**Files:**
- Modify: `src/datasource/adapters/tavily_client.py`
- Create: `tests/test_tavily_client.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: Write failing Tavily trust_env tests**

Create `tests/test_tavily_client.py`:

```python
import pytest

from datasource.adapters import tavily_client as module
from datasource.adapters.tavily_client import AsyncTavilyClient


class _FakeTimeout:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeAsyncClient:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__class__.calls.append(kwargs)

    async def aclose(self):
        return None


def test_tavily_client_defaults_trust_env_false(monkeypatch):
    fake_httpx = type("FakeHttpx", (), {"Timeout": _FakeTimeout, "AsyncClient": _FakeAsyncClient})
    _FakeAsyncClient.calls.clear()
    monkeypatch.setattr(module, "httpx", fake_httpx)

    client = AsyncTavilyClient(api_key="k")

    async def _run():
        async with client:
            pass

    import asyncio
    asyncio.run(_run())

    assert _FakeAsyncClient.calls[-1]["trust_env"] is False


def test_tavily_client_allows_explicit_trust_env(monkeypatch):
    fake_httpx = type("FakeHttpx", (), {"Timeout": _FakeTimeout, "AsyncClient": _FakeAsyncClient})
    _FakeAsyncClient.calls.clear()
    monkeypatch.setattr(module, "httpx", fake_httpx)

    client = AsyncTavilyClient(api_key="k", trust_env=True)

    async def _run():
        await client._ensure_client()

    import asyncio
    asyncio.run(_run())

    assert _FakeAsyncClient.calls[-1]["trust_env"] is True
```

- [ ] **Step 2: Run Tavily tests to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_tavily_client.py
```

Expected: FAIL because `trust_env` is not accepted or not passed to `httpx.AsyncClient`.

- [ ] **Step 3: Implement `trust_env` in Tavily client**

In `AsyncTavilyClient.__init__`, add parameter and assignment:

```python
        trust_env: bool = False,
```

and:

```python
        self.trust_env = trust_env
```

In both `httpx.AsyncClient` construction sites, pass `trust_env=self.trust_env`:

```python
self._client = httpx.AsyncClient(
    timeout=timeout_cfg,
    proxies=self.proxies,
    verify=self.verify,
    trust_env=self.trust_env,
)
```

In the `except TypeError` fallbacks, also pass `trust_env=self.trust_env`:

```python
self._client = httpx.AsyncClient(timeout=timeout_cfg, verify=self.verify, trust_env=self.trust_env)
```

- [ ] **Step 4: Wire explicit proxy mode in Stage2**

In `scripts/stage2_unified_enhancer.py`, when constructing `AsyncTavilyClient`, pass:

```python
        trust_env=(os.getenv("DATASOURCE_NETWORK_MODE", "direct").lower() == "proxy"),
```

The block should become:

```python
    tavily = AsyncTavilyClient(
        api_key=os.getenv("TAVILY_API_KEY"),
        cache=cache,
        timeout=args.read_timeout,
        connect_timeout=args.connect_timeout,
        max_concurrency=4,
        proxies=proxies or None,
        trust_env=(os.getenv("DATASOURCE_NETWORK_MODE", "direct").lower() == "proxy"),
    )
```

- [ ] **Step 5: Run Tavily tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_tavily_client.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/datasource/adapters/tavily_client.py scripts/stage2_unified_enhancer.py tests/test_tavily_client.py
git commit -m "fix: disable environment proxy use in tavily client"
```

### Task 4: Stage2 Proxy Error Fast-Fail

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Modify: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write failing helper tests**

Append to `tests/test_stage2_unified.py`:

```python
import scripts.stage2_unified_enhancer as s2


def test_is_environment_proxy_error_detects_missing_socksio_message():
    exc = RuntimeError("Using SOCKS proxy, but the 'socksio' package is not installed")

    assert s2._is_environment_proxy_error(exc) is True


def test_environment_proxy_fast_switch_records_manual_required():
    task = {"indicator_key": "USDCNY", "task_id": "task-usdcny", "category": "forex"}

    task_record, websearch_item = s2._build_environment_proxy_error_records(
        task,
        RuntimeError("Using SOCKS proxy, but the 'socksio' package is not installed"),
    )

    assert task_record["manual_required"] is True
    assert task_record["manual_reason"] == "environment_proxy_error"
    assert task_record["result_type"] == "manual_required"
    assert websearch_item["manual_required"] is True
    assert websearch_item["extraction"]["manual_reason"] == "environment_proxy_error"
```

- [ ] **Step 2: Run helper tests to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_stage2_unified.py::test_is_environment_proxy_error_detects_missing_socksio_message tests/test_stage2_unified.py::test_environment_proxy_fast_switch_records_manual_required
```

Expected: FAIL because helpers do not exist.

- [ ] **Step 3: Add environment proxy helper functions**

In `scripts/stage2_unified_enhancer.py`, near `_is_tavily_quota_error`, add:

```python
def _is_environment_proxy_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "using socks proxy",
            "socksio",
            "proxyerror",
            "proxy error",
            "proxyconnect",
        )
    )


def _build_environment_proxy_error_records(
    task: Dict[str, Any],
    exc: Exception,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    indicator = task.get("indicator_key")
    note = f"environment_proxy_error:{exc}"
    extraction = {
        "value": None,
        "source_url": None,
        "confidence": 0.0,
        "note": note,
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "llm_timeout": False,
        "llm_error": note,
    }
    task_record = {
        **task,
        "result_type": "manual_required",
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "extraction": extraction,
    }
    websearch_item = {
        "task": task,
        "indicator_key": indicator,
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "source": "Stage2 manual_required",
        "extraction": extraction,
    }
    return task_record, websearch_item
```

- [ ] **Step 4: Wire fast-fail in Stage2 task loop**

Inside `execute_tasks`, define:

```python
    def _mark_environment_proxy_unavailable(exc: Exception) -> None:
        nonlocal tavily_unavailable_reason
        tavily_unavailable_reason = "environment_proxy_error"
        stats["tavily_unavailable_reason"] = "environment_proxy_error"
        stats["environment_proxy_error"] = str(exc)
```

In exception handlers that currently check `_is_tavily_quota_error(exc)`, add this branch before quota handling:

```python
if _is_environment_proxy_error(exc):
    _mark_environment_proxy_unavailable(exc)
    task_record, websearch_item = _build_environment_proxy_error_records(task, exc)
    task_results.append(task_record)
    websearch_results.append(websearch_item)
    manual_required_keys.append(task_record["indicator_key"])
    return task_record
```

Near the existing `if tavily_unavailable_reason == "quota_or_rate_limit":` branch, add:

```python
if tavily_unavailable_reason == "environment_proxy_error":
    exc = RuntimeError(stats.get("environment_proxy_error", "environment_proxy_error"))
    task_record, websearch_item = _build_environment_proxy_error_records(task, exc)
    task_results.append(task_record)
    websearch_results.append(websearch_item)
    manual_required_keys.append(task_record["indicator_key"])
    return task_record
```

- [ ] **Step 5: Run Stage2 helper tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_stage2_unified.py::test_is_environment_proxy_error_detects_missing_socksio_message tests/test_stage2_unified.py::test_environment_proxy_fast_switch_records_manual_required
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "fix: fast fail stage2 on proxy environment errors"
```

### Task 5: Stage2 Official Source Trust Normalization

**Files:**
- Create: `src/datasource/utils/source_trust.py`
- Create: `tests/test_source_trust.py`
- Modify: `scripts/stage2_unified_enhancer.py`
- Modify: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write source trust tests**

Create `tests/test_source_trust.py`:

```python
from datasource.utils.source_trust import (
    is_official_source_url,
    source_url_in_snippets,
    should_mark_official_non_estimated,
)


def test_is_official_source_url_matches_subdomains():
    assert is_official_source_url("https://data.stats.gov.cn/easyquery.htm")
    assert is_official_source_url("https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/index.html")
    assert is_official_source_url("https://www.chinamoney.com.cn/chinese/bkcurv/")
    assert not is_official_source_url("https://finance.sina.com.cn/news.html")


def test_source_url_in_snippets_uses_normalized_url():
    snippets = [{"url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260515_123.html?x=1"}]

    assert source_url_in_snippets(
        "https://www.stats.gov.cn/sj/zxfb/202605/t20260515_123.html",
        snippets,
    )


def test_should_mark_official_non_estimated_requires_period_and_unit():
    task = {"expected_period": "2026-04", "unit_hint": "%"}
    extraction = {
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260515_123.html",
        "report_period": "2026-04",
        "unit": "%",
        "value": 1.2,
    }
    snippets = [{"url": extraction["source_url"], "content": "2026年4月 CPI 同比上涨 1.2%"}]

    decision = should_mark_official_non_estimated(task, extraction, snippets)

    assert decision.allowed is True
    assert decision.reason == "official_source_period_unit_match"


def test_should_mark_official_non_estimated_rejects_fund_flow():
    task = {"category": "fund_flow", "indicator_key": "northbound"}
    extraction = {
        "source_url": "https://www.hkex.com.hk/",
        "report_period": "2026-05-20",
        "unit": "亿元",
        "value": 20.0,
    }
    snippets = [{"url": extraction["source_url"], "content": "northbound"}]

    decision = should_mark_official_non_estimated(task, extraction, snippets)

    assert decision.allowed is False
    assert decision.reason == "fund_flow_requires_window_gate"
```

- [ ] **Step 2: Run source trust tests to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_source_trust.py
```

Expected: FAIL because `source_trust.py` does not exist.

- [ ] **Step 3: Implement source trust helper**

Create `src/datasource/utils/source_trust.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse, urlunparse


OFFICIAL_SOURCE_DOMAINS = {
    "stats.gov.cn",
    "data.stats.gov.cn",
    "pbc.gov.cn",
    "chinamoney.com.cn",
    "cfets.com.cn",
    "hkex.com.hk",
    "sse.com.cn",
    "szse.cn",
}


@dataclass(frozen=True)
class OfficialSourceDecision:
    allowed: bool
    reason: str


def _hostname(url: Any) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.hostname and "://" not in text:
        parsed = urlparse(f"//{text}")
    return (parsed.hostname or "").lower().rstrip(".")


def _normalized_url(url: Any) -> str:
    text = str(url or "").strip()
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return text.rstrip("/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", ""))


def is_official_source_url(url: Any) -> bool:
    host = _hostname(url)
    return any(host == domain or host.endswith(f".{domain}") for domain in OFFICIAL_SOURCE_DOMAINS)


def source_url_in_snippets(source_url: Any, snippets: Iterable[Dict[str, Any]]) -> bool:
    target = _normalized_url(source_url)
    if not target:
        return False
    for snippet in snippets or []:
        if _normalized_url(snippet.get("url")) == target:
            return True
    return False


def _period_matches(task: Dict[str, Any], extraction: Dict[str, Any]) -> bool:
    expected = task.get("expected_period") or task.get("expected_date") or task.get("ref_date")
    if not expected:
        return True
    candidates = (
        extraction.get("report_period"),
        extraction.get("as_of_date"),
        extraction.get("date"),
    )
    expected_text = str(expected)
    for candidate in candidates:
        if candidate and str(candidate).startswith(expected_text[:7]):
            return True
    return False


def _unit_matches(task: Dict[str, Any], extraction: Dict[str, Any]) -> bool:
    hint = str(task.get("unit_hint") or "").strip()
    if not hint:
        return True
    unit = str(extraction.get("unit") or "").strip()
    return bool(unit) and hint in unit


def should_mark_official_non_estimated(
    task: Dict[str, Any],
    extraction: Dict[str, Any],
    snippets: Iterable[Dict[str, Any]],
) -> OfficialSourceDecision:
    if str(task.get("category") or "").lower() == "fund_flow":
        return OfficialSourceDecision(False, "fund_flow_requires_window_gate")
    source_url = extraction.get("source_url")
    if not is_official_source_url(source_url):
        return OfficialSourceDecision(False, "source_url_not_official")
    if not source_url_in_snippets(source_url, snippets):
        return OfficialSourceDecision(False, "source_url_not_in_snippets")
    if extraction.get("value") is None:
        return OfficialSourceDecision(False, "missing_value")
    if not _period_matches(task, extraction):
        return OfficialSourceDecision(False, "period_mismatch")
    if not _unit_matches(task, extraction):
        return OfficialSourceDecision(False, "unit_mismatch")
    return OfficialSourceDecision(True, "official_source_period_unit_match")
```

- [ ] **Step 4: Run source trust tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_source_trust.py
```

Expected: PASS.

- [ ] **Step 5: Write Stage2 normalization test**

Append to `tests/test_stage2_unified.py`:

```python
def test_apply_extraction_marks_official_macro_source_not_estimated():
    payload = {
        "macro_indicators": {
            "cpi": {
                "indicator_name": "CPI",
                "current_value": None,
                "unit": "%",
                "is_estimated": True,
            }
        },
        "metadata": {"date": "2026-05-21"},
    }
    task = {
        "indicator_key": "cpi",
        "category": "macro_indicators",
        "expected_period": "2026-04",
        "unit_hint": "%",
        "task_id": "task-cpi",
    }
    extraction = {
        "value": 1.2,
        "unit": "%",
        "report_period": "2026-04",
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260515_123.html",
        "snippets": [
            {
                "url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260515_123.html",
                "content": "2026年4月 CPI 同比上涨 1.2%",
            }
        ],
    }

    target = s2._apply_extraction(payload, task, extraction)

    assert target == "macro_indicators"
    assert payload["macro_indicators"]["cpi"]["is_estimated"] is False
    assert "official_source_period_unit_match" in payload["macro_indicators"]["cpi"]["note"]
```

- [ ] **Step 6: Run Stage2 normalization test to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_stage2_unified.py::test_apply_extraction_marks_official_macro_source_not_estimated
```

Expected: FAIL because `_apply_extraction` does not call source trust helper.

- [ ] **Step 7: Wire helper into `_apply_extraction`**

At the top of `scripts/stage2_unified_enhancer.py`, import:

```python
from datasource.utils.source_trust import should_mark_official_non_estimated
```

Inside `_apply_extraction`, after `_write_common_fields(entry, "current_value")` in macro and monetary branches, add:

```python
        official_decision = should_mark_official_non_estimated(
            task,
            extraction,
            extraction.get("snippets") or task.get("snippets") or [],
        )
        if official_decision.allowed:
            entry["is_estimated"] = False
            entry["note"] = " ".join(
                part for part in (str(entry.get("note") or ""), official_decision.reason) if part
            ).strip()
```

Do not add this block to fund_flow.

- [ ] **Step 8: Run Stage2 and source trust tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_source_trust.py tests/test_stage2_unified.py::test_apply_extraction_marks_official_macro_source_not_estimated
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/datasource/utils/source_trust.py scripts/stage2_unified_enhancer.py tests/test_source_trust.py tests/test_stage2_unified.py
git commit -m "fix: trust official stage2 evidence as non estimated"
```

### Task 6: DeepSeek Timeout Circuit Breaker

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Modify: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write circuit breaker tests**

Append to `tests/test_stage2_unified.py`:

```python
def test_deepseek_circuit_breaker_triggers_on_consecutive_timeouts():
    state = s2._DeepSeekCircuitBreaker(max_consecutive_timeouts=3, max_timeout_rate=0.5, min_attempts=4)

    state.record(timeout=True)
    state.record(timeout=True)
    assert state.triggered is False
    state.record(timeout=True)

    assert state.triggered is True
    assert state.reason == "consecutive_timeouts"


def test_deepseek_circuit_breaker_triggers_on_timeout_rate():
    state = s2._DeepSeekCircuitBreaker(max_consecutive_timeouts=10, max_timeout_rate=0.5, min_attempts=4)

    state.record(timeout=True)
    state.record(timeout=False)
    state.record(timeout=True)
    state.record(timeout=True)

    assert state.triggered is True
    assert state.reason == "timeout_rate"
    assert state.timeout_rate == 0.75
```

- [ ] **Step 2: Run circuit breaker tests to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_stage2_unified.py::test_deepseek_circuit_breaker_triggers_on_consecutive_timeouts tests/test_stage2_unified.py::test_deepseek_circuit_breaker_triggers_on_timeout_rate
```

Expected: FAIL because `_DeepSeekCircuitBreaker` does not exist.

- [ ] **Step 3: Add circuit breaker class**

In `scripts/stage2_unified_enhancer.py`, near Stage2 stats helpers, add:

```python
class _DeepSeekCircuitBreaker:
    def __init__(
        self,
        *,
        max_consecutive_timeouts: int = 3,
        max_timeout_rate: float = 0.5,
        min_attempts: int = 4,
    ) -> None:
        self.max_consecutive_timeouts = max_consecutive_timeouts
        self.max_timeout_rate = max_timeout_rate
        self.min_attempts = min_attempts
        self.attempts = 0
        self.timeouts = 0
        self.consecutive_timeouts = 0
        self.triggered = False
        self.reason: Optional[str] = None

    @property
    def timeout_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return round(self.timeouts / self.attempts, 4)

    def record(self, *, timeout: bool) -> None:
        if self.triggered:
            return
        self.attempts += 1
        if timeout:
            self.timeouts += 1
            self.consecutive_timeouts += 1
        else:
            self.consecutive_timeouts = 0
        if self.consecutive_timeouts >= self.max_consecutive_timeouts:
            self.triggered = True
            self.reason = "consecutive_timeouts"
        elif self.attempts >= self.min_attempts and self.timeout_rate >= self.max_timeout_rate:
            self.triggered = True
            self.reason = "timeout_rate"
```

- [ ] **Step 4: Wire circuit breaker into DeepSeek extraction**

Inside `execute_tasks`, after `serial_keys = ...`, add:

```python
    deepseek_breaker = _DeepSeekCircuitBreaker()
```

Before each DeepSeek extraction call, if `deepseek_breaker.triggered`, skip DeepSeek:

```python
if deepseek_breaker.triggered:
    skip_deepseek_reason = f"deepseek_circuit_breaker:{deepseek_breaker.reason}"
```

In the `_extract_with_deepseek` exception handling, after computing `is_timeout`, call:

```python
deepseek_breaker.record(timeout=is_timeout)
if deepseek_breaker.triggered:
    stats["deepseek_circuit_breaker_triggered"] = True
    stats["deepseek_circuit_breaker_reason"] = deepseek_breaker.reason
    stats["deepseek_timeout_rate"] = deepseek_breaker.timeout_rate
```

When summary diagnostics are assembled, include:

```python
"deepseek_circuit_breaker_triggered": exec_stats.get("deepseek_circuit_breaker_triggered", False),
"deepseek_circuit_breaker_reason": exec_stats.get("deepseek_circuit_breaker_reason"),
"deepseek_timeout_rate": exec_stats.get("deepseek_timeout_rate", 0.0),
```

- [ ] **Step 5: Run circuit breaker tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_stage2_unified.py::test_deepseek_circuit_breaker_triggers_on_consecutive_timeouts tests/test_stage2_unified.py::test_deepseek_circuit_breaker_triggers_on_timeout_rate
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "fix: add deepseek timeout circuit breaker"
```

### Task 7: Stage2.5 Injection Summary And Metadata-Only Updates

**Files:**
- Modify: `scripts/stage2_5_injector.py`
- Modify: `tests/test_websearch_injector.py`

- [ ] **Step 1: Write summary dataclass tests**

Append to `tests/test_websearch_injector.py`:

```python
import scripts.stage2_5_injector as injector


def test_injection_summary_records_skipped_existing():
    summary = injector.InjectionSummary()

    summary.skipped_existing("macro_indicators", "cpi", "existing_value_present", 1.2, 1.2)

    payload = summary.to_dict()
    assert payload["counts"]["skipped_existing"] == 1
    assert payload["skipped_existing"][0]["category"] == "macro_indicators"
    assert payload["skipped_existing"][0]["key"] == "cpi"


def test_macro_entry_same_value_updates_metadata_without_force():
    entry = {
        "indicator_name": "CPI",
        "current_value": 1.2,
        "previous_value": 1.0,
        "change_rate": 20.0,
        "unit": "%",
        "is_estimated": True,
        "source": "tavily+deepseek",
    }
    payload = {
        "indicator_name": "CPI",
        "current_value": 1.2,
        "previous_value": 1.0,
        "change_rate": 20.0,
        "unit": "%",
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260515_123.html",
        "source": "manual official",
        "is_estimated": False,
    }
    summary = injector.InjectionSummary()

    updated = injector._apply_macro_entry(
        "cpi",
        entry,
        payload,
        "2026-05-21",
        is_manual=True,
        force_override=False,
        summary=summary,
    )

    assert updated is True
    assert entry["source_url"] == payload["source_url"]
    assert entry["is_estimated"] is False
    assert summary.to_dict()["counts"]["metadata_updated"] == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_websearch_injector.py::test_injection_summary_records_skipped_existing tests/test_websearch_injector.py::test_macro_entry_same_value_updates_metadata_without_force
```

Expected: FAIL because `InjectionSummary` and `summary` parameter do not exist.

- [ ] **Step 3: Add `InjectionSummary`**

Near the top of `scripts/stage2_5_injector.py`, add:

```python
@dataclass
class InjectionSummary:
    injected_items: List[Dict[str, Any]] = field(default_factory=list)
    metadata_updated_items: List[Dict[str, Any]] = field(default_factory=list)
    skipped_existing_items: List[Dict[str, Any]] = field(default_factory=list)
    skipped_no_parseable_value_items: List[Dict[str, Any]] = field(default_factory=list)
    forced_override_items: List[Dict[str, Any]] = field(default_factory=list)
    fund_flow_forced_estimated_items: List[Dict[str, Any]] = field(default_factory=list)

    def injected(self, category: str, key: str, reason: str = "injected") -> None:
        self.injected_items.append({"category": category, "key": str(key), "reason": reason})

    def metadata_updated(self, category: str, key: str, reason: str, existing: Any, incoming: Any) -> None:
        self.metadata_updated_items.append(
            {"category": category, "key": str(key), "reason": reason, "existing_value": existing, "incoming_value": incoming}
        )

    def skipped_existing(self, category: str, key: str, reason: str, existing: Any, incoming: Any) -> None:
        self.skipped_existing_items.append(
            {"category": category, "key": str(key), "reason": reason, "existing_value": existing, "incoming_value": incoming}
        )

    def skipped_no_parseable_value(self, category: str, key: str, field: str) -> None:
        self.skipped_no_parseable_value_items.append({"category": category, "key": str(key), "field": field})

    def forced_override(self, category: str, key: str, existing: Any, incoming: Any) -> None:
        self.forced_override_items.append(
            {"category": category, "key": str(key), "reason": "force_override", "existing_value": existing, "incoming_value": incoming}
        )

    def fund_flow_forced_estimated(self, key: str, entry: Dict[str, Any]) -> None:
        self.fund_flow_forced_estimated_items.append(
            {
                "category": "fund_flow",
                "key": str(key),
                "reason": "fund_flow_window_not_direct",
                "source_tier": entry.get("source_tier"),
                "window_evidence": entry.get("window_evidence"),
                "metric_basis": entry.get("metric_basis"),
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "counts": {
                "injected": len(self.injected_items),
                "metadata_updated": len(self.metadata_updated_items),
                "skipped_existing": len(self.skipped_existing_items),
                "skipped_no_parseable_value": len(self.skipped_no_parseable_value_items),
                "forced_override": len(self.forced_override_items),
                "fund_flow_forced_estimated": len(self.fund_flow_forced_estimated_items),
            },
            "injected": self.injected_items,
            "metadata_updated": self.metadata_updated_items,
            "skipped_existing": self.skipped_existing_items,
            "skipped_no_parseable_value": self.skipped_no_parseable_value_items,
            "forced_override": self.forced_override_items,
            "fund_flow_forced_estimated": self.fund_flow_forced_estimated_items,
        }
```

Add imports:

```python
from dataclasses import dataclass, field
```

- [ ] **Step 4: Add metadata-only update helper**

Add helper:

```python
def _same_numeric_value(left: Any, right: Any) -> bool:
    left_num = _coerce_float(left)
    right_num = _coerce_float(right)
    return left_num is not None and right_num is not None and abs(left_num - right_num) < 1e-9


def _update_metadata_only(entry: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    changed = False
    for field in ("source_url", "date", "as_of_date", "report_period", "note", "confidence", "estimation_method"):
        if field in payload and payload.get(field) not in (None, "") and entry.get(field) != payload.get(field):
            entry[field] = payload.get(field)
            changed = True
    if "source" in payload and payload.get("source"):
        source = _format_source_label(payload.get("source"))
        if entry.get("source") != source:
            entry["source"] = source
            changed = True
    if "is_estimated" in payload:
        estimated = _coerce_bool(payload.get("is_estimated"))
        if entry.get("is_estimated") is not estimated:
            entry["is_estimated"] = estimated
            changed = True
    return changed
```

In `_apply_macro_entry` and `_apply_monetary_entry`, add optional parameter:

```python
    summary: Optional[InjectionSummary] = None,
```

Replace the early skip block with:

```python
    incoming_value = _coerce_float(payload.get("current_value"))
    if not force_override and not existing_placeholder and not (override_stale and existing_stale):
        if _same_numeric_value(entry.get("current_value"), incoming_value) and _update_metadata_only(entry, payload):
            if summary:
                summary.metadata_updated("macro_indicators", indicator_key, "existing_value_equal_metadata_updated", entry.get("current_value"), incoming_value)
            return True
        if summary:
            summary.skipped_existing("macro_indicators", indicator_key, "existing_value_present", entry.get("current_value"), incoming_value)
        return False
```

Use `"monetary_policy"` and `policy_key` in `_apply_monetary_entry`.

- [ ] **Step 5: Thread summary through `inject_websearch_results`**

At the start of `inject_websearch_results`, add:

```python
    summary = InjectionSummary()
```

Pass `summary=summary` to `_apply_macro_entry` and `_apply_monetary_entry`.

When a successful injection happens, call:

```python
summary.injected("macro_indicators", key)
```

Use the matching category for monetary, fund_flow, forex, stock_indices, bonds, and commodities.

Before writing output, attach summary:

```python
    market_data.setdefault("metadata", {})["injection_summary"] = summary.to_dict()
```

In final printout, add:

```python
    print(f"  - 元数据更新: {summary.to_dict()['counts']['metadata_updated']}")
    print(f"  - 已有值跳过: {summary.to_dict()['counts']['skipped_existing']}")
    print(f"  - 资金流强制估算: {summary.to_dict()['counts']['fund_flow_forced_estimated']}")
```

- [ ] **Step 6: Run injector summary tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_websearch_injector.py::test_injection_summary_records_skipped_existing tests/test_websearch_injector.py::test_macro_entry_same_value_updates_metadata_without_force
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/stage2_5_injector.py tests/test_websearch_injector.py
git commit -m "fix: report stage25 injection decisions"
```

### Task 8: Fund Flow Forced Estimate Diagnostics

**Files:**
- Modify: `scripts/stage2_5_injector.py`
- Modify: `tests/test_websearch_injector.py`

- [ ] **Step 1: Write forced estimate summary test**

Append to `tests/test_websearch_injector.py`:

```python
def test_fund_flow_forced_estimated_records_summary_details():
    entry = {}
    payload = {
        "recent_5d": 10.0,
        "total_120d": 100.0,
        "trend": "流入",
        "source": "新闻摘要 单日 外推",
        "source_url": "https://finance.sina.com.cn/news.html",
        "is_estimated": False,
        "metric_basis": "news_net_flow",
    }
    summary = injector.InjectionSummary()

    updated = injector._apply_fund_flow_entry(entry, "etf", payload, summary=summary)

    assert updated is True
    assert entry["is_estimated"] is True
    details = summary.to_dict()["fund_flow_forced_estimated"][0]
    assert details["key"] == "etf"
    assert details["source_tier"] == "tier3"
    assert details["metric_basis"] == "news_net_flow"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_websearch_injector.py::test_fund_flow_forced_estimated_records_summary_details
```

Expected: FAIL because `_apply_fund_flow_entry` does not accept `summary`.

- [ ] **Step 3: Update `_apply_fund_flow_entry`**

Change signature:

```python
def _apply_fund_flow_entry(
    entry: Dict[str, Any],
    key: str,
    payload: Dict[str, Any],
    *,
    summary: Optional[InjectionSummary] = None,
) -> bool:
```

After `_normalize_fund_flow_estimation(entry, payload)`, add:

```python
    if entry.get("is_estimated") is True and summary is not None:
        summary.fund_flow_forced_estimated(key, entry)
```

Update call sites to pass `summary=summary`.

- [ ] **Step 4: Run fund flow tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_websearch_injector.py::test_fund_flow_forced_estimated_records_summary_details tests/test_pipeline_quality_state.py::test_pipeline_quality_state_blocks_estimated_fund_flow_with_diagnostics_when_allow_estimated
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/stage2_5_injector.py tests/test_websearch_injector.py
git commit -m "fix: surface fund flow estimate gate details"
```

### Task 9: Shared Gate Formatter For Stage3 And Stage4

**Files:**
- Create: `src/datasource/utils/gate_formatting.py`
- Create: `tests/test_gate_formatting.py`
- Modify: `scripts/stage3_pring_analyzer.py`
- Modify: `scripts/stage4_report_generator.py`
- Modify: `tests/test_stage3_guard.py`
- Modify: `tests/test_stage4_docs.py`

- [ ] **Step 1: Write formatter tests**

Create `tests/test_gate_formatting.py`:

```python
from datasource.utils.gate_formatting import GateBlock, format_gate_blocks, format_quality_issue


def test_format_quality_issue_includes_details():
    issue = {
        "category": "fund_flow",
        "key": "etf",
        "reason": "estimated_not_allowed",
        "details": {
            "source_tier": "tier3",
            "window_evidence": "news_summary",
            "metric_basis": "estimated_net_flow",
        },
    }

    text = format_quality_issue(issue)

    assert text == "fund_flow.etf estimated_not_allowed source_tier=tier3 window_evidence=news_summary metric_basis=estimated_net_flow"


def test_format_gate_blocks_outputs_sections():
    text = format_gate_blocks(
        "Stage3 阻断，以下问题需修复：",
        [
            GateBlock("policy gate", ["fund_flow.etf estimated_not_allowed"]),
            GateBlock("gap_monitor", ["pending: CN10Y_CDB", "manual_required: USDCNY"]),
        ],
    )

    assert "[policy gate]" in text
    assert "- fund_flow.etf estimated_not_allowed" in text
    assert "[gap_monitor]" in text
    assert "- pending: CN10Y_CDB" in text
```

- [ ] **Step 2: Run formatter tests to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_gate_formatting.py
```

Expected: FAIL because `gate_formatting.py` does not exist.

- [ ] **Step 3: Implement formatter**

Create `src/datasource/utils/gate_formatting.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class GateBlock:
    title: str
    items: List[str]


def _detail_text(details: Any) -> str:
    if not isinstance(details, dict):
        return ""
    parts = [f"{key}={value}" for key, value in details.items() if value not in (None, "")]
    return " ".join(parts)


def format_quality_issue(issue: Dict[str, Any]) -> str:
    category = str(issue.get("category") or "unknown")
    key = str(issue.get("key") or "unknown")
    reason = str(issue.get("reason") or "unknown")
    details = _detail_text(issue.get("details"))
    base = f"{category}.{key} {reason}"
    return f"{base} {details}".strip()


def format_gate_blocks(header: str, blocks: Iterable[GateBlock]) -> str:
    lines = [header, ""]
    for block in blocks:
        if not block.items:
            continue
        lines.append(f"[{block.title}]")
        for item in block.items:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip()
```

- [ ] **Step 4: Run formatter tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_gate_formatting.py
```

Expected: PASS.

- [ ] **Step 5: Update Stage3 blocker formatting**

In `scripts/stage3_pring_analyzer.py`, import:

```python
from datasource.utils.gate_formatting import GateBlock, format_gate_blocks, format_quality_issue
```

In `_require_data_completeness`, replace string concatenation with:

```python
    blocks: List[GateBlock] = []
    if completeness < min_completeness:
        blocks.append(
            GateBlock(
                "completeness",
                [f"data_completeness={completeness:.3f} (<{min_completeness})"],
            )
        )

    if quality_blockers:
        blocks.append(
            GateBlock(
                "unified_quality",
                [format_quality_issue(item) for item in quality_blockers],
            )
        )

    if blocks:
        raise RuntimeError(format_gate_blocks("Stage3 阻断，以下问题需修复：", blocks))
```

In `_run_analysis`, replace final `blockers` string rendering with `GateBlock` sections. Build separate lists:

```python
policy_blockers: List[str] = []
gap_blockers: List[str] = []
stage2_blockers: List[str] = []
```

Append policy messages to `policy_blockers`, gap messages to `gap_blockers`, and stage2 flag messages to `stage2_blockers`. At the end:

```python
    if policy_blockers or completeness_error or gap_blockers or stage2_blockers:
        blocks = [
            GateBlock("policy gate", policy_blockers),
            GateBlock("completeness/unified_quality", [line for line in (completeness_error or "").splitlines() if line.strip()]),
            GateBlock("gap_monitor", gap_blockers),
            GateBlock("stage2 flag", stage2_blockers),
        ]
        raise RuntimeError(format_gate_blocks("Stage3 阻断，以下问题需修复：", blocks))
```

- [ ] **Step 6: Update Stage4 quality gate formatting**

In `scripts/stage4_report_generator.py`, import:

```python
from datasource.utils.gate_formatting import GateBlock, format_gate_blocks, format_quality_issue
```

Replace `_format_quality_issue` with use of imported `format_quality_issue`, or remove the local function.

Replace `_assert_stage4_quality_gate` raise block with:

```python
    details = [format_quality_issue(issue) for issue in quality_blockers]
    if policy_blocked and not details:
        details.append("policy_evaluation.block_stage3 true")

    raise RuntimeError(
        format_gate_blocks(
            "Stage4 unified quality gate blocked report generation:",
            [GateBlock("unified_quality", details)],
        )
    )
```

- [ ] **Step 7: Add Stage3/Stage4 assertions**

In `tests/test_stage3_guard.py`, update assertions that check old strings. For tests expecting gap monitor blocks, assert:

```python
assert "[gap_monitor]" in msg
assert "- pending:" in msg or "- manual_required:" in msg
```

In `tests/test_stage4_docs.py::test_stage4_blocks_manual_websearch_commodity_without_source_url`, assert:

```python
assert "[unified_quality]" in str(exc.value)
assert "commodities.BCOM missing_source_url" in str(exc.value)
```

- [ ] **Step 8: Run gate tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_gate_formatting.py tests/test_stage3_guard.py tests/test_stage4_docs.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/datasource/utils/gate_formatting.py scripts/stage3_pring_analyzer.py scripts/stage4_report_generator.py tests/test_gate_formatting.py tests/test_stage3_guard.py tests/test_stage4_docs.py
git commit -m "fix: format pipeline gate blockers by section"
```

### Task 10: Report Rendering Compatibility And Estimated Categories

**Files:**
- Modify: `src/datasource/generators/simple_report.py`
- Modify: `tests/test_simple_report_integration.py`

- [ ] **Step 1: Write stock index compatibility test**

Append to `tests/test_simple_report_integration.py`:

```python
def test_report_backfills_stock_indices_from_macro_compat(tmp_path):
    market_path = tmp_path / "market.json"
    pring_path = tmp_path / "pring.json"
    out_path = tmp_path / "report.md"
    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-05-21", "data_completeness": 1.0},
                "stock_indices": [],
                "macro_indicators": {
                    "000300": {
                        "indicator_name": "沪深300",
                        "current_value": 4685.3,
                        "previous_value": 4600.0,
                        "change_rate": 1.85,
                        "unit": "点",
                        "source": "manual",
                        "source_url": "https://example.com/000300",
                    }
                },
                "monetary_policy": {},
                "commodities": [],
                "bonds": [],
                "forex": [],
                "fund_flow": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pring_path.write_text(
        json.dumps({"final_stage": "Stage 2", "confidence": 0.8, "recommendation": "中性"}),
        encoding="utf-8",
    )

    generate_report(market_path, pring_path, out_path)

    text = out_path.read_text(encoding="utf-8")
    assert "| 沪深300 | 4685.30 |" in text
```

- [ ] **Step 2: Run stock index test to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_simple_report_integration.py::test_report_backfills_stock_indices_from_macro_compat
```

Expected: FAIL because no stock index row is rendered.

- [ ] **Step 3: Add stock index compatibility helper**

In `src/datasource/generators/simple_report.py`, before `generate_report`, add:

```python
STOCK_INDEX_COMPAT_KEYS = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "000300": "沪深300",
    "000016": "上证50",
}


def _stock_indices_with_macro_compat(market_data: Dict[str, Any], stock_indices: list) -> list:
    rows = list(stock_indices or [])
    existing = {str(row.get("symbol") or "") for row in rows if isinstance(row, dict)}
    macro = market_data.get("macro_indicators", {}) or {}
    for symbol, name in STOCK_INDEX_COMPAT_KEYS.items():
        if symbol in existing:
            continue
        entry = macro.get(symbol)
        if not isinstance(entry, dict):
            continue
        current = _to_float(entry.get("current_value"))
        if current is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": entry.get("indicator_name") or name,
                "current_price": current,
                "change_5d": entry.get("change_5d") or entry.get("change_rate") or 0.0,
                "change_120d": entry.get("change_120d") or 0.0,
                "above_ma50": bool(entry.get("above_ma50", False)),
                "above_ma200": bool(entry.get("above_ma200", False)),
                "trend_label": entry.get("trend_label") or "兼容回填",
                "source": entry.get("source"),
                "source_url": entry.get("source_url"),
                "compat_source": "macro_indicators_compat_backfill",
            }
        )
    return rows
```

In `generate_report`, replace:

```python
    stock_indices = _as_list(market_data.get('stock_indices', []))
```

with:

```python
    stock_indices = _stock_indices_with_macro_compat(
        market_data,
        _as_list(market_data.get('stock_indices', [])),
    )
```

- [ ] **Step 4: Run stock index test**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_simple_report_integration.py::test_report_backfills_stock_indices_from_macro_compat
```

Expected: PASS.

- [ ] **Step 5: Write estimated category reminder test**

Append to `tests/test_simple_report_integration.py`:

```python
def test_report_estimated_note_includes_category_and_method(tmp_path):
    market_path = tmp_path / "market.json"
    pring_path = tmp_path / "pring.json"
    out_path = tmp_path / "report.md"
    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-05-21", "data_completeness": 1.0},
                "stock_indices": [],
                "macro_indicators": {},
                "monetary_policy": {},
                "commodities": [
                    {
                        "symbol": "BCOM",
                        "name": "彭博商品指数",
                        "current_price": 108.5,
                        "unit": "点",
                        "daily_change": 0.1,
                        "change_120d": 2.0,
                        "trend": "上行",
                        "is_estimated": True,
                        "estimation_method": "manual_estimated",
                    }
                ],
                "bonds": [],
                "forex": [],
                "fund_flow": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pring_path.write_text(
        json.dumps({"final_stage": "Stage 2", "confidence": 0.8, "recommendation": "中性"}),
        encoding="utf-8",
    )

    generate_report(market_path, pring_path, out_path)

    text = out_path.read_text(encoding="utf-8")
    assert "彭博商品指数" in text
    assert "manual_estimated" in text
```

- [ ] **Step 6: Run estimated note test to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_simple_report_integration.py::test_report_estimated_note_includes_category_and_method
```

Expected: FAIL because commodities are not included in `estimated_items`.

- [ ] **Step 7: Include commodities and methods in estimated reminder**

Inside `_collect_estimated_items`, add commodities and method labels:

```python
        for comm in commodities:
            if comm.get("is_estimated"):
                name = comm.get("name") or comm.get("symbol") or "商品"
                method = comm.get("estimation_method") or comm.get("metric_basis") or "estimated"
                items.append(f"商品:{name}({method})")
```

For existing bond/macro/policy/fund_flow items, append method if present:

```python
method = entry.get("estimation_method") or entry.get("metric_basis")
suffix = f"({method})" if method else ""
items.append(f"宏观:{name}{suffix}")
```

Apply the same pattern to bond, monetary policy, and fund flow.

- [ ] **Step 8: Run report tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_simple_report_integration.py::test_report_backfills_stock_indices_from_macro_compat tests/test_simple_report_integration.py::test_report_estimated_note_includes_category_and_method
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/datasource/generators/simple_report.py tests/test_simple_report_integration.py
git commit -m "fix: clarify estimated values in report output"
```

### Task 11: Manual Previous-Value Recalculation

**Files:**
- Modify: `scripts/stage2_5_injector.py`
- Modify: `tests/test_websearch_injector.py`

- [ ] **Step 1: Write commodity previous-price recalculation test**

Append to `tests/test_websearch_injector.py`:

```python
def test_build_commodity_entry_recomputes_daily_change_from_previous_price():
    payload = {
        "symbol": "BZ=F",
        "name": "Brent原油",
        "current_price": 65.0,
        "previous_price": 70.0,
        "unit": "$/bbl",
        "source_url": "https://example.com/brent",
    }

    entry = injector._build_commodity_entry(payload, is_manual=True, trend_history_base_dir=None)

    assert round(entry["daily_change"], 2) == -7.14
    assert entry["daily_change_base_price"] == 70.0
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_websearch_injector.py::test_build_commodity_entry_recomputes_daily_change_from_previous_price
```

Expected: FAIL because previous price is not used.

- [ ] **Step 3: Add change calculation helper**

In `scripts/stage2_5_injector.py`, add:

```python
def _pct_change(current: Any, previous: Any) -> Optional[float]:
    current_num = _coerce_float(current)
    previous_num = _coerce_float(previous)
    if current_num is None or previous_num in (None, 0):
        return None
    return round((current_num - previous_num) / abs(previous_num) * 100.0, 4)
```

In `_build_commodity_entry` and `_merge_commodity_entry`, after setting `current_price`, add:

```python
    previous_price = _coerce_float(payload.get("previous_price") or payload.get("previous_value"))
    manual_daily_change = _pct_change(entry.get("current_price"), previous_price)
    if manual_daily_change is not None:
        entry["daily_change"] = manual_daily_change
        entry["daily_change_base_price"] = previous_price
        if payload.get("previous_date"):
            entry["daily_change_base_date"] = payload.get("previous_date")
```

Use `merged` instead of `entry` inside `_merge_commodity_entry`.

- [ ] **Step 4: Run commodity recalculation test**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_websearch_injector.py::test_build_commodity_entry_recomputes_daily_change_from_previous_price
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/stage2_5_injector.py tests/test_websearch_injector.py
git commit -m "fix: recompute manual commodity change fields"
```

### Task 12: Docs And Manual Template

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `data/runs/templates/manual_template.json`
- Modify or create docs tests if existing patterns require them

- [ ] **Step 1: Update `AGENTS.md` environment section**

In `AGENTS.md`, update Setup & Health Check to include:

```markdown
- 默认网络模式为 `DATASOURCE_NETWORK_MODE=direct`：`run_clean.sh`/`runtime_env.sh` 会清理 `http_proxy/https_proxy/HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/all_proxy`，保留 `no_proxy/NO_PROXY`。
- 若 Ubuntu/WSL 中 `.venv` 是空目录，可设置 `DATASOURCE_AUTO_VENV=1` 让 `scripts/bootstrap_venv.sh` 一次性创建并安装依赖；非空但不可用的 `.venv` 仍需删除重建。
- 只有明确需要代理时才设置 `DATASOURCE_NETWORK_MODE=proxy`；SOCKS 代理需要 `httpx[socks]`/`socksio`，否则 preflight hard fail。
```

- [ ] **Step 2: Update `CLAUDE.md` high-frequency reminders**

Add:

```markdown
**Ubuntu/WSL Claude Code 启动**: 若 `.venv` 为空目录，优先设置 `DATASOURCE_AUTO_VENV=1` 让 runtime 自动 bootstrap；不要长期依赖 `ALLOW_SYSTEM_PYTHON=1`。非空坏 venv 或 Windows venv 在 Linux 下仍需删除重建。

**VPN/代理变更**: 默认 `DATASOURCE_NETWORK_MODE=direct` 会清理 `ALL_PROXY/all_proxy` 等主动代理变量。换 VPN 后先跑 `bash run_preflight.sh`；若确实需要代理，显式设置 `DATASOURCE_NETWORK_MODE=proxy` 并确保 SOCKS 依赖存在。
```

- [ ] **Step 3: Update manual template fund-flow examples**

In `data/runs/templates/manual_template.json`, ensure fund_flow examples include:

```json
"window_evidence": "direct_window",
"metric_basis": "net_flow_sum"
```

for direct examples, and:

```json
"window_evidence": "news_summary",
"metric_basis": "estimated_net_flow",
"is_estimated": true
```

for ETF/news examples.

- [ ] **Step 4: Run docs/template sanity tests**

Run:

```bash
bash run_clean.sh python -m json.tool data/runs/templates/manual_template.json >/tmp/manual_template_check.json
bash run_clean.sh python -m pytest -q tests/test_stage4_docs.py tests/test_runtime_env.py
```

Expected: JSON command exits 0; pytest PASS.

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md CLAUDE.md data/runs/templates/manual_template.json
git commit -m "docs: document vpn and venv report workflow"
```

### Task 13: Final Verification

**Files:**
- No planned source edits. This task verifies the whole branch.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_bootstrap_venv.py \
  tests/test_runtime_env.py \
  tests/test_run_clean_env.py \
  tests/test_preflight_proxy.py \
  tests/test_tavily_client.py \
  tests/test_source_trust.py \
  tests/test_stage2_unified.py \
  tests/test_websearch_injector.py \
  tests/test_gate_formatting.py \
  tests/test_stage3_guard.py \
  tests/test_stage4_docs.py \
  tests/test_simple_report_integration.py
```

Expected: PASS. If `tests/test_stage2_unified.py` is slow, run the new tests by node id first, then run the whole file before final.

- [ ] **Step 2: Run import and compile sanity**

Run:

```bash
bash run_clean.sh python -c "from datasource import get_manager; print('OK')"
bash run_clean.sh python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py scripts/stage3_pring_analyzer.py scripts/stage4_report_generator.py
```

Expected: `OK`, then no py_compile output and exit code 0.

- [ ] **Step 3: Check git status**

Run:

```bash
git status --short
```

Expected: no unstaged changes except intentionally ignored `.venv` and `.env` symlink.

- [ ] **Step 4: Commit any final doc/test adjustment**

If final verification required small fixes, commit them:

```bash
git add <changed-files>
git commit -m "fix: complete report generation hardening"
```

If no changes remain, do not create an empty commit.

## Self-Review

Spec coverage:

1. VPN/proxy isolation is covered by Tasks 2, 3, and 4.
2. Empty `.venv` Ubuntu/Claude Code startup is covered by Task 1.
3. Stage2 official source non-estimated normalization is covered by Task 5.
4. DeepSeek timeout downgrade is covered by Task 6.
5. Stage2.5 summary, metadata update, and fund_flow diagnostics are covered by Tasks 7 and 8.
6. Stage3/Stage4 gate formatting is covered by Task 9.
7. Report estimated display and stock-index compatibility are covered by Task 10.
8. Manual previous value recalculation is covered by Task 11.
9. AGENTS/CLAUDE/template updates are covered by Task 12.
10. Final verification is covered by Task 13.

Placeholder scan:

No task uses unresolved placeholder language or unspecified test instructions. Each task names exact files, includes code snippets, exact commands, expected outcomes, and a commit step.

Type consistency:

New names are stable across tasks:

- `InjectionSummary`
- `OfficialSourceDecision`
- `should_mark_official_non_estimated`
- `_DeepSeekCircuitBreaker`
- `GateBlock`
- `format_gate_blocks`
- `format_quality_issue`
- `DATASOURCE_AUTO_VENV`
- `DATASOURCE_NETWORK_MODE`
