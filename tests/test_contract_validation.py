import glob
import json

import pytest

from datasource.models.market_data_contract import MarketDataContract
from datasource.models.pring_result_contract import PringResultContract

MD = sorted(glob.glob("data/runs/2026*/market_data_complete.json"))
PR = sorted(glob.glob("data/runs/2026*/pring_result.json"))


@pytest.mark.parametrize("path", MD)
def test_real_market_data_validates(path):
    MarketDataContract.model_validate(json.load(open(path, encoding="utf-8")))


@pytest.mark.parametrize("path", PR)
def test_real_pring_result_validates(path):
    PringResultContract.model_validate(json.load(open(path, encoding="utf-8")))
