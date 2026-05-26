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
import inspect
import json
import os
from typing import Any, Dict, List, Optional, Tuple

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
        verify: Optional[Any] = True,
        trust_env: bool = False,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.semaphore = asyncio.Semaphore(max_concurrency)
        # extract 专用信号量：固定并发 1，避免 422/配额连环触发
        self.extract_semaphore = asyncio.Semaphore(1)
        self.cache = cache
        self.default_search_depth = default_search_depth
        self.proxies = proxies
        self.verify = self._resolve_verify(verify)
        self.trust_env = trust_env
        self._client: Optional[Any] = None
        self._supports_days: Optional[bool] = None

    @staticmethod
    def _supports_kwarg(callable_obj: Any, kwarg: str) -> bool:
        try:
            params = inspect.signature(callable_obj).parameters
        except (TypeError, ValueError):
            return False
        if kwarg in params:
            return True
        return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

    def _make_timeout_config(self) -> Any:
        return httpx.Timeout(
            connect=self.connect_timeout or self.timeout,
            read=self.timeout,
            write=self.timeout,
            pool=None,
        )

    def _build_proxy_mounts(
        self,
        proxy_items: List[Tuple[str, str]],
    ) -> Optional[Dict[str, Any]]:
        transport_cls = getattr(httpx, "AsyncHTTPTransport", None)
        if transport_cls is None:
            return None
        if not self._supports_kwarg(httpx.AsyncClient, "mounts"):
            return None

        transport_kwargs_supported = {
            key
            for key in ("proxy", "verify", "trust_env")
            if self._supports_kwarg(transport_cls, key)
        }
        if "proxy" not in transport_kwargs_supported:
            return None

        mounts: Dict[str, Any] = {}
        for scheme, proxy_url in proxy_items:
            transport_kwargs: Dict[str, Any] = {"proxy": proxy_url}
            if "verify" in transport_kwargs_supported:
                transport_kwargs["verify"] = self.verify
            if "trust_env" in transport_kwargs_supported:
                transport_kwargs["trust_env"] = self.trust_env
            mounts[scheme] = transport_cls(**transport_kwargs)
        return mounts

    def _build_client_kwargs(self, timeout_cfg: Any) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "timeout": timeout_cfg,
            "verify": self.verify,
            "trust_env": self.trust_env,
        }
        proxy_items = [
            (scheme, proxy_url)
            for scheme, proxy_url in (self.proxies or {}).items()
            if proxy_url
        ]
        if not proxy_items:
            return kwargs

        if self._supports_kwarg(httpx.AsyncClient, "proxies"):
            kwargs["proxies"] = dict(proxy_items)
            return kwargs

        if self._supports_kwarg(httpx.AsyncClient, "proxy"):
            unique_proxy_urls = []
            for _, proxy_url in proxy_items:
                if proxy_url not in unique_proxy_urls:
                    unique_proxy_urls.append(proxy_url)

            if len(unique_proxy_urls) == 1:
                kwargs["proxy"] = unique_proxy_urls[0]
                return kwargs

            mounts = self._build_proxy_mounts(proxy_items)
            if mounts:
                kwargs["mounts"] = mounts
                return kwargs

            kwargs["proxy"] = unique_proxy_urls[0]
            logger.warning(
                "当前 httpx 版本不支持多 scheme 显式代理挂载，"
                "仅使用第一个显式代理。"
            )
            return kwargs

        logger.warning(
            "当前 httpx 版本不支持显式代理参数，已跳过代理配置；"
            "仅 trust_env=True 时可能读取环境代理。"
        )
        return kwargs

    @staticmethod
    def _resolve_verify(verify: Optional[Any]) -> Any:
        """
        解析 SSL 校验配置：
        - 环境变量 TAVILY_VERIFY 支持 false/0/no/off 关闭校验；
          也可传 CA 路径。
        - 环境变量 TAVILY_CA_BUNDLE 提供自定义 CA 路径。
        """
        env_verify = os.getenv("TAVILY_VERIFY")
        env_ca = os.getenv("TAVILY_CA_BUNDLE")
        if env_verify:
            flag = env_verify.strip().lower()
            if flag in {"0", "false", "no", "off"}:
                return False
            # 若传入路径，直接返回字符串
            if os.path.exists(env_verify):
                return env_verify
        if verify is None:
            verify = True
        if env_ca and os.path.exists(env_ca):
            return env_ca
        return verify

    async def __aenter__(self) -> "AsyncTavilyClient":
        if httpx is None:
            raise RuntimeError("httpx 未安装，请先运行 pip install httpx")
        timeout_cfg = self._make_timeout_config()
        self._client = httpx.AsyncClient(**self._build_client_kwargs(timeout_cfg))
        if self.verify is False:
            logger.warning("Tavily SSL 验证已关闭（开发环境专用），请在生产环境提供有效 CA。")
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
            timeout_cfg = self._make_timeout_config()
            self._client = httpx.AsyncClient(**self._build_client_kwargs(timeout_cfg))
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
        days: Optional[int] = None,
        cache_ttl: Optional[int] = None,
        language: Optional[str] = None,
        chunks_per_source: Optional[int] = None,
        auto_parameters: Optional[bool] = None,
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
        if days is not None and self._supports_days is not False:
            try:
                days_int = int(days)
            except Exception:
                days_int = None
            if days_int and days_int > 0:
                payload["days"] = days_int
        if language:
            payload["language"] = language
        if chunks_per_source:
            payload["chunks_per_source"] = chunks_per_source
        if auto_parameters is not None:
            payload["auto_parameters"] = auto_parameters

        async def _read_cache(payload_key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            if not self.cache:
                return None
            cached = self.cache.get(self._make_cache_key(payload_key))
            if not cached:
                return None
            cached["cache_hit"] = True
            return cached

        cached = await _read_cache(payload)
        if cached:
            return cached

        async def _do_post(payload_post: Dict[str, Any]) -> Dict[str, Any]:
            async with self.semaphore:
                client = await self._ensure_client()
                logger.debug(f"Tavily request: {query} depth={payload_post['search_depth']}")
                resp = await client.post(self.base_url, json=payload_post)
                resp.raise_for_status()
                data = resp.json()
                data["cache_hit"] = False
                data["query"] = query
                data["search_depth"] = payload_post["search_depth"]
                return data

        try:
            data = await _do_post(payload)
        except Exception as exc:
            # 兼容部分 Tavily 版本/代理层不支持 days 参数：若 400 且报错信息包含 days，自动回退
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if (
                payload.get("days") is not None
                and self._supports_days is None
                and status == 400
                and "days" in str(getattr(getattr(exc, "response", None), "text", "")).lower()
            ):
                self._supports_days = False
                payload.pop("days", None)
                cached2 = await _read_cache(payload)
                if cached2:
                    return cached2
                data = await _do_post(payload)
            else:
                raise exc
        else:
            if payload.get("days") is not None:
                self._supports_days = True

        if self.cache:
            self.cache.set(self._make_cache_key(payload), data, ttl=cache_ttl)
        return data

    async def extract(
        self,
        *,
        search_result_id: Optional[str] = None,
        search_results: Optional[List[Dict[str, Any]]] = None,
        extract_depth: str = "standard",
        include_raw_content: bool = False,
        cache_ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        调用 Tavily extract 接口，对 search 结果执行结构化抽取。
        仅当 search_result_id 或 search_results 之一提供时调用。
        """
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY 未设置，无法执行 Tavily extract")
        if not search_result_id and not search_results:
            raise ValueError("extract 需要 search_result_id 或 search_results")

        payload: Dict[str, Any] = {
            "api_key": self.api_key,
            "extract_depth": extract_depth,
            "include_raw_content": include_raw_content,
        }
        if search_result_id:
            payload["search_result_id"] = search_result_id
        if search_results:
            minimal = []
            # 仅保留前 2 条高分且可解析的 URL，过滤 PDF/空内容，降低 422 风险
            sorted_results = sorted(
                search_results, key=lambda x: x.get("score", 0), reverse=True
            )[:2]
            for item in sorted_results:
                url = (item.get("url") or "").strip()
                if not url or url.lower().endswith(".pdf"):
                    continue
                content = (item.get("content") or item.get("snippet") or "").strip()
                if not content:
                    continue
                minimal.append({"url": url, "content": content})
            if not minimal:
                return {"results": [], "cache_hit": False, "warning": "extract_input_empty"}
            payload["search_results"] = minimal

        cache_key = self._make_cache_key({"extract": payload})
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                cached["cache_hit"] = True
                return cached

        async with self.extract_semaphore:
            client = await self._ensure_client()
            url = self.base_url.replace("/search", "/extract")
            logger.debug(f"Tavily extract depth={extract_depth} raw={include_raw_content}")
            resp = await client.post(url, json=payload)
            try:
                resp.raise_for_status()
                data = resp.json()
                data["cache_hit"] = False
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                logger.debug(f"Tavily extract failed: {exc}")
                data = {
                    "error": str(exc),
                    "status": status,
                    "cache_hit": False,
                    "results": [],
                }

        if self.cache:
            self.cache.set(cache_key, data, ttl=cache_ttl)
        return data


__all__ = ["AsyncTavilyClient"]
