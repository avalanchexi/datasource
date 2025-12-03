#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare two Stage2 summary logs and print a small table/JSON."""
import json
import argparse
from pathlib import Path
from typing import Dict

KEYS = [
    "task_total",
    "task_completed",
    "task_failed",
    "cache_hit_rate",
    "domain_filtered_drop",
    "score_filtered_drop",
    "timeout_count",
    "retry_count",
    "extract_calls",
    "tavily_extract_calls",
    "avg_elapsed_ms",
]

def load(path: Path) -> Dict:
    return json.load(path.open())


def fmt(val):
    if isinstance(val, float):
        return f"{val:.3f}" if abs(val) < 10 else f"{val:.1f}"
    return str(val)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old", help="baseline stage2 log json")
    ap.add_argument("new", help="new stage2 log json")
    ap.add_argument("--json", action="store_true", help="output json diff")
    args = ap.parse_args()

    old = load(Path(args.old))
    new = load(Path(args.new))

    if args.json:
        out = {}
        for k in KEYS:
            out[k] = {"old": old.get(k), "new": new.get(k)}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("metric | old | new | delta")
    print("------ | --- | --- | -----")
    for k in KEYS:
        o = old.get(k)
        n = new.get(k)
        delta = None
        try:
            if isinstance(o, (int, float)) and isinstance(n, (int, float)):
                delta = n - o
        except Exception:
            pass
        print(f"{k} | {fmt(o)} | {fmt(n)} | {fmt(delta) if delta is not None else ''}")


if __name__ == "__main__":
    main()
