#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""简单报告集成测试（样本 A/B/C）
A: 正常数据，阶段Ⅲ，conf高
B: fallback_used=True，pending_websearch 填充
C: legacy 风格（只校验生成成功）
"""
from pathlib import Path
import json
import pytest

from datasource.generators.simple_report import generate_report


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _base_market():
    return {
        "metadata": {"date": "2025-11-23", "data_completeness": 0.85},
        "stock_indices": [], "commodities": [], "bonds": [], "forex": [],
        "macro_indicators": {}, "monetary_policy": {}, "fund_flow": {}
    }


def test_sample_a_generate(tmp_path: Path):
    market = _base_market()
    pring = {
        "final_stage": "第Ⅲ阶段", "confidence": 0.65, "recommendation": "超配股票",
        "layer_1_inventory_cycle": {}, "layer_2_monetary_cycle": {}, "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [], "fallback_used": False
    }
    m = tmp_path / "m.json"; p = tmp_path / "p.json"; out = tmp_path / "o.md"
    _write_json(m, market); _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")
    assert "第Ⅲ阶段" in text
    assert "超配股票" in text


def test_sample_b_fallback_pending(tmp_path: Path):
    market = _base_market()
    pring = {
        "final_stage": "第Ⅱ阶段", "confidence": 0.4, "recommendation": "低配",
        "layer_1_inventory_cycle": {}, "layer_2_monetary_cycle": {}, "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": ["m2", "ppi"], "fallback_used": True
    }
    m = tmp_path / "m.json"; p = tmp_path / "p.json"; out = tmp_path / "o.md"
    _write_json(m, market); _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")
    assert "allow_fallback=TRUE" in text
    assert "m2" in text or "ppi" in text


def test_sample_c_legacy_ok(tmp_path: Path):
    market = _base_market()
    pring = {
        "final_stage": "第Ⅴ阶段", "confidence": 0.55, "recommendation": "超配大宗",
        "layer_1_inventory_cycle": {}, "layer_2_monetary_cycle": {}, "layer_3_pring_final": {},
        "metadata": {"analysis_method": "legacy", "min_completeness": 0.8},
        "pending_websearch": [], "fallback_used": False
    }
    m = tmp_path / "m.json"; p = tmp_path / "p.json"; out = tmp_path / "o.md"
    _write_json(m, market); _write_json(p, pring)
    generate_report(m, p, out)
    assert out.exists()
    assert "第Ⅴ阶段" in out.read_text(encoding="utf-8")


def test_report_shows_changes_even_when_trend_confidence_low(tmp_path: Path):
    market = _base_market()
    market["bonds"] = [
        {
            "symbol": "CN10Y",
            "name": "中国10年期国债",
            "current_yield": 1.83,
            "change_5d_bp": 0.0,
            "change_120d_bp": -12.3,
            "trend": "平稳",
            "source": "websearch_manual",
            "trend_history_confidence": "low",
        }
    ]
    pring = {
        "final_stage": "第Ⅲ阶段",
        "confidence": 0.61,
        "recommendation": "中性",
        "layer_1_inventory_cycle": {},
        "layer_2_monetary_cycle": {},
        "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [],
        "fallback_used": False,
    }
    m = tmp_path / "m.json"
    p = tmp_path / "p.json"
    out = tmp_path / "o.md"
    _write_json(m, market)
    _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")
    assert "| 中国10年期国债 | 1.83% | +0.0bp | -12.3bp |" in text
    assert "N/A（低置信度）" not in text


def test_report_monetary_no_previous_value_hides_zero_change(tmp_path: Path):
    market = _base_market()
    market["monetary_policy"] = {
        "mlf": {
            "policy_name": "MLF利率",
            "current_value": 2.0,
            "change_from_120d": 0.0,
            "unit": "%",
            "date": "2026-01",
            "source": "websearch_manual(TradingEconomics)",
            "note": "reason=no_previous_value",
            "is_estimated": False,
        }
    }
    pring = {
        "final_stage": "第Ⅲ阶段",
        "confidence": 0.61,
        "recommendation": "中性",
        "layer_1_inventory_cycle": {},
        "layer_2_monetary_cycle": {},
        "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [],
        "fallback_used": False,
    }
    m = tmp_path / "m.json"
    p = tmp_path / "p.json"
    out = tmp_path / "o.md"
    _write_json(m, market)
    _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")
    assert "| 中国MLF利率 | 2.00% | N/A（待 WebSearch） | % | 2026-01 |" in text


def test_bond_date_uses_latest_available_note_date(tmp_path: Path):
    market = _base_market()
    market["metadata"]["date"] = "2026-02-09"
    market["bonds"] = [
        {
            "symbol": "CN10Y",
            "name": "中国10年期国债",
            "current_yield": 1.80,
            "change_5d_bp": -1.7,
            "change_120d_bp": 1.3,
            "trend": "平稳",
            "source": "websearch_manual(TradingEconomics/Investing.com)",
            "note": "10Y yield eased to 1.80% on Feb 6, 2026, down 0.8bp",
        },
        {
            "symbol": "CN10Y_CDB",
            "name": "中国10年期国开债",
            "current_yield": 1.959,
            "change_5d_bp": 10.9,
            "change_120d_bp": -8.4,
            "trend": "上行",
            "source": "websearch_manual(东方财富)",
            "note": "10Y CDB yield was 1.959% on Feb 9, 2026",
        },
    ]
    pring = {
        "final_stage": "第Ⅲ阶段",
        "confidence": 0.61,
        "recommendation": "中性",
        "layer_1_inventory_cycle": {},
        "layer_2_monetary_cycle": {},
        "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [],
        "fallback_used": False,
    }
    m = tmp_path / "m.json"
    p = tmp_path / "p.json"
    out = tmp_path / "o.md"
    _write_json(m, market)
    _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")
    assert "| 中国10年期国债 | 1.80% | -1.7bp | +1.3bp | 平稳 | 2026-02-06 |" in text
    assert "| 中国10年期国开债 | 1.96% | +10.9bp | -8.4bp | 上行 | 2026-02-09 |" in text


def test_commodity_table_uses_120d_window_when_ytd_missing(tmp_path: Path):
    market = _base_market()
    market["commodities"] = [
        {
            "symbol": "GC=F",
            "name": "COMEX黄金",
            "current_price": 2650.5,
            "unit": "$/oz",
            "daily_change": None,
            "change_120d": 12.3,
            "ytd_change": None,
            "trend": "强势上涨",
            "source": "websearch_manual",
        }
    ]
    pring = {
        "final_stage": "第Ⅲ阶段",
        "confidence": 0.61,
        "recommendation": "中性",
        "layer_1_inventory_cycle": {},
        "layer_2_monetary_cycle": {},
        "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [],
        "fallback_used": False,
    }
    m = tmp_path / "m.json"
    p = tmp_path / "p.json"
    out = tmp_path / "o.md"
    _write_json(m, market)
    _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")
    assert "| 品种 | 最新报价 | 日涨跌 | 近120日变化 | 趋势方向 |" in text
    assert "| COMEX黄金 | 2650.50 $/oz | N/A | +12.30% | 强势上涨 |" in text
    assert "年内涨跌" not in text


def test_commodity_table_uses_120d_for_all_rows_when_any_ytd_missing(tmp_path: Path):
    market = _base_market()
    market["commodities"] = [
        {
            "symbol": "GC=F",
            "name": "Gold",
            "current_price": 2650.5,
            "unit": "$/oz",
            "daily_change": None,
            "change_120d": 3.3,
            "ytd_change": 8.8,
            "trend": "up",
            "source": "websearch_manual",
        },
        {
            "symbol": "CL=F",
            "name": "WTI Oil",
            "current_price": 70.25,
            "unit": "$/bbl",
            "daily_change": None,
            "change_120d": -4.5,
            "ytd_change": None,
            "trend": "down",
            "source": "websearch_manual",
        },
    ]
    pring = {
        "final_stage": "stage 3",
        "confidence": 0.61,
        "recommendation": "neutral",
        "layer_1_inventory_cycle": {},
        "layer_2_monetary_cycle": {},
        "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [],
        "fallback_used": False,
    }
    m = tmp_path / "m.json"
    p = tmp_path / "p.json"
    out = tmp_path / "o.md"
    _write_json(m, market)
    _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")
    commodity_header = next(line for line in text.splitlines() if line.startswith("| 品种 |"))

    assert "近120日变化" in commodity_header
    assert "年内涨跌" not in commodity_header
    assert "| Gold | 2650.50 $/oz | N/A | +3.30% | up |" in text
    assert "| WTI Oil | 70.25 $/bbl | N/A | -4.50% | down |" in text
    assert "+8.80%" not in text


def test_commodity_table_prefers_120d_when_all_rows_also_have_ytd(tmp_path: Path):
    market = _base_market()
    market["commodities"] = [
        {
            "symbol": "GC=F",
            "name": "Gold",
            "current_price": 2650.5,
            "unit": "$/oz",
            "daily_change": None,
            "change_120d": 3.3,
            "ytd_change": 8.8,
            "trend": "up",
            "source": "websearch_manual",
        },
        {
            "symbol": "CL=F",
            "name": "WTI Oil",
            "current_price": 70.25,
            "unit": "$/bbl",
            "daily_change": None,
            "change_120d": -4.4,
            "ytd_change": 9.9,
            "trend": "down",
            "source": "websearch_manual",
        },
    ]
    pring = {
        "final_stage": "stage 3",
        "confidence": 0.61,
        "recommendation": "neutral",
        "layer_1_inventory_cycle": {},
        "layer_2_monetary_cycle": {},
        "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [],
        "fallback_used": False,
    }
    m = tmp_path / "m.json"
    p = tmp_path / "p.json"
    out = tmp_path / "o.md"
    _write_json(m, market)
    _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")

    assert "| Gold | 2650.50 $/oz | N/A | +3.30% | up |" in text
    assert "| WTI Oil | 70.25 $/bbl | N/A | -4.40% | down |" in text
    assert "+8.80%" not in text
    assert "+9.90%" not in text


def test_report_estimated_appendix_includes_fund_flow_etf(tmp_path: Path):
    market = _base_market()
    market["fund_flow"] = {
        "etf": {
            "recent_5d": 85.6,
            "total_120d": 1250.0,
            "trend": "流入",
            "source": "fallback estimate",
            "note": "estimated fallback pending official source",
            "is_estimated": True,
        }
    }
    pring = {
        "final_stage": "stage 3",
        "confidence": 0.61,
        "recommendation": "neutral",
        "layer_1_inventory_cycle": {},
        "layer_2_monetary_cycle": {},
        "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [],
        "fallback_used": False,
    }
    m = tmp_path / "m.json"
    p = tmp_path / "p.json"
    out = tmp_path / "o.md"
    _write_json(m, market)
    _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")

    assert "估计值提醒" in text
    assert "资金流:ETF资金流" in text


def test_report_preserves_tushare_usdollar_proxy_label(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "DXY",
            "name": "美元指数（TuShare USDOLLAR.FXCM proxy）",
            "current_rate": 105.23,
            "daily_change": 0.12,
            "change_120d": 1.34,
            "trend": "上行",
            "source": "tushare fx_obasic/fx_daily FX_BASKET proxy USDOLLAR.FXCM",
        }
    ]
    pring = {
        "final_stage": "stage 3",
        "confidence": 0.61,
        "recommendation": "neutral",
        "layer_1_inventory_cycle": {},
        "layer_2_monetary_cycle": {},
        "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [],
        "fallback_used": False,
    }
    m = tmp_path / "m.json"
    p = tmp_path / "p.json"
    out = tmp_path / "o.md"
    _write_json(m, market)
    _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")

    assert "| 美元指数（TuShare USDOLLAR.FXCM proxy） | 105.2300 | +0.12% | +1.34% | 上行 |" in text
