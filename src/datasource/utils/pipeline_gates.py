# -*- coding: utf-8 -*-
"""Shared pure helpers for pipeline gate filtering."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


FUND_FLOW_SKIP_REASONS = {
    "fund_flow_window_missing",
    "estimated_not_allowed",
}

_DATA_CATEGORY_EXCLUDES = {
    "metadata",
    "quality_metrics",
    "quality_state",
    "policy_evaluation",
    "gap_monitor",
    "missing_items",
}


def is_fund_flow_skippable_issue(issue: Any) -> bool:
    """Return whether a quality issue is skipped by the fund-flow override."""
    if not isinstance(issue, dict):
        return False
    return issue.get("category") == "fund_flow" and issue.get("reason") in FUND_FLOW_SKIP_REASONS


def effective_quality_blockers(
    blockers: Iterable[Any],
    *,
    skip_fund_flow_check: bool = False,
) -> List[Any]:
    """Return blockers after applying the optional fund-flow skip policy."""
    rows = list(blockers or [])
    if not skip_fund_flow_check:
        return rows
    return [issue for issue in rows if not is_fund_flow_skippable_issue(issue)]


def gap_item_key(item: Any) -> Optional[str]:
    """Extract a stable key from a gap item."""
    if isinstance(item, dict):
        value = item.get("key") or item.get("indicator_key") or item.get("symbol") or item.get("pair")
    else:
        value = item
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def gap_item_category(item: Any) -> Optional[str]:
    """Extract the category from a gap item when present."""
    if not isinstance(item, dict):
        return None
    value = item.get("category") or item.get("stage_category")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def gap_item_label(item: Any) -> str:
    """Return a human-readable label for a gap item."""
    category = gap_item_category(item)
    key = gap_item_key(item)
    if category and key:
        return f"{category}.{key}"
    if key:
        return key
    return str(item)


def payload_entries(market_payload: Any) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Return category/key/entry triples from market payload data sections."""
    if not isinstance(market_payload, dict):
        return []

    entries: List[Tuple[str, str, Dict[str, Any]]] = []
    for category, rows in market_payload.items():
        if category in _DATA_CATEGORY_EXCLUDES:
            continue
        if isinstance(rows, dict):
            for key, entry in rows.items():
                if isinstance(entry, dict):
                    entries.append((str(category), str(key), entry))
        elif isinstance(rows, list):
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                key = gap_item_key(entry)
                if key:
                    entries.append((str(category), key, entry))
    return entries


def matching_payload_entries(
    market_payload: Any,
    gap_item: Any,
) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Return payload entries matching a gap item's category/key."""
    key = gap_item_key(gap_item)
    if not key:
        return []
    category = gap_item_category(gap_item)

    matches: List[Tuple[str, str, Dict[str, Any]]] = []
    for entry_category, entry_key, entry in payload_entries(market_payload):
        if entry_key != key:
            continue
        if category and entry_category != category:
            continue
        matches.append((entry_category, entry_key, entry))
    return matches


def quality_blocker_pairs(blockers: Iterable[Any]) -> Set[Tuple[str, str]]:
    """Return category/key pairs represented in quality blockers."""
    pairs: Set[Tuple[str, str]] = set()
    for issue in blockers or []:
        if not isinstance(issue, dict):
            continue
        category = gap_item_category(issue)
        key = gap_item_key(issue)
        if category and key:
            pairs.add((category, key))
    return pairs


def _fully_skippable_fund_flow_pairs(blockers: Iterable[Any]) -> Set[Tuple[str, str]]:
    grouped: Dict[Tuple[str, str], List[Any]] = {}
    for issue in blockers or []:
        if not isinstance(issue, dict):
            continue
        category = gap_item_category(issue)
        key = gap_item_key(issue)
        if category != "fund_flow" or not key:
            continue
        grouped.setdefault((category, key), []).append(issue)
    return {
        pair
        for pair, issues in grouped.items()
        if issues and all(is_fund_flow_skippable_issue(issue) for issue in issues)
    }


def effective_gap_items(
    market_payload: Any,
    quality_blockers: Iterable[Any],
    gap_items: Iterable[Any],
    *,
    skip_fund_flow_check: bool = False,
) -> List[Any]:
    """Return gap items after applying skippable fund-flow quality blockers."""
    rows = list(gap_items or [])
    if not skip_fund_flow_check:
        return rows

    skippable_pairs = _fully_skippable_fund_flow_pairs(quality_blockers)
    if not skippable_pairs:
        return rows

    effective: List[Any] = []
    for item in rows:
        key = gap_item_key(item)
        if not key:
            effective.append(item)
            continue

        category = gap_item_category(item)
        candidate_pairs: Set[Tuple[str, str]] = set()
        if category:
            candidate_pairs.add((category, key))
        for entry_category, entry_key, _entry in matching_payload_entries(market_payload, item):
            candidate_pairs.add((entry_category, entry_key))

        if candidate_pairs and candidate_pairs.issubset(skippable_pairs):
            continue
        if ("fund_flow", key) in candidate_pairs and ("fund_flow", key) in skippable_pairs:
            continue
        effective.append(item)
    return effective


def assert_no_fallback_pring_result(
    pring_payload: Any,
    *,
    allow_fallback_report: bool = False,
) -> None:
    """Block report generation from fallback Pring results unless explicitly allowed."""
    if allow_fallback_report:
        return
    if isinstance(pring_payload, dict) and pring_payload.get("fallback_used") is True:
        raise RuntimeError("Pring result has fallback_used=true; refusing to continue.")
