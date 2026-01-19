#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""单元测试: WebSearch 注入脚本的数据标准化逻辑"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import inject_websearch_data_test as injector


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
    assert entry["source"] == "MCP WebSearch实时获取"
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


def test_create_monetary_placeholder_infers_date_from_metadata():
    metadata = {"date": "2025-11-14"}
    placeholder = injector._create_monetary_placeholder("dr007", {"unit": "%"}, metadata)
    assert placeholder["policy_name"] == "DR007"
    assert placeholder["date"] == "2025-11-14"
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
    updated = injector._apply_monetary_entry(entry, payload)
    assert updated is True
    assert entry["current_value"] == pytest.approx(1.85)
    assert entry["change_from_120d"] == pytest.approx(-0.15)
    assert entry["source"].startswith("MCP WebSearch实时获取")
