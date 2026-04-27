#!/usr/bin/env python
# -*- coding: utf-8 -*-

from datasource.utils.missing_items import (
    append_missing_item,
    flatten_missing_item_rows,
    flatten_missing_items,
    remove_missing_item,
    sync_top_level_missing_view,
)


def test_flatten_reads_metadata_and_legacy_top_level():
    payload = {
        "missing_items": ["USDCNY", {"key": "GC=F"}],
        "metadata": {
            "missing_items": {
                "macro_indicators": [{"key": "cpi"}],
                "monetary_policy": ["mlf"],
            }
        },
    }

    assert flatten_missing_items(payload) == ["USDCNY", "GC=F", "cpi", "mlf"]


def test_append_writes_metadata_and_syncs_legacy_view():
    payload = {"metadata": {"missing_items": {}}, "missing_items": ["legacy_only"]}

    append_missing_item(payload, "monetary_policy", "mlf", "missing_compare_values")
    append_missing_item(payload, "monetary_policy", "mlf", "missing_compare_values")

    assert payload["metadata"]["missing_items"]["monetary_policy"] == [
        {"key": "mlf", "reason": "missing_compare_values"}
    ]
    assert flatten_missing_items(payload) == ["legacy_only", "mlf"]
    assert payload["missing_items"].count("mlf") == 1


def test_remove_cleans_metadata_and_top_level():
    payload = {
        "missing_items": ["mlf", "cpi"],
        "metadata": {
            "missing_items": {
                "monetary_policy": [{"key": "mlf"}],
                "macro_indicators": [{"key": "cpi"}],
            }
        },
    }

    remove_missing_item(payload, "monetary_policy", "mlf")

    assert flatten_missing_items(payload) == ["cpi"]
    assert payload["metadata"]["missing_items"] == {"macro_indicators": [{"key": "cpi"}]}


def test_sync_preserves_legacy_top_level_when_metadata_absent():
    payload = {"missing_items": ["legacy_top_only"]}

    sync_top_level_missing_view(payload)

    assert payload["missing_items"] == ["legacy_top_only"]
    assert flatten_missing_item_rows(payload) == [
        {"key": "legacy_top_only", "category": None, "item": "legacy_top_only"}
    ]
