#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Policy-as-code evaluation for Stage2/Stage3 gating."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_RULES = {
    "extract_422_threshold": 3,
    "extract_422_cooldown_sec": 300,
    "low_score_threshold": 0.2,
    "critical_missing_keys": ["dxy", "bdi", "rrr", "mlf"],
    "block_on_stale": True,
    "critical_stale_keys": ["cpi", "ppi", "pmi", "m1", "m2", "tsf"],
    "min_trading_days": 100,
}


def _simple_yaml_load(path: Path) -> Dict[str, Any]:
    """Minimal YAML loader (supports simple key: value and top-level lists)."""
    data: Dict[str, Any] = {}
    if not path.exists():
        return data
    current_key: Optional[str] = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line and not line.startswith("-"):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value == "":
                data[key] = []
                current_key = key
            else:
                # cast int if possible
                try:
                    data[key] = int(value)
                except Exception:
                    # cast float / bool if possible
                    lowered = value.lower()
                    if lowered in {"true", "false"}:
                        data[key] = lowered == "true"
                    else:
                        try:
                            data[key] = float(value)
                        except Exception:
                            data[key] = value
                current_key = None
        elif line.startswith("-") and current_key:
            item = line.lstrip("-").strip()
            data.setdefault(current_key, []).append(item)
    return data


def load_policy_rules(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or Path("config/policy_rules.yaml")
    rules = dict(DEFAULT_RULES)
    overrides = _simple_yaml_load(path)
    rules.update(overrides)
    return rules


def evaluate_policy(
    market_payload: Dict[str, Any],
    *,
    stage2_summary: Optional[Dict[str, Any]] = None,
    rules_path: Optional[Path] = None,
) -> Dict[str, Any]:
    rules = load_policy_rules(rules_path)
    metadata = market_payload.get("metadata", {}) if isinstance(market_payload, dict) else {}
    missing = metadata.get("missing_items", {}) if isinstance(metadata.get("missing_items", {}), dict) else {}

    critical_keys = set(k.lower() for k in rules.get("critical_missing_keys", []))
    critical_stale_keys = set(k.lower() for k in rules.get("critical_stale_keys", []))
    redlist = []
    for category, items in missing.items():
        for item in items:
            key = item.get("key") if isinstance(item, dict) else item
            if key and key.lower() in critical_keys:
                redlist.append({"key": key, "category": category})

    stale_redlist = []
    block_on_stale = bool(rules.get("block_on_stale", True))
    for category in ("macro_indicators", "monetary_policy"):
        section = market_payload.get(category, {})
        if not isinstance(section, dict):
            continue
        for key, payload in section.items():
            if not isinstance(payload, dict):
                continue
            if not payload.get("is_stale"):
                continue
            if key.lower() not in critical_stale_keys:
                continue
            stale_redlist.append(
                {
                    "key": key,
                    "category": category,
                    "date": payload.get("date"),
                    "expected_period": payload.get("expected_period"),
                    "reason": payload.get("stale_reason"),
                }
            )

    block_stage3 = bool(redlist) or (block_on_stale and bool(stale_redlist))

    extract_422_threshold = rules.get("extract_422_threshold", 3)
    extract_422_count = 0
    if stage2_summary:
        extract_422_count = stage2_summary.get("tavily_extract_422_count", 0) or 0

    return {
        "generated_at": datetime.now().isoformat(),
        "date": metadata.get("date") or metadata.get("end_date") or metadata.get("start_date"),
        "redlist": redlist,
        "stale_redlist": stale_redlist,
        "block_on_stale": block_on_stale,
        "block_stage3": block_stage3,
        "extract_422_count": extract_422_count,
        "extract_422_threshold": extract_422_threshold,
        "recommend_disable_extract": extract_422_count >= extract_422_threshold,
    }


def write_policy_evaluation(payload: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
