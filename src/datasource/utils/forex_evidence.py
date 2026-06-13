"""Shared forex evidence predicates.

Stage2 and Stage2.5 use similar names for subtly different semantics. This module
centralizes the mechanics while preserving the two predicate families.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional, Tuple

NumberCoercer = Callable[[Any], Optional[float]]
AbsencePredicate = Callable[[Any], bool]

FOREX_COMPARE_FIELDS = ("daily_change", "change_120d")
FOREX_COMPARE_EVIDENCE_TOKENS = {
    "change_120d": ("120d", "120日", "120-day", "120 day", "direct window"),
    "daily_change": (
        "daily change",
        "day change",
        "previous close",
        "change from previous close",
        "日变化",
        "日变动",
        "日涨跌",
    ),
}
FOREX_COMPARE_TEXT_FIELDS = (
    "metric_basis",
    "change_period",
    "window_evidence",
    "estimation_method",
    "note",
    "source",
    "manual_reason",
    "manual_required_reason",
)
FOREX_COMPARE_FIELD_EVIDENCE_KEYS = {
    "daily_change": (
        "daily_change_basis",
        "daily_change_source",
        "daily_change_source_url",
        "daily_change_window_evidence",
        "daily_change_base_date",
        "daily_change_base_price",
        "base_1d_date",
        "change_1d",
        "change_1d_pct",
        "reason_1d",
        "previous_value",
        "previous_rate",
        "previous_price",
    ),
    "change_120d": (
        "change_120d_basis",
        "change_120d_source",
        "change_120d_source_url",
        "change_120d_window_evidence",
        "change_120d_base_date",
        "change_120d_base_price",
    ),
}
STAGE2_FOREX_DAILY_EVIDENCE_MARKERS = (
    "direct_daily_series",
    "direct daily series",
    "direct_daily_window",
    "direct daily window",
    "trend_history_direct_window",
    "trend history direct window",
    "trend_history_full_window",
    "trend history full window",
    "previous_close",
    "previous close",
    "change_1d",
    "change 1d",
    "change_rate",
    "change rate",
    "trend_history",
    "trend history",
)
STAGE2_FOREX_120D_EVIDENCE_MARKERS = (
    "direct_window",
    "direct window",
    "direct_120d_window",
    "direct 120d window",
    "trend_history_direct_window",
    "trend history direct window",
    "trend_history_full_window",
    "trend history full window",
    "change_rate",
    "change rate",
    "trend_history",
    "trend history",
)
STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS = (
    "direct_daily_series",
    "direct_window",
    "trend_history_direct_window",
    "trend_history_full_window",
    "change_1d",
    "change_rate",
    "trend_history",
)
STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS = (
    "direct_window",
    "trend_history_direct_window",
    "trend_history_full_window",
    "change_rate",
    "trend_history",
)
FOREX_DAILY_CHANGE_EVIDENCE_KEYS = FOREX_COMPARE_FIELD_EVIDENCE_KEYS["daily_change"]
FOREX_120D_CHANGE_EVIDENCE_KEYS = FOREX_COMPARE_FIELD_EVIDENCE_KEYS["change_120d"]


def join_forex_compare_evidence_text(extraction: Dict[str, Any]) -> str:
    return " ".join(
        str(extraction.get(field) or "") for field in FOREX_COMPARE_TEXT_FIELDS
    ).lower()


def normalize_forex_compare_text(text: Any) -> str:
    return re.sub(r"[_-]+", " ", str(text or "").strip().lower())


def is_stage2_forex_no_change_absence_text(normalized_text: str) -> bool:
    return any(
        re.search(pattern, normalized_text)
        for pattern in (
            r"\bno change\s+(?:from\s+)?(?:120d|120\s+day|120日)\b",
            r"\bno change\s+(?:value|data|window|evidence)\b",
        )
    )


def is_stage2_forex_absence_text(text: Any) -> bool:
    raw = str(text or "").strip().lower()
    normalized = normalize_forex_compare_text(raw)
    if not raw:
        return False
    if is_stage2_forex_no_change_absence_text(normalized):
        return True
    if any(
        token in normalized
        for token in ("no change", "unchanged", "无变化", "没有变化")
    ):
        non_absence = normalized
        for token in ("no change", "unchanged", "无变化", "没有变化"):
            non_absence = non_absence.replace(token, "")
        if not any(
            marker in non_absence
            for marker in (
                "missing",
                "without",
                "unavailable",
                "not available",
                "no data",
                "no value",
                "no window",
                "no evidence",
                "deepseek no value",
                "no deepseek key",
                "缺少",
                "缺失",
                "不可得",
                "不可用",
                "未披露",
                "没有数据",
                "没有窗口",
                "没有证据",
                "没有值",
                "无数据",
                "无窗口",
                "无证据",
                "无值",
            )
        ):
            return False
    return any(
        marker in normalized
        for marker in (
            "missing",
            "without",
            "unavailable",
            "not available",
            "no data",
            "no value",
            "no window",
            "no evidence",
            "deepseek no value",
            "no deepseek key",
            "missing previous value",
            "no previous value",
            "failed",
            "failure",
            "error",
            "invalid",
            "缺少",
            "缺失",
            "不可得",
            "不可用",
            "未披露",
            "没有数据",
            "没有窗口",
            "没有证据",
            "没有值",
            "无数据",
            "无窗口",
            "无证据",
            "无值",
            "失败",
        )
    )


def has_stage2_forex_no_change_evidence(text: Any) -> bool:
    normalized = normalize_forex_compare_text(text)
    if is_stage2_forex_no_change_absence_text(normalized):
        return False
    return any(
        token in normalized
        for token in ("no change", "unchanged", "无变化", "没有变化")
    )


def is_stage2_forex_compare_absence_text(text: Any, field: str) -> bool:
    raw = str(text or "").strip()
    normalized = normalize_forex_compare_text(raw)
    if not raw:
        return False
    if has_stage2_forex_no_change_evidence(raw):
        non_absence = normalized
        for token in ("no change", "unchanged", "无变化", "没有变化"):
            non_absence = non_absence.replace(token, "")
        if not is_stage2_forex_absence_text(non_absence):
            return False
    if is_stage2_forex_absence_text(raw):
        if field == "change_120d" and any(
            token in normalized
            for token in (
                "missing previous value",
                "no previous value",
                "reason=no previous value",
            )
        ):
            return False
        return True
    if field == "daily_change":
        return any(
            marker in normalized
            for marker in (
                "missing previous value",
                "no previous value",
                "reason=no previous value",
                "missing daily change",
                "no daily change",
                "daily change missing",
            )
        )
    if field == "change_120d":
        return any(
            marker in normalized
            for marker in (
                "missing 120d",
                "120d missing",
                "no 120d",
                "120d no",
                "missing 120 day",
                "120 day missing",
                "missing 120日",
                "120日 缺失",
            )
        )
    return False


def is_stage25_forex_daily_change_absence_text(text: Any) -> bool:
    normalized = str(text or "").strip().lower()
    if normalized in {"", "n/a", "na", "-", "--", "unknown", "pending"}:
        return True
    return bool(
        re.search(r"\breason\s*=", normalized)
        or re.search(r"\b(?:missing|no)[_\s-]", normalized)
        or any(
            marker in normalized
            for marker in (
                "deepseek_no_value",
                "missing_previous_value",
                "missing_value",
                "no_previous_value",
                "no_value",
                "failed",
                "failure",
                "error",
                "invalid",
                "unavailable",
                "not_available",
                "not-available",
                "not available",
                "缺失",
                "失败",
            )
        )
    )


def is_valid_forex_source_url(value: Any, *, is_absence: AbsencePredicate) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if is_absence(text):
        return False
    return bool(re.fullmatch(r"https?://\S+", text, flags=re.IGNORECASE))


def is_valid_forex_base_date(value: Any, *, is_absence: AbsencePredicate) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if is_absence(text):
        return False
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{8}|\d{4}-\d{2}", text))


def is_valid_forex_base_price(
    value: Any,
    *,
    is_absence: AbsencePredicate,
    coerce: NumberCoercer,
) -> bool:
    if value is None:
        return False
    if is_absence(str(value)):
        return False
    return coerce(value) is not None


def has_forex_computed_marker(
    value: Any,
    markers: Tuple[str, ...],
    *,
    is_absence: AbsencePredicate,
    reject_daily_prefix: bool = False,
) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if is_absence(text):
        return False
    tokens = set(re.split(r"[^a-z0-9_]+", text))
    # NOTE(PR-C0): the negative-prefix skip below assumes no entry in `markers`
    # itself starts with one of these prefixes. All STAGE2_*/STAGE25_* marker
    # tuples satisfy this today. If a future marker begins with
    # failed/failure/error/invalid/unavailable, the `token == marker_token`
    # branch would be wrongly skipped here, diverging from the pre-C0 Stage2.5
    # `_has_forex_*_change_computed_marker` (which gated only the endswith branch).
    negative_prefixes = ("failed", "failure", "error", "invalid", "unavailable")
    for token in tokens:
        if reject_daily_prefix and token.startswith("daily_"):
            continue
        if token.startswith(negative_prefixes):
            continue
        for marker in markers:
            marker_token = marker.replace(" ", "_")
            if token == marker_token or token.endswith(f"_{marker_token}"):
                return True
    return False


def has_stage2_forex_positive_compare_text(evidence_text: str, field: str) -> bool:
    normalized = normalize_forex_compare_text(evidence_text)
    if has_stage2_forex_no_change_evidence(evidence_text):
        return True
    if field == "daily_change":
        tokens = (
            FOREX_COMPARE_EVIDENCE_TOKENS.get(field, ())
            + STAGE2_FOREX_DAILY_EVIDENCE_MARKERS
        )
    elif field == "change_120d":
        tokens = (
            FOREX_COMPARE_EVIDENCE_TOKENS.get(field, ())
            + STAGE2_FOREX_120D_EVIDENCE_MARKERS
        )
    else:
        tokens = FOREX_COMPARE_EVIDENCE_TOKENS.get(field, ())
    return any(token in evidence_text or token in normalized for token in tokens)


def has_stage2_forex_field_specific_evidence(
    payload: Dict[str, Any],
    field: str,
    *,
    coerce: NumberCoercer,
) -> bool:
    evidence_keys = FOREX_COMPARE_FIELD_EVIDENCE_KEYS.get(field, ())
    for key in evidence_keys:
        value = payload.get(key)
        if value in (None, "", "N/A"):
            continue
        if field == "daily_change":
            if key in {
                "daily_change_basis",
                "daily_change_source",
                "daily_change_window_evidence",
            }:
                if has_forex_computed_marker(
                    value,
                    STAGE2_FOREX_DAILY_EVIDENCE_MARKERS,
                    is_absence=is_stage2_forex_absence_text,
                ):
                    return True
                continue
            if key == "daily_change_source_url":
                if is_valid_forex_source_url(
                    value, is_absence=is_stage2_forex_absence_text
                ):
                    return True
                continue
            if key in {"daily_change_base_date", "base_1d_date"}:
                if is_valid_forex_base_date(
                    value, is_absence=is_stage2_forex_absence_text
                ):
                    return True
                continue
            if key == "daily_change_base_price" and is_valid_forex_base_price(
                value,
                is_absence=is_stage2_forex_absence_text,
                coerce=coerce,
            ):
                return True
            continue
        if field == "change_120d":
            if key in {
                "change_120d_basis",
                "change_120d_source",
                "change_120d_window_evidence",
            }:
                if has_forex_computed_marker(
                    value,
                    STAGE2_FOREX_120D_EVIDENCE_MARKERS,
                    is_absence=is_stage2_forex_absence_text,
                    reject_daily_prefix=True,
                ):
                    return True
                continue
            if key == "change_120d_source_url":
                if is_valid_forex_source_url(
                    value, is_absence=is_stage2_forex_absence_text
                ):
                    return True
                continue
            if key == "change_120d_base_date":
                if is_valid_forex_base_date(
                    value, is_absence=is_stage2_forex_absence_text
                ):
                    return True
                continue
            if key == "change_120d_base_price" and is_valid_forex_base_price(
                value,
                is_absence=is_stage2_forex_absence_text,
                coerce=coerce,
            ):
                return True
    return False


def has_stage2_forex_structured_compare_evidence(
    payload: Dict[str, Any], field: str
) -> bool:
    change_period = str(payload.get("change_period") or "").strip().lower()
    window_evidence = str(payload.get("window_evidence") or "").strip().lower()
    metric_basis = str(payload.get("metric_basis") or "").strip().lower()
    if field == "daily_change":
        if change_period in {"daily", "1d", "day", "日频", "日变化"}:
            return True
        return any(
            token in window_evidence or token in metric_basis
            for token in STAGE2_FOREX_DAILY_EVIDENCE_MARKERS
        )
    if field == "change_120d":
        if change_period in {"120d", "120-day", "120 day", "120日"}:
            return True
        return any(
            token in window_evidence or token in metric_basis
            for token in STAGE2_FOREX_120D_EVIDENCE_MARKERS
        )
    return False


def has_stage2_negative_forex_compare_marker(evidence_text: str, field: str) -> bool:
    if is_stage2_forex_compare_absence_text(evidence_text, field):
        return True
    context_tokens = FOREX_COMPARE_EVIDENCE_TOKENS.get(field, ())
    ascii_negative_tokens = (
        "missing",
        "without",
        "unavailable",
        "not available",
        "no data",
        "no value",
        "no window",
        "no evidence",
    )
    chinese_negative_tokens = (
        "缺少",
        "缺失",
        "不可得",
        "不可用",
        "未披露",
        "没有数据",
        "没有窗口",
        "没有证据",
        "没有值",
        "无数据",
        "无窗口",
        "无证据",
        "无值",
    )

    for context_token in context_tokens:
        context_pattern = re.escape(context_token).replace(r"\ ", r"\s+")
        if re.search(
            rf"\bno\b[^.;,，。]*{context_pattern}[^.;,，。]*(?:data|value|window|evidence)\b",
            evidence_text,
        ):
            return True
        if re.search(
            rf"{context_pattern}[^.;,，。]*\bno\b[^.;,，。]*(?:data|value|window|evidence)\b",
            evidence_text,
        ):
            return True
        if re.search(
            rf"无[^.;,，。]*{context_pattern}[^.;,，。]*(?:数据|窗口|证据|值)",
            evidence_text,
        ):
            return True
        if re.search(
            rf"{context_pattern}[^.;,，。]*无[^.;,，。]*(?:数据|窗口|证据|值)",
            evidence_text,
        ):
            return True
        for negative_token in ascii_negative_tokens:
            negative_pattern = re.escape(negative_token).replace(r"\ ", r"\s+")
            if re.search(
                rf"\b{negative_pattern}\b[^.;,，。]*{context_pattern}", evidence_text
            ):
                return True
            if re.search(
                rf"{context_pattern}[^.;,，。]*\b{negative_pattern}\b", evidence_text
            ):
                return True
        for negative_token in chinese_negative_tokens:
            negative_pattern = re.escape(negative_token).replace(r"\ ", r"\s*")
            if re.search(
                rf"{negative_pattern}[^.;,，。]*{context_pattern}", evidence_text
            ):
                return True
            if re.search(
                rf"{context_pattern}[^.;,，。]*{negative_pattern}", evidence_text
            ):
                return True
    return False


def has_stage2_forex_compare_evidence(
    extraction: Dict[str, Any],
    field: str,
    existing_entry: Optional[Dict[str, Any]] = None,
    *,
    coerce: NumberCoercer,
) -> bool:
    parsed_value = coerce(extraction.get(field)) if field in extraction else None
    evidence_text = join_forex_compare_evidence_text(extraction)
    if has_stage2_negative_forex_compare_marker(evidence_text, field):
        return False
    if parsed_value is not None and parsed_value != 0.0:
        return True
    if has_stage2_forex_field_specific_evidence(extraction, field, coerce=coerce):
        return True
    if has_stage2_forex_structured_compare_evidence(extraction, field):
        return True
    if has_stage2_forex_positive_compare_text(evidence_text, field):
        return True
    if not existing_entry:
        return False
    existing_evidence_text = join_forex_compare_evidence_text(existing_entry)
    if has_stage2_negative_forex_compare_marker(existing_evidence_text, field):
        return False
    if has_stage2_forex_field_specific_evidence(existing_entry, field, coerce=coerce):
        return True
    if has_stage2_forex_structured_compare_evidence(existing_entry, field):
        return True
    return has_stage2_forex_positive_compare_text(existing_evidence_text, field)


def has_stage25_forex_daily_change_evidence(
    entry: Dict[str, Any],
    *,
    coerce: NumberCoercer,
) -> bool:
    for key in FOREX_DAILY_CHANGE_EVIDENCE_KEYS:
        value = entry.get(key)
        if key in {
            "daily_change_basis",
            "daily_change_source",
            "daily_change_window_evidence",
        }:
            if has_forex_computed_marker(
                value,
                STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS,
                is_absence=is_stage25_forex_daily_change_absence_text,
            ):
                return True
            continue
        if key == "daily_change_source_url":
            if is_valid_forex_source_url(
                value, is_absence=is_stage25_forex_daily_change_absence_text
            ):
                return True
            continue
        if key in {"daily_change_base_date", "base_1d_date"}:
            if is_valid_forex_base_date(
                value, is_absence=is_stage25_forex_daily_change_absence_text
            ):
                return True
            continue
        if key == "daily_change_base_price" and is_valid_forex_base_price(
            value,
            is_absence=is_stage25_forex_daily_change_absence_text,
            coerce=coerce,
        ):
            return True
    return False


def copy_valid_stage25_forex_daily_change_evidence(
    target: Dict[str, Any],
    source: Dict[str, Any],
    *,
    coerce: NumberCoercer,
) -> None:
    for key in FOREX_DAILY_CHANGE_EVIDENCE_KEYS:
        target.pop(key, None)

    for key in (
        "daily_change_basis",
        "daily_change_source",
        "daily_change_window_evidence",
    ):
        value = source.get(key)
        if has_forex_computed_marker(
            value,
            STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS,
            is_absence=is_stage25_forex_daily_change_absence_text,
        ):
            target[key] = str(value).strip()

    source_url = source.get("daily_change_source_url")
    if is_valid_forex_source_url(
        source_url, is_absence=is_stage25_forex_daily_change_absence_text
    ):
        target["daily_change_source_url"] = str(source_url).strip()

    base_date = source.get("daily_change_base_date")
    if is_valid_forex_base_date(
        base_date, is_absence=is_stage25_forex_daily_change_absence_text
    ):
        target["daily_change_base_date"] = str(base_date).strip()

    base_1d_date = source.get("base_1d_date")
    if is_valid_forex_base_date(
        base_1d_date, is_absence=is_stage25_forex_daily_change_absence_text
    ):
        target["base_1d_date"] = str(base_1d_date).strip()

    base_price = coerce(source.get("daily_change_base_price"))
    if base_price is not None and is_valid_forex_base_price(
        source.get("daily_change_base_price"),
        is_absence=is_stage25_forex_daily_change_absence_text,
        coerce=coerce,
    ):
        target["daily_change_base_price"] = base_price


def copy_valid_stage25_forex_120d_change_evidence(
    target: Dict[str, Any],
    source: Dict[str, Any],
    *,
    coerce: NumberCoercer,
) -> None:
    for key in FOREX_120D_CHANGE_EVIDENCE_KEYS:
        target.pop(key, None)

    for key in (
        "change_120d_basis",
        "change_120d_source",
        "change_120d_window_evidence",
    ):
        value = source.get(key)
        if has_forex_computed_marker(
            value,
            STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS,
            is_absence=is_stage25_forex_daily_change_absence_text,
            reject_daily_prefix=True,
        ):
            target[key] = str(value).strip()

    source_url = source.get("change_120d_source_url")
    if is_valid_forex_source_url(
        source_url, is_absence=is_stage25_forex_daily_change_absence_text
    ):
        target["change_120d_source_url"] = str(source_url).strip()

    base_date = source.get("change_120d_base_date")
    if is_valid_forex_base_date(
        base_date, is_absence=is_stage25_forex_daily_change_absence_text
    ):
        target["change_120d_base_date"] = str(base_date).strip()

    base_price = coerce(source.get("change_120d_base_price"))
    if base_price is not None and is_valid_forex_base_price(
        source.get("change_120d_base_price"),
        is_absence=is_stage25_forex_daily_change_absence_text,
        coerce=coerce,
    ):
        target["change_120d_base_price"] = base_price


def has_stage25_forex_120d_change_evidence(
    entry: Dict[str, Any],
    *,
    coerce: NumberCoercer,
) -> bool:
    for key in FOREX_120D_CHANGE_EVIDENCE_KEYS:
        value = entry.get(key)
        if key in {
            "change_120d_basis",
            "change_120d_source",
            "change_120d_window_evidence",
        }:
            if has_forex_computed_marker(
                value,
                STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS,
                is_absence=is_stage25_forex_daily_change_absence_text,
                reject_daily_prefix=True,
            ):
                return True
            continue
        if key == "change_120d_source_url":
            if is_valid_forex_source_url(
                value, is_absence=is_stage25_forex_daily_change_absence_text
            ):
                return True
            continue
        if key == "change_120d_base_date":
            if is_valid_forex_base_date(
                value, is_absence=is_stage25_forex_daily_change_absence_text
            ):
                return True
            continue
        if key == "change_120d_base_price" and is_valid_forex_base_price(
            value,
            is_absence=is_stage25_forex_daily_change_absence_text,
            coerce=coerce,
        ):
            return True
    return False
