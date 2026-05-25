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
from typing import Any, Dict, List, Optional, Set

from datasource import get_manager
from datasource.calculators.pring_analyzer import PringAnalyzer
from datasource.models.market_data_contract import MarketDataContract
from datasource.utils.gate_formatting import (
    GateBlock,
    format_gate_blocks,
    format_quality_issue,
)
from datasource.utils.missing_items import flatten_missing_items as _shared_flatten_missing_items
from datasource.utils.pipeline_gates import (
    effective_gap_items,
    effective_quality_blockers,
    gap_item_key as _shared_gap_item_key,
    gap_item_label as _shared_gap_item_label,
)
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state
from datasource.utils.policy_rules import is_estimated_allowlisted, load_policy_rules
from datasource.utils.run_paths import build_run_paths_from_reference

MIN_COMPLETENESS_DEFAULT = 0.80


def _flatten_missing_items(market_payload: Dict[str, Any]) -> List[str]:
    """提取并扁平化缺口列表，兼容 metadata.missing_items 与顶层 missing_items。"""
    return _shared_flatten_missing_items(market_payload)


def _iter_estimated_entries(market_payload: Dict[str, Any]) -> List[tuple[str, str, Dict[str, Any]]]:
    rows: List[tuple[str, str, Dict[str, Any]]] = []

    for key, entry in (market_payload.get("macro_indicators") or {}).items():
        if isinstance(entry, dict) and entry.get("current_value") not in (None, "N/A") and entry.get("is_estimated"):
            rows.append(("macro_indicators", str(key), entry))
    for key, entry in (market_payload.get("monetary_policy") or {}).items():
        if isinstance(entry, dict) and entry.get("current_value") not in (None, "N/A") and entry.get("is_estimated"):
            rows.append(("monetary_policy", str(key), entry))
    for item in market_payload.get("bonds", []) or []:
        if isinstance(item, dict) and item.get("current_yield") not in (None, 0, "N/A") and item.get("is_estimated"):
            rows.append(("bonds", str(item.get("symbol")), item))
    for item in market_payload.get("forex", []) or []:
        if isinstance(item, dict) and item.get("current_rate") not in (None, 0, "N/A") and item.get("is_estimated"):
            rows.append(("forex", str(item.get("pair")), item))
    for item in market_payload.get("commodities", []) or []:
        if isinstance(item, dict) and item.get("current_price") not in (None, 0, "N/A") and item.get("is_estimated"):
            rows.append(("commodities", str(item.get("symbol")), item))
    for item in market_payload.get("stock_indices", []) or []:
        if isinstance(item, dict) and item.get("current_price") not in (None, 0, "N/A") and item.get("is_estimated"):
            rows.append(("stock_indices", str(item.get("symbol")), item))

    return rows


def _collect_estimated_items(
    market_payload: Dict[str, Any],
    *,
    policy_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[str]]:
    """收集估算值并区分：白名单放行项 / 仍需阻断项。"""
    blocked: List[str] = []
    allowlisted: List[str] = []

    for category, key, entry in _iter_estimated_entries(market_payload):
        label = f"{category}.{key}"
        allowed, reasons = is_estimated_allowlisted(category, key, entry, rules=policy_rules)
        if allowed:
            allowlisted.append(label)
            continue
        if reasons:
            blocked.append(f"{label} ({'|'.join(reasons)})")
        else:
            blocked.append(label)

    return {"blocked": blocked, "allowlisted": allowlisted}


def _append_non_blocking_warning(market_payload: Dict[str, Any], warning: Dict[str, Any]) -> None:
    metadata = market_payload.setdefault("metadata", {})
    warnings = metadata.setdefault("non_blocking_warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        metadata["non_blocking_warnings"] = warnings

    signature = (warning.get("code"), warning.get("key"), warning.get("message"))
    for existing in warnings:
        if not isinstance(existing, dict):
            continue
        if (existing.get("code"), existing.get("key"), existing.get("message")) == signature:
            return
    warnings.append(warning)

def _collect_compare_gaps(market_payload: Dict[str, Any]) -> List[str]:
    """收集“当前值存在但对比值未补齐”的指标。"""
    gaps: List[str] = []
    for key, entry in (market_payload.get("macro_indicators") or {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("current_value") in (None, "N/A"):
            continue
        if entry.get("previous_value") is None or entry.get("change_rate") is None:
            gaps.append(f"macro_indicators.{key}")
    for key, entry in (market_payload.get("monetary_policy") or {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("current_value") in (None, "N/A"):
            continue
        if entry.get("change_from_120d") is None:
            gaps.append(f"monetary_policy.{key}")
    return gaps


def _collect_stale_items(market_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """收集被标记为 stale 的宏观/货币指标。"""
    stale_items: List[Dict[str, Any]] = []
    for category in ("macro_indicators", "monetary_policy"):
        section = market_payload.get(category, {})
        if not isinstance(section, dict):
            continue
        for key, entry in section.items():
            if not isinstance(entry, dict):
                continue
            if not entry.get("is_stale"):
                continue
            stale_items.append(
                {
                    "category": category,
                    "key": str(key),
                    "date": entry.get("date"),
                    "expected_period": entry.get("expected_period"),
                    "reason": entry.get("stale_reason") or "actual_period_behind_expected",
                }
            )
    return stale_items


def _effective_policy_rules(
    policy_rules: Optional[Dict[str, Any]],
    *,
    block_on_stale: bool,
    critical_stale_keys: Optional[List[str]],
) -> Dict[str, Any]:
    rules = dict(policy_rules or load_policy_rules())
    rules["block_on_stale"] = block_on_stale
    if critical_stale_keys is not None:
        rules["critical_stale_keys"] = critical_stale_keys
    return rules


def _issue_label(issue: Dict[str, Any], market_payload: Dict[str, Any]) -> str:
    category = str(issue.get("category") or "unknown")
    key = str(issue.get("key") or "unknown")
    reason = str(issue.get("reason") or "unknown")
    parts = [format_quality_issue(issue)]

    if reason == "critical_stale":
        entry = None
        section = market_payload.get(category)
        if isinstance(section, dict):
            candidate = section.get(key)
            if isinstance(candidate, dict):
                entry = candidate
        if isinstance(entry, dict):
            parts.append(
                "actual={actual} expected={expected} stale_reason={stale_reason}".format(
                    actual=entry.get("date"),
                    expected=entry.get("expected_period"),
                    stale_reason=entry.get("stale_reason") or "actual_period_behind_expected",
                )
            )

    return " ".join(parts)


def _message_items(message: str) -> List[str]:
    items: List[str] = []
    for raw_line in message.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Stage3 阻断"):
            continue
        if line.startswith("[") and line.endswith("]"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if line:
            items.append(line)
    return items


def _filtered_quality_blockers(
    quality_state: Dict[str, Any],
    *,
    skip_fund_flow_check: bool,
) -> List[Dict[str, Any]]:
    blockers = quality_state.get("quality_blockers") or []
    return effective_quality_blockers(
        blockers,
        skip_fund_flow_check=skip_fund_flow_check,
    )


def _gap_item_key(item: Any) -> str:
    return _shared_gap_item_key(item) or ""


def _quality_blocker_keys(blockers: List[Dict[str, Any]]) -> Set[str]:
    keys: Set[str] = set()
    for item in blockers:
        category = str(item.get("category") or "")
        key = str(item.get("key") or "")
        if not key:
            continue
        keys.add(key)
        if category:
            keys.add(f"{category}.{key}")
    return keys


def _item_label(item: Any) -> str:
    return _shared_gap_item_label(item)


def _policy_item_matches_live_blocker(item: Any, live_quality_blocker_keys: Set[str]) -> bool:
    key = _gap_item_key(item)
    if not key:
        return False
    if isinstance(item, dict):
        category = item.get("category")
        if category:
            return f"{category}.{key}" in live_quality_blocker_keys
    return key in live_quality_blocker_keys


def _policy_item_has_current_entry(market_payload: Dict[str, Any], item: Any) -> bool:
    return _find_entry_by_item(market_payload, item) is not None


def _require_data_completeness(
    market_payload: Dict[str, Any],
    min_completeness: float,
    allow_estimated: bool = False,
    skip_fund_flow_check: bool = False,
    block_on_stale: bool = True,
    critical_stale_keys: Optional[List[str]] = None,
    policy_rules: Optional[Dict[str, Any]] = None,
) -> None:
    """在开始 Stage3 之前阻断缺失数据的情形。"""
    metadata = market_payload.setdefault("metadata", {})
    completeness = metadata.get("data_completeness", 0.0) or 0.0
    rules = _effective_policy_rules(
        policy_rules,
        block_on_stale=block_on_stale,
        critical_stale_keys=critical_stale_keys,
    )
    quality_state = build_pipeline_quality_state(
        market_payload,
        policy_rules=rules,
        stage="stage3",
        allow_estimated=allow_estimated,
    )
    quality_blockers = _filtered_quality_blockers(
        quality_state,
        skip_fund_flow_check=skip_fund_flow_check,
    )

    blocks: List[GateBlock] = []
    if completeness < min_completeness:
        blocks.append(
            GateBlock(
                "completeness",
                [
                    f"data_completeness={completeness:.3f} (<{min_completeness})",
                    "run Stage2/Stage2.5 to refresh market_data_complete.json before Stage3",
                ],
            )
        )

    if quality_blockers:
        issue_lines = [_issue_label(item, market_payload) for item in quality_blockers]
        blocks.append(GateBlock("unified_quality", issue_lines))

    if blocks:
        raise RuntimeError(format_gate_blocks("Stage3 阻断，以下问题需修复：", blocks))
    return



def _find_estimated_entry_by_key(
    market_payload: Dict[str, Any],
    key: str,
) -> Optional[tuple[str, str, Dict[str, Any]]]:
    macro = market_payload.get("macro_indicators", {})
    if isinstance(macro, dict) and isinstance(macro.get(key), dict):
        return ("macro_indicators", key, macro[key])

    monetary = market_payload.get("monetary_policy", {})
    if isinstance(monetary, dict) and isinstance(monetary.get(key), dict):
        return ("monetary_policy", key, monetary[key])

    for item in market_payload.get("bonds", []) or []:
        if isinstance(item, dict) and str(item.get("symbol")) == str(key):
            return ("bonds", str(item.get("symbol")), item)
    for item in market_payload.get("forex", []) or []:
        if isinstance(item, dict) and str(item.get("pair")) == str(key):
            return ("forex", str(item.get("pair")), item)
    for item in market_payload.get("commodities", []) or []:
        if isinstance(item, dict) and str(item.get("symbol")) == str(key):
            return ("commodities", str(item.get("symbol")), item)
    for item in market_payload.get("stock_indices", []) or []:
        if isinstance(item, dict) and str(item.get("symbol")) == str(key):
            return ("stock_indices", str(item.get("symbol")), item)
    fund_flow = market_payload.get("fund_flow", {})
    if isinstance(fund_flow, dict) and isinstance(fund_flow.get(key), dict):
        return ("fund_flow", key, fund_flow[key])
    return None


def _find_entry_by_item(
    market_payload: Dict[str, Any],
    item: Any,
) -> Optional[tuple[str, str, Dict[str, Any]]]:
    key = _gap_item_key(item)
    if not key:
        return None

    category = item.get("category") if isinstance(item, dict) else None
    if not category:
        return _find_estimated_entry_by_key(market_payload, key)

    section = market_payload.get(str(category))
    if isinstance(section, dict):
        entry = section.get(key)
        if isinstance(entry, dict):
            return (str(category), key, entry)
        return None

    if isinstance(section, list):
        for entry in section:
            if not isinstance(entry, dict):
                continue
            for field in ("key", "symbol", "pair", "name", "ts_code", "code"):
                value = entry.get(field)
                if value not in (None, "") and str(value) == key:
                    return (str(category), key, entry)
    return None


def _is_allowlisted_gap_item(
    market_payload: Dict[str, Any],
    item: Any,
    policy_rules: Optional[Dict[str, Any]] = None,
) -> bool:
    located = _find_entry_by_item(market_payload, item)
    if not located:
        return False
    category, real_key, entry = located
    if not isinstance(entry, dict) or not entry.get("is_estimated"):
        return False
    allowed, _ = is_estimated_allowlisted(category, real_key, entry, rules=policy_rules)
    return allowed

def _load_gap_monitor(gap_path: Path) -> Dict[str, List[str]]:
    if not gap_path.exists():
        return {"pending_tasks": [], "manual_required": []}
    try:
        with gap_path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {"pending_tasks": [], "manual_required": []}


def _resolve_gap_monitor_path(
    market_payload: Dict[str, Any],
    explicit_gap_path: Optional[Path] = None,
) -> Path:
    """优先使用同日运行目录下的 gap_monitor。"""
    run_paths = build_run_paths_from_reference(payload=market_payload, fallback_to_today=True)
    candidates: List[Path] = []
    candidates.append(run_paths.gap_monitor)
    if explicit_gap_path:
        candidates.append(explicit_gap_path)

    seen = set()
    for candidate in candidates:
        normalized = str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.exists():
            return candidate
    return candidates[0]


async def _run_analysis(
    market_path: Path,
    output_path: Path,
    min_completeness: float = MIN_COMPLETENESS_DEFAULT,
    gap_monitor_path: Optional[Path] = None,
    skip_gap_check: bool = False,
    skip_fund_flow_check: bool = False,
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

    policy_blockers: List[str] = []
    completeness_blockers: List[str] = []
    gap_blockers: List[str] = []
    stage2_blockers: List[str] = []
    fallback_used = False

    # 1) policy gate
    policy_rules = load_policy_rules()
    block_on_stale = bool(policy_rules.get("block_on_stale", True))
    critical_stale_keys = policy_rules.get("critical_stale_keys", ["cpi", "ppi", "pmi", "m1", "m2", "tsf"])
    live_quality_state = build_pipeline_quality_state(
        market_payload,
        policy_rules=_effective_policy_rules(
            policy_rules,
            block_on_stale=block_on_stale,
            critical_stale_keys=critical_stale_keys if isinstance(critical_stale_keys, list) else None,
        ),
        stage="stage3",
        allow_estimated=allow_estimated,
    )
    live_quality_blocker_keys = _quality_blocker_keys(
        _filtered_quality_blockers(
            live_quality_state,
            skip_fund_flow_check=skip_fund_flow_check,
        )
    )
    gap_quality_blocker_keys = _quality_blocker_keys(
        live_quality_state.get("quality_blockers") or []
    )
    meta_date = (
        market_payload.get("metadata", {}).get("date")
        or market_payload.get("metadata", {}).get("end_date")
        or market_payload.get("metadata", {}).get("start_date")
    )
    if meta_date:
        policy_path = build_run_paths_from_reference(payload=market_payload, fallback_to_today=True).policy_evaluation
        if policy_path.exists():
            try:
                policy_payload = json.loads(policy_path.read_text(encoding="utf-8"))

                raw_redlist = policy_payload.get("redlist") or []
                redlist_items: List[Any] = []
                for row in raw_redlist:
                    key = _gap_item_key(row)
                    if key:
                        redlist_items.append(row)

                allowlisted_redlist: List[str] = []
                unresolved_redlist: List[str] = []
                diagnostic_redlist: List[str] = []
                for item in redlist_items:
                    label = _item_label(item)
                    if _is_allowlisted_gap_item(market_payload, item, policy_rules):
                        allowlisted_redlist.append(label)
                    elif _policy_item_matches_live_blocker(item, live_quality_blocker_keys):
                        continue
                    elif _policy_item_has_current_entry(market_payload, item):
                        diagnostic_redlist.append(label)
                    else:
                        unresolved_redlist.append(label)
                for key in allowlisted_redlist:
                    _append_non_blocking_warning(
                        market_payload,
                        {
                            "level": "warning",
                            "code": "policy_allowlisted_redlist_ignored",
                            "key": key,
                            "message": f"policy_evaluation redlist 白名单放行: {key}",
                        },
                    )

                stale_redlist = policy_payload.get("stale_redlist") or []
                unresolved_stale_redlist: List[str] = []
                diagnostic_stale_redlist: List[str] = []
                for item in stale_redlist:
                    key = _gap_item_key(item)
                    if not key:
                        continue
                    label = _item_label(item)
                    if _policy_item_matches_live_blocker(item, live_quality_blocker_keys):
                        continue
                    if _policy_item_has_current_entry(market_payload, item):
                        diagnostic_stale_redlist.append(label)
                    else:
                        unresolved_stale_redlist.append(label)

                if policy_payload.get("block_stage3") and (unresolved_redlist or unresolved_stale_redlist):
                    policy_blockers.append(
                        f"redlist={unresolved_redlist}, stale_redlist={unresolved_stale_redlist}"
                    )

                if policy_payload.get("block_stage3") and (diagnostic_redlist or diagnostic_stale_redlist):
                    _append_non_blocking_warning(
                        market_payload,
                        {
                            "level": "warning",
                            "code": "policy_file_diagnostic_only",
                            "key": "*",
                            "message": (
                                "policy_evaluation.json retained for diagnostics only: "
                                f"redlist={diagnostic_redlist}, stale_redlist={diagnostic_stale_redlist}"
                            ),
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] policy_evaluation check skipped: {exc}")

    # 2) completeness gate
    completeness_error: Optional[str] = None
    try:
        _require_data_completeness(
            market_payload,
            min_completeness,
            allow_estimated=allow_estimated,
            skip_fund_flow_check=skip_fund_flow_check,
            block_on_stale=block_on_stale,
            critical_stale_keys=critical_stale_keys if isinstance(critical_stale_keys, list) else None,
            policy_rules=policy_rules,
        )
    except RuntimeError as exc:
        completeness_error = str(exc)
        if allow_fallback:
            fallback_used = True
            print(f"[WARN] 数据完整性未达标，但 allow_fallback=True，继续运行。原因: {exc}")
        else:
            completeness_blockers.extend(_message_items(completeness_error))

    # 3) gap monitor gate
    ai_websearch_flag = bool(market_payload.get("metadata", {}).get("ai_websearch_enhanced"))

    gap_path = _resolve_gap_monitor_path(market_payload, gap_monitor_path)
    print(f"[META] gap_monitor 路径：{gap_path}")
    if not skip_gap_check:
        gap = _load_gap_monitor(gap_path)
        pending = gap.get("pending_tasks", []) or []
        manual_raw = gap.get("manual_required", []) or []
        pending = effective_gap_items(
            market_payload,
            live_quality_state.get("quality_blockers") or [],
            pending,
            skip_fund_flow_check=skip_fund_flow_check,
        )
        manual_raw = effective_gap_items(
            market_payload,
            live_quality_state.get("quality_blockers") or [],
            manual_raw,
            skip_fund_flow_check=skip_fund_flow_check,
        )
        pending_blocking: List[str] = []
        stale_gap_items: List[str] = []

        for item in pending:
            key = _gap_item_key(item)
            if not key:
                continue
            label = _item_label(item)
            if _is_allowlisted_gap_item(market_payload, item, policy_rules):
                _append_non_blocking_warning(
                    market_payload,
                    {
                        "level": "warning",
                        "code": "gap_allowlisted_pending_ignored",
                        "key": label,
                        "message": f"gap_monitor pending allowlist pass: {label}",
                    },
                )
            elif _policy_item_matches_live_blocker(item, gap_quality_blocker_keys):
                pending_blocking.append(label)
            elif _policy_item_has_current_entry(market_payload, item):
                stale_gap_items.append(label)
            else:
                pending_blocking.append(label)

        manual_blocking: List[str] = []
        for item in manual_raw:
            key = _gap_item_key(item)
            if not key:
                continue
            label = _item_label(item)
            if _is_allowlisted_gap_item(market_payload, item, policy_rules):
                _append_non_blocking_warning(
                    market_payload,
                    {
                        "level": "warning",
                        "code": "gap_allowlisted_manual_ignored",
                        "key": label,
                        "message": f"gap_monitor allowlist pass: {label}",
                    },
                )
            elif _policy_item_matches_live_blocker(item, gap_quality_blocker_keys):
                manual_blocking.append(label)
            elif _policy_item_has_current_entry(market_payload, item):
                stale_gap_items.append(label)
            else:
                manual_blocking.append(label)

        if stale_gap_items:
            _append_non_blocking_warning(
                market_payload,
                {
                    "level": "warning",
                    "code": "gap_monitor_file_diagnostic_only",
                    "key": "*",
                    "message": (
                        "gap_monitor retained for diagnostics only; stale items ignored: "
                        + ", ".join(sorted(set(stale_gap_items)))
                    ),
                },
            )

        if pending_blocking or manual_blocking:
            gap_blockers.append(f"path: {gap_path}")
            if pending_blocking:
                gap_blockers.append(f"pending: {pending_blocking}")
            if manual_blocking:
                gap_blockers.append(f"manual_required: {manual_blocking}")
    else:
        print(f"[WARN] 已跳过 gap_monitor 检查（调试模式），路径: {gap_path}")
    # 4) stage2 completion gate
    if not ai_websearch_flag:
        stage2_blockers.append("未检测到 metadata.ai_websearch_enhanced=true")

    if policy_blockers or completeness_blockers or gap_blockers or stage2_blockers:
        raise RuntimeError(
            format_gate_blocks(
                "Stage3 阻断，以下问题需修复：",
                [
                    GateBlock("policy gate", policy_blockers),
                    GateBlock("completeness/unified_quality", completeness_blockers),
                    GateBlock("gap_monitor", gap_blockers),
                    GateBlock("stage2 flag", stage2_blockers),
                ],
            )
        )

    contract = MarketDataContract(**market_payload)

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
    non_blocking_warnings = market_payload.get("metadata", {}).get("non_blocking_warnings", [])
    if isinstance(non_blocking_warnings, list) and non_blocking_warnings:
        pring_result["metadata"]["non_blocking_warnings"] = non_blocking_warnings

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
        "warnings": non_blocking_warnings if isinstance(non_blocking_warnings, list) else [],
        "errors": [],
        "runtime_sec": round(runtime, 2),
    }
    log_path = build_run_paths_from_reference(payload=market_payload, fallback_to_today=True).stage3_log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_log = log_path.with_suffix(".tmp")
    with tmp_log.open("w", encoding="utf-8") as fp:
        json.dump(log_payload, fp, ensure_ascii=False, indent=2)
    tmp_log.replace(log_path)

    return pring_result


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
        default=None,
        help="可选：显式指定 gap monitor 路径；默认优先按 market_data 日期匹配 data/runs/YYYYMMDD/gap_monitor.json"
    )
    parser.add_argument(
        "--skip-gap-check",
        action="store_true",
        help="跳过 gap monitor 检查（仅调试用，生产禁止）"
    )
    parser.add_argument(
        "--skip-fund-flow-check",
        action="store_true",
        help="跳过 fund_flow 的占位/零值硬阻断（仅在资金流缺口时临时出报告用）"
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
    min_completeness = float(args.min_completeness)
    days = int(args.days)

    if not market_path.exists():
        raise FileNotFoundError(f"未找到市场数据文件: {market_path}")

    output_path = (
        Path(args.output).resolve()
        if args.output
        else (market_path.parent / "pring_result.json").resolve()
    )

    asyncio.run(_run_analysis(
        market_path,
        output_path,
        min_completeness=min_completeness,
        gap_monitor_path=Path(args.gap_monitor) if args.gap_monitor else None,
        skip_gap_check=args.skip_gap_check,
        skip_fund_flow_check=args.skip_fund_flow_check,
        days=days,
        allow_fallback=args.allow_fallback,
        allow_estimated=args.allow_estimated,
        legacy_stage_rules=args.legacy_stage_rules,
    ))


if __name__ == "__main__":
    main()
