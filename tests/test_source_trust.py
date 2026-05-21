from datasource.utils.source_trust import (
    is_official_source_url,
    should_mark_official_non_estimated,
    source_url_in_snippets,
)


def test_official_domains_and_subdomains_are_trusted():
    assert is_official_source_url("https://www.stats.gov.cn/sj/zxfb/202605/t20260509.html")
    assert is_official_source_url("https://data.stats.gov.cn/easyquery.htm")
    assert is_official_source_url("https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html")
    assert is_official_source_url("https://sub.cfets.com.cn/marketdata")
    assert is_official_source_url("https://www.hkex.com.hk/Market-Data")

    assert not is_official_source_url("https://finance.sina.com.cn/china/2026-05-09/doc.html")
    assert not is_official_source_url("https://stats.gov.cn.evil.example/report")


def test_source_url_in_snippets_ignores_query_fragment_and_case():
    source_url = "https://WWW.STATS.GOV.CN/sj/zxfb/202605/t20260509.html?from=tavily#top"
    snippets = [
        {
            "url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260509.html",
            "snippet": "2026年4月份居民消费价格同比上涨0.2%",
        }
    ]

    assert source_url_in_snippets(source_url, snippets)


def test_official_source_decision_requires_period_and_unit_match():
    task = {
        "category": "macro_indicators",
        "indicator_key": "cpi",
        "expected_period": "2026-04",
        "unit": "%",
    }
    extraction = {
        "value": 0.2,
        "unit": "%",
        "report_period": "2026-04",
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260509.html",
    }
    snippets = [{"url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260509.html?utm=1"}]

    decision = should_mark_official_non_estimated(task, extraction, snippets)
    assert decision.allowed is True
    assert decision.reason == "official_source_period_unit_match"

    period_mismatch = dict(extraction, report_period="2026-03")
    decision = should_mark_official_non_estimated(task, period_mismatch, snippets)
    assert decision.allowed is False
    assert decision.reason == "period_mismatch"

    unit_mismatch = dict(extraction, unit="点")
    decision = should_mark_official_non_estimated(task, unit_mismatch, snippets)
    assert decision.allowed is False
    assert decision.reason == "unit_mismatch"


def test_fund_flow_is_rejected_for_separate_window_gate():
    task = {
        "category": "fund_flow",
        "indicator_key": "northbound",
        "expected_period": "2026-05-21",
        "unit": "亿元",
    }
    extraction = {
        "value": 100.0,
        "unit": "亿元",
        "report_period": "2026-05-21",
        "source_url": "https://www.hkex.com.hk/Market-Data/Stock-Connect",
    }
    snippets = [{"url": "https://www.hkex.com.hk/Market-Data/Stock-Connect"}]

    decision = should_mark_official_non_estimated(task, extraction, snippets)

    assert decision.allowed is False
    assert decision.reason == "fund_flow_requires_window_gate"
