#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recap consistency checker.

Use this script before writing a daily recap to avoid template-driven mistakes.
It summarizes facts from same-day files and outputs a JSON fact sheet.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from datasource.utils.json_io import load_json_optional
from datasource.utils.run_paths import build_run_paths


def _parse_date(date_str: Optional[str]) -> Tuple[str, str]:
    if not date_str:
        today = datetime.now().strftime("%Y-%m-%d")
        return today, today.replace("-", "")
    date_str = date_str.strip()
    if re.fullmatch(r"\d{8}", date_str):
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}", date_str
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return date_str, date_str.replace("-", "")
    raise ValueError(f"Invalid date format: {date_str} (expect YYYY-MM-DD or YYYYMMDD)")


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    payload = load_json_optional(path)
    return payload if isinstance(payload, dict) else None


def _find_first(paths: List[Path]) -> Optional[Path]:
    for path in paths:
        if path.exists():
            return path
    return None


def _count_na(text: str) -> int:
    return text.count("N/A（待 WebSearch）")


def _collect_estimated(market_data: Dict[str, Any]) -> List[str]:
    items: List[str] = []
    for key, indicator in (market_data.get("macro_indicators") or {}).items():
        if isinstance(indicator, dict) and indicator.get("is_estimated"):
            name = indicator.get("indicator_name") or key
            items.append(f"macro:{name}")
    for key, policy in (market_data.get("monetary_policy") or {}).items():
        if isinstance(policy, dict) and policy.get("is_estimated"):
            name = policy.get("policy_name") or key
            items.append(f"monetary:{name}")
    for bond in market_data.get("bonds", []) or []:
        if isinstance(bond, dict) and bond.get("is_estimated"):
            name = bond.get("name") or bond.get("symbol") or "bond"
            items.append(f"bonds:{name}")
    return items


def _summarize_missing(market_data: Dict[str, Any]) -> Dict[str, int]:
    missing = market_data.get("metadata", {}).get("missing_items")
    if not isinstance(missing, dict):
        return {}
    summary: Dict[str, int] = {}
    for key, items in missing.items():
        if isinstance(items, list):
            summary[key] = len(items)
    return summary


def _summarize_gap(gap_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not gap_payload:
        return {}
    return {
        "pending_tasks": gap_payload.get("pending_tasks") or [],
        "manual_required": gap_payload.get("manual_required") or [],
    }


def _summarize_stage2(stage2_log: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not stage2_log:
        return {}
    return {
        "task_total": stage2_log.get("task_total"),
        "task_completed": stage2_log.get("task_completed"),
        "task_failed": stage2_log.get("task_failed"),
        "tavily_extract_calls": stage2_log.get("tavily_extract_calls"),
        "extract_calls": stage2_log.get("extract_calls"),
        "extract_auto_disabled": stage2_log.get("extract_auto_disabled"),
        "exa_fallback": stage2_log.get("exa_fallback"),
        "exa_empty": stage2_log.get("exa_empty"),
        "manual_required": stage2_log.get("manual_required") or [],
        "flagged_fund_flow": stage2_log.get("flagged_fund_flow") or [],
        "fund_flow_backend": stage2_log.get("fund_flow_backend"),
        "output": stage2_log.get("output"),
    }


def _summarize_pring(pring_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not pring_payload:
        return {}
    return {
        "final_stage": pring_payload.get("final_stage"),
        "confidence": pring_payload.get("confidence"),
        "data_completeness": pring_payload.get("data_completeness"),
        "pending_websearch": pring_payload.get("pending_websearch") or [],
        "fallback_used": pring_payload.get("fallback_used"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Recap consistency check (fact sheet generator)")
    parser.add_argument("--date", help="Date in YYYY-MM-DD or YYYYMMDD; default today")
    parser.add_argument("--output", help="Output JSON path")
    args = parser.parse_args()

    date_ymd, date_compact = _parse_date(args.date)
    run_paths = build_run_paths(date_ymd)

    stage1_path = run_paths.market_data
    stage2_path = run_paths.market_data_stage2
    complete_path = run_paths.market_data_complete
    pring_path = run_paths.pring_result
    gap_path = run_paths.gap_monitor
    policy_path = run_paths.policy_evaluation
    stage2_log_path = _find_first(
        [
            run_paths.stage2_log,
            Path("logs") / f"stage2_unified_log_{date_compact}.json",
            Path("logs") / f"stage2_unified_log_{date_ymd}.json",
            Path("logs") / "stage2_unified_log.json",
        ]
    )
    report_path = _find_first(
        [
            Path("reports") / f"{date_compact}背景扫描120.md",
            Path("reports") / f"{date_ymd}背景扫描120.md",
            Path("reports") / f"{date_ymd}-背景扫描120.md",
            Path("reports") / f"{date_compact}-背景扫描120.md",
        ]
    )

    stage1_payload = _load_json(stage1_path)
    stage2_payload = _load_json(stage2_path)
    market_payload = _load_json(complete_path)
    pring_payload = _load_json(pring_path)
    gap_payload = _load_json(gap_path)
    policy_payload = _load_json(policy_path)
    stage2_log_payload = _load_json(stage2_log_path) if stage2_log_path else None

    report_text = report_path.read_text(encoding="utf-8") if report_path and report_path.exists() else ""

    facts: Dict[str, Any] = {
        "date": date_ymd,
        "paths": {
            "stage1": str(stage1_path) if stage1_path.exists() else None,
            "stage2": str(stage2_path) if stage2_path.exists() else None,
            "market_data_complete": str(complete_path) if complete_path.exists() else None,
            "pring_result": str(pring_path) if pring_path.exists() else None,
            "gap_monitor": str(gap_path) if gap_path.exists() else None,
            "policy_evaluation": str(policy_path) if policy_path.exists() else None,
            "stage2_log": str(stage2_log_path) if stage2_log_path else None,
            "report": str(report_path) if report_path else None,
        },
        "stage1": {
            "data_completeness": stage1_payload.get("metadata", {}).get("data_completeness")
            if stage1_payload else None
        },
        "stage2": _summarize_stage2(stage2_log_payload),
        "market_data_complete": {
            "data_completeness": market_payload.get("metadata", {}).get("data_completeness")
            if market_payload else None,
            "missing_items": _summarize_missing(market_payload) if market_payload else {},
            "estimated_items": _collect_estimated(market_payload) if market_payload else [],
        },
        "gap_monitor": _summarize_gap(gap_payload),
        "policy_evaluation": policy_payload or {},
        "pring_result": _summarize_pring(pring_payload),
        "report": {
            "contains_na": _count_na(report_text) > 0,
            "na_count": _count_na(report_text),
        },
        "warnings": [],
    }

    warnings: List[str] = []
    if not policy_payload:
        warnings.append("policy_evaluation_missing")
    if market_payload:
        if facts["market_data_complete"]["missing_items"]:
            warnings.append("metadata_missing_items_not_empty")
        if facts["market_data_complete"]["estimated_items"]:
            warnings.append("estimated_items_present")
    if report_text and facts["report"]["contains_na"]:
        warnings.append("report_contains_na")
    if stage2_log_payload:
        output_path = stage2_log_payload.get("output", "")
        if output_path and date_compact not in output_path:
            warnings.append("stage2_log_output_date_mismatch")

    facts["warnings"] = warnings

    output_path = Path(args.output) if args.output else run_paths.recap_facts
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[OK] recap fact sheet generated")
    print(f"  - date: {date_ymd}")
    print(f"  - output: {output_path}")
    if warnings:
        print(f"  - warnings: {', '.join(warnings)}")


if __name__ == "__main__":
    main()
