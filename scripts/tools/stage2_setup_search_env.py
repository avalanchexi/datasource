#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quick validator for Stage2 Tavily/DeepSeek environment.
用法:
    python scripts/tools/stage2_setup_search_env.py
检查项:
- 环境变量 TAVILY_API_KEY / DEEPSEEK_API_KEY 是否存在
- Tavily API 基础连通性 (POST /search)
输出可操作的诊断信息，失败时 exit code 1。
"""

from __future__ import annotations

import json
import os
import sys

import httpx
from loguru import logger


def check_env(key: str) -> bool:
    val = os.getenv(key)
    if val:
        logger.info(f"{key} 已设置")
        return True
    logger.warning(f"{key} 未设置，请在 .env 中填写对应密钥")
    return False


def detect_proxy() -> dict:
    proxies = {
        "http": os.getenv("HTTP_PROXY") or os.getenv("http_proxy"),
        "https": os.getenv("HTTPS_PROXY") or os.getenv("https_proxy"),
        "no_proxy": os.getenv("NO_PROXY") or os.getenv("no_proxy"),
    }
    logger.info(f"Proxy 检测: http={proxies['http']} https={proxies['https']} no_proxy={proxies['no_proxy']}")
    return proxies


def check_tavily_connectivity(api_key: str) -> bool:
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": "ping", "search_depth": "basic", "max_results": 1},
            timeout=8.0,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Tavily 连通性 OK, cache_hit={data.get('cache_hit', False)}")
        return True
    except Exception as exc:
        logger.error(f"Tavily 连通性检查失败: {exc}")
        return False


def main() -> int:
    ok = True
    proxies = detect_proxy()
    has_tavily = check_env("TAVILY_API_KEY")
    has_deepseek = check_env("DEEPSEEK_API_KEY")
    if has_tavily:
        ok = check_tavily_connectivity(os.getenv("TAVILY_API_KEY", "")) and ok
    summary = {"env_ok": has_tavily and has_deepseek, "connectivity_ok": ok, "proxy": proxies}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
