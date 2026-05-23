#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 2 Unified Enhancer (Tavily + DeepSeek)
-------------------------------------------
一次性跑完 Phase-E/Phase-A 的搜索任务规划、执行与写回。
当前实现聚焦“可运行的骨架”：
- 生成 SearchTaskContract JSONL（data/runs/YYYYMMDD/search_tasks_stage2.jsonl）
- 可选执行 Tavily 搜索 + DeepSeek 抽取，并把结果落到 market_data.json
- 计算派生字段 (m1_m2_spread 等)
- 输出日志/状态标志，方便 Stage3 在入口阻断

资金流向统一走 Tavily+DeepSeek；如检测到零值占位会写入 gap_monitor.json 供人工复核。
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import inspect
import json
import os
import sys
import time
from itertools import count
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from loguru import logger
try:  # pragma: no cover - 可选依赖
    import httpx
except Exception:  # noqa: W0703
    httpx = None

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None

from datasource.adapters.tavily_client import AsyncTavilyClient
try:  # pragma: no cover - 可选依赖
    from datasource.adapters.exa_client import AsyncExaClient
except Exception:  # noqa: W0703
    AsyncExaClient = None  # type: ignore
from datasource.cache.memory_cache import MemoryCache
from datasource.cache.sqlite_cache import SQLiteCache
from datasource.engines.deepseek_reasoner import DeepSeekExtractionAgent
try:
    from datasource.engines.stage2_lc_pipeline import run_tasks_lc  # type: ignore
except Exception:  # pragma: no cover - 可选依赖缺失时延迟报错
    run_tasks_lc = None  # type: ignore
from datasource.engines.stage2_task_planner import Stage2TaskPlanner
from datasource.utils.quality_metrics import write_quality_metrics
from datasource.utils.observability import build_observability_log, write_observability_log
from datasource.utils.coercion import is_stage2_number_placeholder
from datasource.utils.json_io import dump_json, load_json_strict
from datasource.utils.key_aliases import canonical_monetary_key, normalize_monetary_section
from datasource.utils.missing_items import append_missing_item, remove_missing_item, sync_top_level_missing_view
from datasource.utils.policy_rules import (
    evaluate_policy,
    write_policy_evaluation,
    load_policy_rules,
    is_estimated_allowlisted,
)
from datasource.utils.run_paths import build_run_paths_from_reference
from datasource.utils.run_snapshot import write_run_snapshot
from datasource.utils.source_conflicts import resolve_websearch_results, write_source_conflicts
from datasource.utils.source_trust import should_mark_official_non_estimated, units_compatible
from datasource.utils.text_markers import contains_ytd_marker
try:  # pragma: no cover - structured providers are optional for Stage2 wiring
    from datasource.providers.stage2_structured import StructuredProviderError, build_default_registry  # noqa: F401
except Exception:  # noqa: W0703
    StructuredProviderError = None  # type: ignore
    build_default_registry = None  # type: ignore

try:
    from .stage2_5_injector import (
        _default_fund_flow_metric_basis,
        _infer_fund_flow_source_tier,
        _infer_fund_flow_window_evidence,
        _normalize_fund_flow_estimation,
    )
except ImportError:  # pragma: no cover - 直接执行 scripts/stage2_unified_enhancer.py 时使用
    from stage2_5_injector import (  # type: ignore
        _default_fund_flow_metric_basis,
        _infer_fund_flow_source_tier,
        _infer_fund_flow_window_evidence,
        _normalize_fund_flow_estimation,
    )

CRITICAL_EXTRACT_KEYS = {
    "industrial",
    "industrial_sales",
    "bdi",
    "rrr",
    "reverse_repo",
    "mlf",
    "northbound",
    "southbound",
    "etf",
}


def _load_json(path: Path) -> Dict[str, Any]:
    return load_json_strict(path)


def _merge_missing_items(market_payload: Dict[str, Any]) -> None:
    """把 metadata.missing_items(dict) 扁平化到顶层 missing_items(list)，便于 Stage2 扫描"""
    sync_top_level_missing_view(market_payload)


def _apply_aliases(market_payload: Dict[str, Any], alias_map: Dict[str, str]) -> None:
    """将旧键名映射为新键名，避免历史数据导致空模板任务。只作用于内存数据，不改原文件。"""
    if not alias_map:
        return
    macro = market_payload.get("macro_indicators", {})
    for old, new in alias_map.items():
        if old in macro and new not in macro:
            macro[new] = macro.pop(old)
    market_payload["macro_indicators"] = macro

    miss = market_payload.get("missing_items")
    if isinstance(miss, list):
        for idx, item in enumerate(miss):
            if isinstance(item, dict):
                key = item.get("key")
                if key in alias_map:
                    miss[idx]["key"] = alias_map[key]
            elif item in alias_map:
                miss[idx] = alias_map[item]
        market_payload["missing_items"] = miss


def _warn_disable_extract_on_critical_tasks(tasks: List[Dict[str, Any]], disable_extract: bool) -> None:
    if not disable_extract:
        return
    affected = sorted(
        {
            str(task.get("indicator_key"))
            for task in tasks
            if str(task.get("indicator_key")) in CRITICAL_EXTRACT_KEYS
        }
    )
    if affected:
        logger.warning(
            "[Stage2] --disable-extract 已启用，关键指标可能落入 manual_required: {}；"
            "建议关键指标不要全局禁用 extract。",
            ",".join(affected),
        )


def _parse_date_str(text: str) -> Optional[datetime]:
    """尝试解析片段中的日期字符串为 UTC 时间，失败返回 None。"""
    if not text:
        return None
    text = str(text).strip()
    # 直接解析 ISO 格式
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # 匹配 YYYY-MM-DD / YYYY/MM/DD
    m = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        try:
            y, mo, d = map(int, m.groups())
            return datetime(y, mo, d, tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _extract_dates(snippets: Optional[List[Dict[str, Any]]]) -> List[datetime]:
    dates: List[datetime] = []
    for snip in snippets or []:
        # 优先使用 Tavily 的 published_date 字段
        dt_val = snip.get("published_date")
        if dt_val:
            parsed = _parse_date_str(dt_val)
            if parsed:
                dates.append(parsed)
                continue
        # 其次尝试从片段文本中提取日期
        content = snip.get("content") or snip.get("snippet") or ""
        parsed = _parse_date_str(content)
        if parsed:
            dates.append(parsed)
    return dates


def _is_stale(snippets: Optional[List[Dict[str, Any]]], max_age_days: Optional[int]) -> bool:
    """若所有可解析日期均早于 max_age_days，则判定为过期；无日期信息则返回 False。"""
    if not max_age_days:
        return False
    dates = _extract_dates(snippets)
    if not dates:
        return False
    now = datetime.now(timezone.utc)
    fresh_found = any((now - dt) <= timedelta(days=max_age_days) for dt in dates)
    if fresh_found:
        return False
    return True


def _prefer_fresh_snippets(snippets: Optional[List[Dict[str, Any]]], max_age_days: Optional[int]) -> List[Dict[str, Any]]:
    """优先返回满足时效性的片段；若没有新鲜片段则原样返回。"""
    if not snippets:
        return []
    if not max_age_days:
        return snippets
    fresh = []
    now = datetime.now(timezone.utc)
    for snip in snippets:
        dt_val = snip.get("published_date") or ""
        parsed = _parse_date_str(dt_val) if dt_val else None
        if not parsed:
            parsed = _parse_date_str(snip.get("content") or snip.get("snippet") or "")
        if parsed and (now - parsed) <= timedelta(days=max_age_days):
            fresh.append(snip)
    return fresh or snippets


_REPORT_MONTH_KEYS = {"industrial", "industrial_sales"}


def _extract_report_month(text: str) -> Optional[Tuple[int, int]]:
    """从文本中提取报告月份(年,月)，优先识别'YYYY年1-XX月'再识别'YYYY年MM月'。"""
    if not text:
        return None
    candidates: List[Tuple[int, int]] = []
    # 例如：2025年1-11月 / 2025年1—11月 / 2025年1至11月
    range_pat = re.compile(r"(20\d{2})\s*年\s*1\s*(?:-|—|~|至|到)\s*(\d{1,2})\s*月")
    for y, m in range_pat.findall(text):
        try:
            year = int(y)
            month = int(m)
            if 1 <= month <= 12:
                candidates.append((year, month))
        except Exception:
            continue
    # 例如：2025年12月 / 2025年12月份
    month_pat = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月")
    for y, m in month_pat.findall(text):
        try:
            year = int(y)
            month = int(m)
            if 1 <= month <= 12:
                candidates.append((year, month))
        except Exception:
            continue
    if not candidates:
        return None
    return max(candidates)


def _prefer_latest_report_snippets(
    snippets: Optional[List[Dict[str, Any]]], indicator_key: Optional[str]
) -> List[Dict[str, Any]]:
    """对月度宏观指标优先保留最新报告月份的片段。"""
    if not snippets:
        return []
    if not indicator_key or indicator_key not in _REPORT_MONTH_KEYS:
        return snippets
    tagged: List[Tuple[Tuple[int, int], Dict[str, Any]]] = []
    for snip in snippets:
        text = " ".join(
            [
                str(snip.get("title") or ""),
                str(snip.get("snippet") or ""),
                str(snip.get("content") or ""),
            ]
        )
        rep = _extract_report_month(text)
        if rep:
            tagged.append((rep, snip))
    if not tagged:
        return snippets
    latest = max(rep for rep, _ in tagged)
    filtered = [snip for rep, snip in tagged if rep == latest]
    return filtered or snippets


_TAVILY_LIMIT_STATUSES = {402, 403, 429, 432, 433}
_TAVILY_ERROR_TEXT_LIMIT = 500
_TAVILY_REQUEST_ID_HEADERS = (
    "x-request-id",
    "x-tavily-request-id",
    "x-tavily-trace-id",
    "request-id",
)


def _coerce_http_status(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_header_value(headers: Any, names: Tuple[str, ...]) -> Optional[str]:
    if not headers:
        return None
    for name in names:
        value = None
        try:
            value = headers.get(name)
        except AttributeError:
            value = None
        if value is None:
            try:
                value = headers.get(name.lower())
            except AttributeError:
                value = None
        if value is None:
            try:
                target = name.casefold()
                for header_name, header_value in headers.items():
                    if str(header_name).casefold() == target:
                        value = header_value
                        break
            except AttributeError:
                value = None
        if value:
            return str(value)
    return None


def _sanitize_tavily_error_text(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    sanitized = re.sub(
        r"(?i)(api[_-]?key[\"']?\s*[:=]\s*)[\"']?[^\"'\s,}]+",
        r"\1[redacted]",
        raw,
    )
    if len(sanitized) > _TAVILY_ERROR_TEXT_LIMIT:
        return sanitized[:_TAVILY_ERROR_TEXT_LIMIT] + "...[truncated]"
    return sanitized


def _tavily_error_metadata(source: Any) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    response = getattr(source, "response", None)

    if isinstance(source, dict):
        status = _coerce_http_status(source.get("status") or source.get("status_code"))
        message = " ".join(
            str(source.get(key) or "")
            for key in ("error", "message", "detail", "warning")
            if source.get(key)
        )
        request_id = source.get("request_id") or source.get("tavily_request_id")
        error_type = "tavily_response"
    else:
        status = _coerce_http_status(getattr(response, "status_code", None))
        message = getattr(response, "text", None) or str(source or "")
        request_id = _safe_header_value(
            getattr(response, "headers", None),
            _TAVILY_REQUEST_ID_HEADERS,
        )
        error_type = source.__class__.__name__

    if status is not None:
        metadata["tavily_http_status"] = status
    metadata["tavily_error_type"] = error_type
    sanitized_message = _sanitize_tavily_error_text(message)
    if sanitized_message:
        metadata["tavily_error_message"] = sanitized_message
    if request_id:
        metadata["tavily_request_id"] = str(request_id)
    return metadata


def _is_tavily_quota_error(exc: Exception) -> bool:
    status = _coerce_http_status(getattr(getattr(exc, "response", None), "status_code", None))
    if status in _TAVILY_LIMIT_STATUSES:
        return True
    return _text_indicates_quota_or_rate_limit(str(exc))


def _text_indicates_quota_or_rate_limit(text: Any) -> bool:
    msg = str(text or "").lower()
    return any(
        token in msg
        for token in [
            "quota",
            "rate limit",
            "rate-limit",
            "rate_limited",
            "ratelimit",
            "too many requests",
            "usage limit",
            "usage exceeded",
            "usage quota",
            "usage cap",
            "usage capped",
            "plan limit",
            "key limit",
            "paygo",
            "billing",
            "payment",
            "402",
            "403",
            "429",
            "432",
            "433",
        ]
    )


def _is_tavily_quota_response(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    status_int = _coerce_http_status(payload.get("status") or payload.get("status_code"))
    if status_int in _TAVILY_LIMIT_STATUSES:
        return True
    return _text_indicates_quota_or_rate_limit(
        " ".join(
            str(payload.get(key) or "")
            for key in ("error", "message", "detail", "warning")
        )
    )


def _is_environment_proxy_error(exc: Exception) -> bool:
    msg = f"{exc.__class__.__name__} {exc}".lower()
    strong_markers = [
        "using socks proxy",
        "socksio",
        "proxyconnect",
        "failed to connect to proxy",
        "cannot connect to proxy",
        "can't connect to proxy",
        "could not connect to proxy",
        "all_proxy",
        "http_proxy",
        "https_proxy",
    ]
    if any(token in msg for token in strong_markers):
        return True
    connectivity_markers = [
        "temporary failure in name resolution",
        "name resolution",
        "nameresolutionerror",
        "name or service not known",
        "getaddrinfo failed",
        "failed to resolve",
        "dns",
        "connecterror",
        "connectionerror",
        "connecttimeout",
        "readtimeout",
        "connect timeout",
        "connection timeout",
        "read operation timed out",
        "timed out",
        "all connection attempts failed",
        "ssl",
        "tls",
        "certificate",
        "connection reset",
        "connection refused",
        "connection aborted",
        "network is unreachable",
        "network error",
    ]
    if any(token in msg for token in connectivity_markers):
        return True
    if "socks" in msg and "proxy" in msg and re.search(r"socks[45]?h?://", msg):
        return True
    if "proxy error" not in msg and "proxyerror" not in msg:
        return False
    local_context = [
        "connect",
        "connection",
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "socks",
        "environment",
        "env",
        "proxy_url",
        "proxies",
    ]
    return any(token in msg for token in local_context)


def _build_environment_proxy_error_records(
    task: Dict[str, Any],
    exc: Exception,
    *,
    attempt_index: int = 0,
    elapsed_ms: int = 0,
    extraction_backend: str = "deepseek",
    query_attempts: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    now_ts = int(datetime.now().timestamp())
    query = task.get("query_used") or task.get("query") or task.get("indicator_key")
    note = f"environment_proxy_error:{exc}"
    source = "Stage2 manual_required"
    category = task.get("category") or task.get("stage_phase")
    task_payload = {
        **task,
        "category": category,
        "query": query,
        "query_used": task.get("query_used") or query,
        "query_attempts": query_attempts or task.get("query_attempts") or [],
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "source": source,
        "note": note,
        "environment_proxy_fast_switch": True,
    }
    extraction = {
        "value": None,
        "unit": task.get("unit"),
        "source_url": None,
        "confidence": 0.0,
        "note": note,
        "llm_error": str(exc),
        "environment_proxy_error": str(exc),
        "llm_latency_ms": 0,
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "environment_proxy_fast_switch": True,
    }
    task_record = {
        "task_id": task["task_id"],
        "indicator_key": task["indicator_key"],
        "category": category,
        "stage_phase": task["stage_phase"],
        "query": query,
        "search_backend": task.get("search_backend", "tavily"),
        "fund_flow_backend": task.get("fund_flow_backend"),
        "extraction_backend": extraction_backend,
        "source": source,
        "source_url": None,
        "confidence": 0.0,
        "error": str(exc),
        "llm_error": str(exc),
        "environment_proxy_error": str(exc),
        "llm_latency_ms": None,
        "attempt_index": attempt_index,
        "elapsed_ms": elapsed_ms,
        "created_at": task.get("created_at", now_ts),
        "finished_at": now_ts,
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "note": note,
        "raw_results": [],
        "environment_proxy_fast_switch": True,
        "result_type": "manual_required",
    }
    task_record.update(_structured_audit_fields_from_task(task))
    websearch_item = {
        "task_id": task["task_id"],
        "indicator_key": task["indicator_key"],
        "category": category,
        "stage_phase": task["stage_phase"],
        "query": query,
        "task": task_payload,
        "extraction": extraction,
        "extraction_backend": extraction_backend,
        "raw_results": [],
        "search_backend": task.get("search_backend", "tavily"),
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "source": source,
        "note": note,
        "environment_proxy_fast_switch": True,
        "result_type": "manual_required",
    }
    return task_record, websearch_item


def _exa_search_type(indicator_key: str) -> Optional[str]:
    keyword_keys = {
        "GC=F",
        "CL=F",
        "BZ=F",
        "HG=F",
        "BCOM",
        "GSG",
        "USDCNY",
        "USDCNH",
        "DXY",
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "US10Y",
        "CN10Y",
        "CN10Y_CDB",
        "000001",
        "000016",
        "000300",
        "399001",
        "399006",
    }
    if indicator_key in keyword_keys:
        return "keyword"
    return None


def _start_date_from_max_age(max_age_days: Optional[int]) -> Optional[str]:
    if not max_age_days:
        return None
    dt = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    return dt.strftime("%Y-%m-%d")


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if pct <= 0:
        return values[0]
    if pct >= 100:
        return values[-1]
    k = (len(values) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[int(k)]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def _score_stats(snippets: List[Dict[str, Any]]) -> Dict[str, Any]:
    scores = []
    for s in snippets:
        score = s.get("score")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    if not scores:
        return {
            "score_count": 0,
            "score_min": None,
            "score_p50": None,
            "score_p95": None,
            "score_max": None,
        }
    return {
        "score_count": len(scores),
        "score_min": min(scores),
        "score_p50": _percentile(scores, 50),
        "score_p95": _percentile(scores, 95),
        "score_max": max(scores),
    }


def _check_task_completeness(tasks: List[Dict[str, Any]]) -> List[str]:
    """检查任务的查询信息是否完整，返回警告列表"""
    warnings: List[str] = []
    for t in tasks:
        key = t.get("indicator_key")
        domains = t.get("preferred_domains") or []
        query = t.get("query")
        queries = t.get("queries") or []
        unit = t.get("unit")
        issuer = t.get("issuer")
        if not query and not queries:
            warnings.append(f"{key}: 缺少 query，已回退为 indicator_key")
        if not domains:
            warnings.append(f"{key}: 缺少 preferred_domains，可能命中词典/非目标站点")
        # 对宏观/货币/资金流向指标建议提供单位/发布机构
        if key in {"cpi", "ppi", "pmi", "pmi_new_orders", "industrial", "industrial_sales",
                   "gdp", "m1", "m2", "dr007", "reverse_repo", "rrr", "mlf", "reverse_repo_7d",
                   "northbound", "southbound", "etf"}:
            if not unit:
                warnings.append(f"{key}: 未设置 unit，建议补充以便抽取校验")
            if not issuer:
                warnings.append(f"{key}: 未设置 issuer（发布机构），建议补充筛选提示")
    return warnings


def _is_placeholder_number(val: Any) -> bool:
    return is_stage2_number_placeholder(val)


def _has_non_placeholder_value(market_payload: Dict[str, Any], indicator_key: str) -> (bool, Optional[float]):
    """
    检查 market_payload 中某指标是否已有有效值（非占位、非估算）。
    返回 (has_value, value)；value 仅用于记录，可能为 float。
    """
    # fund_flow
    fund_flow = market_payload.get("fund_flow", {})
    if indicator_key in fund_flow:
        entry = fund_flow[indicator_key] or {}
        if entry.get("is_estimated") is True:
            return False, None
        r5 = entry.get("recent_5d")
        t120 = entry.get("total_120d")
        if not _is_placeholder_number(r5) and not _is_placeholder_number(t120):
            return True, float(r5)
    # commodities
    for item in market_payload.get("commodities", []):
        if item.get("symbol") == indicator_key:
            if item.get("is_estimated") is True:
                return False, None
            price = item.get("current_price")
            if not _is_placeholder_number(price):
                return True, float(price)
    # forex
    for item in market_payload.get("forex", []):
        if item.get("pair") == indicator_key or item.get("symbol") == indicator_key:
            if item.get("is_estimated") is True:
                return False, None
            rate = item.get("current_rate")
            if not _is_placeholder_number(rate):
                return True, float(rate)
    # bonds
    for item in market_payload.get("bonds", []):
        if item.get("symbol") == indicator_key:
            if item.get("is_estimated") is True:
                return False, None
            yld = item.get("current_yield")
            if not _is_placeholder_number(yld):
                return True, float(yld)
    # macro_indicators
    macro = market_payload.get("macro_indicators", {})
    if indicator_key in macro:
        entry = macro[indicator_key] or {}
        if entry.get("is_estimated") is True:
            return False, None
        val = entry.get("current_value")
        if not _is_placeholder_number(val):
            return True, float(val)
    # monetary_policy
    monetary = market_payload.get("monetary_policy", {})
    if indicator_key in monetary:
        entry = monetary[indicator_key] or {}
        if entry.get("is_estimated") is True:
            return False, None
        val = entry.get("current_value")
        if not _is_placeholder_number(val):
            return True, float(val)
    return False, None

def _dump_json(payload: Dict[str, Any], path: Path, backup: bool = False) -> None:
    dump_json(payload, path, backup=backup)


def _append_task_log(task_log_path: Path, record: Dict[str, Any]) -> None:
    task_log_path.parent.mkdir(parents=True, exist_ok=True)
    with task_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _safe_number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


# 基于经验的合理区间，用于过滤明显离谱的抽取值（仅做人工复核标记）
_RANGE_RULES: Dict[str, tuple[float, float]] = {
    "USDCNY": (5.5, 9.5),
    "USDCNH": (5.5, 10.0),
    "DXY": (70.0, 140.0),
    "EURUSD": (0.5, 2.0),
    "GBPUSD": (0.8, 2.5),
    "USDJPY": (50.0, 200.0),
    "US10Y": (0.0, 15.0),
    "CN10Y": (0.0, 10.0),
    "CN10Y_CDB": (0.0, 12.0),
    "GC=F": (800.0, 5000.0),
    "CL=F": (0.1, 250.0),
    "BZ=F": (0.1, 250.0),
    "HG=F": (0.5, 8.0),
    "BCOM": (30.0, 300.0),
    "GSG": (10.0, 80.0),
    "bdi": (200.0, 10000.0),
    "rrr": (5.0, 20.0),
    "reverse_repo": (1.0, 5.0),
    "mlf": (1.5, 5.0),
}

_FOREX_UPSERT_META: Dict[str, str] = {
    "USDCNY": "USD/CNY在岸",
    "USDCNH": "USD/CNH离岸",
    "DXY": "DXY美元指数",
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
}

_COMMODITY_UPSERT_META: Dict[str, tuple[str, str]] = {
    "GC=F": ("COMEX黄金", "$/oz"),
    "CL=F": ("WTI原油", "$/barrel"),
    "BZ=F": ("Brent原油", "$/barrel"),
    "HG=F": ("COMEX铜", "$/lb"),
    "BCOM": ("BCOM指数", "点"),
    "GSG": ("GSG ETF", "USD"),
}

_BOND_UPSERT_META: Dict[str, str] = {
    "US10Y": "美国10年期国债",
    "CN10Y": "中国10年期国债",
    "CN10Y_CDB": "中国10年期国开债",
}


def _filter_by_domain(
    snippets: List[Dict[str, Any]],
    preferred: Optional[List[str]],
    indicator_key: Optional[str] = None,
    fallback_to_original: bool = True,
) -> List[Dict[str, Any]]:
    """过滤掉不在白名单域名中的搜索结果；若过滤后为空则回退原列表。"""
    if not preferred:
        return snippets
    noisy_path_tokens = {
        "investing.com": ["/news/"],
        "marketwatch.com": ["/story/", "/press-release/"],
    }
    # 仅对实时类指标启用路径噪音过滤，避免误伤宏观新闻类指标
    noisy_filter_keys = {
        "USDCNY",
        "USDCNH",
        "DXY",
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "US10Y",
        "CN10Y",
        "CN10Y_CDB",
        "GC=F",
        "CL=F",
        "BZ=F",
        "HG=F",
        "BCOM",
        "GSG",
        "bdi",
    }
    apply_noisy_filter = indicator_key in noisy_filter_keys if indicator_key else True
    filtered: List[Dict[str, Any]] = []
    for snip in snippets:
        url = snip.get("url") or ""
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc
            path = parsed.path or ""
            matched_domain = None
            for d in preferred:
                if netloc.endswith(d):
                    matched_domain = d
                    break
            if matched_domain:
                # drop obvious news pages for numeric indicators
                if apply_noisy_filter:
                    blocked_tokens = noisy_path_tokens.get(matched_domain)
                    if blocked_tokens and any(tok in path for tok in blocked_tokens):
                        continue
                filtered.append(snip)
        except Exception:
            continue
    if filtered:
        return filtered
    return snippets if fallback_to_original else []


def _official_extract_domains(extract_policy: Dict[str, Any]) -> List[str]:
    if not extract_policy.get("official_domains_only"):
        return []
    domains = extract_policy.get("official_domains") or []
    return [str(domain).strip().lower() for domain in domains if str(domain).strip()]


def _host_matches_official_domain(host: str, domain: str) -> bool:
    host = host.strip().lower().rstrip(".")
    domain = domain.strip().lower().rstrip(".")
    return bool(host and domain and (host == domain or host.endswith(f".{domain}")))


def _filter_by_official_extract_domain(
    snippets: List[Dict[str, Any]],
    official_domains: Optional[List[str]],
) -> List[Dict[str, Any]]:
    if not official_domains:
        return snippets
    domains = [str(domain).strip().lower().rstrip(".") for domain in official_domains if str(domain).strip()]
    if not domains:
        return snippets
    filtered: List[Dict[str, Any]] = []
    for snip in snippets:
        url = snip.get("url") or ""
        try:
            host = (urlparse(url).hostname or "").lower().rstrip(".")
        except Exception:
            continue
        if any(_host_matches_official_domain(host, domain) for domain in domains):
            filtered.append(snip)
    return filtered


def _snippet_blob(snippet: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(snippet.get("title") or ""),
            str(snippet.get("snippet") or ""),
            str(snippet.get("content") or ""),
            str(snippet.get("url") or ""),
        ]
    ).lower()


def _filter_by_keyword_rules(
    snippets: List[Dict[str, Any]],
    required_keywords: Optional[List[str]] = None,
    exclude_keywords: Optional[List[str]] = None,
    fallback_to_original: bool = True,
) -> List[Dict[str, Any]]:
    if not snippets:
        return []
    required = [str(token).lower() for token in (required_keywords or []) if str(token).strip()]
    excluded = [str(token).lower() for token in (exclude_keywords or []) if str(token).strip()]
    filtered: List[Dict[str, Any]] = []
    for snip in snippets:
        text = _snippet_blob(snip)
        if excluded and any(token in text for token in excluded):
            continue
        if required and not any(token in text for token in required):
            continue
        filtered.append(snip)
    if filtered:
        return filtered
    return snippets if fallback_to_original else []


def _snippets_have_issuer(
    snippets: List[Dict[str, Any]],
    issuer_hint: Optional[str],
    issuer_aliases: Optional[List[str]] = None,
) -> bool:
    if not issuer_hint and not issuer_aliases:
        return False
    hint_tokens = [str(issuer_hint or "").lower()] + [
        str(alias).lower() for alias in (issuer_aliases or []) if str(alias).strip()
    ]
    hint_tokens = [token for token in hint_tokens if token]
    if not hint_tokens:
        return False
    for snip in snippets:
        text = _snippet_blob(snip)
        if any(token in text for token in hint_tokens):
            return True
    return False


def _snippets_have_expected_period(
    snippets: List[Dict[str, Any]],
    expected_period_tokens: Optional[List[str]],
) -> bool:
    tokens = [str(token).lower() for token in (expected_period_tokens or []) if str(token).strip()]
    if not tokens:
        return False
    for snip in snippets:
        text = _snippet_blob(snip)
        if any(token in text for token in tokens):
            return True
    return False


def _strict_indicator_tokens(indicator_key: Optional[str]) -> List[str]:
    key = str(indicator_key or "").strip().lower()
    mapping = {
        "gc=f": ["gc=f", "gold", "黄金", "comex"],
        "cl=f": ["cl=f", "wti", "原油", "nymex"],
        "bz=f": ["bz=f", "brent", "布伦特", "ice"],
        "hg=f": ["hg=f", "copper", "铜", "comex"],
        "bcom": ["bcom", "彭博商品指数"],
        "gsg": ["gsg"],
        "usdcny": ["usdcny", "usd/cny", "在岸", "中间价", "美元", "人民币"],
        "usdcnh": ["usdcnh", "usd/cnh", "离岸"],
        "dxy": ["dxy", "美元指数"],
        "cn10y_cdb": ["国开债", "国开", "开发债", "政策性金融债", "中债估值", "cdb", "国家开发银行"],
        "rrr": ["rrr", "存款准备金率"],
        "reverse_repo": ["逆回购", "reverse repo"],
        "mlf": ["mlf", "中期借贷便利"],
    }
    return [token.lower() for token in mapping.get(key, []) if token]


def _pattern_hits(value: str, patterns: Optional[List[str]]) -> List[str]:
    text = str(value or "").lower()
    hits: List[str] = []
    for pattern in patterns or []:
        needle = str(pattern or "").strip()
        if needle and needle.lower() in text:
            hits.append(needle)
    return hits


def _usage_evidence_score(snippet: Dict[str, Any], keywords: Optional[List[str]]) -> int:
    blob = _snippet_blob(snippet)
    return sum(1 for keyword in keywords or [] if str(keyword or "").strip().lower() in blob)


def _value_evidence_score(snippet: Dict[str, Any], task: Dict[str, Any]) -> int:
    blob = _snippet_blob(snippet).lower()
    if not blob:
        return 0
    non_value_hits = sum(
        1
        for token in (
            "methodology",
            "calculation",
            "weights",
            "rebalance",
            "contract specs",
            "contract specifications",
            "rulebook",
            "target weights",
            "annual rebalance",
            "contract unit",
            "minimum price fluctuation",
            "fact card",
        )
        if token in blob
    )
    if non_value_hits >= 2:
        return 0
    unit = str(task.get("unit") or "").lower()
    indicator = str(task.get("indicator_key") or "").lower()
    numeric_hits = len(re.findall(r"(?<!\d)(?:\d{1,4}(?:,\d{3})*|\d+)(?:\.\d+)?(?!\d)", blob))
    if numeric_hits == 0:
        return 0
    score = min(numeric_hits, 3)
    if unit and unit.replace("$", "usd") in blob.replace("$", "usd"):
        score += 2
    if any(token in blob for token in ("price", "level", "last", "settle", "settlement", "收盘", "结算", "点位", "报价")):
        score += 2
    if non_value_hits:
        score -= max(4, non_value_hits * 3)
    if indicator and indicator in blob:
        score += 1
    return max(0, score)


def _final_snippet_diagnostics(task: Dict[str, Any], snippets: List[Dict[str, Any]]) -> Dict[str, Any]:
    good_url_patterns = task.get("good_url_patterns") or []
    bad_url_patterns = task.get("bad_url_patterns") or []
    evidence_keywords = task.get("evidence_keywords") or []
    usage_evidence_score = 0
    value_evidence_score = 0
    good_url_hit_count = 0
    bad_url_hit_count = 0
    for snippet in snippets:
        url_blob = f"{snippet.get('url') or ''} {_snippet_blob(snippet)}"
        if _pattern_hits(url_blob, good_url_patterns):
            good_url_hit_count += 1
        if _pattern_hits(url_blob, bad_url_patterns):
            bad_url_hit_count += 1
        usage_evidence_score += _usage_evidence_score(snippet, evidence_keywords)
        value_evidence_score += _value_evidence_score(snippet, task)
    return {
        "score_stats": _score_stats(snippets),
        "trusted_count": len(snippets),
        "usable_count": len(snippets),
        "issuer_hit": _snippets_have_issuer(
            snippets,
            issuer_hint=task.get("issuer"),
            issuer_aliases=task.get("issuer_aliases"),
        ),
        "period_hit": _snippets_have_expected_period(snippets, task.get("expected_period_tokens")),
        "usage_evidence_score": usage_evidence_score,
        "value_evidence_score": value_evidence_score,
        "good_url_hit_count": good_url_hit_count,
        "bad_url_hit_count": bad_url_hit_count,
    }


def _selected_reason_from_diagnostics(
    diagnostics: Dict[str, Any],
    unusable_reason: Optional[str] = None,
) -> str:
    score_stats = diagnostics.get("score_stats") or {}
    return (
        f"trusted={diagnostics.get('trusted_count', 0)} usable={diagnostics.get('usable_count', 0)} "
        f"issuer_hit={diagnostics.get('issuer_hit', False)} period_hit={diagnostics.get('period_hit', False)} "
        f"usage_evidence={diagnostics.get('usage_evidence_score', 0)} "
        f"value_evidence={diagnostics.get('value_evidence_score', 0)} "
        f"good_url={diagnostics.get('good_url_hit_count', 0)} "
        f"bad_url={diagnostics.get('bad_url_hit_count', 0)} "
        f"score_max={score_stats.get('score_max')}"
        + (f" reason={unusable_reason}" if unusable_reason else "")
    )


def _candidate_query_quality(
    task: Dict[str, Any],
    candidate: Dict[str, Any],
    snippets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    preferred_domains = candidate.get("preferred_domains") or task.get("preferred_domains")
    required_keywords = list(task.get("required_keywords") or [])
    required_keywords.extend(candidate.get("required_keywords") or [])
    exclude_keywords = list(task.get("exclude_keywords") or [])
    exclude_keywords.extend(candidate.get("exclude_keywords") or [])
    strict_required_keywords = bool(
        candidate.get("strict_required_keywords", task.get("strict_required_keywords", False))
    )
    strict_issuer_match = bool(candidate.get("strict_issuer_match", task.get("strict_issuer_match", False)))

    trusted = _filter_by_domain(
        snippets,
        preferred_domains,
        indicator_key=task.get("indicator_key"),
        fallback_to_original=False,
    )
    trusted_or_raw = trusted or list(snippets)
    fresh = _prefer_fresh_snippets(trusted_or_raw, task.get("max_age_days"))
    latest = _prefer_latest_report_snippets(fresh, task.get("indicator_key"))
    keyword_filtered = _filter_by_keyword_rules(
        latest,
        required_keywords=required_keywords,
        exclude_keywords=exclude_keywords,
        fallback_to_original=False,
    )
    trusted_count = len(trusted)
    raw_for_checks = keyword_filtered or latest or trusted_or_raw
    issuer_hit = _snippets_have_issuer(
        raw_for_checks,
        issuer_hint=task.get("issuer"),
        issuer_aliases=task.get("issuer_aliases"),
    )
    period_hit = _snippets_have_expected_period(raw_for_checks, task.get("expected_period_tokens"))
    unusable_reason: Optional[str] = None
    strict_indicator_tokens = _strict_indicator_tokens(task.get("indicator_key"))
    strict_indicator_hit = not strict_indicator_tokens or any(
        token in _snippet_blob(snip) for token in strict_indicator_tokens for snip in raw_for_checks
    )
    if strict_required_keywords and ((required_keywords and not keyword_filtered) or not strict_indicator_hit):
        unusable_reason = "strict_keyword_miss"
    elif strict_issuer_match and not issuer_hit:
        unusable_reason = "strict_issuer_miss"

    usable = [] if unusable_reason else (keyword_filtered or latest or trusted or list(snippets))
    good_url_patterns = candidate.get("good_url_patterns") or task.get("good_url_patterns") or []
    bad_url_patterns = candidate.get("bad_url_patterns") or task.get("bad_url_patterns") or []
    evidence_keywords = candidate.get("evidence_keywords") or task.get("evidence_keywords") or []

    def _score_usable(current: List[Dict[str, Any]]) -> Dict[str, Any]:
        scored: List[Dict[str, Any]] = []
        for snippet in current:
            url_blob = f"{snippet.get('url') or ''} {_snippet_blob(snippet)}"
            bad_hits = _pattern_hits(url_blob, bad_url_patterns)
            good_hits = _pattern_hits(url_blob, good_url_patterns)
            evidence_score = _usage_evidence_score(snippet, evidence_keywords)
            value_score = _value_evidence_score(snippet, task)
            scored.append(
                {
                    "snippet": snippet,
                    "bad_hits": bad_hits,
                    "good_hits": good_hits,
                    "evidence_score": evidence_score,
                    "value_score": value_score,
                }
            )
        return {
            "scored": scored,
            "bad_url_hit_count": sum(1 for item in scored if item["bad_hits"]),
            "good_url_hit_count": sum(1 for item in scored if item["good_hits"]),
            "usage_evidence_score": sum(int(item["evidence_score"]) for item in scored),
            "value_evidence_score": sum(int(item["value_score"]) for item in scored),
        }

    usable_scores = _score_usable(usable)
    scored_usable: List[Dict[str, Any]] = usable_scores["scored"]
    original_bad_url_hit_count = int(usable_scores["bad_url_hit_count"])

    if any(item["bad_hits"] for item in scored_usable) and any(not item["bad_hits"] for item in scored_usable):
        kept = [item for item in scored_usable if not item["bad_hits"]]
        usable = [item["snippet"] for item in kept]
        usable_scores = _score_usable(usable)
        scored_usable = usable_scores["scored"]

    if usable and not unusable_reason:
        issuer_hit = _snippets_have_issuer(
            usable,
            issuer_hint=task.get("issuer"),
            issuer_aliases=task.get("issuer_aliases"),
        )
        period_hit = _snippets_have_expected_period(usable, task.get("expected_period_tokens"))
        if strict_issuer_match and not issuer_hit:
            unusable_reason = "strict_issuer_miss"
            usable = []
            usable_scores = _score_usable(usable)

    requires_value_evidence = bool(task.get("required_output_fields") or task.get("evidence_keywords"))
    high_score = [s for s in usable if s.get("score") is None or s.get("score", 0) >= 0.5]
    if high_score:
        high_score_scores = _score_usable(high_score)
        high_score_value = int(high_score_scores["value_evidence_score"])
        current_value = int(usable_scores["value_evidence_score"])
        if not requires_value_evidence or high_score_value >= current_value or current_value <= 0:
            usable = high_score
            usable_scores = high_score_scores
            issuer_hit = _snippets_have_issuer(
                usable,
                issuer_hint=task.get("issuer"),
                issuer_aliases=task.get("issuer_aliases"),
            )
            period_hit = _snippets_have_expected_period(usable, task.get("expected_period_tokens"))

    usage_evidence_score = int(usable_scores["usage_evidence_score"])
    value_evidence_score = int(usable_scores["value_evidence_score"])
    good_url_hit_count = int(usable_scores["good_url_hit_count"])
    bad_url_hit_count = max(original_bad_url_hit_count, int(usable_scores["bad_url_hit_count"]))

    if usable and not unusable_reason and requires_value_evidence and value_evidence_score <= 0:
        unusable_reason = "value_evidence_miss"
        usable = []
        usable_scores = _score_usable(usable)
        usage_evidence_score = int(usable_scores["usage_evidence_score"])
        value_evidence_score = int(usable_scores["value_evidence_score"])
        good_url_hit_count = int(usable_scores["good_url_hit_count"])
        bad_url_hit_count = max(original_bad_url_hit_count, int(usable_scores["bad_url_hit_count"]))

    score_stats = _score_stats(usable)
    usable_count = len(usable)
    quality_score = (
        trusted_count * 100.0
        + usable_count * 15.0
        + (25.0 if period_hit else 0.0)
        + (15.0 if issuer_hit else 0.0)
        + ((score_stats.get("score_max") or 0.0) * 10.0)
        + usage_evidence_score * 12.0
        + value_evidence_score * 18.0
        + good_url_hit_count * 25.0
        - bad_url_hit_count * 140.0
    )
    if unusable_reason:
        quality_score = -1.0
    return {
        "snippets": usable,
        "trusted_count": trusted_count,
        "usable_count": usable_count,
        "issuer_hit": issuer_hit,
        "period_hit": period_hit,
        "score_stats": score_stats,
        "quality_score": quality_score,
        "usage_evidence_score": usage_evidence_score,
        "value_evidence_score": value_evidence_score,
        "good_url_hit_count": good_url_hit_count,
        "bad_url_hit_count": bad_url_hit_count,
        "unusable_reason": unusable_reason,
        "selected_reason": _selected_reason_from_diagnostics(
            {
                "score_stats": score_stats,
                "trusted_count": trusted_count,
                "usable_count": usable_count,
                "issuer_hit": issuer_hit,
                "period_hit": period_hit,
                "usage_evidence_score": usage_evidence_score,
                "value_evidence_score": value_evidence_score,
                "good_url_hit_count": good_url_hit_count,
                "bad_url_hit_count": bad_url_hit_count,
            },
            unusable_reason,
        ),
    }


def _regex_fallback(snippets: List[Dict[str, Any]], indicator: str) -> Optional[float]:
    """
    针对常见官网文本的兜底数值提取。
    适用：industrial/industrial_sales/bdi/mlf/rrr/reverse_repo 等。
    """
    if not snippets:
        return None
    text = " ".join(
        str(s.get("content") or s.get("snippet") or "") for s in snippets
    )
    ind = indicator.lower()
    patterns: List[str] = []
    if ind == "industrial":
        patterns = [
            r"(?:规模以上)?工业增加值[^\\d]{0,20}(?:同比|增长)[^\\d]{0,10}([-+]?\\d+(?:\\.\\d+)?)\\s*%",
        ]
    elif ind == "industrial_sales":
        patterns = [
            r"(?:规模以上)?工业企业[^\\d]{0,20}(?:营业收入|营收)[^\\d]{0,20}(?:同比|增长)[^\\d]{0,10}([-+]?\\d+(?:\\.\\d+)?)\\s*%",
        ]
    elif ind == "mlf":
        patterns = [r"(?:mlf|中期借贷便利)[^\\d]*([-+]?\\d+(?:\\.\\d+)?)\\s*[%％]"]
    elif ind == "reverse_repo":
        patterns = [r"(?:逆回购|repo)[^\\d]*([-+]?\\d+(?:\\.\\d+)?)\\s*%"]
    elif ind == "rrr":
        patterns = [r"(?:存款准备金率|rrr|降准)[^\\d]*([-+]?\\d+(?:\\.\\d+)?)\\s*%"]
    elif ind == "bdi":
        patterns = [r"(?:BDI|波罗的海)[^\\d]*([-+]?\\d{3,5}(?:\\.\\d+)?)"]
    elif ind == "usdcny":
        patterns = [
            r"(?:USDCNY|USD/CNY|USD CNY|美元/人民币|美元人民币)[^\\d]*([0-9]+\\.\\d{2,6})",
            r"1(?:\\.0+)?\\s*USD\\s*=\\s*([0-9]+\\.\\d{2,6})\\s*CNY",
        ]
    elif ind == "usdcnh":
        patterns = [
            r"(?:USDCNH|USD/CNH|USD CNH|离岸人民币)[^\\d]*([0-9]+\\.\\d{2,6})",
            r"1(?:\\.0+)?\\s*USD\\s*=\\s*([0-9]+\\.\\d{2,6})\\s*CNH",
        ]
    elif ind == "dxy":
        patterns = [
            r"(?:DXY|美元指数|Dollar Index|US Dollar Index)[^\\d]*([0-9]{2,3}(?:\\.\\d+)?)",
            r"([0-9]{2,3}(?:\\.\\d+)?)\\s*(?:DXY|美元指数|Dollar Index)",
        ]
    elif ind == "us10y":
        patterns = [r"(?:US10Y|美国10年|10年期国债|10-year)[^\\d]*([0-9]+\\.\\d{2,3})\\s*%?"]
    elif ind == "cn10y":
        patterns = [
            r"(?:中国10年|10年期国债|China\\s*10\\s*Y|10[- ]?year|10y)[^\\d]*([0-9]+\\.\\d{2,3})\\s*%?",
            r"([0-9]+\\.\\d{2,3})\\s*%?[^\\d]*(?:China\\s*10\\s*Y|10[- ]?year|10y)",
        ]
    elif ind == "cn10y_cdb":
        patterns = [r"(?:国开|国开债|开发债)[^\\d]*([0-9]+\\.\\d{2,3})\\s*%?"]
    else:
        return None

    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                continue
    return None


def _collect_snippet_text(snippets: List[Dict[str, Any]]) -> str:
    return " ".join(
        str(s.get("content") or s.get("snippet") or "") for s in snippets
    )


def _find_number_by_patterns(
    text: str,
    patterns: List[str],
    low: Optional[float] = None,
    high: Optional[float] = None,
    min_decimals: Optional[int] = None,
    require_nonzero_decimal: bool = False,
) -> Optional[float]:
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE | re.DOTALL):
            num = m.group(1)
            if "." in num:
                decimals = num.split(".", 1)[1]
                if min_decimals is not None and len(decimals) < min_decimals:
                    continue
                if require_nonzero_decimal and set(decimals) <= {"0"}:
                    continue
            elif min_decimals is not None:
                continue
            try:
                val = float(num)
            except Exception:
                continue
            if low is not None and val < low:
                continue
            if high is not None and val > high:
                continue
            return val
    return None


def _extract_structured_value(snippets: List[Dict[str, Any]], indicator: str) -> Optional[float]:
    if not snippets:
        return None
    text = _collect_snippet_text(snippets)
    ind = indicator.lower()
    if ind == "usdcny":
        patterns = [
            r"(?:USDCNY|USD/CNY|USD CNY|美元/人民币|美元人民币|在岸人民币)[^\\d]{0,12}([0-9]+\\.\\d{2,6})",
            r"1(?:\\.0+)?\\s*USD\\s*=\\s*([0-9]+\\.\\d{2,6})\\s*CNY",
        ]
        return _find_number_by_patterns(text, patterns, 5.5, 9.5, min_decimals=2, require_nonzero_decimal=True)
    if ind == "usdcnh":
        patterns = [
            r"(?:USDCNH|USD/CNH|USD CNH|离岸人民币|offshore)[^\\d]{0,12}([0-9]+\\.\\d{2,6})",
            r"1(?:\\.0+)?\\s*USD\\s*=\\s*([0-9]+\\.\\d{2,6})\\s*CNH",
        ]
        return _find_number_by_patterns(text, patterns, 5.5, 10.0, min_decimals=2, require_nonzero_decimal=True)
    if ind == "dxy":
        patterns = [
            r"(?:DXY|美元指数|Dollar Index|US Dollar Index)[^\\d]{0,12}([0-9]{2,3}\\.\\d{1,3})",
            r"([0-9]{2,3}\\.\\d{1,3})[^\\d]{0,12}(?:DXY|美元指数|Dollar Index|US Dollar Index)",
        ]
        return _find_number_by_patterns(text, patterns, 70.0, 140.0, min_decimals=1)
    if ind == "cn10y":
        patterns = [
            r"(?:China\\s*10\\s*Y|10[- ]?year|10y|10年|国债收益率)[^\\d]{0,12}([0-9]+\\.\\d{2,3})",
            r"([0-9]+\\.\\d{2,3})[^\\d]{0,12}(?:China\\s*10\\s*Y|10[- ]?year|10y|10年)",
        ]
        return _find_number_by_patterns(text, patterns, 0.0, 10.0, min_decimals=2)
    if ind == "rrr":
        patterns = [
            r"(?:存款准备金率|RRR|reserve requirement)[^\\d]{0,12}([0-9]+\\.\\d+)\\s*%?",
        ]
        return _find_number_by_patterns(text, patterns, 5.0, 20.0, min_decimals=1)
    if ind == "mlf":
        patterns = [
            r"(?:MLF|中期借贷便利|medium-term lending facility)[^\\d]{0,12}([0-9]+\\.\\d+)\\s*%?",
        ]
        return _find_number_by_patterns(text, patterns, 1.5, 5.0, min_decimals=1)
    if ind == "reverse_repo":
        patterns = [
            r"(?:逆回购|reverse repo|repo)[^\\d]{0,12}([0-9]+\\.\\d+)\\s*%?",
        ]
        return _find_number_by_patterns(text, patterns, 1.0, 5.0, min_decimals=1)
    return None


def _extract_flow_value(snippets: List[Dict[str, Any]], indicator: str) -> (Optional[float], Optional[str]):
    if not snippets:
        return None, None
    text = _collect_snippet_text(snippets)
    flow_patterns = [
        r"(?:北向资金|northbound|南向资金|southbound)[^\\d]{0,80}(?:净流入|净流出|净买入|net inflow|net outflow|net buy)[^\\d+\\-]{0,12}([+-]?\\d+(?:\\.\\d+)?)\\s*(亿元|亿港元|billion|bn)",
        r"(?:net inflow|net outflow|净流入|净流出|净买入)[^\\d+\\-]{0,12}([+-]?\\d+(?:\\.\\d+)?)\\s*(亿元|亿港元|billion|bn)",
    ]
    for pat in flow_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        try:
            val = float(m.group(1))
        except Exception:
            continue
        seg = m.group(0).lower()
        direction = None
        if any(tok in seg for tok in ["净流出", "net outflow", "outflow", "卖出"]):
            direction = "outflow"
        elif any(tok in seg for tok in ["净流入", "net inflow", "net buy", "买入", "流入"]):
            direction = "inflow"
        if direction == "outflow" and val > 0:
            val = -abs(val)
        if direction == "inflow" and val < 0:
            val = abs(val)
        return val, direction
    unit_matches = re.findall(r"([+-]?\\d+(?:\\.\\d+)?)\\s*(亿元|亿港元|billion|bn)", text, flags=re.IGNORECASE)
    if unit_matches:
        try:
            vals = [float(v[0]) for v in unit_matches]
        except Exception:
            vals = []
        if vals:
            val = max(vals, key=lambda x: abs(x))
            return val, None
    return None, None


def _refine_extraction_value(
    extraction: Dict[str, Any], task: Dict[str, Any], snippets: Optional[List[Dict[str, Any]]]
) -> None:
    if not snippets:
        return
    indicator = (task.get("indicator_key") or "").lower()
    note = extraction.get("note") or ""
    confidence = extraction.get("confidence", 0.0) or 0.0
    if not (isinstance(note, str) and note.startswith("regex")) and confidence >= 0.6:
        return
    if indicator in {"northbound", "southbound"}:
        flow_val, direction = _extract_flow_value(snippets, indicator)
        if flow_val is not None:
            extraction["value"] = flow_val
            if direction:
                dir_cn = "流出" if direction == "outflow" else "流入"
                extraction["note"] = ((extraction.get("note") or "") + f" structured_dir:{direction} {dir_cn}").strip()
            else:
                extraction["note"] = ((extraction.get("note") or "") + " structured_value").strip()
        return
    refined = _extract_structured_value(snippets, indicator)
    if refined is not None:
        extraction["value"] = refined
        extraction["note"] = ((extraction.get("note") or "") + " structured_refine").strip()


def _contains_ytd_marker(text: str) -> bool:
    return contains_ytd_marker(text)


def _infer_rrr_type(text: str) -> Optional[str]:
    if not text:
        return None
    if "加权" in text or "weighted" in text.lower():
        return "weighted"
    if "法定" in text or "statutory" in text.lower():
        return "statutory"
    return None


def _infer_report_period(text: str) -> Optional[str]:
    rep = _extract_report_month(text)
    if not rep:
        return None
    year, month = rep
    return f"{year}-{month:02d}"


def _infer_as_of_date(snippets: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    if not snippets:
        return None
    dates: List[datetime] = []
    for snip in snippets:
        for field in ("published_date", "date"):
            parsed = _parse_date_str(snip.get(field) or "")
            if parsed:
                dates.append(parsed)
                break
        if not parsed:
            parsed = _parse_date_str(snip.get("content") or snip.get("snippet") or "")
            if parsed:
                dates.append(parsed)
    if not dates:
        return None
    latest = max(dates)
    return latest.date().isoformat()


def _augment_extraction_metadata(
    extraction: Dict[str, Any],
    task: Dict[str, Any],
    snippets: Optional[List[Dict[str, Any]]],
) -> None:
    if not extraction or not snippets:
        return
    indicator_key = task.get("indicator_key")
    text = " ".join(
        [
            str(s.get("title") or "")
            + " "
            + str(s.get("snippet") or "")
            + " "
            + str(s.get("content") or "")
            for s in (snippets or [])
        ]
    )
    if indicator_key == "industrial":
        value_type = "yoy_ytd" if _contains_ytd_marker(text) else "yoy_month"
        if value_type:
            extraction.setdefault("value_type", value_type)
        report_period = _infer_report_period(text)
        if report_period:
            extraction.setdefault("report_period", report_period)
            extraction.setdefault("as_of_date", report_period)
    if indicator_key in {"rrr", "reserve_ratio"}:
        rrr_type = _infer_rrr_type(text)
        if rrr_type:
            extraction.setdefault("rrr_type", rrr_type)
    if indicator_key in {"northbound", "southbound", "etf", "margin"}:
        if not extraction.get("unit") and any(token in text for token in ("亿元", "亿港元", "亿")):
            extraction["unit"] = "亿元"
        metric_basis = _default_fund_flow_metric_basis(str(indicator_key), extraction)
        extraction.setdefault("metric_basis", metric_basis)
        recent_value = _safe_number(extraction.get("recent_5d"))
        total_value = _safe_number(extraction.get("total_120d"))
        if _safe_number(extraction.get("value")) is None and recent_value is not None:
            extraction["value"] = recent_value
        source_snippets = _snippets_for_source_url(snippets, extraction.get("source_url"))
        direct_evidence = {"direct_window", "direct_daily_series", "direct_balance_delta"}
        field_retry_evidence = extraction.setdefault("field_retry_evidence", {})
        if not isinstance(field_retry_evidence, dict):
            field_retry_evidence = {}
            extraction["field_retry_evidence"] = field_retry_evidence
        recent_evidence = None
        total_evidence = None
        if recent_value is not None:
            recent_evidence = _field_retry_window_evidence(
                "recent_5d",
                str(indicator_key),
                extraction,
                source_snippets,
                metric_basis,
                recent_value,
            )
            field_retry_evidence.setdefault(
                "recent_5d",
                {
                    "source_url": extraction.get("source_url"),
                    "source_tier": _infer_fund_flow_source_tier(extraction),
                    "window_evidence": recent_evidence,
                    "metric_basis": metric_basis,
                },
            )
        if total_value is not None:
            total_evidence = _field_retry_window_evidence(
                "total_120d",
                str(indicator_key),
                extraction,
                source_snippets,
                metric_basis,
                total_value,
            )
            field_retry_evidence.setdefault(
                "total_120d",
                {
                    "source_url": extraction.get("source_url"),
                    "source_tier": _infer_fund_flow_source_tier(extraction),
                    "window_evidence": total_evidence,
                    "metric_basis": metric_basis,
                },
            )
        if recent_value is not None and total_value is not None:
            if (
                str(indicator_key) == "margin"
                and recent_evidence == "direct_balance_delta"
                and total_evidence == "direct_balance_delta"
            ):
                extraction["window_evidence"] = "direct_balance_delta"
            elif recent_evidence in direct_evidence and total_evidence in direct_evidence:
                extraction["window_evidence"] = "direct_window"
            else:
                extraction["window_evidence"] = "unknown"
    as_of_date = _infer_as_of_date(snippets)
    if as_of_date:
        extraction.setdefault("as_of_date", as_of_date)


def _first_snippet_url(snippets: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    for snippet in snippets or []:
        url = snippet.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _normalize_url_for_evidence(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _snippets_for_source_url(
    snippets: Optional[List[Dict[str, Any]]],
    source_url: Any,
) -> List[Dict[str, Any]]:
    target = _normalize_url_for_evidence(source_url)
    if not target:
        return []
    return [
        snippet
        for snippet in (snippets or [])
        if isinstance(snippet, dict)
        and _normalize_url_for_evidence(snippet.get("url")) == target
    ]


def _snippet_text(snippet: Dict[str, Any]) -> str:
    return " ".join(
        str(snippet.get(field) or "")
        for field in ("title", "snippet", "content", "raw_content")
    )


def _snippet_contains_number(snippet: Dict[str, Any], value: Optional[float]) -> bool:
    if value is None:
        return False
    text = _snippet_text(snippet)
    for match in re.finditer(
        r"([+-]?\d[\d,]*(?:\.\d+)?)\s*(亿港元|亿元|亿|billion|bn)",
        text,
        flags=re.IGNORECASE,
    ):
        try:
            candidate = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if abs(candidate - value) <= max(1e-6, abs(value) * 1e-9):
            return True
    return False


def _resolve_field_retry_evidence_source(
    field_extraction: Dict[str, Any],
    snippets: Optional[List[Dict[str, Any]]],
    value: Optional[float],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    candidates = [snip for snip in (snippets or []) if isinstance(snip, dict)]
    if not candidates:
        source_url = field_extraction.get("source_url")
        return (str(source_url).strip() if source_url else None), []

    source_url_raw = field_extraction.get("source_url")
    source_url = str(source_url_raw).strip() if isinstance(source_url_raw, str) else ""
    source_snippets = [
        snip for snip in candidates if str(snip.get("url") or "").strip() == source_url
    ]
    source_value_snippets = [
        snip for snip in source_snippets if _snippet_contains_number(snip, value)
    ]
    if source_value_snippets:
        return source_url, source_value_snippets

    value_snippets = [snip for snip in candidates if _snippet_contains_number(snip, value)]
    if value_snippets:
        value_url = _first_snippet_url(value_snippets)
        same_url_value_snippets = [
            snip for snip in value_snippets if str(snip.get("url") or "").strip() == value_url
        ]
        return value_url, same_url_value_snippets or value_snippets

    if source_snippets:
        return source_url, source_snippets
    first_url = _first_snippet_url(candidates)
    return first_url, candidates[:1]


def _field_retry_window_evidence(
    field_scope: str,
    indicator_key: str,
    field_extraction: Dict[str, Any],
    snippets: Optional[List[Dict[str, Any]]],
    metric_basis: str,
    value: Optional[float],
) -> str:
    if not any(_snippet_contains_number(snip, value) for snip in (snippets or [])):
        return "unknown"

    explicit = str(field_extraction.get("window_evidence") or "").strip().lower()
    if explicit in {"direct_window", "direct_daily_series", "direct_balance_delta"}:
        return explicit

    text = " ".join(_snippet_text(s) for s in (snippets or [])).lower()
    if any(token in text for token in ("未披露", "未显示", "没有披露", "无法披露")):
        return "unknown"

    if str(indicator_key).lower() == "margin" and str(metric_basis).lower() == "balance_delta":
        if any(token in text for token in ("余额", "balance", "融资融券")):
            return "direct_balance_delta"
        return "unknown"

    field_tokens = {
        "recent_5d": ("近5日", "5日", "5-day", "5 day"),
        "total_120d": ("近120日", "120日", "120-day", "120 day"),
    }
    has_field_token = any(token in text for token in field_tokens.get(field_scope, ()))
    has_flow_token = any(
        token in text for token in ("净流入", "净流出", "资金流向", "净申购", "净赎回", "累计", "合计")
    )
    if has_field_token and has_flow_token:
        return "direct_window"
    return "unknown"


def _source_label_for_task(
    task: Dict[str, Any],
    source_url: Optional[str],
    extraction_note: Optional[Any] = None,
) -> str:
    backend = str(task.get("search_backend") or "tavily").lower()
    extraction_backend = str(task.get("extraction_backend") or "").lower()
    note = str(extraction_note or "").lower()
    is_regex_note = (
        note.startswith("regex_only")
        or note.startswith("regex_fallback")
        or " regex_fallback" in note
    )
    is_regex_extraction = extraction_backend == "regex" or is_regex_note
    if backend == "structured":
        return "structured"
    if backend == "exa":
        if is_regex_extraction:
            return "exa_regex"
        return "exa+deepseek" if source_url else "exa_regex"
    if is_regex_extraction:
        return "tavily_regex"
    return "tavily+deepseek" if source_url else "tavily_regex"


def _apply_extraction(
    market_payload: Dict[str, Any],
    task: Dict[str, Any],
    extraction: Dict[str, Any],
    snippets: Optional[Iterable[Any]] = None,
) -> str:
    value = extraction.get("value")
    if value is None:
        return "skip_no_value"

    indicator_key = task["indicator_key"]
    note = extraction.get("note")
    source_url = extraction.get("source_url")
    source_label = _source_label_for_task(task, source_url, note)
    as_of_date = extraction.get("as_of_date")
    report_period = extraction.get("report_period")

    def _period_matches_expected(candidate: Optional[Any]) -> bool:
        expected = task.get("expected_period")
        if not expected or not candidate:
            return False
        return str(candidate)[:7] == str(expected)[:7]

    def _write_period_fields(entry: Dict[str, Any]) -> None:
        force_refresh = _is_force_refresh_task(task)
        if report_period and (force_refresh or not entry.get("report_period")):
            entry["report_period"] = report_period
        if as_of_date and (force_refresh or not entry.get("as_of_date")):
            entry["as_of_date"] = as_of_date
        if force_refresh:
            candidate_date = report_period or as_of_date
            if candidate_date:
                entry["date"] = candidate_date
            if task.get("expected_period"):
                entry["expected_period"] = task.get("expected_period")
            if _period_matches_expected(report_period) or _period_matches_expected(as_of_date):
                entry["is_stale"] = False
                entry["stale_reason"] = None
        elif not entry.get("date"):
            entry["date"] = as_of_date or report_period or entry.get("date") or ""

    def _write_common_fields(entry: Dict[str, Any], value_key: str) -> None:
        entry[value_key] = value
        entry["source"] = source_label
        entry["stage_task_id"] = task["task_id"]
        entry["note"] = note
        if source_url:
            entry["source_url"] = source_url

    def _mark_official_non_estimated(entry: Dict[str, Any], category: str) -> None:
        evidence_snippets = snippets if snippets is not None else extraction.get("snippets") or task.get("snippets") or []
        decision = should_mark_official_non_estimated(
            {**task, "category": category},
            extraction,
            evidence_snippets,
        )
        if not decision.allowed:
            return
        entry["is_estimated"] = False
        existing_note = str(entry.get("note") or "").strip()
        if decision.reason not in existing_note.split():
            entry["note"] = f"{existing_note} {decision.reason}".strip()

    macro = market_payload.setdefault("macro_indicators", {})
    if indicator_key in macro:
        entry = macro[indicator_key]
        _write_common_fields(entry, "current_value")
        _write_period_fields(entry)
        if str(indicator_key).lower() == "bdi":
            allowed, reasons = is_estimated_allowlisted("macro_indicators", indicator_key, entry)
            if allowed:
                entry["is_estimated"] = False
            elif reasons:
                marker = "estimated_keep:" + "|".join(reasons)
                entry["note"] = ((entry.get("note") or "") + " " + marker).strip()
        _mark_official_non_estimated(entry, "macro_indicators")
        return "macro_indicators"

    monetary = market_payload.setdefault("monetary_policy", {})
    monetary_key = canonical_monetary_key(indicator_key)
    if monetary_key in monetary:
        entry = monetary[monetary_key]
        _write_common_fields(entry, "current_value")
        _write_period_fields(entry)
        _mark_official_non_estimated(entry, "monetary_policy")
        return "monetary_policy"

    # fund_flow 回写（简化：将抽取值写 recent_5d，total_120d 同值）
    fund_flow = market_payload.get("fund_flow", {})
    if indicator_key in fund_flow:
        flow = fund_flow[indicator_key]
        recent_5d = _safe_number(extraction.get("recent_5d"))
        total_120d = _safe_number(extraction.get("total_120d"))
        trend = str(extraction.get("trend") or "").lower()
        if recent_5d is not None and total_120d is not None:
            flow["recent_5d"] = recent_5d
            flow["total_120d"] = total_120d
            if indicator_key == "etf":
                flow["is_estimated"] = extraction.get("is_estimated") is True
            if trend in {"inflow", "outflow"}:
                flow["trend"] = "流入" if trend == "inflow" else "流出"
            flow["current_value"] = recent_5d
            flow["current_date"] = as_of_date or report_period or market_payload.get("metadata", {}).get("date", "")
        else:
            flow["current_value"] = _safe_number(extraction.get("current_value")) or _safe_number(value)
            flow["current_date"] = as_of_date or report_period or market_payload.get("metadata", {}).get("date", "")
            point_note = "single_point_only"
            note = f"{note} {point_note}".strip() if note else point_note
        flow["source"] = source_label
        flow["stage_task_id"] = task["task_id"]
        flow["note"] = note
        if source_url:
            flow["source_url"] = source_url
        if isinstance(extraction.get("field_retry_evidence"), dict):
            flow["field_retry_evidence"] = extraction["field_retry_evidence"]
        metric_basis = _default_fund_flow_metric_basis(indicator_key, extraction)
        flow["metric_basis"] = metric_basis
        flow["source_tier"] = _infer_fund_flow_source_tier(extraction)
        flow["window_evidence"] = _infer_fund_flow_window_evidence(indicator_key, extraction, metric_basis)
        _normalize_fund_flow_estimation(flow, extraction)
        return "fund_flow"

    # forex 回写（按 pair/symbol 匹配）
    for item in market_payload.get("forex", []):
        if not isinstance(item, dict):
            continue
        if item.get("pair") == indicator_key or item.get("symbol") == indicator_key:
            _write_common_fields(item, "current_rate")
            if not item.get("date"):
                item["date"] = as_of_date or report_period or item.get("date") or ""
            return "forex"

    # commodities 回写（按 symbol 匹配）
    for item in market_payload.get("commodities", []):
        if not isinstance(item, dict):
            continue
        if item.get("symbol") == indicator_key:
            _write_common_fields(item, "current_price")
            if not item.get("date"):
                item["date"] = as_of_date or report_period or item.get("date") or ""
            return "commodities"

    # bonds 回写（按 symbol 匹配）
    for item in market_payload.get("bonds", []):
        if not isinstance(item, dict):
            continue
        if item.get("symbol") == indicator_key:
            _write_common_fields(item, "current_yield")
            if report_period and not item.get("report_period"):
                item["report_period"] = report_period
            if as_of_date and not item.get("as_of_date"):
                item["as_of_date"] = as_of_date
            if not item.get("date"):
                item["date"] = as_of_date or report_period or item.get("date") or ""
            return "bonds"

    if indicator_key in _FOREX_UPSERT_META:
        entry = {
            "pair": indicator_key,
            "name": _FOREX_UPSERT_META[indicator_key],
            "current_rate": value,
            "daily_change": None,
            "change_120d": None,
            "trend": "待校验",
            "source": source_label,
            "stage_task_id": task["task_id"],
            "note": (f"{note} stage2_auto_upsert" if note else "stage2_auto_upsert"),
        }
        market_payload.setdefault("forex", []).append(entry)
        return "forex_upsert"

    if indicator_key in _COMMODITY_UPSERT_META:
        name, default_unit = _COMMODITY_UPSERT_META[indicator_key]
        entry = {
            "symbol": indicator_key,
            "name": name,
            "current_price": value,
            "unit": extraction.get("unit") or default_unit,
            "daily_change": None,
            "ytd_change": None,
            "trend": "待校验",
            "source": source_label,
            "timestamp": market_payload.get("metadata", {}).get("date", ""),
            "stage_task_id": task["task_id"],
            "note": (f"{note} stage2_auto_upsert" if note else "stage2_auto_upsert"),
        }
        market_payload.setdefault("commodities", []).append(entry)
        return "commodities_upsert"

    if indicator_key in _BOND_UPSERT_META:
        entry = {
            "symbol": indicator_key,
            "name": _BOND_UPSERT_META[indicator_key],
            "current_yield": value,
            "change_5d_bp": None,
            "change_120d_bp": None,
            "trend": "待校验",
            "source": source_label,
            "is_estimated": False,
            "stage_task_id": task["task_id"],
            "note": (f"{note} stage2_auto_upsert" if note else "stage2_auto_upsert"),
        }
        market_payload.setdefault("bonds", []).append(entry)
        return "bonds_upsert"

    # 若不存在，则落到 macro_indicators 以便后续 Stage3 检查
    macro[indicator_key] = {
        "indicator_name": indicator_key.upper(),
        "current_value": value,
        "unit": extraction.get("unit") or "%",
        "date": extraction.get("as_of_date")
        or extraction.get("report_period")
        or market_payload.get("metadata", {}).get("date", ""),
        "report_period": extraction.get("report_period"),
        "as_of_date": extraction.get("as_of_date"),
        "source": source_label,
        "stage_task_id": task["task_id"],
        "note": note,
    }
    return "fallback_macro"


def _structured_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    structured = stats.setdefault(
        "structured_provider",
        {
            "attempt": 0,
            "success": 0,
            "fallback": 0,
            "by_key": {},
            "error_breakdown": {},
            "latency_ms": [],
            "latency_ms_by_provider": {},
        },
    )
    structured.setdefault("attempt", 0)
    structured.setdefault("success", 0)
    structured.setdefault("fallback", 0)
    structured.setdefault("by_key", {})
    structured.setdefault("error_breakdown", {})
    structured.setdefault("latency_ms", [])
    structured.setdefault("latency_ms_by_provider", {})
    return structured


def _structured_key_stats(stats: Dict[str, Any], indicator_key: str) -> Dict[str, Any]:
    structured = _structured_stats(stats)
    by_key = structured.setdefault("by_key", {})
    return by_key.setdefault(indicator_key, {"attempt": 0, "success": 0, "fallback": 0})


def _record_structured_attempt(stats: Dict[str, Any], indicator_key: str) -> None:
    structured = _structured_stats(stats)
    structured["attempt"] = structured.get("attempt", 0) + 1
    key_stats = _structured_key_stats(stats, indicator_key)
    key_stats["attempt"] = key_stats.get("attempt", 0) + 1
    stats["structured_attempt"] = stats.get("structured_attempt", 0) + 1


def _record_structured_latency_by_provider(
    structured: Dict[str, Any],
    provider_name: Optional[str],
    latency_ms: Optional[int],
) -> None:
    if latency_ms is None:
        return
    provider_key = str(provider_name or "unknown")
    by_provider = structured.setdefault("latency_ms_by_provider", {})
    if isinstance(by_provider, dict):
        by_provider.setdefault(provider_key, []).append(latency_ms)


def _record_structured_success(
    stats: Dict[str, Any],
    indicator_key: str,
    latency_ms: int,
    provider_name: Optional[str] = None,
) -> None:
    structured = _structured_stats(stats)
    structured["success"] = structured.get("success", 0) + 1
    structured.setdefault("latency_ms", []).append(latency_ms)
    _record_structured_latency_by_provider(structured, provider_name, latency_ms)
    key_stats = _structured_key_stats(stats, indicator_key)
    key_stats["success"] = key_stats.get("success", 0) + 1
    stats["structured_success"] = stats.get("structured_success", 0) + 1


def _record_structured_fallback(
    stats: Dict[str, Any],
    indicator_key: str,
    reason: str,
    latency_ms: Optional[int] = None,
    provider_name: Optional[str] = None,
) -> None:
    structured = _structured_stats(stats)
    structured["fallback"] = structured.get("fallback", 0) + 1
    if latency_ms is not None:
        structured.setdefault("latency_ms", []).append(latency_ms)
    _record_structured_latency_by_provider(structured, provider_name, latency_ms)
    key_stats = _structured_key_stats(stats, indicator_key)
    key_stats["fallback"] = key_stats.get("fallback", 0) + 1
    key_stats["last_fallback_reason"] = reason
    breakdown = structured.setdefault("error_breakdown", {})
    breakdown[reason] = breakdown.get(reason, 0) + 1
    stats["structured_fallback"] = stats.get("structured_fallback", 0) + 1


def _structured_audit_fields_from_task(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: task[key]
        for key in (
            "structured_provider_attempted",
            "structured_provider_fallback_reason",
            "structured_provider_latency_ms",
            "structured_provider_diagnostics",
            "structured_provider_name",
        )
        if key in task
    }


def _mark_structured_fallback_on_task(
    task: Dict[str, Any],
    *,
    reason: str,
    latency_ms: int,
    diagnostics: Optional[Dict[str, Any]] = None,
    provider_name: Optional[Any] = None,
) -> None:
    task["structured_provider_attempted"] = True
    task["structured_provider_fallback_reason"] = reason
    task["structured_provider_latency_ms"] = latency_ms
    task["structured_provider_diagnostics"] = diagnostics or {}
    if provider_name:
        task["structured_provider_name"] = provider_name


async def _try_structured_provider(
    *,
    structured_registry: Any,
    task: Dict[str, Any],
    market_payload: Dict[str, Any],
    task_log_path: Path,
    stats: Dict[str, Any],
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    if structured_registry is None:
        return None

    indicator_key = str(task.get("indicator_key") or "")
    provider_for = getattr(structured_registry, "provider_for", None)
    if callable(provider_for) and provider_for(indicator_key) is None:
        structured = _structured_stats(stats)
        structured["unsupported"] = structured.get("unsupported", 0) + 1
        return None

    reference_date = (
        market_payload.get("metadata", {}).get("date")
        or task.get("reference_date")
        or task.get("expected_period")
        or datetime.now().date().isoformat()
    )
    started = time.perf_counter()
    _record_structured_attempt(stats, indicator_key)
    try:
        result = await structured_registry.fetch(task, market_payload, reference_date)
    except Exception as exc:
        if StructuredProviderError is not None and isinstance(exc, StructuredProviderError):
            reason = str(getattr(exc, "reason", None) or "provider_error")
            diagnostics_fn = getattr(exc, "to_diagnostics", None)
            diagnostics = diagnostics_fn() if callable(diagnostics_fn) else {}
        else:
            reason = "provider_exception"
            diagnostics = {
                "structured_provider_error": reason,
                "structured_provider_message": str(exc),
            }
        latency_ms = int((time.perf_counter() - started) * 1000)
        provider_name = getattr(exc, "provider", None)
        _record_structured_fallback(
            stats,
            indicator_key,
            reason,
            latency_ms,
            provider_name=provider_name,
        )
        _mark_structured_fallback_on_task(
            task,
            reason=reason,
            latency_ms=latency_ms,
            diagnostics=diagnostics,
            provider_name=provider_name,
        )
        samples = stats.setdefault("structured_error_samples", [])
        if isinstance(samples, list) and len(samples) < 5:
            samples.append({**diagnostics, "indicator_key": indicator_key})
        return None

    latency_ms = int((time.perf_counter() - started) * 1000)
    if result is None:
        structured = _structured_stats(stats)
        structured["none"] = structured.get("none", 0) + 1
        return None

    extraction = result.to_extraction()
    snippets = list(result.audit_snippets())
    task_for_log = {
        **task,
        "search_backend": "structured",
        "extraction_backend": "structured",
        "query_used": task.get("query_used") or task.get("query") or indicator_key,
    }
    _augment_extraction_metadata(extraction, task_for_log, snippets)
    _refine_extraction_value(extraction, task_for_log, snippets)

    is_fund_flow = indicator_key in {"northbound", "southbound", "etf", "margin"}
    manual_required = bool(extraction.get("manual_required"))
    if is_fund_flow:
        adjusted_value, unit_manual, note_append = _validate_fund_flow_extraction(
            extraction,
            indicator_key=indicator_key,
        )
        extraction["value"] = adjusted_value
        if note_append:
            extraction["note"] = _append_note(extraction.get("note"), note_append)
        manual_required = manual_required or unit_manual
        if unit_manual and _safe_number(extraction.get("recent_5d")) is not None and _safe_number(
            extraction.get("total_120d")
        ) is not None:
            metric_basis = _default_fund_flow_metric_basis(indicator_key, extraction)
            window_evidence = _infer_fund_flow_window_evidence(indicator_key, extraction, metric_basis)
            if window_evidence not in {"direct_window", "direct_daily_series", "direct_balance_delta"}:
                extraction["manual_reason"] = _append_note(
                    extraction.get("manual_reason"),
                    "fund_flow_window_missing",
                )
                manual_required = True
    else:
        val_adj, manual2, note_append = _validate_general_extraction(extraction, task_for_log, snippets)
        extraction["value"] = val_adj
        if note_append:
            extraction["note"] = _append_note(extraction.get("note"), note_append)
        manual_required = manual_required or manual2

    if extraction.get("manual_reason"):
        extraction["note"] = _append_note(extraction.get("note"), str(extraction.get("manual_reason")))
    if manual_required:
        reason = str(extraction.get("manual_reason") or "policy_gate_blocked")
        provider_name = getattr(result, "provider", None)
        _record_structured_fallback(
            stats,
            indicator_key,
            reason,
            latency_ms,
            provider_name=provider_name,
        )
        _mark_structured_fallback_on_task(
            task,
            reason=reason,
            latency_ms=latency_ms,
            diagnostics=dict(getattr(result, "diagnostics", {}) or {}),
            provider_name=provider_name,
        )
        if reason == "policy_gate_blocked" or "fund_flow_window_missing" in reason:
            stats["structured_policy_gate_blocked"] = stats.get("structured_policy_gate_blocked", 0) + 1
        return None

    snapshot = copy.deepcopy(market_payload)
    write_target = _apply_extraction(market_payload, task_for_log, extraction, snippets=snippets)
    if write_target == "skip_no_value":
        market_payload.clear()
        market_payload.update(snapshot)
        provider_name = getattr(result, "provider", None)
        _record_structured_fallback(
            stats,
            indicator_key,
            write_target,
            latency_ms,
            provider_name=provider_name,
        )
        _mark_structured_fallback_on_task(
            task,
            reason=write_target,
            latency_ms=latency_ms,
            diagnostics=dict(getattr(result, "diagnostics", {}) or {}),
            provider_name=provider_name,
        )
        return None
    post_writeback_reason = _post_writeback_manual_reason(market_payload, indicator_key)
    if post_writeback_reason:
        market_payload.clear()
        market_payload.update(snapshot)
        provider_name = getattr(result, "provider", None)
        _record_structured_fallback(
            stats,
            indicator_key,
            post_writeback_reason,
            latency_ms,
            provider_name=provider_name,
        )
        _mark_structured_fallback_on_task(
            task,
            reason=post_writeback_reason,
            latency_ms=latency_ms,
            diagnostics=dict(getattr(result, "diagnostics", {}) or {}),
            provider_name=provider_name,
        )
        if post_writeback_reason == "estimated_not_allowed":
            stats["structured_policy_gate_blocked"] = stats.get("structured_policy_gate_blocked", 0) + 1
        return None

    write_stats = stats.setdefault("write_back_by_category", {})
    if isinstance(write_stats, dict):
        write_stats[write_target] = write_stats.get(write_target, 0) + 1
    if write_target == "fallback_macro":
        stats["write_back_fallback_count"] = stats.get("write_back_fallback_count", 0) + 1
    _update_missing_items(market_payload, indicator_key)
    provider_name = getattr(result, "provider", None)
    _record_structured_success(stats, indicator_key, latency_ms, provider_name=provider_name)

    now_ts = int(datetime.now().timestamp())
    task_record = {
        "task_id": task["task_id"],
        "indicator_key": indicator_key,
        "category": task.get("category") or task.get("stage_phase"),
        "stage_phase": task["stage_phase"],
        "search_backend": "structured",
        "fund_flow_backend": task.get("fund_flow_backend") if is_fund_flow else None,
        "extraction_backend": "structured",
        "confidence": extraction.get("confidence", 0.0),
        "source_url": extraction.get("source_url"),
        "note": extraction.get("note"),
        "llm_latency_ms": 0,
        "llm_error": None,
        "deepseek_error": None,
        "attempt_index": 0,
        "elapsed_ms": latency_ms,
        "created_at": task.get("created_at", now_ts),
        "finished_at": now_ts,
        "manual_required": False,
        "manual_reason": None,
        "query_used": task_for_log.get("query_used"),
        "result_type": "structured_success",
        "write_back_success": True,
        "write_back_target": write_target,
        "structured_provider": getattr(result, "provider", None),
        "structured_provider_latency_ms": latency_ms,
    }
    websearch_item = result.to_websearch_record(task_for_log)
    websearch_item.update(
        {
            "task": task_for_log,
            "extraction": extraction,
            "extraction_backend": "structured",
            "raw_results": snippets,
            "manual_required": False,
            "manual_reason": None,
            "result_type": "structured_success",
            "write_back_success": True,
            "write_back_target": write_target,
            "structured_provider": getattr(result, "provider", None),
            "structured_provider_latency_ms": latency_ms,
        }
    )
    _append_task_log(task_log_path, task_record)
    return task_record, websearch_item


def _update_missing_items(market_payload: Dict[str, Any], indicator_key: str) -> None:
    remove_missing_item(market_payload, None, indicator_key)
    canonical_key = canonical_monetary_key(indicator_key)
    if canonical_key != indicator_key:
        remove_missing_item(market_payload, None, canonical_key)


def _append_gap_monitor(output_path: Path, pending: List[str], manual: Optional[List[str]] = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pending_tasks": pending,
        "manual_required": manual or [],
        "generated_at": datetime.now().isoformat(),
    }
    _dump_json(payload, output_path)


def _filter_tasks(tasks: List[Dict[str, Any]], task_ids: Optional[List[str]], indicators: Optional[List[str]]) -> List[Dict[str, Any]]:
    if not task_ids and not indicators:
        return tasks
    selected = []
    for t in tasks:
        if task_ids and t["task_id"] in task_ids:
            selected.append(t)
            continue
        if indicators and t["indicator_key"] in indicators:
            selected.append(t)
    return selected


def _compute_derived_metrics(market_payload: Dict[str, Any]) -> None:
    derived = market_payload.setdefault("derived_metrics", {})
    monetary = market_payload.get("monetary_policy", {})

    m1 = _safe_number(monetary.get("m1", {}).get("current_value"))
    m2 = _safe_number(monetary.get("m2", {}).get("current_value"))
    if m1 is not None and m2 is not None:
        derived["m1_m2_spread"] = round(m1 - m2, 4)

    # 简化版 DR007 五日均值：如果存在 dr007_history 列表则计算，否则跳过
    dr007_history = monetary.get("dr007", {}).get("history", [])
    if isinstance(dr007_history, list) and len(dr007_history) >= 1:
        recent = [x for x in dr007_history if _safe_number(x) is not None][-5:]
        if recent:
            avg = sum(_safe_number(x) or 0 for x in recent) / len(recent)
            derived["dr007_5d_avg"] = round(avg, 4)

    commodities = market_payload.get("commodities", [])
    changes = [
        _safe_number(item.get("daily_change")) for item in commodities if _safe_number(item.get("daily_change")) is not None
    ]
    if changes:
        avg_change = sum(changes) / len(changes)
        derived["commodity_trend"] = "上行" if avg_change > 0 else "下行"


def _append_note(note: Optional[str], extra: Optional[str]) -> Optional[str]:
    base = (note or "").strip()
    tail = (extra or "").strip()
    if not tail:
        return base or None
    if not base:
        return tail
    if tail in base:
        return base
    return f"{base} {tail}".strip()


def _post_writeback_manual_reason(market_payload: Dict[str, Any], indicator_key: str) -> Optional[str]:
    fund_flow = market_payload.get("fund_flow", {})
    if indicator_key not in fund_flow:
        return None
    entry = fund_flow.get(indicator_key)
    if not isinstance(entry, dict) or entry.get("is_estimated") is not True:
        return None
    allowed, _reasons = is_estimated_allowlisted("fund_flow", indicator_key, entry)
    if allowed:
        return None
    return "estimated_not_allowed"


def _mark_post_writeback_manual_required(
    market_payload: Dict[str, Any],
    task_record: Dict[str, Any],
    extraction: Dict[str, Any],
    indicator_key: str,
    reason: str,
) -> None:
    task_record["manual_required"] = True
    task_record["manual_reason"] = reason
    task_record["result_type"] = "manual_required"
    extraction["manual_required"] = True
    extraction["manual_reason"] = reason
    extraction["note"] = _append_note(extraction.get("note"), reason)
    task_record["note"] = extraction.get("note")
    append_missing_item(market_payload, "fund_flow", indicator_key, reason)


def _is_force_refresh_task(task: Dict[str, Any]) -> bool:
    return bool(task.get("force_refresh")) or str(task.get("trigger_reason") or "").lower() == "stale_data"


def _finalize_task_result_type(record: Dict[str, Any]) -> str:
    if str(record.get("note") or "").strip() == "skip_existing_value":
        return "skipped_existing"
    if record.get("manual_required"):
        return "manual_required"
    return "search_success"


def _finalize_websearch_result_type(item: Dict[str, Any]) -> str:
    extraction = item.get("extraction") or {}
    if str(extraction.get("note") or "").strip() == "existing_value":
        return "skipped_existing"
    if item.get("manual_required"):
        return "manual_required"
    return "search_success"


def _nested_row_value(row: Dict[str, Any], key: str) -> Any:
    if key in row:
        return row.get(key)
    task = row.get("task")
    if isinstance(task, dict) and key in task:
        return task.get(key)
    extraction = row.get("extraction")
    if isinstance(extraction, dict) and key in extraction:
        return extraction.get(key)
    return None


def _build_retrieval_diagnostics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize search hit, extraction failure, and writeback outcomes."""
    total = 0
    retrieval_hit = 0
    extract_failed = 0
    writeback_success = 0
    reason_counts: Dict[str, int] = {}
    for row in rows:
        if _nested_row_value(row, "result_type") == "skipped_existing":
            continue
        total += 1
        usable_count = int(_nested_row_value(row, "usable_count_before_extract") or 0)
        manual_required = bool(_nested_row_value(row, "manual_required"))
        if usable_count > 0:
            retrieval_hit += 1
            if manual_required:
                extract_failed += 1
        if bool(_nested_row_value(row, "write_back_success")) or (
            not manual_required and _nested_row_value(row, "result_type") == "search_success"
        ):
            writeback_success += 1
        if manual_required:
            reason = (
                _nested_row_value(row, "manual_reason")
                or _nested_row_value(row, "extraction_skipped_reason")
                or _nested_row_value(row, "extract_skipped_reason")
                or "manual_required"
            )
            reason_key = str(reason)
            reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1
    return {
        "retrieval_task_count": total,
        "retrieval_hit_count": retrieval_hit,
        "retrieval_hit_rate": retrieval_hit / total if total else 0.0,
        "retrieval_hit_extract_failed": extract_failed,
        "extract_success_rate": (retrieval_hit - extract_failed) / retrieval_hit if retrieval_hit else 0.0,
        "writeback_success_count": writeback_success,
        "writeback_success_rate": writeback_success / total if total else 0.0,
        "manual_reason_breakdown": reason_counts,
    }


def _has_diagnostic_value(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _merge_nested_diagnostic_dict(existing: Any, incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing) if isinstance(existing, dict) else {}
    for key, value in incoming.items():
        if _has_diagnostic_value(value) or key not in merged:
            merged[key] = value
    return merged


def _merge_diagnostic_row(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key in {"task", "extraction"} and isinstance(value, dict):
            merged[key] = _merge_nested_diagnostic_dict(merged.get(key), value)
            continue
        if _has_diagnostic_value(value) or key not in merged:
            merged[key] = value
    return merged


def _diagnostic_rows_for_summary(
    completed_tasks: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
    websearch_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    index_by_task_id: Dict[str, int] = {}

    for source_rows in (completed_tasks, failures, websearch_results):
        for row in source_rows:
            if not isinstance(row, dict):
                continue
            task_id = _nested_row_value(row, "task_id")
            if not task_id:
                rows.append(row)
                continue
            task_key = str(task_id)
            existing_index = index_by_task_id.get(task_key)
            if existing_index is None:
                index_by_task_id[task_key] = len(rows)
                rows.append(dict(row))
            else:
                rows[existing_index] = _merge_diagnostic_row(rows[existing_index], row)
    return rows


_STAGE2_BACKEND_SUMMARY_KEYS = (
    "search_backend_final",
    "tavily_to_exa_failover",
    "tavily_to_exa_failover_count",
    "tavily_limit_error_count",
    "tavily_error_samples",
    "exa_failover_success",
    "exa_failover_empty",
    "exa_failover_error",
    "exa_unavailable",
    "exa_error_breakdown",
    "exa_error_samples",
    "structured_provider",
    "structured_policy_gate_blocked",
    "structured_error_samples",
)


def _stage2_effective_hit_rate(success_count: int, failure_count: int) -> float:
    denominator = success_count + failure_count
    return success_count / denominator if denominator else 0.0


def _stage2_summary_metric_fields(
    *,
    search_success_count: int,
    structured_success_count: int,
    search_failed_count: int,
) -> Dict[str, Any]:
    search_denominator = search_success_count + search_failed_count
    search_success_rate_incremental = (
        search_success_count / search_denominator if search_denominator else 0.0
    )
    stage2_effective_success = search_success_count + structured_success_count
    stage2_effective_failure = search_failed_count
    stage2_effective_denominator = stage2_effective_success + stage2_effective_failure
    return {
        "task_search_success": search_success_count,
        "task_structured_success": structured_success_count,
        "task_search_failed": search_failed_count,
        "stage2_effective_success": stage2_effective_success,
        "stage2_effective_failure": stage2_effective_failure,
        "stage2_effective_denominator": stage2_effective_denominator,
        "stage2_effective_hit_rate": _stage2_effective_hit_rate(
            stage2_effective_success,
            stage2_effective_failure,
        ),
        "search_success_rate_incremental": search_success_rate_incremental,
    }


def _build_stage2_result_count_fields(
    completed_tasks: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> Dict[str, Any]:
    skipped_existing_count = sum(
        1 for task in completed_tasks if task.get("result_type") == "skipped_existing"
    )
    search_success_count = sum(
        1 for task in completed_tasks if task.get("result_type") == "search_success"
    )
    structured_success_count = sum(
        1 for task in completed_tasks if task.get("result_type") == "structured_success"
    )
    search_failed_count = sum(
        1 for task in failures if task.get("result_type") == "manual_required"
    )
    fields = _stage2_summary_metric_fields(
        search_success_count=search_success_count,
        structured_success_count=structured_success_count,
        search_failed_count=search_failed_count,
    )
    fields["task_skipped_existing"] = skipped_existing_count
    return fields


def _structured_provider_summary_fields(exec_stats: Dict[str, Any]) -> Dict[str, Any]:
    structured = exec_stats.get("structured_provider")
    if not isinstance(structured, dict):
        structured = {}
    by_key = structured.get("by_key", {})
    if not isinstance(by_key, dict):
        by_key = {}
    success_by_key = {
        str(indicator_key): key_stats.get("success", 0)
        for indicator_key, key_stats in by_key.items()
        if isinstance(key_stats, dict) and key_stats.get("success", 0)
    }
    error_breakdown = structured.get("error_breakdown", {})
    if not isinstance(error_breakdown, dict):
        error_breakdown = {}
    latency_by_provider = structured.get("latency_ms_by_provider", {})
    if not isinstance(latency_by_provider, dict):
        latency_by_provider = {}
    return {
        "structured_provider_attempt_count": structured.get(
            "attempt",
            exec_stats.get("structured_attempt", 0),
        ),
        "structured_provider_success_count": structured.get(
            "success",
            exec_stats.get("structured_success", 0),
        ),
        "structured_provider_fallback_to_search_count": structured.get(
            "fallback",
            exec_stats.get("structured_fallback", 0),
        ),
        "structured_provider_success_by_key": success_by_key,
        "structured_provider_error_breakdown": dict(error_breakdown),
        "structured_provider_latency_ms_by_provider": dict(latency_by_provider),
    }


def _build_stage2_summary_diagnostics(
    completed_tasks: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
    websearch_results: List[Dict[str, Any]],
    exec_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    exec_stats = exec_stats or {}
    retrieval_diagnostics = _build_retrieval_diagnostics(
        _diagnostic_rows_for_summary(completed_tasks, failures, websearch_results)
    )
    payload = {
        "retrieval_diagnostics": retrieval_diagnostics,
        "manual_reason_breakdown": retrieval_diagnostics.get("manual_reason_breakdown", {}),
        "deepseek_circuit_breaker_triggered": bool(
            exec_stats.get("deepseek_circuit_breaker_triggered", False)
        ),
        "deepseek_circuit_breaker_reason": exec_stats.get("deepseek_circuit_breaker_reason"),
        "deepseek_timeout_rate": exec_stats.get("deepseek_timeout_rate", 0.0),
        "deepseek_breaker_attempts": exec_stats.get("deepseek_breaker_attempts", 0),
        "deepseek_breaker_timeouts": exec_stats.get("deepseek_breaker_timeouts", 0),
    }
    payload.update(_structured_provider_summary_fields(exec_stats))
    unavailable_reason = exec_stats.get("tavily_unavailable_reason")
    if unavailable_reason:
        payload["tavily_unavailable_reason"] = unavailable_reason
    for key in _STAGE2_BACKEND_SUMMARY_KEYS:
        if key in exec_stats:
            payload[key] = exec_stats[key]
    return payload


class _DeepSeekCircuitBreaker:
    def __init__(
        self,
        *,
        max_consecutive_timeouts: int = 3,
        max_timeout_rate: float = 0.5,
        min_attempts: int = 4,
    ) -> None:
        self.max_consecutive_timeouts = max_consecutive_timeouts
        self.max_timeout_rate = max_timeout_rate
        self.min_attempts = min_attempts
        self.attempts = 0
        self.timeouts = 0
        self.consecutive_timeouts = 0
        self.triggered = False
        self.reason: Optional[str] = None

    @property
    def timeout_rate(self) -> float:
        if self.attempts <= 0:
            return 0.0
        return round(self.timeouts / self.attempts, 4)

    def record(self, *, timeout: bool) -> None:
        if self.triggered:
            return
        self.attempts += 1
        if timeout:
            self.timeouts += 1
            self.consecutive_timeouts += 1
        else:
            self.consecutive_timeouts = 0
        if (
            timeout
            and self.max_consecutive_timeouts > 0
            and self.consecutive_timeouts >= self.max_consecutive_timeouts
        ):
            self.triggered = True
            self.reason = "consecutive_timeouts"
            return
        if (
            self.min_attempts > 0
            and self.max_timeout_rate > 0
            and self.attempts >= self.min_attempts
            and self.timeout_rate >= self.max_timeout_rate
        ):
            self.triggered = True
            self.reason = "timeout_rate"


def _is_deepseek_timeout(exc: Exception) -> bool:
    return isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timeout" in str(exc).lower()


def _mark_stale_refresh_failure(extraction: Dict[str, Any], task: Dict[str, Any]) -> None:
    if not _is_force_refresh_task(task):
        return
    extraction["note"] = _append_note(extraction.get("note"), "stale_refresh_failed")
    extraction["manual_reason"] = _append_note(extraction.get("manual_reason"), "stale_refresh_failed")


def _dedupe_candidate_queries(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for candidate in candidates:
        query = str(candidate.get("query") or "").strip()
        field_scope = str(candidate.get("field_scope") or "")
        if not query:
            continue
        sig = (query, field_scope)
        if sig in seen:
            continue
        seen.add(sig)
        result.append(candidate)
    return result


def _expand_query_candidates(
    task: Dict[str, Any],
    *,
    directed_query_override: Optional[str] = None,
    field_scopes: Optional[List[str]] = None,
    include_primary: bool = True,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    if directed_query_override:
        candidates.append(
            {
                "query": directed_query_override,
                "family": "directed_retry",
                "field_scope": None,
                "preferred_domains": task.get("preferred_domains") or [],
                "exclude_domains": task.get("exclude_domains") or [],
                "required_keywords": task.get("required_keywords") or [],
                "exclude_keywords": task.get("exclude_keywords") or [],
            }
        )
    if include_primary:
        for family in task.get("query_families") or []:
            for query in family.get("queries") or []:
                candidates.append(
                    {
                        "query": query,
                        "family": family.get("name") or "default",
                        "field_scope": family.get("field_scope"),
                        "preferred_domains": family.get("preferred_domains") or task.get("preferred_domains") or [],
                        "exclude_domains": list(task.get("exclude_domains") or [])
                        + list(family.get("exclude_domains") or []),
                        "required_keywords": list(task.get("required_keywords") or [])
                        + list(family.get("required_keywords") or []),
                        "exclude_keywords": list(task.get("exclude_keywords") or [])
                        + list(family.get("exclude_keywords") or []),
                        "time_range": family.get("time_range") or task.get("time_range"),
                        "topic": family.get("topic") or task.get("topic"),
                        "max_results": family.get("max_results") or task.get("max_results"),
                        "search_depth": family.get("search_depth") or task.get("search_depth"),
                        "days": family.get("days") if family.get("days") is not None else task.get("days"),
                        "chunks_per_source": family.get("chunks_per_source")
                        if family.get("chunks_per_source") is not None
                        else task.get("chunks_per_source"),
                        "auto_parameters": family.get("auto_parameters")
                        if family.get("auto_parameters") is not None
                        else task.get("auto_parameters"),
                    }
                )
    if include_primary and not candidates:
        primary_query = task.get("query") or task.get("indicator_key")
        if primary_query:
            candidates.append(
                {
                    "query": primary_query,
                    "family": "legacy_primary",
                    "field_scope": None,
                    "preferred_domains": task.get("preferred_domains") or [],
                    "exclude_domains": task.get("exclude_domains") or [],
                    "required_keywords": task.get("required_keywords") or [],
                    "exclude_keywords": task.get("exclude_keywords") or [],
                    "time_range": task.get("time_range"),
                    "topic": task.get("topic"),
                    "max_results": task.get("max_results"),
                    "search_depth": task.get("search_depth"),
                    "days": task.get("days"),
                    "chunks_per_source": task.get("chunks_per_source"),
                    "auto_parameters": task.get("auto_parameters"),
                }
            )
        for query in task.get("queries") or []:
            candidates.append(
                {
                    "query": query,
                    "family": "legacy_alt",
                    "field_scope": None,
                    "preferred_domains": task.get("preferred_domains") or [],
                    "exclude_domains": task.get("exclude_domains") or [],
                    "required_keywords": task.get("required_keywords") or [],
                    "exclude_keywords": task.get("exclude_keywords") or [],
                    "time_range": task.get("time_range"),
                    "topic": task.get("topic"),
                    "max_results": task.get("max_results"),
                    "search_depth": task.get("search_depth"),
                    "days": task.get("days"),
                    "chunks_per_source": task.get("chunks_per_source"),
                    "auto_parameters": task.get("auto_parameters"),
                }
            )
    selected_fields = field_scopes or []
    for field_scope in selected_fields:
        for query in (task.get("field_queries") or {}).get(field_scope, []):
            candidates.append(
                {
                    "query": query,
                    "family": f"field:{field_scope}",
                    "field_scope": field_scope,
                    "preferred_domains": task.get("preferred_domains") or [],
                    "exclude_domains": task.get("exclude_domains") or [],
                    "required_keywords": task.get("required_keywords") or [],
                    "exclude_keywords": task.get("exclude_keywords") or [],
                    "time_range": task.get("time_range"),
                    "topic": task.get("topic"),
                    "max_results": task.get("max_results"),
                    "search_depth": task.get("search_depth"),
                    "days": task.get("days"),
                    "chunks_per_source": task.get("chunks_per_source"),
                    "auto_parameters": task.get("auto_parameters"),
                }
            )
    deduped = _dedupe_candidate_queries(candidates)
    if include_primary and not field_scopes:
        limit_raw = task.get("max_query_candidates")
        try:
            limit = int(limit_raw) if limit_raw is not None else 0
        except (TypeError, ValueError):
            limit = 0
        if limit > 0:
            directed = [item for item in deduped if item.get("family") == "directed_retry"]
            primary = [item for item in deduped if item.get("family") != "directed_retry"]
            if len(primary) > limit:
                return directed + primary[:limit]
    return deduped


def _build_directed_query(
    task: Dict[str, Any],
    extraction: Dict[str, Any],
    skip_reason: Optional[str],
    extra_reason: Optional[str],
) -> Optional[str]:
    base_query = (task.get("query") or task.get("indicator_key") or "").strip()
    if not base_query:
        return None
    trigger_text = " ".join(
        [
            str(skip_reason or ""),
            str(extra_reason or ""),
            str(extraction.get("manual_reason") or ""),
            str(extraction.get("note") or ""),
        ]
    ).lower()
    if task.get("field_queries"):
        if "recent_5d" in trigger_text or "近5日" in trigger_text:
            values = (task.get("field_queries") or {}).get("recent_5d") or []
            if values:
                return values[0]
        if "total_120d" in trigger_text or "120日" in trigger_text or "累计" in trigger_text:
            values = (task.get("field_queries") or {}).get("total_120d") or []
            if values:
                return values[0]
    hint_tokens: List[str] = ["最新", "官方", "数据"]
    unit = (task.get("unit") or "").strip()
    issuer = (task.get("issuer") or "").strip()
    if unit:
        hint_tokens.append(f"单位{unit}")
    if issuer:
        hint_tokens.append(f"发布机构{issuer}")

    indicator = str(task.get("indicator_key") or "").lower()
    if indicator in {"industrial", "industrial_sales", "cpi", "ppi", "pmi", "pmi_new_orders", "gdp"}:
        now = datetime.now()
        year = now.year
        month = now.month - 1 if now.month > 1 else 12
        if now.month == 1:
            year -= 1
        hint_tokens.append(f"{year}年{month}月")
        hint_tokens.append("同比")

    if "low_score_all" in trigger_text or "低分" in trigger_text:
        hint_tokens.append("公告")
        hint_tokens.append("统计公报")
    if "单位不匹配" in trigger_text:
        hint_tokens.append("精确单位")
    if "发布机构" in trigger_text:
        hint_tokens.append("发布机构原文")
    expected_tokens = task.get("expected_period_tokens") or []
    if expected_tokens:
        hint_tokens.append(str(expected_tokens[0]))

    directed = f"{base_query} {' '.join(hint_tokens)}".strip()
    return directed if directed != base_query else None


def _should_retry_with_directed_query(
    extraction: Dict[str, Any],
    skip_reason: Optional[str],
    extra_reason: Optional[str],
    *,
    attempt: int,
    max_retries: int,
    directed_retry_done: bool,
) -> bool:
    if directed_retry_done:
        return False
    # 当前循环使用 count(start=1)，最多允许触发一次定向重试
    if attempt > max(1, max_retries):
        return False
    trigger_text = " ".join(
        [
            str(skip_reason or ""),
            str(extra_reason or ""),
            str(extraction.get("manual_reason") or ""),
            str(extraction.get("note") or ""),
        ]
    ).lower()
    triggers = [
        "low_score_all",
        "单位不匹配",
        "缺少发布机构",
        "no_value",
        "deepseek_no_value",
        "no_deepseek_key",
    ]
    return any(t in trigger_text for t in triggers)


async def _execute_tasks(
    tasks: List[Dict[str, Any]],
    market_payload: Dict[str, Any],
    client: AsyncTavilyClient,
    exa_client: Optional["AsyncExaClient"],
    extractor: DeepSeekExtractionAgent,
    task_log_path: Path,
    cache_ttl: Optional[int],
    max_retries: int = 1,
    fund_flow_backend: str = "tavily",
    forex_backend: str = "tavily",
    deepseek_timeout: Optional[float] = None,
    extraction_backend: str = "deepseek",
    deepseek_max_concurrency: int = 3,
    deepseek_serial_keys: Optional[List[str]] = None,
    stats: Optional[Dict[str, Any]] = None,
    use_queue: bool = False,
    queue_concurrency: int = 3,
    queue_maxsize: int = 100,
    queue_retry_limit: int = 1,
    disable_extract: bool = False,
    auto_disable_extract_on_422: bool = False,
    extract_422_threshold: int = 1,
    extract_422_cooldown_sec: int = 300,
    extract_topk: int = 3,
    low_score_threshold: float = 0.2,
    llm_hard_timeout: Optional[float] = None,
    deepseek_breaker_consecutive_timeouts: int = 6,
    deepseek_breaker_timeout_rate: float = 0.6,
    deepseek_breaker_min_attempts: int = 8,
    allow_exa_non_quota_fallback: bool = False,
    structured_registry: Any = None,
) -> (List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]):
    completed: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    websearch_results: List[Dict[str, Any]] = []
    manual_required_keys: List[str] = []
    stats = stats if stats is not None else {}
    stats.setdefault("domain_filtered_drop", 0)
    stats.setdefault("regex_hits", 0)
    stats.setdefault("score_filtered_drop", 0)
    stats.setdefault("timeout_count", 0)
    stats.setdefault("deepseek_timeouts", 0)
    stats.setdefault("retry_count", 0)
    stats.setdefault("extract_calls", 0)
    stats.setdefault("tavily_extract_calls", 0)
    stats.setdefault("tavily_extract_422_count", 0)
    stats.setdefault("queue_requeued", 0)
    stats.setdefault("queue_dead_letters", 0)
    stats.setdefault("deepseek_latencies", [])
    stats.setdefault("extract_auto_disabled", False)
    stats.setdefault("extract_cooldown_count", 0)
    stats.setdefault("low_score_drop", 0)
    stats.setdefault("low_score_allow", 0)
    stats.setdefault("value_evidence_drop_count", 0)
    stats.setdefault("field_retry_count", 0)
    stats.setdefault("field_retry_merged_count", 0)
    stats.setdefault("field_retry_missing_fields", {})
    stats.setdefault("post_filter_query_switch_count", 0)
    stats.setdefault("exa_fallback", 0)
    stats.setdefault("exa_empty", 0)
    stats.setdefault("exa_error", 0)
    stats.setdefault("exa_fallback_after_extract_422", 0)
    stats.setdefault("exa_fallback_after_extract_cooldown", 0)
    stats.setdefault("exa_skipped_no_key_after_extract", 0)
    stats.setdefault("extract_globally_disabled", bool(disable_extract))
    stats.setdefault(
        "extract_global_disable_reason",
        "cli_disable_extract" if disable_extract else None,
    )
    stats.setdefault("write_back_by_category", {})
    stats.setdefault("write_back_fallback_count", 0)
    stats.setdefault("write_back_miss_count", 0)
    stats.setdefault("deepseek_circuit_breaker_triggered", False)
    stats.setdefault("deepseek_circuit_breaker_reason", None)
    stats.setdefault("deepseek_timeout_rate", 0.0)
    stats.setdefault("deepseek_breaker_attempts", 0)
    stats.setdefault("deepseek_breaker_timeouts", 0)
    stats.setdefault("search_backend_final", "tavily")
    stats.setdefault("tavily_to_exa_failover", False)
    stats.setdefault("tavily_to_exa_failover_count", 0)
    stats.setdefault("exa_failover_success", 0)
    stats.setdefault("exa_failover_empty", 0)
    stats.setdefault("exa_failover_error", 0)
    stats.setdefault("exa_unavailable", 0)
    stats.setdefault("exa_error_breakdown", {})
    stats.setdefault("exa_error_samples", [])
    _structured_stats(stats)
    active_search_backend = "tavily"
    failover_reason = None
    active_tavily_limit_metadata: Dict[str, Any] = {}
    initial_unavailable_reason = stats.get("tavily_unavailable_reason")
    tavily_unavailable_reason: Optional[str] = (
        initial_unavailable_reason
        if initial_unavailable_reason in {"quota_or_rate_limit", "environment_proxy_error"}
        else None
    )
    forex_keys = {"USDCNY", "USDCNH", "DXY", "EURUSD", "GBPUSD", "USDJPY"}
    ds_semaphore = asyncio.Semaphore(max(1, deepseek_max_concurrency))
    serial_keys = set(deepseek_serial_keys or [])
    deepseek_circuit_breaker = _DeepSeekCircuitBreaker(
        max_consecutive_timeouts=deepseek_breaker_consecutive_timeouts,
        max_timeout_rate=deepseek_breaker_timeout_rate,
        min_attempts=deepseek_breaker_min_attempts,
    )
    extract_globally_disabled = disable_extract
    extract_disabled_until: Dict[str, float] = {}
    extract_422_tracker: Dict[str, Dict[str, Any]] = {}

    def _sync_deepseek_circuit_breaker_stats() -> None:
        stats["deepseek_circuit_breaker_triggered"] = bool(deepseek_circuit_breaker.triggered)
        stats["deepseek_circuit_breaker_reason"] = deepseek_circuit_breaker.reason
        stats["deepseek_timeout_rate"] = deepseek_circuit_breaker.timeout_rate
        stats["deepseek_breaker_attempts"] = deepseek_circuit_breaker.attempts
        stats["deepseek_breaker_timeouts"] = deepseek_circuit_breaker.timeouts

    def _deepseek_circuit_breaker_skip_reason() -> Optional[str]:
        if not deepseek_circuit_breaker.triggered:
            return None
        _sync_deepseek_circuit_breaker_stats()
        return f"deepseek_circuit_breaker:{deepseek_circuit_breaker.reason or 'triggered'}"

    def _mark_tavily_quota_unavailable() -> None:
        nonlocal tavily_unavailable_reason
        tavily_unavailable_reason = "quota_or_rate_limit"
        stats["tavily_unavailable_reason"] = "quota_or_rate_limit"

    def _mark_environment_proxy_unavailable(exc: Exception) -> None:
        nonlocal tavily_unavailable_reason
        tavily_unavailable_reason = "environment_proxy_error"
        stats["tavily_unavailable_reason"] = "environment_proxy_error"
        stats["environment_proxy_error"] = str(exc)

    def _record_tavily_limit_error(source: Any) -> Dict[str, Any]:
        nonlocal active_tavily_limit_metadata
        metadata = _tavily_error_metadata(source)
        active_tavily_limit_metadata = metadata
        stats["tavily_limit_error_count"] = stats.get("tavily_limit_error_count", 0) + 1
        samples = stats.setdefault("tavily_error_samples", [])
        if isinstance(samples, list) and len(samples) < 5:
            samples.append(metadata)
        return metadata

    def _get_or_record_tavily_limit_metadata(source: Any) -> Dict[str, Any]:
        nonlocal active_tavily_limit_metadata
        metadata = getattr(source, "tavily_metadata", None)
        if isinstance(metadata, dict) and metadata:
            active_tavily_limit_metadata = metadata
            return metadata
        return _record_tavily_limit_error(source)

    def _activate_exa_failover(task: Dict[str, Any], reason: str) -> bool:
        nonlocal active_search_backend, failover_reason
        if not exa_client:
            stats["exa_unavailable"] += 1
            return False
        if active_search_backend != "exa":
            active_search_backend = "exa"
            failover_reason = reason
            stats["tavily_to_exa_failover"] = True
            stats["tavily_to_exa_failover_count"] += 1
            stats["search_backend_final"] = "exa"
        return True

    def _record_exa_error(metadata: Dict[str, Any]) -> None:
        stats["exa_failover_error"] += 1
        tag = (
            metadata.get("exa_error_tag")
            or metadata.get("exa_http_status")
            or metadata.get("exa_error_type")
            or "unknown_error"
        )
        breakdown = stats.setdefault("exa_error_breakdown", {})
        if isinstance(breakdown, dict):
            breakdown[str(tag)] = breakdown.get(str(tag), 0) + 1
        samples = stats.setdefault("exa_error_samples", [])
        if isinstance(samples, list) and len(samples) < 5:
            samples.append(metadata)

    def _normalize_exa_snippets(result: Dict[str, Any]) -> Dict[str, Any]:
        normalized: List[Dict[str, Any]] = []
        for item in result.get("results") or []:
            if not isinstance(item, dict):
                continue
            snippet = dict(item)
            highlights = snippet.get("highlights")
            if isinstance(highlights, list):
                highlights_text = " ".join(str(v) for v in highlights if str(v).strip())
            else:
                highlights_text = str(highlights or "")
            content = (
                snippet.get("content")
                or snippet.get("raw_content")
                or snippet.get("text")
                or snippet.get("summary")
                or highlights_text
                or snippet.get("snippet")
                or ""
            )
            summary = snippet.get("summary") or highlights_text or content
            snippet["url"] = snippet.get("url") or snippet.get("source_url") or ""
            snippet["title"] = snippet.get("title") or ""
            snippet["snippet"] = snippet.get("snippet") or summary or content
            snippet["content"] = content
            snippet["published_date"] = snippet.get("published_date") or snippet.get("date")
            snippet["search_backend"] = "exa"
            normalized.append(snippet)
        result["results"] = normalized
        result.setdefault("search_backend", "exa")
        return result

    async def _run_exa_search_for_task(
        task: Dict[str, Any],
        reason: str,
        query_override: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], str, Dict[str, Any]]:
        if not _activate_exa_failover(task, reason):
            return None, "exa_unavailable", {"exa_error_tag": "unavailable"}
        query = query_override or task.get("query_used") or task.get("query") or task.get("indicator_key")
        include_domains = task.get("preferred_domains") or None
        exclude_domains = task.get("exclude_domains") or None
        num_results = task.get("max_results") or None
        start_published = _start_date_from_max_age(task.get("max_age_days"))
        search_type = _exa_search_type(task.get("indicator_key") or "")
        try:
            result = await exa_client.search(  # type: ignore[union-attr]
                query=query,
                num_results=num_results,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                start_published_date=start_published,
                search_type=search_type,
                contents={"text": True, "summary": True, "highlights": True},
                cache_ttl=cache_ttl,
            )
        except Exception as exc:  # pragma: no cover
            if AsyncExaClient and hasattr(AsyncExaClient, "error_metadata"):
                metadata = AsyncExaClient.error_metadata(exc)  # type: ignore[union-attr]
            else:
                metadata = {
                    "exa_error_type": type(exc).__name__,
                    "exa_error_message": str(exc),
                    "exa_error_tag": "unknown_error",
                }
            _record_exa_error(metadata)
            logger.warning(f"Exa search failover failed: {exc}")
            return None, "exa_error", metadata
        result = _normalize_exa_snippets(result or {})
        snippets = result.get("results") or []
        if not snippets:
            stats["exa_failover_empty"] += 1
            return None, "exa_empty", {
                "exa_error_tag": "empty_results",
                "exa_query": query,
                "exa_result_count": 0,
            }
        stats["exa_failover_success"] += 1
        return result, "exa_failover", {
            "exa_query": query,
            "exa_result_count": len(snippets),
            "exa_request_id": result.get("request_id"),
            "request_id": result.get("request_id"),
        }

    def _task_for_candidate(task: Dict[str, Any], candidate: Dict[str, Any], query: str) -> Dict[str, Any]:
        return {
            **task,
            "query": query,
            "preferred_domains": candidate.get("preferred_domains") or task.get("preferred_domains"),
            "exclude_domains": candidate.get("exclude_domains") or task.get("exclude_domains"),
            "required_keywords": candidate.get("required_keywords") or task.get("required_keywords"),
            "exclude_keywords": candidate.get("exclude_keywords") or task.get("exclude_keywords"),
            "strict_required_keywords": candidate.get(
                "strict_required_keywords",
                task.get("strict_required_keywords"),
            ),
            "strict_issuer_match": candidate.get("strict_issuer_match", task.get("strict_issuer_match")),
            "good_url_patterns": candidate.get("good_url_patterns") or task.get("good_url_patterns"),
            "bad_url_patterns": candidate.get("bad_url_patterns") or task.get("bad_url_patterns"),
            "evidence_keywords": candidate.get("evidence_keywords") or task.get("evidence_keywords"),
            "max_results": candidate.get("max_results") or task.get("max_results"),
        }

    async def _run_exa_search_candidates(
        task: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        reason: str,
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], str, Dict[str, Any]]:
        best_payload: Optional[Dict[str, Any]] = None
        attempts: List[Dict[str, Any]] = []
        last_note = "exa_empty"
        last_metadata: Dict[str, Any] = {}
        for idx, candidate in enumerate(candidates):
            query = str(candidate.get("query") or "").strip()
            if not query:
                continue
            exa_task = _task_for_candidate(task, candidate, query)
            result, note, metadata = await _run_exa_search_for_task(
                exa_task,
                reason,
                query_override=query,
            )
            last_note = note
            last_metadata = metadata or {}
            if not result:
                attempts.append(
                    {
                        "query": query,
                        "family": candidate.get("family"),
                        "field_scope": candidate.get("field_scope"),
                        "search_backend": "exa",
                        "manual_required": True,
                        "manual_reason": note,
                        **last_metadata,
                    }
                )
                continue
            raw_snippets = result.get("results") or []
            quality = _candidate_query_quality(task, candidate, raw_snippets)
            score_stats = quality.get("score_stats") or _score_stats(raw_snippets)
            attempt_meta = {
                "query": query,
                "family": candidate.get("family"),
                "field_scope": candidate.get("field_scope"),
                "search_backend": "exa",
                "result_count": len(raw_snippets),
                "usable_count": quality.get("usable_count"),
                "trusted_count": quality.get("trusted_count"),
                "issuer_hit": quality.get("issuer_hit"),
                "period_hit": quality.get("period_hit"),
                "score_max": score_stats.get("score_max"),
                "quality_score": quality.get("quality_score"),
                "usage_evidence_score": quality.get("usage_evidence_score"),
                "value_evidence_score": quality.get("value_evidence_score"),
                "good_url_hit_count": quality.get("good_url_hit_count"),
                "bad_url_hit_count": quality.get("bad_url_hit_count"),
                "unusable_reason": quality.get("unusable_reason"),
                **last_metadata,
            }
            attempts.append(attempt_meta)
            task_for_log = {
                **task,
                "search_backend": "exa",
                "query": query,
                "query_used": query,
                "query_family_used": candidate.get("family"),
                "field_scope": candidate.get("field_scope"),
                "score_stats": score_stats,
                "usable_count_before_extract": quality.get("usable_count", 0),
                "trusted_count": quality.get("trusted_count", 0),
                "issuer_hit": quality.get("issuer_hit", False),
                "period_hit": quality.get("period_hit", False),
                "selected_reason": quality.get("selected_reason"),
                "usage_evidence_score": quality.get("usage_evidence_score", 0),
                "value_evidence_score": quality.get("value_evidence_score", 0),
                "quality_score": quality.get("quality_score", -1.0),
                "good_url_hit_count": quality.get("good_url_hit_count", 0),
                "bad_url_hit_count": quality.get("bad_url_hit_count", 0),
                "unusable_reason": quality.get("unusable_reason"),
                "search_note": note,
                "search_backend_state": "exa_active",
                "failover_reason": reason,
                **last_metadata,
            }
            payload = {
                "candidate": candidate,
                "result": result,
                "raw_snippets": raw_snippets,
                "snippets": quality.get("snippets", raw_snippets),
                "score_stats": score_stats,
                "quality_score": quality.get("quality_score", -1.0),
                "selected_reason": quality.get("selected_reason"),
                "usable_count": quality.get("usable_count", 0),
                "trusted_count": quality.get("trusted_count", 0),
                "issuer_hit": quality.get("issuer_hit", False),
                "period_hit": quality.get("period_hit", False),
                "usage_evidence_score": quality.get("usage_evidence_score", 0),
                "value_evidence_score": quality.get("value_evidence_score", 0),
                "good_url_hit_count": quality.get("good_url_hit_count", 0),
                "bad_url_hit_count": quality.get("bad_url_hit_count", 0),
                "unusable_reason": quality.get("unusable_reason"),
                "task_for_log": task_for_log,
                "note": note,
                "metadata": last_metadata,
                "candidate_index": idx,
            }
            if best_payload is None or payload["quality_score"] > best_payload["quality_score"]:
                best_payload = payload
        if best_payload and best_payload.get("candidate_index", 0) > 0:
            stats["post_filter_query_switch_count"] += 1
        return best_payload, attempts, last_note, last_metadata

    def _quality_filter_exa_result(
        task: Dict[str, Any],
        result: Dict[str, Any],
        query_used: Optional[str],
    ) -> Dict[str, Any]:
        raw_snippets = result.get("results") or []
        candidate = {
            "query": query_used or result.get("query") or task.get("query"),
            "preferred_domains": task.get("preferred_domains"),
            "exclude_domains": task.get("exclude_domains"),
            "required_keywords": task.get("required_keywords"),
            "exclude_keywords": task.get("exclude_keywords"),
            "strict_required_keywords": task.get("strict_required_keywords"),
            "strict_issuer_match": task.get("strict_issuer_match"),
            "good_url_patterns": task.get("good_url_patterns"),
            "bad_url_patterns": task.get("bad_url_patterns"),
            "evidence_keywords": task.get("evidence_keywords"),
        }
        return _candidate_query_quality(task, candidate, raw_snippets)

    def _apply_exa_quality_to_task(
        task: Dict[str, Any],
        result: Dict[str, Any],
        query_used: Optional[str],
        search_note: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
        quality = _quality_filter_exa_result(task, result, query_used)
        snippets = quality.get("snippets") or []
        score_stats = quality.get("score_stats") or _score_stats(snippets)
        task_for_log = {
            **task,
            "search_backend": "exa",
            "query_used": query_used,
            "score_stats": score_stats,
            "usable_count_before_extract": quality.get("usable_count", 0),
            "trusted_count": quality.get("trusted_count", 0),
            "issuer_hit": quality.get("issuer_hit", False),
            "period_hit": quality.get("period_hit", False),
            "selected_reason": quality.get("selected_reason"),
            "usage_evidence_score": quality.get("usage_evidence_score", 0),
            "value_evidence_score": quality.get("value_evidence_score", 0),
            "quality_score": quality.get("quality_score", -1.0),
            "good_url_hit_count": quality.get("good_url_hit_count", 0),
            "bad_url_hit_count": quality.get("bad_url_hit_count", 0),
            "unusable_reason": quality.get("unusable_reason"),
        }
        if search_note:
            task_for_log["search_note"] = search_note
        return snippets, score_stats, task_for_log

    def _build_exa_failover_manual_records(
        task: Dict[str, Any],
        *,
        reason: str,
        attempt_index: int,
        elapsed_ms: int,
        error: Optional[Exception] = None,
        query_attempts: Optional[List[Dict[str, Any]]] = None,
        exa_metadata: Optional[Dict[str, Any]] = None,
        tavily_metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        now_ts = int(datetime.now().timestamp())
        query = task.get("query_used") or task.get("query") or task.get("indicator_key")
        note = f"exa_failover:{reason}"
        source = "Stage2 manual_required"
        category = task.get("category") or task.get("stage_phase")
        diagnostics = {**(tavily_metadata or {}), **(exa_metadata or {})}
        task_payload = {
            **task,
            **diagnostics,
            "category": category,
            "query": query,
            "query_used": task.get("query_used") or query,
            "query_attempts": query_attempts or task.get("query_attempts") or [],
            "search_backend": "exa",
            "search_backend_state": "exa_active",
            "failover_reason": failover_reason,
            "manual_required": True,
            "manual_reason": reason,
            "source": source,
            "note": note,
        }
        extraction = {
            **diagnostics,
            "value": None,
            "unit": task.get("unit"),
            "source_url": None,
            "confidence": 0.0,
            "note": note,
            "llm_error": None,
            "llm_latency_ms": 0,
            "manual_required": True,
            "manual_reason": reason,
        }
        task_record = {
            **diagnostics,
            **_structured_audit_fields_from_task(task),
            "task_id": task["task_id"],
            "indicator_key": task["indicator_key"],
            "category": category,
            "stage_phase": task["stage_phase"],
            "query": query,
            "search_backend": "exa",
            "search_backend_state": "exa_active",
            "failover_reason": failover_reason,
            "fund_flow_backend": task.get("fund_flow_backend"),
            "extraction_backend": extraction_backend,
            "source": source,
            "source_url": None,
            "confidence": 0.0,
            "error": str(error) if error else None,
            "llm_error": str(error) if error else None,
            "llm_latency_ms": None,
            "attempt_index": attempt_index,
            "elapsed_ms": elapsed_ms,
            "created_at": task.get("created_at", now_ts),
            "finished_at": now_ts,
            "manual_required": True,
            "manual_reason": reason,
            "note": note,
            "raw_results": [],
            "result_type": "manual_required",
        }
        websearch_item = {
            **diagnostics,
            "task_id": task["task_id"],
            "indicator_key": task["indicator_key"],
            "category": category,
            "stage_phase": task["stage_phase"],
            "query": query,
            "task": task_payload,
            "extraction": extraction,
            "extraction_backend": extraction_backend,
            "raw_results": [],
            "search_backend": "exa",
            "manual_required": True,
            "manual_reason": reason,
            "source": source,
            "note": note,
            "result_type": "manual_required",
        }
        return task_record, websearch_item

    def _build_tavily_fast_switch_records(
        task: Dict[str, Any],
        *,
        attempt_index: int,
        elapsed_ms: int,
        error: Optional[Exception] = None,
        query_attempts: Optional[List[Dict[str, Any]]] = None,
        tavily_metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        now_ts = int(datetime.now().timestamp())
        query = task.get("query_used") or task.get("query") or task.get("indicator_key")
        note = "tavily_fast_switch:quota_or_rate_limit"
        source = "Stage2 manual_required"
        category = task.get("category") or task.get("stage_phase")
        diagnostics = tavily_metadata or {}
        task_payload = {
            **task,
            **diagnostics,
            "category": category,
            "query": query,
            "query_used": task.get("query_used") or query,
            "query_attempts": query_attempts or task.get("query_attempts") or [],
            "manual_required": True,
            "manual_reason": "quota_or_rate_limit",
            "source": source,
            "note": note,
            "tavily_fast_switch": True,
        }
        extraction = {
            **diagnostics,
            "value": None,
            "unit": task.get("unit"),
            "source_url": None,
            "confidence": 0.0,
            "note": note,
            "llm_error": None,
            "llm_latency_ms": 0,
            "manual_required": True,
            "manual_reason": "quota_or_rate_limit",
            "tavily_fast_switch": True,
        }
        task_record = {
            **diagnostics,
            **_structured_audit_fields_from_task(task),
            "task_id": task["task_id"],
            "indicator_key": task["indicator_key"],
            "category": category,
            "stage_phase": task["stage_phase"],
            "query": query,
            "search_backend": task.get("search_backend", "tavily"),
            "fund_flow_backend": task.get("fund_flow_backend"),
            "extraction_backend": extraction_backend,
            "source": source,
            "source_url": None,
            "confidence": 0.0,
            "error": str(error) if error else None,
            "llm_error": str(error) if error else None,
            "llm_latency_ms": None,
            "attempt_index": attempt_index,
            "elapsed_ms": elapsed_ms,
            "created_at": task.get("created_at", now_ts),
            "finished_at": now_ts,
            "manual_required": True,
            "manual_reason": "quota_or_rate_limit",
            "note": note,
            "raw_results": [],
            "tavily_fast_switch": True,
            "result_type": "manual_required",
        }
        websearch_item = {
            **diagnostics,
            "task_id": task["task_id"],
            "indicator_key": task["indicator_key"],
            "category": category,
            "stage_phase": task["stage_phase"],
            "query": query,
            "task": task_payload,
            "extraction": extraction,
            "extraction_backend": extraction_backend,
            "raw_results": [],
            "search_backend": task.get("search_backend", "tavily"),
            "manual_required": True,
            "manual_reason": "quota_or_rate_limit",
            "source": source,
            "note": note,
            "tavily_fast_switch": True,
            "result_type": "manual_required",
        }
        return task_record, websearch_item

    def _is_tavily_fast_switch_record(record: Dict[str, Any]) -> bool:
        return (
            bool(record.get("tavily_fast_switch") or record.get("environment_proxy_fast_switch"))
            or (
                record.get("manual_reason") == "quota_or_rate_limit"
                and "tavily_fast_switch" in str(record.get("note") or "")
            )
            or (
                record.get("manual_reason") == "environment_proxy_error"
                and "environment_proxy_error" in str(record.get("note") or "")
            )
        )

    def _is_tavily_fast_switch_websearch(item: Dict[str, Any]) -> bool:
        extraction = item.get("extraction") or {}
        task = item.get("task") or {}
        return (
            _is_tavily_fast_switch_record(item)
            or _is_tavily_fast_switch_record(extraction)
            or _is_tavily_fast_switch_record(task)
        )

    def _attach_field_attempts(
        task_record: Dict[str, Any],
        websearch_item: Dict[str, Any],
        field_attempts: List[Dict[str, Any]],
    ) -> None:
        if not field_attempts:
            return
        task_record["field_attempts"] = field_attempts
        websearch_item["field_attempts"] = field_attempts
        if isinstance(websearch_item.get("task"), dict):
            websearch_item["task"]["field_attempts"] = field_attempts

    def _exa_metadata_from_attempt(attempt: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in attempt.items()
            if str(key).startswith("exa_") or key == "request_id"
        }

    def _tavily_diagnostics_from_task(
        task: Dict[str, Any],
        field_attempts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        diagnostics = {
            key: task[key]
            for key in ("tavily_http_status", "tavily_request_id", "tavily_error_message")
            if key in task
        }
        if not diagnostics and field_attempts:
            for attempt in reversed(field_attempts):
                diagnostics = {
                    key: attempt[key]
                    for key in ("tavily_http_status", "tavily_request_id", "tavily_error_message")
                    if key in attempt
                }
                if diagnostics:
                    break
        if not diagnostics and task.get("search_backend") == "exa" and active_tavily_limit_metadata:
            diagnostics = dict(active_tavily_limit_metadata)
        return diagnostics

    def _field_retry_used_exa(field_attempts: List[Dict[str, Any]]) -> bool:
        return any(attempt.get("search_backend") == "exa" for attempt in field_attempts or [])

    def _promote_task_to_exa_after_field_retry(
        task: Dict[str, Any],
        field_attempts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not _field_retry_used_exa(field_attempts):
            return task
        promoted = {
            **task,
            "search_backend": "exa",
            "search_backend_state": "exa_active",
            "failover_reason": failover_reason or "quota_or_rate_limit",
        }
        promoted.update(active_tavily_limit_metadata)
        return promoted

    def _infer_flow_direction(snips: List[Dict[str, Any]]) -> Optional[str]:
        """从 snippet/content 中粗略推断资金流向，返回 inflow/outflow/None"""
        text_parts: List[str] = []
        for s in snips[:3]:  # 只看前几条，减少噪声
            for field in ("content", "snippet"):
                val = s.get(field)
                if val:
                    text_parts.append(str(val))
        blob = " ".join(text_parts).lower()
        if any(k in blob for k in ["流出", "净流出", "净卖出", "卖出"]):
            return "outflow"
        if any(k in blob for k in ["流入", "净流入", "净买入", "买入"]):
            return "inflow"
        return None

    async def _run_with_timeout(coro):
        if llm_hard_timeout and llm_hard_timeout > 0:
            return await asyncio.wait_for(coro, timeout=llm_hard_timeout)
        return await coro

    def _call_fallback_extract(snips: List[Dict[str, Any]], task: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
        """兼容旧/新签名的 fallback 提取器。"""
        fallback_fn = getattr(extractor, "_fallback_extract", None)
        if not callable(fallback_fn):
            return None, snips[0].get("url") if snips else None
        try:
            return fallback_fn(  # type: ignore[misc]
                snips,
                indicator=task.get("indicator_key"),
                unit_hint=task.get("unit"),
            )
        except TypeError:
            # 兼容旧签名: _fallback_extract(snips)
            return fallback_fn(snips)  # type: ignore[misc]

    async def _do_extract(snips: List[Dict[str, Any]], task: Dict[str, Any]) -> Dict[str, Any]:
        """执行抽取，记录 DeepSeek 延迟与错误；regex 模式直接返回占位。"""
        if extraction_backend == "regex":
            val = _regex_fallback(snips, task.get("indicator_key", ""))
            url = None
            if val is None:
                strict_keys = {"industrial", "industrial_sales", "reverse_repo", "mlf"}
                if task.get("indicator_key") in strict_keys:
                    return {
                        "value": None,
                        "unit": task.get("unit"),
                        "source_url": snips[0].get("url") if snips else None,
                        "confidence": 0.0,
                        "note": "regex_only_no_match",
                        "llm_latency_ms": 0,
                        "llm_error": None,
                    }
                val, url = _call_fallback_extract(snips, task)
            return {
                "value": val,
                "unit": task.get("unit"),
                "source_url": url or (snips[0].get("url") if snips else None),
                "confidence": 0.35 if val is not None else 0.0,
                "note": "regex_only",
                "llm_latency_ms": 0,
                "llm_error": None,
            }
        breaker_skip_reason = _deepseek_circuit_breaker_skip_reason()
        if breaker_skip_reason:
            skipped_note = f"skipped_deepseek:{breaker_skip_reason}"
            return {
                "value": None,
                "unit": task.get("unit"),
                "source_url": None,
                "confidence": 0.0,
                "note": skipped_note,
                "llm_error": skipped_note,
                "llm_timeout": False,
                "llm_latency_ms": 0,
                "manual_required": True,
                "manual_reason": skipped_note,
                "extraction_skipped_reason": breaker_skip_reason,
            }
        start_llm = time.perf_counter()
        attempts = 0
        while attempts < 2:
            attempts += 1
            try:
                if task["indicator_key"] in serial_keys:
                    result = await _run_with_timeout(
                        extractor.extract(
                            snips,
                            task["indicator_key"],
                            unit_hint=task.get("unit"),
                            issuer_hint=task.get("issuer"),
                            request_timeout=deepseek_timeout,
                        )
                    )
                else:
                    async with ds_semaphore:
                        result = await _run_with_timeout(
                            extractor.extract(
                                snips,
                                task["indicator_key"],
                                unit_hint=task.get("unit"),
                                issuer_hint=task.get("issuer"),
                                request_timeout=deepseek_timeout,
                            )
                        )
                result = result or {}
                deepseek_circuit_breaker.record(timeout=False)
                _sync_deepseek_circuit_breaker_stats()
                result["llm_latency_ms"] = int((time.perf_counter() - start_llm) * 1000)
                stats.setdefault("deepseek_latencies", []).append(result["llm_latency_ms"])
                if attempts > 1:
                    stats["retry_count"] += 1
                return result
            except Exception as exc:  # pragma: no cover
                is_timeout = _is_deepseek_timeout(exc)
                deepseek_circuit_breaker.record(timeout=is_timeout)
                _sync_deepseek_circuit_breaker_stats()
                if is_timeout:
                    stats["timeout_count"] += 1
                    stats["deepseek_timeouts"] += 1
                if attempts >= 2 or deepseek_circuit_breaker.triggered:
                    logger.warning(f"DeepSeek 请求失败，将使用 regex 兜底: {exc}")
                    val, url = _call_fallback_extract(snips, task)
                    return {
                        "value": val,
                        "unit": task.get("unit"),
                        "source_url": url or (snips[0].get("url") if snips else None),
                        "confidence": 0.2 if val is not None else 0.0,
                        "note": f"deepseek_error:{exc} regex_fallback",
                        "llm_error": str(exc),
                        "llm_timeout": is_timeout,
                        "llm_latency_ms": int((time.perf_counter() - start_llm) * 1000),
                    }

    async def _try_exa_fallback(
        task: Dict[str, Any],
        reason: str,
        query_override: Optional[str] = None,
    ) -> (Optional[Dict[str, Any]], Optional[str]):
        if not allow_exa_non_quota_fallback:
            return None, None
        if not exa_client:
            if reason in {"extract_422", "extract_cooldown"}:
                stats["exa_skipped_no_key_after_extract"] += 1
            return None, None
        if task.get("indicator_key") in {"northbound", "southbound", "etf", "margin"}:
            return None, None
        query = query_override or task.get("query") or task.get("indicator_key")
        include_domains = task.get("preferred_domains") or None
        num_results = task.get("max_results") or None
        start_published = _start_date_from_max_age(task.get("max_age_days"))
        search_type = _exa_search_type(task.get("indicator_key") or "")
        contents = {"text": True, "summary": True, "highlights": True}
        try:
            logger.debug(f"Exa fallback: {task.get('indicator_key')} reason={reason}")
            result = await exa_client.search(
                query=query,
                num_results=num_results,
                include_domains=include_domains,
                start_published_date=start_published,
                search_type=search_type,
                contents=contents,
                cache_ttl=cache_ttl,
            )
        except Exception as exc:  # pragma: no cover
            stats["exa_error"] += 1
            logger.warning(f"Exa fallback failed: {exc}")
            return None, f"exa_error:{exc}"
        snippets = result.get("results") or []
        if not snippets:
            stats["exa_empty"] += 1
            return None, "exa_empty"
        stats["exa_fallback"] += 1
        if reason == "extract_422":
            stats["exa_fallback_after_extract_422"] += 1
            return result, "exa_fallback_after_extract_422"
        if reason == "extract_cooldown":
            stats["exa_fallback_after_extract_cooldown"] += 1
            return result, "exa_fallback_after_extract_cooldown"
        return result, "exa_fallback"

    async def _run_search_candidates(
        task: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[Exception]]:
        best_payload: Optional[Dict[str, Any]] = None
        attempts: List[Dict[str, Any]] = []
        last_exc: Optional[Exception] = None
        for idx, candidate in enumerate(candidates):
            query = str(candidate.get("query") or "").strip()
            if not query:
                continue
            try:
                result = await client.search(
                    query=query,
                    search_depth=candidate.get("search_depth")
                    or ("advanced" if task["stage_phase"] == "assets" else "basic"),
                    include_domains=candidate.get("preferred_domains") or None,
                    exclude_domains=candidate.get("exclude_domains") or None,
                    time_range=candidate.get("time_range"),
                    topic=candidate.get("topic"),
                    language=task.get("language"),
                    max_results=candidate.get("max_results"),
                    days=candidate.get("days"),
                    chunks_per_source=candidate.get("chunks_per_source"),
                    auto_parameters=candidate.get("auto_parameters"),
                    cache_ttl=cache_ttl,
                )
                raw_snippets = result.get("results") or []
                quality = _candidate_query_quality(task, candidate, raw_snippets)
                attempt_meta = {
                    "query": query,
                    "family": candidate.get("family"),
                    "field_scope": candidate.get("field_scope"),
                    "result_count": len(raw_snippets),
                    "usable_count": quality.get("usable_count"),
                    "trusted_count": quality.get("trusted_count"),
                    "issuer_hit": quality.get("issuer_hit"),
                    "period_hit": quality.get("period_hit"),
                    "score_max": quality.get("score_stats", {}).get("score_max"),
                    "quality_score": quality.get("quality_score"),
                    "usage_evidence_score": quality.get("usage_evidence_score"),
                    "value_evidence_score": quality.get("value_evidence_score"),
                    "good_url_hit_count": quality.get("good_url_hit_count"),
                    "bad_url_hit_count": quality.get("bad_url_hit_count"),
                    "unusable_reason": quality.get("unusable_reason"),
                }
                attempts.append(attempt_meta)
                payload = {
                    "candidate": candidate,
                    "result": result,
                    "raw_snippets": raw_snippets,
                    "snippets": quality.get("snippets", raw_snippets),
                    "score_stats": quality.get("score_stats") or _score_stats(raw_snippets),
                    "quality_score": quality.get("quality_score", -1.0),
                    "selected_reason": quality.get("selected_reason"),
                    "usable_count": quality.get("usable_count", 0),
                    "trusted_count": quality.get("trusted_count", 0),
                    "issuer_hit": quality.get("issuer_hit", False),
                    "period_hit": quality.get("period_hit", False),
                    "usage_evidence_score": quality.get("usage_evidence_score", 0),
                    "value_evidence_score": quality.get("value_evidence_score", 0),
                    "good_url_hit_count": quality.get("good_url_hit_count", 0),
                    "bad_url_hit_count": quality.get("bad_url_hit_count", 0),
                    "unusable_reason": quality.get("unusable_reason"),
                    "candidate_index": idx,
                }
                if best_payload is None or payload["quality_score"] > best_payload["quality_score"]:
                    best_payload = payload
            except Exception as exc:
                last_exc = exc
                is_proxy_error = _is_environment_proxy_error(exc)
                is_quota_error = False if is_proxy_error else _is_tavily_quota_error(exc)
                manual_reason = None
                if is_proxy_error:
                    _mark_environment_proxy_unavailable(exc)
                    manual_reason = "environment_proxy_error"
                elif is_quota_error:
                    manual_reason = "quota_or_rate_limit"
                if is_quota_error:
                    _mark_tavily_quota_unavailable()
                attempts.append(
                    {
                        "query": query,
                        "family": candidate.get("family"),
                        "field_scope": candidate.get("field_scope"),
                        "error": str(exc),
                        "manual_required": True if (is_proxy_error or is_quota_error) else None,
                        "manual_reason": manual_reason,
                    }
                )
                if is_proxy_error or is_quota_error:
                    raise exc
        if best_payload and best_payload.get("candidate_index", 0) > 0:
            stats["post_filter_query_switch_count"] += 1
        return best_payload, attempts, last_exc

    async def _retry_fund_flow_fields(
        task: Dict[str, Any],
        extraction: Dict[str, Any],
        active_backend: str,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        field_queries = task.get("field_queries") or {}
        if not field_queries:
            return extraction, []
        missing_fields = []
        if _safe_number(extraction.get("recent_5d")) is None:
            missing_fields.append("recent_5d")
        if _safe_number(extraction.get("total_120d")) is None:
            missing_fields.append("total_120d")
        if not missing_fields:
            return extraction, []

        stats["field_retry_missing_fields"][task["indicator_key"]] = list(missing_fields)
        field_attempts: List[Dict[str, Any]] = []
        for field_scope in missing_fields:
            candidates = _expand_query_candidates(task, field_scopes=[field_scope], include_primary=False)
            if not candidates:
                continue
            stats["field_retry_count"] += 1
            field_failover_reason: Optional[str] = None
            field_failover_tavily_metadata: Dict[str, Any] = {}
            field_failover_exa_metadata: Dict[str, Any] = {}
            if str(active_backend or "").lower() == "exa":
                best_payload = None
                attempts: List[Dict[str, Any]] = []
                field_search_backend = "exa"
                field_failover_tavily_metadata = dict(active_tavily_limit_metadata)
                for idx, candidate in enumerate(candidates):
                    query = str(candidate.get("query") or "").strip()
                    if not query:
                        continue
                    field_task_candidate = {
                        **task,
                        "field_scope": field_scope,
                        "query": query,
                        "preferred_domains": candidate.get("preferred_domains") or task.get("preferred_domains"),
                        "exclude_domains": candidate.get("exclude_domains") or task.get("exclude_domains"),
                        "required_keywords": candidate.get("required_keywords") or task.get("required_keywords"),
                        "exclude_keywords": candidate.get("exclude_keywords") or task.get("exclude_keywords"),
                        "max_results": candidate.get("max_results") or task.get("max_results"),
                    }
                    result, note, metadata = await _run_exa_search_for_task(
                        field_task_candidate,
                        failover_reason or "field_retry",
                        query_override=query,
                    )
                    if not result:
                        field_failover_reason = note
                        field_failover_exa_metadata = metadata or {}
                        attempts.append(
                            {
                                "query": query,
                                "family": candidate.get("family"),
                                "field_scope": field_scope,
                                "search_backend": "exa",
                                "manual_required": True,
                                "manual_reason": note,
                                **(metadata or {}),
                            }
                        )
                        continue
                    field_snippets, field_score_stats, field_task_for_log = _apply_exa_quality_to_task(
                        field_task_candidate,
                        result,
                        result.get("query") or query,
                        note,
                    )
                    attempt_meta = {
                        "query": query,
                        "family": candidate.get("family"),
                        "field_scope": field_scope,
                        "search_backend": "exa",
                        "result_count": len(result.get("results") or []),
                        "usable_count": field_task_for_log.get("usable_count_before_extract"),
                        "trusted_count": field_task_for_log.get("trusted_count"),
                        "issuer_hit": field_task_for_log.get("issuer_hit"),
                        "period_hit": field_task_for_log.get("period_hit"),
                        "score_max": field_score_stats.get("score_max"),
                        "quality_score": field_task_for_log.get("quality_score"),
                        "usage_evidence_score": field_task_for_log.get("usage_evidence_score"),
                        "value_evidence_score": field_task_for_log.get("value_evidence_score"),
                        "good_url_hit_count": field_task_for_log.get("good_url_hit_count"),
                        "bad_url_hit_count": field_task_for_log.get("bad_url_hit_count"),
                        "unusable_reason": field_task_for_log.get("unusable_reason"),
                    }
                    attempts.append(attempt_meta)
                    payload = {
                        "candidate": candidate,
                        "result": result,
                        "snippets": field_snippets,
                        "score_stats": field_score_stats,
                        "quality_score": field_task_for_log.get("quality_score", -1.0),
                        "task_for_log": field_task_for_log,
                        "candidate_index": idx,
                    }
                    if best_payload is None or payload["quality_score"] > best_payload["quality_score"]:
                        best_payload = payload
            else:
                field_search_backend = str(active_backend or task.get("search_backend") or "tavily").lower()
                try:
                    best_payload, attempts, _ = await _run_search_candidates(task, candidates)
                except Exception as exc:
                    if _is_environment_proxy_error(exc):
                        raise
                    if not _is_tavily_quota_error(exc):
                        raise
                    tavily_metadata = _record_tavily_limit_error(exc)
                    _mark_tavily_quota_unavailable()
                    failed_candidate = next(
                        (candidate for candidate in candidates if str(candidate.get("query") or "").strip()),
                        {},
                    )
                    tavily_attempt = {
                        "query": failed_candidate.get("query"),
                        "family": failed_candidate.get("family"),
                        "field_scope": failed_candidate.get("field_scope") or field_scope,
                        "search_backend": "tavily",
                        "manual_required": True,
                        "manual_reason": "quota_or_rate_limit",
                        "error": str(exc),
                        **tavily_metadata,
                    }
                    field_failover_tavily_metadata = tavily_metadata
                    if not _activate_exa_failover(task, "quota_or_rate_limit"):
                        attempts = [tavily_attempt]
                        setattr(exc, "tavily_metadata", tavily_metadata)
                        setattr(exc, "query_attempts", attempts)
                        setattr(exc, "field_attempts", attempts)
                        raise
                    active_backend = "exa"
                    field_search_backend = "exa"
                    exa_best_payload, exa_attempts, _exa_note, _exa_metadata = await _run_exa_search_candidates(
                        task,
                        candidates,
                        "quota_or_rate_limit",
                    )
                    attempts = [tavily_attempt] + exa_attempts
                    field_failover_reason = _exa_note
                    field_failover_exa_metadata = _exa_metadata or {}
                    best_payload = exa_best_payload
            field_attempts.extend(attempts)
            field_failover_manual = extraction.get("_field_retry_failover_manual")
            if isinstance(field_failover_manual, dict):
                field_failover_manual["query_attempts"] = list(field_attempts)
                field_failover_manual["field_attempts"] = list(field_attempts)
            if not best_payload:
                if field_search_backend == "exa" and attempts:
                    exa_attempt = next(
                        (
                            attempt
                            for attempt in reversed(attempts)
                            if attempt.get("search_backend") == "exa"
                        ),
                        {},
                    )
                    reason = (
                        field_failover_reason
                        or exa_attempt.get("manual_reason")
                        or "exa_empty"
                    )
                    if reason in {"exa_empty", "exa_error", "exa_unavailable"} and not extraction.get(
                        "_field_retry_failover_manual"
                    ):
                        extraction["_field_retry_failover_manual"] = {
                            "reason": reason,
                            "tavily_metadata": field_failover_tavily_metadata
                            or dict(active_tavily_limit_metadata),
                            "exa_metadata": field_failover_exa_metadata
                            or _exa_metadata_from_attempt(exa_attempt),
                            "query_attempts": list(field_attempts),
                            "field_attempts": list(field_attempts),
                        }
                        extraction["manual_required"] = True
                        extraction["manual_reason"] = reason
                continue
            field_task = {
                **task,
                "field_scope": field_scope,
                "query": best_payload["candidate"].get("query"),
                "query_used": best_payload["candidate"].get("query"),
                "query_family_used": best_payload["candidate"].get("family"),
                "search_backend": field_search_backend,
            }
            field_snippets = best_payload.get("snippets") or []
            if not field_snippets:
                continue
            field_extraction = await _do_extract(field_snippets, field_task)
            _augment_extraction_metadata(field_extraction, field_task, field_snippets)
            _refine_extraction_value(field_extraction, field_task, field_snippets)
            value = _safe_number(field_extraction.get(field_scope))
            if value is None:
                value = _safe_number(field_extraction.get("value"))
            if value is None:
                value, inferred_direction = _extract_flow_value(field_snippets, task["indicator_key"])
                if inferred_direction and field_extraction.get("trend") in {None, "unknown"}:
                    field_extraction["trend"] = inferred_direction
            if value is None:
                continue
            extraction[field_scope] = value
            field_source_url, evidence_snippets = _resolve_field_retry_evidence_source(
                field_extraction,
                field_snippets,
                value,
            )
            field_payload_for_tier = dict(field_extraction)
            if field_source_url:
                field_payload_for_tier["source_url"] = field_source_url
            field_metric_basis = _default_fund_flow_metric_basis(task["indicator_key"], field_extraction)
            field_window_evidence = _field_retry_window_evidence(
                field_scope,
                task["indicator_key"],
                field_extraction,
                evidence_snippets,
                field_metric_basis,
                value,
            )
            field_retry_evidence = extraction.setdefault("field_retry_evidence", {})
            if isinstance(field_retry_evidence, dict):
                field_retry_evidence[field_scope] = {
                    "source_url": field_source_url,
                    "source_tier": _infer_fund_flow_source_tier(field_payload_for_tier),
                    "window_evidence": field_window_evidence,
                    "metric_basis": field_metric_basis,
                }
            stats["field_retry_merged_count"] += 1
            extraction["note"] = _append_note(
                extraction.get("note"),
                f"{field_scope}_field_retry:{field_task.get('query')}",
            )
            if not extraction.get("source_url"):
                extraction["source_url"] = field_source_url
            trend = field_extraction.get("trend")
            if trend and extraction.get("trend") in {None, "unknown"}:
                extraction["trend"] = trend
        if _safe_number(extraction.get("value")) is None and _safe_number(extraction.get("recent_5d")) is not None:
            extraction["value"] = _safe_number(extraction.get("recent_5d"))
        if (
            _safe_number(extraction.get("recent_5d")) is not None
            and _safe_number(extraction.get("total_120d")) is not None
        ):
            manual_reason = str(extraction.get("manual_reason") or "")
            if "fund_flow_window_missing" in manual_reason:
                cleaned = manual_reason.replace("fund_flow_window_missing", " ").replace(";;", ";")
                cleaned = re.sub(r"\s+", " ", cleaned).strip(" ;")
                extraction["manual_reason"] = cleaned or None
            if not extraction.get("manual_reason"):
                extraction["manual_required"] = False
        return extraction, field_attempts
    queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize) if use_queue else None  # type: ignore

    async def consumer():
        while True:
            try:
                item = await queue.get()  # type: ignore
            except asyncio.CancelledError:
                break
            task, snippets, attempt_idx = item
            try:
                pre_extract_skip_reason = _deepseek_circuit_breaker_skip_reason()
                if not pre_extract_skip_reason:
                    stats["extract_calls"] += 1
                extraction = await _do_extract(snippets, task)
                extraction_skipped_reason = (
                    extraction.get("extraction_skipped_reason")
                    or task.get("extraction_skipped_reason")
                )
                # regex 兜底：关键指标无值时尝试直接提取数字
                if extraction.get("value") is None:
                    regex_val = _regex_fallback(snippets, task["indicator_key"])
                    if regex_val is not None:
                        extraction["value"] = regex_val
                        extraction.setdefault("note", "regex_fallback")
                        stats["regex_hits"] += 1
                _augment_extraction_metadata(extraction, task, snippets)
                _refine_extraction_value(extraction, task, snippets)
                is_fund_flow = task["indicator_key"] in {"northbound", "southbound", "etf", "margin"}
                field_attempts: List[Dict[str, Any]] = []
                if is_fund_flow:
                    extraction, field_attempts = await _retry_fund_flow_fields(
                        task,
                        extraction,
                        str(task.get("search_backend") or active_search_backend),
                    )
                    field_failover_manual = extraction.pop("_field_retry_failover_manual", None)
                    if isinstance(field_failover_manual, dict):
                        task_record, websearch_item = _build_exa_failover_manual_records(
                            task,
                            reason=str(field_failover_manual.get("reason") or "exa_empty"),
                            attempt_index=attempt_idx,
                            elapsed_ms=0,
                            query_attempts=field_attempts or field_failover_manual.get("query_attempts"),
                            exa_metadata=field_failover_manual.get("exa_metadata") or {},
                            tavily_metadata=field_failover_manual.get("tavily_metadata") or {},
                        )
                        _attach_field_attempts(
                            task_record,
                            websearch_item,
                            field_attempts or field_failover_manual.get("field_attempts") or [],
                        )
                        failures.append(task_record)
                        manual_required_keys.append(task_record["indicator_key"])
                        _append_task_log(task_log_path, task_record)
                        websearch_results.append(websearch_item)
                        continue
                    task = _promote_task_to_exa_after_field_retry(task, field_attempts)
                manual_required = bool(extraction.get("manual_required"))
                manual_reason = extraction.get("manual_reason")
                if manual_reason:
                    extraction["note"] = _append_note(extraction.get("note"), str(manual_reason))
                if is_fund_flow and (extraction.get("confidence", 0.0) < 0.5 or extraction.get("value") is None):
                    manual_required = True
                if is_fund_flow:
                    adjusted_value, unit_manual, note_append = _validate_fund_flow_extraction(
                        extraction, indicator_key=task["indicator_key"]
                    )
                    extraction["value"] = adjusted_value
                    combined_note = " ".join(
                        s for s in [extraction.get("note", ""), note_append] if s
                    ).strip()
                    extraction["note"] = combined_note or None
                    if unit_manual and _safe_number(extraction.get("recent_5d")) is not None and _safe_number(
                        extraction.get("total_120d")
                    ) is not None:
                        metric_basis = _default_fund_flow_metric_basis(task["indicator_key"], extraction)
                        window_evidence = _infer_fund_flow_window_evidence(
                            task["indicator_key"], extraction, metric_basis
                        )
                        if window_evidence not in {"direct_window", "direct_daily_series", "direct_balance_delta"}:
                            extraction["manual_reason"] = _append_note(
                                extraction.get("manual_reason"),
                                "fund_flow_window_missing",
                            )
                    manual_required = manual_required or unit_manual
                else:
                    val_adj, manual2, note_append2 = _validate_general_extraction(extraction, task, snippets)
                    extraction["value"] = val_adj
                    if note_append2:
                        extraction["note"] = ((extraction.get("note") or "") + " " + note_append2).strip()
                    manual_required = manual_required or manual2

                tavily_diagnostics = _tavily_diagnostics_from_task(task, field_attempts)
                task_record = {
                    **tavily_diagnostics,
                    "task_id": task["task_id"],
                    "indicator_key": task["indicator_key"],
                    "stage_phase": task["stage_phase"],
                    "search_backend": task["search_backend"],
                    "fund_flow_backend": task.get("fund_flow_backend") if is_fund_flow else None,
                    "extraction_backend": extraction_backend,
                    "confidence": extraction.get("confidence", 0.0),
                    "source_url": extraction.get("source_url"),
                    "note": extraction.get("note"),
                    "llm_latency_ms": extraction.get("llm_latency_ms"),
                    "llm_error": extraction.get("llm_error"),
                    "deepseek_error": extraction.get("note")
                    if isinstance(extraction.get("note"), str)
                    and extraction["note"]
                    and extraction["note"].startswith("deepseek_error")
                    else None,
                    "request_id": task.get("request_id") or task.get("exa_request_id"),
                    "http_status": None,
                    "cache_hit": None,
                    "attempt_index": attempt_idx,
                    "elapsed_ms": None,
                    "created_at": task["created_at"],
                    "finished_at": int(datetime.now().timestamp()),
                    "manual_required": manual_required,
                    "manual_reason": extraction.get("manual_reason"),
                    "extraction_skipped_reason": extraction_skipped_reason,
                    "extract_skipped_reason": task.get("extract_skipped_reason"),
                    "query_used": task.get("query_used"),
                    "query_family_used": task.get("query_family_used"),
                    "field_scope": task.get("field_scope"),
                    "usable_count_before_extract": task.get("usable_count_before_extract"),
                    "trusted_count": task.get("trusted_count"),
                    "issuer_hit": task.get("issuer_hit"),
                    "period_hit": task.get("period_hit"),
                    "selected_reason": task.get("selected_reason"),
                    "usage_evidence_score": task.get("usage_evidence_score"),
                    "value_evidence_score": task.get("value_evidence_score"),
                    "good_url_hit_count": task.get("good_url_hit_count"),
                    "bad_url_hit_count": task.get("bad_url_hit_count"),
                    "score_min": (task.get("score_stats") or {}).get("score_min"),
                    "score_p50": (task.get("score_stats") or {}).get("score_p50"),
                    "score_p95": (task.get("score_stats") or {}).get("score_p95"),
                    "score_max": (task.get("score_stats") or {}).get("score_max"),
                    "score_count": (task.get("score_stats") or {}).get("score_count"),
                    "score_low_threshold": task.get("score_low_threshold"),
                    "score_low_all": task.get("score_low_all"),
                    "score_filtered_drop": task.get("score_filtered_drop"),
                    "domain_filtered_drop": task.get("domain_filtered_drop"),
                }
                task_record.update(_structured_audit_fields_from_task(task))
                if manual_required:
                    failures.append(task_record)
                    if extraction.get("value") is None:
                        manual_required_keys.append(task_record["indicator_key"])
                else:
                    write_target = _apply_extraction(market_payload, task, extraction, snippets=snippets)
                    write_stats = stats.setdefault("write_back_by_category", {})
                    if isinstance(write_stats, dict):
                        write_stats[write_target] = write_stats.get(write_target, 0) + 1
                    if write_target == "fallback_macro":
                        stats["write_back_fallback_count"] += 1
                    elif write_target == "skip_no_value":
                        stats["write_back_miss_count"] += 1
                    post_writeback_reason = _post_writeback_manual_reason(market_payload, task["indicator_key"])
                    if post_writeback_reason:
                        _mark_post_writeback_manual_required(
                            market_payload,
                            task_record,
                            extraction,
                            task["indicator_key"],
                            post_writeback_reason,
                        )
                        failures.append(task_record)
                        manual_required_keys.append(task_record["indicator_key"])
                        manual_required = True
                    else:
                        _update_missing_items(market_payload, task["indicator_key"])
                        completed.append(task_record)
                _append_task_log(task_log_path, task_record)
                websearch_results.append(
                    {
                        "task": (
                            {**task, "extraction_skipped_reason": extraction_skipped_reason}
                            if extraction_skipped_reason
                            else task
                        ),
                        "extraction": extraction,
                        "extraction_backend": extraction_backend,
                        "raw_results": snippets[:3],
                        "field_attempts": field_attempts,
                        "search_backend": task.get("search_backend"),
                        "note": task.get("search_note"),
                        "manual_required": task_record.get("manual_required"),
                        "manual_reason": task_record.get("manual_reason") or extraction.get("manual_reason"),
                    }
                )
            except Exception as exc:
                if _is_tavily_quota_error(exc):
                    tavily_metadata = _get_or_record_tavily_limit_metadata(exc)
                    _mark_tavily_quota_unavailable()
                    query_attempts = getattr(exc, "query_attempts", None) or task.get("query_attempts") or []
                    field_attempts = getattr(exc, "field_attempts", None) or []
                    if field_attempts:
                        query_attempts = list(query_attempts)
                        for field_attempt in field_attempts:
                            if field_attempt not in query_attempts:
                                query_attempts.append(field_attempt)
                    task_record, websearch_item = _build_tavily_fast_switch_records(
                        task,
                        attempt_index=attempt_idx,
                        elapsed_ms=0,
                        error=exc,
                        query_attempts=query_attempts,
                        tavily_metadata=tavily_metadata,
                    )
                    if field_attempts:
                        _attach_field_attempts(task_record, websearch_item, field_attempts)
                    failures.append(task_record)
                    manual_required_keys.append(task_record["indicator_key"])
                    _append_task_log(task_log_path, task_record)
                    websearch_results.append(websearch_item)
                elif attempt_idx <= queue_retry_limit:
                    stats["queue_requeued"] += 1
                    await queue.put((task, snippets, attempt_idx + 1))  # type: ignore
                else:
                    stats["queue_dead_letters"] += 1
                    task_record = {
                        "task_id": task["task_id"],
                        "indicator_key": task["indicator_key"],
                        "stage_phase": task["stage_phase"],
                        "search_backend": task["search_backend"],
                        "fund_flow_backend": task.get("fund_flow_backend"),
                        "manual_required": True,
                        "note": f"queue_error:{exc}",
                        "attempt_index": attempt_idx,
                        "elapsed_ms": None,
                        "created_at": task["created_at"],
                        "finished_at": int(datetime.now().timestamp()),
                    }
                    failures.append(task_record)
                    _append_task_log(task_log_path, task_record)
            finally:
                queue.task_done()  # type: ignore

    consumers: List[asyncio.Task] = []
    if use_queue:
        consumers = [asyncio.create_task(consumer()) for _ in range(max(1, queue_concurrency))]

    for task in tasks:
        is_fund_flow = task["indicator_key"] in {"northbound", "southbound", "etf", "margin"}
        is_forex = task["indicator_key"] in forex_keys
        requested_backend = str(task.get("fund_flow_backend") or fund_flow_backend or "tavily").lower()
        backend = "tavily"
        if is_fund_flow and requested_backend != "tavily":
            logger.warning(
                f"[Stage2] 不再支持 fund_flow_backend={requested_backend}，已自动改为 tavily: {task.get('indicator_key')}"
            )
        try:
            # 若已存在非占位有效值，直接跳过搜索
            has_value, existing_val = _has_non_placeholder_value(market_payload, task["indicator_key"])
            if has_value and not _is_force_refresh_task(task):
                now_ts = int(datetime.now().timestamp())
                task_record = {
                    "task_id": task["task_id"],
                    "indicator_key": task["indicator_key"],
                    "stage_phase": task["stage_phase"],
                    "search_backend": task["search_backend"],
                    "fund_flow_backend": backend if is_fund_flow else None,
                    "extraction_backend": extraction_backend,
                    "manual_required": False,
                    "note": "skip_existing_value",
                    "attempt_index": 0,
                    "elapsed_ms": 0,
                    "created_at": task.get("created_at", now_ts),
                    "finished_at": now_ts,
                    "confidence": 1.0,
                    "source_url": None,
                    "llm_latency_ms": 0,
                    "llm_error": None,
                    "deepseek_error": None,
                    "result_type": "skipped_existing",
                }
                _update_missing_items(market_payload, task["indicator_key"])
                _append_task_log(task_log_path, task_record)
                completed.append(task_record)
                websearch_results.append(
                    {
                        "task": task,
                        "extraction": {
                            "value": existing_val,
                            "unit": task.get("unit"),
                            "note": "existing_value",
                            "confidence": 1.0,
                            "source_url": None,
                        },
                        "extraction_backend": extraction_backend,
                        "raw_results": [],
                        "manual_required": False,
                        "result_type": "skipped_existing",
                    }
                )
                continue
            structured_records = await _try_structured_provider(
                structured_registry=structured_registry,
                task=task,
                market_payload=market_payload,
                task_log_path=task_log_path,
                stats=stats,
            )
            if structured_records is not None:
                task_record, websearch_item = structured_records
                completed.append(task_record)
                websearch_results.append(websearch_item)
                continue
            if tavily_unavailable_reason == "quota_or_rate_limit" and active_search_backend != "exa":
                if _activate_exa_failover(task, "quota_or_rate_limit"):
                    pass
                else:
                    task_record, websearch_item = _build_tavily_fast_switch_records(
                        task,
                        attempt_index=0,
                        elapsed_ms=0,
                        tavily_metadata=active_tavily_limit_metadata,
                    )
                    failures.append(task_record)
                    manual_required_keys.append(task_record["indicator_key"])
                    _append_task_log(task_log_path, task_record)
                    websearch_results.append(websearch_item)
                    continue
            if tavily_unavailable_reason == "environment_proxy_error":
                exc = RuntimeError(stats.get("environment_proxy_error") or "environment_proxy_error")
                task_record, websearch_item = _build_environment_proxy_error_records(
                    task,
                    exc,
                    extraction_backend=extraction_backend,
                )
                failures.append(task_record)
                manual_required_keys.append(task_record["indicator_key"])
                _append_task_log(task_log_path, task_record)
                websearch_results.append(websearch_item)
                continue
            directed_retry_done = False
            directed_query_override: Optional[str] = None
            for attempt in count(start=1):
                started = time.perf_counter()
                skip_deepseek_reason: Optional[str] = None
                extract_skipped_reason: Optional[str] = None
                query_used: Optional[str] = None
                query_attempts: List[Dict[str, Any]] = []
                search_backend = active_search_backend
                search_note: Optional[str] = None
                task_for_log = task
                result: Dict[str, Any] = {}
                exa_best_payload: Optional[Dict[str, Any]] = None
                try:
                    try:
                        if active_search_backend == "exa":
                            search_candidates = _expand_query_candidates(
                                task,
                                directed_query_override=directed_query_override,
                            )
                            best_payload, query_attempts, exa_note, exa_metadata = await _run_exa_search_candidates(
                                task,
                                search_candidates,
                                failover_reason or "quota_or_rate_limit",
                            )
                            if best_payload:
                                result = best_payload["result"]
                                query_used = best_payload["candidate"].get("query")
                                snippets = best_payload.get("snippets") or []
                                score_stats = best_payload.get("score_stats") or _score_stats(snippets)
                                task_for_log = dict(
                                    best_payload.get("task_for_log") or task
                                )
                                task_for_log["query_attempts"] = query_attempts
                                search_backend = "exa"
                                search_note = best_payload.get("note") or exa_note
                                task_for_log.update(
                                    {
                                        "search_backend": "exa",
                                        "search_backend_state": "exa_active",
                                        "failover_reason": failover_reason,
                                    }
                                )
                                task_for_log.update(active_tavily_limit_metadata)
                            else:
                                elapsed_ms = int((time.perf_counter() - started) * 1000)
                                task_record, websearch_item = _build_exa_failover_manual_records(
                                    task,
                                    reason=exa_note,
                                    attempt_index=attempt,
                                    elapsed_ms=elapsed_ms,
                                    query_attempts=query_attempts,
                                    exa_metadata=exa_metadata,
                                    tavily_metadata=active_tavily_limit_metadata,
                                )
                                _append_task_log(task_log_path, task_record)
                                failures.append(task_record)
                                manual_required_keys.append(task_record["indicator_key"])
                                websearch_results.append(websearch_item)
                                break
                        else:
                            search_candidates = _expand_query_candidates(
                                task,
                                directed_query_override=directed_query_override,
                            )
                            best_payload, query_attempts, last_exc = await _run_search_candidates(task, search_candidates)
                            if best_payload:
                                result = best_payload["result"]
                                snippets = best_payload["snippets"]
                                score_stats = best_payload["score_stats"]
                                query_used = best_payload["candidate"].get("query")
                                task_for_log = {
                                    **task,
                                    "query_used": query_used,
                                    "query_family_used": best_payload["candidate"].get("family"),
                                    "field_scope": best_payload["candidate"].get("field_scope"),
                                    "query_attempts": query_attempts,
                                    "score_stats": score_stats,
                                    "usable_count_before_extract": best_payload.get("usable_count", 0),
                                    "trusted_count": best_payload.get("trusted_count", 0),
                                    "issuer_hit": best_payload.get("issuer_hit", False),
                                    "period_hit": best_payload.get("period_hit", False),
                                    "selected_reason": best_payload.get("selected_reason"),
                                    "usage_evidence_score": best_payload.get("usage_evidence_score", 0),
                                    "value_evidence_score": best_payload.get("value_evidence_score", 0),
                                    "good_url_hit_count": best_payload.get("good_url_hit_count", 0),
                                    "bad_url_hit_count": best_payload.get("bad_url_hit_count", 0),
                                    "unusable_reason": best_payload.get("unusable_reason"),
                                }
                            else:
                                snippets = []
                                score_stats = _score_stats(snippets)
                                if last_exc:
                                    raise last_exc
                    except Exception as exc:
                        is_proxy_error = _is_environment_proxy_error(exc)
                        is_quota_error = False if is_proxy_error else _is_tavily_quota_error(exc)
                        tavily_metadata = _record_tavily_limit_error(exc) if is_quota_error else {}
                        exa_metadata: Dict[str, Any] = {}
                        if is_proxy_error:
                            _mark_environment_proxy_unavailable(exc)
                            exa_result, exa_note = None, None
                        elif is_quota_error and _activate_exa_failover(task, "quota_or_rate_limit"):
                            _mark_tavily_quota_unavailable()
                            search_candidates = _expand_query_candidates(
                                task,
                            )
                            exa_best_payload, exa_attempts, exa_note, exa_metadata = await _run_exa_search_candidates(
                                task,
                                search_candidates,
                                "quota_or_rate_limit",
                            )
                            query_attempts.extend(exa_attempts)
                            exa_result = exa_best_payload["result"] if exa_best_payload else None
                        elif is_quota_error:
                            _mark_tavily_quota_unavailable()
                            exa_result, exa_note = None, None
                        else:
                            exa_result, exa_note = await _try_exa_fallback(
                                task, f"tavily_error:{exc}", query_override=task.get("query")
                            )
                        if exa_result:
                            result = exa_result
                            if exa_best_payload:
                                query_used = exa_best_payload["candidate"].get("query")
                                snippets = exa_best_payload.get("snippets") or []
                                score_stats = exa_best_payload.get("score_stats") or _score_stats(snippets)
                                task_for_log = dict(exa_best_payload.get("task_for_log") or task)
                            else:
                                query_used = result.get("query") or task.get("query")
                                snippets, score_stats, task_for_log = _apply_exa_quality_to_task(
                                    task,
                                    result,
                                    query_used,
                                    exa_note,
                                )
                            search_backend = "exa"
                            search_note = exa_best_payload.get("note") if exa_best_payload else exa_note
                            task_for_log["query_attempts"] = query_attempts
                            task_for_log.update(
                                {
                                    "search_backend": "exa",
                                    "search_backend_state": "exa_active",
                                    "failover_reason": failover_reason,
                                }
                            )
                            task_for_log.update(active_tavily_limit_metadata)
                        else:
                            elapsed_ms = int((time.perf_counter() - started) * 1000)
                            logger.warning(
                                f"Tavily/DeepSeek 执行失败 {task['indicator_key']} attempt={attempt}: {exc}"
                            )
                            if is_proxy_error:
                                task_record, websearch_item = _build_environment_proxy_error_records(
                                    task,
                                    exc,
                                    attempt_index=attempt,
                                    elapsed_ms=elapsed_ms,
                                    extraction_backend=extraction_backend,
                                    query_attempts=query_attempts,
                                )
                                _append_task_log(task_log_path, task_record)
                                failures.append(task_record)
                                manual_required_keys.append(task_record["indicator_key"])
                                websearch_results.append(websearch_item)
                                break
                            if is_quota_error:
                                if exa_note in {"exa_error", "exa_empty", "exa_unavailable"}:
                                    task_record, websearch_item = _build_exa_failover_manual_records(
                                        task,
                                        reason=exa_note,
                                        attempt_index=attempt,
                                        elapsed_ms=elapsed_ms,
                                        error=exc,
                                        query_attempts=query_attempts,
                                        exa_metadata=exa_metadata,
                                        tavily_metadata=tavily_metadata,
                                    )
                                else:
                                    task_record, websearch_item = _build_tavily_fast_switch_records(
                                        task,
                                        attempt_index=attempt,
                                        elapsed_ms=elapsed_ms,
                                        error=exc,
                                        query_attempts=query_attempts,
                                        tavily_metadata=tavily_metadata,
                                    )
                                _append_task_log(task_log_path, task_record)
                                failures.append(task_record)
                                manual_required_keys.append(task_record["indicator_key"])
                                websearch_results.append(websearch_item)
                                break
                            if attempt >= max_retries + 1:
                                note = str(exc)
                                if exa_note:
                                    note = f"{note} {exa_note}"
                                task_record = {
                                    "task_id": task["task_id"],
                                    "indicator_key": task["indicator_key"],
                                    "stage_phase": task["stage_phase"],
                                    "search_backend": task["search_backend"],
                                    "fund_flow_backend": backend if is_fund_flow else None,
                                    "error": str(exc),
                                    "llm_error": str(exc),
                                    "llm_latency_ms": None,
                                    "attempt_index": attempt,
                                    "elapsed_ms": elapsed_ms,
                                    "manual_required": True,
                                    "note": note,
                                    "created_at": task["created_at"],
                                    "finished_at": int(datetime.now().timestamp()),
                                }
                                task_record.update(_structured_audit_fields_from_task(task))
                                _append_task_log(task_log_path, task_record)
                                failures.append(task_record)
                                break
                            continue

                    score_stats = _score_stats(snippets)
                    if not snippets:
                        if search_backend == "tavily":
                            exa_result, exa_note = await _try_exa_fallback(task, "no_snippets")
                            if exa_result:
                                result = exa_result
                                query_used = result.get("query") or query_used or task.get("query")
                                snippets, score_stats, task_for_log = _apply_exa_quality_to_task(
                                    task,
                                    result,
                                    query_used,
                                    exa_note,
                                )
                                search_backend = "exa"
                                search_note = exa_note
                        if not snippets:
                            skip_deepseek_reason = (
                                task_for_log.get("unusable_reason")
                                or search_note
                                or "no_snippets"
                            )
                            if skip_deepseek_reason == "value_evidence_miss":
                                stats["value_evidence_drop_count"] += 1
                        score_stats = _score_stats(snippets)
                    score_low_all = False
                    effective_low_score = task.get("low_score_threshold")
                    if effective_low_score is None:
                        effective_low_score = low_score_threshold
                    allow_low_score_extract = bool(task.get("allow_low_score_extract"))
                    if (
                        skip_deepseek_reason is None
                        and score_stats.get("score_count")
                        and effective_low_score is not None
                        and effective_low_score > 0
                    ):
                        score_max = score_stats.get("score_max")
                        if isinstance(score_max, (int, float)) and score_max < effective_low_score:
                            score_low_all = True
                            if allow_low_score_extract:
                                stats["low_score_allow"] += 1
                            else:
                                skip_deepseek_reason = "low_score_all"
                                stats["low_score_drop"] += 1
                    # Tavily extract (two-step) for noisy tasks
                    extract_policy = task.get("extract_policy") or {}
                    use_tavily_extract = extract_policy.get("use_tavily_extract")
                    if use_tavily_extract is None:
                        use_tavily_extract = is_fund_flow or is_forex or task["indicator_key"] in {
                            "GC=F",
                            "CL=F",
                            "BZ=F",
                            "HG=F",
                            "BCOM",
                            "GSG",
                        }
                    local_extract_topk = int(extract_policy.get("extract_topk") or extract_topk)
                    try:
                        if (
                            search_backend == "tavily"
                            and not extract_globally_disabled
                            and use_tavily_extract
                        ):
                            if extract_422_cooldown_sec > 0:
                                cooldown_until = extract_disabled_until.get(task["indicator_key"])
                                if cooldown_until and time.time() < cooldown_until:
                                    extract_skipped_reason = "extract_cooldown"
                            if extract_skipped_reason is None:
                                extract_candidates = snippets
                                official_domains = _official_extract_domains(extract_policy)
                                if official_domains:
                                    extract_candidates = _filter_by_official_extract_domain(
                                        snippets,
                                        official_domains,
                                    )
                                    if not extract_candidates:
                                        extract_skipped_reason = "official_domain_filter_empty"
                                        if snippets:
                                            skip_deepseek_reason = "official_domain_filter_empty"
                                top_for_extract = (
                                    extract_candidates[: max(1, local_extract_topk)]
                                    if extract_skipped_reason is None
                                    else []
                                )
                                if top_for_extract:
                                    stats["tavily_extract_calls"] += 1
                                    extract_resp = await client.extract(
                                        search_results=top_for_extract,
                                        extract_depth="advanced" if is_fund_flow or is_forex else "standard",
                                        include_raw_content=is_fund_flow,
                                        cache_ttl=cache_ttl,
                                    )
                                    extract_resp = extract_resp or {}
                                    if _is_tavily_quota_response(extract_resp):
                                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                                        tavily_metadata = _record_tavily_limit_error(extract_resp)
                                        if _activate_exa_failover(task_for_log, "quota_or_rate_limit"):
                                            _mark_tavily_quota_unavailable()
                                            search_candidates = _expand_query_candidates(task_for_log)
                                            exa_best_payload, exa_attempts, exa_note, exa_metadata = (
                                                await _run_exa_search_candidates(
                                                    task_for_log,
                                                    search_candidates,
                                                    "quota_or_rate_limit",
                                                )
                                            )
                                            query_attempts.extend(exa_attempts)
                                            if exa_best_payload:
                                                result = exa_best_payload["result"]
                                                query_used = exa_best_payload["candidate"].get("query")
                                                snippets = exa_best_payload.get("snippets") or []
                                                score_stats = exa_best_payload.get("score_stats") or _score_stats(
                                                    snippets
                                                )
                                                task_for_log = dict(exa_best_payload.get("task_for_log") or task_for_log)
                                                task_for_log.update(tavily_metadata)
                                                task_for_log["query_attempts"] = query_attempts
                                                search_backend = "exa"
                                                search_note = exa_best_payload.get("note") or exa_note
                                                if not snippets:
                                                    skip_deepseek_reason = (
                                                        task_for_log.get("unusable_reason")
                                                        or exa_note
                                                        or "no_snippets"
                                                    )
                                            else:
                                                task_record, websearch_item = _build_exa_failover_manual_records(
                                                    task_for_log,
                                                    reason=exa_note,
                                                    attempt_index=attempt,
                                                    elapsed_ms=elapsed_ms,
                                                    query_attempts=query_attempts,
                                                    exa_metadata=exa_metadata,
                                                    tavily_metadata=tavily_metadata,
                                                )
                                                _append_task_log(task_log_path, task_record)
                                                failures.append(task_record)
                                                manual_required_keys.append(task_record["indicator_key"])
                                                websearch_results.append(websearch_item)
                                                break
                                        else:
                                            _mark_tavily_quota_unavailable()
                                            task_record, websearch_item = _build_tavily_fast_switch_records(
                                                task_for_log,
                                                attempt_index=attempt,
                                                elapsed_ms=elapsed_ms,
                                                query_attempts=query_attempts,
                                                tavily_metadata=tavily_metadata,
                                            )
                                            _append_task_log(task_log_path, task_record)
                                            failures.append(task_record)
                                            manual_required_keys.append(task_record["indicator_key"])
                                            websearch_results.append(websearch_item)
                                            break
                                    elif extract_resp.get("status") == 422 or "422" in str(extract_resp.get("error", "")):
                                        stats["tavily_extract_422_count"] += 1
                                        logger.debug("Tavily extract 422, 降级到 DeepSeek 直接从 snippets 抽取")
                                        stats.setdefault("extract_fallback_to_deepseek", 0)
                                        stats["extract_fallback_to_deepseek"] += 1
                                        exa_result, exa_note = await _try_exa_fallback(
                                            task_for_log,
                                            "extract_422",
                                            query_override=query_used or task.get("query"),
                                        )
                                        if exa_result:
                                            result = exa_result
                                            query_used = result.get("query") or query_used or task.get("query")
                                            snippets, score_stats, task_for_log = _apply_exa_quality_to_task(
                                                task_for_log,
                                                result,
                                                query_used,
                                                exa_note,
                                            )
                                            search_backend = "exa"
                                            search_note = exa_note
                                            if not snippets:
                                                skip_deepseek_reason = (
                                                    task_for_log.get("unusable_reason")
                                                    or exa_note
                                                    or "no_snippets"
                                                )
                                        # Exa 命中过滤后才替换 snippets；被质量门禁拒绝则跳过 DeepSeek。
                                        await asyncio.sleep(0.5)
                                        if auto_disable_extract_on_422:
                                            now_ts = time.time()
                                            tracker = extract_422_tracker.get(task["indicator_key"])
                                            if (
                                                not tracker
                                                or now_ts - tracker.get("window_start", 0) > extract_422_cooldown_sec
                                            ):
                                                tracker = {"count": 0, "window_start": now_ts}
                                            tracker["count"] = tracker.get("count", 0) + 1
                                            extract_422_tracker[task["indicator_key"]] = tracker
                                            if tracker["count"] >= max(1, extract_422_threshold):
                                                if extract_422_cooldown_sec > 0:
                                                    extract_disabled_until[task["indicator_key"]] = (
                                                        now_ts + extract_422_cooldown_sec
                                                    )
                                                stats["extract_auto_disabled"] = True
                                                stats["extract_cooldown_count"] += 1
                                                logger.warning(
                                                    "[Stage2] Tavily extract 422 达到阈值(%d)，已按指标冷却；"
                                                    "%s 冷却 %ss",
                                                    extract_422_threshold,
                                                        task["indicator_key"],
                                                        extract_422_cooldown_sec,
                                                )
                                    else:
                                        extra_res = extract_resp.get("results") or []
                                        # 将 extract 的内容附加为额外 snippet，供后续抽取/regex 使用
                                        for ex in extra_res:
                                            content = ex.get("content") or ex.get("raw_content")
                                            if content:
                                                snippets.append(
                                                    {
                                                        "content": content,
                                                        "snippet": ex.get("snippet") or "",
                                                        "url": ex.get("url") or ex.get("source_url"),
                                                        "score": ex.get("score"),
                                                    }
                                                )
                    except Exception as exc:  # pragma: no cover
                        if _is_environment_proxy_error(exc):
                            _mark_environment_proxy_unavailable(exc)
                            elapsed_ms = int((time.perf_counter() - started) * 1000)
                            task_record, websearch_item = _build_environment_proxy_error_records(
                                task_for_log,
                                exc,
                                attempt_index=attempt,
                                elapsed_ms=elapsed_ms,
                                extraction_backend=extraction_backend,
                                query_attempts=query_attempts,
                            )
                            _append_task_log(task_log_path, task_record)
                            failures.append(task_record)
                            manual_required_keys.append(task_record["indicator_key"])
                            websearch_results.append(websearch_item)
                            break
                        if _is_tavily_quota_error(exc):
                            tavily_metadata = _record_tavily_limit_error(exc)
                            elapsed_ms = int((time.perf_counter() - started) * 1000)
                            if _activate_exa_failover(task_for_log, "quota_or_rate_limit"):
                                _mark_tavily_quota_unavailable()
                                search_candidates = _expand_query_candidates(task_for_log)
                                exa_best_payload, exa_attempts, exa_note, exa_metadata = (
                                    await _run_exa_search_candidates(
                                        task_for_log,
                                        search_candidates,
                                        "quota_or_rate_limit",
                                    )
                                )
                                query_attempts.extend(exa_attempts)
                                exa_result = exa_best_payload["result"] if exa_best_payload else None
                                if exa_result:
                                    result = exa_result
                                    query_used = exa_best_payload["candidate"].get("query")
                                    snippets = exa_best_payload.get("snippets") or []
                                    score_stats = exa_best_payload.get("score_stats") or _score_stats(snippets)
                                    task_for_log = dict(exa_best_payload.get("task_for_log") or task_for_log)
                                    search_backend = "exa"
                                    search_note = exa_best_payload.get("note") or exa_note
                                    task_for_log["query_attempts"] = query_attempts
                                    task_for_log.update(
                                        {
                                            "search_backend": "exa",
                                            "search_backend_state": "exa_active",
                                            "failover_reason": failover_reason,
                                        }
                                    )
                                    task_for_log.update(active_tavily_limit_metadata)
                                    if not snippets:
                                        skip_deepseek_reason = (
                                            task_for_log.get("unusable_reason")
                                            or exa_note
                                            or "no_snippets"
                                        )
                                else:
                                    task_record, websearch_item = _build_exa_failover_manual_records(
                                        task_for_log,
                                        reason=exa_note,
                                        attempt_index=attempt,
                                        elapsed_ms=elapsed_ms,
                                        error=exc,
                                        query_attempts=query_attempts,
                                        exa_metadata=exa_metadata,
                                        tavily_metadata=tavily_metadata,
                                    )
                                    _append_task_log(task_log_path, task_record)
                                    failures.append(task_record)
                                    manual_required_keys.append(task_record["indicator_key"])
                                    websearch_results.append(websearch_item)
                                    break
                            else:
                                _mark_tavily_quota_unavailable()
                                task_record, websearch_item = _build_tavily_fast_switch_records(
                                    task_for_log,
                                    attempt_index=attempt,
                                    elapsed_ms=elapsed_ms,
                                    error=exc,
                                    query_attempts=query_attempts,
                                    tavily_metadata=tavily_metadata,
                                )
                                _append_task_log(task_log_path, task_record)
                                failures.append(task_record)
                                manual_required_keys.append(task_record["indicator_key"])
                                websearch_results.append(websearch_item)
                                break
                        logger.debug(f"Tavily extract skipped/failed: {exc}")
                    if (
                        search_backend == "tavily"
                        and extract_skipped_reason == "extract_cooldown"
                    ):
                        exa_result, exa_note = await _try_exa_fallback(
                            task_for_log,
                            "extract_cooldown",
                            query_override=query_used or task.get("query"),
                        )
                        if exa_result:
                            result = exa_result
                            query_used = result.get("query") or query_used or task.get("query")
                            snippets, score_stats, task_for_log = _apply_exa_quality_to_task(
                                task_for_log,
                                result,
                                query_used,
                                exa_note,
                            )
                            search_backend = "exa"
                            search_note = exa_note
                            extract_skipped_reason = "extract_cooldown_exa_fallback"
                            if not snippets:
                                skip_deepseek_reason = (
                                    task_for_log.get("unusable_reason")
                                    or exa_note
                                    or "no_snippets"
                                )
                    if search_backend == "tavily" and extract_globally_disabled and extract_skipped_reason is None:
                        extract_skipped_reason = "extract_globally_disabled"
                    # score 过滤
                    before_score = len(snippets)
                    high_score = [s for s in snippets if s.get("score") is None or s.get("score", 0) >= 0.5]
                    if high_score:
                        requires_value_evidence = bool(
                            task_for_log.get("required_output_fields") or task_for_log.get("evidence_keywords")
                        )
                        high_score_diagnostics = _final_snippet_diagnostics(task_for_log, high_score)
                        current_diagnostics = _final_snippet_diagnostics(task_for_log, snippets)
                        high_score_value = int(high_score_diagnostics["value_evidence_score"])
                        current_value = int(current_diagnostics["value_evidence_score"])
                        if not requires_value_evidence or high_score_value >= current_value or current_value <= 0:
                            snippets = high_score
                            stats["score_filtered_drop"] += max(0, before_score - len(snippets))
                    score_filtered_drop_local = max(0, before_score - len(snippets)) if high_score else 0
                    before = len(snippets)
                    snippets = _filter_by_domain(
                        snippets,
                        task.get("preferred_domains"),
                        indicator_key=task.get("indicator_key"),
                    )
                    after = len(snippets)
                    if before and before != after:
                        stats["domain_filtered_drop"] += before - after
                    domain_filtered_drop_local = max(0, before - after) if before and before != after else 0
                    snippets = _prefer_fresh_snippets(snippets, task.get("max_age_days"))
                    snippets = _prefer_latest_report_snippets(snippets, task.get("indicator_key"))
                    final_diagnostics = _final_snippet_diagnostics(task_for_log, snippets)
                    score_stats = final_diagnostics["score_stats"]
                    selected_reason = _selected_reason_from_diagnostics(
                        final_diagnostics,
                        task_for_log.get("unusable_reason"),
                    )
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    request_id_for_log = (
                        result.get("response_id")
                        or result.get("request_id")
                        or task_for_log.get("request_id")
                        or task_for_log.get("exa_request_id")
                    )
                    tavily_diagnostics = {
                        key: task_for_log[key]
                        for key in ("tavily_http_status", "tavily_request_id", "tavily_error_message")
                        if key in task_for_log
                    }
                    task_for_log = {
                        **task,
                        **tavily_diagnostics,
                        "search_backend": search_backend,
                        "search_backend_state": task_for_log.get("search_backend_state"),
                        "failover_reason": task_for_log.get("failover_reason"),
                        "request_id": request_id_for_log,
                        "exa_request_id": request_id_for_log if search_backend == "exa" else task_for_log.get("exa_request_id"),
                        "query_used": query_used,
                        "query_family_used": task_for_log.get("query_family_used"),
                        "field_scope": task_for_log.get("field_scope"),
                        "query_attempts": query_attempts,
                        "score_stats": score_stats,
                        "score_low_all": score_low_all,
                        "score_low_threshold": effective_low_score,
                        "usable_count_before_extract": task_for_log.get("usable_count_before_extract", len(snippets)),
                        "trusted_count": final_diagnostics["trusted_count"],
                        "issuer_hit": final_diagnostics["issuer_hit"],
                        "period_hit": final_diagnostics["period_hit"],
                        "selected_reason": selected_reason,
                        "usage_evidence_score": final_diagnostics["usage_evidence_score"],
                        "value_evidence_score": final_diagnostics["value_evidence_score"],
                        "good_url_hit_count": final_diagnostics["good_url_hit_count"],
                        "bad_url_hit_count": final_diagnostics["bad_url_hit_count"],
                        "score_filtered_drop": score_filtered_drop_local,
                        "domain_filtered_drop": domain_filtered_drop_local,
                        "extraction_skipped_reason": skip_deepseek_reason,
                        "extract_skipped_reason": extract_skipped_reason,
                    }
                    if search_note:
                        task_for_log["search_note"] = search_note
                    if skip_deepseek_reason is None:
                        skip_deepseek_reason = _deepseek_circuit_breaker_skip_reason()
                        if skip_deepseek_reason:
                            task_for_log["extraction_skipped_reason"] = skip_deepseek_reason
                    if use_queue:
                        if skip_deepseek_reason:
                            extraction = {
                                "value": None,
                                "unit": task.get("unit"),
                                "note": f"skipped_deepseek:{skip_deepseek_reason}",
                                "source_url": None,
                                "confidence": 0.0,
                                "llm_error": f"skipped_deepseek:{skip_deepseek_reason}",
                                "llm_timeout": False,
                                "llm_latency_ms": 0,
                                "manual_required": True,
                                "manual_reason": f"skipped_deepseek:{skip_deepseek_reason}",
                            }
                            task_record = {
                                "task_id": task["task_id"],
                                "indicator_key": task["indicator_key"],
                                "stage_phase": task["stage_phase"],
                                "search_backend": task_for_log.get("search_backend"),
                                "fund_flow_backend": backend if is_fund_flow else None,
                                "extraction_backend": extraction_backend,
                                "confidence": extraction.get("confidence", 0.0),
                                "source_url": extraction.get("source_url"),
                                "note": extraction.get("note"),
                                "llm_latency_ms": extraction.get("llm_latency_ms"),
                                "llm_error": extraction.get("llm_error"),
                                "deepseek_error": extraction.get("note")
                                if isinstance(extraction.get("note"), str)
                                and extraction["note"]
                                and extraction["note"].startswith("deepseek_error")
                                else None,
                                "request_id": (
                                    result.get("response_id")
                                    or result.get("request_id")
                                    or task_for_log.get("request_id")
                                    or task_for_log.get("exa_request_id")
                                ),
                                "http_status": result.get("status") if search_backend == "tavily" else None,
                                "cache_hit": result.get("cache_hit", False),
                                "attempt_index": attempt,
                                "elapsed_ms": elapsed_ms,
                                "created_at": task["created_at"],
                                "finished_at": int(datetime.now().timestamp()),
                                "manual_required": True,
                                "manual_reason": extraction.get("manual_reason"),
                                "extraction_skipped_reason": skip_deepseek_reason,
                                "extract_skipped_reason": extract_skipped_reason,
                                "query_used": task_for_log.get("query_used"),
                                "query_family_used": task_for_log.get("query_family_used"),
                                "field_scope": task_for_log.get("field_scope"),
                                "usable_count_before_extract": task_for_log.get("usable_count_before_extract"),
                                "trusted_count": task_for_log.get("trusted_count"),
                                "issuer_hit": task_for_log.get("issuer_hit"),
                                "period_hit": task_for_log.get("period_hit"),
                                "selected_reason": task_for_log.get("selected_reason"),
                                "usage_evidence_score": task_for_log.get("usage_evidence_score"),
                                "value_evidence_score": task_for_log.get("value_evidence_score"),
                                "good_url_hit_count": task_for_log.get("good_url_hit_count"),
                                "bad_url_hit_count": task_for_log.get("bad_url_hit_count"),
                                "score_min": score_stats.get("score_min"),
                                "score_p50": score_stats.get("score_p50"),
                                "score_p95": score_stats.get("score_p95"),
                                "score_max": score_stats.get("score_max"),
                                "score_count": score_stats.get("score_count"),
                                "score_low_threshold": low_score_threshold,
                                "score_low_all": score_low_all,
                                "score_filtered_drop": task_for_log.get("score_filtered_drop"),
                                "domain_filtered_drop": task_for_log.get("domain_filtered_drop"),
                            }
                            task_record.update(_structured_audit_fields_from_task(task_for_log))
                            failures.append(task_record)
                            manual_required_keys.append(task_record["indicator_key"])
                            _append_task_log(task_log_path, task_record)
                            websearch_results.append(
                                {
                                    "task": task_for_log,
                                    "extraction": extraction,
                                    "extraction_backend": extraction_backend,
                                    "raw_results": snippets[:3],
                                    "search_backend": task_for_log.get("search_backend"),
                                    "note": task_for_log.get("search_note"),
                                    "manual_required": True,
                                    "manual_reason": extraction.get("manual_reason"),
                                }
                            )
                            break
                        await queue.put((task_for_log, snippets, attempt))  # type: ignore
                        break
                    else:
                        # 当 Tavily 无结果 / extract 422 / search 异常时，跳过 DeepSeek，直接 regex/人工
                        if skip_deepseek_reason:
                            extraction = {
                                "value": None,
                                "unit": task.get("unit"),
                                "note": f"skipped_deepseek:{skip_deepseek_reason}",
                                "source_url": None,
                                "confidence": 0.0,
                                "llm_error": f"skipped_deepseek:{skip_deepseek_reason}",
                                "llm_timeout": False,
                                "llm_latency_ms": 0,
                                "manual_required": True,
                                "manual_reason": f"skipped_deepseek:{skip_deepseek_reason}",
                            }
                        else:
                            stats["extract_calls"] += 1
                            extraction = await _do_extract(snippets, task)
                            if skip_deepseek_reason is None and extraction.get("extraction_skipped_reason"):
                                skip_deepseek_reason = str(extraction.get("extraction_skipped_reason"))
                                task_for_log["extraction_skipped_reason"] = skip_deepseek_reason
                        # regex 兜底：关键指标无值时尝试直接提取数字（低相关时跳过）
                        if extraction.get("value") is None and skip_deepseek_reason not in {
                            "low_score_all",
                            "official_domain_filter_empty",
                        }:
                            regex_val = _regex_fallback(snippets, task["indicator_key"])
                            if regex_val is not None:
                                extraction["value"] = regex_val
                                extraction.setdefault("note", "regex_fallback")
                                stats["regex_hits"] += 1
                        _augment_extraction_metadata(extraction, task, snippets)
                        _refine_extraction_value(extraction, task, snippets)
                        field_attempts: List[Dict[str, Any]] = []
                        if is_fund_flow:
                            extraction, field_attempts = await _retry_fund_flow_fields(
                                task_for_log,
                                extraction,
                                search_backend,
                            )
                            field_failover_manual = extraction.pop("_field_retry_failover_manual", None)
                            if isinstance(field_failover_manual, dict):
                                elapsed_ms = int((time.perf_counter() - started) * 1000)
                                task_record, websearch_item = _build_exa_failover_manual_records(
                                    task_for_log,
                                    reason=str(field_failover_manual.get("reason") or "exa_empty"),
                                    attempt_index=attempt,
                                    elapsed_ms=elapsed_ms,
                                    query_attempts=field_attempts or field_failover_manual.get("query_attempts"),
                                    exa_metadata=field_failover_manual.get("exa_metadata") or {},
                                    tavily_metadata=field_failover_manual.get("tavily_metadata") or {},
                                )
                                _attach_field_attempts(
                                    task_record,
                                    websearch_item,
                                    field_attempts or field_failover_manual.get("field_attempts") or [],
                                )
                                _append_task_log(task_log_path, task_record)
                                failures.append(task_record)
                                manual_required_keys.append(task_record["indicator_key"])
                                websearch_results.append(websearch_item)
                                break
                            task_for_log = _promote_task_to_exa_after_field_retry(
                                task_for_log,
                                field_attempts,
                            )
                            search_backend = task_for_log.get("search_backend") or search_backend
                        # 对资金流再尝试基于片段推断方向，补充 note，减少 manual_required
                        if is_fund_flow and extraction.get("value") is not None:
                            inferred_dir = _infer_flow_direction(snippets)
                            if inferred_dir:
                                dir_cn = "流出" if inferred_dir == "outflow" else "流入"
                                extraction["note"] = (
                                    (extraction.get("note") or "") + f" regex_dir:{inferred_dir} {dir_cn}"
                                ).strip()
                                if inferred_dir == "outflow" and extraction["value"] > 0:
                                    extraction["value"] = -abs(extraction["value"])
                                if inferred_dir == "inflow" and extraction["value"] < 0:
                                    extraction["value"] = abs(extraction["value"])
                        # 先继承模型层 manual 标记
                        manual_required = bool(extraction.get("manual_required"))
                        if extraction.get("manual_reason"):
                            extraction["note"] = _append_note(
                                extraction.get("note"),
                                str(extraction.get("manual_reason")),
                            )

                        # fund_flow 低置信度或无值 → manual_required
                        if is_fund_flow and (extraction.get("confidence", 0.0) < 0.5 or extraction.get("value") is None):
                            manual_required = True
                        validate_note_append = ""
                        if is_fund_flow:
                            adjusted_value, unit_manual, note_append = _validate_fund_flow_extraction(
                                extraction, indicator_key=task["indicator_key"]
                            )
                            extraction["value"] = adjusted_value
                            combined_note = " ".join(
                                s for s in [extraction.get("note", ""), note_append] if s
                            ).strip()
                            extraction["note"] = combined_note or None
                            if unit_manual and _safe_number(extraction.get("recent_5d")) is not None and _safe_number(
                                extraction.get("total_120d")
                            ) is not None:
                                metric_basis = _default_fund_flow_metric_basis(task["indicator_key"], extraction)
                                window_evidence = _infer_fund_flow_window_evidence(
                                    task["indicator_key"], extraction, metric_basis
                                )
                                if window_evidence not in {"direct_window", "direct_daily_series", "direct_balance_delta"}:
                                    extraction["manual_reason"] = _append_note(
                                        extraction.get("manual_reason"),
                                        "fund_flow_window_missing",
                                    )
                            manual_required = manual_required or unit_manual
                            validate_note_append = note_append or ""
                        else:
                            # 对非资金流向的校验
                            val_adj, manual2, note_append2 = _validate_general_extraction(extraction, task, snippets)
                            extraction["value"] = val_adj
                            if note_append2:
                                extraction["note"] = ((extraction.get("note") or "") + " " + note_append2).strip()
                            manual_required = manual_required or manual2
                            validate_note_append = note_append2 or ""
                        if search_note and search_backend == "exa":
                            extraction["note"] = ((extraction.get("note") or "") + f" {search_note}").strip()
                        if skip_deepseek_reason == "low_score_all":
                            manual_required = True

                        if manual_required and _should_retry_with_directed_query(
                            extraction,
                            skip_reason=skip_deepseek_reason,
                            extra_reason=validate_note_append,
                            attempt=attempt,
                            max_retries=max_retries,
                            directed_retry_done=directed_retry_done,
                        ):
                            directed_query = _build_directed_query(
                                task,
                                extraction,
                                skip_reason=skip_deepseek_reason,
                                extra_reason=validate_note_append,
                            )
                            if directed_query:
                                directed_query_override = directed_query
                                directed_retry_done = True
                                continue

                        tavily_diagnostics = _tavily_diagnostics_from_task(task_for_log, field_attempts)
                        task_record = {
                            **tavily_diagnostics,
                            "task_id": task["task_id"],
                            "indicator_key": task["indicator_key"],
                            "stage_phase": task["stage_phase"],
                            "search_backend": search_backend,
                            "fund_flow_backend": backend if is_fund_flow else None,
                            "extraction_backend": extraction_backend,
                            "confidence": extraction.get("confidence", 0.0),
                            "source_url": extraction.get("source_url"),
                            "note": extraction.get("note"),
                            "llm_latency_ms": extraction.get("llm_latency_ms"),
                            "llm_error": extraction.get("llm_error"),
                            "llm_timeout": extraction.get("llm_timeout"),
                            "deepseek_error": extraction.get("note")
                            if isinstance(extraction.get("note"), str)
                            and extraction["note"].startswith("deepseek_error")
                            else None,
                            "request_id": (
                                result.get("response_id")
                                or result.get("request_id")
                                or task_for_log.get("request_id")
                                or task_for_log.get("exa_request_id")
                            ),
                            "http_status": result.get("status") if search_backend == "tavily" else None,
                            "cache_hit": result.get("cache_hit", False),
                            "attempt_index": attempt,
                            "elapsed_ms": elapsed_ms,
                            "created_at": task["created_at"],
                            "finished_at": int(datetime.now().timestamp()),
                            "manual_required": manual_required,
                            "manual_reason": extraction.get("manual_reason"),
                            "extraction_skipped_reason": skip_deepseek_reason,
                            "extract_skipped_reason": extract_skipped_reason,
                            "query_used": task_for_log.get("query_used"),
                            "query_family_used": task_for_log.get("query_family_used"),
                            "field_scope": task_for_log.get("field_scope"),
                            "usable_count_before_extract": task_for_log.get("usable_count_before_extract"),
                            "trusted_count": task_for_log.get("trusted_count"),
                            "issuer_hit": task_for_log.get("issuer_hit"),
                            "period_hit": task_for_log.get("period_hit"),
                            "selected_reason": task_for_log.get("selected_reason"),
                            "usage_evidence_score": task_for_log.get("usage_evidence_score"),
                            "value_evidence_score": task_for_log.get("value_evidence_score"),
                            "good_url_hit_count": task_for_log.get("good_url_hit_count"),
                            "bad_url_hit_count": task_for_log.get("bad_url_hit_count"),
                            "score_min": score_stats.get("score_min"),
                            "score_p50": score_stats.get("score_p50"),
                            "score_p95": score_stats.get("score_p95"),
                            "score_max": score_stats.get("score_max"),
                            "score_count": score_stats.get("score_count"),
                            "score_low_threshold": low_score_threshold,
                            "score_low_all": score_low_all,
                            "score_filtered_drop": task_for_log.get("score_filtered_drop"),
                            "domain_filtered_drop": task_for_log.get("domain_filtered_drop"),
                        }
                        task_record.update(_structured_audit_fields_from_task(task_for_log))
                        if manual_required:
                            failures.append(task_record)
                            if extraction.get("value") is None:
                                manual_required_keys.append(task_record["indicator_key"])
                        else:
                            write_target = _apply_extraction(market_payload, task_for_log, extraction, snippets=snippets)
                            write_stats = stats.setdefault("write_back_by_category", {})
                            if isinstance(write_stats, dict):
                                write_stats[write_target] = write_stats.get(write_target, 0) + 1
                            if write_target == "fallback_macro":
                                stats["write_back_fallback_count"] += 1
                            elif write_target == "skip_no_value":
                                stats["write_back_miss_count"] += 1
                            post_writeback_reason = _post_writeback_manual_reason(market_payload, task["indicator_key"])
                            if post_writeback_reason:
                                _mark_post_writeback_manual_required(
                                    market_payload,
                                    task_record,
                                    extraction,
                                    task["indicator_key"],
                                    post_writeback_reason,
                                )
                                failures.append(task_record)
                                manual_required_keys.append(task_record["indicator_key"])
                                manual_required = True
                            else:
                                _update_missing_items(market_payload, task["indicator_key"])
                                completed.append(task_record)
                        _append_task_log(task_log_path, task_record)
                        websearch_results.append(
                            {
                                "task": task_for_log,
                                "extraction": extraction,
                                "extraction_backend": extraction_backend,
                                "raw_results": snippets[:3],  # 仅保留前3条片段便于审计
                                "field_attempts": field_attempts,
                                "search_backend": search_backend,
                                "note": search_note,
                                "manual_required": task_record.get("manual_required"),
                                "manual_reason": task_record.get("manual_reason") or extraction.get("manual_reason"),
                            }
                        )
                        break
                except Exception as exc:  # pragma: no cover - 网络错误兜底
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    logger.warning(f"Tavily/DeepSeek 执行失败 {task['indicator_key']} attempt={attempt}: {exc}")
                    if _is_environment_proxy_error(exc):
                        _mark_environment_proxy_unavailable(exc)
                        task_record, websearch_item = _build_environment_proxy_error_records(
                            task,
                            exc,
                            attempt_index=attempt,
                            elapsed_ms=elapsed_ms,
                            extraction_backend=extraction_backend,
                        )
                        _append_task_log(task_log_path, task_record)
                        failures.append(task_record)
                        manual_required_keys.append(task_record["indicator_key"])
                        websearch_results.append(websearch_item)
                        break
                    if _is_tavily_quota_error(exc):
                        tavily_metadata = _get_or_record_tavily_limit_metadata(exc)
                        _mark_tavily_quota_unavailable()
                        task_record, websearch_item = _build_tavily_fast_switch_records(
                            task,
                            attempt_index=attempt,
                            elapsed_ms=elapsed_ms,
                            error=exc,
                            tavily_metadata=tavily_metadata,
                        )
                        _append_task_log(task_log_path, task_record)
                        failures.append(task_record)
                        manual_required_keys.append(task_record["indicator_key"])
                        websearch_results.append(websearch_item)
                        break
                    if attempt >= max_retries + 1:
                        task_record = {
                            "task_id": task["task_id"],
                            "indicator_key": task["indicator_key"],
                            "stage_phase": task["stage_phase"],
                            "search_backend": task["search_backend"],
                            "fund_flow_backend": backend if is_fund_flow else None,
                            "error": str(exc),
                            "llm_error": str(exc),
                            "llm_latency_ms": None,
                            "attempt_index": attempt,
                            "elapsed_ms": elapsed_ms,
                            "manual_required": True,
                            "created_at": task["created_at"],
                            "finished_at": int(datetime.now().timestamp()),
                        }
                        task_record.update(_structured_audit_fields_from_task(task))
                        _append_task_log(task_log_path, task_record)
                        failures.append(task_record)
                        break
                    # retry loop continues
        except Exception as outer_exc:  # pragma: no cover
            logger.error(f"[FATAL] 执行任务 {task['indicator_key']} 失败: {outer_exc}")
    if use_queue:
        await queue.join()  # type: ignore
        for c in consumers:
            c.cancel()
        await asyncio.gather(*consumers, return_exceptions=True)
    force_refresh_by_task = {
        str(t.get("task_id")): _is_force_refresh_task(t)
        for t in tasks
        if t.get("task_id")
    }
    for record in completed:
        task_id = str(record.get("task_id") or "")
        record["force_refresh"] = force_refresh_by_task.get(task_id, False)
        record.setdefault("result_type", _finalize_task_result_type(record))
    for record in failures:
        task_id = str(record.get("task_id") or "")
        record["force_refresh"] = force_refresh_by_task.get(task_id, False)
        if (
            record.get("manual_required")
            and record.get("force_refresh")
            and not _is_tavily_fast_switch_record(record)
        ):
            record["note"] = _append_note(record.get("note"), "stale_refresh_failed")
            record["manual_reason"] = _append_note(record.get("manual_reason"), "stale_refresh_failed")
        record.setdefault("result_type", _finalize_task_result_type(record))
    for item in websearch_results:
        task = item.get("task") or {}
        force_refresh = force_refresh_by_task.get(str(task.get("task_id") or ""), False)
        item["force_refresh"] = force_refresh
        extraction = item.get("extraction") or {}
        if (
            item.get("manual_required")
            and force_refresh
            and not _is_tavily_fast_switch_websearch(item)
        ):
            _mark_stale_refresh_failure(extraction, task)
            item["manual_reason"] = extraction.get("manual_reason")
        item.setdefault("result_type", _finalize_websearch_result_type(item))
    return completed, failures, websearch_results


def _gap_monitor(
    pending: List[str],
    output_path: Path,
    manual_required: Optional[List[str]] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    def _dedupe_keep_order(values: List[str]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for v in values:
            if not v or v in seen:
                continue
            seen.add(v)
            ordered.append(v)
        return ordered

    clean_pending = _dedupe_keep_order([p for p in pending if p])
    clean_manual = _dedupe_keep_order([m for m in manual_required or [] if m])
    payload = {
        "generated_at": datetime.now().isoformat(),
    }
    if clean_pending:
        payload["pending_tasks"] = clean_pending
    if clean_manual:
        payload["manual_required"] = clean_manual
    _dump_json(payload, output_path)


_FUND_FLOW_BOUNDS: Dict[str, Dict[str, Tuple[float, float]]] = {
    "northbound": {
        "recent_5d": (-500.0, 500.0),
        "total_120d": (-8000.0, 8000.0),
    },
    "southbound": {
        "recent_5d": (-500.0, 500.0),
        "total_120d": (-8000.0, 8000.0),
    },
    "etf": {
        "recent_5d": (-3000.0, 3000.0),
        "total_120d": (-30000.0, 30000.0),
    },
    "margin": {
        "recent_5d": (-8000.0, 8000.0),
        "total_120d": (-50000.0, 50000.0),
    },
}


def _detect_fund_flow_suspicious_reason(
    key: str,
    recent: Optional[float],
    total: Optional[float],
) -> Optional[str]:
    if recent is None or total is None:
        return None
    if key in {"northbound", "southbound"} and abs(recent - total) < 1e-9:
        if abs(recent - 100.0) < 1e-9:
            return "疑似占位值(100/100)"
        if abs(recent) <= 150.0:
            return "近5日与120日完全相等且偏小"

    bounds = _FUND_FLOW_BOUNDS.get(key, {})
    recent_bound = bounds.get("recent_5d")
    if recent_bound and not (recent_bound[0] <= recent <= recent_bound[1]):
        return f"recent_5d超出经验区间({recent_bound[0]}~{recent_bound[1]})"
    total_bound = bounds.get("total_120d")
    if total_bound and not (total_bound[0] <= total <= total_bound[1]):
        return f"total_120d超出经验区间({total_bound[0]}~{total_bound[1]})"
    return None


def _flag_fund_flow_anomalies(market_payload: Dict[str, Any]) -> List[str]:
    """标记资金流向的零值/空值/可疑占位值"""
    flagged: List[str] = []
    fund_flow = market_payload.get("fund_flow", {})
    for key, item in fund_flow.items():
        if not isinstance(item, dict):
            continue
        recent = _safe_number(item.get("recent_5d"))
        total = _safe_number(item.get("total_120d"))
        suspicious_reason = _detect_fund_flow_suspicious_reason(key, recent, total)
        if (recent is None or abs(recent) < 1e-9) or (total is None or abs(total) < 1e-9) or suspicious_reason:
            item["source"] = "异常零值-需核查"
            note = (item.get("note") or "").strip()
            anomaly_note = "异常零值-需核查"
            if suspicious_reason:
                anomaly_note = f"{anomaly_note} {suspicious_reason}"
            if anomaly_note not in note:
                note = (note + f" {anomaly_note}").strip()
            item["note"] = note
            item["manual_required"] = True
            flagged.append(key)
        else:
            # 兼容历史旧标注，统一归一到当前 Tavily 口径
            source_text = str(item.get("source") or "").lower()
            if "mcp" in source_text:
                item["source"] = "tavily+deepseek"
                note = (item.get("note") or "").strip()
                compat_note = "legacy_source_normalized:mcp->tavily"
                if compat_note not in note:
                    item["note"] = (note + f" {compat_note}").strip()
    return flagged


def _validate_fund_flow_extraction(
    extraction: Dict[str, Any], indicator_key: Optional[str] = None
) -> (Optional[float], bool, str):
    """确保资金流数值有“亿”单位，并基于关键词确定正负；返回 (value, manual_required, note_append)"""
    val = extraction.get("value")
    note_append = ""
    manual = False
    if val is None:
        return None, True, "no_value"
    try:
        val = float(val)
    except Exception:
        return None, True, "parse_error"
    # 单位校验
    unit = extraction.get("unit") or ""
    unit_lower = str(unit).lower()
    if "亿" not in unit and "bn" not in unit_lower and "billion" not in unit_lower:
        manual = True
        note_append = (note_append + " 单位缺失(需含亿)").strip()
    # 方向校验：根据 note / raw snippet 关键词推断
    text_blob = f"{extraction.get('note') or ''} {extraction.get('trend') or ''}".lower()
    direction_unknown = True
    if "流出" in text_blob or "net outflow" in text_blob:
        if val > 0:
            val = -val
        direction_unknown = False
    elif "流入" in text_blob or "net inflow" in text_blob or "买入" in text_blob:
        if val < 0:
            val = abs(val)
        direction_unknown = False
    elif "卖出" in text_blob:
        if val > 0:
            val = -val
        direction_unknown = False

    if abs(val) < 1e-9:
        manual = True
        note_append = (note_append + " 值为0需复核").strip()
    if direction_unknown:
        manual = True
        note_append = (note_append + " 未能识别流入/流出方向").strip()
    key = str(indicator_key or "").lower()
    if key in {"northbound", "southbound"}:
        if abs(val - 100.0) < 1e-9:
            manual = True
            note_append = (note_append + " 疑似占位值(100)").strip()
    bounds = _FUND_FLOW_BOUNDS.get(key)
    if bounds and "recent_5d" in bounds:
        low, high = bounds["recent_5d"]
        if not (low <= val <= high):
            manual = True
            note_append = (note_append + f" 超出经验区间({low}~{high})").strip()

    return val, manual, note_append


def _validate_general_extraction(
    extraction: Dict[str, Any], task: Dict[str, Any], snippets: Optional[List[Dict[str, Any]]] = None
) -> (Optional[float], bool, str):
    """
    对宏观/利率/商品等结果做基本校验：
    - unit_hint 存在但 extraction.unit 缺失或不包含 -> manual_required
    - preferred_domains 存在且 source_url 域名不在其中 -> manual_required
    - issuer_hint 提供但片段/抽取结果不包含发布机构 -> manual_required
    """
    val = extraction.get("value")
    unit_hint = task.get("unit")
    domains = task.get("preferred_domains") or []
    issuer_hint = task.get("issuer")
    issuer_aliases = task.get("issuer_aliases") or []
    indicator_key = task.get("indicator_key")
    indicator_key_l = str(indicator_key or "").lower()
    manual = False
    note_append = ""
    note_flag = extraction.get("note") or ""
    snippets_text = " ".join(
        [
            str(s.get("content", "")) or str(s.get("snippet", "")) or ""
            for s in (snippets or [])
        ]
    ).lower()

    if val is None:
        manual = True
        note_append = (note_append + " no_value").strip()

    # unit 校验使用与官方来源信任一致的 canonical unit 规则。
    if unit_hint:
        unit_val = extraction.get("unit") or ""
        if not units_compatible(unit_hint, unit_val):
            manual = True
            note_append = (note_append + f" 单位不匹配(需含{unit_hint})").strip()

    # 域名校验
    src = extraction.get("source_url")
    src_netloc = ""
    if src:
        try:
            src_netloc = urlparse(src).netloc
        except Exception:
            src_netloc = ""
    if domains and src:
        try:
            netloc = src_netloc or urlparse(src).netloc
            if not any(netloc.endswith(d) for d in domains):
                manual = True
                note_append = (note_append + " 域名不在白名单").strip()
            # regex_only 时 URL 过于泛（如首页）时标记人工
            strict_regex_keys = {"USDCNY", "USDCNH", "DXY", "bdi"}
            if (
                indicator_key in strict_regex_keys
                and isinstance(note_flag, str)
                and note_flag.startswith("regex")
                and urlparse(src).path in {"", "/"}
            ):
                manual = True
                note_append = (note_append + " regex_only来源过泛").strip()
        except Exception:
            manual = True
            note_append = (note_append + " source_url解析失败").strip()

    # 发布机构校验：若提供 issuer_hint，需要在抽取或片段中出现
    if issuer_hint:
        issuer_relax_domains = {
            "rrr": ["tradingeconomics.com", "ceicdata.com", "chinamoney.com.cn"],
            "mlf": ["tradingeconomics.com", "chinamoney.com.cn"],
            "reverse_repo": ["tradingeconomics.com", "chinamoney.com.cn", "cls.cn"],
            "bcom": ["tradingeconomics.com", "investing.com", "bloomberg.com"],
            "cn10y": ["tradingeconomics.com", "ceicdata.com", "macromicro.me", "investing.com"],
            "cn10y_cdb": ["chinamoney.com.cn", "cfets.com.cn", "eastmoney.com", "tradingeconomics.com", "ceicdata.com"],
            "bdi": ["balticexchange.com", "tradingeconomics.com", "investing.com"],
        }
        issuer_relaxed = False
        if indicator_key_l in issuer_relax_domains and src_netloc:
            issuer_relaxed = any(
                src_netloc.endswith(d) for d in issuer_relax_domains[indicator_key_l]
            )
        issuer_match_flag = extraction.get("issuer_match")
        alias_hit = any(alias.lower() in snippets_text for alias in issuer_aliases)
        if (
            not issuer_relaxed
            and not issuer_match_flag
            and issuer_hint.lower() not in snippets_text
            and not alias_hit
        ):
            # 若已有有效数值但缺发行人，则仅提示不强制人工；无值则仍需人工
            if val is None:
                manual = True
            note_append = (note_append + f" 缺少发布机构({issuer_hint})").strip()
        elif issuer_relaxed:
            note_append = (note_append + " 发布机构校验放宽").strip()
        # regex_only/regex_fallback 情况下，对关键指标要求发布机构命中
        strict_issuer_keys = {
            "usdcny",
            "usdcnh",
            "dxy",
            "bdi",
            "rrr",
            "mlf",
            "reverse_repo",
        }
        if (
            indicator_key_l in strict_issuer_keys
            and isinstance(note_flag, str)
            and note_flag.startswith("regex")
            and not issuer_match_flag
            and issuer_hint.lower() not in snippets_text
            and not alias_hit
            and not issuer_relaxed
        ):
            if val is None:
                manual = True
            note_append = (note_append + f" regex_only缺少发布机构({issuer_hint})").strip()

    # regex_only 时要求命中指标关键词，避免抓取无关数字
    if isinstance(note_flag, str) and note_flag.startswith("regex") and indicator_key:
        keyword_rules = {
            "USDCNY": [
                "usdcny",
                "usd/cny",
                "usd cny",
                "us dollar",
                "chinese yuan",
                "cny",
                "renminbi",
                "美元",
                "人民币",
                "在岸",
                "中间价",
            ],
            "USDCNH": [
                "usdcnh",
                "usd/cnh",
                "usd cnh",
                "offshore",
                "cnh",
                "renminbi",
                "离岸人民币",
            ],
            "DXY": ["dxy", "美元指数", "dollar index", "us dollar index", "ice dollar index"],
            "bdi": ["bdi", "波罗的海", "baltic"],
            "industrial": ["工业增加值", "规模以上工业增加值", "industrial output"],
            "industrial_sales": ["工业企业", "营业收入", "营收", "industrial enterprise"],
            "rrr": ["存款准备金率", "rrr", "降准", "reserve requirement"],
            "mlf": ["mlf", "中期借贷便利", "medium-term lending facility"],
            "reverse_repo": ["逆回购", "repo", "reverse repo", "7-day"],
            "US10Y": ["10年", "10-year", "us10y", "treasury"],
            "CN10Y": ["10年", "10-year", "10 year", "10y", "国债", "government bond", "china 10y"],
            "CN10Y_CDB": ["国开", "开发债", "政策性金融债", "中债估值", "cdb"],
        }
        keywords = keyword_rules.get(indicator_key)
        if keywords and not any(k.lower() in snippets_text for k in keywords):
            manual = True
            note_append = (note_append + " regex_only缺少指标关键词").strip()

    # 时效性校验：若所有可解析日期均超过设定阈值，则标记人工复核
    max_age = task.get("max_age_days")
    if max_age and _is_stale(snippets, max_age):
        manual = True
        note_append = (note_append + f" 数据超过{max_age}天需更新").strip()

    # 合理区间校验：对易被新闻数字干扰的指标做基本范围限制
    if indicator_key in _RANGE_RULES:
        numeric_val = _safe_number(val)
        if numeric_val is not None:
            low, high = _RANGE_RULES[indicator_key]
            if numeric_val < low or numeric_val > high:
                manual = True
                note_append = (note_append + f" 数值超出合理区间({low}-{high})").strip()
        elif val is not None:
            manual = True
            note_append = (note_append + " 数值不可解析").strip()

    # 工业增加值口径保护：仅累计同比时不作为 current_value 使用
    if indicator_key == "industrial" and extraction.get("value_type") == "yoy_ytd":
        manual = True
        note_append = (note_append + " 仅累计同比需补当月同比").strip()

    return val, manual, note_append


def _env_int_default(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in {None, ""}:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _env_float_default(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in {None, ""}:
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 2 Unified Enhancer (Tavily + DeepSeek)")
    parser.add_argument("--market-data", required=True, help="Stage1 生成的 market_data.json 路径")
    parser.add_argument("--output", help="增强后输出路径；默认覆盖输入")
    parser.add_argument("--phase", choices=["essential", "assets", "all"], default="all")
    parser.add_argument("--search-backend", choices=["tavily"], default="tavily")
    parser.add_argument("--fund-flow-backend", choices=["tavily"], default="tavily")
    parser.add_argument("--task-file", default=None, help="输出任务文件路径（默认: data/runs/YYYYMMDD/search_tasks_stage2.jsonl）")
    parser.add_argument("--task-log", default=None, help="逐任务执行日志路径（默认: logs/runs/YYYYMMDD/stage_task_log.jsonl）")
    parser.add_argument("--websearch-results", default=None, help="搜索抽取结果保存路径（默认: data/runs/YYYYMMDD/websearch_results_auto.json）")
    parser.add_argument("--cache-ttl", type=int, default=3600)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--cache-backend", choices=["memory", "sqlite"], default="memory")
    parser.add_argument("--cache-path", default="data/cache/tavily_cache.sqlite")
    parser.add_argument("--http-proxy", help="HTTP proxy, overrides env")
    parser.add_argument("--https-proxy", help="HTTPS proxy, overrides env")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--deepseek-timeout", type=float, default=30.0, help="DeepSeek抽取超时时间(秒)")
    parser.add_argument("--deepseek-max-concurrency", type=int, default=3, help="DeepSeek并发上限")
    parser.add_argument(
        "--deepseek-breaker-consecutive-timeouts",
        type=int,
        default=_env_int_default("DEEPSEEK_BREAKER_CONSECUTIVE_TIMEOUTS", 6),
        help="DeepSeek circuit breaker 连续超时阈值；<=0 禁用连续超时触发",
    )
    parser.add_argument(
        "--deepseek-breaker-timeout-rate",
        type=float,
        default=_env_float_default("DEEPSEEK_BREAKER_TIMEOUT_RATE", 0.6),
        help="DeepSeek circuit breaker 超时率阈值；<=0 禁用超时率触发",
    )
    parser.add_argument(
        "--deepseek-breaker-min-attempts",
        type=int,
        default=_env_int_default("DEEPSEEK_BREAKER_MIN_ATTEMPTS", 8),
        help="DeepSeek circuit breaker 超时率触发的最小尝试数；<=0 禁用超时率触发",
    )
    parser.add_argument("--deepseek-model", default="deepseek-v4-pro", help="DeepSeek模型名")
    parser.add_argument(
        "--deepseek-base-url",
        default=os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
        help="DeepSeek API Base URL",
    )
    parser.add_argument(
        "--deepseek-serial-keys",
        help="逗号分隔的 indicator_key 列表，这些任务串行等待 DeepSeek（无并发），适用于关键指标",
    )
    parser.add_argument(
        "--extraction-backend",
        choices=["deepseek", "regex", "langchain"],
        default="deepseek",
        help="抽取后端：deepseek 优先，或强制 regex 兜底",
    )
    parser.add_argument(
        "--allow-langchain",
        action="store_true",
        help="显式启用 langchain 抽取（默认禁用）；缺依赖或未开启则直接退出",
    )
    parser.add_argument(
        "--lc-max-concurrency", type=int, default=3, help="LangChain 抽取并发上限（仅在 extraction-backend=langchain 时生效）"
    )
    parser.add_argument(
        "--lc-timeout", type=float, default=8.0, help="LangChain 抽取超时(秒)，用于 DeepSeek 调用（langchain模式）"
    )
    parser.add_argument("--langsmith", action="store_true", help="启用 LangSmith 追踪（默认关闭）")
    parser.add_argument("--resume-from-task-file", help="使用已有任务文件，跳过重新扫描 Stage1")
    parser.add_argument("--tasks", help="仅执行指定任务（task_id 或 indicator_key，逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="仅生成任务文件，不执行搜索")
    parser.add_argument("--execute-search", action="store_true", help="立即执行 Tavily+DeepSeek 任务")
    parser.add_argument(
        "--disable-structured-providers",
        action="store_true",
        help="禁用 Stage2 structured provider-first，直接走 Tavily/Exa/DeepSeek 链路",
    )
    parser.add_argument(
        "--enable-exa-fallback",
        action="store_true",
        help="显式启用 Exa 作为 Tavily 后备；默认关闭以保持 Tavily-first 执行边界",
    )
    parser.add_argument("--log-output", default=None, help="Stage2 运行日志路径（默认: logs/runs/YYYYMMDD/stage2_unified_log.json）")
    parser.add_argument("--gap-monitor", default=None, help="gap_monitor 输出路径（默认: data/runs/YYYYMMDD/gap_monitor.json）")
    parser.add_argument(
        "--use-queue",
        dest="use_queue",
        action="store_true",
        default=True,
        help="开启 extraction 阶段 asyncio.Queue 消费模式（默认开启）",
    )
    parser.add_argument(
        "--no-use-queue",
        dest="use_queue",
        action="store_false",
        help="关闭 extraction 阶段 asyncio.Queue 消费模式，按任务串行抽取",
    )
    parser.add_argument("--queue-concurrency", type=int, default=3, help="Queue 消费者并发数")
    parser.add_argument("--queue-maxsize", type=int, default=100, help="Queue 最大容量")
    parser.add_argument("--queue-retry-limit", type=int, default=2, help="Queue 抽取重试次数（超时/网络错误）")
    parser.add_argument(
        "--disable-extract", action="store_true", help="跳过 Tavily extract 二阶段，直接使用 search 结果"
    )
    parser.add_argument(
        "--auto-disable-extract-on-422",
        action="store_true",
        help="Tavily extract 多次返回 422 时自动关闭 extract，后续任务仅 search+regex",
    )
    parser.add_argument(
        "--extract-422-threshold",
        type=int,
        default=1,
        help="触发自动停用 extract 的 Tavily 422 次数阈值（默认1）",
    )
    parser.add_argument(
        "--extract-422-cooldown-sec",
        type=int,
        default=300,
        help="Tavily extract 422 冷却窗口（秒），按指标短窗降级",
    )
    parser.add_argument(
        "--low-score-threshold",
        type=float,
        default=0.2,
        help="Tavily 搜索结果全部低于该分数时跳过抽取并标记人工",
    )
    parser.add_argument(
        "--extract-topk", type=int, default=3, help="Tavily extract 使用的搜索结果条数（默认3）"
    )
    parser.add_argument(
        "--llm-hard-timeout", type=float, default=35.0, help="对单次 LLM 抽取的 asyncio 硬超时（秒），0 表示不设硬超时"
    )
    parser.add_argument(
        "--fast-mode",
        action="store_true",
        help="极速模式：regex 抽取、并发放大、短超时、队列不重试，并禁用 extract 以加速",
    )
    return parser.parse_args()


def _should_enable_exa_fallback(args: argparse.Namespace) -> bool:
    env_value = str(os.getenv("STAGE2_ENABLE_EXA_FALLBACK") or "").strip().lower()
    return bool(getattr(args, "enable_exa_fallback", False)) or env_value in {"1", "true", "yes", "on"}


def _should_initialize_exa_client(args: argparse.Namespace) -> bool:
    return bool(os.getenv("EXA_API_KEY")) or _should_enable_exa_fallback(args)


def _build_structured_registry_for_args(args: argparse.Namespace) -> Any:
    if getattr(args, "disable_structured_providers", False):
        return None
    if build_default_registry is None:
        return None
    try:
        return build_default_registry()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] structured provider registry init failed, fallback to search: {exc}")
        return None


def _is_exa_sdk_available() -> bool:
    return bool(
        AsyncExaClient
        and callable(getattr(AsyncExaClient, "sdk_available", None))
        and AsyncExaClient.sdk_available()  # type: ignore[union-attr]
    )


def _load_tasks_from_file(path: Path) -> List[Dict[str, Any]]:
    tasks = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                tasks.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return tasks


def _ensure_keys(require_tavily: bool = True, require_deepseek: bool = True) -> List[str]:
    """
    校验必需的密钥，缺失时返回列表。
    默认 Tavily/DeepSeek 都需检查；可按调用场景放宽。
    """
    missing: List[str] = []
    if load_dotenv:
        load_dotenv()
    if require_tavily and not os.getenv("TAVILY_API_KEY"):
        missing.append("TAVILY_API_KEY")
    if require_deepseek and not os.getenv("DEEPSEEK_API_KEY"):
        missing.append("DEEPSEEK_API_KEY")
    return missing


def _callable_supports_kwarg(callable_obj: Any, kwarg: str) -> bool:
    try:
        params = inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):
        return False
    if kwarg in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def _select_proxy_for_url(proxies: Dict[str, str], url: str) -> Optional[str]:
    scheme = urlparse(url).scheme.lower()
    for key in (f"{scheme}://", scheme):
        proxy_url = proxies.get(key)
        if proxy_url:
            return proxy_url

    proxy_values = [proxy_url for proxy_url in proxies.values() if proxy_url]
    if len(proxy_values) == 1:
        return proxy_values[0]
    if proxy_values:
        return proxy_values[0]
    return None


def _validate_proxies(proxies: Dict[str, str]) -> Optional[Dict[str, str]]:
    """快速探测代理可用性；不可用则返回 None 并给出提示。"""
    if not proxies:
        return None
    if httpx is None:
        logger.warning("[Stage2] httpx 未安装，无法验证代理可用性，继续按配置使用。")
        return proxies
    test_url = "https://api.tavily.com"
    get_kwargs: Dict[str, Any] = {"timeout": 3}
    if _callable_supports_kwarg(httpx.get, "proxies"):
        get_kwargs["proxies"] = proxies
    elif _callable_supports_kwarg(httpx.get, "proxy"):
        proxy_url = _select_proxy_for_url(proxies, test_url)
        if not proxy_url:
            logger.warning("[Stage2] 代理配置为空，已自动禁用。")
            return None
        get_kwargs["proxy"] = proxy_url
    else:
        logger.warning("[Stage2] 当前 httpx.get 不支持显式代理验证，跳过代理探测并按配置使用。")
        return proxies
    try:
        resp = httpx.get(test_url, **get_kwargs)
        if resp.status_code < 500:
            logger.info(f"[Stage2] 代理可用，继续使用: {proxies}")
            return proxies
    except Exception as exc:
        logger.warning(f"[Stage2] 代理不可用，已自动禁用：{exc}")
    return None


def _parse_task_filter(arg: Optional[str]) -> (List[str], List[str]):
    if not arg:
        return [], []
    parts = [p.strip() for p in arg.split(",") if p.strip()]
    task_ids, indicators = [], []
    for p in parts:
        if len(p) >= 30 and "-" in p:
            task_ids.append(p)
        else:
            indicators.append(p)
    return task_ids, indicators


async def main() -> int:
    args = _parse_args()
    # Apply policy_rules defaults (if present)
    try:
        policy_rules = load_policy_rules()
        if not args.auto_disable_extract_on_422:
            args.auto_disable_extract_on_422 = True
        if policy_rules.get("extract_422_threshold"):
            args.extract_422_threshold = int(policy_rules.get("extract_422_threshold"))
        if policy_rules.get("extract_422_cooldown_sec") is not None:
            args.extract_422_cooldown_sec = int(policy_rules.get("extract_422_cooldown_sec"))
        if policy_rules.get("low_score_threshold") is not None:
            args.low_score_threshold = float(policy_rules.get("low_score_threshold"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] policy_rules load failed: {exc}")
    if args.extraction_backend == "langchain" and not args.allow_langchain:
        print(
            "[ERROR] langchain 模式已默认禁用。如需使用，请添加 --allow-langchain（需安装依赖）或改用 deepseek/regex。",
            file=sys.stderr,
        )
        return 1
    market_path = Path(args.market_data)
    output_path = Path(args.output) if args.output else market_path

    # Fast mode: 优先速度，牺牲部分准确度
    if args.fast_mode:
        logger.info("[Stage2] Fast mode enabled: regex extraction, higher queue concurrency, shorter timeouts.")
        args.extraction_backend = "regex"
        args.queue_concurrency = max(args.queue_concurrency, 6)
        args.queue_retry_limit = 0
        args.deepseek_max_concurrency = 0
        args.deepseek_timeout = 8.0 if args.deepseek_timeout is None else min(args.deepseek_timeout, 8.0)
        args.llm_hard_timeout = 8.0 if args.llm_hard_timeout is None or args.llm_hard_timeout == 0 else min(
            args.llm_hard_timeout, 8.0
        )
        args.disable_extract = True

    market_payload = _load_json(market_path)
    run_paths = build_run_paths_from_reference(
        payload=market_payload,
        path=market_path,
        fallback_to_today=True,
    )
    task_file = Path(args.task_file) if args.task_file else run_paths.search_tasks_stage2
    task_log_path = Path(args.task_log) if args.task_log else run_paths.stage2_task_log
    websearch_results_path = Path(args.websearch_results) if args.websearch_results else run_paths.websearch_results_auto
    log_output = Path(args.log_output) if args.log_output else run_paths.stage2_log
    gap_monitor_path = Path(args.gap_monitor) if args.gap_monitor else run_paths.gap_monitor
    _apply_aliases(market_payload, {"industrial_output": "industrial"})
    if isinstance(market_payload.get("monetary_policy"), dict):
        market_payload["monetary_policy"] = normalize_monetary_section(market_payload.get("monetary_policy"))
    _merge_missing_items(market_payload)

    # 先校验密钥并加载 .env，避免在初始化 TavilyClient 时 api_key 为空
    require_tavily = True  # 当前 search_backend 固定 tavily
    require_deepseek = args.extraction_backend not in {"regex"}  # regex 模式无需 DeepSeek key
    missing_keys = _ensure_keys(require_tavily=require_tavily, require_deepseek=require_deepseek)
    if missing_keys and args.execute_search:
        print(f"[ERROR] 缺少密钥: {', '.join(missing_keys)}。请先执行 `source .env` 或设置环境变量后重试。")
        return 1

    planner = Stage2TaskPlanner(
        stage_phase=args.phase,
        search_backend=args.search_backend,
        task_file=task_file,
        fund_flow_backend=args.fund_flow_backend,
    )
    # 若提供 resume 文件优先加载，否则重建任务（并确保去重逻辑一致）
    if args.resume_from_task_file:
        task_file = Path(args.resume_from_task_file)
        tasks = _load_tasks_from_file(task_file)
        logger.info(f"[Stage2] 使用已有任务文件 {task_file}")
    else:
        tasks = planner.build_tasks(market_payload)
        planner.write_jsonl(tasks)

    task_ids_filter, indicators_filter = _parse_task_filter(args.tasks)
    if task_ids_filter or indicators_filter:
        tasks = _filter_tasks(tasks, task_ids_filter, indicators_filter)
        logger.info(f"[Stage2] 过滤后剩余 {len(tasks)} 条任务")
    # 兼容历史 task_file：统一修正 fund_flow_backend 为 tavily
    normalized_legacy_backend = 0
    for task in tasks:
        b = str(task.get("fund_flow_backend") or "").lower()
        if b and b != "tavily":
            task["fund_flow_backend"] = "tavily"
            normalized_legacy_backend += 1
    if normalized_legacy_backend:
        logger.warning(f"[Stage2] 已将 {normalized_legacy_backend} 条历史任务的 fund_flow_backend 统一为 tavily")
    _warn_disable_extract_on_critical_tasks(tasks, args.disable_extract)
    if not tasks:
        logger.info("[Stage2] 无待执行任务，提前退出。")
        _dump_json([], websearch_results_path)
        return 0

    completeness_warnings = _check_task_completeness(tasks)
    for w in completeness_warnings:
        logger.warning(f"[Stage2] 任务信息不完整: {w}")

    cache = None
    if not args.no_cache:
        if args.cache_backend == "sqlite":
            cache = SQLiteCache(Path(args.cache_path), default_ttl=args.cache_ttl)
            cache.purge_expired()
        else:
            cache = MemoryCache(default_ttl=args.cache_ttl)
    proxies = {}
    if args.http_proxy:
        proxies["http://"] = args.http_proxy
    if args.https_proxy:
        proxies["https://"] = args.https_proxy
    proxies = _validate_proxies(proxies)
    tavily = AsyncTavilyClient(
        api_key=os.getenv("TAVILY_API_KEY"),
        cache=cache,
        timeout=args.read_timeout,
        connect_timeout=args.connect_timeout,
        max_concurrency=4,
        proxies=proxies or None,
        trust_env=(
            os.getenv("DATASOURCE_NETWORK_MODE", "direct").lower() == "proxy"
        ),
    )
    exa_client = None
    exa_api_key = os.getenv("EXA_API_KEY")
    exa_sdk_available = _is_exa_sdk_available()
    if _should_initialize_exa_client(args) and exa_api_key and exa_sdk_available:
        exa_client = AsyncExaClient(
            api_key=exa_api_key,
            cache=cache,
            max_concurrency=2,
        )
        if _should_enable_exa_fallback(args):
            logger.info("[Stage2] Exa fallback enabled.")
        else:
            logger.info(
                "[Stage2] EXA_API_KEY 已设置；将仅用于 Tavily quota/rate-limit failover，"
                "非 quota Exa fallback 仍需 --enable-exa-fallback。"
            )
    elif _should_enable_exa_fallback(args) and exa_api_key and not exa_sdk_available:
        logger.warning("[Stage2] EXA_API_KEY 已设置但 exa-py 未安装，Exa 兜底将被跳过。")
    elif _should_enable_exa_fallback(args) and not exa_api_key:
        logger.warning("[Stage2] Exa fallback requested but EXA_API_KEY is not set")
    elif exa_api_key and not exa_sdk_available:
        logger.warning("[Stage2] EXA_API_KEY 已设置但 exa-py 未安装，Tavily quota Exa failover 将被跳过。")
    extractor = DeepSeekExtractionAgent(
        model=args.deepseek_model,
        base_url=args.deepseek_base_url,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        trust_env=(
            os.getenv("DATASOURCE_NETWORK_MODE", "direct").lower() == "proxy"
        ),
    )

    completed_tasks: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    websearch_results: List[Dict[str, Any]] = []
    exec_stats: Dict[str, int] = {"domain_filtered_drop": 0, "regex_hits": 0}
    structured_registry = None
    if args.execute_search and args.extraction_backend != "langchain":
        structured_registry = _build_structured_registry_for_args(args)
    if args.dry_run:
        logger.info("[Stage2] Dry-run 模式：仅生成任务文件，不执行搜索")
    elif args.execute_search and tasks:
        if args.extraction_backend == "langchain":
            if run_tasks_lc is None:
                print("[ERROR] extraction_backend=langchain 但未安装 langchain 依赖。请安装或切换 deepseek。")
                return 1
            completed_tasks, failures, websearch_results = await run_tasks_lc(
                tasks,
                market_payload,
                tavily,
                extractor,
                task_log_path,
                args.cache_ttl,
                max_retries=args.max_retries,
                fund_flow_backend=args.fund_flow_backend,
                forex_backend="tavily",
                lc_max_concurrency=args.lc_max_concurrency,
                deepseek_timeout=args.lc_timeout,
                llm_hard_timeout=args.llm_hard_timeout,
            )
        else:
            completed_tasks, failures, websearch_results = await _execute_tasks(
                tasks,
                market_payload,
                tavily,
                exa_client,
                extractor,
                task_log_path,
                args.cache_ttl,
                max_retries=args.max_retries,
                fund_flow_backend=args.fund_flow_backend,
                forex_backend="tavily",
                deepseek_timeout=args.deepseek_timeout,
                extraction_backend=args.extraction_backend,
                deepseek_max_concurrency=args.deepseek_max_concurrency,
                stats=exec_stats,
                use_queue=args.use_queue,
                queue_concurrency=args.queue_concurrency,
                queue_maxsize=args.queue_maxsize,
                queue_retry_limit=args.queue_retry_limit,
                disable_extract=args.disable_extract,
                auto_disable_extract_on_422=args.auto_disable_extract_on_422,
                extract_422_threshold=args.extract_422_threshold,
                extract_422_cooldown_sec=args.extract_422_cooldown_sec,
                extract_topk=args.extract_topk,
                low_score_threshold=args.low_score_threshold,
                llm_hard_timeout=args.llm_hard_timeout,
                deepseek_breaker_consecutive_timeouts=args.deepseek_breaker_consecutive_timeouts,
                deepseek_breaker_timeout_rate=args.deepseek_breaker_timeout_rate,
                deepseek_breaker_min_attempts=args.deepseek_breaker_min_attempts,
                allow_exa_non_quota_fallback=_should_enable_exa_fallback(args),
                structured_registry=structured_registry,
            )

    flagged_fund_flow = _flag_fund_flow_anomalies(market_payload)
    # Second WebSearch pass for fund_flow anomalies (zero/None)
    if flagged_fund_flow and args.execute_search and args.fund_flow_backend == "tavily":
        retry_tasks = [t for t in tasks if t.get("indicator_key") in flagged_fund_flow]
        if retry_tasks:
            logger.info(f"[Stage2] fund_flow anomalies detected, retrying: {flagged_fund_flow}")
            retry_completed, retry_failures, retry_results = await _execute_tasks(
                retry_tasks,
                market_payload,
                tavily,
                exa_client,
                extractor,
                task_log_path,
                args.cache_ttl,
                max_retries=0,
                fund_flow_backend=args.fund_flow_backend,
                forex_backend="tavily",
                deepseek_timeout=args.deepseek_timeout,
                extraction_backend="regex",
                deepseek_max_concurrency=1,
                stats=exec_stats,
                use_queue=False,
                queue_concurrency=1,
                queue_maxsize=args.queue_maxsize,
                queue_retry_limit=0,
                disable_extract=True,
                auto_disable_extract_on_422=args.auto_disable_extract_on_422,
                extract_422_threshold=args.extract_422_threshold,
                extract_422_cooldown_sec=args.extract_422_cooldown_sec,
                extract_topk=args.extract_topk,
                low_score_threshold=args.low_score_threshold,
                llm_hard_timeout=args.llm_hard_timeout,
                deepseek_breaker_consecutive_timeouts=args.deepseek_breaker_consecutive_timeouts,
                deepseek_breaker_timeout_rate=args.deepseek_breaker_timeout_rate,
                deepseek_breaker_min_attempts=args.deepseek_breaker_min_attempts,
                allow_exa_non_quota_fallback=_should_enable_exa_fallback(args),
                structured_registry=structured_registry,
            )
            completed_tasks.extend(retry_completed)
            failures.extend(retry_failures)
            websearch_results.extend(retry_results)
            flagged_fund_flow = _flag_fund_flow_anomalies(market_payload)
    if websearch_results:
        websearch_results, conflicts_payload = resolve_websearch_results(websearch_results)
        _dump_json({"results": websearch_results}, websearch_results_path)
        split_dir = websearch_results_path.parent / "websearch_results"
        split_dir.mkdir(parents=True, exist_ok=True)
        for item in websearch_results:
            tid = item["task"]["task_id"]
            _dump_json(item, split_dir / f"{tid}.json")
        try:
            date_val = (
                market_payload.get("metadata", {}).get("date")
                or market_payload.get("metadata", {}).get("end_date")
                or market_payload.get("metadata", {}).get("start_date")
            )
            date_compact_local = str(date_val).replace("-", "") if date_val else datetime.now().strftime("%Y%m%d")
            conflicts_path = run_paths.data_dir / "source_conflicts.json"
            write_source_conflicts(conflicts_payload, conflicts_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[Stage2] source_conflicts write failed: {exc}")

    _compute_derived_metrics(market_payload)
    metadata = market_payload.setdefault("metadata", {})
    metadata["ai_websearch_enhanced"] = True
    metadata["stage2_completed_at"] = datetime.now().isoformat()

    _dump_json(market_payload, output_path, backup=True)

    pending_manual = list(
        dict.fromkeys([f["indicator_key"] for f in failures if f.get("manual_required") and f.get("indicator_key")])
    )
    success_keys = {c["indicator_key"] for c in completed_tasks}
    failure_keys = {f["indicator_key"] for f in failures}
    pending_keys = [
        t["indicator_key"]
        for t in tasks
        if t["indicator_key"] not in success_keys and t["indicator_key"] not in failure_keys
    ]
    _gap_monitor(pending_keys, gap_monitor_path, manual_required=pending_manual)

    # quality metrics & observability logs
    try:
        quality_path = run_paths.quality_metrics
        write_quality_metrics(market_payload, quality_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] quality_metrics write failed: {exc}")

    try:
        observability_payload = build_observability_log(tasks, completed_tasks, failures, pending_keys)
        observability_path = run_paths.observability
        write_observability_log(observability_payload, observability_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] observability log write failed: {exc}")

    avg_elapsed = 0
    p50_elapsed = 0
    p95_elapsed = 0
    deepseek_latency_list = exec_stats.get("deepseek_latencies", [])
    p50_llm = _percentile(deepseek_latency_list, 50) if deepseek_latency_list else 0
    p95_llm = _percentile(deepseek_latency_list, 95) if deepseek_latency_list else 0
    if completed_tasks:
        elapsed_vals = sorted([t.get("elapsed_ms", 0) or 0 for t in completed_tasks])
        avg_elapsed = sum(elapsed_vals) / len(elapsed_vals)
        mid = len(elapsed_vals) // 2
        p50_elapsed = elapsed_vals[mid]
        idx95 = max(0, min(len(elapsed_vals) - 1, int(len(elapsed_vals) * 0.95) - 1))
        p95_elapsed = elapsed_vals[idx95]
    cache_hits = sum(1 for t in completed_tasks if t.get("cache_hit"))
    cache_hit_rate = cache_hits / len(completed_tasks) if completed_tasks else 0

    # per-type 成功率统计
    def _indicator_category(ind: str) -> str:
        if ind in {"northbound", "southbound", "etf", "margin"}:
            return "fund_flow"
        if ind in {"USDCNY", "USDCNH", "DXY", "EURUSD", "GBPUSD", "USDJPY"}:
            return "forex"
        if ind in {"GC=F", "CL=F", "BZ=F", "HG=F", "BCOM", "GSG"}:
            return "commodities"
        if ind in {"US10Y", "CN10Y", "CN10Y_CDB"}:
            return "bonds"
        return "macro"

    success_by_cat = {}
    incremental_success_by_cat = {}
    total_by_cat = {}
    for t in tasks:
        cat = _indicator_category(t["indicator_key"])
        total_by_cat[cat] = total_by_cat.get(cat, 0) + 1
    for t in completed_tasks:
        cat = _indicator_category(t["indicator_key"])
        success_by_cat[cat] = success_by_cat.get(cat, 0) + 1
        if t.get("result_type") == "search_success":
            incremental_success_by_cat[cat] = incremental_success_by_cat.get(cat, 0) + 1
    skipped_existing_count = sum(1 for t in completed_tasks if t.get("result_type") == "skipped_existing")
    search_success_count = sum(1 for t in completed_tasks if t.get("result_type") == "search_success")
    structured_success_count = sum(1 for t in completed_tasks if t.get("result_type") == "structured_success")
    search_failed_count = sum(1 for t in failures if t.get("result_type") == "manual_required")
    stale_refresh_forced = sum(1 for t in tasks if _is_force_refresh_task(t))
    stale_refresh_success = sum(1 for t in completed_tasks if t.get("force_refresh") and t.get("result_type") == "search_success")
    stale_refresh_failed = sum(1 for t in failures if t.get("force_refresh"))
    incremental_denominator = search_success_count + search_failed_count
    search_success_rate_incremental = (
        search_success_count / incremental_denominator if incremental_denominator else 0.0
    )
    stage2_effective_success_count = search_success_count + structured_success_count
    stage2_effective_hit_rate = _stage2_effective_hit_rate(
        stage2_effective_success_count,
        search_failed_count,
    )
    summary_diagnostics = _build_stage2_summary_diagnostics(
        completed_tasks,
        failures,
        websearch_results,
        exec_stats,
    )

    summary = {
        "task_total": len(tasks),
        "task_completed": len(completed_tasks),
        "task_failed": len(failures),
        "task_skipped_existing": skipped_existing_count,
        "task_search_success": search_success_count,
        "task_structured_success": structured_success_count,
        "task_search_failed": search_failed_count,
        "stage2_effective_success": stage2_effective_success_count,
        "stage2_effective_hit_rate": stage2_effective_hit_rate,
        "task_stale_refresh_forced": stale_refresh_forced,
        "task_stale_refresh_success": stale_refresh_success,
        "task_stale_refresh_failed": stale_refresh_failed,
        "search_success_rate_incremental": search_success_rate_incremental,
        "retrieval_diagnostics": summary_diagnostics["retrieval_diagnostics"],
        "manual_reason_breakdown": summary_diagnostics["manual_reason_breakdown"],
        "manual_required": pending_manual,
        "output": str(output_path),
        "task_file": str(task_file),
        "log": str(log_output),
        "gap_monitor": str(gap_monitor_path),
        "flagged_fund_flow": flagged_fund_flow,
        "cache_backend": args.cache_backend if not args.no_cache else "disabled",
        "proxy": {"http": args.http_proxy or os.getenv("HTTP_PROXY"), "https": args.https_proxy or os.getenv("HTTPS_PROXY")},
        "fund_flow_backend": args.fund_flow_backend,
        "avg_elapsed_ms": avg_elapsed,
        "p50_elapsed_ms": p50_elapsed,
        "p95_elapsed_ms": p95_elapsed,
        "cache_hit_rate": cache_hit_rate,
        "domain_filtered_drop": exec_stats.get("domain_filtered_drop", 0),
        "regex_hits": exec_stats.get("regex_hits", 0),
        "score_filtered_drop": exec_stats.get("score_filtered_drop", 0),
        "low_score_drop": exec_stats.get("low_score_drop", 0),
        "value_evidence_drop_count": exec_stats.get("value_evidence_drop_count", 0),
        "timeout_count": exec_stats.get("timeout_count", 0),
        "deepseek_timeouts": exec_stats.get("deepseek_timeouts", 0),
        "deepseek_circuit_breaker_triggered": exec_stats.get("deepseek_circuit_breaker_triggered", False),
        "deepseek_circuit_breaker_reason": exec_stats.get("deepseek_circuit_breaker_reason"),
        "deepseek_timeout_rate": exec_stats.get("deepseek_timeout_rate", 0.0),
        "deepseek_breaker_attempts": exec_stats.get("deepseek_breaker_attempts", 0),
        "deepseek_breaker_timeouts": exec_stats.get("deepseek_breaker_timeouts", 0),
        "retry_count": exec_stats.get("retry_count", 0),
        "extract_calls": exec_stats.get("extract_calls", 0),
        "tavily_extract_calls": exec_stats.get("tavily_extract_calls", 0),
        "tavily_extract_422_count": exec_stats.get("tavily_extract_422_count", 0),
        "extract_fallback_to_deepseek": exec_stats.get("extract_fallback_to_deepseek", 0),
        "extract_auto_disabled": exec_stats.get("extract_auto_disabled", False),
        "extract_cooldown_count": exec_stats.get("extract_cooldown_count", 0),
        "extract_globally_disabled": exec_stats.get("extract_globally_disabled", args.disable_extract),
        "extract_global_disable_reason": exec_stats.get("extract_global_disable_reason"),
        "field_retry_count": exec_stats.get("field_retry_count", 0),
        "field_retry_merged_count": exec_stats.get("field_retry_merged_count", 0),
        "field_retry_missing_fields": exec_stats.get("field_retry_missing_fields", {}),
        "post_filter_query_switch_count": exec_stats.get("post_filter_query_switch_count", 0),
        "exa_fallback": exec_stats.get("exa_fallback", 0),
        "exa_empty": exec_stats.get("exa_empty", 0),
        "exa_error": exec_stats.get("exa_error", 0),
        "exa_fallback_after_extract_422": exec_stats.get("exa_fallback_after_extract_422", 0),
        "exa_fallback_after_extract_cooldown": exec_stats.get("exa_fallback_after_extract_cooldown", 0),
        "exa_skipped_no_key_after_extract": exec_stats.get("exa_skipped_no_key_after_extract", 0),
        "deepseek_p50_ms": p50_llm,
        "deepseek_p95_ms": p95_llm,
        "queue_requeued": exec_stats.get("queue_requeued", 0),
        "queue_dead_letters": exec_stats.get("queue_dead_letters", 0),
        "write_back_by_category": exec_stats.get("write_back_by_category", {}),
        "write_back_fallback_count": exec_stats.get("write_back_fallback_count", 0),
        "write_back_miss_count": exec_stats.get("write_back_miss_count", 0),
        "structured_provider": exec_stats.get("structured_provider", {}),
        "structured_policy_gate_blocked": exec_stats.get("structured_policy_gate_blocked", 0),
        "structured_error_samples": exec_stats.get("structured_error_samples", []),
        "success_by_category": success_by_cat,
        "search_success_by_category": incremental_success_by_cat,
        "total_by_category": total_by_cat,
    }
    if "tavily_unavailable_reason" in summary_diagnostics:
        summary["tavily_unavailable_reason"] = summary_diagnostics["tavily_unavailable_reason"]
    for key in _STAGE2_BACKEND_SUMMARY_KEYS:
        if key in summary_diagnostics:
            summary[key] = summary_diagnostics[key]
    for key in _structured_provider_summary_fields({}).keys():
        summary[key] = summary_diagnostics.get(key, summary.get(key))
    _dump_json(summary, log_output)

    try:
        policy_payload = evaluate_policy(market_payload, stage2_summary=summary)
        policy_path = run_paths.policy_evaluation
        write_policy_evaluation(policy_payload, policy_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] policy evaluation write failed: {exc}")

    try:
        snapshot_path = run_paths.run_snapshot
        write_run_snapshot(snapshot_path, " ".join(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] run_snapshot write failed: {exc}")


    print("\n[Stage2 Summary]")
    print(
        f"  任务总数: {summary['task_total']}, legacy完成: {summary['task_completed']}, "
        f"真实搜索成功: {summary['task_search_success']}, 搜索失败: {summary['task_search_failed']}, "
        f"跳过已有值: {summary['task_skipped_existing']}, 待人工: {len(pending_manual)}"
    )
    if summary["proxy"]["http"] or summary["proxy"]["https"]:
        print(f"  Proxy: http={summary['proxy']['http']} https={summary['proxy']['https']}")
    print(f"  输出: {output_path}")
    print(f"  gap_monitor: {gap_monitor_path}")
    print(f"  平均耗时: {summary['avg_elapsed_ms']:.1f} ms; 缓存命中率: {summary['cache_hit_rate']*100:.1f}%")
    print(
        f"  过滤/兜底: 域名过滤丢弃 {summary['domain_filtered_drop']} 条；score 过滤 {summary['score_filtered_drop']} 条；"
        f"低分跳过 {summary['low_score_drop']} 次；regex 命中 {summary['regex_hits']} 次；"
        f"后过滤改选query {summary.get('post_filter_query_switch_count', 0)} 次"
    )
    auto_flag = "已触发按指标冷却" if summary.get("extract_auto_disabled") else "extract保持开启"
    fallback_ds = summary.get("extract_fallback_to_deepseek", 0)
    print(
        f"  LLM: extract {summary['extract_calls']} 次；timeout {summary['timeout_count']} 次；retry {summary['retry_count']} 次; "
        f"tavily_extract {summary['tavily_extract_calls']} 次 (422={summary['tavily_extract_422_count']}, 降级DS={fallback_ds}, {auto_flag}); "
        f"field_retry {summary.get('field_retry_count', 0)} 次；Exa回退 {summary.get('exa_fallback', 0)} 次 "
        f"(422后={summary.get('exa_fallback_after_extract_422', 0)}, cooldown后={summary.get('exa_fallback_after_extract_cooldown', 0)}); "
        f"queue_requeued {summary.get('queue_requeued',0)} dead {summary.get('queue_dead_letters',0)}"
    )
    if summary.get("extract_globally_disabled"):
        print(
            f"  extract全局停用: True (reason={summary.get('extract_global_disable_reason') or 'unknown'})"
        )
    print(
        f"  回写统计: {summary.get('write_back_by_category', {})} "
        f"(fallback={summary.get('write_back_fallback_count', 0)}, miss={summary.get('write_back_miss_count', 0)})"
    )
    if summary.get("success_by_category"):
        print(f"  分类型成功: {summary['success_by_category']} / {summary['total_by_category']}")
        print(f"  分类型真实搜索成功: {summary.get('search_success_by_category', {})} / {summary['total_by_category']}")
    print(
        f"  增量命中率: {summary['search_success_rate_incremental']*100:.1f}% ; "
        f"stale强制刷新 {summary['task_stale_refresh_forced']} 项 "
        f"(成功 {summary['task_stale_refresh_success']}, 失败 {summary['task_stale_refresh_failed']})"
    )
    if pending_manual or summary["task_failed"] > 0:
        print("  [WARN] 仍有任务未完成或需人工处理，可用 --resume-from-task-file 重试指定任务。")
    logger.info(f"[Stage2 Unified] 完成，写入 {output_path}")
    return 1 if (pending_manual or summary["task_failed"] > 0) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
