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
from datetime import datetime
import shutil
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from datasource.adapters.tavily_client import AsyncTavilyClient
from datasource.cache.memory_cache import MemoryCache
from datasource.cache.sqlite_cache import SQLiteCache
from datasource.engines.deepseek_reasoner import DeepSeekExtractionAgent
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
) -> (List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]):
    completed: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    websearch_results: List[Dict[str, Any]] = []
    skipped_mcp: List[Dict[str, Any]] = []
    for task in tasks:
        is_fund_flow = task["indicator_key"] in {"northbound", "southbound", "etf", "margin"}
        backend = task.get("fund_flow_backend") or fund_flow_backend
        if is_fund_flow and backend == "mcp":
            # MCP 模式：跳过搜索，直接记为待人工/外部注入
            task_record = {
                "task_id": task["task_id"],
                "indicator_key": task["indicator_key"],
                "stage_phase": task["stage_phase"],
                "search_backend": task["search_backend"],
                "fund_flow_backend": backend,
                "manual_required": True,
                "note": "backend=mcp，等待外部MCP注入",
                "attempt_index": 0,
                "elapsed_ms": 0,
                "created_at": task["created_at"],
                "finished_at": int(datetime.now().timestamp()),
            }
            failures.append(task_record)
            _append_task_log(task_log_path, task_record)
            skipped_mcp.append(task_record)
            continue
        try:
            for attempt in count(start=1):
                started = time.perf_counter()
                try:
                    hybrid_note = ""
                    # hybrid 模式预留 MCP -> Tavily 降级；当前无实际 MCP 实现
                    if is_fund_flow and backend == "hybrid":
                        hybrid_note = "MCP通道未实现，已降级 Tavily"

                    result = await client.search(
                        query=task.get("query") or task["indicator_key"],
                        search_depth="advanced" if task["stage_phase"] == "assets" else "basic",
                        include_domains=task.get("preferred_domains") or None,
                        time_range=task.get("time_range"),
                        cache_ttl=cache_ttl,
                    )
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    snippets = result.get("results") or []
                    extraction = await extractor.extract(
                        snippets,
                        task["indicator_key"],
                        unit_hint=task.get("unit"),
                        issuer_hint=task.get("issuer"),
                    )
                    # fund_flow 低置信度或无值 → manual_required
                    manual_required = False
                    if is_fund_flow and (extraction.get("confidence", 0.0) < 0.5 or extraction.get("value") is None):
                        manual_required = True
                    if is_fund_flow:
                        adjusted_value, unit_manual, note_append = _validate_fund_flow_extraction(extraction)
                        extraction["value"] = adjusted_value
                        combined_note = " ".join(
                            s for s in [extraction.get("note", ""), hybrid_note, note_append] if s
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
                        "confidence": extraction.get("confidence", 0.0),
                        "source_url": extraction.get("source_url"),
                        "note": extraction.get("note"),
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
                    else:
                        _apply_extraction(market_payload, task, extraction)
                        _update_missing_items(market_payload, task["indicator_key"])
                        completed.append(task_record)
                    _append_task_log(task_log_path, task_record)
                    websearch_results.append(
                        {
                            "task": task,
                            "extraction": extraction,
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
    return completed, failures, websearch_results


def _gap_monitor(
    pending: List[str],
    output_path: Path,
    manual_required: Optional[List[str]] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pending_tasks": pending,
        "manual_required": manual_required or [],
        "generated_at": datetime.now().isoformat(),
    }
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
    manual = False
    note_append = ""

    # unit 校验
    if unit_hint:
        unit_val = extraction.get("unit") or ""
        if unit_hint not in unit_val:
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
        if not issuer_match_flag and issuer_hint.lower() not in snippets_text:
            manual = True
            note_append = (note_append + f" 缺少发布机构({issuer_hint})").strip()

    return val, manual, note_append


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 2 Unified Enhancer (Tavily + DeepSeek)")
    parser.add_argument("--market-data", required=True, help="Stage1 生成的 market_data.json 路径")
    parser.add_argument("--output", help="增强后输出路径；默认覆盖输入")
    parser.add_argument("--phase", choices=["essential", "assets", "all"], default="all")
    parser.add_argument("--search-backend", choices=["tavily"], default="tavily")
    parser.add_argument("--fund-flow-backend", choices=["mcp", "tavily", "hybrid"], default="tavily")
    parser.add_argument("--task-file", default="reports/search_tasks_stage2.jsonl")
    parser.add_argument("--task-log", default="logs/stage_task_log.jsonl")
    parser.add_argument("--websearch-results", default="reports/websearch_results_auto.json")
    parser.add_argument("--cache-ttl", type=int, default=3600)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--cache-backend", choices=["memory", "sqlite"], default="memory")
    parser.add_argument("--cache-path", default="reports/tavily_cache.sqlite")
    parser.add_argument("--http-proxy", help="HTTP proxy, overrides env")
    parser.add_argument("--https-proxy", help="HTTPS proxy, overrides env")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--resume-from-task-file", help="使用已有任务文件，跳过重新扫描 Stage1")
    parser.add_argument("--tasks", help="仅执行指定任务（task_id 或 indicator_key，逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="仅生成任务文件，不执行搜索")
    parser.add_argument("--execute-search", action="store_true", help="立即执行 Tavily+DeepSeek 任务")
    parser.add_argument("--log-output", default="logs/stage2_unified_log.json")
    parser.add_argument("--gap-monitor", default="reports/gap_monitor.json")
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


def _ensure_keys():
    missing = []
    if not os.getenv("TAVILY_API_KEY"):
        missing.append("TAVILY_API_KEY")
    if not os.getenv("DEEPSEEK_API_KEY"):
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

    if args.resume_from_task_file:
        task_file = Path(args.resume_from_task_file)
        tasks = _load_tasks_from_file(task_file)
        logger.info(f"[Stage2] 使用已有任务文件 {task_file}")
    else:
        planner = Stage2TaskPlanner(
            stage_phase=args.phase,
            search_backend=args.search_backend,
            task_file=task_file,
            fund_flow_backend=args.fund_flow_backend,
        )
        tasks = planner.build_tasks(market_payload)
        planner.write_jsonl(tasks)

    task_ids_filter, indicators_filter = _parse_task_filter(args.tasks)
    if task_ids_filter or indicators_filter:
        tasks = _filter_tasks(tasks, task_ids_filter, indicators_filter)
        logger.info(f"[Stage2] 过滤后剩余 {len(tasks)} 条任务")

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
    extractor = DeepSeekExtractionAgent()

    completed_tasks: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    websearch_results: List[Dict[str, Any]] = []
    if args.dry_run:
        logger.info("[Stage2] Dry-run 模式：仅生成任务文件，不执行搜索")
    elif args.execute_search and tasks:
        missing_keys = _ensure_keys()
        if missing_keys:
            print(f"[ERROR] 缺少密钥: {', '.join(missing_keys)}，请在 .env 中设置并 source .env")
            return 1
        completed_tasks, failures, websearch_results = await _execute_tasks(
            tasks,
            market_payload,
            tavily,
            extractor,
            task_log_path,
            args.cache_ttl,
            max_retries=args.max_retries,
            fund_flow_backend=args.fund_flow_backend,
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
    }
    _dump_json(summary, log_output)

    print("\n[Stage2 Summary]")
    print(f"  任务总数: {summary['task_total']}, 成功: {summary['task_completed']}, 失败: {summary['task_failed']}, 待人工: {len(pending_manual)}")
    if summary["proxy"]["http"] or summary["proxy"]["https"]:
        print(f"  Proxy: http={summary['proxy']['http']} https={summary['proxy']['https']}")
    print(f"  输出: {output_path}")
    print(f"  gap_monitor: {gap_monitor_path}")
    print(f"  平均耗时: {summary['avg_elapsed_ms']:.1f} ms; 缓存命中率: {summary['cache_hit_rate']*100:.1f}%")
    if pending_manual or summary["task_failed"] > 0:
        print("  [WARN] 仍有任务未完成或需人工处理，可用 --resume-from-task-file 重试指定任务。")
    logger.info(f"[Stage2 Unified] 完成，写入 {output_path}")
    return 1 if (pending_manual or summary["task_failed"] > 0) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
