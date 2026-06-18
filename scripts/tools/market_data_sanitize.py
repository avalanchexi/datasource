#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utility to scrub legacy market_data JSON files (remove 7.13/0 placeholders)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from datasource.utils.json_io import atomic_write_json


PLACEHOLDER_THRESHOLD = 1e-9
PLACEHOLDER_VALUE = 7.13


def _is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    try:
        val = float(value)
    except (TypeError, ValueError):
        return True
    if abs(val) < PLACEHOLDER_THRESHOLD:
        return True
    return abs(val - PLACEHOLDER_VALUE) < 1e-3


def _sanitize(payload: Dict[str, Any]) -> Tuple[int, int]:
    commodities = payload.get("commodities", [])
    bonds = payload.get("bonds", [])
    commodity_cleaned = 0
    bond_cleaned = 0

    for item in commodities:
        if _is_placeholder(item.get("current_price")):
            commodity_cleaned += 1
            item["current_price"] = None
            item["daily_change"] = None
            item["ytd_change"] = None
            item["trend"] = "待Stage2.5补数"
            item["source"] = "Stage2.5 manual_required"
            item["manual_required"] = True
            item["manual_reason"] = "placeholder_value_reset"

    for item in bonds:
        if _is_placeholder(item.get("current_yield")):
            bond_cleaned += 1
            item["current_yield"] = None
            item["change_5d_bp"] = None
            item["change_120d_bp"] = None
            item["trend"] = "待Stage2.5补数"
            item["source"] = "Stage2.5 manual_required"
            item["manual_required"] = True
            item["manual_reason"] = "placeholder_value_reset"
            item["is_estimated"] = False

    return commodity_cleaned, bond_cleaned


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrub legacy market_data JSON to remove 7.13 placeholders")
    parser.add_argument("input", help="market_data JSON file")
    parser.add_argument("--output", help="output path (default: overwrite input)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with input_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    commodity_cleaned, bond_cleaned = _sanitize(payload)
    target_path = Path(args.output).resolve() if args.output else input_path

    atomic_write_json(payload, target_path)

    print(f"[OK] 已写入 {target_path} (商品修正 {commodity_cleaned} 项, 债券修正 {bond_cleaned} 项)")


if __name__ == "__main__":
    main()
