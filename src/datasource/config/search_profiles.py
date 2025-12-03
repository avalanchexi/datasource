#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Search Profiles
---------------
指标 → Tavily 查询模板与可信域名映射。
"""

from __future__ import annotations

from typing import Dict, List

SearchProfile = Dict[str, object]


def _profile(
    query: str,
    domains: List[str],
    time_range: str = "year",
    unit: str = "",
    issuer: str = "",
    issuer_aliases: List[str] | None = None,
    max_age_days: int | None = None,
    language: str | None = None,
    topic: str | None = None,
    max_results: int | None = None,
    search_depth: str | None = None,
    chunks_per_source: int | None = None,
    auto_parameters: bool | None = None,
) -> SearchProfile:
    return {
        "query": query,
        "preferred_domains": domains,
        "time_range": time_range,
        "unit": unit,
        "issuer": issuer,
        "issuer_aliases": issuer_aliases or [],
        "max_age_days": max_age_days,
        "language": language,
        "topic": topic,
        "max_results": max_results,
        "search_depth": search_depth,
        "chunks_per_source": chunks_per_source,
        "auto_parameters": auto_parameters,
    }


SEARCH_PROFILES: Dict[str, SearchProfile] = {
    # 大宗商品
    "GC=F": _profile("COMEX 黄金 最新 价格 现货 期货", ["reuters.com", "bloomberg.com", "investing.com"], time_range="day", unit="$/oz", issuer="COMEX/CME", issuer_aliases=["CME", "COMEX"], max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "CL=F": _profile("WTI 原油 期货 最新 价格", ["reuters.com", "bloomberg.com", "investing.com"], time_range="day", unit="$/barrel", issuer="NYMEX/CME", issuer_aliases=["NYMEX", "CME"], max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "BZ=F": _profile("Brent 原油 期货 最新 价格", ["reuters.com", "bloomberg.com", "investing.com"], time_range="day", unit="$/barrel", issuer="ICE", issuer_aliases=["ICE", "ICE Futures Europe"], max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "HG=F": _profile("COMEX 铜 期货 最新 价格", ["reuters.com", "bloomberg.com", "investing.com"], time_range="day", unit="$/lb", issuer="COMEX/CME", issuer_aliases=["COMEX", "CME"], max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "BCOM": _profile("彭博 大宗商品 指数 最新 点位", ["bloomberg.com", "ft.com", "tradingeconomics.com"], time_range="day", unit="点", issuer="Bloomberg", issuer_aliases=["Bloomberg"], max_age_days=3, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "GSG": _profile("GSG 大宗商品 ETF 最新 价格", ["ishares.com", "ft.com", "investing.com"], time_range="day", unit="USD", issuer="iShares/BlackRock", issuer_aliases=["BlackRock", "iShares"], max_age_days=3, language="chinese", topic="news", max_results=8, search_depth="advanced"),

    # 汇率
    "USDCNY": _profile("美元 人民币 在岸 汇率 最新 报价", ["reuters.com", "bloomberg.com", "tradingeconomics.com", "wise.com"], time_range="day", unit="USD/CNY", issuer="SAFE/在岸即期", issuer_aliases=["SAFE", "China FX", "中国外汇交易中心", "CFETS"], max_age_days=1, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "USDCNH": _profile("美元 离岸人民币 汇率 最新 报价", ["reuters.com", "bloomberg.com", "tradingeconomics.com", "wise.com"], time_range="day", unit="USD/CNH", issuer="CFETS/离岸市场", issuer_aliases=["CFETS", "HKEX"], max_age_days=1, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "DXY": _profile("美元 指数 最新 点位", ["marketwatch.com", "investing.com", "fred.stlouisfed.org"], time_range="day", unit="点", issuer="ICE", issuer_aliases=["ICE", "Intercontinental Exchange"], max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),

    # 债券
    "US10Y": _profile("美国10年期 国债 收益率 最新", ["reuters.com", "marketwatch.com", "tradingeconomics.com", "fred.stlouisfed.org"], time_range="day", unit="%", issuer="US Treasury/FRED", issuer_aliases=["U.S. Treasury", "FRED", "Federal Reserve"], max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "CN10Y": _profile("中国10年期 国债 收益率 最新", ["chinabond.com.cn", "tradingeconomics.com", "reuters.com"], time_range="day", unit="%", issuer="中债估值", issuer_aliases=["中债", "CCDC", "ChinaBond"], max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "CN10Y_CDB": _profile("中国10年期 国开债 收益率 最新", ["chinabond.com.cn", "tradingeconomics.com", "reuters.com"], time_range="day", unit="%", issuer="中债估值/国开行", issuer_aliases=["中债", "CCDC", "CDB"], max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),

    # 指数（补齐日志警告项）
    "000016": _profile("上证50 指数 最新 点位 收盘 价格", ["sse.com.cn", "eastmoney.com", "reuters.com"], time_range="day", unit="点", issuer="上交所", max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "000300": _profile("沪深300 指数 最新 点位 收盘 价格", ["sse.com.cn", "eastmoney.com", "reuters.com"], time_range="day", unit="点", issuer="中证指数公司", max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "399001": _profile("深证成指 最新 收盘价 点位", ["szse.cn", "eastmoney.com", "reuters.com"], time_range="day", unit="点", issuer="深交所", max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "399006": _profile("创业板指 最新 收盘价 点位", ["szse.cn", "eastmoney.com", "reuters.com"], time_range="day", unit="点", issuer="深交所", max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "000001": _profile("上证指数 最新 收盘价 点位", ["sse.com.cn", "eastmoney.com", "reuters.com"], time_range="day", unit="点", issuer="上交所", max_age_days=2, language="chinese", topic="news", max_results=8, search_depth="advanced"),

    # 资金流向
    "northbound": _profile("北向资金 净流入 近5日 120日", ["eastmoney.com", "jrj.com.cn", "hkex.com.hk"], time_range="day", unit="亿", issuer="沪深交易所/港交所", issuer_aliases=["沪股通", "深股通", "港交所", "HKEX"], max_age_days=1, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "southbound": _profile("南向资金 净流入 近5日 120日", ["eastmoney.com", "jrj.com.cn", "hkex.com.hk"], time_range="day", unit="亿", issuer="沪深交易所/港交所", issuer_aliases=["港股通", "港交所", "HKEX"], max_age_days=1, language="chinese", topic="news", max_results=8, search_depth="advanced"),
    "etf": _profile("A股 ETF 资金流 申购赎回 近5日 120日", ["eastmoney.com", "fund.eastmoney.com", "sse.com.cn", "szse.cn"], time_range="day", unit="亿", issuer="沪深交易所", issuer_aliases=["ETF", "交易所"], max_age_days=1, language="chinese", topic="news", max_results=8, search_depth="advanced"),

    # 宏观与货币
    "cpi": _profile("中国 CPI 最新公布 数据", ["stats.gov.cn", "ceicdata.com", "wind.com.cn"], time_range="year", unit="%", issuer="国家统计局", language="chinese", max_results=6, search_depth="basic"),
    "ppi": _profile("中国 PPI 最新公布 数据", ["stats.gov.cn", "ceicdata.com"], time_range="year", unit="%", issuer="国家统计局", language="chinese", max_results=6, search_depth="basic"),
    "pmi": _profile("中国 PMI 官方 最新数据", ["stats.gov.cn", "caixin.com"], time_range="year", unit="点", issuer="国家统计局", language="chinese", max_results=6, search_depth="basic"),
    "pmi_new_orders": _profile("中国 PMI 新订单 指数 最新", ["stats.gov.cn", "caixin.com"], time_range="year", unit="点", issuer="国家统计局", language="chinese", max_results=6, search_depth="basic"),
    "m1": _profile("中国 M1 货币供应量 最新值", ["pbc.gov.cn", "ceicdata.com"], time_range="year", unit="%", issuer="中国人民银行", language="chinese", max_results=6, search_depth="basic"),
    "m2": _profile("中国 M2 货币供应量 最新值", ["pbc.gov.cn", "ceicdata.com"], time_range="year", unit="%", issuer="中国人民银行", language="chinese", max_results=6, search_depth="basic"),
    "dr007": _profile("DR007 最新利率", ["chinamoney.com.cn", "wind.com.cn", "jlwsss.com"], time_range="month", unit="%", issuer="中国货币网", language="chinese", max_results=6, search_depth="basic"),
    "reverse_repo": _profile("中国 7天 逆回购 最新中标利率", ["pbc.gov.cn", "chinamoney.com.cn"], time_range="year", unit="%", issuer="中国人民银行", language="chinese", max_results=6, search_depth="basic"),
    "reverse_repo_7d": _profile("中国 7天 逆回购 最新中标利率", ["pbc.gov.cn", "chinamoney.com.cn"], time_range="year", unit="%", issuer="中国人民银行", language="chinese", max_results=6, search_depth="basic"),
    "rrr": _profile("中国 存款准备金率 最新 调整", ["pbc.gov.cn", "reuters.com", "xinhuanet.com"], time_range="year", unit="%", issuer="中国人民银行", language="chinese", max_results=6, search_depth="basic"),
    "mlf": _profile("中国 MLF 1年期 利率 最新 中标利率", ["pbc.gov.cn", "reuters.com", "chinamoney.com.cn"], time_range="year", unit="%", issuer="中国人民银行", language="chinese", max_results=6, search_depth="basic"),
    "gdp": _profile("中国 GDP 最新公布 季度", ["stats.gov.cn", "ceicdata.com"], time_range="year", unit="%", issuer="国家统计局", language="chinese", max_results=6, search_depth="basic"),
    "industrial_output": _profile("中国 规模以上 工业增加值 最新 同比", ["stats.gov.cn"], time_range="year", unit="%", issuer="国家统计局", language="chinese", max_results=6, search_depth="basic"),
    "industrial": _profile("中国 工业增加值 最新 同比 数据", ["stats.gov.cn", "ceicdata.com"], time_range="year", unit="%", issuer="国家统计局", language="chinese", max_results=6, search_depth="basic"),
    "industrial_sales": _profile("规模以上工业企业 营业收入 最新 同比 数据", ["stats.gov.cn", "ceicdata.com"], time_range="year", unit="%", issuer="国家统计局", language="chinese", max_results=6, search_depth="basic"),
    "bdi": _profile("BDI Baltic Dry Index 最新 点位", ["balticexchange.com", "tradingeconomics.com", "markets.businessinsider.com"], time_range="month", unit="点", issuer="Baltic Exchange", language="chinese", max_results=6, search_depth="basic"),
    "m1_m2_spread": _profile("M1 M2 剪刀差 最新", ["pbc.gov.cn"], time_range="year", unit="个百分点", language="chinese", max_results=6, search_depth="basic"),
    "commodity_trend": _profile("大宗商品 指数 走势 最新", ["bloomberg.com", "reuters.com"], time_range="month", language="chinese", max_results=6, search_depth="basic"),
}


__all__ = ["SEARCH_PROFILES"]
