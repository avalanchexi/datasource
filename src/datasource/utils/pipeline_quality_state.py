# -*- coding: utf-8 -*-
"""Pure quality-state calculator for Stage2.5/Stage3/Stage4 pipeline gates."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from datasource.utils.coercion import (
    is_legacy_713_placeholder,
    is_stage2_number_placeholder,
)
from datasource.utils.policy_rules import is_estimated_allowlisted, load_policy_rules


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SOURCE_MARKERS = ("websearch", "manual", "tavily", "deepseek", "stage2_auto", "stage2_auto_extract")


def _estimated_issue_details(category: str, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if category != "fund_flow":
        return None
    details: Dict[str, Any] = {}
    for field in ("source_tier", "window_evidence", "metric_basis"):
        value = entry.get(field)
        if value not in (None, ""):
            details[field] = value
    return details or None


def build_pipeline_quality_state(
    market_payload: Dict[str, Any],
    *,
    policy_rules: Optional[Dict[str, Any]] = None,
    stage: str = "stage3",
    allow_estimated: bool = False,
) -> Dict[str, Any]:
    """Build a derived quality state without mutating market payload values."""
    rules = policy_rules or load_policy_rules()
    payload = market_payload if isinstance(market_payload, dict) else {}
    report_date = _payload_report_date(payload)

    missing_items: Dict[str, List[Dict[str, Any]]] = {}
    quality_blockers: List[Dict[str, Any]] = []
    manual_required: List[Dict[str, Any]] = []
    source_url_issues: List[Dict[str, Any]] = []
    window_metric_issues: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    estimated_blockers: List[str] = []
    estimated_blocker_reasons: Dict[str, List[str]] = {}
    stale_redlist: List[Dict[str, str]] = []
    critical_stale_keys = {str(item).lower() for item in rules.get("critical_stale_keys", [])}
    block_on_stale = bool(rules.get("block_on_stale", True))

    def add_issue(category: str, key: str, reason: str, *, details: Any = None) -> Dict[str, Any]:
        issue = {"category": category, "key": key, "reason": reason}
        if details is not None:
            issue["details"] = details
        if issue not in quality_blockers:
            quality_blockers.append(issue)
        missing = {"key": key, "reason": reason}
        if missing not in missing_items.setdefault(category, []):
            missing_items[category].append(missing)
        if issue not in manual_required:
            manual_required.append(issue)
        return issue

    for category, key, entry in _iter_entries(payload):
        value = _entry_value(category, entry)
        has_real_value = _has_real_value(value)
        has_any_real_value = _entry_has_any_real_value(category, entry)

        if _is_primary_value_missing(category, entry):
            add_issue(category, key, "primary_value_missing")

        if has_real_value and _is_compare_missing(category, entry):
            add_issue(category, key, "missing_compare_values")

        if block_on_stale and entry.get("is_stale") is True and key.lower() in critical_stale_keys:
            add_issue(category, key, "critical_stale")
            stale_item = {"category": category, "key": key}
            if stale_item not in stale_redlist:
                stale_redlist.append(stale_item)

        if has_any_real_value and _needs_source_url(entry):
            issue = add_issue(category, key, "missing_source_url")
            if issue not in source_url_issues:
                source_url_issues.append(issue)

        if entry.get("is_estimated") is True:
            allowed, reasons = is_estimated_allowlisted(
                category,
                key,
                entry,
                rules=rules,
                report_date=report_date,
            )
            if not allowed:
                issue = add_issue(
                    category,
                    key,
                    "estimated_not_allowed",
                    details=_estimated_issue_details(category, entry),
                )
                blocker_key = f"{category}.{key}"
                if blocker_key not in estimated_blockers:
                    estimated_blockers.append(blocker_key)
                estimated_blocker_reasons[blocker_key] = reasons
                if issue not in quality_blockers:
                    quality_blockers.append(issue)

        if category == "commodities":
            for issue in _commodity_window_issues(key, entry):
                if issue not in window_metric_issues:
                    window_metric_issues.append(issue)
                add_issue(issue["category"], issue["key"], issue["reason"])

    for key, entry in _iter_fund_flow(payload.get("fund_flow")):
        for field in ("recent_5d", "total_120d"):
            if is_stage2_number_placeholder(entry.get(field)):
                add_issue("fund_flow", key, "fund_flow_window_missing", details={"field": field})

    manual_keys = _manual_required_keys(manual_required)
    block_stage3 = bool(quality_blockers) if stage == "stage3" else bool(quality_blockers)

    return {
        "missing_items": {k: v for k, v in missing_items.items() if v},
        "quality_blockers": quality_blockers,
        "manual_required": manual_required,
        "policy_evaluation": {
            "block_stage3": block_stage3,
            "quality_blockers": quality_blockers,
            "estimated_blockers": estimated_blockers,
            "estimated_blocker_reasons": estimated_blocker_reasons,
            "stale_redlist": stale_redlist,
            "allow_estimated": allow_estimated,
        },
        "gap_monitor_view": {
            "manual_required": manual_keys,
            "pending_tasks": manual_keys,
            "quality_blockers": quality_blockers,
        },
        "source_url_issues": source_url_issues,
        "window_metric_issues": window_metric_issues,
        "warnings": warnings,
    }


def _iter_entries(payload: Dict[str, Any]) -> Iterable[Tuple[str, str, Dict[str, Any]]]:
    dict_categories = ("macro_indicators", "monetary_policy", "fund_flow")
    list_categories = ("bonds", "forex", "commodities", "stock_indices")

    for category in dict_categories:
        rows = payload.get(category)
        if not isinstance(rows, dict):
            continue
        for key, entry in rows.items():
            if isinstance(entry, dict):
                yield category, str(key), entry

    for category in list_categories:
        rows = payload.get(category)
        if not isinstance(rows, list):
            continue
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            key = _entry_key(category, entry)
            if key:
                yield category, key, entry


def _payload_report_date(payload: Dict[str, Any]) -> Any:
    metadata = payload.get("metadata")
    for source in (metadata, payload):
        if not isinstance(source, dict):
            continue
        for field in ("date", "end_date", "start_date"):
            value = source.get(field)
            if value not in (None, ""):
                return value
    return None


def _iter_fund_flow(rows: Any) -> Iterable[Tuple[str, Dict[str, Any]]]:
    if not isinstance(rows, dict):
        return
    for key, entry in rows.items():
        if isinstance(entry, dict):
            yield str(key), entry


def _entry_key(category: str, entry: Dict[str, Any]) -> str:
    for field in ("key", "symbol", "pair", "name", "ts_code", "code"):
        value = entry.get(field)
        if value not in (None, ""):
            return str(value)
    return category


def _entry_value(category: str, entry: Dict[str, Any]) -> Any:
    fields_by_category = {
        "macro_indicators": ("current_value",),
        "monetary_policy": ("current_value",),
        "bonds": ("current_yield", "current_value", "yield"),
        "forex": ("current_rate", "current_value"),
        "commodities": ("current_price", "current_value"),
        "stock_indices": ("current_price", "current_value", "close", "price"),
        "fund_flow": ("recent_5d", "total_120d", "current_value"),
    }
    for field in fields_by_category.get(category, ("current_value",)):
        if field in entry:
            return entry.get(field)
    return None


def _has_real_value(value: Any) -> bool:
    return not is_stage2_number_placeholder(value) and not is_legacy_713_placeholder(value)


def _is_primary_value_missing(category: str, entry: Dict[str, Any]) -> bool:
    if category == "fund_flow":
        return False
    return not _has_real_value(_entry_value(category, entry))


def _entry_has_any_real_value(category: str, entry: Dict[str, Any]) -> bool:
    fields_by_category = {
        "fund_flow": ("recent_5d", "total_120d", "current_value"),
    }
    fields = fields_by_category.get(category)
    if not fields:
        return _has_real_value(_entry_value(category, entry))
    return any(_has_real_value(entry.get(field)) for field in fields if field in entry)


def _is_compare_missing(category: str, entry: Dict[str, Any]) -> bool:
    if category == "macro_indicators":
        return is_stage2_number_placeholder(entry.get("previous_value")) or entry.get("change_rate") is None
    if category == "monetary_policy":
        return entry.get("change_from_120d") is None
    return False


def _needs_source_url(entry: Dict[str, Any]) -> bool:
    source_text = " ".join(
        str(entry.get(field) or "") for field in ("source", "note", "data_source", "provider")
    ).lower()
    if not any(marker in source_text for marker in _SOURCE_MARKERS):
        return False
    source_url = str(entry.get("source_url") or entry.get("url") or "").strip()
    if source_url:
        return False
    return _URL_RE.search(source_text) is None


def _commodity_window_issues(key: str, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    if entry.get("daily_change_basis") == "change_5d":
        issues.append(
            {"category": "commodities", "key": key, "reason": "daily_change_from_change_5d"}
        )
    if entry.get("ytd_change_basis") == "change_120d":
        issues.append(
            {"category": "commodities", "key": key, "reason": "ytd_change_from_change_120d"}
        )
    return issues


def _manual_required_keys(rows: List[Dict[str, Any]]) -> List[str]:
    keys: List[str] = []
    for row in rows:
        key = str(row.get("key") or "")
        if key and key not in keys:
            keys.append(key)
    return keys
