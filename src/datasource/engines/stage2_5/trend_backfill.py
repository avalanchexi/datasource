import json
from functools import partial
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from datasource.utils.json_io import atomic_write_json
from datasource.utils.contract_validation import validate_market_data
from datasource.utils.forex_evidence import (
    STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS as FOREX_DAILY_CHANGE_SOURCE_MARKERS,  # noqa: E501
    STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS as FOREX_120D_CHANGE_SOURCE_MARKERS,  # noqa: E501
    copy_valid_stage25_forex_120d_change_evidence,
    copy_valid_stage25_forex_daily_change_evidence,
    has_forex_computed_marker,
    has_stage25_forex_120d_change_evidence,
    has_stage25_forex_daily_change_evidence,
    is_stage25_forex_daily_change_absence_text,
    is_valid_forex_base_date,
    is_valid_forex_base_price,
    is_valid_forex_source_url,
)
from datasource.utils.fund_flow_series import (
    apply_override,
    compute_rollup,
    load_daily_series,
)
from datasource.utils.note_utils import (
    append_note_once as _append_note_once,
    append_note_to_entry as _append_note,
)
from datasource.utils.run_paths import build_run_paths_from_reference
from datasource.utils.trend_history_store import (
    DEFAULT_BASE_DIR,
    SERIES_WINDOWS,
)

from datasource.engines.stage2_5.common import (
    DEFAULT_SOURCE_LABEL,
    SOURCE_ANOMALY_LABEL,
    _apply_pipeline_quality_state,
    _calc_change_rate_pct,
    _coerce_float,
    _has_valid_value,
    _merge_quality_issues,
)
from datasource.engines.stage2_5.gap_sync import (
    _cleanup_metadata_missing,
    _refresh_stage2_gap_monitor,
    _refresh_stage2_notes,
    _rewrite_gap_monitor_after_injection,
)


def _infer_trend(
    raw_trend: Optional[str], recent_value: Optional[float]
) -> str:
    if isinstance(recent_value, (int, float)):
        if recent_value > 0:
            return "流入"
        if recent_value < 0:
            return "流出"
    return raw_trend or "未知"


def _infer_asset_trend(
    raw_trend: Optional[str],
    daily_change: Optional[float],
    ytd_change: Optional[float],
    asset_type: str = "commodity",
) -> str:
    """根据涨跌幅自动推断资产趋势方向。

    Args:
        raw_trend: 手工指定的趋势
        daily_change: 日涨跌幅(%)
        ytd_change: 年内/120日涨跌幅(%)
        asset_type: 资产类型 (commodity/bond/forex)

    Returns:
        趋势描述字符串
    """
    if raw_trend and raw_trend not in (
        "未知",
        "待WebSearch补充",
        "待 WebSearch",
    ):
        return raw_trend

    # 债券特殊处理：收益率上行=熊市，下行=牛市
    if asset_type == "bond":
        if isinstance(daily_change, (int, float)):
            if daily_change > 5:  # >5bp
                return "上行"
            elif daily_change < -5:  # <-5bp
                return "下行"
            else:
                return "平稳"
        return "未知"

    # 商品和外汇：基于涨跌幅判断
    if isinstance(ytd_change, (int, float)):
        if ytd_change > 10:
            return "强势上涨"
        elif ytd_change > 3:
            return "温和上涨"
        elif ytd_change < -10:
            return "强势下跌"
        elif ytd_change < -3:
            return "温和下跌"
        else:
            return "横盘震荡"
    elif isinstance(daily_change, (int, float)):
        if daily_change > 2:
            return "上涨"
        elif daily_change < -2:
            return "下跌"
        else:
            return "平稳"

    return "未知"


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y%m"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in ("%Y-%m", "%Y%m"):
                return datetime(dt.year, dt.month, 1)
            return dt
        except Exception:
            continue
    return None


def _load_series_records(
    category: str,
    symbol: str,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
    reference_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    series_path = base_dir / "series" / category / f"{symbol}.json"
    if not series_path.exists():
        return []
    try:
        payload = json.loads(series_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    values = (
        payload.get("values")
        if isinstance(payload.get("values"), list)
        else []
    )
    ref_dt = _parse_date(reference_date) if reference_date else None
    records: List[Dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        dt = _parse_date(item.get("date"))
        if dt is None:
            continue
        if ref_dt and dt > ref_dt:
            continue
        val = _coerce_float(item.get("value"))
        if val is None:
            continue
        records.append(
            {
                "date": dt,
                "value": float(val),
                "is_estimated": bool(item.get("is_estimated", False)),
            }
        )
    records.sort(key=lambda x: x["date"])
    return records


def _calc_change_from_trend_history(
    category: str,
    symbol: str,
    current_value: float,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
    reference_date: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """从 trend_history 计算 change_5d 和 change_120d 百分比变化（带原因信息）。"""
    result: Dict[str, Optional[float]] = {
        "change_5d": None,
        "change_120d": None,
        "change_5d_bp": None,
        "change_120d_bp": None,
        "reason_5d": None,
        "reason_120d": None,
        "base_5d_estimated": None,
        "base_120d_estimated": None,
        "base_5d_date": None,
        "base_120d_date": None,
        "latest_date": None,
    }
    if current_value is None or current_value == 0:
        result["reason_5d"] = "manual_incomplete"
        result["reason_120d"] = "manual_incomplete"
        return result

    records = _load_series_records(
        category, symbol, base_dir=base_dir, reference_date=reference_date
    )
    if not records:
        result["reason_5d"] = "trend_history_missing"
        result["reason_120d"] = "trend_history_missing"
        return result

    ref_dt = _parse_date(reference_date) if reference_date else None
    latest = records[-1]
    result["latest_date"] = latest["date"].strftime("%Y-%m-%d")

    anchor_records = records
    # 有 reference_date 时，剔除同日记录，避免“当日写入”影响基准
    if ref_dt:
        anchor_records = [
            r for r in records if r["date"].date() < ref_dt.date()
        ]

    if not anchor_records:
        result["reason_5d"] = "trend_history_insufficient"
        result["reason_120d"] = "trend_history_insufficient"
        return result

    required_5d = 5
    # 有 reference_date 表示当前值来自当日，需回看 120 交易日基准（不含当日）
    required_120d = (
        120 if ref_dt else min(121, SERIES_WINDOWS.get(category, 121))
    )

    # change_5d
    if len(anchor_records) >= required_5d:
        base_5d = anchor_records[-required_5d]
        base_5d_val = base_5d["value"]
        result["base_5d_date"] = base_5d["date"].strftime("%Y-%m-%d")
        result["base_5d_estimated"] = bool(base_5d.get("is_estimated"))
        if category == "bonds" and base_5d_val > 10:
            result["reason_5d"] = "unit_mismatch"
        elif base_5d_val != 0:
            if category == "bonds":
                result["change_5d_bp"] = (current_value - base_5d_val) * 100
            else:
                result["change_5d"] = (
                    (current_value - base_5d_val) / base_5d_val
                ) * 100
    else:
        result["reason_5d"] = "trend_history_insufficient"

    # change_120d
    if len(anchor_records) >= required_120d:
        base_120d = anchor_records[-required_120d]
        base_120d_val = base_120d["value"]
        result["base_120d_date"] = base_120d["date"].strftime("%Y-%m-%d")
        result["base_120d_estimated"] = bool(base_120d.get("is_estimated"))
        if category == "bonds" and base_120d_val > 10:
            result["reason_120d"] = "unit_mismatch"
        elif base_120d_val != 0:
            if category == "bonds":
                result["change_120d_bp"] = (
                    current_value - base_120d_val
                ) * 100
            else:
                result["change_120d"] = (
                    (current_value - base_120d_val) / base_120d_val
                ) * 100
    else:
        result["reason_120d"] = "trend_history_insufficient"

    return result


def _calc_daily_change_from_trend_history(
    category: str,
    symbol: str,
    current_value: float,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
    reference_date: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """从 trend_history 计算前一交易日变化（百分比变化）。"""
    result: Dict[str, Optional[float]] = {
        "change_1d": None,
        "reason_1d": None,
        "base_1d_estimated": None,
        "base_1d_date": None,
    }
    if current_value is None or current_value == 0:
        result["reason_1d"] = "manual_incomplete"
        return result

    records = _load_series_records(
        category, symbol, base_dir=base_dir, reference_date=reference_date
    )
    if not records:
        result["reason_1d"] = "trend_history_missing"
        return result

    ref_dt = _parse_date(reference_date) if reference_date else None
    if ref_dt:
        anchor_records = [
            r for r in records if r["date"].date() < ref_dt.date()
        ]
    else:
        anchor_records = list(records)
        # 避免同日重复写入后出现“前一日变化=0”。
        if (
            anchor_records
            and abs(anchor_records[-1]["value"] - float(current_value)) < 1e-9
        ):
            anchor_records = anchor_records[:-1]

    if not anchor_records:
        result["reason_1d"] = "trend_history_insufficient"
        return result

    base = anchor_records[-1]
    base_val = base["value"]
    result["base_1d_date"] = base["date"].strftime("%Y-%m-%d")
    result["base_1d_estimated"] = bool(base.get("is_estimated"))
    if base_val == 0:
        result["reason_1d"] = "trend_history_insufficient"
        return result

    result["change_1d"] = (
        (float(current_value) - float(base_val)) / float(base_val)
    ) * 100
    return result


def _load_event_history(
    indicator: str, *, base_dir: Path = DEFAULT_BASE_DIR
) -> List[Dict[str, Any]]:
    path = base_dir / "events" / f"{indicator}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    events = payload.get("events")
    return events if isinstance(events, list) else []


def _calc_change_from_event_history(
    indicator: str,
    current_value: Optional[float],
    reference_date: Optional[str],
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Dict[str, Optional[float]]:
    """基于事件序列估算 120 日变化，返回 change_from_120d 与原因。"""
    result = {
        "change_from_120d": None,
        "reason": None,
        "base_date": None,
        "base_estimated": None,
    }
    if current_value is None:
        return result
    events = _load_event_history(indicator, base_dir=base_dir)
    if not events:
        result["reason"] = "trend_history_missing"
        return result

    ref_dt = _parse_date(reference_date) or datetime.now()
    parsed = []
    for event in events:
        if not isinstance(event, dict):
            continue
        dt = _parse_date(event.get("release_date") or event.get("date"))
        if dt is None or dt > ref_dt:
            continue
        val = _coerce_float(event.get("value"))
        if val is None:
            continue
        parsed.append((dt, val, bool(event.get("is_estimated", False))))

    if not parsed:
        result["reason"] = "trend_history_missing"
        return result

    parsed.sort(key=lambda x: x[0])
    target_dt = ref_dt - timedelta(days=120)

    base_val = None
    base_estimated = None
    base_date = None
    for dt, val, is_est in reversed(parsed):
        if dt <= target_dt:
            base_val = val
            base_estimated = is_est
            base_date = dt
            break

    if base_val is None:
        result["reason"] = "no_previous_value"
        return result

    result["change_from_120d"] = float(current_value) - float(base_val)
    result["base_date"] = base_date.strftime("%Y-%m-%d") if base_date else None
    result["base_estimated"] = base_estimated
    return result


MACRO_CHANGE_RATE_CALIBER = {
    "cpi": "yoy_pp",
    "ppi": "yoy_pp",
    "pmi": "yoy_pp",
    "pmi_new_orders": "yoy_pp",
    "pmi_production": "yoy_pp",
    "gdp": "yoy_pp",
    "industrial": "yoy_pp",
    "industrial_sales": "yoy_pp",
    "bdi": "level_pct",
}


def _macro_change_rate(
    indicator: str,
    current: float,
    previous: float,
    *,
    unit: Optional[str] = None,
) -> Tuple[Optional[float], Optional[str]]:
    caliber = MACRO_CHANGE_RATE_CALIBER.get(indicator)
    inferred = caliber is None
    if caliber is None:
        caliber = "yoy_pp" if str(unit or "").strip() == "%" else "level_pct"

    note = "caliber_inferred" if inferred else None
    if caliber == "yoy_pp":
        return round(current - previous, 4), note

    if abs(previous) < 1e-9:
        return None, "change_rate_pct_div_by_zero"
    return round((current - previous) / abs(previous) * 100, 4), note


def _calc_prev_from_event_history(
    indicator: str,
    current_value: Optional[float],
    reference_date: Optional[str],
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Dict[str, Optional[float]]:
    """为宏观指标从事件序列回推 previous_value 与 change_rate。"""
    result = {"previous_value": None, "change_rate": None, "reason": None}
    if current_value is None:
        return result
    events = _load_event_history(indicator, base_dir=base_dir)
    if not events:
        result["reason"] = "trend_history_missing"
        return result

    def _parse_date(date_text: Optional[str]) -> Optional[datetime]:
        if not date_text:
            return None
        text = str(date_text)[:10]
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y%m%d", "%Y%m"):
            try:
                dt = datetime.strptime(text, fmt)
                if fmt == "%Y-%m":
                    return datetime(dt.year, dt.month, 1)
                if fmt == "%Y%m":
                    return datetime(dt.year, dt.month, 1)
                return dt
            except Exception:
                continue
        return None

    ref_dt = _parse_date(reference_date) or datetime.now()
    parsed = []
    if indicator in {"industrial", "industrial_sales"}:
        for event in events:
            if not isinstance(event, dict):
                continue
            period = event.get("report_period")
            if not isinstance(period, str) or not re.match(
                r"20\\d{2}-\\d{2}$", period
            ):
                continue
            dt = _parse_date(period)
            if dt is None or dt > ref_dt:
                continue
            val = _coerce_float(event.get("value"))
            if val is None:
                continue
            parsed.append((dt, val))
        if len(parsed) < 2:
            result["reason"] = "no_previous_value"
            return result
        parsed.sort(key=lambda x: x[0])
        latest_val = parsed[-1][1]
        prev_val = (
            parsed[-2][1]
            if abs(latest_val - float(current_value)) < 1e-6
            else latest_val
        )
        result["previous_value"] = prev_val
        change_rate_pct = _calc_change_rate_pct(
            float(current_value), float(prev_val)
        )
        if change_rate_pct is None:
            result["reason"] = "change_rate_pct_div_by_zero"
        else:
            result["change_rate"] = change_rate_pct
        return result
    for event in events:
        if not isinstance(event, dict):
            continue
        dt = _parse_date(event.get("release_date") or event.get("date"))
        if dt is None or dt > ref_dt:
            continue
        val = _coerce_float(event.get("value"))
        if val is None:
            continue
        parsed.append((dt, val))

    if len(parsed) < 2:
        result["reason"] = "no_previous_value"
        return result

    parsed.sort(key=lambda x: x[0])
    latest_val = parsed[-1][1]
    prev_val = (
        parsed[-2][1]
        if abs(latest_val - float(current_value)) < 1e-6
        else latest_val
    )

    result["previous_value"] = prev_val
    change_rate_pct = _calc_change_rate_pct(
        float(current_value), float(prev_val)
    )
    if change_rate_pct is None:
        result["reason"] = "change_rate_pct_div_by_zero"
    else:
        result["change_rate"] = change_rate_pct
    return result


def _should_backfill_numeric(value: Any) -> bool:
    if value in (None, "", "N/A"):
        return True
    try:
        return abs(float(value)) < 1e-9
    except Exception:
        return True


_is_forex_daily_change_absence_text = (
    is_stage25_forex_daily_change_absence_text
)
_is_valid_forex_daily_change_base_date = partial(
    is_valid_forex_base_date,
    is_absence=_is_forex_daily_change_absence_text,
)
_is_valid_forex_daily_change_source_url = partial(
    is_valid_forex_source_url,
    is_absence=_is_forex_daily_change_absence_text,
)
_is_valid_forex_change_base_price = partial(
    is_valid_forex_base_price,
    is_absence=_is_forex_daily_change_absence_text,
    coerce=_coerce_float,
)
_has_forex_daily_change_computed_marker = partial(
    has_forex_computed_marker,
    markers=FOREX_DAILY_CHANGE_SOURCE_MARKERS,
    is_absence=_is_forex_daily_change_absence_text,
)
_has_forex_120d_change_computed_marker = partial(
    has_forex_computed_marker,
    markers=FOREX_120D_CHANGE_SOURCE_MARKERS,
    is_absence=_is_forex_daily_change_absence_text,
    reject_daily_prefix=True,
)
_has_forex_daily_change_evidence = partial(
    has_stage25_forex_daily_change_evidence,
    coerce=_coerce_float,
)
_copy_valid_forex_daily_change_evidence = partial(
    copy_valid_stage25_forex_daily_change_evidence,
    coerce=_coerce_float,
)
_copy_valid_forex_120d_change_evidence = partial(
    copy_valid_stage25_forex_120d_change_evidence,
    coerce=_coerce_float,
)
_has_forex_120d_change_evidence = partial(
    has_stage25_forex_120d_change_evidence,
    coerce=_coerce_float,
)


def _is_zero_change_value(value: Any) -> bool:
    numeric = _coerce_float(value)
    return numeric is not None and abs(numeric) < 1e-12


def _should_backfill_forex_daily_change(entry: Dict[str, Any]) -> bool:
    value = _coerce_float(entry.get("daily_change"))
    if value is None:
        return True
    if abs(value) >= 1e-9:
        return False
    return not _has_forex_daily_change_evidence(entry)


def _should_backfill_forex_120d_change(entry: Dict[str, Any]) -> bool:
    value = _coerce_float(entry.get("change_120d"))
    if value is None:
        return True
    if abs(value) >= 1e-9:
        return False
    return not _has_forex_120d_change_evidence(entry)


def _usable_forex_change_value(
    entry: Dict[str, Any], field: str
) -> Optional[float]:
    value = _coerce_float(entry.get(field))
    if value is None:
        return None
    if field == "daily_change" and _should_backfill_forex_daily_change(entry):
        return None
    if field == "change_120d" and _should_backfill_forex_120d_change(entry):
        return None
    return value


def _is_zero_derived_forex_trend(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return text in {
        "flat",
        "sideways",
        "平稳",
        "横盘震荡",
        "骞崇ǔ",
        "妯洏闇囪崱",
    }


def _usable_forex_raw_trend(
    raw_trend: Any, daily_change: Optional[float], change_120d: Optional[float]
) -> Any:
    if (
        daily_change is None or change_120d is None
    ) and _is_zero_derived_forex_trend(raw_trend):
        return None
    return raw_trend


def _backfill_cdb_proxy_changes_from_cn10y(market_data: Dict[str, Any]) -> int:
    bonds = market_data.get("bonds", []) or []
    cn10y = next(
        (
            item
            for item in bonds
            if isinstance(item, dict) and item.get("symbol") == "CN10Y"
        ),
        None,
    )
    cdb = next(
        (
            item
            for item in bonds
            if isinstance(item, dict) and item.get("symbol") == "CN10Y_CDB"
        ),
        None,
    )
    if not isinstance(cn10y, dict) or not isinstance(cdb, dict):
        return 0
    if not _has_valid_value(cdb.get("current_yield")) or not bool(
        cdb.get("is_estimated")
    ):
        return 0
    basis_text = " ".join(
        str(cdb.get(field) or "")
        for field in ("source", "note", "estimation_method", "metric_basis")
    ).lower()
    if "cn10y" not in basis_text and "国债" not in basis_text:
        return 0

    changed = 0
    for field in ("change_5d_bp", "change_120d_bp"):
        if not _should_backfill_numeric(cdb.get(field)):
            continue
        proxy_value = _coerce_float(cn10y.get(field))
        if proxy_value is None:
            continue
        cdb[field] = proxy_value
        changed += 1

    if changed:
        cdb["trend"] = _infer_asset_trend(
            cdb.get("trend"),
            cdb.get("change_5d_bp"),
            cdb.get("change_120d_bp"),
            "bond",
        )
        cdb["note"] = _append_note_once(
            str(cdb.get("note") or ""),
            "cn10y_proxy_change_basis",
        )
    return changed


def _remove_note_markers(
    entry: Dict[str, Any], markers: Tuple[str, ...]
) -> None:
    """从 note 中移除已过期的原因标记（如 no_previous_value）。"""
    note = entry.get("note")
    if not isinstance(note, str) or not note:
        return
    parts = [part for part in note.split("；") if part]
    filtered = [
        part for part in parts if not any(marker in part for marker in markers)
    ]
    entry["note"] = "；".join(filtered)


def _record_backfill_issue(
    metadata: Dict[str, Any],
    category: str,
    key: str,
    field: str,
    reason: str,
) -> None:
    issues = metadata.setdefault("trend_backfill_issues", [])
    issue = {
        "category": category,
        "key": key,
        "field": field,
        "reason": reason,
    }
    if issue not in issues:
        issues.append(issue)


_TREND_CONF_RANK = {
    "low": 0,
    "medium": 1,
    "high": 2,
}


def _merge_trend_confidence(entry: Dict[str, Any], level: str) -> None:
    normalized = str(level or "").strip().lower()
    if normalized not in _TREND_CONF_RANK:
        return
    existing = str(entry.get("trend_history_confidence") or "").strip().lower()
    if (
        existing not in _TREND_CONF_RANK
        or _TREND_CONF_RANK[normalized] < _TREND_CONF_RANK[existing]
    ):
        entry["trend_history_confidence"] = normalized


def _derive_trend_confidence(
    hist: Dict[str, Any],
    *,
    used_5d: bool,
    used_120d: bool,
) -> Tuple[Optional[str], Optional[str]]:
    if not used_5d and not used_120d:
        return None, None
    reasons: List[str] = []
    if used_5d and hist.get("reason_5d"):
        reasons.append(str(hist.get("reason_5d")))
    if used_120d and hist.get("reason_120d"):
        reasons.append(str(hist.get("reason_120d")))
    if reasons:
        reason = "trend_history_reason:" + ",".join(sorted(set(reasons)))
        return "low", reason
    if (used_5d and hist.get("base_5d_estimated")) or (
        used_120d and hist.get("base_120d_estimated")
    ):
        return "low", "trend_history_base_estimated"
    if used_5d and used_120d:
        return "high", None
    return "medium", "trend_history_partial_window"


def _backfill_trend_changes(
    market_data: Dict[str, Any],
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Dict[str, int]:
    """对全量指标回读 trend_history，补齐缺失的变化值。"""
    stats = {
        "bonds": 0,
        "forex": 0,
        "commodities": 0,
        "stock_indices": 0,
        "fund_flow": 0,
        "macro_indicators": 0,
        "monetary_policy": 0,
    }
    metadata = (
        market_data.get("metadata", {})
        if isinstance(market_data, dict)
        else {}
    )
    reference_date = (
        market_data.get("metadata", {}).get("date")
        or market_data.get("metadata", {}).get("end_date")
        or market_data.get("metadata", {}).get("start_date")
    )

    for bond in market_data.get("bonds", []) or []:
        symbol = bond.get("symbol")
        current = _coerce_float(bond.get("current_yield"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history(
            "bonds",
            symbol,
            current,
            base_dir=base_dir,
            reference_date=reference_date,
        )
        used_hist_120d = False
        used_hist_5d = False
        if _should_backfill_numeric(bond.get("change_120d_bp")):
            if hist.get("change_120d_bp") is not None:
                bond["change_120d_bp"] = round(
                    float(hist["change_120d_bp"]), 2
                )
                stats["bonds"] += 1
                used_hist_120d = True
            else:
                bond["change_120d_bp"] = None
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(
                    metadata, "bonds", symbol, "change_120d_bp", reason
                )
                _append_note(bond, f"reason={reason}")
        if bond.get("change_5d_bp") is None:
            if hist.get("change_5d_bp") is not None:
                bond["change_5d_bp"] = round(float(hist["change_5d_bp"]), 2)
                stats["bonds"] += 1
                used_hist_5d = True
            else:
                bond["change_5d_bp"] = None
                reason = hist.get("reason_5d") or "trend_history_missing"
                _record_backfill_issue(
                    metadata, "bonds", symbol, "change_5d_bp", reason
                )
                _append_note(bond, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (
            used_hist_5d and hist.get("base_5d_estimated")
        ):
            _append_note(bond, "trend_history_base_estimated")
        confidence, confidence_reason = _derive_trend_confidence(
            hist,
            used_5d=used_hist_5d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(bond, confidence)
        if confidence_reason:
            _append_note(bond, confidence_reason)
        if bond.get("trend") in (
            None,
            "未知",
            "待WebSearch补充",
            "待 WebSearch",
        ):
            bond["trend"] = _infer_asset_trend(
                None,
                bond.get("change_5d_bp"),
                bond.get("change_120d_bp"),
                "bond",
            )
    stats["bonds"] += _backfill_cdb_proxy_changes_from_cn10y(market_data)

    for fx in market_data.get("forex", []) or []:
        symbol = fx.get("pair")
        current = _coerce_float(fx.get("current_rate"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history(
            "forex",
            symbol,
            current,
            base_dir=base_dir,
            reference_date=reference_date,
        )
        daily_hist = _calc_daily_change_from_trend_history(
            "forex",
            symbol,
            current,
            base_dir=base_dir,
            reference_date=reference_date,
        )
        used_hist_120d = False
        used_hist_1d = False
        existing_fx_evidence = dict(fx)
        _copy_valid_forex_daily_change_evidence(fx, existing_fx_evidence)
        _copy_valid_forex_120d_change_evidence(fx, existing_fx_evidence)
        should_backfill_daily = _should_backfill_forex_daily_change(fx)
        should_backfill_120d = _should_backfill_forex_120d_change(fx)
        if should_backfill_120d:
            if hist.get("change_120d") is not None:
                fx["change_120d"] = round(float(hist["change_120d"]), 2)
                _copy_valid_forex_120d_change_evidence(
                    fx,
                    {
                        "change_120d_basis": "trend_history",
                        "change_120d_base_date": hist.get("base_120d_date"),
                    },
                )
                stats["forex"] += 1
                used_hist_120d = True
            else:
                fx["change_120d"] = None
                _copy_valid_forex_120d_change_evidence(fx, {})
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(
                    metadata, "forex", symbol, "change_120d", reason
                )
                _append_note(fx, f"reason={reason}")
        if should_backfill_daily:
            if daily_hist.get("change_1d") is not None:
                fx["daily_change"] = round(float(daily_hist["change_1d"]), 2)
                _copy_valid_forex_daily_change_evidence(
                    fx,
                    {
                        "daily_change_basis": "trend_history",
                        "daily_change_base_date": daily_hist.get(
                            "base_1d_date"
                        ),
                    },
                )
                stats["forex"] += 1
                used_hist_1d = True
            else:
                fx["daily_change"] = None
                _copy_valid_forex_daily_change_evidence(fx, {})
                reason = daily_hist.get("reason_1d") or "trend_history_missing"
                _record_backfill_issue(
                    metadata, "forex", symbol, "daily_change", reason
                )
                _append_note(fx, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (
            used_hist_1d and daily_hist.get("base_1d_estimated")
        ):
            _append_note(fx, "trend_history_base_estimated")
        confidence, confidence_reason = _derive_trend_confidence(
            hist,
            used_5d=used_hist_1d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(fx, confidence)
        if confidence_reason:
            _append_note(fx, confidence_reason)
        raw_trend = fx.get("trend")
        trend_daily_change = _usable_forex_change_value(fx, "daily_change")
        trend_120d_change = _usable_forex_change_value(fx, "change_120d")
        usable_raw_trend = _usable_forex_raw_trend(
            raw_trend, trend_daily_change, trend_120d_change
        )
        if usable_raw_trend in (
            None,
            "未知",
            "待WebSearch补充",
            "待 WebSearch",
        ):
            fx["trend"] = _infer_asset_trend(
                None,
                trend_daily_change,
                trend_120d_change,
                "forex",
            )
        else:
            fx["trend"] = usable_raw_trend

    for comm in market_data.get("commodities", []) or []:
        symbol = comm.get("symbol")
        current = _coerce_float(comm.get("current_price"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history(
            "commodities",
            symbol,
            current,
            base_dir=base_dir,
            reference_date=reference_date,
        )
        daily_hist = _calc_daily_change_from_trend_history(
            "commodities",
            symbol,
            current,
            base_dir=base_dir,
            reference_date=reference_date,
        )
        used_hist_120d = False
        used_hist_1d = False
        if _should_backfill_numeric(comm.get("change_120d")):
            if hist.get("change_120d") is not None:
                comm["change_120d"] = round(float(hist["change_120d"]), 2)
                comm["change_120d_basis"] = "trend_history"
                stats["commodities"] += 1
                used_hist_120d = True
            else:
                comm["change_120d"] = None
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(
                    metadata, "commodities", symbol, "change_120d", reason
                )
                _append_note(comm, f"reason={reason}")
        if comm.get("daily_change") is None:
            if daily_hist.get("change_1d") is not None:
                comm["daily_change"] = round(float(daily_hist["change_1d"]), 2)
                comm["daily_change_basis"] = "change_1d"
                stats["commodities"] += 1
                used_hist_1d = True
            else:
                comm["daily_change"] = None
                reason = daily_hist.get("reason_1d") or "trend_history_missing"
                _record_backfill_issue(
                    metadata, "commodities", symbol, "daily_change", reason
                )
                _append_note(comm, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (
            used_hist_1d and daily_hist.get("base_1d_estimated")
        ):
            _append_note(comm, "trend_history_base_estimated")
        confidence, confidence_reason = _derive_trend_confidence(
            hist,
            used_5d=used_hist_1d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(comm, confidence)
        if confidence_reason:
            _append_note(comm, confidence_reason)
        if comm.get("trend") in (
            None,
            "未知",
            "待WebSearch补充",
            "待 WebSearch",
        ):
            comm["trend"] = _infer_asset_trend(
                None,
                comm.get("daily_change"),
                (
                    comm.get("ytd_change")
                    if comm.get("ytd_change") is not None
                    else comm.get("change_120d")
                ),
                "commodity",
            )

    for idx in market_data.get("stock_indices", []) or []:
        symbol = idx.get("symbol")
        current = _coerce_float(idx.get("current_price"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history(
            "stock_indices",
            symbol,
            current,
            base_dir=base_dir,
            reference_date=reference_date,
        )
        used_hist_120d = False
        used_hist_5d = False
        if _should_backfill_numeric(idx.get("change_120d")):
            if hist.get("change_120d") is not None:
                idx["change_120d"] = round(float(hist["change_120d"]), 2)
                stats["stock_indices"] += 1
                used_hist_120d = True
            else:
                idx["change_120d"] = None
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(
                    metadata, "stock_indices", symbol, "change_120d", reason
                )
                _append_note(idx, f"reason={reason}")
        if idx.get("change_5d") is None:
            if hist.get("change_5d") is not None:
                idx["change_5d"] = round(float(hist["change_5d"]), 2)
                stats["stock_indices"] += 1
                used_hist_5d = True
            else:
                idx["change_5d"] = None
                reason = hist.get("reason_5d") or "trend_history_missing"
                _record_backfill_issue(
                    metadata, "stock_indices", symbol, "change_5d", reason
                )
                _append_note(idx, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (
            used_hist_5d and hist.get("base_5d_estimated")
        ):
            _append_note(idx, "trend_history_base_estimated")
        confidence, confidence_reason = _derive_trend_confidence(
            hist,
            used_5d=used_hist_5d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(idx, confidence)
        if confidence_reason:
            _append_note(idx, confidence_reason)

    # fund_flow rollups from daily series
    for key, flow in (market_data.get("fund_flow", {}) or {}).items():
        if not isinstance(flow, dict):
            continue
        if not (
            _should_backfill_numeric(flow.get("recent_5d"))
            or _should_backfill_numeric(flow.get("total_120d"))
        ):
            continue
        daily_series = load_daily_series(key, base_dir=base_dir)
        if not daily_series:
            continue

        override_value = _coerce_float(flow.get("current_value"))
        override_date = (
            flow.get("current_date") or flow.get("date") or reference_date
        )
        if override_value is not None:
            daily_series = apply_override(
                daily_series, override_value, override_date
            )

        recent_5d, full5, used_date, _ = compute_rollup(
            daily_series, end_date=reference_date, window=5
        )
        total_120d, full120, used_date_120, _ = compute_rollup(
            daily_series, end_date=reference_date, window=120
        )
        if recent_5d is not None and _should_backfill_numeric(
            flow.get("recent_5d")
        ):
            flow["recent_5d"] = round(float(recent_5d), 2)
            stats["fund_flow"] += 1
        if total_120d is not None and _should_backfill_numeric(
            flow.get("total_120d")
        ):
            flow["total_120d"] = round(float(total_120d), 2)
            stats["fund_flow"] += 1

        trend_base = flow.get("recent_5d")
        if flow.get("trend") in (
            None,
            "未知",
            "待获取",
            "待WebSearch补充",
            "待 WebSearch",
        ):
            flow["trend"] = _infer_trend(flow.get("trend"), trend_base)

        anomaly = any(
            value == 0
            for value in (flow.get("recent_5d"), flow.get("total_120d"))
            if value is not None
        )
        flow["source"] = (
            SOURCE_ANOMALY_LABEL if anomaly else DEFAULT_SOURCE_LABEL
        )
        note_parts: List[str] = []
        existing_note = flow.get("note")
        if isinstance(existing_note, str) and existing_note:
            note_parts.append(existing_note)
        note_parts.append(f"日度序列回算:截至{used_date_120 or used_date}")
        if override_value is not None:
            note_parts.append("当日值参考新闻")
        if not full5 or not full120:
            note_parts.append("window不足已估计")
        flow["note"] = "；".join(note_parts)

    # macro indicators previous_value / change_rate
    for key, indicator in (
        market_data.get("macro_indicators", {}) or {}
    ).items():
        if not isinstance(indicator, dict):
            continue
        current = _coerce_float(indicator.get("current_value"))
        if current is None:
            continue
        prev_missing = indicator.get("previous_value") is None
        change_missing = indicator.get("change_rate") is None
        if prev_missing or change_missing:
            hist_prev = _calc_prev_from_event_history(
                key, current, reference_date, base_dir=base_dir
            )
            if prev_missing and hist_prev.get("previous_value") is not None:
                indicator["previous_value"] = hist_prev.get("previous_value")
            if change_missing and hist_prev.get("change_rate") is not None:
                indicator["change_rate"] = hist_prev.get("change_rate")
            reason = hist_prev.get("reason") or "manual_incomplete"
            if indicator.get("previous_value") is None:
                _append_note(indicator, f"reason={reason}")
                _record_backfill_issue(
                    metadata, "macro_indicators", key, "previous_value", reason
                )
            if indicator.get("change_rate") is None:
                reason = hist_prev.get("reason") or "manual_incomplete"
                _append_note(indicator, f"reason={reason}")
                _record_backfill_issue(
                    metadata, "macro_indicators", key, "change_rate", reason
                )
            if (
                indicator.get("previous_value") is not None
                and indicator.get("change_rate") is not None
            ):
                _remove_note_markers(
                    indicator, ("reason=no_previous_value", "无前值可比")
                )
            stats["macro_indicators"] += 1

    # monetary policy change_from_120d
    for key, policy in (market_data.get("monetary_policy", {}) or {}).items():
        if not isinstance(policy, dict):
            continue
        current = _coerce_float(policy.get("current_value"))
        if current is None:
            continue
        if policy.get("change_from_120d") is None:
            hist = _calc_change_from_event_history(
                key, current, reference_date, base_dir=base_dir
            )
            used_hist_120d = False
            if hist.get("change_from_120d") is not None:
                policy["change_from_120d"] = hist.get("change_from_120d")
                used_hist_120d = True
            reason = hist.get("reason")
            if reason:
                if reason == "no_previous_value":
                    _append_note(policy, "无前值可比")
                _append_note(policy, f"reason={reason}")
                _record_backfill_issue(
                    metadata,
                    "monetary_policy",
                    key,
                    "change_from_120d",
                    reason,
                )
            elif used_hist_120d:
                _remove_note_markers(
                    policy, ("reason=no_previous_value", "无前值可比")
                )
            if hist.get("base_estimated"):
                policy["is_estimated"] = True
                _append_note(policy, "trend_history_base_estimated")
                if used_hist_120d:
                    _merge_trend_confidence(policy, "low")
            elif used_hist_120d:
                _merge_trend_confidence(policy, "high")
            stats["monetary_policy"] += 1

    return stats


def _run_post_write_trend_backfill(
    market_data: Dict[str, Any],
    output_path: Path,
    *,
    base_dir: Optional[Path] = None,
) -> Dict[str, int]:
    """在 trend_history 最终写入后，基于最新明细再回填一轮变化值。"""
    metadata = market_data.setdefault("metadata", {})
    metadata["trend_backfill_issues"] = []

    if base_dir is None:
        stats = _backfill_trend_changes(market_data)
    else:
        stats = _backfill_trend_changes(market_data, base_dir=base_dir)
    gap_summary = _refresh_stage2_gap_monitor(market_data)
    _refresh_stage2_notes(metadata, gap_summary)
    _cleanup_metadata_missing(metadata, market_data)
    _apply_pipeline_quality_state(market_data)

    validate_market_data(market_data)
    atomic_write_json(market_data, output_path)
    return stats


def _sync_backfill_issues_to_logs(
    market_data: Dict[str, Any],
    *,
    date_override: Optional[str] = None,
    gap_monitor_path: Optional[Path] = None,
) -> None:
    """将趋势派生失败原因和非阻断告警写入 observability，并按当前状态重写当日 gap_monitor。"""
    metadata = (
        market_data.get("metadata", {})
        if isinstance(market_data, dict)
        else {}
    )
    issues = metadata.get("trend_backfill_issues") or []
    non_blocking_warnings = metadata.get("non_blocking_warnings") or []
    run_paths = build_run_paths_from_reference(
        date=date_override,
        payload=market_data,
        fallback_to_today=True,
    )

    _rewrite_gap_monitor_after_injection(
        market_data,
        date_override=date_override,
        gap_monitor_path=gap_monitor_path,
        extra_issues=issues,
    )

    if not issues and not non_blocking_warnings:
        return

    observability_path = run_paths.observability
    payload: Dict[str, Any] = {}
    if observability_path.exists():
        try:
            payload = (
                json.loads(observability_path.read_text(encoding="utf-8"))
                or {}
            )
        except Exception:
            payload = {}
    payload.setdefault("generated_at", datetime.now().isoformat())
    payload["data_quality_issues"] = _merge_quality_issues(
        payload.get("data_quality_issues", []), issues
    )

    existing_warnings = payload.get("non_blocking_warnings", [])
    if not isinstance(existing_warnings, list):
        existing_warnings = []
    merged_warnings: List[Dict[str, Any]] = []
    seen = set()
    for row in list(existing_warnings) + list(non_blocking_warnings or []):
        if not isinstance(row, dict):
            continue
        sig = (
            row.get("code"),
            row.get("key"),
            row.get("source_url"),
            row.get("message"),
        )
        if sig in seen:
            continue
        seen.add(sig)
        merged_warnings.append(row)
    if merged_warnings:
        payload["non_blocking_warnings"] = merged_warnings

    atomic_write_json(payload, observability_path)
