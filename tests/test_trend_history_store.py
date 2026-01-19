import json
from pathlib import Path
import pytest

from datasource.utils.trend_history_store import SeriesRecord, write_series_record, write_from_market_data


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
