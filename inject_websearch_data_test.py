#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI WebSearch数据注入脚本 (测试版)
将websearch_results注入到market_data_enhanced文件中
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple

from datasource.models.market_data_contract import FundFlowData
from datasource.utils.trend_history_store import write_from_market_data, DEFAULT_BASE_DIR, SERIES_WINDOWS
from datasource.utils.fund_flow_series import apply_override, compute_rollup, load_daily_series
from datasource.utils.quality_metrics import write_quality_metrics
from datasource.utils.policy_rules import evaluate_policy, write_policy_evaluation

FUND_FLOW_KEY_MAP = {
    "etf_flow": "etf",
    "margin_trading": "margin",
}

MONETARY_KEY_MAP = {
    "reverse_repo_7d": "reverse_repo",
    "mlf_rate": "mlf",
    "tsf_growth": "tsf",
    "m1_growth": "m1",
    "m2_growth": "m2",
    "rrr": "reserve_ratio",
}

# 宏观指标键名映射：注入脚本键名 → Stage2/market_data 规范键名
MACRO_KEY_MAP = {
    "industrial_production": "industrial",  # 常见混淆
    "industrial_output": "industrial",
}

# indicator → 类别映射，供 Stage2 results 转换
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


def _extract_source_url(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("source_url", "sourceUrl", "url"):
        url = payload.get(key)
        if isinstance(url, str) and url.strip().startswith("http"):
            return url.strip()
    source = payload.get("source")
    if isinstance(source, str) and "http" in source:
        return source
    note = payload.get("note")
    if isinstance(note, str) and "http" in note:
        return note
    return None


def _attach_source_url(payload: Dict[str, Any]) -> None:
    url = payload.get("source_url")
    if not isinstance(url, str) or not url.strip().startswith("http"):
        return
    if _extract_source_url(payload):
        return
    source = payload.get("source")
    if isinstance(source, str) and source.strip():
        payload["source"] = f"{source} | {url}"
    else:
        payload["source"] = url


def _collect_missing_source_urls(websearch_data: Dict[str, Any]) -> List[str]:
    missing: List[str] = []

    for entry in websearch_data.get("commodities", []) or []:
        symbol = entry.get("symbol") or "unknown"
        if _has_valid_value(entry.get("current_price")) and not _extract_source_url(entry):
            missing.append(f"commodities.{symbol}")

    for entry in websearch_data.get("forex", []) or []:
        pair = entry.get("pair") or "unknown"
        if _has_valid_value(entry.get("current_rate")) and not _extract_source_url(entry):
            missing.append(f"forex.{pair}")

    for entry in websearch_data.get("bonds", []) or []:
        symbol = entry.get("symbol") or "unknown"
        if _has_valid_value(entry.get("current_yield")) and not _extract_source_url(entry):
            missing.append(f"bonds.{symbol}")

    for entry in websearch_data.get("stock_indices", []) or []:
        symbol = entry.get("symbol") or "unknown"
        if _has_valid_value(entry.get("current_price")) and not _extract_source_url(entry):
            missing.append(f"stock_indices.{symbol}")

    for key, payload in (websearch_data.get("macro_indicators") or {}).items():
        if _has_valid_value(payload.get("current_value")) and not _extract_source_url(payload):
            missing.append(f"macro_indicators.{key}")

    for key, payload in (websearch_data.get("monetary_policy") or {}).items():
        if _has_valid_value(payload.get("current_value")) and not _extract_source_url(payload):
            missing.append(f"monetary_policy.{key}")

    for key, payload in (websearch_data.get("fund_flow") or {}).items():
        has_value = _has_valid_value(payload.get("recent_5d")) or _has_valid_value(payload.get("total_120d"))
        has_value = has_value or _has_valid_value(payload.get("current_value"))
        if has_value and not _extract_source_url(payload):
            missing.append(f"fund_flow.{key}")

    return missing


def _is_placeholder_numeric(value: Any) -> bool:
    if value in (None, "", "N/A"):
        return True
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return True
    if abs(numeric) < 1e-9:
        return True
    return abs(numeric - 7.13) < 1e-3


def _has_valid_value(value: Any) -> bool:
    return not _is_placeholder_numeric(value)


def _remove_missing_item(metadata: Dict[str, Any], category: str, key: str) -> None:
    missing = metadata.get('missing_items')
    if not missing or category not in missing:
        return
    cleaned = []
    for item in missing[category]:
        if isinstance(item, dict):
            item_key = item.get('key') or item.get('indicator_key')
            if item_key == key:
                continue
        else:
            if item == key:
                continue
        cleaned.append(item)
    if cleaned:
        missing[category] = cleaned
    else:
        missing.pop(category, None)


def _remove_top_missing(market_data: Dict[str, Any], key: str) -> None:
    """同步清理顶层 missing_items 列表，避免已补齐的缺口再次触发 Stage3 校验。"""
    missing = market_data.get('missing_items')
    if not isinstance(missing, list):
        return
    filtered = []
    for item in missing:
        if isinstance(item, dict):
            if item.get('key') == key or item.get('indicator_key') == key:
                continue
        elif item == key:
            continue
        filtered.append(item)
    market_data['missing_items'] = filtered


def _is_missing_item_filled(market_data: Dict[str, Any], category: str, key: str) -> bool:
    if category in ('macro_indicators', 'monetary_policy'):
        entry = market_data.get(category, {}).get(key)
        if not isinstance(entry, dict):
            return False
        return _has_valid_value(entry.get('current_value'))
    if category == 'fund_flow':
        entry = market_data.get('fund_flow', {}).get(key)
        if not isinstance(entry, dict):
            return False
        return _has_valid_value(entry.get('recent_5d')) and _has_valid_value(entry.get('total_120d'))
    if category == 'commodities':
        for item in market_data.get('commodities', []):
            if item.get('symbol') == key:
                return _has_valid_value(item.get('current_price'))
        return False
    if category == 'forex':
        for item in market_data.get('forex', []):
            if item.get('pair') == key:
                return _has_valid_value(item.get('current_rate'))
        return False
    if category == 'bonds':
        for item in market_data.get('bonds', []):
            if item.get('symbol') == key:
                return _has_valid_value(item.get('current_yield'))
        return False
    if category == 'stock_indices':
        for item in market_data.get('stock_indices', []):
            if item.get('symbol') == key:
                return _has_valid_value(item.get('current_price'))
        return False
    return False


def _refresh_stage2_gap_monitor(payload: Dict[str, Any]) -> Dict[str, int]:
    commodities = payload.get('commodities', [])
    bonds = payload.get('bonds', [])
    summary = {
        'commodities': sum(1 for item in commodities if _is_placeholder_numeric(item.get('current_price'))),
        'bonds': sum(1 for item in bonds if _is_placeholder_numeric(item.get('current_yield'))),
    }
    payload.setdefault('metadata', {})['stage2_gap_monitor'] = summary
    return summary


def _refresh_stage2_notes(metadata: Dict[str, Any], gap_summary: Dict[str, int]) -> None:
    notes = metadata.setdefault('stage2_notes', [])
    filtered = [
        note for note in notes
        if not note.startswith("Stage2: 行情缺口仍存在") and not note.startswith("Stage2: Yahoo Fallback")
    ]
    summary_text = f"Stage2.5: WebSearch注入完成 (commodities={gap_summary['commodities']}, bonds={gap_summary['bonds']})."
    if summary_text not in filtered:
        filtered.append(summary_text)
    metadata['stage2_notes'] = filtered


def _cleanup_metadata_missing(metadata: Dict[str, Any], market_data: Dict[str, Any]) -> None:
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
            if key and _is_missing_item_filled(market_data, category, key):
                continue
            if item:
                kept.append(item)
        if kept:
            cleaned[category] = kept
    if cleaned:
        metadata['missing_items'] = cleaned
    else:
        metadata.pop('missing_items', None)


def _cleanup_monetary_aliases(market_data: Dict[str, Any], metadata: Dict[str, Any]) -> None:
    """清理货币政策别名重复项（canonical 有值、alias 仍为占位时删除 alias）。"""
    section = market_data.get('monetary_policy', {}) if isinstance(market_data, dict) else {}
    if not isinstance(section, dict):
        return
    for alias, canonical in MONETARY_KEY_MAP.items():
        if alias == canonical:
            continue
        if alias not in section or canonical not in section:
            continue
        alias_entry = section.get(alias) or {}
        canonical_entry = section.get(canonical) or {}
        if _has_valid_value(canonical_entry.get('current_value')) and not _has_valid_value(alias_entry.get('current_value')):
            section.pop(alias, None)
            _remove_missing_item(metadata, 'monetary_policy', alias)
            _remove_top_missing(market_data, alias)


def _normalize_fund_flow_payload(raw_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload or {})
    if raw_key == "etf_flow":
        normalized.setdefault('recent_5d', normalized.get('recent_week'))
        normalized.setdefault('note', normalized.get('hot_sectors'))
    if raw_key == "margin_trading":
        normalized.setdefault('total_120d', normalized.get('balance'))
        normalized.setdefault('note', normalized.get('ratio'))
        normalized.setdefault('recent_5d', None)
    return normalized


def _coerce_stage2_results_to_schema(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 Stage2 Unified 的 websearch_results（results 数组，含 task/extraction）转换为
    inject_websearch_data_test.py 期望的 schema。
    """
    if "results" not in raw or not isinstance(raw.get("results"), list):
        return raw
    schema: Dict[str, Any] = {
        "commodities": [],
        "forex": [],
        "bonds": [],
        "fund_flow": {},
        "macro_indicators": {},
    }

    def _num(val):
        try:
            return float(val)
        except Exception:
            return None

    for item in raw["results"]:
        task = item.get("task") or {}
        extraction = item.get("extraction") or {}
        if item.get("manual_required") is True:
            continue
        key = task.get("indicator_key")
        if not key:
            continue
        cat = INDICATOR_CATEGORY.get(key)
        if not cat:
            continue
        note_text = extraction.get("note") or ""
        if isinstance(note_text, str) and ("数据超过" in note_text or "需更新" in note_text):
            continue
        val = _num(extraction.get("value"))
        if val is None:
            continue
        source = extraction.get("note") or extraction.get("source_url") or "MCP WebSearch自动抽取"
        if cat == "commodities":
            schema["commodities"].append(
                {
                    "symbol": key,
                    "name": key,
                    "current_price": val,
                    "unit": task.get("unit") or "",
                    "ytd_change": extraction.get("ytd_change"),
                    "trend": "未知",
                    "source": source,
                }
            )
        elif cat == "forex":
            schema["forex"].append(
                {
                    "pair": key,
                    "name": key,
                    "current_rate": val,
                    "daily_change": extraction.get("daily_change"),
                    "change_120d": extraction.get("change_120d"),
                    "trend": extraction.get("trend") or "未知",
                    "source": source,
                }
            )
        elif cat == "bonds":
            schema["bonds"].append(
                {
                    "symbol": key,
                    "name": key,
                    "current_yield": val,
                    "change_5d_bp": extraction.get("change_5d_bp"),
                    "change_120d_bp": extraction.get("change_120d_bp"),
                    "trend": extraction.get("trend") or "未知",
                    "source": source,
                }
            )
        elif cat == "fund_flow":
            # 单值无法拆 recent_5d/total_120d，跳过，仍留 gap_monitor 提醒人工
            continue
        elif cat == "macro_indicators":
            schema["macro_indicators"][key] = {
                "indicator_name": key,
                "current_value": val,
                "previous_value": extraction.get("previous_value"),
                "change_rate": extraction.get("change_rate"),
                "unit": task.get("unit") or "%",
                "date": extraction.get("date") or "",
                "as_of_date": extraction.get("as_of_date") or extraction.get("report_period"),
                "value_type": extraction.get("value_type"),
                "yoy_month": extraction.get("yoy_month"),
                "yoy_ytd": extraction.get("yoy_ytd"),
                "source": source,
            }
    # 移除空类别，保持与原脚本兼容
    return {k: v for k, v in schema.items() if v}


def inject_websearch_data(market_data_path, websearch_path, output_path, *, backfill_trend: bool = True):
    """
    将WebSearch结果注入到市场数据JSON中

    Args:
        market_data_path: 市场数据JSON路径
        websearch_path: WebSearch结果JSON路径
        output_path: 输出路径
    """

    # 读取市场数据
    print(f"[INFO] 读取市场数据: {market_data_path}")
    with open(market_data_path, 'r', encoding='utf-8') as f:
        market_data = json.load(f)
    metadata = market_data.setdefault('metadata', {})

    # 读取WebSearch结果
    print(f"[INFO] 读取WebSearch结果: {websearch_path}")
    with open(websearch_path, 'r', encoding='utf-8') as f:
        websearch_raw = json.load(f)
    is_stage2_results = isinstance(websearch_raw, dict) and isinstance(websearch_raw.get("results"), list)
    # 若为 Stage2 results 结构，先转换为 schema
    websearch_data = _coerce_stage2_results_to_schema(websearch_raw)
    # 统一结构，容忍 {symbol: {...}} / list / None
    websearch_data['forex'] = _normalize_keyed_list(websearch_data.get('forex'), 'pair')
    websearch_data['bonds'] = _normalize_keyed_list(websearch_data.get('bonds'), 'symbol')
    websearch_data['commodities'] = _normalize_keyed_list(websearch_data.get('commodities'), 'symbol')
    websearch_data['stock_indices'] = _normalize_keyed_list(websearch_data.get('stock_indices'), 'symbol')

    is_manual = "manual" in Path(websearch_path).name.lower() and not is_stage2_results
    if is_manual:
        missing_urls = _collect_missing_source_urls(websearch_data)
        if missing_urls:
            raise ValueError(
                "manual.json 缺少 WebSearch 来源 URL: "
                + ", ".join(missing_urls)
                + "。请为每个已填写数值的条目补充 source_url 或在 source/note 中提供 URL。"
            )
        # 将 source_url 绑定到 source，便于审计
        for entry in websearch_data.get("commodities", []) or []:
            _attach_source_url(entry)
        for entry in websearch_data.get("forex", []) or []:
            _attach_source_url(entry)
        for entry in websearch_data.get("bonds", []) or []:
            _attach_source_url(entry)
        for entry in websearch_data.get("stock_indices", []) or []:
            _attach_source_url(entry)
        for payload in (websearch_data.get("macro_indicators") or {}).values():
            _attach_source_url(payload)
        for payload in (websearch_data.get("monetary_policy") or {}).values():
            _attach_source_url(payload)
        for payload in (websearch_data.get("fund_flow") or {}).values():
            _attach_source_url(payload)

    inject_count = 0

    # 1. 注入宏观指标
    print("\n[STEP 1] 注入宏观指标数据...")
    macro_section = market_data.setdefault('macro_indicators', {})
    for raw_key, payload in websearch_data.get('macro_indicators', {}).items():
        key = MACRO_KEY_MAP.get(raw_key, raw_key)  # 键名规范化
        if key not in macro_section:
            # 缺失即创建占位，避免 industrial_sales 等被跳过
            macro_section[key] = _create_macro_placeholder(key, payload, metadata)
        if _apply_macro_entry(key, macro_section[key], payload, metadata.get('date'), is_manual=is_manual):
            inject_count += 1
            print(f"  [OK] {payload.get('indicator_name', key)}: {payload.get('current_value')} {payload.get('unit', '')}".strip())
            _remove_missing_item(metadata, 'macro_indicators', key)
            _remove_top_missing(market_data, key)

    # 2. 注入货币政策
    print("\n[STEP 2] 注入货币政策数据...")
    monetary_section = market_data.setdefault('monetary_policy', {})
    for raw_key, payload in websearch_data.get('monetary_policy', {}).items():
        key = MONETARY_KEY_MAP.get(raw_key, raw_key)
        if key not in monetary_section:
            monetary_section[key] = _create_monetary_placeholder(key, payload, metadata)
        if _apply_monetary_entry(key, monetary_section[key], payload, metadata.get('date'), is_manual=is_manual):
            inject_count += 1
            print(f"  [OK] {payload.get('policy_name', key)}: {payload.get('current_value')} {payload.get('unit', '')}".strip())
            _remove_missing_item(metadata, 'monetary_policy', key)
            _remove_top_missing(market_data, key)
    _cleanup_monetary_aliases(market_data, metadata)

    # 3. 注入资金流向（标准化为浮点+统一来源）
    print("\n[STEP 3] 注入资金流向数据...")
    for raw_key, payload in websearch_data.get('fund_flow', {}).items():
        key = FUND_FLOW_KEY_MAP.get(raw_key, raw_key)
        if key not in market_data.get('fund_flow', {}):
            continue
        normalized_payload = _normalize_fund_flow_payload(raw_key, payload)
        if _apply_fund_flow_entry(market_data['fund_flow'][key], key, normalized_payload):
            inject_count += 1
            print(
                f"  [OK] {key}: recent_5d={market_data['fund_flow'][key]['recent_5d']} "
                f"total_120d={market_data['fund_flow'][key]['total_120d']} source={market_data['fund_flow'][key]['source']}"
            )
            _remove_missing_item(metadata, 'fund_flow', key)
            _remove_top_missing(market_data, key)

    # 4. 注入外汇数据
    print("\n[STEP 4] 注入外汇数据...")
    forex_iterable = websearch_data.get('forex') or []

    market_forex = market_data.setdefault('forex', [])
    for fx in forex_iterable:
        pair = fx.get('pair') or fx.get('symbol')
        if not pair:
            continue
        updated = False
        for i, item in enumerate(market_forex):
            if item.get('pair') == pair:
                market_forex[i] = _merge_forex_entry(item, fx, is_manual=is_manual)
                updated = True
                break
        if not updated:
            market_forex.append(_build_forex_entry(fx))
        inject_count += 1
        print(f"  [OK] {fx.get('name', pair)}: {fx.get('current_rate')} (source={fx.get('source')})")
        _remove_missing_item(metadata, 'forex', pair)
        _remove_top_missing(market_data, pair)

    # 5. 注入股票指数（含 000016 等补全）
    print("\n[STEP 5] 注入股票指数数据...")
    stock_indices_iterable = websearch_data.get('stock_indices') or []
    stock_indices_section = market_data.setdefault('stock_indices', [])
    for idx_payload in stock_indices_iterable:
        symbol = idx_payload.get('symbol')
        if not symbol:
            print("  [WARN] stock_index 缺少 symbol，已跳过")
            continue
        price = _coerce_float(idx_payload.get('current_price') or idx_payload.get('close') or idx_payload.get('price'))
        if price is None:
            print(f"  [WARN] {symbol} 缺少可解析价格，跳过注入")
            continue
        merged = False
        for i, existing in enumerate(stock_indices_section):
            if existing.get('symbol') == symbol:
                stock_indices_section[i] = _merge_stock_index_entry(existing, idx_payload)
                merged = True
                break
        if not merged:
            stock_indices_section.append(_build_stock_index_entry(symbol, idx_payload))
        inject_count += 1
        print(f"  [OK] {idx_payload.get('name', symbol)}: {price}")
        _remove_missing_item(metadata, 'stock_indices', symbol)
        _remove_top_missing(market_data, symbol)

    # 6. 注入债券收益率
    print("\n[STEP 6] 注入债券收益率数据...")
    bond_iterable = websearch_data.get('bonds') or []

    for bond_data in bond_iterable:
        symbol = bond_data.get('symbol')
        if not symbol:
            print("  [WARN] bond 缺少 symbol，已跳过")
            continue
        bond_data.setdefault('name', symbol)
        bond_data['current_yield'] = _coerce_float(bond_data.get('current_yield'))
        if bond_data['current_yield'] is None:
            print(f"  [WARN] {symbol} 缺少 current_yield，跳过注入")
            continue
        # 在bonds列表中找到对应项并更新
        updated = False
        for i, bond in enumerate(market_data['bonds']):
            if bond.get('symbol') == symbol:
                market_data['bonds'][i] = _merge_bond_entry(bond, bond_data, is_manual=is_manual)
                inject_count += 1
                print(f"  [OK] {bond_data['name']}: {bond_data['current_yield']}%")
                _remove_missing_item(metadata, 'bonds', symbol)
                _remove_top_missing(market_data, symbol)
                updated = True
                break
        if not updated:
            merged_entry = _merge_bond_entry({}, bond_data, is_manual=is_manual)
            market_data.setdefault('bonds', []).append(merged_entry)
            inject_count += 1
            _remove_missing_item(metadata, 'bonds', symbol)
            _remove_top_missing(market_data, symbol)

    # 7. 注入商品价格
    print("\n[STEP 7] 注入商品价格数据...")
    commodity_iterable = websearch_data.get('commodities') or []

    for commodity_data in commodity_iterable:
        symbol = commodity_data.get('symbol')
        if not symbol:
            print("  [WARN] commodity 缺少 symbol，已跳过")
            continue
        commodity_data.setdefault('name', symbol)
        commodity_data['current_price'] = _coerce_float(commodity_data.get('current_price'))
        if commodity_data['current_price'] is None:
            print(f"  [WARN] {symbol} 缺少 current_price，跳过注入")
            continue
        # 在commodities列表中找到对应项并更新
        updated = False
        for i, commodity in enumerate(market_data['commodities']):
            if commodity.get('symbol') == symbol:
                market_data['commodities'][i] = _merge_commodity_entry(commodity, commodity_data, is_manual=is_manual)
                updated = True
                break
        if not updated:
            market_data.setdefault('commodities', []).append(_merge_commodity_entry({}, commodity_data, is_manual=is_manual))
        inject_count += 1
        price_val = commodity_data.get('current_price') or 0.0
        ytd_val = commodity_data.get('ytd_change') or 0.0
        print(f"  [OK] {commodity_data['name']}: {commodity_data.get('unit','')}{price_val:.2f} (YTD {ytd_val:+.2f}%)")
        _remove_missing_item(metadata, 'commodities', symbol)
        _remove_top_missing(market_data, symbol)

    # 注入完成后回读 trend_history 补齐缺失变化值（默认开启）
    if backfill_trend:
        try:
            backfill_stats = _backfill_trend_changes(market_data)
            total_backfilled = sum(backfill_stats.values())
            if total_backfilled:
                print(f"  - trend_history backfill: {backfill_stats}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] trend_history backfill failed: {exc}")

    # 更新元数据
    metadata_section = websearch_data.get('metadata', {})
    # 按实际数据重新计算完整度：非占位/非零的数据占比
    def _is_filled(val: Any) -> bool:
        if val in (None, "", "N/A"):
            return False
        try:
            if isinstance(val, (int, float)):
                return abs(val) > 1e-9
        except Exception:
            pass
        return True

    filled = 0
    total = 0
    # commodities
    for item in market_data.get('commodities', []):
        total += 1
        filled += 1 if _is_filled(item.get('current_price')) else 0
    # forex
    for item in market_data.get('forex', []):
        total += 1
        filled += 1 if _is_filled(item.get('current_rate')) else 0
    # bonds
    for item in market_data.get('bonds', []):
        total += 1
        filled += 1 if _is_filled(item.get('current_yield')) else 0
    # stock indices
    for item in market_data.get('stock_indices', []):
        total += 1
        filled += 1 if _is_filled(item.get('current_price')) else 0
    # fund flow
    for item in market_data.get('fund_flow', {}).values():
        total += 1
        filled += 1 if _is_filled(item.get('recent_5d')) and _is_filled(item.get('total_120d')) else 0
    # macro & monetary
    for section in ('macro_indicators', 'monetary_policy'):
        for entry in market_data.get(section, {}).values():
            total += 1
            filled += 1 if _is_filled(entry.get('current_value')) else 0

    metadata['data_completeness'] = round(filled / total, 3) if total else 1.0
    metadata['ai_websearch_enhanced'] = True
    collection_time = websearch_data.get('collection_time') or metadata_section.get('collection_time')
    if collection_time:
        metadata['websearch_timestamp'] = collection_time

    # 根据已有数据再清理一次顶层 missing_items，避免遗留占位符
    for key in list(market_data.get('missing_items', [])):
        if isinstance(key, dict):
            key_val = key.get('key') or key.get('indicator_key')
        else:
            key_val = key
        if not key_val:
            continue
        _remove_top_missing(market_data, key_val)
    # 同步根据已填充的 stock_indices 清理缺口
    for idx in market_data.get('stock_indices', []):
        _remove_top_missing(market_data, idx.get('symbol'))
    _cleanup_metadata_missing(metadata, market_data)
    if not market_data.get('missing_items'):
        market_data['missing_items'] = []

    gap_summary = _refresh_stage2_gap_monitor(market_data)
    _refresh_stage2_notes(metadata, gap_summary)

    # 保存到输出文件
    print(f"\n[INFO] 保存完整数据到: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(market_data, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] 数据注入完成！")
    print(f"  - 注入数据项: {inject_count}")
    print(f"  - 数据完整性: {market_data['metadata']['data_completeness']:.1%}")
    print(f"  - 输出文件: {output_path}")

    # Final write to trend_history (post Stage2.5)
    try:
        write_count = write_from_market_data(market_data, is_partial=False, source_path=output_path)
        print(f"  - trend_history final write: {write_count} items")
    except Exception as exc:  # noqa: BLE001
        print(f"  - trend_history final write failed: {exc}")

    date_val = (
        market_data.get("metadata", {}).get("date")
        or market_data.get("metadata", {}).get("end_date")
        or market_data.get("metadata", {}).get("start_date")
    )
    date_compact = str(date_val).replace("-", "") if date_val else datetime.now().strftime("%Y%m%d")

    # Refresh quality metrics after manual injection
    try:
        quality_path = Path("reports") / f"quality_metrics_{date_compact}.json"
        write_quality_metrics(market_data, quality_path)
        print(f"  - quality_metrics refreshed: {quality_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"  - quality_metrics refresh failed: {exc}")

    # Refresh policy evaluation after manual injection
    try:
        policy_path = Path("reports") / f"policy_evaluation_{date_compact}.json"
        policy_payload = evaluate_policy(market_data, stage2_summary=None)
        write_policy_evaluation(policy_payload, policy_path)
        print(f"  - policy_evaluation refreshed: {policy_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"  - policy_evaluation refresh failed: {exc}")

    # Post-injection validation: check for remaining estimated values
    _post_injection_validation(market_data)
    _sync_backfill_issues_to_logs(market_data)

    return output_path


def _post_injection_validation(market_data: Dict[str, Any]) -> None:
    """注入后校验，打印仍为估计值的字段。

    检查 bonds, macro_indicators, monetary_policy 中 is_estimated=True 的条目，
    作为 CI 检查点警示数据质量问题。
    """
    estimated_fields: List[str] = []

    # Check bonds
    for bond in market_data.get('bonds', []) or []:
        if bond.get('is_estimated'):
            name = bond.get('name') or bond.get('symbol') or 'unknown'
            estimated_fields.append(f"bonds.{name}")

    # Check macro_indicators
    for key, entry in (market_data.get('macro_indicators', {}) or {}).items():
        if isinstance(entry, dict) and entry.get('is_estimated'):
            name = entry.get('indicator_name') or key
            estimated_fields.append(f"macro_indicators.{name}")

    # Check monetary_policy
    for key, entry in (market_data.get('monetary_policy', {}) or {}).items():
        if isinstance(entry, dict) and entry.get('is_estimated'):
            name = entry.get('policy_name') or key
            estimated_fields.append(f"monetary_policy.{name}")

    # Check commodities
    for comm in market_data.get('commodities', []) or []:
        if comm.get('is_estimated'):
            name = comm.get('name') or comm.get('symbol') or 'unknown'
            estimated_fields.append(f"commodities.{name}")

    # Check forex
    for fx in market_data.get('forex', []) or []:
        if fx.get('is_estimated'):
            name = fx.get('name') or fx.get('pair') or 'unknown'
            estimated_fields.append(f"forex.{name}")

    # Print validation result
    print("\n[VALIDATION] 估计值校验:")
    if estimated_fields:
        print(f"  [WARN] 仍有 {len(estimated_fields)} 个估计值字段:")
        for field in estimated_fields:
            print(f"    - {field}")
    else:
        print("  [OK] 所有字段已去除估计值标记")


def _coerce_float(value: Any) -> Optional[float]:
    if value in (None, '', 'N/A'):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(',', '')
        if not text:
            return None
        text = text.replace('%', '')
        match = re.search(r'[-+]?\d+(?:\.\d+)?', text)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return None
    return None


def _format_source_label(raw_source: Optional[str]) -> str:
    source_text = (raw_source or "MCP WebSearch").strip()
    if "MCP WebSearch" in source_text:
        return source_text
    return f"MCP WebSearch实时获取({source_text})"


def _normalize_rrr_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip().lower()
    if "加权" in text or "weighted" in text:
        return "weighted"
    if "法定" in text or "statutory" in text:
        return "statutory"
    if "平均" in text:
        # 无明确口径时保守归类为法定平均
        return "statutory"
    return None


def _contains_ytd_marker(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(tok in lowered for tok in ["累计", "年初至今", "ytd", "year-to-date"]):
        return True
    return bool(re.search(r"1\s*(?:-|—|~|至|到)\s*\d{1,2}\s*月", lowered))


def _apply_macro_entry(
    indicator_key: str,
    entry: Dict[str, Any],
    payload: Dict[str, Any],
    reference_date: Optional[str],
    *,
    is_manual: bool = False,
) -> bool:
    if not isinstance(entry, dict):
        return False
    entry['indicator_name'] = payload.get('indicator_name', entry.get('indicator_name'))
    entry['unit'] = payload.get('unit', entry.get('unit', ''))
    incoming_date = payload.get('date') or payload.get('as_of_date') or payload.get('report_period')
    if incoming_date:
        entry['date'] = incoming_date
    entry['as_of_date'] = payload.get('as_of_date') or payload.get('report_period') or entry.get('as_of_date')
    entry['source'] = _format_source_label(payload.get('source'))
    # 确保 note 为字符串，避免 None 参与字符串拼接时报错
    note_val = payload.get('note', entry.get('note'))
    if is_manual and 'note' not in payload:
        note_val = ""
    entry['note'] = note_val if isinstance(note_val, str) else ''
    fallback_reason = None

    if indicator_key == "industrial":
        raw_current = _coerce_float(payload.get('current_value'))
        yoy_month = _coerce_float(payload.get('yoy_month'))
        yoy_ytd = _coerce_float(payload.get('yoy_ytd'))
        raw_type = payload.get('value_type')
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
                str(payload.get(k) or "") for k in ("note", "source", "indicator_name", "report_period")
            )
            if _contains_ytd_marker(hint_text):
                yoy_ytd = raw_current
                value_type = "yoy_ytd"
            else:
                yoy_month = raw_current
                value_type = "yoy_month"

        entry['yoy_month'] = yoy_month
        entry['yoy_ytd'] = yoy_ytd
        entry['value_type'] = value_type or entry.get('value_type')
        entry['current_value'] = yoy_month
        entry['previous_value'] = _coerce_float(payload.get('previous_value')) if yoy_month is not None else None
        entry['change_rate'] = _coerce_float(payload.get('change_rate')) if yoy_month is not None else None

        if yoy_month is not None and yoy_ytd is not None and abs(yoy_month - yoy_ytd) < 1e-6:
            _append_note(entry, "口径疑似混淆(yoy_month≈yoy_ytd)")
        if yoy_month is None and yoy_ytd is not None:
            _append_note(entry, "only_yoy_ytd_provided")
            fallback_reason = fallback_reason or "manual_incomplete"
    else:
        entry['current_value'] = _coerce_float(payload.get('current_value'))
        entry['previous_value'] = _coerce_float(payload.get('previous_value'))
        entry['change_rate'] = _coerce_float(payload.get('change_rate'))
        entry['value_type'] = payload.get('value_type', entry.get('value_type'))

    # is_estimated 规则：手工注入默认不估算；regex_only/明确标注才估算
    if 'is_estimated' in payload:
        entry['is_estimated'] = _coerce_bool(payload.get('is_estimated'))
    else:
        source_text = str(payload.get('source') or entry.get('source') or "")
        note_text = str(entry.get('note') or "")
        estimated_markers = ("regex_only", "regex_fallback", "bond_etf_proxy", "ETF代理", "估", "estimated")
        if any(m in source_text or m in note_text for m in estimated_markers):
            entry['is_estimated'] = True
        else:
            entry['is_estimated'] = False if entry.get('current_value') is not None else bool(entry.get('is_estimated'))

    # 先尝试事件序列回填 previous_value / change_rate（工业增加值仅在当月同比可用时回填）
    if entry['previous_value'] is None and entry['current_value'] is not None:
        hist_prev = _calc_prev_from_event_history(indicator_key, entry['current_value'], reference_date)
        if hist_prev.get("previous_value") is not None:
            entry['previous_value'] = hist_prev.get("previous_value")
            if entry['change_rate'] is None and hist_prev.get("change_rate") is not None:
                entry['change_rate'] = hist_prev.get("change_rate")
        else:
            fallback_reason = hist_prev.get("reason")

    # 兜底回填前值：若有 current_value + change_rate 但前值缺失，用差值推算；若连 change_rate 也无，则保持为空
    if entry['previous_value'] is None and entry['current_value'] is not None:
        if not entry.get('note'):
            entry['note'] = ''
        if entry['change_rate'] is not None:
            try:
                entry['previous_value'] = round(entry['current_value'] - entry['change_rate'], 4)
                if entry['note']:
                    entry['note'] += '；'
                entry['note'] += 'auto-backfilled previous_value via current_value - change_rate'
                fallback_reason = fallback_reason or "no_previous_value"
            except Exception:
                pass
        else:
            fallback_reason = fallback_reason or "manual_incomplete"

    if fallback_reason:
        if entry['note']:
            entry['note'] += '；'
        entry['note'] += f"reason={fallback_reason}"
    # 若仍无有效 current_value，则视为缺失，抛出异常阻断流程，避免 Stage3 出现 N/A
    if entry['current_value'] is None:
        raise ValueError(f"macro_indicators.{entry.get('indicator_name', 'unknown')} current_value is missing after injection")
    return True


def _create_monetary_placeholder(key: str, payload: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    """当原始市场数据缺少某个货币政策字段时，动态创建占位符"""
    default_date = payload.get('date') or payload.get('as_of_date') or payload.get('report_period') or ""
    return {
        "policy_name": payload.get('policy_name', key.upper()),
        "current_value": None,
        "change_from_120d": None,
        "unit": payload.get('unit', '%'),
        "date": default_date,
        "as_of_date": payload.get('as_of_date'),
        "rrr_type": payload.get('rrr_type'),
        "source": "待MCP WebSearch获取(websearch导入)",
        "note": payload.get('note'),
        "is_estimated": True
    }


def _create_macro_placeholder(key: str, payload: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    """缺失宏观指标时创建占位，便于后续注入而不跳过"""
    default_date = payload.get('date') or payload.get('as_of_date') or payload.get('report_period') or ""
    return {
        "indicator_name": payload.get('indicator_name', key),
        "current_value": None,
        "yoy_month": None,
        "yoy_ytd": None,
        "previous_value": None,
        "change_rate": None,
        "unit": payload.get('unit', payload.get('unit', '%')),
        "date": default_date,
        "as_of_date": payload.get('as_of_date'),
        "value_type": payload.get('value_type'),
        "source": "MCP WebSearch待补充",
        "note": payload.get('note'),
        "is_estimated": True,
    }


def _apply_monetary_entry(
    indicator_key: str,
    entry: Dict[str, Any],
    payload: Dict[str, Any],
    reference_date: Optional[str],
    *,
    is_manual: bool = False,
) -> bool:
    if not isinstance(entry, dict):
        return False
    entry['policy_name'] = payload.get('policy_name', entry.get('policy_name'))
    incoming_value = _coerce_float(payload.get('current_value'))
    change_value = payload.get('change_from_120d', payload.get('change_rate'))
    entry['change_from_120d'] = _coerce_float(change_value)
    entry['unit'] = payload.get('unit', entry.get('unit', ''))
    incoming_date = payload.get('date') or payload.get('as_of_date') or payload.get('report_period')
    if incoming_date:
        entry['date'] = incoming_date
    entry['as_of_date'] = payload.get('as_of_date') or entry.get('as_of_date')
    entry['source'] = _format_source_label(payload.get('source'))
    note_val = payload.get('note', entry.get('note'))
    if is_manual and 'note' not in payload:
        note_val = ""
    entry['note'] = note_val
    incoming_rrr_type = _normalize_rrr_type(payload.get('rrr_type') or payload.get('value_type'))
    if indicator_key in {"rrr", "reserve_ratio"}:
        existing_rrr_type = _normalize_rrr_type(entry.get('rrr_type'))
        if incoming_rrr_type:
            if existing_rrr_type and incoming_rrr_type != existing_rrr_type and entry.get('current_value') is not None:
                _append_note(entry, f"rrr_type_conflict:{existing_rrr_type}->{incoming_rrr_type}")
                incoming_value = None
            else:
                entry['rrr_type'] = incoming_rrr_type

    if incoming_value is not None:
        entry['current_value'] = incoming_value

    # is_estimated 规则：手工注入默认不估算；regex_only/明确标注才估算
    if 'is_estimated' in payload:
        entry['is_estimated'] = _coerce_bool(payload.get('is_estimated'))
    else:
        source_text = str(payload.get('source') or entry.get('source') or "")
        note_text = str(entry.get('note') or "")
        estimated_markers = ("regex_only", "regex_fallback", "bond_etf_proxy", "ETF代理", "估", "estimated")
        if any(m in source_text or m in note_text for m in estimated_markers):
            entry['is_estimated'] = True
        else:
            entry['is_estimated'] = False if entry.get('current_value') is not None else bool(entry.get('is_estimated'))

    fallback_reason = None
    if entry['change_from_120d'] is None and entry['current_value'] is not None:
        hist = _calc_change_from_event_history(indicator_key, entry['current_value'], reference_date)
        if hist.get("change_from_120d") is not None:
            entry['change_from_120d'] = hist.get("change_from_120d")
        else:
            entry['change_from_120d'] = None
        fallback_reason = hist.get("reason")

    if fallback_reason:
        note_val = entry.get('note')
        if not isinstance(note_val, str):
            note_val = ''
        if note_val:
            note_val += '；'
        note_val += f"reason={fallback_reason}"
        entry['note'] = note_val
    return True


def _apply_fund_flow_entry(entry: Dict[str, Any], key: str, payload: Dict[str, Any]) -> bool:
    existing_recent = _coerce_float(entry.get("recent_5d"))
    existing_total = _coerce_float(entry.get("total_120d"))
    existing_suspicious = _is_suspicious_fund_flow_pair(key, existing_recent, existing_total)
    recent_value = FundFlowData._parse_amount(payload.get('recent_5d'))
    total_value = FundFlowData._parse_amount(payload.get('total_120d'))
    current_value = FundFlowData._parse_amount(
        payload.get('current_value') or payload.get('daily_value') or payload.get('today_value')
    )
    if recent_value is None and total_value is None and current_value is None:
        print(f"  [WARN] {key} 缺少可解析的金额，跳过注入")
        return False

    entry['type'] = key
    updated = False
    if recent_value is not None:
        entry['recent_5d'] = recent_value
        updated = True
    if total_value is not None:
        entry['total_120d'] = total_value
        updated = True
    if current_value is not None:
        entry['current_value'] = current_value
        entry['current_date'] = payload.get('date') or entry.get('current_date')
        updated = True
    if not updated:
        return False

    trend_base = recent_value if recent_value is not None else current_value
    entry['trend'] = _infer_trend(payload.get('trend'), trend_base)

    anomaly = any(value == 0 for value in (recent_value, total_value, current_value) if value is not None)
    anomaly = anomaly or _is_suspicious_fund_flow_pair(key, recent_value, total_value)
    entry['source'] = "异常零值-需核查" if anomaly else "MCP WebSearch实时获取"
    entry['note'] = _build_fund_flow_note(payload, anomaly)
    if existing_suspicious:
        entry['note'] = (
            f"覆盖Stage2可疑占位值；{entry['note']}" if entry.get('note') else "覆盖Stage2可疑占位值"
        )
    return True


def _infer_trend(raw_trend: Optional[str], recent_value: Optional[float]) -> str:
    if isinstance(recent_value, (int, float)):
        if recent_value > 0:
            return '流入'
        if recent_value < 0:
            return '流出'
    return raw_trend or '未知'


def _is_suspicious_fund_flow_pair(
    key: str, recent_value: Optional[float], total_value: Optional[float]
) -> bool:
    if recent_value is None or total_value is None:
        return False
    if key in {"northbound", "southbound"} and abs(recent_value - total_value) < 1e-9:
        if abs(recent_value - 100.0) < 1e-9:
            return True
        if abs(recent_value) <= 150.0:
            return True
    return False


def _infer_asset_trend(
    raw_trend: Optional[str],
    daily_change: Optional[float],
    ytd_change: Optional[float],
    asset_type: str = "commodity"
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
    if raw_trend and raw_trend not in ('未知', '待MCP获取', '待 WebSearch'):
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


def _build_fund_flow_note(payload: Dict[str, Any], anomaly: bool) -> str:
    parts = []
    raw_source = payload.get('source')
    if raw_source:
        parts.append(f"来源:{raw_source}")
    if payload.get('date'):
        parts.append(f"日期:{payload.get('date')}")
    if payload.get('unit'):
        parts.append(f"单位:{payload['unit']}")
    if payload.get('note'):
        parts.append(payload['note'])
    if payload.get('current_value') or payload.get('daily_value') or payload.get('today_value'):
        raw_daily = payload.get('current_value') or payload.get('daily_value') or payload.get('today_value')
        parts.append(f"原始当日:{raw_daily}")
    if payload.get('recent_5d'):
        parts.append(f"原始5日:{payload['recent_5d']}")
    if payload.get('total_120d'):
        parts.append(f"原始120日:{payload['total_120d']}")
    if anomaly:
        parts.append("异常: 零值待WebSearch复核")
    return '；'.join(parts)


def _coerce_percent(value: Any) -> Optional[float]:
    if value in (None, '', 'N/A'):
        return None
    try:
        return float(str(value).replace('%', '').strip())
    except Exception:
        return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {'true', '1', 'yes', 'y', '是'}
    return False


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
    values = payload.get("values") if isinstance(payload.get("values"), list) else []
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

    records = _load_series_records(category, symbol, base_dir=base_dir, reference_date=reference_date)
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
        anchor_records = [r for r in records if r["date"].date() < ref_dt.date()]

    if not anchor_records:
        result["reason_5d"] = "trend_history_insufficient"
        result["reason_120d"] = "trend_history_insufficient"
        return result

    required_5d = 5
    # 有 reference_date 表示当前值来自当日，需回看 120 交易日基准（不含当日）
    required_120d = 120 if ref_dt else min(121, SERIES_WINDOWS.get(category, 121))

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
                result["change_5d"] = ((current_value - base_5d_val) / base_5d_val) * 100
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
                result["change_120d_bp"] = (current_value - base_120d_val) * 100
            else:
                result["change_120d"] = ((current_value - base_120d_val) / base_120d_val) * 100
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

    records = _load_series_records(category, symbol, base_dir=base_dir, reference_date=reference_date)
    if not records:
        result["reason_1d"] = "trend_history_missing"
        return result

    ref_dt = _parse_date(reference_date) if reference_date else None
    if ref_dt:
        anchor_records = [r for r in records if r["date"].date() < ref_dt.date()]
    else:
        anchor_records = list(records)
        # 避免同日重复写入后出现“前一日变化=0”。
        if anchor_records and abs(anchor_records[-1]["value"] - float(current_value)) < 1e-9:
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

    result["change_1d"] = ((float(current_value) - float(base_val)) / float(base_val)) * 100
    return result


def _load_event_history(indicator: str, *, base_dir: Path = DEFAULT_BASE_DIR) -> List[Dict[str, Any]]:
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
            if not isinstance(period, str) or not re.match(r"20\\d{2}-\\d{2}$", period):
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
        prev_val = parsed[-2][1] if abs(latest_val - float(current_value)) < 1e-6 else latest_val
        result["previous_value"] = prev_val
        result["change_rate"] = float(current_value) - float(prev_val)
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
    prev_val = parsed[-2][1] if abs(latest_val - float(current_value)) < 1e-6 else latest_val

    result["previous_value"] = prev_val
    result["change_rate"] = float(current_value) - float(prev_val)
    return result


def _should_backfill_numeric(value: Any) -> bool:
    if value in (None, "", "N/A"):
        return True
    try:
        return abs(float(value)) < 1e-9
    except Exception:
        return True


def _append_note(entry: Dict[str, Any], message: str) -> None:
    if not message:
        return
    note = entry.get("note") or ""
    if note:
        note += "；"
    note += message
    entry["note"] = note


def _record_backfill_issue(
    metadata: Dict[str, Any],
    category: str,
    key: str,
    field: str,
    reason: str,
) -> None:
    issues = metadata.setdefault("trend_backfill_issues", [])
    issue = {"category": category, "key": key, "field": field, "reason": reason}
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
    if existing not in _TREND_CONF_RANK or _TREND_CONF_RANK[normalized] < _TREND_CONF_RANK[existing]:
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
    if (used_5d and hist.get("base_5d_estimated")) or (used_120d and hist.get("base_120d_estimated")):
        return "low", "trend_history_base_estimated"
    if used_5d and used_120d:
        return "high", None
    return "medium", "trend_history_partial_window"


def _backfill_trend_changes(market_data: Dict[str, Any]) -> Dict[str, int]:
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
    metadata = market_data.get("metadata", {}) if isinstance(market_data, dict) else {}
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
        hist = _calc_change_from_trend_history("bonds", symbol, current, reference_date=reference_date)
        used_hist_120d = False
        used_hist_5d = False
        if _should_backfill_numeric(bond.get("change_120d_bp")):
            if hist.get("change_120d_bp") is not None:
                bond["change_120d_bp"] = round(float(hist["change_120d_bp"]), 2)
                stats["bonds"] += 1
                used_hist_120d = True
            else:
                bond["change_120d_bp"] = None
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(metadata, "bonds", symbol, "change_120d_bp", reason)
                _append_note(bond, f"reason={reason}")
        if bond.get("change_5d_bp") is None:
            if hist.get("change_5d_bp") is not None:
                bond["change_5d_bp"] = round(float(hist["change_5d_bp"]), 2)
                stats["bonds"] += 1
                used_hist_5d = True
            else:
                bond["change_5d_bp"] = None
                reason = hist.get("reason_5d") or "trend_history_missing"
                _record_backfill_issue(metadata, "bonds", symbol, "change_5d_bp", reason)
                _append_note(bond, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (used_hist_5d and hist.get("base_5d_estimated")):
            bond["is_estimated"] = True
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
        if bond.get("trend") in (None, "未知", "待MCP获取", "待 WebSearch"):
            bond["trend"] = _infer_asset_trend(
                None,
                bond.get("change_5d_bp"),
                bond.get("change_120d_bp"),
                "bond",
            )

    for fx in market_data.get("forex", []) or []:
        symbol = fx.get("pair")
        current = _coerce_float(fx.get("current_rate"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history("forex", symbol, current, reference_date=reference_date)
        daily_hist = _calc_daily_change_from_trend_history("forex", symbol, current, reference_date=reference_date)
        used_hist_120d = False
        used_hist_1d = False
        if _should_backfill_numeric(fx.get("change_120d")):
            if hist.get("change_120d") is not None:
                fx["change_120d"] = round(float(hist["change_120d"]), 2)
                stats["forex"] += 1
                used_hist_120d = True
            else:
                fx["change_120d"] = None
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(metadata, "forex", symbol, "change_120d", reason)
                _append_note(fx, f"reason={reason}")
        if fx.get("daily_change") is None:
            if daily_hist.get("change_1d") is not None:
                fx["daily_change"] = round(float(daily_hist["change_1d"]), 2)
                stats["forex"] += 1
                used_hist_1d = True
            else:
                fx["daily_change"] = None
                reason = daily_hist.get("reason_1d") or "trend_history_missing"
                _record_backfill_issue(metadata, "forex", symbol, "daily_change", reason)
                _append_note(fx, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (used_hist_1d and daily_hist.get("base_1d_estimated")):
            fx["is_estimated"] = True
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
        if fx.get("trend") in (None, "未知", "待MCP获取", "待 WebSearch"):
            fx["trend"] = _infer_asset_trend(
                None,
                fx.get("daily_change"),
                fx.get("change_120d"),
                "forex",
            )

    for comm in market_data.get("commodities", []) or []:
        symbol = comm.get("symbol")
        current = _coerce_float(comm.get("current_price"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history("commodities", symbol, current, reference_date=reference_date)
        used_hist_120d = False
        used_hist_5d = False
        if _should_backfill_numeric(comm.get("ytd_change")):
            if hist.get("change_120d") is not None:
                comm["ytd_change"] = round(float(hist["change_120d"]), 2)
                stats["commodities"] += 1
                used_hist_120d = True
            else:
                comm["ytd_change"] = None
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(metadata, "commodities", symbol, "ytd_change", reason)
                _append_note(comm, f"reason={reason}")
        if comm.get("daily_change") is None:
            if hist.get("change_5d") is not None:
                comm["daily_change"] = round(float(hist["change_5d"]), 2)
                stats["commodities"] += 1
                used_hist_5d = True
            else:
                comm["daily_change"] = None
                reason = hist.get("reason_5d") or "trend_history_missing"
                _record_backfill_issue(metadata, "commodities", symbol, "daily_change", reason)
                _append_note(comm, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (used_hist_5d and hist.get("base_5d_estimated")):
            comm["is_estimated"] = True
            _append_note(comm, "trend_history_base_estimated")
        confidence, confidence_reason = _derive_trend_confidence(
            hist,
            used_5d=used_hist_5d,
            used_120d=used_hist_120d,
        )
        if confidence:
            _merge_trend_confidence(comm, confidence)
        if confidence_reason:
            _append_note(comm, confidence_reason)
        if comm.get("trend") in (None, "未知", "待MCP获取", "待 WebSearch"):
            comm["trend"] = _infer_asset_trend(
                None,
                comm.get("daily_change"),
                comm.get("ytd_change"),
                "commodity",
            )

    for idx in market_data.get("stock_indices", []) or []:
        symbol = idx.get("symbol")
        current = _coerce_float(idx.get("current_price"))
        if not symbol or current is None:
            continue
        hist = _calc_change_from_trend_history("stock_indices", symbol, current, reference_date=reference_date)
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
                _record_backfill_issue(metadata, "stock_indices", symbol, "change_120d", reason)
                _append_note(idx, f"reason={reason}")
        if idx.get("change_5d") is None:
            if hist.get("change_5d") is not None:
                idx["change_5d"] = round(float(hist["change_5d"]), 2)
                stats["stock_indices"] += 1
                used_hist_5d = True
            else:
                idx["change_5d"] = None
                reason = hist.get("reason_5d") or "trend_history_missing"
                _record_backfill_issue(metadata, "stock_indices", symbol, "change_5d", reason)
                _append_note(idx, f"reason={reason}")
        if (used_hist_120d and hist.get("base_120d_estimated")) or (used_hist_5d and hist.get("base_5d_estimated")):
            idx["is_estimated"] = True
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
        if not (_should_backfill_numeric(flow.get("recent_5d")) or _should_backfill_numeric(flow.get("total_120d"))):
            continue
        daily_series = load_daily_series(key, base_dir=DEFAULT_BASE_DIR)
        if not daily_series:
            continue

        override_value = _coerce_float(flow.get("current_value"))
        override_date = flow.get("current_date") or flow.get("date") or reference_date
        if override_value is not None:
            daily_series = apply_override(daily_series, override_value, override_date)

        recent_5d, full5, used_date, _ = compute_rollup(daily_series, end_date=reference_date, window=5)
        total_120d, full120, used_date_120, _ = compute_rollup(daily_series, end_date=reference_date, window=120)
        if recent_5d is not None and _should_backfill_numeric(flow.get("recent_5d")):
            flow["recent_5d"] = round(float(recent_5d), 2)
            stats["fund_flow"] += 1
        if total_120d is not None and _should_backfill_numeric(flow.get("total_120d")):
            flow["total_120d"] = round(float(total_120d), 2)
            stats["fund_flow"] += 1

        trend_base = flow.get("recent_5d")
        if flow.get("trend") in (None, "未知", "待获取", "待MCP获取", "待 WebSearch"):
            flow["trend"] = _infer_trend(flow.get("trend"), trend_base)

        anomaly = any(
            value == 0 for value in (flow.get("recent_5d"), flow.get("total_120d")) if value is not None
        )
        flow["source"] = "异常零值-需核查" if anomaly else "MCP WebSearch实时获取"
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
    for key, indicator in (market_data.get("macro_indicators", {}) or {}).items():
        if not isinstance(indicator, dict):
            continue
        current = _coerce_float(indicator.get("current_value"))
        if current is None:
            continue
        prev_missing = indicator.get("previous_value") is None
        change_missing = indicator.get("change_rate") is None
        if prev_missing or change_missing:
            hist_prev = _calc_prev_from_event_history(key, current, reference_date)
            if prev_missing and hist_prev.get("previous_value") is not None:
                indicator["previous_value"] = hist_prev.get("previous_value")
            if change_missing and hist_prev.get("change_rate") is not None:
                indicator["change_rate"] = hist_prev.get("change_rate")
            if indicator.get("previous_value") is None:
                reason = hist_prev.get("reason") or "manual_incomplete"
                _append_note(indicator, f"reason={reason}")
                _record_backfill_issue(metadata, "macro_indicators", key, "previous_value", reason)
            stats["macro_indicators"] += 1

    # monetary policy change_from_120d
    for key, policy in (market_data.get("monetary_policy", {}) or {}).items():
        if not isinstance(policy, dict):
            continue
        current = _coerce_float(policy.get("current_value"))
        if current is None:
            continue
        if policy.get("change_from_120d") is None:
            hist = _calc_change_from_event_history(key, current, reference_date)
            used_hist_120d = False
            if hist.get("change_from_120d") is not None:
                policy["change_from_120d"] = hist.get("change_from_120d")
                used_hist_120d = True
            reason = hist.get("reason")
            if reason:
                if reason == "no_previous_value":
                    _append_note(policy, "无前值可比")
                _append_note(policy, f"reason={reason}")
                _record_backfill_issue(metadata, "monetary_policy", key, "change_from_120d", reason)
            if hist.get("base_estimated"):
                policy["is_estimated"] = True
                _append_note(policy, "trend_history_base_estimated")
                if used_hist_120d:
                    _merge_trend_confidence(policy, "low")
            elif used_hist_120d:
                _merge_trend_confidence(policy, "high")
            stats["monetary_policy"] += 1

    return stats


def _sync_backfill_issues_to_logs(market_data: Dict[str, Any]) -> None:
    """将趋势派生失败原因写入 gap_monitor/observability 的 data_quality_issues。"""
    metadata = market_data.get("metadata", {}) if isinstance(market_data, dict) else {}
    issues = metadata.get("trend_backfill_issues")
    if not issues:
        return
    date_val = metadata.get("date") or metadata.get("end_date") or metadata.get("start_date")
    date_compact = str(date_val).replace("-", "") if date_val else datetime.now().strftime("%Y%m%d")

    def _merge_quality_issues(path: Path) -> None:
        payload: Dict[str, Any] = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8")) or {}
            except Exception:
                payload = {}
        payload.setdefault("generated_at", datetime.now().isoformat())
        payload.setdefault("data_quality_issues", [])
        existing = {
            (item.get("category"), item.get("key"), item.get("field"), item.get("reason"))
            for item in payload.get("data_quality_issues", [])
            if isinstance(item, dict)
        }
        for issue in issues:
            sig = (issue.get("category"), issue.get("key"), issue.get("field"), issue.get("reason"))
            if sig in existing:
                continue
            payload["data_quality_issues"].append(issue)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _merge_quality_issues(Path("reports") / f"gap_monitor_{date_compact}.json")
    _merge_quality_issues(Path("logs") / f"observability_{date_compact}.json")


def _merge_stock_index_entry(orig: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """更新已存在的股票指数条目，缺失字段用原值或默认值兜底。"""
    merged = dict(orig)
    merged['symbol'] = payload.get('symbol', orig.get('symbol'))
    merged['name'] = payload.get('name', orig.get('name', merged['symbol']))
    merged['current_price'] = _coerce_float(payload.get('current_price') or payload.get('close') or payload.get('price')) or orig.get('current_price', 0.0)
    merged['change_5d'] = _coerce_float(payload.get('change_5d') or payload.get('change_5d_pct') or payload.get('weekly_change')) or orig.get('change_5d', 0.0)
    merged['change_120d'] = _coerce_float(
        payload.get('change_120d') or payload.get('change_120d_pct') or payload.get('ytd_change') or payload.get('change_ytd')
    ) or orig.get('change_120d', 0.0)
    merged['above_ma50'] = _coerce_bool(payload.get('above_ma50') if 'above_ma50' in payload else orig.get('above_ma50', False))
    merged['above_ma200'] = _coerce_bool(payload.get('above_ma200') if 'above_ma200' in payload else orig.get('above_ma200', False))
    merged['ma50_slope'] = _coerce_float(payload.get('ma50_slope')) or orig.get('ma50_slope', 0.0)
    merged['volatility_30d'] = _coerce_float(payload.get('volatility_30d') or payload.get('volatility')) or orig.get('volatility_30d', 0.0)
    merged['trend_score'] = int(payload.get('trend_score', orig.get('trend_score', 0)))
    merged['trend_label'] = payload.get('trend_label', orig.get('trend_label', '中性'))
    merged['source'] = _format_source_label(payload.get('source') or orig.get('source'))
    return merged


def _build_stock_index_entry(symbol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """为缺失的指数（如000016）构造完整条目，确保 Pydantic 校验通过。"""
    return {
        "symbol": symbol,
        "name": payload.get('name', symbol),
        "current_price": _coerce_float(payload.get('current_price') or payload.get('close') or payload.get('price')) or 0.0,
        "change_5d": _coerce_float(payload.get('change_5d') or payload.get('change_5d_pct') or payload.get('weekly_change')) or 0.0,
        "change_120d": _coerce_float(
            payload.get('change_120d') or payload.get('change_120d_pct') or payload.get('ytd_change') or payload.get('change_ytd')
        ) or 0.0,
        "above_ma50": _coerce_bool(payload.get('above_ma50')),
        "above_ma200": _coerce_bool(payload.get('above_ma200')),
        "ma50_slope": _coerce_float(payload.get('ma50_slope')) or 0.0,
        "volatility_30d": _coerce_float(payload.get('volatility_30d') or payload.get('volatility')) or 0.0,
        "trend_score": int(payload.get('trend_score', 0)),
        "trend_label": payload.get('trend_label', '中性'),
        "source": _format_source_label(payload.get('source')),
    }


def _merge_bond_entry(
    existing: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
) -> Dict[str, Any]:
    merged = dict(existing)
    merged['symbol'] = payload.get('symbol', existing.get('symbol'))
    merged['name'] = payload.get('name', existing.get('name', merged['symbol']))
    merged['current_yield'] = _coerce_float(payload.get('current_yield')) or existing.get('current_yield')

    # 从 trend_history 计算 bp 变化值
    current_yield = merged.get('current_yield')
    symbol = merged.get('symbol')
    used_hist_5d = False
    used_hist_120d = False
    if current_yield and symbol:
        hist_changes = _calc_change_from_trend_history("bonds", symbol, current_yield)
        merged['change_5d_bp'] = _coerce_float(payload.get('change_5d_bp'))
        if merged['change_5d_bp'] is None:
            hist_5d = _coerce_float(hist_changes.get('change_5d_bp'))
            if hist_5d is not None:
                merged['change_5d_bp'] = hist_5d
                used_hist_5d = True
            else:
                merged['change_5d_bp'] = existing.get('change_5d_bp', 0.0)
        merged['change_120d_bp'] = _coerce_float(payload.get('change_120d_bp'))
        if merged['change_120d_bp'] is None:
            hist_120d = _coerce_float(hist_changes.get('change_120d_bp'))
            if hist_120d is not None:
                merged['change_120d_bp'] = hist_120d
                used_hist_120d = True
            else:
                merged['change_120d_bp'] = existing.get('change_120d_bp', 0.0)
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
        merged['change_5d_bp'] = _coerce_float(payload.get('change_5d_bp')) or existing.get('change_5d_bp', 0.0)
        merged['change_120d_bp'] = _coerce_float(payload.get('change_120d_bp')) or existing.get('change_120d_bp', 0.0)

    # 自动推断债券趋势（基于bp变化）
    raw_trend = payload.get('trend', existing.get('trend'))
    merged['trend'] = _infer_asset_trend(raw_trend, merged.get('change_5d_bp'), merged.get('change_120d_bp'), "bond")
    merged['source'] = _format_source_label(payload.get('source') or existing.get('source'))
    payload_estimated = payload.get('is_estimated')
    if payload_estimated is not None:
        merged['is_estimated'] = bool(payload_estimated)
    else:
        merged['is_estimated'] = bool(existing.get('is_estimated', False))
        if is_manual and _has_valid_value(merged.get('current_yield')):
            merged['is_estimated'] = False
    merged['note'] = payload.get('note', existing.get('note'))
    return merged


def _merge_commodity_entry(
    existing: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
) -> Dict[str, Any]:
    merged = dict(existing)
    merged['symbol'] = payload.get('symbol', existing.get('symbol'))
    merged['name'] = payload.get('name', existing.get('name', merged['symbol']))
    merged['current_price'] = _coerce_float(payload.get('current_price')) or existing.get('current_price')
    merged['unit'] = payload.get('unit', existing.get('unit', ''))

    # 从 trend_history 计算变化值
    current_price = merged.get('current_price')
    symbol = merged.get('symbol')
    used_hist_5d = False
    used_hist_120d = False
    if current_price and symbol:
        hist_changes = _calc_change_from_trend_history("commodities", symbol, current_price)
        # daily_change 优先使用 payload，否则用历史计算的 change_5d
        merged['daily_change'] = _coerce_percent(payload.get('daily_change'))
        if merged['daily_change'] is None:
            hist_5d = _coerce_float(hist_changes.get('change_5d'))
            if hist_5d is not None:
                merged['daily_change'] = hist_5d
                used_hist_5d = True
            else:
                merged['daily_change'] = existing.get('daily_change', 0.0)
        # ytd_change 使用 trend_history 的 change_120d
        merged['ytd_change'] = _coerce_percent(payload.get('ytd_change'))
        if merged['ytd_change'] is None:
            hist_120d = _coerce_float(hist_changes.get('change_120d'))
            if hist_120d is not None:
                merged['ytd_change'] = hist_120d
                used_hist_120d = True
            else:
                merged['ytd_change'] = existing.get('ytd_change', 0.0)
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
        merged['daily_change'] = _coerce_percent(payload.get('daily_change')) or existing.get('daily_change', 0.0)
        merged['ytd_change'] = _coerce_percent(payload.get('ytd_change')) or existing.get('ytd_change', 0.0)

    # 自动推断商品趋势（基于涨跌幅）
    raw_trend = payload.get('trend', existing.get('trend'))
    merged['trend'] = _infer_asset_trend(raw_trend, merged.get('daily_change'), merged.get('ytd_change'), "commodity")
    merged['source'] = _format_source_label(payload.get('source') or existing.get('source'))
    merged['timestamp'] = payload.get('timestamp') or existing.get('timestamp') or datetime.now().strftime("%Y-%m-%d")
    merged['note'] = payload.get('note', existing.get('note'))
    if is_manual and 'is_estimated' not in payload and _has_valid_value(merged.get('current_price')):
        if 'is_estimated' in merged:
            merged['is_estimated'] = False
    return merged


def _merge_forex_entry(
    orig: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    is_manual: bool = False,
) -> Dict[str, Any]:
    merged = dict(orig)
    merged['pair'] = payload.get('pair', orig.get('pair'))
    merged['name'] = payload.get('name', orig.get('name', merged['pair']))
    merged['current_rate'] = _coerce_float(payload.get('current_rate')) or merged.get('current_rate')

    # 从 trend_history 计算变化值（daily_change 取前一交易日变化）
    current_rate = merged.get('current_rate')
    symbol = merged.get('pair')
    used_hist_1d = False
    used_hist_120d = False
    if current_rate and symbol:
        hist_changes = _calc_change_from_trend_history("forex", symbol, current_rate)
        daily_hist = _calc_daily_change_from_trend_history("forex", symbol, current_rate)
        merged['daily_change'] = _coerce_percent(payload.get('daily_change'))
        if merged['daily_change'] is None:
            hist_1d = _coerce_float(daily_hist.get('change_1d'))
            if hist_1d is not None:
                merged['daily_change'] = hist_1d
                used_hist_1d = True
            else:
                merged['daily_change'] = orig.get('daily_change', 0.0)
        merged['change_120d'] = _coerce_percent(payload.get('change_120d'))
        if merged['change_120d'] is None:
            hist_120d = _coerce_float(hist_changes.get('change_120d'))
            if hist_120d is not None:
                merged['change_120d'] = hist_120d
                used_hist_120d = True
            else:
                merged['change_120d'] = orig.get('change_120d', 0.0)
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
        merged['daily_change'] = _coerce_percent(payload.get('daily_change')) or orig.get('daily_change', 0.0)
        merged['change_120d'] = _coerce_percent(payload.get('change_120d')) or orig.get('change_120d', 0.0)

    # 自动推断外汇趋势（基于涨跌幅）
    raw_trend = payload.get('trend', orig.get('trend'))
    merged['trend'] = _infer_asset_trend(raw_trend, merged.get('daily_change'), merged.get('change_120d'), "forex")
    merged['source'] = _format_source_label(payload.get('source'))
    if is_manual and 'is_estimated' not in payload and _has_valid_value(merged.get('current_rate')):
        if 'is_estimated' in merged:
            merged['is_estimated'] = False
    return merged


def _build_forex_entry(payload: Dict[str, Any]) -> Dict[str, Any]:
    pair = payload.get('pair') or payload.get('symbol') or 'UNKNOWN'
    current_rate = _coerce_float(payload.get('current_rate'))

    # 从 trend_history 计算变化值（daily_change 取前一交易日变化）
    daily_change = _coerce_percent(payload.get('daily_change'))
    change_120d = _coerce_percent(payload.get('change_120d'))
    if current_rate and pair:
        hist_changes = _calc_change_from_trend_history("forex", pair, current_rate)
        daily_hist = _calc_daily_change_from_trend_history("forex", pair, current_rate)
        if daily_change is None:
            daily_change = daily_hist.get('change_1d') or 0.0
        if change_120d is None:
            change_120d = hist_changes.get('change_120d') or 0.0

    daily_change_val = daily_change or 0.0
    change_120d_val = change_120d or 0.0
    return {
        "pair": pair,
        "name": payload.get('name', pair),
        "current_rate": current_rate,
        "daily_change": daily_change_val,
        "change_120d": change_120d_val,
        "trend": _infer_asset_trend(payload.get('trend'), daily_change_val, change_120d_val, "forex"),
        "source": _format_source_label(payload.get('source')),
    }

if __name__ == '__main__':
    # 默认路径
    data_dir = Path(__file__).parent / 'data'

    market_data_file = data_dir / '20251114_market_data_enhanced_test.json'
    websearch_file = data_dir / 'websearch_results_20251114_test.json'
    output_file = data_dir / '20251114_market_data_complete_test.json'
    backfill_trend = True

    # 如果提供了命令行参数，使用它们
    raw_args = sys.argv[1:]
    flags = {arg for arg in raw_args if arg.startswith("--")}
    positional = [arg for arg in raw_args if not arg.startswith("--")]
    if "--no-backfill-trend" in flags or "--disable-backfill-trend" in flags:
        backfill_trend = False
    if "--backfill-trend" in flags:
        backfill_trend = True

    if len(positional) > 0:
        market_data_file = Path(positional[0])
    if len(positional) > 1:
        websearch_file = Path(positional[1])
    if len(positional) > 2:
        output_file = Path(positional[2])

    # 检查文件是否存在
    if not market_data_file.exists():
        print(f"[ERROR] 市场数据文件不存在: {market_data_file}")
        sys.exit(1)

    if not websearch_file.exists():
        print(f"[ERROR] WebSearch结果文件不存在: {websearch_file}")
        sys.exit(1)

    # 执行注入
    try:
        inject_websearch_data(
            market_data_path=market_data_file,
            websearch_path=websearch_file,
            output_path=output_file,
            backfill_trend=backfill_trend,
        )
    except Exception as e:
        print(f"\n[ERROR] 数据注入失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
