"""Stage2.5 gap and missing-items synchronization helpers."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from datasource.engines.stage2_5.common import (
    _apply_pipeline_quality_state,
    _extract_source_url,
    _has_valid_value,
    _is_estimated_allowlisted_entry,
    _is_placeholder_numeric,
    _merge_quality_issues,
)
from datasource.utils.key_aliases import (
    MONETARY_KEY_ALIASES,
    canonical_monetary_key,
)
from datasource.utils.missing_items import append_missing_item
from datasource.utils.run_paths import build_run_paths_from_reference


MONETARY_KEY_MAP = MONETARY_KEY_ALIASES


def _collect_missing_source_urls(websearch_data: Dict[str, Any]) -> List[str]:
    missing: List[str] = []

    for entry in websearch_data.get("commodities", []) or []:
        symbol = entry.get("symbol") or "unknown"
        if (
            _has_valid_value(entry.get("current_price"))
            and not _extract_source_url(entry)
        ):
            missing.append(f"commodities.{symbol}")

    for entry in websearch_data.get("forex", []) or []:
        pair = entry.get("pair") or "unknown"
        if (
            _has_valid_value(entry.get("current_rate"))
            and not _extract_source_url(entry)
        ):
            missing.append(f"forex.{pair}")

    for entry in websearch_data.get("bonds", []) or []:
        symbol = entry.get("symbol") or "unknown"
        if (
            _has_valid_value(entry.get("current_yield"))
            and not _extract_source_url(entry)
        ):
            missing.append(f"bonds.{symbol}")

    for entry in websearch_data.get("stock_indices", []) or []:
        symbol = entry.get("symbol") or "unknown"
        if (
            _has_valid_value(entry.get("current_price"))
            and not _extract_source_url(entry)
        ):
            missing.append(f"stock_indices.{symbol}")

    for key, payload in (websearch_data.get("macro_indicators") or {}).items():
        if (
            _has_valid_value(payload.get("current_value"))
            and not _extract_source_url(payload)
        ):
            missing.append(f"macro_indicators.{key}")

    for key, payload in (websearch_data.get("monetary_policy") or {}).items():
        if (
            _has_valid_value(payload.get("current_value"))
            and not _extract_source_url(payload)
        ):
            missing.append(f"monetary_policy.{key}")

    for key, payload in (websearch_data.get("fund_flow") or {}).items():
        has_value = _has_valid_value(
            payload.get("recent_5d")
        ) or _has_valid_value(payload.get("total_120d"))
        has_value = has_value or _has_valid_value(payload.get("current_value"))
        if has_value and not _extract_source_url(payload):
            missing.append(f"fund_flow.{key}")

    return missing


def _remove_missing_item(
    metadata: Dict[str, Any],
    category: str,
    key: str,
) -> None:
    missing = metadata.get('missing_items')
    if not missing or category not in missing:
        return
    targets = {str(key)}
    if category == "monetary_policy":
        canonical = canonical_monetary_key(key)
        targets.add(canonical)
        targets.update(
            alias
            for alias, mapped in MONETARY_KEY_MAP.items()
            if mapped == canonical
        )
    cleaned = []
    for item in missing[category]:
        if isinstance(item, dict):
            item_key = item.get('key') or item.get('indicator_key')
            if str(item_key) in targets:
                continue
        else:
            if str(item) in targets:
                continue
        cleaned.append(item)
    if cleaned:
        missing[category] = cleaned
    else:
        missing.pop(category, None)


def _remove_top_missing(market_data: Dict[str, Any], key: str) -> None:
    """
    同步清理顶层 missing_items 列表，避免已补齐的缺口再次触发 Stage3 校验。
    """
    missing = market_data.get('missing_items')
    if not isinstance(missing, list):
        return
    targets = {str(key)}
    canonical = canonical_monetary_key(key)
    targets.add(canonical)
    targets.update(
        alias
        for alias, mapped in MONETARY_KEY_MAP.items()
        if mapped == canonical
    )
    filtered = []
    for item in missing:
        if isinstance(item, dict):
            item_key = item.get('key') or item.get('indicator_key')
            if str(item_key) in targets:
                continue
        elif str(item) in targets:
            continue
        filtered.append(item)
    market_data['missing_items'] = filtered


def _remove_top_missing_on_skip(
    market_data: Dict[str, Any],
    key: str,
    entry: Optional[Dict[str, Any]],
) -> None:
    """
    已有有效值但跳过注入时，仍清理顶层 missing_items。
    """
    if (
        isinstance(entry, dict)
        and _has_valid_value(entry.get("current_value"))
    ):
        _remove_top_missing(market_data, key)


def _is_missing_item_filled(
    market_data: Dict[str, Any],
    category: str,
    key: str,
) -> bool:
    if category in ('macro_indicators', 'monetary_policy'):
        entry = market_data.get(category, {}).get(key)
        if not isinstance(entry, dict):
            return False
        if not _has_valid_value(entry.get('current_value')):
            return False
        if entry.get("is_stale"):
            return False
        if entry.get('is_estimated') and not _is_estimated_allowlisted_entry(
            category,
            key,
            entry,
        ):
            return False
        if category == 'macro_indicators':
            return (
                entry.get('previous_value') is not None
                and entry.get('change_rate') is not None
            )
        return entry.get('change_from_120d') is not None
    if category == 'fund_flow':
        entry = market_data.get('fund_flow', {}).get(key)
        if not isinstance(entry, dict):
            return False
        return _has_valid_value(entry.get('recent_5d')) and _has_valid_value(
            entry.get('total_120d')
        )
    if category == 'commodities':
        for item in market_data.get('commodities', []):
            if item.get('symbol') == key:
                if (
                    item.get('is_estimated')
                    and not _is_estimated_allowlisted_entry(
                        'commodities',
                        key,
                        item,
                    )
                ):
                    return False
                return _has_valid_value(item.get('current_price'))
        return False
    if category == 'forex':
        for item in market_data.get('forex', []):
            if item.get('pair') == key:
                if (
                    item.get('is_estimated')
                    and not _is_estimated_allowlisted_entry(
                        'forex',
                        key,
                        item,
                    )
                ):
                    return False
                return _has_valid_value(item.get('current_rate'))
        return False
    if category == 'bonds':
        for item in market_data.get('bonds', []):
            if item.get('symbol') == key:
                if (
                    item.get('is_estimated')
                    and not _is_estimated_allowlisted_entry(
                        'bonds',
                        key,
                        item,
                    )
                ):
                    return False
                return _has_valid_value(item.get('current_yield'))
        return False
    if category == 'stock_indices':
        for item in market_data.get('stock_indices', []):
            if item.get('symbol') == key:
                if (
                    item.get('is_estimated')
                    and not _is_estimated_allowlisted_entry(
                        'stock_indices',
                        key,
                        item,
                    )
                ):
                    return False
                return _has_valid_value(item.get('current_price'))
        return False
    return False


def _refresh_stage2_gap_monitor(payload: Dict[str, Any]) -> Dict[str, int]:
    commodities = payload.get('commodities', [])
    bonds = payload.get('bonds', [])
    summary = {
        'commodities': sum(
            1
            for item in commodities
            if _is_placeholder_numeric(item.get('current_price'))
        ),
        'bonds': sum(
            1
            for item in bonds
            if _is_placeholder_numeric(item.get('current_yield'))
        ),
    }
    payload.setdefault('metadata', {})['stage2_gap_monitor'] = summary
    return summary


def _refresh_stage2_notes(
    metadata: Dict[str, Any],
    gap_summary: Dict[str, int],
) -> None:
    notes = metadata.setdefault('stage2_notes', [])
    filtered = [
        note for note in notes
        if not note.startswith("Stage2: 行情缺口仍存在")
        and not note.startswith("Stage2: Yahoo Fallback")
    ]
    summary_text = (
        "Stage2.5: WebSearch注入完成 "
        f"(commodities={gap_summary['commodities']}, "
        f"bonds={gap_summary['bonds']})."
    )
    if summary_text not in filtered:
        filtered.append(summary_text)
    metadata['stage2_notes'] = filtered


def _cleanup_metadata_missing(
    metadata: Dict[str, Any],
    market_data: Dict[str, Any],
) -> None:
    """根据实际填充情况清理 metadata.missing_items，避免 Stage3 误阻断。"""
    missing = metadata.get('missing_items')
    if not isinstance(missing, dict):
        return
    cleaned: Dict[str, list] = {}
    for category, items in missing.items():
        if not items:
            continue
        kept = []
        for item in items:
            key = None
            if isinstance(item, dict):
                key = item.get('key') or item.get('indicator_key')
            elif isinstance(item, str):
                key = item
            check_key = (
                canonical_monetary_key(key)
                if category == "monetary_policy"
                else key
            )
            if key and _is_missing_item_filled(
                market_data,
                category,
                check_key,
            ):
                continue
            if item:
                kept.append(item)
        if kept:
            cleaned[category] = kept
    if cleaned:
        metadata['missing_items'] = cleaned
    else:
        metadata.pop('missing_items', None)


def _append_missing_item(
    market_data: Dict[str, Any],
    category: str,
    key: str,
    reason: str,
) -> None:
    """
    将质量阻断项写回 metadata/top-level missing_items，确保 Stage3 能硬阻断。
    """
    canonical_key = (
        canonical_monetary_key(key)
        if category == "monetary_policy"
        else key
    )
    append_missing_item(market_data, category, canonical_key, reason)


def _collect_unresolved_gap_items(market_data: Dict[str, Any]) -> List[str]:
    """收集仍未补齐的缺口项，用于重写 gap_monitor.manual_required。"""
    unresolved: List[str] = []
    metadata = (
        market_data.get("metadata", {})
        if isinstance(market_data, dict)
        else {}
    )
    metadata_missing = metadata.get("missing_items", {})
    if isinstance(metadata_missing, dict):
        for category, items in metadata_missing.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    key = item.get("key") or item.get("indicator_key")
                else:
                    key = item
                if not key:
                    continue
                key_str = str(key)
                if _is_missing_item_filled(market_data, category, key_str):
                    continue
                unresolved.append(key_str)

    top_missing = market_data.get("missing_items", [])
    if isinstance(top_missing, list):
        for item in top_missing:
            if isinstance(item, dict):
                key = item.get("key") or item.get("indicator_key")
            else:
                key = item
            if key:
                unresolved.append(str(key))

    deduped: List[str] = []
    seen = set()
    for key in unresolved:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _rewrite_gap_monitor_after_injection(
    market_data: Dict[str, Any],
    *,
    date_override: Optional[str] = None,
    gap_monitor_path: Optional[Path] = None,
    extra_issues: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """按当前 market_data 状态重写 gap_monitor，避免遗留旧 manual_required。"""
    run_paths = build_run_paths_from_reference(
        date=date_override,
        payload=market_data,
        fallback_to_today=True,
    )
    target_path = gap_monitor_path or run_paths.gap_monitor

    state = _apply_pipeline_quality_state(market_data)
    merged_issues = _merge_quality_issues(
        state.get("quality_blockers", []),
        extra_issues or [],
    )
    gap_view = (
        state.get("gap_monitor_view", {})
        if isinstance(state, dict)
        else {}
    )

    payload: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "manual_required": list(gap_view.get("manual_required") or []),
        "pending_tasks": list(gap_view.get("pending_tasks") or []),
        "data_quality_issues": merged_issues,
        "quality_blockers": list(state.get("quality_blockers") or []),
    }

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target_path
