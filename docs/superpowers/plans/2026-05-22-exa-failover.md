# Exa Failover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Tavily-first Stage2 search with global Exa failover when Tavily quota, payment, forbidden, or rate-limit errors make Tavily unavailable.

**Architecture:** Keep Tavily as the normal backend. Add an in-run `active_search_backend` state to `scripts/stage2_unified_enhancer.py`; when Tavily emits 402/403/429/quota/rate/payment errors, switch to Exa for the failed task and all remaining tasks. Exa returns Tavily-compatible snippets, then existing DeepSeek/regex extraction, fund-flow gates, Stage2.5 injection, and Stage3 policy gates continue unchanged.

**Tech Stack:** Python async pipeline, `exa-py` through `AsyncExaClient`, existing Tavily client, DeepSeek extractor, pytest/anyio test suite.

---

## File Structure

- Modify `src/datasource/adapters/exa_client.py`: keep the Exa SDK boundary thin, bound Exa result text, and expose reusable structured error metadata.
- Modify `scripts/stage2_unified_enhancer.py`: own failover state, backend-aware search routing, source labels, diagnostics, and CLI initialization behavior.
- Modify `tests/test_exa_client.py`: cover Exa result mapping and error metadata.
- Modify `tests/test_stage2_fallbacks.py`: cover Tavily quota failover, extract quota failover, no Exa fallback for environment errors, and fund-flow gate preservation.
- Modify `tests/test_stage2_unified.py`: cover writeback source labels, summary diagnostics, and Exa initialization rules.
- Modify `AGENTS.md`: document the production operating contract.
- Modify `CLAUDE.md`: mirror only high-frequency Stage2 reminders from `AGENTS.md`.

## Task 1: Bound Exa Result Text And Error Metadata

**Files:**
- Modify: `src/datasource/adapters/exa_client.py`
- Test: `tests/test_exa_client.py`

- [ ] **Step 1: Write failing Exa mapping tests**

Append these tests to `tests/test_exa_client.py`:

```python
def test_exa_map_result_truncates_snippet_and_content():
    client = AsyncExaClient(api_key="test-key")
    long_text = "A" * 5000

    mapped = client._map_result({
        "url": "https://example.com/a",
        "title": "Example",
        "text": long_text,
        "summary": long_text,
        "highlights": [long_text],
        "score": 0.91,
        "publishedDate": "2026-05-22",
    })

    assert mapped["url"] == "https://example.com/a"
    assert len(mapped["snippet"]) <= client.snippet_max_chars
    assert len(mapped["content"]) <= client.content_max_chars
    assert mapped["snippet"].endswith("...")
    assert mapped["content"].endswith("...")
```

```python
def test_exa_error_metadata_extracts_status_tag_and_request_id():
    class Response:
        status_code = 429
        headers = {"x-request-id": "req-123"}

    exc = RuntimeError("rate limit exceeded")
    exc.response = Response()

    metadata = AsyncExaClient.error_metadata(exc)

    assert metadata["exa_http_status"] == 429
    assert metadata["exa_error_tag"] == "rate_limited"
    assert metadata["exa_error_type"] == "RuntimeError"
    assert metadata["exa_request_id"] == "req-123"
    assert "rate limit" in metadata["exa_error_message"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_exa_client.py -k "truncates_snippet or error_metadata"
```

Expected: fail with missing `snippet_max_chars`, missing `content_max_chars`, or missing `AsyncExaClient.error_metadata`.

- [ ] **Step 3: Add bounded result fields and error metadata**

Change `AsyncExaClient.__init__` in `src/datasource/adapters/exa_client.py`:

```python
def __init__(
    self,
    api_key: Optional[str] = None,
    max_concurrency: int = 2,
    cache: Optional[Any] = None,
    default_num_results: int = 6,
    use_autoprompt: bool = False,
    snippet_max_chars: int = 600,
    content_max_chars: int = 2000,
) -> None:
    self.api_key = api_key
    self.semaphore = asyncio.Semaphore(max_concurrency)
    self.cache = cache
    self.default_num_results = default_num_results
    self.use_autoprompt = use_autoprompt
    self.snippet_max_chars = snippet_max_chars
    self.content_max_chars = content_max_chars
    self._client: Optional[Any] = None
    self._supports_use_autoprompt: Optional[bool] = None
```

Change `_map_result`:

```python
snippet = self._truncate(highlights or summary or text or title, self.snippet_max_chars)
content = self._truncate(text or summary or highlights or "", self.content_max_chars)
```

Add this static method below `_truncate`:

```python
@staticmethod
def error_metadata(exc: Exception) -> Dict[str, Any]:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    headers = getattr(response, "headers", {}) or {}
    message = str(exc)
    lowered = message.lower()

    if status == 401:
        tag = "auth_error"
    elif status in {402, 403}:
        tag = "quota_or_payment"
    elif status == 429:
        tag = "rate_limited"
    elif isinstance(status, int) and status >= 500:
        tag = "server_error"
    elif any(token in lowered for token in ("quota", "rate limit", "payment", "billing")):
        tag = "quota_or_payment"
    else:
        tag = "unknown_error"

    request_id = None
    for key in ("x-request-id", "request-id", "x-exa-request-id"):
        if key in headers:
            request_id = headers[key]
            break

    return {
        "exa_error_type": type(exc).__name__,
        "exa_http_status": status,
        "exa_error_tag": tag,
        "exa_error_message": message,
        "exa_request_id": request_id,
    }
```

- [ ] **Step 4: Verify Exa client tests pass**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_exa_client.py
```

Expected: all `tests/test_exa_client.py` tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/datasource/adapters/exa_client.py tests/test_exa_client.py
git commit -m "feat: bound exa snippets and expose error metadata"
```

Expected: commit succeeds on branch `feat/exa-failover`.

## Task 2: Make Stage2 Writeback Source Labels Backend-Aware

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Test: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write failing source-label tests**

Append these tests to `tests/test_stage2_unified.py` and use the existing `stage2` module import in that file:

```python
def test_apply_extraction_uses_exa_deepseek_source_label():
    market_payload = {
        "commodities": [
            {"symbol": "GC=F", "name": "COMEX黄金", "current_price": None}
        ]
    }
    task = {
        "category": "commodities",
        "indicator_key": "GC=F",
        "search_backend": "exa",
        "unit": "$/oz",
    }
    extraction = {
        "value": 2400.5,
        "unit": "$/oz",
        "source_url": "https://example.com/gold",
        "confidence": 0.9,
    }

    assert stage2._apply_extraction(market_payload, task, extraction, snippets=[])
    item = market_payload["commodities"][0]
    assert item["source"] == "exa+deepseek"
    assert item["source_url"] == "https://example.com/gold"
```

```python
def test_apply_extraction_uses_exa_regex_source_label_without_source_url():
    market_payload = {
        "commodities": [
            {"symbol": "CL=F", "name": "WTI原油", "current_price": None}
        ]
    }
    task = {
        "category": "commodities",
        "indicator_key": "CL=F",
        "search_backend": "exa",
        "unit": "$/bbl",
    }
    extraction = {"value": 77.2, "unit": "$/bbl", "confidence": 0.55}

    assert stage2._apply_extraction(market_payload, task, extraction, snippets=[])
    assert market_payload["commodities"][0]["source"] == "exa_regex"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_unified.py -k "apply_extraction_uses_exa"
```

Expected: fail because `_apply_extraction` currently emits Tavily labels for all search-backed values.

- [ ] **Step 3: Add backend-aware source label helper**

Add near `_apply_extraction` in `scripts/stage2_unified_enhancer.py`:

```python
def _source_label_for_task(task: Dict[str, Any], source_url: Optional[str]) -> str:
    backend = str(task.get("search_backend") or "tavily").lower()
    if backend == "exa":
        return "exa+deepseek" if source_url else "exa_regex"
    return "tavily+deepseek" if source_url else "tavily_regex"
```

Replace the existing hard-coded source assignment inside `_apply_extraction` with:

```python
source_label = _source_label_for_task(task, source_url)
```

- [ ] **Step 4: Preserve Exa backend in non-queue writeback**

In both non-queue `_apply_extraction(...)` calls inside `_execute_tasks`, replace:

```python
_apply_extraction(market_payload, task, extraction, snippets=snippets)
```

with:

```python
_apply_extraction(market_payload, task_for_log, extraction, snippets=snippets)
```

- [ ] **Step 5: Verify source-label tests pass**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_unified.py -k "apply_extraction_uses_exa"
.venv/bin/python -m pytest -q tests/test_stage2_unified.py::test_augment_fund_flow_metadata_infers_direct_window_from_snippets
```

Expected: selected tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "fix: label exa-backed stage2 writebacks"
```

Expected: commit succeeds.

## Task 3: Add Search Quota Failover State

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Test: `tests/test_stage2_fallbacks.py`

- [ ] **Step 1: Add reusable Exa and extractor fakes**

Add these classes near the existing `QuotaTavilyClient` helpers in `tests/test_stage2_fallbacks.py`:

```python
class RecordingExaClient:
    def __init__(self, value="123.45"):
        self.calls = []
        self.value = value

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        query = kwargs.get("query") or "quote"
        return {
            "results": [{
                "url": "https://example.com/quote",
                "title": "quote",
                "snippet": f"{query} 收盘 {self.value}",
                "content": f"{query} 收盘 {self.value}",
                "score": 0.91,
                "published_date": "2026-05-22",
            }],
            "query": query,
        }


class ValueExtractor:
    async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
        return {
            "value": 123.45,
            "unit": unit_hint,
            "source_url": snippets[0].get("url") if snippets else None,
            "confidence": 0.9,
            "manual_required": False,
            "manual_reason": None,
        }
```

- [ ] **Step 2: Write failing search quota failover test**

Add this test to `tests/test_stage2_fallbacks.py`:

```python
@pytest.mark.anyio("asyncio")
async def test_tavily_quota_switches_current_and_remaining_tasks_to_exa(tmp_path):
    client = QuotaTavilyClient()
    exa = RecordingExaClient()
    stats = {}
    tasks = [
        {
            "task_id": "quota-gold",
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
            "task_id": "quota-oil",
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
    assert stats["exa_failover_success"] == 2
    assert all(item["search_backend"] == "exa" for item in websearch_results)
```

- [ ] **Step 3: Run test and verify failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_fallbacks.py -k "quota_switches_current_and_remaining"
```

Expected: fail because quota currently writes `manual_required` records instead of retrying with Exa.

- [ ] **Step 4: Add state and Exa search helper**

In `_execute_tasks`, add parameter:

```python
allow_exa_non_quota_fallback: bool = False,
```

After `stats = stats if stats is not None else {}`, add:

```python
stats.setdefault("search_backend_final", "tavily")
stats.setdefault("tavily_to_exa_failover", False)
stats.setdefault("tavily_to_exa_failover_count", 0)
stats.setdefault("exa_failover_success", 0)
stats.setdefault("exa_failover_empty", 0)
stats.setdefault("exa_failover_error", 0)
stats.setdefault("exa_unavailable", 0)
stats.setdefault("exa_error_breakdown", {})
stats.setdefault("exa_error_samples", [])
active_search_backend = "tavily"
failover_reason = None
```

Add local helpers inside `_execute_tasks` after the existing stats initialization:

```python
def _activate_exa_failover(task: Dict[str, Any], reason: str) -> bool:
    nonlocal active_search_backend, failover_reason
    if not exa_client:
        stats["exa_unavailable"] += 1
        return False
    if active_search_backend != "exa":
        active_search_backend = "exa"
        failover_reason = reason
        stats["tavily_to_exa_failover"] = True
        stats["tavily_to_exa_failover_count"] += 1
        stats["search_backend_final"] = "exa"
    return True


def _record_exa_error(metadata: Dict[str, Any]) -> None:
    tag = metadata.get("exa_error_tag") or "unknown_error"
    stats["exa_failover_error"] += 1
    stats["exa_error_breakdown"][tag] = stats["exa_error_breakdown"].get(tag, 0) + 1
    if len(stats["exa_error_samples"]) < 5:
        stats["exa_error_samples"].append(metadata)


async def _run_exa_search_for_task(
    task: Dict[str, Any],
    reason: str,
    query_override: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    if not exa_client:
        stats["exa_unavailable"] += 1
        return None, {"manual_reason": "exa_unavailable"}
    query = query_override or task.get("query") or task.get("name") or task.get("indicator_key")
    try:
        response = await exa_client.search(
            query=query,
            num_results=min(int(task.get("max_results") or 6), 8),
            include_domains=task.get("include_domains") or task.get("preferred_domains"),
            exclude_domains=task.get("exclude_domains"),
            contents={"text": True, "summary": True, "highlights": True},
        )
    except Exception as exc:
        metadata = AsyncExaClient.error_metadata(exc) if AsyncExaClient is not None else {
            "exa_error_type": type(exc).__name__,
            "exa_error_tag": "unknown_error",
            "exa_error_message": str(exc),
        }
        _record_exa_error(metadata)
        metadata["manual_reason"] = "exa_error"
        return None, metadata

    results = response.get("results") or []
    if not results:
        stats["exa_failover_empty"] += 1
        return None, {"manual_reason": "exa_empty", "exa_error_tag": "empty_results"}
    stats["exa_failover_success"] += 1
    response["search_backend"] = "exa"
    response["failover_reason"] = reason
    return response, {}
```

- [ ] **Step 5: Route Tavily search quota to Exa**

Before changing the search exception branch, rename `_build_tavily_fast_switch_records` to `_build_search_manual_required_records` and add explicit reason fields:

```python
def _build_search_manual_required_records(
    task: Dict[str, Any],
    *,
    attempt_index: int,
    elapsed_ms: int,
    manual_reason: str,
    note: str,
    search_backend: str,
    error: Optional[Exception] = None,
    query_attempts: Optional[List[Dict[str, Any]]] = None,
    extra_diagnostics: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    now_ts = int(datetime.now().timestamp())
    query = task.get("query_used") or task.get("query") or task.get("indicator_key")
    source = "Stage2 manual_required"
    category = task.get("category") or task.get("stage_phase")
    diagnostics = extra_diagnostics or {}
    task_payload = {
        **task,
        **diagnostics,
        "category": category,
        "query": query,
        "query_used": task.get("query_used") or query,
        "query_attempts": query_attempts or task.get("query_attempts") or [],
        "manual_required": True,
        "manual_reason": manual_reason,
        "source": source,
        "note": note,
        "search_backend": search_backend,
    }
    extraction = {
        **diagnostics,
        "value": None,
        "unit": task.get("unit"),
        "source_url": None,
        "confidence": 0.0,
        "note": note,
        "llm_error": str(error) if error else None,
        "llm_latency_ms": 0,
        "manual_required": True,
        "manual_reason": manual_reason,
    }
    task_record = {
        **diagnostics,
        "task_id": task["task_id"],
        "indicator_key": task["indicator_key"],
        "category": category,
        "stage_phase": task["stage_phase"],
        "query": query,
        "search_backend": search_backend,
        "fund_flow_backend": task.get("fund_flow_backend"),
        "extraction_backend": extraction_backend,
        "source": source,
        "source_url": None,
        "confidence": 0.0,
        "error": str(error) if error else None,
        "llm_error": str(error) if error else None,
        "llm_latency_ms": None,
        "attempt_index": attempt_index,
        "elapsed_ms": elapsed_ms,
        "created_at": task.get("created_at", now_ts),
        "finished_at": now_ts,
        "manual_required": True,
        "manual_reason": manual_reason,
        "note": note,
        "raw_results": [],
        "result_type": "manual_required",
    }
    websearch_item = {
        **diagnostics,
        "task_id": task["task_id"],
        "indicator_key": task["indicator_key"],
        "category": category,
        "stage_phase": task["stage_phase"],
        "query": query,
        "task": task_payload,
        "extraction": extraction,
        "extraction_backend": extraction_backend,
        "raw_results": [],
        "search_backend": search_backend,
        "manual_required": True,
        "manual_reason": manual_reason,
        "source": source,
        "note": note,
        "result_type": "manual_required",
    }
    if manual_reason == "quota_or_rate_limit":
        task_record["tavily_fast_switch"] = True
        websearch_item["tavily_fast_switch"] = True
        task_payload["tavily_fast_switch"] = True
        extraction["tavily_fast_switch"] = True
    return task_record, websearch_item
```

Replace existing `_build_tavily_fast_switch_records(...)` call sites with `_build_search_manual_required_records(...)` using:

```python
manual_reason="quota_or_rate_limit"
note="tavily_fast_switch:quota_or_rate_limit"
search_backend=task.get("search_backend", "tavily")
```

Then, in the Tavily search exception branch, keep environment errors first. For quota errors, replace the immediate manual-required path with:

```python
if _is_tavily_quota_error(exc):
    _mark_tavily_quota_unavailable(str(exc))
    if _activate_exa_failover(task, "quota_or_rate_limit"):
        search_response, exa_diag = await _run_exa_search_for_task(task, "quota_or_rate_limit")
        if search_response:
            search_backend = "exa"
            task_for_log = {
                **task,
                "search_backend": "exa",
                "search_backend_state": "exa_active",
                "failover_reason": failover_reason,
            }
            raw_results = search_response.get("results") or []
            snippets = raw_results
            search_meta = search_response
        else:
            manual_reason = exa_diag.get("manual_reason", "exa_error")
            task_record, websearch_item = _build_search_manual_required_records(
                task_for_log,
                attempt_index=attempt,
                elapsed_ms=elapsed_ms,
                manual_reason=manual_reason,
                note=f"{manual_reason}:exa_failover",
                search_backend="exa",
                error=exc,
                extra_diagnostics=exa_diag,
            )
    else:
        # Keep the existing quota manual-required fast-switch behavior.
```

Use the same snippet filtering and extraction code that Tavily search uses after `snippets` is assigned. Do not duplicate extraction logic.

- [ ] **Step 6: Verify new failover test passes**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_fallbacks.py -k "quota_switches_current_and_remaining"
```

Expected: the new test passes.

Commit after Task 4 updates old quota tests to the new compatibility contract.

## Task 4: Preserve Manual Fast-Switch When Exa Is Missing And Keep 422 Local

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Test: `tests/test_stage2_fallbacks.py`

- [ ] **Step 1: Rename old quota tests for missing-Exa behavior**

In `tests/test_stage2_fallbacks.py`, rename:

```python
async def test_tavily_quota_fast_switches_remaining_tasks_to_manual_required(tmp_path):
```

to:

```python
async def test_tavily_quota_without_exa_keeps_manual_required_fast_switch(tmp_path):
```

Rename:

```python
async def test_tavily_extract_quota_fast_switches_remaining_tasks(tmp_path):
```

to:

```python
async def test_tavily_extract_quota_without_exa_keeps_manual_required_fast_switch(tmp_path):
```

Keep their existing `exa_client=None` setup and manual-required assertions.

- [ ] **Step 2: Write extract quota failover test**

Add this test:

```python
@pytest.mark.anyio("asyncio")
async def test_tavily_extract_quota_switches_current_and_remaining_tasks_to_exa(tmp_path):
    client = ExtractQuotaTavilyClient()
    exa = RecordingExaClient()
    stats = {}
    tasks = [
        {
            "task_id": "extract-quota-gold",
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
            "task_id": "extract-quota-oil",
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
    assert all(item["search_backend"] == "exa" for item in websearch_results)
```

- [ ] **Step 3: Write 422 non-global test**

Change existing `test_extract_422_uses_exa_fallback_for_non_fund_flow` to require explicit non-quota fallback:

```python
completed, failures, websearch_results = await _execute_tasks(
    [task],
    payload,
    FakeClientCommodity422(),
    FakeExaClient(),
    FakeExtractorCommodity(),
    task_log_path=tmp_path / "task_log.jsonl",
    cache_ttl=None,
    deepseek_timeout=8,
    extraction_backend="deepseek",
    deepseek_max_concurrency=1,
    stats=stats,
    use_queue=False,
    queue_concurrency=1,
    queue_maxsize=10,
    queue_retry_limit=0,
    disable_extract=False,
    auto_disable_extract_on_422=True,
    extract_422_threshold=1,
    extract_topk=1,
    llm_hard_timeout=10,
    allow_exa_non_quota_fallback=True,
)
```

Add this test to prove default 422 does not activate global failover:

```python
@pytest.mark.anyio("asyncio")
async def test_tavily_extract_422_does_not_activate_global_exa_failover_by_default(tmp_path):
    stats = {}
    payload = {"commodities": [{"symbol": "GC=F", "current_price": None, "source": ""}]}
    task = {
        "task_id": "test-gold-422-no-global",
        "indicator_key": "GC=F",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "preferred_domains": ["cmegroup.com", "investing.com"],
        "query": "COMEX 黄金期货 最新价格",
        "unit": "$/oz",
        "extract_policy": {"use_tavily_extract": True, "extract_topk": 1},
        "created_at": 0,
    }
    exa = FakeExaClient()

    await _execute_tasks(
        [task],
        payload,
        FakeClientCommodity422(),
        exa,
        FakeExtractorCommodity(),
        task_log_path=tmp_path / "task_log.jsonl",
        cache_ttl=None,
        deepseek_timeout=8,
        extraction_backend="deepseek",
        deepseek_max_concurrency=1,
        stats=stats,
        use_queue=False,
        queue_concurrency=1,
        queue_maxsize=10,
        queue_retry_limit=0,
        disable_extract=False,
        auto_disable_extract_on_422=True,
        extract_422_threshold=1,
        extract_topk=1,
        llm_hard_timeout=10,
        allow_exa_non_quota_fallback=False,
    )

    assert stats["tavily_to_exa_failover"] is False
    assert stats["search_backend_final"] == "tavily"
    assert exa.calls == 0
```

- [ ] **Step 4: Implement extract quota routing and 422 guard**

In Tavily extract exception handling:

```python
if _is_environment_proxy_error(exc):
    # Keep existing environment_proxy_error manual fast-switch.
elif _is_tavily_quota_error(exc):
    _mark_tavily_quota_unavailable(str(exc))
    if _activate_exa_failover(task, "quota_or_rate_limit"):
        search_response, exa_diag = await _run_exa_search_for_task(task, "quota_or_rate_limit")
        if search_response:
            search_backend = "exa"
            task_for_log = {
                **task,
                "search_backend": "exa",
                "search_backend_state": "exa_active",
                "failover_reason": failover_reason,
            }
            raw_results = search_response.get("results") or []
            snippets = raw_results
            # Continue into existing DeepSeek/regex extraction with snippets.
        else:
            manual_reason = exa_diag.get("manual_reason", "exa_error")
            task_record, websearch_item = _build_search_manual_required_records(
                task_for_log,
                attempt_index=attempt,
                elapsed_ms=elapsed_ms,
                manual_reason=manual_reason,
                note=f"{manual_reason}:exa_failover",
                search_backend="exa",
                error=exc,
                extra_diagnostics=exa_diag,
            )
    else:
        # Keep existing quota manual-required fast-switch.
elif extract_resp.get("status") == 422 or "422" in str(extract_resp.get("error", "")):
    # Keep the existing 422 cooldown; only call old Exa fallback when allow_exa_non_quota_fallback is true.
```

Update `_try_exa_fallback` so non-quota calls return immediately when `allow_exa_non_quota_fallback` is false:

```python
if reason != "quota_or_rate_limit" and not allow_exa_non_quota_fallback:
    return None, "exa_fallback_not_enabled"
```

- [ ] **Step 5: Add Exa-not-called assertions to proxy tests**

In `test_environment_proxy_error_fast_switches_remaining_tasks_to_manual_required`, pass `RecordingExaClient()` as `exa_client` and assert:

```python
assert len(exa.calls) == 0
```

Repeat the same for `test_tavily_extract_environment_proxy_fast_switches_remaining_tasks`.

- [ ] **Step 6: Verify fallback suite**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_fallbacks.py -k "quota or proxy or 422"
```

Expected: selected tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_fallbacks.py
git commit -m "feat: fail over stage2 search to exa on tavily quota"
```

Expected: commit succeeds.

## Task 5: Include Fund Flow In Exa Failover With Existing Gates

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Test: `tests/test_stage2_fallbacks.py`

- [ ] **Step 1: Add fund-flow Exa fake and extractor**

Add to `tests/test_stage2_fallbacks.py`:

```python
class FundFlowExaClient:
    def __init__(self, content):
        self.calls = []
        self.content = content

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "results": [{
                "url": "https://data.eastmoney.com/hsgt/",
                "title": "沪深港通资金流向",
                "snippet": self.content,
                "content": self.content,
                "score": 0.95,
                "published_date": "2026-05-22",
            }],
            "query": kwargs.get("query"),
        }


class FundFlowExtractor:
    async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
        return {
            "recent_5d": 5.0,
            "total_120d": 120.0,
            "trend": "流入",
            "source_url": snippets[0].get("url") if snippets else None,
            "confidence": 0.8,
            "manual_required": False,
            "manual_reason": None,
        }
```

- [ ] **Step 2: Write weak-evidence fund-flow test**

Add:

```python
@pytest.mark.anyio("asyncio")
async def test_exa_failover_runs_fund_flow_and_blocks_weak_window_evidence(tmp_path):
    stats = {}
    exa = FundFlowExaClient("新闻称近期北向资金呈净流入态势。")
    tasks = [{
        "task_id": "fund-flow-northbound",
        "indicator_key": "northbound",
        "stage_phase": "fund_flow",
        "category": "fund_flow",
        "search_backend": "tavily",
        "query": "北向资金 近5日 120日",
        "created_at": 1700000000,
        "preferred_domains": ["data.eastmoney.com"],
    }]
    payload = {"fund_flow": {"northbound": {"type": "northbound", "recent_5d": None, "total_120d": None}}}

    completed, failures, websearch_results = await _execute_tasks(
        tasks,
        payload,
        QuotaTavilyClient(),
        exa,
        FundFlowExtractor(),
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

    assert len(exa.calls) == 1
    assert completed == []
    assert len(failures) == 1
    assert failures[0]["manual_reason"] in {"estimated_not_allowed", "fund_flow_window_missing"}
    assert websearch_results[0]["search_backend"] == "exa"
```

- [ ] **Step 3: Write direct-window fund-flow success test**

Add:

```python
@pytest.mark.anyio("asyncio")
async def test_exa_failover_fund_flow_direct_window_can_complete(tmp_path):
    stats = {}
    content = "北向资金近5日净流入5.0亿元，近120日累计净流入120.0亿元。"
    exa = FundFlowExaClient(content)
    tasks = [{
        "task_id": "fund-flow-northbound-direct",
        "indicator_key": "northbound",
        "stage_phase": "fund_flow",
        "category": "fund_flow",
        "search_backend": "tavily",
        "query": "北向资金 近5日 120日",
        "created_at": 1700000000,
        "preferred_domains": ["data.eastmoney.com"],
    }]
    payload = {"fund_flow": {"northbound": {"type": "northbound", "recent_5d": None, "total_120d": None}}}

    completed, failures, websearch_results = await _execute_tasks(
        tasks,
        payload,
        QuotaTavilyClient(),
        exa,
        FundFlowExtractor(),
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

    assert failures == []
    assert len(completed) == 1
    assert len(exa.calls) == 1
    assert websearch_results[0]["search_backend"] == "exa"
    assert payload["fund_flow"]["northbound"]["window_evidence"] == "direct_window"
```

- [ ] **Step 4: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_fallbacks.py -k "exa_failover_runs_fund_flow or exa_failover_fund_flow_direct_window"
```

Expected: fail if Exa fallback skips fund-flow indicators or if Exa snippets do not flow through existing metadata gates.

- [ ] **Step 5: Remove fund-flow exclusion from quota failover**

In the Exa search helper, do not skip `northbound`, `southbound`, `etf`, or `margin` when `reason == "quota_or_rate_limit"`.

If the old `_try_exa_fallback` still has a fund-flow skip, keep that skip only for non-quota fallback:

```python
if reason != "quota_or_rate_limit" and task.get("indicator_key") in {"northbound", "southbound", "etf", "margin"}:
    return None, "fund_flow_exa_fallback_disabled"
```

- [ ] **Step 6: Route fund-flow field retry through active backend**

In `_retry_fund_flow_fields`, add an `active_backend` argument:

```python
async def _retry_fund_flow_fields(
    task: Dict[str, Any],
    extraction: Dict[str, Any],
    active_backend: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
```

When `active_backend == "exa"`, call `_run_exa_search_for_task(task, failover_reason or "quota_or_rate_limit", query_override=query)` for each field query instead of Tavily `_run_search_candidates(...)`.

At both call sites, pass:

```python
extraction, field_attempts = await _retry_fund_flow_fields(task_for_log, extraction, active_search_backend)
```

- [ ] **Step 7: Verify fund-flow gates**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_fallbacks.py -k "fund_flow or quota"
.venv/bin/python -m pytest -q tests/test_pipeline_quality_state.py::test_pipeline_quality_state_blocks_estimated_fund_flow_with_diagnostics_when_allow_estimated
```

Expected: selected tests pass; weak fund-flow evidence remains blocked.

- [ ] **Step 8: Commit**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_fallbacks.py
git commit -m "fix: preserve fund flow gates during exa failover"
```

Expected: commit succeeds.

## Task 6: Expose Exa Failover Diagnostics In Summary

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Test: `tests/test_stage2_fallbacks.py`
- Test: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write missing-Exa diagnostic test**

Add to `tests/test_stage2_fallbacks.py`:

```python
@pytest.mark.anyio("asyncio")
async def test_tavily_quota_without_exa_records_exa_unavailable(tmp_path):
    client = QuotaTavilyClient()
    stats = {}
    tasks = [{
        "task_id": "quota-gold-no-exa",
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
    assert stats["exa_unavailable"] == 1
    assert failures[0]["manual_reason"] in {"quota_or_rate_limit", "exa_unavailable"}
```

- [ ] **Step 2: Write Exa error diagnostic test**

Add:

```python
class ErroringExaClient:
    async def search(self, **kwargs):
        exc = RuntimeError("429 rate limit exceeded")
        exc.response = type(
            "Response",
            (),
            {"status_code": 429, "headers": {"x-request-id": "req-err"}},
        )()
        raise exc


@pytest.mark.anyio("asyncio")
async def test_exa_failover_error_records_structured_diagnostics(tmp_path):
    stats = {}
    tasks = [{
        "task_id": "quota-gold-exa-error",
        "indicator_key": "GC=F",
        "stage_phase": "assets",
        "category": "commodities",
        "search_backend": "tavily",
        "query": "COMEX gold latest price",
        "unit": "$/oz",
        "created_at": 1700000000,
        "preferred_domains": [],
    }]

    await _execute_tasks(
        tasks,
        {"commodities": []},
        QuotaTavilyClient(),
        ErroringExaClient(),
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

    assert stats["exa_failover_error"] == 1
    assert stats["exa_error_breakdown"]["rate_limited"] == 1
    assert stats["exa_error_samples"][0]["exa_request_id"] == "req-err"
```

- [ ] **Step 3: Write summary diagnostic test**

Add to `tests/test_stage2_unified.py`:

```python
def test_stage2_summary_includes_exa_failover_diagnostics():
    summary = stage2._build_stage2_summary_diagnostics(
        completed_tasks=[],
        failures=[],
        websearch_results=[],
        exec_stats={
            "search_backend_final": "exa",
            "tavily_to_exa_failover": True,
            "tavily_to_exa_failover_count": 1,
            "exa_failover_success": 3,
            "exa_failover_empty": 1,
            "exa_failover_error": 2,
            "exa_unavailable": 0,
            "exa_error_breakdown": {"rate_limited": 2},
            "exa_error_samples": [{"exa_error_tag": "rate_limited"}],
        },
    )

    assert summary["search_backend_final"] == "exa"
    assert summary["tavily_to_exa_failover"] is True
    assert summary["tavily_to_exa_failover_count"] == 1
    assert summary["exa_failover_success"] == 3
    assert summary["exa_failover_empty"] == 1
    assert summary["exa_failover_error"] == 2
    assert summary["exa_error_breakdown"] == {"rate_limited": 2}
```

- [ ] **Step 4: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_fallbacks.py -k "exa_unavailable or structured_diagnostics"
.venv/bin/python -m pytest -q tests/test_stage2_unified.py -k "summary_includes_exa"
```

Expected: fail until summary fields and structured Exa error counters are wired.

- [ ] **Step 5: Add summary fields**

In `_build_stage2_summary_diagnostics`, after the existing DeepSeek fields, copy these keys from `exec_stats` into `payload`:

```python
for key in (
    "search_backend_final",
    "tavily_to_exa_failover",
    "tavily_to_exa_failover_count",
    "exa_failover_success",
    "exa_failover_empty",
    "exa_failover_error",
    "exa_unavailable",
    "exa_error_breakdown",
    "exa_error_samples",
):
    if key in exec_stats:
        payload[key] = exec_stats[key]
```

In the main summary assembly near the existing `tavily_unavailable_reason` copy, copy the same keys from `summary_diagnostics` into `summary`.

- [ ] **Step 6: Verify diagnostics tests pass**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_fallbacks.py -k "exa_unavailable or structured_diagnostics"
.venv/bin/python -m pytest -q tests/test_stage2_unified.py -k "summary_includes_exa"
```

Expected: selected tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_fallbacks.py tests/test_stage2_unified.py
git commit -m "feat: report exa failover diagnostics"
```

Expected: commit succeeds.

## Task 7: Initialize Exa For Quota Failover Without Enabling Non-Quota Fallback

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Test: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write Exa initialization tests**

Add to `tests/test_stage2_unified.py`:

```python
def test_stage2_exa_client_initializes_for_quota_failover_when_key_present(monkeypatch):
    monkeypatch.setattr("sys.argv", ["stage2_unified_enhancer.py", "--market-data", "market.json"])
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key")
    monkeypatch.delenv("STAGE2_ENABLE_EXA_FALLBACK", raising=False)

    args = stage2._parse_args()

    assert stage2._should_initialize_exa_client(args) is True
    assert stage2._should_enable_exa_fallback(args) is False
```

```python
def test_stage2_exa_client_not_initialized_without_key_or_explicit_fallback(monkeypatch):
    monkeypatch.setattr("sys.argv", ["stage2_unified_enhancer.py", "--market-data", "market.json"])
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("STAGE2_ENABLE_EXA_FALLBACK", raising=False)

    args = stage2._parse_args()

    assert stage2._should_initialize_exa_client(args) is False
    assert stage2._should_enable_exa_fallback(args) is False
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_unified.py -k "exa_client_initializes or exa_fallback_is_opt_in or exa_fallback_can_be_enabled"
```

Expected: fail because `_should_initialize_exa_client` does not exist.

- [ ] **Step 3: Add initialization helper**

Keep `_should_enable_exa_fallback(args)` as the opt-in switch for non-quota fallback. Add:

```python
def _should_initialize_exa_client(args: argparse.Namespace) -> bool:
    return bool(os.getenv("EXA_API_KEY")) or _should_enable_exa_fallback(args)
```

In `main`, replace the existing Exa initialization condition with:

```python
exa_api_key = os.getenv("EXA_API_KEY")
if _should_initialize_exa_client(args) and exa_api_key:
    exa_client = AsyncExaClient(api_key=exa_api_key)
elif _should_enable_exa_fallback(args) and not exa_api_key:
    logger.warning("Exa fallback requested but EXA_API_KEY is not set")
    exa_client = None
else:
    exa_client = None
```

Pass the explicit non-quota flag into `_execute_tasks`:

```python
allow_exa_non_quota_fallback=_should_enable_exa_fallback(args),
```

Apply this at both `_execute_tasks` call sites.

- [ ] **Step 4: Verify initialization tests pass**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_stage2_unified.py -k "exa_client_initializes or exa_fallback_is_opt_in or exa_fallback_can_be_enabled"
.venv/bin/python -m pytest -q tests/test_stage2_fallbacks.py -k "422 or quota"
```

Expected: selected tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "feat: initialize exa for tavily quota failover"
```

Expected: commit succeeds.

## Task 8: Update Operator Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `AGENTS.md` Stage2 and troubleshooting text**

In `AGENTS.md`, update the Exa-related bullets in sections 3.2, 6, 11, and 12 to state:

```markdown
- Optional: `EXA_API_KEY`。当 Tavily 触发 402/403/429/quota/rate-limit/payment 类不可用时，Stage2 会在本轮切换 `search_backend_state=tavily_active -> exa_active`，当前失败任务和剩余任务统一走 Exa；正常 Tavily-first 路径不受影响。
- `--enable-exa-fallback` / `STAGE2_ENABLE_EXA_FALLBACK=1` 仍仅用于非 quota 场景的实验性 Exa fallback；Tavily quota failover 只要求 `EXA_API_KEY` 和 `exa-py` 可用。
- 环境代理、SOCKS、DNS、TLS 类错误不切换 Exa，继续走 manual_required fast-fail。
- Tavily extract 422 不触发全局 Exa failover；若 422 同时包含 quota/rate/payment 语义，以 quota failover 为准。
- Exa failover 覆盖 `fund_flow`，但 `source_tier/window_evidence/metric_basis/is_estimated/estimated_not_allowed` gate 不放宽。
- Stage2 summary 排查字段：`search_backend_final`、`tavily_to_exa_failover`、`tavily_to_exa_failover_count`、`exa_failover_success`、`exa_failover_empty`、`exa_failover_error`、`exa_unavailable`、`exa_error_breakdown`、`exa_error_samples`。
```

- [ ] **Step 2: Update `CLAUDE.md` quick reminders**

Add a short Stage2 note in `CLAUDE.md`:

```markdown
- Stage2 remains Tavily-first. With `EXA_API_KEY`, Tavily 402/403/429/quota/rate-limit/payment switches the current run to Exa for the failed and remaining tasks, including `fund_flow`; proxy/DNS/TLS errors and plain Tavily extract 422 do not trigger global Exa failover.
```

- [ ] **Step 3: Verify documentation references**

Run:

```bash
rg -n "Exa|Tavily|quota|rate-limit|422|fund_flow|search_backend_final" AGENTS.md CLAUDE.md
```

Expected: output shows the new operating contract in both docs.

- [ ] **Step 4: Commit**

Run:

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: document exa quota failover"
```

Expected: commit succeeds.

## Task 9: Final Verification

**Files:**
- Verify: all changed files

- [ ] **Step 1: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_exa_client.py \
  tests/test_stage2_fallbacks.py \
  tests/test_stage2_unified.py \
  tests/test_pipeline_quality_state.py \
  tests/test_websearch_injector.py
```

Expected: all selected tests pass.

- [ ] **Step 2: Run syntax checks**

Run:

```bash
.venv/bin/python -m py_compile \
  src/datasource/adapters/exa_client.py \
  scripts/stage2_unified_enhancer.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Check diff hygiene**

Run:

```bash
git diff --check
git status --short
git log --oneline --decorate -5
```

Expected:

```text
git diff --check
# no output
```

`git status --short` should show no unstaged implementation changes after final commits. The plan file may remain uncommitted unless the executor chooses to commit planning docs separately.

- [ ] **Step 4: Manual review checklist**

Confirm these facts from tests and diff:

```text
Tavily quota/rate/payment errors activate Exa once.
The failed current task is retried through Exa.
Remaining tasks use Exa and do not call Tavily.
fund_flow uses Exa after failover while existing gates still block weak evidence.
Proxy, SOCKS, DNS, and TLS errors do not call Exa.
Plain Tavily extract 422 does not set search_backend_state=exa_active.
Exa-backed writeback uses exa+deepseek or exa_regex.
Exa text is bounded before DeepSeek extraction.
Stage2 summary includes Exa success, empty, unavailable, and error diagnostics.
No real API key appears in tracked files.
```
