#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Observability log builder for Stage2 execution."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from datasource.utils.json_io import atomic_write_json


def build_observability_log(
    tasks: List[Dict[str, Any]],
    completed: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
    pending_keys: List[str],
) -> Dict[str, Any]:
    index: Dict[str, Dict[str, Any]] = {}

    for task in tasks:
        key = task.get("indicator_key")
        if not key:
            continue
        index[key] = {
            "indicator_key": key,
            "stage_phase": task.get("stage_phase"),
            "category": task.get("stage_category"),
            "search_backend": task.get("search_backend"),
            "preferred_domains": task.get("preferred_domains"),
            "status": "pending" if key in pending_keys else "planned",
        }

    for item in completed:
        key = item.get("indicator_key")
        if not key:
            continue
        base = index.get(key, {"indicator_key": key})
        base.update(
            {
                "status": "skipped_existing" if item.get("result_type") == "skipped_existing" else "success",
                "elapsed_ms": item.get("elapsed_ms"),
                "search_backend": item.get("search_backend"),
                "extraction_backend": item.get("extraction_backend"),
                "cache_hit": item.get("cache_hit"),
                "result_type": item.get("result_type"),
            }
        )
        for field in (
            "score_min",
            "score_p50",
            "score_p95",
            "score_max",
            "score_count",
            "score_low_threshold",
            "score_low_all",
            "score_filtered_drop",
            "domain_filtered_drop",
            "extraction_skipped_reason",
            "extract_skipped_reason",
        ):
            if field in item:
                base[field] = item.get(field)
        index[key] = base

    for item in failures:
        key = item.get("indicator_key")
        if not key:
            continue
        base = index.get(key, {"indicator_key": key})
        error_text = str(item.get("error") or item.get("llm_error") or "").lower()
        failure_type = None
        if "422" in error_text:
            failure_type = "422"
        elif "timeout" in error_text:
            failure_type = "timeout"
        elif "empty" in error_text or "no_value" in error_text:
            failure_type = "empty"
        elif "parse" in error_text:
            failure_type = "parse_error"
        base.update(
            {
                "status": "failed",
                "elapsed_ms": item.get("elapsed_ms"),
                "search_backend": item.get("search_backend"),
                "error": item.get("error") or item.get("llm_error"),
                "failure_type": failure_type,
                "manual_required": item.get("manual_required", False),
                "result_type": item.get("result_type"),
            }
        )
        for field in (
            "score_min",
            "score_p50",
            "score_p95",
            "score_max",
            "score_count",
            "score_low_threshold",
            "score_low_all",
            "score_filtered_drop",
            "domain_filtered_drop",
            "extraction_skipped_reason",
            "extract_skipped_reason",
        ):
            if field in item:
                base[field] = item.get(field)
        index[key] = base

    items = list(index.values())
    return {
        "generated_at": datetime.now().isoformat(),
        "items": items,
    }


def write_observability_log(payload: Dict[str, Any], output_path: Path) -> None:
    atomic_write_json(payload, output_path)
