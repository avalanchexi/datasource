"""Estimated fallback provider for the 10Y CDB yield."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.chinabond import ChinaBondProvider
from datasource.providers.stage2_structured.source_tiers import classify_structured_source_tier


SpreadProvenance = Dict[str, Any]


class CDBEstimatorResult(StructuredResult):
    @property
    def note(self) -> str:
        payload_note = self.payload.get("note")
        if payload_note:
            return "{0}; {1}".format(super().note, payload_note)
        return super().note


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
        proxy_yield = self._safe_number(self._proxy_yield_value(cn10y))
        if proxy_yield is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="missing_cn10y_proxy",
                message="CN10Y_CDB estimator requires an existing CN10Y yield",
                diagnostics={"source_url": self.source_url},
            )
        if proxy_yield <= 0:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="invalid_cn10y_proxy",
                message="CN10Y_CDB estimator requires a positive CN10Y yield",
                diagnostics={"source_url": self.source_url, "proxy_yield": proxy_yield},
            )

        spread = self._spread_provenance(task, market_payload)
        spread_bp = float(spread["bp"])
        spread_source = str(spread["source"])
        result_source_url = str(spread.get("source_url") or self.source_url)
        spread_source_url = spread.get("source_url")
        spread_observed_date = spread.get("observed_date")
        spread_note = spread.get("note")
        estimated_yield = round(proxy_yield + spread_bp / 100.0, 4)
        change_5d = self._safe_number(cn10y.get("change_5d_bp"))
        change_120d = self._safe_number(cn10y.get("change_120d_bp"))
        estimation_basis = (
            "cn10y_proxy_change_basis; "
            "CN10Y_CDB estimated from CN10Y proxy yield and explicit CDB spread; "
            "spread_source={0}".format(spread_source)
        )
        note_parts = [
            "CN10Y_CDB estimated from CN10Y proxy plus configured CDB spread",
            "cn10y_proxy_change_basis",
        ]
        if spread_source == "metadata.cn10y_cdb_spread.bp":
            note_parts.append("structured_metadata_spread")
        if spread_observed_date:
            note_parts.append(
                "spread_observed_date={0}".format(str(spread_observed_date))
            )
        if spread_note:
            note_parts.append("spread_note={0}".format(str(spread_note)))
        note = "; ".join(note_parts)
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
        return CDBEstimatorResult(
            provider=self.name,
            indicator_key=key,
            category="bonds",
            payload=payload,
            source="CN10Y proxy plus configured CDB spread",
            source_url=result_source_url,
            source_tier=classify_structured_source_tier(result_source_url),
            as_of_date=str(cn10y.get("date") or cn10y.get("as_of_date") or reference_date),
            confidence=0.65,
            diagnostics={
                "proxy_symbol": "CN10Y",
                "proxy_yield": proxy_yield,
                "spread_bp": spread_bp,
                "spread_source": spread_source,
                "spread_source_url": (
                    str(spread_source_url) if spread_source_url else None
                ),
                "spread_observed_date": (
                    str(spread_observed_date) if spread_observed_date else None
                ),
                "spread_note": str(spread_note) if spread_note else None,
                "estimated_yield": estimated_yield,
                "estimation_method": "CN10Y plus observed CDB spread",
                "estimation_basis": estimation_basis,
                "source_url": result_source_url,
            },
        )

    @staticmethod
    def _find_cn10y_entry(market_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        for entry in market_payload.get("bonds") or []:
            if isinstance(entry, Mapping) and str(entry.get("symbol") or "") == "CN10Y":
                return entry
        return {}

    @staticmethod
    def _proxy_yield_value(cn10y: Mapping[str, Any]) -> Any:
        current_yield = cn10y.get("current_yield")
        if current_yield not in (None, "", "N/A"):
            return current_yield
        return cn10y.get("current_value")

    def _spread_provenance(
        self,
        task: Mapping[str, Any],
        market_payload: Mapping[str, Any],
    ) -> SpreadProvenance:
        task_spread = self._safe_number(task.get("cdb_spread_bp"))
        if task_spread is not None:
            return {"bp": task_spread, "source": "task.cdb_spread_bp"}

        metadata = market_payload.get("metadata")
        if isinstance(metadata, Mapping):
            structured_spread = metadata.get("cn10y_cdb_spread")
            if isinstance(structured_spread, Mapping):
                structured_spread_bp = self._safe_number(structured_spread.get("bp"))
                if structured_spread_bp is not None:
                    provenance: SpreadProvenance = {
                        "bp": structured_spread_bp,
                        "source": "metadata.cn10y_cdb_spread.bp",
                    }
                    for field in ("source_url", "observed_date", "note"):
                        value = structured_spread.get(field)
                        if value not in (None, ""):
                            provenance[field] = value
                    return provenance

            metadata_spread = self._safe_number(metadata.get("cn10y_cdb_spread_bp"))
            if metadata_spread is not None:
                return {
                    "bp": metadata_spread,
                    "source": "metadata.cn10y_cdb_spread_bp",
                }

        if self.default_spread_bp is not None:
            return {
                "bp": self.default_spread_bp,
                "source": "constructor_default_spread_bp",
            }

        raise StructuredProviderError(
            provider=self.name,
            indicator_key=str(task.get("indicator_key") or ""),
            reason="missing_cdb_spread",
            message="CN10Y_CDB estimator requires explicit CDB spread provenance",
            diagnostics={
                "source_url": self.source_url,
                "required_spread_fields": [
                    "task.cdb_spread_bp",
                    "metadata.cn10y_cdb_spread.bp",
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
