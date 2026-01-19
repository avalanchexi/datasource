#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backfill trend_history using TuShare-accessible series (no WebSearch)."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from datasource import get_manager
from datasource.utils.trend_history_store import SeriesRecord, write_series_record


INDEX_SYMBOLS = {
    "000300": "沪深300",
    "000016": "上证50",
    "399006": "创业板指",
    "399001": "深证成指",
    "000001": "上证指数",
}

FOREX_SYMBOLS = ["USDCNY", "USDCNH"]
BOND_SYMBOLS = ["US10Y", "CN10Y", "CN10Y_CDB"]


def _to_date_str(date_val: str) -> str:
    if not date_val:
        return ""
    text = str(date_val)
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").strftime("%Y-%m-%d")
    return text[:10]


def _pick_fx_rate(row: pd.Series) -> Optional[float]:
    for key in ("bid_close", "ask_close", "bid_open", "ask_open"):
        val = row.get(key)
        if pd.notna(val):
            return float(val)
    return None


async def _backfill_indices(manager, start_date: str, end_date: str) -> int:
    writes = 0
    for symbol in INDEX_SYMBOLS.keys():
        resp = await manager.get_index_daily(symbol, start_date, end_date)
        data = getattr(resp, "data", None)
        if data is None or isinstance(data, dict) or data.empty:
            continue
        data = data.sort_values("trade_date")
        for _, row in data.iterrows():
            date_str = _to_date_str(row.get("trade_date"))
            close = row.get("close")
            if pd.isna(close):
                continue
            record = SeriesRecord(
                date=date_str,
                value=float(close),
                unit=None,
                source=resp.metadata.get("data_source") if resp.metadata else resp.source,
                source_timestamp=None,
                market_calendar="CN",
                is_estimated=False,
                is_partial=False,
            )
            if write_series_record("stock_indices", symbol, record):
                writes += 1
    return writes


async def _backfill_forex(start_date: str, end_date: str) -> int:
    writes = 0
    try:
        import tushare as ts
        token = None
        try:
            import os
            token = os.getenv("TUSHARE_TOKEN")
        except Exception:
            token = None
        pro = ts.pro_api(token) if token else ts.pro_api()
        for symbol in FOREX_SYMBOLS:
            df = pro.fx_daily(
                ts_code=symbol,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
            )
            if df is None or df.empty:
                continue
            df = df.sort_values("trade_date")
            for _, row in df.iterrows():
                date_str = _to_date_str(row.get("trade_date"))
                rate = _pick_fx_rate(row)
                if rate is None:
                    continue
                record = SeriesRecord(
                    date=date_str,
                    value=float(rate),
                    unit=None,
                    source="TuShare fx_daily",
                    source_timestamp=None,
                    market_calendar="CN",
                    is_estimated=False,
                    is_partial=False,
                )
                if write_series_record("forex", symbol, record):
                    writes += 1
    except Exception:
        return writes
    return writes


async def _backfill_bonds(manager, start_date: str, end_date: str) -> int:
    writes = 0
    for symbol in BOND_SYMBOLS:
        resp = await manager.get_bond_yield_data(symbol, start_date, end_date)
        data = getattr(resp, "data", None)
        if data is None or isinstance(data, dict) or data.empty:
            continue
        source_type = resp.metadata.get("source_type") if resp and resp.metadata else None
        if source_type == "bond_etf_proxy":
            print(f"[WARN] skip {symbol}: bond_etf_proxy backfill disabled")
            continue
        data = data.sort_values("date") if "date" in data.columns else data
        for _, row in data.iterrows():
            date_str = _to_date_str(row.get("date"))
            value = row.get("yield_rate") if "yield_rate" in data.columns else row.get("close")
            if pd.isna(value):
                continue
            calendar = "US" if symbol.startswith("US") else "CN"
            record = SeriesRecord(
                date=date_str,
                value=float(value),
                unit="%",
                source=resp.metadata.get("data_source") if resp.metadata else resp.source,
                source_timestamp=None,
                market_calendar=calendar,
                is_estimated=False,
                is_partial=False,
            )
            if write_series_record("bonds", symbol, record):
                writes += 1
    return writes


async def main_async(start_date: str, end_date: str) -> None:
    manager = get_manager()
    manager.set_primary_source("tushare")
    manager.add_fallback_source("international_finance")

    idx = await _backfill_indices(manager, start_date, end_date)
    fx = await _backfill_forex(start_date, end_date)
    bonds = await _backfill_bonds(manager, start_date, end_date)

    print(f"[OK] backfill done: indices={idx}, forex={fx}, bonds={bonds}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill trend_history from TuShare")
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    args = parser.parse_args()

    end_date = args.end or datetime.now().strftime("%Y-%m-%d")
    if args.start:
        start_date = args.start
    else:
        start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=370)).strftime("%Y-%m-%d")

    asyncio.run(main_async(start_date, end_date))


if __name__ == "__main__":
    main()
