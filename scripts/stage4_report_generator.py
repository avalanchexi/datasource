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
from typing import Any, Dict, Optional

from datasource.generators.simple_report import generate_report
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state
from datasource.utils.run_paths import build_run_paths_from_reference


def parse_args() -> argparse.Namespace:
    default_paths = build_run_paths_from_reference(fallback_to_today=True)
    parser = argparse.ArgumentParser(
        description="Stage 4: 生成背景扫描 Markdown 报告",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--market-data",
        default=str(default_paths.market_data_complete),
        help="市场数据 JSON 路径",
    )
    parser.add_argument(
        "--pring-result",
        default=None,
        help="Pring 分析结果 JSON 路径",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="报告输出路径",
    )
    parser.add_argument(
        "--gap-monitor",
        default=None,
        help="gap_monitor JSON 路径（默认: data/runs/YYYYMMDD/gap_monitor.json）",
    )
    return parser.parse_args()


def _format_quality_issue(issue: Dict[str, Any]) -> str:
    category = str(issue.get("category") or "unknown")
    key = str(issue.get("key") or "unknown")
    reason = str(issue.get("reason") or "unknown")
    return f"{category}.{key}:{reason}"


def _assert_stage4_quality_gate(market_payload: Dict[str, Any]) -> None:
    quality_state = build_pipeline_quality_state(
        market_payload,
        stage="stage4",
        allow_estimated=True,
    )
    quality_blockers = quality_state.get("quality_blockers") or []
    policy = quality_state.get("policy_evaluation") or {}
    policy_blocked = bool(policy.get("block_stage3"))

    if not quality_blockers and not policy_blocked:
        return

    details = [_format_quality_issue(issue) for issue in quality_blockers]
    if policy_blocked and not details:
        details.append("policy_evaluation.block_stage3:true")

    raise RuntimeError(
        "Stage4 unified quality gate blocked report generation: "
        f"{', '.join(details)}"
    )


def _market_report_date(market_payload: Dict[str, Any]) -> Optional[str]:
    metadata = market_payload.get("metadata") or {}
    candidates = (
        metadata.get("date"),
        metadata.get("end_date"),
        market_payload.get("end_date"),
        metadata.get("start_date"),
        market_payload.get("start_date"),
    )
    for value in candidates:
        if value not in (None, ""):
            return str(value)
    return None


def _pring_analysis_date(pring_payload: Dict[str, Any]) -> Optional[str]:
    metadata = pring_payload.get("metadata") or {}
    value = metadata.get("analysis_date")
    if value in (None, ""):
        return None
    return str(value)


def _assert_pring_matches_market(
    market_payload: Dict[str, Any],
    pring_payload: Dict[str, Any],
) -> None:
    market_date = _market_report_date(market_payload)
    pring_date = _pring_analysis_date(pring_payload)
    if market_date and pring_date and market_date != pring_date:
        raise RuntimeError(
            "Stage4 date mismatch: "
            f"market_date={market_date}, pring_analysis_date={pring_date}"
        )


def main() -> None:
    args = parse_args()
    market_path = Path(args.market_data)
    run_paths = build_run_paths_from_reference(path=market_path, fallback_to_today=True)
    pring_path = Path(args.pring_result) if args.pring_result else run_paths.pring_result
    output_path = Path(args.output) if args.output else run_paths.report_markdown

    if not market_path.exists():
        raise FileNotFoundError(f"未找到市场数据文件: {market_path}")
    if not pring_path.exists():
        raise FileNotFoundError(f"未找到Pring结果文件: {pring_path}")

    # gap_monitor 校验（支持带日期版本，自动从 market_data 路径推断）
    market_payload = json.load(market_path.open("r", encoding="utf-8"))
    pring_payload = json.load(pring_path.open("r", encoding="utf-8"))

    gap_path: Optional[Path]
    if args.gap_monitor:
        gap_path = Path(args.gap_monitor)
    else:
        gap_path = run_paths.gap_monitor

    if gap_path.exists():
        gap = json.load(gap_path.open("r", encoding="utf-8"))
        pending = gap.get("pending_tasks", [])
        manual = gap.get("manual_required", [])
        if pending or manual:
            raise RuntimeError(
                f"gap_monitor 未清空（{gap_path}），pending={pending}, "
                f"manual_required={manual}，请先补齐再生成报告。"
            )
    else:
        print(f"[WARN] gap_monitor 文件未找到（查找: {gap_path}），跳过 gap 校验")

    # ai_websearch_enhanced 校验
    meta = market_payload.get("metadata", {})
    if not meta.get("ai_websearch_enhanced"):
        raise RuntimeError("metadata.ai_websearch_enhanced 未设置，Stage4 已阻断。请先完成 Stage2。")

    _assert_stage4_quality_gate(market_payload)
    _assert_pring_matches_market(market_payload, pring_payload)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        shutil.copy2(output_path, output_path.with_suffix(output_path.suffix + ".bak"))

    print("[INFO] 开始生成 Markdown 报告 ...")
    generate_report(market_path, pring_path, output_path)
    print(f"[DONE] 报告已写入: {output_path}")


if __name__ == "__main__":
    main()
