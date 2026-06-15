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
from functools import partial
from itertools import count
from datetime import datetime, timedelta, timezone
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from loguru import logger
from datasource.engines.stage2.errors import (  # noqa: F401 (C1 re-export)
    _TAVILY_LIMIT_STATUSES,
    _TAVILY_ERROR_TEXT_LIMIT,
    _TAVILY_REQUEST_ID_HEADERS,
    _coerce_http_status,
    _safe_header_value,
    _sanitize_tavily_error_text,
    _tavily_error_metadata,
    _is_tavily_quota_error,
    _text_indicates_quota_or_rate_limit,
    _is_tavily_quota_response,
    _is_environment_proxy_error,
    _build_environment_proxy_error_records,
    _structured_audit_fields_from_task,
)
from datasource.engines.stage2.snippet_filters import (  # noqa: F401 (C1 re-export)
    _REPORT_MONTH_KEYS,
    _parse_date_str,
    _extract_dates,
    _is_stale,
    _prefer_fresh_snippets,
    _extract_report_month,
    _prefer_latest_report_snippets,
    _percentile,
    _score_stats,
    _filter_by_domain,
    _official_extract_domains,
    _host_matches_official_domain,
    _filter_by_official_extract_domain,
    _snippet_blob,
    _filter_by_keyword_rules,
    _snippets_have_issuer,
    _snippets_have_expected_period,
    _strict_indicator_tokens,
)
from datasource.engines.stage2.regex_extraction import (  # noqa: F401 (C1 re-export)
    _regex_fallback,
    _collect_snippet_text,
    _find_number_by_patterns,
    _extract_structured_value,
    _extract_flow_value,
    _refine_extraction_value,
    _infer_rrr_type,
)
from datasource.engines.stage2.evidence import (  # noqa: F401 (C1 re-export)
    _pattern_hits,
    _usage_evidence_score,
    _value_evidence_score,
    _final_snippet_diagnostics,
    _selected_reason_from_diagnostics,
    _first_snippet_url,
    _normalize_url_for_evidence,
    _snippets_for_source_url,
    _snippet_text,
    _snippet_contains_number,
    _resolve_field_retry_evidence_source,
    _field_retry_window_evidence,
    _source_label_for_task,
)
from datasource.engines.stage2.common import (  # noqa: F401 (C2 re-export)
    _safe_number,
    _RANGE_RULES,
    _FOREX_UPSERT_META,
    _COMMODITY_UPSERT_META,
    _BOND_UPSERT_META,
    _is_force_refresh_task,
    _entry_for_task,
)
from datasource.engines.stage2.cli import (  # noqa: F401 (C2 re-export)
    _env_int_default,
    _env_float_default,
    _parse_args,
    _should_enable_exa_fallback,
    _should_initialize_exa_client,
    _build_structured_registry_for_args,
    _is_exa_sdk_available,
    _load_tasks_from_file,
    _ensure_keys,
    _callable_supports_kwarg,
    _select_proxy_for_url,
    _validate_proxies,
    _parse_task_filter,
)
from datasource.engines.stage2.query_planner import (  # noqa: F401 (C2 re-export)
    _candidate_query_quality,
    _exa_search_type,
    _start_date_from_max_age,
    _dedupe_candidate_queries,
    _expand_query_candidates,
    _build_directed_query,
    _should_retry_with_directed_query,
)
from datasource.engines.stage2.structured_runner import (  # noqa: F401 (C2 re-export)
    _structured_stats,
    _structured_key_stats,
    _record_structured_attempt,
    _record_structured_latency_by_provider,
    _record_structured_success,
    _record_structured_fallback,
    _mark_structured_fallback_on_task,
)
from datasource.engines.stage2.diagnostics import (  # noqa: F401 (C2 re-export)
    _missing_required_output_fields,
    _post_writeback_manual_reason,
    _post_writeback_missing_category,
    _mark_post_writeback_manual_required,
    _finalize_task_result_type,
    _finalize_websearch_result_type,
    _nested_row_value,
    _build_retrieval_diagnostics,
    _manual_failure_layer,
    _build_manual_required_details,
    _has_diagnostic_value,
    _merge_nested_diagnostic_dict,
    _merge_diagnostic_row,
    _diagnostic_rows_for_summary,
    _STAGE2_BACKEND_SUMMARY_KEYS,
    _stage2_effective_hit_rate,
    _stage2_summary_metric_fields,
    _build_stage2_result_count_fields,
    _format_stage2_task_count_line,
    _format_stage2_hit_rate_line,
    _structured_provider_summary_fields,
    _build_stage2_summary_diagnostics,
)
from datasource.engines.stage2.validation import (  # noqa: F401 (C2 re-export)
    _FUND_FLOW_BOUNDS,
    _detect_fund_flow_suspicious_reason,
    _flag_fund_flow_anomalies,
    _validate_fund_flow_extraction,
    _validate_general_extraction,
)
from datasource.engines.stage2.extraction_apply import (  # noqa: F401 (C2 re-export)
    _contains_ytd_marker,
    _infer_report_period,
    _infer_as_of_date,
    _augment_extraction_metadata,
    _join_forex_compare_evidence_text,
    _normalize_forex_compare_text,
    _has_forex_positive_compare_text,
    _has_forex_no_change_evidence,
    _is_forex_no_change_absence_text,
    _is_forex_absence_text,
    _is_forex_compare_absence_text,
    _is_valid_forex_compare_source_url,
    _is_valid_forex_compare_base_date,
    _is_valid_forex_compare_base_price,
    _has_forex_computed_marker,
    _has_forex_field_specific_evidence,
    _has_forex_structured_compare_evidence,
    _has_negative_forex_compare_marker,
    _has_forex_compare_evidence,
    _scrub_unevidenced_forex_zeroes,
    _copy_forex_compare_fields,
    _apply_extraction,
)
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
from datasource.utils.source_trust import should_mark_official_non_estimated
from datasource.utils.text_markers import contains_ytd_marker
from datasource.utils.forex_evidence import (
    FOREX_COMPARE_FIELDS,
    FOREX_COMPARE_EVIDENCE_TOKENS as _FOREX_COMPARE_EVIDENCE_TOKENS,
    FOREX_COMPARE_FIELD_EVIDENCE_KEYS as _FOREX_COMPARE_FIELD_EVIDENCE_KEYS,
    FOREX_COMPARE_TEXT_FIELDS as _FOREX_COMPARE_TEXT_FIELDS,
    STAGE2_FOREX_DAILY_EVIDENCE_MARKERS as _FOREX_DAILY_EVIDENCE_MARKERS,
    STAGE2_FOREX_120D_EVIDENCE_MARKERS as _FOREX_120D_EVIDENCE_MARKERS,
    has_forex_computed_marker,
    has_stage2_forex_compare_evidence,
    has_stage2_forex_field_specific_evidence,
    has_stage2_forex_no_change_evidence,
    has_stage2_forex_positive_compare_text,
    has_stage2_forex_structured_compare_evidence,
    has_stage2_negative_forex_compare_marker,
    is_stage2_forex_absence_text,
    is_stage2_forex_compare_absence_text,
    is_stage2_forex_no_change_absence_text,
    is_valid_forex_base_date,
    is_valid_forex_base_price,
    is_valid_forex_source_url,
    join_forex_compare_evidence_text,
    normalize_forex_compare_text,
)
from datasource.utils.note_utils import append_note_text as _append_note
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
    post_writeback_reason = _post_writeback_manual_reason(market_payload, task_for_log, indicator_key)
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
                extract_kwargs = {
                    "unit_hint": task.get("unit"),
                    "issuer_hint": task.get("issuer"),
                    "request_timeout": deepseek_timeout,
                }
                if (
                    task.get("required_output_fields")
                    and _callable_supports_kwarg(extractor.extract, "required_output_fields")
                ):
                    extract_kwargs["required_output_fields"] = task.get("required_output_fields")
                if task["indicator_key"] in serial_keys:
                    result = await _run_with_timeout(
                        extractor.extract(
                            snips,
                            task["indicator_key"],
                            **extract_kwargs,
                        )
                    )
                else:
                    async with ds_semaphore:
                        result = await _run_with_timeout(
                            extractor.extract(
                                snips,
                                task["indicator_key"],
                                **extract_kwargs,
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
                    post_writeback_reason = _post_writeback_manual_reason(market_payload, task, task["indicator_key"])
                    if post_writeback_reason:
                        _mark_post_writeback_manual_required(
                            market_payload,
                            task_record,
                            task,
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
                            post_writeback_reason = _post_writeback_manual_reason(
                                market_payload,
                                task_for_log,
                                task["indicator_key"],
                            )
                            if post_writeback_reason:
                                _mark_post_writeback_manual_required(
                                    market_payload,
                                    task_record,
                                    task_for_log,
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
    result_count_fields = _build_stage2_result_count_fields(completed_tasks, failures)
    stale_refresh_forced = sum(1 for t in tasks if _is_force_refresh_task(t))
    stale_refresh_success = sum(1 for t in completed_tasks if t.get("force_refresh") and t.get("result_type") == "search_success")
    stale_refresh_failed = sum(1 for t in failures if t.get("force_refresh"))
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
        **result_count_fields,
        "task_stale_refresh_forced": stale_refresh_forced,
        "task_stale_refresh_success": stale_refresh_success,
        "task_stale_refresh_failed": stale_refresh_failed,
        "retrieval_diagnostics": summary_diagnostics["retrieval_diagnostics"],
        "manual_reason_breakdown": summary_diagnostics["manual_reason_breakdown"],
        "manual_required_details": summary_diagnostics["manual_required_details"],
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
    print(_format_stage2_hit_rate_line(summary))
    print(_format_stage2_task_count_line(summary, pending_manual_count=len(pending_manual)))
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
        print(f"  分类型搜索链路成功: {summary.get('search_success_by_category', {})} / {summary['total_by_category']}")
    print(
        f"  stale强制刷新 {summary['task_stale_refresh_forced']} 项 "
        f"(成功 {summary['task_stale_refresh_success']}, 失败 {summary['task_stale_refresh_failed']})"
    )
    if pending_manual or summary["task_failed"] > 0:
        print("  [WARN] 仍有任务未完成或需人工处理，可用 --resume-from-task-file 重试指定任务。")
    logger.info(f"[Stage2 Unified] 完成，写入 {output_path}")
    return 1 if (pending_manual or summary["task_failed"] > 0) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
