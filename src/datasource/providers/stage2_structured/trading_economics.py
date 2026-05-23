"""Trading Economics provider for Stage2 quote pages."""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, Optional

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.http_fetcher import (
    fetch_text as default_fetch_text,
)
from datasource.providers.stage2_structured.source_tiers import (
    classify_structured_source_tier,
)


FetchText = Callable[[str, Optional[Dict[str, Any]]], Awaitable[str]]


URLS = {
    "bdi": (
        "https://tradingeconomics.com/commodity/baltic",
        "points",
        "Baltic Dry Index",
    ),
    "DXY": (
        "https://tradingeconomics.com/united-states/currency",
        "points",
        "US Dollar Index",
    ),
}


class TradingEconomicsProvider(Stage2StructuredProvider):
    name = "trading_economics"
    supported_keys = set(URLS)

    def __init__(self, fetch_text: FetchText = default_fetch_text) -> None:
        self._fetch_text = fetch_text

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        if key not in URLS:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="unsupported_key",
                message="Trading Economics provider does not support {0}".format(key),
            )

        url, unit, label = URLS[key]
        params = None
        try:
            html = await self._fetch_text(url, params)
        except StructuredProviderError:
            raise
        except Exception as exc:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="fetch_error",
                message=str(exc),
                diagnostics={"url": url, "params": params},
            )
        value = self._parse_value(html)
        if value is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="missing_value",
                message="Trading Economics page did not contain a parseable value",
                diagnostics={"url": url},
            )

        category = "macro_indicators" if key == "bdi" else "forex"
        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category=category,
            payload={"value": value, "unit": unit},
            source="Trading Economics structured page",
            source_url=url,
            source_tier=classify_structured_source_tier(url),
            as_of_date=self._parse_date(html) or reference_date,
            confidence=0.85,
            diagnostics={
                "label": label,
                "evidence_text": "{0} {1} {2}".format(label, value, unit),
            },
        )

    @staticmethod
    def _parse_value(html: str) -> Optional[float]:
        patterns = [
            r'id=["\']p["\'][^>]*>\s*([0-9,]+(?:\.\d+)?)',
            r'data-last=["\']([0-9,]+(?:\.\d+)?)["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                return float(match.group(1).replace(",", ""))
        return None

    @staticmethod
    def _parse_date(html: str) -> Optional[str]:
        match = re.search(r"(20\d{2}-\d{2}-\d{2})", html)
        return match.group(1) if match else None


def build_provider() -> TradingEconomicsProvider:
    return TradingEconomicsProvider()
