import json
from pathlib import Path

import pytest

from datasource.engines.stage2_task_planner import Stage2TaskPlanner
import asyncio

from scripts.stage2_unified_enhancer import (
    _apply_extraction,
    _flag_fund_flow_anomalies,
    _compute_derived_metrics,
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


def test_flag_fund_flow_anomalies_marks_zero_values():
    payload = {
        "fund_flow": {
            "northbound": {"recent_5d": 0, "total_120d": None, "source": "MCP raw"},
            "southbound": {"recent_5d": 10.5, "total_120d": 20.1, "source": "MCP raw"},
        }
    }
    flagged = _flag_fund_flow_anomalies(payload)
    assert "northbound" in flagged
    assert payload["fund_flow"]["northbound"]["source"] == "异常零值-需核查"
    assert payload["fund_flow"]["southbound"]["source"] == "MCP WebSearch实时获取"


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


def test_execute_tasks_mcp_backend_skips_search(tmp_path: Path):
    # MCP backend should mark manual_required without invoking client.search
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
        async def search(self, *args, **kwargs):
            raise AssertionError("search should not be called in MCP mode")

    class DummyExtractor:
        async def extract(self, *args, **kwargs):
            return {}

    completed, failures, _ = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            DummyClient(),
            None,
            DummyExtractor(),
            tmp_path / "log.jsonl",
            cache_ttl=10,
            fund_flow_backend="mcp",
        )
    )
    assert not completed
    assert failures and failures[0]["manual_required"] is True
import pytest

pytest.importorskip("langchain_core")
