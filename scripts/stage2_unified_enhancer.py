#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 2 Unified Enhancer (Tavily + DeepSeek)
-------------------------------------------
一次性跑完 Phase-E/Phase-A 的搜索任务规划、执行与写回。
当前实现聚焦“可运行的骨架”：
- 生成 SearchTaskContract JSONL（reports/search_tasks_stage2.jsonl）
- 可选执行 Tavily 搜索 + DeepSeek 抽取，并把结果落到 market_data.json
- 计算派生字段 (m1_m2_spread 等)
- 输出日志/状态标志，方便 Stage3 在入口阻断

资金流向仍保持 MCP WebSearch 独立通道；如检测到零值占位会写入 gap_monitor.json 供人工复核。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from itertools import count
from datetime import datetime, timedelta, timezone
import re
import shutil
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None

from datasource.adapters.tavily_client import AsyncTavilyClient
from datasource.cache.memory_cache import MemoryCache
from datasource.cache.sqlite_cache import SQLiteCache
from datasource.engines.deepseek_reasoner import DeepSeekExtractionAgent
try:
    from datasource.engines.stage2_lc_pipeline import run_tasks_lc  # type: ignore
except Exception:  # pragma: no cover - 可选依赖缺失时延迟报错
    run_tasks_lc = None  # type: ignore
from datasource.engines.stage2_task_planner import Stage2TaskPlanner


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _merge_missing_items(market_payload: Dict[str, Any]) -> None:
    """把 metadata.missing_items(dict) 扁平化到顶层 missing_items(list)，便于 Stage2 扫描"""
    top = market_payload.get("missing_items")
    merged: List[Any] = []
    if isinstance(top, list):
        merged.extend(top)
    metadata_missing = market_payload.get("metadata", {}).get("missing_items", {})
    if isinstance(metadata_missing, dict):
        for category, items in metadata_missing.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict):
                    if "stage_category" not in it:
                        it = {**it, "stage_category": category}
                    merged.append(it)
                else:
                    merged.append({"key": it, "stage_category": category})
    # 去重按 key+category
    seen = set()
    unique = []
    for it in merged:
        key = it.get("key") if isinstance(it, dict) else it
        cat = it.get("stage_category") if isinstance(it, dict) else ""
        sig = (key, cat)
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(it)
    if unique:
        market_payload["missing_items"] = unique


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
    m = re.search(r"(20\\d{2})[-/.](\\d{1,2})[-/.](\\d{1,2})", text)
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


def _check_task_completeness(tasks: List[Dict[str, Any]]) -> List[str]:
    """检查任务的查询信息是否完整，返回警告列表"""
    warnings: List[str] = []
    for t in tasks:
        key = t.get("indicator_key")
        domains = t.get("preferred_domains") or []
        query = t.get("query")
        unit = t.get("unit")
        issuer = t.get("issuer")
        if not query:
            warnings.append(f"{key}: 缺少 query，已回退为 indicator_key")
        if not domains:
            warnings.append(f"{key}: 缺少 preferred_domains，可能命中词典/非目标站点")
        # 对宏观/货币/资金流向指标建议提供单位/发布机构
        if key in {"cpi", "ppi", "pmi", "pmi_new_orders", "industrial_output", "industrial", "industrial_sales",
                   "gdp", "m1", "m2", "dr007", "reverse_repo", "rrr", "mlf", "reverse_repo_7d",
                   "northbound", "southbound", "etf"}:
            if not unit:
                warnings.append(f"{key}: 未设置 unit，建议补充以便抽取校验")
            if not issuer:
                warnings.append(f"{key}: 未设置 issuer（发布机构），建议补充筛选提示")
    return warnings

def _dump_json(payload: Dict[str, Any], path: Path, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        backup_path = path.with_name(path.name + f".bak")
        timestamp_path = path.with_name(f"{path.stem}_{datetime.now():%Y%m%d%H%M%S}{path.suffix}")
        try:
            shutil.copy2(path, backup_path)
            shutil.copy2(path, timestamp_path)
        except Exception:
            pass  # 备份失败不阻塞写入
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _append_task_log(task_log_path: Path, record: Dict[str, Any]) -> None:
    task_log_path.parent.mkdir(parents=True, exist_ok=True)
    with task_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _safe_number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _filter_by_domain(snippets: List[Dict[str, Any]], preferred: Optional[List[str]]) -> List[Dict[str, Any]]:
    """过滤掉不在白名单域名中的搜索结果；若过滤后为空则回退原列表。"""
    if not preferred:
        return snippets
    filtered: List[Dict[str, Any]] = []
    for snip in snippets:
        url = snip.get("url") or ""
        try:
            netloc = urlparse(url).netloc
            if any(netloc.endswith(d) for d in preferred):
                filtered.append(snip)
        except Exception:
            continue
    return filtered or snippets


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
    if ind in {"industrial", "industrial_sales"}:
        patterns = [r"([-+]?\\d+(?:\\.\\d+)?)\\s*%"]
    elif ind in {"mlf", "reverse_repo", "rrr"}:
        patterns = [r"([-+]?\\d+(?:\\.\\d+)?)\\s*%"]
    elif ind == "bdi":
        patterns = [r"BDI[^\\d]*([-+]?\\d{3,5}(?:\\.\\d+)?)", r"([-+]?\\d{3,5}(?:\\.\\d+)?)"]
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


def _apply_extraction(market_payload: Dict[str, Any], task: Dict[str, Any], extraction: Dict[str, Any]) -> None:
    value = extraction.get("value")
    if value is None:
        return

    indicator_key = task["indicator_key"]
    note = extraction.get("note")
    source_url = extraction.get("source_url")
    source_label = "tavily+deepseek" if source_url else "tavily_regex"

    macro = market_payload.setdefault("macro_indicators", {})
    if indicator_key in macro:
        macro[indicator_key]["current_value"] = value
        macro[indicator_key]["source"] = source_label
        macro[indicator_key]["stage_task_id"] = task["task_id"]
        macro[indicator_key]["note"] = note
        return

    monetary = market_payload.setdefault("monetary_policy", {})
    if indicator_key in monetary:
        monetary[indicator_key]["current_value"] = value
        monetary[indicator_key]["source"] = source_label
        monetary[indicator_key]["stage_task_id"] = task["task_id"]
        monetary[indicator_key]["note"] = note
        return

    # fund_flow 回写（简化：将抽取值写 recent_5d，total_120d 同值）
    fund_flow = market_payload.get("fund_flow", {})
    if indicator_key in fund_flow:
        flow = fund_flow[indicator_key]
        flow["recent_5d"] = value
        flow["total_120d"] = flow.get("total_120d") or value
        flow["source"] = source_label
        flow["stage_task_id"] = task["task_id"]
        flow["note"] = note
        return

    # 若不存在，则落到 macro_indicators 以便后续 Stage3 检查
    macro[indicator_key] = {
        "indicator_name": indicator_key.upper(),
        "current_value": value,
        "unit": extraction.get("unit") or "%",
        "date": market_payload.get("metadata", {}).get("date", ""),
        "source": source_label,
        "stage_task_id": task["task_id"],
        "note": note,
    }


def _update_missing_items(market_payload: Dict[str, Any], indicator_key: str) -> None:
    missing = market_payload.get("missing_items", [])
    if not missing:
        return
    filtered = []
    for item in missing:
        if isinstance(item, dict):
            key = item.get("key", "")
            if key and key != indicator_key:
                filtered.append(item)
        else:
            if item != indicator_key:
                filtered.append(item)
    market_payload["missing_items"] = filtered


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


async def _execute_tasks(
    tasks: List[Dict[str, Any]],
    market_payload: Dict[str, Any],
    client: AsyncTavilyClient,
    extractor: DeepSeekExtractionAgent,
    task_log_path: Path,
    cache_ttl: Optional[int],
    max_retries: int = 1,
    fund_flow_backend: str = "mcp",
    forex_backend: str = "hybrid",
    deepseek_timeout: Optional[float] = None,
    extraction_backend: str = "deepseek",
    deepseek_max_concurrency: int = 3,
    deepseek_serial_keys: Optional[List[str]] = None,
    stats: Optional[Dict[str, int]] = None,
    use_queue: bool = False,
    queue_concurrency: int = 3,
    queue_maxsize: int = 100,
    queue_retry_limit: int = 1,
) -> (List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]):
    completed: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    websearch_results: List[Dict[str, Any]] = []
    manual_required_keys: List[str] = []
    skipped_mcp: List[Dict[str, Any]] = []
    stats = stats if stats is not None else {}
    stats.setdefault("domain_filtered_drop", 0)
    stats.setdefault("regex_hits", 0)
    stats.setdefault("score_filtered_drop", 0)
    stats.setdefault("timeout_count", 0)
    stats.setdefault("retry_count", 0)
    stats.setdefault("extract_calls", 0)
    stats.setdefault("tavily_extract_calls", 0)
    stats.setdefault("queue_requeued", 0)
    stats.setdefault("queue_dead_letters", 0)
    forex_keys = {"USDCNY", "USDCNH", "DXY", "EURUSD", "GBPUSD", "USDJPY"}
    ds_semaphore = asyncio.Semaphore(max(1, deepseek_max_concurrency))
    serial_keys = set(deepseek_serial_keys or [])

    async def _do_extract(snips: List[Dict[str, Any]], task: Dict[str, Any]) -> Dict[str, Any]:
        """执行抽取，记录 DeepSeek 延迟与错误；regex 模式直接返回占位。"""
        if extraction_backend == "regex":
            val, url = extractor._fallback_extract(snips)  # type: ignore
            return {
                "value": val,
                "unit": task.get("unit"),
                "source_url": url or (snips[0].get("url") if snips else None),
                "confidence": 0.35 if val is not None else 0.0,
                "note": "regex_only",
                "llm_latency_ms": 0,
                "llm_error": None,
            }
        start_llm = time.perf_counter()
        attempts = 0
        last_exc: Optional[Exception] = None
        while attempts < 2:
            attempts += 1
            try:
                if task["indicator_key"] in serial_keys:
                    result = await extractor.extract(
                        snips,
                        task["indicator_key"],
                        unit_hint=task.get("unit"),
                        issuer_hint=task.get("issuer"),
                        request_timeout=deepseek_timeout,
                    )
                else:
                    async with ds_semaphore:
                        result = await extractor.extract(
                            snips,
                            task["indicator_key"],
                            unit_hint=task.get("unit"),
                            issuer_hint=task.get("issuer"),
                            request_timeout=deepseek_timeout,
                        )
                result = result or {}
                result["llm_latency_ms"] = int((time.perf_counter() - start_llm) * 1000)
                if attempts > 1:
                    stats["retry_count"] += 1
                return result
            except Exception as exc:  # pragma: no cover
                last_exc = exc
                stats["timeout_count"] += 1
                if attempts >= 2:
                    logger.warning(f"DeepSeek 请求失败，将使用 regex 兜底: {exc}")
                    val, url = extractor._fallback_extract(snips)  # type: ignore
                    return {
                        "value": val,
                        "unit": task.get("unit"),
                        "source_url": url or (snips[0].get("url") if snips else None),
                        "confidence": 0.2 if val is not None else 0.0,
                        "note": f"deepseek_error:{exc}",
                        "llm_error": str(exc),
                        "llm_latency_ms": int((time.perf_counter() - start_llm) * 1000),
                    }
    queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize) if use_queue else None  # type: ignore

    async def consumer():
        while True:
            try:
                item = await queue.get()  # type: ignore
            except asyncio.CancelledError:
                break
            task, snippets, attempt_idx = item
            try:
                stats["extract_calls"] += 1
                extraction = await _do_extract(snippets, task)
                # regex 兜底：关键指标无值时尝试直接提取数字
                if extraction.get("value") is None:
                    regex_val = _regex_fallback(snippets, task["indicator_key"])
                    if regex_val is not None:
                        extraction["value"] = regex_val
                        extraction.setdefault("note", "regex_fallback")
                        stats["regex_hits"] += 1
                is_fund_flow = task["indicator_key"] in {"northbound", "southbound", "etf", "margin"}
                manual_required = False
                if is_fund_flow and (extraction.get("confidence", 0.0) < 0.5 or extraction.get("value") is None):
                    manual_required = True
                if is_fund_flow:
                    adjusted_value, unit_manual, note_append = _validate_fund_flow_extraction(extraction)
                    extraction["value"] = adjusted_value
                    combined_note = " ".join(
                        s for s in [extraction.get("note", ""), note_append] if s
                    ).strip()
                    extraction["note"] = combined_note or None
                    manual_required = manual_required or unit_manual
                else:
                    val_adj, manual2, note_append2 = _validate_general_extraction(extraction, task, snippets)
                    extraction["value"] = val_adj
                    if note_append2:
                        extraction["note"] = ((extraction.get("note") or "") + " " + note_append2).strip()
                    manual_required = manual_required or manual2

                task_record = {
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
                    "request_id": None,
                    "http_status": None,
                    "cache_hit": None,
                    "attempt_index": attempt_idx,
                    "elapsed_ms": None,
                    "created_at": task["created_at"],
                    "finished_at": int(datetime.now().timestamp()),
                    "manual_required": manual_required,
                }
                if manual_required:
                    failures.append(task_record)
                    if extraction.get("value") is None:
                        manual_required_keys.append(task_record["indicator_key"])
                else:
                    _apply_extraction(market_payload, task, extraction)
                    _update_missing_items(market_payload, task["indicator_key"])
                    completed.append(task_record)
                _append_task_log(task_log_path, task_record)
                websearch_results.append(
                    {
                        "task": task,
                        "extraction": extraction,
                        "extraction_backend": extraction_backend,
                        "raw_results": snippets[:3],
                    }
                )
            except Exception as exc:
                if attempt_idx <= queue_retry_limit:
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
        backend = task.get("fund_flow_backend") or fund_flow_backend
        backend_forex = task.get("forex_backend") or forex_backend
        try:
            for attempt in count(start=1):
                started = time.perf_counter()
                try:
                    result = await client.search(
                        query=task.get("query") or task["indicator_key"],
                        search_depth=task.get("search_depth") or ("advanced" if task["stage_phase"] == "assets" else "basic"),
                        include_domains=task.get("preferred_domains") or None,
                        time_range=task.get("time_range"),
                        topic=task.get("topic"),
                        language=task.get("language"),
                        max_results=task.get("max_results"),
                        chunks_per_source=task.get("chunks_per_source"),
                        auto_parameters=task.get("auto_parameters"),
                        cache_ttl=cache_ttl,
                    )
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    snippets = result.get("results") or []
                    # Tavily extract (two-step) for noisy tasks
                    try:
                        if is_fund_flow or is_forex or task["indicator_key"] in {"GC=F", "CL=F", "BZ=F", "HG=F", "BCOM", "GSG"}:
                            top_for_extract = snippets[:3]
                            if top_for_extract:
                                stats["tavily_extract_calls"] += 1
                                extract_resp = await client.extract(
                                    search_results=top_for_extract,
                                    extract_depth="advanced" if is_fund_flow or is_forex else "standard",
                                    include_raw_content=is_fund_flow,
                                    cache_ttl=cache_ttl,
                                )
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
                        logger.debug(f"Tavily extract skipped/failed: {exc}")
                    # score 过滤
                    before_score = len(snippets)
                    high_score = [s for s in snippets if s.get("score") is None or s.get("score", 0) >= 0.5]
                    if high_score:
                        snippets = high_score
                        stats["score_filtered_drop"] += max(0, before_score - len(snippets))
                    before = len(snippets)
                    snippets = _filter_by_domain(snippets, task.get("preferred_domains"))
                    after = len(snippets)
                    if before and before != after:
                        stats["domain_filtered_drop"] += before - after
                    snippets = _prefer_fresh_snippets(snippets, task.get("max_age_days"))
                    if use_queue:
                        await queue.put((task, snippets, attempt))  # type: ignore
                        break
                    else:
                        stats["extract_calls"] += 1
                        extraction = await _do_extract(snippets, task)
                        # regex 兜底：关键指标无值时尝试直接提取数字
                        if extraction.get("value") is None:
                            regex_val = _regex_fallback(snippets, task["indicator_key"])
                            if regex_val is not None:
                                extraction["value"] = regex_val
                                extraction.setdefault("note", "regex_fallback")
                                stats["regex_hits"] += 1
                        # fund_flow 低置信度或无值 → manual_required
                        manual_required = False
                        if is_fund_flow and (extraction.get("confidence", 0.0) < 0.5 or extraction.get("value") is None):
                            manual_required = True
                        if is_fund_flow:
                            adjusted_value, unit_manual, note_append = _validate_fund_flow_extraction(extraction)
                            extraction["value"] = adjusted_value
                            combined_note = " ".join(
                                s for s in [extraction.get("note", ""), note_append] if s
                            ).strip()
                            extraction["note"] = combined_note or None
                            manual_required = manual_required or unit_manual
                        else:
                            # 对非资金流向的校验
                            val_adj, manual2, note_append2 = _validate_general_extraction(extraction, task, snippets)
                            extraction["value"] = val_adj
                            if note_append2:
                                extraction["note"] = ((extraction.get("note") or "") + " " + note_append2).strip()
                            manual_required = manual_required or manual2

                        task_record = {
                            "task_id": task["task_id"],
                            "indicator_key": task["indicator_key"],
                            "stage_phase": task["stage_phase"],
                            "search_backend": task["search_backend"],
                            "fund_flow_backend": backend if is_fund_flow else None,
                            "extraction_backend": extraction_backend,
                            "confidence": extraction.get("confidence", 0.0),
                            "source_url": extraction.get("source_url"),
                            "note": extraction.get("note"),
                            "llm_latency_ms": extraction.get("llm_latency_ms"),
                            "llm_error": extraction.get("llm_error"),
                            "deepseek_error": extraction.get("note")
                            if isinstance(extraction.get("note"), str)
                            and extraction["note"].startswith("deepseek_error")
                            else None,
                            "request_id": result.get("response_id") or result.get("request_id"),
                            "http_status": result.get("status"),
                            "cache_hit": result.get("cache_hit", False),
                            "attempt_index": attempt,
                            "elapsed_ms": elapsed_ms,
                            "created_at": task["created_at"],
                            "finished_at": int(datetime.now().timestamp()),
                            "manual_required": manual_required,
                        }
                        if manual_required:
                            failures.append(task_record)
                            if attempt >= max_retries + 1 and extraction.get("value") is None:
                                manual_required_keys.append(task_record["indicator_key"])
                        else:
                            _apply_extraction(market_payload, task, extraction)
                            _update_missing_items(market_payload, task["indicator_key"])
                            completed.append(task_record)
                        _append_task_log(task_log_path, task_record)
                        websearch_results.append(
                            {
                                "task": task,
                                "extraction": extraction,
                                "extraction_backend": extraction_backend,
                                "raw_results": snippets[:3],  # 仅保留前3条片段便于审计
                            }
                        )
                        break
                except Exception as exc:  # pragma: no cover - 网络错误兜底
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    logger.warning(f"Tavily/DeepSeek 执行失败 {task['indicator_key']} attempt={attempt}: {exc}")
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
    if manual_required_keys:
        _append_gap_monitor(Path(args.gap_monitor), [], sorted(set(manual_required_keys)))
    return completed, failures, websearch_results


def _gap_monitor(
    pending: List[str],
    output_path: Path,
    manual_required: Optional[List[str]] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    clean_pending = [p for p in pending if p]
    clean_manual = [m for m in manual_required or [] if m]
    payload = {
        "generated_at": datetime.now().isoformat(),
    }
    if clean_pending:
        payload["pending_tasks"] = clean_pending
    if clean_manual:
        payload["manual_required"] = clean_manual
    _dump_json(payload, output_path)


def _flag_fund_flow_anomalies(market_payload: Dict[str, Any]) -> List[str]:
    """标记资金流向的零值/空值"""
    flagged: List[str] = []
    fund_flow = market_payload.get("fund_flow", {})
    for key, item in fund_flow.items():
        recent = _safe_number(item.get("recent_5d"))
        total = _safe_number(item.get("total_120d"))
        if (recent is None or abs(recent) < 1e-9) or (total is None or abs(total) < 1e-9):
            item["source"] = "异常零值-需核查"
            note = (item.get("note") or "").strip()
            if "异常零值-需核查" not in note:
                note = (note + " 异常零值-需核查").strip()
            item["note"] = note
            item["manual_required"] = True
            flagged.append(key)
        else:
            # 合规标注 MCP
            if "mcp" in (item.get("source") or "").lower():
                item["source"] = "MCP WebSearch实时获取"
    return flagged


def _validate_fund_flow_extraction(extraction: Dict[str, Any]) -> (Optional[float], bool, str):
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
    if "亿" not in unit:
        manual = True
        note_append = (note_append + " 单位缺失(需含亿)").strip()
    # 方向校验：根据 note / raw snippet 关键词推断
    text_blob = str(extraction.get("note") or "").lower()
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
    manual = False
    note_append = ""

    # unit 校验（允许点/points 互通）
    if unit_hint:
        unit_val = extraction.get("unit") or ""
        # 点的宽松匹配
        if unit_hint in {"点", "points"} and any(tok in unit_val for tok in ["点", "points"]):
            pass
        elif unit_hint not in unit_val:
            manual = True
            note_append = (note_append + f" 单位不匹配(需含{unit_hint})").strip()

    # 域名校验
    src = extraction.get("source_url")
    if domains and src:
        try:
            netloc = urlparse(src).netloc
            if not any(netloc.endswith(d) for d in domains):
                manual = True
                note_append = (note_append + " 域名不在白名单").strip()
        except Exception:
            manual = True
            note_append = (note_append + " source_url解析失败").strip()

    # 发布机构校验：若提供 issuer_hint，需要在抽取或片段中出现
    if issuer_hint:
        issuer_match_flag = extraction.get("issuer_match")
        snippets_text = " ".join(
            [
                str(s.get("content", "")) or str(s.get("snippet", "")) or ""
                for s in (snippets or [])
            ]
        ).lower()
        alias_hit = any(alias.lower() in snippets_text for alias in issuer_aliases)
        if not issuer_match_flag and issuer_hint.lower() not in snippets_text and not alias_hit:
            # 若已有有效数值但缺发行人，则仅提示不强制人工；无值则仍需人工
            if val is None:
                manual = True
            note_append = (note_append + f" 缺少发布机构({issuer_hint})").strip()

    # 时效性校验：若所有可解析日期均超过设定阈值，则标记人工复核
    max_age = task.get("max_age_days")
    if max_age and _is_stale(snippets, max_age):
        manual = True
        note_append = (note_append + f" 数据超过{max_age}天需更新").strip()

    return val, manual, note_append


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 2 Unified Enhancer (Tavily + DeepSeek)")
    parser.add_argument("--market-data", required=True, help="Stage1 生成的 market_data.json 路径")
    parser.add_argument("--output", help="增强后输出路径；默认覆盖输入")
    parser.add_argument("--phase", choices=["essential", "assets", "all"], default="all")
    parser.add_argument("--search-backend", choices=["tavily"], default="tavily")
    parser.add_argument("--fund-flow-backend", choices=["tavily", "hybrid"], default="tavily")
    parser.add_argument("--task-file", default="reports/search_tasks_stage2.jsonl", help="输出任务文件路径")
    parser.add_argument("--task-log", default="logs/stage_task_log.jsonl")
    parser.add_argument("--websearch-results", default="reports/websearch_results_auto.json", help="搜索抽取结果保存路径")
    parser.add_argument("--cache-ttl", type=int, default=3600)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--cache-backend", choices=["memory", "sqlite"], default="memory")
    parser.add_argument("--cache-path", default="reports/tavily_cache.sqlite")
    parser.add_argument("--http-proxy", help="HTTP proxy, overrides env")
    parser.add_argument("--https-proxy", help="HTTPS proxy, overrides env")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--deepseek-timeout", type=float, default=12.0, help="DeepSeek抽取超时时间(秒)")
    parser.add_argument("--deepseek-max-concurrency", type=int, default=2, help="DeepSeek并发上限")
    parser.add_argument("--deepseek-model", default="deepseek-reasoner", help="DeepSeek模型名")
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
    parser.add_argument("--log-output", default="logs/stage2_unified_log.json")
    parser.add_argument("--gap-monitor", default="reports/gap_monitor.json")
    parser.add_argument("--use-queue", action="store_true", help="开启 extraction 阶段 asyncio.Queue 消费模式")
    parser.add_argument("--queue-concurrency", type=int, default=3, help="Queue 消费者并发数")
    parser.add_argument("--queue-maxsize", type=int, default=100, help="Queue 最大容量")
    parser.add_argument("--queue-retry-limit", type=int, default=2, help="Queue 抽取重试次数（超时/网络错误）")
    return parser.parse_args()


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
    market_path = Path(args.market_data)
    output_path = Path(args.output) if args.output else market_path
    task_file = Path(args.task_file)
    task_log_path = Path(args.task_log)
    websearch_results_path = Path(args.websearch_results)
    log_output = Path(args.log_output)
    gap_monitor_path = Path(args.gap_monitor)

    market_payload = _load_json(market_path)
    _merge_missing_items(market_payload)

    # 先校验密钥并加载 .env，避免在初始化 TavilyClient 时 api_key 为空
    require_tavily = True  # 当前 search_backend 固定 tavily
    require_deepseek = True  # extractor 默认 deepseek/langchain
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
    tavily = AsyncTavilyClient(
        api_key=os.getenv("TAVILY_API_KEY"),
        cache=cache,
        timeout=args.read_timeout,
        connect_timeout=args.connect_timeout,
        max_concurrency=4,
        proxies=proxies or None,
    )
    extractor = DeepSeekExtractionAgent(
        model=args.deepseek_model,
        base_url=args.deepseek_base_url,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
    )

    completed_tasks: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    websearch_results: List[Dict[str, Any]] = []
    exec_stats: Dict[str, int] = {"domain_filtered_drop": 0, "regex_hits": 0}
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
                forex_backend="hybrid",
                lc_max_concurrency=args.lc_max_concurrency,
                deepseek_timeout=args.lc_timeout,
            )
        else:
            completed_tasks, failures, websearch_results = await _execute_tasks(
                tasks,
                market_payload,
                tavily,
                extractor,
                task_log_path,
                args.cache_ttl,
                max_retries=args.max_retries,
                fund_flow_backend=args.fund_flow_backend,
                forex_backend="hybrid",
                deepseek_timeout=args.deepseek_timeout,
                extraction_backend=args.extraction_backend,
                deepseek_max_concurrency=args.deepseek_max_concurrency,
                stats=exec_stats,
            )

    flagged_fund_flow = _flag_fund_flow_anomalies(market_payload)
    if websearch_results:
        _dump_json({"results": websearch_results}, websearch_results_path)
        split_dir = websearch_results_path.parent / "websearch_results"
        split_dir.mkdir(parents=True, exist_ok=True)
        for item in websearch_results:
            tid = item["task"]["task_id"]
            _dump_json(item, split_dir / f"{tid}.json")

    _compute_derived_metrics(market_payload)
    metadata = market_payload.setdefault("metadata", {})
    metadata["ai_websearch_enhanced"] = True
    metadata["stage2_completed_at"] = datetime.now().isoformat()

    _dump_json(market_payload, output_path, backup=True)

    pending_manual = [f["indicator_key"] for f in failures if f.get("manual_required")]
    success_keys = {c["indicator_key"] for c in completed_tasks}
    failure_keys = {f["indicator_key"] for f in failures}
    pending_keys = [
        t["indicator_key"]
        for t in tasks
        if t["indicator_key"] not in success_keys and t["indicator_key"] not in failure_keys
    ]
    _gap_monitor(pending_keys, gap_monitor_path, manual_required=pending_manual)

    avg_elapsed = 0
    if completed_tasks:
        avg_elapsed = sum(t.get("elapsed_ms", 0) or 0 for t in completed_tasks) / len(completed_tasks)
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
    total_by_cat = {}
    for t in tasks:
        cat = _indicator_category(t["indicator_key"])
        total_by_cat[cat] = total_by_cat.get(cat, 0) + 1
    for t in completed_tasks:
        cat = _indicator_category(t["indicator_key"])
        success_by_cat[cat] = success_by_cat.get(cat, 0) + 1

    summary = {
        "task_total": len(tasks),
        "task_completed": len(completed_tasks),
        "task_failed": len(failures),
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
        "cache_hit_rate": cache_hit_rate,
        "domain_filtered_drop": exec_stats.get("domain_filtered_drop", 0),
        "regex_hits": exec_stats.get("regex_hits", 0),
        "score_filtered_drop": exec_stats.get("score_filtered_drop", 0),
        "timeout_count": exec_stats.get("timeout_count", 0),
        "retry_count": exec_stats.get("retry_count", 0),
        "extract_calls": exec_stats.get("extract_calls", 0),
        "tavily_extract_calls": exec_stats.get("tavily_extract_calls", 0),
        "queue_requeued": exec_stats.get("queue_requeued", 0),
        "queue_dead_letters": exec_stats.get("queue_dead_letters", 0),
        "success_by_category": success_by_cat,
        "total_by_category": total_by_cat,
    }
    _dump_json(summary, log_output)

    print("\n[Stage2 Summary]")
    print(f"  任务总数: {summary['task_total']}, 成功: {summary['task_completed']}, 失败: {summary['task_failed']}, 待人工: {len(pending_manual)}")
    if summary["proxy"]["http"] or summary["proxy"]["https"]:
        print(f"  Proxy: http={summary['proxy']['http']} https={summary['proxy']['https']}")
    print(f"  输出: {output_path}")
    print(f"  gap_monitor: {gap_monitor_path}")
    print(f"  平均耗时: {summary['avg_elapsed_ms']:.1f} ms; 缓存命中率: {summary['cache_hit_rate']*100:.1f}%")
    print(f"  过滤/兜底: 域名过滤丢弃 {summary['domain_filtered_drop']} 条；score 过滤 {summary['score_filtered_drop']} 条；regex 命中 {summary['regex_hits']} 次")
    print(f"  LLM: extract {summary['extract_calls']} 次；timeout {summary['timeout_count']} 次；retry {summary['retry_count']} 次; tavily_extract {summary['tavily_extract_calls']} 次; queue_requeued {summary.get('queue_requeued',0)} dead {summary.get('queue_dead_letters',0)}")
    if summary.get("success_by_category"):
        print(f"  分类型成功: {summary['success_by_category']} / {summary['total_by_category']}")
    if pending_manual or summary["task_failed"] > 0:
        print("  [WARN] 仍有任务未完成或需人工处理，可用 --resume-from-task-file 重试指定任务。")
    logger.info(f"[Stage2 Unified] 完成，写入 {output_path}")
    return 1 if (pending_manual or summary["task_failed"] > 0) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
