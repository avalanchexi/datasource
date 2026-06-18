import json
from pathlib import Path

import pytest

from datasource.models.market_data_contract import MarketDataContract
from datasource.models.pring_result_contract import PringResultContract
from datasource.utils.contract_validation import (
    ContractValidationError,
    validate_market_data,
    validate_pring_result,
)

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


def _good_market_payload():
    return _load_json(MD[-1])


def _good_pring_payload():
    return _load_json(PR[-1])


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


def test_validate_market_data_ok():
    validate_market_data(_good_market_payload())


def test_validate_market_data_missing_required_raises():
    payload = _good_market_payload()
    del payload["stock_indices"]

    with pytest.raises(ContractValidationError):
        validate_market_data(payload)


def test_validate_market_data_bad_type_raises():
    payload = _good_market_payload()
    payload["commodities"][0]["current_price"] = "not-a-number"

    with pytest.raises(ContractValidationError):
        validate_market_data(payload)


def test_validate_pring_missing_required_raises():
    payload = _good_pring_payload()
    del payload["stage"]

    with pytest.raises(ContractValidationError):
        validate_pring_result(payload)


def test_no_validate_env_bypasses(monkeypatch):
    monkeypatch.setenv("DATASOURCE_NO_VALIDATE_OUTPUT", "1")

    validate_market_data({"garbage": True})
    validate_pring_result({"garbage": True})
