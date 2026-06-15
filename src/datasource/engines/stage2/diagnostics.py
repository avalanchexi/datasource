"""Diagnostics and summary helpers for Stage2."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from datasource.engines.stage2.common import _entry_for_task, _safe_number
from datasource.utils.missing_items import append_missing_item
from datasource.utils.note_utils import append_note_text as _append_note
from datasource.utils.policy_rules import is_estimated_allowlisted


def _missing_required_output_fields(entry: Dict[str, Any], fields: List[str]) -> List[str]:  # noqa: E501
    missing: List[str] = []
    numeric_fields = {
        "current_value",
        "previous_value",
        "change_rate",
        "change_from_120d",
        "recent_5d",
        "total_120d",
        "current_yield",
        "current_rate",
        "daily_change",
        "change_120d",
        "change_5d_bp",
        "change_120d_bp",
    }
    for field in fields:
        value = entry.get(field)
        if field in numeric_fields:
            if _safe_number(value) is None:
                missing.append(field)
            continue
        if value in (None, "", "N/A"):
            missing.append(field)
    return missing


def _post_writeback_manual_reason(
    market_payload: Dict[str, Any],
    task_or_indicator: Any,
    indicator_key: Optional[str] = None,
) -> Optional[str]:
    if isinstance(task_or_indicator, dict):
        task = task_or_indicator
        indicator = str(indicator_key or task.get("indicator_key") or "")
    else:
        task = {"indicator_key": str(task_or_indicator or "")}
        indicator = str(indicator_key or task_or_indicator or "")

    category, entry = _entry_for_task(market_payload, task, indicator)
    if category == "forex" and isinstance(entry, dict):
        pending = entry.get("compare_fields_pending")
        if isinstance(pending, list):
            pending_fields = [str(field) for field in pending if str(field)]
        elif pending:
            pending_fields = [str(pending)]
        else:
            pending_fields = []
        if pending_fields:
            task["post_writeback_missing_fields"] = pending_fields
            return "missing_compare_values"

    if (
        task.get("quality_gap_reason") == "missing_compare_values"
        and isinstance(entry, dict)
    ):
        required_fields = list(task.get("required_output_fields") or [])
        missing_fields = _missing_required_output_fields(entry, required_fields)  # noqa: E501
        if missing_fields:
            task["post_writeback_missing_fields"] = missing_fields
            return "missing_compare_values"

    fund_flow = market_payload.get("fund_flow", {})
    if indicator not in fund_flow:
        return None
    entry = fund_flow.get(indicator)
    if not isinstance(entry, dict) or entry.get("is_estimated") is not True:
        return None
    allowed, _reasons = is_estimated_allowlisted("fund_flow", indicator, entry)
    if allowed:
        return None
    return "estimated_not_allowed"


def _post_writeback_missing_category(
    market_payload: Dict[str, Any],
    task: Dict[str, Any],
    task_record: Dict[str, Any],
    indicator_key: str,
) -> str:
    category = (
        task.get("quality_gap_category")
        or task.get("category")
        or task_record.get("category")
    )
    if category in {None, "", "assets", "essential", "all"}:
        category, _entry = _entry_for_task(market_payload, task, indicator_key)
    if category in {None, ""}:
        return "fund_flow"
    return str(category)


def _mark_post_writeback_manual_required(
    market_payload: Dict[str, Any],
    task_record: Dict[str, Any],
    task: Dict[str, Any],
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
    category = _post_writeback_missing_category(market_payload, task, task_record, indicator_key)  # noqa: E501
    append_missing_item(market_payload, category, indicator_key, reason)


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
        usable_count = int(_nested_row_value(row, "usable_count_before_extract") or 0)  # noqa: E501
        manual_required = bool(_nested_row_value(row, "manual_required"))
        if usable_count > 0:
            retrieval_hit += 1
            if manual_required:
                extract_failed += 1
        if bool(_nested_row_value(row, "write_back_success")) or (
            not manual_required and _nested_row_value(row, "result_type") == "search_success"  # noqa: E501
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
        "extract_success_rate": (retrieval_hit - extract_failed) / retrieval_hit if retrieval_hit else 0.0,  # noqa: E501
        "writeback_success_count": writeback_success,
        "writeback_success_rate": writeback_success / total if total else 0.0,
        "manual_reason_breakdown": reason_counts,
    }


def _manual_failure_layer(row: Dict[str, Any]) -> str:
    structured_reason = _nested_row_value(row, "structured_provider_fallback_reason")  # noqa: E501
    manual_reason = str(_nested_row_value(row, "manual_reason") or "")
    usable_count = int(_nested_row_value(row, "usable_count_before_extract") or 0)  # noqa: E501
    write_back_success = bool(_nested_row_value(row, "write_back_success"))

    if (
        structured_reason == "policy_gate_blocked"
        or "fund_flow_window_missing" in manual_reason
        or "estimated_not_allowed" in manual_reason
    ):
        return "policy_gate"
    if structured_reason:
        return "structured_provider"
    if usable_count <= 0:
        return "retrieval"
    if write_back_success is False and _nested_row_value(row, "result_type") == "manual_required":  # noqa: E501
        return "extraction"
    return "extraction"


def _build_manual_required_details(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:  # noqa: E501
    details: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in rows:
        if not bool(_nested_row_value(row, "manual_required")):
            continue
        key = (
            _nested_row_value(row, "indicator_key")
            or _nested_row_value(row, "task.indicator_key")
            or _nested_row_value(row, "task_indicator_key")
            or "unknown"
        )
        key_text = str(key)
        if key_text in seen_keys:
            continue
        seen_keys.add(key_text)
        details.append(
            {
                "key": key_text,
                "failure_layer": _manual_failure_layer(row),
                "reason": str(
                    _nested_row_value(row, "manual_reason")
                    or _nested_row_value(row, "extraction.manual_reason")
                    or _nested_row_value(row, "extraction_skipped_reason")
                    or _nested_row_value(row, "extract_skipped_reason")
                    or "manual_required"
                ),
                "structured_provider_fallback_reason": _nested_row_value(
                    row,
                    "structured_provider_fallback_reason",
                ),
                "usable_count_before_extract": int(
                    _nested_row_value(row, "usable_count_before_extract") or 0
                ),
                "result_type": str(_nested_row_value(row, "result_type") or "manual_required"),  # noqa: E501
            }
        )
    return details


def _has_diagnostic_value(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _merge_nested_diagnostic_dict(existing: Any, incoming: Dict[str, Any]) -> Dict[str, Any]:  # noqa: E501
    merged = dict(existing) if isinstance(existing, dict) else {}
    for key, value in incoming.items():
        if _has_diagnostic_value(value) or key not in merged:
            merged[key] = value
    return merged


def _merge_diagnostic_row(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:  # noqa: E501
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
                rows[existing_index] = _merge_diagnostic_row(rows[existing_index], row)  # noqa: E501
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


def _stage2_effective_hit_rate(success_count: int, failure_count: int) -> float:  # noqa: E501
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
        search_success_count / search_denominator if search_denominator else 0.0  # noqa: E501
    )
    stage2_effective_success = search_success_count + structured_success_count
    stage2_effective_failure = search_failed_count
    stage2_effective_denominator = stage2_effective_success + stage2_effective_failure  # noqa: E501
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
        1 for task in completed_tasks if task.get("result_type") == "skipped_existing"  # noqa: E501
    )
    search_success_count = sum(
        1 for task in completed_tasks if task.get("result_type") == "search_success"  # noqa: E501
    )
    structured_success_count = sum(
        1 for task in completed_tasks if task.get("result_type") == "structured_success"  # noqa: E501
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


def _format_stage2_task_count_line(
    summary: Dict[str, Any],
    *,
    pending_manual_count: int,
) -> str:
    return (
        f"  任务总数: {summary['task_total']}, legacy完成: {summary['task_completed']}, "  # noqa: E501
        f"Stage2有效成功: {summary['stage2_effective_success']}, "
        f"结构化源成功: {summary['task_structured_success']}, "
        f"搜索链路成功: {summary['task_search_success']}, "
        f"搜索失败: {summary['task_search_failed']}, "
        f"跳过已有值: {summary['task_skipped_existing']}, 待人工: {pending_manual_count}"  # noqa: E501
    )


def _format_stage2_hit_rate_line(summary: Dict[str, Any]) -> str:
    effective_success = summary["stage2_effective_success"]
    effective_denominator = summary["stage2_effective_denominator"]
    search_success = summary["task_search_success"]
    search_denominator = summary["task_search_success"] + summary["task_search_failed"]  # noqa: E501
    return (
        f"  Stage2有效命中率: {summary['stage2_effective_hit_rate'] * 100:.1f}% "
        f"({effective_success}/{effective_denominator}); "
        f"搜索链路命中率: {summary['search_success_rate_incremental'] * 100:.1f}% "
        f"({search_success}/{search_denominator})"
    )


def _structured_provider_summary_fields(exec_stats: Dict[str, Any]) -> Dict[str, Any]:  # noqa: E501
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
        "structured_provider_latency_ms_by_provider": dict(latency_by_provider),  # noqa: E501
    }


def _build_stage2_summary_diagnostics(
    completed_tasks: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
    websearch_results: List[Dict[str, Any]],
    exec_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    exec_stats = exec_stats or {}
    diagnostic_rows = _diagnostic_rows_for_summary(completed_tasks, failures, websearch_results)  # noqa: E501
    retrieval_diagnostics = _build_retrieval_diagnostics(diagnostic_rows)
    payload = {
        "retrieval_diagnostics": retrieval_diagnostics,
        "manual_reason_breakdown": retrieval_diagnostics.get("manual_reason_breakdown", {}),  # noqa: E501
        "manual_required_details": _build_manual_required_details(diagnostic_rows),  # noqa: E501
        "deepseek_circuit_breaker_triggered": bool(
            exec_stats.get("deepseek_circuit_breaker_triggered", False)
        ),
        "deepseek_circuit_breaker_reason": exec_stats.get("deepseek_circuit_breaker_reason"),  # noqa: E501
        "deepseek_timeout_rate": exec_stats.get("deepseek_timeout_rate", 0.0),
        "deepseek_breaker_attempts": exec_stats.get("deepseek_breaker_attempts", 0),  # noqa: E501
        "deepseek_breaker_timeouts": exec_stats.get("deepseek_breaker_timeouts", 0),  # noqa: E501
    }
    payload.update(_structured_provider_summary_fields(exec_stats))
    unavailable_reason = exec_stats.get("tavily_unavailable_reason")
    if unavailable_reason:
        payload["tavily_unavailable_reason"] = unavailable_reason
    for key in _STAGE2_BACKEND_SUMMARY_KEYS:
        if key in exec_stats:
            payload[key] = exec_stats[key]
    return payload
