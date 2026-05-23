# Stage2 Hit-Rate Structured Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Stage2 structured-provider-first execution so the 2026-05-23 golden task set reaches at least 70% true Stage2 writeback hit rate before Stage2.5.

**Architecture:** Stage2 keeps the existing task planner, Tavily-first search, Exa quota failover, DeepSeek extraction, and writeback contracts. A new `datasource.providers.stage2_structured` package runs before search; a valid provider result is converted into the existing extraction shape and written through `_apply_extraction()`, while provider failures fall back to the current search path.

**Tech Stack:** Python 3.7-compatible typing, `httpx`, existing Stage2 task dicts, existing fund-flow gate helpers from `scripts/stage2_5_injector.py`, `pytest`.

---

## Scope Check

This plan covers one subsystem: Stage2 structured-provider-first execution. It does not change Stage1, Stage2.5 schema, Stage3, Stage4, trend-history storage, or report generation.

## File Structure

- Create `src/datasource/providers/__init__.py`: package marker.
- Create `src/datasource/providers/stage2_structured/__init__.py`: public exports for Stage2 structured providers.
- Create `src/datasource/providers/stage2_structured/base.py`: provider result dataclasses, provider error, helper conversion from provider payload to Stage2 extraction dict.
- Create `src/datasource/providers/stage2_structured/source_tiers.py`: explicit Tier 1/Tier 2/Tier 3 source classification for provider audit metadata.
- Create `src/datasource/providers/stage2_structured/registry.py`: deterministic provider dispatch and default registry construction.
- Create `src/datasource/providers/stage2_structured/http_fetcher.py`: bounded `httpx` fetch helpers used by live providers and replaced by fixtures in tests.
- Create `src/datasource/providers/stage2_structured/yahoo_finance.py`: structured daily quote provider for `GC=F`, `CL=F`, `BZ=F`, `HG=F`, `GSG`.
- Create `src/datasource/providers/stage2_structured/official_china.py`: official China provider for `reverse_repo`, `mlf`, `USDCNY`, `industrial`, `industrial_sales`, and `reserve_ratio`.
- Create `src/datasource/providers/stage2_structured/chinabond.py`: structured provider for `CN10Y_CDB`.
- Create `src/datasource/providers/stage2_structured/trading_economics.py`: structured provider for `DXY` and `bdi`.
- Create `src/datasource/providers/stage2_structured/eastmoney_etf.py`: structured provider for `fund_flow.etf` with direct-window-only writeback.
- Modify `scripts/stage2_unified_enhancer.py`: wire provider registry before search, add diagnostics, add CLI opt-out, include structured successes in effective hit-rate metrics.
- Modify `AGENTS.md`: update Stage2 collection priority and command notes.
- Modify `CLAUDE.md`: keep quick summary aligned with `AGENTS.md`.
- Create `tests/test_stage2_structured_providers.py`: provider unit tests with fixture fetchers.
- Create `tests/test_stage2_structured_integration.py`: Stage2 `_execute_tasks()` integration tests with fake registry and fake search clients.
- Create `tests/test_stage2_structured_golden.py`: 2026-05-23 golden task-set hit-rate guard using fake structured providers.

## Task 1: Provider Foundation

**Files:**
- Create: `src/datasource/providers/__init__.py`
- Create: `src/datasource/providers/stage2_structured/__init__.py`
- Create: `src/datasource/providers/stage2_structured/base.py`
- Create: `src/datasource/providers/stage2_structured/source_tiers.py`
- Create: `src/datasource/providers/stage2_structured/registry.py`
- Test: `tests/test_stage2_structured_providers.py`

- [ ] **Step 1: Write the failing foundation tests**

Add this initial content to `tests/test_stage2_structured_providers.py`:

```python
import pytest

from datasource.providers.stage2_structured.base import (
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.registry import StructuredProviderRegistry
from datasource.providers.stage2_structured.source_tiers import classify_structured_source_tier


class FakeProvider:
    name = "fake"
    supported_keys = {"GC=F"}

    async def fetch(self, task, market_payload, reference_date):
        return StructuredResult(
            provider=self.name,
            indicator_key=task["indicator_key"],
            category="commodities",
            payload={"value": 2401.5, "unit": "$/oz"},
            source="Fake structured quote",
            source_url="https://finance.yahoo.com/quote/GC=F",
            source_tier="tier2",
            as_of_date="2026-05-22",
            confidence=0.99,
            diagnostics={"fixture": True},
        )


class FailingProvider:
    name = "failing"
    supported_keys = {"CL=F"}

    async def fetch(self, task, market_payload, reference_date):
        raise StructuredProviderError(
            provider=self.name,
            indicator_key=task["indicator_key"],
            reason="parse_error",
            message="fixture parse error",
        )


@pytest.mark.asyncio
async def test_registry_dispatches_supported_provider():
    registry = StructuredProviderRegistry([FakeProvider()])
    task = {"indicator_key": "GC=F", "category": "commodities"}

    result = await registry.fetch(task, {}, "2026-05-23")

    assert result is not None
    assert result.provider == "fake"
    assert result.indicator_key == "GC=F"
    assert result.to_extraction()["value"] == 2401.5
    assert result.to_extraction()["source_url"] == "https://finance.yahoo.com/quote/GC=F"
    assert result.to_websearch_record(task)["search_backend"] == "structured"
    assert result.to_websearch_record(task)["result_type"] == "structured_success"


@pytest.mark.asyncio
async def test_registry_returns_none_for_unsupported_key():
    registry = StructuredProviderRegistry([FakeProvider()])

    result = await registry.fetch({"indicator_key": "BCOM"}, {}, "2026-05-23")

    assert result is None


@pytest.mark.asyncio
async def test_registry_surfaces_provider_error_with_diagnostics():
    registry = StructuredProviderRegistry([FailingProvider()])

    with pytest.raises(StructuredProviderError) as exc_info:
        await registry.fetch({"indicator_key": "CL=F"}, {}, "2026-05-23")

    assert exc_info.value.provider == "failing"
    assert exc_info.value.indicator_key == "CL=F"
    assert exc_info.value.reason == "parse_error"
    assert exc_info.value.to_diagnostics()["structured_provider_error"] == "parse_error"


def test_source_tier_classifier_uses_explicit_allowlists():
    assert classify_structured_source_tier("https://www.stats.gov.cn/sj/zxfb/202605/t.html") == "tier1"
    assert classify_structured_source_tier("https://finance.yahoo.com/quote/GC=F") == "tier2"
    assert classify_structured_source_tier("https://finance.sina.com.cn/a/20260523.html") == "tier3"
    assert classify_structured_source_tier("https://example.com/quote") == "unknown"
```

- [ ] **Step 2: Run the foundation tests and verify they fail**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_providers.py -q
```

Expected: FAIL during import because `datasource.providers.stage2_structured` does not exist.

- [ ] **Step 3: Add the provider foundation package**

Create `src/datasource/providers/__init__.py`:

```python
"""Datasource provider packages."""
```

Create `src/datasource/providers/stage2_structured/__init__.py`:

```python
"""Structured Stage2 providers used before web search fallback."""

from .base import StructuredProviderError, StructuredResult, Stage2StructuredProvider
from .registry import StructuredProviderRegistry, build_default_registry

__all__ = [
    "StructuredProviderError",
    "StructuredResult",
    "Stage2StructuredProvider",
    "StructuredProviderRegistry",
    "build_default_registry",
]
```

Create `src/datasource/providers/stage2_structured/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Set


class StructuredProviderError(Exception):
    def __init__(
        self,
        *,
        provider: str,
        indicator_key: str,
        reason: str,
        message: str = "",
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.provider = provider
        self.indicator_key = indicator_key
        self.reason = reason
        self.message = message or reason
        self.diagnostics = diagnostics or {}
        super().__init__(f"{provider}:{indicator_key}:{reason}:{self.message}")

    def to_diagnostics(self) -> Dict[str, Any]:
        payload = dict(self.diagnostics)
        payload.update(
            {
                "structured_provider": self.provider,
                "structured_provider_error": self.reason,
                "structured_provider_error_message": self.message,
            }
        )
        return payload


@dataclass
class StructuredResult:
    provider: str
    indicator_key: str
    category: str
    payload: Dict[str, Any]
    source: str
    source_url: str
    source_tier: str
    as_of_date: Optional[str] = None
    report_period: Optional[str] = None
    is_estimated: bool = False
    confidence: float = 1.0
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_extraction(self) -> Dict[str, Any]:
        extraction = dict(self.payload)
        if "value" not in extraction:
            for key in ("current_value", "current_price", "current_rate", "current_yield", "recent_5d"):
                if key in extraction:
                    extraction["value"] = extraction[key]
                    break
        extraction.update(
            {
                "source_url": self.source_url,
                "source": self.source,
                "source_tier": self.source_tier,
                "as_of_date": self.as_of_date,
                "report_period": self.report_period,
                "is_estimated": self.is_estimated,
                "confidence": self.confidence,
                "note": self._note(),
                "structured_provider": self.provider,
                "manual_required": False,
                "manual_reason": None,
            }
        )
        return extraction

    def audit_snippets(self) -> Iterable[Dict[str, Any]]:
        text = self.diagnostics.get("evidence_text") or self.source
        return [
            {
                "url": self.source_url,
                "title": self.source,
                "snippet": str(text),
                "content": str(text),
                "score": None,
                "published_date": self.as_of_date or self.report_period,
                "search_backend": "structured",
            }
        ]

    def to_websearch_record(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task": {
                **task,
                "search_backend": "structured",
                "structured_provider": self.provider,
                "source_tier": self.source_tier,
            },
            "extraction": self.to_extraction(),
            "extraction_backend": "structured",
            "raw_results": list(self.audit_snippets()),
            "search_backend": "structured",
            "result_type": "structured_success",
            "manual_required": False,
            "source_url": self.source_url,
            "source_tier": self.source_tier,
            "provider": self.provider,
            "as_of_date": self.as_of_date,
            "report_period": self.report_period,
        }

    def _note(self) -> str:
        parts = ["structured_provider", self.provider]
        if self.diagnostics.get("note"):
            parts.append(str(self.diagnostics["note"]))
        return ":".join(parts[:2]) if len(parts) == 2 else ":".join(parts[:2]) + " " + parts[2]


class Stage2StructuredProvider:
    name = "base"
    supported_keys: Set[str] = set()

    async def fetch(
        self,
        task: Dict[str, Any],
        market_payload: Dict[str, Any],
        reference_date: str,
    ) -> StructuredResult:
        raise NotImplementedError("Stage2StructuredProvider.fetch must be implemented by subclasses")
```

Create `src/datasource/providers/stage2_structured/source_tiers.py`:

```python
from __future__ import annotations

from typing import Iterable
from urllib.parse import urlparse


TIER1_DOMAINS = (
    "pbc.gov.cn",
    "stats.gov.cn",
    "data.stats.gov.cn",
    "chinamoney.com.cn",
    "cfets.com.cn",
    "chinabond.com.cn",
    "yield.chinabond.com.cn",
    "sse.com.cn",
    "szse.cn",
    "hkex.com.hk",
)

TIER2_DOMAINS = (
    "finance.yahoo.com",
    "query1.finance.yahoo.com",
    "tradingeconomics.com",
    "data.eastmoney.com",
    "investing.com",
    "marketwatch.com",
    "nasdaq.com",
)

TIER3_DOMAINS = (
    "finance.sina.com.cn",
    "sina.com.cn",
    "stcn.com",
    "cs.com.cn",
    "cls.cn",
    "10jqka.com.cn",
    "caifuhao.eastmoney.com",
    "guba.eastmoney.com",
)


def _hostname(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.hostname and "://" not in str(url):
        parsed = urlparse("//" + str(url))
    return (parsed.hostname or "").lower().rstrip(".")


def _matches(host: str, domains: Iterable[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def classify_structured_source_tier(url: str) -> str:
    host = _hostname(url)
    if not host:
        return "unknown"
    if _matches(host, TIER1_DOMAINS):
        return "tier1"
    if _matches(host, TIER2_DOMAINS):
        return "tier2"
    if _matches(host, TIER3_DOMAINS):
        return "tier3"
    return "unknown"
```

Create `src/datasource/providers/stage2_structured/registry.py`:

```python
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .base import Stage2StructuredProvider, StructuredResult


class StructuredProviderRegistry:
    def __init__(self, providers: Iterable[Stage2StructuredProvider]) -> None:
        self.providers: List[Stage2StructuredProvider] = list(providers)

    def provider_for(self, indicator_key: str) -> Optional[Stage2StructuredProvider]:
        for provider in self.providers:
            if indicator_key in provider.supported_keys:
                return provider
        return None

    async def fetch(
        self,
        task: Dict[str, Any],
        market_payload: Dict[str, Any],
        reference_date: str,
    ) -> Optional[StructuredResult]:
        indicator_key = str(task.get("indicator_key") or "")
        provider = self.provider_for(indicator_key)
        if provider is None:
            return None
        return await provider.fetch(task, market_payload, reference_date)


def build_default_registry() -> StructuredProviderRegistry:
    from .chinabond import ChinaBondProvider
    from .eastmoney_etf import EastMoneyETFProvider
    from .official_china import OfficialChinaProvider
    from .trading_economics import TradingEconomicsProvider
    from .yahoo_finance import YahooFinanceProvider

    return StructuredProviderRegistry(
        [
            YahooFinanceProvider(),
            OfficialChinaProvider(),
            ChinaBondProvider(),
            TradingEconomicsProvider(),
            EastMoneyETFProvider(),
        ]
    )
```

- [ ] **Step 4: Run the foundation tests and verify they pass**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_providers.py -q
```

Expected: PASS for the four tests in this file.

- [ ] **Step 5: Commit the foundation**

Run:

```bash
git add src/datasource/providers tests/test_stage2_structured_providers.py
git commit -m "feat: add stage2 structured provider foundation"
```

## Task 2: HTTP Fetcher and Quote Providers

**Files:**
- Create: `src/datasource/providers/stage2_structured/http_fetcher.py`
- Create: `src/datasource/providers/stage2_structured/yahoo_finance.py`
- Create: `src/datasource/providers/stage2_structured/trading_economics.py`
- Create: `src/datasource/providers/stage2_structured/chinabond.py`
- Modify: `tests/test_stage2_structured_providers.py`

- [ ] **Step 1: Add failing provider tests for daily quote providers**

Append these tests to `tests/test_stage2_structured_providers.py`:

```python
from datasource.providers.stage2_structured.chinabond import ChinaBondProvider
from datasource.providers.stage2_structured.trading_economics import TradingEconomicsProvider
from datasource.providers.stage2_structured.yahoo_finance import YahooFinanceProvider


@pytest.mark.asyncio
async def test_yahoo_finance_provider_parses_chart_quote():
    async def fetch_json(url, params=None):
        assert "query1.finance.yahoo.com" in url
        assert params["range"] == "5d"
        return {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 3367.8,
                            "regularMarketTime": 1779480000,
                        },
                        "timestamp": [1779393600, 1779480000],
                    }
                ]
            }
        }

    provider = YahooFinanceProvider(fetch_json=fetch_json)
    result = await provider.fetch({"indicator_key": "GC=F"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.provider == "yahoo_finance"
    assert result.source_tier == "tier2"
    assert extraction["value"] == 3367.8
    assert extraction["unit"] == "$/oz"
    assert extraction["source_url"] == "https://finance.yahoo.com/quote/GC=F"


@pytest.mark.asyncio
async def test_trading_economics_provider_parses_bdi_fixture():
    html = '<html><body><h1>Baltic Dry</h1><span id="p">1,346.00</span><time>2026-05-22</time></body></html>'

    async def fetch_text(url, params=None):
        assert "tradingeconomics.com" in url
        return html

    provider = TradingEconomicsProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "bdi"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.provider == "trading_economics"
    assert result.source_tier == "tier2"
    assert extraction["value"] == 1346.0
    assert extraction["unit"] == "points"
    assert extraction["source_url"] == "https://tradingeconomics.com/commodity/baltic"


@pytest.mark.asyncio
async def test_chinabond_provider_parses_cn10y_cdb_fixture():
    html = "中债国开债到期收益率曲线 10年 2.0380 2026-05-22"

    async def fetch_text(url, params=None):
        assert "chinabond.com.cn" in url
        return html

    provider = ChinaBondProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "CN10Y_CDB"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.provider == "chinabond"
    assert result.source_tier == "tier1"
    assert extraction["value"] == 2.038
    assert extraction["unit"] == "%"
    assert extraction["source_url"].startswith("https://yield.chinabond.com.cn/")
```

- [ ] **Step 2: Run provider tests and verify the new cases fail**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_providers.py -q
```

Expected: FAIL during import because the provider modules do not exist.

- [ ] **Step 3: Add the bounded HTTP fetcher**

Create `src/datasource/providers/stage2_structured/http_fetcher.py`:

```python
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx


DEFAULT_TIMEOUT_SECONDS = 12.0
USER_AGENT = "datasource-stage2-structured-provider/1.0"


async def fetch_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS, trust_env=False) as client:
        response = await client.get(url, params=params, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.json()


async def fetch_text(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS, trust_env=False, follow_redirects=True) as client:
        response = await client.get(url, params=params, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        if response.encoding is None:
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text
```

- [ ] **Step 4: Add `YahooFinanceProvider`**

Create `src/datasource/providers/stage2_structured/yahoo_finance.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from .base import Stage2StructuredProvider, StructuredProviderError, StructuredResult
from .http_fetcher import fetch_json as default_fetch_json
from .source_tiers import classify_structured_source_tier


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
            raise StructuredProviderError(provider=self.name, indicator_key=key, reason="unsupported_key")
        yahoo_symbol, unit, _name = YAHOO_SYMBOLS[key]
        url = "https://query1.finance.yahoo.com/v8/finance/chart/{0}".format(yahoo_symbol)
        data = await self._fetch_json(url, {"range": "5d", "interval": "1d"})
        try:
            result = data["chart"]["result"][0]
            meta = result["meta"]
            price = float(meta["regularMarketPrice"])
            market_time = int(meta.get("regularMarketTime") or result.get("timestamp", [])[-1])
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
            diagnostics={"yahoo_symbol": yahoo_symbol, "evidence_text": "{0} {1} {2}".format(key, price, unit)},
        )
```

- [ ] **Step 5: Add `TradingEconomicsProvider` and `ChinaBondProvider`**

Create `src/datasource/providers/stage2_structured/trading_economics.py`:

```python
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, Optional

from .base import Stage2StructuredProvider, StructuredProviderError, StructuredResult
from .http_fetcher import fetch_text as default_fetch_text
from .source_tiers import classify_structured_source_tier


FetchText = Callable[[str, Optional[Dict[str, Any]]], Awaitable[str]]


URLS = {
    "bdi": ("https://tradingeconomics.com/commodity/baltic", "points", "Baltic Dry Index"),
    "DXY": ("https://tradingeconomics.com/united-states/currency", "points", "US Dollar Index"),
}


class TradingEconomicsProvider(Stage2StructuredProvider):
    name = "trading_economics"
    supported_keys = set(URLS)

    def __init__(self, fetch_text: FetchText = default_fetch_text) -> None:
        self._fetch_text = fetch_text

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        if key not in URLS:
            raise StructuredProviderError(provider=self.name, indicator_key=key, reason="unsupported_key")
        url, unit, label = URLS[key]
        html = await self._fetch_text(url, None)
        value = self._parse_value(html)
        if value is None:
            raise StructuredProviderError(provider=self.name, indicator_key=key, reason="missing_value", diagnostics={"url": url})
        as_of_date = self._parse_date(html) or reference_date
        category = "macro_indicators" if key == "bdi" else "forex"
        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category=category,
            payload={"value": value, "unit": unit},
            source="Trading Economics structured page",
            source_url=url,
            source_tier=classify_structured_source_tier(url),
            as_of_date=as_of_date,
            confidence=0.85,
            diagnostics={"label": label, "evidence_text": "{0} {1} {2}".format(label, value, unit)},
        )

    @staticmethod
    def _parse_value(html: str) -> Optional[float]:
        patterns = [
            r'id=["\\']p["\\'][^>]*>\\s*([0-9,]+(?:\\.\\d+)?)',
            r'data-last=["\\']([0-9,]+(?:\\.\\d+)?)["\\']',
            r'([0-9,]+(?:\\.\\d+)?)\\s*</span>',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                return float(match.group(1).replace(",", ""))
        return None

    @staticmethod
    def _parse_date(html: str) -> Optional[str]:
        match = re.search(r'(20\\d{2}-\\d{2}-\\d{2})', html)
        return match.group(1) if match else None
```

Create `src/datasource/providers/stage2_structured/chinabond.py`:

```python
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, Optional

from .base import Stage2StructuredProvider, StructuredProviderError, StructuredResult
from .http_fetcher import fetch_text as default_fetch_text
from .source_tiers import classify_structured_source_tier


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
            raise StructuredProviderError(provider=self.name, indicator_key=key, reason="unsupported_key")
        html = await self._fetch_text(self.source_url, None)
        value = self._parse_value(html)
        if value is None:
            raise StructuredProviderError(provider=self.name, indicator_key=key, reason="missing_value", diagnostics={"url": self.source_url})
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
        match = re.search(r'(?:国开|政策性金融债|CDB).*?(?:10年|10\\s*Y).*?([0-9]+(?:\\.[0-9]+)?)', html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            match = re.search(r'(?:10年|10\\s*Y).*?([0-9]+(?:\\.[0-9]+)?)', html, flags=re.IGNORECASE | re.DOTALL)
        return float(match.group(1)) if match else None

    @staticmethod
    def _parse_date(html: str) -> Optional[str]:
        match = re.search(r'(20\\d{2}-\\d{2}-\\d{2})', html)
        return match.group(1) if match else None
```

- [ ] **Step 6: Run quote provider tests**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_providers.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit quote providers**

Run:

```bash
git add src/datasource/providers/stage2_structured tests/test_stage2_structured_providers.py
git commit -m "feat: add stage2 structured quote providers"
```

## Task 3: Official China Provider

**Files:**
- Create: `src/datasource/providers/stage2_structured/official_china.py`
- Modify: `tests/test_stage2_structured_providers.py`

- [ ] **Step 1: Add failing official China provider tests**

Append these tests to `tests/test_stage2_structured_providers.py`:

```python
from datasource.providers.stage2_structured.official_china import OfficialChinaProvider


@pytest.mark.asyncio
async def test_official_china_provider_parses_reverse_repo_fixture():
    pages = {
        OfficialChinaProvider.REVERSE_REPO_URL: "2026年5月22日人民银行以固定利率、数量招标方式开展了7天期逆回购操作1185亿元，中标利率1.40%。"
    }

    async def fetch_text(url, params=None):
        return pages[url]

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "reverse_repo"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.source_tier == "tier1"
    assert extraction["value"] == 1.4
    assert extraction["unit"] == "%"
    assert extraction["operation_amount"] == 1185.0
    assert extraction["source_url"].startswith("https://www.pbc.gov.cn/")


@pytest.mark.asyncio
async def test_official_china_provider_parses_mlf_fixture():
    pages = {
        OfficialChinaProvider.MLF_URL: "2026年5月15日开展中期借贷便利（MLF）操作1250亿元，中标利率2.00%。"
    }

    async def fetch_text(url, params=None):
        return pages[url]

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "mlf"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == 2.0
    assert extraction["operation_amount"] == 1250.0
    assert extraction["unit"] == "%"


@pytest.mark.asyncio
async def test_official_china_provider_parses_usdcny_fixture():
    pages = {
        OfficialChinaProvider.USDCNY_URL: "2026-05-22 USD/CNY 人民币汇率中间价 7.1138"
    }

    async def fetch_text(url, params=None):
        return pages[url]

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "USDCNY"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.category == "forex"
    assert extraction["value"] == 7.1138
    assert extraction["unit"] == ""


@pytest.mark.asyncio
async def test_official_china_provider_parses_industrial_fixture():
    pages = {
        OfficialChinaProvider.NBS_URL: "2026年4月份，规模以上工业增加值同比实际增长6.1%。从环比看，4月份，规模以上工业增加值比上月增长0.22%。"
    }

    async def fetch_text(url, params=None):
        return pages[url]

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "industrial", "expected_period": "2026-04"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.category == "macro_indicators"
    assert extraction["value"] == 6.1
    assert extraction["value_type"] == "yoy_month"
    assert extraction["report_period"] == "2026-04"
```

- [ ] **Step 2: Run official provider tests and verify they fail**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_providers.py -q
```

Expected: FAIL because `official_china.py` does not exist.

- [ ] **Step 3: Implement `OfficialChinaProvider`**

Create `src/datasource/providers/stage2_structured/official_china.py`:

```python
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, Optional

from datasource.utils.key_aliases import canonical_monetary_key

from .base import Stage2StructuredProvider, StructuredProviderError, StructuredResult
from .http_fetcher import fetch_text as default_fetch_text
from .source_tiers import classify_structured_source_tier


FetchText = Callable[[str, Optional[Dict[str, Any]]], Awaitable[str]]


class OfficialChinaProvider(Stage2StructuredProvider):
    name = "official_china"
    supported_keys = {"reverse_repo", "mlf", "USDCNY", "industrial", "industrial_sales", "reserve_ratio"}

    REVERSE_REPO_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125434/125798/index.html"
    MLF_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125437/125446/125873/index.html"
    USDCNY_URL = "https://www.chinamoney.com.cn/chinese/bkccpr/"
    NBS_URL = "https://www.stats.gov.cn/sj/zxfb/"
    RESERVE_RATIO_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/125838/index.html"

    def __init__(self, fetch_text: FetchText = default_fetch_text) -> None:
        self._fetch_text = fetch_text

    async def fetch(self, task, market_payload, reference_date):
        key = canonical_monetary_key(str(task.get("indicator_key") or ""))
        if key == "reverse_repo":
            return await self._fetch_reverse_repo(task, reference_date)
        if key == "mlf":
            return await self._fetch_mlf(task, reference_date)
        if key == "reserve_ratio":
            return await self._fetch_reserve_ratio(task, reference_date)
        raw_key = str(task.get("indicator_key") or "")
        if raw_key == "USDCNY":
            return await self._fetch_usdcny(task, reference_date)
        if raw_key == "industrial":
            return await self._fetch_industrial(task, reference_date)
        if raw_key == "industrial_sales":
            return await self._fetch_industrial_sales(task, reference_date)
        raise StructuredProviderError(provider=self.name, indicator_key=raw_key, reason="unsupported_key")

    async def _fetch_reverse_repo(self, task, reference_date):
        text = await self._fetch_text(self.REVERSE_REPO_URL, None)
        rate = self._first_number(text, r'(?:利率|中标利率)\\s*([0-9]+(?:\\.[0-9]+)?)\\s*%')
        amount = self._first_number(text, r'([0-9]+(?:\\.[0-9]+)?)\\s*亿元')
        if rate is None:
            raise self._error(task, "missing_value", self.REVERSE_REPO_URL)
        return self._result(task, "monetary_policy", rate, "%", self.REVERSE_REPO_URL, reference_date, {"operation_amount": amount})

    async def _fetch_mlf(self, task, reference_date):
        text = await self._fetch_text(self.MLF_URL, None)
        rate = self._first_number(text, r'(?:利率|中标利率)\\s*([0-9]+(?:\\.[0-9]+)?)\\s*%')
        amount = self._first_number(text, r'([0-9]+(?:\\.[0-9]+)?)\\s*亿元')
        if rate is None:
            raise self._error(task, "missing_value", self.MLF_URL)
        extras = {"operation_amount": amount}
        if "多重价位" in text:
            extras["note"] = "多重价位中标，无统一利率；展示参考值"
        return self._result(task, "monetary_policy", rate, "%", self.MLF_URL, reference_date, extras)

    async def _fetch_reserve_ratio(self, task, reference_date):
        text = await self._fetch_text(self.RESERVE_RATIO_URL, None)
        value = self._first_number(text, r'(?:存款准备金率|reserve requirement).*?([0-9]+(?:\\.[0-9]+)?)\\s*%')
        if value is None:
            raise self._error(task, "missing_value", self.RESERVE_RATIO_URL)
        return self._result(task, "monetary_policy", value, "%", self.RESERVE_RATIO_URL, reference_date, {})

    async def _fetch_usdcny(self, task, reference_date):
        text = await self._fetch_text(self.USDCNY_URL, None)
        value = self._first_number(text, r'(?:USD/CNY|美元).*?([0-9]+\\.[0-9]+)')
        if value is None:
            raise self._error(task, "missing_value", self.USDCNY_URL)
        return self._result(task, "forex", value, "", self.USDCNY_URL, reference_date, {})

    async def _fetch_industrial(self, task, reference_date):
        text = await self._fetch_text(self.NBS_URL, None)
        value = self._first_number(text, r'工业增加值同比(?:实际)?增长\\s*([0-9]+(?:\\.[0-9]+)?)\\s*%')
        if value is None:
            raise self._error(task, "missing_value", self.NBS_URL)
        report_period = str(task.get("expected_period") or self._period_from_text(text) or reference_date[:7])
        return self._result(task, "macro_indicators", value, "%", self.NBS_URL, reference_date, {"value_type": "yoy_month", "report_period": report_period})

    async def _fetch_industrial_sales(self, task, reference_date):
        text = await self._fetch_text(self.NBS_URL, None)
        value = self._first_number(text, r'(?:营业收入|营收).*?增长\\s*([0-9]+(?:\\.[0-9]+)?)\\s*%')
        if value is None:
            raise self._error(task, "missing_value", self.NBS_URL)
        report_period = str(task.get("expected_period") or self._period_from_text(text) or reference_date[:7])
        return self._result(task, "macro_indicators", value, "%", self.NBS_URL, reference_date, {"value_type": "yoy_ytd", "report_period": report_period})

    def _result(self, task, category, value, unit, source_url, reference_date, extras):
        payload = {"value": value, "unit": unit}
        payload.update({k: v for k, v in extras.items() if v is not None})
        report_period = payload.get("report_period")
        return StructuredResult(
            provider=self.name,
            indicator_key=str(task.get("indicator_key") or ""),
            category=category,
            payload=payload,
            source="Official China structured source",
            source_url=source_url,
            source_tier=classify_structured_source_tier(source_url),
            as_of_date=reference_date if report_period is None else None,
            report_period=report_period,
            is_estimated=False,
            confidence=0.9,
            diagnostics={"evidence_text": "{0} {1} {2}".format(task.get("indicator_key"), value, unit)},
        )

    def _error(self, task, reason, url):
        return StructuredProviderError(
            provider=self.name,
            indicator_key=str(task.get("indicator_key") or ""),
            reason=reason,
            diagnostics={"url": url},
        )

    @staticmethod
    def _first_number(text, pattern):
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        return float(match.group(1)) if match else None

    @staticmethod
    def _period_from_text(text):
        match = re.search(r'(20\\d{2})年(\\d{1,2})月', text)
        if not match:
            return None
        return "{0}-{1:02d}".format(int(match.group(1)), int(match.group(2)))
```

- [ ] **Step 4: Run official provider tests**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_providers.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit official provider**

Run:

```bash
git add src/datasource/providers/stage2_structured/official_china.py tests/test_stage2_structured_providers.py
git commit -m "feat: add official china structured provider"
```

## Task 4: EastMoney ETF Provider With Strict Fund-Flow Windows

**Files:**
- Create: `src/datasource/providers/stage2_structured/eastmoney_etf.py`
- Modify: `tests/test_stage2_structured_providers.py`

- [ ] **Step 1: Add failing ETF provider tests**

Append these tests to `tests/test_stage2_structured_providers.py`:

```python
from datasource.providers.stage2_structured.eastmoney_etf import EastMoneyETFProvider


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_computes_direct_daily_windows():
    rows = [{"date": "2026-01-{0:02d}".format(i + 1), "net_flow": "1.0"} for i in range(120)]

    async def fetch_json(url, params=None):
        assert "push2his.eastmoney.com" in url
        return {"data": {"klines": rows}}

    provider = EastMoneyETFProvider(fetch_json=fetch_json)
    result = await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.category == "fund_flow"
    assert extraction["recent_5d"] == 5.0
    assert extraction["total_120d"] == 120.0
    assert extraction["metric_basis"] == "net_flow_sum"
    assert extraction["window_evidence"] == "direct_daily_series"
    assert extraction["is_estimated"] is False
    assert extraction["source_url"] == "https://data.eastmoney.com/etf/"


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_rejects_short_window():
    rows = [{"date": "2026-05-{0:02d}".format(i + 1), "net_flow": "1.0"} for i in range(10)]

    async def fetch_json(url, params=None):
        return {"data": {"klines": rows}}

    provider = EastMoneyETFProvider(fetch_json=fetch_json)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-23")

    assert exc_info.value.reason == "policy_gate_blocked"
```

- [ ] **Step 2: Run ETF tests and verify they fail**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_providers.py -q
```

Expected: FAIL because `eastmoney_etf.py` does not exist.

- [ ] **Step 3: Implement `EastMoneyETFProvider`**

Create `src/datasource/providers/stage2_structured/eastmoney_etf.py`:

```python
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

from .base import Stage2StructuredProvider, StructuredProviderError, StructuredResult
from .http_fetcher import fetch_json as default_fetch_json
from .source_tiers import classify_structured_source_tier


FetchJson = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Dict[str, Any]]]


class EastMoneyETFProvider(Stage2StructuredProvider):
    name = "eastmoney_etf"
    supported_keys = {"etf"}
    api_url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    source_url = "https://data.eastmoney.com/etf/"

    def __init__(self, fetch_json: FetchJson = default_fetch_json) -> None:
        self._fetch_json = fetch_json

    async def fetch(self, task, market_payload, reference_date):
        if str(task.get("indicator_key") or "") != "etf":
            raise StructuredProviderError(provider=self.name, indicator_key=str(task.get("indicator_key") or ""), reason="unsupported_key")
        data = await self._fetch_json(self.api_url, {"secid": "1.000000", "klt": "101", "fqt": "1"})
        rows = self._parse_rows(data)
        if len(rows) < 120:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key="etf",
                reason="policy_gate_blocked",
                message="direct_daily_series requires at least 120 rows",
                diagnostics={"row_count": len(rows), "source_url": self.source_url},
            )
        recent_5d = round(sum(row["net_flow"] for row in rows[-5:]), 4)
        total_120d = round(sum(row["net_flow"] for row in rows[-120:]), 4)
        trend = "inflow" if recent_5d >= 0 else "outflow"
        return StructuredResult(
            provider=self.name,
            indicator_key="etf",
            category="fund_flow",
            payload={
                "value": recent_5d,
                "recent_5d": recent_5d,
                "total_120d": total_120d,
                "trend": trend,
                "unit": "亿元",
                "metric_basis": "net_flow_sum",
                "window_evidence": "direct_daily_series",
            },
            source="EastMoney ETF direct daily series",
            source_url=self.source_url,
            source_tier=classify_structured_source_tier(self.source_url),
            as_of_date=rows[-1]["date"],
            is_estimated=False,
            confidence=0.9,
            diagnostics={"row_count": len(rows), "evidence_text": "ETF direct_daily_series recent_5d total_120d"},
        )

    def _parse_rows(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_rows = ((data.get("data") or {}).get("klines") or [])
        rows = []
        for item in raw_rows:
            if isinstance(item, dict):
                date = str(item.get("date") or item.get("trade_date") or "")
                net_flow = float(item.get("net_flow"))
            else:
                parts = str(item).split(",")
                date = parts[0]
                net_flow = float(parts[-1])
            if date:
                rows.append({"date": date, "net_flow": net_flow})
        return rows
```

- [ ] **Step 4: Run ETF provider tests**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_providers.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit ETF provider**

Run:

```bash
git add src/datasource/providers/stage2_structured/eastmoney_etf.py tests/test_stage2_structured_providers.py
git commit -m "feat: add eastmoney etf structured provider"
```

## Task 5: Stage2 Structured Provider Integration

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Test: `tests/test_stage2_structured_integration.py`

- [ ] **Step 1: Write failing Stage2 integration tests**

Create `tests/test_stage2_structured_integration.py`:

```python
import asyncio
from pathlib import Path

import pytest

from datasource.providers.stage2_structured.base import StructuredProviderError, StructuredResult
from scripts.stage2_unified_enhancer import _execute_tasks


class NoSearchClient:
    async def search(self, *args, **kwargs):
        raise AssertionError("search must not run when structured provider succeeds")

    async def extract(self, *args, **kwargs):
        raise AssertionError("tavily extract must not run when structured provider succeeds")


class NoDeepSeekExtractor:
    async def extract(self, *args, **kwargs):
        raise AssertionError("DeepSeek must not run when structured provider succeeds")


class StructuredGoldRegistry:
    async def fetch(self, task, market_payload, reference_date):
        return StructuredResult(
            provider="fixture_structured",
            indicator_key="GC=F",
            category="commodities",
            payload={"value": 3367.8, "unit": "$/oz"},
            source="fixture quote",
            source_url="https://finance.yahoo.com/quote/GC=F",
            source_tier="tier2",
            as_of_date="2026-05-22",
            confidence=0.99,
        )


def test_execute_tasks_writes_structured_success_without_search(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-23"},
        "commodities": [{"symbol": "GC=F", "name": "COMEX黄金", "current_price": None}],
        "missing_items": [{"key": "GC=F"}],
    }
    task = {
        "task_id": "gold-task",
        "indicator_key": "GC=F",
        "stage_phase": "assets",
        "category": "commodities",
        "search_backend": "tavily",
        "unit": "$/oz",
        "created_at": 1779480000,
    }
    stats = {}

    completed, failures, websearch_results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            NoSearchClient(),
            None,
            NoDeepSeekExtractor(),
            tmp_path / "task_log.jsonl",
            cache_ttl=10,
            stats=stats,
            structured_registry=StructuredGoldRegistry(),
        )
    )

    assert len(completed) == 1
    assert failures == []
    assert payload["commodities"][0]["current_price"] == 3367.8
    assert payload["commodities"][0]["source"] == "structured"
    assert websearch_results[0]["search_backend"] == "structured"
    assert websearch_results[0]["result_type"] == "structured_success"
    assert stats["structured_provider_attempt_count"] == 1
    assert stats["structured_provider_success_count"] == 1
    assert stats["structured_provider_success_by_key"] == {"GC=F": 1}


class FailingRegistry:
    async def fetch(self, task, market_payload, reference_date):
        raise StructuredProviderError(
            provider="fixture_structured",
            indicator_key=task["indicator_key"],
            reason="parse_error",
            message="fixture parse failure",
        )


class SearchClient:
    def __init__(self):
        self.search_called = 0

    async def search(self, *args, **kwargs):
        self.search_called += 1
        return {
            "results": [
                {
                    "url": "https://finance.yahoo.com/quote/CL=F",
                    "snippet": "CL=F WTI crude oil 61.5 $/bbl",
                    "content": "CL=F WTI crude oil 61.5 $/bbl",
                    "score": 0.9,
                }
            ]
        }

    async def extract(self, *args, **kwargs):
        return {"results": []}


class SearchExtractor:
    async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
        return {
            "value": 61.5,
            "unit": "$/bbl",
            "source_url": "https://finance.yahoo.com/quote/CL=F",
            "confidence": 0.9,
            "manual_required": False,
            "manual_reason": None,
        }


def test_execute_tasks_falls_back_to_search_after_provider_failure(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-23"},
        "commodities": [{"symbol": "CL=F", "name": "WTI原油", "current_price": None}],
        "missing_items": [{"key": "CL=F"}],
    }
    task = {
        "task_id": "oil-task",
        "indicator_key": "CL=F",
        "stage_phase": "assets",
        "category": "commodities",
        "search_backend": "tavily",
        "unit": "$/bbl",
        "preferred_domains": ["finance.yahoo.com"],
        "created_at": 1779480000,
    }
    client = SearchClient()
    stats = {}

    completed, failures, websearch_results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            client,
            None,
            SearchExtractor(),
            tmp_path / "task_log.jsonl",
            cache_ttl=10,
            stats=stats,
            structured_registry=FailingRegistry(),
            low_score_threshold=0,
        )
    )

    assert len(completed) == 1
    assert failures == []
    assert client.search_called == 1
    assert payload["commodities"][0]["current_price"] == 61.5
    assert websearch_results[-1]["search_backend"] == "tavily"
    assert stats["structured_provider_attempt_count"] == 1
    assert stats["structured_provider_fallback_to_search_count"] == 1
    assert stats["structured_provider_error_breakdown"] == {"parse_error": 1}
```

- [ ] **Step 2: Run integration tests and verify they fail**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_integration.py -q
```

Expected: FAIL because `_execute_tasks()` does not accept `structured_registry`.

- [ ] **Step 3: Add Stage2 integration helpers**

Modify `scripts/stage2_unified_enhancer.py` imports:

```python
try:  # pragma: no cover - optional provider package is tested directly
    from datasource.providers.stage2_structured import StructuredProviderError, build_default_registry
except Exception:  # noqa: W0703
    StructuredProviderError = None  # type: ignore
    build_default_registry = None  # type: ignore
```

Add this helper near `_apply_extraction()`:

```python
def _structured_source_label_for_task(task: Dict[str, Any], source_url: Optional[str], note: Optional[str]) -> str:
    return "structured"


async def _try_structured_provider(
    *,
    task: Dict[str, Any],
    market_payload: Dict[str, Any],
    reference_date: str,
    structured_registry: Any,
    stats: Dict[str, Any],
    task_log_path: Path,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    if structured_registry is None:
        return None
    stats["structured_provider_attempt_count"] += 1
    started = time.perf_counter()
    try:
        result = await structured_registry.fetch(task, market_payload, reference_date)
    except Exception as exc:
        reason = getattr(exc, "reason", "provider_error")
        stats["structured_provider_fallback_to_search_count"] += 1
        breakdown = stats.setdefault("structured_provider_error_breakdown", {})
        breakdown[reason] = breakdown.get(reason, 0) + 1
        return None
    if result is None:
        stats["structured_provider_attempt_count"] -= 1
        return None

    extraction = result.to_extraction()
    snippets = list(result.audit_snippets())
    task_for_log = {
        **task,
        "search_backend": "structured",
        "structured_provider": result.provider,
        "source_tier": result.source_tier,
    }
    is_fund_flow = task["indicator_key"] in {"northbound", "southbound", "etf", "margin"}
    if is_fund_flow:
        adjusted_value, manual_required, note_append = _validate_fund_flow_extraction(
            extraction,
            indicator_key=task["indicator_key"],
        )
        extraction["value"] = adjusted_value
        if note_append:
            extraction["note"] = _append_note(extraction.get("note"), note_append)
    else:
        adjusted_value, manual_required, note_append = _validate_general_extraction(
            extraction,
            task_for_log,
            snippets=snippets,
        )
        extraction["value"] = adjusted_value
        if note_append:
            extraction["note"] = _append_note(extraction.get("note"), note_append)
    if manual_required:
        stats["structured_provider_fallback_to_search_count"] += 1
        breakdown = stats.setdefault("structured_provider_error_breakdown", {})
        breakdown["policy_gate_blocked"] = breakdown.get("policy_gate_blocked", 0) + 1
        return None

    write_target = _apply_extraction(market_payload, task_for_log, extraction, snippets=snippets)
    if write_target == "skip_no_value":
        stats["structured_provider_fallback_to_search_count"] += 1
        breakdown = stats.setdefault("structured_provider_error_breakdown", {})
        breakdown["missing_value"] = breakdown.get("missing_value", 0) + 1
        return None
    post_writeback_reason = _post_writeback_manual_reason(market_payload, task["indicator_key"])
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    task_record = {
        "task_id": task["task_id"],
        "indicator_key": task["indicator_key"],
        "stage_phase": task["stage_phase"],
        "search_backend": "structured",
        "structured_provider": result.provider,
        "source_tier": result.source_tier,
        "extraction_backend": "structured",
        "confidence": extraction.get("confidence", 0.0),
        "source_url": extraction.get("source_url"),
        "note": extraction.get("note"),
        "llm_latency_ms": 0,
        "llm_error": None,
        "llm_timeout": False,
        "attempt_index": 0,
        "elapsed_ms": elapsed_ms,
        "created_at": task.get("created_at"),
        "finished_at": int(datetime.now().timestamp()),
        "manual_required": bool(post_writeback_reason),
        "manual_reason": post_writeback_reason,
        "write_back_success": post_writeback_reason is None,
        "result_type": "structured_success" if post_writeback_reason is None else "manual_required",
    }
    if post_writeback_reason:
        stats["structured_provider_fallback_to_search_count"] += 1
        breakdown = stats.setdefault("structured_provider_error_breakdown", {})
        breakdown[post_writeback_reason] = breakdown.get(post_writeback_reason, 0) + 1
        return None
    stats["structured_provider_success_count"] += 1
    by_key = stats.setdefault("structured_provider_success_by_key", {})
    by_key[task["indicator_key"]] = by_key.get(task["indicator_key"], 0) + 1
    latency = stats.setdefault("structured_provider_latency_ms_by_provider", {})
    latency[result.provider] = latency.get(result.provider, []) + [elapsed_ms]
    _update_missing_items(market_payload, task["indicator_key"])
    _append_task_log(task_log_path, task_record)
    return task_record, result.to_websearch_record(task_for_log)
```

Modify `_execute_tasks()` signature to include:

```python
    structured_registry: Any = None,
```

Add stats defaults near the other `stats.setdefault()` calls:

```python
    stats.setdefault("structured_provider_attempt_count", 0)
    stats.setdefault("structured_provider_success_count", 0)
    stats.setdefault("structured_provider_fallback_to_search_count", 0)
    stats.setdefault("structured_provider_success_by_key", {})
    stats.setdefault("structured_provider_error_breakdown", {})
    stats.setdefault("structured_provider_latency_ms_by_provider", {})
```

Inside the `for task in tasks:` loop, after the existing-value skip block and before Tavily unavailable checks, add:

```python
            reference_date = str(market_payload.get("metadata", {}).get("date") or datetime.now().date().isoformat())
            structured_result = await _try_structured_provider(
                task=task,
                market_payload=market_payload,
                reference_date=reference_date,
                structured_registry=structured_registry,
                stats=stats,
                task_log_path=task_log_path,
            )
            if structured_result is not None:
                task_record, websearch_item = structured_result
                completed.append(task_record)
                websearch_results.append(websearch_item)
                continue
```

- [ ] **Step 4: Make structured source label explicit**

Modify `_source_label_for_task()` so structured provider writes `source="structured"`:

```python
def _source_label_for_task(task: Dict[str, Any], source_url: Optional[str], note: Optional[str]) -> str:
    backend = str(task.get("search_backend") or "tavily").lower()
    if backend == "structured":
        return "structured"
    extraction_backend = str(task.get("extraction_backend") or "").lower()
    is_regex_note = isinstance(note, str) and (
        note.startswith("regex")
        or " regex_only" in note
        or " regex_fallback" in note
    )
    is_regex_extraction = extraction_backend == "regex" or is_regex_note
    if backend == "exa":
        if is_regex_extraction:
            return "exa_regex"
        return "exa+deepseek" if source_url else "exa_regex"
    if is_regex_extraction:
        return "tavily_regex"
    return "tavily+deepseek" if source_url else "tavily_regex"
```

- [ ] **Step 5: Run the integration tests**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_integration.py -q
```

Expected: PASS.

- [ ] **Step 6: Run existing Stage2 focused tests**

Run:

```bash
.venv/bin/pytest tests/test_stage2_unified.py tests/test_stage2_fallbacks.py tests/test_stage2_unified_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Stage2 integration**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_structured_integration.py
git commit -m "feat: run structured providers before stage2 search"
```

## Task 6: Summary Metrics and CLI Opt-Out

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Modify: `tests/test_stage2_structured_integration.py`

- [ ] **Step 1: Add failing metrics tests**

Append this test to `tests/test_stage2_structured_integration.py`:

```python
import scripts.stage2_unified_enhancer as stage2


def test_stage2_summary_includes_structured_provider_diagnostics():
    completed = [
        {"task_id": "a", "indicator_key": "GC=F", "result_type": "structured_success", "manual_required": False},
        {"task_id": "b", "indicator_key": "CL=F", "result_type": "search_success", "manual_required": False},
    ]
    failures = [
        {"task_id": "c", "indicator_key": "BCOM", "result_type": "manual_required", "manual_required": True},
    ]
    summary_fields = stage2._build_stage2_summary_diagnostics(
        completed,
        failures,
        websearch_results=[],
        exec_stats={
            "structured_provider_attempt_count": 2,
            "structured_provider_success_count": 1,
            "structured_provider_fallback_to_search_count": 1,
            "structured_provider_success_by_key": {"GC=F": 1},
            "structured_provider_error_breakdown": {"parse_error": 1},
            "structured_provider_latency_ms_by_provider": {"fixture": [3]},
        },
    )

    assert summary_fields["structured_provider_attempt_count"] == 2
    assert summary_fields["structured_provider_success_count"] == 1
    assert summary_fields["structured_provider_success_by_key"] == {"GC=F": 1}
    assert summary_fields["retrieval_diagnostics"]["writeback_success_count"] == 2
```

- [ ] **Step 2: Run the metrics test and verify it fails**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_integration.py::test_stage2_summary_includes_structured_provider_diagnostics -q
```

Expected: FAIL because `_build_stage2_summary_diagnostics()` does not copy structured-provider keys.

- [ ] **Step 3: Add summary keys and effective hit-rate helper**

Modify `scripts/stage2_unified_enhancer.py` near `_STAGE2_BACKEND_SUMMARY_KEYS`:

```python
_STAGE2_STRUCTURED_SUMMARY_KEYS = (
    "structured_provider_attempt_count",
    "structured_provider_success_count",
    "structured_provider_fallback_to_search_count",
    "structured_provider_success_by_key",
    "structured_provider_error_breakdown",
    "structured_provider_latency_ms_by_provider",
)
```

Modify `_build_stage2_summary_diagnostics()` after the backend summary loop:

```python
    for key in _STAGE2_STRUCTURED_SUMMARY_KEYS:
        if key in exec_stats:
            payload[key] = exec_stats[key]
```

Add this helper near `_build_retrieval_diagnostics()`:

```python
def _stage2_effective_hit_rate(success_count: int, failure_count: int) -> float:
    denominator = success_count + failure_count
    return success_count / denominator if denominator else 0.0
```

Modify the main summary calculation:

```python
    search_success_count = sum(
        1
        for t in completed_tasks
        if t.get("result_type") in {"search_success", "structured_success"}
    )
    search_failed_count = sum(1 for t in failures if t.get("result_type") == "manual_required")
    search_success_rate_incremental = _stage2_effective_hit_rate(search_success_count, search_failed_count)
```

Add this field in `summary`:

```python
        "stage2_effective_hit_rate": search_success_rate_incremental,
```

After backend summary keys are copied into `summary`, also copy structured keys:

```python
    for key in _STAGE2_STRUCTURED_SUMMARY_KEYS:
        if key in summary_diagnostics:
            summary[key] = summary_diagnostics[key]
```

- [ ] **Step 4: Add CLI opt-out and default registry construction**

Modify `_parse_args()` after `--enable-exa-fallback`:

```python
    parser.add_argument(
        "--disable-structured-providers",
        action="store_true",
        help="关闭 Stage2 structured-provider-first 路径，仅执行原 Tavily/Exa/DeepSeek 搜索链路",
    )
```

In `main()`, before calling `_execute_tasks()`, add:

```python
    structured_registry = None
    if not args.disable_structured_providers and build_default_registry is not None:
        structured_registry = build_default_registry()
```

Pass the registry into `_execute_tasks()`:

```python
                structured_registry=structured_registry,
```

Keep the LangChain path unchanged because `run_tasks_lc()` is experimental and does not use the structured provider registry in this iteration.

- [ ] **Step 5: Run structured integration and summary tests**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_integration.py tests/test_stage2_unified.py::test_retrieval_diagnostics_separates_search_extract_and_writeback -q
```

Expected: PASS.

- [ ] **Step 6: Commit metrics and CLI wiring**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_structured_integration.py
git commit -m "feat: audit structured stage2 hit rate"
```

## Task 7: Golden 2026-05-23 Hit-Rate Guard

**Files:**
- Create: `tests/test_stage2_structured_golden.py`

- [ ] **Step 1: Write the golden guard test**

Create `tests/test_stage2_structured_golden.py`:

```python
import asyncio
from pathlib import Path

from datasource.providers.stage2_structured.base import StructuredProviderError, StructuredResult
from scripts.stage2_unified_enhancer import _execute_tasks, _stage2_effective_hit_rate


P0_SUCCESS = {
    "GC=F": ("commodities", {"value": 3367.8, "unit": "$/oz"}, "https://finance.yahoo.com/quote/GC=F"),
    "CL=F": ("commodities", {"value": 61.5, "unit": "$/bbl"}, "https://finance.yahoo.com/quote/CL=F"),
    "BZ=F": ("commodities", {"value": 64.8, "unit": "$/bbl"}, "https://finance.yahoo.com/quote/BZ=F"),
    "HG=F": ("commodities", {"value": 4.9, "unit": "$/lb"}, "https://finance.yahoo.com/quote/HG=F"),
    "GSG": ("commodities", {"value": 22.1, "unit": "USD"}, "https://finance.yahoo.com/quote/GSG"),
    "reverse_repo": ("monetary_policy", {"value": 1.4, "unit": "%"}, "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125434/125798/index.html"),
    "mlf": ("monetary_policy", {"value": 2.0, "unit": "%"}, "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125437/125446/125873/index.html"),
    "USDCNY": ("forex", {"value": 7.1138, "unit": ""}, "https://www.chinamoney.com.cn/chinese/bkccpr/"),
    "industrial": ("macro_indicators", {"value": 6.1, "unit": "%", "value_type": "yoy_month", "report_period": "2026-04"}, "https://www.stats.gov.cn/sj/zxfb/"),
    "industrial_sales": ("macro_indicators", {"value": 5.0, "unit": "%", "value_type": "yoy_ytd", "report_period": "2026-04"}, "https://www.stats.gov.cn/sj/zxfb/"),
    "CN10Y_CDB": ("bonds", {"value": 2.038, "unit": "%"}, "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/more?locale=cn_ZH"),
    "bdi": ("macro_indicators", {"value": 1346.0, "unit": "points"}, "https://tradingeconomics.com/commodity/baltic"),
    "DXY": ("forex", {"value": 99.1, "unit": "points"}, "https://tradingeconomics.com/united-states/currency"),
}


class GoldenRegistry:
    async def fetch(self, task, market_payload, reference_date):
        key = task["indicator_key"]
        if key not in P0_SUCCESS:
            raise StructuredProviderError(provider="golden", indicator_key=key, reason="missing_value")
        category, payload, source_url = P0_SUCCESS[key]
        tier = "tier1" if any(host in source_url for host in ["pbc.gov.cn", "chinamoney.com.cn", "stats.gov.cn", "chinabond.com.cn"]) else "tier2"
        return StructuredResult(
            provider="golden",
            indicator_key=key,
            category=category,
            payload=payload,
            source="golden fixture",
            source_url=source_url,
            source_tier=tier,
            as_of_date="2026-05-22" if "report_period" not in payload else None,
            report_period=payload.get("report_period"),
            confidence=0.95,
        )


class ManualSearchClient:
    async def search(self, *args, **kwargs):
        return {"results": []}

    async def extract(self, *args, **kwargs):
        return {"results": []}


class ManualExtractor:
    async def extract(self, *args, **kwargs):
        return {"value": None, "unit": "", "manual_required": True, "manual_reason": "no_value"}


def _market_payload():
    return {
        "metadata": {"date": "2026-05-23"},
        "commodities": [
            {"symbol": "GC=F", "current_price": None},
            {"symbol": "CL=F", "current_price": None},
            {"symbol": "BZ=F", "current_price": None},
            {"symbol": "HG=F", "current_price": None},
            {"symbol": "BCOM", "current_price": None},
            {"symbol": "GSG", "current_price": None},
        ],
        "forex": [{"pair": "USDCNY", "current_rate": None}, {"pair": "DXY", "current_rate": None}],
        "bonds": [{"symbol": "CN10Y_CDB", "current_yield": None}],
        "macro_indicators": {
            "industrial": {"current_value": None, "unit": "%"},
            "industrial_sales": {"current_value": None, "unit": "%"},
            "bdi": {"current_value": None, "unit": "points"},
        },
        "monetary_policy": {
            "reverse_repo": {"current_value": None, "unit": "%"},
            "mlf": {"current_value": None, "unit": "%"},
        },
        "fund_flow": {
            "etf": {"recent_5d": None, "total_120d": None, "is_estimated": True},
        },
        "missing_items": [{"key": key} for key in [
            "GC=F", "CL=F", "BZ=F", "HG=F", "BCOM", "GSG", "USDCNY", "DXY",
            "industrial", "industrial_sales", "CN10Y_CDB", "bdi", "reverse_repo", "mlf", "etf",
        ]],
    }


def _tasks(payload):
    tasks = []
    for item in payload["missing_items"]:
        key = item["key"]
        tasks.append(
            {
                "task_id": "task-" + key,
                "indicator_key": key,
                "stage_phase": "assets",
                "category": "fund_flow" if key == "etf" else "",
                "search_backend": "tavily",
                "unit": payload.get("macro_indicators", {}).get(key, {}).get("unit") or "$/bbl",
                "preferred_domains": [],
                "created_at": 1779480000,
            }
        )
    return tasks


def test_golden_20260523_structured_path_reaches_minimum_hit_rate(tmp_path: Path):
    payload = _market_payload()
    stats = {}

    completed, failures, _websearch = asyncio.run(
        _execute_tasks(
            _tasks(payload),
            payload,
            ManualSearchClient(),
            None,
            ManualExtractor(),
            tmp_path / "golden_task_log.jsonl",
            cache_ttl=10,
            stats=stats,
            structured_registry=GoldenRegistry(),
            low_score_threshold=0,
        )
    )

    success_count = len([row for row in completed if row.get("result_type") in {"structured_success", "search_success"}])
    failure_count = len([row for row in failures if row.get("result_type") == "manual_required"])
    assert _stage2_effective_hit_rate(success_count, failure_count) >= 0.70
    assert stats["structured_provider_success_count"] >= 12
    assert "BCOM" not in stats["structured_provider_success_by_key"]
```

- [ ] **Step 2: Run the golden guard**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_golden.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit golden guard**

Run:

```bash
git add tests/test_stage2_structured_golden.py
git commit -m "test: guard stage2 structured golden hit rate"
```

## Task 8: Markdown Documentation Audit and Final Verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify if audit finds live-current drift: `README.md`
- Modify if audit finds live-current drift: other non-historical `*.md` files that describe the active Stage1-4 pipeline
- Do not rewrite dated historical plans/specs solely because they describe the old state; treat files under `docs/superpowers/plans/` and `docs/superpowers/specs/` as historical unless they are this implementation plan or the current approved spec.

- [x] **Step 1: Audit all Markdown docs for active Stage2 references**

Run:

```bash
rg --files -g '*.md' | sort
rg -n "Stage2|Stage 2|Tavily|Exa|DeepSeek|Stage2\\.5|manual_required|search_success_rate|structured-provider|structured provider|采集优先级|核心数据流|Yahoo|AKShare|MCP WebSearch" -g '*.md'
```

Expected: produce a list of Markdown files that mention the active pipeline. Classify them into:

```text
living docs to update: AGENTS.md, CLAUDE.md, README.md if it describes current active Stage2
historical docs to leave intact: dated docs/superpowers/plans/*.md and docs/superpowers/specs/*.md except the current 2026-05-24 structured-provider spec/plan
generated or archived docs to update only if they claim to be current operating instructions
```

The implementation summary must include the audit result: which Markdown files were checked, which were updated, and which were intentionally left as historical records.

Audit result: 137 Markdown files checked. Updated living/current runbook files: `AGENTS.md`, `CLAUDE.md`, `README.md`, `README_STAGE2_SNIPPET.md`, `SCRIPTS.md`, `docs/AI背景扫描报告执行完整手册.md`, and `templates/AI_EXECUTION_CHECKLIST.md`. Left dated plans/specs, archive folders, optimization retrospectives, generated reports, and standalone outputs intact as historical context.

- [x] **Step 2: Update AGENTS Stage2 rules**

Modify `AGENTS.md` section 5.3 and section 6 so the Stage2 description says:

```markdown
Stage2 默认执行 structured-provider-first：对 `GC=F/CL=F/BZ=F/HG=F/GSG`、`reverse_repo/mlf/USDCNY/industrial/industrial_sales`、`CN10Y_CDB`、`DXY/bdi`、`etf` 先尝试可信结构化源；结构化源失败、超时、解析失败或质量 gate 阻断时，继续走 Tavily-first 搜索，Tavily quota/rate/payment 不可用时再进入 Exa failover。排障时可传 `--disable-structured-providers` 只跑原搜索链路。
```

Also add this summary rule:

```markdown
Stage2 真实命中率优先看 `stage2_effective_hit_rate`；该指标包含 structured-provider 成功和搜索抽取成功，不包含 skipped_existing，也不包含 Stage2.5 manual 注入。
```

- [x] **Step 3: Update CLAUDE quick summary**

Modify `CLAUDE.md` Project Overview and Critical Constraints so the core data flow says:

```markdown
**核心数据流**: Stage1 (API采集) → Stage2 (structured-provider-first + Tavily-first 搜索；必要时 Exa quota failover) → Stage2.5 (手工注入补缺) → Stage3 (Pring分析) → Stage4 (报告生成)
```

Modify the collection priority bullet so it says:

```markdown
- **采集优先级固定**: `TuShare(Stage1) -> Stage2(structured-provider-first + Tavily-first，必要时 Exa quota failover) -> Stage2.5`；排障可用 `--disable-structured-providers` 回到搜索-only 诊断路径
```

- [x] **Step 4: Update other living Markdown docs found by the audit**

If `README.md` or another non-historical Markdown file describes Stage2 as only Tavily/Exa/DeepSeek, update the active-flow sentence to:

```markdown
Stage2 uses structured-provider-first for known official or structured indicators, then falls back to Tavily-first search, Exa quota/rate/payment failover, and DeepSeek/regex extraction.
```

If a Markdown file is a dated historical plan, dated spec, generated report, archive note, or retrospective, do not rewrite its historical claims. If it is easy to confuse with current instructions, add one short pointer near the top:

```markdown
> Current operating instructions live in `AGENTS.md`; this dated document is historical context.
```

Do not add that pointer to every historical file automatically; only add it where the audit shows likely operator confusion.

- [x] **Step 5: Run focused verification**

Run:

```bash
.venv/bin/pytest tests/test_stage2_structured_providers.py tests/test_stage2_structured_integration.py tests/test_stage2_structured_golden.py -q
.venv/bin/pytest tests/test_stage2_unified.py tests/test_stage2_fallbacks.py tests/test_websearch_injector.py tests/test_stage3_guard.py -q
```

Expected: PASS.

- [x] **Step 6: Run full verification**

Run:

```bash
.venv/bin/pytest -q
```

Expected: `595 passed` or higher, `4 skipped`, and no failures. Warning count can change if dependencies emit additional deprecation warnings; list the final warning count in the implementation summary.

- [x] **Step 7: Commit documentation**

Run:

```bash
git add AGENTS.md CLAUDE.md README.md docs/superpowers/plans/2026-05-24-stage2-hit-rate-structured-provider.md
git commit -m "docs: document stage2 structured provider path"
```

## Task 9: Live Golden Validation

**Files:**
- No required code changes.
- Generated data/log files stay ignored unless the user explicitly asks to keep a run artifact.

- [ ] **Step 1: Run preflight**

Run:

```bash
bash run_preflight.sh
```

Expected: Tavily, DeepSeek, and TuShare connectivity pass. If Tavily is quota-limited but preflight still reaches the endpoint, continue because structured providers should carry the P0 set and Exa failover covers quota.

- [ ] **Step 2: Run Stage2 against a 2026-05-23 fixture or restored run input**

If `data/runs/20260523/market_data.json` exists in the active workspace, run:

```bash
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/20260523/market_data.json" \
  --output "data/runs/20260523/market_data_stage2_structured.json" \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend deepseek \
  --deepseek-timeout 30 \
  --llm-hard-timeout 35 \
  --deepseek-max-concurrency 3 \
  --queue-retry-limit 0 \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results "data/runs/20260523/websearch_results_auto_structured.json" \
  --log-output "logs/runs/20260523/stage2_unified_log_structured.json" \
  --gap-monitor "data/runs/20260523/gap_monitor_structured.json"
```

Expected: command exits 0 and writes the three structured-suffixed artifacts.

- [ ] **Step 3: Check hit-rate acceptance**

Run:

```bash
.venv/bin/python - <<'PY'
import json
p='logs/runs/20260523/stage2_unified_log_structured.json'
d=json.load(open(p, encoding='utf-8'))
print('stage2_effective_hit_rate=', d.get('stage2_effective_hit_rate'))
print('task_search_success=', d.get('task_search_success'))
print('task_search_failed=', d.get('task_search_failed'))
print('structured_provider_success_count=', d.get('structured_provider_success_count'))
print('structured_provider_success_by_key=', d.get('structured_provider_success_by_key'))
assert d.get('stage2_effective_hit_rate', 0) >= 0.70
PY
```

Expected: assertion passes. If it fails, inspect `structured_provider_error_breakdown` first; do not loosen `fund_flow` gates to raise the number.

- [ ] **Step 4: Final commit if live validation required code/doc corrections**

If live validation required a code or doc correction, commit only those tracked files:

```bash
git status --short
git add <tracked-files-that-were-corrected>
git commit -m "fix: harden stage2 structured provider validation"
```

Expected: no generated `data/`, `logs/`, or `reports/` artifacts are committed.
