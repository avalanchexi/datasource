import json
from pathlib import Path

import pytest

from datasource.models.market_data_contract import MarketDataContract
from datasource.models.pring_result_contract import PringResultContract

ROOT = Path(__file__).resolve().parents[1]
MD = sorted(ROOT.glob("data/runs/2026*/market_data_complete.json"))
PR = sorted(ROOT.glob("data/runs/2026*/pring_result.json"))

assert MD, "expected real fixtures under data/runs/2026*/market_data_complete.json"
assert PR, "expected real fixtures under data/runs/2026*/pring_result.json"


def _load_json(path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("path", MD)
def test_real_market_data_validates(path):
    MarketDataContract.model_validate(_load_json(path))


@pytest.mark.parametrize("path", PR)
def test_real_pring_result_validates(path):
    PringResultContract.model_validate(_load_json(path))
