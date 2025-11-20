#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unified Background Scan Generator (Stage 1→4 pipeline, V3.3+)
"""

import argparse
import asyncio
import subprocess
import sys
import io
import json
import time
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


class UnifiedBackgroundScanner:
    """Unified runner that orchestrates Stage 1-4."""

    def __init__(
        self,
        end_date: str,
        output_path: str,
        keep_intermediates: bool = False,
        enable_mcp: bool = False,
        enable_full_mcp: bool = False,
    ) -> None:
        self.end_date = end_date
        self.output_path = Path(output_path)
        self.keep_intermediates = keep_intermediates
        self.enable_full_mcp = enable_full_mcp
        self.enable_mcp = enable_mcp or enable_full_mcp

        if self.enable_full_mcp:
            self.mode = "V3.3-Full"
            self.mode_desc = "Full mode (Stage 2 full MCP enhancement)"
            self.stage2_mode = "full"
        elif self.enable_mcp:
            self.mode = "V3.3-Accurate"
            self.mode_desc = "Accurate mode (Stage 2 supplement MCP)"
            self.stage2_mode = "supplement"
        else:
            self.mode = "V3.1-Fast"
            self.mode_desc = "Fast mode (no Stage 2 MCP)"
            self.stage2_mode = None

        date_token = end_date.replace("-", "")
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        self.logs_dir = Path("logs")
        self.logs_dir.mkdir(exist_ok=True)

        self.market_data_path = self.data_dir / f"{date_token}_market_data.json"
        self.market_data_stage2_path = self.data_dir / f"{date_token}_market_data_stage2.json"
        self.pring_result_path = self.data_dir / f"{date_token}_pring_result.json"
        self.stage2_log_path = self.logs_dir / f"{date_token}_stage2_log.json"

    async def run(self) -> bool:
        print(f"\n{'=' * 70}")
        print(f"Unified Background Scan V3.3 ({self.mode})")
        print(f"{'=' * 70}")
        print(f"Date:   {self.end_date}")
        print(f"Output: {self.output_path}")
        print(f"Mode:   {self.mode_desc}")
        self._print_pipeline()
        print(f"{'=' * 70}\n")

        start_time = datetime.now()
        try:
            await self._run_stage1()

            if self.stage2_mode:
                await self._run_stage2(self.stage2_mode)

            await self._run_stage3()
            await self._run_stage4()

            if not self.keep_intermediates:
                self._cleanup_intermediates()

            elapsed = (datetime.now() - start_time).total_seconds()
            self._print_summary(elapsed)
            return True
        except Exception as exc:  # pragma: no cover
            print(f"\n[ERROR] Pipeline aborted: {exc}")
            import traceback

            traceback.print_exc()
            return False

    def _print_pipeline(self) -> None:
        if not self.stage2_mode:
            steps = "Stage 1 -> Stage 3 -> Stage 4"
        elif self.stage2_mode == "supplement":
            steps = "Stage 1 -> Stage 2 (MCP supplement) -> Stage 3 -> Stage 4"
        else:
            steps = "Stage 1 -> Stage 2 (MCP full) -> Stage 3 -> Stage 4"
        print(f"Pipeline: {steps}")

    async def _run_stage1(self) -> None:
        print(f"\n{'─' * 70}")
        print("[Stage 1] Market data collection")
        print(f"{'─' * 70}")

        cmd = [
            sys.executable,
            "scripts/stage1_data_collector.py",
            "--date",
            self.end_date,
            "--output",
            str(self.market_data_path),
        ]
        result = subprocess.run(cmd, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Stage 1 failed with exit code {result.returncode}")
        print(f"[OK] Stage 1 output: {self.market_data_path}")

    async def _run_stage2(self, mode: str) -> None:
        print(f"\n{'─' * 70}")
        print("[Stage 2] MCP data enhancement")
        print(f"{'─' * 70}")
        print(f"  Mode: {mode}")

        cmd = [
            sys.executable,
            "scripts/stage2_mcp_enhancer.py",
            "--market-data",
            str(self.market_data_path),
            "--output",
            str(self.market_data_stage2_path),
            "--log-output",
            str(self.stage2_log_path),
            "--mode",
            mode,
        ]
        result = subprocess.run(cmd, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Stage 2 failed with exit code {result.returncode}")

        print(f"[OK] Stage 2 output: {self.market_data_stage2_path}")
        self._check_pring_data_completeness()

    def _select_market_input(self) -> Path:
        return self.market_data_stage2_path if self.market_data_stage2_path.exists() else self.market_data_path

    async def _run_stage3(self) -> None:
        print(f"\n{'─' * 70}")
        print("[Stage 3] Pring three-layer analysis")
        print(f"{'─' * 70}")
        input_path = self._select_market_input()

        cmd = [
            sys.executable,
            "scripts/stage3_pring_analyzer.py",
            "--input",
            str(input_path),
            "--output",
            str(self.pring_result_path),
        ]
        result = subprocess.run(cmd, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Stage 3 failed with exit code {result.returncode}")

        print(f"[OK] Stage 3 output: {self.pring_result_path}")
        print(f"  Input: {input_path.name}")

    async def _run_stage4(self) -> None:
        print(f"\n{'─' * 70}")
        print("[Stage 4] Markdown report generation")
        print(f"{'─' * 70}")
        input_path = self._select_market_input()

        cmd = [
            sys.executable,
            "scripts/stage4_report_generator.py",
            "--market-data",
            str(input_path),
            "--pring-result",
            str(self.pring_result_path),
            "--output",
            str(self.output_path),
        ]
        result = subprocess.run(cmd, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Stage 4 failed with exit code {result.returncode}")

        print(f"[OK] Stage 4 output: {self.output_path}")
        print(f"  Input: {input_path.name}")

    def _check_pring_data_completeness(self) -> None:
        if not self.stage2_log_path.exists():
            return
        try:
            log_data = json.loads(self.stage2_log_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            print(f"[WARN] Unable to parse Stage 2 log: {err}")
            return

        if not log_data.get("pring_data_missing"):
            return

        macro_missing = log_data.get("missing_macro_count", 0)
        monetary_missing = log_data.get("missing_monetary_count", 0)
        prompt_file = log_data.get("mcp_prompts_file", "N/A")

        print(f"\n{'=' * 70}")
        print("[WARNING] Pring prerequisites are incomplete")
        print(f"Missing macro indicators: {macro_missing}, monetary policies: {monetary_missing}")
        print("建议: 补充 WebSearch 结果后重跑 Stage 2 (scripts/stage2_mcp_enhancer.py)")
        print(f"参考提示文件: {prompt_file}")
        print(f"{'=' * 70}\n")
        for seconds in range(5, 0, -1):
            print(f"继续执行倒计时: {seconds}s", end="\r")
            time.sleep(1)
        print("继续执行...        ")

    def _cleanup_intermediates(self) -> None:
        print(f"\n{'─' * 70}")
        print("[Cleanup] Removing intermediate files")
        print(f"{'─' * 70}")
        for path in [self.market_data_path, self.market_data_stage2_path, self.pring_result_path]:
            if path.exists():
                path.unlink()
                print(f"  Removed: {path}")

    def _print_summary(self, elapsed: float) -> None:
        size_kb = self.output_path.stat().st_size / 1024 if self.output_path.exists() else 0
        print(f"\n{'=' * 70}")
        print("[DONE] Background scan generated")
        print(f"{'=' * 70}")
        print(f"Report:   {self.output_path}")
        print(f"Size:     {size_kb:.1f} KB")
        print(f"Duration: {elapsed:.1f} s")
        print(f"Mode:     {self.mode_desc}")
        print(f"{'=' * 70}")

        if self.mode == "V3.1-Fast":
            print("\n[Hint] Use --enable-mcp for higher data completeness.")
        elif self.mode == "V3.3-Accurate":
            print("\n[Hint] Use --enable-full-mcp for full MCP coverage if needed.")
        else:
            print("\n[Info] Full MCP mode already applied.")

        if self.keep_intermediates:
            print("\nIntermediate files kept:")
            print(f"  Stage1: {self.market_data_path}")
            if self.market_data_stage2_path.exists():
                print(f"  Stage2: {self.market_data_stage2_path}")
            print(f"  Pring:  {self.pring_result_path}")
            if self.stage2_log_path.exists():
                print(f"  Stage2 log: {self.stage2_log_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified background scan generator (Stage 1→4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python background_scan_unified.py --date 2025-11-14 --output reports/20251114背景扫描120.md
  python background_scan_unified.py --date 2025-11-14 --output reports/20251114背景扫描120.md --enable-mcp
  python background_scan_unified.py --date 2025-11-14 --output reports/20251114背景扫描120.md --enable-full-mcp --keep-intermediates
""",
    )
    parser.add_argument("--date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", required=True, help="Markdown report output path")
    parser.add_argument(
        "--keep-intermediates",
        action="store_true",
        help="Keep intermediate JSON files (Stage1/Stage2/Pring)",
    )
    parser.add_argument(
        "--enable-mcp",
        action="store_true",
        help="Run Stage 2 in supplement mode (fund flow + headlines)",
    )
    parser.add_argument(
        "--enable-full-mcp",
        action="store_true",
        help="Run Stage 2 in full mode (all MCP enhancements)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Legacy flag (no-op, kept for backward compatibility)",
    )

    args = parser.parse_args()
    scanner = UnifiedBackgroundScanner(
        end_date=args.date,
        output_path=args.output,
        keep_intermediates=args.keep_intermediates,
        enable_mcp=args.enable_mcp,
        enable_full_mcp=args.enable_full_mcp,
    )
    success = asyncio.run(scanner.run())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
