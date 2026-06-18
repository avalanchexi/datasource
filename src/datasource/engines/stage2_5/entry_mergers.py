from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from datasource.models.market_data_contract import FundFlowData
from datasource.utils.note_utils import append_note_to_entry as _append_note
from datasource.utils.text_markers import contains_ytd_marker
from datasource.utils.trend_history_store import DEFAULT_BASE_DIR

from datasource.engines.stage2_5 import trend_backfill
from datasource.engines.stage2_5.common import (
    DEFAULT_SOURCE_LABEL,
    SOURCE_ANOMALY_LABEL,
    _calc_change_rate_pct,
    _calc_previous_from_change_rate_pct,
    _coerce_bool,
    _coerce_float,
    _coerce_percent,
    _format_source_label,
    _has_valid_value,
    _is_placeholder_numeric,
    _merge_same_value_report_fields,
    _pct_change,
    _same_numeric_value,
)
from datasource.engines.stage2_5.fund_flow import (
    _default_fund_flow_metric_basis,
    _infer_fund_flow_source_tier,
    _infer_fund_flow_window_evidence,
    _normalize_fund_flow_estimation,
    _normalize_source_tier,
)
from datasource.engines.stage2_5.manual_official import (
    _apply_manual_official_estimation_rule,
    _has_rrr_type_conflict,
    _is_trusted_monetary_manual_quality_override,
    _normalize_rrr_type,
    _should_preserve_existing_official_source,
)
from datasource.engines.stage2_5.schema_coercion import (
    _copy_payload_metadata_fields,
    _copy_source_url,
)
from datasource.engines.stage2_5.trend_backfill import (
    _copy_valid_forex_120d_change_evidence,
    _copy_valid_forex_daily_change_evidence,
    _derive_trend_confidence,
    _infer_asset_trend,
    _infer_trend,
    _merge_trend_confidence,
    _usable_forex_change_value,
    _usable_forex_raw_trend,
)

if TYPE_CHECKING:
    from datasource.engines.stage2_5.core import InjectionSummary

_contains_ytd_marker = contains_ytd_marker


def _apply_macro_entry(
    indicator_key: str,
    entry: Dict[str, Any],
    payload: Dict[str, Any],
    reference_date: Optional[str],
    *,
    is_manual: bool = False,
    override_stale: bool = True,
    force_override: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
    summary: Optional[InjectionSummary] = None,
) -> bool:
    if not isinstance(entry, dict):
        return False
    original_current_value = entry.get("current_value")
    incoming_current_value = _coerce_float(payload.get("current_value"))
    existing_placeholder = _is_placeholder_numeric(entry.get("current_value"))
    existing_stale = bool(entry.get("is_stale"))
    if (
        not force_override
        and not existing_placeholder
        and not (override_stale and existing_stale)
    ):
        if _same_numeric_value(original_current_value, incoming_current_value):
            if _merge_same_value_report_fields(
                entry,
                payload,
                category="macro_indicators",
                key=indicator_key,
                is_manual=is_manual,
                override_stale=override_stale,
            ):
                if summary is not None:
                    summary.metadata_updated(
                        "macro_indicators",
                        indicator_key,
                        "same_numeric_value_report_fields_merged",
                        original_current_value,
                        incoming_current_value,
                    )
                return True
        if summary is not None:
            if incoming_current_value is None:
                summary.skipped_no_parseable_value(
                    "macro_indicators", indicator_key
                )
            else:
                summary.skipped_existing(
                    "macro_indicators",
                    indicator_key,
                    "existing_value_present",
                    original_current_value,
                    incoming_current_value,
                )
        return False
    entry["indicator_name"] = payload.get(
        "indicator_name", entry.get("indicator_name")
    )
    entry["unit"] = payload.get("unit", entry.get("unit", ""))
    incoming_date = (
        payload.get("date")
        or payload.get("as_of_date")
        or payload.get("report_period")
    )
    if incoming_date:
        entry["date"] = incoming_date
    if payload.get("expected_period"):
        entry["expected_period"] = payload.get("expected_period")
    if payload.get("report_period"):
        entry["report_period"] = payload.get("report_period")
    entry["as_of_date"] = (
        payload.get("as_of_date")
        or payload.get("report_period")
        or entry.get("as_of_date")
    )
    entry["source"] = _format_source_label(payload.get("source"))
    _copy_source_url(entry, payload)
    _copy_payload_metadata_fields(
        entry, payload, ("estimation_method", "metric_basis", "confidence")
    )
    # 确保 note 为字符串，避免 None 参与字符串拼接时报错
    note_val = payload.get("note", entry.get("note"))
    if is_manual and "note" not in payload:
        note_val = ""
    entry["note"] = note_val if isinstance(note_val, str) else ""
    fallback_reason = None

    if indicator_key == "industrial":
        raw_current = _coerce_float(payload.get("current_value"))
        yoy_month = _coerce_float(payload.get("yoy_month"))
        yoy_ytd = _coerce_float(payload.get("yoy_ytd"))
        raw_type = payload.get("value_type")
        value_type = None
        if isinstance(raw_type, str) and raw_type.strip():
            raw_lower = raw_type.lower()
            if "month" in raw_lower or "当月" in raw_type:
                value_type = "yoy_month"
            elif "ytd" in raw_lower or "累计" in raw_type:
                value_type = "yoy_ytd"
        if value_type == "yoy_month":
            if yoy_month is None:
                yoy_month = raw_current
        elif value_type == "yoy_ytd":
            if yoy_ytd is None:
                yoy_ytd = raw_current
        elif raw_current is not None and yoy_month is None and yoy_ytd is None:
            hint_text = " ".join(
                str(payload.get(k) or "")
                for k in ("note", "source", "indicator_name", "report_period")
            )
            if _contains_ytd_marker(hint_text):
                yoy_ytd = raw_current
                value_type = "yoy_ytd"
            else:
                yoy_month = raw_current
                value_type = "yoy_month"

        entry["yoy_month"] = yoy_month
        entry["yoy_ytd"] = yoy_ytd
        entry["value_type"] = value_type or entry.get("value_type")
        entry["current_value"] = yoy_month
        entry["previous_value"] = (
            _coerce_float(payload.get("previous_value"))
            if yoy_month is not None
            else None
        )
        entry["change_rate"] = (
            _coerce_float(payload.get("change_rate"))
            if yoy_month is not None
            else None
        )

        if (
            yoy_month is not None
            and yoy_ytd is not None
            and abs(yoy_month - yoy_ytd) < 1e-6
        ):
            _append_note(entry, "口径疑似混淆(yoy_month≈yoy_ytd)")
        if yoy_month is None and yoy_ytd is not None:
            _append_note(entry, "only_yoy_ytd_provided")
            fallback_reason = fallback_reason or "manual_incomplete"
    else:
        entry["current_value"] = _coerce_float(payload.get("current_value"))
        entry["previous_value"] = _coerce_float(payload.get("previous_value"))
        entry["change_rate"] = _coerce_float(payload.get("change_rate"))
        entry["value_type"] = payload.get(
            "value_type", entry.get("value_type")
        )

    # is_estimated 规则：手工注入默认不估算；regex_only/明确标注才估算
    if "is_estimated" in payload:
        entry["is_estimated"] = _coerce_bool(payload.get("is_estimated"))
    else:
        source_text = str(payload.get("source") or entry.get("source") or "")
        note_text = str(entry.get("note") or "")
        estimated_markers = (
            "regex_only",
            "regex_fallback",
            "bond_etf_proxy",
            "ETF代理",
            "估",
            "estimated",
        )
        if any(m in source_text or m in note_text for m in estimated_markers):
            entry["is_estimated"] = True
        else:
            entry["is_estimated"] = (
                False
                if entry.get("current_value") is not None
                else bool(entry.get("is_estimated"))
            )

    # 先尝试事件序列回填 previous_value / change_rate（工业增加值仅在当月同比可用时回填）
    if (
        entry["previous_value"] is None
        and entry["current_value"] is not None
        and trend_history_base_dir is not None
    ):
        hist_prev = trend_backfill._calc_prev_from_event_history(
            indicator_key,
            entry["current_value"],
            reference_date,
            base_dir=trend_history_base_dir,
            current_period=(
                entry.get("report_period")
                or entry.get("date")
                or entry.get("as_of_date")
            ),
            unit=entry.get("unit"),
        )
        if hist_prev.get("previous_value") is not None:
            entry["previous_value"] = hist_prev.get("previous_value")
            existing_value_source = entry.get("value_source")
            if existing_value_source in (
                None,
                "",
                "event_history_backfill",
            ) and hist_prev.get("value_source"):
                entry["value_source"] = hist_prev.get("value_source")
            if hist_prev.get("caliber_note"):
                _append_note(entry, "caliber_inferred")
            if (
                entry["change_rate"] is None
                and hist_prev.get("change_rate") is not None
            ):
                entry["change_rate"] = hist_prev.get("change_rate")
        else:
            fallback_reason = hist_prev.get("reason")

    # 兜底回填变化率：若有 current_value + previous_value 且 change_rate 缺失，自动按百分比补齐
    if (
        entry["change_rate"] is None
        and entry["current_value"] is not None
        and entry["previous_value"] is not None
    ):
        change_rate_pct = _calc_change_rate_pct(
            entry["current_value"], entry["previous_value"]
        )
        if change_rate_pct is not None:
            entry["change_rate"] = change_rate_pct
            if not entry.get("note"):
                entry["note"] = ""
            if entry["note"]:
                entry["note"] += "；"
            entry["note"] += (
                "auto-backfilled change_rate% via "
                "(current-previous)/abs(previous)*100"
            )
        else:
            fallback_reason = fallback_reason or "change_rate_pct_div_by_zero"

    # 兜底回填前值：若有 current_value + change_rate(%) 但前值缺失，按百分比反推
    if entry["previous_value"] is None and entry["current_value"] is not None:
        if not entry.get("note"):
            entry["note"] = ""
        if entry["change_rate"] is not None:
            previous_value = _calc_previous_from_change_rate_pct(
                entry["current_value"], entry["change_rate"]
            )
            if previous_value is not None:
                entry["previous_value"] = previous_value
                if entry["note"]:
                    entry["note"] += "；"
                entry["note"] += (
                    "auto-backfilled previous_value via "
                    "current/(1+change_rate/100)"
                )
                fallback_reason = fallback_reason or "no_previous_value"
            else:
                fallback_reason = (
                    fallback_reason or "change_rate_pct_invalid_denominator"
                )
        else:
            fallback_reason = fallback_reason or "manual_incomplete"

    if fallback_reason:
        if entry["note"]:
            entry["note"] += "；"
        entry["note"] += f"reason={fallback_reason}"
    # 若仍无有效 current_value，则视为缺失，抛出异常阻断流程，避免 Stage3 出现 N/A
    if entry["current_value"] is None:
        raise ValueError(
            f"macro_indicators.{entry.get('indicator_name', 'unknown')} "
            "current_value is missing after injection"
        )
    entry["is_stale"] = False
    entry["stale_reason"] = None
    if summary is not None:
        if (
            force_override
            and _coerce_float(original_current_value) is not None
            and not _same_numeric_value(
                original_current_value, entry.get("current_value")
            )
        ):
            summary.forced_override(
                "macro_indicators",
                indicator_key,
                original_current_value,
                incoming_current_value,
            )
        summary.injected("macro_indicators", indicator_key)
    return True


def _create_monetary_placeholder(
    key: str, payload: Dict[str, Any], metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """当原始市场数据缺少某个货币政策字段时，动态创建占位符"""
    default_date = (
        payload.get("date")
        or payload.get("as_of_date")
        or payload.get("report_period")
        or ""
    )
    return {
        "policy_name": payload.get("policy_name", key.upper()),
        "current_value": None,
        "change_from_120d": None,
        "unit": payload.get("unit", "%"),
        "date": default_date,
        "as_of_date": payload.get("as_of_date"),
        "rrr_type": payload.get("rrr_type"),
        "source": "待WebSearch补充(websearch导入)",
        "note": payload.get("note"),
        "is_estimated": True,
        "is_stale": False,
        "expected_period": payload.get("expected_period"),
        "stale_reason": None,
    }


def _create_macro_placeholder(
    key: str, payload: Dict[str, Any], metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """缺失宏观指标时创建占位，便于后续注入而不跳过"""
    default_date = (
        payload.get("date")
        or payload.get("as_of_date")
        or payload.get("report_period")
        or ""
    )
    return {
        "indicator_name": payload.get("indicator_name", key),
        "current_value": None,
        "yoy_month": None,
        "yoy_ytd": None,
        "previous_value": None,
        "change_rate": None,
        "unit": payload.get("unit", payload.get("unit", "%")),
        "date": default_date,
        "as_of_date": payload.get("as_of_date"),
        "value_type": payload.get("value_type"),
        "source": "待WebSearch补充",
        "note": payload.get("note"),
        "is_estimated": True,
        "is_stale": False,
        "expected_period": payload.get("expected_period"),
        "stale_reason": None,
    }


def _apply_monetary_entry(
    indicator_key: str,
    entry: Dict[str, Any],
    payload: Dict[str, Any],
    reference_date: Optional[str],
    *,
    is_manual: bool = False,
    override_stale: bool = True,
    force_override: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
    summary: Optional[InjectionSummary] = None,
) -> bool:
    if not isinstance(entry, dict):
        return False
    original_current_value = entry.get("current_value")
    incoming_current_value = _coerce_float(payload.get("current_value"))
    existing_placeholder = _is_placeholder_numeric(entry.get("current_value"))
    existing_stale = bool(entry.get("is_stale"))
    preserve_stale = existing_stale and not override_stale
    original_stale_reason = entry.get("stale_reason")
    rrr_type_conflict = indicator_key in {
        "rrr",
        "reserve_ratio",
    } and _has_rrr_type_conflict(entry, payload)
    if rrr_type_conflict:
        if summary is not None:
            summary.skipped_existing(
                "monetary_policy",
                indicator_key,
                "rrr_type_conflict",
                original_current_value,
                incoming_current_value,
            )
        return False
    trusted_quality_override = _is_trusted_monetary_manual_quality_override(
        indicator_key,
        entry,
        payload,
        incoming_current_value,
        is_manual=is_manual,
    )
    preserve_existing_official_source = (
        _should_preserve_existing_official_source(entry, payload)
    )
    if (
        not force_override
        and not existing_placeholder
        and not (override_stale and existing_stale)
    ):
        if _same_numeric_value(original_current_value, incoming_current_value):
            if _merge_same_value_report_fields(
                entry,
                payload,
                category="monetary_policy",
                key=indicator_key,
                is_manual=is_manual,
                override_stale=override_stale,
            ):
                if summary is not None:
                    summary.metadata_updated(
                        "monetary_policy",
                        indicator_key,
                        "same_numeric_value_report_fields_merged",
                        original_current_value,
                        incoming_current_value,
                    )
                return True
        if not trusted_quality_override:
            if summary is not None:
                if incoming_current_value is None:
                    summary.skipped_no_parseable_value(
                        "monetary_policy", indicator_key
                    )
                else:
                    summary.skipped_existing(
                        "monetary_policy",
                        indicator_key,
                        "existing_value_present",
                        original_current_value,
                        incoming_current_value,
                    )
            return False
    entry["policy_name"] = payload.get("policy_name", entry.get("policy_name"))
    incoming_value = _coerce_float(payload.get("current_value"))
    change_value = payload.get("change_from_120d", payload.get("change_rate"))
    entry["change_from_120d"] = _coerce_float(change_value)
    entry["unit"] = payload.get("unit", entry.get("unit", ""))
    incoming_date = (
        payload.get("date")
        or payload.get("as_of_date")
        or payload.get("report_period")
    )
    if incoming_date:
        entry["date"] = incoming_date
    if payload.get("expected_period"):
        entry["expected_period"] = payload.get("expected_period")
    entry["as_of_date"] = payload.get("as_of_date") or entry.get("as_of_date")
    if not preserve_existing_official_source:
        entry["source"] = _format_source_label(payload.get("source"))
        _copy_source_url(entry, payload)
    _copy_payload_metadata_fields(
        entry, payload, ("estimation_method", "metric_basis", "confidence")
    )
    note_val = payload.get("note", entry.get("note"))
    if is_manual and "note" not in payload:
        note_val = ""
    if not preserve_existing_official_source:
        entry["note"] = note_val
    incoming_rrr_type = _normalize_rrr_type(
        payload.get("rrr_type") or payload.get("value_type")
    )
    if indicator_key in {"rrr", "reserve_ratio"}:
        existing_rrr_type = _normalize_rrr_type(entry.get("rrr_type"))
        if incoming_rrr_type:
            if (
                existing_rrr_type
                and incoming_rrr_type != existing_rrr_type
                and entry.get("current_value") is not None
            ):
                _append_note(
                    entry,
                    "rrr_type_conflict:"
                    f"{existing_rrr_type}->{incoming_rrr_type}",
                )
                incoming_value = None
            else:
                entry["rrr_type"] = incoming_rrr_type

    if incoming_value is not None:
        entry["current_value"] = incoming_value

    # is_estimated 规则：手工注入默认不估算；regex_only/明确标注才估算
    if "is_estimated" in payload:
        incoming_estimated = _coerce_bool(payload.get("is_estimated"))
        if not (
            preserve_existing_official_source
            and entry.get("is_estimated") is False
            and incoming_estimated is True
        ):
            entry["is_estimated"] = incoming_estimated
    else:
        if not preserve_existing_official_source:
            source_text = str(
                payload.get("source") or entry.get("source") or ""
            )
            note_text = str(entry.get("note") or "")
            estimated_markers = (
                "regex_only",
                "regex_fallback",
                "bond_etf_proxy",
                "ETF代理",
                "估",
                "estimated",
            )
            if any(
                m in source_text or m in note_text for m in estimated_markers
            ):
                entry["is_estimated"] = True
            else:
                entry["is_estimated"] = (
                    False
                    if entry.get("current_value") is not None
                    else bool(entry.get("is_estimated"))
                )
    if is_manual:
        _apply_manual_official_estimation_rule(
            "monetary_policy", indicator_key, payload, entry
        )

    fallback_reason = None
    if (
        entry["change_from_120d"] is None
        and entry["current_value"] is not None
        and trend_history_base_dir is not None
    ):
        hist = trend_backfill._calc_change_from_event_history(
            indicator_key,
            entry["current_value"],
            reference_date,
            base_dir=trend_history_base_dir,
        )
        if hist.get("change_from_120d") is not None:
            entry["change_from_120d"] = hist.get("change_from_120d")
        else:
            entry["change_from_120d"] = None
        fallback_reason = hist.get("reason")

    if fallback_reason:
        note_val = entry.get("note")
        if not isinstance(note_val, str):
            note_val = ""
        if note_val:
            note_val += "；"
        note_val += f"reason={fallback_reason}"
        entry["note"] = note_val
    if entry.get("current_value") is not None:
        if preserve_stale:
            entry["is_stale"] = True
            entry["stale_reason"] = original_stale_reason
        else:
            entry["is_stale"] = False
            entry["stale_reason"] = None
    if summary is not None:
        if (
            force_override
            and _coerce_float(original_current_value) is not None
            and not _same_numeric_value(
                original_current_value, entry.get("current_value")
            )
        ):
            summary.forced_override(
                "monetary_policy",
                indicator_key,
                original_current_value,
                incoming_current_value,
            )
        summary.injected("monetary_policy", indicator_key)
    return True


def _apply_fund_flow_entry(
    entry: Dict[str, Any],
    key: str,
    payload: Dict[str, Any],
    *,
    summary: Optional[InjectionSummary] = None,
) -> bool:
    existing_recent = _coerce_float(entry.get("recent_5d"))
    existing_total = _coerce_float(entry.get("total_120d"))
    existing_suspicious = _is_suspicious_fund_flow_pair(
        key, existing_recent, existing_total
    )
    payload_requested_estimated = _coerce_bool(payload.get("is_estimated"))
    recent_value = FundFlowData._parse_amount(payload.get("recent_5d"))
    total_value = FundFlowData._parse_amount(payload.get("total_120d"))
    current_value = FundFlowData._parse_amount(
        payload.get("current_value")
        or payload.get("daily_value")
        or payload.get("today_value")
    )
    if recent_value is None and total_value is None and current_value is None:
        print(f"  [WARN] {key} 缺少可解析的金额，跳过注入")
        return False

    entry["type"] = key
    updated = False
    if recent_value is not None:
        entry["recent_5d"] = recent_value
        updated = True
    if total_value is not None:
        entry["total_120d"] = total_value
        updated = True
    if current_value is not None:
        entry["current_value"] = current_value
        entry["current_date"] = payload.get("date") or entry.get(
            "current_date"
        )
        updated = True
    if not updated:
        return False

    trend_base = recent_value if recent_value is not None else current_value
    entry["trend"] = _infer_trend(payload.get("trend"), trend_base)

    anomaly = any(
        value == 0
        for value in (recent_value, total_value, current_value)
        if value is not None
    )
    anomaly = anomaly or _is_suspicious_fund_flow_pair(
        key, recent_value, total_value
    )
    entry["source"] = SOURCE_ANOMALY_LABEL if anomaly else DEFAULT_SOURCE_LABEL
    entry["note"] = _build_fund_flow_note(payload, anomaly)
    _copy_source_url(entry, payload)
    _copy_payload_metadata_fields(
        entry,
        payload,
        ("is_estimated", "estimation_method", "confidence"),
    )
    claimed_source_tier = _normalize_source_tier(payload.get("source_tier"))
    if claimed_source_tier:
        entry["claimed_source_tier"] = claimed_source_tier
    else:
        entry.pop("claimed_source_tier", None)
    entry["metric_basis"] = _default_fund_flow_metric_basis(key, payload)
    entry["source_tier"] = _infer_fund_flow_source_tier(payload)
    entry["window_evidence"] = _infer_fund_flow_window_evidence(
        key,
        payload,
        entry["metric_basis"],
    )
    _normalize_fund_flow_estimation(entry, payload)
    if (
        summary is not None
        and not payload_requested_estimated
        and entry.get("is_estimated") is True
    ):
        summary.fund_flow_forced_estimated(
            "fund_flow",
            key,
            source_tier=entry.get("source_tier"),
            window_evidence=entry.get("window_evidence"),
            metric_basis=entry.get("metric_basis") or "unknown",
            reason="fund_flow_estimated_gate",
        )
    if existing_suspicious:
        entry["note"] = (
            f"覆盖Stage2可疑占位值；{entry['note']}"
            if entry.get("note")
            else "覆盖Stage2可疑占位值"
        )
    return True


def _is_suspicious_fund_flow_pair(
    key: str, recent_value: Optional[float], total_value: Optional[float]
) -> bool:
    if recent_value is None or total_value is None:
        return False
    if (
        key in {"northbound", "southbound"}
        and abs(recent_value - total_value) < 1e-9
    ):
        if abs(recent_value - 100.0) < 1e-9:
            return True
        if abs(recent_value) <= 150.0:
            return True
    return False


def _build_fund_flow_note(payload: Dict[str, Any], anomaly: bool) -> str:
    parts = []
    raw_source = payload.get("source")
    if raw_source:
        parts.append(f"来源:{raw_source}")
    if payload.get("date"):
        parts.append(f"日期:{payload.get('date')}")
    if payload.get("unit"):
        parts.append(f"单位:{payload['unit']}")
    if payload.get("note"):
        parts.append(payload["note"])
    if (
        payload.get("current_value")
        or payload.get("daily_value")
        or payload.get("today_value")
    ):
        raw_daily = (
            payload.get("current_value")
            or payload.get("daily_value")
            or payload.get("today_value")
        )
        parts.append(f"原始当日:{raw_daily}")
    if payload.get("recent_5d"):
        parts.append(f"原始5日:{payload['recent_5d']}")
    if payload.get("total_120d"):
        parts.append(f"原始120日:{payload['total_120d']}")
    if anomaly:
        parts.append("异常: 零值待WebSearch复核")
    return "；".join(parts)


def _merge_stock_index_entry(
    orig: Dict[str, Any], payload: Dict[str, Any]
) -> Dict[str, Any]:
    """更新已存在的股票指数条目，缺失字段用原值或默认值兜底。"""
    merged = dict(orig)
    merged["symbol"] = payload.get("symbol", orig.get("symbol"))
    merged["name"] = payload.get("name", orig.get("name", merged["symbol"]))
    merged["current_price"] = _coerce_float(
        payload.get("current_price")
        or payload.get("close")
        or payload.get("price")
    ) or orig.get("current_price", 0.0)
    merged["change_5d"] = _coerce_float(
        payload.get("change_5d")
        or payload.get("change_5d_pct")
        or payload.get("weekly_change")
    ) or orig.get("change_5d", 0.0)
    merged["change_120d"] = _coerce_float(
        payload.get("change_120d")
        or payload.get("change_120d_pct")
        or payload.get("ytd_change")
        or payload.get("change_ytd")
    ) or orig.get("change_120d", 0.0)
    merged["above_ma50"] = _coerce_bool(
        payload.get("above_ma50")
        if "above_ma50" in payload
        else orig.get("above_ma50", False)
    )
    merged["above_ma200"] = _coerce_bool(
        payload.get("above_ma200")
        if "above_ma200" in payload
        else orig.get("above_ma200", False)
    )
    merged["ma50_slope"] = _coerce_float(
        payload.get("ma50_slope")
    ) or orig.get("ma50_slope", 0.0)
    merged["volatility_30d"] = _coerce_float(
        payload.get("volatility_30d") or payload.get("volatility")
    ) or orig.get("volatility_30d", 0.0)
    merged["trend_score"] = int(
        payload.get("trend_score", orig.get("trend_score", 0))
    )
    merged["trend_label"] = payload.get(
        "trend_label", orig.get("trend_label", "中性")
    )
    merged["source"] = _format_source_label(
        payload.get("source") or orig.get("source")
    )
    _copy_source_url(merged, payload)
    _copy_payload_metadata_fields(
        merged,
        payload,
        ("is_estimated", "estimation_method", "metric_basis", "confidence"),
    )
    return merged


def _build_stock_index_entry(
    symbol: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """为缺失的指数（如000016）构造完整条目，确保 Pydantic 校验通过。"""
    entry = {
        "symbol": symbol,
        "name": payload.get("name", symbol),
        "current_price": _coerce_float(
            payload.get("current_price")
            or payload.get("close")
            or payload.get("price")
        )
        or 0.0,
        "change_5d": _coerce_float(
            payload.get("change_5d")
            or payload.get("change_5d_pct")
            or payload.get("weekly_change")
        )
        or 0.0,
        "change_120d": _coerce_float(
            payload.get("change_120d")
            or payload.get("change_120d_pct")
            or payload.get("ytd_change")
            or payload.get("change_ytd")
        )
        or 0.0,
        "above_ma50": _coerce_bool(payload.get("above_ma50")),
        "above_ma200": _coerce_bool(payload.get("above_ma200")),
        "ma50_slope": _coerce_float(payload.get("ma50_slope")) or 0.0,
        "volatility_30d": _coerce_float(
            payload.get("volatility_30d") or payload.get("volatility")
        )
        or 0.0,
        "trend_score": int(payload.get("trend_score", 0)),
        "trend_label": payload.get("trend_label", "中性"),
        "source": _format_source_label(payload.get("source")),
    }
    _copy_source_url(entry, payload)
    _copy_payload_metadata_fields(
        entry,
        payload,
        ("is_estimated", "estimation_method", "metric_basis", "confidence"),
    )
    return entry


def _merge_bond_entry(
    existing: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    merged = dict(existing)
    merged["symbol"] = payload.get("symbol", existing.get("symbol"))
    merged["name"] = payload.get(
        "name", existing.get("name", merged["symbol"])
    )
    merged["current_yield"] = _coerce_float(
        payload.get("current_yield")
    ) or existing.get("current_yield")
    # 保留债券日期字段，供报告侧“当日数据”校验与展示
    if payload.get("date"):
        merged["date"] = payload.get("date")
    if payload.get("as_of_date"):
        merged["as_of_date"] = payload.get("as_of_date")
    if payload.get("report_period"):
        merged.setdefault("as_of_date", payload.get("report_period"))
        merged.setdefault("date", payload.get("report_period"))

    # 从 trend_history 计算 bp 变化值
    current_yield = merged.get("current_yield")
    symbol = merged.get("symbol")
    used_hist_5d = False
    used_hist_120d = False
    if current_yield and symbol and trend_history_base_dir is not None:
        hist_changes = trend_backfill._calc_change_from_trend_history(
            "bonds",
            symbol,
            current_yield,
            base_dir=trend_history_base_dir,
        )
        merged["change_5d_bp"] = _coerce_float(payload.get("change_5d_bp"))
        if merged["change_5d_bp"] is None:
            hist_5d = _coerce_float(hist_changes.get("change_5d_bp"))
            if hist_5d is not None:
                merged["change_5d_bp"] = hist_5d
                used_hist_5d = True
            else:
                merged["change_5d_bp"] = existing.get("change_5d_bp", 0.0)
        merged["change_120d_bp"] = _coerce_float(payload.get("change_120d_bp"))
        if merged["change_120d_bp"] is None:
            hist_120d = _coerce_float(hist_changes.get("change_120d_bp"))
            if hist_120d is not None:
                merged["change_120d_bp"] = hist_120d
                used_hist_120d = True
            else:
                merged["change_120d_bp"] = existing.get("change_120d_bp", 0.0)
        confidence, confidence_reason = _derive_trend_confidence(
            hist_changes,
            used_5d=used_hist_5d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(merged, confidence)
        if confidence_reason:
            _append_note(merged, confidence_reason)
    else:
        merged["change_5d_bp"] = _coerce_float(
            payload.get("change_5d_bp")
        ) or existing.get("change_5d_bp", 0.0)
        merged["change_120d_bp"] = _coerce_float(
            payload.get("change_120d_bp")
        ) or existing.get("change_120d_bp", 0.0)
    _copy_source_url(merged, payload)
    _copy_payload_metadata_fields(
        merged, payload, ("estimation_method", "metric_basis", "confidence")
    )

    # 自动推断债券趋势（基于bp变化）
    raw_trend = payload.get("trend", existing.get("trend"))
    merged["trend"] = _infer_asset_trend(
        raw_trend,
        merged.get("change_5d_bp"),
        merged.get("change_120d_bp"),
        "bond",
    )
    merged["source"] = _format_source_label(
        payload.get("source") or existing.get("source")
    )
    payload_estimated = payload.get("is_estimated")
    if payload_estimated is not None:
        merged["is_estimated"] = bool(payload_estimated)
    else:
        merged["is_estimated"] = bool(existing.get("is_estimated", False))
        if is_manual and _has_valid_value(merged.get("current_yield")):
            merged["is_estimated"] = False
    merged["note"] = payload.get("note", existing.get("note"))
    if is_manual:
        _apply_manual_official_estimation_rule(
            "bonds", str(merged.get("symbol") or ""), payload, merged
        )
    return merged


def _merge_commodity_entry(
    existing: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    merged = dict(existing)
    merged["symbol"] = payload.get("symbol", existing.get("symbol"))
    merged["name"] = payload.get(
        "name", existing.get("name", merged["symbol"])
    )
    payload_current_price = _coerce_float(payload.get("current_price"))
    if payload_current_price is not None:
        merged["current_price"] = payload_current_price
    else:
        merged["current_price"] = existing.get("current_price")
    merged["unit"] = payload.get("unit", existing.get("unit", ""))

    # 从 trend_history 计算变化值
    current_price = merged.get("current_price")
    symbol = merged.get("symbol")
    explicit_daily_change = _coerce_percent(payload.get("daily_change"))
    daily_change_base_price = _coerce_float(payload.get("previous_price"))
    daily_change_basis_field = "previous_price"
    if (
        daily_change_base_price is None
        and explicit_daily_change is None
        and payload.get("previous_value") is not None
    ):
        daily_change_base_price = _coerce_float(payload.get("previous_value"))
        daily_change_basis_field = "previous_value"
    payload_daily_change = _pct_change(current_price, daily_change_base_price)
    used_hist_120d = False
    payload_120d = _coerce_percent(payload.get("change_120d"))
    if payload_120d is None:
        payload_120d = _coerce_percent(payload.get("change_120d_pct"))
    if payload_120d is not None:
        merged["change_120d"] = payload_120d
        merged["change_120d_basis"] = payload.get("change_120d_basis") or (
            "websearch_manual" if is_manual else "payload"
        )
    if current_price and symbol and trend_history_base_dir is not None:
        hist_changes = trend_backfill._calc_change_from_trend_history(
            "commodities",
            symbol,
            current_price,
            base_dir=trend_history_base_dir,
        )
        merged["daily_change"] = explicit_daily_change
        if merged["daily_change"] is None:
            merged["daily_change"] = existing.get("daily_change")
        merged["ytd_change"] = _coerce_percent(payload.get("ytd_change"))
        if merged["ytd_change"] is None:
            merged["ytd_change"] = existing.get("ytd_change")
        elif (
            payload.get("ytd_change_basis") or "ytd_change_basis" not in merged
        ):
            merged["ytd_change_basis"] = (
                payload.get("ytd_change_basis") or "year_to_date"
            )
        hist_120d = _coerce_float(hist_changes.get("change_120d"))
        if payload_120d is None and hist_120d is not None:
            merged["change_120d"] = hist_120d
            merged["change_120d_basis"] = "trend_history"
            used_hist_120d = True
        confidence, confidence_reason = _derive_trend_confidence(
            hist_changes,
            used_5d=False,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(merged, confidence)
        if confidence_reason:
            _append_note(merged, confidence_reason)
    else:
        merged["daily_change"] = explicit_daily_change
        if merged["daily_change"] is None:
            merged["daily_change"] = existing.get("daily_change")
        merged["ytd_change"] = _coerce_percent(payload.get("ytd_change"))
        if merged["ytd_change"] is None:
            merged["ytd_change"] = existing.get("ytd_change")
        elif (
            payload.get("ytd_change_basis") or "ytd_change_basis" not in merged
        ):
            merged["ytd_change_basis"] = (
                payload.get("ytd_change_basis") or "year_to_date"
            )
        if payload_120d is None:
            merged["change_120d"] = existing.get("change_120d")
    if payload_daily_change is not None:
        merged["daily_change"] = payload_daily_change
        merged["daily_change_base_price"] = daily_change_base_price
        if payload.get("previous_date"):
            merged["daily_change_base_date"] = payload.get("previous_date")
        basis_prefix = "manual" if is_manual else "payload"
        merged["daily_change_basis"] = (
            f"{basis_prefix}_{daily_change_basis_field}"
        )
    _copy_source_url(merged, payload)
    _copy_payload_metadata_fields(
        merged,
        payload,
        ("is_estimated", "estimation_method", "metric_basis", "confidence"),
    )

    # 自动推断商品趋势（基于涨跌幅）
    raw_trend = payload.get("trend", existing.get("trend"))
    merged["trend"] = _infer_asset_trend(
        raw_trend,
        merged.get("daily_change"),
        (
            merged.get("ytd_change")
            if merged.get("ytd_change") is not None
            else merged.get("change_120d")
        ),
        "commodity",
    )
    merged["source"] = _format_source_label(
        payload.get("source") or existing.get("source")
    )
    merged["timestamp"] = (
        payload.get("timestamp")
        or existing.get("timestamp")
        or datetime.now().strftime("%Y-%m-%d")
    )
    merged["note"] = payload.get("note", existing.get("note"))
    if (
        is_manual
        and "is_estimated" not in payload
        and _has_valid_value(merged.get("current_price"))
    ):
        if "is_estimated" in merged:
            merged["is_estimated"] = False
    if is_manual:
        _apply_manual_official_estimation_rule(
            "commodities", str(merged.get("symbol") or ""), payload, merged
        )
    return merged


def _merge_forex_entry(
    orig: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    merged = dict(orig)
    merged["pair"] = payload.get("pair", orig.get("pair"))
    merged["name"] = payload.get("name", orig.get("name", merged["pair"]))
    merged["current_rate"] = _coerce_float(
        payload.get("current_rate")
    ) or merged.get("current_rate")

    # 从 trend_history 计算变化值（daily_change 取前一交易日变化）
    current_rate = merged.get("current_rate")
    symbol = merged.get("pair")
    payload_has_daily_change = "daily_change" in payload
    payload_daily_change = _coerce_percent(payload.get("daily_change"))
    payload_has_120d_change = "change_120d" in payload
    payload_120d_change = _coerce_percent(payload.get("change_120d"))
    used_hist_1d = False
    used_hist_120d = False
    if current_rate and symbol and trend_history_base_dir is not None:
        hist_changes = trend_backfill._calc_change_from_trend_history(
            "forex",
            symbol,
            current_rate,
            base_dir=trend_history_base_dir,
        )
        daily_hist = trend_backfill._calc_daily_change_from_trend_history(
            "forex",
            symbol,
            current_rate,
            base_dir=trend_history_base_dir,
        )
        merged["daily_change"] = payload_daily_change
        if merged["daily_change"] is None:
            hist_1d = _coerce_float(daily_hist.get("change_1d"))
            if hist_1d is not None:
                merged["daily_change"] = hist_1d
                _copy_valid_forex_daily_change_evidence(
                    merged,
                    {
                        "daily_change_basis": "trend_history",
                        "daily_change_base_date": daily_hist.get(
                            "base_1d_date"
                        ),
                    },
                )
                used_hist_1d = True
            else:
                merged["daily_change"] = orig.get("daily_change")
                _copy_valid_forex_daily_change_evidence(merged, orig)
        merged["change_120d"] = payload_120d_change
        if merged["change_120d"] is None:
            hist_120d = _coerce_float(hist_changes.get("change_120d"))
            if hist_120d is not None:
                merged["change_120d"] = hist_120d
                _copy_valid_forex_120d_change_evidence(
                    merged,
                    {
                        "change_120d_basis": "trend_history",
                        "change_120d_base_date": hist_changes.get(
                            "base_120d_date"
                        ),
                    },
                )
                used_hist_120d = True
            else:
                merged["change_120d"] = orig.get("change_120d")
                _copy_valid_forex_120d_change_evidence(merged, orig)
        else:
            _copy_valid_forex_120d_change_evidence(merged, payload)
        confidence, confidence_reason = _derive_trend_confidence(
            hist_changes,
            used_5d=used_hist_1d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(merged, confidence)
        if confidence_reason:
            _append_note(merged, confidence_reason)
        if used_hist_1d and daily_hist.get("base_1d_estimated"):
            _merge_trend_confidence(merged, "low")
            _append_note(merged, "trend_history_base_estimated")
    else:
        merged["daily_change"] = payload_daily_change
        if merged["daily_change"] is None:
            merged["daily_change"] = orig.get("daily_change")
            _copy_valid_forex_daily_change_evidence(merged, orig)
        merged["change_120d"] = payload_120d_change
        if merged["change_120d"] is None:
            merged["change_120d"] = orig.get("change_120d")
            _copy_valid_forex_120d_change_evidence(merged, orig)
        else:
            _copy_valid_forex_120d_change_evidence(merged, payload)
    if payload_has_daily_change and not used_hist_1d:
        _copy_valid_forex_daily_change_evidence(merged, payload)
    if payload_has_120d_change and not used_hist_120d:
        _copy_valid_forex_120d_change_evidence(merged, payload)
    _copy_source_url(merged, payload)
    _copy_payload_metadata_fields(
        merged,
        payload,
        ("is_estimated", "estimation_method", "metric_basis", "confidence"),
    )

    # 自动推断外汇趋势（基于涨跌幅）
    raw_trend = payload.get("trend", orig.get("trend"))
    trend_daily_change = _usable_forex_change_value(merged, "daily_change")
    trend_120d_change = _usable_forex_change_value(merged, "change_120d")
    merged["trend"] = _infer_asset_trend(
        _usable_forex_raw_trend(
            raw_trend, trend_daily_change, trend_120d_change
        ),
        trend_daily_change,
        trend_120d_change,
        "forex",
    )
    merged["source"] = _format_source_label(payload.get("source"))
    merged["note"] = payload.get("note", orig.get("note"))
    if (
        is_manual
        and "is_estimated" not in payload
        and _has_valid_value(merged.get("current_rate"))
    ):
        if "is_estimated" in merged:
            merged["is_estimated"] = False
    if is_manual:
        _apply_manual_official_estimation_rule(
            "forex", str(merged.get("pair") or ""), payload, merged
        )
    return merged


def _build_forex_entry(
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
    trend_history_base_dir: Optional[Path] = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    pair = payload.get("pair") or payload.get("symbol") or "UNKNOWN"
    current_rate = _coerce_float(payload.get("current_rate"))

    # 从 trend_history 计算变化值（daily_change 取前一交易日变化）
    payload_daily_change = _coerce_percent(payload.get("daily_change"))
    daily_change = payload_daily_change
    payload_120d_change = _coerce_percent(payload.get("change_120d"))
    change_120d = payload_120d_change
    trend_history_daily_evidence: Optional[Dict[str, Any]] = None
    trend_history_120d_evidence: Optional[Dict[str, Any]] = None
    if current_rate and pair and trend_history_base_dir is not None:
        hist_changes = trend_backfill._calc_change_from_trend_history(
            "forex",
            pair,
            current_rate,
            base_dir=trend_history_base_dir,
        )
        daily_hist = trend_backfill._calc_daily_change_from_trend_history(
            "forex",
            pair,
            current_rate,
            base_dir=trend_history_base_dir,
        )
        if daily_change is None:
            hist_daily_change = _coerce_float(daily_hist.get("change_1d"))
            if hist_daily_change is not None:
                daily_change = hist_daily_change
                trend_history_daily_evidence = {
                    "daily_change_basis": "trend_history",
                    "daily_change_base_date": daily_hist.get("base_1d_date"),
                }
        if change_120d is None:
            hist_120d_change = _coerce_float(hist_changes.get("change_120d"))
            if hist_120d_change is not None:
                change_120d = hist_120d_change
                trend_history_120d_evidence = {
                    "change_120d_basis": "trend_history",
                    "change_120d_base_date": hist_changes.get(
                        "base_120d_date"
                    ),
                }

    entry = {
        "pair": pair,
        "name": payload.get("name", pair),
        "current_rate": current_rate,
        "daily_change": daily_change,
        "change_120d": change_120d,
        "source": _format_source_label(payload.get("source")),
        "note": payload.get("note"),
    }
    if payload_daily_change is not None:
        _copy_valid_forex_daily_change_evidence(entry, payload)
    elif trend_history_daily_evidence is not None:
        _copy_valid_forex_daily_change_evidence(
            entry, trend_history_daily_evidence
        )
    if payload_120d_change is not None:
        _copy_valid_forex_120d_change_evidence(entry, payload)
    elif trend_history_120d_evidence is not None:
        _copy_valid_forex_120d_change_evidence(
            entry, trend_history_120d_evidence
        )
    _copy_source_url(entry, payload)
    _copy_payload_metadata_fields(
        entry,
        payload,
        ("is_estimated", "estimation_method", "metric_basis", "confidence"),
    )
    trend_daily_change = _usable_forex_change_value(entry, "daily_change")
    trend_120d_change = _usable_forex_change_value(entry, "change_120d")
    raw_trend = _usable_forex_raw_trend(
        payload.get("trend"), trend_daily_change, trend_120d_change
    )
    entry["trend"] = _infer_asset_trend(
        raw_trend,
        trend_daily_change,
        trend_120d_change,
        "forex",
    )
    if is_manual:
        _apply_manual_official_estimation_rule("forex", pair, payload, entry)
    return entry
