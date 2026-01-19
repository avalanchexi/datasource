#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sync fund_flow daily series from 10jqka and compute 5d/120d rollups."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from datasource.models.market_data_contract import FundFlowData
from datasource.utils.fund_flow_series import apply_override, compute_rollup, compute_rollup_series
from datasource.utils.trend_history_store import DEFAULT_BASE_DIR, SeriesRecord, write_series_record


THS_HISTORY_URL = "https://data.10jqka.com.cn/hsgt/history/type/{flow_type}/date/day/"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.10jqka.com.cn/hsgt/",
}


def _normalize_date(date_str: Optional[str]) -> str:
    if not date_str:
        return ""
    return str(date_str)[:10]


def _parse_amount(value: Optional[str]) -> Optional[float]:
    return FundFlowData._parse_amount(value)


def _fetch_ths_daily_series(flow_type: str) -> List[Dict[str, float]]:
    url = THS_HISTORY_URL.format(flow_type=flow_type)
    resp = httpx.get(url, headers=DEFAULT_HEADERS, timeout=12.0)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status_code") != 0:
        raise RuntimeError(f"THS history failed: {payload.get('status_msg')}")
    zhuri = payload.get("data", {}).get("zhuri", {}) or {}
    dates = zhuri.get("date") or []
    totals = zhuri.get("total") or []
    records: Dict[str, float] = {}
    for date, raw_val in zip(dates, totals):
        date = _normalize_date(date)
        if not date:
            continue
        try:
            val = float(raw_val) / 1e8  # 元 -> 亿元
        except (TypeError, ValueError):
            continue
        records[date] = val
    return [{"date": d, "value": records[d]} for d in sorted(records)]


def _write_series(
    symbol: str,
    values: List[Dict[str, float]],
    *,
    source: str,
    metric: Optional[str],
    base_dir: Path,
) -> int:
    writes = 0
    for item in values:
        record = SeriesRecord(
            date=item["date"],
            value=float(item["value"]),
            unit="亿元",
            source=source,
            source_timestamp=None,
            market_calendar="CN",
            is_estimated=bool(item.get("is_estimated", False)),
            is_partial=False,
            metric=metric,
        )
        if write_series_record("fund_flow", symbol, record, base_dir=base_dir):
            writes += 1
    return writes


def _extract_news_override(path: Path) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    if not path.exists():
        return None, None, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    ff = payload.get("fund_flow", {}) or {}
    nb = ff.get("northbound") or {}
    raw_val = nb.get("current_value") or nb.get("daily_value") or nb.get("today_value")
    override = _parse_amount(raw_val)
    date = _normalize_date(nb.get("date") or payload.get("metadata", {}).get("date"))
    source = nb.get("source")
    return override, date, source


def _update_market_data(
    market_path: Path,
    *,
    output_path: Optional[Path],
    target_date: Optional[str],
    series_map: Dict[str, List[Dict[str, float]]],
    north_override: Optional[float],
    north_override_date: Optional[str],
    north_override_source: Optional[str],
) -> None:
    market = json.loads(market_path.read_text(encoding="utf-8"))
    metadata = market.get("metadata", {}) or {}
    reference_date = _normalize_date(target_date or metadata.get("date") or metadata.get("end_date") or metadata.get("start_date"))
    fund_flow = market.setdefault("fund_flow", {})
    for key, series in series_map.items():
        if not series:
            continue
        series_local = list(series)
        if key == "northbound" and north_override is not None:
            series_local = apply_override(series_local, north_override, north_override_date or reference_date)
        recent_5d, full5, used_date, _ = compute_rollup(series_local, end_date=reference_date, window=5)
        total_120d, full120, used_date_120, _ = compute_rollup(series_local, end_date=reference_date, window=120)
        if recent_5d is None or total_120d is None:
            continue
        entry = fund_flow.get(key) if isinstance(fund_flow, dict) else None
        if not isinstance(entry, dict):
            entry = {"type": key}
            fund_flow[key] = entry

        entry["recent_5d"] = round(float(recent_5d), 2)
        entry["total_120d"] = round(float(total_120d), 2)
        entry["trend"] = "流入" if entry["recent_5d"] > 0 else "流出" if entry["recent_5d"] < 0 else "未知"

        anomaly = entry["recent_5d"] == 0 or entry["total_120d"] == 0
        entry["source"] = "异常零值-需核查" if anomaly else "MCP WebSearch实时获取"

        note_parts: List[str] = []
        existing_note = entry.get("note")
        if isinstance(existing_note, str) and existing_note:
            note_parts.append(existing_note)
        note_parts.append(f"来源:同花顺数据中心(日度净流入:{key})")
        if used_date_120 or used_date:
            note_parts.append(f"区间终止:{used_date_120 or used_date}")
        if key == "northbound" and north_override is not None:
            entry["current_value"] = round(float(north_override), 2)
            entry["current_date"] = north_override_date or reference_date
            source_label = north_override_source or "新闻口径"
            note_parts.append(f"当日值参考:{source_label}")
        if not full5 or not full120:
            note_parts.append("window不足已估计")
        entry["note"] = "；".join(note_parts)

    out_path = output_path or market_path
    out_path.write_text(json.dumps(market, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] market_data updated: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync fund_flow daily series from 10jqka")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR), help="trend_history base dir")
    parser.add_argument("--market-data", help="market_data JSON to update with 5d/120d rollups")
    parser.add_argument("--output", help="output path for updated market_data (default: overwrite)")
    parser.add_argument("--target-date", help="target date for rollup (YYYY-MM-DD)")
    parser.add_argument("--news-json", help="WebSearch manual JSON for northbound override")
    parser.add_argument("--northbound-news-value", help="override northbound daily value (亿元)")
    parser.add_argument("--northbound-news-date", help="override date (YYYY-MM-DD)")
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    series_map: Dict[str, List[Dict[str, float]]] = {}

    for key, flow_type in {"northbound": "north", "southbound": "south"}.items():
        try:
            series_map[key] = _fetch_ths_daily_series(flow_type)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] {key} daily series fetch failed: {exc}")
            series_map[key] = []

    north_override, north_override_date, north_override_source = None, None, None
    if args.news_json:
        override_val, override_date, override_source = _extract_news_override(Path(args.news_json))
        if override_val is not None:
            north_override = override_val
            north_override_date = override_date
            north_override_source = override_source

    if args.northbound_news_value:
        override_val = _parse_amount(args.northbound_news_value)
        if override_val is not None:
            north_override = override_val
            north_override_date = _normalize_date(args.northbound_news_date)

    total_writes = 0
    for key, series in series_map.items():
        if not series:
            continue
        series_local = list(series)
        if key == "northbound" and north_override is not None:
            series_local = apply_override(series_local, north_override, north_override_date)

        tail_series = series_local[-120:]
        source_label = "MCP WebSearch实时获取|同花顺数据中心日度净流入"
        total_writes += _write_series(key, tail_series, source=source_label, metric=None, base_dir=base_dir)

        roll5 = compute_rollup_series(series_local, window=5, keep=120)
        roll120 = compute_rollup_series(series_local, window=120, keep=120)

        roll5_records = [
            {"date": item["date"], "value": item["value"], "is_estimated": not item["full_window"]}
            for item in roll5
        ]
        roll120_records = [
            {"date": item["date"], "value": item["value"], "is_estimated": not item["full_window"]}
            for item in roll120
        ]

        total_writes += _write_series(
            f"{key}_recent_5d",
            roll5_records,
            source=source_label,
            metric="recent_5d",
            base_dir=base_dir,
        )
        total_writes += _write_series(
            f"{key}_total_120d",
            roll120_records,
            source=source_label,
            metric="total_120d",
            base_dir=base_dir,
        )

    print(f"[OK] trend_history writes: {total_writes}")

    if args.market_data:
        _update_market_data(
            Path(args.market_data),
            output_path=Path(args.output) if args.output else None,
            target_date=args.target_date,
            series_map=series_map,
            north_override=north_override,
            north_override_date=north_override_date,
            north_override_source=north_override_source,
        )


if __name__ == "__main__":
    main()
