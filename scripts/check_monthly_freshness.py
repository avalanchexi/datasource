#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage1 月度指标新鲜度快速检查。"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


PMI_KEYS = {"pmi", "pmi_new_orders", "pmi_production"}
DEFAULT_CHECKS = {
    "ppi": "macro_indicators",
    "cpi": "macro_indicators",
    "pmi": "macro_indicators",
    "m1": "monetary_policy",
    "m2": "monetary_policy",
    "tsf": "monetary_policy",
}


def _period_key(period: Optional[str]) -> Optional[int]:
    if not period:
        return None
    text = str(period).strip().replace("/", "-")
    if len(text) >= 7:
        text = text[:7]
    parts = text.split("-")
    if len(parts) != 2:
        return None
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError:
        return None
    if month < 1 or month > 12:
        return None
    return year * 12 + month


def _expected_period(run_date: datetime, indicator_key: str) -> str:
    key = indicator_key.lower()
    if key in PMI_KEYS:
        month_end = calendar.monthrange(run_date.year, run_date.month)[1]
        if run_date.day >= month_end:
            return f"{run_date.year}-{run_date.month:02d}"
    if key in {"cpi", "ppi", "m0", "m1", "m2", "tsf"}:
        lag_months = 1 if run_date.day >= 15 else 2
        target_year = run_date.year
        target_month = run_date.month - lag_months
        while target_month <= 0:
            target_year -= 1
            target_month += 12
        return f"{target_year}-{target_month:02d}"
    if run_date.month == 1:
        return f"{run_date.year - 1}-12"
    return f"{run_date.year}-{run_date.month - 1:02d}"


def _load_payload(data: Dict[str, Any], category: str, key: str) -> Dict[str, Any]:
    section = data.get(category, {})
    if not isinstance(section, dict):
        return {}
    payload = section.get(key)
    return payload if isinstance(payload, dict) else {}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查宏观/货币月度指标是否落后预期期次")
    parser.add_argument("market_data", help="market_data JSON 路径（通常是 Stage1 或 Stage2 结果）")
    parser.add_argument(
        "--date",
        default=None,
        help="覆盖运行日期(YYYY-MM-DD)。默认使用 metadata.date/end_date/start_date",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    path = Path(args.market_data).expanduser().resolve()
    if not path.exists():
        print(f"[ERROR] 文件不存在: {path}")
        return 1
    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    date_val = args.date or metadata.get("date") or metadata.get("end_date") or metadata.get("start_date")
    if not date_val:
        print("[ERROR] 无法识别运行日期，请通过 --date 指定")
        return 1
    try:
        run_date = datetime.strptime(str(date_val)[:10], "%Y-%m-%d")
    except ValueError:
        print(f"[ERROR] 日期格式错误: {date_val}")
        return 1

    print(f"[INFO] Freshness check date: {run_date.strftime('%Y-%m-%d')}")
    print("key\tactual\texpected\tstatus")

    stale_items = []
    for key, category in DEFAULT_CHECKS.items():
        item = _load_payload(payload, category, key)
        actual = str(item.get("date") or "-")
        actual_period = actual[:7] if len(actual) >= 7 else ""
        expected = str(item.get("expected_period") or _expected_period(run_date, key))
        actual_k = _period_key(actual_period)
        expected_k = _period_key(expected)
        status = "OK"
        if actual_k is None:
            status = "MISSING"
            stale_items.append((key, actual_period or "-", expected))
        elif expected_k is not None and actual_k < expected_k:
            status = "STALE"
            stale_items.append((key, actual_period, expected))
        print(f"{key}\t{actual_period or '-'}\t{expected}\t{status}")

    if stale_items:
        print("\n[WARN] 以下指标期次落后或缺失：")
        for key, actual, expected in stale_items:
            print(f"  - {key}: actual={actual}, expected={expected}")
        return 1
    print("\n[SUCCESS] 月度指标期次校验通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
