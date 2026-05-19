#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage3 前置校验单元测试：
- 数据完整性达到阈值且无缺口应通过
- 缺口或完整性不足应直接抛 RuntimeError
"""

import pytest
from datetime import datetime
from pathlib import Path
import asyncio
import json

import scripts.stage3_pring_analyzer as s3


def test_require_data_completeness_pass():
    payload = {
        "metadata": {"data_completeness": 0.85},
        "missing_items": [],
    }
    # 不应抛异常
    s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_fail_on_missing():
    payload = {
        "metadata": {"data_completeness": 0.85},
        "missing_items": ["cpi", {"key": "pmi_new_orders"}],
        "macro_indicators": {
            "industrial": {
                "current_value": None,
                "previous_value": None,
                "change_rate": None,
                "is_estimated": False,
            }
        },
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_ignores_stale_metadata_missing_when_live_state_clean():
    payload = {
        "metadata": {
            "data_completeness": 0.95,
            "missing_items": {"macro_indicators": ["cpi"]},
        },
        "missing_items": ["industrial"],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": 5.0,
                "change_rate": 4.0,
                "source_url": "https://example.com/industrial",
                "is_estimated": False,
            }
        },
    }

    s3._require_data_completeness(payload, 0.8, allow_estimated=True)


def test_require_data_completeness_blocks_manual_commodity_without_source_url():
    payload = {
        "metadata": {"data_completeness": 0.95},
        "missing_items": [],
        "commodities": [
            {
                "symbol": "GC=F",
                "name": "COMEX gold",
                "current_price": 3450.0,
                "source": "websearch_manual",
                "is_estimated": False,
            }
        ],
    }

    with pytest.raises(RuntimeError) as exc:
        s3._require_data_completeness(payload, 0.8)
    assert "missing_source_url" in str(exc.value)


def test_require_data_completeness_does_not_skip_fund_flow_missing_source_url():
    payload = {
        "metadata": {"data_completeness": 0.95},
        "missing_items": [],
        "fund_flow": {
            "northbound": {
                "recent_5d": 12.3,
                "total_120d": 456.7,
                "trend": "inflow",
                "source": "websearch_manual",
                "is_estimated": False,
            }
        },
    }

    with pytest.raises(RuntimeError) as exc:
        s3._require_data_completeness(payload, 0.8, skip_fund_flow_check=True)
    assert "missing_source_url" in str(exc.value)


def test_require_data_completeness_blocks_estimated_fund_flow_even_with_allow_estimated():
    payload = {
        "metadata": {"data_completeness": 0.95},
        "missing_items": [],
        "fund_flow": {
            "etf": {
                "recent_5d": -50.0,
                "total_120d": -9000.0,
                "trend": "流出",
                "source": "websearch_manual",
                "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
                "metric_basis": "news_net_flow",
                "source_tier": "tier3",
                "window_evidence": "news_summary",
                "is_estimated": True,
            }
        },
    }

    with pytest.raises(RuntimeError) as exc:
        s3._require_data_completeness(payload, 0.8, allow_estimated=True)

    assert "fund_flow.etf" in str(exc.value)
    assert "estimated_not_allowed" in str(exc.value)


def test_require_data_completeness_fail_on_low_score():
    payload = {
        "metadata": {"data_completeness": 0.5},
        "missing_items": [],
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_allows_cn10y_cdb_estimated():
    payload = {
        "metadata": {"data_completeness": 0.9},
        "missing_items": [],
        "bonds": [
            {"symbol": "CN10Y_CDB", "current_yield": 1.97, "is_estimated": True},
        ],
    }
    s3._require_data_completeness(payload, 0.8, allow_estimated=False)


def test_require_data_completeness_fail_on_non_allowlisted_estimated():
    payload = {
        "metadata": {"data_completeness": 0.9},
        "missing_items": [],
        "bonds": [
            {"symbol": "US10Y", "current_yield": 4.18, "is_estimated": True},
        ],
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8, allow_estimated=False)


def test_require_data_completeness_allows_bdi_when_trusted():
    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        "metadata": {"data_completeness": 0.9},
        "missing_items": [],
        "macro_indicators": {
            "bdi": {
                "current_value": 2233.0,
                "previous_value": 2190.0,
                "change_rate": 1.96,
                "unit": "points",
                "date": today,
                "source_url": "https://www.tradingeconomics.com/commodity/baltic",
                "is_estimated": True,
            }
        },
    }
    s3._require_data_completeness(payload, 0.8, allow_estimated=False)


def test_require_data_completeness_blocks_bdi_when_untrusted():
    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        "metadata": {"data_completeness": 0.9},
        "missing_items": [],
        "macro_indicators": {
            "bdi": {
                "current_value": 2233.0,
                "unit": "points",
                "date": today,
                "source_url": "https://example.com/bdi",
                "is_estimated": True,
            }
        },
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8, allow_estimated=False)

def test_require_data_completeness_fail_on_missing_compare_values():
    payload = {
        "metadata": {"data_completeness": 0.9},
        "missing_items": [],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": None,
                "change_rate": None,
                "is_estimated": False,
            }
        },
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_fail_on_stale_critical_items():
    payload = {
        "metadata": {"data_completeness": 0.9},
        "missing_items": [],
        "macro_indicators": {
            "cpi": {
                "current_value": 0.2,
                "previous_value": 0.8,
                "change_rate": -0.6,
                "is_estimated": False,
                "is_stale": True,
                "date": "2025-12",
                "expected_period": "2026-01",
                "stale_reason": "actual_period_behind_expected",
            }
        },
    }
    with pytest.raises(RuntimeError) as exc:
        s3._require_data_completeness(payload, 0.8, block_on_stale=True, critical_stale_keys=["cpi"])
    assert "expected=2026-01" in str(exc.value)


def test_resolve_gap_monitor_prefers_dated_file(tmp_path: Path, monkeypatch):
    run_dir = tmp_path / "data" / "runs" / "20260209"
    run_dir.mkdir(parents=True, exist_ok=True)
    dated = run_dir / "gap_monitor.json"
    explicit = tmp_path / "custom_gap.json"
    dated.write_text('{"manual_required": []}', encoding="utf-8")
    explicit.write_text('{"manual_required": ["USDCNY"]}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    payload = {"metadata": {"date": "2026-02-09"}}
    resolved = s3._resolve_gap_monitor_path(payload, explicit_gap_path=explicit)
    assert resolved == Path("data/runs/20260209/gap_monitor.json")


def test_resolve_gap_monitor_uses_explicit_when_dated_missing(tmp_path: Path, monkeypatch):
    explicit = tmp_path / "custom_gap.json"
    explicit.write_text('{"manual_required": []}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    payload = {"metadata": {"date": "2026-02-09"}}
    resolved = s3._resolve_gap_monitor_path(payload, explicit_gap_path=explicit)
    assert resolved == explicit


def test_run_analysis_reports_all_blockers_once(tmp_path: Path, monkeypatch):
    market_payload = {
        "metadata": {
            "date": "2026-02-09",
            "data_completeness": 0.5,
            "ai_websearch_enhanced": False,
        },
        "missing_items": ["cpi"],
        "macro_indicators": {
            "cpi": {
                "current_value": None,
                "previous_value": None,
                "change_rate": None,
                "is_estimated": False,
            }
        },
    }
    run_dir = tmp_path / "data" / "runs" / "20260209"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "policy_evaluation.json").write_text(
        json.dumps({"block_stage3": True, "redlist": ["mlf"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "gap_monitor.json").write_text(
        json.dumps({"manual_required": ["cpi"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "pring.json"
    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            s3._run_analysis(
                market_path=market_path,
                output_path=output_path,
                allow_fallback=False,
                skip_gap_check=False,
            )
        )
    msg = str(exc.value)
    assert "completeness:" in msg
    assert "unified_quality:" in msg
    assert "gap_monitor(" in msg
    assert "stage2:" in msg


def test_run_analysis_does_not_block_on_stale_policy_file_when_live_state_clean(tmp_path: Path, monkeypatch):
    market_payload = {
        "metadata": {
            "date": "2026-02-09",
            "data_completeness": 1.0,
            "ai_websearch_enhanced": True,
        },
        "missing_items": ["industrial"],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": 5.0,
                "change_rate": 4.0,
                "source_url": "https://example.com/industrial",
                "is_estimated": False,
            }
        },
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }
    run_dir = tmp_path / "data" / "runs" / "20260209"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "policy_evaluation.json").write_text(
        json.dumps({"block_stage3": True, "redlist": ["industrial"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "gap_monitor.json").write_text(
        json.dumps({"manual_required": [], "pending_tasks": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "pring.json"
    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")

    class DummyContract:
        def __init__(self, **payload):
            self.metadata = payload.get("metadata", {})
            self.macro_indicators = payload.get("macro_indicators", {})
            self.monetary_policy = payload.get("monetary_policy", {})

    class DummyAnalyzer:
        def __init__(self, *args, **kwargs):
            pass

        async def analyze_pring_stage(self, days):
            return {"stage": "Expansion", "confidence": 0.9}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(s3, "MarketDataContract", DummyContract)
    monkeypatch.setattr(s3, "PringAnalyzer", DummyAnalyzer)
    monkeypatch.setattr(s3, "get_manager", lambda: object())

    result = asyncio.run(
        s3._run_analysis(
            market_path=market_path,
            output_path=output_path,
            allow_fallback=False,
            skip_gap_check=False,
        )
    )

    assert result["metadata"]["non_blocking_warnings"][0]["code"] == "policy_file_diagnostic_only"
    assert output_path.exists()


def test_run_analysis_blocks_unresolved_policy_redlist_missing_from_payload(tmp_path: Path, monkeypatch):
    market_payload = {
        "metadata": {
            "date": "2026-02-09",
            "data_completeness": 1.0,
            "ai_websearch_enhanced": True,
            "missing_items": {"monetary_policy": ["mlf"]},
        },
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }
    run_dir = tmp_path / "data" / "runs" / "20260209"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "policy_evaluation.json").write_text(
        json.dumps({"block_stage3": True, "redlist": ["mlf"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "gap_monitor.json").write_text(
        json.dumps({"manual_required": [], "pending_tasks": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "pring.json"
    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            s3._run_analysis(
                market_path=market_path,
                output_path=output_path,
                allow_fallback=False,
                skip_gap_check=False,
            )
        )

    msg = str(exc.value)
    assert "policy:" in msg
    assert "mlf" in msg


def test_run_analysis_blocks_category_specific_policy_redlist_missing_from_payload(tmp_path: Path, monkeypatch):
    market_payload = {
        "metadata": {
            "date": "2026-02-09",
            "data_completeness": 1.0,
            "ai_websearch_enhanced": True,
        },
        "macro_indicators": {
            "mlf": {
                "current_value": 2.0,
                "previous_value": 2.0,
                "change_rate": 0.0,
                "source_url": "https://example.com/macro-mlf",
                "is_estimated": False,
            }
        },
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }
    run_dir = tmp_path / "data" / "runs" / "20260209"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "policy_evaluation.json").write_text(
        json.dumps(
            {"block_stage3": True, "redlist": [{"category": "monetary_policy", "key": "mlf"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "gap_monitor.json").write_text(
        json.dumps({"manual_required": [], "pending_tasks": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "pring.json"
    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            s3._run_analysis(
                market_path=market_path,
                output_path=output_path,
                allow_fallback=False,
                skip_gap_check=False,
            )
        )

    msg = str(exc.value)
    assert "policy:" in msg
    assert "monetary_policy.mlf" in msg


def test_run_analysis_blocks_gap_monitor_missing_item_absent_from_payload(tmp_path: Path, monkeypatch):
    market_payload = {
        "metadata": {
            "date": "2026-02-09",
            "data_completeness": 1.0,
            "ai_websearch_enhanced": True,
        },
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }
    run_dir = tmp_path / "data" / "runs" / "20260209"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "gap_monitor.json").write_text(
        json.dumps({"manual_required": ["mlf"], "pending_tasks": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "pring.json"
    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            s3._run_analysis(
                market_path=market_path,
                output_path=output_path,
                allow_fallback=False,
                skip_gap_check=False,
            )
        )

    msg = str(exc.value)
    assert "gap_monitor" in msg
    assert "mlf" in msg


def test_run_analysis_does_not_block_on_stale_gap_monitor_when_live_state_clean(tmp_path: Path, monkeypatch):
    market_payload = {
        "metadata": {
            "date": "2026-02-09",
            "data_completeness": 1.0,
            "ai_websearch_enhanced": True,
        },
        "missing_items": ["industrial"],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": 5.0,
                "change_rate": 4.0,
                "source_url": "https://example.com/industrial",
                "is_estimated": False,
            }
        },
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }
    run_dir = tmp_path / "data" / "runs" / "20260209"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "gap_monitor.json").write_text(
        json.dumps(
            {"manual_required": ["industrial"], "pending_tasks": ["industrial"]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "pring.json"
    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")

    class DummyContract:
        def __init__(self, **payload):
            self.metadata = payload.get("metadata", {})
            self.macro_indicators = payload.get("macro_indicators", {})
            self.monetary_policy = payload.get("monetary_policy", {})

    class DummyAnalyzer:
        def __init__(self, *args, **kwargs):
            pass

        async def analyze_pring_stage(self, days):
            return {"stage": "Expansion", "confidence": 0.9}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(s3, "MarketDataContract", DummyContract)
    monkeypatch.setattr(s3, "PringAnalyzer", DummyAnalyzer)
    monkeypatch.setattr(s3, "get_manager", lambda: object())

    result = asyncio.run(
        s3._run_analysis(
            market_path=market_path,
            output_path=output_path,
            allow_fallback=False,
            skip_gap_check=False,
        )
    )

    warning_codes = [
        row.get("code")
        for row in result["metadata"].get("non_blocking_warnings", [])
    ]
    assert "gap_monitor_file_diagnostic_only" in warning_codes
    assert output_path.exists()
