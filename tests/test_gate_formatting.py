from datasource.utils.gate_formatting import (
    GateBlock,
    format_gate_blocks,
    format_quality_issue,
)


def test_format_quality_issue_includes_details():
    issue = {
        "category": "fund_flow",
        "key": "etf",
        "reason": "estimated_not_allowed",
        "details": {
            "source_tier": "tier3",
            "window_evidence": "news_summary",
            "metric_basis": "estimated_net_flow",
        },
    }

    text = format_quality_issue(issue)

    assert (
        text
        == "fund_flow.etf estimated_not_allowed "
        "source_tier=tier3 window_evidence=news_summary metric_basis=estimated_net_flow"
    )


def test_format_gate_blocks_outputs_sections():
    text = format_gate_blocks(
        "Stage3 阻断，以下问题需修复：",
        [
            GateBlock("policy gate", ["fund_flow.etf estimated_not_allowed"]),
            GateBlock("gap_monitor", ["pending: CN10Y_CDB", "manual_required: USDCNY"]),
        ],
    )

    assert "[policy gate]" in text
    assert "- fund_flow.etf estimated_not_allowed" in text
    assert "[gap_monitor]" in text
    assert "- pending: CN10Y_CDB" in text
