import json
from pathlib import Path
import pytest

from datasource.utils.trend_history_store import (
    SeriesRecord,
    scan_trend_history,
    write_trend_history_gap_snapshot,
    write_from_market_data,
    write_series_record,
)


def test_series_trim_window(tmp_path: Path):
    base_dir = tmp_path / "trend"
    for i in range(210):
        record = SeriesRecord(
            date=f"2025-01-{i+1:02d}" if i < 31 else f"2025-02-{i-30:02d}",
            value=float(i),
            unit=None,
            source="test",
            source_timestamp=None,
            market_calendar="CN",
            is_estimated=False,
            is_partial=False,
        )
        write_series_record("stock_indices", "000300", record, base_dir=base_dir)

    path = base_dir / "series" / "stock_indices" / "000300.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["values"]) == 200


def test_block_reports_source(tmp_path: Path):
    market_data = {
        "metadata": {"date": "2025-01-01"},
        "stock_indices": [{"symbol": "000300", "current_price": 1.0, "source": "test"}],
    }
    with pytest.raises(ValueError):
        write_from_market_data(market_data, is_partial=True, source_path=Path("reports/fake.md"), base_dir=tmp_path)


def test_scan_trend_history_reports_estimated_and_partial_ratios(tmp_path: Path):
    base_dir = tmp_path / "trend"
    write_series_record(
        "commodities",
        "BCOM",
        SeriesRecord(
            date="2026-04-27",
            value=131.48,
            unit="points",
            source="manual",
            source_timestamp=None,
            market_calendar="GLOBAL",
            is_estimated=True,
            is_partial=False,
        ),
        base_dir=base_dir,
    )
    write_series_record(
        "commodities",
        "BCOM",
        SeriesRecord(
            date="2026-04-28",
            value=132.0,
            unit="points",
            source="manual",
            source_timestamp=None,
            market_calendar="GLOBAL",
            is_estimated=False,
            is_partial=True,
        ),
        base_dir=base_dir,
    )

    result = scan_trend_history("2026-04-28", base_dir=base_dir)

    quality = result["series"]["quality"]
    bcom = next(item for item in quality if item["category"] == "commodities" and item["symbol"] == "BCOM")
    assert bcom["count"] == 2
    assert bcom["estimated_count"] == 1
    assert bcom["estimated_ratio"] == 0.5
    assert bcom["partial_count"] == 1
    assert bcom["partial_ratio"] == 0.5


def test_write_trend_history_gap_snapshot_writes_run_file(tmp_path: Path):
    base_dir = tmp_path / "trend"
    output_path = tmp_path / "data" / "runs" / "20260428" / "trend_history_gap.json"
    write_series_record(
        "forex",
        "USDCNY",
        SeriesRecord(
            date="2026-04-28",
            value=6.86,
            unit=None,
            source="manual",
            source_timestamp=None,
            market_calendar="GLOBAL",
            is_estimated=False,
            is_partial=False,
        ),
        base_dir=base_dir,
    )

    payload = write_trend_history_gap_snapshot("2026-04-28", output_path, base_dir=base_dir)

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved == payload
    assert saved["date"] == "2026-04-28"
    assert isinstance(saved["series"]["missing"], list)
    assert isinstance(saved["series"]["insufficient"], list)
    assert isinstance(saved["series"]["stale"], list)
    assert isinstance(saved["events"]["missing"], list)
    assert isinstance(saved["events"]["insufficient"], list)
    assert any(item["category"] == "forex" and item["symbol"] == "USDCNY" for item in saved["series"]["quality"])
