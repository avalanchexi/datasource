#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
手动资金流向数据更新工具

用途: AI执行MCP WebSearch后，使用此脚本更新market_data.json
用法: python scripts/utility/manual_fund_flow_updater.py --market-data <path> --flow-type <type> --data '<json>'
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from datasource.models.market_data_contract import FundFlowData


def update_fund_flow(
    market_data_path: str,
    flow_type: str,
    recent_5d: str,
    total_120d: str,
    trend: str,
    source: str,
    note: str = "",
    *,
    infer_trend: bool = True
) -> None:
    """更新market_data.json中的资金流向数据"""

    market_path = Path(market_data_path)
    if not market_path.exists():
        raise FileNotFoundError(f"market_data文件不存在: {market_path}")

    # 加载market_data
    with open(market_path, 'r', encoding='utf-8') as f:
        market_data = json.load(f)

    # 验证fund_flow字段存在
    if 'fund_flow' not in market_data:
        market_data['fund_flow'] = {}

    # 更新指定类型的资金流向数据
    if flow_type not in market_data['fund_flow']:
        market_data['fund_flow'][flow_type] = {
            'type': flow_type,
            'recent_5d': None,
            'total_120d': None,
            'trend': '待获取',
            'source': 'MCP WebSearch待获取',
            'note': ''
        }

    recent_value = FundFlowData._parse_amount(recent_5d)
    total_value = FundFlowData._parse_amount(total_120d)
    if recent_value is None and total_value is None:
        raise ValueError(
            f"无法解析资金流向金额，请检查输入: recent_5d='{recent_5d}', total_120d='{total_120d}'"
        )

    normalized_source, anomaly_note = _normalize_source_label(source, recent_value, total_value)
    inferred_trend = _infer_trend(trend, recent_value) if infer_trend else _require_manual_trend(trend)
    composed_note = _build_note(note, source, recent_5d, total_120d, anomaly_note)

    # 更新数据
    flow_entry = market_data['fund_flow'][flow_type]
    flow_entry['recent_5d'] = recent_value
    flow_entry['total_120d'] = total_value
    flow_entry['trend'] = inferred_trend
    flow_entry['source'] = normalized_source
    flow_entry['note'] = composed_note

    # 保存回文件
    with open(market_path, 'w', encoding='utf-8') as f:
        json.dump(market_data, f, ensure_ascii=False, indent=2)

    print(f"[OK] 已更新{flow_type}资金流向数据")
    print(f"  近5日: {recent_5d}")
    print(f"  近120日: {total_120d}")
    print(f"  趋势: {flow_entry['trend']}")
    print(f"  数据源: {flow_entry['source']}")


def _normalize_source_label(
    raw_source: str,
    recent_value: Optional[float],
    total_value: Optional[float]
) -> Tuple[str, Optional[str]]:
    abnormal = any(value == 0 for value in (recent_value, total_value) if value is not None)
    anomaly = "异常: 零值待WebSearch复核" if abnormal else None
    return "MCP WebSearch实时获取", anomaly


def _infer_trend(raw_trend: str, recent_value: Any) -> str:
    if isinstance(recent_value, (int, float)):
        if recent_value > 0:
            return '流入'
        if recent_value < 0:
            return '流出'
    return raw_trend or '未知'


def _require_manual_trend(raw_trend: str) -> str:
    cleaned = raw_trend.strip()
    if not cleaned:
        raise ValueError("未提供 --trend 值，且已选择 --trend-mode=manual")
    return cleaned


def _build_note(note: str, raw_source: str, recent_raw: str, total_raw: str, anomaly_note: Optional[str]) -> str:
    parts = []
    if raw_source:
        parts.append(f"来源:{raw_source}")
    if note:
        parts.append(note)
    if recent_raw:
        parts.append(f"原始5日:{recent_raw}")
    if total_raw:
        parts.append(f"原始120日:{total_raw}")
    if anomaly_note:
        parts.append(anomaly_note)
    return '；'.join(part for part in parts if part)


def main():
    parser = argparse.ArgumentParser(description='手动更新资金流向数据')
    parser.add_argument('--market-data', required=True, help='market_data.json路径')
    parser.add_argument('--flow-type', required=True,
                       choices=['northbound', 'southbound', 'etf', 'margin'],
                       help='资金流向类型')
    parser.add_argument('--recent-5d', required=True, help='近5日流向（如: +132.6亿、约55亿港元净流出）')
    parser.add_argument('--total-120d', required=True, help='近120日累计（如: +845.2亿）')
    parser.add_argument('--trend', default='', help='流向趋势（为空时自动根据数值推断）')
    parser.add_argument('--source', default='MCP WebSearch实时获取', help='数据来源（将自动规范化）')
    parser.add_argument('--note', default='', help='备注信息')
    parser.add_argument(
        '--trend-mode',
        choices=['auto', 'manual'],
        default='auto',
        help='auto=根据数值自动判定流入/流出，manual=完全使用 --trend 输入'
    )

    args = parser.parse_args()

    try:
        update_fund_flow(
            market_data_path=args.market_data,
            flow_type=args.flow_type,
            recent_5d=args.recent_5d,
            total_120d=args.total_120d,
            trend=args.trend,
            source=args.source,
            note=args.note,
            infer_trend=(args.trend_mode == 'auto')
        )
    except Exception as e:
        print(f"[ERROR] 更新失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
