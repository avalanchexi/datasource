import pytest

from datasource.config.search_profiles import SEARCH_PROFILES
from datasource.engines.stage2.query_planner import _candidate_query_quality
from datasource.engines.stage2.validation import _validate_general_extraction
from datasource.providers.stage2_structured import trading_economics as te
from datasource.providers.stage2_structured.base import (
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.market_quote_pages import (
    QUOTE_PAGES,
)
from datasource.providers.stage2_structured.official_china import (
    OfficialChinaProvider,
)
from datasource.providers.stage2_structured.registry import (
    build_default_registry,
)
from datasource.providers.stage2_structured.trading_economics import (
    TradingEconomicsProvider,
)


def _names(key):
    return [p.name for p in build_default_registry().providers_for(key)]


def test_trading_economics_no_longer_supports_reserve_ratio():
    assert "reserve_ratio" not in te.build_provider().supported_keys
    assert "reserve_ratio" not in te.URLS


def test_registry_reserve_ratio_only_official_china():
    assert _names("reserve_ratio") == ["official_china"]


@pytest.mark.asyncio
async def test_reserve_ratio_official_failure_does_not_fallback_to_te(
    monkeypatch,
):
    async def fail_official(self, task, market_payload, reference_date):
        raise StructuredProviderError(
            provider=self.name,
            indicator_key=task["indicator_key"],
            reason="fixture_official_failure",
            message="official fixture failure",
        )

    async def wrong_te_fallback(self, task, market_payload, reference_date):
        return StructuredResult(
            provider=self.name,
            indicator_key=task["indicator_key"],
            category="monetary_policy",
            payload={"value": 7.5, "unit": "%", "is_estimated": False},
            source="Trading Economics structured page",
            source_url="https://tradingeconomics.com/china/cash-reserve-ratio",
            source_tier="tier2",
            as_of_date="2026-04-30",
            confidence=0.85,
            diagnostics={"fixture": "wrong_te_fallback"},
        )

    monkeypatch.setattr(OfficialChinaProvider, "fetch", fail_official)
    monkeypatch.setattr(TradingEconomicsProvider, "fetch", wrong_te_fallback)

    with pytest.raises(StructuredProviderError) as exc_info:
        await build_default_registry().fetch(
            {"indicator_key": "reserve_ratio"},
            {},
            "2026-05-23",
        )

    assert exc_info.value.provider == "official_china"
    attempts = exc_info.value.diagnostics.get(
        "structured_provider_attempts", []
    )
    assert [item["structured_provider"] for item in attempts] == [
        "official_china"
    ]


def test_trading_economics_keeps_other_keys():
    supported_keys = te.build_provider().supported_keys
    for key in ("GC=F", "CL=F", "BZ=F", "HG=F", "reverse_repo"):
        assert key in supported_keys, key


def test_bcom_single_fixed_quote_source():
    assert _names("BCOM") == ["market_quote_pages"]


def test_bcom_rejects_total_return_variants():
    bad_tokens = [token.lower() for token in QUOTE_PAGES["BCOM"]["bad_tokens"]]
    assert "total return" in bad_tokens
    assert "bcomtr" in bad_tokens


def test_rrr_search_profile_blocks_trading_economics_cash_reserve_ratio():
    profile = SEARCH_PROFILES["rrr"]

    assert "tradingeconomics.com" not in profile["preferred_domains"]
    assert "Trading Economics" not in profile["issuer_aliases"]
    assert "tradingeconomics.com" not in profile["good_url_patterns"]
    assert "cash-reserve-ratio" in profile["bad_url_patterns"]
    assert all(
        "tradingeconomics.com" not in family.get("preferred_domains", [])
        for family in profile["query_families"]
    )


def test_rrr_query_quality_rejects_cash_reserve_ratio_url():
    task = {
        **SEARCH_PROFILES["rrr"],
        "indicator_key": "rrr",
    }
    candidate = {
        "query": "China reserve requirement ratio latest PBOC",
        "preferred_domains": task["preferred_domains"],
    }
    snippets = [
        {
            "url": "https://tradingeconomics.com/china/cash-reserve-ratio",
            "title": "China Cash Reserve Ratio",
            "content": (
                "China Cash Reserve Ratio was 7.50 percent. "
                "PBOC reserve requirement ratio latest. "
                "中国人民银行 存款准备金率 降准 当前水平."
            ),
            "score": 0.95,
        }
    ]

    quality = _candidate_query_quality(task, candidate, snippets)

    assert quality["usable_count"] == 0
    assert quality["bad_url_hit_count"] == 1
    assert quality["unusable_reason"] == "search_result_scope_mismatch"


def test_rrr_validation_rejects_cash_reserve_ratio_source_url():
    extraction = {
        "value": 7.5,
        "unit": "%",
        "source_url": "https://tradingeconomics.com/china/cash-reserve-ratio",
        "issuer_match": True,
    }
    task = {
        **SEARCH_PROFILES["rrr"],
        "indicator_key": "rrr",
    }

    value, manual_required, note = _validate_general_extraction(
        extraction,
        task,
        snippets=[],
    )

    assert value == 7.5
    assert manual_required is True
    assert "错口径来源" in note
