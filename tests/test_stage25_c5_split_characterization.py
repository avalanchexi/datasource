"""C5 Stage2.5 split characterization.

All tests are offline. Expected values are captured from current monolith
behavior before moving the remaining Stage2.5 execution helpers.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from datasource.engines.stage2_5 import cli, common, core, entry_mergers, trend_backfill

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

INJ = importlib.import_module("stage2_5_injector")


C5_MOVED_NAMES = [
    "InjectionSummary",
    "_append_non_blocking_warning",
    "_collect_gc_non_blocking_warnings",
    "_derive_date_compact",
    "_enforce_quality_blockers",
    "_write_unified_quality_artifacts",
    "_cleanup_monetary_aliases",
    "inject_websearch_data",
    "inject_websearch_results",
    "_post_injection_validation",
    "_format_source_label",
    "_update_metadata_only",
    "_merge_same_value_report_fields",
    "_apply_macro_entry",
    "_create_monetary_placeholder",
    "_create_macro_placeholder",
    "_apply_monetary_entry",
    "_apply_fund_flow_entry",
    "_is_suspicious_fund_flow_pair",
    "_infer_trend",
    "_infer_asset_trend",
    "_build_fund_flow_note",
    "_parse_date",
    "_load_series_records",
    "_calc_change_from_trend_history",
    "_calc_daily_change_from_trend_history",
    "_load_event_history",
    "_calc_change_from_event_history",
    "_calc_prev_from_event_history",
    "_should_backfill_numeric",
    "_is_forex_daily_change_absence_text",
    "_is_valid_forex_daily_change_base_date",
    "_is_valid_forex_daily_change_source_url",
    "_is_valid_forex_change_base_price",
    "_has_forex_daily_change_computed_marker",
    "_has_forex_120d_change_computed_marker",
    "_has_forex_daily_change_evidence",
    "_copy_valid_forex_daily_change_evidence",
    "_copy_valid_forex_120d_change_evidence",
    "_has_forex_120d_change_evidence",
    "_is_zero_change_value",
    "_should_backfill_forex_daily_change",
    "_should_backfill_forex_120d_change",
    "_usable_forex_change_value",
    "_is_zero_derived_forex_trend",
    "_usable_forex_raw_trend",
    "_backfill_cdb_proxy_changes_from_cn10y",
    "_remove_note_markers",
    "_record_backfill_issue",
    "_merge_trend_confidence",
    "_derive_trend_confidence",
    "_backfill_trend_changes",
    "_run_post_write_trend_backfill",
    "_sync_backfill_issues_to_logs",
    "_merge_stock_index_entry",
    "_build_stock_index_entry",
    "_merge_bond_entry",
    "_merge_commodity_entry",
    "_merge_forex_entry",
    "_build_forex_entry",
    "_default_cli_paths",
    "parse_args",
    "main",
]


@pytest.mark.parametrize("name", C5_MOVED_NAMES)
def test_c5_import_surface_monolith(name):
    assert hasattr(INJ, name), f"stage2_5_injector should still export {name}"


def test_c5_reexports_are_canonical_module_objects():
    expected = {
        "InjectionSummary": core.InjectionSummary,
        "_append_non_blocking_warning": core._append_non_blocking_warning,
        "_collect_gc_non_blocking_warnings": core._collect_gc_non_blocking_warnings,
        "_derive_date_compact": core._derive_date_compact,
        "_enforce_quality_blockers": core._enforce_quality_blockers,
        "_write_unified_quality_artifacts": core._write_unified_quality_artifacts,
        "_cleanup_monetary_aliases": core._cleanup_monetary_aliases,
        "inject_websearch_data": core.inject_websearch_data,
        "inject_websearch_results": core.inject_websearch_results,
        "_post_injection_validation": core._post_injection_validation,
        "_format_source_label": common._format_source_label,
        "_update_metadata_only": common._update_metadata_only,
        "_merge_same_value_report_fields": common._merge_same_value_report_fields,
        "_apply_macro_entry": entry_mergers._apply_macro_entry,
        "_create_monetary_placeholder": entry_mergers._create_monetary_placeholder,
        "_create_macro_placeholder": entry_mergers._create_macro_placeholder,
        "_apply_monetary_entry": entry_mergers._apply_monetary_entry,
        "_apply_fund_flow_entry": entry_mergers._apply_fund_flow_entry,
        "_is_suspicious_fund_flow_pair": entry_mergers._is_suspicious_fund_flow_pair,
        "_build_fund_flow_note": entry_mergers._build_fund_flow_note,
        "_merge_stock_index_entry": entry_mergers._merge_stock_index_entry,
        "_build_stock_index_entry": entry_mergers._build_stock_index_entry,
        "_merge_bond_entry": entry_mergers._merge_bond_entry,
        "_merge_commodity_entry": entry_mergers._merge_commodity_entry,
        "_merge_forex_entry": entry_mergers._merge_forex_entry,
        "_build_forex_entry": entry_mergers._build_forex_entry,
        "_infer_trend": trend_backfill._infer_trend,
        "_infer_asset_trend": trend_backfill._infer_asset_trend,
        "_parse_date": trend_backfill._parse_date,
        "_load_series_records": trend_backfill._load_series_records,
        "_calc_change_from_trend_history": (
            trend_backfill._calc_change_from_trend_history
        ),
        "_calc_daily_change_from_trend_history": (
            trend_backfill._calc_daily_change_from_trend_history
        ),
        "_load_event_history": trend_backfill._load_event_history,
        "_calc_change_from_event_history": (
            trend_backfill._calc_change_from_event_history
        ),
        "_calc_prev_from_event_history": trend_backfill._calc_prev_from_event_history,
        "_should_backfill_numeric": trend_backfill._should_backfill_numeric,
        "_is_forex_daily_change_absence_text": (
            trend_backfill._is_forex_daily_change_absence_text
        ),
        "_is_valid_forex_daily_change_base_date": (
            trend_backfill._is_valid_forex_daily_change_base_date
        ),
        "_is_valid_forex_daily_change_source_url": (
            trend_backfill._is_valid_forex_daily_change_source_url
        ),
        "_is_valid_forex_change_base_price": (
            trend_backfill._is_valid_forex_change_base_price
        ),
        "_has_forex_daily_change_computed_marker": (
            trend_backfill._has_forex_daily_change_computed_marker
        ),
        "_has_forex_120d_change_computed_marker": (
            trend_backfill._has_forex_120d_change_computed_marker
        ),
        "_has_forex_daily_change_evidence": (
            trend_backfill._has_forex_daily_change_evidence
        ),
        "_copy_valid_forex_daily_change_evidence": (
            trend_backfill._copy_valid_forex_daily_change_evidence
        ),
        "_copy_valid_forex_120d_change_evidence": (
            trend_backfill._copy_valid_forex_120d_change_evidence
        ),
        "_has_forex_120d_change_evidence": (
            trend_backfill._has_forex_120d_change_evidence
        ),
        "_is_zero_change_value": trend_backfill._is_zero_change_value,
        "_should_backfill_forex_daily_change": (
            trend_backfill._should_backfill_forex_daily_change
        ),
        "_should_backfill_forex_120d_change": (
            trend_backfill._should_backfill_forex_120d_change
        ),
        "_usable_forex_change_value": trend_backfill._usable_forex_change_value,
        "_is_zero_derived_forex_trend": (
            trend_backfill._is_zero_derived_forex_trend
        ),
        "_usable_forex_raw_trend": trend_backfill._usable_forex_raw_trend,
        "_backfill_cdb_proxy_changes_from_cn10y": (
            trend_backfill._backfill_cdb_proxy_changes_from_cn10y
        ),
        "_remove_note_markers": trend_backfill._remove_note_markers,
        "_record_backfill_issue": trend_backfill._record_backfill_issue,
        "_merge_trend_confidence": trend_backfill._merge_trend_confidence,
        "_derive_trend_confidence": trend_backfill._derive_trend_confidence,
        "_backfill_trend_changes": trend_backfill._backfill_trend_changes,
        "_run_post_write_trend_backfill": (
            trend_backfill._run_post_write_trend_backfill
        ),
        "_sync_backfill_issues_to_logs": trend_backfill._sync_backfill_issues_to_logs,
        "_default_cli_paths": cli._default_cli_paths,
        "parse_args": cli.parse_args,
        "main": cli.main,
    }
    for name, canonical in expected.items():
        assert getattr(INJ, name) is canonical, name


def test_c5_entry_merger_reaches_qualified_trend_patch(monkeypatch):
    calls = []

    def fake_hist(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "change_120d": 4.56,
            "reason_120d": None,
            "base_120d_estimated": False,
            "base_120d_date": "2026-02-01",
        }

    monkeypatch.setattr(
        trend_backfill,
        "_calc_change_from_trend_history",
        fake_hist,
    )
    monkeypatch.setattr(
        trend_backfill,
        "_calc_daily_change_from_trend_history",
        lambda *args, **kwargs: {
            "change_1d": None,
            "reason_1d": "trend_history_missing",
        },
    )

    merged = INJ._merge_forex_entry(
        {"pair": "USDCNY", "name": "USD/CNY", "current_rate": None},
        {"pair": "USDCNY", "current_rate": "7.1", "source": "manual"},
        is_manual=True,
    )

    assert calls
    assert merged["change_120d"] == pytest.approx(4.56)
    assert merged["change_120d_basis"] == "trend_history"


@pytest.mark.parametrize(
    ("raw_source", "expected"),
    [
        (None, "websearch_manual"),
        ("", "websearch_manual"),
        ("manual_required: x", "websearch_manual"),
        ("websearch_manual", "websearch_manual"),
        ("websearch_manual(foo)", "websearch_manual(foo)"),
        ("tavily_search", "tavily_search"),
        ("https://example.com/a", "websearch_manual(https://example.com/a)"),
        ("source text", "websearch_manual(source text)"),
        ("异常零值-需核查", "异常零值-需核查"),
    ],
)
def test_common_extension_format_source_label_locked(raw_source, expected):
    assert INJ._format_source_label(raw_source) == expected


def test_common_extension_metadata_only_locked():
    entry = {"current_value": 10, "is_stale": True, "stale_reason": "old"}
    payload = {
        "date": "2026-01-02",
        "source": "manual source",
        "source_url": "https://example.com/a",
        "note": "n",
        "is_estimated": "false",
        "confidence": "high",
    }

    assert INJ._update_metadata_only(entry, payload) is True
    assert entry == {
        "current_value": 10,
        "is_stale": True,
        "stale_reason": "old",
        "date": "2026-01-02",
        "source": "websearch_manual(manual source)",
        "source_url": "https://example.com/a",
        "note": "n",
        "confidence": "high",
        "is_estimated": False,
    }


def test_common_extension_merge_same_value_report_fields_locked():
    entry = {"current_value": 10, "is_stale": True, "stale_reason": "old"}
    payload = {
        "previous_value": "8",
        "change_rate": "25",
        "value_type": "yoy",
        "report_period": "2026-01",
    }

    assert (
        INJ._merge_same_value_report_fields(
            entry,
            payload,
            category="macro_indicators",
            key="industrial",
        )
        is True
    )
    assert entry == {
        "current_value": 10,
        "is_stale": False,
        "stale_reason": None,
        "date": "2026-01",
        "as_of_date": "2026-01",
        "report_period": "2026-01",
        "previous_value": 8.0,
        "change_rate": 25.0,
        "value_type": "yoy",
    }


def _write_series(base_dir: Path) -> None:
    series_dir = base_dir / "series" / "commodities"
    series_dir.mkdir(parents=True)
    payload = {
        "values": [
            {"date": "2026-01-01", "value": 100},
            {"date": "2026-01-02", "value": 105},
            {"date": "2026-01-03", "value": 110},
            {"date": "2026-01-04", "value": 115},
            {"date": "2026-01-05", "value": 120},
        ]
    }
    (series_dir / "GC=F.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _write_events(base_dir: Path) -> None:
    events_dir = base_dir / "events"
    events_dir.mkdir()
    payload = {
        "events": [
            {"release_date": "2025-09-01", "value": 7.0},
            {"release_date": "2026-01-01", "value": 7.5},
        ]
    }
    (events_dir / "rrr.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_trend_backfill_history_calculations_locked(tmp_path):
    _write_series(tmp_path)
    _write_events(tmp_path)

    assert INJ._calc_change_from_trend_history(
        "commodities",
        "GC=F",
        125.0,
        base_dir=tmp_path,
        reference_date="2026-01-08",
    ) == {
        "change_5d": 25.0,
        "change_120d": None,
        "change_5d_bp": None,
        "change_120d_bp": None,
        "reason_5d": None,
        "reason_120d": "trend_history_insufficient",
        "base_5d_estimated": False,
        "base_120d_estimated": None,
        "base_5d_date": "2026-01-01",
        "base_120d_date": None,
        "latest_date": "2026-01-05",
    }
    assert INJ._calc_daily_change_from_trend_history(
        "commodities",
        "GC=F",
        125.0,
        base_dir=tmp_path,
        reference_date="2026-01-08",
    ) == {
        "change_1d": pytest.approx(4.166666666666666),
        "reason_1d": None,
        "base_1d_estimated": False,
        "base_1d_date": "2026-01-05",
    }
    assert INJ._calc_change_from_event_history(
        "rrr",
        8.0,
        "2026-01-10",
        base_dir=tmp_path,
    ) == {
        "change_from_120d": 1.0,
        "reason": None,
        "base_date": "2025-09-01",
        "base_estimated": False,
    }
    assert INJ._calc_prev_from_event_history(
        "rrr",
        7.5,
        "2026-01-10",
        base_dir=tmp_path,
    ) == {"previous_value": 7.0, "change_rate": 7.1429, "reason": None}


def test_trend_backfill_forex_and_confidence_helpers_locked():
    assert [INJ._should_backfill_numeric(x) for x in [None, "", 0, "0", "1.2", "N/A", "abc"]] == [
        True,
        True,
        True,
        True,
        False,
        True,
        True,
    ]
    assert [INJ._is_zero_change_value(x) for x in [None, "0", "0.0000000000001", "0.1"]] == [
        False,
        True,
        True,
        False,
    ]
    assert INJ._should_backfill_forex_daily_change({"daily_change": 0}) is True
    assert INJ._should_backfill_forex_120d_change({"change_120d": 0}) is True
    assert INJ._usable_forex_change_value({"daily_change": "1.2"}, "daily_change") == 1.2
    assert INJ._usable_forex_raw_trend("flat", None, 2.0) is None

    assert [INJ._infer_trend(raw, value) for raw, value in [(None, 1), (None, -1), ("custom", None)]] == [
        "流入",
        "流出",
        "custom",
    ]
    assert [
        INJ._infer_asset_trend(None, 6, None, "bond"),
        INJ._infer_asset_trend(None, 3, None, "forex"),
        INJ._infer_asset_trend(None, None, 11, "commodity"),
    ] == ["上行", "上涨", "强势上涨"]

    entry = {"trend_history_confidence": "high"}
    INJ._merge_trend_confidence(entry, "low")
    assert entry == {"trend_history_confidence": "low"}
    assert INJ._derive_trend_confidence(
        {"base_5d_estimated": False, "base_120d_estimated": False},
        used_5d=True,
        used_120d=True,
    ) == ("high", None)


def test_trend_backfill_cdb_proxy_locked():
    market_data = {
        "bonds": [
            {"symbol": "CN10Y", "change_5d_bp": 1.5, "change_120d_bp": -2.5},
            {
                "symbol": "CN10Y_CDB",
                "current_yield": 2.1,
                "is_estimated": True,
                "source": "cn10y proxy",
                "note": "based on 国债",
            },
        ]
    }

    assert INJ._backfill_cdb_proxy_changes_from_cn10y(market_data) == 2
    cdb = market_data["bonds"][1]
    assert cdb["change_5d_bp"] == 1.5
    assert cdb["change_120d_bp"] == -2.5
    assert cdb["trend"] == "平稳"
    assert cdb["note"] == "based on 国债；cn10y_proxy_change_basis"


def test_entry_mergers_stock_bond_commodity_forex_locked():
    assert INJ._merge_stock_index_entry(
        {"symbol": "000300", "name": "old", "current_price": 1},
        {"symbol": "000300", "current_price": "2", "source": "manual", "source_url": "https://example.com"},
    ) == {
        "symbol": "000300",
        "name": "old",
        "current_price": 2.0,
        "change_5d": 0.0,
        "change_120d": 0.0,
        "above_ma50": False,
        "above_ma200": False,
        "ma50_slope": 0.0,
        "volatility_30d": 0.0,
        "trend_score": 0,
        "trend_label": "中性",
        "source": "websearch_manual(manual)",
        "source_url": "https://example.com",
    }
    assert INJ._build_stock_index_entry(
        "000016",
        {"current_price": "3", "above_ma50": "true", "source": "manual"},
    )["above_ma50"] is True
    assert INJ._merge_bond_entry(
        {"symbol": "US10Y", "name": "US", "current_yield": 4.0, "change_5d_bp": 0, "change_120d_bp": 0},
        {"current_yield": "4.2", "source": "manual", "is_estimated": False},
        trend_history_base_dir=None,
    ) == {
        "symbol": "US10Y",
        "name": "US",
        "current_yield": 4.2,
        "change_5d_bp": 0,
        "change_120d_bp": 0,
        "trend": "平稳",
        "source": "websearch_manual(manual)",
        "is_estimated": False,
        "note": None,
    }

    commodity = INJ._merge_commodity_entry(
        {"symbol": "GC=F", "name": "Gold", "current_price": 2000, "daily_change": 1, "ytd_change": 2},
        {"current_price": "2100", "previous_price": "2000", "source": "manual", "timestamp": "2026-01-02"},
        trend_history_base_dir=None,
    )
    assert commodity["daily_change"] == 5.0
    assert commodity["trend"] == "横盘震荡"
    assert commodity["timestamp"] == "2026-01-02"

    forex = INJ._merge_forex_entry(
        {"pair": "USDCNY", "name": "USD/CNY", "current_rate": 7.1, "daily_change": 0.1, "change_120d": 1.0},
        {"current_rate": "7.2", "daily_change": "0.2", "change_120d": "1.2", "source": "manual"},
        trend_history_base_dir=None,
    )
    assert forex == {
        "pair": "USDCNY",
        "name": "USD/CNY",
        "current_rate": 7.2,
        "daily_change": 0.2,
        "change_120d": 1.2,
        "trend": "横盘震荡",
        "source": "websearch_manual(manual)",
        "note": None,
    }
    built_forex = INJ._build_forex_entry(
        {"pair": "EURUSD", "current_rate": "1.1", "daily_change": "0.5", "change_120d": "2", "source": "manual"},
        trend_history_base_dir=None,
    )
    assert built_forex["daily_change"] == 0.5
    assert built_forex["change_120d"] == 2.0
    assert built_forex["trend"] == "横盘震荡"


def test_entry_apply_functions_locked():
    fund_entry: dict = {}
    assert INJ._apply_fund_flow_entry(
        fund_entry,
        "northbound",
        {
            "recent_5d": "10",
            "total_120d": "30",
            "source_url": "https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Historical-Data",
            "window_evidence": "direct_window",
        },
    ) is True
    assert fund_entry == {
        "type": "northbound",
        "recent_5d": 10.0,
        "total_120d": 30.0,
        "trend": "流入",
        "source": "websearch_manual",
        "note": "原始5日:10；原始120日:30",
        "source_url": "https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Historical-Data",
        "metric_basis": "net_flow_sum",
        "source_tier": "tier1",
        "window_evidence": "direct_window",
        "is_estimated": False,
    }

    macro_entry = {"current_value": None}
    assert INJ._apply_macro_entry(
        "industrial",
        macro_entry,
        {"current_value": "4.5", "previous_value": "4.0", "source": "manual"},
        "2026-01-02",
        trend_history_base_dir=None,
    ) is True
    assert macro_entry["current_value"] == 4.5
    assert macro_entry["previous_value"] == 4.0
    assert macro_entry["change_rate"] == 12.5
    assert macro_entry["value_type"] == "yoy_month"


def test_core_summary_and_date_helpers_locked():
    assert INJ.InjectionSummary().to_dict() == {
        "counts": {
            "injected": 0,
            "metadata_updated": 0,
            "skipped_existing": 0,
            "skipped_no_parseable_value": 0,
            "forced_override": 0,
            "fund_flow_forced_estimated": 0,
        },
        "injected": [],
        "metadata_updated": [],
        "skipped_existing": [],
        "skipped_no_parseable_value": [],
        "forced_override": [],
        "fund_flow_forced_estimated": [],
    }
    assert INJ._derive_date_compact({"metadata": {"date": "2026-01-02"}}) == "20260102"
    assert INJ._derive_date_compact({}, "20260103") == "20260103"
