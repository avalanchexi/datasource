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

from typing import Any, Dict, List

SearchProfile = Dict[str, object]


def _dedupe_preserve(items: List[str] | None) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items or []:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result

# ========== 键名别名映射 ==========
# 解决 Stage2 输出键名与注入脚本/search_profiles 不一致的问题
# 规范化方向：注入脚本中的键名 → Stage2/search_profiles 中的键名
KEY_ALIASES: Dict[str, str] = {
    # 宏观指标
    "industrial_production": "industrial",  # 注入脚本 → Stage2
    "industrial": "industrial",             # 自身映射（规范键名）
    # 货币政策
    "rrr": "reserve_ratio",
    "reserve_ratio": "reserve_ratio",
    "reverse_repo_7d": "reverse_repo",
    "reverse_repo": "reverse_repo",
    "mlf": "mlf_rate",
    "mlf_rate": "mlf_rate",
}


def get_canonical_key(key: str) -> str:
    """获取规范化的键名，用于跨模块一致性"""
    return KEY_ALIASES.get(key, key)


def _profile(
    query: str,
    domains: List[str],
    time_range: str = "month",
    unit: str = "",
    issuer: str = "",
    issuer_aliases: List[str] | None = None,
    queries: List[str] | None = None,
    exclude_domains: List[str] | None = None,
    max_age_days: int | None = None,
    language: str = "chinese",
    topic: str = "news",
    max_results: int = 6,
    search_depth: str = "basic",
    chunks_per_source: int | None = None,
    auto_parameters: bool | None = None,
    days: int | None = None,
    low_score_threshold: float | None = None,
    allow_low_score_extract: bool = False,
    query_families: List[Dict[str, Any]] | None = None,
    required_keywords: List[str] | None = None,
    exclude_keywords: List[str] | None = None,
    strict_required_keywords: bool = False,
    strict_issuer_match: bool = False,
    field_queries: Dict[str, List[str]] | None = None,
    extract_policy: Dict[str, Any] | None = None,
) -> SearchProfile:
    combined_queries = _dedupe_preserve(([query] if query else []) + list(queries or []))
    normalized_families: List[Dict[str, Any]] = []
    for family in query_families or []:
        family_queries = _dedupe_preserve(list(family.get("queries") or []))
        if not family_queries:
            continue
        normalized_families.append(
            {
                **family,
                "queries": family_queries,
                "required_keywords": _dedupe_preserve(list(family.get("required_keywords") or [])),
                "exclude_keywords": _dedupe_preserve(list(family.get("exclude_keywords") or [])),
            }
        )
    if not normalized_families and combined_queries:
        normalized_families = [
            {
                "name": "default",
                "queries": combined_queries,
                "required_keywords": [],
                "exclude_keywords": [],
            }
        ]
    normalized_field_queries = {
        field: _dedupe_preserve(values)
        for field, values in (field_queries or {}).items()
        if _dedupe_preserve(values)
    }
    return {
        "query": query,
        "queries": combined_queries[1:] if combined_queries and combined_queries[0] == query else combined_queries,
        "preferred_domains": domains,
        "exclude_domains": exclude_domains or [],
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
        "low_score_threshold": low_score_threshold,
        "allow_low_score_extract": allow_low_score_extract,
        "query_families": normalized_families,
        "required_keywords": _dedupe_preserve(required_keywords or []),
        "exclude_keywords": _dedupe_preserve(exclude_keywords or []),
        "strict_required_keywords": strict_required_keywords,
        "strict_issuer_match": strict_issuer_match,
        "field_queries": normalized_field_queries,
        "extract_policy": extract_policy or {},
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

_REALTIME_GENERAL_5D = {
    **_REALTIME_DEFAULTS,
    "topic": "general",
    "days": 5,
}

_REALTIME_GENERAL_3D = {
    **_REALTIME_DEFAULTS,
    "topic": "general",
    "days": 3,
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
        query="COMEX黄金期货 价格 今日收盘 美元/盎司 GC=F gold futures price",
        domains=["investing.com", "cmegroup.com", "tradingeconomics.com", "jin10.com", "eastmoney.com"],
        exclude_domains=["reuters.com", "marketwatch.com", "news.yahoo.com"],
        unit="$/oz",
        issuer="COMEX/CME",
        issuer_aliases=["CME", "COMEX", "芝商所"],
        queries=[
            "GC=F gold futures price",
            "GC gold futures settlement price",
            "COMEX黄金期货 最新价格 美元/盎司",
            "gold futures price per ounce",
        ],
        query_families=[
            {
                "name": "official_quote",
                "queries": [
                    "CME COMEX gold futures settlement price latest",
                    "COMEX黄金期货 主力合约 最新结算价 美元/盎司",
                ],
                "preferred_domains": ["cmegroup.com", "investing.com", "tradingeconomics.com"],
                "required_keywords": ["gold", "黄金", "comex"],
            },
            {
                "name": "ticker_quote",
                "queries": [
                    "GC=F gold futures quote latest",
                    "GC gold futures last price",
                ],
                "required_keywords": ["gc", "gold", "黄金"],
            },
        ],
        required_keywords=["gold", "黄金", "comex"],
        exclude_keywords=["gsg", "bcom"],
        strict_required_keywords=True,
        extract_policy={"use_tavily_extract": True, "extract_topk": 2},
        max_age_days=5,
        **_REALTIME_GENERAL_5D,
    ),
    "CL=F": _profile(
        query="WTI原油期货 价格 今日收盘 美元/桶 CL=F WTI crude futures price",
        domains=["investing.com", "cmegroup.com", "tradingeconomics.com", "jin10.com", "eastmoney.com"],
        exclude_domains=["reuters.com", "marketwatch.com", "news.yahoo.com"],
        unit="$/barrel",
        issuer="NYMEX/CME",
        issuer_aliases=["NYMEX", "CME", "纽约商品交易所"],
        queries=[
            "CL=F WTI crude futures price",
            "WTI原油期货 最新价格 美元/桶",
            "WTI crude futures quote",
        ],
        query_families=[
            {
                "name": "official_quote",
                "queries": [
                    "NYMEX WTI crude futures settlement price latest",
                    "NYMEX WTI原油期货 主力合约 最新结算价 美元/桶",
                ],
                "preferred_domains": ["cmegroup.com", "investing.com", "tradingeconomics.com"],
                "required_keywords": ["wti", "nymex", "原油"],
                "exclude_keywords": ["brent"],
            },
            {
                "name": "ticker_quote",
                "queries": [
                    "CL=F WTI crude futures quote latest",
                    "CL NYMEX WTI crude futures last price",
                ],
                "required_keywords": ["cl", "wti", "nymex"],
                "exclude_keywords": ["brent"],
            },
        ],
        required_keywords=["wti", "nymex", "原油"],
        exclude_keywords=["brent"],
        strict_required_keywords=True,
        extract_policy={"use_tavily_extract": True, "extract_topk": 2},
        max_age_days=5,
        **_REALTIME_GENERAL_5D,
    ),
    "BZ=F": _profile(
        query="布伦特原油期货 价格 今日收盘 美元/桶 BZ=F Brent crude futures price",
        domains=["investing.com", "ice.com", "tradingeconomics.com", "jin10.com", "eastmoney.com"],
        exclude_domains=["reuters.com", "marketwatch.com", "news.yahoo.com"],
        unit="$/barrel",
        issuer="ICE",
        issuer_aliases=["ICE", "洲际交易所"],
        queries=[
            "BZ=F Brent crude futures price",
            "布伦特原油期货 最新价格 美元/桶",
            "Brent crude futures quote",
        ],
        query_families=[
            {
                "name": "official_quote",
                "queries": [
                    "ICE Brent crude futures settlement price latest",
                    "ICE布伦特原油期货 主力合约 最新结算价 美元/桶",
                ],
                "preferred_domains": ["ice.com", "investing.com", "tradingeconomics.com"],
                "required_keywords": ["brent", "ice", "布伦特"],
                "exclude_keywords": ["wti"],
            },
            {
                "name": "ticker_quote",
                "queries": [
                    "BZ=F Brent crude futures quote latest",
                    "Brent crude front month last price",
                ],
                "required_keywords": ["brent", "bz", "ice"],
                "exclude_keywords": ["wti"],
            },
        ],
        required_keywords=["brent", "ice", "布伦特"],
        exclude_keywords=["wti"],
        strict_required_keywords=True,
        extract_policy={"use_tavily_extract": True, "extract_topk": 2},
        max_age_days=5,
        **_REALTIME_GENERAL_5D,
    ),
    "HG=F": _profile(
        query="COMEX铜期货 价格 今日收盘 美元/磅 HG=F copper futures price",
        domains=["investing.com", "cmegroup.com", "tradingeconomics.com", "jin10.com", "eastmoney.com"],
        exclude_domains=["reuters.com", "marketwatch.com", "news.yahoo.com"],
        unit="$/lb",
        issuer="COMEX/CME",
        issuer_aliases=["COMEX", "CME", "芝商所"],
        queries=[
            "HG=F copper futures price",
            "COMEX铜期货 最新价格 美元/磅",
            "copper futures quote",
        ],
        query_families=[
            {
                "name": "official_quote",
                "queries": [
                    "COMEX copper futures settlement price latest",
                    "COMEX铜期货 主力合约 最新结算价 美元/磅",
                ],
                "preferred_domains": ["cmegroup.com", "investing.com", "tradingeconomics.com"],
                "required_keywords": ["copper", "铜", "comex"],
                "exclude_keywords": ["micro copper", "mini copper"],
            },
            {
                "name": "ticker_quote",
                "queries": [
                    "HG=F copper futures quote latest",
                    "HG COMEX copper futures last price",
                ],
                "required_keywords": ["hg", "copper", "铜"],
                "exclude_keywords": ["micro copper", "mini copper"],
            },
        ],
        required_keywords=["copper", "铜", "comex"],
        exclude_keywords=["micro copper", "mini copper"],
        strict_required_keywords=True,
        extract_policy={"use_tavily_extract": True, "extract_topk": 2},
        max_age_days=5,
        **_REALTIME_GENERAL_5D,
    ),
    "BCOM": _profile(
        query="彭博商品指数 BCOM 最新点位 BCOM Index level Bloomberg Commodity Index",
        domains=["bloomberg.com", "tradingeconomics.com", "investing.com", "stockcharts.com"],
        unit="点",
        issuer="Bloomberg",
        issuer_aliases=["彭博"],
        queries=[
            "BCOM index level",
            "BCOM:IND Bloomberg Commodity Index level",
            "Bloomberg Commodity Index value today",
            "Bloomberg Commodity Index level",
            "彭博商品指数 BCOM 点位",
        ],
        query_families=[
            {
                "name": "official_index",
                "queries": [
                    "Bloomberg Commodity Index BCOM level latest",
                    "BCOM:IND Bloomberg Commodity Index quote",
                ],
                "preferred_domains": ["bloomberg.com", "tradingeconomics.com", "stockcharts.com"],
                "required_keywords": ["bcom", "bloomberg commodity index", "彭博商品指数"],
                "exclude_keywords": ["gsci", "gsg"],
            },
        ],
        required_keywords=["bcom", "bloomberg commodity index", "彭博商品指数"],
        exclude_keywords=["gsci", "gsg"],
        strict_required_keywords=True,
        extract_policy={"use_tavily_extract": True, "extract_topk": 2},
        max_age_days=7,
        **_REALTIME_GENERAL_5D,
    ),
    "GSG": _profile(
        query="GSG ETF 价格 iShares S&P GSCI Commodity-Indexed Trust quote",
        domains=["ishares.com", "blackrock.com", "finance.yahoo.com", "investing.com"],
        exclude_domains=["reuters.com", "marketwatch.com", "news.yahoo.com"],
        unit="USD",
        issuer="iShares/BlackRock",
        issuer_aliases=["BlackRock", "贝莱德", "iShares"],
        queries=[
            "GSG ETF price",
            "NYSEARCA:GSG price",
            "GSG ETF quote",
            "iShares GSG quote",
            "GSG ETF 价格",
        ],
        query_families=[
            {
                "name": "official_quote",
                "queries": [
                    "iShares GSG ETF quote latest",
                    "NYSEARCA:GSG last price",
                ],
                "preferred_domains": ["ishares.com", "blackrock.com", "investing.com"],
                "required_keywords": ["gsg", "ishares", "quote"],
            },
        ],
        required_keywords=["gsg", "ishares", "quote"],
        exclude_keywords=["net inflow", "资金流", "flow"],
        strict_required_keywords=True,
        extract_policy={"use_tavily_extract": True, "extract_topk": 2},
        max_age_days=7,
        **_REALTIME_GENERAL_5D,
    ),

    # ==================== 汇率（实时） ====================
    "USDCNY": _profile(
        query="USD CNY exchange rate 美元人民币 在岸即期汇率 最新",
        queries=[
            "USD/CNY onshore exchange rate today",
            "USD/CNY exchange rate investing.com",
            "USD/CNY exchange rate tradingeconomics",
            "{ref_year}年{ref_month}月 美元人民币 在岸 即期 汇率",
            "美元人民币 在岸即期汇率 最新报价",
            "中国货币网 USD/CNY 在岸 即期 汇率",
            "CFETS 美元 人民币 即期 汇率",
            "中国银行 外汇牌价 美元 现汇卖出",
        ],
        domains=[
            "chinamoney.com.cn",
            "cfets.com.cn",
            "eastmoney.com",
            "investing.com",
            "tradingeconomics.com",
        ],
        exclude_domains=["xe.com", "x-rates.com", "boc.cn", "bankofchina.com"],
        unit="CNY",
        issuer="中国外汇交易中心",
        issuer_aliases=[
            "CFETS",
            "外汇交易中心",
            "中国货币网",
            "中国银行",
            "中行",
            "BOC",
            "外汇牌价",
            "SAFE",
            "Investing.com",
            "Trading Economics",
        ],
        query_families=[
            {
                "name": "official_cfets",
                "queries": [
                    "CFETS USD/CNY 在岸即期汇率 最新报价",
                    "中国货币网 USD/CNY 在岸即期汇率 最新",
                    "{ref_year}年{ref_month}月 USD/CNY 在岸即期汇率 CFETS",
                ],
                "preferred_domains": ["cfets.com.cn", "chinamoney.com.cn"],
                "required_keywords": ["usd/cny", "usdcny", "在岸"],
                "exclude_keywords": ["外汇牌价", "现汇卖出"],
            },
            {
                "name": "market_quote",
                "queries": [
                    "USD/CNY onshore exchange rate latest",
                    "USD/CNY quote investing tradingeconomics",
                ],
                "preferred_domains": ["investing.com", "tradingeconomics.com", "eastmoney.com"],
                "required_keywords": ["usd/cny", "在岸"],
                "exclude_keywords": ["外汇牌价", "现汇卖出"],
            },
        ],
        required_keywords=["usd/cny", "在岸", "即期"],
        exclude_keywords=["外汇牌价", "现汇卖出"],
        strict_required_keywords=True,
        strict_issuer_match=True,
        extract_policy={"use_tavily_extract": True, "extract_topk": 2},
        max_age_days=3,
        **_REALTIME_GENERAL_3D,
    ),
    "USDCNH": _profile(
        query="USD/CNH exchange rate 离岸人民币 汇率 最新",
        domains=["investing.com", "tradingeconomics.com", "eastmoney.com", "reuters.com"],
        exclude_domains=["marketwatch.com", "news.yahoo.com"],
        unit="CNH",
        issuer="离岸市场",
        issuer_aliases=["HKEX", "港交所", "CNH", "离岸人民币", "offshore", "Investing.com", "Trading Economics"],
        queries=[
            "USD/CNH offshore exchange rate today",
            "USD/CNH exchange rate investing.com",
            "USD/CNH exchange rate tradingeconomics",
            "{ref_year}年{ref_month}月 离岸人民币 汇率",
            "离岸人民币 USDCNH 即期 汇率 最新",
            "USD/CNH offshore yuan rate",
            "USDCNH quote",
        ],
        required_keywords=["usdcnh", "usd/cnh", "离岸人民币", "offshore"],
        strict_required_keywords=True,
        max_age_days=5,
        **_REALTIME_GENERAL_5D,
    ),
    "DXY": _profile(
        query="DXY US dollar index 美元指数 最新",
        queries=[
            "DXY dollar index today",
            "US Dollar Index quote latest",
            "DXY index value tradingeconomics",
            "Dollar Index value today",
            "DXY index value",
            "美元指数 DXY 实时点位",
        ],
        domains=["theice.com", "investing.com", "tradingeconomics.com", "eastmoney.com", "jin10.com"],
        unit="点",
        issuer="ICE",
        issuer_aliases=[
            "Intercontinental Exchange",
            "ICE Futures U.S.",
            "US Dollar Index",
            "Dollar Index",
            "美元指数",
            "DXY",
            "Investing.com",
            "Trading Economics",
        ],
        max_age_days=3,
        low_score_threshold=0.05,
        allow_low_score_extract=True,
        required_keywords=["dxy", "美元指数", "dollar index"],
        strict_required_keywords=True,
        **_REALTIME_GENERAL_3D,
    ),

    # ==================== 债券收益率（实时） ====================
    "US10Y": _profile(
        query="美国10年期国债收益率 最新 数据 历史",
        domains=["investing.com", "tradingeconomics.com", "fred.stlouisfed.org", "eastmoney.com"],
        queries=[
            "US 10Y Treasury yield historical data",
            "美国10年期国债收益率 历史数据",
            "US10Y yield quote",
        ],
        exclude_domains=["reuters.com", "bloomberg.com"],
        unit="%",
        issuer="美国财政部",
        issuer_aliases=["U.S. Treasury", "FRED", "美联储"],
        max_age_days=2,
        **_REALTIME_DEFAULTS,
    ),
    "CN10Y": _profile(
        query="China 10Y bond yield 中国10年期国债收益率 最新",
        domains=[
            "chinabond.com.cn",
            "chinamoney.com.cn",
            "cfets.com.cn",
            "investing.com",
            "tradingeconomics.com",
            "ceicdata.com",
            "macromicro.me",
        ],
        queries=[
            "CN10Y China 10 year government bond yield",
            "China 10Y treasury yield tradingeconomics",
            "China 10-year government bond yield investing",
            "中国10年期国债收益率 中债估值",
            "中国10年期国债收益率 历史数据",
        ],
        unit="%",
        issuer="中债估值中心",
        issuer_aliases=["中债", "CCDC", "中央国债登记结算公司", "Trading Economics", "CEIC", "MacroMicro", "Investing.com"],
        max_age_days=5,
        low_score_threshold=0.05,
        allow_low_score_extract=True,
        **_REALTIME_GENERAL_3D,
    ),
    "CN10Y_CDB": _profile(
        query="中国10年期国开债收益率 最新 数据 中债估值 历史",
        domains=["chinabond.com.cn", "chinamoney.com.cn", "cfets.com.cn", "eastmoney.com"],
        queries=[
            "中国10年期国开债收益率 历史数据",
            "国开债 10年期 收益率 最新",
        ],
        unit="%",
        issuer="国家开发银行",
        issuer_aliases=["中债", "CCDC", "CDB", "国开行"],
        query_families=[
            {
                "name": "official_cdb",
                "queries": [
                    "国家开发银行债 10年期 到期收益率 最新",
                    "国开债 10年期 活跃券 收益率 最新",
                    "政策性金融债 国开债 10年期 收益率",
                ],
                "preferred_domains": ["chinabond.com.cn", "chinamoney.com.cn", "cfets.com.cn", "eastmoney.com"],
                "required_keywords": ["国开债", "国家开发银行", "cdb"],
                "exclude_keywords": ["国债", "treasury"],
            },
        ],
        required_keywords=["国开债", "国家开发银行", "cdb"],
        exclude_keywords=["国债", "treasury"],
        strict_required_keywords=True,
        extract_policy={"use_tavily_extract": True, "extract_topk": 2},
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
        query="northbound capital flow 北向资金 沪深港通 月度净流入 HKEX",
        domains=["eastmoney.com", "data.eastmoney.com", "10jqka.com.cn", "cls.cn", "cs.com.cn", "hkex.com.hk", "macromicro.me"],
        unit="亿元",
        issuer="沪深港通",
        issuer_aliases=["沪股通", "深股通", "港交所", "HKEX", "Stock Connect", "Hong Kong Exchanges"],
        queries=[
            "Stock Connect northbound monthly flow",
            "HKEX northbound trading statistics",
            "{ref_year}年{ref_month}月 北向资金 净买入",
            "北向资金 累计净买入 沪股通 深股通",
            "northbound net inflow monthly",
        ],
        max_age_days=45,
        time_range="month",
        search_depth="advanced",
        max_results=6,
        language="chinese",
        topic="general",
        days=45,
        auto_parameters=False,
        chunks_per_source=3,
    ),
    "southbound": _profile(
        query="southbound capital flow 南向资金 港股通 月度净流入 HKEX",
        domains=["eastmoney.com", "data.eastmoney.com", "10jqka.com.cn", "cls.cn", "cs.com.cn", "hkex.com.hk", "macromicro.me"],
        unit="亿港元",
        issuer="港股通",
        issuer_aliases=["港股通", "港交所", "HKEX", "Stock Connect", "Hong Kong Exchanges"],
        queries=[
            "Stock Connect southbound monthly flow",
            "HKEX southbound trading statistics",
            "{ref_year}年{ref_month}月 南向资金 净买入",
            "南向资金 累计净买入 港股通",
            "southbound net inflow monthly",
        ],
        max_age_days=45,
        time_range="month",
        search_depth="advanced",
        max_results=6,
        language="chinese",
        topic="general",
        days=45,
        auto_parameters=False,
        chunks_per_source=3,
    ),
    "etf": _profile(
        query="A股ETF资金流向 今日净申购 近5日净申购 东方财富",
        domains=["eastmoney.com", "data.eastmoney.com", "fund.eastmoney.com", "10jqka.com.cn"],
        unit="亿元",
        issuer="沪深交易所",
        issuer_aliases=["ETF", "交易所"],
        query_families=[
            {
                "name": "summary",
                "queries": [
                    "A股ETF资金流向 近5日 净流入 东方财富",
                    "A股ETF 申购赎回 资金净流入 最新 东方财富",
                ],
                "preferred_domains": ["data.eastmoney.com", "fund.eastmoney.com", "eastmoney.com"],
                "required_keywords": ["etf", "净流入", "申购"],
            },
        ],
        required_keywords=["etf", "净流入", "申购"],
        field_queries={
            "recent_5d": [
                "A股ETF 近5日净流入 亿元 东方财富",
                "{ref_year}年{ref_month}月 A股ETF 近5日资金净流入 东方财富",
            ],
            "total_120d": [
                "A股ETF 近120日累计净流入 亿元 东方财富",
                "{ref_year}年 A股ETF 年内累计净流入 东方财富",
            ],
        },
        extract_policy={"use_tavily_extract": True, "extract_topk": 2, "field_retry": True},
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
        queries=[
            "{report_year}年{report_month}月 规模以上工业增加值 同比 增速 国家统计局",
            "{report_year}年{report_month}月 工业增加值 同比 国家统计局",
            "国家统计局 工业增加值 最新发布 同比",
        ],
        domains=["stats.gov.cn", "eastmoney.com", "10jqka.com.cn"],
        unit="%",
        issuer="国家统计局",
        issuer_aliases=["统计局", "NBS"],
        query_families=[
            {
                "name": "official_period",
                "queries": [
                    "{expected_period_label} 规模以上工业增加值 同比 国家统计局",
                    "{expected_period_range_label} 规模以上工业增加值 同比 国家统计局",
                    "国家统计局 规模以上工业增加值 {expected_period_label} 同比",
                ],
                "preferred_domains": ["stats.gov.cn", "ce.cn", "people.com.cn"],
                "required_keywords": ["工业增加值", "同比"],
            },
        ],
        required_keywords=["工业增加值", "同比"],
        extract_policy={"use_tavily_extract": False},
        max_age_days=45,
        **_MACRO_DEFAULTS,
    ),
    "industrial_sales": _profile(
        query="规模以上工业企业 营业收入 同比 最新 数据 国家统计局",
        queries=[
            "{report_year}年1-{report_month}月 规模以上工业企业 营业收入 同比 国家统计局",
            "{report_year}年{report_month}月 规模以上工业企业 营业收入 同比 国家统计局",
            "国家统计局 工业企业 营业收入 同比 最新发布",
        ],
        domains=["stats.gov.cn", "ce.cn", "eastmoney.com", "people.com.cn", "10jqka.com.cn"],
        unit="%",
        issuer="国家统计局",
        issuer_aliases=["统计局", "NBS"],
        query_families=[
            {
                "name": "official_ytd",
                "queries": [
                    "{expected_period_range_label} 规模以上工业企业营业收入同比 国家统计局",
                    "{expected_period_label} 规模以上工业企业营业收入同比 国家统计局",
                    "国家统计局 工业企业营业收入 同比 {expected_period_range_label}",
                ],
                "preferred_domains": ["stats.gov.cn", "ce.cn", "people.com.cn"],
                "required_keywords": ["工业企业", "营业收入", "同比"],
            },
        ],
        required_keywords=["工业企业", "营业收入", "同比"],
        extract_policy={"use_tavily_extract": False},
        max_age_days=150,
        max_results=6,
        search_depth="basic",
        language="chinese",
        auto_parameters=True,
    ),
    "bdi": _profile(
        query="波罗的海干散货指数 BDI 最新点位 历史数据 Baltic Exchange",
        queries=[
            "Baltic Dry Index historical data",
            "BDI Baltic Exchange index value",
            "波罗的海干散货指数 BDI 最新 点位 历史数据",
        ],
        domains=[
            "balticexchange.com",
            "tradingeconomics.com",
            "investing.com",
            "eastmoney.com",
        ],
        exclude_domains=["reuters.com", "bloomberg.com", "jin10.com"],
        unit="点",
        issuer="波罗的海交易所",
        issuer_aliases=["Baltic Exchange", "BDI", "波罗的海干散货指数"],
        max_age_days=2,
        time_range="day",
        max_results=6,
        search_depth="advanced",
        language="chinese",
        topic="general",
        days=3,
        auto_parameters=False,
        low_score_threshold=0.05,
        allow_low_score_extract=True,
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
        query="China RRR reserve requirement ratio 存款准备金率 最新",
        domains=["pbc.gov.cn", "eastmoney.com", "cls.cn", "xinhuanet.com", "tradingeconomics.com", "ceicdata.com"],
        queries=[
            "PBOC RRR reserve ratio latest",
            "中国央行 存款准备金率 最新",
            "reserve requirement ratio China latest",
            "China reserve requirement ratio {ref_year}",
        ],
        unit="%",
        issuer="中国人民银行",
        issuer_aliases=["央行", "PBOC", "人行", "RRR", "Trading Economics", "CEIC"],
        query_families=[
            {
                "name": "official_pbc",
                "queries": [
                    "中国人民银行 存款准备金率 调整 公告 最新",
                    "人民银行 降准 公告 存款准备金率",
                    "{ref_year}年 人民银行 存款准备金率 调整",
                ],
                "preferred_domains": ["pbc.gov.cn", "xinhuanet.com", "cls.cn"],
                "required_keywords": ["存款准备金率", "降准", "人民银行"],
                "exclude_keywords": ["农业", "设施农业", "种植"],
            },
            {
                "name": "macro_aggregator",
                "queries": [
                    "PBOC reserve requirement ratio latest",
                    "China reserve requirement ratio latest PBOC",
                ],
                "preferred_domains": ["tradingeconomics.com", "ceicdata.com", "eastmoney.com"],
                "required_keywords": ["reserve requirement ratio", "rrr", "pboc"],
            },
        ],
        required_keywords=["存款准备金率", "降准", "人民银行"],
        exclude_keywords=["农业", "设施农业", "种植", "lpr", "loan prime rate"],
        max_age_days=365,
        low_score_threshold=0.02,
        allow_low_score_extract=False,
        strict_required_keywords=True,
        strict_issuer_match=True,
        extract_policy={"use_tavily_extract": False},
        auto_parameters=False,
        **_MACRO_DEFAULTS,
    ),
    "reverse_repo": _profile(
        query="中国央行 7天逆回购 中标利率 最新 Reverse Repo rate",
        domains=["pbc.gov.cn", "chinamoney.com.cn", "eastmoney.com", "cls.cn", "tradingeconomics.com"],
        queries=[
            "China 7-day reverse repo rate latest",
            "PBOC 7-day reverse repo operation rate",
            "央行 7天逆回购 中标利率",
            "reverse repo rate China latest",
        ],
        unit="%",
        issuer="中国人民银行",
        issuer_aliases=["央行", "PBOC", "人行", "公开市场操作", "中标利率", "7天逆回购"],
        query_families=[
            {
                "name": "official_notice",
                "queries": [
                    "人民银行 公开市场业务交易公告 7天逆回购 中标利率",
                    "中国人民银行 7天逆回购 中标利率 公告",
                    "{ref_year}年{ref_month}月 7天逆回购 中标利率 人民银行",
                ],
                "preferred_domains": ["pbc.gov.cn", "chinamoney.com.cn", "cls.cn"],
                "required_keywords": ["逆回购", "中标利率", "公开市场业务"],
            },
            {
                "name": "macro_aggregator",
                "queries": [
                    "China 7-day reverse repo rate latest PBOC",
                    "PBOC 7-day reverse repo operation rate",
                ],
                "preferred_domains": ["tradingeconomics.com", "eastmoney.com", "chinamoney.com.cn"],
                "required_keywords": ["reverse repo", "7-day", "pboc"],
            },
        ],
        required_keywords=["逆回购", "中标利率", "公开市场业务"],
        exclude_keywords=["lpr", "loan prime rate"],
        strict_required_keywords=True,
        strict_issuer_match=True,
        extract_policy={"use_tavily_extract": False},
        max_age_days=14,
        auto_parameters=False,
        **_MACRO_DEFAULTS,
    ),
    "mlf": _profile(
        query="人民银行 中期借贷便利 操作公告 多重价位 中标利率区间 最新",
        domains=["pbc.gov.cn", "chinamoney.com.cn", "eastmoney.com", "cls.cn", "tradingeconomics.com"],
        queries=[
            "人民银行 中期借贷便利 操作公告 多重价位 中标利率",
            "央行 MLF 操作公告 利率区间",
            "中期借贷便利 MLF 1年期 中标利率区间 最新",
            "MLF 加权平均利率 最新",
            "MLF 多重价位中标 利率中枢",
            "PBOC MLF rate latest",
            "China MLF rate 1 year latest",
            "medium-term lending facility rate China",
        ],
        unit="%",
        issuer="中国人民银行",
        issuer_aliases=[
            "央行",
            "PBOC",
            "人行",
            "中期借贷便利",
            "中标利率",
            "利率区间",
            "多重价位",
            "加权平均利率",
            "MLF",
            "Trading Economics",
        ],
        query_families=[
            {
                "name": "official_notice",
                "queries": [
                    "人民银行 中期借贷便利 操作公告 1年期 中标利率",
                    "{expected_period_label} 中期借贷便利 操作公告 利率 人民银行",
                    "人民银行 MLF 操作公告 中标利率",
                ],
                "preferred_domains": ["pbc.gov.cn", "chinamoney.com.cn", "cls.cn"],
                "required_keywords": ["mlf", "中期借贷便利", "利率"],
            },
            {
                "name": "macro_aggregator",
                "queries": [
                    "China MLF rate latest PBOC",
                    "PBOC MLF 1 year rate latest",
                ],
                "preferred_domains": ["tradingeconomics.com", "eastmoney.com", "chinamoney.com.cn"],
                "required_keywords": ["mlf", "rate", "pboc"],
            },
        ],
        required_keywords=["mlf", "中期借贷便利", "利率"],
        exclude_keywords=["lpr", "loan prime rate"],
        strict_required_keywords=True,
        strict_issuer_match=True,
        extract_policy={"use_tavily_extract": False},
        max_age_days=90,
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
