# Daily Pipeline Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the daily Stage1 -> Stage4 pipeline resilient to missing `.venv`, Tavily/Exa failures, DeepSeek model changes, manual official data handling, and misleading MLF display.

**Architecture:** Keep the current Stage1 -> Stage2 -> Stage2.5 -> Stage3 -> Stage4 contract. Add small helpers around existing entrypoints instead of replacing the Stage2 scheduler: `run_clean.sh` owns environment fallback, Stage2 owns search/extract diagnostics and fallback metadata, Stage2.5 owns manual official-vs-estimated normalization, and Stage4 owns report display wording.

**Tech Stack:** Bash, Python 3, pytest, `exa-py`, `tavily-python`, OpenAI-compatible DeepSeek calls, existing `datasource` package modules.

---

## Execution Context

Worktree: `D:\cursor\datasource\.worktrees\codex\daily-pipeline-hardening`

Branch: `codex/daily-pipeline-hardening`

Design source: `docs/superpowers/specs/2026-04-28-daily-pipeline-hardening-design.md`

Known baseline before implementation:

```text
python -m pytest -q
Result: 253 passed, 12 failed, 2 skipped
Failure classes:
- 11 async tests fail because they are unmarked async functions under current pytest configuration.
- tests/test_pring_scoring_golden.py::test_stage3_golden_replay_stable_fields fails because the golden fixture lacks source_url under the current quality gate.
```

Do not treat those existing failures as regressions for every task. Each task must run its focused tests. At the end, run `python -m pytest -q` and report whether the same baseline failures remain or whether new failures appeared.

## Scope Update: Tavily-First Batch

User direction on 2026-04-28: temporarily do not use Exa Search. Improve Tavily Search hit rate first.

Immediate execution scope:

- Execute Task 5: Stage2 retrieval diagnostics and Tavily fast-switch records.
- Execute Task 6: search profile tuning for `reserve_ratio`/`rrr`, `CN10Y_CDB`, `USDCNY`, and `BDI`.
- Update docs in Task 9 only for Tavily diagnostics/profile behavior if code behavior changes.

Deferred execution scope:

- Do not execute Task 3 in this batch.
- Do not execute Task 4 in this batch.
- Do not add Exa live probe usage or broaden Exa fallback routing in this batch.
- If a touched command would otherwise call Exa because `EXA_API_KEY` exists, add an explicit CLI/env opt-in before any future Exa work rather than using Exa automatically.

## File Responsibility Map

- `run_clean.sh`: single clean runtime launcher; detects Linux venv, Windows venv, or explicit system Python fallback.
- `.env.example`: documents `DEEPSEEK_MODEL=deepseek-v4-pro` and optional `EXA_API_KEY`.
- `src/datasource/engines/deepseek_reasoner.py`: default DeepSeek extraction model.
- `scripts/stage2_unified_enhancer.py`: Stage2 CLI defaults, Tavily/Exa fallback, manual-required records, retrieval diagnostics, profile alias handling.
- `src/datasource/adapters/exa_client.py`: Exa SDK compatibility, structured error metadata, Tavily-compatible result mapping.
- `scripts/stage2_health_check.py`: static Exa readiness and explicit optional Exa live probe.
- `src/datasource/config/search_profiles.py`: query families and strict matching rules for high-failure indicators.
- `scripts/stage2_5_injector.py`: manual official data normalization, estimated gate behavior, gap monitor refresh.
- `src/datasource/generators/simple_report.py`: Stage4 asset summary DeepSeek default and MLF display helpers.
- `AGENTS.md` and `CLAUDE.md`: durable workflow rules and quick reminders.

## Task 1: Harden `run_clean.sh` Runtime Selection

**Files:**
- Modify: `run_clean.sh`
- Create: `tests/test_run_clean.py`

- [ ] **Step 1: Write failing tests for Linux venv, Windows venv, missing venv, and explicit system fallback**

Create `tests/test_run_clean.py`:

```python
import os
import shutil
import subprocess
from pathlib import Path


def _copy_runner(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy2(Path("run_clean.sh"), root / "run_clean.sh")
    (root / ".env").write_text("TUSHARE_TOKEN=x\nTAVILY_API_KEY=y\nDEEPSEEK_API_KEY=z\n", encoding="utf-8")
    return root


def _run(root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env or {})
    return subprocess.run(
        ["bash", "run_clean.sh", *args],
        cwd=root,
        env=merged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_run_clean_uses_windows_venv_when_linux_venv_missing(tmp_path: Path):
    root = _copy_runner(tmp_path)
    scripts = root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "activate").write_text("export VENV_KIND=windows\n", encoding="utf-8")

    result = _run(root, "bash", "-lc", "printf \"$VENV_KIND|$PYTHONPATH|$http_proxy\"")

    assert result.returncode == 0
    assert "windows|./src|" in result.stdout


def test_run_clean_missing_venv_without_system_fallback_fails(tmp_path: Path):
    root = _copy_runner(tmp_path)

    result = _run(root, "python", "--version")

    assert result.returncode == 1
    assert "Missing virtual environment" in result.stdout
    assert "ALLOW_SYSTEM_PYTHON=1" in result.stdout


def test_run_clean_system_fallback_is_explicit_and_sets_pythonpath(tmp_path: Path):
    root = _copy_runner(tmp_path)

    result = _run(root, "bash", "-lc", "printf \"$PYTHONPATH|$http_proxy\"", env={"ALLOW_SYSTEM_PYTHON": "1"})

    assert result.returncode == 0
    assert "./src|" in result.stdout


def test_run_clean_requires_env_file_even_with_system_fallback(tmp_path: Path):
    root = _copy_runner(tmp_path)
    (root / ".env").unlink()

    result = _run(root, "python", "--version", env={"ALLOW_SYSTEM_PYTHON": "1"})

    assert result.returncode == 1
    assert "Missing .env" in result.stdout
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_run_clean.py -q
```

Expected: at least `test_run_clean_uses_windows_venv_when_linux_venv_missing` and `test_run_clean_system_fallback_is_explicit_and_sets_pythonpath` fail because `run_clean.sh` currently only accepts `.venv/bin/activate`.

- [ ] **Step 3: Implement runtime selection in `run_clean.sh`**

Replace the current venv check and `source .venv/bin/activate` block with this logic:

```bash
ACTIVATE_SCRIPT=""
if [ -f ".venv/bin/activate" ]; then
  ACTIVATE_SCRIPT=".venv/bin/activate"
elif [ -f ".venv/Scripts/activate" ]; then
  ACTIVATE_SCRIPT=".venv/Scripts/activate"
fi

if [ -z "$ACTIVATE_SCRIPT" ] && [ "${ALLOW_SYSTEM_PYTHON:-}" != "1" ]; then
  echo "[ERROR] Missing virtual environment. Run: python -m venv .venv"
  echo "[ERROR] To use the current system Python explicitly, rerun with: ALLOW_SYSTEM_PYTHON=1 bash run_clean.sh <command> [args...]"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "[ERROR] Missing .env. Copy from .env.example first."
  exit 1
fi

if [ -n "$ACTIVATE_SCRIPT" ]; then
  source "$ACTIVATE_SCRIPT"
else
  echo "[WARN] Using system Python because ALLOW_SYSTEM_PYTHON=1 and no .venv activate script was found."
fi
```

Keep the existing `.env` sourcing, proxy cleanup, and `PYTHONPATH=./src` logic after this block.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python -m pytest tests/test_run_clean.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add run_clean.sh tests/test_run_clean.py
git commit -m "fix: harden clean runner environment fallback"
```

## Task 2: Switch DeepSeek Defaults to `deepseek-v4-pro`

**Files:**
- Modify: `src/datasource/engines/deepseek_reasoner.py`
- Modify: `scripts/stage2_unified_enhancer.py`
- Modify: `src/datasource/generators/simple_report.py`
- Modify: `.env.example`
- Create: `tests/test_deepseek_defaults.py`

- [ ] **Step 1: Write failing default-model tests**

Create `tests/test_deepseek_defaults.py`:

```python
import argparse
import inspect

import scripts.stage2_unified_enhancer as stage2
from datasource.engines.deepseek_reasoner import DeepSeekExtractionAgent
from datasource.generators import simple_report


def test_deepseek_extraction_agent_default_model_is_v4_pro():
    signature = inspect.signature(DeepSeekExtractionAgent)
    assert signature.parameters["model"].default == "deepseek-v4-pro"


def test_stage2_cli_default_deepseek_model_is_v4_pro(monkeypatch):
    captured = {}

    class ParserSpy(argparse.ArgumentParser):
        def add_argument(self, *args, **kwargs):
            if "--deepseek-model" in args:
                captured["default"] = kwargs.get("default")
            return super().add_argument(*args, **kwargs)

    monkeypatch.setattr(stage2.argparse, "ArgumentParser", ParserSpy)
    monkeypatch.setattr("sys.argv", ["stage2_unified_enhancer.py", "--market-data", "x.json"])

    try:
        stage2._parse_args()
    except SystemExit:
        pass

    assert captured["default"] == "deepseek-v4-pro"


def test_stage4_asset_summary_default_model_is_v4_pro(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_SUMMARY_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key")

    calls = {}

    class FakeMessage:
        content = "资产结论。"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        def create(self, **kwargs):
            calls.update(kwargs)
            return type("Resp", (), {"choices": [FakeChoice()]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

        def __init__(self, **kwargs):
            pass

        def with_options(self, **kwargs):
            return self

    monkeypatch.setattr(simple_report, "OpenAI", FakeClient)

    text, status, _ = simple_report._generate_asset_conclusion("黄金上涨")

    assert text == "资产结论。"
    assert status == "success"
    assert calls["model"] == "deepseek-v4-pro"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_deepseek_defaults.py -q
```

Expected: failures show the current default is `deepseek-chat`.

- [ ] **Step 3: Change defaults**

Apply these direct changes:

```python
# src/datasource/engines/deepseek_reasoner.py
model: str = "deepseek-v4-pro",
```

```python
# scripts/stage2_unified_enhancer.py
parser.add_argument("--deepseek-model", default="deepseek-v4-pro", help="DeepSeek模型名")
```

```python
# src/datasource/generators/simple_report.py
model = os.getenv("DEEPSEEK_SUMMARY_MODEL") or os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-pro"
```

Add these lines to `.env.example` near the DeepSeek key:

```bash
DEEPSEEK_MODEL=deepseek-v4-pro
# Optional Tavily fallback. Required only when Stage2 should try Exa after Tavily failures.
EXA_API_KEY=
```

- [ ] **Step 4: Run focused tests and default scan**

Run:

```bash
python -m pytest tests/test_deepseek_defaults.py -q
git grep -n "deepseek-chat" -- src scripts .env.example
```

Expected: tests pass. `git grep` may still show historical documentation if present, but no default value in active `src/` or `scripts/`.

- [ ] **Step 5: Commit**

```bash
git add src/datasource/engines/deepseek_reasoner.py scripts/stage2_unified_enhancer.py src/datasource/generators/simple_report.py .env.example tests/test_deepseek_defaults.py
git commit -m "fix: default deepseek calls to v4 pro"
```

## Deferred Task 3: Add Exa SDK Compatibility and Health Checks

**Files:**
- Modify: `src/datasource/adapters/exa_client.py`
- Modify: `scripts/stage2_health_check.py`
- Modify: `tests/test_exa_client.py`
- Create: `tests/test_stage2_health_check.py`

- [ ] **Step 1: Add Exa client tests**

Append to `tests/test_exa_client.py`:

```python
import asyncio


def test_exa_client_passes_contents_payload_to_sdk(monkeypatch):
    calls = {}

    class FakeResponse:
        results = [
            {
                "url": "https://example.com",
                "title": "Title",
                "text": "Body",
                "summary": "Summary",
                "highlights": ["Hit"],
                "publishedDate": "2026-04-28",
            }
        ]

    class FakeExa:
        def __init__(self, api_key=None):
            calls["api_key"] = api_key

        def search(self, **kwargs):
            calls.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr("datasource.adapters.exa_client.Exa", FakeExa)
    client = AsyncExaClient(api_key="exa-key")

    result = asyncio.run(
        client.search(
            query="gold latest",
            num_results=3,
            include_domains=["example.com"],
            start_published_date="2026-04-01",
            search_type="keyword",
            contents={"text": True, "summary": True, "highlights": True},
        )
    )

    assert calls["api_key"] == "exa-key"
    assert calls["query"] == "gold latest"
    assert calls["contents"] == {"text": True, "summary": True, "highlights": True}
    assert calls["type"] == "keyword"
    assert result["results"][0]["snippet"] == "Hit"


def test_exa_error_metadata_extracts_status_and_type():
    class FakeResponse:
        status_code = 429
        text = "rate limited"

    exc = RuntimeError("quota exceeded")
    exc.response = FakeResponse()

    meta = AsyncExaClient.error_metadata(exc)

    assert meta["exa_error_type"] == "RuntimeError"
    assert meta["exa_http_status"] == 429
    assert meta["exa_error_tag"] == "rate_limited"
    assert "quota exceeded" in meta["exa_error_message"]
```

- [ ] **Step 2: Add health-check tests**

Create `tests/test_stage2_health_check.py`:

```python
import os

import scripts.stage2_health_check as health


def test_check_exa_static_reports_missing_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    result = health.check_exa_static()

    assert result["enabled"] is False
    assert result["status"] == "missing_key"


def test_check_exa_static_reports_importable_when_key_present(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa-key")

    result = health.check_exa_static()

    assert result["enabled"] is True
    assert result["status"] in {"ok", "sdk_unavailable"}
    assert "sdk_importable" in result


def test_stage2_health_check_live_probe_is_opt_in(monkeypatch):
    called = {"live": False}

    monkeypatch.setenv("TAVILY_API_KEY", "tavily")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek")
    monkeypatch.setattr(health, "_ping", lambda *args, **kwargs: True)
    monkeypatch.setattr(health, "check_path", lambda path: True)

    def fake_live_probe():
        called["live"] = True
        return {"status": "ok"}

    monkeypatch.setattr(health, "check_exa_live", fake_live_probe)
    monkeypatch.setattr("sys.argv", ["stage2_health_check.py"])

    try:
        health.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert called["live"] is False
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_exa_client.py tests/test_stage2_health_check.py -q
```

Expected: tests fail because `error_metadata`, `check_exa_static`, `check_exa_live`, and CLI parsing do not exist.

- [ ] **Step 4: Implement Exa error metadata**

Add to `AsyncExaClient`:

```python
    @staticmethod
    def error_metadata(exc: Exception) -> Dict[str, Any]:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        message = str(exc)
        lower = message.lower()
        if status == 401:
            tag = "auth_failed"
        elif status == 402:
            tag = "payment_required"
        elif status == 429 or "rate" in lower or "quota" in lower:
            tag = "rate_limited"
        elif status and 400 <= int(status) < 500:
            tag = "request_error"
        elif status and int(status) >= 500:
            tag = "server_error"
        else:
            tag = "unknown_error"
        return {
            "exa_error_type": type(exc).__name__,
            "exa_http_status": status,
            "exa_error_tag": tag,
            "exa_error_message": message[:500],
        }
```

- [ ] **Step 5: Implement health check parsing and Exa checks**

In `scripts/stage2_health_check.py`, add:

```python
import argparse


def check_exa_static():
    key = os.getenv("EXA_API_KEY")
    if not key:
        return {"enabled": False, "status": "missing_key", "sdk_importable": False}
    try:
        from datasource.adapters.exa_client import AsyncExaClient  # noqa: F401

        return {"enabled": True, "status": "ok", "sdk_importable": True}
    except Exception as exc:
        return {
            "enabled": True,
            "status": "sdk_unavailable",
            "sdk_importable": False,
            "error": str(exc),
        }


def check_exa_live():
    from datasource.adapters.exa_client import AsyncExaClient
    import asyncio

    async def _run():
        client = AsyncExaClient(api_key=os.getenv("EXA_API_KEY"), default_num_results=1)
        return await client.search(query="site:example.com example", num_results=1, cache_ttl=0)

    try:
        result = asyncio.run(_run())
        return {"status": "ok", "result_count": len(result.get("results") or [])}
    except Exception as exc:
        return {"status": "failed", **AsyncExaClient.error_metadata(exc)}
```

Change `main()` to parse `--check-exa-live`:

```python
parser = argparse.ArgumentParser()
parser.add_argument("--check-exa-live", action="store_true")
args = parser.parse_args()
```

After DeepSeek connectivity output, print static Exa status and only call `check_exa_live()` when `args.check_exa_live` is true.

- [ ] **Step 6: Run focused tests**

Run:

```bash
python -m pytest tests/test_exa_client.py tests/test_stage2_health_check.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/datasource/adapters/exa_client.py scripts/stage2_health_check.py tests/test_exa_client.py tests/test_stage2_health_check.py
git commit -m "feat: add exa health diagnostics"
```

## Deferred Task 4: Structure Exa Fallback Telemetry Without Replacing Tavily Snippets

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Modify: `tests/test_stage2_fallbacks.py`

- [ ] **Step 1: Add failing fallback telemetry tests**

Append to `tests/test_stage2_fallbacks.py`:

```python
class ErroringExaClient:
    async def search(self, **kwargs):
        exc = RuntimeError("rate limit")
        exc.response = type("Resp", (), {"status_code": 429, "text": "rate limit"})()
        raise exc


async def test_exa_error_records_structured_metadata_without_dropping_tavily_snippets(tmp_path):
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "out.json"
    websearch_path = tmp_path / "websearch.json"
    task_log = tmp_path / "task_log.jsonl"

    market_path.write_text(
        '{"metadata": {"date": "2026-04-28"}, "commodities": [{"symbol": "GC=F", "current_price": null}]}',
        encoding="utf-8",
    )

    class FakeTavily:
        async def search(self, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://example.com/gold",
                        "title": "Gold",
                        "content": "Gold latest price 3300 USD/oz",
                        "snippet": "Gold latest price 3300 USD/oz",
                        "score": 0.99,
                    }
                ],
                "request_id": "tavily-1",
                "cache_hit": False,
            }

        async def extract(self, urls):
            raise RuntimeError("422 Unprocessable Entity")

    stats = await run_stage2_enhancement(
        market_data_path=market_path,
        output_path=output_path,
        phase="all",
        execute_search=True,
        client=FakeTavily(),
        exa_client=ErroringExaClient(),
        extraction_backend="regex",
        websearch_results_path=websearch_path,
        task_log_path=task_log,
        cache_ttl=0,
    )

    assert stats["exa_error"] == 1
    assert stats["exa_error_breakdown"]["rate_limited"] == 1
    payload = json.loads(websearch_path.read_text(encoding="utf-8"))
    assert payload["results"][0]["raw_results"][0]["url"] == "https://example.com/gold"
    assert payload["results"][0]["exa_error_tag"] == "rate_limited"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
python -m pytest tests/test_stage2_fallbacks.py::test_exa_error_records_structured_metadata_without_dropping_tavily_snippets -q
```

Expected: failure because `exa_error_breakdown` and per-result Exa error metadata are not recorded.

- [ ] **Step 3: Add Exa metadata helpers**

In `scripts/stage2_unified_enhancer.py`, add helper near `_try_exa_fallback`:

```python
    def _record_exa_error(exc: Exception, task: Dict[str, Any], reason: str, query: str) -> Dict[str, Any]:
        stats["exa_error"] += 1
        if hasattr(exa_client, "error_metadata"):
            meta = exa_client.error_metadata(exc)
        else:
            meta = {
                "exa_error_type": type(exc).__name__,
                "exa_http_status": getattr(getattr(exc, "response", None), "status_code", None),
                "exa_error_tag": "unknown_error",
                "exa_error_message": str(exc)[:500],
            }
        breakdown = stats.setdefault("exa_error_breakdown", {})
        tag = meta.get("exa_error_tag") or "unknown_error"
        breakdown[tag] = int(breakdown.get(tag, 0)) + 1
        meta.update(
            {
                "exa_reason": reason,
                "exa_query": query,
                "exa_indicator_key": task.get("indicator_key"),
                "exa_domains": task.get("preferred_domains") or [],
            }
        )
        stats.setdefault("exa_error_samples", []).append(meta)
        return meta
```

Change `_try_exa_fallback` to return `(result, note, metadata)` and use `_record_exa_error()` in the exception branch.

- [ ] **Step 4: Preserve Tavily snippets when Exa fails**

Where callers handle `exa_result`, keep current `result` and `snippets` if `exa_result` is `None`. When `exa_metadata` is present, attach it to the current websearch record by adding the metadata fields into the extraction item that is appended to `websearch_results`.

Use this merge pattern before writing a manual-required item:

```python
if exa_metadata:
    extraction.update(exa_metadata)
    note = extraction.get("note") or ""
    extraction["note"] = f"{note} exa_error:{exa_metadata.get('exa_error_tag')}".strip()
```

- [ ] **Step 5: Include Exa breakdown in summary**

Add to summary construction:

```python
"exa_error_breakdown": exec_stats.get("exa_error_breakdown", {}),
"exa_error_samples": exec_stats.get("exa_error_samples", [])[:5],
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
python -m pytest tests/test_stage2_fallbacks.py::test_extract_422_uses_exa_fallback_for_non_fund_flow tests/test_stage2_fallbacks.py::test_exa_error_records_structured_metadata_without_dropping_tavily_snippets -q
```

Expected: selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_fallbacks.py
git commit -m "feat: record exa fallback diagnostics"
```

## Task 5: Add Stage2 Retrieval Diagnostics and Fast Switch Records

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Modify: `tests/test_stage2_fallbacks.py`
- Modify: `tests/test_stage2_unified.py`

- [ ] **Step 1: Add diagnostics unit test**

Append to `tests/test_stage2_unified.py`:

```python
def test_retrieval_diagnostics_separates_search_extract_and_writeback():
    rows = [
        {"indicator_key": "GC=F", "usable_count_before_extract": 3, "manual_required": True, "manual_reason": "no_deepseek_key"},
        {"indicator_key": "CN10Y_CDB", "usable_count_before_extract": 0, "manual_required": True, "manual_reason": "strict_keyword_miss"},
        {"indicator_key": "northbound", "manual_required": False, "result_type": "skipped_existing"},
        {"indicator_key": "etf", "usable_count_before_extract": 4, "manual_required": False, "write_back_success": True},
    ]

    diag = stage2._build_retrieval_diagnostics(rows)

    assert diag["retrieval_hit_count"] == 2
    assert diag["retrieval_hit_extract_failed"] == 1
    assert diag["writeback_success_count"] == 1
    assert diag["manual_reason_breakdown"]["no_deepseek_key"] == 1
    assert diag["manual_reason_breakdown"]["strict_keyword_miss"] == 1
```

- [ ] **Step 2: Add fast-switch test for quota**

Append to `tests/test_stage2_fallbacks.py`:

```python
class QuotaTavily:
    def __init__(self):
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        exc = RuntimeError("429 quota exceeded")
        exc.response = type("Resp", (), {"status_code": 429})()
        raise exc


async def test_tavily_quota_fast_switch_writes_manual_records(tmp_path):
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "out.json"
    websearch_path = tmp_path / "websearch.json"
    gap_path = tmp_path / "gap.json"

    market_path.write_text(
        '{"metadata": {"date": "2026-04-28"}, "commodities": [{"symbol": "GC=F", "current_price": null}, {"symbol": "CL=F", "current_price": null}]}',
        encoding="utf-8",
    )
    client = QuotaTavily()

    stats = await run_stage2_enhancement(
        market_data_path=market_path,
        output_path=output_path,
        phase="all",
        execute_search=True,
        client=client,
        extraction_backend="regex",
        websearch_results_path=websearch_path,
        gap_monitor_path=gap_path,
        queue_retry_limit=0,
        cache_ttl=0,
    )

    assert client.calls == 1
    assert stats["tavily_unavailable_reason"] == "quota_or_rate_limit"
    payload = json.loads(websearch_path.read_text(encoding="utf-8"))
    assert any(row["manual_required"] for row in payload["results"])
    gap = json.loads(gap_path.read_text(encoding="utf-8"))
    assert gap["manual_required"]
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_stage2_unified.py::test_retrieval_diagnostics_separates_search_extract_and_writeback tests/test_stage2_fallbacks.py::test_tavily_quota_fast_switch_writes_manual_records -q
```

Expected: diagnostics helper and fast-switch behavior are missing.

- [ ] **Step 4: Implement `_build_retrieval_diagnostics`**

Add this module-level helper to `scripts/stage2_unified_enhancer.py`:

```python
def _build_retrieval_diagnostics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = 0
    retrieval_hit = 0
    extract_failed = 0
    writeback_success = 0
    reasons: Dict[str, int] = {}
    for row in rows:
        if row.get("result_type") == "skipped_existing":
            continue
        total += 1
        usable = int(row.get("usable_count_before_extract") or 0)
        manual_required = bool(row.get("manual_required"))
        reason = row.get("manual_reason") or row.get("extraction_skipped_reason") or row.get("extract_skipped_reason")
        if usable > 0:
            retrieval_hit += 1
            if manual_required:
                extract_failed += 1
        if row.get("write_back_success") or row.get("write_back_category"):
            writeback_success += 1
        if manual_required:
            key = str(reason or "manual_required")
            reasons[key] = reasons.get(key, 0) + 1
    return {
        "retrieval_task_count": total,
        "retrieval_hit_count": retrieval_hit,
        "retrieval_hit_rate": retrieval_hit / total if total else 0.0,
        "retrieval_hit_extract_failed": extract_failed,
        "writeback_success_count": writeback_success,
        "writeback_success_rate": writeback_success / total if total else 0.0,
        "manual_reason_breakdown": reasons,
    }
```

- [ ] **Step 5: Implement quota fast switch**

Add `tavily_unavailable_reason` state inside `run_stage2_enhancement`. When `_is_tavily_quota_error(exc)` returns true, set:

```python
tavily_unavailable_reason = "quota_or_rate_limit"
stats["tavily_unavailable_reason"] = tavily_unavailable_reason
```

Before each later Tavily search, if this variable is set, append a manual-required result:

```python
manual_item = {
    "task_id": task.get("task_id"),
    "indicator_key": task.get("indicator_key"),
    "category": task.get("category"),
    "stage_phase": task.get("stage_phase"),
    "query": task.get("query"),
    "manual_required": True,
    "manual_reason": tavily_unavailable_reason,
    "source": "Stage2 manual_required",
    "note": f"tavily_fast_switch:{tavily_unavailable_reason}",
    "raw_results": [],
}
websearch_results.append(manual_item)
```

Ensure the existing gap monitor writer sees these rows.

- [ ] **Step 6: Add diagnostics to summary**

At summary build time, call `_build_retrieval_diagnostics(task_log_rows_or_websearch_rows)` and merge keys into the JSON summary:

```python
summary["retrieval_diagnostics"] = _build_retrieval_diagnostics(websearch_results)
summary["manual_reason_breakdown"] = summary["retrieval_diagnostics"]["manual_reason_breakdown"]
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
python -m pytest tests/test_stage2_unified.py::test_retrieval_diagnostics_separates_search_extract_and_writeback tests/test_stage2_fallbacks.py::test_tavily_quota_fast_switch_writes_manual_records -q
```

Expected: selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py tests/test_stage2_fallbacks.py
git commit -m "feat: add stage2 retrieval diagnostics"
```

## Task 6: Tune Search Profiles for High-Failure Indicators

**Files:**
- Modify: `src/datasource/config/search_profiles.py`
- Modify: `scripts/stage2_unified_enhancer.py`
- Modify: `tests/test_stage2_unified.py`

- [ ] **Step 1: Add profile tests**

Append to `tests/test_stage2_unified.py`:

```python
from datasource.config.search_profiles import SEARCH_PROFILES


def test_stage2_profile_alias_reserve_ratio_to_rrr():
    assert stage2._profile_key("reserve_ratio") == "rrr"
    assert "rrr" in SEARCH_PROFILES


def test_cn10y_cdb_profile_accepts_chinabond_policy_bank_language():
    profile = SEARCH_PROFILES["CN10Y_CDB"]
    aliases = " ".join(profile["issuer_aliases"]).lower()
    required = " ".join(profile["required_keywords"]).lower()

    assert "中债估值" in aliases
    assert "政策性金融债" in aliases
    assert "国开" in required
    assert "10年" in required


def test_usdcny_profile_has_separate_midpoint_and_spot_families():
    families = {family["name"] for family in SEARCH_PROFILES["USDCNY"]["query_families"]}

    assert {"pboc_midpoint", "cfets_spot", "onshore_spot"}.issubset(families)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_stage2_unified.py::test_stage2_profile_alias_reserve_ratio_to_rrr tests/test_stage2_unified.py::test_cn10y_cdb_profile_accepts_chinabond_policy_bank_language tests/test_stage2_unified.py::test_usdcny_profile_has_separate_midpoint_and_spot_families -q
```

Expected: failures show missing `_profile_key` and profile gaps.

- [ ] **Step 3: Add profile alias helper**

In `scripts/stage2_unified_enhancer.py`, add:

```python
def _profile_key(indicator_key: str) -> str:
    aliases = {
        "reserve_ratio": "rrr",
    }
    return aliases.get(indicator_key, indicator_key)
```

Use `_profile_key(indicator_key)` at every place that reads `SEARCH_PROFILES`.

- [ ] **Step 4: Update `CN10Y_CDB` profile**

In `src/datasource/config/search_profiles.py`, set the `CN10Y_CDB` profile to include:

```python
required_keywords=["国开", "开发债", "政策性金融债", "10年", "10Y", "CDB"],
issuer_aliases=["国家开发银行", "国开债", "开发债", "中债估值", "政策性金融债", "ChinaBond", "CDB"],
strict_required_keywords=True,
strict_issuer_match=False,
```

Keep existing preferred domains, but include `chinamoney.com.cn`, `cfets.com.cn`, and `chinabond.com.cn` if the profile already has a domain list.

- [ ] **Step 5: Split `USDCNY` query families**

In the `USDCNY` profile, ensure these query families exist:

```python
query_families=[
    {
        "name": "pboc_midpoint",
        "query": "中国人民银行 人民币汇率中间价 USD CNY 最新",
        "required_keywords": ["中间价", "美元", "人民币"],
        "issuer_aliases": ["中国人民银行", "PBOC"],
        "topic": "news",
        "time_range": "day",
    },
    {
        "name": "cfets_spot",
        "query": "中国货币网 USD/CNY 在岸即期汇率 最新",
        "required_keywords": ["USD/CNY", "在岸", "即期"],
        "issuer_aliases": ["中国货币网", "CFETS"],
        "topic": "news",
        "time_range": "day",
    },
    {
        "name": "onshore_spot",
        "query": "USD CNY onshore spot latest",
        "required_keywords": ["USD", "CNY", "onshore"],
        "topic": "general",
        "time_range": "day",
    },
]
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
python -m pytest tests/test_stage2_unified.py::test_stage2_profile_alias_reserve_ratio_to_rrr tests/test_stage2_unified.py::test_cn10y_cdb_profile_accepts_chinabond_policy_bank_language tests/test_stage2_unified.py::test_usdcny_profile_has_separate_midpoint_and_spot_families -q
```

Expected: selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/datasource/config/search_profiles.py scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "fix: tune stage2 search profiles"
```

## Task 7: Normalize Manual Official Data Without Treating It as Estimated

**Files:**
- Modify: `scripts/stage2_5_injector.py`
- Modify: `tests/test_websearch_injector.py`
- Modify: `tests/test_policy_rules.py`

- [ ] **Step 1: Add official manual normalization tests**

Append to `tests/test_websearch_injector.py`:

```python
def test_manual_official_mlf_payload_is_not_estimated(tmp_path):
    market_path = tmp_path / "stage2.json"
    manual_path = tmp_path / "manual.json"
    output_path = tmp_path / "complete.json"

    market_path.write_text(
        '{"metadata": {"date": "2026-04-28"}, "monetary_policy": {"mlf": {"current_value": null}}}',
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "monetary_policy": {
                    "mlf": {
                        "current_value": 2.0,
                        "source": "中国人民银行 https://www.pbc.gov.cn/example",
                        "source_url": "https://www.pbc.gov.cn/example",
                        "as_of_date": "2026-04-25",
                        "is_estimated": True,
                        "note": "MLF 多重价位中标利率参考值",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    injector.inject_websearch_results(market_path, manual_path, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    mlf = payload["monetary_policy"]["mlf"]
    assert mlf["is_estimated"] is False
    assert "manual_official" in mlf["note"]
    assert payload["missing_items"] == []
```

Append a similar test for `forex.USDCNY`:

```python
def test_manual_official_usdcny_payload_is_not_estimated(tmp_path):
    market_path = tmp_path / "stage2.json"
    manual_path = tmp_path / "manual.json"
    output_path = tmp_path / "complete.json"

    market_path.write_text(
        '{"metadata": {"date": "2026-04-28"}, "forex": [{"pair": "USDCNY", "current_rate": null}]}',
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "forex": [
                    {
                        "pair": "USDCNY",
                        "current_rate": 6.865,
                        "source": "中国外汇交易中心 https://www.chinamoney.com.cn/example",
                        "source_url": "https://www.chinamoney.com.cn/example",
                        "as_of_date": "2026-04-24",
                        "is_estimated": True,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    injector.inject_websearch_results(market_path, manual_path, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    row = payload["forex"][0]
    assert row["is_estimated"] is False
    assert "manual_official" in row["note"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_websearch_injector.py::test_manual_official_mlf_payload_is_not_estimated tests/test_websearch_injector.py::test_manual_official_usdcny_payload_is_not_estimated -q
```

Expected: failures show explicit `is_estimated=True` remains true.

- [ ] **Step 3: Implement allowlisted official source detection**

Add to `scripts/stage2_5_injector.py`:

```python
OFFICIAL_MANUAL_SOURCE_DOMAINS = {
    ("monetary_policy", "mlf"): {"pbc.gov.cn", "chinamoney.com.cn"},
    ("forex", "USDCNY"): {"chinamoney.com.cn", "cfets.com.cn", "pbc.gov.cn"},
    ("commodities", "BCOM"): {"bloomberg.com"},
}


def _is_manual_official_value(category: str, key: str, payload: Dict[str, Any]) -> bool:
    trusted_domains = OFFICIAL_MANUAL_SOURCE_DOMAINS.get((category, key))
    if not trusted_domains:
        return False

    source_url = payload.get("source_url")
    if not isinstance(source_url, str):
        return False

    evidence_urls = _collect_url_like_evidence(payload)
    if len(evidence_urls) != 1 or evidence_urls[0] != source_url:
        return False

    return _is_trusted_https_url(source_url, trusted_domains)


def _apply_manual_official_estimation_rule(category: str, key: str, payload: Dict[str, Any], entry: Dict[str, Any]) -> None:
    if _is_manual_official_value(category, key, payload):
        entry["is_estimated"] = False
        _append_note(entry, "manual_official_not_estimated")
```

Official override is intentionally narrow:

- It only applies to `monetary_policy.mlf`, `forex.USDCNY`, and `commodities.BCOM`.
- It requires trusted official HTTPS URL evidence, and every URL-like evidence string in the payload must pass the trusted-domain check.
- Explicit URL fields must contain one string URL only. Mixed prose, multiple URLs, non-HTTPS URLs, invalid ports, untrusted/spoof/conflicting URLs, and bare-domain evidence do not trigger official override.
- Issuer/name text without a URL does not trigger official override.
- ETF/fund flow is not allowlisted. Ordinary manual sources should not be automatically marked estimated or blocked just because the domain is not official.

Call this helper after each manual payload merge for monetary, forex, and commodities. Keep bonds and ETF/fund flow outside this official override unless a future rule explicitly allowlists them.

- [ ] **Step 4: Ensure true estimates remain estimated**

Add a test where ETF fund flow has `is_estimated=True` and `source_url=https://eastmoney.com/...`; assert it remains estimated or quality-blocked according to existing rules. Do not add ETF to the allowlist.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python -m pytest tests/test_websearch_injector.py::test_manual_official_mlf_payload_is_not_estimated tests/test_websearch_injector.py::test_manual_official_usdcny_payload_is_not_estimated tests/test_fix_estimated_verified.py tests/test_policy_rules.py -q
```

Expected: selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/stage2_5_injector.py tests/test_websearch_injector.py tests/test_policy_rules.py
git commit -m "fix: classify official manual values as verified"
```

## Task 8: Display Non-Uniform MLF Values as Reference Values

**Files:**
- Modify: `src/datasource/generators/simple_report.py`
- Modify: `tests/test_stage4_docs.py`

- [ ] **Step 1: Add MLF display test**

Append to `tests/test_stage4_docs.py`:

```python
from datasource.generators.simple_report import _format_monetary_value_for_report


def test_stage4_mlf_non_unified_rate_display():
    entry = {
        "current_value": 2.0,
        "change_120d_bp": 0.0,
        "note": "MLF 多重价位中标利率参考值，口径不适用",
        "as_of_date": "2026-04-25",
    }

    current, change = _format_monetary_value_for_report("mlf", entry)

    assert current == "2.00%（参考）"
    assert change == "口径不适用"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
python -m pytest tests/test_stage4_docs.py::test_stage4_mlf_non_unified_rate_display -q
```

Expected: import or assertion failure because `_format_monetary_value_for_report` does not exist.

- [ ] **Step 3: Implement report helper**

Add to `src/datasource/generators/simple_report.py` near other format helpers:

```python
def _is_non_unified_mlf(entry: dict) -> bool:
    text = " ".join(str(entry.get(field) or "") for field in ("note", "source", "manual_reason"))
    markers = ("多重价位", "中标利率", "参考值", "口径不适用")
    return any(marker in text for marker in markers)


def _format_monetary_value_for_report(key: str, entry: dict) -> tuple[str, str]:
    value = _to_float(entry.get("current_value"))
    if value is None:
        current = "N/A"
    elif key == "mlf" and _is_non_unified_mlf(entry):
        current = f"{value:.2f}%（参考）"
    else:
        current = f"{value:.2f}%"

    bp = _to_float(entry.get("change_120d_bp"))
    if key == "mlf" and _is_non_unified_mlf(entry):
        change = "口径不适用"
    elif bp is None:
        change = "N/A"
    else:
        change = _fmt_bp(bp)
    return current, change
```

Update the monetary policy table generation to use `_format_monetary_value_for_report(key, entry)` for current value and 120-day change.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python -m pytest tests/test_stage4_docs.py::test_stage4_mlf_non_unified_rate_display tests/test_stage4_docs.py -q
```

Expected: selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/datasource/generators/simple_report.py tests/test_stage4_docs.py
git commit -m "fix: clarify mlf reference rate display"
```

## Task 9: Sync Durable Docs and Final Verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `.env.example`

- [ ] **Step 1: Update `AGENTS.md` durable rules**

Add or adjust these durable rules:

```markdown
- `run_clean.sh` 激活顺序为 `.venv/bin/activate` -> `.venv/Scripts/activate` -> 显式 `ALLOW_SYSTEM_PYTHON=1` 系统 Python fallback；fallback 仍会 source `.env`、清理代理并设置 `PYTHONPATH=./src`。
- Stage2 Tavily quota/rate limit 后同轮快切为 manual_required skeleton，不新增 quota probe，不重复消耗当日 Tavily。
- Stage2 summary 以 `retrieval_diagnostics`、`manual_reason_breakdown` 判断检索/抽取/写回问题，不只看 `task_search_success`。
- Exa 默认关闭；只有配置 `EXA_API_KEY` 且显式传 `--enable-exa-fallback` 或设置 `STAGE2_ENABLE_EXA_FALLBACK=1` 时才作为 Tavily 后备。当前日常路径先提升 Tavily 命中率，不启用 Exa。
- DeepSeek 默认模型为 `deepseek-v4-pro`，`DEEPSEEK_MODEL` 或命令行参数可覆盖。
- MLF 多重价位或参考口径在报告中显示为参考值，120日变化显示 `口径不适用`。
```

- [ ] **Step 2: Update `CLAUDE.md` quick reminders**

Add short reminders:

```markdown
- DeepSeek 默认模型：`deepseek-v4-pro`。
- Exa fallback 默认关闭；只有配置 `EXA_API_KEY` 且显式传 `--enable-exa-fallback` 或设置 `STAGE2_ENABLE_EXA_FALLBACK=1` 才作为 Tavily 后备。当前日常路径先提升 Tavily 命中率，不启用 Exa。
- `.venv` 缺失时可显式使用：`ALLOW_SYSTEM_PYTHON=1 bash run_clean.sh ...`。
```

- [ ] **Step 3: Run documentation and targeted verification**

Run:

```bash
git diff --check
python -m pytest tests/test_run_clean.py tests/test_deepseek_defaults.py tests/test_exa_client.py tests/test_stage2_health_check.py tests/test_stage2_fallbacks.py tests/test_stage2_unified.py tests/test_websearch_injector.py tests/test_stage4_docs.py -q
```

Expected: `git diff --check` passes. Targeted tests pass, except any existing failures in broad files must be isolated and listed with exact test names.

- [ ] **Step 4: Run full suite and compare with known baseline**

Run:

```bash
python -m pytest -q
```

Expected: either full suite passes, or failures are limited to the known baseline classes listed in this plan. If new failures appear, fix them before committing.

- [ ] **Step 5: Commit docs**

```bash
git add AGENTS.md CLAUDE.md .env.example
git commit -m "docs: document daily pipeline hardening"
```

## Final Review Gate

- [ ] **Step 1: Verify branch status**

Run:

```bash
git status --short --branch
git log --oneline --decorate -10
```

Expected: branch is `codex/daily-pipeline-hardening` and worktree is clean.

- [ ] **Step 2: Run final diff check**

Run:

```bash
git diff --check main...HEAD
```

Expected: no output.

- [ ] **Step 3: Request final code review**

Use `superpowers:requesting-code-review` after all tasks are complete. The reviewer must check:

```text
- run_clean fallback behavior is explicit and does not silently choose system Python.
- Stage2 does not add Tavily quota probes.
- Exa fallback diagnostics are structured and do not replace good Tavily snippets on failure.
- DeepSeek defaults are `deepseek-v4-pro`.
- Stage2.5 official manual values are not estimated, while ETF estimates remain constrained.
- MLF report display is not misleading.
- Docs match behavior.
```

## Self-Review

Spec coverage:

- `run_clean.sh` fallback: Task 1.
- DeepSeek `deepseek-v4-pro`: Task 2.
- Exa fallback exploration and diagnostics: Tasks 3 and 4.
- Stage2 fast switch and diagnostics: Task 5.
- Stage2 hit-rate profile tuning: Task 6.
- Manual official vs estimated values: Task 7.
- MLF reference display: Task 8.
- `AGENTS.md`, `CLAUDE.md`, `.env.example`: Tasks 2 and 9.

Type consistency:

- Exa structured fields use the same names across tasks: `exa_error_type`, `exa_http_status`, `exa_error_tag`, `exa_error_message`, `exa_reason`, `exa_query`, `exa_domains`, `exa_result_count`, `exa_usable_count`.
- Retrieval diagnostics use the same names across tests and summary: `retrieval_diagnostics`, `retrieval_hit_rate`, `writeback_success_rate`, `manual_reason_breakdown`.
- Manual official detection uses `category`, `key`, `payload`, and mutates the merged `entry`.

Execution choice after this plan:

1. Subagent-Driven: dispatch one fresh subagent per task, run spec review and code quality review after each task.
2. Inline Execution: execute tasks in this session using the same task order and commit gates.
