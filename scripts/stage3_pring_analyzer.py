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
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from datasource import get_manager
from datasource.calculators.pring_analyzer import PringAnalyzer
from datasource.models.market_data_contract import MarketDataContract

MIN_COMPLETENESS_DEFAULT = 0.80


def _flatten_missing_items(market_payload: Dict[str, Any]) -> List[str]:
    """提取并扁平化缺口列表，兼容 metadata.missing_items 与顶层 missing_items。"""
    missing: List[str] = []
    top_level = market_payload.get("missing_items", [])
    if isinstance(top_level, list):
        for item in top_level:
            if isinstance(item, dict):
                key = item.get("key") or item.get("indicator_key")
                if key:
                    missing.append(str(key))
            else:
                missing.append(str(item))
    metadata_missing = market_payload.get("metadata", {}).get("missing_items", {})
    if isinstance(metadata_missing, dict):
        for _, items in metadata_missing.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict):
                    key = it.get("key") or it.get("indicator_key")
                    if key:
                        missing.append(str(key))
                else:
                    missing.append(str(it))
    # 去重保持顺序
    seen = set()
    unique = []
    for k in missing:
        if k in seen:
            continue
        seen.add(k)
        unique.append(k)
    return unique


def _require_data_completeness(
    market_payload: Dict[str, Any],
    min_completeness: float,
    allow_estimated: bool = False,
) -> None:
    """在开始 Stage3 之前阻断缺失数据的情形。"""
    metadata = market_payload.get("metadata", {})
    completeness = metadata.get("data_completeness", 0.0) or 0.0
    missing_items = _flatten_missing_items(market_payload)
    # 若允许估算值，自动忽略那些已经被估算填充但仍留在 missing 列表中的条目
    if allow_estimated:
        def _has_non_null_value(key: str) -> bool:
            # fund flow
            flow = market_payload.get("fund_flow", {}).get(key)
            if isinstance(flow, dict) and flow.get("recent_5d") not in (None, 0) and flow.get("total_120d") not in (None, 0):
                return True
            # forex
            for fx in market_payload.get("forex", []):
                if fx.get("pair") == key and fx.get("current_rate") not in (None, 0):
                    return True
            # bonds
            for bond in market_payload.get("bonds", []):
                if bond.get("symbol") == key and bond.get("current_yield") not in (None, 0):
                    return True
            # commodities
            for com in market_payload.get("commodities", []):
                if com.get("symbol") == key and com.get("current_price") not in (None, 0):
                    return True
            # macro
            indicator = market_payload.get("macro_indicators", {}).get(key)
            if isinstance(indicator, dict) and indicator.get("current_value") is not None:
                return True
            # monetary
            policy = market_payload.get("monetary_policy", {}).get(key)
            if isinstance(policy, dict) and policy.get("current_value") is not None:
                return True
            return False

        missing_items = [k for k in missing_items if not _has_non_null_value(k)]
    # 硬阻断占位/零值：fund_flow/forex/bonds/commodities 中的 0 或 None
    hard_gaps = []
    for flow in market_payload.get("fund_flow", {}).values():
        if flow.get("recent_5d") in (0, None) or flow.get("total_120d") in (0, None):
            hard_gaps.append(flow.get("type"))
    for fx in market_payload.get("forex", []):
        if fx.get("current_rate") in (0, None):
            hard_gaps.append(fx.get("pair"))
    for bond in market_payload.get("bonds", []):
        if bond.get("current_yield") in (0, None):
            hard_gaps.append(bond.get("symbol"))
    for com in market_payload.get("commodities", []):
        if com.get("current_price") in (0, None):
            hard_gaps.append(com.get("symbol"))
    if hard_gaps:
        raise RuntimeError(f"检测到占位/零值数据: {', '.join(set(map(str, hard_gaps)))}。请补齐真实数据后再运行 Stage3。")

    if missing_items or completeness < min_completeness:
        msg_lines = [
            f"检测到数据缺口或完整性不足: completeness={completeness:.3f} (<{min_completeness})",
        ]
        if missing_items:
            msg_lines.append(f"缺口: {', '.join(missing_items)}")
        msg_lines.append(
            "请先运行 Stage2/Stage2.5 补数，示例："
        )
        msg_lines.append(
            "  PYTHONPATH=. python scripts/stage2_unified_enhancer.py "
            "--market-data data/market_data.json "
            "--output data/market_data_stage2.json "
            "--execute-search --fund-flow-backend hybrid "
            "--cache-backend sqlite --cache-path reports/tavily_cache.sqlite "
            "--websearch-results reports/websearch_results_auto.json "
            "--gap-monitor reports/gap_monitor.json"
        )
        msg_lines.append(
            "若仅需重注入 WebSearch: "
            "python inject_websearch_data_test.py "
            "data/market_data_stage2.json reports/websearch_results_auto.json data/market_data_complete.json"
        )
        raise RuntimeError("\n".join(msg_lines))


def _load_gap_monitor(gap_path: Path) -> Dict[str, List[str]]:
    if not gap_path.exists():
        return {"pending_tasks": [], "manual_required": []}
    try:
        with gap_path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {"pending_tasks": [], "manual_required": []}


async def _run_analysis(
    market_path: Path,
    output_path: Path,
    min_completeness: float = MIN_COMPLETENESS_DEFAULT,
    gap_monitor_path: Optional[Path] = None,
    skip_gap_check: bool = False,
    days: int = 120,
    allow_fallback: bool = False,
    allow_estimated: bool = False,
    legacy_stage_rules: bool = False,
) -> Dict[str, Any]:
    """执行 Pring 三层框架分析。

    Args:
        market_path: Stage 1/2 生成的 `market_data_complete.json` 路径。
        output_path: 保存 Pring 分析结果的路径。
    """

    start_ts = time.time()

    print(f"[INFO] 读取市场数据: {market_path}")
    with market_path.open('r', encoding='utf-8') as fp:
        market_payload = json.load(fp)

    fallback_used = False
    try:
        _require_data_completeness(market_payload, min_completeness, allow_estimated=allow_estimated)
    except RuntimeError as e:
        if allow_fallback:
            fallback_used = True
            print(f"[WARN] 数据完整性未达标，但 allow_fallback=True，继续运行。原因: {e}")
        else:
            raise

    contract = MarketDataContract(**market_payload)
    ai_websearch_flag = bool(contract.metadata.get('ai_websearch_enhanced'))

    gap_path = gap_monitor_path or Path("reports/gap_monitor.json")
    if not skip_gap_check:
        gap = _load_gap_monitor(gap_path)
        pending = gap.get("pending_tasks", [])
        manual = gap.get("manual_required", [])
        if pending or manual:
            raise RuntimeError(
                f"Gap monitor 未清空，pending: {pending}, manual_required: {manual}。请先补全缺口后再运行 Stage3。"
            )
    else:
        print(f"[WARN] 已跳过 gap_monitor 检查（调试模式），路径: {gap_path}")
    if not ai_websearch_flag:
        raise RuntimeError("未检测到 Stage2 WebSearch 标记 (metadata.ai_websearch_enhanced)。请先完成 Stage2。")

    manager = get_manager()
    analyzer = PringAnalyzer(
        manager,
        contract,
        use_legacy_stage_rules=legacy_stage_rules,
        allow_estimated=allow_estimated,
    )

    completeness = contract.metadata.get('data_completeness', 0.0)
    print(f"[META] 数据完整性：{completeness:.1%}")
    print(f"[META] AI WebSearch 注入：{'已完成' if ai_websearch_flag else '未检测到'}")
    print(f"[META] 宏观指标：{len(contract.macro_indicators)} 项，"
          f"货币政策：{len(contract.monetary_policy)} 项")

    print("[STEP] 开始执行三层框架分析：库存周期 → 货币周期 → Pring阶段")
    result = await analyzer.analyze_pring_stage(days)

    pring_result = result or {}
    pring_result.setdefault("metadata", {})
    pring_result["metadata"].update({
        "analysis_date": contract.metadata.get('date'),
        "data_completeness": completeness,
        "analysis_method": "Pring V4.0 三层框架",
        "ai_websearch_enhanced": ai_websearch_flag,
        "gap_monitor_cleared": True,
        "min_completeness": min_completeness,
    })
    pring_result.setdefault("final_stage", pring_result.get("stage", "未知"))
    pring_result.setdefault("confidence", pring_result.get("confidence", 0.0))
    pring_result.setdefault("recommendation", pring_result.get("recommendation", "数据不足，无法生成建议"))
    pring_result["data_period"] = f"{days}天历史数据"
    pring_result["fallback_used"] = fallback_used
    pring_result.setdefault("pending_websearch", [])
    pring_result["data_completeness"] = completeness
    pring_result["weights_version"] = "stage_weights_v1"

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

    runtime = time.time() - start_ts
    log_payload = {
        "input": {
            "market_data": str(market_path),
            "output": str(output_path),
            "ai_websearch_enhanced": ai_websearch_flag,
            "gap_monitor": str(gap_path),
            "gap_check_skipped": skip_gap_check,
        },
        "completeness": {
            "value": completeness,
            "min_required": min_completeness,
        },
        "stage": {
            "final_stage": pring_result.get("final_stage"),
            "confidence": pring_result.get("confidence"),
            "base_stage": pring_result.get("layer_3_pring_final", {}).get("base_stage"),
        },
        "data_sources": {
            "macro": pring_result.get("layer_1_inventory_cycle", {}).get("data_source"),
            "monetary": pring_result.get("layer_2_monetary_cycle", {}).get("data_source"),
            "asset": "market_price",
        },
        "fallback_used": fallback_used,
        "warnings": [],
        "errors": [],
        "runtime_sec": round(runtime, 2),
    }
    log_path = Path("reports/pring_stage3_log.json")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_log = log_path.with_suffix(".tmp")
    with tmp_log.open("w", encoding="utf-8") as fp:
        json.dump(log_payload, fp, ensure_ascii=False, indent=2)
    tmp_log.replace(log_path)

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
    parser.add_argument(
        "--days",
        type=int,
        default=120,
        help="资产信号回看窗口天数"
    )
    parser.add_argument(
        "--min-completeness",
        type=float,
        default=MIN_COMPLETENESS_DEFAULT,
        help="运行前数据完整性最低要求，低于该值将直接终止"
    )
    parser.add_argument(
        "--gap-monitor",
        default="reports/gap_monitor.json",
        help="Gap monitor 文件路径，用于阻断未补齐的任务"
    )
    parser.add_argument(
        "--skip-gap-check",
        action="store_true",
        help="跳过 gap monitor 检查（仅调试用，生产禁止）"
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="允许在数据缺失时继续（不推荐，生产请保持关闭）"
    )
    parser.add_argument(
        "--allow-estimated",
        action="store_true",
        help="允许使用 WebSearch/估算值填补缺口（默认仅接受权威/非估算数据）"
    )
    parser.add_argument(
        "--legacy-stage-rules",
        action="store_true",
        help="启用旧版静态阶段映射（回滚/对比用）"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    market_path = Path(args.market_data).resolve()
    output_path = Path(args.output).resolve()
    min_completeness = float(args.min_completeness)
    days = int(args.days)

    if not market_path.exists():
        raise FileNotFoundError(f"未找到市场数据文件: {market_path}")

    asyncio.run(_run_analysis(
        market_path,
        output_path,
        min_completeness=min_completeness,
        gap_monitor_path=Path(args.gap_monitor),
        skip_gap_check=args.skip_gap_check,
        days=days,
        allow_fallback=args.allow_fallback,
        allow_estimated=args.allow_estimated,
        legacy_stage_rules=args.legacy_stage_rules,
    ))


if __name__ == "__main__":
    main()
