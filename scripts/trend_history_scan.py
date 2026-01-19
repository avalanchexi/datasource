#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scan trend_history coverage before Stage1 runs."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from datasource.utils.trend_history_store import scan_trend_history


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan trend_history gaps")
    parser.add_argument("--date", required=True, help="Target date (YYYY-MM-DD or YYYYMMDD)")
    parser.add_argument("--output", help="Output path for gap report JSON")
    args = parser.parse_args()

    date_str = args.date.strip()
    if len(date_str) == 8 and date_str.isdigit():
        date_str = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")

    result = scan_trend_history(date_str)

    if args.output:
        output_path = Path(args.output)
    else:
        date_compact = date_str.replace("-", "")
        output_path = Path("reports") / f"trend_history_gap_{date_compact}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[OK] trend_history gap report saved: {output_path}")


if __name__ == "__main__":
    main()
