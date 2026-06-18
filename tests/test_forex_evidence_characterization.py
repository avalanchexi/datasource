import pytest
from types import SimpleNamespace

from datasource.engines.stage2 import common as stage2_common
from datasource.engines.stage2 import extraction_apply as stage2_extraction_apply
from datasource.engines.stage2_5 import (
    common as stage25_common,
    entry_mergers as stage25_entry_mergers,
    trend_backfill as stage25_trend_backfill,
)
from datasource.utils import forex_evidence as stage2_forex_evidence
from datasource.utils import forex_evidence as stage25_forex_evidence
from datasource.utils import note_utils as stage2_note_utils
from datasource.utils import note_utils as stage25_note_utils
from datasource.utils import text_markers as stage2_text_markers

stage2 = SimpleNamespace(
    _is_forex_absence_text=stage2_extraction_apply._is_forex_absence_text,
    _safe_number=stage2_common._safe_number,
    _FOREX_DAILY_EVIDENCE_MARKERS=stage2_forex_evidence.STAGE2_FOREX_DAILY_EVIDENCE_MARKERS,
    _FOREX_120D_EVIDENCE_MARKERS=stage2_forex_evidence.STAGE2_FOREX_120D_EVIDENCE_MARKERS,
    _FOREX_COMPARE_FIELD_EVIDENCE_KEYS=stage2_forex_evidence.FOREX_COMPARE_FIELD_EVIDENCE_KEYS,
    _has_forex_compare_evidence=stage2_extraction_apply._has_forex_compare_evidence,
    _append_note=stage2_note_utils.append_note_text,
    _contains_ytd_marker=stage2_text_markers.contains_ytd_marker,
)


@pytest.mark.parametrize(
    "value,stage2_expected,stage25_expected",
    [
        ("", False, True),
        (None, False, True),
        ("N/A", False, True),
        ("no change", False, True),
        ("no change 120d value", True, True),
        ("missing previous value", True, True),
        ("direct_daily_series", False, False),
    ],
)
def test_forex_absence_predicates_keep_stage_specific_semantics(
    value, stage2_expected, stage25_expected
):
    assert stage2._is_forex_absence_text(value) is stage2_expected
    assert stage25_trend_backfill._is_forex_daily_change_absence_text(value) is stage25_expected


@pytest.mark.parametrize(
    "value,stage2_expected,stage25_expected",
    [
        ("7.13", 7.13, 7.13),
        ("1,234", None, 1234.0),
        ("7.13%", None, 7.13),
        ("abc 7.13", None, 7.13),
        ("abc", None, None),
        ("", None, None),
        (None, None, None),
    ],
)
def test_forex_number_coercion_keeps_stage_specific_semantics(
    value, stage2_expected, stage25_expected
):
    assert stage2._safe_number(value) == stage2_expected
    assert stage25_common._coerce_float(value) == stage25_expected


def test_forex_marker_constants_are_not_accidentally_merged():
    assert (
        stage2._FOREX_DAILY_EVIDENCE_MARKERS
        != stage25_forex_evidence.STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS
    )
    assert sorted(
        set(stage2._FOREX_DAILY_EVIDENCE_MARKERS)
        - set(stage25_forex_evidence.STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS)
    ) == [
        "change 1d",
        "change rate",
        "direct daily series",
        "direct daily window",
        "direct_daily_window",
        "previous close",
        "previous_close",
        "trend history",
        "trend history direct window",
        "trend history full window",
    ]
    assert sorted(
        set(stage25_forex_evidence.STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS)
        - set(stage2._FOREX_DAILY_EVIDENCE_MARKERS)
    ) == ["direct_window"]

    assert (
        stage2._FOREX_120D_EVIDENCE_MARKERS != stage25_forex_evidence.STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS
    )
    assert sorted(
        set(stage2._FOREX_120D_EVIDENCE_MARKERS)
        - set(stage25_forex_evidence.STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS)
    ) == [
        "change rate",
        "direct 120d window",
        "direct window",
        "direct_120d_window",
        "trend history",
        "trend history direct window",
        "trend history full window",
    ]
    assert (
        sorted(
            set(stage25_forex_evidence.STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS)
            - set(stage2._FOREX_120D_EVIDENCE_MARKERS)
        )
        == []
    )

    assert (
        stage2._FOREX_COMPARE_FIELD_EVIDENCE_KEYS["daily_change"]
        == stage25_forex_evidence.FOREX_DAILY_CHANGE_EVIDENCE_KEYS
    )
    assert (
        stage2._FOREX_COMPARE_FIELD_EVIDENCE_KEYS["change_120d"]
        == stage25_forex_evidence.FOREX_120D_CHANGE_EVIDENCE_KEYS
    )


@pytest.mark.parametrize(
    "extraction,field,expected",
    [
        (
            {"daily_change": 0.0, "daily_change_basis": "direct_daily_series"},
            "daily_change",
            True,
        ),
        (
            {"daily_change": 0.0, "daily_change_basis": "failed_trend_history"},
            "daily_change",
            False,
        ),
        ({"daily_change": 0.0, "note": "no change"}, "daily_change", True),
        ({"daily_change": 0.25}, "daily_change", True),
        (
            {"change_120d": 0.0, "daily_change_basis": "direct_daily_series"},
            "change_120d",
            False,
        ),
        (
            {"change_120d": 0.0, "change_120d_window_evidence": "direct_120d_window"},
            "change_120d",
            True,
        ),
        ({"change_120d": 0.0, "note": "no change 120d value"}, "change_120d", False),
    ],
)
def test_stage2_compare_evidence_cases(extraction, field, expected):
    assert stage2._has_forex_compare_evidence(extraction, field) is expected


def test_stage25_daily_evidence_copy_uses_stage25_float_coercion():
    target = {}
    source = {
        "daily_change_basis": "direct_daily_series",
        "daily_change_source_url": "https://example.com/fx",
        "daily_change_base_date": "2026-06-02",
        "daily_change_base_price": "7.13%",
    }

    stage25_trend_backfill._copy_valid_forex_daily_change_evidence(target, source)

    assert target == {
        "daily_change_basis": "direct_daily_series",
        "daily_change_source_url": "https://example.com/fx",
        "daily_change_base_date": "2026-06-02",
        "daily_change_base_price": 7.13,
    }
    assert stage25_trend_backfill._has_forex_daily_change_evidence(target) is True


def test_stage25_invalid_daily_evidence_is_not_preserved():
    target = {
        "daily_change_basis": "direct_daily_series",
        "daily_change_base_date": "2026-06-02",
    }
    source = {
        "daily_change_basis": "failed_trend_history",
        "daily_change_source_url": "N/A",
        "daily_change_base_date": "N/A",
        "daily_change_base_price": "N/A",
    }

    stage25_trend_backfill._copy_valid_forex_daily_change_evidence(target, source)

    assert target == {}
    assert stage25_trend_backfill._has_forex_daily_change_evidence(target) is False


def test_note_helper_semantics_are_distinct():
    assert stage2._append_note(None, "tail") == "tail"
    assert stage2._append_note("base", "tail") == "base tail"
    assert stage2._append_note("base tail", "tail") == "base tail"
    assert stage2._append_note("base", "") == "base"
    assert stage2._append_note(None, "") is None

    assert stage25_note_utils.append_note_once("base", "tail") == "base；tail"
    assert stage25_note_utils.append_note_once("base；tail", "tail") == "base；tail"

    entry = {"note": "base"}
    stage25_note_utils.append_note_to_entry(entry, "tail")
    stage25_note_utils.append_note_to_entry(entry, "tail")
    assert entry["note"] == "base；tail；tail"


def test_ytd_marker_script_compatibility_names_are_shared():
    assert stage2._contains_ytd_marker("1-2月累计同比增长") is True
    assert stage25_entry_mergers._contains_ytd_marker("1-2月累计同比增长") is True
    assert stage2._contains_ytd_marker("同比增长") is False
    assert stage25_entry_mergers._contains_ytd_marker("同比增长") is False
