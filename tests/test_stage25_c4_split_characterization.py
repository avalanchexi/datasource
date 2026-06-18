"""C4 Stage2.5 split characterization.

All tests are offline. Expected values are captured from current monolith
behavior before moving helpers out of ``stage2_5_injector``.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent

COMMON = importlib.import_module("datasource.engines.stage2_5.common")
FF = importlib.import_module("datasource.engines.stage2_5.fund_flow")
SC = importlib.import_module("datasource.engines.stage2_5.schema_coercion")
GS = importlib.import_module("datasource.engines.stage2_5.gap_sync")
MO = importlib.import_module("datasource.engines.stage2_5.manual_official")


C4_MOVED_NAMES = [
    "_extract_domain",
    "_normalize_parseable_http_url",
    "_is_url_evidence_terminator",
    "_collect_http_like_evidence",
    "_extract_embedded_http_url",
    "_iter_http_like_evidence",
    "_extract_source_url",
    "_attach_source_url",
    "_is_https_url_evidence",
    "_extract_domains_from_payload",
    "_extract_domains_from_evidence",
    "_is_placeholder_numeric",
    "_has_valid_value",
    "_coerce_float",
    "_pct_change",
    "_same_numeric_value",
    "_calc_change_rate_pct",
    "_calc_previous_from_change_rate_pct",
    "_coerce_percent",
    "_coerce_bool",
    "_normalize_fund_flow_payload",
    "_default_fund_flow_metric_basis",
    "_normalize_source_tier",
    "_normalize_window_evidence",
    "_domain_matches",
    "_parse_url_domain_path",
    "_path_matches_prefix",
    "_is_fund_flow_tier2_structured_source",
    "_infer_fund_flow_source_tier",
    "_infer_fund_flow_window_evidence",
    "_fund_flow_has_trusted_window",
    "_normalize_fund_flow_estimation",
    "_normalize_keyed_list",
    "_normalize_monetary_payload",
    "_copy_payload_metadata_fields",
    "_copy_source_url",
    "_coerce_stage2_results_to_schema",
    "_collect_missing_source_urls",
    "_remove_missing_item",
    "_remove_top_missing",
    "_remove_top_missing_on_skip",
    "_is_missing_item_filled",
    "_refresh_stage2_gap_monitor",
    "_refresh_stage2_notes",
    "_cleanup_metadata_missing",
    "_append_missing_item",
    "_collect_unresolved_gap_items",
    "_rewrite_gap_monitor_after_injection",
    "_should_preserve_existing_official_source",
    "_normalize_manual_official_key",
    "_iter_url_like_evidence",
    "_iter_explicit_url_evidence",
    "_has_multi_value_explicit_url_evidence",
    "_has_invalid_explicit_url_evidence",
    "_single_trusted_explicit_https_url",
    "_official_domain_matches",
    "_is_manual_official_value",
    "_apply_manual_official_estimation_rule",
    "_is_trusted_monetary_manual_quality_override",
]


def _canonical_namespace() -> SimpleNamespace:
    names = set(C4_MOVED_NAMES)
    names.update({"_apply_pipeline_quality_state", "_has_rrr_type_conflict"})
    namespace = {}
    for module in (COMMON, FF, SC, GS, MO):
        for name in names:
            if hasattr(module, name):
                namespace[name] = getattr(module, name)
    return SimpleNamespace(**namespace)


INJ = _canonical_namespace()


@pytest.mark.parametrize("name", C4_MOVED_NAMES)
def test_c4_canonical_modules_export_moved_names(name):
    assert hasattr(INJ, name)


def test_new_modules_export_moved_names():
    assert hasattr(COMMON, "_coerce_float")
    assert hasattr(FF, "_infer_fund_flow_window_evidence")
    assert hasattr(SC, "_coerce_stage2_results_to_schema")
    assert hasattr(GS, "_rewrite_gap_monitor_after_injection")
    assert hasattr(MO, "_apply_manual_official_estimation_rule")


def test_moved_fn_identity_via_canonical_namespace():
    assert INJ._coerce_float is COMMON._coerce_float
    assert INJ._infer_fund_flow_window_evidence is FF._infer_fund_flow_window_evidence
    assert INJ._coerce_stage2_results_to_schema is SC._coerce_stage2_results_to_schema
    assert INJ._rewrite_gap_monitor_after_injection is GS._rewrite_gap_monitor_after_injection
    assert INJ._apply_manual_official_estimation_rule is MO._apply_manual_official_estimation_rule
    assert INJ._iter_url_like_evidence is COMMON._iter_url_like_evidence
    assert INJ._apply_pipeline_quality_state is COMMON._apply_pipeline_quality_state
    if hasattr(MO, "_has_rrr_type_conflict") and hasattr(INJ, "_has_rrr_type_conflict"):
        assert INJ._has_rrr_type_conflict is MO._has_rrr_type_conflict


def test_extraction_apply_uses_canonical_fund_flow():
    ea = importlib.import_module("datasource.engines.stage2.extraction_apply")
    ex = importlib.import_module("datasource.engines.stage2.execution")

    assert ea._default_fund_flow_metric_basis is FF._default_fund_flow_metric_basis
    assert ea._infer_fund_flow_source_tier is FF._infer_fund_flow_source_tier
    assert ea._infer_fund_flow_window_evidence is FF._infer_fund_flow_window_evidence
    assert ea._normalize_fund_flow_estimation is FF._normalize_fund_flow_estimation
    assert ex._default_fund_flow_metric_basis is FF._default_fund_flow_metric_basis
    assert ex._infer_fund_flow_source_tier is FF._infer_fund_flow_source_tier
    assert ex._infer_fund_flow_window_evidence is FF._infer_fund_flow_window_evidence


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("N/A", None),
        (" 1,234.50% ", 1234.5),
        ("abc", None),
        ("-7.2bp", -7.2),
        (0, 0.0),
        ("0", 0.0),
        ("--", None),
    ],
)
def test_common_coerce_float_locked(value, expected):
    assert INJ._coerce_float(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("N/A", None),
        ("12.5%", 12.5),
        (" 3.0 ", 3.0),
        ("1,234%", None),
        ("abc", None),
    ],
)
def test_common_coerce_percent_locked(value, expected):
    assert INJ._coerce_percent(value) == expected


@pytest.mark.parametrize(
    ("value", "is_placeholder", "has_valid"),
    [
        (None, True, False),
        ("", True, False),
        ("N/A", True, False),
        ("待 WebSearch", True, False),
        ("no_value", True, False),
        ("deepseek_no_value", True, False),
        ("no_deepseek_key", True, False),
        (0, True, False),
        ("0", True, False),
        (7.13, True, False),
        ("7.13", True, False),
    ],
)
def test_common_numeric_placeholder_boundaries_locked(value, is_placeholder, has_valid):
    assert INJ._is_placeholder_numeric(value) is is_placeholder
    assert INJ._has_valid_value(value) is has_valid


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        (110, 100, 10.0),
        (90, -100, 190.0),
        (100, 0, None),
        (None, 100, None),
        (100, None, None),
    ],
)
def test_common_calc_change_rate_pct_locked(current, previous, expected):
    assert INJ._calc_change_rate_pct(current, previous) == expected


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        ("110", "100", 10.0),
        ("90", "-100", 190.0),
        ("100", "0", None),
        ("abc", "100", None),
        ("100", None, None),
    ],
)
def test_common_pct_change_locked(current, previous, expected):
    assert INJ._pct_change(current, previous) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Sub.Example.COM:443/a", "sub.example.com"),
        ("example.com/path", "example.com"),
        ("//www.pbc.gov.cn/a", "www.pbc.gov.cn"),
        ("https://bad:99999/a", ""),
        ("not a url", "not a url"),
    ],
)
def test_common_extract_domain_locked(value, expected):
    assert INJ._extract_domain(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" https://example.com/a ", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com:80/a"),
        ("ftp://example.com/a", None),
        ("https://bad:99999/a", None),
        ("https://exa mple.com/a", None),
        (None, None),
    ],
)
def test_common_normalize_parseable_http_url_locked(value, expected):
    assert INJ._normalize_parseable_http_url(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.com", True),
        ("http://example.com", False),
        ("HTTPS://EXAMPLE.COM", True),
    ],
)
def test_common_is_https_url_evidence_locked(value, expected):
    assert INJ._is_https_url_evidence(value) is expected


@pytest.mark.parametrize(
    ("key", "payload", "expected"),
    [
        ("northbound", {}, "net_flow_sum"),
        ("southbound", {}, "net_flow_sum"),
        ("margin", {}, "balance_delta"),
        ("etf", {}, "net_flow_sum"),
        ("etf", {"is_estimated": True}, "estimated_net_flow"),
        ("other", {}, "net_flow_sum"),
        ("northbound", {"metric_basis": "custom"}, "custom"),
    ],
)
def test_fund_flow_default_metric_basis_locked(key, payload, expected):
    assert INJ._default_fund_flow_metric_basis(key, payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "source_url": (
                    "https://www.hkex.com.hk/Mutual-Market/Stock-Connect/"
                    "Statistics/Historical-Data"
                )
            },
            "tier1",
        ),
        ({"source_url": "https://data.eastmoney.com/hsgt/index.html"}, "tier2"),
        ({"source_url": "https://data.eastmoney.com/etf/x.html"}, "tier2"),
        ({"source_url": "https://data.eastmoney.com/rzrq/detail.html"}, "tier2"),
        ({"source_url": "https://data.eastmoney.com/stockdata/foo"}, "unknown"),
        ({"source_url": "https://finance.sina.com.cn/a.html"}, "tier3"),
    ],
)
def test_fund_flow_infer_source_tier_locked(payload, expected):
    assert INJ._infer_fund_flow_source_tier(payload) == expected


@pytest.mark.parametrize(
    ("key", "payload", "metric_basis", "expected"),
    [
        ("northbound", {"window_evidence": "direct_window"}, "net_flow_sum", "direct_window"),
        (
            "northbound",
            {"window_evidence": "direct_daily_series"},
            "net_flow_sum",
            "direct_daily_series",
        ),
        (
            "margin",
            {"source": "融资余额 balance", "note": "余额"},
            "balance_delta",
            "direct_balance_delta",
        ),
        ("etf", {"note": "季度摘要"}, "net_flow_sum", "news_summary"),
        ("etf", {"note": "近5日与120日窗口"}, "net_flow_sum", "direct_window"),
        ("etf", {}, "estimated_net_flow", "derived"),
        ("etf", {}, "news_net_flow", "news_summary"),
    ],
)
def test_fund_flow_infer_window_evidence_locked(key, payload, metric_basis, expected):
    assert INJ._infer_fund_flow_window_evidence(key, payload, metric_basis) == expected


@pytest.mark.parametrize(
    ("source_tier", "window_evidence", "metric_basis", "expected"),
    [
        ("tier1", "direct_window", "net_flow_sum", True),
        ("tier2", "direct_daily_series", "net_flow_sum", True),
        ("tier2", "direct_balance_delta", "balance_delta", True),
        ("tier3", "direct_window", "net_flow_sum", False),
        ("tier2", "news_summary", "net_flow_sum", False),
        ("tier1", "direct_window", "estimated_net_flow", False),
    ],
)
def test_fund_flow_has_trusted_window_locked(
    source_tier, window_evidence, metric_basis, expected
):
    assert INJ._fund_flow_has_trusted_window(source_tier, window_evidence, metric_basis) is expected


def test_fund_flow_normalize_estimation_clears_trusted_window_locked():
    entry = {
        "source_tier": "tier2",
        "window_evidence": "direct_daily_series",
        "metric_basis": "net_flow_sum",
        "note": "base",
    }

    INJ._normalize_fund_flow_estimation(entry, {})

    assert entry == {
        "source_tier": "tier2",
        "window_evidence": "direct_daily_series",
        "metric_basis": "net_flow_sum",
        "note": "base",
        "is_estimated": False,
    }


def test_fund_flow_normalize_estimation_marks_untrusted_window_locked():
    entry = {
        "source_tier": "tier3",
        "window_evidence": "news_summary",
        "metric_basis": "news_net_flow",
        "note": "base",
    }

    INJ._normalize_fund_flow_estimation(entry, {})

    assert entry == {
        "source_tier": "tier3",
        "window_evidence": "news_summary",
        "metric_basis": "news_net_flow",
        "note": (
            "base；fund_flow_estimated_gate:source_tier=tier3,"
            "window_evidence=news_summary,metric_basis=news_net_flow"
        ),
        "is_estimated": True,
        "estimation_method": "fund_flow_manual_window_not_direct",
    }


def test_schema_coerce_stage2_results_to_schema_locked():
    raw = {
        "results": [
            {
                "task": {"indicator_key": "GC=F", "unit": "$/oz", "query": "gold"},
                "extraction": {
                    "value": "3450.5",
                    "source_url": "https://example.com/gold",
                    "note": "spot",
                },
            },
            {
                "task": {"indicator_key": "USDCNY"},
                "extraction": {
                    "value": "7.123",
                    "daily_change": 0.01,
                    "change_120d": -0.2,
                    "source_url": "https://www.chinamoney.com.cn/x",
                },
            },
            {
                "task": {"indicator_key": "CN10Y_CDB", "unit": "%"},
                "extraction": {
                    "value": "2.123",
                    "is_estimated": True,
                    "estimation_method": "spread",
                    "confidence": 0.7,
                    "source_url": "https://example.com/cdb",
                },
            },
            {
                "task": {"indicator_key": "northbound"},
                "extraction": {
                    "recent_5d": "10.5",
                    "total_120d": "200",
                    "trend": "inflow",
                    "metric_basis": "net_flow_sum",
                    "window_evidence": "direct_daily_series",
                    "source_tier": "tier1",
                    "is_estimated": False,
                    "source_url": "https://www.hkex.com.hk/a",
                },
            },
            {
                "task": {"indicator_key": "reserve_ratio", "unit": "%"},
                "manual_required": True,
                "extraction": {
                    "manual_reason": "missing_compare_values",
                    "source_url": "https://www.pbc.gov.cn/a",
                },
            },
        ]
    }

    schema = INJ._coerce_stage2_results_to_schema(raw)

    assert schema["commodities"] == [
        {
            "symbol": "GC=F",
            "name": "GC=F",
            "current_price": 3450.5,
            "unit": "$/oz",
            "ytd_change": None,
            "trend": "未知",
            "source": "https://example.com/gold",
            "source_url": "https://example.com/gold",
        }
    ]
    assert schema["forex"][0] == {
        "pair": "USDCNY",
        "name": "USDCNY",
        "current_rate": 7.123,
        "daily_change": 0.01,
        "change_120d": -0.2,
        "trend": "未知",
        "source": "https://www.chinamoney.com.cn/x",
        "source_url": "https://www.chinamoney.com.cn/x",
    }
    assert schema["bonds"][0]["is_estimated"] is True
    assert schema["bonds"][0]["estimation_method"] == "spread"
    assert schema["fund_flow"]["northbound"]["is_estimated"] is False
    assert schema["fund_flow"]["northbound"]["metric_basis"] == "net_flow_sum"
    assert schema["metadata"]["manual_required"] == [
        {
            "indicator_key": "reserve_ratio",
            "category": "monetary_policy",
            "reason": "missing_compare_values",
            "source_url": "https://www.pbc.gov.cn/a",
            "query": None,
            "query_used": None,
        }
    ]
    assert schema["monetary_policy"]["reserve_ratio"]["current_value"] is None


def test_schema_normalize_monetary_payload_locked():
    payload = {
        "rrr": {"current_value": None},
        "reserve_ratio": {"current_value": 7.0},
        "mlf": {"current_value": 2.0},
        "unknown": {"current_value": 1},
    }

    assert INJ._normalize_monetary_payload(payload) == {
        "reserve_ratio": {"current_value": 7.0},
        "mlf": {"current_value": 2.0},
        "unknown": {"current_value": 1},
    }


def test_schema_normalize_keyed_list_locked():
    assert INJ._normalize_keyed_list({"a": {"value": 1}, "b": None}, "symbol") == [
        {"value": 1, "symbol": "a"},
        {"symbol": "b"},
    ]
    assert INJ._normalize_keyed_list([{"symbol": "x"}], "symbol") == [{"symbol": "x"}]
    assert INJ._normalize_keyed_list(None, "symbol") == []


def _gap_market_data():
    return {
        "metadata": {
            "date": "2026-04-27",
            "missing_items": {
                "macro_indicators": [{"key": "industrial"}, {"key": "pmi"}]
            },
        },
        "missing_items": ["industrial", {"key": "pmi"}, "keep"],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": 5.0,
                "change_rate": 4.0,
                "is_stale": False,
            },
            "pmi": {"current_value": None},
        },
        "commodities": [
            {"symbol": "GC=F", "current_price": None},
            {"symbol": "CL=F", "current_price": 70},
        ],
        "bonds": [
            {"symbol": "US10Y", "current_yield": "no_value"},
            {"symbol": "CN10Y", "current_yield": 2.0},
        ],
        "fund_flow": {"northbound": {"recent_5d": 1, "total_120d": 2}},
    }


def test_gap_sync_remove_append_and_refresh_locked():
    metadata = {
        "missing_items": {
            "macro_indicators": [{"key": "industrial"}, {"key": "pmi"}],
            "monetary_policy": [{"key": "rrr"}],
        },
        "stage2_notes": ["Stage2: 行情缺口仍存在 old", "keep"],
    }
    INJ._remove_missing_item(metadata, "macro_indicators", "industrial")
    assert metadata == {
        "missing_items": {
            "macro_indicators": [{"key": "pmi"}],
            "monetary_policy": [{"key": "rrr"}],
        },
        "stage2_notes": ["Stage2: 行情缺口仍存在 old", "keep"],
    }

    market_data = _gap_market_data()
    assert INJ._is_missing_item_filled(market_data, "macro_indicators", "industrial")
    assert not INJ._is_missing_item_filled(market_data, "macro_indicators", "pmi")
    assert INJ._is_missing_item_filled(market_data, "fund_flow", "northbound")
    assert INJ._is_missing_item_filled(market_data, "commodities", "CL=F")
    assert not INJ._is_missing_item_filled(market_data, "commodities", "GC=F")

    summary = INJ._refresh_stage2_gap_monitor(market_data)
    INJ._refresh_stage2_notes(market_data["metadata"], summary)
    INJ._cleanup_metadata_missing(market_data["metadata"], market_data)
    INJ._remove_top_missing(market_data, "industrial")
    INJ._append_missing_item(market_data, "forex", "USDCNY", "missing_compare_values")

    assert summary == {"commodities": 1, "bonds": 1}
    assert market_data["metadata"]["stage2_notes"] == [
        "Stage2.5: WebSearch注入完成 (commodities=1, bonds=1)."
    ]
    assert market_data["metadata"]["stage2_gap_monitor"] == {
        "commodities": 1,
        "bonds": 1,
    }
    assert market_data["missing_items"] == [{"key": "pmi"}, "keep", "USDCNY"]
    assert market_data["metadata"]["missing_items"] == {
        "macro_indicators": [{"key": "pmi"}],
        "forex": [{"key": "USDCNY", "reason": "missing_compare_values"}],
    }


def test_gap_sync_rewrite_gap_monitor_after_injection_locked(tmp_path):
    market_data = _gap_market_data()
    INJ._refresh_stage2_gap_monitor(market_data)
    INJ._cleanup_metadata_missing(market_data["metadata"], market_data)
    INJ._remove_top_missing(market_data, "industrial")
    INJ._append_missing_item(market_data, "forex", "USDCNY", "missing_compare_values")
    gap_monitor_path = tmp_path / "gap_monitor.json"

    returned_path = INJ._rewrite_gap_monitor_after_injection(
        market_data,
        date_override="2026-04-27",
        gap_monitor_path=gap_monitor_path,
        extra_issues=[{"category": "x", "key": "y", "reason": "z"}],
    )

    assert returned_path == gap_monitor_path
    payload = json.loads(gap_monitor_path.read_text(encoding="utf-8"))
    assert set(payload) == {
        "generated_at",
        "manual_required",
        "pending_tasks",
        "data_quality_issues",
        "quality_blockers",
    }
    assert payload["manual_required"] == ["pmi", "US10Y", "GC=F"]
    assert payload["pending_tasks"] == ["pmi", "US10Y", "GC=F"]
    assert payload["quality_blockers"] == [
        {"category": "macro_indicators", "key": "pmi", "reason": "primary_value_missing"},
        {"category": "bonds", "key": "US10Y", "reason": "primary_value_missing"},
        {"category": "commodities", "key": "GC=F", "reason": "primary_value_missing"},
    ]
    assert payload["data_quality_issues"][-1] == {
        "category": "x",
        "key": "y",
        "reason": "z",
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "source_url": (
                    "https://www.pbc.gov.cn/goutongjiaoliu/113456/"
                    "113469/index.html"
                )
            },
            "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
        ),
        ({"source_url": "https://www.pbc.gov.cn/a https://www.pbc.gov.cn/b"}, None),
        ({"source_url": "http://www.pbc.gov.cn/a"}, None),
        ({"source_url": "https://www.pbc.gov.cn:99999/a"}, None),
        ({"source_url": "https://pbc.gov.cn.evil.example/a"}, None),
        ({"source_url": "https://www.pbc.gov.cn/a", "note": "see https://evil.example/b"}, None),
    ],
)
def test_manual_official_single_trusted_explicit_https_url_locked(payload, expected):
    assert INJ._single_trusted_explicit_https_url(payload, ("pbc.gov.cn",)) == expected


@pytest.mark.parametrize(
    ("category", "key", "payload", "expected"),
    [
        ("monetary_policy", "mlf", {"source_url": "https://www.pbc.gov.cn/a"}, True),
        ("monetary_policy", "mlf", {"source_url": "https://example.com/a"}, False),
        ("forex", "USDCNY", {"source_url": "https://www.chinamoney.com.cn/a"}, True),
        ("commodities", "BCOM", {"source_url": "https://www.bloomberg.com/quote/BCOM:IND"}, True),
    ],
)
def test_manual_official_value_detection_locked(category, key, payload, expected):
    assert INJ._is_manual_official_value(category, key, payload) is expected


def test_manual_official_apply_estimation_rule_locked():
    entry = {"is_estimated": True, "note": "base"}

    INJ._apply_manual_official_estimation_rule(
        "forex",
        "USDCNY",
        {"source_url": "https://www.chinamoney.com.cn/a"},
        entry,
    )

    assert entry == {
        "is_estimated": False,
        "note": "base；manual_official_not_estimated",
    }

    rejected = {"is_estimated": True, "note": "base"}
    INJ._apply_manual_official_estimation_rule(
        "forex", "USDCNY", {"source_url": "https://example.com/a"}, rejected
    )
    assert rejected == {"is_estimated": True, "note": "base"}


@pytest.mark.parametrize(
    ("entry", "payload", "incoming_value", "is_manual", "expected"),
    [
        (
            {"is_estimated": True, "current_value": 7.0, "note": "估算 fallback"},
            {"current_value": 7.2, "is_estimated": False, "source_url": "https://www.pbc.gov.cn/new"},
            7.2,
            True,
            True,
        ),
        (
            {
                "is_estimated": False,
                "current_value": 7.0,
                "note": "缺少发布机构",
                "change_from_120d": None,
                "source_url": "https://example.com/rrr",
            },
            {"current_value": 7.2, "is_estimated": False, "source_url": "https://www.pbc.gov.cn/new"},
            7.2,
            True,
            True,
        ),
        (
            {
                "is_estimated": False,
                "current_value": 7.0,
                "note": "缺少发布机构",
                "change_from_120d": None,
                "source_url": "https://www.pbc.gov.cn/old",
            },
            {"current_value": 7.2, "is_estimated": False, "source_url": "https://www.pbc.gov.cn/new"},
            7.2,
            True,
            False,
        ),
        (
            {"is_estimated": True, "current_value": 7.0, "note": "估算 fallback"},
            {"current_value": 7.2, "is_estimated": False, "source_url": "https://www.pbc.gov.cn/new"},
            7.2,
            False,
            False,
        ),
        (
            {"is_estimated": True, "current_value": 7.0, "note": "估算 fallback"},
            {"current_value": 7.2, "is_estimated": False, "source_url": "https://www.chinamoney.com.cn/a"},
            7.2,
            True,
            False,
        ),
        (
            {"is_estimated": True, "current_value": 7.0, "note": "估算 fallback"},
            {"current_value": 7.2, "is_estimated": True, "source_url": "https://www.pbc.gov.cn/a"},
            7.2,
            True,
            False,
        ),
    ],
)
def test_manual_official_trusted_monetary_quality_override_locked(
    entry, payload, incoming_value, is_manual, expected
):
    assert (
        INJ._is_trusted_monetary_manual_quality_override(
            "reserve_ratio",
            entry,
            payload,
            incoming_value,
            is_manual=is_manual,
        )
        is expected
    )
