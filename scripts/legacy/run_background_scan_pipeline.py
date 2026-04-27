#!/usr/bin/env python3
"""Archived 120-day background scan pipeline runner.

This legacy helper is retained only for historical/manual comparison. The
supported daily pipeline is Stage1 -> Stage2 unified enhancer -> Stage2.5
injection -> Stage3 Pring analysis -> Stage4 report generation.

Historically this script stitched together the execution phases defined in
``docs/AI_EXECUTION_WORKFLOW.md`` and ``120背景扫描方案.md``. It performed the
following steps for a given target date:

1. Executes the enhanced background scan generator to produce the raw report
   Markdown.
2. Copies the raw output to ``reports/archive/{date}背景扫描120_archived.md``.
3. Runs structural and completeness validations expected by the workflow
   (mandatory指数/ETF覆盖、无 ``N/A`` 占位等)。

If any validation fails, the script raises an exception so the operator (or AI
agent) can review the accompanying日志/报错文件, ensuring we never publish an
incomplete report silently.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXECUTABLE = sys.executable or "python3"
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def run_command(cmd: List[str], *, env: dict | None = None) -> None:
    """Run a subprocess command, streaming output and failing fast on errors."""

    cmd_display = " ".join(cmd)
    print(f"\n[Pipeline] → {cmd_display}")
    process_env = os.environ.copy()
    if env:
        process_env.update(env)

    # Ensure project root (and optional stubs) are available to subprocesses
    pythonpath_entries = [str(PROJECT_ROOT)]
    stubs_path = PROJECT_ROOT / "stubs"
    if stubs_path.exists():
        pythonpath_entries.append(str(stubs_path))

    existing_pythonpath = process_env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_entries.append(existing_pythonpath)
    process_env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

    result = subprocess.run(cmd, env=process_env, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {cmd_display}")


def ensure_sections(report_text: str, required_labels: Iterable[str], *, section_name: str) -> List[str]:
    """Check that each required label exists in the table and has no N/A placeholders."""

    failures: List[str] = []
    for label in required_labels:
        pattern = re.compile(rf"\|\s*{re.escape(label)}\s*\|.*")
        match = pattern.search(report_text)
        if not match:
            failures.append(f"{section_name}: missing row for '{label}'")
            continue

        row = match.group(0)
        if "N/A" in row:
            failures.append(f"{section_name}: '{label}' contains N/A → {row}")
    return failures


def validate_report(report_path: Path) -> None:
    """Validate the generated Markdown against mandatory workflow expectations."""

    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")

    report_text = report_path.read_text(encoding="utf-8")

    errors: List[str] = []

    # 核心指数（A股+美股）
    required_indices = ["上证指数", "上证50", "深证成指", "创业板指", "标普500", "纳斯达克"]
    errors.extend(ensure_sections(report_text, required_indices, section_name="股票市场综述"))

    # 商品基准完整性
    required_commodities = [
        "WTI原油(美元/桶)",
        "Brent原油(美元/桶)",
        "COMEX铜(美元/磅)",
        "现货黄金(XAUUSD)",
        "BCOM商品指数(GSG代理)",
    ]
    errors.extend(ensure_sections(report_text, required_commodities, section_name="商品与黄金"))

    # 汇率 & 债券表格内禁止 N/A
    fx_labels = ["USD/CNY", "USD/CNH", "美元指数(DXY)"]
    errors.extend(ensure_sections(report_text, fx_labels, section_name="汇率变化"))

    bond_labels = ["中国10Y国债", "美国10Y国债", "中国10Y国开债"]
    errors.extend(ensure_sections(report_text, bond_labels, section_name="利率与债券收益率"))

    if errors:
        formatted = "\n".join(f"  - {msg}" for msg in errors)
        raise RuntimeError(f"Report validation failed:\n{formatted}")


def compute_start_date(end_date: datetime, days: int = 120) -> datetime:
    """Compute inclusive start date for the rolling window."""

    return end_date - timedelta(days=days)


def run_data_completion(
    raw_report_path: Path,
    *,
    target_date: str,
    use_mcp: bool,
) -> str:
    """Invoke the DataCompletionChecker to supplement missing values."""

    from datasource import get_manager
    from datasource.utils.data_completion import DataCompletionChecker

    report_text = raw_report_path.read_text(encoding="utf-8")
    manager = get_manager()

    checker = DataCompletionChecker(
        enforce_completeness=True,
        use_mcp=use_mcp,
        manager=manager,
    )

    return asyncio.run(checker.supplement_missing_data(report_text, target_date))


def main() -> None:
    parser = argparse.ArgumentParser(description="Archived 120-day background scan pipeline runner")
    parser.add_argument("--date", required=True, help="Target report date (YYYY-MM-DD)")
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip markdown validation (not recommended; only for exploratory runs)",
    )
    parser.add_argument(
        "--skip-completion",
        action="store_true",
        help="Skip the DataCompletionChecker supplementation step",
    )
    parser.add_argument(
        "--use-mcp",
        action="store_true",
        help="Historical only: allow the completion helper to invoke MCP-style adapters when available",
    )
    parser.add_argument(
        "--run-archived",
        action="store_true",
        help="Explicitly run this archived legacy pipeline for historical comparison",
    )
    args = parser.parse_args()

    if not args.run_archived:
        print(
            "[ARCHIVED] scripts/legacy/run_background_scan_pipeline.py 已停用为归档工具。\n"
            "当前报告生成请使用 AGENTS.md 中的 Stage1 -> Stage2 -> Stage2.5 -> Stage3 -> Stage4 主链路。\n"
            "如仅需历史比对，可显式添加 --run-archived。",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        report_end = datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit(f"Invalid --date value: {args.date} ({exc})")

    start_date = compute_start_date(report_end)
    date_compact = report_end.strftime("%Y%m%d")

    reports_dir = PROJECT_ROOT / "reports" / "archive"
    reports_dir.mkdir(parents=True, exist_ok=True)

    raw_report = reports_dir / f"{date_compact}背景扫描120_archived_raw.md"
    final_report = reports_dir / f"{date_compact}背景扫描120_archived.md"

    # 1. 生成初稿
    run_command(
        [
            PYTHON_EXECUTABLE,
            str(PROJECT_ROOT / "scripts/utility/background_scan_120d_generator.py"),
            "--date",
            args.date,
            "--output",
            str(raw_report),
            "--run-archived",
        ]
    )

    # 2. 备份原始输出并同步为最终文件
    completion_error: Optional[str] = None
    if args.skip_completion:
        shutil.copy2(raw_report, final_report)
        print(f"[Pipeline] Raw report copied to {final_report.name} (completion skipped)")
    else:
        try:
            supplemented_text = run_data_completion(
                raw_report,
                target_date=args.date,
                use_mcp=args.use_mcp,
            )
        except Exception as exc:  # pragma: no cover - runtime/network variability
            completion_error = str(exc)
            shutil.copy2(raw_report, final_report)
            print(f"[Pipeline] Data completion failed: {completion_error}")
            print("[Pipeline] Falling back to raw report without supplementation")
        else:
            final_report.write_text(supplemented_text, encoding="utf-8")
            print(f"[Pipeline] Data completion applied → {final_report.name}")

    # 3. 执行结构校验
    if not args.skip_validation:
        try:
            validate_report(final_report)
        except Exception as validation_error:
            raise SystemExit(str(validation_error))

    print("\n[Pipeline] 归档120背景扫描流程完成")
    print(f"  报告窗口: {start_date.strftime('%Y-%m-%d')} → {args.date}")
    print(f"  报告文件: {final_report}")
    if not args.skip_validation:
        print("  校验状态: PASS")
    if completion_error:
        print(f"  ⚠️ 数据补全过程失败: {completion_error}")


if __name__ == "__main__":
    main()
