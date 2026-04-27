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


def _prefer_entry(existing: Any, incoming: Any, *, incoming_is_canonical: bool) -> Any:
    existing_live = _has_live_current_value(existing)
    incoming_live = _has_live_current_value(incoming)
    if existing_live:
        return existing
    if incoming_live:
        return incoming
    if incoming_is_canonical:
        return incoming
    return existing


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
        normalized[canonical] = _prefer_entry(
            normalized[canonical],
            entry,
            incoming_is_canonical=str(raw_key) == canonical,
        )
    return normalized
