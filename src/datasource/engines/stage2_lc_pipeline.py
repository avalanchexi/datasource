#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LangChain-based pipeline for Stage2 (Tavily + DeepSeek) task execution.
Keeps output compatible with legacy Stage2: completed/failures/websearch_results.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from langchain_core.runnables import RunnableLambda

from datasource.engines.deepseek_reasoner import DeepSeekExtractionAgent


async def run_tasks_lc(
    tasks: List[Dict[str, Any]],
    market_payload: Dict[str, Any],
    tavily_client: Any,
    extractor: DeepSeekExtractionAgent,
    task_log_path,
    cache_ttl: Optional[int],
    max_retries: int,
    fund_flow_backend: str,
    forex_backend: str,
    lc_max_concurrency: int,
    deepseek_timeout: Optional[float],
    llm_hard_timeout: Optional[float],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Execute tasks using LangChain Runnable pipeline.
    """

    # 延迟导入避免循环依赖
    from scripts.stage2_unified_enhancer import (
        _validate_fund_flow_extraction,
        _validate_general_extraction,
        _update_missing_items,
        _apply_extraction,
        _augment_extraction_metadata,
        _post_writeback_manual_reason,
        _mark_post_writeback_manual_required,
        _filter_by_domain,
        _prefer_fresh_snippets,
    )

    forex_keys = {"USDCNY", "USDCNH", "DXY", "EURUSD", "GBPUSD", "USDJPY"}
    ds_semaphore = asyncio.Semaphore(max(1, lc_max_concurrency))

    def _append_task_log(record: Dict[str, Any]) -> None:
        try:
            path = Path(task_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            logger.warning("写 task_log 失败，已忽略")

    async def _search(task: Dict[str, Any]) -> Dict[str, Any]:
        # 所有任务统一 Tavily，不再跳过 MCP
        search_params = {
            "query": task.get("query") or task["indicator_key"],
            "search_depth": task.get("search_depth")
            or ("advanced" if task["stage_phase"] == "assets" else "basic"),
            "include_domains": task.get("preferred_domains") or None,
            "time_range": task.get("time_range"),
            "topic": task.get("topic"),
            "language": task.get("language"),
            "max_results": task.get("max_results"),
            "chunks_per_source": task.get("chunks_per_source"),
            "auto_parameters": task.get("auto_parameters"),
            "days": task.get("days"),
            "cache_ttl": cache_ttl,
        }
        compact_params = {k: v for k, v in search_params.items() if v is not None}
        try:
            result = await tavily_client.search(**compact_params)
        except TypeError as exc:
            # 兼容旧版 tavily SDK 不支持 days 参数的情况
            if "days" in compact_params:
                compact_params.pop("days", None)
                result = await tavily_client.search(**compact_params)
            else:
                raise exc
        snippets = result.get("results") or []
        # two-step extract for noisy tasks
        if task["indicator_key"] in {"northbound", "southbound", "etf", "margin", "USDCNY", "USDCNH", "DXY", "EURUSD", "GBPUSD", "USDJPY", "GC=F", "CL=F", "BZ=F", "HG=F", "BCOM", "GSG"}:
            try:
                top_for_extract = snippets[:3]
                if top_for_extract:
                    extract_resp = await tavily_client.extract(
                        search_results=top_for_extract,
                        extract_depth="advanced",
                        include_raw_content=task["indicator_key"] in {"northbound", "southbound", "etf", "margin"},
                        cache_ttl=cache_ttl,
                    )
                    if extract_resp.get("status") == 422:
                        logger.debug("Tavily extract 422 in LC, fallback to search-only")
                    else:
                        extra = extract_resp.get("results") or []
                        for ex in extra:
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
            except Exception as exc:
                logger.debug(f"Tavily extract skipped/failed in LC: {exc}")
        snippets = _filter_by_domain(snippets, task.get("preferred_domains"))
        snippets = _prefer_fresh_snippets(snippets, task.get("max_age_days"))
        return {"task": task, "search_result": {**result, "results": snippets}, "skipped_mcp": False}

    async def _extract(bundle: Dict[str, Any]) -> Dict[str, Any]:
        task = bundle["task"]
        snippets = (bundle.get("search_result") or {}).get("results") or []
        # score 过滤
        filtered = [s for s in snippets if s.get("score") is None or s.get("score", 0) >= 0.5]
        if filtered:
            snippets = filtered
        if not snippets:
            return {
                "task": task,
                "extraction": {
                    "value": None,
                    "unit": task.get("unit"),
                    "note": "skipped_deepseek:no_snippets",
                    "llm_error": "skipped_deepseek:no_snippets",
                    "llm_timeout": False,
                    "confidence": 0.0,
                    "llm_latency_ms": 0,
                },
                "raw_results": [],
                "search_result": bundle.get("search_result"),
            }

        async with ds_semaphore:
            start_llm = asyncio.get_event_loop().time()
            coro = extractor.extract(
                snippets,
                task["indicator_key"],
                unit_hint=task.get("unit"),
                issuer_hint=task.get("issuer"),
                request_timeout=deepseek_timeout,
            )
            llm_timeout = False
            try:
                if llm_hard_timeout and llm_hard_timeout > 0:
                    extraction = await asyncio.wait_for(coro, timeout=llm_hard_timeout)
                else:
                    extraction = await coro
            except Exception as exc:
                llm_timeout = isinstance(exc, asyncio.TimeoutError) or "Timeout" in str(exc)
                logger.debug(f"DeepSeek (LC) failed, fallback regex: {exc}")
                val, url = extractor._fallback_extract(snippets)
                extraction = {
                    "value": val,
                    "unit": task.get("unit"),
                    "note": f"deepseek_error:{exc}",
                    "llm_error": str(exc),
                    "llm_timeout": llm_timeout,
                    "source_url": url or (snippets[0].get("url") if snippets else None),
                    "confidence": 0.2 if val is not None else 0.0,
                }
            llm_latency_ms = int((asyncio.get_event_loop().time() - start_llm) * 1000)
            if extraction is None:
                extraction = {}
            extraction["llm_latency_ms"] = llm_latency_ms
            if llm_timeout:
                extraction["llm_timeout"] = True
        return {
            "task": task,
            "extraction": extraction,
            "raw_results": snippets[:3],
            "search_result": bundle.get("search_result"),
        }

    chain = RunnableLambda(_search) | RunnableLambda(_extract)

    results: List[Dict[str, Any]] = await chain.abatch(
        tasks, config={"max_concurrency": lc_max_concurrency}
    )

    completed: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    websearch_results: List[Dict[str, Any]] = []

    for res in results:
        task = res["task"]
        is_fund_flow = task["indicator_key"] in {"northbound", "southbound", "etf", "margin"}
        extraction = res.get("extraction") or {}
        search_result = res.get("search_result") or {}
        manual_required = False
        hybrid_note = ""
        raw_results = res.get("raw_results", [])

        _augment_extraction_metadata(extraction, task, raw_results)

        if is_fund_flow and (extraction.get("confidence", 0.0) < 0.5 or extraction.get("value") is None):
            manual_required = True

        if is_fund_flow:
            val_adj, unit_manual, note_append = _validate_fund_flow_extraction(extraction)
            extraction["value"] = val_adj
            combined_note = " ".join(s for s in [extraction.get("note", ""), hybrid_note, note_append] if s).strip()
            extraction["note"] = combined_note or None
            manual_required = manual_required or unit_manual
        else:
            val_adj, manual2, note_append2 = _validate_general_extraction(extraction, task, res.get("raw_results", []))
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
            "extraction_backend": "langchain",
            "confidence": extraction.get("confidence", 0.0),
            "source_url": extraction.get("source_url"),
            "note": extraction.get("note"),
            "llm_latency_ms": extraction.get("llm_latency_ms"),
            "llm_error": extraction.get("llm_error"),
            "deepseek_error": extraction.get("note")
            if isinstance(extraction.get("note"), str) and extraction["note"].startswith("deepseek_error")
            else None,
            "request_id": search_result.get("response_id") or search_result.get("request_id"),
            "http_status": search_result.get("status"),
            "cache_hit": search_result.get("cache_hit", False),
            "attempt_index": 1,
            "elapsed_ms": None,
            "created_at": task["created_at"],
            "finished_at": None,
            "manual_required": manual_required,
        }

        if manual_required:
            failures.append(task_record)
        else:
            _apply_extraction(market_payload, task, extraction)
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
            else:
                _update_missing_items(market_payload, task["indicator_key"])
                completed.append(task_record)

        _append_task_log(task_record)
        websearch_results.append(
            {
                "task": task,
                "extraction": extraction,
                "extraction_backend": "langchain",
                "raw_results": raw_results,
                "manual_required": task_record.get("manual_required"),
                "manual_reason": task_record.get("manual_reason") or extraction.get("manual_reason"),
            }
        )

    return completed, failures, websearch_results


__all__ = ["run_tasks_lc"]
