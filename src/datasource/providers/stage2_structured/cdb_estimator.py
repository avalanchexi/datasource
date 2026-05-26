"""Estimated fallback provider for the 10Y CDB yield."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.chinabond import ChinaBondProvider
from datasource.providers.stage2_structured.source_tiers import classify_structured_source_tier


class CDBEstimatorProvider(Stage2StructuredProvider):
    name = "cdb_estimator"
    supported_keys = {"CN10Y_CDB"}

    def __init__(
        self,
        *,
        default_spread_bp: Optional[float] = None,
        source_url: str = ChinaBondProvider.source_url,
    ) -> None:
        self.default_spread_bp = (
            None if default_spread_bp is None else float(default_spread_bp)
        )
        self.source_url = source_url

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        if key != "CN10Y_CDB":
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="unsupported_key",
                message="CDB estimator provider does not support {0}".format(key),
            )

        cn10y = self._find_cn10y_entry(market_payload)
        proxy_yield = self._safe_number(cn10y.get("current_yield") or cn10y.get("current_value"))
        if proxy_yield is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="missing_cn10y_proxy",
                message="CN10Y_CDB estimator requires an existing CN10Y yield",
                diagnostics={"source_url": self.source_url},
            )

        spread_bp, spread_source = self._spread_bp(task, market_payload)
        estimated_yield = round(proxy_yield + spread_bp / 100.0, 4)
        change_5d = self._safe_number(cn10y.get("change_5d_bp"))
        change_120d = self._safe_number(cn10y.get("change_120d_bp"))
        estimation_basis = (
            "cn10y_proxy_change_basis; "
            "CN10Y_CDB estimated from CN10Y proxy yield and explicit CDB spread; "
            "spread_source={0}".format(spread_source)
        )
        note = (
            "CN10Y_CDB estimated from CN10Y proxy plus configured CDB spread; "
            "cn10y_proxy_change_basis"
        )
        payload = {
            "value": estimated_yield,
            "current_yield": estimated_yield,
            "unit": "%",
            "change_5d_bp": change_5d,
            "change_120d_bp": change_120d,
            "is_estimated": True,
            "estimation_method": "CN10Y plus observed CDB spread",
            "metric_basis": "cn10y_proxy_plus_spread",
            "estimation_basis": estimation_basis,
            "note": note,
        }
        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category="bonds",
            payload=payload,
            source="CN10Y proxy plus configured CDB spread",
            source_url=self.source_url,
            source_tier=classify_structured_source_tier(self.source_url),
            as_of_date=str(cn10y.get("date") or cn10y.get("as_of_date") or reference_date),
            confidence=0.65,
            diagnostics={
                "proxy_symbol": "CN10Y",
                "proxy_yield": proxy_yield,
                "spread_bp": spread_bp,
                "spread_source": spread_source,
                "estimated_yield": estimated_yield,
                "estimation_method": "CN10Y plus observed CDB spread",
                "estimation_basis": estimation_basis,
                "source_url": self.source_url,
            },
        )

    @staticmethod
    def _find_cn10y_entry(market_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        for entry in market_payload.get("bonds") or []:
            if isinstance(entry, Mapping) and str(entry.get("symbol") or "") == "CN10Y":
                return entry
        return {}

    def _spread_bp(
        self,
        task: Mapping[str, Any],
        market_payload: Mapping[str, Any],
    ) -> Tuple[float, str]:
        task_spread = self._safe_number(task.get("cdb_spread_bp"))
        if task_spread is not None:
            return task_spread, "task.cdb_spread_bp"

        metadata = market_payload.get("metadata")
        if isinstance(metadata, Mapping):
            metadata_spread = self._safe_number(metadata.get("cn10y_cdb_spread_bp"))
            if metadata_spread is not None:
                return metadata_spread, "metadata.cn10y_cdb_spread_bp"

        if self.default_spread_bp is not None:
            return self.default_spread_bp, "constructor_default_spread_bp"

        raise StructuredProviderError(
            provider=self.name,
            indicator_key=str(task.get("indicator_key") or ""),
            reason="missing_cdb_spread",
            message="CN10Y_CDB estimator requires explicit CDB spread provenance",
            diagnostics={
                "source_url": self.source_url,
                "required_spread_fields": [
                    "task.cdb_spread_bp",
                    "metadata.cn10y_cdb_spread_bp",
                ],
            },
        )

    @staticmethod
    def _safe_number(value: Any) -> Optional[float]:
        try:
            if value in (None, "", "N/A"):
                return None
            return float(value)
        except Exception:
            return None


def build_provider() -> CDBEstimatorProvider:
    return CDBEstimatorProvider()
