import importlib.util
from pathlib import Path


def _load_sanitizer():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "sanitize_market_data.py"
    spec = importlib.util.spec_from_file_location("sanitize_market_data", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sanitize_marks_placeholders_manual_required():
    sanitizer = _load_sanitizer()
    payload = {
        "commodities": [{"current_price": 7.13, "source": "legacy"}],
        "bonds": [{"current_yield": 0, "source": "legacy", "is_estimated": True}],
    }

    commodity_count, bond_count = sanitizer._sanitize(payload)

    assert (commodity_count, bond_count) == (1, 1)
    commodity = payload["commodities"][0]
    bond = payload["bonds"][0]
    assert commodity["current_price"] is None
    assert commodity["source"] == "Stage2.5 manual_required"
    assert commodity["manual_required"] is True
    assert bond["current_yield"] is None
    assert bond["source"] == "Stage2.5 manual_required"
    assert bond["manual_required"] is True
    assert bond["is_estimated"] is False
