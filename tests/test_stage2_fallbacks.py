import asyncio
import json
from pathlib import Path
import pytest

from scripts.stage2_unified_enhancer import _execute_tasks


class FakeClient422:
    def __init__(self):
        self.extract_calls = 0

    async def search(self, **kwargs):
        # 返回一条高分 snippet，触发 extract 分支
        return {
            "results": [
                {
                    "url": "https://example.com/etf_flow",
                    "snippet": "ETF 资金净流入 10 亿元",
                    "score": 0.9,
                }
            ]
        }

    async def extract(self, **kwargs):
        self.extract_calls += 1
        return {"status": 422}


class FakeExtractorTimeout:
    def __init__(self):
        self.calls = 0

    async def extract(self, *args, **kwargs):  # pragma: no cover - 异常路径
        self.calls += 1
        raise asyncio.TimeoutError("deepseek timeout")

    def _fallback_extract(self, snips):
        # 提供一个数值兜底
        return 1.23, snips[0].get("url") if snips else None


@pytest.mark.anyio("asyncio")
async def test_extract_422_triggers_indicator_cooldown(tmp_path):
    client = FakeClient422()
    extractor = FakeExtractorTimeout()
    stats = {}
    market_payload = {"fund_flow": {"etf": {"type": "etf"}, "northbound": {"type": "northbound"}}}
    tasks = [
        {
            "task_id": "test-etf-422",
            "indicator_key": "etf",
            "stage_phase": "assets",
            "search_backend": "tavily",
            "fund_flow_backend": "tavily",
            "extraction_backend": "deepseek",
            "query": "A股 ETF 资金流 申购赎回 近5日 120日",
            "created_at": 1700000000,
            "preferred_domains": [],
        },
        {
            "task_id": "test-etf-422-repeat",
            "indicator_key": "etf",
            "stage_phase": "assets",
            "search_backend": "tavily",
            "fund_flow_backend": "tavily",
            "extraction_backend": "deepseek",
            "query": "A股 ETF 资金流 申购赎回 近5日 120日",
            "created_at": 1700000001,
            "preferred_domains": [],
        },
        {
            "task_id": "test-northbound-422",
            "indicator_key": "northbound",
            "stage_phase": "assets",
            "search_backend": "tavily",
            "fund_flow_backend": "tavily",
            "extraction_backend": "deepseek",
            "query": "北向资金 近5日 120日",
            "created_at": 1700000002,
            "preferred_domains": [],
        },
    ]

    completed, failures, websearch_results = await _execute_tasks(
        tasks,
        market_payload,
        client,
        None,
        extractor,
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
        auto_disable_extract_on_422=True,
        extract_422_threshold=1,
        extract_topk=1,
        llm_hard_timeout=10,
    )

    assert len(completed) + len(failures) == 3
    assert stats.get("tavily_extract_422_count", 0) >= 1
    assert stats.get("extract_globally_disabled") is False
    assert stats.get("extract_cooldown_count", 0) >= 1
    # 第二个 ETF 任务应走按指标冷却路径；northbound 仍会单独触发 extract
    assert client.extract_calls == 2
    assert websearch_results
    assert any(
        result.get("task", {}).get("extract_skipped_reason") == "extract_cooldown"
        for result in websearch_results
    )


@pytest.mark.anyio("asyncio")
async def test_deepseek_timeout_records_error(tmp_path):
    client = FakeClient422()
    # 让 extract 完全跳过，直接走 DeepSeek（无 422）
    async def search_only(**kwargs):
        return {
            "results": [
                {
                    "url": "https://example.com/etf_flow",
                    "snippet": "ETF 资金净流入 10 亿元",
                    "score": 0.9,
                }
            ]
        }

    client.search = search_only  # type: ignore
    client.extract = None  # type: ignore

    extractor = FakeExtractorTimeout()
    stats = {}
    market_payload = {"fund_flow": {"etf": {"type": "etf"}}}
    task = {
        "task_id": "test-etf-timeout",
        "indicator_key": "etf",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "extraction_backend": "deepseek",
        "query": "A股 ETF 资金流 申购赎回 近5日 120日",
        "created_at": 1700000000,
        "preferred_domains": [],
    }

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        market_payload,
        client,
        None,
        extractor,
        task_log_path=tmp_path / "task_log.jsonl",
        cache_ttl=None,
        fund_flow_backend="tavily",
        forex_backend="tavily",
        deepseek_timeout=0.1,
        extraction_backend="deepseek",
        deepseek_max_concurrency=1,
        deepseek_serial_keys=None,
        stats=stats,
        use_queue=False,
        queue_concurrency=1,
        queue_maxsize=10,
        queue_retry_limit=0,
        disable_extract=True,
        extract_topk=1,
        llm_hard_timeout=0.2,
    )

    assert not completed
    assert len(failures) == 1
    record = failures[0]
    # Timeout 会被包装为 deepseek_error:... 并计入 llm_error
    assert "deepseek_error" in (record.get("note") or "") or "Timeout" in (record.get("llm_error") or "")
    assert stats.get("timeout_count", 0) >= 1
    assert stats.get("deepseek_timeouts", 0) >= 1
    # fallback_extract 提供的值应被写回 extraction
    extraction_note = websearch_results[0]["extraction"].get("note", "")
    assert "regex_fallback" in extraction_note or "deepseek_error" in extraction_note


@pytest.mark.anyio("asyncio")
async def test_deepseek_circuit_breaker_skips_subsequent_extractions(tmp_path):
    class SearchOnlyClient:
        async def search(self, **kwargs):
            indicator = kwargs.get("query") or "macro"
            return {
                "results": [
                    {
                        "url": f"https://example.com/{indicator}",
                        "snippet": f"{indicator} 最新同比 1.2 %",
                        "content": f"{indicator} 最新同比 1.2 %",
                        "score": 0.95,
                    }
                ]
            }

    class TimeoutExtractor:
        def __init__(self):
            self.calls = 0

        async def extract(self, *args, **kwargs):
            self.calls += 1
            raise asyncio.TimeoutError("deepseek timeout")

        def _fallback_extract(self, snips):
            return None, snips[0].get("url") if snips else None

    indicators = ["cpi", "ppi", "pmi", "m1", "m2"]
    tasks = [
        {
            "task_id": f"macro-{indicator}",
            "indicator_key": indicator,
            "stage_phase": "macro",
            "search_backend": "tavily",
            "extraction_backend": "deepseek",
            "query": indicator,
            "created_at": 1700000000 + idx,
            "preferred_domains": [],
            "unit": "%",
        }
        for idx, indicator in enumerate(indicators)
    ]
    market_payload = {
        "macro_indicators": {
            indicator: {"current_value": None, "previous_value": 1.0}
            for indicator in indicators
        }
    }
    extractor = TimeoutExtractor()
    stats = {}

    completed, failures, websearch_results = await _execute_tasks(
        tasks,
        market_payload,
        SearchOnlyClient(),
        None,
        extractor,
        task_log_path=tmp_path / "task_log.jsonl",
        cache_ttl=None,
        deepseek_timeout=0.1,
        extraction_backend="deepseek",
        deepseek_max_concurrency=1,
        stats=stats,
        disable_extract=True,
        extract_topk=1,
        llm_hard_timeout=0.2,
        deepseek_breaker_consecutive_timeouts=3,
        deepseek_breaker_timeout_rate=0.5,
        deepseek_breaker_min_attempts=4,
    )

    assert len(completed) + len(failures) == len(tasks)
    assert stats["deepseek_circuit_breaker_triggered"] is True
    assert stats["deepseek_circuit_breaker_reason"] == "consecutive_timeouts"
    assert extractor.calls < len(tasks)
    skipped_items = [
        item
        for item in websearch_results
        if "deepseek_circuit_breaker" in str(item.get("manual_reason") or "")
        or "deepseek_circuit_breaker" in str(item.get("extraction", {}).get("manual_reason") or "")
    ]
    assert skipped_items
    assert all(
        "deepseek_circuit_breaker" in str(item.get("task", {}).get("extraction_skipped_reason") or "")
        for item in skipped_items
    )


@pytest.mark.anyio("asyncio")
async def test_deepseek_timeout_then_success_updates_partial_breaker_stats(tmp_path):
    class SearchOnlyClient:
        async def search(self, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://example.com/cpi",
                        "snippet": "CPI 最新同比 2.3",
                        "content": "CPI 最新同比 2.3",
                        "score": 0.95,
                    }
                ]
            }

    class TimeoutThenSuccessExtractor:
        def __init__(self):
            self.calls = 0

        async def extract(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise asyncio.TimeoutError("deepseek timeout")
            return {
                "value": 2.3,
                "unit": None,
                "source_url": "https://example.com/cpi",
                "confidence": 0.9,
                "manual_required": False,
                "manual_reason": None,
                "note": "deepseek_structured",
            }

    task = {
        "task_id": "macro-cpi",
        "indicator_key": "cpi",
        "stage_phase": "macro",
        "search_backend": "tavily",
        "extraction_backend": "deepseek",
        "query": "cpi",
        "created_at": 1700000000,
        "preferred_domains": [],
    }
    market_payload = {
        "macro_indicators": {
            "cpi": {"current_value": None, "previous_value": 2.0}
        }
    }
    stats = {}

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        market_payload,
        SearchOnlyClient(),
        None,
        TimeoutThenSuccessExtractor(),
        task_log_path=tmp_path / "task_log.jsonl",
        cache_ttl=None,
        deepseek_timeout=0.1,
        extraction_backend="deepseek",
        deepseek_max_concurrency=1,
        stats=stats,
        disable_extract=True,
        extract_topk=1,
        llm_hard_timeout=0.2,
    )

    assert completed
    assert not failures
    assert stats["deepseek_circuit_breaker_triggered"] is False
    assert stats["deepseek_timeout_rate"] > 0
    assert stats["deepseek_breaker_attempts"] == 2
    assert stats["deepseek_breaker_timeouts"] == 1
    assert all(
        "deepseek_circuit_breaker" not in str(item.get("manual_reason") or "")
        for item in websearch_results
    )


@pytest.fixture
def anyio_backend():
    # 强制使用 asyncio，避免缺少 trio 依赖导致的参数化失败
    return "asyncio"


class FakeClientCommodity422:
    def __init__(self):
        self.extract_calls = 0

    async def search(self, **kwargs):
        return {
            "results": [
                {
                    "url": "https://www.cmegroup.com/gold",
                    "snippet": "COMEX gold futures contract details",
                    "content": "COMEX gold futures contract details",
                    "score": 0.92,
                }
            ]
        }

    async def extract(self, **kwargs):
        self.extract_calls += 1
        return {"status": 422}


class FakeExaClient:
    def __init__(self):
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        return {
            "results": [
                {
                    "url": "https://www.investing.com/commodities/gold",
                    "snippet": "Gold futures quote 3025.6 $/oz",
                    "content": "Gold futures quote 3025.6 $/oz",
                    "score": 0.9,
                }
            ]
        }


class FakeExtractorCommodity:
    async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
        text = " ".join(str(s.get("content") or s.get("snippet") or "") for s in snippets)
        if "3025.6" not in text:
            return {
                "value": None,
                "unit": unit_hint,
                "source_url": snippets[0].get("url") if snippets else None,
                "confidence": 0.0,
                "manual_required": True,
                "manual_reason": "no_value",
            }
        return {
            "value": 3025.6,
            "unit": "$/oz",
            "source_url": "https://www.investing.com/commodities/gold",
            "confidence": 0.9,
            "manual_required": False,
            "manual_reason": None,
        }


@pytest.mark.anyio("asyncio")
async def test_extract_422_uses_exa_fallback_for_non_fund_flow(tmp_path):
    stats = {}
    payload = {"commodities": [{"symbol": "GC=F", "current_price": None, "source": ""}]}
    task = {
        "task_id": "test-gold-422",
        "indicator_key": "GC=F",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "preferred_domains": ["cmegroup.com", "investing.com"],
        "query": "COMEX 黄金期货 最新价格",
        "unit": "$/oz",
        "issuer": "COMEX/CME",
        "issuer_aliases": ["CME", "COMEX"],
        "extract_policy": {"use_tavily_extract": True, "extract_topk": 1},
        "required_keywords": ["gold", "黄金", "comex"],
        "strict_required_keywords": True,
        "retry_count": 0,
        "created_at": 0,
    }

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
    )

    assert completed
    assert not failures
    assert stats.get("tavily_extract_422_count", 0) >= 1
    assert stats.get("exa_fallback_after_extract_422", 0) >= 1
    assert websearch_results[0]["search_backend"] == "exa"
    assert websearch_results[0]["result_type"] == "search_success"


class QuotaTavilyClient:
    def __init__(self):
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        exc = RuntimeError("429 quota exceeded")
        exc.response = type("Response", (), {"status_code": 429})()
        raise exc

    async def extract(self, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("extract should not run after Tavily quota failure")


class RecordingExaClient:
    def __init__(self, value="123.45"):
        self.calls = []
        self.value = value

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        query = kwargs.get("query") or "quote"
        return {
            "results": [
                {
                    "url": "https://example.com/quote",
                    "title": "quote",
                    "snippet": f"{query} 收盘 {self.value}",
                    "content": f"{query} 收盘 {self.value}",
                    "score": 0.91,
                    "published_date": "2026-05-22",
                }
            ],
            "query": query,
        }


class UnrelatedExaClient:
    def __init__(self):
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "results": [
                {
                    "url": "https://example.com/weather",
                    "title": "weather",
                    "snippet": "New York weather forecast 1234.5 sunshine index",
                    "content": "New York weather forecast 1234.5 sunshine index",
                    "score": 0.98,
                    "published_date": "2026-05-22",
                }
            ],
            "query": kwargs.get("query") or "weather",
        }


class ErrorExaClient:
    def __init__(self):
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        exc = RuntimeError("429 rate limited")
        exc.response = type(
            "Response",
            (),
            {
                "status_code": 429,
                "headers": {"x-request-id": "exa-request-123"},
            },
        )()
        raise exc


class EmptyExaClient:
    def __init__(self):
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return {"results": [], "query": kwargs.get("query") or "empty"}


class ValueExtractor:
    def __init__(self):
        self.calls = 0

    async def extract(
        self,
        snippets,
        indicator,
        unit_hint=None,
        issuer_hint=None,
        request_timeout=None,
    ):
        self.calls += 1
        value = 1234.5 if indicator == "GC=F" else 123.45
        return {
            "value": value,
            "unit": unit_hint,
            "source_url": snippets[0].get("url") if snippets else None,
            "confidence": 0.9,
            "manual_required": False,
            "manual_reason": None,
        }


class ProxyErrorTavilyClient:
    def __init__(self):
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        raise RuntimeError("Using SOCKS proxy, but the 'socksio' package is not installed")

    async def extract(self, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("extract should not run after proxy environment failure")


class ExtractProxyErrorTavilyClient:
    def __init__(self):
        self.search_calls = 0
        self.extract_calls = 0

    async def search(self, **kwargs):
        self.search_calls += 1
        return {
            "results": [
                {
                    "url": "https://www.cmegroup.com/markets/metals/precious/gold.html",
                    "snippet": "COMEX gold latest futures quote 3300.0 $/oz",
                    "content": "COMEX gold latest futures quote 3300.0 $/oz",
                    "score": 0.92,
                }
            ]
        }

    async def extract(self, **kwargs):
        self.extract_calls += 1
        raise RuntimeError("Cannot connect to proxy http://127.0.0.1:7890")


class NoopExtractor:
    async def extract(self, *args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("DeepSeek should not run after Tavily quota failure")


class ExtractQuotaTavilyClient:
    def __init__(self):
        self.search_calls = 0
        self.extract_calls = 0

    async def search(self, **kwargs):
        self.search_calls += 1
        return {
            "results": [
                {
                    "url": "https://www.cmegroup.com/markets/metals/precious/gold.html",
                    "snippet": "COMEX gold latest futures quote 3300.0 $/oz",
                    "content": "COMEX gold latest futures quote 3300.0 $/oz",
                    "score": 0.92,
                }
            ]
        }

    async def extract(self, **kwargs):
        self.extract_calls += 1
        exc = RuntimeError("429 rate limit exceeded")
        exc.response = type("Response", (), {"status_code": 429})()
        raise exc


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


@pytest.mark.anyio("asyncio")
async def test_tavily_quota_exa_failover_applies_strict_required_quality_gate(tmp_path):
    client = QuotaTavilyClient()
    exa = UnrelatedExaClient()
    extractor = ValueExtractor()
    stats = {}
    task = {
        "task_id": "quota-gold-unrelated-exa",
        "indicator_key": "GC=F",
        "stage_phase": "assets",
        "category": "commodities",
        "search_backend": "tavily",
        "query": "COMEX gold latest price",
        "unit": "$/oz",
        "created_at": 1700000000,
        "preferred_domains": [],
        "required_keywords": ["gold", "comex"],
        "strict_required_keywords": True,
    }

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        {"commodities": []},
        client,
        exa,
        extractor,
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
    assert len(exa.calls) >= 1
    assert completed == []
    assert len(failures) == 1
    assert failures[0]["manual_required"] is True
    assert "strict_keyword_miss" in (failures[0].get("manual_reason") or "")
    assert websearch_results[0]["search_backend"] == "exa"
    assert websearch_results[0]["manual_required"] is True
    assert "strict_keyword_miss" in (websearch_results[0].get("manual_reason") or "")
    assert extractor.calls == 0


@pytest.mark.anyio("asyncio")
async def test_tavily_quota_exa_error_metadata_is_audited(tmp_path):
    client = QuotaTavilyClient()
    exa = ErrorExaClient()
    stats = {}
    task = {
        "task_id": "quota-gold-exa-error",
        "indicator_key": "GC=F",
        "stage_phase": "assets",
        "category": "commodities",
        "search_backend": "tavily",
        "query": "COMEX gold latest price",
        "unit": "$/oz",
        "created_at": 1700000000,
        "preferred_domains": [],
    }

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        {"commodities": []},
        client,
        exa,
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

    assert client.calls == 1
    assert len(exa.calls) == 1
    assert completed == []
    assert len(failures) == 1
    assert failures[0]["search_backend"] == "exa"
    assert failures[0]["manual_reason"] == "exa_error"
    assert failures[0]["exa_error_tag"] == "rate_limited"
    assert failures[0]["exa_request_id"] == "exa-request-123"
    assert websearch_results[0]["manual_reason"] == "exa_error"
    assert websearch_results[0]["exa_error_tag"] == "rate_limited"
    assert websearch_results[0]["exa_request_id"] == "exa-request-123"


@pytest.mark.anyio("asyncio")
async def test_tavily_quota_exa_empty_records_manual_required(tmp_path):
    client = QuotaTavilyClient()
    exa = EmptyExaClient()
    stats = {}
    task = {
        "task_id": "quota-gold-exa-empty",
        "indicator_key": "GC=F",
        "stage_phase": "assets",
        "category": "commodities",
        "search_backend": "tavily",
        "query": "COMEX gold latest price",
        "unit": "$/oz",
        "created_at": 1700000000,
        "preferred_domains": [],
    }

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        {"commodities": []},
        client,
        exa,
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

    assert client.calls == 1
    assert len(exa.calls) == 1
    assert completed == []
    assert len(failures) == 1
    assert failures[0]["search_backend"] == "exa"
    assert failures[0]["manual_reason"] == "exa_empty"
    assert websearch_results[0]["search_backend"] == "exa"
    assert websearch_results[0]["manual_reason"] == "exa_empty"


@pytest.mark.anyio("asyncio")
async def test_tavily_quota_fast_switches_remaining_tasks_to_manual_required(tmp_path):
    client = QuotaTavilyClient()
    stats = {}
    task_log_path = tmp_path / "task_log.jsonl"
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
        None,
        NoopExtractor(),
        task_log_path=task_log_path,
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
    assert client.calls == 1
    assert stats["tavily_unavailable_reason"] == "quota_or_rate_limit"
    assert len(failures) == 2
    assert len(websearch_results) == 2
    assert all(record["manual_required"] is True for record in failures)
    assert all(record["manual_reason"] == "quota_or_rate_limit" for record in failures)
    assert all("tavily_fast_switch" in record["note"] for record in failures)
    assert [record["indicator_key"] for record in failures] == ["GC=F", "CL=F"]

    for item in websearch_results:
        assert item["manual_required"] is True
        assert item["manual_reason"] == "quota_or_rate_limit"
        assert item["source"] == "Stage2 manual_required"
        assert item["raw_results"] == []
        assert item["task"]["manual_required"] is True
        assert item["task"]["manual_reason"] == "quota_or_rate_limit"
        assert item["extraction"]["manual_required"] is True
        assert item["extraction"]["manual_reason"] == "quota_or_rate_limit"
        assert item["result_type"] == "manual_required"

    task_log_records = [
        json.loads(line)
        for line in task_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(task_log_records) == 2
    assert all(record["manual_required"] is True for record in task_log_records)
    assert all(record["manual_reason"] == "quota_or_rate_limit" for record in task_log_records)


@pytest.mark.anyio("asyncio")
async def test_environment_proxy_error_fast_switches_remaining_tasks_to_manual_required(tmp_path):
    client = ProxyErrorTavilyClient()
    stats = {}
    task_log_path = tmp_path / "task_log.jsonl"
    tasks = [
        {
            "task_id": "proxy-gold",
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
            "task_id": "proxy-oil",
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
        None,
        NoopExtractor(),
        task_log_path=task_log_path,
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
    assert client.calls == 1
    assert stats["tavily_unavailable_reason"] == "environment_proxy_error"
    assert "socksio" in stats["environment_proxy_error"].lower()
    assert len(failures) == 2
    assert len(websearch_results) == 2
    assert all(record["manual_required"] is True for record in failures)
    assert all(record["manual_reason"] == "environment_proxy_error" for record in failures)
    assert all(record["result_type"] == "manual_required" for record in failures)
    assert all(record["note"].startswith("environment_proxy_error:") for record in failures)
    assert [record["indicator_key"] for record in failures] == ["GC=F", "CL=F"]

    for item in websearch_results:
        assert item["manual_required"] is True
        assert item["manual_reason"] == "environment_proxy_error"
        assert item["source"] == "Stage2 manual_required"
        assert item["raw_results"] == []
        assert item["task"]["manual_required"] is True
        assert item["task"]["manual_reason"] == "environment_proxy_error"
        assert item["extraction"]["manual_required"] is True
        assert item["extraction"]["manual_reason"] == "environment_proxy_error"
        assert "socksio" in item["extraction"]["llm_error"].lower()
        assert "socksio" in item["extraction"]["environment_proxy_error"].lower()
        assert item["result_type"] == "manual_required"

    task_log_records = [
        json.loads(line)
        for line in task_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(task_log_records) == 2
    assert all(record["manual_required"] is True for record in task_log_records)
    assert all(record["manual_reason"] == "environment_proxy_error" for record in task_log_records)


@pytest.mark.anyio("asyncio")
async def test_environment_proxy_queue_fast_switch_bounds_duplicate_searches_after_marker(tmp_path):
    client = ProxyErrorTavilyClient()
    stats = {}
    task_log_path = tmp_path / "task_log.jsonl"
    tasks = [
        {
            "task_id": "proxy-queue-gold",
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
            "task_id": "proxy-queue-oil",
            "indicator_key": "CL=F",
            "stage_phase": "assets",
            "category": "commodities",
            "search_backend": "tavily",
            "query": "WTI crude latest price",
            "unit": "$/bbl",
            "created_at": 1700000001,
            "preferred_domains": [],
        },
        {
            "task_id": "proxy-queue-copper",
            "indicator_key": "HG=F",
            "stage_phase": "assets",
            "category": "commodities",
            "search_backend": "tavily",
            "query": "COMEX copper latest price",
            "unit": "$/lb",
            "created_at": 1700000002,
            "preferred_domains": [],
        },
    ]

    completed, failures, websearch_results = await _execute_tasks(
        tasks,
        {"commodities": []},
        client,
        None,
        NoopExtractor(),
        task_log_path=task_log_path,
        cache_ttl=None,
        fund_flow_backend="tavily",
        forex_backend="tavily",
        deepseek_timeout=8,
        extraction_backend="deepseek",
        deepseek_max_concurrency=1,
        deepseek_serial_keys=None,
        stats=stats,
        use_queue=True,
        queue_concurrency=2,
        queue_maxsize=10,
        queue_retry_limit=0,
        disable_extract=False,
        extract_topk=1,
        llm_hard_timeout=10,
    )

    assert completed == []
    assert client.calls <= 2
    assert stats["tavily_unavailable_reason"] == "environment_proxy_error"
    assert len(failures) == 3
    assert len(websearch_results) == 3
    assert all(record["manual_required"] is True for record in failures)
    assert all(record["manual_reason"] == "environment_proxy_error" for record in failures)
    assert all(item["manual_reason"] == "environment_proxy_error" for item in websearch_results)


@pytest.mark.anyio("asyncio")
async def test_tavily_quota_fast_switch_preserves_manual_reason_for_force_refresh(tmp_path):
    client = QuotaTavilyClient()
    stats = {}
    tasks = [
        {
            "task_id": "quota-force-refresh-gold",
            "indicator_key": "GC=F",
            "stage_phase": "assets",
            "category": "commodities",
            "search_backend": "tavily",
            "query": "COMEX gold latest price",
            "unit": "$/oz",
            "force_refresh": True,
            "created_at": 1700000000,
            "preferred_domains": [],
        },
        {
            "task_id": "quota-stale-oil",
            "indicator_key": "CL=F",
            "stage_phase": "assets",
            "category": "commodities",
            "search_backend": "tavily",
            "query": "WTI crude latest price",
            "unit": "$/bbl",
            "trigger_reason": "stale_data",
            "created_at": 1700000001,
            "preferred_domains": [],
        },
    ]

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
    assert client.calls == 1
    assert len(failures) == 2
    assert len(websearch_results) == 2
    assert all(record["force_refresh"] is True for record in failures)
    assert all(record["manual_reason"] == "quota_or_rate_limit" for record in failures)
    assert all(item["force_refresh"] is True for item in websearch_results)
    assert all(item["manual_reason"] == "quota_or_rate_limit" for item in websearch_results)
    assert all(
        item["extraction"]["manual_reason"] == "quota_or_rate_limit"
        for item in websearch_results
    )


@pytest.mark.anyio("asyncio")
async def test_tavily_extract_environment_proxy_fast_switches_remaining_tasks(tmp_path):
    client = ExtractProxyErrorTavilyClient()
    stats = {}
    tasks = [
        {
            "task_id": "extract-proxy-gold",
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
            "task_id": "extract-proxy-oil",
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
    assert client.search_calls == 1
    assert client.extract_calls == 1
    assert stats["tavily_unavailable_reason"] == "environment_proxy_error"
    assert len(failures) == 2
    assert len(websearch_results) == 2
    assert all(record["manual_required"] is True for record in failures)
    assert all(record["manual_reason"] == "environment_proxy_error" for record in failures)
    assert all(item["manual_required"] is True for item in websearch_results)
    assert all(item["manual_reason"] == "environment_proxy_error" for item in websearch_results)


@pytest.mark.anyio("asyncio")
async def test_tavily_extract_quota_fast_switches_remaining_tasks(tmp_path):
    client = ExtractQuotaTavilyClient()
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
    assert client.search_calls == 1
    assert client.extract_calls == 1
    assert stats["tavily_unavailable_reason"] == "quota_or_rate_limit"
    assert len(failures) == 2
    assert len(websearch_results) == 2
    assert all(record["manual_required"] is True for record in failures)
    assert all(record["manual_reason"] == "quota_or_rate_limit" for record in failures)
    assert all(item["manual_required"] is True for item in websearch_results)
    assert all(item["manual_reason"] == "quota_or_rate_limit" for item in websearch_results)
    assert all(
        item["extraction"]["manual_reason"] == "quota_or_rate_limit"
        for item in websearch_results
    )
