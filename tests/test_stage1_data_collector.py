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

from scripts.stage1_data_collector import FundFlowData, MarketDataCollector


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


def test_index_daily_fallback_short_window_returns_none_changes(monkeypatch):
    class _Pro:
        def index_daily(self, **_kwargs):
            return pd.DataFrame(
                {
                    "trade_date": ["20260424", "20260427"],
                    "close": [3000.0, 3010.0],
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(
        collector._fallback_index_from_tushare("000001", "SH", "2026-04-01", "2026-04-27")
    )

    assert result is not None
    assert result.change_5d is None
    assert result.change_120d is None


def test_index_daily_fallback_calculates_exact_5d_window(monkeypatch):
    class _Pro:
        def index_daily(self, **_kwargs):
            return pd.DataFrame(
                {
                    "trade_date": [f"202604{day:02d}" for day in range(20, 26)],
                    "close": [100.0, 101.0, 102.0, 103.0, 104.0, 106.0],
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(
        collector._fallback_index_from_tushare("000001", "SH", "2026-04-01", "2026-04-27")
    )

    assert result is not None
    assert result.change_5d == pytest.approx(6.0)
    assert result.change_120d is None


def test_index_daily_fallback_calculates_exact_120d_window(monkeypatch):
    class _Pro:
        def index_daily(self, **_kwargs):
            closes = list(range(100, 221))
            return pd.DataFrame(
                {
                    "trade_date": [f"2026{i:04d}" for i in range(len(closes))],
                    "close": closes,
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(
        collector._fallback_index_from_tushare("000001", "SH", "2026-04-01", "2026-04-27")
    )

    assert result is not None
    assert result.change_5d is not None
    assert result.change_120d == pytest.approx(120.0)


def test_minute_fallback_returns_none_window_changes(monkeypatch):
    class _Pro:
        def index_daily(self, **_kwargs):
            return pd.DataFrame()

        def pro_bar(self, **_kwargs):
            return pd.DataFrame(
                {
                    "trade_time": ["2026-04-27 14:59:00", "2026-04-27 15:00:00"],
                    "close": [3000.0, 3010.0],
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(
        collector._fallback_index_from_tushare("000001", "SH", "2026-04-01", "2026-04-27")
    )

    assert result is not None
    assert result.change_5d is None
    assert result.change_120d is None


def test_previous_trade_fallback_returns_none_window_changes(monkeypatch):
    class _Pro:
        def index_daily(self, **kwargs):
            if kwargs.get("start_date") == kwargs.get("end_date"):
                return pd.DataFrame({"trade_date": ["20260424"], "close": [3000.0]})
            return pd.DataFrame()

        def pro_bar(self, **_kwargs):
            return pd.DataFrame()

        def trade_cal(self, **_kwargs):
            return pd.DataFrame(
                {
                    "cal_date": ["20260424", "20260427"],
                    "is_open": [1, 1],
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(
        collector._fallback_index_from_tushare("000001", "SH", "2026-04-01", "2026-04-27")
    )

    assert result is not None
    assert result.change_5d is None
    assert result.change_120d is None


def test_fetch_fx_from_tushare_discovers_dxy_fxcm_proxy(monkeypatch):
    class _Pro:
        def __init__(self):
            self.obasic_calls = []
            self.daily_calls = []

        def fx_obasic(self, **kwargs):
            self.obasic_calls.append(kwargs)
            return pd.DataFrame(
                {
                    "ts_code": ["EURUSD.FXCM", "USDOLLAR.FXCM"],
                    "name": ["EUR/USD", "USDollar basket"],
                }
            )

        def fx_daily(self, **kwargs):
            self.daily_calls.append(kwargs)
            return pd.DataFrame(
                {
                    "trade_date": ["20260424", "20260427"],
                    "bid_close": [101.0, 102.5],
                    "ask_close": [101.2, 102.7],
                    "bid_open": [100.8, 102.0],
                    "ask_open": [101.0, 102.2],
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    pro = _Pro()
    monkeypatch.setitem(sys.modules, "tushare", _Tushare(pro))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(collector._fetch_fx_from_tushare("DXY", "DXY美元指数"))

    assert result is not None
    assert pro.obasic_calls == [{"classify": "FX_BASKET", "exchange": "FXCM"}]
    assert pro.daily_calls == [
        {"ts_code": "USDOLLAR.FXCM", "start_date": "20251228", "end_date": "20260427"}
    ]
    assert result.pair == "DXY"
    assert "USDOLLAR" in result.name
    assert "代理" in result.name
    assert result.current_rate == pytest.approx(102.5)
    assert result.daily_change == pytest.approx((102.5 / 101.0 - 1.0) * 100.0)
    assert result.change_120d == pytest.approx((102.5 / 101.0 - 1.0) * 100.0)
    assert result.trend == "上行"
    assert result.source == "TuShare fx_daily(USDOLLAR.FXCM, FX_BASKET proxy)"
    assert result.as_of_date == "2026-04-27"
    assert result.note is not None
    assert "FXCM USDOLLAR" in result.note
    assert "not equivalent to ICE DXY" in result.note
    assert "Stage2/Stage2.5" in result.note


def test_fetch_fx_from_tushare_dxy_prefers_exact_usdollar_fxcm(monkeypatch):
    class _Pro:
        def __init__(self):
            self.daily_calls = []

        def fx_obasic(self, **_kwargs):
            return pd.DataFrame(
                {
                    "ts_code": ["XUSDOLLAR.FXCM", "USDOLLAR_ALT.FXCM", "USDOLLAR.FXCM"],
                }
            )

        def fx_daily(self, **kwargs):
            self.daily_calls.append(kwargs)
            return pd.DataFrame(
                {
                    "trade_date": ["20260424", "20260427"],
                    "bid_close": [101.0, 102.5],
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    pro = _Pro()
    monkeypatch.setitem(sys.modules, "tushare", _Tushare(pro))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(collector._fetch_fx_from_tushare("DXY", "DXY美元指数"))

    assert result is not None
    assert pro.daily_calls == [
        {"ts_code": "USDOLLAR.FXCM", "start_date": "20251228", "end_date": "20260427"}
    ]


def test_fetch_fx_from_tushare_dxy_returns_none_with_single_usable_row(monkeypatch):
    class _Pro:
        def fx_obasic(self, **_kwargs):
            return pd.DataFrame({"ts_code": ["USDOLLAR.FXCM"]})

        def fx_daily(self, **_kwargs):
            return pd.DataFrame({"trade_date": ["20260427"], "bid_close": [102.5]})

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(collector._fetch_fx_from_tushare("DXY", "DXY美元指数"))

    assert result is None


def test_fetch_fx_from_tushare_dxy_returns_none_without_usdollar_candidate(monkeypatch):
    class _Pro:
        def __init__(self):
            self.daily_calls = []

        def fx_obasic(self, **_kwargs):
            return pd.DataFrame({"ts_code": ["EURUSD.FXCM", "GBPUSD.FXCM"]})

        def fx_daily(self, **kwargs):
            self.daily_calls.append(kwargs)
            return pd.DataFrame({"trade_date": ["20260427"], "bid_close": [102.5]})

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    pro = _Pro()
    monkeypatch.setitem(sys.modules, "tushare", _Tushare(pro))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(collector._fetch_fx_from_tushare("DXY", "DXY美元指数"))

    assert result is None
    assert pro.daily_calls == []


def test_fetch_fx_from_tushare_dxy_rejects_out_of_range_proxy_value(monkeypatch):
    class _Pro:
        def fx_obasic(self, **_kwargs):
            return pd.DataFrame({"ts_code": ["USDOLLAR.FXCM"]})

        def fx_daily(self, **_kwargs):
            return pd.DataFrame({"trade_date": ["20260427"], "bid_close": [145.0]})

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(collector._fetch_fx_from_tushare("DXY", "DXY美元指数"))

    assert result is None


def test_fetch_fx_from_tushare_usdcny_skips_zero_quote_candidates(monkeypatch):
    class _Pro:
        def fx_daily(self, **_kwargs):
            return pd.DataFrame(
                {
                    "trade_date": ["20260427"],
                    "bid_close": [0.0],
                    "ask_close": [7.25],
                    "bid_open": [7.24],
                    "ask_open": [7.26],
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(collector._fetch_fx_from_tushare("USDCNY", "USD/CNY在岸"))

    assert result is not None
    assert result.current_rate == pytest.approx(7.25)


def test_fetch_fx_from_tushare_usdcny_returns_none_when_all_quotes_invalid(monkeypatch):
    class _Pro:
        def fx_daily(self, **_kwargs):
            return pd.DataFrame(
                {
                    "trade_date": ["20260427"],
                    "bid_close": [0.0],
                    "ask_close": [None],
                    "bid_open": [0.0],
                    "ask_open": [0.0],
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = asyncio.run(collector._fetch_fx_from_tushare("USDCNY", "USD/CNY在岸"))

    assert result is None


def test_fetch_etf_total_size_on_date_sums_exchanges_and_converts_to_yi(monkeypatch):
    class _Pro:
        def __init__(self):
            self.calls = []

        def etf_share_size(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("exchange") == "SSE":
                return pd.DataFrame({"total_size": [10000.0, 30000.0]})
            if kwargs.get("exchange") == "SZSE":
                return pd.DataFrame({"total_size": [20000.0]})
            return pd.DataFrame()

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    pro = _Pro()
    monkeypatch.setitem(sys.modules, "tushare", _Tushare(pro))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = collector._fetch_etf_total_size_on_date("20260427")

    assert result == pytest.approx(6.0)
    assert pro.calls == [
        {"trade_date": "20260427", "exchange": "SSE"},
        {"trade_date": "20260427", "exchange": "SZSE"},
    ]


def test_fetch_etf_total_size_on_date_returns_none_when_one_exchange_missing(monkeypatch):
    class _Pro:
        def etf_share_size(self, **kwargs):
            if kwargs.get("exchange") == "SSE":
                return pd.DataFrame({"total_size": [10000.0]})
            if kwargs.get("exchange") == "SZSE":
                return pd.DataFrame()
            return pd.DataFrame()

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = collector._fetch_etf_total_size_on_date("20260427")

    assert result is None


def test_fetch_etf_total_size_on_date_returns_none_when_one_exchange_has_no_usable_rows(monkeypatch):
    class _Pro:
        def etf_share_size(self, **kwargs):
            if kwargs.get("exchange") == "SSE":
                return pd.DataFrame({"total_size": [10000.0]})
            if kwargs.get("exchange") == "SZSE":
                return pd.DataFrame({"total_size": [0.0]})
            return pd.DataFrame()

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = collector._fetch_etf_total_size_on_date("20260427")

    assert result is None


def test_fetch_etf_flow_from_tushare_share_size_builds_trade_cal_windows(monkeypatch):
    trade_dates = [f"2026{i:04d}" for i in range(121)]

    class _Pro:
        def trade_cal(self, **_kwargs):
            return pd.DataFrame({"cal_date": trade_dates, "is_open": [1] * len(trade_dates)})

        def etf_share_size(self, **kwargs):
            idx = trade_dates.index(kwargs["trade_date"])
            total_yi = 1000.0 + idx
            half_wan = total_yi * 10000.0 / 2
            return pd.DataFrame({"total_size": [half_wan]})

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = collector._fetch_etf_flow_from_tushare_share_size()

    assert result is not None
    assert result.type == "ETF资金流"
    assert result.recent_5d == pytest.approx(5.0)
    assert result.total_120d == pytest.approx(120.0)
    assert result.trend == "流入"
    assert result.source == "TuShare etf_share_size"
    assert result.metric_basis == "etf_total_size_delta"
    assert result.is_estimated is False
    assert "ETF规模/份额推导" in (result.note or "")


def test_fetch_etf_flow_from_tushare_share_size_returns_none_when_window_incomplete(monkeypatch):
    trade_dates = [f"2026{i:04d}" for i in range(120)]

    class _Pro:
        def trade_cal(self, **_kwargs):
            return pd.DataFrame({"cal_date": trade_dates, "is_open": [1] * len(trade_dates)})

        def etf_share_size(self, **_kwargs):
            return pd.DataFrame({"total_size": [10000.0]})

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    result = collector._fetch_etf_flow_from_tushare_share_size()

    assert result is None


def test_collect_fund_flow_keeps_etf_missing_when_only_estimated_fallback(monkeypatch):
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-27")

    async def _empty_hsgt():
        return {
            "north_recent_5d": None,
            "north_total_120d": None,
            "south_recent_5d": None,
            "south_total_120d": None,
            "as_of_trade_date": None,
            "full_120_window": False,
        }

    async def _no_margin():
        return None

    async def _estimated_etf_proxy():
        return FundFlowData(
            type="etf",
            recent_5d=12.3,
            total_120d=45.6,
            trend="inflow",
            source="TuShare daily_info estimate",
            metric_basis="estimated_net_flow",
            is_estimated=True,
            note="diagnostic estimate",
        )

    monkeypatch.setattr(collector, "_fetch_hsgt_from_tushare", _empty_hsgt)
    monkeypatch.setattr(collector, "_fetch_margin_flow_from_tushare", _no_margin)
    monkeypatch.setattr(collector, "_fetch_etf_flow_from_tushare_share_size", lambda: None)
    monkeypatch.setattr(collector, "_fetch_etf_flow_proxy", _estimated_etf_proxy)

    fund_flow = asyncio.run(collector.collect_fund_flow())

    assert fund_flow["etf"].is_estimated is True
    etf_missing = [
        item
        for item in collector.missing_items.get("fund_flow", [])
        if isinstance(item, dict) and item.get("key") == "etf"
    ]
    assert len(etf_missing) == 1
    assert "etf_share_size" in etf_missing[0]["reason"]
    assert "estimated fallback" in etf_missing[0]["reason"]
