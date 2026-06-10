"""Registry and dispatch for Stage2 structured providers."""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from typing import Any, Iterable, List, Mapping, Optional

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)


class StructuredProviderRegistry:
    """Dispatch Stage2 tasks to the first structured provider that supports them."""

    def __init__(self, providers: Iterable[Stage2StructuredProvider]) -> None:
        self.providers = list(providers)

    def provider_for(self, indicator_key: str) -> Optional[Stage2StructuredProvider]:
        for provider in self.providers:
            if indicator_key in provider.supported_keys:
                return provider
        return None

    def providers_for(self, indicator_key: str) -> List[Stage2StructuredProvider]:
        return [
            provider
            for provider in self.providers
            if indicator_key in provider.supported_keys
        ]

    async def fetch(
        self,
        task: Mapping[str, Any],
        market_payload: Mapping[str, Any],
        reference_date: str,
    ) -> Optional[StructuredResult]:
        indicator_key = str(task.get("indicator_key", ""))
        providers = self.providers_for(indicator_key)
        if not providers:
            return None

        last_error = None
        attempts = []
        for provider in providers:
            try:
                result = await provider.fetch(task, market_payload, reference_date)
                if attempts:
                    diagnostics = dict(result.diagnostics or {})
                    diagnostics.setdefault("structured_provider_attempts", attempts)
                    return replace(result, diagnostics=diagnostics)
                return result
            except StructuredProviderError as exc:
                last_error = exc
                attempts.append(exc.to_diagnostics())
                if exc.diagnostics.get("terminal_structured_provider_error") is True:
                    exc.diagnostics.setdefault("structured_provider_attempts", attempts)
                    raise exc

        if attempts and hasattr(last_error, "diagnostics"):
            diagnostics = getattr(last_error, "diagnostics", {})
            if isinstance(diagnostics, dict):
                diagnostics.setdefault("structured_provider_attempts", attempts)
        if last_error is not None:
            raise last_error
        return None


def build_default_registry() -> StructuredProviderRegistry:
    providers: List[Stage2StructuredProvider] = []
    module_names = (
        "chinabond",
        "cdb_estimator",
        "tushare_etf",
        "eastmoney_etf",
        "official_china",
        "trading_economics",
        "market_quote_pages",
        "stooq",
        "yahoo_finance",
    )

    for module_name in module_names:
        try:
            module = import_module(f"datasource.providers.stage2_structured.{module_name}")
        except ModuleNotFoundError as exc:
            if exc.name == f"datasource.providers.stage2_structured.{module_name}":
                continue
            raise

        build_provider = getattr(module, "build_provider", None)
        if build_provider is not None:
            providers.append(build_provider())

    return StructuredProviderRegistry(providers)
