#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Archived Stage 2: MCP Data Enhancer（全量补齐）

ARCHIVED/DEPRECATED: this module remains runnable only for historical
diagnostics. Current daily runs use scripts/stage2_unified_enhancer.py followed
by scripts/stage2_5_injector.py for manual/WebSearch injection.

职责:
- 读取 Stage 1 生成的 market_data.json
- supplement 模式优先补充资金流向与财经要闻；full 模式会重跑全部增强（债券 / 商品 / 资金流向 / 要闻）
- 输出增强后的 market_data，并可选触发报告再生成
"""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 允许直接复用 Stage 2a 的增强器实现，避免重复造轮子
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from mcp_data_enhancer import MCPDataEnhancer


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "ARCHIVED/DEPRECATED legacy Stage2 MCP enhancer; for historical "
            "diagnostics only. Current flow: scripts/stage2_unified_enhancer.py "
            "+ scripts/stage2_5_injector.py."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=(
            "当前生产路径: run Stage2 with scripts/stage2_unified_enhancer.py, "
            "then inject remaining WebSearch/manual data with "
            "scripts/stage2_5_injector.py. Do not use this legacy script as "
            "the daily Stage2 entry point or补数入口."
        ),
    )
    parser.add_argument("--market-data", required=True, help="Stage 1 输出的 market_data.json 路径")
    parser.add_argument("--pring-result", help="Pring 结果路径（重新生成报告时必填）")
    parser.add_argument("--output", help="增强后的 market_data 输出路径；默认覆盖输入文件")
    parser.add_argument("--log-output", help="增强日志输出路径")
    parser.add_argument(
        "--mode",
        choices=["essential", "supplement", "full"],
        default="essential",
        help="essential=核心必需项(债券/商品/宏观/货币)，supplement=仅资金流向+要闻，full=全部增强",
    )
    parser.add_argument("--disable-mcp", action="store_true", help="禁用 MCP（调试/排障时使用）")
    parser.add_argument(
        "--enable-yahoo-fallback",
        action="store_true",
        help=(
            "显式启用 legacy Yahoo Finance diagnostic fallback；"
            "默认禁用，当前生产流程应转 scripts/stage2_5_injector.py 注入。"
        ),
    )
    parser.add_argument(
        "--disable-yahoo-fallback",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--regenerate-report",
        action="store_true",
        help="legacy diagnostic only；当前请单独运行 scripts/stage4_report_generator.py",
    )
    parser.add_argument("--report-output", help="配合 --regenerate-report 使用的报告输出路径")
    parser.add_argument(
        "--websearch-results",
        help=(
            "legacy-only direct Stage2 injection input；当前请把 WebSearch/manual "
            "结果交给 scripts/stage2_5_injector.py"
        ),
    )
    return parser.parse_args()



def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_json(payload: dict, path: Path, label: str) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[OK] {label}已写入 {path}")


def _save_market_payload(payload: Dict[str, Any], path: Path) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _append_stage2_note(payload: Dict[str, Any], message: str) -> None:
    metadata = payload.setdefault("metadata", {})
    notes = metadata.setdefault("stage2_notes", [])
    if message not in notes:
        notes.append(message)


def _print_banner(
    market_path: Path,
    output_path: Path,
    mode: str,
    mcp_enabled: bool,
    yahoo_enabled: bool,
    websearch_results_path: Optional[Path] = None,
) -> None:
    print(f"\n{'=' * 70}")
    print("Stage 2: MCP Full Enhancement")
    print(f"{'=' * 70}")
    print(f"输入 market_data: {market_path}")
    print(f"输出 market_data: {output_path}")
    print(f"执行模式: {mode}")
    print(f"MCP 启用: {mcp_enabled}")
    print(f"Yahoo Fallback: {yahoo_enabled}")
    if websearch_results_path:
        print(f"WebSearch结果: {websearch_results_path}")
    print(f"{'=' * 70}\n")
    if mode == "supplement":
        print("[WARN] 当前在supplement模式下，仅会补资金流向+财经要闻，不会填充Pring核心数据。")
        print("       如需完整Pring分析，请使用 --mode essential 或 --mode full。\n")


def _print_footer(output_path: Path, log_path: Optional[Path], enhanced: bool, yahoo_used: bool) -> None:
    status = "补充完成" if enhanced else "跳过 (MCP 未启用)"
    print(f"\n{'=' * 70}")
    print(f"[Stage 2] {status}")
    print(f"市场数据文件: {output_path}")
    if log_path:
        print(f"增强日志: {log_path}")
    if yahoo_used:
        print("已执行 Yahoo Finance 回填以替换剩余商品/债券占位值。")
    print(f"{'=' * 70}\n")


def _run_stage4_report(market_path: Path, pring_path: Path, report_output: Path) -> None:
    stage4_script = SCRIPT_DIR / "stage4_report_generator.py"
    cmd = [
        sys.executable,
        str(stage4_script),
        "--market-data",
        str(market_path),
        "--pring-result",
        str(pring_path),
        "--output",
        str(report_output),
    ]
    print(f"\n[INFO] 正在重新生成报告 -> {report_output}")
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Stage 4 生成报告失败，退出码: {result.returncode}")
    print("[OK] 报告已重新生成")


def _needs_yahoo_fallback(market_payload: Dict[str, Any]) -> bool:
    def _bad(value: Any) -> bool:
        if value is None:
            return True
        try:
            val = float(value)
        except (TypeError, ValueError):
            return True
        if abs(val) < 1e-9:
            return True
        return abs(val - 7.13) < 1e-3

    for commodity in market_payload.get("commodities", []):
        if _bad(commodity.get("current_price")):
            return True
    for bond in market_payload.get("bonds", []):
        if _bad(bond.get("current_yield")):
            return True
    return False


def _gap_summary(market_payload: Dict[str, Any]) -> Dict[str, int]:
    def _bad(value: Any) -> bool:
        if value is None:
            return True
        try:
            val = float(value)
        except (TypeError, ValueError):
            return True
        if abs(val) < 1e-9:
            return True
        return abs(val - 7.13) < 1e-3

    summary = {
        "commodities": sum(
            1 for item in market_payload.get("commodities", []) if _bad(item.get("current_price"))
        ),
        "bonds": sum(
            1 for item in market_payload.get("bonds", []) if _bad(item.get("current_yield"))
        ),
    }
    return summary


def _run_yahoo_fallback(target_path: Path) -> Tuple[bool, List[Dict[str, Any]]]:
    try:
        from fill_market_data_from_yahoo import MarketDataFiller
    except Exception as exc:
        print(f"[WARN] 无法导入 fill_market_data_from_yahoo: {exc}")
        return False, []

    try:
        filler = MarketDataFiller(target_path, target_path)
        filler.fill()
        return True, getattr(filler, "fetch_records", [])
    except Exception as exc:
        print(f"[WARN] Yahoo Finance 回填失败: {exc}")
        return False, []


def _is_placeholder_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        val = float(value)
    except (TypeError, ValueError):
        return True
    if abs(val) < 1e-12:
        return True
    return abs(val - 7.13) < 1e-3


def _sanitize_market_payload(payload: Dict[str, Any]) -> List[str]:
    notes: List[str] = []

    for item in payload.get("commodities", []):
        if _is_placeholder_value(item.get("current_price")):
            if item.get("current_price") is not None:
                notes.append(f"商品 {item.get('name', item.get('symbol'))} 使用占位值，已重置为待 WebSearch")
            item["current_price"] = None
            item["daily_change"] = None
            item["ytd_change"] = None
            item["trend"] = "待 WebSearch"
            item["source"] = "MCP WebFetch待获取"

    for item in payload.get("bonds", []):
        if _is_placeholder_value(item.get("current_yield")):
            if item.get("current_yield") is not None:
                notes.append(f"债券 {item.get('name', item.get('symbol'))} 使用占位值，已重置为待 WebSearch")
            item["current_yield"] = None
            item["change_5d_bp"] = None
            item["change_120d_bp"] = None
            item["trend"] = "待 WebSearch"
            item["source"] = "MCP WebFetch待获取"
            item["is_estimated"] = True

    return notes


async def _run_enhancer(
    market_data_path: Path,
    pring_result_path: Optional[Path],
    output_path: Path,
    log_path: Optional[Path],
    mode: str,
    mcp_enabled: bool,
    websearch_results_path: Optional[Path],
) -> dict:
    enhancer = MCPDataEnhancer(
        market_data_path=str(market_data_path),
        pring_result_path=str(pring_result_path) if pring_result_path else None,
        enable_mcp=mcp_enabled,
        websearch_results_path=str(websearch_results_path) if websearch_results_path else None,
    )
    result = await enhancer.enhance(mode=mode)

    sanitize_notes = _sanitize_market_payload(result["market_data"])
    _write_json(result["market_data"], output_path, "增强后的 market_data")
    if log_path:
        _write_json(result["log"], log_path, "Stage 2 日志")
    result["sanitize_notes"] = sanitize_notes
    return result


async def main_async() -> None:
    args = _parse_args()

    market_data_path = Path(args.market_data).expanduser().resolve()
    if not market_data_path.exists():
        raise FileNotFoundError(f"market_data 文件不存在: {market_data_path}")

    output_path = Path(args.output).expanduser().resolve() if args.output else market_data_path
    pring_path = Path(args.pring_result).expanduser().resolve() if args.pring_result else None
    log_path = Path(args.log_output).expanduser().resolve() if args.log_output else None
    report_output = Path(args.report_output).expanduser().resolve() if args.report_output else None
    websearch_results_path = (
        Path(args.websearch_results).expanduser().resolve() if args.websearch_results else None
    )

    if args.regenerate_report and (pring_path is None or report_output is None):
        raise ValueError("--regenerate-report 需要提供 --pring-result 和 --report-output")

    yahoo_enabled = bool(args.enable_yahoo_fallback)
    _print_banner(
        market_data_path,
        output_path,
        args.mode,
        not args.disable_mcp,
        yahoo_enabled,
        websearch_results_path,
    )

    result = await _run_enhancer(
        market_data_path=market_data_path,
        pring_result_path=pring_path,
        output_path=output_path,
        log_path=log_path,
        mode=args.mode,
        mcp_enabled=not args.disable_mcp,
        websearch_results_path=websearch_results_path,
    )

    yahoo_ran = False
    fetch_records: List[Dict[str, Any]] = []
    market_payload = result.get("market_data", {})
    pending_after_enhance = _needs_yahoo_fallback(market_payload)
    notes: List[str] = list(result.get("sanitize_notes") or [])

    if yahoo_enabled and pending_after_enhance:
        yahoo_ran, fetch_records = _run_yahoo_fallback(output_path)
        if yahoo_ran:
            with open(output_path, "r", encoding="utf-8") as f:
                market_payload = json.load(f)
                result["market_data"] = market_payload
        if fetch_records:
            cache_hits = sum(1 for r in fetch_records if r.get("source") == "cache")
            network_hits = sum(1 for r in fetch_records if r.get("source") == "network")
            max_retries = max((r.get("retries", 0) for r in fetch_records), default=0)
            note = (
                f"Stage2: Yahoo fallback完成 (cache={cache_hits}, network={network_hits}, max_retries={max_retries})."
            )
            notes.append(note)
        else:
            notes.append(
                "Stage2: legacy Yahoo Fallback 调用失败，仍存在商品/债券缺口；"
                "请写入 Stage2.5 manual/WebSearch JSON，并通过 scripts/stage2_5_injector.py 注入。"
            )

        pending_after_yahoo = _needs_yahoo_fallback(market_payload)
        if pending_after_yahoo:
            notes.append(
                "Stage2: legacy Yahoo Fallback 后仍检测到商品/债券缺口；"
                "请写入 Stage2.5 manual/WebSearch JSON，并通过 scripts/stage2_5_injector.py 注入。"
            )
    else:
        pending_after_yahoo = pending_after_enhance
        if pending_after_enhance and not yahoo_enabled:
            notes.append(
                "Stage2: 检测到商品/债券缺口，但已禁用 Yahoo Fallback；"
                "请写入 Stage2.5 manual/WebSearch JSON，并通过 scripts/stage2_5_injector.py 注入。"
            )

    if notes:
        for note in notes:
            print(f"[WARN] {note}")
            _append_stage2_note(market_payload, note)
        _save_market_payload(market_payload, output_path)
        result["market_data"] = market_payload

    gap_summary = _gap_summary(market_payload)
    metadata = market_payload.setdefault("metadata", {})
    metadata["stage2_gap_monitor"] = gap_summary
    if any(gap_summary.values()):
        gap_note = (
            f"Stage2: 行情缺口仍存在 (commodities={gap_summary['commodities']}, bonds={gap_summary['bonds']})。"
        )
        print(f"[WARN] {gap_note}")
        _append_stage2_note(market_payload, gap_note)
        _save_market_payload(market_payload, output_path)
        result["market_data"] = market_payload

    if args.regenerate_report and report_output and pring_path:
        _run_stage4_report(output_path, pring_path, report_output)

    _print_footer(output_path, log_path, result.get("enhanced", False), yahoo_ran)


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[WARN] Stage 2 执行被用户中断")
        sys.exit(130)
    except Exception as exc:
        print(f"\n[ERROR] Stage 2 执行失败: {exc}")
        sys.exit(1)



if __name__ == "__main__":
    main()
