from datasource.utils.quality_metrics import build_quality_metrics


def test_quality_metrics_ignores_stale_flag_when_report_period_matches_expected():
    payload = {
        "metadata": {"date": "2026-05-08"},
        "macro_indicators": {
            "pmi_production": {
                "indicator_name": "PMI production",
                "current_value": 51.5,
                "previous_value": 49.6,
                "change_rate": 1.8,
                "unit": "points",
                "date": "2026-03",
                "as_of_date": "2026-04-30",
                "report_period": "2026-04",
                "expected_period": "2026-04",
                "is_stale": True,
                "stale_reason": "actual_period_behind_expected",
            }
        },
        "monetary_policy": {},
    }

    metrics = build_quality_metrics(payload)

    assert metrics["stale_count"] == 0
    assert metrics["stale_items"] == []
    assert metrics["stale_by_category"]["macro_indicators"] == 0
