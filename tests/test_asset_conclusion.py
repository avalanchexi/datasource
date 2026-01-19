#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""资产层面 50 字结论相关测试"""

import os

from datasource.generators import simple_report


def test_limit_text_length_truncates():
    text = "这是一个用于测试的超长文本，用于验证长度截断逻辑是否正确执行以及句号补全。"
    limited = simple_report._limit_text_length(text, max_len=50)
    assert len(limited) <= 50
    assert limited[-1] in "。！？.!?"


def test_generate_asset_conclusion_no_summary():
    output, status, latency = simple_report._generate_asset_conclusion("")
    assert output == simple_report.DEFAULT_ASSET_CONCLUSION
    assert status == "no_summary"
    assert latency == 0.0


def test_generate_asset_conclusion_no_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    output, status, _ = simple_report._generate_asset_conclusion("商品:黄金(年内+10.0%)")
    assert output == simple_report.DEFAULT_ASSET_CONCLUSION
    assert status == "no_deepseek_key"


def test_build_asset_summary_filters_tushare():
    commodities = [
        {"symbol": "GC=F", "name": "黄金", "ytd_change": 12.0, "source": "MCP WebSearch"},
        {"symbol": "CL=F", "name": "原油", "ytd_change": -3.0, "source": "TuShare"},
    ]
    forex = [
        {"pair": "USDCNY", "name": "USD/CNY", "change_120d": -2.0, "source": "MCP WebSearch"},
        {"pair": "DXY", "name": "DXY", "change_120d": 1.0, "source": "tushare"},
    ]
    bonds = [
        {"symbol": "US10Y", "name": "美国10Y", "change_5d_bp": 8.0, "source": "MCP WebSearch"},
        {"symbol": "CN10Y", "name": "中国10Y", "change_5d_bp": 2.0, "source": "TuShare"},
    ]
    fund_flow = {
        "northbound": {"recent_5d": 12.0, "source": "MCP WebSearch"},
        "margin": {"recent_5d": -5.0, "source": "TuShare"},
    }

    summary = simple_report._build_asset_summary(commodities, forex, bonds, fund_flow)
    assert "黄金" in summary
    assert "USD/CNY" in summary
    assert "美国10Y" in summary
    # TuShare 来源应被过滤
    assert "原油" not in summary
    assert "DXY" not in summary
    assert "中国10Y" not in summary


def test_build_asset_summary_handles_missing_fields():
    summary = simple_report._build_asset_summary(
        commodities=[{"symbol": "GC=F", "name": "黄金"}],
        forex_list=[{"pair": "USDCNY", "name": "USD/CNY"}],
        bonds=[{"symbol": "US10Y", "name": "美国10Y"}],
        fund_flow={"northbound": {}},
    )
    assert isinstance(summary, str)
