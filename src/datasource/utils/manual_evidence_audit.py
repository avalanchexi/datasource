# -*- coding: utf-8 -*-
"""Audit evidence metadata in Stage2.5 manual JSON payloads."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse


_LIST_CATEGORIES = ("commodities", "forex", "bonds", "stock_indices")
_DICT_CATEGORIES = ("macro_indicators", "monetary_policy", "fund_flow")
_IDENTIFIER_FIELDS = ("symbol", "pair", "name")
_NUMERIC_FIELDS = (
    "current_value",
    "current_price",
    "current_rate",
    "current_yield",
    "recent_5d",
    "total_120d",
)
_PREVIOUS_FIELDS = ("previous_value", "change_rate")
_SOURCE_TEXT_FIELDS = ("source", "provider", "note")
_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
_NUMERIC_STRING_PATTERN = re.compile(
    r"^[+-]?(?:\d+(?:,\d{3})*|\d+|\.\d+)(?:\.\d+)?%?$"
)

_PROVIDERS = (
    {
        "domain": "investing.com",
        "markers": ("investing.com", "investing"),
    },
    {
        "domain": "bloomberg.com",
        "markers": ("bloomberg.com", "bloomberg", "彭博"),
    },
    {
        "domain": "stats.gov.cn",
        "markers": ("stats.gov.cn", "国家统计局"),
    },
    {
        "domain": "pbc.gov.cn",
        "markers": ("pbc.gov.cn", "中国人民银行", "央行", "pboc"),
    },
    {
        "domain": "tradingeconomics.com",
        "markers": ("tradingeconomics.com", "trading economics"),
    },
)


def audit_manual_evidence(
    manual_payload: Dict[str, Any],
    *,
    market_payload: Optional[Dict[str, Any]] = None,
    stage2_log: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Return evidence audit errors and warnings for manual JSON entries."""
    _ = (market_payload, stage2_log)
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    payload = manual_payload if isinstance(manual_payload, dict) else {}

    for path, entry in _iter_manual_entries(payload):
        if not _has_numeric_manual_value(entry):
            continue

        source_url = entry.get("source_url")
        url_error, host = _validate_source_url(source_url)
        if url_error == "missing_source_url":
            errors.append(
                _issue(
                    "missing_source_url",
                    path,
                    "Numeric manual value requires a single HTTPS source_url.",
                )
            )
        elif url_error == "invalid_source_url":
            errors.append(
                _issue(
                    "invalid_source_url",
                    path,
                    "source_url must be one single HTTPS URL with a valid host and port.",
                )
            )
        else:
            errors.extend(_provider_mismatch_errors(path, entry, host or ""))

        if _has_previous_or_change(entry) and not entry.get("previous_source_url") and not entry.get("note"):
            warnings.append(
                _issue(
                    "previous_value_without_evidence_note",
                    path,
                    "previous_value/change_rate requires previous_source_url or a note explaining adjacent-period evidence.",
                )
            )

    return {"errors": errors, "warnings": warnings}


def _iter_manual_entries(payload: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    for category in _LIST_CATEGORIES:
        items = payload.get(category)
        if not isinstance(items, list):
            continue
        for index, entry in enumerate(items):
            if not isinstance(entry, dict):
                continue
            identifier = _entry_identifier(entry)
            path = f"{category}.{identifier}" if identifier else f"{category}[{index}]"
            yield path, entry

    for category in _DICT_CATEGORIES:
        items = payload.get(category)
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if not isinstance(entry, dict):
                continue
            yield f"{category}.{key}", entry


def _entry_identifier(entry: Dict[str, Any]) -> str:
    for field in _IDENTIFIER_FIELDS:
        value = entry.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _has_numeric_manual_value(entry: Dict[str, Any]) -> bool:
    return any(_is_numeric(entry.get(field)) for field in _NUMERIC_FIELDS)


def _is_numeric(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        normalized = value.strip().replace(",", "")
        return bool(normalized and _NUMERIC_STRING_PATTERN.match(normalized))
    return False


def _validate_source_url(source_url: Any) -> Tuple[Optional[str], Optional[str]]:
    if source_url is None or not isinstance(source_url, str) or not source_url:
        return "missing_source_url", None
    if source_url != source_url.strip() or any(char.isspace() for char in source_url):
        return "invalid_source_url", None
    if len(_URL_PATTERN.findall(source_url)) != 1:
        return "invalid_source_url", None

    parsed = urlparse(source_url)
    try:
        _ = parsed.port
    except ValueError:
        return "invalid_source_url", None

    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        return "invalid_source_url", host.lower() if host else None
    return None, host.lower()


def _provider_mismatch_errors(
    path: str, entry: Dict[str, Any], host: str
) -> List[Dict[str, Any]]:
    source_text = " ".join(
        str(entry.get(field) or "") for field in _SOURCE_TEXT_FIELDS
    )
    source_text_lower = source_text.lower()
    errors = []

    for provider in _mentioned_providers(source_text, source_text_lower):
        provider_domain = provider["domain"]
        if _host_matches_provider(host, provider_domain):
            continue
        errors.append(
            _issue(
                "source_provider_mismatch",
                path,
                (
                    f"source mentions {provider_domain} but source_url host is {host}; "
                    "source/provider text must match the evidence URL host."
                ),
            )
        )
    return errors


def _mentioned_providers(
    source_text: str, source_text_lower: str
) -> Iterable[Dict[str, Any]]:
    seen = set()
    for provider in _PROVIDERS:
        for marker in provider["markers"]:
            marker_text = marker if _contains_non_ascii(marker) else marker.lower()
            haystack = source_text if _contains_non_ascii(marker) else source_text_lower
            if marker_text in haystack:
                domain = provider["domain"]
                if domain not in seen:
                    seen.add(domain)
                    yield provider
                break


def _contains_non_ascii(value: str) -> bool:
    return any(ord(char) > 127 for char in value)


def _host_matches_provider(host: str, provider_domain: str) -> bool:
    return host == provider_domain or host.endswith("." + provider_domain)


def _has_previous_or_change(entry: Dict[str, Any]) -> bool:
    return any(_has_present_value(entry.get(field)) for field in _PREVIOUS_FIELDS)


def _has_present_value(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _issue(code: str, path: str, message: str) -> Dict[str, Any]:
    return {"code": code, "path": path, "message": message}
