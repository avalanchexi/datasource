import argparse
import sys
from pathlib import Path
from typing import Tuple

from datasource.engines.stage2_5 import core
from datasource.utils.run_lock import DailyRunLock, run_dir_from_artifact
from datasource.utils.run_paths import build_run_paths_from_reference


def _default_cli_paths() -> Tuple[Path, Path, Path]:
    run_paths = build_run_paths_from_reference(fallback_to_today=True)
    return (
        run_paths.market_data_stage2,
        run_paths.websearch_results_manual,
        run_paths.market_data_complete,
    )


def parse_args() -> argparse.Namespace:
    default_market, default_websearch, default_output = _default_cli_paths()
    parser = argparse.ArgumentParser(
        description="Stage2.5 WebSearch 数据注入脚本",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "market_data_path",
        nargs="?",
        default=str(default_market),
        help="Stage2 产出的市场数据 JSON 路径",
    )
    parser.add_argument(
        "websearch_path",
        nargs="?",
        default=str(default_websearch),
        help="WebSearch 结果 JSON 路径（支持 Stage2 results 或 manual schema）",
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        default=str(default_output),
        help="注入后的完整市场数据输出路径",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="覆盖日期（YYYY-MM-DD 或 YYYYMMDD），用于质量指标/gap_monitor 文件名",
    )
    parser.add_argument(
        "--gap-monitor-path",
        default=None,
        help="指定重写的 gap_monitor 路径；不传则默认 data/runs/YYYYMMDD/gap_monitor.json",
    )
    parser.add_argument(
        "--backfill-trend",
        dest="backfill_trend",
        action="store_true",
        default=True,
        help="启用 trend_history 回填（默认开启）",
    )
    parser.add_argument(
        "--no-backfill-trend",
        "--disable-backfill-trend",
        dest="backfill_trend",
        action="store_false",
        help="禁用 trend_history 回填",
    )
    parser.add_argument(
        "--override-stale",
        dest="override_stale",
        action="store_true",
        default=True,
        help="允许手工注入覆盖 is_stale=True 的宏观/货币字段（默认开启）",
    )
    parser.add_argument(
        "--no-override-stale",
        dest="override_stale",
        action="store_false",
        help="禁用 stale 覆盖，仅填充 current_value 为空的字段",
    )
    parser.add_argument(
        "--force-override",
        action="store_true",
        default=False,
        help="强制覆盖已有值（应急模式，谨慎使用）",
    )
    parser.add_argument(
        "--trend-history-base-dir",
        default=None,
        help="指定 trend_history/min 基础目录；测试夹具可传入临时目录隔离真实历史",
    )
    parser.add_argument(
        "--disable-trend-history-write",
        action="store_true",
        default=False,
        help="禁用 Stage2.5 最终 trend_history 写入；只影响写入，不放松 Stage3/Stage4 gate",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    market_data_arg = getattr(
        args, "market_data_path", getattr(args, "input_file", None)
    )
    websearch_arg = getattr(
        args, "websearch_path", getattr(args, "websearch_file", None)
    )
    output_arg = getattr(
        args, "output_path", getattr(args, "output_file", None)
    )
    market_data_file = Path(market_data_arg).expanduser().resolve()
    websearch_file = Path(websearch_arg).expanduser().resolve()
    output_file = Path(output_arg).expanduser().resolve()
    gap_monitor_path = (
        Path(args.gap_monitor_path).expanduser().resolve()
        if args.gap_monitor_path
        else None
    )
    trend_history_base_dir = (
        Path(args.trend_history_base_dir).expanduser().resolve()
        if args.trend_history_base_dir
        else None
    )

    if not market_data_file.exists():
        print(f"[ERROR] 市场数据文件不存在: {market_data_file}")
        sys.exit(1)
    if not websearch_file.exists():
        print(f"[ERROR] WebSearch结果文件不存在: {websearch_file}")
        sys.exit(1)

    try:
        run_dir = run_dir_from_artifact(output_file)
        with DailyRunLock(run_dir, owner="stage2_5_injector").acquire():
            core.inject_websearch_data(
                market_data_path=market_data_file,
                websearch_path=websearch_file,
                output_path=output_file,
                backfill_trend=args.backfill_trend,
                date_override=args.date,
                gap_monitor_path=gap_monitor_path,
                override_stale=args.override_stale,
                force_override=args.force_override,
                trend_history_base_dir=trend_history_base_dir,
                disable_trend_history_write=args.disable_trend_history_write,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] 数据注入失败: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
