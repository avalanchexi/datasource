import json
import runpy
from pathlib import Path

import pytest


stage4 = runpy.run_path(
    Path(__file__).resolve().parents[1] / "scripts" / "stage4_risk_review.py",
    run_name="stage4_risk_review_test",
)


def _build_review(payload, **kwargs):
    return stage4["build_review"](payload, **kwargs)


def _findings(review, severity):
    return review["findings"][severity]


def _codes(review, severity):
    return {finding["code"] for finding in _findings(review, severity)}


def _has_finding(review, severity, key, code):
    return any(
        finding["key"] == key and finding["code"] == code
        for finding in _findings(review, severity)
    )


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_bcom_total_return_scope_is_blocker():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "commodities": {
            "BCOM": {
                "symbol": "BCOM",
                "name": "Bloomberg Commodity Total Return Index",
                "current_value": 102.4,
                "source_url": "https://example.com/bcomtr",
            }
        },
    }

    review = _build_review(payload)

    assert _has_finding(
        review,
        "blocker",
        "commodities.BCOM",
        "bcom_scope_mismatch",
    )


def test_bcom_single_commodity_scope_is_blocker():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "commodities": {
            "BCOM": {
                "symbol": "BCOM",
                "name": "Bloomberg Gold Commodity Index",
                "current_value": 88.2,
                "source_url": "https://example.com/markets/bloomberg-gold",
            }
        },
    }

    review = _build_review(payload)

    assert _has_finding(
        review,
        "blocker",
        "commodities.BCOM",
        "bcom_scope_mismatch",
    )


def test_bcom_plain_bloomberg_commodity_index_still_review_required():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "commodities": {
            "BCOM": {
                "symbol": "BCOM",
                "name": "Bloomberg Commodity Index",
                "current_value": 104.8,
                "source_url": "https://example.com/bcom",
            }
        },
    }

    review = _build_review(payload)

    assert _has_finding(
        review,
        "review_required",
        "commodities.BCOM",
        "bcom_plain_index_review",
    )
    assert not _findings(review, "blocker")


def test_cn10y_cdb_estimated_without_explicit_basis_is_review_required():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "bonds": {
            "CN10Y_CDB": {
                "symbol": "CN10Y_CDB",
                "current_yield": 2.18,
                "is_estimated": True,
                "estimation_method": "proxy estimate",
                "source_url": "https://example.com/cn10y-cdb",
            }
        },
    }

    review = _build_review(payload)

    assert _has_finding(
        review,
        "review_required",
        "bonds.CN10Y_CDB",
        "cn10y_cdb_estimate_missing_basis",
    )


def test_cn10y_cdb_estimated_with_explicit_spread_basis_info():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "bonds": {
            "CN10Y_CDB": {
                "symbol": "CN10Y_CDB",
                "current_yield": 2.18,
                "is_estimated": True,
                "estimation_method": "CN10Y plus observed CDB spread 22bp",
                "source_url": "https://example.com/cn10y-cdb",
            }
        },
    }

    review = _build_review(payload)

    assert _has_finding(
        review,
        "info",
        "bonds.CN10Y_CDB",
        "cn10y_cdb_estimate_disclosed",
    )
    assert "cn10y_cdb_estimate_missing_basis" not in _codes(review, "review_required")


def test_fund_flow_estimated_news_basis_with_allow_downgrade_is_review_required():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "fund_flow": {
            "etf": {
                "recent_5d": 12.3,
                "total_120d": 456.7,
                "is_estimated": True,
                "metric_basis": "news_net_flow",
                "window_evidence": "news_summary",
                "source_url": "https://example.com/etf-flow",
            }
        },
    }

    review = _build_review(payload, allow_fund_flow_downgrade=True)

    assert _has_finding(
        review,
        "review_required",
        "fund_flow.etf",
        "fund_flow_downgrade_review",
    )


def test_fund_flow_direct_window_non_estimated_does_not_produce_fund_flow_finding():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "fund_flow": {
            "northbound": {
                "recent_5d": 12.3,
                "total_120d": 456.7,
                "is_estimated": False,
                "metric_basis": "net_flow_sum",
                "window_evidence": "direct_window",
                "source_url": "https://example.com/northbound-flow",
            }
        },
    }

    review = _build_review(payload)

    fund_flow_findings = [
        finding
        for severity in ("blocker", "review_required", "info")
        for finding in _findings(review, severity)
        if finding["key"].startswith("fund_flow.")
    ]
    assert fund_flow_findings == []


def test_fund_flow_estimated_news_basis_without_downgrade_uses_estimate_review_code():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "fund_flow": {
            "southbound": {
                "recent_5d": 12.3,
                "total_120d": 456.7,
                "is_estimated": True,
                "metric_basis": "news_net_flow",
                "window_evidence": "news_summary",
                "source_url": "https://example.com/southbound-flow",
            }
        },
    }

    review = _build_review(payload, allow_fund_flow_downgrade=False)

    assert _has_finding(
        review,
        "review_required",
        "fund_flow.southbound",
        "fund_flow_estimate_review",
    )
    assert "fund_flow_downgrade_review" not in _codes(review, "review_required")


@pytest.mark.parametrize(
    ("item_updates", "case_name"),
    [
        ({"is_estimated": True}, "estimated_flag_only"),
        ({"metric_basis": "estimated_net_flow"}, "estimated_metric_basis"),
        ({"window_evidence": "news_summary"}, "weak_window_evidence"),
        ({"window_evidence": ""}, "missing_window_evidence"),
    ],
)
def test_fund_flow_independent_risk_triggers_are_review_required(
    item_updates,
    case_name,
):
    base_item = {
        "recent_5d": 12.3,
        "total_120d": 456.7,
        "is_estimated": False,
        "metric_basis": "net_flow_sum",
        "window_evidence": "direct_window",
        "source_url": "https://example.com/fund-flow",
    }
    base_item.update(item_updates)
    payload = {
        "metadata": {"date": "2026-05-28"},
        "fund_flow": {case_name: base_item},
    }

    review = _build_review(payload)

    assert _has_finding(
        review,
        "review_required",
        f"fund_flow.{case_name}",
        "fund_flow_estimate_review",
    )


def test_critical_numeric_item_without_source_url_is_blocker():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "forex": {
            "USDCNY": {
                "pair": "USDCNY",
                "current_rate": 7.12,
            }
        },
    }

    review = _build_review(payload)

    assert _has_finding(
        review,
        "blocker",
        "forex.USDCNY",
        "missing_source_url",
    )


@pytest.mark.parametrize(
    "source_url",
    [
        "https://example.com/a,https://b.com",
        "https://example.com/path（官方公告）",
        "https://example.com/path|official",
    ],
)
def test_malformed_source_url_is_invalid_evidence_and_triggers_missing_source_url(source_url):
    payload = {
        "metadata": {"date": "2026-05-28"},
        "macro_indicators": {
            "bdi": {
                "current_value": 1388.0,
                "source_url": source_url,
            }
        },
    }

    review = _build_review(payload)

    assert _has_finding(
        review,
        "blocker",
        "macro_indicators.bdi",
        "missing_source_url",
    )


def test_url_alias_is_valid_source_evidence():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "macro_indicators": {
            "bdi": {
                "current_value": 1388.0,
                "url": "https://example.com/value",
            }
        },
    }

    review = _build_review(payload)

    assert "missing_source_url" not in _codes(review, "blocker")
    assert "missing_source_url" not in _codes(review, "review_required")


def test_monetary_policy_rrr_numeric_value_without_source_evidence_is_blocker():
    payload = {
        "metadata": {"date": "2026-05-28"},
        "monetary_policy": {
            "rrr": {
                "current_value": 6.2,
            }
        },
    }

    review = _build_review(payload)

    assert _has_finding(
        review,
        "blocker",
        "monetary_policy.rrr",
        "missing_source_url",
    )


def test_cli_writes_review_json_for_synthetic_market_file(tmp_path, monkeypatch):
    market_path = tmp_path / "synthetic_market.json"
    output_path = tmp_path / "review.json"
    _write_json(
        market_path,
        {
            "metadata": {"date": "2026-05-28"},
            "forex": {"USDCNY": {"pair": "USDCNY", "current_rate": 7.12}},
        },
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_risk_review.py",
            "--market-data",
            str(market_path),
            "--output",
            str(output_path),
        ],
    )

    stage4["main"]()

    review = json.loads(output_path.read_text(encoding="utf-8"))
    assert review["metadata"]["date"] == "2026-05-28"
    assert review["metadata"]["gap_monitor_present"] is False
    assert review["metadata"]["quality_metrics_present"] is False
    assert review["metadata"]["missing_optional_files"] == [
        "data/runs/20260528/gap_monitor.json",
        "data/runs/20260528/quality_metrics.json",
    ]
    assert _has_finding(review, "blocker", "forex.USDCNY", "missing_source_url")


def test_cli_missing_explicit_market_data_file_reports_required_path(
    tmp_path,
    monkeypatch,
):
    market_path = tmp_path / "missing_market_data.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_risk_review.py",
            "--market-data",
            str(market_path),
            "--output",
            str(tmp_path / "review.json"),
        ],
    )

    with pytest.raises(FileNotFoundError) as exc:
        stage4["main"]()

    message = str(exc.value)
    assert "required market data input not found" in message
    assert str(market_path) in message


def test_cli_malformed_required_market_data_json_reports_path_context(
    tmp_path,
    monkeypatch,
):
    market_path = tmp_path / "bad_market_data.json"
    market_path.write_text('{"metadata": ', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_risk_review.py",
            "--market-data",
            str(market_path),
            "--output",
            str(tmp_path / "review.json"),
        ],
    )

    with pytest.raises(ValueError) as exc:
        stage4["main"]()

    message = str(exc.value)
    assert f"failed to load JSON {market_path}" in message


def test_explicit_market_data_without_path_date_uses_payload_date_for_default_output(
    tmp_path,
    monkeypatch,
):
    market_path = tmp_path / "synthetic_market.json"
    _write_json(
        market_path,
        {
            "metadata": {"date": "2026-04-30"},
            "macro_indicators": {
                "bdi": {
                    "current_value": 1400.0,
                    "source_url": "https://example.com/bdi",
                }
            },
        },
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_risk_review.py",
            "--market-data",
            str(market_path),
        ],
    )

    stage4["main"]()

    output_path = tmp_path / "data" / "runs" / "20260430" / "stage4_risk_review.json"
    review = json.loads(output_path.read_text(encoding="utf-8"))
    assert review["metadata"]["date"] == "2026-04-30"


def test_explicit_market_data_without_path_or_payload_date_requires_output(
    tmp_path,
    monkeypatch,
):
    market_path = tmp_path / "synthetic_market.json"
    _write_json(market_path, {"metadata": {}, "forex": {}})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_risk_review.py",
            "--market-data",
            str(market_path),
        ],
    )

    with pytest.raises(ValueError) as exc:
        stage4["main"]()

    assert "cannot infer run date for explicit --market-data" in str(exc.value)
