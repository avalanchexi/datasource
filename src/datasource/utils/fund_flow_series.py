#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilities for fund_flow daily series and rollups."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .trend_history_store import DEFAULT_BASE_DIR


def _normalize_date(date_str: Optional[str]) -> str:
    if not date_str:
        return ""
    text = str(date_str)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return text


def _safe_json_load(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_daily_series(symbol: str, *, base_dir: Path = DEFAULT_BASE_DIR) -> List[Dict[str, float]]:
    """Load fund_flow daily series (date/value) from trend_history."""
    series_path = base_dir / "series" / "fund_flow" / f"{symbol}.json"
    payload = _safe_json_load(series_path)
    values = payload.get("values") if isinstance(payload.get("values"), list) else []
    records: List[Dict[str, float]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        date = _normalize_date(item.get("date"))
        if not date:
            continue
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        records.append({"date": date, "value": value})
    records.sort(key=lambda x: x["date"])
    return records


def apply_override(
    series: List[Dict[str, float]],
    override_value: Optional[float],
    override_date: Optional[str] = None,
) -> List[Dict[str, float]]:
    """Apply an override value to the series at a specific date (default: latest)."""
    if override_value is None:
        return series
    override_date = _normalize_date(override_date) if override_date else ""
    if not series:
        if override_date:
            return [{"date": override_date, "value": float(override_value)}]
        return series

    target_date = override_date or series[-1]["date"]
    updated = list(series)
    for idx, item in enumerate(updated):
        if item.get("date") == target_date:
            updated[idx] = {"date": target_date, "value": float(override_value)}
            break
    else:
        if target_date > updated[-1]["date"]:
            updated.append({"date": target_date, "value": float(override_value)})
    return updated


def resolve_end_date(series: List[Dict[str, float]], end_date: Optional[str]) -> Optional[str]:
    """Pick the last available date <= end_date (or the latest date)."""
    if not series:
        return None
    if not end_date:
        return series[-1]["date"]
    end_date = _normalize_date(end_date)
    eligible = [item["date"] for item in series if item["date"] <= end_date]
    return eligible[-1] if eligible else series[-1]["date"]


def compute_rollup(
    series: List[Dict[str, float]],
    *,
    end_date: Optional[str],
    window: int,
) -> Tuple[Optional[float], bool, Optional[str], int]:
    """Compute rolling sum up to end_date; returns (value, full_window, used_date, count)."""
    if not series or window <= 0:
        return None, False, None, 0
    used_date = resolve_end_date(series, end_date)
    if not used_date:
        return None, False, None, 0
    values = [item["value"] for item in series if item["date"] <= used_date]
    if not values:
        return None, False, None, 0
    count = min(window, len(values))
    total = sum(values[-count:])
    full_window = len(values) >= window
    return total, full_window, used_date, count


def compute_rollup_series(
    series: List[Dict[str, float]],
    *,
    window: int,
    keep: int = 120,
) -> List[Dict[str, object]]:
    """Compute rolling sums for each day, keeping the latest `keep` entries."""
    if not series or window <= 0:
        return []
    values = [item["value"] for item in series]
    dates = [item["date"] for item in series]
    prefix = [0.0]
    for val in values:
        prefix.append(prefix[-1] + float(val))
    start_idx = max(0, len(values) - keep)
    rollups: List[Dict[str, object]] = []
    for idx in range(start_idx, len(values)):
        start = max(0, idx - window + 1)
        total = prefix[idx + 1] - prefix[start]
        count = idx - start + 1
        full_window = count == window
        rollups.append({"date": dates[idx], "value": total, "full_window": full_window, "count": count})
    return rollups
