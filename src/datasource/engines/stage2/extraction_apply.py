"""Extraction writeback helpers for Stage2."""
from __future__ import annotations

from datetime import datetime
from functools import partial
from typing import Any, Dict, Iterable, List, Optional

from datasource.engines.stage2.common import (
    _BOND_UPSERT_META,
    _COMMODITY_UPSERT_META,
    _FOREX_UPSERT_META,
    _is_force_refresh_task,
    _safe_number,
)
from datasource.engines.stage2.evidence import (
    _field_retry_window_evidence,
    _snippets_for_source_url,
    _source_label_for_task,
)
from datasource.engines.stage2.regex_extraction import _infer_rrr_type
from datasource.engines.stage2.snippet_filters import _extract_report_month, _parse_date_str  # noqa: E501
from datasource.utils.forex_evidence import (
    FOREX_COMPARE_FIELDS,
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
from datasource.utils.key_aliases import canonical_monetary_key
from datasource.utils.policy_rules import is_estimated_allowlisted
from datasource.utils.source_trust import should_mark_official_non_estimated
from datasource.utils.text_markers import contains_ytd_marker

try:
    # C4-cleanup: move shared fund_flow gate helpers out of scripts/stage2_5_injector.py.  # noqa: E501
    from scripts.stage2_5_injector import (
        _default_fund_flow_metric_basis,
        _infer_fund_flow_source_tier,
        _infer_fund_flow_window_evidence,
        _normalize_fund_flow_estimation,
    )
except ImportError:  # pragma: no cover - direct script execution keeps scripts/ on sys.path  # noqa: E501
    # C4-cleanup: keep the existing direct-execution fallback until the shared module exists.  # noqa: E501
    from stage2_5_injector import (  # type: ignore
        _default_fund_flow_metric_basis,
        _infer_fund_flow_source_tier,
        _infer_fund_flow_window_evidence,
        _normalize_fund_flow_estimation,
    )


_contains_ytd_marker = contains_ytd_marker


def _infer_report_period(text: str) -> Optional[str]:
    rep = _extract_report_month(text)
    if not rep:
        return None
    year, month = rep
    return f"{year}-{month:02d}"


def _infer_as_of_date(snippets: Optional[List[Dict[str, Any]]]) -> Optional[str]:  # noqa: E501
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
            parsed = _parse_date_str(snip.get("content") or snip.get("snippet") or "")  # noqa: E501
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
        if not extraction.get("unit") and any(token in text for token in ("亿元", "亿港元", "亿")):  # noqa: E501
            extraction["unit"] = "亿元"
        metric_basis = _default_fund_flow_metric_basis(str(indicator_key), extraction)  # noqa: E501
        extraction.setdefault("metric_basis", metric_basis)
        is_structured_provider_task = (
            task.get("extraction_backend") == "structured"
            or task.get("search_backend") == "structured"
        )
        explicit_window_evidence = str(extraction.get("window_evidence") or "").strip().lower()  # noqa: E501
        recent_value = _safe_number(extraction.get("recent_5d"))
        total_value = _safe_number(extraction.get("total_120d"))
        if _safe_number(extraction.get("value")) is None and recent_value is not None:  # noqa: E501
            extraction["value"] = recent_value
        source_snippets = _snippets_for_source_url(snippets, extraction.get("source_url"))  # noqa: E501
        direct_evidence = {"direct_window", "direct_daily_series", "direct_balance_delta"}  # noqa: E501
        field_retry_evidence = extraction.setdefault("field_retry_evidence", {})  # noqa: E501
        if not isinstance(field_retry_evidence, dict):
            field_retry_evidence = {}
            extraction["field_retry_evidence"] = field_retry_evidence
        recent_evidence = None
        total_evidence = None
        if recent_value is not None:
            if is_structured_provider_task and explicit_window_evidence in direct_evidence:  # noqa: E501
                recent_evidence = explicit_window_evidence
            else:
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
            if is_structured_provider_task and explicit_window_evidence in direct_evidence:  # noqa: E501
                total_evidence = explicit_window_evidence
            else:
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
        if (
            is_structured_provider_task
            and explicit_window_evidence in direct_evidence
            and recent_value is not None
            and total_value is not None
        ):
            extraction["window_evidence"] = explicit_window_evidence
        elif recent_value is not None and total_value is not None:
            if (
                str(indicator_key) == "margin"
                and recent_evidence == "direct_balance_delta"
                and total_evidence == "direct_balance_delta"
            ):
                extraction["window_evidence"] = "direct_balance_delta"
            elif recent_evidence in direct_evidence and total_evidence in direct_evidence:  # noqa: E501
                extraction["window_evidence"] = "direct_window"
            else:
                extraction["window_evidence"] = "unknown"
    as_of_date = _infer_as_of_date(snippets)
    if as_of_date:
        extraction.setdefault("as_of_date", as_of_date)


_join_forex_compare_evidence_text = join_forex_compare_evidence_text
_normalize_forex_compare_text = normalize_forex_compare_text
_has_forex_positive_compare_text = has_stage2_forex_positive_compare_text
_has_forex_no_change_evidence = has_stage2_forex_no_change_evidence
_is_forex_no_change_absence_text = is_stage2_forex_no_change_absence_text
_is_forex_absence_text = is_stage2_forex_absence_text
_is_forex_compare_absence_text = is_stage2_forex_compare_absence_text
_is_valid_forex_compare_source_url = partial(
    is_valid_forex_source_url,
    is_absence=_is_forex_absence_text,
)
_is_valid_forex_compare_base_date = partial(
    is_valid_forex_base_date,
    is_absence=_is_forex_absence_text,
)
_is_valid_forex_compare_base_price = partial(
    is_valid_forex_base_price,
    is_absence=_is_forex_absence_text,
    coerce=_safe_number,
)
_has_forex_computed_marker = partial(
    has_forex_computed_marker,
    is_absence=_is_forex_absence_text,
)
_has_forex_field_specific_evidence = partial(
    has_stage2_forex_field_specific_evidence,
    coerce=_safe_number,
)
_has_forex_structured_compare_evidence = has_stage2_forex_structured_compare_evidence  # noqa: E501
_has_negative_forex_compare_marker = has_stage2_negative_forex_compare_marker
_has_forex_compare_evidence = partial(
    has_stage2_forex_compare_evidence,
    coerce=_safe_number,
)


def _scrub_unevidenced_forex_zeroes(
    entry: Dict[str, Any],
    extraction: Dict[str, Any],
    existing_entry: Optional[Dict[str, Any]] = None,
) -> None:
    pending = entry.get("compare_fields_pending")
    if isinstance(pending, list):
        pending_fields = list(pending)
    elif pending:
        pending_fields = [pending]
    else:
        pending_fields = []

    for field in FOREX_COMPARE_FIELDS:
        if _safe_number(entry.get(field)) != 0.0:
            continue
        if _has_forex_compare_evidence(extraction, field, existing_entry or entry):  # noqa: E501
            if field in pending_fields:
                pending_fields = [pending_field for pending_field in pending_fields if pending_field != field]  # noqa: E501
            continue
        entry.pop(field, None)
        if field not in pending_fields:
            pending_fields.append(field)

    if pending_fields:
        entry["compare_fields_pending"] = pending_fields
    else:
        entry.pop("compare_fields_pending", None)


def _copy_forex_compare_fields(entry: Dict[str, Any], extraction: Dict[str, Any]) -> None:  # noqa: E501
    pending = entry.get("compare_fields_pending")
    if isinstance(pending, list):
        pending_fields = list(pending)
    elif pending:
        pending_fields = [pending]
    else:
        pending_fields = []

    changed_pending = False
    for field in FOREX_COMPARE_FIELDS:
        if field not in extraction:
            continue
        parsed_value = _safe_number(extraction.get(field))
        if parsed_value is None:
            continue
        entry[field] = parsed_value
        if field in pending_fields:
            pending_fields = [pending_field for pending_field in pending_fields if pending_field != field]  # noqa: E501
            changed_pending = True

    if changed_pending:
        if pending_fields:
            entry["compare_fields_pending"] = pending_fields
        else:
            entry.pop("compare_fields_pending", None)


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
            if _period_matches_expected(report_period) or _period_matches_expected(as_of_date):  # noqa: E501
                entry["is_stale"] = False
                entry["stale_reason"] = None
        elif not entry.get("date"):
            entry["date"] = as_of_date or report_period or entry.get("date") or ""  # noqa: E501

    def _write_common_fields(entry: Dict[str, Any], value_key: str) -> None:
        entry[value_key] = value
        entry["source"] = source_label
        entry["stage_task_id"] = task["task_id"]
        entry["note"] = note
        if source_url:
            entry["source_url"] = source_url
        for field in ("is_estimated", "estimation_method", "metric_basis", "estimation_basis", "confidence"):  # noqa: E501
            if field in extraction and extraction.get(field) is not None:
                entry[field] = extraction.get(field)

    def _copy_non_null(
        entry: Dict[str, Any],
        field: str,
        source_field: Optional[str] = None,
        numeric: bool = False,
    ) -> None:
        field_value = extraction.get(source_field or field)
        if field_value is None:
            return
        if numeric:
            parsed_value = _safe_number(field_value)
            if parsed_value is None:
                return
            entry[field] = parsed_value
            return
        entry[field] = field_value

    def _has_explicit_120d_change_basis() -> bool:
        basis_text = " ".join(
            str(extraction.get(field) or "")
            for field in ("change_period", "metric_basis")
        ).lower()
        if any(token in basis_text for token in ("120d", "120日", "120-day")):
            return True
        note_text = str(extraction.get("note") or "").lower()
        return (
            "change_from_120d" in note_text
            and any(token in note_text for token in ("120d", "120日", "120-day"))  # noqa: E501
        )

    def _mark_official_non_estimated(entry: Dict[str, Any], category: str) -> None:  # noqa: E501
        evidence_snippets = snippets if snippets is not None else extraction.get("snippets") or task.get("snippets") or []  # noqa: E501
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
        for field in ("previous_value", "change_rate", "yoy_month", "yoy_ytd"):
            _copy_non_null(entry, field, numeric=True)
        _copy_non_null(entry, "value_type")
        if str(indicator_key).lower() == "bdi":
            allowed, reasons = is_estimated_allowlisted("macro_indicators", indicator_key, entry)  # noqa: E501
            if allowed:
                entry["is_estimated"] = False
            elif reasons:
                marker = "estimated_keep:" + "|".join(reasons)
                entry["note"] = ((entry.get("note") or "") + " " + marker).strip()  # noqa: E501
        _mark_official_non_estimated(entry, "macro_indicators")
        return "macro_indicators"

    monetary = market_payload.setdefault("monetary_policy", {})
    monetary_key = canonical_monetary_key(indicator_key)
    if monetary_key in monetary:
        entry = monetary[monetary_key]
        _write_common_fields(entry, "current_value")
        _write_period_fields(entry)
        _copy_non_null(entry, "change_from_120d", numeric=True)
        if extraction.get("change_from_120d") is None and _has_explicit_120d_change_basis():  # noqa: E501
            _copy_non_null(entry, "change_from_120d", "change_rate", numeric=True)  # noqa: E501
        _copy_non_null(entry, "rrr_type")
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
            flow["current_date"] = as_of_date or report_period or market_payload.get("metadata", {}).get("date", "")  # noqa: E501
        else:
            flow["current_value"] = _safe_number(extraction.get("current_value")) or _safe_number(value)  # noqa: E501
            flow["current_date"] = as_of_date or report_period or market_payload.get("metadata", {}).get("date", "")  # noqa: E501
            point_note = "single_point_only"
            note = f"{note} {point_note}".strip() if note else point_note
        flow["source"] = source_label
        flow["stage_task_id"] = task["task_id"]
        flow["note"] = note
        if source_url:
            flow["source_url"] = source_url
        if isinstance(extraction.get("field_retry_evidence"), dict):
            flow["field_retry_evidence"] = extraction["field_retry_evidence"]
        metric_basis = _default_fund_flow_metric_basis(indicator_key, extraction)  # noqa: E501
        flow["metric_basis"] = metric_basis
        flow["source_tier"] = _infer_fund_flow_source_tier(extraction)
        flow["window_evidence"] = _infer_fund_flow_window_evidence(indicator_key, extraction, metric_basis)  # noqa: E501
        _normalize_fund_flow_estimation(flow, extraction)
        return "fund_flow"

    # forex 回写（按 pair/symbol 匹配）
    for item in market_payload.get("forex", []):
        if not isinstance(item, dict):
            continue
        if item.get("pair") == indicator_key or item.get("symbol") == indicator_key:  # noqa: E501
            existing_item = dict(item)
            _write_common_fields(item, "current_rate")
            _copy_forex_compare_fields(item, extraction)
            _scrub_unevidenced_forex_zeroes(item, extraction, existing_item)
            if not item.get("date"):
                item["date"] = as_of_date or report_period or item.get("date") or ""  # noqa: E501
            return "forex"

    # commodities 回写（按 symbol 匹配）
    for item in market_payload.get("commodities", []):
        if not isinstance(item, dict):
            continue
        if item.get("symbol") == indicator_key:
            _write_common_fields(item, "current_price")
            if not item.get("date"):
                item["date"] = as_of_date or report_period or item.get("date") or ""  # noqa: E501
            return "commodities"

    # bonds 回写（按 symbol 匹配）
    for item in market_payload.get("bonds", []):
        if not isinstance(item, dict):
            continue
        if item.get("symbol") == indicator_key:
            _write_common_fields(item, "current_yield")
            for field in ("change_5d_bp", "change_120d_bp"):
                _copy_non_null(item, field, numeric=True)
            if report_period and not item.get("report_period"):
                item["report_period"] = report_period
            if as_of_date and not item.get("as_of_date"):
                item["as_of_date"] = as_of_date
            if not item.get("date"):
                item["date"] = as_of_date or report_period or item.get("date") or ""  # noqa: E501
            return "bonds"

    if indicator_key in _FOREX_UPSERT_META:
        entry = {
            "pair": indicator_key,
            "name": _FOREX_UPSERT_META[indicator_key],
            "current_rate": value,
            "trend": "待校验",
            "source": source_label,
            "stage_task_id": task["task_id"],
            "note": (f"{note} stage2_auto_upsert" if note else "stage2_auto_upsert"),  # noqa: E501
        }
        _copy_forex_compare_fields(entry, extraction)
        _scrub_unevidenced_forex_zeroes(entry, extraction)
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
            "note": (f"{note} stage2_auto_upsert" if note else "stage2_auto_upsert"),  # noqa: E501
        }
        market_payload.setdefault("commodities", []).append(entry)
        return "commodities_upsert"

    if indicator_key in _BOND_UPSERT_META:
        entry = {
            "symbol": indicator_key,
            "name": _BOND_UPSERT_META[indicator_key],
            "current_yield": value,
            "change_5d_bp": _safe_number(extraction.get("change_5d_bp")),
            "change_120d_bp": _safe_number(extraction.get("change_120d_bp")),
            "trend": "待校验",
            "source": source_label,
            "is_estimated": extraction.get("is_estimated") is True,
            "estimation_method": extraction.get("estimation_method"),
            "metric_basis": extraction.get("metric_basis"),
            "estimation_basis": extraction.get("estimation_basis"),
            "confidence": extraction.get("confidence"),
            "stage_task_id": task["task_id"],
            "note": (f"{note} stage2_auto_upsert" if note else "stage2_auto_upsert"),  # noqa: E501
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
