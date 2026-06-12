#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick pre-check for Stage2 inputs.
Verifies: no legacy industrial_output key; missing_items keys exist in SEARCH_PROFILES.
Usage:
    python scripts/tools/stage2_check_inputs.py --market-data data/20251211_market_data.json
Exit code 0 if passed, non-zero otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from datasource.config.search_profiles import SEARCH_PROFILES


def _has_legacy_key(obj: Any, legacy_key: str) -> bool:
    if isinstance(obj, dict):
        if legacy_key in obj:
            return True
        return any(_has_legacy_key(v, legacy_key) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_legacy_key(v, legacy_key) for v in obj)
    return False


def _check_missing_items(data: Dict[str, Any]) -> List[str]:
    """Return unknown keys in missing_items (flattened)"""
    unknown: List[str] = []
    items = data.get("missing_items") or []
    for it in items:
        key = it.get("key") if isinstance(it, dict) else it
        if key not in SEARCH_PROFILES:
            unknown.append(str(key))
    return unknown


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-check Stage2 market data for legacy keys and missing_items.")
    parser.add_argument("--market-data", required=True, help="Path to market_data json")
    args = parser.parse_args()

    path = Path(args.market_data)
    if not path.exists():
        print(f"[ERROR] file not found: {path}", file=sys.stderr)
        return 2
    try:
        data = json.load(path.open("r", encoding="utf-8"))
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] failed to load json: {exc}", file=sys.stderr)
        return 2

    errors: List[str] = []
    if _has_legacy_key(data, "industrial_output"):
        errors.append("found legacy key industrial_output (should be industrial)")

    unknown = _check_missing_items(data)
    if unknown:
        errors.append(f"missing_items contain unknown keys: {', '.join(unknown)}")

    if errors:
        for e in errors:
            print(f"[FAIL] {e}", file=sys.stderr)
        return 1

    print("[OK] stage2 inputs passed pre-check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
