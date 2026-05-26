from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from datasource.providers.stage2_structured import StructuredProviderError, StructuredResult
from datasource.providers.stage2_structured.registry import StructuredProviderRegistry
from datasource.providers.stage2_structured.tushare_etf import TuShareETFProvider
import scripts.stage2_unified_enhancer as stage2
from scripts.stage2_unified_enhancer import _execute_tasks


def _commodity_task() -> dict:
    return {
        "task_id": "commodity-gold",
        "indicator_key": "GC=F",
        "category": "commodities",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "extraction_backend": "deepseek",
        "query": "COMEX gold close",
        "unit": "$/oz",
        "preferred_domains": [],
        "created_at": 1700000000,
    }


def _commodity_payload() -> dict:
    return {
        "metadata": {"date": "2026-05-23", "missing_items": {"commodities": [{"key": "GC=F"}]}},
        "commodities": [
            {
                "symbol": "GC=F",
                "name": "COMEX黄金",
                "current_price": None,
                "unit": "$/oz",
            }
        ],
        "missing_items": ["GC=F"],
    }


class StructuredGoldRegistry:
    def __init__(self):
        self.calls = 0

    def provider_for(self, indicator_key):
        return object() if indicator_key == "GC=F" else None

    async def fetch(self, task, market_payload, reference_date):
        self.calls += 1
        return StructuredResult(
            provider="gold-fixture",
            indicator_key=task["indicator_key"],
            category="commodities",
            payload={"value": 2410.5, "unit": "$/oz"},
            source="Structured gold fixture",
            source_url="https://finance.yahoo.com/quote/GC=F",
            source_tier="tier2",
            as_of_date=reference_date,
            confidence=0.98,
            diagnostics={"fixture": True},
        )


class ParseErrorGoldRegistry:
    def __init__(self):
        self.calls = 0

    def provider_for(self, indicator_key):
        return object() if indicator_key == "GC=F" else None

    async def fetch(self, task, market_payload, reference_date):
        self.calls += 1
        raise StructuredProviderError(
            provider="gold-fixture",
            indicator_key=task["indicator_key"],
            reason="parse_error",
            message="fixture parse error",
        )


class PolicyBlockedETFRegistry:
    def __init__(self):
        self.calls = 0

    def provider_for(self, indicator_key):
        return object() if indicator_key == "etf" else None

    async def fetch(self, task, market_payload, reference_date):
        self.calls += 1
        return StructuredResult(
            provider="etf-fixture",
            indicator_key=task["indicator_key"],
            category="fund_flow",
            payload={
                "value": 85.0,
                "recent_5d": 85.0,
                "total_120d": 1200.0,
                "trend": "inflow",
                "unit": "亿元",
                "metric_basis": "news_net_flow",
                "window_evidence": "unknown",
                "is_estimated": False,
            },
            source="ETF news fixture",
            source_url="https://finance.example.com/etf-news",
            source_tier="tier3",
            as_of_date=reference_date,
            confidence=0.9,
        )


class MacroCompareRegistry:
    def __init__(self):
        self.calls = 0

    def provider_for(self, indicator_key):
        return object() if indicator_key == "industrial" else None

    async def fetch(self, task, market_payload, reference_date):
        self.calls += 1
        return StructuredResult(
            provider="macro-compare-fixture",
            indicator_key=task["indicator_key"],
            category="macro_indicators",
            payload={
                "value": 4.1,
                "current_value": 4.1,
                "previous_value": 5.7,
                "change_rate": -28.07,
                "value_type": "yoy_month",
                "yoy_month": 4.1,
                "unit": "%",
                "is_estimated": False,
            },
            source="国家统计局",
            source_url="https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963731.html",
            source_tier="tier1",
            as_of_date=reference_date,
            confidence=0.95,
            diagnostics={"fixture": True},
        )


class FailingTavilyClient:
    def __init__(self):
        self.search_calls = 0
        self.extract_calls = 0

    async def search(self, **kwargs):  # pragma: no cover - should not be called
        self.search_calls += 1
        raise AssertionError("Tavily search should not run after structured success")

    async def extract(self, **kwargs):  # pragma: no cover - should not be called
        self.extract_calls += 1
        raise AssertionError("Tavily extract should not run after structured success")


class SearchClient:
    def __init__(self, snippets):
        self.snippets = snippets
        self.search_calls = 0
        self.extract_calls = 0

    async def search(self, **kwargs):
        self.search_calls += 1
        return {"results": list(self.snippets), "request_id": "search-fixture"}

    async def extract(self, **kwargs):  # disabled in these tests
        self.extract_calls += 1
        return {"results": []}


class FailingExtractor:
    def __init__(self):
        self.calls = 0

    async def extract(self, *args, **kwargs):  # pragma: no cover - should not be called
        self.calls += 1
        raise AssertionError("DeepSeek extractor should not run after structured success")


class CommodityExtractor:
    def __init__(self):
        self.calls = 0

    async def extract(self, *args, **kwargs):
        self.calls += 1
        return {
            "value": 2420.25,
            "unit": "$/oz",
            "source_url": "https://example.com/gold",
            "confidence": 0.91,
            "manual_required": False,
        }


class ETFExtractor:
    async def extract(self, *args, **kwargs):
        return {
            "value": 90.0,
            "recent_5d": 90.0,
            "total_120d": 1300.0,
            "trend": "inflow",
            "unit": "亿元",
            "source_url": "https://data.eastmoney.com/etf/",
            "confidence": 0.92,
            "manual_required": False,
            "metric_basis": "net_flow_sum",
            "window_evidence": "direct_daily_series",
            "is_estimated": False,
        }


def _trade_dates(count):
    return [
        (pd.Timestamp("2026-01-01") + pd.Timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range(count)
    ]


class FakeTuShareETFPro:
    def __init__(self):
        self.trade_dates = _trade_dates(121)

    def trade_cal(self, exchange="", start_date=None, end_date=None, is_open=1):
        return pd.DataFrame(
            {"cal_date": self.trade_dates, "is_open": [1] * len(self.trade_dates)}
        )

    def etf_share_size(self, trade_date, exchange=None, market=None):
        exchange_value = exchange or market
        index = self.trade_dates.index(trade_date)
        total_size_wan = (1000.0 + index) * 10000.0 / 2.0
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "exchange": exchange_value,
                    "total_size": total_size_wan,
                }
            ]
        )


class LargeMoveTuShareETFPro(FakeTuShareETFPro):
    def etf_share_size(self, trade_date, exchange=None, market=None):
        exchange_value = exchange or market
        index = self.trade_dates.index(trade_date)
        if index <= 115:
            total_yi = 50435.1099 + (43166.5479 - 50435.1099) * (index / 115.0)
        else:
            total_yi = 43166.5479 + (40000.0 - 43166.5479) * ((index - 115) / 5.0)
        total_size_wan = total_yi * 10000.0 / 2.0
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "exchange": exchange_value,
                    "total_size": total_size_wan,
                }
            ]
        )


@pytest.mark.asyncio
async def test_execute_tasks_structured_success_writes_back_and_skips_search(tmp_path: Path):
    payload = _commodity_payload()
    registry = StructuredGoldRegistry()
    client = FailingTavilyClient()
    extractor = FailingExtractor()
    stats = {}

    completed, failures, websearch_results = await _execute_tasks(
        [_commodity_task()],
        payload,
        client,
        None,
        extractor,
        tmp_path / "task_log.jsonl",
        cache_ttl=None,
        stats=stats,
        structured_registry=registry,
    )

    assert len(completed) == 1
    assert failures == []
    assert payload["commodities"][0]["current_price"] == 2410.5
    assert payload["commodities"][0]["source"] == "structured"
    assert websearch_results[0]["search_backend"] == "structured"
    assert websearch_results[0]["result_type"] == "structured_success"
    assert websearch_results[0]["write_back_success"] is True
    assert websearch_results[0]["write_back_target"] == "commodities"
    assert websearch_results[0]["structured_provider"] == "gold-fixture"
    assert isinstance(websearch_results[0]["structured_provider_latency_ms"], int)
    assert client.search_calls == 0
    assert client.extract_calls == 0
    assert extractor.calls == 0
    assert stats["structured_provider"]["attempt"] == 1
    assert stats["structured_provider"]["success"] == 1
    assert stats["structured_provider"]["by_key"]["GC=F"]["attempt"] == 1
    assert stats["structured_provider"]["by_key"]["GC=F"]["success"] == 1


@pytest.mark.asyncio
async def test_execute_tasks_quality_gap_force_refresh_does_not_skip_existing_macro_value(
    tmp_path: Path,
):
    task = {
        "task_id": "quality-industrial",
        "indicator_key": "industrial",
        "category": "macro_indicators",
        "stage_phase": "essential",
        "search_backend": "tavily",
        "extraction_backend": "structured",
        "query": "国家统计局 工业增加值 2026年4月 同比",
        "unit": "%",
        "preferred_domains": ["stats.gov.cn"],
        "trigger_reason": "quality_gap",
        "quality_gap_reason": "missing_compare_values",
        "required_output_fields": ["current_value", "previous_value", "change_rate"],
        "force_refresh": True,
        "created_at": 1700000000,
    }
    payload = {
        "metadata": {
            "date": "2026-05-22",
            "missing_items": {"macro_indicators": [{"key": "industrial"}]},
        },
        "macro_indicators": {
            "industrial": {
                "indicator_name": "工业增加值",
                "current_value": 1.0,
                "previous_value": None,
                "change_rate": None,
                "unit": "%",
                "is_estimated": False,
                "source": "old",
            }
        },
        "missing_items": ["industrial"],
    }
    registry = MacroCompareRegistry()
    stats = {}

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        payload,
        FailingTavilyClient(),
        None,
        None,
        tmp_path / "task_log.jsonl",
        cache_ttl=None,
        stats=stats,
        disable_extract=True,
        structured_registry=registry,
    )

    assert registry.calls == 1
    assert failures == []
    assert len(completed) == 1
    assert completed[0]["result_type"] == "structured_success"
    industrial = payload["macro_indicators"]["industrial"]
    assert industrial["current_value"] == pytest.approx(4.1)
    assert industrial["previous_value"] == pytest.approx(5.7)
    assert industrial["change_rate"] == pytest.approx(-28.07)
    assert industrial["value_type"] == "yoy_month"
    assert industrial["yoy_month"] == pytest.approx(4.1)
    assert industrial["is_estimated"] is False
    assert websearch_results[0]["result_type"] == "structured_success"
    assert stats["structured_provider"]["success"] == 1


@pytest.mark.asyncio
async def test_execute_tasks_structured_parse_error_falls_back_to_search(tmp_path: Path):
    payload = _commodity_payload()
    registry = ParseErrorGoldRegistry()
    client = SearchClient(
        [
            {
                "url": "https://example.com/gold",
                "title": "Gold close",
                "snippet": "COMEX gold closed at 2420.25 $/oz",
                "content": "COMEX gold closed at 2420.25 $/oz",
                "score": 0.9,
            }
        ]
    )
    extractor = CommodityExtractor()
    stats = {}

    completed, failures, websearch_results = await _execute_tasks(
        [_commodity_task()],
        payload,
        client,
        None,
        extractor,
        tmp_path / "task_log.jsonl",
        cache_ttl=None,
        stats=stats,
        disable_extract=True,
        structured_registry=registry,
    )

    assert len(completed) == 1
    assert failures == []
    assert payload["commodities"][0]["current_price"] == 2420.25
    assert client.search_calls == 1
    assert extractor.calls == 1
    assert websearch_results[-1]["search_backend"] == "tavily"
    assert completed[0]["structured_provider_attempted"] is True
    assert completed[0]["structured_provider_fallback_reason"] == "parse_error"
    assert websearch_results[-1]["task"]["structured_provider_attempted"] is True
    assert websearch_results[-1]["task"]["structured_provider_fallback_reason"] == "parse_error"
    assert stats["structured_provider"]["fallback"] == 1
    assert stats["structured_provider"]["error_breakdown"]["parse_error"] == 1
    assert stats["structured_provider"]["by_key"]["GC=F"]["fallback"] == 1


@pytest.mark.asyncio
async def test_execute_tasks_structured_fund_flow_gate_block_falls_back_to_search(tmp_path: Path):
    task = {
        "task_id": "fund-flow-etf",
        "indicator_key": "etf",
        "category": "fund_flow",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "extraction_backend": "deepseek",
        "query": "A股 ETF 资金流向",
        "unit": "亿元",
        "preferred_domains": [],
        "created_at": 1700000000,
    }
    payload = {
        "metadata": {"date": "2026-05-23", "missing_items": {"fund_flow": [{"key": "etf"}]}},
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None, "is_estimated": False}},
        "missing_items": ["etf"],
    }
    client = SearchClient(
        [
            {
                "url": "https://data.eastmoney.com/etf/",
                "title": "ETF flow",
                "snippet": "ETF 近5日净流入 90 亿元，近120日累计 1300 亿元",
                "content": "ETF 近5日净流入 90 亿元，近120日累计 1300 亿元",
                "score": 0.95,
            }
        ]
    )
    stats = {}

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        payload,
        client,
        None,
        ETFExtractor(),
        tmp_path / "task_log.jsonl",
        cache_ttl=None,
        stats=stats,
        disable_extract=True,
        structured_registry=PolicyBlockedETFRegistry(),
    )

    assert len(completed) == 1
    assert failures == []
    assert client.search_calls == 1
    assert payload["fund_flow"]["etf"]["recent_5d"] == 90.0
    assert payload["fund_flow"]["etf"]["is_estimated"] is False
    assert websearch_results[-1]["search_backend"] == "tavily"
    assert stats["structured_policy_gate_blocked"] == 1
    assert stats["structured_provider"]["fallback"] == 1
    assert sum(stats["structured_provider"]["error_breakdown"].values()) == 1


@pytest.mark.asyncio
async def test_execute_tasks_tushare_etf_keeps_direct_window_metadata(tmp_path: Path):
    task = {
        "task_id": "fund-flow-etf",
        "indicator_key": "etf",
        "category": "fund_flow",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "extraction_backend": "deepseek",
        "query": "A股 ETF 资金流向",
        "unit": "亿元",
        "preferred_domains": [],
        "created_at": 1700000000,
    }
    payload = {
        "metadata": {"date": "2026-05-23", "missing_items": {"fund_flow": [{"key": "etf"}]}},
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None, "is_estimated": False}},
        "missing_items": ["etf"],
    }
    client = FailingTavilyClient()
    extractor = FailingExtractor()
    registry = StructuredProviderRegistry([TuShareETFProvider(pro=FakeTuShareETFPro())])

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        payload,
        client,
        None,
        extractor,
        tmp_path / "task_log.jsonl",
        cache_ttl=None,
        stats={},
        structured_registry=registry,
    )

    etf = payload["fund_flow"]["etf"]
    assert len(completed) == 1
    assert failures == []
    assert etf["source_tier"] == "tier2"
    assert etf["window_evidence"] == "direct_balance_delta"
    assert etf["metric_basis"] == "etf_total_size_delta"
    assert etf["is_estimated"] is False
    assert client.search_calls == 0
    assert client.extract_calls == 0
    assert extractor.calls == 0
    assert websearch_results[0]["search_backend"] == "structured"


@pytest.mark.asyncio
async def test_execute_tasks_tushare_etf_accepts_large_scale_delta_with_direct_window(
    tmp_path: Path,
):
    task = {
        "task_id": "fund-flow-etf",
        "indicator_key": "etf",
        "category": "fund_flow",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "extraction_backend": "deepseek",
        "query": "A股 ETF 资金流向",
        "unit": "亿元",
        "preferred_domains": [],
        "created_at": 1700000000,
    }
    payload = {
        "metadata": {"date": "2026-05-23", "missing_items": {"fund_flow": [{"key": "etf"}]}},
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None, "is_estimated": False}},
        "missing_items": ["etf"],
    }
    client = FailingTavilyClient()
    extractor = FailingExtractor()
    registry = StructuredProviderRegistry([TuShareETFProvider(pro=LargeMoveTuShareETFPro())])
    stats = {}

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        payload,
        client,
        None,
        extractor,
        tmp_path / "task_log.jsonl",
        cache_ttl=None,
        stats=stats,
        structured_registry=registry,
    )

    etf = payload["fund_flow"]["etf"]
    assert len(completed) == 1
    assert failures == []
    assert etf["recent_5d"] == pytest.approx(-3166.5479)
    assert etf["total_120d"] == pytest.approx(-10435.1099)
    assert etf["metric_basis"] == "etf_total_size_delta"
    assert etf["window_evidence"] == "direct_balance_delta"
    assert etf["is_estimated"] is False
    assert client.search_calls == 0
    assert extractor.calls == 0
    assert stats.get("structured_policy_gate_blocked", 0) == 0
    assert websearch_results[0]["search_backend"] == "structured"


def test_build_structured_registry_for_args_defaults_to_registry(monkeypatch):
    registry = object()
    monkeypatch.setattr(stage2, "build_default_registry", lambda: registry)

    result = stage2._build_structured_registry_for_args(
        SimpleNamespace(disable_structured_providers=False)
    )

    assert result is registry


def test_build_structured_registry_for_args_disable_returns_none(monkeypatch):
    monkeypatch.setattr(stage2, "build_default_registry", lambda: object())

    result = stage2._build_structured_registry_for_args(
        SimpleNamespace(disable_structured_providers=True)
    )

    assert result is None


def test_build_structured_registry_for_args_failure_returns_none(monkeypatch):
    def boom():
        raise RuntimeError("registry failed")

    monkeypatch.setattr(stage2, "build_default_registry", boom)

    result = stage2._build_structured_registry_for_args(
        SimpleNamespace(disable_structured_providers=False)
    )

    assert result is None


def test_stage2_effective_hit_rate():
    assert stage2._stage2_effective_hit_rate(2, 1) == pytest.approx(2 / 3)
    assert stage2._stage2_effective_hit_rate(0, 0) == 0.0


def test_stage2_summary_includes_structured_provider_diagnostics():
    completed = [
        {
            "task_id": "structured-gold",
            "indicator_key": "GC=F",
            "result_type": "structured_success",
            "write_back_success": True,
        }
    ]
    summary = stage2._build_stage2_summary_diagnostics(
        completed,
        failures=[],
        websearch_results=[],
        exec_stats={
            "structured_provider": {
                "attempt": 2,
                "success": 1,
                "fallback": 1,
                "by_key": {
                    "GC=F": {"attempt": 1, "success": 1, "fallback": 0},
                    "CL=F": {"attempt": 1, "success": 0, "fallback": 1},
                },
                "error_breakdown": {"parse_error": 1},
                "latency_ms_by_provider": {"gold-fixture": [12]},
            }
        },
    )

    assert summary["structured_provider_attempt_count"] == 2
    assert summary["structured_provider_success_count"] == 1
    assert summary["structured_provider_fallback_to_search_count"] == 1
    assert summary["structured_provider_success_by_key"] == {"GC=F": 1}
    assert summary["structured_provider_error_breakdown"] == {"parse_error": 1}
    assert summary["structured_provider_latency_ms_by_provider"] == {"gold-fixture": [12]}
    assert summary["retrieval_diagnostics"]["writeback_success_count"] == 1
