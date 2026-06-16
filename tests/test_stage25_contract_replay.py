#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import scripts.stage2_5_injector as injector
from datasource.engines.stage2_5 import core, entry_mergers, gap_sync, trend_backfill
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state


@pytest.fixture(autouse=True)
def freeze_stage25_datetime(monkeypatch):
    fixed_now = datetime(2026, 6, 13, 0, 0, 0)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return fixed_now.replace(tzinfo=tz)
            return fixed_now

    monkeypatch.setattr(injector, "datetime", FixedDatetime)
    monkeypatch.setattr(core, "datetime", FixedDatetime)
    monkeypatch.setattr(entry_mergers, "datetime", FixedDatetime)
    monkeypatch.setattr(gap_sync, "datetime", FixedDatetime)
    monkeypatch.setattr(trend_backfill, "datetime", FixedDatetime)


def test_stage25_refreshes_trend_history_gap_from_custom_base_dir(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    market_path = tmp_path / "market_data_stage2.json"
    manual_path = tmp_path / "websearch_results_manual.json"
    output_path = tmp_path / "market_data_complete.json"
    trend_base = tmp_path / "isolated_trend_history" / "min"
    snapshot_path = tmp_path / "data" / "runs" / "20260427" / "trend_history_gap.json"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-04-27", "data_completeness": 1.0},
                "missing_items": [],
                "monetary_policy": {},
                "macro_indicators": {},
                "fund_flow": {},
                "commodities": [],
                "forex": [
                    {
                        "pair": "USDCNY",
                        "name": "USD/CNY",
                        "current_rate": 7.12,
                        "source": "manual https://example.com/usdcny",
                        "source_url": "https://example.com/usdcny",
                    }
                ],
                "bonds": [],
                "stock_indices": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        backfill_trend=False,
        gap_monitor_path=tmp_path / "gap_monitor.json",
        trend_history_base_dir=trend_base,
    )

    assert snapshot_path.exists()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["date"] == "2026-04-27"
    assert any(
        item["category"] == "forex" and item["symbol"] == "USDCNY"
        for item in snapshot["series"]["quality"]
    )
    assert not (tmp_path / "data" / "trend_history" / "min").exists()


def test_stage25_outputs_are_accepted_by_unified_quality_state(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "data" / "runs" / "20260427"
    market_path = tmp_path / "market_data_stage2.json"
    manual_path = tmp_path / "websearch_results_manual.json"
    output_path = tmp_path / "market_data_complete.json"
    gap_monitor_path = run_dir / "gap_monitor.json"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "date": "2026-04-27",
                    "data_completeness": 0.25,
                    "ai_websearch_enhanced": False,
                    "missing_items": {
                        "macro_indicators": [{"key": "industrial"}],
                    },
                },
                "missing_items": ["industrial"],
                "macro_indicators": {
                    "industrial": {
                        "indicator_name": "工业增加值",
                        "current_value": None,
                        "previous_value": None,
                        "change_rate": None,
                        "unit": "%",
                        "source": "待人工补数(Stage2 manual_required)",
                    }
                },
                "fund_flow": {
                    "northbound": {
                        "type": "northbound",
                        "recent_5d": None,
                        "total_120d": None,
                        "trend": "未知",
                        "source": "待人工补数(Stage2 manual_required)",
                    }
                },
                "commodities": [
                    {
                        "symbol": "GC=F",
                        "name": "COMEX黄金",
                        "current_price": None,
                        "unit": "$/oz",
                        "source": "待人工补数(Stage2 manual_required)",
                    }
                ],
                "monetary_policy": {},
                "forex": [],
                "bonds": [],
                "stock_indices": [],
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
                        "indicator_name": "工业增加值",
                        "current_value": 5.2,
                        "previous_value": 5.0,
                        "change_rate": 4.0,
                        "unit": "%",
                        "source": "websearch_manual https://example.com/industrial",
                        "source_url": "https://example.com/industrial",
                    }
                },
                "fund_flow": {
                    "northbound": {
                        "recent_5d": 85.6,
                        "total_120d": 1250.0,
                        "trend": "流入",
                        "source": "东方财富 沪深港通日频净买入序列求和",
                        "source_url": "https://data.eastmoney.com/hsgt/hsgtV2.html",
                        "metric_basis": "net_flow_sum",
                        "window_evidence": "direct_daily_series",
                    }
                },
                "commodities": [
                    {
                        "symbol": "GC=F",
                        "name": "COMEX黄金",
                        "current_price": 3450.5,
                        "unit": "$/oz",
                        "source": "websearch_manual https://example.com/gold",
                        "source_url": "https://example.com/gold",
                    }
                ],
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
        gap_monitor_path=gap_monitor_path,
        disable_trend_history_write=True,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    state = build_pipeline_quality_state(output)
    gap = json.loads(gap_monitor_path.read_text(encoding="utf-8"))
    metadata = output["metadata"]

    assert state["quality_blockers"] == []
    assert state["manual_required"] == []
    assert "manual_required" in gap
    assert gap["manual_required"] == []
    assert "pending_tasks" in gap
    assert gap["pending_tasks"] == []
    assert "quality_blockers" in gap
    assert gap["quality_blockers"] == []
    assert "data_quality_issues" in gap
    assert gap["data_quality_issues"] == []
    assert metadata["ai_websearch_enhanced"] is True
    assert "quality_blockers" in metadata
    assert metadata["quality_blockers"] == []
    assert "manual_required" in metadata
    assert metadata["manual_required"] == []
    assert output["macro_indicators"]["industrial"]["source_url"] == "https://example.com/industrial"
    assert output["fund_flow"]["northbound"]["source_url"] == "https://data.eastmoney.com/hsgt/hsgtV2.html"
    assert output["fund_flow"]["northbound"]["is_estimated"] is False
    assert output["commodities"][0]["source_url"] == "https://example.com/gold"


def test_stage25_replay_normalizes_legacy_monetary_key_and_disables_trend_write(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    market_path = tmp_path / "market_data_stage2.json"
    manual_path = tmp_path / "websearch_results_manual.json"
    output_path = tmp_path / "market_data_complete.json"
    trend_base = tmp_path / "isolated_trend_history" / "min"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "date": "2026-04-27",
                    "data_completeness": 0.5,
                    "missing_items": {"monetary_policy": [{"key": "mlf_rate"}]},
                },
                "missing_items": ["mlf_rate"],
                "monetary_policy": {
                    "mlf_rate": {
                        "policy_name": "MLF rate",
                        "current_value": None,
                        "change_from_120d": None,
                        "unit": "%",
                        "source": "placeholder",
                        "is_estimated": True,
                    }
                },
                "macro_indicators": {},
                "fund_flow": {},
                "commodities": [],
                "forex": [],
                "bonds": [],
                "stock_indices": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "monetary_policy": {
                    "mlf": {
                        "policy_name": "MLF rate",
                        "current_value": 2.0,
                        "change_from_120d": 0.1,
                        "unit": "%",
                        "date": "2026-04",
                        "source": "manual https://example.com/mlf",
                        "source_url": "https://example.com/mlf",
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
        gap_monitor_path=tmp_path / "gap_monitor.json",
        trend_history_base_dir=trend_base,
        disable_trend_history_write=True,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))

    assert "mlf" in output["monetary_policy"]
    assert "mlf_rate" not in output["monetary_policy"]
    assert output["monetary_policy"]["mlf"]["current_value"] == 2.0
    assert output["missing_items"] == []
    assert output["metadata"].get("missing_items") in (None, {})
    assert not trend_base.exists()
    assert not (tmp_path / "data" / "trend_history" / "min").exists()


def test_stage25_disable_trend_write_without_base_skips_real_trend_reads(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    market_path = tmp_path / "market_data_stage2.json"
    manual_path = tmp_path / "websearch_results_manual.json"
    output_path = tmp_path / "market_data_complete.json"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-04-27", "data_completeness": 0.8},
                "missing_items": ["US10Y"],
                "monetary_policy": {},
                "macro_indicators": {},
                "fund_flow": {},
                "commodities": [],
                "forex": [],
                "bonds": [
                    {
                        "symbol": "US10Y",
                        "name": "US 10Y",
                        "current_yield": None,
                        "change_5d_bp": None,
                        "change_120d_bp": None,
                    }
                ],
                "stock_indices": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "bonds": [
                    {
                        "symbol": "US10Y",
                        "name": "US 10Y",
                        "current_yield": 4.2,
                        "source": "manual https://example.com/us10y",
                        "source_url": "https://example.com/us10y",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def _fail_trend_read(*args, **kwargs):
        raise AssertionError("trend history read should be skipped")

    def _fail_backfill(*args, **kwargs):
        raise AssertionError("trend backfill should be skipped")

    monkeypatch.setattr(trend_backfill, "_calc_change_from_trend_history", _fail_trend_read)
    monkeypatch.setattr(trend_backfill, "_calc_daily_change_from_trend_history", _fail_trend_read)
    monkeypatch.setattr(trend_backfill, "_calc_change_from_event_history", _fail_trend_read)
    monkeypatch.setattr(trend_backfill, "_calc_prev_from_event_history", _fail_trend_read)
    monkeypatch.setattr(trend_backfill, "_backfill_trend_changes", _fail_backfill)

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        gap_monitor_path=tmp_path / "gap_monitor.json",
        disable_trend_history_write=True,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))

    assert output["bonds"][0]["current_yield"] == 4.2
    assert not (tmp_path / "data" / "trend_history" / "min").exists()


def test_stage25_20260519_like_fund_flow_extrapolations_do_not_clear_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "data" / "runs" / "20260519"
    run_dir.mkdir(parents=True)
    market_path = run_dir / "market_data_stage2.json"
    manual_path = run_dir / "websearch_results_manual.json"
    output_path = run_dir / "market_data_complete.json"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "date": "2026-05-19",
                    "data_completeness": 0.9,
                    "missing_items": {"fund_flow": [{"key": "etf"}]},
                },
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
                "fund_flow": {
                    "etf": {
                        "recent_5d": -50.0,
                        "total_120d": -9000.0,
                        "trend": "流出",
                        "source": "新浪财经 ETF季度报告 2026Q1 全市场 ETF 净赎回 9211 亿元",
                        "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
                        "metric_basis": "news_net_flow",
                        "is_estimated": False,
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
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    flow = output["fund_flow"]["etf"]
    blockers = output["metadata"].get("quality_blockers", [])

    assert flow["is_estimated"] is True
    assert flow["source_tier"] == "tier3"
    assert flow["window_evidence"] == "news_summary"
    assert any(
        item.get("category") == "fund_flow"
        and item.get("key") == "etf"
        and item.get("reason") == "estimated_not_allowed"
        for item in blockers
    )

    gap_payload = json.loads((run_dir / "gap_monitor.json").read_text(encoding="utf-8"))
    assert "etf" in gap_payload.get("manual_required", [])
    policy_payload = json.loads((run_dir / "policy_evaluation.json").read_text(encoding="utf-8"))
    assert policy_payload.get("block_stage3") is True
