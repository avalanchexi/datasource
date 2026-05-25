import pytest

from datasource.utils.pipeline_gates import (
    FUND_FLOW_SKIP_REASONS,
    assert_no_fallback_pring_result,
    effective_gap_items,
    effective_quality_blockers,
    gap_item_label,
)


def test_fund_flow_skip_reasons_are_explicit():
    assert FUND_FLOW_SKIP_REASONS == {
        "fund_flow_window_missing",
        "estimated_not_allowed",
    }


def test_effective_quality_blockers_filters_only_fund_flow_skip_reasons():
    blockers = [
        {"category": "fund_flow", "key": "etf", "reason": "fund_flow_window_missing"},
        {"category": "fund_flow", "key": "northbound", "reason": "estimated_not_allowed"},
        {"category": "commodities", "key": "BCOM", "reason": "estimated_not_allowed"},
        {"category": "macro_indicators", "key": "industrial", "reason": "missing_compare_values"},
    ]

    assert effective_quality_blockers(blockers, skip_fund_flow_check=True) == [
        {"category": "commodities", "key": "BCOM", "reason": "estimated_not_allowed"},
        {"category": "macro_indicators", "key": "industrial", "reason": "missing_compare_values"},
    ]


def test_effective_quality_blockers_keeps_fund_flow_source_url_issues():
    blockers = [
        {"category": "fund_flow", "key": "northbound", "reason": "missing_source_url"},
    ]

    assert effective_quality_blockers(blockers, skip_fund_flow_check=True) == blockers


def test_gap_item_label_prefers_category_and_key():
    assert gap_item_label({"category": "fund_flow", "key": "etf"}) == "fund_flow.etf"
    assert gap_item_label({"symbol": "BCOM"}) == "BCOM"
    assert gap_item_label("bdi") == "bdi"


def test_effective_gap_items_filters_matching_fund_flow_quality_blockers():
    market_payload = {
        "fund_flow": {
            "etf": {"recent_5d": None, "total_120d": None},
        },
        "macro_indicators": {
            "bdi": {"current_value": 2991.0},
        },
    }
    quality_blockers = [
        {"category": "fund_flow", "key": "etf", "reason": "fund_flow_window_missing"},
        {"category": "macro_indicators", "key": "bdi", "reason": "estimated_not_allowed"},
    ]
    gap_items = [
        {"category": "fund_flow", "key": "etf"},
        {"category": "macro_indicators", "key": "bdi"},
        "missing_unknown",
    ]

    assert effective_gap_items(
        market_payload,
        quality_blockers,
        gap_items,
        skip_fund_flow_check=True,
    ) == [
        {"category": "macro_indicators", "key": "bdi"},
        "missing_unknown",
    ]


def test_assert_no_fallback_pring_result_blocks_by_default():
    with pytest.raises(RuntimeError) as exc:
        assert_no_fallback_pring_result({"fallback_used": True})

    assert "fallback_used=true" in str(exc.value)


def test_assert_no_fallback_pring_result_allows_debug_override():
    assert_no_fallback_pring_result({"fallback_used": True}, allow_fallback_report=True)
