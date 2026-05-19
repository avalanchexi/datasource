# -*- coding: utf-8 -*-

from datasource.utils.pipeline_quality_state import build_pipeline_quality_state


def _base_payload():
    return {
        "metadata": {
            "date": "2026-04-27",
            "data_completeness": 1.0,
            "missing_items": {"macro_indicators": [{"key": "industrial"}]},
            "quality_blockers": [{"category": "monetary_policy", "key": "mlf", "reason": "old"}],
        },
        "missing_items": ["industrial"],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": 5.0,
                "change_rate": 4.0,
                "is_estimated": False,
                "source": "websearch_manual(https://example.com/industrial)",
                "source_url": "https://example.com/industrial",
            }
        },
        "monetary_policy": {
            "mlf": {
                "current_value": 2.0,
                "change_from_120d": 0.0,
                "is_estimated": False,
                "source": "websearch_manual(https://example.com/mlf)",
                "source_url": "https://example.com/mlf",
            }
        },
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }


def test_pipeline_quality_state_ignores_stale_missing_when_values_are_complete():
    state = build_pipeline_quality_state(_base_payload(), allow_estimated=False)

    assert state["missing_items"] == {}
    assert state["quality_blockers"] == []
    assert state["manual_required"] == []
    assert state["policy_evaluation"]["block_stage3"] is False
    assert state["gap_monitor_view"]["manual_required"] == []


def test_pipeline_quality_state_blocks_missing_compare_values():
    payload = _base_payload()
    payload["macro_indicators"]["industrial"]["previous_value"] = None
    payload["macro_indicators"]["industrial"]["change_rate"] = None

    state = build_pipeline_quality_state(payload, allow_estimated=False)

    assert {"category": "macro_indicators", "key": "industrial", "reason": "missing_compare_values"} in state["quality_blockers"]
    assert state["missing_items"]["macro_indicators"][0]["key"] == "industrial"
    assert "industrial" in state["gap_monitor_view"]["manual_required"]


def test_pipeline_quality_state_requires_source_url_for_manual_values():
    payload = _base_payload()
    payload["commodities"] = [
        {
            "symbol": "GC=F",
            "name": "COMEX黄金",
            "current_price": 3450.0,
            "daily_change": 1.2,
            "source": "websearch_manual",
        }
    ]

    state = build_pipeline_quality_state(payload, allow_estimated=False)

    assert {"category": "commodities", "key": "GC=F", "reason": "missing_source_url"} in state["source_url_issues"]
    assert {"category": "commodities", "key": "GC=F", "reason": "missing_source_url"} in state["quality_blockers"]


def test_pipeline_quality_state_requires_source_url_for_stage2_auto_values():
    payload = _base_payload()
    payload["commodities"] = [
        {
            "symbol": "GC=F",
            "current_price": 3450.0,
            "source": "stage2_auto_extract",
        }
    ]

    state = build_pipeline_quality_state(payload, allow_estimated=False)

    assert {"category": "commodities", "key": "GC=F", "reason": "missing_source_url"} in state["source_url_issues"]
    assert {"category": "commodities", "key": "GC=F", "reason": "missing_source_url"} in state["quality_blockers"]


def test_pipeline_quality_state_blocks_disallowed_estimated_values_even_with_allow_estimated():
    payload = _base_payload()
    payload["monetary_policy"]["m2"] = {
        "current_value": 7.1,
        "change_from_120d": 0.2,
        "is_estimated": True,
        "source_url": "https://example.com/m2",
    }

    state = build_pipeline_quality_state(payload, allow_estimated=True)

    assert {"category": "monetary_policy", "key": "m2", "reason": "estimated_not_allowed"} in state["quality_blockers"]
    assert "monetary_policy.m2" in state["policy_evaluation"]["estimated_blockers"]


def test_pipeline_quality_state_flags_commodity_window_mismatch():
    payload = _base_payload()
    payload["commodities"] = [
        {
            "symbol": "GC=F",
            "current_price": 3450.0,
            "daily_change": 2.0,
            "daily_change_basis": "change_5d",
            "ytd_change": 12.0,
            "ytd_change_basis": "change_120d",
            "source_url": "https://example.com/gold",
        }
    ]

    state = build_pipeline_quality_state(payload, allow_estimated=False)

    reasons = {row["reason"] for row in state["window_metric_issues"]}
    assert "daily_change_from_change_5d" in reasons
    assert "ytd_change_from_change_120d" in reasons
    assert {"category": "commodities", "key": "GC=F", "reason": "daily_change_from_change_5d"} in state["quality_blockers"]
    assert {"category": "commodities", "key": "GC=F", "reason": "ytd_change_from_change_120d"} in state["quality_blockers"]
    assert state["policy_evaluation"]["block_stage3"] is True


def test_pipeline_quality_state_requires_source_url_when_any_fund_flow_value_is_real():
    payload = _base_payload()
    payload["fund_flow"] = {
        "northbound": {
            "recent_5d": 0,
            "total_120d": 520.3,
            "trend": "流入",
            "source": "websearch_manual",
        }
    }

    state = build_pipeline_quality_state(payload, allow_estimated=False)

    assert {"category": "fund_flow", "key": "northbound", "reason": "missing_source_url"} in state["source_url_issues"]
    assert {"category": "fund_flow", "key": "northbound", "reason": "missing_source_url"} in state["quality_blockers"]


def test_pipeline_quality_state_flags_fund_flow_window_missing_for_missing_or_zero_values():
    payload = _base_payload()
    payload["fund_flow"] = {
        "northbound": {
            "recent_5d": 0,
            "total_120d": 520.3,
            "source_url": "https://example.com/northbound",
        },
        "southbound": {
            "recent_5d": 31.2,
            "source_url": "https://example.com/southbound",
        },
    }

    state = build_pipeline_quality_state(payload, allow_estimated=False)

    fund_flow_blockers = [
        row
        for row in state["quality_blockers"]
        if row["category"] == "fund_flow" and row["reason"] == "fund_flow_window_missing"
    ]
    assert {"key": "northbound", "field": "recent_5d"} in [
        {"key": row["key"], "field": row["details"]["field"]} for row in fund_flow_blockers
    ]
    assert {"key": "southbound", "field": "total_120d"} in [
        {"key": row["key"], "field": row["details"]["field"]} for row in fund_flow_blockers
    ]


def test_pipeline_quality_state_blocks_estimated_fund_flow_with_diagnostics_when_allow_estimated():
    payload = _base_payload()
    payload["fund_flow"] = {
        "etf": {
            "recent_5d": -50.0,
            "total_120d": -9000.0,
            "trend": "流出",
            "source": "websearch_manual",
            "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
            "metric_basis": "news_net_flow",
            "source_tier": "tier3",
            "window_evidence": "news_summary",
            "is_estimated": True,
        }
    }

    state = build_pipeline_quality_state(payload, allow_estimated=True)

    blocker = next(
        row
        for row in state["quality_blockers"]
        if row["category"] == "fund_flow"
        and row["key"] == "etf"
        and row["reason"] == "estimated_not_allowed"
    )
    assert blocker["details"] == {
        "source_tier": "tier3",
        "window_evidence": "news_summary",
        "metric_basis": "news_net_flow",
    }
    assert state["policy_evaluation"]["block_stage3"] is True
    assert "etf" in state["gap_monitor_view"]["manual_required"]


def test_pipeline_quality_state_blocks_missing_zero_and_placeholder_primary_values():
    payload = _base_payload()
    payload["macro_indicators"]["industrial"]["current_value"] = None
    payload["commodities"] = [
        {
            "symbol": "GC=F",
            "current_price": None,
            "source_url": "https://example.com/gold",
        }
    ]
    payload["forex"] = [
        {
            "pair": "USDCNY",
            "current_rate": 7.13,
            "source_url": "https://example.com/usdcny",
        }
    ]
    payload["stock_indices"] = [
        {
            "symbol": "000001.SH",
            "current_price": 0,
            "source_url": "https://example.com/sh",
        }
    ]

    state = build_pipeline_quality_state(payload, allow_estimated=False)

    assert {"category": "macro_indicators", "key": "industrial", "reason": "primary_value_missing"} in state["quality_blockers"]
    assert {"category": "commodities", "key": "GC=F", "reason": "primary_value_missing"} in state["quality_blockers"]
    assert {"category": "forex", "key": "USDCNY", "reason": "primary_value_missing"} in state["quality_blockers"]
    assert {"category": "stock_indices", "key": "000001.SH", "reason": "primary_value_missing"} in state["quality_blockers"]
    assert state["missing_items"]["macro_indicators"][0]["key"] == "industrial"
    assert "industrial" in state["gap_monitor_view"]["manual_required"]
    assert state["policy_evaluation"]["block_stage3"] is True


def test_pipeline_quality_state_blocks_critical_stale_items_from_policy_rules():
    payload = _base_payload()
    payload["macro_indicators"]["cpi"] = {
        "current_value": 1.2,
        "previous_value": 1.0,
        "change_rate": 20.0,
        "is_stale": True,
        "source_url": "https://example.com/cpi",
    }
    payload["monetary_policy"]["m2"] = {
        "current_value": 7.1,
        "change_from_120d": 0.2,
        "is_stale": True,
        "source_url": "https://example.com/m2",
    }

    state = build_pipeline_quality_state(
        payload,
        policy_rules={"block_on_stale": True, "critical_stale_keys": ["cpi", "m2", "tsf"]},
        allow_estimated=False,
    )

    assert {"category": "macro_indicators", "key": "cpi", "reason": "critical_stale"} in state["quality_blockers"]
    assert {"category": "monetary_policy", "key": "m2", "reason": "critical_stale"} in state["quality_blockers"]
    assert {"category": "macro_indicators", "key": "cpi"} in state["policy_evaluation"]["stale_redlist"]
    assert {"category": "monetary_policy", "key": "m2"} in state["policy_evaluation"]["stale_redlist"]
    assert state["policy_evaluation"]["block_stage3"] is True
