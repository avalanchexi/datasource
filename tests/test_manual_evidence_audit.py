# -*- coding: utf-8 -*-

import pytest

from datasource.utils.manual_evidence_audit import audit_manual_evidence


def _issue(audit, bucket, code, path):
    matches = [
        item
        for item in audit[bucket]
        if item.get("code") == code and item.get("path") == path
    ]
    assert matches, audit
    return matches[0]


def test_manual_audit_flags_source_provider_mismatch_for_bcom():
    audit = audit_manual_evidence(
        {
            "commodities": [
                {
                    "symbol": "BCOM",
                    "name": "Bloomberg Commodity Index",
                    "current_price": 105.4,
                    "source": "Investing.com BCOM quote",
                    "source_url": "https://www.bloomberg.com/quote/BCOM:IND",
                }
            ]
        }
    )

    error = _issue(audit, "errors", "source_provider_mismatch", "commodities.BCOM")
    message = error["message"].lower()
    assert "source mentions investing.com" in message
    assert "www.bloomberg.com" in message


def test_manual_audit_flags_numeric_value_missing_source_url():
    audit = audit_manual_evidence(
        {"macro_indicators": {"industrial": {"current_value": 4.1}}}
    )

    _issue(audit, "errors", "missing_source_url", "macro_indicators.industrial")


@pytest.mark.parametrize(
    "source_url",
    [
        "http://www.pbc.gov.cn/example",
        "https://www.pbc.gov.cn/example https://www.pbc.gov.cn/other",
        "not-a-url",
    ],
)
def test_manual_audit_flags_invalid_source_url(source_url):
    audit = audit_manual_evidence(
        {
            "monetary_policy": {
                "reserve_ratio": {
                    "current_value": 6.8,
                    "source_url": source_url,
                }
            }
        }
    )

    _issue(audit, "errors", "invalid_source_url", "monetary_policy.reserve_ratio")


def test_manual_audit_warns_when_previous_value_lacks_evidence_note():
    audit = audit_manual_evidence(
        {
            "bonds": [
                {
                    "symbol": "US10Y",
                    "current_yield": 4.2,
                    "previous_value": 4.0,
                    "source_url": "https://www.bloomberg.com/markets/rates-bonds",
                }
            ]
        }
    )

    _issue(
        audit,
        "warnings",
        "previous_value_without_evidence_note",
        "bonds.US10Y",
    )
