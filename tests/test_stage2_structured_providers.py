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
