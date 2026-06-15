"""C2 characterization tests for Stage2 helper moves.

These tests lock current monolith behavior before C2 moves helpers into
``datasource.engines.stage2`` modules. Expected values are taken from the
current ``stage2_unified_enhancer`` implementation.
"""

from __future__ import annotations

import importlib
import sys
from datetime import timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

ENH = importlib.import_module("stage2_unified_enhancer")
COMMON = importlib.import_module("datasource.engines.stage2.common")
CLI = importlib.import_module("datasource.engines.stage2.cli")
QUERY_PLANNER = importlib.import_module("datasource.engines.stage2.query_planner")
STRUCTURED_RUNNER = importlib.import_module(
    "datasource.engines.stage2.structured_runner"
)
DIAGNOSTICS = importlib.import_module("datasource.engines.stage2.diagnostics")
VALIDATION = importlib.import_module("datasource.engines.stage2.validation")
EXTRACTION_APPLY = importlib.import_module(
    "datasource.engines.stage2.extraction_apply"
)


C2_MOVED_NAMES = [
    "_safe_number",
    "_RANGE_RULES",
    "_FOREX_UPSERT_META",
    "_COMMODITY_UPSERT_META",
    "_BOND_UPSERT_META",
    "_is_force_refresh_task",
    "_entry_for_task",
    "_env_int_default",
    "_env_float_default",
    "_parse_args",
    "_should_enable_exa_fallback",
    "_should_initialize_exa_client",
    "_build_structured_registry_for_args",
    "_is_exa_sdk_available",
    "_load_tasks_from_file",
    "_ensure_keys",
    "_callable_supports_kwarg",
    "_select_proxy_for_url",
    "_validate_proxies",
    "_parse_task_filter",
    "_candidate_query_quality",
    "_exa_search_type",
    "_start_date_from_max_age",
    "_dedupe_candidate_queries",
    "_expand_query_candidates",
    "_build_directed_query",
    "_should_retry_with_directed_query",
    "_structured_stats",
    "_structured_key_stats",
    "_record_structured_attempt",
    "_record_structured_latency_by_provider",
    "_record_structured_success",
    "_record_structured_fallback",
    "_mark_structured_fallback_on_task",
    "_finalize_task_result_type",
    "_finalize_websearch_result_type",
    "_post_writeback_manual_reason",
    "_post_writeback_missing_category",
    "_mark_post_writeback_manual_required",
    "_missing_required_output_fields",
    "_nested_row_value",
    "_build_retrieval_diagnostics",
    "_manual_failure_layer",
    "_build_manual_required_details",
    "_has_diagnostic_value",
    "_merge_nested_diagnostic_dict",
    "_merge_diagnostic_row",
    "_diagnostic_rows_for_summary",
    "_stage2_effective_hit_rate",
    "_stage2_summary_metric_fields",
    "_build_stage2_result_count_fields",
    "_format_stage2_task_count_line",
    "_format_stage2_hit_rate_line",
    "_structured_provider_summary_fields",
    "_build_stage2_summary_diagnostics",
    "_detect_fund_flow_suspicious_reason",
    "_flag_fund_flow_anomalies",
    "_validate_fund_flow_extraction",
    "_validate_general_extraction",
    "_infer_report_period",
    "_infer_as_of_date",
    "_augment_extraction_metadata",
    "_scrub_unevidenced_forex_zeroes",
    "_copy_forex_compare_fields",
    "_apply_extraction",
]


C2_MODULE_EXPORTS = {
    COMMON: [
        "_safe_number",
        "_RANGE_RULES",
        "_FOREX_UPSERT_META",
        "_COMMODITY_UPSERT_META",
        "_BOND_UPSERT_META",
        "_is_force_refresh_task",
        "_entry_for_task",
    ],
    CLI: [
        "_env_int_default",
        "_env_float_default",
        "_parse_args",
        "_should_enable_exa_fallback",
        "_should_initialize_exa_client",
        "_build_structured_registry_for_args",
        "_is_exa_sdk_available",
        "_load_tasks_from_file",
        "_ensure_keys",
        "_callable_supports_kwarg",
        "_select_proxy_for_url",
        "_validate_proxies",
        "_parse_task_filter",
    ],
    QUERY_PLANNER: [
        "_candidate_query_quality",
        "_exa_search_type",
        "_start_date_from_max_age",
        "_dedupe_candidate_queries",
        "_expand_query_candidates",
        "_build_directed_query",
        "_should_retry_with_directed_query",
    ],
    STRUCTURED_RUNNER: [
        "_structured_stats",
        "_structured_key_stats",
        "_record_structured_attempt",
        "_record_structured_latency_by_provider",
        "_record_structured_success",
        "_record_structured_fallback",
        "_mark_structured_fallback_on_task",
    ],
    DIAGNOSTICS: [
        "_finalize_task_result_type",
        "_finalize_websearch_result_type",
        "_post_writeback_manual_reason",
        "_post_writeback_missing_category",
        "_mark_post_writeback_manual_required",
        "_missing_required_output_fields",
        "_nested_row_value",
        "_build_retrieval_diagnostics",
        "_manual_failure_layer",
        "_build_manual_required_details",
        "_has_diagnostic_value",
        "_merge_nested_diagnostic_dict",
        "_merge_diagnostic_row",
        "_diagnostic_rows_for_summary",
        "_stage2_effective_hit_rate",
        "_stage2_summary_metric_fields",
        "_build_stage2_result_count_fields",
        "_format_stage2_task_count_line",
        "_format_stage2_hit_rate_line",
        "_structured_provider_summary_fields",
        "_build_stage2_summary_diagnostics",
        "_STAGE2_BACKEND_SUMMARY_KEYS",
    ],
    VALIDATION: [
        "_detect_fund_flow_suspicious_reason",
        "_flag_fund_flow_anomalies",
        "_validate_fund_flow_extraction",
        "_validate_general_extraction",
        "_FUND_FLOW_BOUNDS",
    ],
    EXTRACTION_APPLY: [
        "_contains_ytd_marker",
        "_infer_report_period",
        "_infer_as_of_date",
        "_augment_extraction_metadata",
        "_join_forex_compare_evidence_text",
        "_normalize_forex_compare_text",
        "_has_forex_positive_compare_text",
        "_has_forex_no_change_evidence",
        "_is_forex_no_change_absence_text",
        "_is_forex_absence_text",
        "_is_forex_compare_absence_text",
        "_is_valid_forex_compare_source_url",
        "_is_valid_forex_compare_base_date",
        "_is_valid_forex_compare_base_price",
        "_has_forex_computed_marker",
        "_has_forex_field_specific_evidence",
        "_has_forex_structured_compare_evidence",
        "_has_negative_forex_compare_marker",
        "_has_forex_compare_evidence",
        "_scrub_unevidenced_forex_zeroes",
        "_copy_forex_compare_fields",
        "_apply_extraction",
    ],
}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12.5", 12.5),
        ("1,234.5", None),
        ("  7.1 ", 7.1),
        ("abc", None),
        (None, None),
        ("", None),
        ("1.0%", None),
    ],
)
def test_safe_number_locked(raw, expected):
    assert ENH._safe_number(raw) == expected


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ({"force_refresh": True}, True),
        ({"force_refresh": False}, False),
        ({"trigger_reason": "quality_gap"}, False),
        ({"trigger_reason": "stale_data"}, True),
        ({}, False),
    ],
)
def test_is_force_refresh_task_locked(task, expected):
    assert ENH._is_force_refresh_task(task) is expected


def _entry_market_payload():
    return {
        "macro_indicators": {"gdp": {"current_value": 5.0}},
        "monetary_policy": {"reserve_ratio": {"current_value": 7.0}},
        "forex": [{"pair": "USDCNY", "current_rate": 7.2}],
        "commodities": [{"symbol": "GC=F", "current_price": 2300}],
        "bonds": [{"symbol": "US10Y", "current_yield": 4.2}],
        "fund_flow": {"northbound": {"recent_5d": 1.0}},
    }


@pytest.mark.parametrize(
    ("task", "indicator_key", "expected_category", "expected_marker"),
    [
        ({"category": "macro_indicators"}, "gdp", "macro_indicators", 5.0),
        ({"category": "monetary_policy"}, "rrr", "monetary_policy", 7.0),
        ({"category": "forex"}, "USDCNY", "forex", 7.2),
        ({"category": "commodities"}, "GC=F", "commodities", 2300),
        ({"category": "bonds"}, "US10Y", "bonds", 4.2),
        ({"category": "fund_flow"}, "northbound", "fund_flow", 1.0),
        ({}, "DXY", None, None),
    ],
)
def test_entry_for_task_locked(
    task, indicator_key, expected_category, expected_marker
):
    category, entry = ENH._entry_for_task(
        _entry_market_payload(), task, indicator_key
    )
    assert category == expected_category
    if expected_category is None:
        assert entry is None
    else:
        assert expected_marker in set(entry.values())


def test_cli_helpers_locked(monkeypatch):
    monkeypatch.delenv("C2_INT", raising=False)
    monkeypatch.delenv("C2_FLOAT", raising=False)
    assert ENH._env_int_default("C2_INT", 3) == 3
    assert ENH._env_float_default("C2_FLOAT", 1.5) == 1.5

    monkeypatch.setenv("C2_INT", "42")
    monkeypatch.setenv("C2_FLOAT", "2.25")
    assert ENH._env_int_default("C2_INT", 3) == 42
    assert ENH._env_float_default("C2_FLOAT", 1.5) == 2.25

    monkeypatch.setenv("C2_INT", "bad")
    monkeypatch.setenv("C2_FLOAT", "bad")
    assert ENH._env_int_default("C2_INT", 3) == 3
    assert ENH._env_float_default("C2_FLOAT", 1.5) == 1.5

    assert ENH._parse_task_filter(None) == ([], [])
    assert ENH._parse_task_filter(
        "abc, 123456789012345678901234567890-1, DXY"
    ) == (["123456789012345678901234567890-1"], ["abc", "DXY"])

    assert (
        ENH._select_proxy_for_url(
            {"https": "https://p"}, "https://api.example.com"
        )
        == "https://p"
    )
    assert (
        ENH._select_proxy_for_url({"http://": "http://p"}, "http://x")
        == "http://p"
    )
    assert (
        ENH._select_proxy_for_url({"only": "socks://p"}, "https://x")
        == "socks://p"
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["stage2_unified_enhancer.py", "--market-data", "market.json"],
    )
    args = ENH._parse_args()
    assert {
        "market_data": args.market_data,
        "phase": args.phase,
        "search_backend": args.search_backend,
        "execute_search": args.execute_search,
        "cache_ttl": args.cache_ttl,
        "use_queue": args.use_queue,
        "disable_structured_providers": args.disable_structured_providers,
        "enable_exa_fallback": args.enable_exa_fallback,
    } == {
        "market_data": "market.json",
        "phase": "all",
        "search_backend": "tavily",
        "execute_search": False,
        "cache_ttl": 3600,
        "use_queue": True,
        "disable_structured_providers": False,
        "enable_exa_fallback": False,
    }


def test_validate_proxies_locked(monkeypatch):
    class Response:
        status_code = 200

    class FakeHttpx:
        @staticmethod
        def get(url, proxies=None, timeout=None):
            return Response()

    class FailingHttpx:
        @staticmethod
        def get(url, proxies=None, timeout=None):
            raise RuntimeError("proxy down")

    proxies = {"https": "https://proxy"}
    monkeypatch.setitem(ENH._validate_proxies.__globals__, "httpx", FakeHttpx)
    assert ENH._validate_proxies(proxies) == proxies
    monkeypatch.setitem(
        ENH._validate_proxies.__globals__, "httpx", FailingHttpx
    )
    assert ENH._validate_proxies(proxies) is None


def test_query_planner_helpers_locked(monkeypatch):
    class FixedDatetime(ENH.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return cls(2026, 6, 15, tzinfo=timezone.utc)
            return cls(2026, 6, 15)

    monkeypatch.setitem(
        ENH._start_date_from_max_age.__globals__, "datetime", FixedDatetime
    )
    assert ENH._start_date_from_max_age(None) is None
    assert ENH._start_date_from_max_age(5) == "2026-06-10"
    assert ENH._exa_search_type("GC=F") == "keyword"
    assert ENH._exa_search_type("northbound") is None
    assert ENH._dedupe_candidate_queries(
        [
            {"query": " q ", "field_scope": "a"},
            {"query": "q", "field_scope": "a"},
            {"query": "q", "field_scope": "b"},
            {"query": "", "field_scope": "x"},
        ]
    ) == [
        {"query": " q ", "field_scope": "a"},
        {"query": "q", "field_scope": "b"},
    ]

    task = {
        "query": "base query",
        "indicator_key": "gdp",
        "unit": "%",
        "issuer": "NBS",
        "field_queries": {
            "recent_5d": ["recent query"],
            "total_120d": ["total query"],
        },
        "expected_period_tokens": ["2026年5月"],
    }
    assert (
        ENH._build_directed_query(
            task, {"manual_reason": "recent_5d missing"}, None, None
        )
        == "recent query"
    )
    assert (
        ENH._should_retry_with_directed_query(
            {"manual_reason": "low_score_all"},
            None,
            None,
            attempt=1,
            max_retries=1,
            directed_retry_done=False,
        )
        is True
    )
    assert (
        ENH._should_retry_with_directed_query(
            {"manual_reason": "low_score_all"},
            None,
            None,
            attempt=2,
            max_retries=1,
            directed_retry_done=False,
        )
        is False
    )
    assert (
        ENH._should_retry_with_directed_query(
            {"manual_reason": "low_score_all"},
            None,
            None,
            attempt=1,
            max_retries=1,
            directed_retry_done=True,
        )
        is False
    )


def test_query_quality_and_expansion_locked():
    quality = ENH._candidate_query_quality(
        {
            "indicator_key": "gdp",
            "preferred_domains": ["stats.gov.cn"],
            "required_keywords": ["GDP"],
            "issuer": "NBS",
            "expected_period_tokens": ["2026年5月"],
            "evidence_keywords": ["同比"],
            "required_output_fields": ["current_value"],
        },
        {
            "query": "GDP query",
            "preferred_domains": ["stats.gov.cn"],
            "good_url_patterns": ["stats.gov.cn"],
            "evidence_keywords": ["同比"],
        },
        [
            {
                "title": "NBS GDP",
                "snippet": "2026年5月 GDP 同比 5.1% NBS",
                "content": "",
                "url": "https://stats.gov.cn/a",
                "score": 0.9,
                "published_date": "2026-06-01",
            }
        ],
    )
    assert len(quality.pop("snippets")) == 1
    assert quality == {
        "trusted_count": 1,
        "usable_count": 1,
        "issuer_hit": True,
        "period_hit": True,
        "score_stats": {
            "score_count": 1,
            "score_max": 0.9,
            "score_min": 0.9,
            "score_p50": 0.9,
            "score_p95": 0.9,
        },
        "quality_score": 273.0,
        "usage_evidence_score": 1,
        "value_evidence_score": 4,
        "good_url_hit_count": 1,
        "bad_url_hit_count": 0,
        "unusable_reason": None,
        "selected_reason": (
            "trusted=1 usable=1 issuer_hit=True period_hit=True "
            "usage_evidence=1 "
            "value_evidence=4 good_url=1 bad_url=0 score_max=0.9"
        ),
    }

    assert ENH._expand_query_candidates(
        {
            "indicator_key": "gdp",
            "query": "primary",
            "queries": ["alt"],
            "query_families": [
                {
                    "name": "fam",
                    "queries": ["famq"],
                    "field_scope": "x",
                    "required_keywords": ["kw"],
                }
            ],
            "field_queries": {"recent_5d": ["recent q"]},
            "preferred_domains": ["d"],
            "max_query_candidates": 1,
        },
        field_scopes=["recent_5d"],
    ) == [
        {
            "query": "famq",
            "family": "fam",
            "field_scope": "x",
            "preferred_domains": ["d"],
            "exclude_domains": [],
            "required_keywords": ["kw"],
            "exclude_keywords": [],
            "time_range": None,
            "topic": None,
            "max_results": None,
            "search_depth": None,
            "days": None,
            "chunks_per_source": None,
            "auto_parameters": None,
        },
        {
            "query": "recent q",
            "family": "field:recent_5d",
            "field_scope": "recent_5d",
            "preferred_domains": ["d"],
            "exclude_domains": [],
            "required_keywords": [],
            "exclude_keywords": [],
            "time_range": None,
            "topic": None,
            "max_results": None,
            "search_depth": None,
            "days": None,
            "chunks_per_source": None,
            "auto_parameters": None,
        },
    ]


def test_structured_runner_stats_locked():
    stats = {}
    ENH._record_structured_attempt(stats, "DXY")
    ENH._record_structured_success(stats, "DXY", 12, "prov")
    ENH._record_structured_fallback(stats, "USDCNY", "no_data", 5, "prov")
    assert stats == {
        "structured_attempt": 1,
        "structured_success": 1,
        "structured_fallback": 1,
        "structured_provider": {
            "attempt": 1,
            "success": 1,
            "fallback": 1,
            "by_key": {
                "DXY": {"attempt": 1, "success": 1, "fallback": 0},
                "USDCNY": {
                    "attempt": 0,
                    "success": 0,
                    "fallback": 1,
                    "last_fallback_reason": "no_data",
                },
            },
            "error_breakdown": {"no_data": 1},
            "latency_ms": [12, 5],
            "latency_ms_by_provider": {"prov": [12, 5]},
        },
    }

    task = {}
    ENH._mark_structured_fallback_on_task(
        task,
        reason="policy",
        latency_ms=7,
        diagnostics={"x": 1},
        provider_name="prov",
    )
    assert task == {
        "structured_provider_attempted": True,
        "structured_provider_fallback_reason": "policy",
        "structured_provider_latency_ms": 7,
        "structured_provider_diagnostics": {"x": 1},
        "structured_provider_name": "prov",
    }


def test_diagnostics_helpers_locked():
    rows = [
        {
            "task_id": "1",
            "indicator_key": "A",
            "usable_count_before_extract": 2,
            "manual_required": True,
            "manual_reason": "x",
            "result_type": "manual_required",
        },
        {
            "task_id": "2",
            "indicator_key": "B",
            "usable_count_before_extract": 1,
            "manual_required": False,
            "result_type": "search_success",
        },
    ]
    assert ENH._build_retrieval_diagnostics(rows) == {
        "retrieval_task_count": 2,
        "retrieval_hit_count": 2,
        "retrieval_hit_rate": 1.0,
        "retrieval_hit_extract_failed": 1,
        "extract_success_rate": 0.5,
        "writeback_success_count": 1,
        "writeback_success_rate": 0.5,
        "manual_reason_breakdown": {"x": 1},
    }
    assert ENH._manual_failure_layer(rows[0]) == "extraction"
    assert (
        ENH._manual_failure_layer(
            {
                "structured_provider_fallback_reason": "provider_error",
                "manual_required": True,
            }
        )
        == "structured_provider"
    )
    assert ENH._build_manual_required_details(rows) == [
        {
            "key": "A",
            "failure_layer": "extraction",
            "reason": "x",
            "structured_provider_fallback_reason": None,
            "usable_count_before_extract": 2,
            "result_type": "manual_required",
        }
    ]
    assert ENH._stage2_effective_hit_rate(3, 1) == 0.75
    assert ENH._stage2_effective_hit_rate(0, 0) == 0.0
    assert [
        ENH._finalize_task_result_type({"note": "skip_existing_value"}),
        ENH._finalize_task_result_type({"manual_required": True}),
        ENH._finalize_task_result_type({}),
        ENH._finalize_websearch_result_type(
            {"extraction": {"note": "existing_value"}}
        ),
    ] == [
        "skipped_existing",
        "manual_required",
        "search_success",
        "skipped_existing",
    ]
    assert ENH._missing_required_output_fields(
        {"current_value": "abc", "source": "", "date": "2026-01-01"},
        ["current_value", "source", "date"],
    ) == ["current_value", "source"]


def test_validation_fund_flow_locked():
    assert [
        ENH._detect_fund_flow_suspicious_reason("northbound", 100.0, 100.0),
        ENH._detect_fund_flow_suspicious_reason("northbound", 120.0, 120.0),
        ENH._detect_fund_flow_suspicious_reason("northbound", 9999.0, 1.0),
        ENH._detect_fund_flow_suspicious_reason("northbound", 1.0, 2.0),
    ] == [
        "疑似占位值(100/100)",
        "近5日与120日完全相等且偏小",
        "recent_5d超出经验区间(-500.0~500.0)",
        None,
    ]
    payload = {
        "fund_flow": {
            "northbound": {"recent_5d": 100, "total_120d": 100},
            "southbound": {"recent_5d": 1, "total_120d": 2, "source": "mcp"},
        }
    }
    assert ENH._flag_fund_flow_anomalies(payload) == ["northbound"]
    assert payload == {
        "fund_flow": {
            "northbound": {
                "recent_5d": 100,
                "total_120d": 100,
                "source": "异常零值-需核查",
                "note": "异常零值-需核查 疑似占位值(100/100)",
                "manual_required": True,
            },
            "southbound": {
                "recent_5d": 1,
                "total_120d": 2,
                "source": "tavily+deepseek",
                "note": "legacy_source_normalized:mcp->tavily",
            },
        }
    }
    assert [
        ENH._validate_fund_flow_extraction(
            {"value": 10, "unit": "亿元", "note": "净流入"}, "northbound"
        ),
        ENH._validate_fund_flow_extraction(
            {"value": 10, "unit": "元", "note": "净流入"}, "northbound"
        ),
        ENH._validate_fund_flow_extraction(
            {"value": 100, "unit": "亿元", "note": "净流入"}, "northbound"
        ),
        ENH._validate_fund_flow_extraction({"value": None}, "northbound"),
    ] == [
        (10.0, False, ""),
        (10.0, True, "单位缺失(需含亿)"),
        (100.0, True, "疑似占位值(100)"),
        (None, True, "no_value"),
    ]


def test_validate_general_extraction_locked():
    assert ENH._validate_general_extraction(
        {
            "value": 1,
            "unit": "%",
            "source_url": "https://stats.gov.cn/x",
            "issuer_match": True,
        },
        {
            "indicator_key": "gdp",
            "unit": "%",
            "preferred_domains": ["stats.gov.cn"],
            "issuer": "NBS",
        },
        [{"content": "NBS data"}],
    ) == (1, False, "")
    assert ENH._validate_general_extraction(
        {"value": None, "unit": "pts", "source_url": "https://bad.com/"},
        {
            "indicator_key": "gdp",
            "unit": "%",
            "preferred_domains": ["stats.gov.cn"],
            "issuer": "NBS",
        },
        [],
    ) == (None, True, "no_value 单位不匹配(需含%) 域名不在白名单 缺少发布机构(NBS)")


def test_extraction_metadata_and_forex_helpers_locked():
    assert ENH._infer_report_period("2026年5月工业增加值") == "2026-05"
    assert (
        ENH._infer_as_of_date(
            [{"published_date": "2026-06-01"}, {"date": "2026-06-03"}]
        )
        == "2026-06-03"
    )
    extraction = {}
    ENH._augment_extraction_metadata(
        extraction,
        {"indicator_key": "industrial"},
        [
            {
                "title": "",
                "snippet": "2026年5月规模以上工业增加值累计同比增长",
                "content": "",
            }
        ],
    )
    assert extraction == {}

    entry = {"daily_change": 0.0, "change_120d": 0.0}
    ENH._scrub_unevidenced_forex_zeroes(entry, {"value": 7.2, "note": "regex"})
    assert entry == {"compare_fields_pending": ["daily_change", "change_120d"]}

    entry = {"compare_fields_pending": ["daily_change"], "daily_change": 1}
    ENH._copy_forex_compare_fields(
        entry, {"daily_change": "0.5", "change_120d": "bad"}
    )
    assert entry == {"daily_change": 0.5}


def _base_apply_payload():
    return {
        "metadata": {"date": "2026-06-15"},
        "macro_indicators": {"gdp": {}},
        "monetary_policy": {"reserve_ratio": {}},
        "fund_flow": {"northbound": {}},
        "forex": [{"pair": "USDCNY"}],
        "commodities": [{"symbol": "GC=F"}],
        "bonds": [{"symbol": "US10Y"}],
    }


def test_apply_extraction_category_paths_locked():
    payload = _base_apply_payload()
    cases = [
        (
            {"indicator_key": "gdp", "task_id": "t1"},
            {
                "value": 5.1,
                "unit": "%",
                "note": "n",
                "source_url": "https://stats.gov.cn",
                "as_of_date": "2026-06-01",
            },
        ),
        (
            {"indicator_key": "rrr", "task_id": "t2"},
            {
                "value": 7.0,
                "unit": "%",
                "note": "n",
                "source_url": "https://pboc.gov.cn",
                "change_rate": "0.1",
                "change_period": "120d",
                "rrr_type": "weighted",
            },
        ),
        (
            {"indicator_key": "northbound", "task_id": "t3"},
            {
                "value": 10,
                "recent_5d": 10,
                "total_120d": 20,
                "unit": "亿元",
                "trend": "inflow",
                "note": "n",
                "source_url": "https://hkex.com",
                "as_of_date": "2026-06-01",
            },
        ),
        (
            {"indicator_key": "USDCNY", "task_id": "t4"},
            {
                "value": 7.2,
                "note": "n",
                "source_url": "https://safe.gov.cn",
                "daily_change": 0.1,
            },
        ),
        (
            {"indicator_key": "GC=F", "task_id": "t5"},
            {
                "value": 2300,
                "unit": "$/oz",
                "note": "n",
                "source_url": "https://cmegroup.com",
            },
        ),
        (
            {"indicator_key": "US10Y", "task_id": "t6"},
            {
                "value": 4.2,
                "note": "n",
                "source_url": "https://treasury.gov",
                "change_5d_bp": "1.2",
            },
        ),
        (
            {"indicator_key": "DXY", "task_id": "t7"},
            {"value": 105, "note": "n"},
        ),
        (
            {"indicator_key": "UNKNOWN", "task_id": "t8"},
            {"value": 1, "note": "n", "unit": "x"},
        ),
    ]
    results = [
        ENH._apply_extraction(payload, task, extraction, [])
        for task, extraction in cases
    ]
    assert results == [
        "macro_indicators",
        "monetary_policy",
        "fund_flow",
        "forex",
        "commodities",
        "bonds",
        "forex_upsert",
        "fallback_macro",
    ]
    assert payload["macro_indicators"]["gdp"]["current_value"] == 5.1
    assert payload["monetary_policy"]["reserve_ratio"] == {
        "current_value": 7.0,
        "source": "tavily+deepseek",
        "stage_task_id": "t2",
        "note": "n",
        "source_url": "https://pboc.gov.cn",
        "change_from_120d": 0.1,
        "rrr_type": "weighted",
        "date": "",
    }
    assert payload["fund_flow"]["northbound"]["recent_5d"] == 10.0
    assert payload["fund_flow"]["northbound"]["total_120d"] == 20.0
    assert payload["forex"][0]["current_rate"] == 7.2
    assert payload["forex"][0]["daily_change"] == 0.1
    assert payload["commodities"][0]["current_price"] == 2300
    assert payload["bonds"][0]["current_yield"] == 4.2
    assert payload["bonds"][0]["change_5d_bp"] == 1.2
    assert payload["forex"][1] == {
        "pair": "DXY",
        "name": "DXY美元指数",
        "current_rate": 105,
        "trend": "待校验",
        "source": "tavily_regex",
        "stage_task_id": "t7",
        "note": "n stage2_auto_upsert",
    }
    assert payload["macro_indicators"]["UNKNOWN"]["current_value"] == 1


@pytest.mark.parametrize("name", C2_MOVED_NAMES)
def test_import_surface_monolith(name):
    assert hasattr(ENH, name), f"monolith should still expose {name}"


def test_moved_reexports_are_same_objects_as_new_modules():
    for module, names in C2_MODULE_EXPORTS.items():
        for name in names:
            assert getattr(ENH, name) is getattr(module, name), name


def test_execute_lane_stays_in_monolith_for_c3():
    assert "_try_structured_provider" not in C2_MOVED_NAMES
    assert not hasattr(STRUCTURED_RUNNER, "_try_structured_provider")
    assert ENH._try_structured_provider.__module__ == "stage2_unified_enhancer"


def test_moved_names_list_is_stable():
    assert len(C2_MOVED_NAMES) == 65
    assert len(C2_MOVED_NAMES) == len(set(C2_MOVED_NAMES))
