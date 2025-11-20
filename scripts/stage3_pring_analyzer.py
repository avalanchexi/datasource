#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 3: Pring 三层框架分析脚本

该脚本用于在完成 Stage 1/2a/AI 补全之后，读取 `market_data_complete.json`
并调用 `PringAnalyzer` 输出最终的三层分析结果。文件内部的提示信息、
日志和注释全部重新整理为中文，避免原始文件中的乱码问题。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from datasource import get_manager
from datasource.calculators.pring_analyzer import PringAnalyzer
from datasource.models.market_data_contract import MarketDataContract


def _load_gap_monitor() -> Dict[str, List[str]]:
    gap_path = Path("reports/gap_monitor.json")
    if not gap_path.exists():
        return {"pending_tasks": [], "manual_required": []}
    try:
        with gap_path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {"pending_tasks": [], "manual_required": []}


async def _run_analysis(market_path: Path, output_path: Path) -> Dict[str, Any]:
    """执行 Pring 三层框架分析。

    Args:
        market_path: Stage 1/2 生成的 `market_data_complete.json` 路径。
        output_path: 保存 Pring 分析结果的路径。
    """

    print(f"[INFO] 读取市场数据: {market_path}")
    with market_path.open('r', encoding='utf-8') as fp:
        market_payload = json.load(fp)

    contract = MarketDataContract(**market_payload)
    ai_websearch_flag = bool(contract.metadata.get('ai_websearch_enhanced'))

    gap = _load_gap_monitor()
    pending = gap.get("pending_tasks", [])
    manual = gap.get("manual_required", [])
    if pending or manual:
        raise RuntimeError(
            f"Gap monitor 未清空，pending: {pending}, manual_required: {manual}。请先补全缺口后再运行 Stage3。"
        )
    if not ai_websearch_flag:
        raise RuntimeError("未检测到 Stage2 WebSearch 标记 (metadata.ai_websearch_enhanced)。请先完成 Stage2。")

    manager = get_manager()
    analyzer = PringAnalyzer(manager, contract)

    completeness = contract.metadata.get('data_completeness', 0.0)
    print(f"[META] 数据完整性：{completeness:.1%}")
    print(f"[META] AI WebSearch 注入：{'已完成' if ai_websearch_flag else '未检测到'}")
    print(f"[META] 宏观指标：{len(contract.macro_indicators)} 项，"
          f"货币政策：{len(contract.monetary_policy)} 项")

    print("[STEP] 开始执行三层框架分析：库存周期 → 货币周期 → Pring阶段")
    result = await analyzer.analyze_pring_stage(120)

    pring_result = {
        "metadata": {
            "analysis_date": contract.metadata.get('date'),
            "data_completeness": completeness,
            "analysis_method": "Pring V4.0 三层框架",
            "confidence_level": result.get('confidence', 0.0),
        },
        "layer_1_inventory_cycle": result.get('layer_1_inventory_cycle', {}),
        "layer_2_monetary_cycle": result.get('layer_2_monetary_cycle', {}),
        "layer_3_pring_final": result.get('layer_3_pring_final', {}),
        "final_stage": result.get('stage', '未知'),
        "confidence": result.get('confidence', 0.0),
        "recommendation": result.get('recommendation', '数据不足，无法生成建议'),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        backup = output_path.with_suffix(output_path.suffix + ".bak")
        shutil.copy2(output_path, backup)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp.open('w', encoding='utf-8') as fp:
        json.dump(pring_result, fp, ensure_ascii=False, indent=2)
    tmp.replace(output_path)

    print("[SUCCESS] Pring 分析完成：")
    print(f"         最终阶段: {pring_result['final_stage']}")
    print(f"         置信度: {pring_result['confidence']:.1%}")
    return pring_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 3: 执行 Pring 三层分析",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--market-data",
        default="data/market_data.json",
        help="Stage 1/2 生成的 market_data.json",
    )
    parser.add_argument(
        "--output",
        default="data/pring_result.json",
        help="Pring 分析结果输出路径",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    market_path = Path(args.market_data).resolve()
    output_path = Path(args.output).resolve()

    if not market_path.exists():
        raise FileNotFoundError(f"未找到市场数据文件: {market_path}")

    asyncio.run(_run_analysis(market_path, output_path))


if __name__ == "__main__":
    main()
