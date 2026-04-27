#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared key alias registry for cross-stage compatibility."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from datasource.utils.coercion import is_legacy_713_placeholder, is_stage2_number_placeholder


MONETARY_KEY_ALIASES: Dict[str, str] = {
    "reverse_repo_7d": "reverse_repo",
    "reverse_repo": "reverse_repo",
    "mlf_rate": "mlf",
    "mlf": "mlf",
    "tsf_growth": "tsf",
    "tsf": "tsf",
    "m1_growth": "m1",
    "m1": "m1",
    "m2_growth": "m2",
    "m2": "m2",
    "rrr": "reserve_ratio",
    "reserve_ratio": "reserve_ratio",
    "dr007_rate": "dr007",
    "dr007": "dr007",
}


def canonical_monetary_key(key: Any) -> str:
    """Return the canonical monetary-policy key for legacy and new inputs."""
    text = str(key or "").strip()
    return MONETARY_KEY_ALIASES.get(text, text)


def _has_live_current_value(entry: Any) -> bool:
    if not isinstance(entry, Mapping):
        return False
    value = entry.get("current_value")
    return not (is_stage2_number_placeholder(value) or is_legacy_713_placeholder(value))


def _is_missing_metadata_value(value: Any) -> bool:
    return value is None or value == ""


METADATA_PLACEHOLDER_VALUES = {
    "n/a",
    "placeholder",
    "占位",
    "待获取",
    "待 websearch",
    "待人工补数(stage2 manual_required)",
}


def _is_metadata_placeholder_value(value: Any) -> bool:
    if _is_missing_metadata_value(value):
        return True
    if not isinstance(value, str):
        return False

    normalized = value.strip().lower()
    if normalized in METADATA_PLACEHOLDER_VALUES:
        return True
    return "待 websearch" in normalized


def _is_non_placeholder_value(value: Any) -> bool:
    return not (is_stage2_number_placeholder(value) or is_legacy_713_placeholder(value))


MERGE_FIELDS = {
    "source",
    "source_url",
    "date",
    "as_of_date",
    "report_period",
    "change_from_120d",
    "unit",
    "policy_name",
    "note",
    "is_estimated",
    "is_stale",
    "expected_period",
    "stale_reason",
}


def _merge_entry_metadata(kept: Dict[str, Any], discarded: Mapping[str, Any]) -> Dict[str, Any]:
    merged = dict(kept)
    if not _has_live_current_value(merged):
        candidate_current = discarded.get("current_value")
        if _is_non_placeholder_value(candidate_current):
            merged["current_value"] = candidate_current

    for field in MERGE_FIELDS:
        if not _is_metadata_placeholder_value(merged.get(field)):
            continue
        candidate = discarded.get(field)
        if _is_metadata_placeholder_value(candidate):
            continue
        if field == "change_from_120d" and not _is_non_placeholder_value(candidate):
            continue
        merged[field] = candidate
    return merged


def _merge_entries(existing: Any, incoming: Any, *, incoming_is_canonical: bool) -> Any:
    if not isinstance(existing, Mapping):
        return incoming if incoming_is_canonical or _has_live_current_value(incoming) else existing
    if not isinstance(incoming, Mapping):
        return existing

    existing_live = _has_live_current_value(existing)
    incoming_live = _has_live_current_value(incoming)
    if existing_live:
        return _merge_entry_metadata(dict(existing), incoming)
    if incoming_live:
        return _merge_entry_metadata(dict(incoming), existing)
    if incoming_is_canonical:
        return _merge_entry_metadata(dict(incoming), existing)
    return _merge_entry_metadata(dict(existing), incoming)


def normalize_monetary_section(section: Any) -> Dict[str, Any]:
    """
    Normalize a monetary_policy mapping to canonical keys.

    Conflict rule: live canonical/non-placeholder values win over placeholder
    aliases. If an alias has the only live value, it is moved to the canonical
    key. Duplicate live alias/canonical entries are collapsed to one canonical
    entry.
    """
    if not isinstance(section, Mapping):
        return {}

    normalized: Dict[str, Any] = {}
    ordered_items = sorted(
        section.items(),
        key=lambda item: 0 if str(item[0]) == canonical_monetary_key(item[0]) else 1,
    )
    for raw_key, entry in ordered_items:
        canonical = canonical_monetary_key(raw_key)
        if canonical not in normalized:
            normalized[canonical] = entry
            continue
        normalized[canonical] = _merge_entries(
            normalized[canonical],
            entry,
            incoming_is_canonical=str(raw_key) == canonical,
        )
    return normalized
