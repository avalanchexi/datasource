#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage1 关键逻辑回归测试。"""

import asyncio
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from scripts.stage1_data_collector import MarketDataCollector


class _FakeManager:
    def __init__(self):
        self.fallback_sources = []

    def set_primary_source(self, *_args, **_kwargs):
        return None

    async def get_gdp_data(self, *_args, **_kwargs):
        payload = type("Resp", (), {})()
        payload.data = pd.DataFrame(
            {
                "quarter": ["2025Q3", "2025Q4"],
                "gdp_yoy": [5.2, 5.0],
            }
        )
        return payload


class _MacroLagManager(_FakeManager):
    async def get_ppi_data(self, *_args, **_kwargs):
        payload = type("Resp", (), {})()
        payload.data = pd.DataFrame({"month": ["202511", "202512"], "ppi_yoy": [-2.1, -1.9]})
        return payload

    async def get_cpi_data(self, *_args, **_kwargs):
        payload = type("Resp", (), {})()
        payload.data = pd.DataFrame({"month": ["202511", "202512"], "cpi_yoy": [0.6, 0.8]})
        return payload

    async def get_pmi_data(self, *_args, **_kwargs):
        payload = type("Resp", (), {})()
        payload.data = pd.DataFrame({"month": ["202511", "202512"], "pmi010100": [50.1, 50.8]})
        return payload


def test_fetch_gdp_uses_delta_change_rate(monkeypatch):
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-02-06")
    payload = asyncio.run(collector._fetch_gdp_from_tushare())

    assert payload is not None
    assert payload["current_value"] == pytest.approx(5.0)
    assert payload["previous_value"] == pytest.approx(5.2)
    assert payload["change_rate"] == pytest.approx(-0.2)


def test_apply_monthly_freshness_marks_stale_for_lagging_month(monkeypatch):
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-02-27")
    payload = {"date": "2025-12", "current_value": 0.8}
    marked = collector._apply_monthly_freshness(payload, "cpi")
    assert marked is not None
    assert marked["expected_period"] == "2026-01"
    assert marked["is_stale"] is True
    assert marked["stale_reason"] == "actual_period_behind_expected"


def test_apply_monthly_freshness_pmi_uses_current_month_after_month_end(monkeypatch):
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-02-28")
    payload = {"date": "2026-01", "current_value": 50.2}
    marked = collector._apply_monthly_freshness(payload, "pmi")
    assert marked is not None
    assert marked["expected_period"] == "2026-02"
    assert marked["is_stale"] is True


def test_apply_monthly_freshness_respects_release_lag_before_mid_month(monkeypatch):
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-02-10")
    payload = {"date": "2025-12", "current_value": 0.8}
    marked = collector._apply_monthly_freshness(payload, "cpi")
    assert marked is not None
    assert marked["expected_period"] == "2025-12"
    assert marked["is_stale"] is False


def test_collect_macro_indicators_records_stale_items(monkeypatch):
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _MacroLagManager())
    collector = MarketDataCollector("2026-02-27")
    result = asyncio.run(collector.collect_macro_indicators())
    assert result["cpi"].is_stale is True
    assert result["cpi"].expected_period == "2026-01"
    stale_keys = {
        item.get("key")
        for item in collector.missing_items.get("macro_indicators", [])
        if isinstance(item, dict) and "stale_data" in str(item.get("reason"))
    }
    assert {"cpi", "ppi", "pmi"} <= stale_keys


def test_calculate_change_uses_true_t_minus_window_baseline():
    import pandas as pd
    from scripts.stage1_data_collector import Stage1DataCollector

    df = pd.DataFrame({"close": list(range(1, 123))})
    collector = Stage1DataCollector.__new__(Stage1DataCollector)

    assert collector._calculate_change(df, 120) == round(((122 / 2) - 1) * 100, 1)


def test_calculate_change_returns_none_when_window_unavailable():
    import pandas as pd
    from scripts.stage1_data_collector import Stage1DataCollector

    df = pd.DataFrame({"close": list(range(1, 121))})
    collector = Stage1DataCollector.__new__(Stage1DataCollector)

    assert collector._calculate_change(df, 120) is None
