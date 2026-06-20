#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Manual fallback policy loader for provenance-only skeleton prefill."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse


DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[3]
    / "config/manual_fallback_policies.json"
)

NUMERIC_MANUAL_FIELDS = {
    "change_120d",
    "change_120d_bp",
    "change_5d",
    "change_5d_bp",
    "change_from_120d",
    "change_rate",
    "current_price",
    "current_rate",
    "current_value",
    "current_yield",
    "daily_change",
    "previous_value",
    "recent_5d",
    "total_120d",
    "yoy_month",
    "ytd_change",
}

PREFILL_FIELDS = {
    "estimation_method",
    "is_estimated",
    "metric_basis",
    "note",
    "source",
    "source_tier",
    "source_url",
    "window_evidence",
}

REQUIRED_POLICY_FIELDS = {
    "category",
    "is_estimated",
    "key",
    "source",
    "source_url_template",
}


def policy_id(category: str, key: str) -> str:
    return f"{str(category).strip()}:{str(key).strip()}"


def _is_https_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme.lower() == "https" and bool(parsed.hostname)


def _validate_policy(raw: Mapping[str, Any], *, index: int) -> Dict[str, Any]:
    policy = dict(raw)
    missing = [
        field
        for field in sorted(REQUIRED_POLICY_FIELDS)
        if field not in policy or policy.get(field) in (None, "")
    ]
    if missing:
        raise ValueError(
            "manual fallback policy "
            f"#{index} missing required fields: {missing}"
        )

    forbidden = sorted(NUMERIC_MANUAL_FIELDS.intersection(policy))
    policy_key = policy_id(policy["category"], policy["key"])
    if forbidden:
        raise ValueError(
            f"manual fallback policy {policy_key} "
            f"must not define numeric fields: {forbidden}"
        )

    if not isinstance(policy.get("is_estimated"), bool):
        raise ValueError(
            f"manual fallback policy {policy_key} "
            "requires boolean is_estimated"
        )

    if not _is_https_url(policy.get("source_url_template")):
        raise ValueError(
            f"manual fallback policy {policy_key} "
            "requires an HTTPS source_url_template"
        )

    return policy


def load_manual_fallback_policies(
    path: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """Load and validate manual fallback policies keyed by category:key."""

    policy_path = path or DEFAULT_POLICY_PATH
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    raw_policies = payload.get("policies")
    if not isinstance(raw_policies, list):
        raise ValueError(
            "manual fallback policy config requires a policies list"
        )

    policies: Dict[str, Dict[str, Any]] = {}
    for index, raw in enumerate(raw_policies):
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"manual fallback policy #{index} must be an object"
            )
        policy = _validate_policy(raw, index=index)
        key = policy_id(policy["category"], policy["key"])
        if key in policies:
            raise ValueError(f"duplicate manual fallback policy: {key}")
        policies[key] = policy
    return policies
