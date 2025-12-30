#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Async Exa Client
----------------
Thin async wrapper around exa-py SDK, returns Tavily-compatible results.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import inspect
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - optional dependency
    from exa_py import Exa
except Exception:  # noqa: W0703
    Exa = None

class AsyncExaClient:
    """Async wrapper for Exa SDK search."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_concurrency: int = 2,
        cache: Optional[Any] = None,
        default_num_results: int = 6,
        use_autoprompt: bool = False,
    ) -> None:
        self.api_key = api_key
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.cache = cache
        self.default_num_results = default_num_results
        self.use_autoprompt = use_autoprompt
        self._client: Optional[Any] = None
        self._supports_use_autoprompt: Optional[bool] = None

    def _ensure_client(self) -> Any:
        if Exa is None:
            raise RuntimeError("exa-py 未安装，请先运行 pip install exa-py")
        if not self._client:
            self._client = Exa(api_key=self.api_key)
            try:
                sig = inspect.signature(self._client.search)
                self._supports_use_autoprompt = "use_autoprompt" in sig.parameters
            except Exception:
                self._supports_use_autoprompt = False
        return self._client

    @staticmethod
    def _make_cache_key(payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_attr(item: Any, key: str) -> Any:
        if isinstance(item, dict):
            return item.get(key)
        return getattr(item, key, None)

    @staticmethod
    def _join_highlights(highlights: Any) -> str:
        if isinstance(highlights, list):
            return " ".join(str(h) for h in highlights if h)
        if isinstance(highlights, str):
            return highlights
        return ""

    @staticmethod
    def _truncate(text: str, max_len: int = 600) -> str:
        if not text:
            return ""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def _map_result(self, item: Any) -> Dict[str, Any]:
        url = self._extract_attr(item, "url") or ""
        title = self._extract_attr(item, "title") or ""
        text = self._extract_attr(item, "text") or self._extract_attr(item, "content") or ""
        summary = self._extract_attr(item, "summary") or ""
        highlights = self._join_highlights(self._extract_attr(item, "highlights"))
        snippet = highlights or summary or self._truncate(text) or title
        content = text or summary or highlights or ""
        published = (
            self._extract_attr(item, "published_date")
            or self._extract_attr(item, "publishedDate")
            or self._extract_attr(item, "published_at")
        )
        score = self._extract_attr(item, "score")
        return {
            "url": url,
            "title": title,
            "snippet": snippet,
            "content": content,
            "score": score,
            "published_date": published,
        }

    async def search(
        self,
        *,
        query: str,
        num_results: Optional[int] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        start_published_date: Optional[str] = None,
        end_published_date: Optional[str] = None,
        start_crawl_date: Optional[str] = None,
        end_crawl_date: Optional[str] = None,
        use_autoprompt: Optional[bool] = None,
        search_type: Optional[str] = None,
        contents: Optional[Dict[str, Any]] = None,
        cache_ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("EXA_API_KEY 未设置，无法执行 Exa 搜索")

        if use_autoprompt or self.use_autoprompt:
            self._ensure_client()

        payload: Dict[str, Any] = {
            "query": query,
            "num_results": num_results or self.default_num_results,
        }
        if (self._supports_use_autoprompt or self._supports_use_autoprompt is None) and (
            use_autoprompt is not None or self.use_autoprompt
        ):
            payload["use_autoprompt"] = self.use_autoprompt if use_autoprompt is None else use_autoprompt
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains
        if start_published_date:
            payload["start_published_date"] = start_published_date
        if end_published_date:
            payload["end_published_date"] = end_published_date
        if start_crawl_date:
            payload["start_crawl_date"] = start_crawl_date
        if end_crawl_date:
            payload["end_crawl_date"] = end_crawl_date
        if search_type:
            payload["type"] = search_type
        if contents:
            payload["contents"] = contents

        cache_key = self._make_cache_key(payload)
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                cached["cache_hit"] = True
                return cached

        async with self.semaphore:
            client = self._ensure_client()
            resp = await asyncio.to_thread(client.search, **payload)

        results: List[Any] = []
        if isinstance(resp, dict):
            results = resp.get("results") or []
        else:
            results = getattr(resp, "results", None) or resp  # resp may already be a list
        if not isinstance(results, list):
            results = []

        mapped = [self._map_result(item) for item in results]
        data = {"results": mapped, "query": query, "cache_hit": False}
        if self.cache:
            self.cache.set(cache_key, data, ttl=cache_ttl)
        return data


__all__ = ["AsyncExaClient"]
