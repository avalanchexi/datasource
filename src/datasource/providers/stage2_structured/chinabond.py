"""ChinaBond provider for the 10Y CDB yield."""

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


class ChinaBondProvider(Stage2StructuredProvider):
    name = "chinabond"
    supported_keys = {"CN10Y_CDB"}
    source_url = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/more?locale=cn_ZH"

    def __init__(self, fetch_text: FetchText = default_fetch_text) -> None:
        self._fetch_text = fetch_text

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        if key != "CN10Y_CDB":
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="unsupported_key",
                message="ChinaBond provider does not support {0}".format(key),
            )

        params = None
        try:
            html = await self._fetch_text(self.source_url, params)
        except StructuredProviderError:
            raise
        except Exception as exc:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="fetch_error",
                message=str(exc),
                diagnostics={"url": self.source_url, "params": params},
            )
        value = self._parse_value(html)
        if value is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="missing_value",
                message="ChinaBond page did not contain a parseable 10Y CDB yield",
                diagnostics={"url": self.source_url},
            )

        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category="bonds",
            payload={"value": value, "unit": "%"},
            source="ChinaBond yield curve",
            source_url=self.source_url,
            source_tier=classify_structured_source_tier(self.source_url),
            as_of_date=self._parse_date(html) or reference_date,
            confidence=0.9,
            diagnostics={"evidence_text": "CN10Y_CDB {0}%".format(value)},
        )

    @staticmethod
    def _parse_value(html: str) -> Optional[float]:
        for match in re.finditer(r"(?:10年|10\s*Y)", html, flags=re.IGNORECASE):
            context = html[match.end() : match.end() + 80]
            value = ChinaBondProvider._parse_yield_from_context(context)
            if value is not None:
                return value
        return None

    @staticmethod
    def _parse_yield_from_context(context: str) -> Optional[float]:
        cleaned = re.sub(r"20\d{2}-\d{1,2}-\d{1,2}", " ", context)
        number_patterns = [
            r"(?<![\d.-])([0-9]+\.[0-9]+)(?![\d.-])",
            r"(?<![\d.-])([0-9]+)(?![\d.-])",
        ]
        for pattern in number_patterns:
            for match in re.finditer(pattern, cleaned):
                value = float(match.group(1))
                if 0 < value < 20:
                    return value
        return None

    @staticmethod
    def _parse_date(html: str) -> Optional[str]:
        match = re.search(r"(20\d{2}-\d{2}-\d{2})", html)
        return match.group(1) if match else None


def build_provider() -> ChinaBondProvider:
    return ChinaBondProvider()
