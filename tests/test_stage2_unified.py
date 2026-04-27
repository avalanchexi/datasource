import json
from datetime import datetime
from pathlib import Path

import pytest

from datasource.engines.stage2_task_planner import Stage2TaskPlanner
import asyncio

from scripts.stage2_unified_enhancer import (
    _apply_extraction,
    _candidate_query_quality,
    _flag_fund_flow_anomalies,
    _compute_derived_metrics,
    _update_missing_items,
    _gap_monitor,
    _merge_missing_items,
    _validate_fund_flow_extraction,
    _execute_tasks,
)

def test_task_planner_detects_missing_and_placeholders(tmp_path: Path):
    payload = {
        "missing_items": [{"key": "cpi"}, "pmi_new_orders"],
        "macro_indicators": {"ppi": {"current_value": 7.13}},
        "monetary_policy": {"m2": {"current_value": None}},
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    indicator_keys = {t["indicator_key"] for t in tasks}
    assert {"cpi", "pmi_new_orders", "ppi", "m2"} <= indicator_keys


def test_task_planner_picks_stale_entries(tmp_path: Path):
    payload = {
        "missing_items": [],
        "macro_indicators": {
            "cpi": {"current_value": 0.8, "is_stale": True, "expected_period": "2026-01"},
        },
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    task_map = {t["indicator_key"]: t for t in tasks}
    assert "cpi" in task_map
    assert task_map["cpi"]["trigger_reason"] == "stale_data"
    assert task_map["cpi"]["expected_period"] == "2026-01"
    assert "2026-01" in task_map["cpi"]["expected_period_tokens"]


def test_task_planner_expands_expected_period_for_query_families(tmp_path: Path):
    payload = {
        "missing_items": [],
        "macro_indicators": {
            "industrial_sales": {"current_value": None, "is_stale": True, "expected_period": "2026-02"},
        },
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    task = next(t for t in tasks if t["indicator_key"] == "industrial_sales")
    assert any("2026年1-2月" in q for q in task["query_candidates_expanded"])


def test_task_planner_keeps_etf_field_queries(tmp_path: Path):
    payload = {
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None}},
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    task = next(t for t in tasks if t["indicator_key"] == "etf")
    assert "recent_5d" in task["field_queries"]
    assert "total_120d" in task["field_queries"]


def test_task_planner_dedupe_prefers_stale_reason(tmp_path: Path):
    payload = {
        "missing_items": [{"key": "cpi", "reason": "manual_missing"}],
        "macro_indicators": {
            "cpi": {"current_value": 7.13, "is_stale": True, "expected_period": "2026-01"},
        },
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    cpi_tasks = [t for t in tasks if t["indicator_key"] == "cpi"]
    assert len(cpi_tasks) == 1
    assert cpi_tasks[0]["trigger_reason"] == "stale_data"


def test_flag_fund_flow_anomalies_marks_zero_values():
    payload = {
        "fund_flow": {
            "northbound": {"recent_5d": 0, "total_120d": None, "source": "legacy_raw"},
            "southbound": {"recent_5d": 10.5, "total_120d": 20.1, "source": "legacy_raw"},
        }
    }
    flagged = _flag_fund_flow_anomalies(payload)
    assert "northbound" in flagged
    assert payload["fund_flow"]["northbound"]["source"] == "异常零值-需核查"
    assert payload["fund_flow"]["southbound"]["source"] in ("legacy_raw", "tavily+deepseek")


def test_gap_monitor_pending_only_incomplete(tmp_path: Path):
    pending = ["a", "b"]
    path = tmp_path / "gap.json"
    _gap_monitor(pending, path, manual_required=["b"])
    data = json.load(path.open())
    assert data["pending_tasks"] == pending
    assert data["manual_required"] == ["b"]


def test_merge_missing_items_flatten_metadata():
    payload = {
        "metadata": {
            "missing_items": {
                "macro": [{"key": "cpi"}],
                "fund_flow": ["northbound"],
            }
        }
    }
    _merge_missing_items(payload)
    assert "missing_items" in payload
    keys = {it["key"] if isinstance(it, dict) else it for it in payload["missing_items"]}
    assert {"cpi", "northbound"} <= keys


def test_compute_derived_metrics_spread_and_trend():
    payload = {
        "monetary_policy": {"m1": {"current_value": 5}, "m2": {"current_value": 8}, "dr007": {"history": [2.1, 2.2]}},
        "commodities": [{"daily_change": 1.0}, {"daily_change": -0.5}],
    }
    _compute_derived_metrics(payload)
    derived = payload["derived_metrics"]
    assert derived["m1_m2_spread"] == -3.0
    assert "commodity_trend" in derived


def test_candidate_query_quality_prefers_trusted_period_and_issuer():
    task = {
        "indicator_key": "reverse_repo",
        "preferred_domains": ["pbc.gov.cn"],
        "required_keywords": ["逆回购", "中标利率"],
        "exclude_keywords": [],
        "issuer": "中国人民银行",
        "issuer_aliases": ["人民银行", "PBOC"],
        "expected_period_tokens": ["2026-02", "2026年2月"],
        "max_age_days": 30,
    }
    candidate = {
        "required_keywords": [],
        "exclude_keywords": [],
        "preferred_domains": ["pbc.gov.cn"],
    }
    official_snippets = [
        {
            "url": "https://www.pbc.gov.cn/notice/2026-02-18.html",
            "content": "2026年2月 人民银行公开市场业务交易公告 7天逆回购中标利率为1.40%",
            "score": 0.61,
        }
    ]
    noisy_snippets = [
        {
            "url": "https://example.com/forecast",
            "content": "reverse repo forecast 1.40% without issuer or target period",
            "score": 0.99,
        }
    ]
    official = _candidate_query_quality(task, candidate, official_snippets)
    noisy = _candidate_query_quality(task, candidate, noisy_snippets)
    assert official["quality_score"] > noisy["quality_score"]


def test_candidate_query_quality_strict_keywords_rejects_unrelated_snippets():
    task = {
        "indicator_key": "GSG",
        "preferred_domains": ["ishares.com", "investing.com"],
        "required_keywords": ["gsg", "ishares", "quote"],
        "exclude_keywords": [],
        "issuer": "iShares/BlackRock",
        "issuer_aliases": ["iShares", "BlackRock"],
        "expected_period_tokens": [],
        "max_age_days": 7,
        "strict_required_keywords": True,
    }
    candidate = {
        "preferred_domains": ["investing.com"],
        "required_keywords": ["gsg", "ishares", "quote"],
        "exclude_keywords": [],
    }
    noisy_snippets = [
        {
            "url": "https://www.investing.com/etfs/ishares-s-p-global-telecom",
            "content": "iShares Global Telecom ETF quote latest",
            "score": 0.95,
        }
    ]
    quality = _candidate_query_quality(task, candidate, noisy_snippets)
    assert quality["snippets"] == []
    assert quality["usable_count"] == 0
    assert quality["unusable_reason"] == "strict_keyword_miss"


def test_validate_fund_flow_direction_outflow():
    extraction = {"value": 12.0, "unit": "亿元", "note": "近5日净流出，总览"}
    val, manual, note = _validate_fund_flow_extraction(extraction, indicator_key="northbound")
    assert val == -12.0
    assert manual is False
    assert "方向" not in (note or "")


def test_validate_fund_flow_missing_unit_marks_manual():
    extraction = {"value": 5, "unit": "", "note": "净流入"}
    val, manual, note = _validate_fund_flow_extraction(extraction, indicator_key="northbound")
    assert manual is True
    assert "单位缺失" in (note or "")
    assert val == 5


def test_validate_fund_flow_placeholder_100_marks_manual():
    extraction = {"value": 100.0, "unit": "亿元", "note": "净流入"}
    val, manual, note = _validate_fund_flow_extraction(extraction, indicator_key="northbound")
    assert val == 100.0
    assert manual is True
    assert "疑似占位值" in (note or "")


def test_apply_extraction_writes_to_array_sections():
    payload = {
        "metadata": {"date": "2026-02-06"},
        "macro_indicators": {},
        "monetary_policy": {},
        "forex": [{"pair": "USDCNY", "current_rate": None, "source": ""}],
        "commodities": [{"symbol": "CL=F", "current_price": None, "source": ""}],
        "bonds": [{"symbol": "CN10Y", "current_yield": None, "source": ""}],
    }
    task_fx = {"indicator_key": "USDCNY", "task_id": "t-fx"}
    task_cmdty = {"indicator_key": "CL=F", "task_id": "t-cmdty"}
    task_bond = {"indicator_key": "CN10Y", "task_id": "t-bond"}

    cat_fx = _apply_extraction(payload, task_fx, {"value": 7.12, "note": "ok", "source_url": "https://example.com"})
    cat_cmdty = _apply_extraction(payload, task_cmdty, {"value": 72.5, "note": "ok", "source_url": "https://example.com"})
    cat_bond = _apply_extraction(payload, task_bond, {"value": 2.15, "note": "ok", "source_url": "https://example.com"})

    assert cat_fx == "forex"
    assert cat_cmdty == "commodities"
    assert cat_bond == "bonds"
    assert payload["forex"][0]["current_rate"] == pytest.approx(7.12)
    assert payload["commodities"][0]["current_price"] == pytest.approx(72.5)
    assert payload["bonds"][0]["current_yield"] == pytest.approx(2.15)


def test_apply_extraction_upserts_forex_when_section_missing_item():
    payload = {
        "metadata": {"date": "2026-02-06"},
        "macro_indicators": {},
        "monetary_policy": {},
        "forex": [],
        "commodities": [],
        "bonds": [],
    }
    task_fx = {"indicator_key": "USDCNY", "task_id": "t-fx-upsert"}
    category = _apply_extraction(
        payload,
        task_fx,
        {"value": 6.98, "note": "ok", "source_url": "https://example.com"},
    )
    assert category == "forex_upsert"
    assert payload["forex"]
    assert payload["forex"][0]["pair"] == "USDCNY"
    assert payload["forex"][0]["current_rate"] == pytest.approx(6.98)



def test_apply_extraction_bdi_trusted_source_clears_estimated_and_missing():
    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        "metadata": {
            "date": today,
            "missing_items": {"macro_indicators": [{"key": "bdi", "reason": "estimated_not_allowed"}]},
        },
        "missing_items": ["bdi"],
        "macro_indicators": {
            "bdi": {
                "indicator_name": "BDI",
                "current_value": None,
                "unit": "points",
                "date": today,
                "is_estimated": True,
                "source": "tavily+deepseek",
            }
        },
        "monetary_policy": {},
        "forex": [],
        "commodities": [],
        "bonds": [],
    }
    task = {"indicator_key": "bdi", "task_id": "t-bdi"}

    category = _apply_extraction(
        payload,
        task,
        {
            "value": 2233.0,
            "unit": "points",
            "as_of_date": today,
            "source_url": "https://www.tradingeconomics.com/commodity/baltic",
            "note": "verified",
        },
    )
    _update_missing_items(payload, "bdi")

    assert category == "macro_indicators"
    assert payload["macro_indicators"]["bdi"]["is_estimated"] is False
    assert payload["missing_items"] == []
    assert payload["metadata"]["missing_items"] == {}
def test_flag_fund_flow_anomalies_marks_placeholder_pair():
    payload = {
        "fund_flow": {
            "northbound": {"recent_5d": 100.0, "total_120d": 100.0, "source": "tavily+deepseek"},
        }
    }
    flagged = _flag_fund_flow_anomalies(payload)
    assert "northbound" in flagged
    assert payload["fund_flow"]["northbound"]["source"] == "异常零值-需核查"
    assert "疑似占位值" in payload["fund_flow"]["northbound"]["note"]


def test_execute_tasks_legacy_mcp_backend_still_searches(tmp_path: Path):
    # 历史 mcp backend 配置应被忽略，仍走 tavily 搜索
    payload = {"fund_flow": {"northbound": {"recent_5d": None, "total_120d": None}}}
    task = {
        "task_id": "t1",
        "indicator_key": "northbound",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "mcp",
        "preferred_domains": [],
        "time_range": None,
        "query": None,
        "unit": "亿元",
        "issuer": None,
        "retry_count": 0,
        "created_at": 0,
    }

    class DummyClient:
        def __init__(self):
            self.called = 0

        async def search(self, *args, **kwargs):
            self.called += 1
            return {
                "results": [
                    {
                        "url": "https://example.com/northbound",
                        "snippet": "北向资金近5日净流入 12.3 亿元，近120日累计 456.7 亿元",
                        "score": 0.9,
                    }
                ]
            }

    class DummyExtractor:
        async def extract(self, *args, **kwargs):
            return {
                "value": 12.3,
                "unit": "亿元",
                "source_url": "https://example.com/northbound",
                "confidence": 0.9,
                "manual_required": False,
                "recent_5d": 12.3,
                "total_120d": 456.7,
                "trend": "inflow",
            }

    client = DummyClient()
    completed, failures, _ = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            client,
            None,
            DummyExtractor(),
            tmp_path / "log.jsonl",
            cache_ttl=10,
            fund_flow_backend="mcp",
        )
    )
    assert client.called == 1
    assert completed
    assert not failures


def test_execute_tasks_force_refresh_ignores_existing_value_skip(tmp_path: Path):
    payload = {
        "macro_indicators": {
            "cpi": {
                "current_value": 1.2,
                "is_stale": True,
                "expected_period": "2026-02",
            }
        },
        "missing_items": [{"key": "cpi", "reason": "stale_data"}],
    }
    task = {
        "task_id": "t-force-refresh",
        "indicator_key": "cpi",
        "stage_phase": "essential",
        "search_backend": "tavily",
        "preferred_domains": ["stats.gov.cn"],
        "query": "中国CPI 最新公布 国家统计局",
        "unit": "%",
        "issuer": "国家统计局",
        "retry_count": 0,
        "created_at": 0,
        "trigger_reason": "stale_data",
        "force_refresh": True,
    }

    class DummyClient:
        def __init__(self):
            self.called = 0

        async def search(self, *args, **kwargs):
            self.called += 1
            return {
                "results": [
                    {
                        "url": "https://www.stats.gov.cn/cpi",
                        "snippet": "国家统计局公布 CPI 同比上涨 0.9%",
                        "content": "国家统计局公布 CPI 同比上涨 0.9%",
                        "score": 0.95,
                    }
                ]
            }

    class DummyExtractor:
        async def extract(self, *args, **kwargs):
            return {
                "value": 0.9,
                "unit": "%",
                "source_url": "https://www.stats.gov.cn/cpi",
                "confidence": 0.9,
                "manual_required": False,
                "manual_reason": None,
            }

    client = DummyClient()
    completed, failures, results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            client,
            None,
            DummyExtractor(),
            tmp_path / "force_refresh.jsonl",
            cache_ttl=10,
            disable_extract=True,
            extraction_backend="deepseek",
        )
    )
    assert client.called == 1
    assert completed
    assert not failures
    assert results[0]["result_type"] == "search_success"
    assert results[0]["extraction"].get("note") != "existing_value"


def test_execute_tasks_skip_existing_value_clears_missing_items_and_marks_result_type(tmp_path: Path):
    payload = {
        "fund_flow": {
            "northbound": {"recent_5d": 10.0, "total_120d": 20.0, "source": "tushare"}
        },
        "missing_items": [{"key": "northbound", "reason": "manual_missing"}],
        "metadata": {"missing_items": {"fund_flow": [{"key": "northbound"}]}},
    }
    task = {
        "task_id": "t-skip-existing",
        "indicator_key": "northbound",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "preferred_domains": [],
        "query": "北向资金 月度净流入",
        "unit": "亿元",
        "issuer": None,
        "retry_count": 0,
        "created_at": 0,
        "trigger_reason": "missing",
    }

    class NeverCalledClient:
        async def search(self, *args, **kwargs):  # pragma: no cover - 不应执行
            raise AssertionError("search should not be called")

    completed, failures, results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            NeverCalledClient(),
            None,
            object(),
            tmp_path / "skip_existing.jsonl",
            cache_ttl=10,
        )
    )
    assert completed
    assert not failures
    assert results[0]["result_type"] == "skipped_existing"
    assert payload["missing_items"] == []
    assert payload["metadata"]["missing_items"] == {}


def test_execute_tasks_etf_field_retry_fills_missing_windows(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-03-06"},
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None, "source": ""}},
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == "etf")

    class DummyClient:
        async def search(self, query, **kwargs):
            if "近120日" in query or "年内累计" in query:
                snippet = "A股ETF近120日累计净流入1200亿元"
            elif "近5日" in query:
                snippet = "A股ETF近5日净流入85亿元"
            else:
                snippet = "A股ETF近5日净流入85亿元"
            return {
                "results": [
                    {
                        "url": "https://data.eastmoney.com/etf",
                        "snippet": snippet,
                        "content": snippet,
                        "score": 0.88,
                    }
                ]
            }

    class DummyExtractor:
        async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
            text = " ".join(str(s.get("content") or s.get("snippet") or "") for s in snippets)
            if "近120日" in text or "累计" in text:
                return {
                    "value": 1200.0,
                    "unit": "亿元",
                    "source_url": "https://data.eastmoney.com/etf",
                    "confidence": 0.9,
                    "note": "field_total",
                    "manual_required": False,
                    "manual_reason": None,
                    "recent_5d": None,
                    "total_120d": 1200.0,
                    "trend": "inflow",
                }
            return {
                "value": 85.0,
                "unit": "亿元",
                "source_url": "https://data.eastmoney.com/etf",
                "confidence": 0.9,
                "note": "field_recent",
                "manual_required": True,
                "manual_reason": "fund_flow_window_missing",
                "recent_5d": 85.0,
                "total_120d": None,
                "trend": "inflow",
            }

    completed, failures, _ = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            DummyClient(),
            None,
            DummyExtractor(),
            tmp_path / "field_retry_log.jsonl",
            cache_ttl=10,
            disable_extract=True,
            extraction_backend="deepseek",
        )
    )
    assert completed
    assert not failures
    assert payload["fund_flow"]["etf"]["recent_5d"] == pytest.approx(85.0)
    assert payload["fund_flow"]["etf"]["total_120d"] == pytest.approx(1200.0)
    assert payload["fund_flow"]["etf"]["trend"] == "流入"
