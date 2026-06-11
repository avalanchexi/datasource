#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backfill fund_flow trend_history series from market_data_complete snapshots."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

from datasource.utils.json_io import load_json_strict
from datasource.utils.trend_history_store import SeriesRecord, write_series_record


FLOW_KEYS = ("northbound", "southbound", "etf")
METRICS = ("recent_5d", "total_120d")


def _load_json(path: Path) -> Dict[str, Any]:
    return load_json_strict(path)


def _collect_snapshots(paths: List[Path]) -> List[Tuple[str, Dict[str, Any]]]:
    snapshots = []
    for path in sorted(paths):
        payload = _load_json(path)
        date_val = (
            payload.get("metadata", {}).get("date")
            or payload.get("metadata", {}).get("end_date")
            or payload.get("metadata", {}).get("start_date")
        )
        if not date_val:
            continue
        snapshots.append((str(date_val)[:10], payload))
    return snapshots


def _write_flow_series(date_str: str, item: Dict[str, Any]) -> int:
    writes = 0
    source = item.get("source")
    for metric in METRICS:
        value = item.get(metric)
        if value is None:
            continue
        record = SeriesRecord(
            date=date_str,
            value=float(value),
            unit="亿元",
            source=source,
            source_timestamp=None,
            market_calendar="CN",
            is_estimated=False,
            is_partial=False,
            metric=metric,
        )
        symbol = f"{item.get('type', '') or item.get('key', '') or ''}_{metric}".strip("_")
        if not symbol:
            continue
        if write_series_record("fund_flow", symbol, record):
            writes += 1
    return writes


def _load_calendar_dates(path: Path) -> List[str]:
    if not path.exists():
        return []
    payload = _load_json(path)
    values = payload.get("values") if isinstance(payload.get("values"), list) else []
    dates = [v.get("date") for v in values if isinstance(v, dict) and v.get("date")]
    return [str(d)[:10] for d in dates]


def _pad_series(symbol: str, dates: List[str], value: float) -> int:
    writes = 0
    for date_str in dates:
        record = SeriesRecord(
            date=date_str,
            value=float(value),
            unit="亿元",
            source="carry_forward_estimated",
            source_timestamp=None,
            market_calendar="CN",
            is_estimated=True,
            is_partial=False,
            metric="recent_5d" if symbol.endswith("recent_5d") else "total_120d",
        )
        if write_series_record("fund_flow", symbol, record):
            writes += 1
    return writes


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill fund_flow series from daily snapshots")
    parser.add_argument("--source-dir", default="data", help="Directory containing *_market_data_complete.json")
    parser.add_argument("--pattern", default="*_market_data_complete.json", help="Glob pattern for input files")
    parser.add_argument("--pad-to-120", action="store_true", help="Pad missing days with estimated carry-forward")
    parser.add_argument("--calendar", default="data/trend_history/min/series/stock_indices/000300.json",
                        help="Calendar source series for CN trading dates")
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    paths = list(source_dir.glob(args.pattern))
    if not paths:
        print("[WARN] no market_data_complete files found")
        return

    snapshots = _collect_snapshots(paths)
    total_writes = 0
    latest_values: Dict[str, float] = {}

    for date_str, payload in snapshots:
        fund_flow = payload.get("fund_flow", {}) or {}
        for key in FLOW_KEYS:
            item = fund_flow.get(key)
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["type"] = key
            writes = _write_flow_series(date_str, item)
            total_writes += writes
            for metric in METRICS:
                val = item.get(metric)
                if val is not None:
                    latest_values[f"{key}_{metric}"] = float(val)

    if args.pad_to_120:
        dates = _load_calendar_dates(Path(args.calendar))
        if dates:
            pad_dates = dates[-120:]
            for symbol, value in latest_values.items():
                total_writes += _pad_series(symbol, pad_dates, value)
        else:
            print("[WARN] calendar dates not found; skip padding")

    print(f"[OK] fund_flow series backfill writes: {total_writes}")


if __name__ == "__main__":
    main()
