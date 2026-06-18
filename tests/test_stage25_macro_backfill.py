import json
from pathlib import Path
from typing import Dict, List

from datasource.engines.stage2_5.trend_backfill import (
    MACRO_CHANGE_RATE_CALIBER,
    _calc_prev_from_event_history,
    _macro_change_rate,
)


def _write_events(
    base_dir: Path, indicator: str, events: List[Dict[str, object]]
) -> None:
    events_dir = base_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / f"{indicator}.json").write_text(
        json.dumps({"events": events}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_yoy_pp_uses_point_difference():
    assert MACRO_CHANGE_RATE_CALIBER["ppi"] == "yoy_pp"
    assert _macro_change_rate("ppi", 2.8, 0.5) == (2.3, None)
    assert _macro_change_rate("cpi", 1.2, 1.0)[0] == 0.2


def test_level_uses_percentage():
    assert MACRO_CHANGE_RATE_CALIBER["bdi"] == "level_pct"
    assert _macro_change_rate("bdi", 2818.0, 2916.0)[0] == round(
        (2818 - 2916) / 2916 * 100,
        4,
    )


def test_level_div_by_zero_returns_none():
    assert _macro_change_rate("bdi", 5.0, 0.0) == (
        None,
        "change_rate_pct_div_by_zero",
    )


def test_level_near_zero_returns_none():
    assert _macro_change_rate("bdi", 1.0, 1e-10) == (
        None,
        "change_rate_pct_div_by_zero",
    )


def test_unknown_key_infers_by_unit():
    assert _macro_change_rate("xx", 3.0, 2.0, unit="%") == (
        1.0,
        "caliber_inferred",
    )
    assert _macro_change_rate("xx", 300.0, 200.0, unit="点") == (
        50.0,
        "caliber_inferred",
    )


def test_prev_history_anchors_cpi_to_current_period(tmp_path):
    _write_events(
        tmp_path,
        "cpi",
        [
            {
                "report_period": "2026-04",
                "release_date": "2026-05-09",
                "value": 0.8,
            },
            {
                "report_period": "2026-05",
                "release_date": "2026-06-09",
                "value": 1.0,
            },
            {
                "report_period": "2026-06",
                "release_date": "2026-07-09",
                "value": 1.2,
            },
        ],
    )

    result = _calc_prev_from_event_history(
        "cpi",
        1.2,
        "2026-07-10",
        base_dir=tmp_path,
        current_period="2026-06",
    )

    assert result["previous_value"] == 1.0
    assert result["change_rate"] == 0.2
    assert result["value_source"] == "event_history_backfill"
    assert result["reason"] is None


def test_prev_history_parses_industrial_report_period(tmp_path):
    _write_events(
        tmp_path,
        "industrial",
        [
            {
                "report_period": "2026-03",
                "release_date": "2026-04-16",
                "value": 5.7,
            },
            {
                "report_period": "2026-04",
                "release_date": "2026-05-16",
                "value": 4.1,
            },
        ],
    )

    result = _calc_prev_from_event_history(
        "industrial",
        4.1,
        "2026-05-20",
        base_dir=tmp_path,
        current_period="2026-04",
    )

    assert result["previous_value"] == 5.7
    assert result["change_rate"] == round(4.1 - 5.7, 4)
    assert result["value_source"] == "event_history_backfill"
    assert result["reason"] is None


def test_prev_history_requires_strict_prior_period(tmp_path):
    _write_events(
        tmp_path,
        "cpi",
        [
            {
                "report_period": "2026-06",
                "release_date": "2026-07-09",
                "value": 1.2,
            },
        ],
    )

    result = _calc_prev_from_event_history(
        "cpi",
        1.2,
        "2026-07-10",
        base_dir=tmp_path,
        current_period="2026-06",
    )

    assert result["previous_value"] is None
    assert result["change_rate"] is None
    assert result["reason"] == "no_previous_value"


def test_prev_history_anchored_requires_explicit_report_period(tmp_path):
    _write_events(
        tmp_path,
        "cpi",
        [
            {
                "release_date": "2026-05-09",
                "value": 0.8,
            },
            {
                "release_date": "2026-06-09",
                "value": 1.0,
            },
        ],
    )

    result = _calc_prev_from_event_history(
        "cpi",
        1.2,
        "2026-07-10",
        base_dir=tmp_path,
        current_period="2026-06",
    )

    assert result["previous_value"] is None
    assert result["change_rate"] is None
    assert result["reason"] == "no_previous_value"


def test_prev_history_uses_level_pct_caliber_for_bdi(tmp_path):
    _write_events(
        tmp_path,
        "bdi",
        [
            {
                "report_period": "2026-05",
                "release_date": "2026-05-31",
                "value": 2916.0,
            },
            {
                "report_period": "2026-06",
                "release_date": "2026-06-30",
                "value": 2818.0,
            },
        ],
    )

    result = _calc_prev_from_event_history(
        "bdi",
        2818.0,
        "2026-06-30",
        base_dir=tmp_path,
        current_period="2026-06",
    )

    assert result["previous_value"] == 2916.0
    assert result["change_rate"] == round((2818.0 - 2916.0) / 2916.0 * 100, 4)
    assert result["value_source"] == "event_history_backfill"
    assert result["reason"] is None


def test_prev_history_old_call_keeps_prior_same_value(tmp_path):
    _write_events(
        tmp_path,
        "cpi",
        [
            {
                "report_period": "2026-05",
                "release_date": "2026-06-09",
                "value": 1.2,
            },
            {
                "report_period": "2026-06",
                "release_date": "2026-07-09",
                "value": 1.2,
            },
        ],
    )

    result = _calc_prev_from_event_history(
        "cpi",
        1.2,
        "2026-07-10",
        base_dir=tmp_path,
    )

    assert result["previous_value"] == 1.2
    assert result["change_rate"] == 0.0
    assert result["value_source"] == "event_history_backfill"
    assert result["reason"] is None


def test_prev_history_unknown_key_infers_percent_unit(tmp_path):
    _write_events(
        tmp_path,
        "custom_macro",
        [
            {
                "report_period": "2026-05",
                "release_date": "2026-06-09",
                "value": 2.0,
            },
            {
                "report_period": "2026-06",
                "release_date": "2026-07-09",
                "value": 3.0,
            },
        ],
    )

    result = _calc_prev_from_event_history(
        "custom_macro",
        3.0,
        "2026-07-10",
        base_dir=tmp_path,
        current_period="2026-06",
        unit="%",
    )

    assert result["previous_value"] == 2.0
    assert result["change_rate"] == 1.0
    assert result["value_source"] == "event_history_backfill"
    assert result["caliber_note"] == "caliber_inferred"
    assert result["reason"] is None


def test_prev_history_unknown_key_old_call_returns_source_and_caliber_note(
    tmp_path,
):
    _write_events(
        tmp_path,
        "custom_level",
        [
            {"release_date": "2026-05-31", "value": 200.0},
            {"release_date": "2026-06-30", "value": 300.0},
        ],
    )

    result = _calc_prev_from_event_history(
        "custom_level",
        300.0,
        "2026-06-30",
        base_dir=tmp_path,
    )

    assert result["previous_value"] == 200.0
    assert result["change_rate"] == 50.0
    assert result["value_source"] == "event_history_backfill"
    assert result["caliber_note"] == "caliber_inferred"
    assert result["reason"] is None


def test_prev_history_unparseable_current_period_drops_current_value(tmp_path):
    _write_events(
        tmp_path,
        "cpi",
        [
            {"release_date": "2026-05-09", "value": 0.9},
            {"release_date": "2026-06-09", "value": 1.2},
        ],
    )

    result = _calc_prev_from_event_history(
        "cpi",
        1.2,
        "2026-06-30",
        base_dir=tmp_path,
        current_period="not-a-period",
    )

    assert result["previous_value"] == 0.9
    assert result["change_rate"] == 0.3
    assert result["value_source"] == "event_history_backfill"
    assert result["reason"] is None


def test_prev_history_old_call_filters_future_release_by_visibility(tmp_path):
    _write_events(
        tmp_path,
        "cpi",
        [
            {
                "report_period": "2026-05",
                "release_date": "2026-06-09",
                "value": 1.0,
            },
            {
                "report_period": "2026-06",
                "release_date": "2026-07-09",
                "value": 1.2,
            },
        ],
    )

    result = _calc_prev_from_event_history(
        "cpi",
        1.3,
        "2026-06-30",
        base_dir=tmp_path,
    )

    assert result["previous_value"] == 1.0
    assert result["change_rate"] == 0.3
    assert result["value_source"] == "event_history_backfill"
    assert result["reason"] is None
