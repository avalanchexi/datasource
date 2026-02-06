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


def test_fetch_gdp_uses_delta_change_rate(monkeypatch):
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-02-06")
    payload = asyncio.run(collector._fetch_gdp_from_tushare())

    assert payload is not None
    assert payload["current_value"] == pytest.approx(5.0)
    assert payload["previous_value"] == pytest.approx(5.2)
    assert payload["change_rate"] == pytest.approx(-0.2)
