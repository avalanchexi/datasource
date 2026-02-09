#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import types

import pandas as pd

from scripts.stage1_data_collector import MarketDataCollector


class _FakePro:
    def moneyflow_hsgt(self, start_date=None, end_date=None):
        # TuShare 原始字段按“万元”口径返回，脚本需换算成“亿元”
        rows = []
        for i in range(1, 7):
            rows.append(
                {
                    "trade_date": f"2026020{i}",
                    "north_money": float(i * 10000),   # 1,2,3... 亿元（换算后）
                    "south_money": float(i * 20000),   # 2,4,6... 亿元（换算后）
                }
            )
        return pd.DataFrame(rows)


def test_fetch_hsgt_from_tushare_rolls_5d_and_120d(monkeypatch):
    fake_module = types.SimpleNamespace(pro_api=lambda token=None: _FakePro())
    import sys

    monkeypatch.setitem(sys.modules, "tushare", fake_module)
    collector = MarketDataCollector.__new__(MarketDataCollector)
    collector.end_date = "2026-02-09"
    monkeypatch.setattr(collector, "_get_recent_open_dates", lambda count=120: [f"202601{i:02d}" for i in range(1, 121)])

    result = asyncio.run(collector._fetch_hsgt_from_tushare())

    # north: 1..6 亿元，recent_5d = 2+3+4+5+6 = 20
    assert result["north_recent_5d"] == 20.0
    assert result["north_total_120d"] == 21.0
    # south: 2..12 亿元，recent_5d = 4+6+8+10+12 = 40
    assert result["south_recent_5d"] == 40.0
    assert result["south_total_120d"] == 42.0
    assert result["as_of_trade_date"] == "20260206"
    assert result["full_5_window"] is True
    # 返回行数不足120时仍标记部分窗口，交由 Stage2/Stage2.5 补齐
    assert result["full_120_window"] is False
