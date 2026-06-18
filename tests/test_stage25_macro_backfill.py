import json
from pathlib import Path
from typing import Dict, List

from datasource.engines.stage2_5 import trend_backfill
from datasource.engines.stage2_5.entry_mergers import _apply_macro_entry
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


def test_apply_macro_entry_passes_period_and_unit_to_event_backfill(
    tmp_path,
):
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
    entry = {
        "indicator_name": "Custom Macro",
        "current_value": None,
        "previous_value": None,
        "change_rate": None,
        "unit": "%",
        "date": "",
        "source": "待WebSearch补充",
        "note": "",
        "is_estimated": True,
    }
    payload = {
        "indicator_name": "Custom Macro",
        "current_value": 3.0,
        "report_period": "2026-06",
        "unit": "%",
        "source": "manual",
    }

    assert _apply_macro_entry(
        "custom_macro",
        entry,
        payload,
        "2026-06-30",
        trend_history_base_dir=tmp_path,
    )

    assert entry["previous_value"] == 2.0
    assert entry["change_rate"] == 1.0
    assert entry["value_source"] == "event_history_backfill"
    assert "caliber_inferred" in entry["note"]


def test_apply_macro_entry_wires_period_and_unit_arguments(
    monkeypatch,
    tmp_path,
):
    captured: Dict[str, object] = {}

    def _fake_prev_from_history(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {
            "previous_value": 2.0,
            "change_rate": 1.0,
            "reason": None,
            "value_source": "event_history_backfill",
            "caliber_note": "caliber_inferred",
        }

    monkeypatch.setattr(
        trend_backfill,
        "_calc_prev_from_event_history",
        _fake_prev_from_history,
    )
    entry = {
        "indicator_name": "Custom Macro",
        "current_value": None,
        "previous_value": None,
        "change_rate": None,
        "unit": "%",
        "date": "",
        "source": "待WebSearch补充",
        "note": "",
    }
    payload = {
        "indicator_name": "Custom Macro",
        "current_value": 3.0,
        "report_period": "2026-06",
        "unit": "%",
        "source": "manual",
    }

    assert _apply_macro_entry(
        "custom_macro",
        entry,
        payload,
        "2026-06-30",
        trend_history_base_dir=tmp_path,
    )

    assert captured["args"][:3] == (
        "custom_macro",
        3.0,
        "2026-06-30",
    )
    assert captured["kwargs"]["current_period"] == "2026-06"
    assert captured["kwargs"]["unit"] == "%"
    assert captured["kwargs"]["base_dir"] == tmp_path


def test_apply_macro_entry_preserves_existing_non_backfill_value_source(
    tmp_path,
):
    _write_events(
        tmp_path,
        "custom_macro",
        [
            {"report_period": "2026-05", "value": 2.0},
            {"report_period": "2026-06", "value": 3.0},
        ],
    )
    entry = {
        "indicator_name": "Custom Macro",
        "current_value": None,
        "previous_value": None,
        "change_rate": None,
        "unit": "%",
        "date": "",
        "source": "待WebSearch补充",
        "value_source": "manual_override",
    }
    payload = {
        "indicator_name": "Custom Macro",
        "current_value": 3.0,
        "report_period": "2026-06",
        "unit": "%",
        "source": "manual",
    }

    assert _apply_macro_entry(
        "custom_macro",
        entry,
        payload,
        "2026-06-30",
        trend_history_base_dir=tmp_path,
    )

    assert entry["previous_value"] == 2.0
    assert entry["change_rate"] == 1.0
    assert entry["value_source"] == "manual_override"


def test_apply_macro_entry_macro_caliber_fills_missing_change_rate():
    entry = {
        "indicator_name": "CPI同比",
        "current_value": None,
        "previous_value": None,
        "change_rate": None,
        "unit": "%",
        "date": "",
        "source": "待WebSearch补充",
        "note": "",
        "value_source": "manual_override",
    }
    payload = {
        "indicator_name": "CPI同比",
        "current_value": 1.2,
        "previous_value": 1.0,
        "unit": "%",
        "source": "manual",
    }

    assert _apply_macro_entry(
        "cpi",
        entry,
        payload,
        "2026-06-30",
        trend_history_base_dir=None,
    )

    assert entry["previous_value"] == 1.0
    assert entry["change_rate"] == 0.2
    assert entry["value_source"] == "manual_override"


def test_backfill_trend_changes_tags_macro_event_history_source(tmp_path):
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
    market_data = {
        "metadata": {"date": "2026-06-30"},
        "macro_indicators": {
            "custom_macro": {
                "indicator_name": "Custom Macro",
                "current_value": 3.0,
                "previous_value": None,
                "change_rate": None,
                "report_period": "2026-06",
                "unit": "%",
            }
        },
    }

    stats = trend_backfill._backfill_trend_changes(
        market_data,
        base_dir=tmp_path,
    )

    indicator = market_data["macro_indicators"]["custom_macro"]
    assert stats["macro_indicators"] == 1
    assert indicator["previous_value"] == 2.0
    assert indicator["change_rate"] == 1.0
    assert indicator["value_source"] == "event_history_backfill"


def test_backfill_trend_changes_wires_period_and_unit_arguments(
    monkeypatch,
):
    captured: Dict[str, object] = {}

    def _fake_prev_from_history(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {
            "previous_value": 2.0,
            "change_rate": 1.0,
            "reason": None,
            "value_source": "event_history_backfill",
        }

    monkeypatch.setattr(
        trend_backfill,
        "_calc_prev_from_event_history",
        _fake_prev_from_history,
    )
    market_data = {
        "metadata": {"date": "2026-06-30"},
        "macro_indicators": {
            "custom_macro": {
                "indicator_name": "Custom Macro",
                "current_value": 3.0,
                "previous_value": None,
                "change_rate": None,
                "report_period": "2026-06",
                "unit": "%",
            }
        },
    }

    trend_backfill._backfill_trend_changes(
        market_data,
        base_dir=Path("/tmp/trend-history-test"),
    )

    assert captured["args"][:3] == (
        "custom_macro",
        3.0,
        "2026-06-30",
    )
    assert captured["kwargs"]["current_period"] == "2026-06"
    assert captured["kwargs"]["unit"] == "%"
    assert captured["kwargs"]["base_dir"] == Path("/tmp/trend-history-test")


def test_backfill_trend_changes_preserves_non_backfill_value_source(tmp_path):
    _write_events(
        tmp_path,
        "custom_macro",
        [
            {"report_period": "2026-05", "value": 2.0},
            {"report_period": "2026-06", "value": 3.0},
        ],
    )
    market_data = {
        "metadata": {"date": "2026-06-30"},
        "macro_indicators": {
            "custom_macro": {
                "indicator_name": "Custom Macro",
                "current_value": 3.0,
                "previous_value": None,
                "change_rate": None,
                "report_period": "2026-06",
                "unit": "%",
                "value_source": "manual_override",
            }
        },
    }

    trend_backfill._backfill_trend_changes(market_data, base_dir=tmp_path)

    indicator = market_data["macro_indicators"]["custom_macro"]
    assert indicator["previous_value"] == 2.0
    assert indicator["change_rate"] == 1.0
    assert indicator["value_source"] == "manual_override"
