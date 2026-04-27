#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compatibility helpers for metadata and legacy top-level missing_items."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple


def _item_key(item: Any) -> Optional[str]:
    if isinstance(item, dict):
        key = item.get("key") or item.get("indicator_key")
    else:
        key = item
    if key is None:
        return None
    text = str(key).strip()
    return text or None


def _item_category(item: Any, default: Optional[str] = None) -> Optional[str]:
    if isinstance(item, dict):
        value = item.get("stage_category") or item.get("category") or default
    else:
        value = default
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def flatten_missing_items(payload: Dict[str, Any]) -> List[str]:
    """Return unique missing item keys from both legacy top-level and metadata."""
    rows = flatten_missing_item_rows(payload)
    result: List[str] = []
    seen = set()
    for row in rows:
        key = row.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def flatten_missing_item_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return missing item rows with key/category while preserving legacy items."""
    rows: List[Dict[str, Any]] = []
    top_level = payload.get("missing_items", []) if isinstance(payload, dict) else []
    if isinstance(top_level, list):
        for item in top_level:
            key = _item_key(item)
            if not key:
                continue
            rows.append({"key": key, "category": _item_category(item), "item": item})

    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    metadata_missing = metadata.get("missing_items", {}) if isinstance(metadata, dict) else {}
    if isinstance(metadata_missing, dict):
        for category, items in metadata_missing.items():
            if not isinstance(items, list):
                continue
            for item in items:
                key = _item_key(item)
                if not key:
                    continue
                rows.append({"key": key, "category": str(category), "item": item})

    unique: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        sig = (row.get("category") or "", row.get("key"))
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(row)
    return unique


def append_missing_item(payload: Dict[str, Any], category: str, key: str, reason: Optional[str] = None) -> None:
    """Append to canonical metadata.missing_items and refresh the legacy view."""
    metadata = payload.setdefault("metadata", {})
    missing = metadata.setdefault("missing_items", {})
    category_items = missing.setdefault(category, [])
    if not any(_item_key(item) == str(key) for item in category_items):
        item: Dict[str, Any] = {"key": str(key)}
        if reason:
            item["reason"] = reason
        category_items.append(item)
    sync_top_level_missing_view(payload)


def remove_missing_item(payload: Dict[str, Any], category: Optional[str], key: str) -> None:
    """Remove a key from metadata and top-level compatibility views."""
    target = str(key)
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    metadata_missing = metadata.get("missing_items") if isinstance(metadata, dict) else None
    if isinstance(metadata_missing, dict):
        categories = [category] if category else list(metadata_missing.keys())
        for cat in list(categories):
            if cat not in metadata_missing:
                continue
            kept = [item for item in metadata_missing.get(cat, []) if _item_key(item) != target]
            if kept:
                metadata_missing[cat] = kept
            else:
                metadata_missing.pop(cat, None)
        if not metadata_missing:
            metadata.pop("missing_items", None)

    top_level = payload.get("missing_items")
    if isinstance(top_level, list):
        payload["missing_items"] = [item for item in top_level if _item_key(item) != target]


def sync_top_level_missing_view(payload: Dict[str, Any]) -> None:
    """
    Refresh legacy top-level missing_items from metadata while preserving legacy
    top-level-only items when metadata is absent.
    """
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    metadata_missing = metadata.get("missing_items") if isinstance(metadata, dict) else None
    if not isinstance(metadata_missing, dict):
        if "missing_items" not in payload:
            payload["missing_items"] = []
        return

    merged: List[Any] = []
    top_level = payload.get("missing_items")
    if isinstance(top_level, list):
        merged.extend(deepcopy(top_level))

    for category, items in metadata_missing.items():
        if not isinstance(items, list):
            continue
        for item in items:
            key = _item_key(item)
            if key:
                merged.append(key)

    unique: List[Any] = []
    seen: set[Tuple[str, str]] = set()
    for item in merged:
        key = _item_key(item)
        if not key:
            continue
        cat = _item_category(item) or ""
        sig = (cat, key)
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(item)
    payload["missing_items"] = unique
