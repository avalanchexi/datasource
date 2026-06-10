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

from datasource.generators import simple_report
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


def test_asset_summary_omits_unreliable_zero_forex_change():
    summary = simple_report._build_asset_summary(
        [],
        [
            {
                "pair": "USDCNY",
                "name": "USD/CNY",
                "current_rate": 6.8184,
                "change_120d": 0.0,
                "trend": "pending",
                "source": "structured",
            }
        ],
        [],
        {},
    )

    assert "USD/CNY" not in summary
    assert "+0.0%" not in summary
    assert "+0.00%" not in summary


def test_macro_change_suffix_renders_bdi_change_rate_as_percent():
    from datasource.generators.simple_report import _macro_change_suffix_for_report

    assert _macro_change_suffix_for_report("bdi", {"unit": "点", "change_rate": -3.36}) == "%"
    assert _macro_change_suffix_for_report("industrial", {"unit": "%", "change_rate": 0.1}) == "%"


@pytest.mark.parametrize("trend", ["横盘震荡", "flat", "sideways"])
def test_asset_summary_omits_zero_derived_forex_trend_without_usable_change(trend):
    summary = simple_report._build_asset_summary(
        [],
        [
            {
                "pair": "USDCNY",
                "name": "USD/CNY",
                "current_rate": 6.8184,
                "daily_change": 0.0,
                "trend": trend,
                "source": "structured",
            }
        ],
        [],
        {},
    )

    assert "USD/CNY" not in summary
    assert trend not in summary


def test_asset_summary_omits_zero_derived_forex_trend_when_one_change_unusable():
    summary = simple_report._build_asset_summary(
        [],
        [
            {
                "pair": "USDCNY",
                "name": "USD/CNY",
                "current_rate": 6.8184,
                "daily_change": 0.0,
                "change_120d": 1.2,
                "change_120d_basis": "trend_history",
                "change_120d_base_date": "2026-02-01",
                "trend": "flat",
                "source": "structured",
            }
        ],
        [],
        {},
    )

    assert "USD/CNY" in summary
    assert "+1.2%" in summary
    assert "flat" not in summary


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


def test_quality_gate_does_not_red_flag_estimated_allowlist_items():
    rules = {
        "estimated_allowlist_keys": ["CN10Y_CDB", "bdi"],
        "bdi_estimated_allow_conditions": {
            "trusted_domains": ["tradingeconomics.com"],
            "max_age_days": 9999,
            "value_range": [200.0, 10000.0],
            "unit_keywords": ["points"],
        },
    }
    market = _base_market()
    market["bonds"] = [
        {
            "symbol": "CN10Y_CDB",
            "name": "China policy bank 10Y",
            "current_yield": 1.86,
            "change_120d_bp": -27.69,
            "is_estimated": True,
            "source_url": "https://example.com/cdb",
        }
    ]
    market["macro_indicators"] = {
        "bdi": {
            "indicator_name": "BDI",
            "current_value": 1410.0,
            "previous_value": 1380.0,
            "change_rate": 2.17,
            "unit": "points",
            "date": "2026-05-08",
            "as_of_date": "2026-05-08",
            "is_estimated": True,
            "source_url": "https://tradingeconomics.com/commodity/baltic",
        }
    }

    issues = simple_report._collect_quality_issues(market, policy_rules=rules)

    assert not issues


def test_report_shows_bdi_estimated_date_instead_of_pending_websearch(tmp_path: Path):
    market = _base_market()
    market["metadata"]["date"] = "2026-05-19"
    market["macro_indicators"] = {
        "bdi": {
            "indicator_name": "BDI",
            "current_value": 2017.0,
            "previous_value": 2031.0,
            "change_rate": -0.69,
            "unit": "points",
            "date": "2026-05-18",
            "source": "websearch_manual(TradingEconomics Baltic Dry Index)",
            "source_url": "https://tradingeconomics.com/commodity/baltic",
            "is_estimated": True,
        }
    }
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.725,
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
    assert "| BDI | 2017.0points(估) | 2031.0points(估) | -0.7%(估) | points | 2026-05-18 |" in text
    assert "N/A（待 WebSearch）" not in text


def test_commodity_daily_change_spike_is_hidden_in_report(tmp_path: Path):
    market = _base_market()
    market["commodities"] = [
        {
            "symbol": "BCOM",
            "name": "BCOM index",
            "current_price": 137.33,
            "unit": "points",
            "daily_change": 119.62,
            "change_120d": 33.55,
            "ytd_change": None,
            "trend": "up",
            "source": "websearch_manual",
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
    assert "| BCOM index | 137.33 points | \u2014\uff08\u5f02\u5e38\uff09 | +33.55% | up |" in text
    assert "+119.62%" not in text


def test_report_estimated_appendix_includes_fund_flow_etf(tmp_path: Path):
    market = _base_market()
    market["fund_flow"] = {
        "etf": {
            "recent_5d": 85.6,
            "total_120d": 1250.0,
            "trend": "流入",
            "source": "fallback estimate",
            "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
            "note": "estimated fallback pending official source: news_net_flow https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
            "metric_basis": "news_net_flow",
            "window_evidence": "news_summary",
            "estimation_method": "fund_flow_manual_window_not_direct",
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
    assert "news_net_flow" in text
    assert "news_summary" in text
    assert "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml" in text
    assert "| ETF资金流 | 85.60(估) | 1250.00(估) | 流入 | fallback estimate | estimated fallback pending official source: news_net_flow https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml; metric_basis=news_net_flow; window_evidence=news_summary; source_url=https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml |" in text


def test_report_fund_flow_window_missing_discloses_structured_evidence(tmp_path: Path):
    market = _base_market()
    market["fund_flow"] = {
        "etf": {
            "recent_5d": None,
            "total_120d": None,
            "trend": "待核查",
            "source": "websearch_manual",
            "source_url": "https://data.eastmoney.com/etf/",
            "metric_basis": "etf_total_size_delta",
            "window_evidence": "direct_balance_delta",
            "is_estimated": False,
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

    assert "资金流:ETF资金流" not in text
    assert "| ETF资金流 | N/A | N/A | 待核查 | websearch_manual | metric_basis=etf_total_size_delta; window_evidence=direct_balance_delta; source_url=https://data.eastmoney.com/etf/ |" in text


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


def test_report_hides_unreliable_zero_forex_daily_change(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "change_120d": -4.18,
            "trend": "待获取",
            "source": "structured",
            "note": "structured_provider:official_china",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | N/A | -4.18% | 待补变化 |" in text


def test_report_keeps_evidenced_zero_forex_daily_change(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "daily_change_basis": "direct_daily_series",
            "daily_change_base_date": "2026-06-02",
            "change_120d": -4.18,
            "trend": "横盘震荡",
            "source": "structured",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | +0.00% | -4.18% | 横盘震荡 |" in text


def test_fx_daily_zero_valid_evidence_overrides_stale_reason_1d():
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "daily_change": 0.0,
            "daily_change_basis": "trend_history",
            "reason_1d": "no_previous_value",
        },
        "daily_change",
        digits=2,
        suffix="%",
    )

    assert cell == "+0.00%"
    assert unavailable is False


def test_fx_daily_zero_rejects_failed_trend_history_basis():
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "daily_change": 0.0,
            "daily_change_basis": "failed_trend_history",
        },
        "daily_change",
        digits=2,
        suffix="%",
    )

    assert cell == "N/A"
    assert unavailable is True


@pytest.mark.parametrize("field", ["change_1d", "change_1d_pct"])
def test_fx_daily_zero_rejects_bare_change_1d_numeric_evidence(field):
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "daily_change": 0.0,
            field: 0.0,
        },
        "daily_change",
        digits=2,
        suffix="%",
    )

    assert cell == "N/A"
    assert unavailable is True


def test_fx_daily_zero_accepts_base_1d_date_evidence():
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "daily_change": 0.0,
            "base_1d_date": "2026-06-02",
        },
        "daily_change",
        digits=2,
        suffix="%",
    )

    assert cell == "+0.00%"
    assert unavailable is False


def test_fx_daily_zero_rejects_source_url_with_reason_marker():
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "daily_change": 0.0,
            "daily_change_source_url": "https://example.com/fx?reason=trend_history",
        },
        "daily_change",
        digits=2,
        suffix="%",
    )

    assert cell == "N/A"
    assert unavailable is True


@pytest.mark.parametrize("trend", ["flat", "sideways"])
def test_fx_trend_replaces_raw_flat_when_change_unavailable(trend):
    assert (
        simple_report._format_fx_trend(
            {"trend": trend},
            current_rate=6.8184,
            change_unavailable=True,
        )
        == simple_report.FX_CHANGE_UNAVAILABLE_TEXT
    )


@pytest.mark.parametrize(
    "basis",
    ["not-available_trend_history", "not_available_trend_history"],
)
def test_fx_daily_zero_rejects_not_available_trend_history_basis(basis):
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "daily_change": 0.0,
            "daily_change_basis": basis,
        },
        "daily_change",
        digits=2,
        suffix="%",
    )

    assert cell == "N/A"
    assert unavailable is True


def test_fx_120d_zero_valid_evidence_overrides_stale_source_marker():
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "change_120d": 0.0,
            "change_120d_basis": "trend_history",
            "change_120d_source": "no_value",
        },
        "change_120d",
        digits=2,
        suffix="%",
    )

    assert cell == "+0.00%"
    assert unavailable is False


def test_fx_120d_zero_accepts_direct_window_evidence():
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "change_120d": 0.0,
            "change_120d_window_evidence": "direct_window",
        },
        "change_120d",
        digits=2,
        suffix="%",
    )

    assert cell == "+0.00%"
    assert unavailable is False


@pytest.mark.parametrize("marker", ["change_1d", "direct_daily_series"])
def test_fx_120d_zero_rejects_daily_only_evidence_markers(marker):
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "change_120d": 0.0,
            "change_120d_window_evidence": marker,
        },
        "change_120d",
        digits=2,
        suffix="%",
    )

    assert cell == "N/A"
    assert unavailable is True


def test_fx_120d_zero_rejects_daily_change_rate_marker():
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "change_120d": 0.0,
            "change_120d_basis": "daily_change_rate",
        },
        "change_120d",
        digits=2,
        suffix="%",
    )

    assert cell == "N/A"
    assert unavailable is True


def test_fx_120d_zero_rejects_invalid_trend_history_basis():
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "change_120d": 0.0,
            "change_120d_basis": "invalid_trend_history",
        },
        "change_120d",
        digits=2,
        suffix="%",
    )

    assert cell == "N/A"
    assert unavailable is True


def test_fx_120d_zero_rejects_reason_equals_trend_history_basis():
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "change_120d": 0.0,
            "change_120d_basis": "reason=trend_history",
        },
        "change_120d",
        digits=2,
        suffix="%",
    )

    assert cell == "N/A"
    assert unavailable is True


def test_fx_120d_zero_rejects_source_url_with_reason_marker():
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "change_120d": 0.0,
            "change_120d_source_url": "https://example.com/fx?reason=trend_history",
        },
        "change_120d",
        digits=2,
        suffix="%",
    )

    assert cell == "N/A"
    assert unavailable is True


@pytest.mark.parametrize(
    "basis",
    ["not-available_trend_history", "not_available_trend_history"],
)
def test_fx_120d_zero_rejects_not_available_trend_history_basis(basis):
    cell, unavailable = simple_report._format_fx_change_cell(
        {
            "change_120d": 0.0,
            "change_120d_basis": basis,
        },
        "change_120d",
        digits=2,
        suffix="%",
    )

    assert cell == "N/A"
    assert unavailable is True


def test_report_rejects_invalid_daily_base_date_for_forex_zero(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "daily_change_base_date": "N/A",
            "change_120d": -4.18,
            "trend": "pending",
            "source": "structured",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | N/A | -4.18% | 待补变化 |" in text


def test_report_rejects_invalid_120d_base_date_for_forex_zero(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.12,
            "change_120d": 0.0,
            "change_120d_base_date": "N/A",
            "trend": "pending",
            "source": "structured",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | +0.12% | N/A | 待补变化 |" in text


def test_report_keeps_valid_base_date_only_forex_zero_changes(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "daily_change_base_date": "2026-06-02",
            "change_120d": -4.18,
            "trend": "pending",
            "source": "structured",
        },
        {
            "pair": "USDCNH",
            "name": "USD/CNH离岸",
            "current_rate": 6.8211,
            "daily_change": 0.12,
            "change_120d": 0.0,
            "change_120d_base_date": "2026-02-01",
            "trend": "pending",
            "source": "structured",
        },
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | +0.00% | -4.18% | 未知 |" in text
    assert "| USD/CNH离岸 | 6.8211 | +0.12% | +0.00% | 未知 |" in text


def test_report_rejects_failure_marker_in_forex_previous_value(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "previous_value": "no_value",
            "change_120d": -4.18,
            "trend": "pending",
            "source": "structured",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | N/A | -4.18% | 待补变化 |" in text


def test_report_rejects_provider_only_forex_daily_change_source(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "daily_change_source": "ChinaMoney",
            "change_120d": -4.18,
            "trend": "pending",
            "source": "structured",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | N/A | -4.18% | 待补变化 |" in text


def test_report_rejects_generic_source_exchange_rate_text_for_forex_zero(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "change_120d": -4.18,
            "trend": "pending",
            "source": "official exchange_rate source",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | N/A | -4.18% | 待补变化 |" in text


def test_report_rejects_generic_note_exchange_rate_text_for_forex_zero(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "change_120d": -4.18,
            "trend": "pending",
            "source": "structured",
            "note": "exchange_rate provider",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | N/A | -4.18% | 待补变化 |" in text


def test_report_rejects_entry_level_trend_confidence_for_forex_120d_zero(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.12,
            "change_120d": 0.0,
            "trend_history_confidence": "medium",
            "trend": "pending",
            "source": "structured",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | +0.12% | N/A | 待补变化 |" in text


def test_report_keeps_120d_field_specific_evidence_for_forex_zero(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.12,
            "change_120d": 0.0,
            "change_120d_basis": "trend_history",
            "change_120d_base_date": "2026-02-01",
            "trend": "横盘震荡",
            "source": "structured",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | +0.12% | +0.00% | 横盘震荡 |" in text


def test_report_field_specific_daily_evidence_survives_generic_missing_note(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "daily_change_basis": "trend_history",
            "change_120d": -4.18,
            "trend": "pending",
            "source": "structured",
            "note": "reason=no_previous_value",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | +0.00% | -4.18% | 未知 |" in text


def test_report_keeps_hyphenated_non_pending_forex_trend(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "change_120d": -4.18,
            "trend": "range-bound",
            "source": "structured",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
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
    assert "| USD/CNY在岸 | 6.8184 | N/A | -4.18% | range-bound |" in text


def test_report_backfills_stock_indices_from_macro_compat(tmp_path: Path):
    market = _base_market()
    market["metadata"] = {"date": "2026-05-21", "data_completeness": 1.0}
    market["stock_indices"] = []
    market["macro_indicators"] = {
        "000300": {
            "indicator_name": "沪深300",
            "current_value": 4685.3,
            "previous_value": 4600.0,
            "change_rate": 1.85,
            "unit": "点",
            "source": "manual",
            "source_url": "https://example.com/000300",
        }
    }
    pring = {
        "final_stage": "Stage 2",
        "confidence": 0.8,
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
    assert "| 沪深300 | 4685.30 |" in text


def test_report_deduplicates_stock_indices_with_exchange_suffix(tmp_path: Path):
    market = _base_market()
    market["metadata"] = {"date": "2026-05-21", "data_completeness": 1.0}
    market["stock_indices"] = [
        {
            "symbol": "000001.SH",
            "name": "上证指数",
            "current_price": 3200.0,
            "change_5d": 0.5,
            "change_120d": 3.2,
            "above_ma50": True,
            "above_ma200": True,
            "trend_label": "上行",
        }
    ]
    market["macro_indicators"] = {
        "000001": {
            "indicator_name": "上证指数",
            "current_value": 4000.0,
            "change_rate": 9.9,
            "unit": "点",
        }
    }
    pring = {
        "final_stage": "Stage 2",
        "confidence": 0.8,
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
    assert "| 上证指数 | 3200.00 |" in text
    assert "| 上证指数 | 4000.00 |" not in text


def test_report_filters_suffixed_index_keys_from_macro_table(tmp_path: Path):
    market = _base_market()
    market["metadata"] = {"date": "2026-05-21", "data_completeness": 1.0}
    market["macro_indicators"] = {
        "000300.SH": {
            "indicator_name": "沪深300",
            "current_value": 4685.3,
            "previous_value": 4600.0,
            "change_rate": 1.85,
            "unit": "点",
        }
    }
    pring = {
        "final_stage": "Stage 2",
        "confidence": 0.8,
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
    assert text.count("| 沪深300 |") == 1


def test_report_estimated_note_includes_category_and_method(tmp_path: Path):
    market = _base_market()
    market["metadata"] = {"date": "2026-05-21", "data_completeness": 1.0}
    market["commodities"] = [
        {
            "symbol": "BCOM",
            "name": "彭博商品指数",
            "current_price": 108.5,
            "unit": "点",
            "daily_change": 0.1,
            "change_120d": 2.0,
            "trend": "上行",
            "is_estimated": True,
            "estimation_method": "manual_estimated",
        }
    ]
    pring = {
        "final_stage": "Stage 2",
        "confidence": 0.8,
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
    assert "商品:彭博商品指数(manual_estimated)" in text
