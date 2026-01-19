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
