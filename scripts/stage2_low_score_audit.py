#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit low-score tasks that still entered extraction."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from datasource.utils.json_io import load_json_optional
from datasource.utils.policy_rules import load_policy_rules
from datasource.utils.run_paths import build_run_paths


def _parse_date(date_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not date_str:
        return None, None
    date_str = date_str.strip()
    if re.fullmatch(r"\d{8}", date_str):
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}", date_str
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return date_str, date_str.replace("-", "")
    raise ValueError(f"Invalid date format: {date_str} (expect YYYY-MM-DD or YYYYMMDD)")


def _find_latest_observability() -> Optional[Path]:
    logs_root = Path("logs") / "runs"
    if not logs_root.exists():
        return None
    candidates = sorted(logs_root.glob("*/observability.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    payload = load_json_optional(path)
    return payload if isinstance(payload, dict) else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit low-score tasks that still entered extraction")
    parser.add_argument("--date", help="Date in YYYY-MM-DD or YYYYMMDD; default latest observability file")
    parser.add_argument("--threshold", type=float, help="Low-score threshold override")
    parser.add_argument("--output", help="Output JSON path (optional)")
    args = parser.parse_args()

    date_ymd, date_compact = _parse_date(args.date)
    obs_path = build_run_paths(date_ymd).observability if date_ymd else _find_latest_observability()
    if not obs_path or not obs_path.exists():
        print("[ERROR] observability log not found.")
        return

    payload = _load_json(obs_path)
    if not payload:
        print("[ERROR] failed to parse observability log.")
        return

    rules = load_policy_rules()
    threshold = args.threshold if args.threshold is not None else float(rules.get("low_score_threshold", 0.2))

    items = payload.get("items") or []
    scored_items = [
        item for item in items
        if isinstance(item, dict)
        and item.get("score_count")
        and isinstance(item.get("score_max"), (int, float))
    ]
    low_score_items = [i for i in scored_items if i.get("score_max") < threshold]
    low_score_entered = [
        i for i in low_score_items if i.get("extraction_skipped_reason") != "low_score_all"
    ]
    ratio = (len(low_score_entered) / len(low_score_items)) if low_score_items else 0.0

    offenders = []
    for item in low_score_entered:
        offenders.append(
            {
                "indicator_key": item.get("indicator_key"),
                "status": item.get("status"),
                "score_max": item.get("score_max"),
                "score_p50": item.get("score_p50"),
                "search_backend": item.get("search_backend"),
                "extraction_skipped_reason": item.get("extraction_skipped_reason"),
            }
        )

    report = {
        "generated_at": datetime.now().isoformat(),
        "date": date_ymd,
        "observability_path": str(obs_path),
        "threshold": threshold,
        "total_with_scores": len(scored_items),
        "low_score_total": len(low_score_items),
        "low_score_entered_extract": len(low_score_entered),
        "low_score_entered_ratio": round(ratio, 4),
        "offenders": offenders,
    }

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
