"""Trading Economics provider for Stage2 quote pages."""

from __future__ import annotations

import json
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


URLS: Dict[str, Dict[str, Any]] = {
    "bdi": {
        "url": "https://tradingeconomics.com/commodity/baltic",
        "unit": "points",
        "label": "Baltic Dry Index",
        "category": "macro_indicators",
    },
    "DXY": {
        "url": "https://tradingeconomics.com/united-states/currency",
        "unit": "points",
        "label": "US Dollar Index",
        "category": "forex",
    },
    "USDCNY": {
        "url": "https://tradingeconomics.com/china/currency",
        "unit": "",
        "label": "Chinese Yuan",
        "category": "forex",
    },
    "GC=F": {
        "url": "https://tradingeconomics.com/commodity/gold",
        "unit": "$/oz",
        "label": "Gold",
        "category": "commodities",
    },
    "CL=F": {
        "url": "https://tradingeconomics.com/commodity/crude-oil",
        "unit": "$/barrel",
        "label": "Crude Oil",
        "category": "commodities",
        "match_exclude": ["brent"],
    },
    "BZ=F": {
        "url": "https://tradingeconomics.com/commodity/brent-crude-oil",
        "unit": "$/barrel",
        "label": "Brent Crude Oil",
        "category": "commodities",
        "match_required": ["brent"],
    },
    "HG=F": {
        "url": "https://tradingeconomics.com/commodity/copper",
        "unit": "$/lb",
        "label": "Copper",
        "category": "commodities",
    },
    "reverse_repo": {
        "url": "https://tradingeconomics.com/china/reverse-repo-rate",
        "unit": "%",
        "label": "China Reverse Repo Rate",
        "category": "monetary_policy",
    },
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
                message=(
                    "Trading Economics provider does not support "
                    "{0}".format(key)
                ),
            )

        config = URLS[key]
        url = config["url"]
        unit = config["unit"]
        label = config["label"]
        category = config["category"]
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
        value = self._parse_value(
            html,
            expected_label=label,
            required_tokens=config.get("match_required") or [],
            exclude_tokens=config.get("match_exclude") or [],
        )
        if value is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="missing_value",
                message=(
                    "Trading Economics page did not contain a parseable value"
                ),
                diagnostics={"url": url},
            )

        payload = {"value": value, "unit": unit}
        if category == "monetary_policy":
            payload["is_estimated"] = False
        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category=category,
            payload=payload,
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
    def _parse_value(
        html: str,
        expected_label: Optional[str] = None,
        required_tokens: Optional[list[str]] = None,
        exclude_tokens: Optional[list[str]] = None,
    ) -> Optional[float]:
        chart_meta_value = TradingEconomicsProvider._parse_chart_meta_value(
            html,
            expected_label,
            required_tokens=required_tokens,
            exclude_tokens=exclude_tokens,
        )
        if chart_meta_value is not None:
            return chart_meta_value

        description_value = TradingEconomicsProvider._parse_description_value(
            html
        )
        if description_value is not None:
            return description_value

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
    def _parse_chart_meta_value(
        html: str,
        expected_label: Optional[str] = None,
        required_tokens: Optional[list[str]] = None,
        exclude_tokens: Optional[list[str]] = None,
    ) -> Optional[float]:
        match = re.search(
            r"TEChartsMeta\s*=\s*(\[.*?\]);",
            html,
            flags=re.DOTALL,
        )
        if not match:
            return None
        try:
            records = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

        expected = (expected_label or "").lower()
        required = [token.lower() for token in (required_tokens or [])]
        excluded = [token.lower() for token in (exclude_tokens or [])]
        for record in records:
            if not isinstance(record, dict):
                continue
            haystack = " ".join(
                str(record.get(field) or "")
                for field in (
                    "name",
                    "full_name",
                    "description",
                    "symbol",
                    "ticker",
                )
            ).lower()
            if excluded and any(token in haystack for token in excluded):
                continue
            if required and not all(token in haystack for token in required):
                continue
            if expected and expected not in haystack:
                expected_tokens = [
                    token for token in expected.split() if len(token) > 2
                ]
                if expected_tokens and not all(
                    token in haystack for token in expected_tokens
                ):
                    continue
            for field in ("last", "value", "converted_value"):
                value = record.get(field)
                try:
                    if value is not None:
                        return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _parse_description_value(html: str) -> Optional[float]:
        description = TradingEconomicsProvider._description_text(html)
        if not description:
            return None
        patterns = [
            r"(?:fell|rose|unchanged|recorded|traded|remained)"
            r"[^0-9]{0,40}(?:at|to)\s*([0-9,]+(?:\.\d+)?)",
            r"last recorded at\s*([0-9,]+(?:\.\d+)?)",
        ]
        for pattern in patterns:
            found = re.search(pattern, description, flags=re.IGNORECASE)
            if found:
                return float(found.group(1).replace(",", ""))
        return None

    @staticmethod
    def _parse_date(html: str) -> Optional[str]:
        parsed = TradingEconomicsProvider._parse_description_date(
            TradingEconomicsProvider._description_text(html)
        )
        if parsed is not None:
            return parsed

        last_update = re.search(
            r"TELastUpdate\s*=\s*['\"](\d{4})(\d{2})(\d{2})",
            html,
        )
        if last_update:
            year, month, day = last_update.groups()
            return "{0}-{1}-{2}".format(year, month, day)

        match = re.search(r"(20\d{2}-\d{2}-\d{2})", html)
        return match.group(1) if match else None

    @staticmethod
    def _description_text(html: str) -> str:
        match = re.search(
            r'name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else ""

    @staticmethod
    def _parse_description_date(description: str) -> Optional[str]:
        months = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }
        match = re.search(
            r"\bon\s+([A-Za-z]+)\s+(\d{1,2}),\s*(20\d{2})",
            description,
            flags=re.IGNORECASE,
        )
        if match:
            month = months.get(match.group(1).lower())
            if month:
                return "{0}-{1:02d}-{2:02d}".format(
                    int(match.group(3)), month, int(match.group(2))
                )

        period_match = re.search(
            r"\bin\s+([A-Za-z]+)\b.*updated on\s+[A-Za-z]+\s+of\s+(20\d{2})",
            description,
            flags=re.IGNORECASE,
        )
        if period_match:
            month = months.get(period_match.group(1).lower())
            if month:
                return "{0}-{1:02d}-01".format(
                    int(period_match.group(2)), month
                )
        return None


def build_provider() -> TradingEconomicsProvider:
    return TradingEconomicsProvider()
