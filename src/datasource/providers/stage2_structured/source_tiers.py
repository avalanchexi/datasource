"""Source tier classification for structured Stage2 providers."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlparse


TIER1_DOMAINS = {
    "stats.gov.cn",
    "pbc.gov.cn",
    "chinabond.com.cn",
    "chinamoney.com.cn",
    "chinaforeignexchange.com.cn",
    "cfets.com.cn",
    "hkex.com.hk",
    "sse.com.cn",
    "szse.cn",
}

TIER2_DOMAINS = {
    "finance.yahoo.com",
    "tradingeconomics.com",
    "data.eastmoney.com",
    "eastmoney.com",
    "stooq.com",
    "ishares.com",
    "blackrock.com",
    "tushare.pro",
}

TIER3_DOMAINS = {
    "finance.sina.com.cn",
    "sina.com.cn",
    "10jqka.com.cn",
    "wallstreetcn.com",
}


def _hostname(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    return hostname.lower().strip(".")


def _matches_domain(hostname: str, domains: Iterable[str]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)


def classify_structured_source_tier(url: str) -> str:
    hostname = _hostname(url)
    if not hostname:
        return "unknown"
    if _matches_domain(hostname, TIER1_DOMAINS):
        return "tier1"
    if _matches_domain(hostname, TIER2_DOMAINS):
        return "tier2"
    if _matches_domain(hostname, TIER3_DOMAINS):
        return "tier3"
    return "unknown"
