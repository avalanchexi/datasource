"""Summary text helpers for Pring stage analysis."""

from __future__ import annotations

from typing import Any, Dict, List


def _extract_highlights(details: Dict[str, str], keys: List[str], limit: int = 3) -> List[str]:
    highlights: List[str] = []
    for key in keys:
        text = details.get(key)
        if not text:
            continue
        comment = text.split(" - ", 1)[1] if " - " in text else text
        highlights.append(f"{key}{comment}")
        if len(highlights) >= limit:
            break
    return highlights

def _summarize_leading_indicator_text(indicator: Dict[str, Any]) -> str:
    if not indicator:
        return "领先指标缺失，暂无阶段前瞻"
    status = indicator.get("status")
    if status == "missing":
        return "缺少DR007/M1-M2数据，需补充WebSearch"
    parts = []
    if indicator.get("message"):
        parts.append(indicator["message"])
    if indicator.get("m1_m2_spread") is not None and "M1-M2" not in parts[0]:
        parts.append(f"M1-M2剪刀差{indicator['m1_m2_spread']:+.1f}pct")
    shift = indicator.get("applied_shift", indicator.get("expected_shift", 0))
    if shift:
        arrow = "前" if shift < 0 else "后"
        parts.append(f"阶段可能向{arrow}{abs(shift)}档")
    return "；".join(parts) if parts else "领先指标暂无显著变化"

def _build_inventory_summary_text(details: Dict[str, str], stage: str, bias: str) -> str:
    prefix = f"{stage}，{bias}。"
    highlights = _extract_highlights(
        details,
        ["PPI同比", "PMI综合", "PMI新订单", "PMI生产", "工业增加值", "工业营收", "GDP同比"]
    )
    if highlights:
        return prefix + "关键驱动：" + "；".join(highlights)
    return prefix + "指标数据待WebSearch补全。"

def _build_monetary_summary_text(details: Dict[str, str], stage: str, equity_bias: str, bond_bias: str) -> str:
    prefix = f"{stage}，权益偏向{equity_bias}，债券偏向{bond_bias}。"
    highlights = _extract_highlights(
        details,
        ["降准幅度", "7天逆回购", "DR007变化", "M1-M2剪刀差", "M1增速", "TSF增速", "M2增速"]
    )
    if highlights:
        return prefix + "流动性信号：" + "；".join(highlights)
    return prefix + "货币指标待补数。"

def _build_stage_summary_text(
    final_stage: PringStage,
    confidence: float,
    inventory_stage: str,
    monetary_stage: str,
    leading_summary: str
) -> str:
    return (
        f"{final_stage.to_display_format()}（置信度{confidence:.0%}）。"
        f"库存周期：{inventory_stage}，货币周期：{monetary_stage}。"
        f"领先指标：{leading_summary}"
    )
