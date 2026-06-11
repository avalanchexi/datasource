#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backfill missing date fields in trend_history events."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    events_dir = Path("data/trend_history/min/events")
    if not events_dir.exists():
        print("[WARN] events dir not found")
        return
    updated_files = 0
    for path in events_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        events = payload.get("events")
        if not isinstance(events, list):
            continue
        changed = False
        for item in events:
            if not isinstance(item, dict):
                continue
            if not item.get("release_date") and item.get("date"):
                item["release_date"] = item.get("date")
                changed = True
            if "date" not in item and item.get("release_date"):
                item["date"] = item.get("release_date")
                changed = True
        if changed:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            updated_files += 1
    print(f"[OK] backfilled event dates: {updated_files} files")


if __name__ == "__main__":
    main()
