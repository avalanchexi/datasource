#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""单元测试: WebSearch 注入脚本的数据标准化逻辑"""

import sys
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import scripts.stage2_5_injector as injector
from datasource.models.market_data_contract import CommodityData


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("-2.1%", -2.1),
        ("49.0点", 49.0),
        ("", None),
        (None, None),
        (123, 123.0),
    ],
)
def test_coerce_float_handles_percent_and_units(raw, expected):
    assert injector._coerce_float(raw) == expected


@pytest.mark.parametrize("raw", [7.13, "7.13"])
def test_is_placeholder_numeric_preserves_legacy_713_placeholder(raw):
    assert injector._is_placeholder_numeric(raw) is True


def test_apply_fund_flow_entry_normalizes_websearch_payload():
    entry = {"type": "northbound", "recent_5d": None, "total_120d": None, "trend": "待获取", "source": "占位", "note": ""}
    payload = {
        "recent_5d": "约140亿元",
        "total_120d": "约1800亿元",
        "trend": "流入",
        "source": "东方财富网",
        "note": "11月5日成交创阶段高位",
    }

    updated = injector._apply_fund_flow_entry(entry, "northbound", payload)
    assert updated is True
    assert entry["recent_5d"] == pytest.approx(140.0)
    assert entry["total_120d"] == pytest.approx(1800.0)
    assert entry["trend"] == "流入"
    assert entry["source"] == "websearch_manual"
    assert "来源:东方财富网" in entry["note"]
    assert "原始5日:约140亿元" in entry["note"]


def test_apply_fund_flow_entry_marks_zero_anomaly():
    entry = {"type": "southbound", "recent_5d": None, "total_120d": None, "trend": "待获取", "source": "占位", "note": ""}
    payload = {
        "recent_5d": "0",
        "total_120d": "0",
        "trend": "震荡",
        "source": "同花顺",
    }

    updated = injector._apply_fund_flow_entry(entry, "southbound", payload)
    assert updated is True
    assert entry["recent_5d"] == 0.0
    assert entry["total_120d"] == 0.0
    assert entry["trend"] == "震荡"
    assert entry["source"] == "异常零值-需核查"
    assert "异常: 零值待WebSearch复核" in entry["note"]


def test_apply_fund_flow_entry_accepts_current_value_only():
    entry = {"type": "northbound", "recent_5d": None, "total_120d": None, "trend": "待获取", "source": "占位", "note": ""}
    payload = {
        "current_value": "35.6亿元",
        "date": "2026-01-12",
        "source": "每日经济新闻",
    }

    updated = injector._apply_fund_flow_entry(entry, "northbound", payload)
    assert updated is True
    assert entry["current_value"] == pytest.approx(35.6)
    assert entry["current_date"] == "2026-01-12"
    assert "原始当日:35.6亿元" in entry["note"]


def test_apply_fund_flow_entry_overrides_suspicious_stage2_pair():
    entry = {
        "type": "northbound",
        "recent_5d": 100.0,
        "total_120d": 100.0,
        "trend": "流入",
        "source": "tavily+deepseek",
        "note": "stage2_auto",
    }
    payload = {
        "recent_5d": "268.5亿元",
        "total_120d": "1320.2亿元",
        "trend": "流入",
        "source": "东方财富",
    }

    updated = injector._apply_fund_flow_entry(entry, "northbound", payload)
    assert updated is True
    assert entry["recent_5d"] == pytest.approx(268.5)
    assert entry["total_120d"] == pytest.approx(1320.2)
    assert entry["source"] == "websearch_manual"
    assert entry["note"].startswith("覆盖Stage2可疑占位值")


def test_create_monetary_placeholder_keeps_date_empty_when_unknown():
    metadata = {"date": "2025-11-14"}
    placeholder = injector._create_monetary_placeholder("dr007", {"unit": "%"}, metadata)
    assert placeholder["policy_name"] == "DR007"
    assert placeholder["date"] == ""
    assert placeholder["is_estimated"] is True


def test_apply_monetary_entry_uses_change_rate_when_delta_missing():
    entry = {
        "policy_name": "DR007",
        "current_value": None,
        "change_from_120d": None,
        "unit": "%",
        "date": "2025-11-14",
        "source": "占位",
        "note": "",
    }
    payload = {
        "policy_name": "DR007",
        "current_value": "1.85",
        "change_rate": "-0.15",
        "unit": "%",
        "date": "2025-11-14",
        "source": "全国银行间同业拆借中心",
    }
    updated = injector._apply_monetary_entry("dr007", entry, payload, "2025-11-14")
    assert updated is True
    assert entry["current_value"] == pytest.approx(1.85)
    assert entry["change_from_120d"] == pytest.approx(-0.15)
    assert entry["source"].startswith("websearch_manual(")


def test_merge_bond_entry_marks_low_confidence_when_history_base_estimated(monkeypatch):
    existing = {
        "symbol": "CN10Y",
        "name": "中国10年期国债",
        "current_yield": None,
        "change_5d_bp": None,
        "change_120d_bp": None,
        "trend": "未知",
        "source": "占位",
        "note": "",
    }
    payload = {"symbol": "CN10Y", "current_yield": "1.83", "source": "东方财富"}

    def _fake_history(*args, **kwargs):
        return {
            "change_5d_bp": 2.1,
            "change_120d_bp": -8.4,
            "reason_5d": None,
            "reason_120d": None,
            "base_5d_estimated": True,
            "base_120d_estimated": False,
        }

    monkeypatch.setattr(injector, "_calc_change_from_trend_history", _fake_history)
    merged = injector._merge_bond_entry(existing, payload, is_manual=True)
    assert merged["change_5d_bp"] == pytest.approx(2.1)
    assert merged["change_120d_bp"] == pytest.approx(-8.4)
    assert merged["trend_history_confidence"] == "low"


def test_merge_bond_entry_preserves_date_fields(monkeypatch):
    existing = {
        "symbol": "CN10Y_CDB",
        "name": "中国10年期国开债",
        "current_yield": None,
        "change_5d_bp": None,
        "change_120d_bp": None,
        "trend": "未知",
        "source": "占位",
        "note": "",
    }
    payload = {
        "symbol": "CN10Y_CDB",
        "current_yield": "1.959",
        "date": "2026-02-09",
        "as_of_date": "2026-02-09",
        "source": "东方财富",
    }

    def _fake_history(*args, **kwargs):
        return {
            "change_5d_bp": 10.9,
            "change_120d_bp": -8.4,
            "reason_5d": None,
            "reason_120d": None,
            "base_5d_estimated": False,
            "base_120d_estimated": False,
        }

    monkeypatch.setattr(injector, "_calc_change_from_trend_history", _fake_history)
    merged = injector._merge_bond_entry(existing, payload, is_manual=True)
    assert merged["date"] == "2026-02-09"
    assert merged["as_of_date"] == "2026-02-09"


def test_apply_monetary_entry_keeps_none_when_no_previous_value(monkeypatch):
    entry = {
        "policy_name": "MLF利率",
        "current_value": None,
        "change_from_120d": None,
        "unit": "%",
        "date": "",
        "source": "占位",
        "note": "",
    }
    payload = {
        "policy_name": "MLF利率",
        "current_value": "2.0",
        "unit": "%",
        "date": "2026-01",
        "source": "TradingEconomics",
    }

    def _fake_hist(*args, **kwargs):
        return {"change_from_120d": None, "reason": "no_previous_value"}

    monkeypatch.setattr(injector, "_calc_change_from_event_history", _fake_hist)
    updated = injector._apply_monetary_entry("mlf", entry, payload, "2026-02-06")
    assert updated is True
    assert entry["current_value"] == pytest.approx(2.0)
    assert entry["change_from_120d"] is None
    assert "reason=no_previous_value" in str(entry.get("note") or "")


def test_remove_top_missing_on_skip_keeps_stage3_unblocked():
    market_data = {"missing_items": ["bdi", "cpi"]}
    entry = {
        "current_value": 2233.0,
        "is_estimated": True,
        "source_url": "https://www.tradingeconomics.com/commodity/baltic",
    }

    injector._remove_top_missing_on_skip(market_data, "bdi", entry)

    assert market_data["missing_items"] == ["cpi"]


def test_stock_index_merge_preserves_source_url_and_metadata():
    merged = injector._merge_stock_index_entry(
        {
            "symbol": "000300",
            "name": "沪深300",
            "current_price": None,
            "source": "placeholder",
        },
        {
            "symbol": "000300",
            "name": "沪深300",
            "current_price": 4200.5,
            "source": "manual",
            "source_url": "https://example.com/hs300",
            "is_estimated": True,
            "estimation_method": "manual_estimate",
            "metric_basis": "close",
            "confidence": "high",
        },
    )

    assert merged["source_url"] == "https://example.com/hs300"
    assert merged["is_estimated"] is True
    assert merged["estimation_method"] == "manual_estimate"
    assert merged["metric_basis"] == "close"
    assert merged["confidence"] == "high"


def test_stock_index_build_preserves_source_url_alias():
    built = injector._build_stock_index_entry(
        "000016",
        {
            "name": "上证50",
            "current_price": 2950.2,
            "source": "manual",
            "sourceUrl": "https://example.com/sse50",
        },
    )

    assert built["source_url"] == "https://example.com/sse50"


def test_coerce_stage2_results_uses_raw_result_url_when_extraction_lacks_source_url():
    converted = injector._coerce_stage2_results_to_schema(
        {
            "results": [
                {
                    "task": {"indicator_key": "GC=F", "unit": "$/oz"},
                    "extraction": {"value": "2650.5", "note": "stage2 snippet"},
                    "raw_results": [{"url": "https://example.com/gold"}],
                }
            ]
        }
    )

    row = converted["commodities"][0]
    assert row["source_url"] == "https://example.com/gold"
    assert "https://example.com/gold" in row["source"]


def test_merge_forex_entry_uses_prev_session_change_for_daily(monkeypatch):
    existing = {
        "pair": "USDCNY",
        "name": "USD/CNY在岸",
        "current_rate": 0.0,
        "daily_change": 0.0,
        "change_120d": 0.0,
        "trend": "待获取",
        "source": "占位",
    }
    payload = {"pair": "USDCNY", "current_rate": "6.9388", "source": "TradingEconomics"}

    def _fake_hist(*args, **kwargs):
        return {
            "change_5d": -1.98,
            "change_120d": -3.32,
            "reason_5d": None,
            "reason_120d": None,
            "base_5d_estimated": False,
            "base_120d_estimated": False,
        }

    def _fake_daily_hist(*args, **kwargs):
        return {
            "change_1d": -0.16,
            "reason_1d": None,
            "base_1d_estimated": False,
        }

    monkeypatch.setattr(injector, "_calc_change_from_trend_history", _fake_hist)
    monkeypatch.setattr(injector, "_calc_daily_change_from_trend_history", _fake_daily_hist)
    merged = injector._merge_forex_entry(existing, payload, is_manual=True)
    assert merged["daily_change"] == pytest.approx(-0.16)
    assert merged["change_120d"] == pytest.approx(-3.32)


def test_backfill_trend_changes_clears_no_previous_note_when_monetary_filled(monkeypatch):
    market_data = {
        "metadata": {"date": "2026-02-09"},
        "monetary_policy": {
            "reverse_repo": {
                "policy_name": "7天逆回购利率",
                "current_value": 1.4,
                "change_from_120d": None,
                "note": "央行公开市场；reason=no_previous_value；无前值可比",
                "is_estimated": False,
            }
        },
        "macro_indicators": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }

    def _fake_event_hist(*args, **kwargs):
        return {
            "change_from_120d": 0.0,
            "reason": None,
            "base_estimated": False,
        }

    monkeypatch.setattr(injector, "_calc_change_from_event_history", _fake_event_hist)
    stats = injector._backfill_trend_changes(market_data)

    entry = market_data["monetary_policy"]["reverse_repo"]
    assert stats["monetary_policy"] == 1
    assert entry["change_from_120d"] == pytest.approx(0.0)
    assert "reason=no_previous_value" not in str(entry.get("note") or "")
    assert "无前值可比" not in str(entry.get("note") or "")


def test_run_post_write_trend_backfill_persists_output_and_resets_issues(monkeypatch, tmp_path: Path):
    output_path = tmp_path / "out.json"
    market_data = {
        "metadata": {
            "date": "2026-02-09",
            "trend_backfill_issues": [
                {
                    "category": "monetary_policy",
                    "key": "reverse_repo",
                    "field": "change_from_120d",
                    "reason": "no_previous_value",
                }
            ],
        },
        "monetary_policy": {
            "reverse_repo": {
                "policy_name": "7天逆回购利率",
                "current_value": 1.4,
                "change_from_120d": None,
                "note": "reason=no_previous_value",
            }
        },
    }

    def _fake_backfill(payload):
        payload["monetary_policy"]["reverse_repo"]["change_from_120d"] = 0.0
        return {"monetary_policy": 1}

    monkeypatch.setattr(injector, "_backfill_trend_changes", _fake_backfill)
    monkeypatch.setattr(injector, "_refresh_stage2_gap_monitor", lambda payload: {"top_level": 0, "metadata": 0})
    monkeypatch.setattr(injector, "_refresh_stage2_notes", lambda metadata, gap: None)
    monkeypatch.setattr(injector, "_cleanup_metadata_missing", lambda metadata, payload: None)

    stats = injector._run_post_write_trend_backfill(market_data, output_path)
    saved = json.loads(output_path.read_text(encoding="utf-8"))

    assert stats["monetary_policy"] == 1
    assert market_data["metadata"]["trend_backfill_issues"] == []
    assert saved["monetary_policy"]["reverse_repo"]["change_from_120d"] == pytest.approx(0.0)


def test_is_missing_item_filled_requires_compare_and_non_estimated():
    market_data = {
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": None,
                "change_rate": None,
                "is_estimated": False,
            }
        },
        "bonds": [
            {
                "symbol": "CN10Y_CDB",
                "current_yield": 1.97,
                "is_estimated": True,
            }
        ],
    }
    assert injector._is_missing_item_filled(market_data, "macro_indicators", "industrial") is False
    assert injector._is_missing_item_filled(market_data, "bonds", "CN10Y_CDB") is True


def test_enforce_quality_blockers_marks_missing_items():
    market_data = {
        "metadata": {"missing_items": {}},
        "missing_items": [],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": None,
                "change_rate": None,
                "is_estimated": False,
            }
        },
        "monetary_policy": {
            "mlf": {
                "current_value": 2.0,
                "change_from_120d": 0.0,
                "is_estimated": True,
            }
        },
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }
    blockers = injector._enforce_quality_blockers(market_data)

    assert {"category": "macro_indicators", "key": "industrial", "reason": "missing_compare_values"} in blockers
    assert {"category": "monetary_policy", "key": "mlf", "reason": "estimated_not_allowed"} in blockers
    metadata_missing = market_data["metadata"]["missing_items"]
    assert "macro_indicators" in metadata_missing
    assert "monetary_policy" in metadata_missing
    assert "industrial" in market_data["missing_items"]
    assert "mlf" in market_data["missing_items"]



def test_enforce_quality_blockers_marks_etf_window_missing():
    market_data = {
        "metadata": {"missing_items": {}},
        "missing_items": [],
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {
            "etf": {"recent_5d": None, "total_120d": -250.0, "source": "tavily+deepseek"},
        },
    }

    blockers = injector._enforce_quality_blockers(market_data)
    assert {"category": "fund_flow", "key": "etf", "reason": "fund_flow_window_missing"} in blockers
    assert "etf" in market_data["missing_items"]


def test_collect_gc_non_blocking_warnings_risk_and_anomaly():
    market_data = {
        "commodities": [{"symbol": "GC=F", "current_price": 5340.0}],
        "metadata": {},
    }
    websearch_raw = {
        "results": [
            {
                "task": {"indicator_key": "GC=F"},
                "extraction": {
                    "value": 4907.5,
                    "source_url": "https://guba.eastmoney.com/news,GCF,12345.html",
                },
            }
        ]
    }

    warnings = injector._collect_gc_non_blocking_warnings(market_data, websearch_raw)
    codes = {item.get("code") for item in warnings}
    assert "gc_f_source_risk" in codes
    assert "gc_f_price_anomaly" in codes


def test_sync_backfill_issues_to_logs_merges_non_blocking_warnings(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    market_data = {
        "metadata": {
            "date": "2026-03-05",
            "missing_items": {},
            "trend_backfill_issues": [],
            "non_blocking_warnings": [
                {
                    "code": "gc_f_source_risk",
                    "key": "GC=F",
                    "message": "GC=F 来源域名风险: guba.eastmoney.com",
                }
            ],
        },
        "missing_items": [],
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }

    injector._sync_backfill_issues_to_logs(market_data)
    obs = json.loads((tmp_path / "logs" / "runs" / "20260305" / "observability.json").read_text(encoding="utf-8"))
    warnings = obs.get("non_blocking_warnings", [])
    assert isinstance(warnings, list) and warnings
    assert warnings[0].get("code") == "gc_f_source_risk"
def test_apply_macro_entry_autofills_change_rate_from_previous_value():
    entry = {
        "indicator_name": "CPI同比",
        "current_value": None,
        "previous_value": None,
        "change_rate": None,
        "unit": "%",
        "date": "2026-02-09",
        "source": "占位",
        "note": "",
    }
    payload = {
        "indicator_name": "CPI同比",
        "current_value": "2.1",
        "previous_value": "1.9",
        "unit": "%",
        "source": "国家统计局",
    }

    updated = injector._apply_macro_entry("cpi", entry, payload, "2026-02-09")
    assert updated is True
    assert entry["current_value"] == pytest.approx(2.1)
    assert entry["previous_value"] == pytest.approx(1.9)
    assert entry["change_rate"] == pytest.approx(10.5263)
    assert "auto-backfilled change_rate% via (current-previous)/abs(previous)*100" in str(entry.get("note") or "")


def test_apply_macro_entry_backfills_previous_from_change_rate_percent(monkeypatch):
    entry = {
        "indicator_name": "CPI同比",
        "current_value": None,
        "previous_value": None,
        "change_rate": None,
        "unit": "%",
        "date": "2026-02-09",
        "source": "占位",
        "note": "",
    }
    payload = {
        "indicator_name": "CPI同比",
        "current_value": "2.1",
        "change_rate": "5.0",
        "unit": "%",
        "source": "国家统计局",
    }
    monkeypatch.setattr(
        injector,
        "_calc_prev_from_event_history",
        lambda *args, **kwargs: {"previous_value": None, "change_rate": None, "reason": "no_previous_value"},
    )

    updated = injector._apply_macro_entry("cpi", entry, payload, "2026-02-09")
    assert updated is True
    assert entry["current_value"] == pytest.approx(2.1)
    assert entry["previous_value"] == pytest.approx(2.0)
    assert entry["change_rate"] == pytest.approx(5.0)
    assert "auto-backfilled previous_value via current/(1+change_rate/100)" in str(entry.get("note") or "")


def test_apply_macro_entry_marks_reason_when_previous_is_zero():
    entry = {
        "indicator_name": "CPI同比",
        "current_value": None,
        "previous_value": None,
        "change_rate": None,
        "unit": "%",
        "date": "2026-02-09",
        "source": "占位",
        "note": "",
    }
    payload = {
        "indicator_name": "CPI同比",
        "current_value": "2.1",
        "previous_value": "0",
        "unit": "%",
        "source": "国家统计局",
    }

    updated = injector._apply_macro_entry("cpi", entry, payload, "2026-02-09")
    assert updated is True
    assert entry["current_value"] == pytest.approx(2.1)
    assert entry["previous_value"] == pytest.approx(0.0)
    assert entry["change_rate"] is None
    assert "reason=change_rate_pct_div_by_zero" in str(entry.get("note") or "")


def test_apply_macro_entry_skips_non_stale_existing_value():
    entry = {
        "indicator_name": "CPI同比",
        "current_value": 2.1,
        "previous_value": 1.9,
        "change_rate": 10.5,
        "unit": "%",
        "date": "2026-01",
        "source": "TuShare cn_cpi",
        "is_stale": False,
        "expected_period": "2026-01",
        "stale_reason": None,
        "note": "",
    }
    payload = {
        "indicator_name": "CPI同比",
        "current_value": "2.0",
        "previous_value": "1.8",
        "change_rate": "11.1",
        "unit": "%",
        "date": "2026-01",
        "source": "国家统计局",
    }
    updated = injector._apply_macro_entry("cpi", entry, payload, "2026-02-27")
    assert updated is False
    assert entry["current_value"] == pytest.approx(2.1)
    assert entry["is_stale"] is False


def test_apply_macro_entry_overrides_stale_and_clears_flag():
    entry = {
        "indicator_name": "CPI同比",
        "current_value": 0.8,
        "previous_value": 0.6,
        "change_rate": 0.2,
        "unit": "%",
        "date": "2025-12",
        "source": "TuShare cn_cpi",
        "is_stale": True,
        "expected_period": "2026-01",
        "stale_reason": "actual_period_behind_expected",
        "note": "",
    }
    payload = {
        "indicator_name": "CPI同比",
        "current_value": "0.2",
        "previous_value": "0.8",
        "change_rate": "-0.6",
        "unit": "%",
        "date": "2026-01",
        "source": "国家统计局",
    }
    updated = injector._apply_macro_entry("cpi", entry, payload, "2026-02-27", override_stale=True)
    assert updated is True
    assert entry["current_value"] == pytest.approx(0.2)
    assert entry["date"] == "2026-01"
    assert entry["is_stale"] is False
    assert entry["stale_reason"] is None


def test_rewrite_gap_monitor_after_injection_clears_stale_manual_required(tmp_path: Path):
    gap_path = tmp_path / "gap_monitor_20260209.json"
    gap_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-02-09T00:00:00",
                "manual_required": ["northbound", "etf"],
                "pending_tasks": ["northbound"],
                "data_quality_issues": [
                    {
                        "category": "macro_indicators",
                        "key": "industrial",
                        "field": "previous_value",
                        "reason": "no_previous_value",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    market_data = {
        "metadata": {"date": "2026-02-09", "missing_items": {}, "trend_backfill_issues": []},
        "missing_items": [],
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }

    injector._rewrite_gap_monitor_after_injection(
        market_data,
        gap_monitor_path=gap_path,
        extra_issues=[],
    )
    payload = json.loads(gap_path.read_text(encoding="utf-8"))
    assert payload.get("manual_required", []) == []
    assert payload.get("pending_tasks", []) == []
    assert payload.get("data_quality_issues", []) == []


def test_sync_backfill_issues_to_logs_rewrites_gap_monitor_even_without_issues(tmp_path: Path):
    gap_path = tmp_path / "gap_monitor_20260209.json"
    gap_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-02-09T00:00:00",
                "manual_required": ["USDCNY"],
                "data_quality_issues": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    market_data = {
        "metadata": {"date": "2026-02-09", "missing_items": {}, "trend_backfill_issues": []},
        "missing_items": [],
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }

    injector._sync_backfill_issues_to_logs(market_data, gap_monitor_path=gap_path)
    payload = json.loads(gap_path.read_text(encoding="utf-8"))
    assert payload.get("manual_required", []) == []
    assert payload.get("pending_tasks", []) == []


def _stub_trend_writes(monkeypatch):
    monkeypatch.setattr(injector, "write_from_market_data", lambda *args, **kwargs: 0)
    monkeypatch.setattr(injector, "_backfill_trend_changes", lambda *args, **kwargs: {})
    monkeypatch.setattr(injector, "_run_post_write_trend_backfill", lambda *args, **kwargs: {})


def _write_json(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_manual_official_mlf_payload_is_not_estimated(tmp_path: Path, monkeypatch):
    _stub_trend_writes(monkeypatch)
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "data" / "runs" / "20260428"
    run_dir.mkdir(parents=True)
    market_path = run_dir / "market_data_stage2.json"
    manual_path = run_dir / "websearch_results_manual.json"
    output_path = run_dir / "market_data_complete.json"

    _write_json(
        market_path,
        {
            "metadata": {"date": "2026-04-28", "missing_items": {"monetary_policy": [{"key": "mlf"}]}},
            "missing_items": ["mlf"],
            "macro_indicators": {},
            "monetary_policy": {
                "mlf": {
                    "policy_name": "MLF利率",
                    "current_value": None,
                    "change_from_120d": None,
                    "unit": "%",
                    "date": "",
                    "source": "placeholder",
                    "note": "",
                    "is_estimated": True,
                }
            },
            "bonds": [],
            "forex": [],
            "commodities": [],
            "stock_indices": [],
            "fund_flow": {},
        },
    )
    _write_json(
        manual_path,
        {
            "monetary_policy": {
                "mlf": {
                    "policy_name": "MLF利率",
                    "current_value": 2.0,
                    "change_from_120d": 0.0,
                    "unit": "%",
                    "date": "2026-04-25",
                    "source": "中国人民银行",
                    "source_url": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/index.html",
                    "note": "中国人民银行官方发布",
                    "is_estimated": True,
                }
            }
        },
    )

    injector.inject_websearch_results(market_path, manual_path, output_path)

    output = json.loads(output_path.read_text(encoding="utf-8"))
    entry = output["monetary_policy"]["mlf"]
    assert entry["is_estimated"] is False
    assert "manual_official_not_estimated" in entry["note"]
    assert "mlf" not in output.get("missing_items", [])
    assert not any(
        item.get("category") == "monetary_policy" and item.get("key") == "mlf"
        for item in output["metadata"].get("quality_blockers", [])
    )


def test_manual_official_usdcny_payload_is_not_estimated(tmp_path: Path, monkeypatch):
    _stub_trend_writes(monkeypatch)
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "data" / "runs" / "20260428"
    run_dir.mkdir(parents=True)
    market_path = run_dir / "market_data_stage2.json"
    manual_path = run_dir / "websearch_results_manual.json"
    output_path = run_dir / "market_data_complete.json"

    _write_json(
        market_path,
        {
            "metadata": {"date": "2026-04-28", "missing_items": {"forex": [{"key": "USDCNY"}]}},
            "missing_items": ["USDCNY"],
            "macro_indicators": {},
            "monetary_policy": {},
            "bonds": [],
            "forex": [
                {
                    "pair": "USDCNY",
                    "name": "USD/CNY在岸",
                    "current_rate": None,
                    "daily_change": None,
                    "change_120d": None,
                    "trend": "待WebSearch补充",
                    "source": "placeholder",
                    "is_estimated": True,
                }
            ],
            "commodities": [],
            "stock_indices": [],
            "fund_flow": {},
        },
    )
    _write_json(
        manual_path,
        {
            "forex": [
                {
                    "pair": "USDCNY",
                    "name": "USD/CNY在岸",
                    "current_rate": 7.2472,
                    "daily_change": 0.01,
                    "change_120d": 1.2,
                    "source": "中国外汇交易中心 CFETS",
                    "source_url": "https://www.chinamoney.com.cn/chinese/bkccpr/",
                    "note": "中国货币网官方发布",
                    "is_estimated": True,
                }
            ]
        },
    )

    injector.inject_websearch_results(market_path, manual_path, output_path)

    output = json.loads(output_path.read_text(encoding="utf-8"))
    entry = output["forex"][0]
    assert entry["pair"] == "USDCNY"
    assert entry["is_estimated"] is False
    assert "manual_official_not_estimated" in entry["note"]
    assert "USDCNY" not in output.get("missing_items", [])
    assert not any(
        item.get("category") == "forex" and item.get("key") == "USDCNY"
        for item in output["metadata"].get("quality_blockers", [])
    )


def test_manual_etf_eastmoney_estimate_stays_estimated_and_blocked(tmp_path: Path, monkeypatch):
    _stub_trend_writes(monkeypatch)
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "data" / "runs" / "20260428"
    run_dir.mkdir(parents=True)
    market_path = run_dir / "market_data_stage2.json"
    manual_path = run_dir / "websearch_results_manual.json"
    output_path = run_dir / "market_data_complete.json"

    _write_json(
        market_path,
        {
            "metadata": {"date": "2026-04-28", "missing_items": {"fund_flow": [{"key": "etf"}]}},
            "missing_items": ["etf"],
            "macro_indicators": {},
            "monetary_policy": {},
            "bonds": [],
            "forex": [],
            "commodities": [],
            "stock_indices": [],
            "fund_flow": {
                "etf": {
                    "type": "etf",
                    "recent_5d": None,
                    "total_120d": None,
                    "trend": "待WebSearch补充",
                    "source": "placeholder",
                    "is_estimated": True,
                }
            },
        },
    )
    _write_json(
        manual_path,
        {
            "fund_flow": {
                "etf": {
                    "recent_5d": 86.5,
                    "total_120d": 1250.0,
                    "trend": "流入",
                    "source": "东方财富",
                    "source_url": "https://data.eastmoney.com/etf/",
                    "note": "Eastmoney manual estimate",
                    "is_estimated": True,
                }
            }
        },
    )

    injector.inject_websearch_results(market_path, manual_path, output_path)

    output = json.loads(output_path.read_text(encoding="utf-8"))
    entry = output["fund_flow"]["etf"]
    assert entry["is_estimated"] is True
    assert "manual_official_not_estimated" not in str(entry.get("note") or "")
    assert {
        "category": "fund_flow",
        "key": "etf",
        "reason": "estimated_not_allowed",
    } in output["metadata"].get("quality_blockers", [])


def test_stage25_writes_unified_quality_state_files(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "data" / "runs" / "20260427"
    run_dir.mkdir(parents=True)
    market_path = run_dir / "market_data_stage2.json"
    manual_path = run_dir / "websearch_results_manual.json"
    output_path = run_dir / "market_data_complete.json"
    gap_path = run_dir / "gap_monitor.json"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "date": "2026-04-27",
                    "missing_items": {"macro_indicators": [{"key": "industrial", "reason": "old"}]},
                    "quality_blockers": [{"category": "macro_indicators", "key": "industrial", "reason": "old"}],
                },
                "missing_items": ["industrial"],
                "macro_indicators": {
                    "industrial": {
                        "indicator_name": "industrial",
                        "current_value": None,
                        "previous_value": None,
                        "change_rate": None,
                        "source": "placeholder",
                    }
                },
                "monetary_policy": {},
                "bonds": [],
                "forex": [],
                "commodities": [],
                "stock_indices": [],
                "fund_flow": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "macro_indicators": {
                    "industrial": {
                        "indicator_name": "industrial",
                        "current_value": 5.8,
                        "previous_value": 5.2,
                        "change_rate": 11.54,
                        "unit": "%",
                        "date": "2026-03",
                        "source": "manual",
                        "source_url": "https://example.com/industrial",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        backfill_trend=False,
        disable_trend_history_write=True,
        gap_monitor_path=gap_path,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["metadata"].get("missing_items") in ({}, None)
    assert output.get("missing_items") == []
    assert output["metadata"].get("quality_blockers") == []

    gap_payload = json.loads(gap_path.read_text(encoding="utf-8"))
    assert gap_payload.get("manual_required", []) == []
    assert gap_payload.get("pending_tasks", []) == []
    assert gap_payload.get("quality_blockers", []) == []

    policy_payload = json.loads((run_dir / "policy_evaluation.json").read_text(encoding="utf-8"))
    assert policy_payload.get("block_stage3") is False


def test_stage25_preserves_manual_source_url_and_fund_flow_metric_basis(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "data" / "runs" / "20260427"
    run_dir.mkdir(parents=True)
    market_path = run_dir / "market_data_stage2.json"
    manual_path = run_dir / "websearch_results_manual.json"
    output_path = run_dir / "market_data_complete.json"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-04-27", "missing_items": {}},
                "missing_items": [],
                "macro_indicators": {},
                "monetary_policy": {},
                "bonds": [],
                "forex": [],
                "commodities": [
                    {"symbol": "GC=F", "name": "COMEX黄金", "current_price": None, "source": "placeholder"}
                ],
                "stock_indices": [],
                "fund_flow": {
                    "northbound": {
                        "type": "northbound",
                        "recent_5d": None,
                        "total_120d": None,
                        "trend": "待获取",
                        "source": "placeholder",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "commodities": [
                    {
                        "symbol": "GC=F",
                        "name": "COMEX黄金",
                        "current_price": 3350.5,
                        "unit": "$/oz",
                        "source": "manual",
                        "source_url": "https://example.com/gold",
                    }
                ],
                "fund_flow": {
                    "northbound": {
                        "recent_5d": 85.6,
                        "total_120d": 1250.0,
                        "trend": "流入",
                        "source": "manual",
                        "source_url": "https://example.com/northbound",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        backfill_trend=False,
        disable_trend_history_write=True,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["commodities"][0]["source_url"] == "https://example.com/gold"
    assert output["fund_flow"]["northbound"]["source_url"] == "https://example.com/northbound"
    assert output["fund_flow"]["northbound"]["metric_basis"] == "net_flow_sum"


def test_merge_commodity_entry_does_not_put_5d_into_daily_or_120d_into_ytd(monkeypatch):
    existing = {
        "symbol": "GC=F",
        "name": "COMEX黄金",
        "current_price": None,
        "daily_change": None,
        "ytd_change": None,
        "source": "占位",
    }
    payload = {
        "symbol": "GC=F",
        "current_price": "3450.0",
        "source": "manual https://example.com/gold",
        "source_url": "https://example.com/gold",
    }

    monkeypatch.setattr(
        injector,
        "_calc_change_from_trend_history",
        lambda *args, **kwargs: {
            "change_5d": 1.5,
            "change_120d": 12.3,
            "reason_5d": None,
            "reason_120d": None,
            "base_5d_estimated": False,
            "base_120d_estimated": False,
        },
    )

    merged = injector._merge_commodity_entry(existing, payload, is_manual=True)

    assert merged["daily_change"] is None
    assert merged["ytd_change"] is None
    assert merged["change_120d"] == pytest.approx(12.3)
    assert merged["change_120d_basis"] == "trend_history"
    assert "daily_change_basis" not in merged
    assert "ytd_change_basis" not in merged


def test_merge_commodity_entry_preserves_payload_change_120d_and_source_url(monkeypatch):
    existing = {
        "symbol": "GC=F",
        "name": "COMEX黄金",
        "current_price": None,
        "daily_change": None,
        "ytd_change": None,
        "source": "占位",
    }
    payload = {
        "symbol": "GC=F",
        "current_price": "3450.0",
        "change_120d": "12.3",
        "source": "manual https://example.com/gold",
        "source_url": "https://example.com/gold",
    }

    monkeypatch.setattr(
        injector,
        "_calc_change_from_trend_history",
        lambda *args, **kwargs: {
            "change_5d": 1.5,
            "change_120d": None,
            "reason_5d": None,
            "reason_120d": "trend_history_missing",
            "base_5d_estimated": False,
            "base_120d_estimated": False,
        },
    )

    merged = injector._merge_commodity_entry(existing, payload, is_manual=True)

    assert merged["change_120d"] == pytest.approx(12.3)
    assert merged["change_120d_basis"] == "websearch_manual"
    assert merged["source_url"] == "https://example.com/gold"


def test_commodity_data_preserves_120d_fields_and_source_url():
    commodity = CommodityData(
        symbol="GC=F",
        name="COMEX黄金",
        current_price=3450.0,
        unit="$/oz",
        daily_change=None,
        ytd_change=None,
        change_120d=12.3,
        change_120d_basis="websearch_manual",
        trend="上涨",
        source="manual",
        source_url="https://example.com/gold",
        timestamp="2026-04-27",
    )

    payload = commodity.model_dump()
    assert payload["change_120d"] == pytest.approx(12.3)
    assert payload["change_120d_basis"] == "websearch_manual"
    assert payload["source_url"] == "https://example.com/gold"


def test_build_forex_entry_keeps_unknown_changes_as_none(monkeypatch):
    monkeypatch.setattr(
        injector,
        "_calc_change_from_trend_history",
        lambda *args, **kwargs: {"change_120d": None, "reason_120d": "trend_history_missing"},
    )
    monkeypatch.setattr(
        injector,
        "_calc_daily_change_from_trend_history",
        lambda *args, **kwargs: {"change_1d": None, "reason_1d": "trend_history_missing"},
    )

    entry = injector._build_forex_entry(
        {"pair": "USDCNY", "current_rate": "7.1", "source": "manual https://example.com/fx", "source_url": "https://example.com/fx"}
    )

    assert entry["daily_change"] is None
    assert entry["change_120d"] is None
