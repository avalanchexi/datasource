#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Minimal rolling-window storage for trend history (no SQLite).
Per-symbol files: data/trend_history/min/series/{category}/{symbol}.json
Event series: data/trend_history/min/events/{indicator}.json
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_BASE_DIR = Path("data/trend_history/min")
SERIES_DIR = "series"
EVENTS_DIR = "events"

# Rolling windows (trading days)
SERIES_WINDOWS = {
    "stock_indices": 200,
    "commodities": 121,
    "forex": 121,
    "bonds": 121,
    "fund_flow": 120,
    "macro_indicators": 121,
}

EVENTS_WINDOWS = {
    "macro_indicators": 24,
    "monetary_policy": 24,
}

# Daily macro indicators that should be stored as series as well
DAILY_MACRO_SERIES = {"bdi"}
# Daily monetary policy indicators (allow using record_date when date missing)
DAILY_MONETARY_KEYS = {"dr007"}


@dataclass
class SeriesRecord:
    date: str
    value: float
    unit: Optional[str] = None
    source: Optional[str] = None
    source_timestamp: Optional[str] = None
    market_calendar: Optional[str] = None
    is_estimated: bool = False
    is_partial: bool = False
    metric: Optional[str] = None


@dataclass
class EventRecord:
    release_date: str
    report_period: Optional[str]
    value: float
    unit: Optional[str]
    source: Optional[str]
    is_estimated: bool = False


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _safe_json_load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _safe_json_write(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_dir(path.parent)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _is_placeholder_numeric(value: Any) -> bool:
    if value in (None, "", "N/A"):
        return True
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return True
    if abs(numeric) < 1e-9:
        return True
    # Legacy placeholder 7.13
    return abs(numeric - 7.13) < 1e-3


def _is_valid_value(value: Any) -> bool:
    return not _is_placeholder_numeric(value)


def _has_low_quality_marker(source: str) -> bool:
    markers = (
        "数值超出合理区间",
        "异常零值-需核查",
        "异常零值",
        "数据超过",
        "需更新",
    )
    return any(marker in source for marker in markers)


def _should_skip_series_record(category: str, symbol: str, record: SeriesRecord) -> bool:
    if not _is_valid_value(record.value):
        return True
    source_text = str(record.source or "")
    source_lower = source_text.lower()

    if _has_low_quality_marker(source_text):
        return True

    if ("regex_only" in source_lower or "regex_fallback" in source_lower) and "缺少发布机构" in source_text:
        return True

    if category == "bonds" and symbol in {"CN10Y", "CN10Y_CDB"}:
        if record.unit == "ETF" or "bond_etf_proxy" in source_lower or "etf" in source_lower:
            return True
        # 防止 ETF 代理净值污染收益率序列（非硬性范围，只做明显异常兜底）
        if record.value > 20:
            return True

    return False


def _normalize_date(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return date_str[:10]


def _calendar_for_symbol(category: str, symbol: str) -> Optional[str]:
    if category in {"stock_indices", "fund_flow"}:
        return "CN"
    if category == "bonds" and symbol.startswith("US"):
        return "US"
    if category == "bonds" and symbol.startswith("CN"):
        return "CN"
    return "GLOBAL"


def _get_last_open_date_cn(target_date: str) -> Optional[str]:
    """Resolve last open trading day for CN calendar via TuShare trade_cal."""
    try:
        import tushare as ts  # local import to avoid hard dependency on import time
        token = None
        try:
            import os
            token = os.getenv("TUSHARE_TOKEN")
        except Exception:
            token = None
        pro = ts.pro_api(token) if token else ts.pro_api()
        end_dt = datetime.strptime(target_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=20)
        cal = pro.trade_cal(
            exchange="",
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=end_dt.strftime("%Y%m%d"),
        )
        open_dates = [str(d) for d in cal[cal.is_open == 1].cal_date]
        if not open_dates:
            return None
        last_open = max(open_dates)
        return datetime.strptime(last_open, "%Y%m%d").strftime("%Y-%m-%d")
    except Exception:
        return None


def _upsert_series(path: Path, symbol: str, record: SeriesRecord, window: int) -> None:
    payload = _safe_json_load(path)
    values = payload.get("values") if isinstance(payload.get("values"), list) else []
    by_date: Dict[str, Dict[str, Any]] = {}
    for item in values:
        if isinstance(item, dict) and item.get("date"):
            by_date[str(item.get("date"))] = item

    record_dict = {
        "date": record.date,
        "value": record.value,
        "unit": record.unit,
        "source": record.source,
        "source_timestamp": record.source_timestamp,
        "market_calendar": record.market_calendar,
        "is_estimated": bool(record.is_estimated),
        "is_partial": bool(record.is_partial),
    }
    if record.metric:
        record_dict["metric"] = record.metric

    by_date[record.date] = record_dict
    sorted_vals = sorted(by_date.values(), key=lambda x: x.get("date", ""))
    if window and len(sorted_vals) > window:
        sorted_vals = sorted_vals[-window:]

    payload = {
        "symbol": symbol,
        "values": sorted_vals,
    }
    _safe_json_write(path, payload)


def _upsert_event(path: Path, indicator: str, record: EventRecord, window: int) -> None:
    payload = _safe_json_load(path)
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    by_date: Dict[str, Dict[str, Any]] = {}
    for item in events:
        if isinstance(item, dict) and item.get("release_date"):
            if "date" not in item:
                item["date"] = item.get("release_date")
            by_date[str(item.get("release_date"))] = item

    by_date[record.release_date] = {
        "release_date": record.release_date,
        "date": record.release_date,
        "report_period": record.report_period,
        "value": record.value,
        "unit": record.unit,
        "source": record.source,
        "is_estimated": bool(record.is_estimated),
    }
    sorted_vals = sorted(by_date.values(), key=lambda x: x.get("release_date", ""))
    if window and len(sorted_vals) > window:
        sorted_vals = sorted_vals[-window:]

    payload = {
        "indicator": indicator,
        "events": sorted_vals,
    }
    _safe_json_write(path, payload)


def write_series_record(
    category: str,
    symbol: str,
    record: SeriesRecord,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> bool:
    window = SERIES_WINDOWS.get(category, 121)
    series_path = base_dir / SERIES_DIR / category / f"{symbol}.json"
    if _should_skip_series_record(category, symbol, record):
        return False
    _upsert_series(series_path, symbol, record, window)
    return True


def write_event_record(
    indicator: str,
    record: EventRecord,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
    window: Optional[int] = None,
) -> None:
    max_events = window or 12
    events_path = base_dir / EVENTS_DIR / f"{indicator}.json"
    _upsert_event(events_path, indicator, record, max_events)


def _resolve_source_timestamp(metadata: Dict[str, Any]) -> Optional[str]:
    for key in ("websearch_timestamp", "generation_time"):
        value = metadata.get(key)
        if value:
            return str(value)
    return datetime.now().isoformat()


def load_series_values(
    category: str,
    symbol: str,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> List[float]:
    """Load numeric series values for a given category/symbol."""
    series_path = base_dir / SERIES_DIR / category / f"{symbol}.json"
    payload = _safe_json_load(series_path)
    values = payload.get("values") if isinstance(payload.get("values"), list) else []
    sorted_vals = sorted(
        [item for item in values if isinstance(item, dict) and item.get("date")],
        key=lambda x: x.get("date", ""),
    )
    numeric = []
    for item in sorted_vals:
        try:
            numeric.append(float(item.get("value")))
        except (TypeError, ValueError):
            continue
    return numeric


def write_from_market_data(
    market_data: Dict[str, Any],
    *,
    is_partial: bool,
    source_path: Optional[Path] = None,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> int:
    """从 market_data 结构写入 trend_history，返回写入条目数。"""
    if source_path is not None:
        source_text = str(source_path).lower()
        if source_text.endswith(".md") or "/reports/" in source_text or "\\reports\\" in source_text:
            raise ValueError("trend_history write blocked: reports/*.md is not an allowed source")
    metadata = market_data.get("metadata", {}) if isinstance(market_data, dict) else {}
    record_date = metadata.get("date") or metadata.get("end_date") or metadata.get("start_date")
    record_date = _normalize_date(record_date)
    if not record_date:
        record_date = datetime.now().strftime("%Y-%m-%d")

    source_timestamp = _resolve_source_timestamp(metadata)
    writes = 0

    # stock indices
    for item in market_data.get("stock_indices", []) or []:
        value = item.get("current_price")
        if not _is_valid_value(value):
            continue
        symbol = str(item.get("symbol"))
        record = SeriesRecord(
            date=record_date,
            value=float(value),
            unit=None,
            source=item.get("source"),
            source_timestamp=source_timestamp,
            market_calendar=_calendar_for_symbol("stock_indices", symbol),
            is_estimated=bool(item.get("is_estimated", False)),
            is_partial=is_partial,
        )
        if write_series_record("stock_indices", symbol, record, base_dir=base_dir):
            writes += 1

    # commodities
    for item in market_data.get("commodities", []) or []:
        value = item.get("current_price")
        if not _is_valid_value(value):
            continue
        symbol = str(item.get("symbol"))
        record = SeriesRecord(
            date=record_date,
            value=float(value),
            unit=item.get("unit"),
            source=item.get("source"),
            source_timestamp=source_timestamp,
            market_calendar=_calendar_for_symbol("commodities", symbol),
            is_estimated=bool(item.get("is_estimated", False)),
            is_partial=is_partial,
        )
        if write_series_record("commodities", symbol, record, base_dir=base_dir):
            writes += 1

    # forex
    for item in market_data.get("forex", []) or []:
        value = item.get("current_rate")
        if not _is_valid_value(value):
            continue
        symbol = str(item.get("pair"))
        record = SeriesRecord(
            date=record_date,
            value=float(value),
            unit=None,
            source=item.get("source"),
            source_timestamp=source_timestamp,
            market_calendar=_calendar_for_symbol("forex", symbol),
            is_estimated=bool(item.get("is_estimated", False)),
            is_partial=is_partial,
        )
        if write_series_record("forex", symbol, record, base_dir=base_dir):
            writes += 1

    # bonds
    for item in market_data.get("bonds", []) or []:
        value = item.get("current_yield")
        if not _is_valid_value(value):
            continue
        symbol = str(item.get("symbol"))
        record = SeriesRecord(
            date=record_date,
            value=float(value),
            unit="%",
            source=item.get("source"),
            source_timestamp=source_timestamp,
            market_calendar=_calendar_for_symbol("bonds", symbol),
            is_estimated=bool(item.get("is_estimated", False)),
            is_partial=is_partial,
        )
        if write_series_record("bonds", symbol, record, base_dir=base_dir):
            writes += 1

    # fund flow (store recent_5d / total_120d as separate metrics)
    fund_flow = market_data.get("fund_flow", {}) or {}
    if isinstance(fund_flow, dict):
        for key, item in fund_flow.items():
            if not isinstance(item, dict):
                continue
            for metric in ("recent_5d", "total_120d"):
                value = item.get(metric)
                if not _is_valid_value(value):
                    continue
                symbol = f"{key}_{metric}"
                record = SeriesRecord(
                    date=record_date,
                    value=float(value),
                    unit="亿元",
                    source=item.get("source"),
                    source_timestamp=source_timestamp,
                    market_calendar=_calendar_for_symbol("fund_flow", key),
                    is_estimated=False,
                    is_partial=is_partial,
                    metric=metric,
                )
                if write_series_record("fund_flow", symbol, record, base_dir=base_dir):
                    writes += 1

    # macro indicators (event series)
    for key, item in (market_data.get("macro_indicators", {}) or {}).items():
        if not isinstance(item, dict):
            continue
        value = item.get("current_value")
        if not _is_valid_value(value):
            continue
        raw_date = item.get("as_of_date") or item.get("report_period") or item.get("date")
        if not raw_date:
            # 非日更宏观指标缺少发布日期时，避免写入“当天”占位日期
            if key in DAILY_MACRO_SERIES:
                raw_date = record_date
            else:
                continue
        release_date = _normalize_date(raw_date)
        record = EventRecord(
            release_date=release_date,
            report_period=item.get("report_period") or item.get("as_of_date") or item.get("date") or release_date,
            value=float(value),
            unit=item.get("unit"),
            source=item.get("source"),
            is_estimated=bool(item.get("is_estimated", False)),
        )
        window = EVENTS_WINDOWS.get("macro_indicators", 12)
        write_event_record(key, record, base_dir=base_dir, window=window)
        writes += 1

        if key in DAILY_MACRO_SERIES:
            series_record = SeriesRecord(
                date=record_date,
                value=float(value),
                unit=item.get("unit"),
                source=item.get("source"),
                source_timestamp=source_timestamp,
                market_calendar=_calendar_for_symbol("macro_indicators", key),
                is_estimated=bool(item.get("is_estimated", False)),
                is_partial=is_partial,
            )
            if write_series_record("macro_indicators", key, series_record, base_dir=base_dir):
                writes += 1

    # monetary policy (event series)
    for key, item in (market_data.get("monetary_policy", {}) or {}).items():
        if not isinstance(item, dict):
            continue
        value = item.get("current_value")
        if not _is_valid_value(value):
            continue
        raw_date = item.get("as_of_date") or item.get("report_period") or item.get("date")
        if not raw_date:
            # 非日更政策指标缺少发布日期时，避免写入“当天”占位日期
            if key in DAILY_MONETARY_KEYS:
                raw_date = record_date
            else:
                continue
        release_date = _normalize_date(raw_date)
        record = EventRecord(
            release_date=release_date,
            report_period=item.get("report_period") or item.get("as_of_date") or item.get("date") or release_date,
            value=float(value),
            unit=item.get("unit"),
            source=item.get("source"),
            is_estimated=bool(item.get("is_estimated", False)),
        )
        window = EVENTS_WINDOWS.get("monetary_policy", 12)
        write_event_record(key, record, base_dir=base_dir, window=window)
        writes += 1

    return writes


def scan_trend_history(
    target_date: str,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    """扫描 trend_history 缺口（按窗口长度/最新日期），返回结果字典。"""
    target_date = _normalize_date(target_date)
    results: Dict[str, Any] = {
        "date": target_date,
        "series": {"missing": [], "insufficient": [], "stale": []},
        "events": {"missing": [], "insufficient": []},
    }

    last_open_cn = _get_last_open_date_cn(target_date) if target_date else None

    # series scan
    series_dir = base_dir / SERIES_DIR
    for category, window in SERIES_WINDOWS.items():
        category_dir = series_dir / category
        if not category_dir.exists():
            results["series"]["missing"].append({"category": category, "reason": "dir_missing"})
            continue
        for path in category_dir.glob("*.json"):
            payload = _safe_json_load(path)
            values = payload.get("values") if isinstance(payload.get("values"), list) else []
            if not values:
                results["series"]["missing"].append({"category": category, "symbol": path.stem, "reason": "empty"})
                continue
            if len(values) < window:
                results["series"]["insufficient"].append(
                    {"category": category, "symbol": path.stem, "count": len(values), "required": window}
                )
            last_date = str(values[-1].get("date")) if isinstance(values[-1], dict) else None
            if last_date and target_date:
                expected_date = target_date
                if category in {"stock_indices", "fund_flow"}:
                    expected_date = last_open_cn or target_date
                if category == "bonds" and path.stem.startswith("CN"):
                    expected_date = last_open_cn or target_date
                if last_date < expected_date:
                    results["series"]["stale"].append(
                        {
                            "category": category,
                            "symbol": path.stem,
                            "last_date": last_date,
                            "target_date": expected_date,
                        }
                    )

    # events scan
    events_dir = base_dir / EVENTS_DIR
    if events_dir.exists():
        for path in events_dir.glob("*.json"):
            payload = _safe_json_load(path)
            events = payload.get("events") if isinstance(payload.get("events"), list) else []
            if not events:
                results["events"]["missing"].append({"indicator": path.stem, "reason": "empty"})
                continue
            if len(events) < 6:
                results["events"]["insufficient"].append(
                    {"indicator": path.stem, "count": len(events), "required": 6}
                )
    else:
        results["events"]["missing"].append({"reason": "dir_missing"})

    return results
