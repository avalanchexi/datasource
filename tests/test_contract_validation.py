import importlib
import json
import warnings
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from datasource.models import market_data_contract as market_contract
from datasource.models.market_data_contract import (
    MacroIndicatorData,
    MarketDataContract,
)
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
GOLDEN_MARKET_DATA = GOLDEN_DIR / "market_data_complete.json"
GOLDEN_PRING_RESULT = GOLDEN_DIR / "pring_result.json"


def _discover_fixtures(pattern, fallback):
    paths = sorted(ROOT.glob(pattern))
    if paths:
        return paths
    if fallback.exists():
        return [fallback]
    return []


MD = _discover_fixtures(
    MARKET_DATA_PATTERN,
    GOLDEN_MARKET_DATA,
)
PR = _discover_fixtures(
    PRING_RESULT_PATTERN,
    GOLDEN_PRING_RESULT,
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
    return _load_json(GOLDEN_MARKET_DATA)


def _good_pring_payload():
    return _load_json(GOLDEN_PRING_RESULT)


def _model_validate(model, payload):
    validate = getattr(model, "model_validate", None)
    if validate is not None:
        return validate(payload)
    return model.parse_obj(payload)


def test_discover_fixtures_falls_back_to_tracked_golden_when_runs_missing():
    fixtures = _discover_fixtures(
        "data/runs/0000*/market_data_complete.json",
        GOLDEN_MARKET_DATA,
    )

    assert fixtures == [GOLDEN_MARKET_DATA]


def test_market_data_contract_import_has_no_v1_validator_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(market_contract)

    v1_validator_warnings = [
        warning
        for warning in caught
        if "Pydantic V1 style `@validator` validators are deprecated"
        in str(warning.message)
    ]
    assert v1_validator_warnings == []


@pytest.mark.parametrize("path", MD)
def test_real_market_data_validates(path):
    _model_validate(MarketDataContract, _load_json(path))


@pytest.mark.parametrize("path", PR)
def test_real_pring_result_validates(path):
    _model_validate(PringResultContract, _load_json(path))


def test_validate_market_data_ok():
    validate_market_data(_good_market_payload())


def test_validate_market_data_does_not_mutate_payload():
    payload = _good_market_payload()
    before = deepcopy(payload)

    validate_market_data(payload)

    assert payload == before


def test_validate_market_data_missing_required_raises():
    payload = _good_market_payload()
    del payload["stock_indices"]

    with pytest.raises(ContractValidationError) as exc_info:
        validate_market_data(payload)

    assert "market_data contract validation failed" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, ValidationError)


def test_validate_market_data_bad_type_raises():
    payload = _good_market_payload()
    assert payload["commodities"]
    payload["commodities"][0]["current_price"] = "not-a-number"

    with pytest.raises(ContractValidationError):
        validate_market_data(payload)


def test_macro_indicator_contract_preserves_value_source():
    indicator = _model_validate(
        MacroIndicatorData,
        {
            "indicator_name": "Custom Macro",
            "current_value": 3.0,
            "previous_value": 2.0,
            "change_rate": 1.0,
            "unit": "%",
            "date": "2026-06",
            "source": "manual",
            "value_source": "event_history_backfill",
        },
    )

    assert indicator.value_source == "event_history_backfill"


def test_validate_market_data_non_validation_error_propagates(monkeypatch):
    payload = _good_market_payload()
    message = "unexpected validation plumbing failure"

    def raise_unexpected_error(model, payload):
        raise RuntimeError(message)

    monkeypatch.setattr(
        "datasource.utils.contract_validation._model_validate",
        raise_unexpected_error,
    )

    with pytest.raises(RuntimeError, match=message):
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
