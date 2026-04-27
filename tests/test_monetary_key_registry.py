#!/usr/bin/env python
# -*- coding: utf-8 -*-

from datasource.utils.key_aliases import canonical_monetary_key, normalize_monetary_section


def test_canonical_monetary_key_registry():
    expected = {
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
    for raw, canonical in expected.items():
        assert canonical_monetary_key(raw) == canonical


def test_normalize_monetary_section_prefers_canonical_live_over_alias_placeholder():
    section = {
        "mlf_rate": {"current_value": None, "source": "placeholder"},
        "mlf": {"current_value": 2.0, "source": "manual"},
    }

    normalized = normalize_monetary_section(section)

    assert list(normalized) == ["mlf"]
    assert normalized["mlf"]["current_value"] == 2.0
    assert normalized["mlf"]["source"] == "manual"


def test_normalize_monetary_section_moves_alias_live_when_canonical_placeholder():
    section = {
        "mlf": {"current_value": 0, "source": "placeholder"},
        "mlf_rate": {"current_value": 2.1, "source": "legacy"},
    }

    normalized = normalize_monetary_section(section)

    assert list(normalized) == ["mlf"]
    assert normalized["mlf"]["current_value"] == 2.1
    assert normalized["mlf"]["source"] == "legacy"


def test_normalize_monetary_section_collapses_duplicate_live_entries_to_canonical():
    section = {
        "reverse_repo_7d": {"current_value": 1.6, "source": "legacy"},
        "reverse_repo": {"current_value": 1.7, "source": "canonical"},
    }

    normalized = normalize_monetary_section(section)

    assert list(normalized) == ["reverse_repo"]
    assert normalized["reverse_repo"]["current_value"] == 1.7


def test_normalize_monetary_section_merges_alias_metadata_into_canonical_live_entry():
    section = {
        "mlf": {
            "current_value": 2.0,
            "source": "",
            "date": None,
            "change_from_120d": None,
            "unit": "%",
        },
        "mlf_rate": {
            "current_value": None,
            "source": "legacy source",
            "date": "2026-04",
            "change_from_120d": 0.1,
            "source_url": "https://example.com/mlf",
        },
    }

    normalized = normalize_monetary_section(section)

    assert list(normalized) == ["mlf"]
    assert normalized["mlf"]["current_value"] == 2.0
    assert normalized["mlf"]["source"] == "legacy source"
    assert normalized["mlf"]["date"] == "2026-04"
    assert normalized["mlf"]["change_from_120d"] == 0.1
    assert normalized["mlf"]["source_url"] == "https://example.com/mlf"
    assert normalized["mlf"]["unit"] == "%"


def test_normalize_monetary_section_keeps_alias_live_value_and_canonical_metadata():
    section = {
        "mlf_rate": {
            "current_value": 2.0,
            "source": "placeholder",
            "note": "占位",
        },
        "mlf": {
            "current_value": 7.13,
            "source": "PBOC",
            "date": "2026-04-25",
            "report_period": "2026-04",
            "change_from_120d": -0.2,
            "note": "来源: 中国人民银行",
        },
    }

    normalized = normalize_monetary_section(section)

    assert list(normalized) == ["mlf"]
    assert normalized["mlf"]["current_value"] == 2.0
    assert normalized["mlf"]["source"] == "PBOC"
    assert normalized["mlf"]["date"] == "2026-04-25"
    assert normalized["mlf"]["report_period"] == "2026-04"
    assert normalized["mlf"]["change_from_120d"] == -0.2
    assert normalized["mlf"]["note"] == "来源: 中国人民银行"
