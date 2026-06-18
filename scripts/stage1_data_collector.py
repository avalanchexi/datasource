#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 1: Market Data Collector (V3.1 解耦架构)
职责: 收集所有市场数据,输出标准JSON格式
输出: data/runs/YYYYMMDD/market_data.json
"""

import asyncio
import argparse
from pathlib import Path

from datasource.models.market_data_contract import FundFlowData  # noqa: F401
from datasource.utils.json_io import atomic_write_json
from datasource.utils.trend_history_store import (
    write_from_market_data,
    write_trend_history_gap_snapshot,
)
from datasource.utils.run_paths import build_run_paths
from datasource.engines.stage1.collector import (  # noqa: F401 (C6 re-export)
    MarketDataCollector,
    Stage1DataCollector,
    _calc_change_from_trend_history,
    _is_missing_change,
    _backfill_stage1_trend,
    _normalize_date_str,
    _resolve_last_trading_day,
)


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Stage 1: 市场数据收集器')
    parser.add_argument('--date', required=True, help='结束日期 (YYYY-MM-DD 或 YYYYMMDD)')
    parser.add_argument('--output', help='输出JSON文件路径 (默认: data/runs/YYYYMMDD/market_data.json)')

    args = parser.parse_args()

    # 统一日期格式，容忍 YYYYMMDD
    try:
        normalized_date = _normalize_date_str(args.date)
    except ValueError as ve:
        print(f"[ERROR] {ve}")
        return

    # 若传入日期为休市日，则回退到最近交易日
    trading_date = _resolve_last_trading_day(normalized_date)
    if trading_date != normalized_date:
        print(f"[INFO] 目标日期 {normalized_date} 为休市日，自动回退至最近交易日 {trading_date}")
    else:
        print(f"[INFO] 使用交易日: {trading_date}")

    run_paths = build_run_paths(trading_date)
    output_path = Path(args.output) if args.output else run_paths.market_data

    # Pre-scan trend_history gaps before Stage1 collection
    try:
        gap_output = run_paths.trend_history_gap
        write_trend_history_gap_snapshot(trading_date, gap_output)
        print(f"[INFO] trend_history gap snapshot refreshed: {gap_output}")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] trend_history gap snapshot refresh failed: {exc}")

    # 创建收集器
    collector = MarketDataCollector(
        end_date=trading_date
    )

    # 收集数据
    contract = await collector.collect_all_data()
    market_payload = contract.model_dump()

    # 回读 trend_history 补充缺失变化值（避免 120d 为 N/A）
    try:
        backfilled = _backfill_stage1_trend(market_payload)
        if backfilled:
            print(f"[INFO] trend_history backfill applied: {backfilled} fields")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] trend_history backfill failed: {exc}")

    # 保存JSON
    atomic_write_json(market_payload, output_path)

    print(f"[OK] 数据已保存到: {output_path}")
    print(f"   文件大小: {output_path.stat().st_size / 1024:.1f} KB")

    # Partial write to trend_history (TuShare-available daily values)
    try:
        write_count = write_from_market_data(market_payload, is_partial=True, source_path=output_path)
        print(f"[INFO] trend_history partial write: {write_count} items")
        try:
            write_trend_history_gap_snapshot(trading_date, run_paths.trend_history_gap)
            print(f"[INFO] trend_history gap snapshot refreshed: {run_paths.trend_history_gap}")
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] trend_history gap snapshot refresh failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] trend_history partial write failed: {exc}")


if __name__ == '__main__':
    asyncio.run(main())
