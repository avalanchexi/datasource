"""Pre-write contract validation for pipeline JSON outputs."""
from __future__ import annotations

import os
from typing import Any

from datasource.models.market_data_contract import MarketDataContract
from datasource.models.pring_result_contract import PringResultContract


class ContractValidationError(Exception):
    """Raised when a pipeline payload fails its contract before write."""


def _bypassed() -> bool:
    return os.getenv("DATASOURCE_NO_VALIDATE_OUTPUT") == "1"


def _model_validate(model: Any, payload: Any) -> None:
    validate = getattr(model, "model_validate", None)
    if validate is not None:
        validate(payload)
    else:
        model.parse_obj(payload)


def validate_market_data(payload: Any) -> None:
    if _bypassed():
        return
    try:
        _model_validate(MarketDataContract, payload)
    except Exception as exc:  # noqa: BLE001 - re-raise as contract error
        raise ContractValidationError(
            f"market_data contract validation failed:\n{exc}"
        ) from exc


def validate_pring_result(payload: Any) -> None:
    if _bypassed():
        return
    try:
        _model_validate(PringResultContract, payload)
    except Exception as exc:  # noqa: BLE001
        raise ContractValidationError(
            f"pring_result contract validation failed:\n{exc}"
        ) from exc
