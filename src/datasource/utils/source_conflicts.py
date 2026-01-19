#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Collect source conflicts from websearch results."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .source_priority import source_weight


def _candidate_from_item(item: Dict[str, Any]) -> Dict[str, Any]:
    task = item.get("task") or {}
    extraction = item.get("extraction") or {}
    src_url = extraction.get("source_url") or ""
    conf = extraction.get("confidence")
    try:
        conf_val = float(conf) if conf is not None else 0.0
    except Exception:
        conf_val = 0.0
    return {
        "indicator_key": task.get("indicator_key"),
        "value": extraction.get("value"),
        "source_url": src_url,
        "confidence": conf_val,
        "weight": source_weight(src_url),
    }


def resolve_websearch_results(results: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in results:
        key = (item.get("task") or {}).get("indicator_key")
        if not key:
            continue
        grouped.setdefault(key, []).append(item)

    conflicts: List[Dict[str, Any]] = []
    deduped: List[Dict[str, Any]] = []

    for key, items in grouped.items():
        if len(items) == 1:
            deduped.append(items[0])
            continue
        candidates = [_candidate_from_item(it) for it in items]
        # filter numeric values
        numeric_vals = []
        for c in candidates:
            try:
                numeric_vals.append(float(c.get("value")))
            except Exception:
                pass
        is_conflict = len(set(numeric_vals)) > 1 if numeric_vals else False

        # choose by weight -> confidence
        ranked = sorted(
            zip(items, candidates),
            key=lambda pair: (pair[1]["weight"], pair[1]["confidence"]),
            reverse=True,
        )
        chosen_item, chosen_meta = ranked[0]
        deduped.append(chosen_item)

        if is_conflict:
            conflicts.append(
                {
                    "indicator_key": key,
                    "chosen": chosen_meta,
                    "candidates": candidates,
                }
            )

    payload = {"generated_at": datetime.now().isoformat(), "conflicts": conflicts}
    return deduped, payload


def write_source_conflicts(payload: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
