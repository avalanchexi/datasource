#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
临时Pring分析脚本 - 用于测试
直接调用PringAnalyzer进行三层框架分析
"""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from datasource import get_manager
from datasource.calculators.pring_analyzer import PringAnalyzer
from datasource.models.market_data_contract import MarketDataContract
from datasource.utils.run_paths import build_run_paths

async def run_pring_analysis(input_file, output_file):
    """执行Pring三层框架分析"""

    print(f"[INFO] 输入文件: {input_file}")
    print(f"[INFO] 输出文件: {output_file}\n")

    # 读取市场数据
    print("[STEP 1] 读取市场数据...")
    with open(input_file, 'r', encoding='utf-8') as f:
        market_data = json.load(f)

    completeness = market_data['metadata']['data_completeness']
    print(f"  - 数据完整性: {completeness:.1%}")
    print(f"  - 宏观指标: {len([k for k, v in market_data['macro_indicators'].items() if v.get('current_value') is not None])}/5")
    print(f"  - 货币政策: {len([k for k, v in market_data['monetary_policy'].items() if v.get('current_value') is not None])}/5\n")

    # 初始化PringAnalyzer
    print("[STEP 2] 初始化Pring分析器...")
    manager = get_manager()
    market_contract = MarketDataContract(**market_data)
    analyzer = PringAnalyzer(manager, market_contract)

    # 执行三层框架分析
    print("[STEP 3] 执行Pring三层框架分析...")
    print("  - Layer 1: 库存周期分析 (PPI/PMI/Industrial/BDI/CPI)")
    print("  - Layer 2: 货币周期叠加 (RRR/Reverse Repo/MLF/TSF/M2)")
    print("  - Layer 3: Pring六阶段最终判定\n")

    try:
        result = await analyzer.analyze_pring_stage(120)

        # 直接使用完整结果，补充元数据并对齐 Stage3 字段
        pring_result = result or {}
        pring_result.setdefault("metadata", {})
        pring_result["metadata"].update({
            "analysis_date": market_data['metadata']['date'],
            "data_completeness": completeness,
            "analysis_method": pring_result.get("methodology", "Pring V4.0 三层框架"),
        })
        pring_result.setdefault("final_stage", pring_result.get("stage", "未知"))
        pring_result.setdefault("confidence", pring_result.get("confidence", 0.0))
        pring_result.setdefault("recommendation", pring_result.get("recommendation", "数据不足，无法生成建议"))
        pring_result.setdefault("asset_signals", result.get("asset_signals", {}))
        pring_result.setdefault("asset_allocation_pct", result.get("asset_allocation_pct", {}))
        pring_result.setdefault("leading_indicator", result.get("leading_indicator", {}))
        pring_result.setdefault("pending_websearch", result.get("pending_websearch", []))
        pring_result["data_completeness"] = completeness

        # 保存结果
        print("[STEP 4] 保存分析结果...")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(pring_result, f, ensure_ascii=False, indent=2)

        # 打印摘要
        print(f"\n[SUCCESS] Pring分析完成！")
        print(f"  - 最终阶段: {pring_result['final_stage']}")
        print(f"  - 置信度: {pring_result['confidence']:.1%}")
        print(f"  - Layer 1: {pring_result['layer_1_inventory_cycle'].get('cycle_stage', 'N/A')}")
        print(f"  - Layer 2: {pring_result['layer_2_monetary_cycle'].get('cycle_stage', 'N/A')}")
        print(f"  - 输出文件: {output_file}\n")

        return pring_result

    except Exception as e:
        print(f"\n[ERROR] Pring分析失败: {e}")
        import traceback
        traceback.print_exc()

        # 创建失败结果
        error_result = {
            "metadata": {
                "analysis_date": market_data['metadata']['date'],
                "data_completeness": completeness,
                "error": str(e)
            },
            "final_stage": "分析失败",
            "confidence": 0.0,
            "recommendation": "分析过程中出现错误，请检查数据完整性"
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(error_result, f, ensure_ascii=False, indent=2)

        return error_result

if __name__ == '__main__':
    import sys

    defaults = build_run_paths(datetime.now().strftime("%Y-%m-%d"))
    input_path = defaults.market_data_complete
    output_path = defaults.pring_result

    if len(sys.argv) > 1:
        input_path = Path(sys.argv[1])
    if len(sys.argv) > 2:
        output_path = Path(sys.argv[2])

    # 运行分析
    asyncio.run(run_pring_analysis(input_path, output_path))
