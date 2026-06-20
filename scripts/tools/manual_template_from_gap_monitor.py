#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a WebSearch manual JSON skeleton from gap_monitor issues."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from datasource.utils.key_aliases import canonical_monetary_key  # noqa: E402
from datasource.utils.manual_fallback_policies import (  # noqa: E402
    NUMERIC_MANUAL_FIELDS,
    PREFILL_FIELDS,
    load_manual_fallback_policies,
    policy_id,
)


FLOW_KEYS = {"northbound", "southbound", "etf", "margin"}
LIST_SECTION_KEY_FIELDS = {
    "bonds": "symbol",
    "commodities": "symbol",
    "forex": "pair",
    "stock_indices": "symbol",
}


def _safe_load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _find_market_item(section: Any, key: str, field: str) -> Optional[Any]:
    if isinstance(section, dict):
        return section.get(key, {}).get(field)
    if isinstance(section, list):
        for item in section:
            if not isinstance(item, dict):
                continue
            if item.get("symbol") == key or item.get("pair") == key:
                return item.get(field)
    return None


def _find_market_name(section: Any, key: str, fallback: str) -> str:
    if isinstance(section, dict):
        item = section.get(key)
        if isinstance(item, dict):
            return (
                item.get("name")
                or item.get("indicator_name")
                or item.get("policy_name")
                or fallback
            )
    if isinstance(section, list):
        for item in section:
            if not isinstance(item, dict):
                continue
            if item.get("symbol") == key or item.get("pair") == key:
                return item.get("name") or fallback
    return fallback


def _lookup_policy(
    policies: Mapping[str, Dict[str, Any]], category: str, key: str
) -> Optional[Dict[str, Any]]:
    candidates = [policy_id(category, key)]
    if category == "monetary_policy":
        candidates.append(policy_id(category, canonical_monetary_key(key)))
    for candidate in candidates:
        policy = policies.get(candidate)
        if policy is not None:
            return policy
    return None


def _prefill_entry(
    category: str,
    key: str,
    entry: Dict[str, Any],
    policy: Mapping[str, Any],
) -> Dict[str, Any]:
    """Apply provenance-only defaults to one manual skeleton entry."""

    before_numeric = {
        field: entry.get(field)
        for field in NUMERIC_MANUAL_FIELDS
        if field in entry
    }

    for field in PREFILL_FIELDS:
        if field == "source_url":
            value = policy.get("source_url_template")
        else:
            value = policy.get(field)
        if value is None:
            continue
        entry[field] = value

    entry["_manual_fallback_policy"] = policy_id(
        str(policy.get("category") or category),
        str(policy.get("key") or key),
    )
    for field, value in before_numeric.items():
        entry[field] = value
    return entry


def _apply_policies(
    template: Dict[str, Any],
    policies: Optional[Mapping[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Prefill manual skeleton provenance for entries already present."""

    if policies is None:
        resolved = load_manual_fallback_policies()
    else:
        resolved = policies
    for category in ("macro_indicators", "monetary_policy", "fund_flow"):
        section = template.get(category)
        if not isinstance(section, dict):
            continue
        for key, entry in section.items():
            if not isinstance(entry, dict):
                continue
            policy = _lookup_policy(resolved, category, str(key))
            if policy is None:
                continue
            _prefill_entry(category, str(key), entry, policy)

    for category, key_field in LIST_SECTION_KEY_FIELDS.items():
        section = template.get(category)
        if not isinstance(section, list):
            continue
        for entry in section:
            if not isinstance(entry, dict):
                continue
            key = entry.get(key_field)
            if not key:
                continue
            policy = _lookup_policy(resolved, category, str(key))
            if policy is None:
                continue
            _prefill_entry(category, str(key), entry, policy)

    return template


def _build_template(
    gap_payload: Dict[str, Any],
    market_payload: Optional[Dict[str, Any]] = None,
    *,
    report_date: Optional[str] = None,
) -> Dict[str, Any]:
    template: Dict[str, Any] = {
        "metadata": {
            "date": report_date or datetime.now().strftime("%Y-%m-%d")
        },
        "bonds": [],
        "commodities": [],
        "forex": [],
        "fund_flow": {},
        "macro_indicators": {},
        "monetary_policy": {},
    }

    market_payload = market_payload or {}
    issues = gap_payload.get("data_quality_issues") or []
    pending = (
        gap_payload.get("manual_required")
        or gap_payload.get("pending_tasks")
        or []
    )

    # data_quality_issues
    for issue in issues:
        category = issue.get("category")
        key = issue.get("key")
        if not category or not key:
            continue

        if category == "bonds":
            name = _find_market_name(
                market_payload.get("bonds", []), key, key
            )
            if not any(
                item.get("symbol") == key for item in template["bonds"]
            ):
                template["bonds"].append(
                    {
                        "symbol": key,
                        "name": name,
                        "current_yield": None,
                        "change_5d_bp": None,
                        "change_120d_bp": None,
                        "trend": "unknown",
                        "source": "MCP WebSearch (source detail)",
                    }
                )
        elif category == "commodities":
            name = _find_market_name(
                market_payload.get("commodities", []), key, key
            )
            if not any(
                item.get("symbol") == key
                for item in template["commodities"]
            ):
                template["commodities"].append(
                    {
                        "symbol": key,
                        "name": name,
                        "current_price": None,
                        "unit": _find_market_item(
                            market_payload.get("commodities", []),
                            key,
                            "unit",
                        )
                        or "",
                        "ytd_change": None,
                        "trend": "unknown",
                        "source": "MCP WebSearch (source detail)",
                    }
                )
        elif category == "forex":
            name = _find_market_name(market_payload.get("forex", []), key, key)
            if not any(item.get("pair") == key for item in template["forex"]):
                template["forex"].append(
                    {
                        "pair": key,
                        "name": name,
                        "current_rate": None,
                        "daily_change": None,
                        "change_120d": None,
                        "trend": "unknown",
                        "source": "MCP WebSearch (source detail)",
                    }
                )
        elif category == "macro_indicators":
            name = _find_market_name(
                market_payload.get("macro_indicators", {}), key, key
            )
            unit = (
                _find_market_item(
                    market_payload.get("macro_indicators", {}),
                    key,
                    "unit",
                )
                or "%"
            )
            template["macro_indicators"][key] = {
                "indicator_name": name,
                "current_value": None,
                "previous_value": None,
                "change_rate": None,
                "unit": unit,
                "date": report_date or "",
                "source": "MCP WebSearch (source detail)",
            }
        elif category == "monetary_policy":
            name = _find_market_name(
                market_payload.get("monetary_policy", {}), key, key
            )
            unit = (
                _find_market_item(
                    market_payload.get("monetary_policy", {}),
                    key,
                    "unit",
                )
                or "%"
            )
            template["monetary_policy"][key] = {
                "policy_name": name,
                "current_value": None,
                "change_from_120d": None,
                "unit": unit,
                "date": report_date or "",
                "source": "MCP WebSearch (source detail)",
            }

    # pending / manual_required (fund_flow)
    for item in pending:
        if isinstance(item, dict):
            key = (
                item.get("key")
                or item.get("indicator_key")
                or item.get("name")
            )
        else:
            key = str(item)
        if not key:
            continue
        if key in FLOW_KEYS:
            template["fund_flow"].setdefault(
                key,
                {
                    "recent_5d": None,
                    "total_120d": None,
                    "trend": "unknown",
                    "source": "MCP WebSearch",
                    "note": "source detail",
                },
            )

    return template


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build manual WebSearch JSON skeleton from gap_monitor issues."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--gap",
        required=True,
        help="Path to gap_monitor_YYYYMMDD.json",
    )
    parser.add_argument(
        "--market-data",
        help="Optional market_data_complete.json for metadata fill",
    )
    parser.add_argument("--output", help="Output JSON path (default: stdout)")
    parser.add_argument("--date", help="Override date (YYYY-MM-DD)")
    parser.add_argument(
        "--policy-config",
        help="Optional manual fallback policy config path",
    )
    parser.add_argument(
        "--no-prefill-policies",
        action="store_true",
        help=(
            "Disable provenance prefill from "
            "config/manual_fallback_policies.json"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gap_path = Path(args.gap)
    gap_payload = _safe_load(gap_path)
    market_payload = (
        _safe_load(Path(args.market_data)) if args.market_data else None
    )
    date_val = args.date
    if not date_val and market_payload:
        date_val = (
            market_payload.get("metadata", {}).get("date")
            or market_payload.get("metadata", {}).get("end_date")
            or market_payload.get("metadata", {}).get("start_date")
        )

    template = _build_template(
        gap_payload, market_payload, report_date=date_val
    )
    if not args.no_prefill_policies:
        policies = load_manual_fallback_policies(
            Path(args.policy_config) if args.policy_config else None
        )
        _apply_policies(template, policies)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[OK] manual template saved: {output_path}")
    else:
        print(json.dumps(template, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
