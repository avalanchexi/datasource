#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quality metrics builder for market_data payload."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load_thresholds(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_float(val: Any) -> float:
    try:
        return float(val)
    except Exception:
        return 0.0


def _is_filled(val: Any) -> bool:
    if val in (None, "", "N/A"):
        return False
    try:
        return abs(float(val)) > 1e-9
    except Exception:
        return False


def _count_filled(items: List[Any], key: str) -> Tuple[int, int]:
    total = len(items)
    filled = 0
    for item in items:
        if isinstance(item, dict) and _is_filled(item.get(key)):
            filled += 1
    return filled, total


def _source_level(source: str) -> str:
    src = (source or "").lower()
    if "tushare" in src or "人民银行" in src or "stats.gov" in src:
        return "S"
    if "mcp" in src or "websearch" in src or "investing" in src or "reuters" in src:
        return "A"
    if src:
        return "B"
    return "unknown"


def build_quality_metrics(market_payload: Dict[str, Any]) -> Dict[str, Any]:
    metadata = market_payload.get("metadata", {}) if isinstance(market_payload, dict) else {}
    date_val = metadata.get("date") or metadata.get("end_date") or metadata.get("start_date")
    date_val = str(date_val) if date_val else datetime.now().strftime("%Y-%m-%d")

    # completeness
    completeness_by_category: Dict[str, Any] = {}

    filled, total = _count_filled(market_payload.get("commodities", []) or [], "current_price")
    completeness_by_category["commodities"] = {"filled": filled, "total": total}

    filled, total = _count_filled(market_payload.get("forex", []) or [], "current_rate")
    completeness_by_category["forex"] = {"filled": filled, "total": total}

    filled, total = _count_filled(market_payload.get("bonds", []) or [], "current_yield")
    completeness_by_category["bonds"] = {"filled": filled, "total": total}

    filled, total = _count_filled(market_payload.get("stock_indices", []) or [], "current_price")
    completeness_by_category["stock_indices"] = {"filled": filled, "total": total}

    fund_flow = market_payload.get("fund_flow", {}) or {}
    ff_total = len(fund_flow)
    ff_filled = 0
    for item in fund_flow.values():
        if isinstance(item, dict) and _is_filled(item.get("recent_5d")) and _is_filled(item.get("total_120d")):
            ff_filled += 1
    completeness_by_category["fund_flow"] = {"filled": ff_filled, "total": ff_total}

    macro = market_payload.get("macro_indicators", {}) or {}
    macro_total = len(macro)
    macro_filled = 0
    for item in macro.values():
        if isinstance(item, dict) and _is_filled(item.get("current_value")):
            macro_filled += 1
    completeness_by_category["macro_indicators"] = {"filled": macro_filled, "total": macro_total}

    monetary = market_payload.get("monetary_policy", {}) or {}
    monetary_total = len(monetary)
    monetary_filled = 0
    for item in monetary.values():
        if isinstance(item, dict) and _is_filled(item.get("current_value")):
            monetary_filled += 1
    completeness_by_category["monetary_policy"] = {"filled": monetary_filled, "total": monetary_total}

    totals = sum(v["total"] for v in completeness_by_category.values())
    filled_all = sum(v["filled"] for v in completeness_by_category.values())
    data_completeness = round(filled_all / totals, 4) if totals else 1.0

    # anomalies
    anomalies: List[Dict[str, Any]] = []
    for key, item in fund_flow.items():
        if not isinstance(item, dict):
            continue
        recent = item.get("recent_5d")
        total_val = item.get("total_120d")
        if not _is_filled(recent) or not _is_filled(total_val):
            anomalies.append({"category": "fund_flow", "key": key, "reason": "missing_or_zero"})

    stale_items: List[Dict[str, Any]] = []
    stale_by_category: Dict[str, int] = {"macro_indicators": 0, "monetary_policy": 0}
    for category in ("macro_indicators", "monetary_policy"):
        section = market_payload.get(category, {}) or {}
        if not isinstance(section, dict):
            continue
        for key, item in section.items():
            if not isinstance(item, dict):
                continue
            if not item.get("is_stale"):
                continue
            stale_items.append(
                {
                    "category": category,
                    "key": key,
                    "date": item.get("date"),
                    "expected_period": item.get("expected_period"),
                    "reason": item.get("stale_reason"),
                }
            )
            stale_by_category[category] = stale_by_category.get(category, 0) + 1

    # volatility threshold checks (simple)
    thresholds = _load_thresholds(Path("config/quality_thresholds.json"))
    vol_pct = thresholds.get("volatility_pct", {}) if isinstance(thresholds.get("volatility_pct"), dict) else {}
    bond_bp = thresholds.get("bond_bp", {}) if isinstance(thresholds.get("bond_bp"), dict) else {}

    com_limit = _safe_float(vol_pct.get("commodities"))
    if com_limit:
        for item in market_payload.get("commodities", []) or []:
            if not isinstance(item, dict):
                continue
            daily = item.get("daily_change")
            if daily is not None and abs(_safe_float(daily)) > com_limit:
                anomalies.append({"category": "commodities", "key": item.get("symbol"), "reason": "daily_change_spike"})

    fx_limit = _safe_float(vol_pct.get("forex"))
    if fx_limit:
        for item in market_payload.get("forex", []) or []:
            if not isinstance(item, dict):
                continue
            daily = item.get("daily_change")
            if daily is not None and abs(_safe_float(daily)) > fx_limit:
                anomalies.append({"category": "forex", "key": item.get("pair"), "reason": "daily_change_spike"})

    idx_limit = _safe_float(vol_pct.get("stock_indices"))
    if idx_limit:
        for item in market_payload.get("stock_indices", []) or []:
            if not isinstance(item, dict):
                continue
            chg5 = item.get("change_5d")
            if chg5 is not None and abs(_safe_float(chg5)) > idx_limit:
                anomalies.append({"category": "stock_indices", "key": item.get("symbol"), "reason": "change_5d_spike"})

    bond_limit = _safe_float(bond_bp.get("bonds"))
    if bond_limit:
        for item in market_payload.get("bonds", []) or []:
            if not isinstance(item, dict):
                continue
            chg5 = item.get("change_5d_bp")
            if chg5 is not None and abs(_safe_float(chg5)) > bond_limit:
                anomalies.append({"category": "bonds", "key": item.get("symbol"), "reason": "change_5d_bp_spike"})

    # source levels
    source_levels: Dict[str, int] = {"S": 0, "A": 0, "B": 0, "unknown": 0}
    def _count_sources(items: List[Dict[str, Any]], key: str) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            level = _source_level(item.get(key) or item.get("source") or "")
            source_levels[level] = source_levels.get(level, 0) + 1

    _count_sources(market_payload.get("commodities", []) or [], "source")
    _count_sources(market_payload.get("forex", []) or [], "source")
    _count_sources(market_payload.get("bonds", []) or [], "source")
    _count_sources(market_payload.get("stock_indices", []) or [], "source")

    for item in macro.values():
        if isinstance(item, dict):
            level = _source_level(item.get("source", ""))
            source_levels[level] = source_levels.get(level, 0) + 1
    for item in monetary.values():
        if isinstance(item, dict):
            level = _source_level(item.get("source", ""))
            source_levels[level] = source_levels.get(level, 0) + 1

    return {
        "date": date_val,
        "generated_at": datetime.now().isoformat(),
        "data_completeness": data_completeness,
        "completeness_by_category": completeness_by_category,
        "missing_items": metadata.get("missing_items", {}),
        "anomalies": anomalies,
        "stale_count": len(stale_items),
        "stale_items": stale_items,
        "stale_by_category": stale_by_category,
        "source_levels": source_levels,
        "thresholds": thresholds,
    }


def write_quality_metrics(market_payload: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_quality_metrics(market_payload)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # Append trend CSV (optional)
    try:
        trend_path = output_path.parent / "quality_trend.csv"
        header = "date,data_completeness,filled,total\n"
        filled = sum(v.get("filled", 0) for v in payload.get("completeness_by_category", {}).values())
        total = sum(v.get("total", 0) for v in payload.get("completeness_by_category", {}).values())
        line = f"{payload.get('date')},{payload.get('data_completeness')},{filled},{total}\n"
        if not trend_path.exists():
            trend_path.write_text(header, encoding="utf-8")
        with trend_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
