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
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from datasource.utils.coercion import to_float

try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover - 环境缺省时延迟导入
    AsyncOpenAI = None  # type: ignore


class DeepSeekExtractionAgent:
    """从 Tavily 搜索结果里提取结构化指标的轻量代理"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek-v4-pro",
        base_url: Optional[str] = None,
        extract_max_tokens: Optional[int] = None,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
        raw_tokens = (
            extract_max_tokens
            if extract_max_tokens is not None
            else os.getenv("DEEPSEEK_EXTRACT_MAX_TOKENS") or 900
        )
        try:
            self.extract_max_tokens = max(300, int(raw_tokens))
        except (TypeError, ValueError):
            self.extract_max_tokens = 900
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

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        return to_float(value)

    @staticmethod
    def _normalize_date(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        # 支持 YYYY-MM-DD / YYYY/MM/DD / YYYY-MM / YYYYMM
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y%m"):
            try:
                dt = datetime.strptime(text, fmt)
                if fmt in ("%Y-%m", "%Y%m"):
                    return dt.strftime("%Y-%m")
                return dt.strftime("%Y-%m-%d")
            except Exception:
                continue
        # 兼容 ISO 格式
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def _normalize_report_period(value: Any) -> Optional[str]:
        normalized = DeepSeekExtractionAgent._normalize_date(value)
        if not normalized:
            return None
        if len(normalized) >= 7:
            return normalized[:7]
        return None

    @staticmethod
    def _append_reason(base: Optional[str], extra: Optional[str]) -> Optional[str]:
        a = (base or "").strip()
        b = (extra or "").strip()
        if not b:
            return a or None
        if not a:
            return b
        if b in a:
            return a
        return f"{a}; {b}"

    @staticmethod
    def _normalize_trend(value: Any) -> str:
        if value is None:
            return "unknown"
        text = str(value).strip().lower()
        if text in {"inflow", "flow_in", "net_inflow", "流入", "净流入", "净买入", "buy"}:
            return "inflow"
        if text in {"outflow", "flow_out", "net_outflow", "流出", "净流出", "净卖出", "sell"}:
            return "outflow"
        return "unknown"

    @staticmethod
    def _is_fund_flow_indicator(indicator: str) -> bool:
        return indicator.lower() in {"northbound", "southbound", "etf", "margin"}

    @staticmethod
    def _pick_valid_source_url(
        source_url: Optional[str], snippets: List[Dict[str, Any]], fallback_url: Optional[str]
    ) -> (Optional[str], bool):
        if not source_url:
            return fallback_url, False
        try:
            normalized = source_url.strip()
        except Exception:
            return fallback_url, False
        if not normalized:
            return fallback_url, False
        snippet_urls = {
            str(s.get("url")).strip()
            for s in snippets
            if isinstance(s, dict) and isinstance(s.get("url"), str) and s.get("url").strip()
        }
        if not snippet_urls:
            return normalized, True
        if normalized in snippet_urls:
            return normalized, True
        # 允许同域名弱匹配，避免模型补 querystring 导致误判
        try:
            from urllib.parse import urlparse

            src_netloc = urlparse(normalized).netloc
            if src_netloc and any(urlparse(u).netloc == src_netloc for u in snippet_urls):
                return normalized, True
        except Exception:
            pass
        return fallback_url, False

    @staticmethod
    def _schema_hint(is_fund_flow: bool) -> str:
        fields = [
            '"value": float|null',
            '"unit": str|null',
            '"source_url": str|null',
            '"as_of_date": "YYYY-MM-DD"|null',
            '"report_period": "YYYY-MM"|null',
            '"manual_required": bool',
            '"manual_reason": str|null',
        ]
        if is_fund_flow:
            fields.extend(
                [
                    '"recent_5d": float|null',
                    '"total_120d": float|null',
                    '"trend": "inflow"|"outflow"|"unknown"',
                ]
            )
        return "{" + ", ".join(fields) + "}"

    @staticmethod
    def _json_error_reason(exc: json.JSONDecodeError) -> str:
        text = str(exc).lower()
        if "unterminated string" in text:
            return "deepseek_json_truncated"
        stripped_doc = (exc.doc or "").rstrip()
        near_eof = bool(stripped_doc) and exc.pos >= len(stripped_doc)
        open_container = (
            stripped_doc.count("{") > stripped_doc.count("}")
            or stripped_doc.count("[") > stripped_doc.count("]")
        )
        if "expecting value" in text and near_eof and open_container:
            return "deepseek_json_truncated"
        if near_eof and open_container and any(
            marker in text
            for marker in (
                "expecting ',' delimiter",
                "expecting ':' delimiter",
                "expecting property name enclosed in double quotes",
            )
        ):
            return "deepseek_json_truncated"
        return "deepseek_json_parse_error"

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
        is_fund_flow = self._is_fund_flow_indicator(indicator)

        # 兜底：无密钥或无法导入时直接返回简单提取
        if client is None:
            fallback_value, url = self._fallback_extract(
                snippets,
                indicator=indicator,
                unit_hint=unit_hint,
            )
            manual_reason = "no_deepseek_key" if fallback_value is None else "regex_fallback_only"
            trend = "unknown"
            if is_fund_flow and fallback_value is not None:
                trend = "inflow" if fallback_value > 0 else ("outflow" if fallback_value < 0 else "unknown")
            return {
                "value": fallback_value,
                "unit": unit_hint,
                "source_url": url or first_url,
                "confidence": 0.35 if fallback_value is not None else 0.0,
                "issuer_match": bool(issuer_hint and issuer_hint.lower() in combined_text),
                "note": "regex_fallback" if fallback_value is not None else "no_deepseek_key",
                "as_of_date": None,
                "report_period": None,
                "manual_required": fallback_value is None,
                "manual_reason": manual_reason if fallback_value is None else None,
                "recent_5d": None,
                "total_120d": None,
                "trend": trend,
            }

        schema_hint = self._schema_hint(is_fund_flow)
        prompt = (
            "你是财经数据抽取助手。"
            "必须仅基于提供的 snippets 抽取，不得猜测或补造。"
            f"目标指标: {indicator}。"
            f"严格返回 JSON 对象，字段必须完整: {schema_hint}。"
            "证据约束：source_url 必须来自 snippets 里的 url；若证据不足/冲突，"
            "将 value 置 null，并设置 manual_required=true 与 manual_reason。"
            "若无法确认日期，as_of_date/report_period 可为 null。"
        )
        if unit_hint:
            prompt += f" 单位约束：优先提取单位为 {unit_hint} 的值。"
        if issuer_hint:
            prompt += f" 机构约束：优先采用发布机构为 {issuer_hint} 的证据。"
        if is_fund_flow:
            prompt += (
                "资金流专项约束：尽量同时提取 recent_5d 和 total_120d；"
                "trend 仅允许 inflow/outflow/unknown；"
                "若只有单点值，manual_required=true，manual_reason 标记缺窗口值。"
            )

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
                temperature=0.0,
                max_tokens=self.extract_max_tokens,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content or "{}"
            try:
                data = json.loads(content)
            except json.JSONDecodeError as exc:
                reason = self._json_error_reason(exc)
                return {
                    "value": None,
                    "unit": unit_hint,
                    "source_url": first_url,
                    "issuer_match": False,
                    "confidence": 0.0,
                    "note": reason,
                    "as_of_date": None,
                    "report_period": None,
                    "manual_required": True,
                    "manual_reason": reason,
                    "recent_5d": None,
                    "total_120d": None,
                    "trend": "unknown",
                }
            value = self._to_float(data.get("value"))
            unit_val = data.get("unit") or unit_hint
            source_url_raw = data.get("source_url") or first_url
            source_url, source_is_valid = self._pick_valid_source_url(source_url_raw, snippets, first_url)
            as_of_date = self._normalize_date(data.get("as_of_date"))
            report_period = self._normalize_report_period(data.get("report_period"))
            confidence = self._to_float(data.get("confidence"))
            if confidence is None:
                confidence = 0.75 if value is not None else 0.0
            confidence = max(0.0, min(1.0, confidence))
            manual_required = bool(data.get("manual_required", False))
            manual_reason = str(data.get("manual_reason") or "").strip() or None
            issuer_val = data.get("issuer")
            issuer_match = False
            if issuer_hint:
                hint = str(issuer_hint).lower()
                issuer_match = (issuer_val and hint in str(issuer_val).lower()) or (hint in combined_text)
            if not source_is_valid and source_url_raw:
                manual_required = True
                manual_reason = self._append_reason(manual_reason, "source_url_not_in_snippets")
            if value is None:
                manual_required = True
                manual_reason = self._append_reason(manual_reason, "no_value")

            recent_5d = self._to_float(data.get("recent_5d"))
            total_120d = self._to_float(data.get("total_120d"))
            trend = self._normalize_trend(data.get("trend"))
            if is_fund_flow:
                if trend == "unknown" and value is not None:
                    trend = "inflow" if value > 0 else ("outflow" if value < 0 else "unknown")
                if recent_5d is None and value is not None:
                    recent_5d = value
                if recent_5d is None or total_120d is None:
                    manual_required = True
                    manual_reason = self._append_reason(manual_reason, "fund_flow_window_missing")

            note = "deepseek_structured" if value is not None else "deepseek_no_value"
            if manual_required and manual_reason:
                note = f"{note} {manual_reason}".strip()
            return {
                "value": value,
                "unit": unit_val,
                "source_url": source_url,
                "issuer": issuer_val,
                "issuer_match": issuer_match,
                "confidence": confidence,
                "note": note,
                "as_of_date": as_of_date,
                "report_period": report_period,
                "manual_required": manual_required,
                "manual_reason": manual_reason,
                "recent_5d": recent_5d,
                "total_120d": total_120d,
                "trend": trend,
            }
        except Exception as exc:  # pragma: no cover - 网络异常兜底
            logger.warning(f"DeepSeek 请求失败，使用 regex 兜底: {exc}")
            fallback_value, url = self._fallback_extract(
                snippets,
                indicator=indicator,
                unit_hint=unit_hint,
            )
            trend = "unknown"
            if is_fund_flow and fallback_value is not None:
                trend = "inflow" if fallback_value > 0 else ("outflow" if fallback_value < 0 else "unknown")
            return {
                "value": fallback_value,
                "unit": unit_hint,
                "source_url": url or first_url,
                "issuer_match": bool(issuer_hint and issuer_hint in combined_text),
                "confidence": 0.2,
                "note": f"deepseek_error:{exc}",
                "as_of_date": None,
                "report_period": None,
                "manual_required": True,
                "manual_reason": f"deepseek_error:{exc}",
                "recent_5d": None,
                "total_120d": None,
                "trend": trend,
            }


__all__ = ["DeepSeekExtractionAgent"]
