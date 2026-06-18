"""Stage2.5 schema coercion helpers."""
from typing import Any, Dict, List, Optional, Tuple

from datasource.engines.stage2_5.common import (
    _extract_source_url,
    _has_valid_value,
)
from datasource.utils.key_aliases import canonical_monetary_key


# indicator -> 类别映射，供 Stage2 results 转换
INDICATOR_CATEGORY = {
    # commodities
    "GC=F": "commodities",
    "CL=F": "commodities",
    "BZ=F": "commodities",
    "HG=F": "commodities",
    "BCOM": "commodities",
    "GSG": "commodities",
    # forex
    "USDCNY": "forex",
    "USDCNH": "forex",
    "DXY": "forex",
    # bonds
    "US10Y": "bonds",
    "CN10Y": "bonds",
    "CN10Y_CDB": "bonds",
    # fund flow
    "northbound": "fund_flow",
    "southbound": "fund_flow",
    "etf": "fund_flow",
    # macro
    "industrial": "macro_indicators",
    "industrial_sales": "macro_indicators",
    "bdi": "macro_indicators",
    "cpi": "macro_indicators",
    "ppi": "macro_indicators",
    "pmi": "macro_indicators",
    "pmi_new_orders": "macro_indicators",
    "gdp": "macro_indicators",
    # monetary
    "rrr": "monetary_policy",
    "reserve_ratio": "monetary_policy",
    "reverse_repo": "monetary_policy",
    "mlf": "monetary_policy",
    "tsf": "monetary_policy",
    "m1": "monetary_policy",
    "m2": "monetary_policy",
    "dr007": "monetary_policy",
    # stock indices
    "000001": "stock_indices",
    "000016": "stock_indices",
    "000300": "stock_indices",
    "399001": "stock_indices",
    "399006": "stock_indices",
}


def _normalize_keyed_list(payload: Any, key_field: str) -> list:
    """接受 dict/list/None，统一为 list 并补齐 key_field。"""
    if payload is None:
        return []
    if isinstance(payload, dict):
        normalized = []
        for key, value in payload.items():
            item = dict(value or {})
            item.setdefault(key_field, key)
            normalized.append(item)
        return normalized
    if isinstance(payload, list):
        return payload
    return []


def _normalize_monetary_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    normalized: Dict[str, Any] = {}
    for raw_key, value in payload.items():
        key = canonical_monetary_key(raw_key)
        if key not in normalized:
            normalized[key] = value
            continue
        existing = normalized[key] if isinstance(normalized[key], dict) else {}
        incoming = value if isinstance(value, dict) else {}
        existing_value = existing.get("current_value")
        incoming_value = incoming.get("current_value")
        if _has_valid_value(existing_value):
            continue
        if _has_valid_value(incoming_value) or raw_key == key:
            normalized[key] = value
    return normalized


def _copy_payload_metadata_fields(target: Dict[str, Any], payload: Dict[str, Any], fields: Tuple[str, ...]) -> None:  # noqa: E501
    for field in fields:
        if field in payload and payload.get(field) is not None:
            target[field] = payload.get(field)


def _copy_source_url(target: Dict[str, Any], payload: Dict[str, Any]) -> None:
    url = _extract_source_url(payload)
    if url:
        target["source_url"] = url


def _coerce_stage2_results_to_schema(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 Stage2 Unified 的 websearch_results（results 数组，含 task/extraction）转换为
    Stage2.5 期望的 schema。
    """
    if "results" not in raw or not isinstance(raw.get("results"), list):
        return raw
    schema: Dict[str, Any] = {
        "commodities": [],
        "forex": [],
        "bonds": [],
        "stock_indices": [],
        "fund_flow": {},
        "macro_indicators": {},
        "monetary_policy": {},
        "metadata": {"manual_required": []},
    }

    def _num(val):
        try:
            return float(val)
        except Exception:
            return None

    def _trend_cn(raw_trend: Any, val: Optional[float]) -> str:
        text = str(raw_trend or "").strip().lower()
        if text in {"inflow", "流入", "净流入", "net_inflow", "buy"}:
            return "流入"
        if text in {"outflow", "流出", "净流出", "net_outflow", "sell"}:
            return "流出"
        if val is not None:
            if val > 0:
                return "流入"
            if val < 0:
                return "流出"
        return "未知"

    def _candidate_url(item: Dict[str, Any], extraction: Dict[str, Any]) -> Optional[str]:  # noqa: E501
        url = extraction.get("source_url")
        if isinstance(url, str) and url.strip().startswith("http"):
            return url.strip()
        for row in item.get("raw_results") or []:
            u = row.get("url")
            if isinstance(u, str) and u.strip().startswith("http"):
                return u.strip()
        return None

    def _upsert(rows: List[Dict[str, Any]], key_field: str, payload: Dict[str, Any]) -> None:  # noqa: E501
        key_val = payload.get(key_field)
        for i, row in enumerate(rows):
            if row.get(key_field) == key_val:
                rows[i] = payload
                return
        rows.append(payload)

    def _stage2_quality_metadata(extraction: Dict[str, Any]) -> Dict[str, Any]:
        fields = (
            "is_estimated",
            "estimation_method",
            "metric_basis",
            "confidence",
            "note",
            "as_of_date",
            "report_period",
        )
        return {field: extraction.get(field) for field in fields if extraction.get(field) is not None}  # noqa: E501

    def _append_manual_skeleton(
        key: str,
        cat: str,
        task: Dict[str, Any],
        extraction: Dict[str, Any],
        reason: str,
        item: Dict[str, Any],
    ) -> None:
        src = _candidate_url(item, extraction)
        schema["metadata"]["manual_required"].append(
            {
                "indicator_key": key,
                "category": cat,
                "reason": reason,
                "source_url": src,
                "query": task.get("query"),
                "query_used": task.get("query_used"),
            }
        )
        source_text = "待人工补数(Stage2 manual_required)"
        note_text = reason
        if src:
            note_text = f"{reason} | {src}"

        if cat == "commodities":
            _upsert(
                schema["commodities"],
                "symbol",
                {
                    "symbol": key,
                    "name": key,
                    "current_price": None,
                    "unit": task.get("unit") or "",
                    "trend": "未知",
                    "source": source_text,
                    "note": note_text,
                    "source_url": src,
                },
            )
            return
        if cat == "forex":
            _upsert(
                schema["forex"],
                "pair",
                {
                    "pair": key,
                    "name": key,
                    "current_rate": None,
                    "trend": "未知",
                    "source": source_text,
                    "note": note_text,
                    "source_url": src,
                },
            )
            return
        if cat == "bonds":
            _upsert(
                schema["bonds"],
                "symbol",
                {
                    "symbol": key,
                    "name": key,
                    "current_yield": None,
                    "trend": "未知",
                    "source": source_text,
                    "note": note_text,
                    "source_url": src,
                },
            )
            return
        if cat == "stock_indices":
            _upsert(
                schema["stock_indices"],
                "symbol",
                {
                    "symbol": key,
                    "name": key,
                    "current_price": None,
                    "source": source_text,
                    "note": note_text,
                    "source_url": src,
                },
            )
            return
        if cat == "fund_flow":
            schema["fund_flow"][key] = {
                "recent_5d": _num(extraction.get("recent_5d")),
                "total_120d": _num(extraction.get("total_120d")),
                "trend": _trend_cn(extraction.get("trend"), _num(extraction.get("value"))),  # noqa: E501
                "source": source_text,
                "note": note_text,
                "source_url": src,
            }
            return
        if cat == "macro_indicators":
            schema["macro_indicators"][key] = {
                "indicator_name": key,
                "current_value": None,
                "previous_value": extraction.get("previous_value"),
                "change_rate": extraction.get("change_rate"),
                "unit": task.get("unit") or "%",
                "date": extraction.get("date") or "",
                "as_of_date": extraction.get("as_of_date") or extraction.get("report_period"),  # noqa: E501
                "value_type": extraction.get("value_type"),
                "yoy_month": extraction.get("yoy_month"),
                "yoy_ytd": extraction.get("yoy_ytd"),
                "source": source_text,
                "note": note_text,
                "source_url": src,
            }
            return
        if cat == "monetary_policy":
            schema["monetary_policy"][key] = {
                "policy_name": key,
                "current_value": None,
                "unit": task.get("unit") or "%",
                "date": extraction.get("date") or "",
                "as_of_date": extraction.get("as_of_date") or extraction.get("report_period"),  # noqa: E501
                "source": source_text,
                "note": note_text,
                "source_url": src,
            }

    # 用于 manual_required 元数据去重
    seen_manual_keys: set = set()

    for item in raw["results"]:
        task = item.get("task") or {}
        extraction = item.get("extraction") or {}
        key = task.get("indicator_key")
        if not key:
            continue
        cat = INDICATOR_CATEGORY.get(key)
        if not cat:
            continue
        manual_reason = (
            extraction.get("manual_reason")
            or extraction.get("note")
            or item.get("note")
            or "manual_required"
        )
        if item.get("manual_required") is True:
            uniq_key = f"{cat}:{key}"
            if uniq_key not in seen_manual_keys:
                _append_manual_skeleton(key, cat, task, extraction, str(manual_reason), item)  # noqa: E501
                seen_manual_keys.add(uniq_key)
            continue
        note_text = extraction.get("note") or ""
        if isinstance(note_text, str) and ("数据超过" in note_text or "需更新" in note_text):  # noqa: E501
            continue
        val = _num(extraction.get("value"))
        if val is None and cat != "fund_flow":
            uniq_key = f"{cat}:{key}"
            if uniq_key not in seen_manual_keys:
                _append_manual_skeleton(key, cat, task, extraction, "no_value_from_stage2", item)  # noqa: E501
                seen_manual_keys.add(uniq_key)
            continue
        src = _candidate_url(item, extraction)
        source = extraction.get("source_url") or extraction.get("note") or "stage2_auto_extract"  # noqa: E501
        if src:
            source_text = str(source or "stage2_auto_extract")
            if src not in source_text:
                source = f"{source_text}({src})"
        elif "stage2_auto" not in str(source).lower():
            source = f"stage2_auto_extract:{source}" if source else "stage2_auto_extract"  # noqa: E501
        if cat == "commodities":
            _upsert(
                schema["commodities"],
                "symbol",
                {
                    "symbol": key,
                    "name": key,
                    "current_price": val,
                    "unit": task.get("unit") or "",
                    "ytd_change": extraction.get("ytd_change"),
                    "trend": "未知",
                    "source": source,
                    "source_url": src,
                },
            )
        elif cat == "forex":
            _upsert(
                schema["forex"],
                "pair",
                {
                    "pair": key,
                    "name": key,
                    "current_rate": val,
                    "daily_change": extraction.get("daily_change"),
                    "change_120d": extraction.get("change_120d"),
                    "trend": extraction.get("trend") or "未知",
                    "source": source,
                    "source_url": src,
                },
            )
        elif cat == "bonds":
            _upsert(
                schema["bonds"],
                "symbol",
                {
                    "symbol": key,
                    "name": key,
                    "current_yield": val,
                    "change_5d_bp": extraction.get("change_5d_bp"),
                    "change_120d_bp": extraction.get("change_120d_bp"),
                    "trend": extraction.get("trend") or "未知",
                    "source": source,
                    "source_url": src,
                    **_stage2_quality_metadata(extraction),
                },
            )
        elif cat == "stock_indices":
            _upsert(
                schema["stock_indices"],
                "symbol",
                {
                    "symbol": key,
                    "name": key,
                    "current_price": val,
                    "source": source,
                    "source_url": src,
                },
            )
        elif cat == "fund_flow":
            recent = _num(extraction.get("recent_5d"))
            total = _num(extraction.get("total_120d"))
            if recent is None or total is None:
                uniq_key = f"{cat}:{key}"
                if uniq_key not in seen_manual_keys:
                    _append_manual_skeleton(key, cat, task, extraction, "fund_flow_window_missing", item)  # noqa: E501
                    seen_manual_keys.add(uniq_key)
                continue
            schema["fund_flow"][key] = {
                "recent_5d": recent,
                "total_120d": total,
                "trend": _trend_cn(extraction.get("trend"), recent),
                "source": source,
                "note": extraction.get("note"),
                "source_url": src,
                "is_estimated": extraction.get("is_estimated"),
                "estimation_method": extraction.get("estimation_method"),
                "confidence": extraction.get("confidence"),
                "metric_basis": extraction.get("metric_basis"),
                "window_evidence": extraction.get("window_evidence"),
                "source_tier": extraction.get("source_tier"),
                "field_retry_evidence": extraction.get("field_retry_evidence"),
            }
        elif cat == "macro_indicators":
            schema["macro_indicators"][key] = {
                "indicator_name": key,
                "current_value": val,
                "previous_value": extraction.get("previous_value"),
                "change_rate": extraction.get("change_rate"),
                "unit": task.get("unit") or "%",
                "date": extraction.get("date") or "",
                "as_of_date": extraction.get("as_of_date") or extraction.get("report_period"),  # noqa: E501
                "value_type": extraction.get("value_type"),
                "yoy_month": extraction.get("yoy_month"),
                "yoy_ytd": extraction.get("yoy_ytd"),
                "source": source,
                "source_url": src,
            }
        elif cat == "monetary_policy":
            schema["monetary_policy"][key] = {
                "policy_name": key,
                "current_value": val,
                "change_from_120d": extraction.get("change_from_120d"),
                "unit": task.get("unit") or "%",
                "date": extraction.get("date") or "",
                "as_of_date": extraction.get("as_of_date") or extraction.get("report_period"),  # noqa: E501
                "rrr_type": extraction.get("rrr_type"),
                "source": source,
                "source_url": src,
            }
    # 移除空类别，保持与原脚本兼容
    metadata = schema.get("metadata") or {}
    if isinstance(metadata, dict):
        manual_rows = metadata.get("manual_required") or []
        if manual_rows:
            deduped: List[Dict[str, Any]] = []
            seen = set()
            for row in manual_rows:
                mk = f"{row.get('category')}:{row.get('indicator_key')}"
                if mk in seen:
                    continue
                seen.add(mk)
                deduped.append(row)
            metadata["manual_required"] = deduped
        else:
            schema.pop("metadata", None)
    return {k: v for k, v in schema.items() if v}
