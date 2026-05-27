# -*- coding: utf-8 -*-
"""Shared effective quality gates for Stage3/Stage4 report readiness."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

FUND_FLOW_DOWNGRADE_REASONS = frozenset(
    {
        "fund_flow_window_missing",
        "estimated_not_allowed",
        "missing_or_zero_value",
        "missing_value",
        "placeholder_value",
    }
)


def _is_fund_flow_downgrade_issue(issue: Any) -> bool:
    if not isinstance(issue, dict):
        return False
    return (
        str(issue.get("category") or "").lower() == "fund_flow"
        and str(issue.get("reason") or "") in FUND_FLOW_DOWNGRADE_REASONS
    )


def filter_effective_quality_blockers(
    quality_state: Dict[str, Any],
    *,
    market_payload: Optional[Dict[str, Any]] = None,
    allow_fund_flow_downgrade: bool = False,
) -> List[Dict[str, Any]]:
    """Return effective blockers from build_pipeline_quality_state() output.

    Fund-flow downgrades require explicit source evidence in the market payload.
    Without the payload, or without a source_url/url on the matching entry, the
    blocker remains effective.
    """
    blockers = quality_state.get("quality_blockers") or []
    if not isinstance(blockers, list):
        return []
    normalized = [item for item in blockers if isinstance(item, dict)]
    if not allow_fund_flow_downgrade:
        return normalized
    return [
        item
        for item in normalized
        if not (
            _is_fund_flow_downgrade_issue(item)
            and _fund_flow_issue_has_source_url(market_payload, item)
        )
    ]


def collect_fund_flow_downgraded_items(
    quality_state: Dict[str, Any],
    *,
    market_payload: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return fund_flow blockers downgraded from build_pipeline_quality_state()."""
    blockers = quality_state.get("quality_blockers") or []
    if not isinstance(blockers, list):
        return []
    return [
        dict(item)
        for item in blockers
        if _is_fund_flow_downgrade_issue(item)
        and _fund_flow_issue_has_source_url(market_payload, item)
    ]


def filter_effective_gap_items(
    market_payload: Dict[str, Any],
    quality_state: Dict[str, Any],
    gap_items: Any,
    *,
    allow_fund_flow_downgrade: bool = False,
) -> List[Any]:
    """Filter gap_monitor item lists against effective quality blockers."""
    if not isinstance(gap_items, list):
        return []

    blocker_pairs = {
        (str(issue.get("category") or "").lower(), str(issue.get("key") or "").lower())
        for issue in filter_effective_quality_blockers(
            quality_state,
            market_payload=market_payload,
            allow_fund_flow_downgrade=allow_fund_flow_downgrade,
        )
        if isinstance(issue, dict)
    }

    unresolved: List[Any] = []
    for item in gap_items:
        matches = _matching_payload_entries(market_payload, item)
        if not matches:
            unresolved.append(item)
            continue
        if any(
            (category.lower(), key.lower()) in blocker_pairs
            for category, key in matches
        ):
            unresolved.append(item)
    return unresolved


def assert_no_fallback_pring_result(
    pring_payload: Dict[str, Any],
    *,
    allow_fallback_report: bool = False,
) -> None:
    """Block Stage4 reports generated from fallback Pring payloads by default."""
    if allow_fallback_report:
        return
    if pring_payload.get("fallback_used") is True:
        raise RuntimeError(
            "Stage4 fallback Pring result blocked report generation: fallback_used=true"
        )


def _gap_item_label(item: Any) -> str:
    if isinstance(item, dict):
        for field in (
            "key",
            "indicator_key",
            "symbol",
            "pair",
            "task",
            "type",
            "name",
            "field",
        ):
            value = item.get(field)
            if value not in (None, ""):
                return str(value)
        return str(item)
    return str(item)


def _fund_flow_issue_has_source_url(
    market_payload: Optional[Dict[str, Any]],
    issue: Dict[str, Any],
) -> bool:
    if not isinstance(market_payload, dict):
        return False
    rows = market_payload.get("fund_flow")
    if not isinstance(rows, dict):
        return False
    key = issue.get("key")
    if key in (None, ""):
        return False
    entry = rows.get(str(key))
    if not isinstance(entry, dict):
        return False
    source_url = entry.get("source_url") or entry.get("url")
    return _is_http_url(source_url)


def _is_http_url(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or any(char.isspace() for char in text):
        return False
    parsed = urlparse(text)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _gap_item_category(item: Any) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    category = item.get("category")
    return str(category) if category not in (None, "") else None


def _payload_entries(
    market_payload: Dict[str, Any],
) -> List[Tuple[str, str, Tuple[str, ...]]]:
    entries: List[Tuple[str, str, Tuple[str, ...]]] = []
    for category in ("macro_indicators", "monetary_policy", "fund_flow"):
        rows = market_payload.get(category)
        if not isinstance(rows, dict):
            continue
        for key, entry in rows.items():
            if isinstance(entry, dict):
                canonical_key = str(key)
                entries.append((category, canonical_key, (canonical_key,)))

    key_fields = {
        "bonds": ("symbol", "name"),
        "forex": ("pair", "name"),
        "commodities": ("symbol", "name"),
        "stock_indices": ("symbol", "name", "ts_code", "code"),
    }
    for category, fields in key_fields.items():
        rows = market_payload.get(category)
        if not isinstance(rows, list):
            continue
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            canonical_key = _payload_entry_canonical_key(entry)
            if canonical_key is None:
                continue
            aliases: List[str] = [canonical_key]
            for field in fields:
                value = entry.get(field)
                if value not in (None, ""):
                    aliases.append(str(value))
            entries.append((category, canonical_key, tuple(dict.fromkeys(aliases))))
    return entries


def _payload_entry_canonical_key(entry: Dict[str, Any]) -> Optional[str]:
    for field in ("key", "symbol", "pair", "name", "ts_code", "code"):
        value = entry.get(field)
        if value not in (None, ""):
            return str(value)
    return None


def _matching_payload_entries(
    market_payload: Dict[str, Any],
    gap_item: Any,
) -> List[Tuple[str, str]]:
    label = _gap_item_label(gap_item).strip()
    category = _gap_item_category(gap_item)
    if "." in label and category is None:
        maybe_category, maybe_key = label.split(".", 1)
        if maybe_category and maybe_key:
            category = maybe_category
            label = maybe_key
    label_norm = label.lower()
    category_norm = category.lower() if category else None

    matches: List[Tuple[str, str]] = []
    for entry_category, canonical_key, aliases in _payload_entries(market_payload):
        if category_norm and entry_category.lower() != category_norm:
            continue
        if any(alias.lower() == label_norm for alias in aliases):
            matches.append((entry_category, canonical_key))
    return matches
