"""Trusted quote page parser for selected Stage2 market quotes."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

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


QUOTE_PAGES: Dict[str, Dict[str, Any]] = {
    "BCOM": {
        "url": "https://www.investing.com/indices/bloomberg-commodity-historical-data",
        "unit": "index points",
        "label": "Bloomberg Commodity Historical Data",
        "required_tokens": ["bloomberg", "commodity", "historical data"],
        "bad_tokens": ["total return", "bcomtr", "bcomx", "sub-index", "sub index"],
        "parse_strategy": "date_row_first",
        "price_basis": "official_close",
        "source": "Investing structured historical close page",
        "confidence": 0.82,
    },
    "GSG": {
        "url": "https://stockanalysis.com/etf/gsg/",
        "unit": "USD",
        "label": "iShares S&P GSCI Commodity-Indexed Trust",
        "required_tokens": ["ishares", "s&p gsci", "commodity-indexed trust"],
        "bad_tokens": [],
        "parse_strategy": "labelled_close_first",
        "price_basis": "market_close",
        "source": "StockAnalysis structured ETF quote page",
        "confidence": 0.82,
    },
}


class MarketQuotePageProvider(Stage2StructuredProvider):
    name = "market_quote_pages"
    supported_keys = set(QUOTE_PAGES)

    def __init__(self, fetch_text: FetchText = default_fetch_text) -> None:
        self._fetch_text = fetch_text

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        config = QUOTE_PAGES.get(key)
        if config is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="unsupported_key",
                message="Market quote page provider does not support {0}".format(key),
            )

        url = str(config["url"])
        params = None
        try:
            raw_text = await self._fetch_text(url, params)
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

        text = self._normalize_text(raw_text)
        self._validate_page(key, text, config, url)
        expected_close_date = self._expected_close_date(reference_date)
        parsed = self._parse_close_value(
            text,
            expected_close_date,
            str(config.get("parse_strategy") or "date_row_first"),
        )
        if parsed is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="missing_value",
                message="Market quote page did not contain a parseable close value",
                diagnostics={
                    "url": url,
                    "expected_close_date": expected_close_date,
                },
            )
        value, as_of_date, evidence_text = parsed

        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category="commodities",
            payload={"value": value, "unit": config["unit"]},
            source=str(config["source"]),
            source_url=url,
            source_tier=classify_structured_source_tier(url),
            as_of_date=as_of_date,
            confidence=float(config["confidence"]),
            diagnostics={
                "label": config["label"],
                "price_basis": config["price_basis"],
                "expected_close_date": expected_close_date,
                "evidence_text": evidence_text,
            },
        )

    @staticmethod
    def _normalize_text(raw_text: str) -> str:
        text = re.sub(
            r"<(script|style)\b[^>]*>.*?</\1>",
            " ",
            raw_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    def _validate_page(
        self,
        key: str,
        text: str,
        config: Dict[str, Any],
        url: str,
    ) -> None:
        lower_text = text.lower()
        bad_tokens = [str(token).lower() for token in config.get("bad_tokens") or []]
        matched_bad_tokens = [token for token in bad_tokens if token in lower_text]
        if matched_bad_tokens:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="rejected_page",
                message="Market quote page matched a rejected instrument token",
                diagnostics={
                    "url": url,
                    "matched_bad_tokens": matched_bad_tokens,
                },
            )

        required_tokens = [
            str(token).lower() for token in config.get("required_tokens") or []
        ]
        missing_required_tokens = [
            token for token in required_tokens if token not in lower_text
        ]
        if missing_required_tokens:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="rejected_page",
                message="Market quote page did not contain required instrument tokens",
                diagnostics={
                    "url": url,
                    "required_tokens": required_tokens,
                    "missing_required_tokens": missing_required_tokens,
                },
            )

    @staticmethod
    def _expected_close_date(reference_date: str) -> str:
        ref_date = datetime.strptime(reference_date, "%Y-%m-%d").date()
        return (ref_date - timedelta(days=1)).isoformat()

    @classmethod
    def _parse_close_value(
        cls,
        text: str,
        expected_close_date: str,
        parse_strategy: str = "date_row_first",
    ) -> Optional[Tuple[float, str, str]]:
        parsers = {
            "date_row_first": (
                cls._parse_date_row_close_value,
                cls._parse_labelled_close_value,
            ),
            "labelled_close_first": (
                cls._parse_labelled_close_value,
                cls._parse_date_row_close_value,
            ),
        }.get(
            parse_strategy,
            (
                cls._parse_date_row_close_value,
                cls._parse_labelled_close_value,
            ),
        )
        for parser in parsers:
            parsed = parser(text, expected_close_date)
            if parsed is not None:
                return parsed
        return None

    @classmethod
    def _parse_date_row_close_value(
        cls,
        text: str,
        expected_close_date: str,
    ) -> Optional[Tuple[float, str, str]]:
        date_label = cls._date_label(expected_close_date)
        date_pattern = re.escape(date_label).replace(r"\ ", r"\s+")
        date_match = re.search(
            r"({0})(?P<tail>.{{0,240}})".format(date_pattern),
            text,
            flags=re.IGNORECASE,
        )
        if date_match:
            tail = date_match.group("tail")
            value = cls._first_number(tail)
            if value is not None:
                evidence = "{0}{1}".format(date_match.group(1), tail[:80]).strip()
                return value, expected_close_date, evidence
        return None

    @classmethod
    def _parse_labelled_close_value(
        cls,
        text: str,
        expected_close_date: str,
    ) -> Optional[Tuple[float, str, str]]:
        close_match = re.search(
            r"\b(?:previous\s+close|close)\s+([0-9][0-9,]*(?:\.\d+)?)\b",
            text,
            flags=re.IGNORECASE,
        )
        if close_match:
            evidence_start = max(0, close_match.start() - 40)
            evidence_end = min(len(text), close_match.end() + 80)
            evidence = text[evidence_start:evidence_end].strip()
            return cls._parse_number(close_match.group(1)), expected_close_date, evidence
        return None

    @staticmethod
    def _date_label(iso_date: str) -> str:
        date_value = datetime.strptime(iso_date, "%Y-%m-%d").date()
        return date_value.strftime("%b %d, %Y")

    @classmethod
    def _first_number(cls, text: str) -> Optional[float]:
        match = re.search(r"\b([0-9][0-9,]*(?:\.\d+)?)\b", text)
        if not match:
            return None
        return cls._parse_number(match.group(1))

    @staticmethod
    def _parse_number(value: str) -> float:
        return float(value.replace(",", ""))


def build_provider() -> MarketQuotePageProvider:
    return MarketQuotePageProvider()
