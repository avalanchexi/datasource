"""Yahoo Finance chart provider for Stage2 commodity quotes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.http_fetcher import (
    fetch_json as default_fetch_json,
)
from datasource.providers.stage2_structured.source_tiers import (
    classify_structured_source_tier,
)


FetchJson = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Dict[str, Any]]]


YAHOO_SYMBOLS = {
    "GC=F": ("GC=F", "$/oz", "COMEX黄金"),
    "CL=F": ("CL=F", "$/bbl", "WTI原油"),
    "BZ=F": ("BZ=F", "$/bbl", "Brent原油"),
    "HG=F": ("HG=F", "$/lb", "COMEX铜"),
    "GSG": ("GSG", "USD", "S&P GSCI ETF"),
}


class YahooFinanceProvider(Stage2StructuredProvider):
    name = "yahoo_finance"
    supported_keys = set(YAHOO_SYMBOLS)

    def __init__(self, fetch_json: FetchJson = default_fetch_json) -> None:
        self._fetch_json = fetch_json

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        if key not in YAHOO_SYMBOLS:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="unsupported_key",
                message="Yahoo Finance provider does not support {0}".format(key),
            )

        yahoo_symbol, unit, label = YAHOO_SYMBOLS[key]
        url = "https://query1.finance.yahoo.com/v8/finance/chart/{0}".format(
            yahoo_symbol
        )
        data = await self._fetch_json(url, {"range": "5d", "interval": "1d"})

        try:
            result = data["chart"]["result"][0]
            meta = result["meta"]
            price = float(meta["regularMarketPrice"])
            timestamps = result.get("timestamp") or []
            market_time = int(meta.get("regularMarketTime") or timestamps[-1])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="parse_error",
                message=str(exc),
                diagnostics={"url": url},
            )

        source_url = "https://finance.yahoo.com/quote/{0}".format(yahoo_symbol)
        as_of_date = datetime.fromtimestamp(market_time, tz=timezone.utc).date().isoformat()

        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category="commodities",
            payload={"value": price, "unit": unit},
            source="Yahoo Finance structured chart",
            source_url=source_url,
            source_tier=classify_structured_source_tier(source_url),
            as_of_date=as_of_date,
            confidence=0.95,
            diagnostics={
                "label": label,
                "yahoo_symbol": yahoo_symbol,
                "evidence_text": "{0} {1} {2}".format(key, price, unit),
            },
        )


def build_provider() -> YahooFinanceProvider:
    return YahooFinanceProvider()
