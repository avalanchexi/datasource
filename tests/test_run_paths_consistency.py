from pathlib import Path

import pytest

from datasource.utils.run_paths import (
    build_run_paths,
    build_run_paths_from_reference,
    infer_date_from_path,
    normalize_run_date,
)


def test_normalize_run_date_accepts_dashed_and_compact():
    assert normalize_run_date("2026-04-27") == "2026-04-27"
    assert normalize_run_date("20260427") == "2026-04-27"


def test_normalize_run_date_rejects_invalid():
    with pytest.raises(ValueError):
        normalize_run_date("2026/04/27")


def test_build_run_paths_defaults():
    paths = build_run_paths("2026-04-27")
    assert paths.market_data == Path("data/runs/20260427/market_data.json")
    assert paths.market_data_stage2 == Path(
        "data/runs/20260427/market_data_stage2.json"
    )
    assert paths.market_data_complete == Path(
        "data/runs/20260427/market_data_complete.json"
    )
    assert paths.pring_result == Path("data/runs/20260427/pring_result.json")
    assert paths.gap_monitor == Path("data/runs/20260427/gap_monitor.json")
    assert paths.stage2_log == Path(
        "logs/runs/20260427/stage2_unified_log.json"
    )
    assert paths.report_markdown == Path("reports/2026-04-27-背景扫描120.md")


def test_data_dir_whitelist_matches_expected():
    paths = build_run_paths("2026-06-10")
    expected = {
        "market_data.json",
        "market_data_stage2.json",
        "market_data_complete.json",
        "pring_result.json",
        "search_tasks_stage2.jsonl",
        "websearch_results_auto.json",
        "websearch_results_manual.json",
        "gap_monitor.json",
        "quality_metrics.json",
        "quality_trend.csv",
        "policy_evaluation.json",
        "run_snapshot.json",
        "source_conflicts.json",
        "stage4_risk_review.json",
        "trend_history_gap.json",
        "recap_facts.json",
        "stage2_log.json",
        ".run.lock",
    }
    data_dir_property_names = {
        "market_data",
        "market_data_stage2",
        "market_data_complete",
        "pring_result",
        "search_tasks_stage2",
        "websearch_results_auto",
        "websearch_results_manual",
        "gap_monitor",
        "quality_metrics",
        "quality_trend",
        "policy_evaluation",
        "run_snapshot",
        "source_conflicts",
        "stage4_risk_review",
        "trend_history_gap",
        "recap_facts",
        "stage2_log_data",
        "run_lock",
    }

    assert paths.data_dir_whitelist() == expected
    data_dir_property_basenames = {
        getattr(paths, name).name for name in data_dir_property_names
    }
    assert data_dir_property_basenames == expected


def test_build_run_paths_from_payload_metadata_date():
    payload = {"metadata": {"date": "2026-04-27"}}
    paths = build_run_paths_from_reference(payload=payload)
    assert paths.market_data_complete == Path(
        "data/runs/20260427/market_data_complete.json"
    )


def test_infer_date_from_path_supports_run_dir_and_report_name():
    assert (
        infer_date_from_path("data/runs/20260427/market_data.json")
        == "2026-04-27"
    )
    assert (
        infer_date_from_path("reports/2026-04-27-背景扫描120.md")
        == "2026-04-27"
    )
