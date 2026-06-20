"""Stage3 Pring 三层框架分析 CLI。"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from datasource.engines.stage3 import core
from datasource.utils.run_lock import DailyRunLock, run_dir_from_artifact
from datasource.utils.run_paths import build_run_paths_from_reference


def parse_args() -> argparse.Namespace:
    default_paths = build_run_paths_from_reference(fallback_to_today=True)
    parser = argparse.ArgumentParser(
        description="Stage 3: 执行 Pring 三层分析",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--market-data",
        default=str(default_paths.market_data_complete),
        help="Stage 1/2 生成的 market_data.json",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Pring 分析结果输出路径",
    )
    parser.add_argument(
        "--days", type=int, default=120, help="资产信号回看窗口天数"
    )
    parser.add_argument(
        "--min-completeness",
        type=float,
        default=core.MIN_COMPLETENESS_DEFAULT,
        help="运行前数据完整性最低要求，低于该值将直接终止",
    )
    parser.add_argument(
        "--gap-monitor",
        default=None,
        help=(
            "可选：显式指定 gap monitor 路径；默认优先按 market_data "
            "日期匹配 data/runs/YYYYMMDD/gap_monitor.json"
        ),
    )
    parser.add_argument(
        "--skip-gap-check",
        action="store_true",
        help="跳过 gap monitor 检查（仅调试用，生产禁止）",
    )
    parser.add_argument(
        "--skip-fund-flow-check",
        action="store_true",
        help="跳过 fund_flow 的占位/零值硬阻断（仅在资金流缺口时临时出报告用）",
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="允许在数据缺失时继续（不推荐，生产请保持关闭）",
    )
    parser.add_argument(
        "--allow-estimated",
        action="store_true",
        help="允许使用 WebSearch/估算值填补缺口（默认仅接受权威/非估算数据）",
    )
    parser.add_argument(
        "--legacy-stage-rules",
        action="store_true",
        help="启用旧版静态阶段映射（回滚/对比用）",
    )
    parser.add_argument(
        "--no-validate-output",
        action="store_true",
        help="跳过写盘前 contract 校验(逃生门)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if getattr(args, "no_validate_output", False):
        os.environ["DATASOURCE_NO_VALIDATE_OUTPUT"] = "1"

    market_path = Path(args.market_data).resolve()
    min_completeness = float(args.min_completeness)
    days = int(args.days)

    if not market_path.exists():
        raise FileNotFoundError(f"未找到市场数据文件: {market_path}")

    output_path = (
        Path(args.output).resolve()
        if args.output
        else (market_path.parent / "pring_result.json").resolve()
    )

    with DailyRunLock(
        run_dir_from_artifact(output_path), owner="stage3_pring_analyzer"
    ).acquire():
        asyncio.run(
            core._run_analysis(
                market_path,
                output_path,
                min_completeness=min_completeness,
                gap_monitor_path=(
                    Path(args.gap_monitor) if args.gap_monitor else None
                ),
                skip_gap_check=args.skip_gap_check,
                skip_fund_flow_check=args.skip_fund_flow_check,
                days=days,
                allow_fallback=args.allow_fallback,
                allow_estimated=args.allow_estimated,
                legacy_stage_rules=args.legacy_stage_rules,
            )
        )
