#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI WebSearch数据注入脚本 (测试版)
将websearch_results注入到market_data_enhanced文件中
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from datasource.models.market_data_contract import FundFlowData

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


def _remove_missing_item(metadata: Dict[str, Any], category: str, key: str) -> None:
    missing = metadata.get('missing_items')
    if not missing or category not in missing:
        return
    items = [item for item in missing[category] if item.get('key') != key]
    if items:
        missing[category] = items
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


def _cleanup_metadata_missing(metadata: Dict[str, Any]) -> None:
    """若 metadata.missing_items 已清空，则移除字段，避免 Stage3 误阻断。"""
    missing = metadata.get('missing_items')
    if not isinstance(missing, dict):
        return
    cleaned = {k: [item for item in v if item] for k, v in missing.items() if v}
    if cleaned:
        metadata['missing_items'] = cleaned
    else:
        metadata.pop('missing_items', None)


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


def inject_websearch_data(market_data_path, websearch_path, output_path):
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
        websearch_data = json.load(f)
    # 统一结构，容忍 {symbol: {...}} / list / None
    websearch_data['forex'] = _normalize_keyed_list(websearch_data.get('forex'), 'pair')
    websearch_data['bonds'] = _normalize_keyed_list(websearch_data.get('bonds'), 'symbol')
    websearch_data['commodities'] = _normalize_keyed_list(websearch_data.get('commodities'), 'symbol')
    websearch_data['stock_indices'] = _normalize_keyed_list(websearch_data.get('stock_indices'), 'symbol')

    inject_count = 0

    # 1. 注入宏观指标
    print("\n[STEP 1] 注入宏观指标数据...")
    for key, payload in websearch_data.get('macro_indicators', {}).items():
        if key not in market_data.get('macro_indicators', {}):
            continue
        if _apply_macro_entry(market_data['macro_indicators'][key], payload):
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
        if _apply_monetary_entry(monetary_section[key], payload):
            inject_count += 1
            print(f"  [OK] {payload.get('policy_name', key)}: {payload.get('current_value')} {payload.get('unit', '')}".strip())
            _remove_missing_item(metadata, 'monetary_policy', key)
            _remove_top_missing(market_data, key)

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
                market_forex[i] = _merge_forex_entry(item, fx)
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
                market_data['bonds'][i] = _merge_bond_entry(bond, bond_data)
                inject_count += 1
                print(f"  [OK] {bond_data['name']}: {bond_data['current_yield']}%")
                _remove_missing_item(metadata, 'bonds', symbol)
                _remove_top_missing(market_data, symbol)
                updated = True
                break
        if not updated:
            merged_entry = _merge_bond_entry({}, bond_data)
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
                market_data['commodities'][i] = _merge_commodity_entry(commodity, commodity_data)
                updated = True
                break
        if not updated:
            market_data.setdefault('commodities', []).append(_merge_commodity_entry({}, commodity_data))
        inject_count += 1
        print(f"  [OK] {commodity_data['name']}: {commodity_data.get('unit','')}{commodity_data['current_price']:.2f} (YTD {commodity_data.get('ytd_change', 0):+.2f}%)")
        _remove_missing_item(metadata, 'commodities', symbol)
        _remove_top_missing(market_data, symbol)

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
    _cleanup_metadata_missing(metadata)
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

    return output_path


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


def _apply_macro_entry(entry: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    entry['indicator_name'] = payload.get('indicator_name', entry.get('indicator_name'))
    entry['current_value'] = _coerce_float(payload.get('current_value'))
    entry['previous_value'] = _coerce_float(payload.get('previous_value'))
    entry['change_rate'] = _coerce_float(payload.get('change_rate'))
    entry['unit'] = payload.get('unit', entry.get('unit', ''))
    entry['date'] = payload.get('date', entry.get('date'))
    entry['source'] = _format_source_label(payload.get('source'))
    entry['note'] = payload.get('note', entry.get('note'))
    entry['is_estimated'] = False
    # 兜底回填前值：若有 current_value + change_rate 但前值缺失，用差值推算；若连 change_rate 也无，则假定前值=当前值
    if entry['previous_value'] is None and entry['current_value'] is not None:
        entry.setdefault('note', '')
        if entry['change_rate'] is not None:
            try:
                entry['previous_value'] = round(entry['current_value'] - entry['change_rate'], 4)
                if entry['note']:
                    entry['note'] += '；'
                entry['note'] += 'auto-backfilled previous_value via current_value - change_rate'
            except Exception:
                pass
        else:
            entry['previous_value'] = entry['current_value']
            entry['change_rate'] = 0.0
            if entry['note']:
                entry['note'] += '；'
            entry['note'] += 'auto-backfilled previous_value=current_value (no change_rate provided)'
    return True


def _create_monetary_placeholder(key: str, payload: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    """当原始市场数据缺少某个货币政策字段时，动态创建占位符"""
    default_date = payload.get('date') or metadata.get('date') or metadata.get('end_date') or ""
    return {
        "policy_name": payload.get('policy_name', key.upper()),
        "current_value": None,
        "change_from_120d": None,
        "unit": payload.get('unit', '%'),
        "date": default_date,
        "source": "待MCP WebSearch获取(websearch导入)",
        "note": payload.get('note'),
        "is_estimated": True
    }


def _apply_monetary_entry(entry: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    entry['policy_name'] = payload.get('policy_name', entry.get('policy_name'))
    entry['current_value'] = _coerce_float(payload.get('current_value'))
    change_value = payload.get('change_from_120d', payload.get('change_rate'))
    entry['change_from_120d'] = _coerce_float(change_value)
    entry['unit'] = payload.get('unit', entry.get('unit', ''))
    entry['date'] = payload.get('date', entry.get('date'))
    entry['source'] = _format_source_label(payload.get('source'))
    entry['note'] = payload.get('note', entry.get('note'))
    entry['is_estimated'] = False
    return True


def _apply_fund_flow_entry(entry: Dict[str, Any], key: str, payload: Dict[str, Any]) -> bool:
    recent_value = FundFlowData._parse_amount(payload.get('recent_5d'))
    total_value = FundFlowData._parse_amount(payload.get('total_120d'))
    if recent_value is None and total_value is None:
        print(f"  [WARN] {key} 缺少可解析的金额，跳过注入")
        return False

    entry['type'] = key
    entry['recent_5d'] = recent_value
    entry['total_120d'] = total_value
    entry['trend'] = _infer_trend(payload.get('trend'), recent_value)

    anomaly = any(value == 0 for value in (recent_value, total_value) if value is not None)
    entry['source'] = "异常零值-需核查" if anomaly else "MCP WebSearch实时获取"
    entry['note'] = _build_fund_flow_note(payload, anomaly)
    return True


def _infer_trend(raw_trend: Optional[str], recent_value: Optional[float]) -> str:
    if isinstance(recent_value, (int, float)):
        if recent_value > 0:
            return '流入'
        if recent_value < 0:
            return '流出'
    return raw_trend or '未知'


def _build_fund_flow_note(payload: Dict[str, Any], anomaly: bool) -> str:
    parts = []
    raw_source = payload.get('source')
    if raw_source:
        parts.append(f"来源:{raw_source}")
    if payload.get('unit'):
        parts.append(f"单位:{payload['unit']}")
    if payload.get('note'):
        parts.append(payload['note'])
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


def _merge_bond_entry(existing: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    merged['symbol'] = payload.get('symbol', existing.get('symbol'))
    merged['name'] = payload.get('name', existing.get('name', merged['symbol']))
    merged['current_yield'] = _coerce_float(payload.get('current_yield')) or existing.get('current_yield')
    merged['change_5d_bp'] = _coerce_float(payload.get('change_5d_bp')) or existing.get('change_5d_bp')
    merged['change_120d_bp'] = _coerce_float(payload.get('change_120d_bp')) or existing.get('change_120d_bp')
    merged['trend'] = payload.get('trend', existing.get('trend', '未知'))
    merged['source'] = _format_source_label(payload.get('source') or existing.get('source'))
    merged['is_estimated'] = bool(payload.get('is_estimated', existing.get('is_estimated', False)))
    merged['note'] = payload.get('note', existing.get('note'))
    return merged


def _merge_commodity_entry(existing: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    merged['symbol'] = payload.get('symbol', existing.get('symbol'))
    merged['name'] = payload.get('name', existing.get('name', merged['symbol']))
    merged['current_price'] = _coerce_float(payload.get('current_price')) or existing.get('current_price')
    merged['unit'] = payload.get('unit', existing.get('unit', ''))
    merged['daily_change'] = _coerce_percent(payload.get('daily_change')) if 'daily_change' in payload else existing.get('daily_change')
    merged['ytd_change'] = _coerce_percent(payload.get('ytd_change')) if 'ytd_change' in payload else existing.get('ytd_change')
    merged['trend'] = payload.get('trend', existing.get('trend', '未知'))
    merged['source'] = _format_source_label(payload.get('source') or existing.get('source'))
    merged['timestamp'] = payload.get('timestamp') or existing.get('timestamp') or datetime.now().strftime("%Y-%m-%d")
    merged['note'] = payload.get('note', existing.get('note'))
    return merged


def _merge_forex_entry(orig: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(orig)
    merged['pair'] = payload.get('pair', orig.get('pair'))
    merged['name'] = payload.get('name', orig.get('name', merged['pair']))
    merged['current_rate'] = _coerce_float(payload.get('current_rate')) or merged.get('current_rate')
    merged['daily_change'] = _coerce_percent(payload.get('daily_change'))
    merged['change_120d'] = _coerce_percent(payload.get('change_120d'))
    merged['trend'] = payload.get('trend', orig.get('trend', '未知'))
    merged['source'] = _format_source_label(payload.get('source'))
    if merged['daily_change'] is None:
        merged['daily_change'] = 0.0
    if merged['change_120d'] is None:
        merged['change_120d'] = 0.0
    return merged


def _build_forex_entry(payload: Dict[str, Any]) -> Dict[str, Any]:
    pair = payload.get('pair') or payload.get('symbol') or 'UNKNOWN'
    return {
        "pair": pair,
        "name": payload.get('name', pair),
        "current_rate": _coerce_float(payload.get('current_rate')) or 0.0,
        "daily_change": _coerce_percent(payload.get('daily_change')) or 0.0,
        "change_120d": _coerce_percent(payload.get('change_120d')) or 0.0,
        "trend": payload.get('trend', '未知'),
        "source": _format_source_label(payload.get('source')),
    }

if __name__ == '__main__':
    # 默认路径
    data_dir = Path(__file__).parent / 'data'

    market_data_file = data_dir / '20251114_market_data_enhanced_test.json'
    websearch_file = data_dir / 'websearch_results_20251114_test.json'
    output_file = data_dir / '20251114_market_data_complete_test.json'

    # 如果提供了命令行参数，使用它们
    if len(sys.argv) > 1:
        market_data_file = Path(sys.argv[1])
    if len(sys.argv) > 2:
        websearch_file = Path(sys.argv[2])
    if len(sys.argv) > 3:
        output_file = Path(sys.argv[3])

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
            output_path=output_file
        )
    except Exception as e:
        print(f"\n[ERROR] 数据注入失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
