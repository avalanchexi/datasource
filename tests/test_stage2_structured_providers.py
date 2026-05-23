import pytest

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.chinabond import ChinaBondProvider
from datasource.providers.stage2_structured.registry import StructuredProviderRegistry
from datasource.providers.stage2_structured.source_tiers import classify_structured_source_tier
from datasource.providers.stage2_structured.trading_economics import TradingEconomicsProvider
from datasource.providers.stage2_structured.yahoo_finance import YahooFinanceProvider


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


class AlternateFakeProvider(FakeProvider):
    name = "alternate_fake"


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


def test_registry_provider_for_returns_first_registered_provider():
    first = FakeProvider()
    second = AlternateFakeProvider()
    registry = StructuredProviderRegistry([first, second])

    assert registry.provider_for("GC=F") is first


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


@pytest.mark.asyncio
async def test_base_provider_fetch_must_be_implemented():
    provider = Stage2StructuredProvider()

    with pytest.raises(NotImplementedError) as exc_info:
        await provider.fetch({"indicator_key": "GC=F"}, {}, "2026-05-23")

    assert str(exc_info.value) == "Stage2StructuredProvider.fetch must be implemented by subclasses"


def test_source_tier_classifier_uses_explicit_allowlists():
    assert classify_structured_source_tier("https://www.stats.gov.cn/sj/zxfb/202605/t.html") == "tier1"
    assert classify_structured_source_tier("https://finance.yahoo.com/quote/GC=F") == "tier2"
    assert classify_structured_source_tier("https://finance.sina.com.cn/a/20260523.html") == "tier3"
    assert classify_structured_source_tier("https://example.com/quote") == "unknown"
    assert classify_structured_source_tier("https://stats.gov.cn.evil.com/path") == "unknown"
    assert classify_structured_source_tier("https://evil.com/?next=stats.gov.cn") == "unknown"
    assert classify_structured_source_tier("https://stats.gov.cn@evil.com/path") == "unknown"
    assert classify_structured_source_tier("https://sub.stats.gov.cn/path") == "tier1"


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
async def test_yahoo_finance_provider_wraps_fetch_errors():
    async def fetch_json(url, params=None):
        raise RuntimeError("network down")

    provider = YahooFinanceProvider(fetch_json=fetch_json)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "GC=F"}, {}, "2026-05-23")

    assert exc_info.value.reason == "fetch_error"
    assert "query1.finance.yahoo.com" in exc_info.value.diagnostics["url"]
    assert exc_info.value.diagnostics["params"]["range"] == "5d"


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
async def test_trading_economics_provider_rejects_unmarked_span_value():
    html = "<html><body><span>999</span></body></html>"

    async def fetch_text(url, params=None):
        return html

    provider = TradingEconomicsProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "bdi"}, {}, "2026-05-23")

    assert exc_info.value.reason == "missing_value"


@pytest.mark.asyncio
async def test_trading_economics_provider_wraps_fetch_errors():
    async def fetch_text(url, params=None):
        raise RuntimeError("timeout")

    provider = TradingEconomicsProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "bdi"}, {}, "2026-05-23")

    assert exc_info.value.reason == "fetch_error"
    assert exc_info.value.diagnostics["url"] == "https://tradingeconomics.com/commodity/baltic"
    assert exc_info.value.diagnostics["params"] is None


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


@pytest.mark.asyncio
async def test_chinabond_provider_parses_reordered_date_fixture():
    html = "中债国开债到期收益率曲线 10年 2026-05-22 2.0380"

    async def fetch_text(url, params=None):
        return html

    provider = ChinaBondProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "CN10Y_CDB"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == 2.038


@pytest.mark.asyncio
async def test_chinabond_provider_wraps_fetch_errors():
    async def fetch_text(url, params=None):
        raise RuntimeError("timeout")

    provider = ChinaBondProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "CN10Y_CDB"}, {}, "2026-05-23")

    assert exc_info.value.reason == "fetch_error"
    assert exc_info.value.diagnostics["url"].startswith("https://yield.chinabond.com.cn/")
    assert exc_info.value.diagnostics["params"] is None


@pytest.mark.asyncio
async def test_chinabond_provider_rejects_unreasonable_yield_value():
    html = "中债国开债到期收益率曲线 10年 2026.0 2026-05-22"

    async def fetch_text(url, params=None):
        return html

    provider = ChinaBondProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "CN10Y_CDB"}, {}, "2026-05-23")

    assert exc_info.value.reason in {"missing_value", "parse_error"}
