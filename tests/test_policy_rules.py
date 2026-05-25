from datetime import datetime

from datasource.utils.policy_rules import (
    evaluate_policy,
    get_estimated_allowlist_keys,
    get_non_blocking_warning_rules,
    is_estimated_allowlisted,
)


def test_policy_blocks_on_critical_missing():
    market_payload = {
        "metadata": {
            "date": "2025-01-01",
            "missing_items": {
                "macro_indicators": [{"key": "dxy"}]
            },
        }
    }
    result = evaluate_policy(market_payload)
    assert result["block_stage3"] is True
    assert result["redlist"]


def test_policy_blocks_on_critical_stale():
    market_payload = {
        "metadata": {"date": "2026-02-27"},
        "macro_indicators": {
            "cpi": {
                "current_value": 0.8,
                "date": "2025-12",
                "expected_period": "2026-01",
                "is_stale": True,
                "stale_reason": "actual_period_behind_expected",
            }
        },
    }
    result = evaluate_policy(market_payload)
    assert result["block_stage3"] is True
    assert result["stale_redlist"]


def test_estimated_allowlist_defaults_include_cn10y_cdb_and_bdi():
    keys = {item.lower() for item in get_estimated_allowlist_keys()}
    assert "cn10y_cdb" in keys
    assert "bdi" in keys


def test_bdi_allowlist_requires_trusted_source():
    today = datetime.now().strftime("%Y-%m-%d")
    ok, _ = is_estimated_allowlisted(
        "macro_indicators",
        "bdi",
        {
            "current_value": 2233.0,
            "unit": "points",
            "date": today,
            "source_url": "https://www.tradingeconomics.com/commodity/baltic",
            "is_estimated": True,
        },
    )
    assert ok is True

    blocked, reasons = is_estimated_allowlisted(
        "macro_indicators",
        "bdi",
        {
            "current_value": 2233.0,
            "unit": "points",
            "date": today,
            "source_url": "https://example.com/bdi",
            "is_estimated": True,
        },
    )
    assert blocked is False
    assert any("untrusted" in reason for reason in reasons)


def test_bdi_allowlist_accepts_friday_value_on_monday_with_weekend_grace():
    rules = {
        "estimated_allowlist_keys": ["bdi"],
        "bdi_estimated_allow_conditions": {
            "trusted_domains": ["tradingeconomics.com"],
            "max_age_days": 2,
            "weekend_grace": True,
            "value_range": [200.0, 10000.0],
            "unit_keywords": ["points"],
        },
    }

    ok, reasons = is_estimated_allowlisted(
        "macro_indicators",
        "bdi",
        {
            "current_value": 1450.0,
            "unit": "points",
            "date": "2026-05-22",
            "source_url": "https://www.tradingeconomics.com/commodity/baltic",
            "is_estimated": True,
        },
        rules=rules,
        report_date="2026-05-25",
    )

    assert ok is True
    assert reasons == []


def test_bdi_allowlist_blocks_friday_value_on_tuesday_without_holiday_grace():
    rules = {
        "estimated_allowlist_keys": ["bdi"],
        "bdi_estimated_allow_conditions": {
            "trusted_domains": ["tradingeconomics.com"],
            "max_age_days": 2,
            "weekend_grace": True,
            "value_range": [200.0, 10000.0],
            "unit_keywords": ["points"],
        },
    }

    ok, reasons = is_estimated_allowlisted(
        "macro_indicators",
        "bdi",
        {
            "current_value": 1450.0,
            "unit": "points",
            "date": "2026-05-22",
            "source_url": "https://www.tradingeconomics.com/commodity/baltic",
            "is_estimated": True,
        },
        rules=rules,
        report_date="2026-05-26",
    )

    assert ok is False
    assert "bdi_date_stale:4d" in reasons


def test_non_blocking_warning_defaults_loaded():
    warning_cfg = get_non_blocking_warning_rules()
    assert "gc_f_risk_domains" in warning_cfg
    assert "gc_f_anomaly_threshold_pct" in warning_cfg
