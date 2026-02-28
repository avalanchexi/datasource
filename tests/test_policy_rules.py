from datasource.utils.policy_rules import evaluate_policy


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
