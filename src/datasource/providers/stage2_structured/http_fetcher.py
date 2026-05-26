"""Bounded HTTP helpers for Stage2 structured providers."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx


DEFAULT_TIMEOUT_SECONDS = 12.0
USER_AGENT = "datasource-stage2-structured-provider/1.0"


async def fetch_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS, trust_env=False) as client:
        response = await client.get(url, params=params, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.json()


async def fetch_text(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT_SECONDS,
        trust_env=False,
        follow_redirects=True,
    ) as client:
        response = await client.get(url, params=params, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        if response.encoding is None:
            response.encoding = getattr(response, "apparent_encoding", None) or "utf-8"
        return response.text
