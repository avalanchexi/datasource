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
    def _find_number_by_patterns(
        text: str,
        patterns: List[str],
        low: Optional[float] = None,
        high: Optional[float] = None,
        min_decimals: int = 1,
    ) -> Optional[float]:
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
                num_text = match.group(1)
                if "." not in num_text:
                    continue
                decimals = num_text.split(".", 1)[1]
                if len(decimals) < min_decimals:
                    continue
                try:
                    value = float(num_text)
                except Exception:
                    continue
                if low is not None and value < low:
                    continue
                if high is not None and value > high:
                    continue
                return value
        return None

    @classmethod
    def _fallback_extract(
        cls,
        snippets: List[Dict[str, Any]],
        indicator: Optional[str] = None,
        unit_hint: Optional[str] = None,
    ) -> (Optional[float], Optional[str]):
        """无模型时的保守兜底提取：优先指标关键词+范围匹配，避免首数字误提取。"""
        indicator_key = (indicator or "").lower()
        pattern_rules: Dict[str, Dict[str, Any]] = {
            "usdcny": {
                "patterns": [
                    r"(?:USDCNY|USD/CNY|USD CNY|美元/人民币|美元人民币|在岸人民币)[^\d]{0,12}([0-9]+\.[0-9]{2,6})",
                    r"1(?:\.0+)?\s*USD\s*=\s*([0-9]+\.[0-9]{2,6})\s*CNY",
                ],
                "range": (5.5, 9.5),
            },
            "usdcnh": {
                "patterns": [
                    r"(?:USDCNH|USD/CNH|USD CNH|离岸人民币|offshore)[^\d]{0,12}([0-9]+\.[0-9]{2,6})",
                    r"1(?:\.0+)?\s*USD\s*=\s*([0-9]+\.[0-9]{2,6})\s*CNH",
                ],
                "range": (5.5, 10.0),
            },
            "dxy": {
                "patterns": [
                    r"(?:DXY|美元指数|Dollar Index|US Dollar Index)[^\d]{0,12}([0-9]{2,3}\.[0-9]{1,3})",
                    r"([0-9]{2,3}\.[0-9]{1,3})[^\d]{0,12}(?:DXY|美元指数|Dollar Index|US Dollar Index)",
                ],
                "range": (70.0, 140.0),
            },
            "cn10y": {
                "patterns": [
                    r"(?:China\s*10\s*Y|10[- ]?year|10y|10年|国债收益率)[^\d]{0,12}([0-9]+\.[0-9]{2,3})",
                    r"([0-9]+\.[0-9]{2,3})[^\d]{0,12}(?:China\s*10\s*Y|10[- ]?year|10y|10年)",
                ],
                "range": (0.0, 10.0),
            },
            "cn10y_cdb": {
                "patterns": [
                    r"(?:国开|国开债|开发债|CDB)[^\d]{0,16}([0-9]+\.[0-9]{2,3})",
                ],
                "range": (0.0, 12.0),
            },
            "us10y": {
                "patterns": [
                    r"(?:US10Y|美国10年|10年期美债|10-year treasury)[^\d]{0,12}([0-9]+\.[0-9]{2,3})",
                ],
                "range": (0.0, 15.0),
            },
            "gc=f": {
                "patterns": [
                    r"(?:GC=F|gold futures|COMEX黄金)[^\d]{0,20}([0-9]{3,5}\.[0-9]{1,2})",
                    r"([0-9]{3,5}\.[0-9]{1,2})\s*(?:美元/盎司|\$/oz)",
                ],
                "range": (800.0, 5000.0),
            },
            "cl=f": {
                "patterns": [
                    r"(?:CL=F|WTI原油|WTI crude)[^\d]{0,20}([0-9]{2,3}\.[0-9]{1,2})",
                    r"([0-9]{2,3}\.[0-9]{1,2})\s*(?:美元/桶|\$/barrel)",
                ],
                "range": (0.1, 250.0),
            },
            "bz=f": {
                "patterns": [
                    r"(?:BZ=F|Brent原油|Brent crude)[^\d]{0,20}([0-9]{2,3}\.[0-9]{1,2})",
                    r"([0-9]{2,3}\.[0-9]{1,2})\s*(?:美元/桶|\$/barrel)",
                ],
                "range": (0.1, 250.0),
            },
            "hg=f": {
                "patterns": [
                    r"(?:HG=F|COMEX铜|copper futures)[^\d]{0,20}([0-9]+\.[0-9]{2,3})",
                    r"([0-9]+\.[0-9]{2,3})\s*(?:美元/磅|\$/lb)",
                ],
                "range": (0.5, 8.0),
            },
            "bcom": {
                "patterns": [
                    r"(?:BCOM|彭博商品指数)[^\d]{0,12}([0-9]{2,3}\.[0-9]{1,3})",
                ],
                "range": (30.0, 300.0),
            },
            "gsg": {
                "patterns": [
                    r"(?:GSG|GSG ETF)[^\d]{0,12}([0-9]{1,3}\.[0-9]{1,3})",
                ],
                "range": (10.0, 80.0),
            },
            "bdi": {
                "patterns": [
                    r"(?:BDI|波罗的海)[^\d]{0,20}([0-9]{3,5}\.[0-9]{1,2})",
                    r"(?:BDI|波罗的海)[^\d]{0,20}([0-9]{3,5})",
                ],
                "range": (200.0, 10000.0),
                "min_decimals": 0,
            },
            "rrr": {
                "patterns": [
                    r"(?:存款准备金率|RRR)[^\d]{0,12}([0-9]+\.[0-9]+)",
                ],
                "range": (5.0, 20.0),
            },
            "reverse_repo": {
                "patterns": [
                    r"(?:逆回购|reverse repo|repo)[^\d]{0,12}([0-9]+\.[0-9]+)",
                ],
                "range": (1.0, 5.0),
            },
            "mlf": {
                "patterns": [
                    r"(?:MLF|中期借贷便利)[^\d]{0,12}([0-9]+\.[0-9]+)",
                ],
                "range": (1.5, 5.0),
            },
        }

        rule = pattern_rules.get(indicator_key)
        if rule:
            patterns = rule.get("patterns", [])
            low, high = rule.get("range", (None, None))
            min_decimals = int(rule.get("min_decimals", 1))
            for item in snippets:
                text = " ".join(
                    str(item.get("content", "")) or str(item.get("snippet", "")) or ""
                )
                value = cls._find_number_by_patterns(
                    text,
                    patterns=patterns,
                    low=low,
                    high=high,
                    min_decimals=min_decimals,
                )
                if value is not None:
                    return value, item.get("url")
            # 指标已知但未命中，宁可返回空值，不退回首数字误提取
            return None, snippets[0].get("url") if snippets else None

        # 非白名单指标：保守策略，只提取带小数且带单位的数值
        unit_tokens = ["%", "bp", "亿元", "点", "yield", "price", "rate", "usd", "cny", "cnh"]
        for item in snippets:
            text = " ".join(
                str(item.get("content", "")) or str(item.get("snippet", "")) or ""
            )
            lowered = text.lower()
            if not any(tok in lowered for tok in unit_tokens):
                continue
            for match in re.finditer(r"([-+]?\d+\.\d+)", text):
                try:
                    value = float(match.group(1))
                except Exception:
                    continue
                if unit_hint and unit_hint == "%" and not (-100.0 <= value <= 100.0):
                    continue
                return value, item.get("url")
        return None, snippets[0].get("url") if snippets else None

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
            fallback_value, url = self._fallback_extract(
                snippets,
                indicator=indicator,
                unit_hint=unit_hint,
            )
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
            fallback_value, url = self._fallback_extract(
                snippets,
                indicator=indicator,
                unit_hint=unit_hint,
            )
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
