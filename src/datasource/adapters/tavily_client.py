#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Async Tavily Client
-------------------
轻量封装 Tavily Search API，提供异步调用、并发控制、简单重试与可选内存缓存能力。
设计目标：
- 在 Stage2 Unified Pipeline 中作为唯一 WebSearch 通道（除资金流向仍走 MCP）
- 便于在 CLI 层通过信号量限制并发，避免击穿配额
- 结果结构保持与 Tavily API 兼容，便于后续 DeepSeek 抽取
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - optional dependency
    import httpx
except Exception:  # noqa: W0703
    httpx = None

from loguru import logger

from datasource.cache.memory_cache import MemoryCache


class AsyncTavilyClient:
    """Tavily Search 的异步客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.tavily.com/search",
        timeout: float = 30.0,
        connect_timeout: Optional[float] = None,
        max_concurrency: int = 4,
        cache: Optional[Any] = None,
        default_search_depth: str = "basic",
        proxies: Optional[Dict[str, str]] = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.cache = cache
        self.default_search_depth = default_search_depth
        self.proxies = proxies
        self._client: Optional[Any] = None

    async def __aenter__(self) -> "AsyncTavilyClient":
        if httpx is None:
            raise RuntimeError("httpx 未安装，请先运行 pip install httpx")
        timeout_cfg = httpx.Timeout(
            connect=self.connect_timeout or self.timeout,
            read=self.timeout,
            write=self.timeout,
            pool=None,
        )
        try:
            self._client = httpx.AsyncClient(timeout=timeout_cfg, proxies=self.proxies)
        except TypeError:
            # 兼容老版本 httpx 无 proxies 参数
            logger.warning("httpx 版本不支持 proxies 参数，回退使用环境变量代理")
            self._client = httpx.AsyncClient(timeout=timeout_cfg)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._client:
            await self._client.aclose()
            self._client = None

    def _make_cache_key(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    async def _ensure_client(self) -> Any:
        if self._client is None:
            if httpx is None:
                raise RuntimeError("httpx 未安装，请先运行 pip install httpx")
            timeout_cfg = httpx.Timeout(
                connect=self.connect_timeout or self.timeout,
                read=self.timeout,
                write=self.timeout,
                pool=None,
            )
            try:
                self._client = httpx.AsyncClient(timeout=timeout_cfg, proxies=self.proxies)
            except TypeError:
                logger.warning("httpx 版本不支持 proxies 参数，回退使用环境变量代理")
                self._client = httpx.AsyncClient(timeout=timeout_cfg)
        return self._client

    async def search(
        self,
        query: str,
        *,
        topic: Optional[str] = None,
        search_depth: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        time_range: Optional[str] = None,
        max_results: Optional[int] = None,
        cache_ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        执行 Tavily 搜索请求。

        Returns:
            Tavily API 原始 JSON 响应，额外附加 cache_hit 标识。
        """
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY 未设置，无法执行 Tavily 搜索")

        payload: Dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": search_depth or self.default_search_depth,
        }
        if topic:
            payload["topic"] = topic
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains
        if time_range:
            payload["time_range"] = time_range
        if max_results:
            payload["max_results"] = max_results

        cache_key = self._make_cache_key(payload)
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                cached["cache_hit"] = True
                return cached

        async with self.semaphore:
            client = await self._ensure_client()
            logger.debug(f"Tavily request: {query} depth={payload['search_depth']}")
            resp = await client.post(self.base_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            data["cache_hit"] = False
            data["query"] = query
            data["search_depth"] = payload["search_depth"]

        if self.cache:
            self.cache.set(cache_key, data, ttl=cache_ttl)
        return data


__all__ = ["AsyncTavilyClient"]
