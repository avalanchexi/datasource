# -*- coding: utf-8 -*-

from datasource.utils.pipeline_audit import build_pipeline_audit, build_rule_inventory


def test_rule_inventory_includes_core_gate_rules():
    inventory = build_rule_inventory()

    rule_ids = {rule["rule_id"] for rule in inventory["rules"]}

    assert {
        "missing_source_url",
        "fund_flow_window_missing",
        "estimated_not_allowed",
        "daily_change_from_change_5d",
        "ytd_change_from_change_120d",
    }.issubset(rule_ids)


def test_pipeline_audit_skips_fund_flow_gaps_when_override_enabled():
    market_payload = {
        "fund_flow": {
            "etf": {
                "recent_5d": None,
                "total_120d": None,
                "source_url": "https://example.com/etf",
            }
        }
    }
    gap_payload = {
        "pending_tasks": [{"category": "fund_flow", "key": "etf"}],
        "manual_required": [{"category": "fund_flow", "key": "etf"}],
    }

    audit = build_pipeline_audit(
        market_payload,
        gap_payload=gap_payload,
        skip_fund_flow_check=True,
    )

    assert audit["errors"] == []
    assert audit["stage3_effective_blockers"] == []
    assert audit["stage4_effective_blockers"] == []
    assert audit["effective_gap_monitor"]["pending_tasks"] == []
    assert audit["effective_gap_monitor"]["manual_required"] == []


def test_pipeline_audit_blocks_fallback_pring_result_for_production_reports():
    audit = build_pipeline_audit(
        {},
        pring_payload={"fallback_used": True},
    )

    fallback_errors = [
        error for error in audit["errors"] if error.get("code") == "fallback_pring_result"
    ]

    assert fallback_errors
    message = fallback_errors[0]["message"]
    assert "fallback_used=true" in message
    assert "production report" in message.lower()


def test_pipeline_audit_inventory_covers_commodity_window_blockers():
    market_payload = {
        "commodities": [
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
    }

    audit = build_pipeline_audit(market_payload)
    raw_reasons = {blocker["reason"] for blocker in audit["raw_quality_blockers"]}
    inventory_reasons = {rule["rule_id"] for rule in build_rule_inventory()["rules"]}
    commodity_window_reasons = {
        "daily_change_from_change_5d",
        "ytd_change_from_change_120d",
    }

    assert commodity_window_reasons.issubset(raw_reasons)
    assert commodity_window_reasons.issubset(inventory_reasons)
