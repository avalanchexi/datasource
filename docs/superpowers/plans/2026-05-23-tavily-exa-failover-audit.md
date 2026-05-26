# Tavily 432/433 Exa Failover Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Tavily HTTP 432/433 activate the existing Exa failover path, add safe Tavily diagnostics to auditable outputs, and preserve ETF fund-flow Stage3 blocking.

**Architecture:** Keep Stage2's existing Tavily-first state machine and add the missing Tavily limit statuses to the shared classifier. Add a small safe metadata helper in `scripts/stage2_unified_enhancer.py`, propagate its output through manual-required skeletons and summary diagnostics, and cover the ETF gate with focused regression tests.

**Tech Stack:** Python, pytest, async pytest via `pytest.mark.anyio`, existing Stage2/Stage3 pipeline helpers.

---

## File Structure

- Modify `scripts/stage2_unified_enhancer.py`
  - Owns Stage2 search execution, Tavily/Exa failover, diagnostics, websearch result skeletons, and Stage2 summary fields.
  - Add shared Tavily limit status constants and safe Tavily metadata helpers near the existing `_is_tavily_quota_error` functions.
  - Propagate Tavily metadata through `_build_tavily_fast_switch_records`, `_build_exa_failover_manual_records`, and `_execute_tasks`.
- Modify `tests/test_stage2_fallbacks.py`
  - Owns Stage2 failover behavior tests.
  - Add 432/433 classifier tests and end-to-end failover/skeleton tests.
- Modify `tests/test_stage2_unified.py`
  - Owns Stage2 helper and summary diagnostics tests.
  - Add a summary persistence test for Tavily metadata.
- Modify `tests/test_stage3_guard.py`
  - Owns Stage3 preflight guard behavior.
  - Add an ETF missing-window test proving `--allow-estimated` does not bypass the fund-flow window gate.
- Modify `AGENTS.md`
  - Update long-lived operating guidance so future runs identify Tavily 432/433 as quota/payment limit responses eligible for Exa failover.

## Task 1: Tavily Limit Classifier and Safe Metadata Helper

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py:285-330`
- Modify: `tests/test_stage2_fallbacks.py:1-12`
- Test: `tests/test_stage2_fallbacks.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_stage2_fallbacks.py`, change the import:

```python
from scripts.stage2_unified_enhancer import _execute_tasks, _is_tavily_quota_error
```

to:

```python
from scripts.stage2_unified_enhancer import (
    _execute_tasks,
    _is_tavily_quota_error,
    _is_tavily_quota_response,
    _tavily_error_metadata,
)
```

Then insert these helper classes and tests after `FakeExtractorTimeout`:

```python
class FakeTavilyResponse:
    def __init__(self, status_code, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def _make_tavily_http_error(status_code, text="", headers=None):
    exc = RuntimeError(f"Client error '{status_code} ' for url 'https://api.tavily.com/search'")
    exc.response = FakeTavilyResponse(status_code, text=text, headers=headers)
    return exc


@pytest.mark.parametrize("status_code", [402, 403, 429, 432, 433])
def test_tavily_quota_error_classifier_covers_http_limit_statuses(status_code):
    exc = _make_tavily_http_error(status_code)

    assert _is_tavily_quota_error(exc) is True


@pytest.mark.parametrize("status_code", [402, 403, 429, 432, 433])
def test_tavily_quota_response_classifier_covers_http_limit_statuses(status_code):
    assert _is_tavily_quota_response({"status": status_code, "error": "limit reached"}) is True
    assert _is_tavily_quota_response({"status": str(status_code), "detail": "limit reached"}) is True


def test_tavily_error_metadata_is_safe_and_includes_status_message_and_request_id():
    exc = _make_tavily_http_error(
        432,
        text='{"detail":"Key limit exceeded","api_key":"secret-value-that-must-not-leak"}',
        headers={"x-request-id": "tavily-req-432"},
    )

    metadata = _tavily_error_metadata(exc)

    assert metadata["tavily_http_status"] == 432
    assert metadata["tavily_error_type"] == "RuntimeError"
    assert metadata["tavily_request_id"] == "tavily-req-432"
    assert "Key limit exceeded" in metadata["tavily_error_message"]
    assert "secret-value-that-must-not-leak" not in metadata["tavily_error_message"]
    assert "[redacted]" in metadata["tavily_error_message"]
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_stage2_fallbacks.py::test_tavily_quota_error_classifier_covers_http_limit_statuses \
  tests/test_stage2_fallbacks.py::test_tavily_quota_response_classifier_covers_http_limit_statuses \
  tests/test_stage2_fallbacks.py::test_tavily_error_metadata_is_safe_and_includes_status_message_and_request_id
```

Expected: FAIL during test collection with an import error for `_tavily_error_metadata`.

- [ ] **Step 3: Implement shared limit status and metadata helpers**

In `scripts/stage2_unified_enhancer.py`, replace the current `_is_tavily_quota_error`, `_text_indicates_quota_or_rate_limit`, and `_is_tavily_quota_response` block with this code:

```python
_TAVILY_LIMIT_STATUSES = {402, 403, 429, 432, 433}
_TAVILY_ERROR_TEXT_LIMIT = 500
_TAVILY_REQUEST_ID_HEADERS = (
    "x-request-id",
    "x-tavily-request-id",
    "x-tavily-trace-id",
    "request-id",
)


def _coerce_http_status(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_header_value(headers: Any, names: Tuple[str, ...]) -> Optional[str]:
    if not headers:
        return None
    for name in names:
        value = None
        try:
            value = headers.get(name)
        except AttributeError:
            value = None
        if value is None:
            try:
                value = headers.get(name.lower())
            except AttributeError:
                value = None
        if value:
            return str(value)
    return None


def _sanitize_tavily_error_text(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    sanitized = re.sub(
        r"(?i)(api[_-]?key[\"']?\\s*[:=]\\s*)[\"']?[^\"'\\s,}]+",
        r"\1[redacted]",
        raw,
    )
    if len(sanitized) > _TAVILY_ERROR_TEXT_LIMIT:
        return sanitized[:_TAVILY_ERROR_TEXT_LIMIT] + "...[truncated]"
    return sanitized


def _tavily_error_metadata(source: Any) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    response = getattr(source, "response", None)

    if isinstance(source, dict):
        status = _coerce_http_status(source.get("status") or source.get("status_code"))
        message = " ".join(
            str(source.get(key) or "")
            for key in ("error", "message", "detail", "warning")
            if source.get(key)
        )
        request_id = source.get("request_id") or source.get("tavily_request_id")
        error_type = "tavily_response"
    else:
        status = _coerce_http_status(getattr(response, "status_code", None))
        message = getattr(response, "text", None) or str(source or "")
        request_id = _safe_header_value(
            getattr(response, "headers", None),
            _TAVILY_REQUEST_ID_HEADERS,
        )
        error_type = source.__class__.__name__

    if status is not None:
        metadata["tavily_http_status"] = status
    metadata["tavily_error_type"] = error_type
    sanitized_message = _sanitize_tavily_error_text(message)
    if sanitized_message:
        metadata["tavily_error_message"] = sanitized_message
    if request_id:
        metadata["tavily_request_id"] = str(request_id)
    return metadata


def _is_tavily_quota_error(exc: Exception) -> bool:
    status = _coerce_http_status(getattr(getattr(exc, "response", None), "status_code", None))
    if status in _TAVILY_LIMIT_STATUSES:
        return True
    return _text_indicates_quota_or_rate_limit(str(exc))


def _text_indicates_quota_or_rate_limit(text: Any) -> bool:
    msg = str(text or "").lower()
    return any(
        token in msg
        for token in [
            "quota",
            "rate limit",
            "rate-limit",
            "rate_limited",
            "ratelimit",
            "too many requests",
            "usage limit",
            "plan limit",
            "key limit",
            "paygo",
            "billing",
            "payment",
            "402",
            "403",
            "429",
            "432",
            "433",
        ]
    )


def _is_tavily_quota_response(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    status_int = _coerce_http_status(payload.get("status") or payload.get("status_code"))
    if status_int in _TAVILY_LIMIT_STATUSES:
        return True
    return _text_indicates_quota_or_rate_limit(
        " ".join(
            str(payload.get(key) or "")
            for key in ("error", "message", "detail", "warning")
        )
    )
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_stage2_fallbacks.py::test_tavily_quota_error_classifier_covers_http_limit_statuses \
  tests/test_stage2_fallbacks.py::test_tavily_quota_response_classifier_covers_http_limit_statuses \
  tests/test_stage2_fallbacks.py::test_tavily_error_metadata_is_safe_and_includes_status_message_and_request_id
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_fallbacks.py
git commit -m "fix: classify tavily 432 433 as limit errors"
```

## Task 2: Propagate Tavily Diagnostics Through Failover Records

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py:2530-2620`
- Modify: `scripts/stage2_unified_enhancer.py:2874-3050`
- Modify: `scripts/stage2_unified_enhancer.py:3740-4305`
- Modify: `scripts/stage2_unified_enhancer.py:4715-4745`
- Modify: `tests/test_stage2_fallbacks.py`

- [ ] **Step 1: Write the failing tests**

Add this Tavily client after `QuotaTavilyClient` in `tests/test_stage2_fallbacks.py`:

```python
class Limit432TavilyClient:
    def __init__(self):
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        raise _make_tavily_http_error(
            432,
            text='{"detail":"Key limit exceeded for current plan"}',
            headers={"x-request-id": "tavily-search-432"},
        )

    async def extract(self, **kwargs):  # pragma: no cover - search raises before extract
        raise AssertionError("extract should not run after Tavily 432 search failure")
```

Add this test after `test_tavily_quota_without_exa_records_exa_unavailable`:

```python
@pytest.mark.anyio("asyncio")
async def test_tavily_432_without_exa_writes_safe_tavily_diagnostics_to_skeleton(tmp_path):
    client = Limit432TavilyClient()
    stats = {}
    tasks = [{
        "task_id": "quota-gold-432-no-exa",
        "indicator_key": "GC=F",
        "stage_phase": "assets",
        "category": "commodities",
        "search_backend": "tavily",
        "query": "COMEX gold latest price",
        "unit": "$/oz",
        "created_at": 1700000000,
        "preferred_domains": [],
    }]

    completed, failures, websearch_results = await _execute_tasks(
        tasks,
        {"commodities": []},
        client,
        None,
        NoopExtractor(),
        task_log_path=tmp_path / "task_log.jsonl",
        cache_ttl=None,
        fund_flow_backend="tavily",
        forex_backend="tavily",
        deepseek_timeout=8,
        extraction_backend="deepseek",
        deepseek_max_concurrency=1,
        deepseek_serial_keys=None,
        stats=stats,
        use_queue=False,
        queue_concurrency=1,
        queue_maxsize=10,
        queue_retry_limit=0,
        disable_extract=False,
        extract_topk=1,
        llm_hard_timeout=10,
    )

    assert completed == []
    assert len(failures) == 1
    assert len(websearch_results) == 1
    assert failures[0]["manual_required"] is True
    assert failures[0]["manual_reason"] in {"quota_or_rate_limit", "exa_unavailable"}
    assert failures[0]["tavily_http_status"] == 432
    assert failures[0]["tavily_request_id"] == "tavily-search-432"
    assert "Key limit exceeded" in failures[0]["tavily_error_message"]
    assert websearch_results[0]["tavily_http_status"] == 432
    assert websearch_results[0]["task"]["tavily_http_status"] == 432
    assert websearch_results[0]["extraction"]["tavily_http_status"] == 432
    assert stats["tavily_limit_error_count"] == 1
    assert stats["tavily_error_samples"][0]["tavily_http_status"] == 432
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_stage2_fallbacks.py::test_tavily_432_without_exa_writes_safe_tavily_diagnostics_to_skeleton
```

Expected: FAIL because `_execute_tasks` does not yet attach `tavily_http_status`, `tavily_request_id`, `tavily_error_message`, or `tavily_limit_error_count` to the skeleton/stat fields.

- [ ] **Step 3: Implement diagnostic recording in `_execute_tasks`**

Inside `_execute_tasks`, after `_mark_environment_proxy_unavailable`, add:

```python
    def _record_tavily_limit_error(source: Any) -> Dict[str, Any]:
        metadata = _tavily_error_metadata(source)
        stats["tavily_limit_error_count"] = stats.get("tavily_limit_error_count", 0) + 1
        samples = stats.setdefault("tavily_error_samples", [])
        if isinstance(samples, list) and len(samples) < 5:
            samples.append(metadata)
        return metadata
```

Update `_build_exa_failover_manual_records` signature from:

```python
        exa_metadata: Optional[Dict[str, Any]] = None,
```

to:

```python
        exa_metadata: Optional[Dict[str, Any]] = None,
        tavily_metadata: Optional[Dict[str, Any]] = None,
```

At the top of `_build_exa_failover_manual_records`, after `category = task.get("category") or task.get("stage_phase")`, add:

```python
        diagnostics = {**(tavily_metadata or {}), **(exa_metadata or {})}
```

Then replace each `**(exa_metadata or {}),` in `task_payload`, `extraction`, `task_record`, and `websearch_item` with:

```python
            **diagnostics,
```

Update `_build_tavily_fast_switch_records` signature from:

```python
        query_attempts: Optional[List[Dict[str, Any]]] = None,
```

to:

```python
        query_attempts: Optional[List[Dict[str, Any]]] = None,
        tavily_metadata: Optional[Dict[str, Any]] = None,
```

At the top of `_build_tavily_fast_switch_records`, after `category = task.get("category") or task.get("stage_phase")`, add:

```python
        diagnostics = tavily_metadata or {}
```

Then add `**diagnostics,` as the first entry inside `task_payload`, `extraction`, `task_record`, and `websearch_item`.

In every quota exception branch, call `_record_tavily_limit_error(exc)` once and pass the result to whichever manual skeleton is created. For example, in the search exception handler, change:

```python
                        is_quota_error = False if is_proxy_error else _is_tavily_quota_error(exc)
                        exa_metadata: Dict[str, Any] = {}
```

to:

```python
                        is_quota_error = False if is_proxy_error else _is_tavily_quota_error(exc)
                        tavily_metadata = _record_tavily_limit_error(exc) if is_quota_error else {}
                        exa_metadata: Dict[str, Any] = {}
```

In that same handler, pass `tavily_metadata=tavily_metadata` to both `_build_exa_failover_manual_records(...)` and `_build_tavily_fast_switch_records(...)`.

Apply the same pattern to the extract exception quota branch:

```python
                        if _is_tavily_quota_error(exc):
                            elapsed_ms = int((time.perf_counter() - started) * 1000)
                            tavily_metadata = _record_tavily_limit_error(exc)
```

and pass `tavily_metadata=tavily_metadata` to both manual-record builders in that branch.

Apply the same pattern to the outer exception quota branch near the end of `_execute_tasks`:

```python
                    if _is_tavily_quota_error(exc):
                        _mark_tavily_quota_unavailable()
                        tavily_metadata = _record_tavily_limit_error(exc)
```

and pass `tavily_metadata=tavily_metadata` into `_build_tavily_fast_switch_records(...)`.

- [ ] **Step 4: Run the focused test to verify it passes**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_stage2_fallbacks.py::test_tavily_432_without_exa_writes_safe_tavily_diagnostics_to_skeleton
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_fallbacks.py
git commit -m "fix: audit tavily limit diagnostics"
```

## Task 3: 432/433 End-to-End Exa Failover for Search and Extract

**Files:**
- Modify: `tests/test_stage2_fallbacks.py`
- Modify: `scripts/stage2_unified_enhancer.py:4085-4155`
- Modify: `scripts/stage2_unified_enhancer.py:4225-4305`

- [ ] **Step 1: Write the failing tests**

Add this extract client after `ExtractQuotaResponseTavilyClient`:

```python
class ExtractLimit433ResponseTavilyClient(ExtractQuotaTavilyClient):
    async def extract(self, **kwargs):
        self.extract_calls += 1
        return {
            "status": 433,
            "error": "PayGo limit exceeded",
            "request_id": "tavily-extract-433",
            "results": [],
        }
```

Add these tests after `test_tavily_quota_switches_current_and_remaining_tasks_to_exa` and after `test_tavily_extract_quota_response_switches_current_and_remaining_tasks_to_exa`:

```python
@pytest.mark.anyio("asyncio")
async def test_tavily_432_search_switches_current_and_remaining_tasks_to_exa(tmp_path):
    client = Limit432TavilyClient()
    exa = RecordingExaClient(request_id="exa-after-432")
    stats = {}
    tasks = [
        {
            "task_id": "quota-432-gold",
            "indicator_key": "GC=F",
            "stage_phase": "assets",
            "category": "commodities",
            "search_backend": "tavily",
            "query": "COMEX gold latest price",
            "unit": "$/oz",
            "created_at": 1700000000,
            "preferred_domains": [],
        },
        {
            "task_id": "quota-432-oil",
            "indicator_key": "CL=F",
            "stage_phase": "assets",
            "category": "commodities",
            "search_backend": "tavily",
            "query": "WTI crude latest price",
            "unit": "$/bbl",
            "created_at": 1700000001,
            "preferred_domains": [],
        },
    ]

    completed, failures, websearch_results = await _execute_tasks(
        tasks,
        {"commodities": []},
        client,
        exa,
        ValueExtractor(),
        task_log_path=tmp_path / "task_log.jsonl",
        cache_ttl=None,
        fund_flow_backend="tavily",
        forex_backend="tavily",
        deepseek_timeout=8,
        extraction_backend="deepseek",
        deepseek_max_concurrency=1,
        deepseek_serial_keys=None,
        stats=stats,
        use_queue=False,
        queue_concurrency=1,
        queue_maxsize=10,
        queue_retry_limit=0,
        disable_extract=False,
        extract_topk=1,
        llm_hard_timeout=10,
    )

    assert client.calls == 1
    assert len(exa.calls) == 2
    assert len(completed) == 2
    assert failures == []
    assert stats["tavily_to_exa_failover"] is True
    assert stats["tavily_to_exa_failover_count"] == 1
    assert stats["search_backend_final"] == "exa"
    assert stats["tavily_limit_error_count"] == 1
    assert stats["tavily_error_samples"][0]["tavily_http_status"] == 432
    assert all(item["search_backend"] == "exa" for item in websearch_results)
    assert all(item["task"]["search_backend_state"] == "exa_active" for item in websearch_results)


@pytest.mark.anyio("asyncio")
async def test_tavily_extract_433_response_switches_current_and_remaining_tasks_to_exa(tmp_path):
    client = ExtractLimit433ResponseTavilyClient()
    exa = RecordingExaClient(request_id="exa-after-433")
    stats = {}
    tasks = [
        {
            "task_id": "extract-433-gold",
            "indicator_key": "GC=F",
            "stage_phase": "assets",
            "category": "commodities",
            "search_backend": "tavily",
            "query": "COMEX gold latest price",
            "unit": "$/oz",
            "created_at": 1700000000,
            "preferred_domains": [],
            "extract_policy": {"use_tavily_extract": True, "extract_topk": 1},
        },
        {
            "task_id": "extract-433-oil",
            "indicator_key": "CL=F",
            "stage_phase": "assets",
            "category": "commodities",
            "search_backend": "tavily",
            "query": "WTI crude latest price",
            "unit": "$/bbl",
            "created_at": 1700000001,
            "preferred_domains": [],
            "extract_policy": {"use_tavily_extract": True, "extract_topk": 1},
        },
    ]

    completed, failures, websearch_results = await _execute_tasks(
        tasks,
        {"commodities": []},
        client,
        exa,
        ValueExtractor(),
        task_log_path=tmp_path / "task_log.jsonl",
        cache_ttl=None,
        fund_flow_backend="tavily",
        forex_backend="tavily",
        deepseek_timeout=8,
        extraction_backend="deepseek",
        deepseek_max_concurrency=1,
        deepseek_serial_keys=None,
        stats=stats,
        use_queue=False,
        queue_concurrency=1,
        queue_maxsize=10,
        queue_retry_limit=0,
        disable_extract=False,
        extract_topk=1,
        llm_hard_timeout=10,
    )

    assert client.search_calls == 1
    assert client.extract_calls == 1
    assert len(exa.calls) == 2
    assert len(completed) == 2
    assert failures == []
    assert stats["tavily_to_exa_failover"] is True
    assert stats["search_backend_final"] == "exa"
    assert stats["tavily_limit_error_count"] == 1
    assert stats["tavily_error_samples"][0]["tavily_http_status"] == 433
    assert all(item["search_backend"] == "exa" for item in websearch_results)
```

- [ ] **Step 2: Run the new 433 extract-response test to verify it fails**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_stage2_fallbacks.py::test_tavily_extract_433_response_switches_current_and_remaining_tasks_to_exa
```

Expected: FAIL because the extract-response path does not yet record Tavily payload metadata in `tavily_limit_error_count` or `tavily_error_samples`.

- [ ] **Step 3: Implement extract-response metadata recording**

In the Tavily extract response branch that starts with:

```python
                                    if _is_tavily_quota_response(extract_resp):
                                        elapsed_ms = int((time.perf_counter() - started) * 1000)
```

change it to:

```python
                                    if _is_tavily_quota_response(extract_resp):
                                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                                        tavily_metadata = _record_tavily_limit_error(extract_resp)
```

In that branch, pass `tavily_metadata=tavily_metadata` to `_build_exa_failover_manual_records(...)` and `_build_tavily_fast_switch_records(...)`.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_stage2_fallbacks.py::test_tavily_432_search_switches_current_and_remaining_tasks_to_exa \
  tests/test_stage2_fallbacks.py::test_tavily_extract_433_response_switches_current_and_remaining_tasks_to_exa
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_fallbacks.py
git commit -m "fix: fail over tavily 432 433 to exa"
```

## Task 4: Summary Diagnostics and ETF Stage3 Gate Regression

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py:2127-2165`
- Modify: `tests/test_stage2_unified.py`
- Modify: `tests/test_stage3_guard.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_stage2_unified.py`, add this test after `test_stage2_summary_includes_exa_failover_diagnostics`:

```python
def test_stage2_summary_includes_tavily_limit_error_diagnostics():
    summary = stage2._build_stage2_summary_diagnostics(
        completed_tasks=[],
        failures=[],
        websearch_results=[],
        exec_stats={
            "tavily_limit_error_count": 1,
            "tavily_error_samples": [
                {
                    "tavily_http_status": 432,
                    "tavily_request_id": "tavily-summary-432",
                    "tavily_error_message": "Key limit exceeded",
                }
            ],
        },
    )

    assert summary["tavily_limit_error_count"] == 1
    assert summary["tavily_error_samples"][0]["tavily_http_status"] == 432
    assert summary["tavily_error_samples"][0]["tavily_request_id"] == "tavily-summary-432"
```

In `tests/test_stage3_guard.py`, add this test after `test_require_data_completeness_blocks_estimated_fund_flow_even_with_allow_estimated`:

```python
def test_require_data_completeness_blocks_etf_missing_windows_even_with_allow_estimated():
    payload = {
        "metadata": {"data_completeness": 0.9737},
        "missing_items": [],
        "fund_flow": {
            "etf": {
                "recent_5d": None,
                "total_120d": None,
                "trend": "待核查",
                "source": "异常零值-需核查",
                "source_url": "https://data.eastmoney.com/etf/",
                "manual_required": True,
                "manual_reason": "fund_flow_window_missing",
                "is_estimated": False,
            }
        },
    }

    with pytest.raises(RuntimeError) as exc:
        s3._require_data_completeness(payload, 0.8, allow_estimated=True)

    message = str(exc.value)
    assert "fund_flow.etf" in message
    assert "fund_flow_window_missing" in message
    assert "recent_5d" in message
    assert "total_120d" in message
```

- [ ] **Step 2: Run the Stage2 summary test to verify it fails**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_stage2_unified.py::test_stage2_summary_includes_tavily_limit_error_diagnostics
```

Expected: FAIL with `KeyError: 'tavily_limit_error_count'`.

- [ ] **Step 3: Run the ETF gate regression test to verify the current gate is already strict**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_stage3_guard.py::test_require_data_completeness_blocks_etf_missing_windows_even_with_allow_estimated
```

Expected: PASS. This confirms the implementation work must not change Stage3 gate behavior.

- [ ] **Step 4: Persist Tavily diagnostics in Stage2 summary**

In `_build_stage2_summary_diagnostics`, extend `exa_failover_summary_keys` from:

```python
    exa_failover_summary_keys = (
        "search_backend_final",
        "tavily_to_exa_failover",
        "tavily_to_exa_failover_count",
        "exa_failover_success",
        "exa_failover_empty",
        "exa_failover_error",
        "exa_unavailable",
        "exa_error_breakdown",
        "exa_error_samples",
    )
```

to:

```python
    exa_failover_summary_keys = (
        "search_backend_final",
        "tavily_to_exa_failover",
        "tavily_to_exa_failover_count",
        "tavily_limit_error_count",
        "tavily_error_samples",
        "exa_failover_success",
        "exa_failover_empty",
        "exa_failover_error",
        "exa_unavailable",
        "exa_error_breakdown",
        "exa_error_samples",
    )
```

Do not change Stage3 gate code. The ETF test should verify existing behavior remains intact.

- [ ] **Step 5: Run the focused tests to verify they pass**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_stage2_unified.py::test_stage2_summary_includes_tavily_limit_error_diagnostics \
  tests/test_stage3_guard.py::test_require_data_completeness_blocks_etf_missing_windows_even_with_allow_estimated
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py tests/test_stage3_guard.py
git commit -m "test: preserve etf fund flow gate"
```

## Task 5: Long-Lived Runbook Update

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Update Stage2 runbook wording**

In `AGENTS.md`, find the Stage2 rule that currently says:

```markdown
- Tavily search/extract 遇到 quota/rate limit 后，本轮立即 fast-switch 为 `manual_required` skeleton；不新增 quota probe，不重跑当日 Tavily。排查看 summary 的 `tavily_unavailable_reason=quota_or_rate_limit`、`retrieval_diagnostics`、`manual_reason_breakdown`。
```

Replace it with:

```markdown
- Tavily search/extract 遇到 quota/rate limit/payment/plan limit 后（含 HTTP `402/403/429/432/433`），本轮立即切换搜索后端状态：有 Exa 时 `tavily_active -> exa_active` 并由 Exa 接管当前与后续任务；无 Exa 或 Exa 失败时写 `manual_required` skeleton。不新增 quota probe，不重跑当日 Tavily。排查看 summary 的 `tavily_unavailable_reason=quota_or_rate_limit`、`tavily_limit_error_count`、`tavily_error_samples`、`retrieval_diagnostics`、`manual_reason_breakdown`。
```

In the Troubleshooting table, find:

```markdown
| Tavily quota/rate limit | Tavily 额度或频率限制 | 同轮 fast-switch 为 `manual_required` skeleton；不要新增 quota probe 或重跑当日 Tavily，查看 `tavily_unavailable_reason=quota_or_rate_limit`、`retrieval_diagnostics`、`manual_reason_breakdown` 后转 Stage2.5 补数 |
```

Replace it with:

```markdown
| Tavily quota/rate/payment/plan limit | Tavily 额度、频率、计费或计划限制，常见 HTTP `402/403/429/432/433` | 有 Exa 时同轮切换到 `exa_active` 接管当前与后续任务；无 Exa 或 Exa 失败时写 `manual_required` skeleton。不要新增 quota probe 或重跑当日 Tavily，查看 `tavily_unavailable_reason=quota_or_rate_limit`、`tavily_limit_error_count`、`tavily_error_samples`、`retrieval_diagnostics`、`manual_reason_breakdown` 后决定是否转 Stage2.5 补数 |
```

- [ ] **Step 2: Review docs diff**

Run:

```bash
git diff -- AGENTS.md
```

Expected: diff only documents 432/433 Exa failover behavior and does not change unrelated daily-run instructions.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: document tavily limit failover codes"
```

## Task 6: Verification

**Files:**
- Verify: `scripts/stage2_unified_enhancer.py`
- Verify: `tests/test_stage2_fallbacks.py`
- Verify: `tests/test_stage2_unified.py`
- Verify: `tests/test_stage3_guard.py`
- Verify: `AGENTS.md`

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_stage2_fallbacks.py \
  tests/test_stage2_unified.py \
  tests/test_stage3_guard.py \
  tests/test_policy_rules.py \
  tests/test_fund_flow_pipeline.py
```

Expected: all tests pass. The current clean baseline before this plan was `149 passed, 1 skipped` for the Stage2/Policy/Fund Flow subset; the exact count may increase by the new tests.

- [ ] **Step 2: Run syntax check**

Run:

```bash
PYTHONPATH=src python -m py_compile scripts/stage2_unified_enhancer.py scripts/stage3_pring_analyzer.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git diff --stat main...HEAD
git diff -- scripts/stage2_unified_enhancer.py tests/test_stage2_fallbacks.py tests/test_stage2_unified.py tests/test_stage3_guard.py AGENTS.md
```

Expected: changes are limited to Tavily limit classification, diagnostics propagation, failover tests, ETF gate regression, and runbook documentation.

- [ ] **Step 5: Commit verification note if any fixups were required**

If Step 1-4 required code or test fixups, commit them:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_fallbacks.py tests/test_stage2_unified.py tests/test_stage3_guard.py AGENTS.md
git commit -m "fix: stabilize tavily exa failover audit"
```

If no fixups were required, do not create an empty commit.
