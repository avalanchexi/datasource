"""Shared low-level helpers for Stage2 split modules."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from datasource.utils.key_aliases import canonical_monetary_key


def _safe_number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


# 基于经验的合理区间，用于过滤明显离谱的抽取值（仅做人工复核标记）
_RANGE_RULES: Dict[str, tuple[float, float]] = {
    "USDCNY": (5.5, 9.5),
    "USDCNH": (5.5, 10.0),
    "DXY": (70.0, 140.0),
    "EURUSD": (0.5, 2.0),
    "GBPUSD": (0.8, 2.5),
    "USDJPY": (50.0, 200.0),
    "US10Y": (0.0, 15.0),
    "CN10Y": (0.0, 10.0),
    "CN10Y_CDB": (0.0, 12.0),
    "GC=F": (800.0, 5000.0),
    "CL=F": (0.1, 250.0),
    "BZ=F": (0.1, 250.0),
    "HG=F": (0.5, 8.0),
    "BCOM": (30.0, 300.0),
    "GSG": (10.0, 80.0),
    "bdi": (200.0, 10000.0),
    "rrr": (5.0, 20.0),
    "reverse_repo": (1.0, 5.0),
    "mlf": (1.5, 5.0),
}

_FOREX_UPSERT_META: Dict[str, str] = {
    "USDCNY": "USD/CNY在岸",
    "USDCNH": "USD/CNH离岸",
    "DXY": "DXY美元指数",
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
}

_COMMODITY_UPSERT_META: Dict[str, tuple[str, str]] = {
    "GC=F": ("COMEX黄金", "$/oz"),
    "CL=F": ("WTI原油", "$/barrel"),
    "BZ=F": ("Brent原油", "$/barrel"),
    "HG=F": ("COMEX铜", "$/lb"),
    "BCOM": ("BCOM指数", "点"),
    "GSG": ("GSG ETF", "USD"),
}

_BOND_UPSERT_META: Dict[str, str] = {
    "US10Y": "美国10年期国债",
    "CN10Y": "中国10年期国债",
    "CN10Y_CDB": "中国10年期国开债",
}


def _entry_for_task(
    market_payload: Dict[str, Any],
    task: Dict[str, Any],
    indicator_key: str,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    category = task.get("quality_gap_category") or task.get("category") or task.get("stage_phase")  # noqa: E501
    if category == "forex" or indicator_key in _FOREX_UPSERT_META:
        for item in market_payload.get("forex", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("pair") == indicator_key or item.get("symbol") == indicator_key:  # noqa: E501
                return "forex", item
    if category == "commodities" or indicator_key in _COMMODITY_UPSERT_META:
        for item in market_payload.get("commodities", []) or []:
            if isinstance(item, dict) and item.get("symbol") == indicator_key:
                return "commodities", item
    if category == "bonds" or indicator_key in _BOND_UPSERT_META:
        for item in market_payload.get("bonds", []) or []:
            if isinstance(item, dict) and item.get("symbol") == indicator_key:
                return "bonds", item
    if category == "macro_indicators":
        entry = market_payload.get("macro_indicators", {}).get(indicator_key)
        return category, entry if isinstance(entry, dict) else None
    if category == "monetary_policy":
        monetary_key = canonical_monetary_key(indicator_key)
        entry = market_payload.get("monetary_policy", {}).get(monetary_key)
        return category, entry if isinstance(entry, dict) else None
    if category == "fund_flow":
        entry = market_payload.get("fund_flow", {}).get(indicator_key)
        return category, entry if isinstance(entry, dict) else None
    return None, None


def _is_force_refresh_task(task: Dict[str, Any]) -> bool:
    return bool(task.get("force_refresh")) or str(task.get("trigger_reason") or "").lower() == "stale_data"  # noqa: E501
