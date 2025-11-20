#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4: Markdown 报告生成脚本

旧版脚本存在大量乱码，这里重写为精简版本，直接复用
`generate_simple_report.generate_report`，以保证中文日志和注释
全部可读。
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from generate_simple_report import generate_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 4: 生成背景扫描 Markdown 报告",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--market-data",
        default="data/market_data.json",
        help="市场数据 JSON 路径",
    )
    parser.add_argument(
        "--pring-result",
        default="data/pring_result.json",
        help="Pring 分析结果 JSON 路径",
    )
    parser.add_argument(
        "--output",
        default="reports/background_scan_120.md",
        help="报告输出路径",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    market_path = Path(args.market_data)
    pring_path = Path(args.pring_result)
    output_path = Path(args.output)

    if not market_path.exists():
        raise FileNotFoundError(f"未找到市场数据文件: {market_path}")
    if not pring_path.exists():
        raise FileNotFoundError(f"未找到Pring结果文件: {pring_path}")

    # gap_monitor 校验
    gap_path = Path("reports/gap_monitor.json")
    if gap_path.exists():
        gap = json.load(gap_path.open("r", encoding="utf-8"))
        pending = gap.get("pending_tasks", [])
        manual = gap.get("manual_required", [])
        if pending or manual:
            raise RuntimeError(f"gap_monitor 未清空，pending={pending}, manual_required={manual}，请先补齐再生成报告。")

    # ai_websearch_enhanced 校验
    meta = json.load(market_path.open("r", encoding="utf-8")).get("metadata", {})
    if not meta.get("ai_websearch_enhanced"):
        raise RuntimeError("metadata.ai_websearch_enhanced 未设置，Stage4 已阻断。请先完成 Stage2。")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        shutil.copy2(output_path, output_path.with_suffix(output_path.suffix + ".bak"))

    print("[INFO] 开始生成 Markdown 报告 ...")
    generate_report(market_path, pring_path, output_path)
    print(f"[DONE] 报告已写入: {output_path}")


if __name__ == "__main__":
    main()
