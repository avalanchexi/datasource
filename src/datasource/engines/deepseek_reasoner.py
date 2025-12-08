#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DeepSeekExtractionAgent
-----------------------
轻量封装 DeepSeek（OpenAI 兼容协议），在 Stage2 Unified Pipeline 中用于从搜索结果里抽取
数值、单位、周期与来源。当前实现优先使用本地正则回退，避免无密钥时阻塞流程。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional

from loguru import logger

try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover - 环境缺省时延迟导入
    AsyncOpenAI = None  # type: ignore


class DeepSeekExtractionAgent:
    """从 Tavily 搜索结果里提取结构化指标的轻量代理"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek-chat",
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
        self._client: Optional[Any] = None

    async def _ensure_client(self) -> Optional[Any]:
        if not self.api_key or AsyncOpenAI is None:
            return None
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    @staticmethod
    def _fallback_extract(snippets: List[Dict[str, Any]]) -> (Optional[float], Optional[str]):
        """无模型时的兜底提取：扫描 snippet 里的首个数值并返回对应 URL"""
        for item in snippets:
            text = " ".join(
                str(item.get("content", "")) or str(item.get("snippet", "")) or ""
            )
            match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
            if match:
                try:
                    return float(match.group()), item.get("url")
                except ValueError:
                    continue
        return None, None

    @staticmethod
    def _combine_text(snippets: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for item in snippets:
            parts.append(str(item.get("content", "")) or str(item.get("snippet", "")) or "")
        return " ".join(parts)

    async def extract(
        self,
        snippets: List[Dict[str, Any]],
        indicator: str,
        unit_hint: Optional[str] = None,
        issuer_hint: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        从 Tavily 结果中提取结构化字段。

        Returns:
            dict(value, unit, source_url, confidence, note)
        """
        logger.debug(f"[DeepSeekExtractionAgent] extracting indicator={indicator}")
        client = await self._ensure_client()

        combined_text = self._combine_text(snippets).lower()
        first_url = snippets[0].get("url") if snippets else None

        # 兜底：无密钥或无法导入时直接返回简单提取
        if client is None:
            fallback_value, url = self._fallback_extract(snippets)
            return {
                "value": fallback_value,
                "unit": unit_hint,
                "source_url": url or first_url,
                "confidence": 0.35 if fallback_value is not None else 0.0,
                "issuer_match": bool(issuer_hint and issuer_hint.lower() in combined_text),
                "note": "regex_fallback" if fallback_value is not None else "no_deepseek_key",
            }

        prompt = (
            "你是财经数据抽取助手。根据搜索片段提取指标的数值、单位、来源 URL，"
            "返回 JSON: {value: float/null, unit: str/null, source_url: str/null}。"
            f"目标指标: {indicator}。"
        )
        if unit_hint:
            prompt += f" 数值单位通常为 {unit_hint}。"
        if issuer_hint:
            prompt += f" 发布机构通常是 {issuer_hint}。"

        messages = [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": str(snippets),
            },
        ]

        try:
            client_opts = client.with_options(timeout=request_timeout) if request_timeout else client
            completion = await client_opts.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content or "{}"
            data = json.loads(content)
            value = data.get("value")
            try:
                value = float(value)
            except Exception:
                value = None
            unit_val = data.get("unit") or unit_hint
            source_url = data.get("source_url") or first_url
            issuer_val = data.get("issuer")
            issuer_match = False
            if issuer_hint:
                hint = str(issuer_hint).lower()
                issuer_match = (issuer_val and hint in str(issuer_val).lower()) or (hint in combined_text)
            return {
                "value": value,
                "unit": unit_val,
                "source_url": source_url,
                "issuer": issuer_val,
                "issuer_match": issuer_match,
                "confidence": data.get("confidence", 0.75 if value is not None else 0.0),
                "note": "deepseek_structured" if value is not None else "deepseek_no_value",
            }
        except Exception as exc:  # pragma: no cover - 网络异常兜底
            logger.warning(f"DeepSeek 请求失败，使用 regex 兜底: {exc}")
            fallback_value, url = self._fallback_extract(snippets)
            return {
                "value": fallback_value,
                "unit": unit_hint,
                "source_url": url or first_url,
                "issuer_match": bool(issuer_hint and issuer_hint in combined_text),
                "confidence": 0.2,
                "note": f"deepseek_error:{exc}",
            }

        match = re.search(r"[-+]?\d+(?:\.\d+)?", content or "")
        value = float(match.group()) if match else None
        return {
            "value": value,
            "unit": unit_hint,
            "source_url": None,
            "confidence": 0.62 if value is not None else 0.0,
            "note": "deepseek_structured" if value is not None else "deepseek_no_value",
        }


__all__ = ["DeepSeekExtractionAgent"]
