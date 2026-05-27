# -*- coding: utf-8 -*-

import pytest

from datasource.utils.pipeline_gate import (
    assert_no_fallback_pring_result,
    collect_fund_flow_downgraded_items,
    filter_effective_gap_items,
    filter_effective_quality_blockers,
)
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state


def _base_payload():
    return {
        "metadata": {"date": "2026-05-27", "data_completeness": 1.0},
        "missing_items": [],
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }


def _estimated_etf_payload():
    payload = _base_payload()
    payload["fund_flow"] = {
        "etf": {
            "recent_5d": -200.0,
            "total_120d": -1500.0,
            "trend": "流出",
            "source": "websearch_manual",
            "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
            "metric_basis": "news_net_flow",
            "source_tier": "tier3",
            "window_evidence": "news_summary",
            "is_estimated": True,
        }
    }
    return payload


def test_filter_effective_quality_blockers_downgrades_only_fund_flow_estimate():
    payload = _estimated_etf_payload()
    payload["macro_indicators"]["industrial"] = {
        "current_value": 5.2,
        "previous_value": None,
        "change_rate": None,
        "source_url": "https://example.com/industrial",
        "is_estimated": False,
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)

    strict = filter_effective_quality_blockers(state)
    downgraded = filter_effective_quality_blockers(
        state,
        allow_fund_flow_downgrade=True,
    )

    assert {
        "category": "fund_flow",
        "key": "etf",
        "reason": "estimated_not_allowed",
        "details": {
            "source_tier": "tier3",
            "window_evidence": "news_summary",
            "metric_basis": "news_net_flow",
        },
    } in strict
    assert {
        "category": "macro_indicators",
        "key": "industrial",
        "reason": "missing_compare_values",
    } in strict
    assert {
        "category": "macro_indicators",
        "key": "industrial",
        "reason": "missing_compare_values",
    } in downgraded
    assert not any(
        item["category"] == "fund_flow" and item["key"] == "etf" for item in downgraded
    )


def test_filter_effective_quality_blockers_keeps_fund_flow_missing_source_url():
    payload = _base_payload()
    payload["fund_flow"] = {
        "etf": {
            "recent_5d": -200.0,
            "total_120d": -1500.0,
            "trend": "流出",
            "source": "websearch_manual",
            "metric_basis": "news_net_flow",
            "source_tier": "tier3",
            "window_evidence": "news_summary",
            "is_estimated": True,
        }
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)

    downgraded = filter_effective_quality_blockers(
        state,
        allow_fund_flow_downgrade=True,
    )

    assert {
        "category": "fund_flow",
        "key": "etf",
        "reason": "missing_source_url",
    } in downgraded


def test_filter_effective_quality_blockers_downgrades_missing_fund_flow_windows():
    payload = _base_payload()
    payload["fund_flow"] = {
        "etf": {
            "recent_5d": None,
            "total_120d": None,
            "trend": "待核查",
            "source": "websearch_manual",
            "source_url": "https://data.eastmoney.com/etf/",
            "is_estimated": False,
        }
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)

    downgraded = filter_effective_quality_blockers(
        state,
        allow_fund_flow_downgrade=True,
    )

    assert downgraded == []


def test_filter_effective_gap_items_uses_downgraded_quality_state():
    payload = _estimated_etf_payload()
    payload["macro_indicators"]["industrial"] = {
        "current_value": 5.2,
        "previous_value": None,
        "change_rate": None,
        "source_url": "https://example.com/industrial",
        "is_estimated": False,
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)
    gap_items = [
        {"category": "fund_flow", "key": "etf"},
        {"category": "macro_indicators", "key": "industrial"},
    ]

    strict = filter_effective_gap_items(payload, state, gap_items)
    downgraded = filter_effective_gap_items(
        payload,
        state,
        gap_items,
        allow_fund_flow_downgrade=True,
    )

    assert strict == gap_items
    assert downgraded == [{"category": "macro_indicators", "key": "industrial"}]


def test_filter_effective_gap_items_keeps_absent_fund_flow_item():
    payload = _base_payload()
    state = build_pipeline_quality_state(payload, allow_estimated=True)
    gap_items = [{"category": "fund_flow", "key": "etf"}]

    unresolved = filter_effective_gap_items(
        payload,
        state,
        gap_items,
        allow_fund_flow_downgrade=True,
    )

    assert unresolved == gap_items


def test_filter_effective_gap_items_uses_canonical_key_for_list_alias_match():
    payload = _base_payload()
    payload["commodities"] = [
        {
            "symbol": "GC=F",
            "name": "COMEX黄金",
            "current_price": None,
            "source_url": "https://example.com/gold",
        }
    ]
    state = build_pipeline_quality_state(payload, allow_estimated=True)
    gap_items = [{"category": "commodities", "name": "COMEX黄金"}]

    unresolved = filter_effective_gap_items(payload, state, gap_items)

    assert {
        "category": "commodities",
        "key": "GC=F",
        "reason": "primary_value_missing",
    } in state["quality_blockers"]
    assert unresolved == gap_items


def test_filter_effective_quality_blockers_downgrades_non_etf_fund_flow_estimate():
    payload = _base_payload()
    payload["fund_flow"] = {
        "northbound": {
            "recent_5d": 12.3,
            "total_120d": 456.7,
            "trend": "流入",
            "source": "websearch_manual",
            "source_url": "https://data.eastmoney.com/hsgt/",
            "metric_basis": "news_net_flow",
            "source_tier": "tier3",
            "window_evidence": "news_summary",
            "is_estimated": True,
        }
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)

    strict = filter_effective_quality_blockers(state)
    downgraded = filter_effective_quality_blockers(
        state,
        allow_fund_flow_downgrade=True,
    )

    assert {
        "category": "fund_flow",
        "key": "northbound",
        "reason": "estimated_not_allowed",
        "details": {
            "source_tier": "tier3",
            "window_evidence": "news_summary",
            "metric_basis": "news_net_flow",
        },
    } in strict
    assert downgraded == []


def test_collect_fund_flow_downgraded_items_returns_only_downgradable_items():
    payload = _estimated_etf_payload()
    payload["fund_flow"]["northbound"] = {
        "recent_5d": 12.3,
        "total_120d": 456.7,
        "trend": "流入",
        "source": "websearch_manual",
        "is_estimated": False,
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)

    items = collect_fund_flow_downgraded_items(state)

    assert items == [
        {
            "category": "fund_flow",
            "key": "etf",
            "reason": "estimated_not_allowed",
            "details": {
                "source_tier": "tier3",
                "window_evidence": "news_summary",
                "metric_basis": "news_net_flow",
            },
        }
    ]


def test_assert_no_fallback_pring_result_blocks_by_default():
    with pytest.raises(RuntimeError) as exc:
        assert_no_fallback_pring_result({"fallback_used": True})

    assert "fallback_used=true" in str(exc.value)


def test_assert_no_fallback_pring_result_can_be_allowed_explicitly():
    assert_no_fallback_pring_result(
        {"fallback_used": True},
        allow_fallback_report=True,
    )
