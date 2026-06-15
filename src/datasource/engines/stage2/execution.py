"""Task execution helpers for Stage2."""
from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from datasource.adapters.tavily_client import AsyncTavilyClient

try:  # pragma: no cover - optional dependency
    from datasource.adapters.exa_client import AsyncExaClient
except Exception:  # noqa: W0703
    AsyncExaClient = None  # type: ignore

try:  # pragma: no cover - structured providers are optional
    from datasource.providers.stage2_structured import StructuredProviderError
except Exception:  # noqa: W0703
    StructuredProviderError = None  # type: ignore

from datasource.engines.deepseek_reasoner import DeepSeekExtractionAgent
from datasource.engines.stage2.cli import _callable_supports_kwarg
from datasource.engines.stage2.common import _is_force_refresh_task, _safe_number
from datasource.engines.stage2.diagnostics import (
    _finalize_task_result_type,
    _finalize_websearch_result_type,
    _mark_post_writeback_manual_required,
    _post_writeback_manual_reason,
)
from datasource.engines.stage2.errors import (
    _build_environment_proxy_error_records,
    _is_environment_proxy_error,
    _is_tavily_quota_error,
    _is_tavily_quota_response,
    _structured_audit_fields_from_task,
    _tavily_error_metadata,
)
from datasource.engines.stage2.evidence import (
    _field_retry_window_evidence,
    _final_snippet_diagnostics,
    _resolve_field_retry_evidence_source,
    _selected_reason_from_diagnostics,
)
from datasource.engines.stage2.extraction_apply import (
    _apply_extraction,
    _augment_extraction_metadata,
    _default_fund_flow_metric_basis,
    _infer_fund_flow_source_tier,
    _infer_fund_flow_window_evidence,
)
from datasource.engines.stage2.query_planner import (
    _build_directed_query,
    _candidate_query_quality,
    _exa_search_type,
    _expand_query_candidates,
    _should_retry_with_directed_query,
    _start_date_from_max_age,
)
from datasource.engines.stage2.regex_extraction import (
    _extract_flow_value,
    _refine_extraction_value,
    _regex_fallback,
)
from datasource.engines.stage2.snippet_filters import (
    _filter_by_domain,
    _filter_by_official_extract_domain,
    _official_extract_domains,
    _prefer_fresh_snippets,
    _prefer_latest_report_snippets,
    _score_stats,
)
from datasource.engines.stage2.structured_runner import (
    _mark_structured_fallback_on_task,
    _record_structured_attempt,
    _record_structured_fallback,
    _record_structured_success,
    _structured_stats,
)
from datasource.engines.stage2.validation import (
    _validate_fund_flow_extraction,
    _validate_general_extraction,
)
from datasource.utils.coercion import is_stage2_number_placeholder
from datasource.utils.key_aliases import canonical_monetary_key
from datasource.utils.missing_items import remove_missing_item
from datasource.utils.note_utils import append_note_text as _append_note


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
