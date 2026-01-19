#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Source priority helpers for conflict resolution."""
from __future__ import annotations

from urllib.parse import urlparse

OFFICIAL_DOMAINS = {
    "pbc.gov.cn",
    "stats.gov.cn",
    "sse.com.cn",
    "szse.cn",
    "chinabond.com.cn",
    "treasury.gov",
    "cfets.com.cn",
}

MAINSTREAM_DOMAINS = {
    "reuters.com",
    "investing.com",
    "eastmoney.com",
    "cls.cn",
    "wallstreetcn.com",
    "cailianshe.com",
}


def source_weight(url: str) -> int:
    if not url:
        return 0
    try:
        netloc = urlparse(url).netloc
    except Exception:
        netloc = ""
    if not netloc:
        return 0
    if any(netloc.endswith(dom) for dom in OFFICIAL_DOMAINS):
        return 3
    if any(netloc.endswith(dom) for dom in MAINSTREAM_DOMAINS):
        return 2
    return 1
