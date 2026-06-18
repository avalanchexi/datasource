import json
from pathlib import Path

import pytest

from datasource.models.market_data_contract import MarketDataContract
from datasource.models.pring_result_contract import PringResultContract

ROOT = Path(__file__).resolve().parents[1]
MARKET_DATA_PATTERN = "data/runs/2026*/market_data_complete.json"
PRING_RESULT_PATTERN = "data/runs/2026*/pring_result.json"
GOLDEN_DIR = ROOT / "tests/fixtures/pring_golden"


def _discover_fixtures(pattern, fallback):
    paths = sorted(ROOT.glob(pattern))
    if paths:
        return paths
    if fallback.exists():
        return [fallback]
    return []


MD = _discover_fixtures(
    MARKET_DATA_PATTERN,
    GOLDEN_DIR / "market_data_complete.json",
)
PR = _discover_fixtures(
    PRING_RESULT_PATTERN,
    GOLDEN_DIR / "pring_result.json",
)

assert MD, (
    "expected market data fixtures under local "
    f"{MARKET_DATA_PATTERN} or tracked tests/fixtures/pring_golden"
)
assert PR, (
    "expected pring result fixtures under local "
    f"{PRING_RESULT_PATTERN} or tracked tests/fixtures/pring_golden"
)


def _load_json(path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _model_validate(model, payload):
    validate = getattr(model, "model_validate", None)
    if validate is not None:
        return validate(payload)
    return model.parse_obj(payload)


@pytest.mark.parametrize("path", MD)
def test_real_market_data_validates(path):
    _model_validate(MarketDataContract, _load_json(path))


@pytest.mark.parametrize("path", PR)
def test_real_pring_result_validates(path):
    _model_validate(PringResultContract, _load_json(path))
