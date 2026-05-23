"""Registry and dispatch for Stage2 structured providers."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Iterable, List, Mapping, Optional

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
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

    async def fetch(
        self,
        task: Mapping[str, Any],
        market_payload: Mapping[str, Any],
        reference_date: str,
    ) -> Optional[StructuredResult]:
        indicator_key = str(task.get("indicator_key", ""))
        provider = self.provider_for(indicator_key)
        if provider is None:
            return None
        return await provider.fetch(task, market_payload, reference_date)


def build_default_registry() -> StructuredProviderRegistry:
    providers: List[Stage2StructuredProvider] = []
    module_names = (
        "chinabond",
        "eastmoney_etf",
        "official_china",
        "trading_economics",
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
