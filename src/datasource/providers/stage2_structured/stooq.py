"""Stooq CSV provider for selected Stage2 exchange-traded quotes."""

from __future__ import annotations

import csv
from io import StringIO
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


STOOQ_QUOTES = {
    "GSG": {
        "url": "https://stooq.com/q/l/?s=gsg.us&f=sd2t2ohlcv&h&e=csv",
        "unit": "USD",
        "label": "GSG ETF",
    },
}


class StooqQuoteProvider(Stage2StructuredProvider):
    name = "stooq"
    supported_keys = set(STOOQ_QUOTES)

    def __init__(self, fetch_text: FetchText = default_fetch_text) -> None:
        self._fetch_text = fetch_text

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        quote = STOOQ_QUOTES.get(key)
        if quote is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="unsupported_key",
                message="Stooq provider does not support {0}".format(key),
            )

        url = str(quote["url"])
        try:
            text = await self._fetch_text(url, None)
        except StructuredProviderError:
            raise
        except Exception as exc:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="fetch_error",
                message=str(exc),
                diagnostics={"url": url, "params": None},
            )

        parsed = self._parse_csv(text)
        if parsed is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="missing_value",
                message="Stooq CSV did not contain a parseable close value",
                diagnostics={"url": url},
            )
        close, as_of_date = parsed

        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category="commodities",
            payload={"value": close, "unit": quote["unit"]},
            source="Stooq structured quote",
            source_url=url,
            source_tier=classify_structured_source_tier(url),
            as_of_date=as_of_date or reference_date,
            confidence=0.85,
            diagnostics={
                "label": quote["label"],
                "price_basis": "market_close",
                "evidence_text": "{0} {1} {2}".format(key, close, quote["unit"]),
            },
        )

    @staticmethod
    def _parse_csv(text: str) -> Optional[tuple[float, Optional[str]]]:
        reader = csv.DictReader(StringIO(text))
        for row in reader:
            close_text = (row.get("Close") or "").strip()
            date_text = (row.get("Date") or "").strip()
            if not close_text or close_text.upper() == "N/D":
                return None
            try:
                return float(close_text), date_text if date_text.upper() != "N/D" else None
            except ValueError:
                return None
        return None


def build_provider() -> StooqQuoteProvider:
    return StooqQuoteProvider()
