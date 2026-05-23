import pytest

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.chinabond import ChinaBondProvider
from datasource.providers.stage2_structured.official_china import (
    MLF_URL,
    NBS_URL,
    RESERVE_RATIO_URL,
    REVERSE_REPO_URL,
    USDCNY_URL,
    OfficialChinaProvider,
)
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
    assert classify_structured_source_tier(OfficialChinaProvider.USDCNY_URL) == "tier1"


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


def test_official_china_provider_exposes_module_url_constants():
    assert OfficialChinaProvider.REVERSE_REPO_URL == REVERSE_REPO_URL
    assert OfficialChinaProvider.MLF_URL == MLF_URL
    assert OfficialChinaProvider.USDCNY_URL == USDCNY_URL
    assert OfficialChinaProvider.NBS_URL == NBS_URL
    assert OfficialChinaProvider.RESERVE_RATIO_URL == RESERVE_RATIO_URL


@pytest.mark.asyncio
async def test_official_china_provider_parses_reverse_repo_fixture():
    html = "2026年5月22日人民银行以固定利率、数量招标方式开展了7天期逆回购操作1185亿元，中标利率1.40%。"

    async def fetch_text(url, params=None):
        assert url == OfficialChinaProvider.REVERSE_REPO_URL
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "reverse_repo"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.source_tier == "tier1"
    assert extraction["value"] == 1.4
    assert extraction["unit"] == "%"
    assert extraction["operation_amount"] == 1185.0
    assert extraction["source_url"].startswith("https://www.pbc.gov.cn/")


@pytest.mark.asyncio
async def test_official_china_provider_parses_prefixed_reverse_repo_amount():
    html = "2026年5月22日人民银行开展1185亿元7天期逆回购操作，中标利率1.40%。"

    async def fetch_text(url, params=None):
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "reverse_repo"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == 1.4
    assert extraction["operation_amount"] == 1185.0


@pytest.mark.asyncio
async def test_official_china_provider_parses_mlf_fixture():
    html = "2026年5月15日开展中期借贷便利（MLF）操作1250亿元，中标利率2.00%。"

    async def fetch_text(url, params=None):
        assert url == OfficialChinaProvider.MLF_URL
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "mlf"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == 2.0
    assert extraction["operation_amount"] == 1250.0
    assert extraction["unit"] == "%"


@pytest.mark.asyncio
async def test_official_china_provider_parses_prefixed_mlf_amount():
    html = "2026年5月15日开展3000亿元中期借贷便利（MLF）操作，中标利率2.00%。"

    async def fetch_text(url, params=None):
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "mlf"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == 2.0
    assert extraction["operation_amount"] == 3000.0


@pytest.mark.asyncio
async def test_official_china_provider_exposes_mlf_multiple_price_markers():
    html = "2026年5月15日开展中期借贷便利（MLF）操作1250亿元，多重价位，中标利率2.00%。"

    async def fetch_text(url, params=None):
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "mlf"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    marker_text = "{0} {1}".format(
        extraction.get("policy_name", ""),
        extraction.get("manual_reason", ""),
    )
    assert extraction["source"] == "Official China structured source"
    assert "多重价位" in marker_text
    assert "参考值" in marker_text


@pytest.mark.asyncio
async def test_official_china_provider_parses_usdcny_fixture():
    html = "2026-05-22 USD/CNY 人民币汇率中间价 7.1138"

    async def fetch_text(url, params=None):
        assert url == OfficialChinaProvider.USDCNY_URL
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "USDCNY"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["category"] == "forex"
    assert extraction["value"] == 7.1138
    assert extraction["unit"] == ""


@pytest.mark.asyncio
async def test_official_china_provider_parses_industrial_fixture():
    html = "2026年4月份，规模以上工业增加值同比实际增长6.1%。从环比看，4月份，规模以上工业增加值比上月增长0.22%。"

    async def fetch_text(url, params=None):
        assert url == OfficialChinaProvider.NBS_URL
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch(
        {"indicator_key": "industrial", "expected_period": "2026-04"},
        {},
        "2026-05-23",
    )

    extraction = result.to_extraction()
    assert extraction["category"] == "macro_indicators"
    assert extraction["value"] == 6.1
    assert extraction["value_type"] == "yoy_month"
    assert extraction["report_period"] == "2026-04"


@pytest.mark.asyncio
async def test_official_china_provider_parses_negative_industrial_fixture():
    html = "2026年4月份，规模以上工业增加值同比下降1.2%。"

    async def fetch_text(url, params=None):
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "industrial"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == -1.2
    assert extraction["yoy_month"] == -1.2


@pytest.mark.asyncio
async def test_official_china_provider_parses_reserve_ratio_fixture():
    html = "中国人民银行决定下调金融机构存款准备金率0.5个百分点，调整后加权平均存款准备金率约为6.2%。"

    async def fetch_text(url, params=None):
        assert url == OfficialChinaProvider.RESERVE_RATIO_URL
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "reserve_ratio"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["category"] == "monetary_policy"
    assert extraction["value"] == 6.2
    assert extraction["unit"] == "%"


@pytest.mark.asyncio
async def test_official_china_provider_parses_industrial_sales_ytd_fixture():
    html = "规模以上工业企业营业收入同比增长2.5%。"

    async def fetch_text(url, params=None):
        assert url == OfficialChinaProvider.NBS_URL
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "industrial_sales"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["category"] == "macro_indicators"
    assert extraction["value"] == 2.5
    assert extraction["value_type"] == "yoy_ytd"
    assert extraction["yoy_ytd"] == extraction["value"]
    assert extraction["report_period"] == "2026-05"


@pytest.mark.asyncio
async def test_official_china_provider_parses_negative_industrial_sales_fixture():
    html = "规模以上工业企业营业收入同比减少0.8%。"

    async def fetch_text(url, params=None):
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "industrial_sales"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == -0.8
    assert extraction["yoy_ytd"] == -0.8


@pytest.mark.asyncio
async def test_official_china_provider_wraps_fetch_errors():
    async def fetch_text(url, params=None):
        raise RuntimeError("network down")

    provider = OfficialChinaProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "reverse_repo"}, {}, "2026-05-23")

    assert exc_info.value.reason == "fetch_error"
    assert exc_info.value.diagnostics["url"] == OfficialChinaProvider.REVERSE_REPO_URL


@pytest.mark.asyncio
async def test_official_china_provider_rejects_unsupported_key():
    provider = OfficialChinaProvider()

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "BCOM"}, {}, "2026-05-23")

    assert exc_info.value.reason == "unsupported_key"


@pytest.mark.asyncio
async def test_official_china_provider_rejects_missing_value():
    async def fetch_text(url, params=None):
        return "央行公告未包含可解析利率。"

    provider = OfficialChinaProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "reverse_repo"}, {}, "2026-05-23")

    assert exc_info.value.reason == "missing_value"
    assert exc_info.value.diagnostics["url"] == OfficialChinaProvider.REVERSE_REPO_URL
