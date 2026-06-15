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
from datasource.engines.stage2.execution import (  # noqa: F401 (C3 re-export)
    _DeepSeekCircuitBreaker,
    _append_task_log,
    _execute_tasks,
    _has_non_placeholder_value,
    _is_deepseek_timeout,
    _is_placeholder_number,
    _mark_stale_refresh_failure,
    _try_structured_provider,
    _update_missing_items,
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





def _dump_json(payload: Dict[str, Any], path: Path, backup: bool = False) -> None:
    dump_json(payload, path, backup=backup)

















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
