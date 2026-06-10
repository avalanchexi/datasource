from datetime import date, timedelta

import pandas as pd
import pytest

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.chinabond import ChinaBondProvider
from datasource.providers.stage2_structured.cdb_estimator import (
    CDBEstimatorProvider,
    build_provider as build_cdb_estimator_provider,
)
from datasource.providers.stage2_structured.eastmoney_etf import EastMoneyETFProvider
from datasource.providers.stage2_structured.official_china import (
    MLF_URL,
    NBS_URL,
    RESERVE_RATIO_URL,
    REVERSE_REPO_URL,
    USDCNY_URL,
    OfficialChinaProvider,
)
from datasource.providers.stage2_structured.registry import StructuredProviderRegistry
from datasource.providers.stage2_structured.registry import build_default_registry
from datasource.providers.stage2_structured.source_tiers import classify_structured_source_tier
from datasource.providers.stage2_structured.market_quote_pages import MarketQuotePageProvider
from datasource.providers.stage2_structured.stooq import StooqQuoteProvider
from datasource.providers.stage2_structured.trading_economics import TradingEconomicsProvider
from datasource.providers.stage2_structured.tushare_etf import (
    SOURCE_URL as TUSHARE_ETF_SOURCE_URL,
    TuShareETFProvider,
)
from datasource.providers.stage2_structured.yahoo_finance import YahooFinanceProvider


ALLOWED_ETF_SECID = "90.BKETF_FULL_MARKET_FIXTURE"


def _date_texts(count, start=date(2026, 1, 1)):
    return [(start + timedelta(days=offset)).isoformat() for offset in range(count)]


def _trade_dates(count, start=date(2026, 1, 1)):
    return [(start + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(count)]


class FakeTuShareETFPro:
    def __init__(
        self,
        missing_exchange=None,
        trade_date_count=131,
        wrong_trade_date=False,
        wrong_exchange=False,
        missing_by_date_exchange=None,
    ):
        self.trade_dates = _trade_dates(trade_date_count)
        self.missing_exchange = missing_exchange
        self.wrong_trade_date = wrong_trade_date
        self.wrong_exchange = wrong_exchange
        self.missing_by_date_exchange = set(missing_by_date_exchange or [])

    def trade_cal(self, exchange="", start_date=None, end_date=None, is_open=1):
        return pd.DataFrame(
            {"cal_date": self.trade_dates, "is_open": [1] * len(self.trade_dates)}
        )

    def etf_share_size(self, trade_date, exchange=None, market=None):
        exchange_value = exchange or market
        if exchange_value == self.missing_exchange:
            return pd.DataFrame([])
        if (trade_date, exchange_value) in self.missing_by_date_exchange:
            return pd.DataFrame([])
        index = self.trade_dates.index(trade_date)
        total_size_wan = (1000.0 + index) * 10000.0 / 2.0
        return pd.DataFrame(
            [
                {
                    "trade_date": "19000101" if self.wrong_trade_date else trade_date,
                    "exchange": "SSE" if self.wrong_exchange else exchange_value,
                    "total_size": total_size_wan,
                }
            ]
        )


class FakeTuShareETFProLatestMissing(FakeTuShareETFPro):
    def __init__(self):
        super().__init__(trade_date_count=131)

    def etf_share_size(self, trade_date=None, exchange=None, market=None):
        exchange_value = exchange or market
        if trade_date == _trade_dates(131)[-1] and exchange_value == "SSE":
            return []
        return super().etf_share_size(trade_date=trade_date, exchange=exchange_value)


class FakeTuShareETFProInternalMissing(FakeTuShareETFPro):
    def __init__(self):
        super().__init__(
            trade_date_count=131,
            missing_by_date_exchange={(_trade_dates(131)[20], "SSE")},
        )


class FakeTuShareETFProPartialRows(FakeTuShareETFPro):
    def __init__(
        self,
        partial_trade_date,
        partial_exchange="SSE",
        trade_date_count=131,
    ):
        super().__init__(trade_date_count=trade_date_count)
        self.partial_trade_date = partial_trade_date
        self.partial_exchange = partial_exchange

    def etf_share_size(self, trade_date, exchange=None, market=None):
        exchange_value = exchange or market
        index = self.trade_dates.index(trade_date)
        total_size_wan = (1000.0 + index) * 10000.0 / 2.0
        row_count = (
            1
            if (
                trade_date == self.partial_trade_date
                and exchange_value == self.partial_exchange
            )
            else 4
        )
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "exchange": exchange_value,
                    "ts_code": "{0}.{1:03d}".format(exchange_value, row_index),
                    "total_size": total_size_wan / row_count,
                }
                for row_index in range(row_count)
            ]
        )


class FakeTuShareETFProMostlyPartialRows(FakeTuShareETFPro):
    def __init__(self, partial_count=66, trade_date_count=131, partial_exchange="SSE"):
        super().__init__(trade_date_count=trade_date_count)
        self.partial_dates = set(self.trade_dates[:partial_count])
        self.partial_exchange = partial_exchange

    def etf_share_size(self, trade_date, exchange=None, market=None):
        exchange_value = exchange or market
        index = self.trade_dates.index(trade_date)
        total_size_wan = (1000.0 + index) * 10000.0 / 2.0
        row_count = (
            1
            if (
                trade_date in self.partial_dates
                and exchange_value == self.partial_exchange
            )
            else 4
        )
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "exchange": exchange_value,
                    "ts_code": "{0}.{1:03d}".format(exchange_value, row_index),
                    "total_size": total_size_wan / row_count,
                }
                for row_index in range(row_count)
            ]
        )


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
async def test_registry_falls_back_to_next_supported_provider():
    class PrimaryFailingProvider(FakeProvider):
        name = "primary"

        async def fetch(self, task, market_payload, reference_date):
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=task["indicator_key"],
                reason="fetch_error",
                message="primary provider failed",
            )

    registry = StructuredProviderRegistry(
        [PrimaryFailingProvider(), AlternateFakeProvider()]
    )

    result = await registry.fetch({"indicator_key": "GC=F"}, {}, "2026-05-23")

    assert result.provider == "alternate_fake"
    assert result.diagnostics["structured_provider_attempts"][0]["structured_provider"] == "primary"


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
async def test_registry_terminal_policy_block_does_not_try_next_provider():
    class TerminalFailingProvider(FakeProvider):
        name = "terminal"

        async def fetch(self, task, market_payload, reference_date):
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=task["indicator_key"],
                reason="policy_gate_blocked",
                message="terminal fixture",
                diagnostics={"terminal_structured_provider_error": True},
            )

    class ShouldNotRunProvider(FakeProvider):
        name = "should_not_run"
        calls = 0

        async def fetch(self, task, market_payload, reference_date):
            self.calls += 1
            return await super().fetch(task, market_payload, reference_date)

    fallback = ShouldNotRunProvider()
    registry = StructuredProviderRegistry([TerminalFailingProvider(), fallback])

    with pytest.raises(StructuredProviderError) as exc_info:
        await registry.fetch({"indicator_key": "GC=F"}, {}, "2026-05-23")

    assert exc_info.value.reason == "policy_gate_blocked"
    assert fallback.calls == 0
    assert exc_info.value.diagnostics["structured_provider_attempts"][0][
        "structured_provider"
    ] == "terminal"


@pytest.mark.asyncio
async def test_registry_does_not_fallback_on_unexpected_provider_exception():
    class UnexpectedFailureProvider(FakeProvider):
        name = "unexpected"

        async def fetch(self, task, market_payload, reference_date):
            raise RuntimeError("programming error")

    registry = StructuredProviderRegistry(
        [UnexpectedFailureProvider(), AlternateFakeProvider()]
    )

    with pytest.raises(RuntimeError, match="programming error"):
        await registry.fetch({"indicator_key": "GC=F"}, {}, "2026-05-23")


@pytest.mark.asyncio
async def test_base_provider_fetch_must_be_implemented():
    provider = Stage2StructuredProvider()

    with pytest.raises(NotImplementedError) as exc_info:
        await provider.fetch({"indicator_key": "GC=F"}, {}, "2026-05-23")

    assert str(exc_info.value) == "Stage2StructuredProvider.fetch must be implemented by subclasses"


def test_source_tier_classifier_uses_explicit_allowlists():
    assert classify_structured_source_tier("https://www.stats.gov.cn/sj/zxfb/202605/t.html") == "tier1"
    assert classify_structured_source_tier("https://finance.yahoo.com/quote/GC=F") == "tier2"
    assert classify_structured_source_tier("https://data.eastmoney.com/etf/") == "tier2"
    assert classify_structured_source_tier("https://finance.sina.com.cn/a/20260523.html") == "tier3"
    assert classify_structured_source_tier("https://example.com/quote") == "unknown"
    assert classify_structured_source_tier("https://stats.gov.cn.evil.com/path") == "unknown"
    assert classify_structured_source_tier("https://evil.com/?next=stats.gov.cn") == "unknown"
    assert classify_structured_source_tier("https://stats.gov.cn@evil.com/path") == "unknown"
    assert classify_structured_source_tier("https://sub.stats.gov.cn/path") == "tier1"
    assert classify_structured_source_tier(OfficialChinaProvider.USDCNY_URL) == "tier1"
    assert classify_structured_source_tier("https://stooq.com/q/l/?s=gsg.us") == "tier2"


def test_source_tier_classifier_marks_tushare_pro_as_tier2():
    assert classify_structured_source_tier(TUSHARE_ETF_SOURCE_URL) == "tier2"


def test_default_registry_orders_tushare_etf_before_eastmoney_etf():
    provider_names = [
        provider.name
        for provider in build_default_registry().providers_for("etf")
    ]

    assert provider_names.index("tushare_etf") < provider_names.index("eastmoney_etf")


def test_default_registry_orders_market_quote_pages_before_quote_fallbacks():
    provider_names = [
        provider.name
        for provider in build_default_registry().providers_for("GSG")
    ]

    assert provider_names.index("market_quote_pages") < provider_names.index("stooq")
    assert provider_names.index("market_quote_pages") < provider_names.index("yahoo_finance")


@pytest.mark.asyncio
async def test_market_quote_page_provider_parses_bcom_investing_close():
    html = """
    <html><body>
      <h1>Bloomberg Commodity Historical Data</h1>
      <table>
        <tr><td>Jun 09, 2026</td><td>130.9746</td><td>132.4088</td></tr>
      </table>
    </body></html>
    """

    async def fetch_text(url, params=None):
        assert "bloomberg-commodity-historical-data" in url
        return html

    provider = MarketQuotePageProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "BCOM"}, {}, "2026-06-10")

    extraction = result.to_extraction()
    assert result.provider == "market_quote_pages"
    assert extraction["value"] == pytest.approx(130.9746)
    assert extraction["unit"] == "index points"
    assert extraction["as_of_date"] == "2026-06-09"
    assert extraction["diagnostics"]["price_basis"] == "official_close"


@pytest.mark.asyncio
async def test_market_quote_page_provider_uses_previous_weekday_for_monday_bcom_close():
    html = """
    <html><body>
      <h1>Bloomberg Commodity Historical Data</h1>
      <table>
        <tr><td>Jun 12, 2026</td><td>129.5000</td><td>130.9746</td></tr>
      </table>
    </body></html>
    """

    async def fetch_text(url, params=None):
        assert "bloomberg-commodity-historical-data" in url
        return html

    provider = MarketQuotePageProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "BCOM"}, {}, "2026-06-15")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(129.5)
    assert extraction["as_of_date"] == "2026-06-12"
    assert extraction["diagnostics"]["candidate_close_dates"][:3] == [
        "2026-06-12",
        "2026-06-11",
        "2026-06-10",
    ]
    assert extraction["diagnostics"]["as_of_date_basis"] == "date_row"


@pytest.mark.asyncio
async def test_market_quote_page_provider_parses_gsg_stockanalysis_close():
    html = """
    <html><body>
      <h1>iShares S&P GSCI Commodity-Indexed Trust</h1>
      <div>Previous Close 31.24</div>
      <div>Jun 09, 2026</div>
    </body></html>
    """

    async def fetch_text(url, params=None):
        assert "stockanalysis.com/etf/gsg" in url
        return html

    provider = MarketQuotePageProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "GSG"}, {}, "2026-06-10")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(31.24)
    assert extraction["unit"] == "USD"
    assert extraction["as_of_date"] == "2026-06-09"
    assert extraction["diagnostics"]["price_basis"] == "market_close"


@pytest.mark.asyncio
async def test_market_quote_page_provider_uses_explicit_page_date_for_labelled_gsg_close():
    html = """
    <html><body>
      <h1>iShares S&P GSCI Commodity-Indexed Trust</h1>
      <div>Previous Close 31.24</div>
      <div>Market data as of Jun 12, 2026</div>
    </body></html>
    """

    async def fetch_text(url, params=None):
        assert "stockanalysis.com/etf/gsg" in url
        return html

    provider = MarketQuotePageProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "GSG"}, {}, "2026-06-16")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(31.24)
    assert extraction["as_of_date"] == "2026-06-12"
    assert extraction["diagnostics"]["as_of_date_basis"] == "labelled_close_with_date"
    assert "2026-06-12" in extraction["diagnostics"]["candidate_close_dates"]


@pytest.mark.asyncio
async def test_market_quote_page_provider_uses_nearest_explicit_date_for_labelled_gsg_close():
    html = """
    <html><body>
      <h1>iShares S&P GSCI Commodity-Indexed Trust</h1>
      <section>Older table heading Jun 10, 2026 with enough intervening context to keep this stale heading farther away from the close value than the later page date.</section>
      <div>Previous Close 31.24</div>
      <div>Market data as of Jun 12, 2026</div>
    </body></html>
    """

    async def fetch_text(url, params=None):
        assert "stockanalysis.com/etf/gsg" in url
        return html

    provider = MarketQuotePageProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "GSG"}, {}, "2026-06-16")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(31.24)
    assert extraction["as_of_date"] == "2026-06-12"
    assert extraction["diagnostics"]["as_of_date_basis"] == "labelled_close_with_date"


@pytest.mark.asyncio
async def test_market_quote_page_provider_prefers_closest_date_over_farther_as_of_date():
    html = """
    <html><body>
      <h1>iShares S&P GSCI Commodity-Indexed Trust</h1>
      <div>Previous Close 31.24 <span>Jun 11, 2026</span></div>
      <p>Supplemental context with enough words to move the later date farther away from the close value.</p>
      <p>Market data as of Jun 12, 2026</p>
    </body></html>
    """

    async def fetch_text(url, params=None):
        assert "stockanalysis.com/etf/gsg" in url
        return html

    provider = MarketQuotePageProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "GSG"}, {}, "2026-06-16")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(31.24)
    assert extraction["as_of_date"] == "2026-06-11"
    assert extraction["diagnostics"]["as_of_date_basis"] == "labelled_close_with_date"


@pytest.mark.asyncio
async def test_market_quote_page_provider_does_not_invent_labelled_close_date():
    html = """
    <html><body>
      <h1>iShares S&P GSCI Commodity-Indexed Trust</h1>
      <div>Previous Close 31.24</div>
    </body></html>
    """

    async def fetch_text(url, params=None):
        assert "stockanalysis.com/etf/gsg" in url
        return html

    provider = MarketQuotePageProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "GSG"}, {}, "2026-06-16")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(31.24)
    assert "as_of_date" not in extraction
    assert extraction["diagnostics"]["as_of_date_basis"] == "labelled_close_without_date"


@pytest.mark.asyncio
async def test_market_quote_page_provider_prefers_gsg_labelled_close():
    html = """
    <html><body>
      <h1>iShares S&P GSCI Commodity-Indexed Trust</h1>
      <section>
        <span>Jun 09, 2026</span>
        <span>Volume 637017</span>
      </section>
      <div>Previous Close 31.24</div>
    </body></html>
    """

    async def fetch_text(url, params=None):
        assert "stockanalysis.com/etf/gsg" in url
        return html

    provider = MarketQuotePageProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "GSG"}, {}, "2026-06-10")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(31.24)
    assert extraction["value"] != pytest.approx(637017)


@pytest.mark.asyncio
async def test_market_quote_page_provider_rejects_bcom_total_return_page():
    async def fetch_text(url, params=None):
        return "Bloomberg Commodity Total Return Index BCOMTR 295.44 Jun 09, 2026"

    provider = MarketQuotePageProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "BCOM"}, {}, "2026-06-10")

    assert exc_info.value.reason == "rejected_page"


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
async def test_yahoo_finance_provider_fetches_market_quote():
    await test_yahoo_finance_provider_parses_chart_quote()


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
async def test_tushare_etf_provider_computes_total_size_delta_windows():
    provider = TuShareETFProvider(pro=FakeTuShareETFPro())

    result = await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.provider == "tushare_etf"
    assert result.source_tier == "tier2"
    assert extraction["category"] == "fund_flow"
    assert extraction["recent_5d"] == pytest.approx(5.0)
    assert extraction["total_120d"] == pytest.approx(120.0)
    assert extraction["metric_basis"] == "etf_total_size_delta"
    assert extraction["window_evidence"] == "direct_balance_delta"
    assert extraction["is_estimated"] is False
    assert extraction["source_url"] == TUSHARE_ETF_SOURCE_URL
    assert extraction["diagnostics"]["row_count"] == 262
    assert extraction["diagnostics"]["date_count"] == 121
    assert extraction["diagnostics"]["candidate_date_count"] == 131
    assert extraction["diagnostics"]["complete_date_count"] == 131
    assert extraction["diagnostics"]["exchange_count"] == 2


@pytest.mark.asyncio
async def test_tushare_etf_provider_uses_latest_complete_window_when_reference_date_incomplete():
    provider = TuShareETFProvider(pro=FakeTuShareETFProLatestMissing())

    result = await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-24")

    extraction = result.to_extraction()
    assert extraction["is_estimated"] is False
    assert extraction["metric_basis"] == "etf_total_size_delta"
    assert extraction["total_120d"] == pytest.approx(120.0)
    assert extraction["as_of_date"] == _trade_dates(131)[-2]
    assert extraction["diagnostics"]["latest_trade_date"] == _trade_dates(131)[-2]
    assert extraction["diagnostics"]["start_trade_date"] == _trade_dates(131)[9]
    assert extraction["diagnostics"]["latest_trade_date_was_incomplete"] is True
    assert extraction["diagnostics"]["skipped_incomplete_trade_dates"] == [
        _trade_dates(131)[-1]
    ]
    assert extraction["diagnostics"]["date_count"] == 121
    assert extraction["diagnostics"]["candidate_date_count"] == 131
    assert extraction["diagnostics"]["complete_date_count"] == 130


@pytest.mark.asyncio
async def test_tushare_etf_provider_fails_closed_when_internal_exchange_date_missing():
    provider = TuShareETFProvider(pro=FakeTuShareETFProInternalMissing())

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-24")

    assert exc_info.value.reason == "policy_gate_blocked"
    assert exc_info.value.diagnostics["missing_trade_date"] == _trade_dates(131)[20]
    assert exc_info.value.diagnostics["missing_exchange"] == "SSE"
    assert exc_info.value.diagnostics["latest_trade_date_was_incomplete"] is False
    assert exc_info.value.diagnostics["skipped_incomplete_trade_dates"] == [
        _trade_dates(131)[20]
    ]
    assert exc_info.value.diagnostics["candidate_date_count"] == 131
    assert exc_info.value.diagnostics["complete_date_count"] == 130


@pytest.mark.asyncio
async def test_tushare_etf_provider_fails_closed_when_exchange_rows_are_partial():
    partial_trade_date = _trade_dates(131)[20]
    provider = TuShareETFProvider(
        pro=FakeTuShareETFProPartialRows(partial_trade_date=partial_trade_date)
    )

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-24")

    diagnostics = exc_info.value.diagnostics
    assert exc_info.value.reason == "policy_gate_blocked"
    assert diagnostics["missing_trade_date"] == partial_trade_date
    assert diagnostics["missing_exchange"] == "SSE"
    assert diagnostics["incomplete_reason"] == "partial_exchange_rows"
    assert diagnostics["usable_row_count"] == 1
    assert diagnostics["min_required_row_count"] == 4
    assert diagnostics["usable_row_count_by_exchange"]["SSE"] == 1
    assert diagnostics["usable_row_count_by_exchange"]["SZSE"] == 4
    assert diagnostics["min_required_rows_by_exchange"]["SSE"] == 4
    assert diagnostics["skipped_incomplete_trade_dates"] == [partial_trade_date]
    assert diagnostics["terminal_structured_provider_error"] is True


@pytest.mark.asyncio
async def test_tushare_etf_provider_rolls_back_when_latest_exchange_rows_are_partial():
    latest_trade_date = _trade_dates(131)[-1]
    provider = TuShareETFProvider(
        pro=FakeTuShareETFProPartialRows(partial_trade_date=latest_trade_date)
    )

    result = await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-24")

    extraction = result.to_extraction()
    assert extraction["is_estimated"] is False
    assert extraction["metric_basis"] == "etf_total_size_delta"
    assert extraction["total_120d"] == pytest.approx(120.0)
    assert extraction["as_of_date"] == _trade_dates(131)[-2]
    assert extraction["diagnostics"]["latest_trade_date_was_incomplete"] is True
    assert extraction["diagnostics"]["skipped_incomplete_trade_dates"] == [
        latest_trade_date
    ]
    assert extraction["diagnostics"]["min_required_rows_by_exchange"]["SSE"] == 4
    assert extraction["diagnostics"]["min_required_rows_by_exchange"]["SZSE"] == 4
    assert extraction["diagnostics"]["complete_date_count"] == 130


@pytest.mark.asyncio
async def test_tushare_etf_provider_fails_closed_when_partial_rows_are_majority():
    provider = TuShareETFProvider(pro=FakeTuShareETFProMostlyPartialRows())

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-24")

    diagnostics = exc_info.value.diagnostics
    assert exc_info.value.reason == "policy_gate_blocked"
    assert diagnostics["missing_exchange"] == "SSE"
    assert diagnostics["incomplete_reason"] == "partial_exchange_rows"
    assert diagnostics["usable_row_count"] == 1
    assert diagnostics["min_required_row_count"] == 4
    assert diagnostics["min_required_rows_by_exchange"]["SSE"] == 4
    assert diagnostics["min_required_rows_by_exchange"]["SZSE"] == 4
    assert diagnostics["terminal_structured_provider_error"] is True


@pytest.mark.asyncio
async def test_tushare_etf_provider_accepts_compact_reference_date():
    provider = TuShareETFProvider(pro=FakeTuShareETFPro())

    result = await provider.fetch({"indicator_key": "etf"}, {}, "20260523")

    assert result.payload["recent_5d"] == pytest.approx(5.0)
    assert result.payload["total_120d"] == pytest.approx(120.0)


@pytest.mark.asyncio
async def test_tushare_etf_provider_fails_closed_when_exchange_missing():
    provider = TuShareETFProvider(pro=FakeTuShareETFPro(missing_exchange="SZSE"))

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-23")

    assert exc_info.value.reason == "policy_gate_blocked"
    assert exc_info.value.diagnostics["missing_exchange"] == "SZSE"
    assert exc_info.value.diagnostics["window_evidence"] == "direct_balance_delta"
    assert exc_info.value.diagnostics["terminal_structured_provider_error"] is True


@pytest.mark.asyncio
async def test_tushare_etf_provider_rejects_invalid_reference_date():
    provider = TuShareETFProvider(pro=FakeTuShareETFPro())

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026/05/23")

    assert exc_info.value.reason == "invalid_reference_date"


@pytest.mark.asyncio
async def test_tushare_etf_provider_skips_wrong_trade_date_rows_and_fails_closed():
    provider = TuShareETFProvider(pro=FakeTuShareETFPro(wrong_trade_date=True))

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-23")

    assert exc_info.value.reason == "policy_gate_blocked"
    assert exc_info.value.diagnostics["missing_trade_date"] == _trade_dates(121)[0]
    assert exc_info.value.diagnostics["terminal_structured_provider_error"] is True


@pytest.mark.asyncio
async def test_tushare_etf_provider_skips_wrong_exchange_rows_and_fails_closed():
    provider = TuShareETFProvider(pro=FakeTuShareETFPro(wrong_exchange=True))

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-23")

    assert exc_info.value.reason == "policy_gate_blocked"
    assert exc_info.value.diagnostics["missing_exchange"] == "SZSE"
    assert exc_info.value.diagnostics["terminal_structured_provider_error"] is True


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_computes_direct_daily_windows():
    rows = [
        {"date": date_text, "net_flow_yi": "1.0"} for date_text in _date_texts(120)
    ]

    async def fetch_json(url, params=None):
        assert "stock/fflow/daykline/get" in url
        assert params["secid"] == ALLOWED_ETF_SECID
        return {"data": {"klines": rows}}

    provider = EastMoneyETFProvider(
        fetch_json=fetch_json,
        allowed_full_market_secids={ALLOWED_ETF_SECID},
    )
    result = await provider.fetch(
        {"indicator_key": "etf", "secid": ALLOWED_ETF_SECID}, {}, "2026-05-23"
    )

    extraction = result.to_extraction()
    assert result.provider == "eastmoney_etf"
    assert result.source_tier == "tier2"
    assert extraction["category"] == "fund_flow"
    assert extraction["recent_5d"] == 5.0
    assert extraction["total_120d"] == 120.0
    assert extraction["metric_basis"] == "net_flow_sum"
    assert extraction["window_evidence"] == "direct_daily_series"
    assert extraction["is_estimated"] is False
    assert extraction["source_url"] == "https://data.eastmoney.com/etf/"
    assert extraction["diagnostics"]["row_count"] == 120
    assert extraction["diagnostics"]["net_flow_field"] == "net_flow_yi"
    assert extraction["diagnostics"]["net_flow_unit"] == "yi"


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_parses_fflow_daykline_strings():
    rows = [
        "{0},100000000,0,0,0,0,0,0,0,0,0,0,0,0,0".format(date_text)
        for date_text in _date_texts(120)
    ]

    async def fetch_json(url, params=None):
        assert "stock/fflow/daykline/get" in url
        assert params["fields2"].startswith("f51,f52")
        assert params["lmt"] == "0"
        return {"data": {"klines": rows}}

    provider = EastMoneyETFProvider(
        fetch_json=fetch_json,
        allowed_full_market_secids={ALLOWED_ETF_SECID},
    )
    result = await provider.fetch(
        {"indicator_key": "etf", "eastmoney_secid": ALLOWED_ETF_SECID},
        {},
        "2026-05-23",
    )

    extraction = result.to_extraction()
    assert extraction["recent_5d"] == 5.0
    assert extraction["total_120d"] == 120.0
    assert extraction["unit"] == "亿元"
    assert extraction["is_estimated"] is False
    assert extraction["diagnostics"]["net_flow_field"] == "f52"
    assert extraction["diagnostics"]["net_flow_unit"] == "yuan_to_yi"


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_sorts_rows_by_date_for_windows():
    rows = [
        "{0},{1},0,0,0,0,0,0,0,0,0,0,0,0,0".format(
            date_text,
            100000000 if index < 115 else 200000000,
        )
        for index, date_text in enumerate(_date_texts(120))
    ]
    rows = list(reversed(rows))

    async def fetch_json(url, params=None):
        return {"data": {"klines": rows}}

    provider = EastMoneyETFProvider(
        fetch_json=fetch_json,
        allowed_full_market_secids={ALLOWED_ETF_SECID},
    )
    result = await provider.fetch(
        {"indicator_key": "etf", "secid": ALLOWED_ETF_SECID}, {}, "2026-05-23"
    )

    extraction = result.to_extraction()
    assert extraction["recent_5d"] == 10.0
    assert extraction["total_120d"] == 125.0
    assert extraction["as_of_date"] == _date_texts(120)[-1]


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_blocks_unverified_secid_without_fetch():
    called = {"fetch": False}

    async def fetch_json(url, params=None):
        called["fetch"] = True
        return {"data": {"klines": []}}

    provider = EastMoneyETFProvider(fetch_json=fetch_json)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf", "secid": "1.515000"}, {}, "2026-05-23")

    assert called["fetch"] is False
    assert exc_info.value.reason == "policy_gate_blocked"
    assert exc_info.value.diagnostics["policy_gate"] == "unverified_full_market_etf_scope"
    assert exc_info.value.diagnostics["secid"] == "1.515000"


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_blocks_missing_secid_without_fetch():
    called = {"fetch": False}

    async def fetch_json(url, params=None):
        called["fetch"] = True
        return {"data": {"klines": []}}

    provider = EastMoneyETFProvider(
        fetch_json=fetch_json,
        allowed_full_market_secids={ALLOWED_ETF_SECID},
    )

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-23")

    assert called["fetch"] is False
    assert exc_info.value.reason == "policy_gate_blocked"
    assert exc_info.value.diagnostics["secid"] is None


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_rejects_short_window():
    rows = [
        {"date": date_text, "net_flow_yi": "1.0"} for date_text in _date_texts(10)
    ]

    async def fetch_json(url, params=None):
        return {"data": {"klines": rows}}

    provider = EastMoneyETFProvider(
        fetch_json=fetch_json,
        allowed_full_market_secids={ALLOWED_ETF_SECID},
    )

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch(
            {"indicator_key": "etf", "secid": ALLOWED_ETF_SECID}, {}, "2026-05-23"
        )

    assert exc_info.value.reason == "policy_gate_blocked"
    assert exc_info.value.diagnostics["row_count"] == 10
    assert exc_info.value.diagnostics["source_url"] == "https://data.eastmoney.com/etf/"


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_rejects_unsupported_key():
    provider = EastMoneyETFProvider()

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "northbound"}, {}, "2026-05-23")

    assert exc_info.value.reason == "unsupported_key"


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_wraps_fetch_errors():
    async def fetch_json(url, params=None):
        raise RuntimeError("network down")

    provider = EastMoneyETFProvider(
        fetch_json=fetch_json,
        allowed_full_market_secids={ALLOWED_ETF_SECID},
    )

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch(
            {"indicator_key": "etf", "secid": ALLOWED_ETF_SECID}, {}, "2026-05-23"
        )

    assert exc_info.value.reason == "fetch_error"
    assert exc_info.value.diagnostics["api_url"].startswith(
        "https://push2his.eastmoney.com/"
    )
    assert exc_info.value.diagnostics["source_url"] == "https://data.eastmoney.com/etf/"


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_malformed_rows_do_not_pass_policy_gate():
    rows = [
        {"date": date_text, "net_flow_yi": "1.0"} for date_text in _date_texts(118)
    ]
    rows.extend(
        [
            {"date": "2026-05-21", "net_flow": "not-a-number"},
            "2026-05-22,100000000,2,3,4,5",
            "2026-05-23,not-a-number,0,0,0,0,0,0,0,0,0,0,0,0,0",
        ]
    )

    async def fetch_json(url, params=None):
        return {"data": {"klines": rows}}

    provider = EastMoneyETFProvider(
        fetch_json=fetch_json,
        allowed_full_market_secids={ALLOWED_ETF_SECID},
    )

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch(
            {"indicator_key": "etf", "secid": ALLOWED_ETF_SECID}, {}, "2026-05-23"
        )

    assert exc_info.value.reason == "policy_gate_blocked"
    assert exc_info.value.diagnostics["row_count"] == 118
    assert exc_info.value.diagnostics["malformed_row_count"] == 3


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_latest_malformed_row_blocks_full_window():
    rows = [
        "{0},100000000,0,0,0,0,0,0,0,0,0,0,0,0,0".format(date_text)
        for date_text in _date_texts(120)
    ]
    rows.append("2026-05-31,not-a-number,0,0,0,0,0,0,0,0,0,0,0,0,0")

    async def fetch_json(url, params=None):
        return {"data": {"klines": rows}}

    provider = EastMoneyETFProvider(
        fetch_json=fetch_json,
        allowed_full_market_secids={ALLOWED_ETF_SECID},
    )

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch(
            {"indicator_key": "etf", "secid": ALLOWED_ETF_SECID}, {}, "2026-05-23"
        )

    assert exc_info.value.reason == "policy_gate_blocked"
    assert exc_info.value.diagnostics["row_count"] == 120
    assert exc_info.value.diagnostics["malformed_row_count"] == 1


@pytest.mark.asyncio
async def test_eastmoney_etf_provider_all_malformed_rows_parse_error():
    async def fetch_json(url, params=None):
        return {
            "data": {
                "klines": [
                    "2026-05-22,100000000,2,3,4,5",
                    "2026-05-23,not-a-number,0,0,0,0,0,0,0,0,0,0,0,0,0",
                ]
            }
        }

    provider = EastMoneyETFProvider(
        fetch_json=fetch_json,
        allowed_full_market_secids={ALLOWED_ETF_SECID},
    )

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch(
            {"indicator_key": "etf", "secid": ALLOWED_ETF_SECID}, {}, "2026-05-23"
        )

    assert exc_info.value.reason == "parse_error"
    assert exc_info.value.diagnostics["row_count"] == 0


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


@pytest.mark.parametrize(
    ("key", "url_fragment", "label", "unit", "value"),
    [
        ("GC=F", "/commodity/gold", "Gold", "$/oz", 4516.75),
        ("CL=F", "/commodity/crude-oil", "Crude Oil", "$/barrel", 97.0),
        ("BZ=F", "/commodity/brent-crude-oil", "Brent Crude Oil", "$/barrel", 103.94),
        ("HG=F", "/commodity/copper", "Copper", "$/lb", 6.345),
    ],
)
@pytest.mark.asyncio
async def test_trading_economics_provider_parses_commodity_chart_meta(
    key, url_fragment, label, unit, value
):
    html = (
        '<meta id="metaDesc" name="description" content="{label} traded at {value} '
        'on May 22, 2026." />'
        '<span id="p">999.00</span>'
        '<script>TEChartsMeta = [{{"last":{value},"value":{value},'
        '"name":"{label}","full_name":"{label}"}}];</script>'
        "<time>2026-05-22</time>"
    ).format(label=label, value=value)

    async def fetch_text(url, params=None):
        assert url_fragment in url
        return html

    provider = TradingEconomicsProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": key}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["category"] == "commodities"
    assert extraction["value"] == value
    assert extraction["unit"] == unit
    assert extraction["as_of_date"] == "2026-05-22"


@pytest.mark.asyncio
async def test_trading_economics_provider_uses_chart_meta_before_wrong_span():
    html = (
        '<meta id="metaDesc" name="description" content="Brent rose to 103.94 USD/Bbl '
        'on May 22, 2026." />'
        '<span id="p">97.00</span>'
        '<script>TEChartsMeta = [{"last":103.94,"value":103.94,'
        '"name":"Brent","full_name":"Brent Crude Oil"}];</script>'
        "<time>2026-05-22</time>"
    )

    async def fetch_text(url, params=None):
        return html

    provider = TradingEconomicsProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "BZ=F"}, {}, "2026-05-23")

    assert result.to_extraction()["value"] == 103.94


@pytest.mark.asyncio
async def test_trading_economics_provider_rejects_brent_meta_for_wti():
    html = (
        '<meta id="metaDesc" name="description" content="Crude Oil rose to 97 USD/Bbl '
        'on May 22, 2026." />'
        '<script>TEChartsMeta = ['
        '{"last":103.94,"value":103.94,"name":"Brent","full_name":"Brent Crude Oil"},'
        '{"last":97.0,"value":97.0,"name":"Crude Oil","full_name":"Crude Oil"}'
        "];</script>"
        "<time>2026-05-22</time>"
    )

    async def fetch_text(url, params=None):
        return html

    provider = TradingEconomicsProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "CL=F"}, {}, "2026-05-23")

    assert result.to_extraction()["value"] == 97.0


@pytest.mark.asyncio
async def test_trading_economics_provider_requires_brent_meta_for_brent():
    html = (
        '<meta id="metaDesc" name="description" content="Brent rose to 103.94 USD/Bbl '
        'on May 22, 2026." />'
        '<script>TEChartsMeta = ['
        '{"last":97.0,"value":97.0,"name":"Crude Oil","full_name":"Crude Oil"},'
        '{"last":103.94,"value":103.94,"name":"Brent","full_name":"Brent Crude Oil"}'
        "];</script>"
        "<time>2026-05-22</time>"
    )

    async def fetch_text(url, params=None):
        return html

    provider = TradingEconomicsProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "BZ=F"}, {}, "2026-05-23")

    assert result.to_extraction()["value"] == 103.94


@pytest.mark.asyncio
async def test_trading_economics_provider_parses_reserve_ratio_meta_description():
    html = (
        '<meta id="metaDesc" name="description" content="Cash Reserve Ratio in China '
        'remained unchanged at 7.50 percent in April." />'
        "<time>2026-04-30</time>"
    )

    async def fetch_text(url, params=None):
        assert "cash-reserve-ratio" in url
        return html

    provider = TradingEconomicsProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "reserve_ratio"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["category"] == "monetary_policy"
    assert extraction["value"] == 7.5
    assert extraction["unit"] == "%"


@pytest.mark.asyncio
async def test_trading_economics_provider_prefers_te_last_update_for_date():
    html = (
        '<meta id="metaDesc" name="description" content="Reverse Repo Rate in China '
        'remained unchanged at 1.40 percent in April." />'
        "<script>TELastUpdate = '20260430000000';</script>"
        "<time>2012-05-31</time>"
    )

    async def fetch_text(url, params=None):
        assert "reverse-repo-rate" in url
        return html

    provider = TradingEconomicsProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "reverse_repo"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == 1.4
    assert extraction["as_of_date"] == "2026-04-30"


@pytest.mark.asyncio
async def test_stooq_quote_provider_parses_gsg_csv_close():
    csv_text = (
        "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
        "GSG.US,2026-05-22,22:00:21,33.27,33.55,32.96,33.25,637017\n"
    )

    async def fetch_text(url, params=None):
        assert "stooq.com" in url
        return csv_text

    provider = StooqQuoteProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "GSG"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["category"] == "commodities"
    assert extraction["value"] == 33.25
    assert extraction["unit"] == "USD"
    assert extraction["as_of_date"] == "2026-05-22"
    assert extraction["source_tier"] == "tier2"


@pytest.mark.asyncio
async def test_stooq_provider_parses_gsg_csv_quote():
    await test_stooq_quote_provider_parses_gsg_csv_close()


@pytest.mark.asyncio
async def test_stooq_quote_provider_rejects_no_data_rows():
    async def fetch_text(url, params=None):
        return "Symbol,Date,Time,Open,High,Low,Close,Volume\nGSG.US,N/D,N/D,N/D,N/D,N/D,N/D,N/D\n"

    provider = StooqQuoteProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "GSG"}, {}, "2026-05-23")

    assert exc_info.value.reason == "missing_value"


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


@pytest.mark.asyncio
async def test_cdb_estimator_provider_uses_cn10y_proxy_plus_spread():
    provider = CDBEstimatorProvider()
    market_payload = {
        "bonds": [
            {
                "symbol": "CN10Y",
                "current_yield": 1.7484,
                "change_5d_bp": -1.01,
                "change_120d_bp": -10.62,
                "date": "2026-05-25",
                "source_url": "https://yield.chinabond.com.cn/cn10y",
            }
        ]
    }

    result = await provider.fetch(
        {"indicator_key": "CN10Y_CDB", "cdb_spread_bp": 10.0},
        market_payload,
        "2026-05-26",
    )

    extraction = result.to_extraction()
    assert result.provider == "cdb_estimator"
    assert result.source_url.startswith("https://yield.chinabond.com.cn/")
    assert extraction["value"] == pytest.approx(1.8484)
    assert extraction["current_yield"] == pytest.approx(1.8484)
    assert extraction["change_5d_bp"] == pytest.approx(-1.01)
    assert extraction["change_120d_bp"] == pytest.approx(-10.62)
    assert extraction["is_estimated"] is True
    assert extraction["estimation_method"] == "CN10Y plus observed CDB spread"
    assert extraction["metric_basis"] == "cn10y_proxy_plus_spread"
    assert "cn10y_proxy_change_basis" in extraction["estimation_basis"]
    assert extraction["diagnostics"]["spread_source"] == "task.cdb_spread_bp"
    assert "cn10y_proxy_change_basis" in extraction["diagnostics"]["estimation_basis"]


@pytest.mark.asyncio
async def test_cdb_estimator_provider_accepts_structured_metadata_spread():
    provider = CDBEstimatorProvider()
    market_payload = {
        "metadata": {
            "cn10y_cdb_spread": {
                "bp": 7.4,
                "source_url": "https://yield.chinabond.com.cn/cbweb-czb-web/czb/moreInfo?locale=cn_ZH&nameType=1",
                "observed_date": "2026-06-02",
                "note": "10Y CDB active bond yield about 1.774%; CN10Y 1.7036%",
            }
        },
        "bonds": [
            {
                "symbol": "CN10Y",
                "current_yield": 1.7036,
                "change_5d_bp": -3.69,
                "change_120d_bp": -19.86,
                "date": "2026-06-02",
                "source_url": "https://yield.chinabond.com.cn/cn10y",
            }
        ],
    }

    result = await provider.fetch({"indicator_key": "CN10Y_CDB"}, market_payload, "2026-06-03")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(1.7776)
    assert extraction["source_url"] == "https://yield.chinabond.com.cn/cbweb-czb-web/czb/moreInfo?locale=cn_ZH&nameType=1"
    assert extraction["diagnostics"]["spread_source"] == "metadata.cn10y_cdb_spread.bp"
    assert extraction["diagnostics"]["spread_source_url"] == "https://yield.chinabond.com.cn/cbweb-czb-web/czb/moreInfo?locale=cn_ZH&nameType=1"
    assert extraction["diagnostics"]["spread_observed_date"] == "2026-06-02"
    assert "structured_metadata_spread" in extraction["note"]


@pytest.mark.asyncio
async def test_cdb_estimator_provider_fails_without_explicit_spread():
    provider = build_cdb_estimator_provider()
    market_payload = {
        "bonds": [
            {
                "symbol": "CN10Y",
                "current_yield": 1.7484,
                "change_5d_bp": -1.01,
                "change_120d_bp": -10.62,
                "date": "2026-05-25",
            }
        ]
    }

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "CN10Y_CDB"}, market_payload, "2026-05-26")

    assert exc_info.value.reason == "missing_cdb_spread"
    assert "task.cdb_spread_bp" in exc_info.value.diagnostics["required_spread_fields"]
    assert "metadata.cn10y_cdb_spread.bp" in exc_info.value.diagnostics["required_spread_fields"]


@pytest.mark.asyncio
async def test_cdb_estimator_provider_fails_without_cn10y_proxy():
    provider = CDBEstimatorProvider(default_spread_bp=10.0)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "CN10Y_CDB"}, {"bonds": []}, "2026-05-26")

    assert exc_info.value.reason == "missing_cn10y_proxy"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cn10y_entry",
    [
        {"symbol": "CN10Y", "current_yield": 0},
        {"symbol": "CN10Y", "current_value": "0"},
    ],
)
async def test_cdb_estimator_provider_rejects_zero_cn10y_proxy(cn10y_entry):
    provider = CDBEstimatorProvider(default_spread_bp=10.0)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch(
            {"indicator_key": "CN10Y_CDB", "cdb_spread_bp": 10.0},
            {"bonds": [cn10y_entry]},
            "2026-05-26",
        )

    assert exc_info.value.reason == "invalid_cn10y_proxy"


@pytest.mark.asyncio
async def test_default_registry_orders_cdb_estimator_after_chinabond():
    provider_names = [
        provider.name
        for provider in build_default_registry().providers_for("CN10Y_CDB")
    ]

    assert provider_names[:2] == ["chinabond", "cdb_estimator"]


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
async def test_official_china_provider_follows_reverse_repo_list_detail():
    detail_url = (
        "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/"
        "125475/2026052208514823570/index.html"
    )
    list_html = (
        '<a href="./index.html">公开市场业务交易公告</a>'
        '<a href="./2026052208514823570/index.html">'
        "公开市场业务交易公告 [2026]第96号</a>"
    )
    detail_html = (
        '<meta name="Description" content="2026年5月22日中国人民银行以固定利率、'
        "数量招标方式开展了1530亿元7天期逆回购操作。"
        "逆回购操作情况期限操作利率投标量中标量7天1.40%1530亿元1530亿元"
        '">'
    )

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.REVERSE_REPO_URL:
            return list_html
        assert url == detail_url
        return detail_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "reverse_repo"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == 1.4
    assert extraction["operation_amount"] == 1530.0
    assert extraction["source_url"] == detail_url


@pytest.mark.asyncio
async def test_official_china_provider_selects_reverse_repo_detail_by_ref_date():
    old_url = (
        "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/"
        "125475/2026052108514823570/index.html"
    )
    target_url = (
        "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/"
        "125475/2026052208514823570/index.html"
    )
    list_html = (
        '<a href="./2026052108514823570/index.html">'
        "公开市场业务交易公告 [2026]第95号</a>"
        '<a href="./2026052208514823570/index.html">'
        "公开市场业务交易公告 [2026]第96号</a>"
    )
    target_html = (
        '<meta name="Description" content="2026年5月22日中国人民银行'
        "开展1530亿元7天期逆回购操作，中标利率1.40%。"
        '">'
    )

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.REVERSE_REPO_URL:
            return list_html
        assert url == target_url
        assert url != old_url
        return target_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch(
        {"indicator_key": "reverse_repo", "ref_date": "2026-05-22"},
        {},
        "2026-05-23",
    )

    extraction = result.to_extraction()
    assert extraction["value"] == 1.4
    assert extraction["as_of_date"] == "2026-05-22"
    assert extraction["source_url"] == target_url


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
    payload = {
        "data": {"head": ["USD/CNY"]},
        "records": [{"date": "2026-05-22", "values": ["7.1138"]}],
    }

    async def fetch_text(url, params=None):
        raise AssertionError("USDCNY should use the JSON API")

    async def fetch_json(url, params=None):
        assert url == OfficialChinaProvider.USDCNY_API_URL
        return payload

    provider = OfficialChinaProvider(fetch_text=fetch_text, fetch_json=fetch_json)
    result = await provider.fetch({"indicator_key": "USDCNY"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["category"] == "forex"
    assert extraction["value"] == 7.1138
    assert extraction["unit"] == "CNY"


@pytest.mark.asyncio
async def test_official_china_provider_parses_usdcny_json_by_head_name():
    payload = {
        "data": {
            "head": ["EUR/CNY", "USD/CNY"],
            "records": [
                {"date": "2026-05-22", "values": ["7.9193", "6.8373"]},
            ],
        }
    }

    async def fetch_text(url, params=None):
        raise AssertionError("USDCNY should use the JSON API")

    async def fetch_json(url, params=None):
        assert "CcprHisNew" in url
        return payload

    provider = OfficialChinaProvider(fetch_text=fetch_text, fetch_json=fetch_json)
    result = await provider.fetch({"indicator_key": "USDCNY"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == 6.8373
    assert extraction["as_of_date"] == "2026-05-22"


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
async def test_official_china_provider_follows_nbs_industrial_detail_and_prefers_month():
    detail_url = "https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963731.html"
    list_html = (
        '<a href="./202605/t20260518_1963731.html" '
        'title="2026年1—4月份规模以上工业增加值增长5.6%">'
        "2026年1—4月份规模以上工业增加值增长5.6%</a>"
    )
    detail_html = (
        "<title>2026年1—4月份规模以上工业增加值增长5.6%</title>"
        "1—4月份，规模以上工业增加值同比实际增长5.6%。"
        "4月份，规模以上工业增加值同比增长4.1%。"
    )

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.NBS_URL:
            return list_html
        assert url == detail_url
        return detail_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch(
        {"indicator_key": "industrial", "expected_period": "2026-04"},
        {},
        "2026-05-23",
    )

    extraction = result.to_extraction()
    assert extraction["value"] == 4.1
    assert extraction["yoy_month"] == 4.1
    assert extraction["source_url"] == detail_url


@pytest.mark.asyncio
async def test_official_china_provider_rejects_industrial_ytd_without_month_value():
    html = "2026年1—4月份，规模以上工业增加值同比实际增长5.6%。"

    async def fetch_text(url, params=None):
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch(
            {"indicator_key": "industrial", "expected_period": "2026-04"},
            {},
            "2026-05-23",
        )

    assert exc_info.value.reason == "missing_value"


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
async def test_official_china_provider_preserves_actual_negative_industrial_direction():
    html = "2026年4月份，工业增加值同比实际下降1.2%。"

    async def fetch_text(url, params=None):
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch(
        {"indicator_key": "industrial", "expected_period": "2026-04"},
        {},
        "2026-05-23",
    )

    extraction = result.to_extraction()
    assert extraction["value"] == -1.2
    assert extraction["yoy_month"] == -1.2
    assert extraction["report_period"] == "2026-04"


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
async def test_official_china_provider_does_not_treat_rrr_delta_as_current_level():
    html = "中国人民银行决定下调金融机构存款准备金率0.5个百分点。"

    async def fetch_text(url, params=None):
        return html

    provider = OfficialChinaProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "reserve_ratio"}, {}, "2026-05-23")

    assert exc_info.value.reason == "missing_value"


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
async def test_official_china_provider_follows_nbs_industrial_sales_paginated_detail():
    first_page = '<a href="./202605/t20260518_1963731.html">规模以上工业增加值</a>'
    second_page = (
        '<a href="./202604/t20260427_1963001.html" '
        'title="2026年1—3月份全国规模以上工业企业利润增长15.5%">'
        "2026年1—3月份全国规模以上工业企业利润增长15.5%</a>"
    )
    detail_url = "https://www.stats.gov.cn/sj/zxfb/202604/t20260427_1963001.html"
    detail_html = (
        "<title>2026年1—3月份全国规模以上工业企业利润增长15.5%</title>"
        "1—3月份，规模以上工业企业营业收入同比增长4.5%。"
    )

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.NBS_URL:
            return first_page
        if url == "https://www.stats.gov.cn/sj/zxfb/index_1.html":
            return second_page
        assert url == detail_url
        return detail_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "industrial_sales"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert extraction["value"] == 4.5
    assert extraction["yoy_ytd"] == 4.5
    assert extraction["report_period"] == "2026-03"
    assert extraction["source_url"] == detail_url


@pytest.mark.asyncio
async def test_official_china_provider_returns_mlf_multi_price_reference_result():
    list_html = (
        '<a href="./2026052217453752767/index.html">'
        "2026年5月中期借贷便利招标公告</a>"
    )
    detail_html = "开展6000亿元中期借贷便利（MLF）操作，固定数量、利率招标、多重价位中标方式。"

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.MLF_URL:
            return list_html
        return detail_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "mlf", "ref_date": "2026-05-23"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.provider == "official_china"
    assert result.source_url.startswith("https://www.pbc.gov.cn/")
    assert extraction["value"] == 2.0
    assert extraction["unit"] == "%"
    assert extraction["is_estimated"] is False
    assert extraction["change_from_120d"] == 0.0
    assert "多重价位" in extraction["manual_reason"]
    assert "参考值" in extraction["manual_reason"]
    assert "展示参考值" in extraction["diagnostics"]["note"]


@pytest.mark.asyncio
async def test_official_china_provider_rejects_mlf_interest_rate_tender_without_multi_price_marker():
    list_html = (
        '<a href="./2026052217453752767/index.html">'
        "2026年5月中期借贷便利招标公告</a>"
    )
    detail_html = "开展6000亿元中期借贷便利（MLF）操作，固定数量、利率招标方式。"

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.MLF_URL:
            return list_html
        return detail_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "mlf", "ref_date": "2026-05-23"}, {}, "2026-05-23")

    assert exc_info.value.reason == "missing_value"


@pytest.mark.asyncio
async def test_official_china_provider_rejects_mlf_multi_price_non_pbc_source_url():
    list_html = (
        '<a href="https://news.example.com/2026052217453752767/index.html">'
        "2026年5月中期借贷便利招标公告</a>"
    )
    detail_html = "2026年5月15日开展6000亿元中期借贷便利（MLF）操作，固定数量、利率招标、多重价位中标方式。"

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.MLF_URL:
            return list_html
        return detail_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "mlf", "ref_date": "2026-05-23"}, {}, "2026-05-23")

    assert exc_info.value.reason == "untrusted_source_url"


@pytest.mark.asyncio
async def test_official_china_provider_rejects_mlf_multi_price_rate_from_non_pbc_source_url():
    list_html = (
        '<a href="https://news.example.com/2026052217453752767/index.html">'
        "2026年5月中期借贷便利招标公告</a>"
    )
    detail_html = (
        "2026年5月15日开展6000亿元中期借贷便利（MLF）操作，"
        "固定数量、利率招标、多重价位中标方式，中标利率2.00%。"
    )

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.MLF_URL:
            return list_html
        return detail_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "mlf", "ref_date": "2026-05-23"}, {}, "2026-05-23")

    assert exc_info.value.reason == "untrusted_source_url"


@pytest.mark.asyncio
async def test_official_china_provider_rejects_mlf_multi_price_wrong_month():
    list_html = (
        '<a href="./2026052217453752767/index.html">'
        "2026年5月中期借贷便利招标公告</a>"
    )
    detail_html = "开展6000亿元中期借贷便利（MLF）操作，固定数量、利率招标、多重价位中标方式。"

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.MLF_URL:
            return list_html
        return detail_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "mlf", "ref_date": "2026-06-03"}, {}, "2026-06-03")

    assert exc_info.value.reason == "period_mismatch"


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
