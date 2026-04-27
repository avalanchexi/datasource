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
    assert paths.market_data_stage2 == Path("data/runs/20260427/market_data_stage2.json")
    assert paths.market_data_complete == Path("data/runs/20260427/market_data_complete.json")
    assert paths.pring_result == Path("data/runs/20260427/pring_result.json")
    assert paths.gap_monitor == Path("data/runs/20260427/gap_monitor.json")
    assert paths.stage2_log == Path("logs/runs/20260427/stage2_unified_log.json")
    assert paths.report_markdown == Path("reports/2026-04-27-背景扫描120.md")


def test_build_run_paths_from_payload_metadata_date():
    payload = {"metadata": {"date": "2026-04-27"}}
    paths = build_run_paths_from_reference(payload=payload)
    assert paths.market_data_complete == Path("data/runs/20260427/market_data_complete.json")


def test_infer_date_from_path_supports_run_dir_and_report_name():
    assert infer_date_from_path("data/runs/20260427/market_data.json") == "2026-04-27"
    assert infer_date_from_path("reports/2026-04-27-背景扫描120.md") == "2026-04-27"
