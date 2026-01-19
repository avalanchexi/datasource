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
    redlist = []
    for category, items in missing.items():
        for item in items:
            key = item.get("key") if isinstance(item, dict) else item
            if key and key.lower() in critical_keys:
                redlist.append({"key": key, "category": category})

    block_stage3 = bool(redlist)

    extract_422_threshold = rules.get("extract_422_threshold", 3)
    extract_422_count = 0
    if stage2_summary:
        extract_422_count = stage2_summary.get("tavily_extract_422_count", 0) or 0

    return {
        "generated_at": datetime.now().isoformat(),
        "date": metadata.get("date") or metadata.get("end_date") or metadata.get("start_date"),
        "redlist": redlist,
        "block_stage3": block_stage3,
        "extract_422_count": extract_422_count,
        "extract_422_threshold": extract_422_threshold,
        "recommend_disable_extract": extract_422_count >= extract_422_threshold,
    }


def write_policy_evaluation(payload: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
