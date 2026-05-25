# -*- coding: utf-8 -*-
"""Pipeline rule inventory and consistency audit helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from datasource.utils.pipeline_gates import (
    assert_no_fallback_pring_result,
    effective_gap_items,
    effective_quality_blockers,
)
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state


_QUALITY_STATE_MODULE = "datasource.utils.pipeline_quality_state"
_STAGE_CONSUMERS = [
    "scripts.stage3_pring_analyzer",
    "scripts.stage4_report_generator",
    "scripts.audit_pipeline_consistency",
]


def build_rule_inventory() -> Dict[str, Any]:
    """Return the stable inventory of pipeline gate rules and consumers."""
    return {
        "schema_version": 1,
        "rules": [
            _rule("primary_value_missing", _QUALITY_STATE_MODULE, True, False),
            _rule("missing_compare_values", _QUALITY_STATE_MODULE, True, False),
            _rule("critical_stale", _QUALITY_STATE_MODULE, True, False),
            _rule("missing_source_url", _QUALITY_STATE_MODULE, True, False),
            _rule("daily_change_from_change_5d", _QUALITY_STATE_MODULE, True, False),
            _rule("ytd_change_from_change_120d", _QUALITY_STATE_MODULE, True, False),
            _rule(
                "estimated_not_allowed",
                "datasource.utils.pipeline_quality_state + datasource.utils.policy_rules",
                True,
                True,
            ),
            _rule("fund_flow_window_missing", _QUALITY_STATE_MODULE, True, True),
            _rule(
                "manual_official_not_estimated",
                "scripts.stage2_5_injector",
                False,
                False,
                consumers=[
                    "scripts.stage2_5_injector",
                    "scripts.stage3_pring_analyzer",
                    "scripts.stage4_report_generator",
                    "scripts.audit_pipeline_consistency",
                ],
            ),
        ],
    }


def build_pipeline_audit(
    market_payload: Dict[str, Any],
    pring_payload: Optional[Dict[str, Any]] = None,
    gap_payload: Optional[Dict[str, Any]] = None,
    skip_fund_flow_check: bool = False,
) -> Dict[str, Any]:
    """Build Stage3/Stage4 consistency audit output from shared gate helpers."""
    market = market_payload if isinstance(market_payload, dict) else {}
    quality_state = build_pipeline_quality_state(
        market,
        stage="stage4",
        allow_estimated=True,
    )
    raw_quality_blockers = list(quality_state.get("quality_blockers") or [])
    stage3_effective_blockers = effective_quality_blockers(
        raw_quality_blockers,
        skip_fund_flow_check=skip_fund_flow_check,
    )
    stage4_effective_blockers = effective_quality_blockers(
        raw_quality_blockers,
        skip_fund_flow_check=skip_fund_flow_check,
    )

    errors: List[Dict[str, Any]] = []
    warnings = list(quality_state.get("warnings") or [])

    if stage3_effective_blockers != stage4_effective_blockers:
        errors.append(
            {
                "code": "rule_drift",
                "message": "Stage3 and Stage4 effective quality blockers diverged.",
                "stage3_effective_blockers": stage3_effective_blockers,
                "stage4_effective_blockers": stage4_effective_blockers,
            }
        )

    try:
        assert_no_fallback_pring_result(pring_payload)
    except RuntimeError as exc:
        errors.append(
            {
                "code": "fallback_pring_result",
                "message": (
                    "fallback_used=true Pring result cannot be used for production reports; "
                    f"{exc}"
                ),
            }
        )

    return {
        "raw_quality_blockers": raw_quality_blockers,
        "stage3_effective_blockers": stage3_effective_blockers,
        "stage4_effective_blockers": stage4_effective_blockers,
        "effective_gap_monitor": _effective_gap_monitor(
            market,
            raw_quality_blockers,
            quality_state,
            gap_payload,
            skip_fund_flow_check=skip_fund_flow_check,
        ),
        "errors": errors,
        "warnings": warnings,
    }


def _rule(
    rule_id: str,
    source_module: str,
    blockable: bool,
    fund_flow_skip_allowed: bool,
    *,
    consumers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "rule_id": rule_id,
        "source_module": source_module,
        "consumers": list(consumers or _STAGE_CONSUMERS),
        "blockable": blockable,
        "fund_flow_skip_allowed": fund_flow_skip_allowed,
    }


def _effective_gap_monitor(
    market_payload: Dict[str, Any],
    raw_quality_blockers: List[Dict[str, Any]],
    quality_state: Dict[str, Any],
    gap_payload: Optional[Dict[str, Any]],
    *,
    skip_fund_flow_check: bool,
) -> Dict[str, Any]:
    gap = (
        gap_payload
        if isinstance(gap_payload, dict)
        else quality_state.get("gap_monitor_view") or {}
    )
    pending = _gap_list(gap.get("pending_tasks"))
    manual_required = _gap_list(gap.get("manual_required"))
    return {
        "pending_tasks": effective_gap_items(
            market_payload,
            raw_quality_blockers,
            pending,
            skip_fund_flow_check=skip_fund_flow_check,
        ),
        "manual_required": effective_gap_items(
            market_payload,
            raw_quality_blockers,
            manual_required,
            skip_fund_flow_check=skip_fund_flow_check,
        ),
    }


def _gap_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []
