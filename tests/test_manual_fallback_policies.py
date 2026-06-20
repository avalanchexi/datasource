import importlib.util
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from datasource.engines.stage2_5.manual_official import (
    OFFICIAL_MANUAL_SOURCES,
    TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS,
    _official_domain_matches,
)
from datasource.utils.manual_fallback_policies import (
    NUMERIC_MANUAL_FIELDS,
    load_manual_fallback_policies,
    policy_id,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts/tools/manual_template_from_gap_monitor.py"


def _load_tool_module():
    spec = importlib.util.spec_from_file_location(
        "manual_template_from_gap_monitor", TOOL_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _domain(policy):
    parsed = urlparse(policy["source_url_template"])
    return (parsed.hostname or "").lower()


def test_manual_fallback_policy_config_has_expected_eleven_keys():
    policies = load_manual_fallback_policies()

    assert set(policies) == {
        "bonds:CN10Y_CDB",
        "commodities:BCOM",
        "commodities:GSG",
        "forex:USDCNY",
        "fund_flow:etf",
        "macro_indicators:bdi",
        "macro_indicators:industrial",
        "macro_indicators:industrial_sales",
        "monetary_policy:mlf",
        "monetary_policy:reserve_ratio",
        "monetary_policy:reverse_repo",
    }

    for policy in policies.values():
        assert not NUMERIC_MANUAL_FIELDS.intersection(policy)


def test_manual_fallback_policy_domains_match_official_manual_rules():
    policies = load_manual_fallback_policies()

    for category, category_rules in OFFICIAL_MANUAL_SOURCES.items():
        for key, rule in category_rules.items():
            if not rule:
                continue
            resolved = None
            for candidate in (key, key.upper()):
                resolved = policies.get(policy_id(category, candidate))
                if resolved is not None:
                    break
            assert resolved is not None
            domain = _domain(resolved)
            assert any(
                _official_domain_matches(domain, trusted)
                for trusted in rule["trusted_domains"]
            )

    reserve_policy = policies["monetary_policy:reserve_ratio"]
    assert reserve_policy["is_estimated"] is False
    reserve_domain = _domain(reserve_policy)
    assert any(
        _official_domain_matches(reserve_domain, trusted)
        for trusted in TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS["reserve_ratio"]
    )


def test_manual_fallback_prefill_keeps_numeric_fields_null():
    tool = _load_tool_module()
    gap_payload = {
        "data_quality_issues": [
            {"category": "macro_indicators", "key": "bdi"},
            {"category": "monetary_policy", "key": "rrr"},
            {"category": "commodities", "key": "BCOM"},
        ],
        "pending_tasks": [{"key": "etf"}],
    }
    market_payload = {
        "macro_indicators": {
            "bdi": {
                "indicator_name": "BDI指数",
                "current_value": 2999,
                "unit": "points",
            }
        },
        "monetary_policy": {
            "rrr": {
                "policy_name": "存款准备金率",
                "current_value": 7.0,
                "unit": "%",
            }
        },
        "commodities": [
            {
                "symbol": "BCOM",
                "name": "BCOM指数",
                "current_price": 101.5,
                "unit": "points",
            }
        ],
    }

    template = tool._build_template(
        gap_payload,
        market_payload,
        report_date="2026-06-19",
    )
    tool._apply_policies(template)

    bdi = template["macro_indicators"]["bdi"]
    reserve_ratio = template["monetary_policy"]["rrr"]
    bcom = template["commodities"][0]
    etf = template["fund_flow"]["etf"]

    assert bdi["current_value"] is None
    assert bdi["previous_value"] is None
    assert bdi["change_rate"] is None
    assert bdi["source_url"] == "https://www.investing.com/indices/baltic-dry"
    assert bdi["is_estimated"] is True

    assert reserve_ratio["current_value"] is None
    assert reserve_ratio["change_from_120d"] is None
    assert reserve_ratio["is_estimated"] is False
    assert (
        reserve_ratio["_manual_fallback_policy"]
        == "monetary_policy:reserve_ratio"
    )

    assert bcom["current_price"] is None
    assert bcom["ytd_change"] is None
    assert bcom["is_estimated"] is False
    assert bcom["source_url"] == "https://www.bloomberg.com/quote/BCOM:IND"

    assert etf["recent_5d"] is None
    assert etf["total_120d"] is None
    assert etf["is_estimated"] is True
    assert etf["metric_basis"] == "estimated_net_flow"
    assert etf["window_evidence"] == "news_summary"
    assert etf["source_url"] == "https://data.eastmoney.com/etf/"
    assert "downgraded disclosure" in etf["note"]


def test_stage25_injector_files_untouched_by_manual_fallback_policies():
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--",
            "scripts/stage2_5_injector.py",
            "src/datasource/engines/stage2_5",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.strip() == ""
