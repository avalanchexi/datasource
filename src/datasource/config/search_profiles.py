#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Search Profiles
---------------
指标 → Tavily 查询模板与可信域名映射。

优化原则：
1. 实时类数据（商品/汇率/债券/资金流向）: time_range="day", search_depth="advanced", max_results=8
2. 宏观类数据（CPI/PPI/PMI等）: time_range="month", search_depth="basic", max_results=6
3. 查询语句包含具体时间限定词提高准确性
4. preferred_domains 优先使用官方/权威数据源
"""

from __future__ import annotations

from typing import Dict, List

SearchProfile = Dict[str, object]


def _profile(
    query: str,
    domains: List[str],
    time_range: str = "month",
    unit: str = "",
    issuer: str = "",
    issuer_aliases: List[str] | None = None,
    max_age_days: int | None = None,
    language: str = "chinese",
    topic: str = "news",
    max_results: int = 6,
    search_depth: str = "basic",
    chunks_per_source: int | None = None,
    auto_parameters: bool | None = None,
    days: int | None = None,
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
        "days": days,
    }


# ========== 实时类数据通用配置 ==========
_REALTIME_DEFAULTS = {
    "time_range": "day",
    "max_results": 8,
    "search_depth": "advanced",
    "language": "chinese",
    "topic": "news",
    # Tavily 最佳实践：news 主题传递 days 可用发布日期过滤，减少过期结果
    "days": 2,
    # 让 Tavily 自动微调参数（例如是否包含爬取、分页等），显式参数优先生效
    "auto_parameters": True,
}

# ========== 宏观类数据通用配置 ==========
_MACRO_DEFAULTS = {
    "time_range": "month",
    "max_results": 6,
    "search_depth": "basic",
    "language": "chinese",
    "topic": "news",
}


SEARCH_PROFILES: Dict[str, SearchProfile] = {
    # ==================== 大宗商品（实时） ====================
    "GC=F": _profile(
        query="COMEX黄金期货 最新价格 今日收盘 美元/盎司",
        domains=["investing.com", "jin10.com", "eastmoney.com", "reuters.com"],
        unit="$/oz",
        issuer="COMEX/CME",
        issuer_aliases=["CME", "COMEX", "芝商所"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),
    "CL=F": _profile(
        query="WTI原油期货 最新价格 今日收盘 美元/桶",
        domains=["investing.com", "jin10.com", "eastmoney.com", "reuters.com"],
        unit="$/barrel",
        issuer="NYMEX/CME",
        issuer_aliases=["NYMEX", "CME", "纽约商品交易所"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),
    "BZ=F": _profile(
        query="布伦特原油期货 最新价格 今日收盘 美元/桶",
        domains=["investing.com", "jin10.com", "eastmoney.com", "reuters.com"],
        unit="$/barrel",
        issuer="ICE",
        issuer_aliases=["ICE", "洲际交易所"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),
    "HG=F": _profile(
        query="COMEX铜期货 最新价格 今日收盘 美元/磅",
        domains=["investing.com", "jin10.com", "eastmoney.com", "reuters.com"],
        unit="$/lb",
        issuer="COMEX/CME",
        issuer_aliases=["COMEX", "CME", "芝商所"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),
    "BCOM": _profile(
        query="彭博商品指数 BCOM 最新点位 今日",
        domains=["bloomberg.com", "tradingeconomics.com", "investing.com"],
        unit="点",
        issuer="Bloomberg",
        issuer_aliases=["彭博"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),
    "GSG": _profile(
        query="iShares GSG商品ETF 最新价格 今日",
        domains=["ishares.com", "investing.com", "finance.yahoo.com"],
        unit="USD",
        issuer="iShares/BlackRock",
        issuer_aliases=["BlackRock", "贝莱德"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),

    # ==================== 汇率（实时） ====================
    "USDCNY": _profile(
        query="美元人民币 在岸汇率 USDCNY 今日 最新报价 中间价",
        domains=["eastmoney.com", "investing.com", "chinamoney.com.cn", "cfets.com.cn"],
        unit="CNY",
        issuer="中国外汇交易中心",
        issuer_aliases=["CFETS", "外汇交易中心", "SAFE"],
        max_age_days=1,
        **_REALTIME_DEFAULTS,
    ),
    "USDCNH": _profile(
        query="美元离岸人民币 汇率 USDCNH 今日 最新报价",
        domains=["eastmoney.com", "investing.com", "hkex.com.hk", "reuters.com"],
        unit="CNH",
        issuer="离岸市场",
        issuer_aliases=["HKEX", "港交所"],
        max_age_days=1,
        **_REALTIME_DEFAULTS,
    ),
    "DXY": _profile(
        query="美元指数 DXY 今日 最新点位",
        domains=["investing.com", "tradingeconomics.com", "marketwatch.com", "eastmoney.com", "jin10.com"],
        unit="点",
        issuer="ICE",
        issuer_aliases=["Intercontinental Exchange", "洲际交易所"],
        max_age_days=2,
        **_REALTIME_DEFAULTS,
    ),

    # ==================== 债券收益率（实时） ====================
    "US10Y": _profile(
        query="美国10年期国债收益率 今日 最新",
        domains=["investing.com", "tradingeconomics.com", "cn.reuters.com", "eastmoney.com"],
        unit="%",
        issuer="美国财政部",
        issuer_aliases=["U.S. Treasury", "FRED", "美联储"],
        max_age_days=2,
        **_REALTIME_DEFAULTS,
    ),
    "CN10Y": _profile(
        query="中国10年期国债收益率 今日 最新 中债估值",
        domains=["chinabond.com.cn", "eastmoney.com", "investing.com", "chinamoney.com.cn", "cfets.com.cn"],
        unit="%",
        issuer="中债估值中心",
        issuer_aliases=["中债", "CCDC", "中央国债登记结算公司"],
        max_age_days=2,
        **_REALTIME_DEFAULTS,
    ),
    "CN10Y_CDB": _profile(
        query="中国10年期国开债收益率 今日 最新 中债估值",
        domains=["chinabond.com.cn", "eastmoney.com", "chinamoney.com.cn", "cfets.com.cn"],
        unit="%",
        issuer="国家开发银行",
        issuer_aliases=["中债", "CCDC", "CDB", "国开行"],
        max_age_days=2,
        **_REALTIME_DEFAULTS,
    ),

    # ==================== A股指数（实时） ====================
    "000001": _profile(
        query="上证指数 今日收盘 最新点位",
        domains=["eastmoney.com", "sse.com.cn", "sina.com.cn"],
        unit="点",
        issuer="上海证券交易所",
        issuer_aliases=["上交所", "SSE"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),
    "000016": _profile(
        query="上证50指数 今日收盘 最新点位",
        domains=["eastmoney.com", "sse.com.cn", "sina.com.cn"],
        unit="点",
        issuer="上海证券交易所",
        issuer_aliases=["上交所", "SSE"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),
    "000300": _profile(
        query="沪深300指数 今日收盘 最新点位",
        domains=["eastmoney.com", "csindex.com.cn", "sina.com.cn"],
        unit="点",
        issuer="中证指数公司",
        issuer_aliases=["CSI", "中证"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),
    "399001": _profile(
        query="深证成指 今日收盘 最新点位",
        domains=["eastmoney.com", "szse.cn", "sina.com.cn"],
        unit="点",
        issuer="深圳证券交易所",
        issuer_aliases=["深交所", "SZSE"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),
    "399006": _profile(
        query="创业板指 今日收盘 最新点位",
        domains=["eastmoney.com", "szse.cn", "sina.com.cn"],
        unit="点",
        issuer="深圳证券交易所",
        issuer_aliases=["深交所", "SZSE"],
        max_age_days=3,
        **_REALTIME_DEFAULTS,
    ),

    # ==================== 资金流向（实时，Tavily优先） ====================
    "northbound": _profile(
        query="北向资金 今日净流入 近5日净流入 沪股通 深股通 东方财富",
        domains=["eastmoney.com", "data.eastmoney.com", "10jqka.com.cn", "cls.cn", "cs.com.cn"],
        unit="亿元",
        issuer="沪深港通",
        issuer_aliases=["沪股通", "深股通", "港交所", "HKEX"],
        max_age_days=1,
        time_range="day",
        search_depth="advanced",
        max_results=6,
        language="chinese",
        topic="news",
        days=1,
        auto_parameters=False,
        chunks_per_source=3,
    ),
    "southbound": _profile(
        query="南向资金 今日净流入 近5日净流入 港股通 东方财富",
        domains=["eastmoney.com", "data.eastmoney.com", "10jqka.com.cn", "cls.cn", "cs.com.cn"],
        unit="亿港元",
        issuer="港股通",
        issuer_aliases=["港股通", "港交所", "HKEX"],
        max_age_days=1,
        time_range="day",
        search_depth="advanced",
        max_results=6,
        language="chinese",
        topic="news",
        days=1,
        auto_parameters=False,
        chunks_per_source=3,
    ),
    "etf": _profile(
        query="A股ETF资金流向 今日净申购 近5日净申购 东方财富",
        domains=["eastmoney.com", "data.eastmoney.com", "fund.eastmoney.com", "10jqka.com.cn"],
        unit="亿元",
        issuer="沪深交易所",
        issuer_aliases=["ETF", "交易所"],
        max_age_days=1,
        time_range="day",
        search_depth="advanced",
        max_results=6,
        language="chinese",
        topic="news",
        days=1,
        auto_parameters=False,
        chunks_per_source=3,
    ),
    "margin": _profile(
        query="融资融券余额 今日 近5日变化 沪深两市 东方财富",
        domains=["eastmoney.com", "data.eastmoney.com", "sse.com.cn", "szse.cn", "10jqka.com.cn"],
        unit="亿元",
        issuer="沪深交易所",
        issuer_aliases=["融资融券", "两融"],
        max_age_days=1,
        time_range="day",
        search_depth="advanced",
        max_results=6,
        language="chinese",
        topic="news",
        days=1,
        auto_parameters=False,
        chunks_per_source=3,
    ),

    # ==================== 宏观指标（月度/季度发布） ====================
    "cpi": _profile(
        query="中国CPI 居民消费价格指数 最新公布 同比 国家统计局",
        domains=["stats.gov.cn", "eastmoney.com", "10jqka.com.cn", "cls.cn"],
        unit="%",
        issuer="国家统计局",
        issuer_aliases=["统计局", "NBS"],
        max_age_days=45,
        **_MACRO_DEFAULTS,
    ),
    "ppi": _profile(
        query="中国PPI 工业生产者出厂价格指数 最新公布 同比 国家统计局",
        domains=["stats.gov.cn", "eastmoney.com", "10jqka.com.cn", "cls.cn"],
        unit="%",
        issuer="国家统计局",
        issuer_aliases=["统计局", "NBS"],
        max_age_days=45,
        **_MACRO_DEFAULTS,
    ),
    "pmi": _profile(
        query="中国制造业PMI 采购经理指数 最新公布 国家统计局",
        domains=["stats.gov.cn", "eastmoney.com", "caixin.com", "cls.cn"],
        unit="点",
        issuer="国家统计局",
        issuer_aliases=["统计局", "NBS"],
        max_age_days=35,
        **_MACRO_DEFAULTS,
    ),
    "pmi_new_orders": _profile(
        query="中国PMI新订单指数 最新公布 国家统计局",
        domains=["stats.gov.cn", "eastmoney.com", "caixin.com"],
        unit="点",
        issuer="国家统计局",
        issuer_aliases=["统计局", "NBS"],
        max_age_days=35,
        **_MACRO_DEFAULTS,
    ),
    "industrial": _profile(
        query="中国工业增加值 规模以上 最新同比增速 国家统计局",
        domains=["stats.gov.cn", "eastmoney.com", "10jqka.com.cn"],
        unit="%",
        issuer="国家统计局",
        issuer_aliases=["统计局", "NBS"],
        max_age_days=45,
        **_MACRO_DEFAULTS,
    ),
    "industrial_sales": _profile(
        query="规模以上工业企业 营业收入 同比 最新 数据 国家统计局",
        domains=["stats.gov.cn", "ce.cn", "eastmoney.com", "people.com.cn", "10jqka.com.cn"],
        unit="%",
        issuer="国家统计局",
        issuer_aliases=["统计局", "NBS"],
        max_age_days=150,
        max_results=6,
        search_depth="basic",
        language="chinese",
        auto_parameters=True,
    ),
    "bdi": _profile(
        query="波罗的海干散货指数 BDI 最新点位",
        domains=["tradingeconomics.com", "investing.com", "eastmoney.com", "balticexchange.com"],
        unit="点",
        issuer="波罗的海交易所",
        issuer_aliases=["Baltic Exchange"],
        max_age_days=7,
        auto_parameters=False,
        **_MACRO_DEFAULTS,
    ),
    "gdp": _profile(
        query="中国GDP 季度增速 最新公布 国家统计局",
        domains=["stats.gov.cn", "eastmoney.com", "cls.cn"],
        unit="%",
        issuer="国家统计局",
        issuer_aliases=["统计局", "NBS"],
        max_age_days=120,
        time_range="quarter",
        max_results=6,
        search_depth="basic",
        language="chinese",
        topic="news",
    ),

    # ==================== 货币政策指标 ====================
    "rrr": _profile(
        query="中国央行存款准备金率 最新调整 降准 人民银行公告",
        domains=["pbc.gov.cn", "eastmoney.com", "cls.cn", "xinhuanet.com"],
        unit="%",
        issuer="中国人民银行",
        issuer_aliases=["央行", "PBOC", "人行"],
        max_age_days=90,
        auto_parameters=False,
        **_MACRO_DEFAULTS,
    ),
    "reverse_repo": _profile(
        query="中国央行7天逆回购 中标利率 最新 人民银行公开市场操作",
        domains=["pbc.gov.cn", "chinamoney.com.cn", "eastmoney.com", "cls.cn"],
        unit="%",
        issuer="中国人民银行",
        issuer_aliases=["央行", "PBOC", "人行"],
        max_age_days=7,
        auto_parameters=False,
        **_MACRO_DEFAULTS,
    ),
    "mlf": _profile(
        query="中国央行MLF 中期借贷便利 1年期利率 最新 人民银行公告",
        domains=["pbc.gov.cn", "chinamoney.com.cn", "eastmoney.com", "cls.cn"],
        unit="%",
        issuer="中国人民银行",
        issuer_aliases=["央行", "PBOC", "人行"],
        max_age_days=45,
        auto_parameters=False,
        **_MACRO_DEFAULTS,
    ),
    "tsf": _profile(
        query="社会融资规模 增量 存量增速 最新 人民银行",
        domains=["pbc.gov.cn", "eastmoney.com", "cls.cn", "10jqka.com.cn"],
        unit="%",
        issuer="中国人民银行",
        issuer_aliases=["央行", "PBOC", "社融"],
        max_age_days=45,
        **_MACRO_DEFAULTS,
    ),
    "m1": _profile(
        query="中国M1 狭义货币供应量 同比增速 最新 人民银行",
        domains=["pbc.gov.cn", "eastmoney.com", "cls.cn"],
        unit="%",
        issuer="中国人民银行",
        issuer_aliases=["央行", "PBOC"],
        max_age_days=45,
        **_MACRO_DEFAULTS,
    ),
    "m2": _profile(
        query="中国M2 广义货币供应量 同比增速 最新 人民银行",
        domains=["pbc.gov.cn", "eastmoney.com", "cls.cn"],
        unit="%",
        issuer="中国人民银行",
        issuer_aliases=["央行", "PBOC"],
        max_age_days=45,
        **_MACRO_DEFAULTS,
    ),
    "dr007": _profile(
        query="DR007 银行间质押式回购利率 最新 中国货币网",
        domains=["chinamoney.com.cn", "eastmoney.com", "cls.cn"],
        unit="%",
        issuer="中国货币网",
        issuer_aliases=["CFETS", "货币网"],
        max_age_days=3,
        **_MACRO_DEFAULTS,
    ),

    # ==================== 派生/辅助指标 ====================
    "m1_m2_spread": _profile(
        query="M1 M2 剪刀差 增速差 最新",
        domains=["pbc.gov.cn", "eastmoney.com", "cls.cn"],
        unit="个百分点",
        issuer="中国人民银行",
        max_age_days=45,
        **_MACRO_DEFAULTS,
    ),
    "commodity_trend": _profile(
        query="大宗商品指数 走势 最新 综述",
        domains=["eastmoney.com", "investing.com", "cls.cn"],
        unit="",
        issuer="",
        max_age_days=7,
        **_MACRO_DEFAULTS,
    ),
}


__all__ = ["SEARCH_PROFILES"]
