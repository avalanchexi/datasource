import json
from datetime import datetime
from pathlib import Path

import pytest

from datasource.config.search_profiles import SEARCH_PROFILES
from datasource.engines.stage2_task_planner import Stage2TaskPlanner
import asyncio
import scripts.stage2_unified_enhancer as stage2

from scripts.stage2_unified_enhancer import (
    _apply_extraction,
    _candidate_query_quality,
    _flag_fund_flow_anomalies,
    _compute_derived_metrics,
    _update_missing_items,
    _gap_monitor,
    _merge_missing_items,
    _validate_fund_flow_extraction,
    _validate_general_extraction,
    _execute_tasks,
    _augment_extraction_metadata,
    _is_environment_proxy_error,
    _build_environment_proxy_error_records,
    _DeepSeekCircuitBreaker,
)


def test_deepseek_circuit_breaker_triggers_on_consecutive_timeouts():
    breaker = _DeepSeekCircuitBreaker(max_consecutive_timeouts=3)

    breaker.record(timeout=True)
    breaker.record(timeout=True)
    breaker.record(timeout=True)

    assert breaker.triggered is True
    assert breaker.reason == "consecutive_timeouts"
    breaker.record(timeout=False)
    assert breaker.attempts == 3
    assert breaker.timeouts == 3


def test_deepseek_circuit_breaker_triggers_on_timeout_rate():
    breaker = _DeepSeekCircuitBreaker(max_timeout_rate=0.5, min_attempts=4)

    for timeout in [True, False, True, True]:
        breaker.record(timeout=timeout)

    assert breaker.triggered is True
    assert breaker.reason == "timeout_rate"
    assert breaker.timeout_rate == 0.75


def test_retrieval_diagnostics_separates_search_extract_and_writeback():
    rows = [
        {
            "indicator_key": "GC=F",
            "usable_count_before_extract": 3,
            "manual_required": True,
            "manual_reason": "no_deepseek_key",
        },
        {
            "indicator_key": "CN10Y_CDB",
            "usable_count_before_extract": 0,
            "manual_required": True,
            "manual_reason": "strict_keyword_miss",
        },
        {
            "indicator_key": "northbound",
            "manual_required": False,
            "result_type": "skipped_existing",
        },
        {
            "indicator_key": "etf",
            "usable_count_before_extract": 4,
            "manual_required": False,
            "write_back_success": True,
        },
    ]

    diagnostics = stage2._build_retrieval_diagnostics(rows)

    assert diagnostics["retrieval_task_count"] == 3
    assert diagnostics["retrieval_hit_count"] == 2
    assert diagnostics["retrieval_hit_extract_failed"] == 1
    assert diagnostics["writeback_success_count"] == 1
    assert diagnostics["manual_reason_breakdown"]["no_deepseek_key"] == 1
    assert diagnostics["manual_reason_breakdown"]["strict_keyword_miss"] == 1


def test_summary_diagnostics_include_failures_without_duplicate_websearch_rows():
    completed = [
        {
            "task_id": "success-task",
            "indicator_key": "etf",
            "usable_count_before_extract": 2,
            "manual_required": False,
            "result_type": "search_success",
        }
    ]
    failures = [
        {
            "task_id": "duplicate-manual-task",
            "indicator_key": "GC=F",
            "usable_count_before_extract": 1,
            "manual_required": True,
            "manual_reason": "no_value",
            "result_type": "manual_required",
        },
        {
            "task_id": "failure-only-task",
            "indicator_key": "CL=F",
            "manual_required": True,
            "manual_reason": "network_error",
            "result_type": "manual_required",
        },
    ]
    websearch_results = [
        {
            "task": {
                "task_id": "duplicate-manual-task",
                "indicator_key": "GC=F",
                "usable_count_before_extract": 1,
            },
            "extraction": {
                "manual_required": True,
                "manual_reason": "no_value",
            },
            "manual_required": True,
            "manual_reason": "no_value",
            "result_type": "manual_required",
        }
    ]

    summary_fields = stage2._build_stage2_summary_diagnostics(
        completed,
        failures,
        websearch_results,
        exec_stats={},
    )

    diagnostics = summary_fields["retrieval_diagnostics"]
    assert diagnostics["retrieval_task_count"] == 3
    assert diagnostics["manual_reason_breakdown"]["no_value"] == 1
    assert diagnostics["manual_reason_breakdown"]["network_error"] == 1


def test_summary_diagnostics_persist_tavily_unavailable_reason():
    summary_fields = stage2._build_stage2_summary_diagnostics(
        completed_tasks=[],
        failures=[],
        websearch_results=[],
        exec_stats={
            "tavily_unavailable_reason": "quota_or_rate_limit",
            "deepseek_circuit_breaker_triggered": True,
            "deepseek_circuit_breaker_reason": "timeout_rate",
            "deepseek_timeout_rate": 0.75,
        },
    )

    assert summary_fields["tavily_unavailable_reason"] == "quota_or_rate_limit"
    assert summary_fields["deepseek_circuit_breaker_triggered"] is True
    assert summary_fields["deepseek_circuit_breaker_reason"] == "timeout_rate"
    assert summary_fields["deepseek_timeout_rate"] == 0.75


def test_is_environment_proxy_error_detects_missing_socksio_message():
    exc = RuntimeError("Using SOCKS proxy, but the 'socksio' package is not installed")

    assert _is_environment_proxy_error(exc) is True


def test_environment_proxy_error_ignores_ambiguous_upstream_proxy_text():
    exc = RuntimeError("502 Proxy Error from upstream")

    assert _is_environment_proxy_error(exc) is False


def test_environment_proxy_fast_switch_records_manual_required():
    task = {
        "task_id": "proxy-gold",
        "indicator_key": "GC=F",
        "stage_phase": "assets",
        "category": "commodities",
        "search_backend": "tavily",
        "query": "COMEX gold latest price",
        "unit": "$/oz",
        "created_at": 1700000000,
    }
    exc = RuntimeError("Using SOCKS proxy, but the 'socksio' package is not installed")

    task_record, websearch_item = _build_environment_proxy_error_records(task, exc)

    assert task_record["manual_required"] is True
    assert task_record["manual_reason"] == "environment_proxy_error"
    assert task_record["result_type"] == "manual_required"
    assert task_record["source"] == "Stage2 manual_required"
    assert task_record["note"].startswith("environment_proxy_error:")
    assert websearch_item["manual_required"] is True
    assert websearch_item["manual_reason"] == "environment_proxy_error"
    assert websearch_item["source"] == "Stage2 manual_required"
    assert websearch_item["extraction"]["manual_required"] is True
    assert websearch_item["extraction"]["manual_reason"] == "environment_proxy_error"
    assert "socksio" in websearch_item["extraction"]["environment_proxy_error"].lower()


def test_apply_extraction_clears_stale_status_on_matching_force_refresh():
    market_payload = {
        "metadata": {"date": "2026-05-08"},
        "macro_indicators": {
            "pmi_production": {
                "indicator_name": "PMI production",
                "current_value": 51.4,
                "previous_value": 49.6,
                "change_rate": 1.8,
                "unit": "points",
                "date": "2026-03",
                "is_stale": True,
                "expected_period": "2026-04",
                "stale_reason": "actual_period_behind_expected",
            }
        },
    }
    task = {
        "task_id": "pmi-production-refresh",
        "indicator_key": "pmi_production",
        "force_refresh": True,
        "expected_period": "2026-04",
    }
    extraction = {
        "value": 51.5,
        "unit": "points",
        "source_url": "https://www.stats.gov.cn/example.html",
        "as_of_date": "2026-04-30",
        "report_period": "2026-04",
        "note": "deepseek_structured",
    }

    section = _apply_extraction(market_payload, task, extraction)

    entry = market_payload["macro_indicators"]["pmi_production"]
    assert section == "macro_indicators"
    assert entry["current_value"] == 51.5
    assert entry["date"] == "2026-04"
    assert entry["as_of_date"] == "2026-04-30"
    assert entry["is_stale"] is False
    assert entry["stale_reason"] is None


def test_apply_extraction_marks_official_macro_source_not_estimated():
    market_payload = {
        "metadata": {"date": "2026-05-21"},
        "macro_indicators": {
            "cpi": {
                "indicator_name": "CPI",
                "current_value": None,
                "unit": "%",
                "date": "",
                "is_estimated": True,
                "source": "Stage2 manual_required",
            }
        },
        "monetary_policy": {},
        "fund_flow": {},
    }
    task = {
        "task_id": "macro.cpi",
        "category": "macro_indicators",
        "indicator_key": "cpi",
        "expected_period": "2026-04",
        "unit": "%",
    }
    extraction = {
        "value": 0.2,
        "unit": "%",
        "report_period": "2026-04",
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260509.html",
        "note": "deepseek_structured",
        "snippets": [
            {
                "url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260509.html?utm_source=tavily",
                "snippet": "2026年4月份居民消费价格同比上涨0.2%",
            }
        ],
    }

    section = _apply_extraction(market_payload, task, extraction)

    entry = market_payload["macro_indicators"]["cpi"]
    assert section == "macro_indicators"
    assert entry["current_value"] == 0.2
    assert entry["is_estimated"] is False
    assert "official_source_period_unit_match" in entry["note"]


def test_apply_extraction_marks_official_macro_source_not_estimated_with_runtime_snippets():
    market_payload = {
        "metadata": {"date": "2026-05-21"},
        "macro_indicators": {
            "cpi": {
                "indicator_name": "CPI",
                "current_value": None,
                "unit": "%",
                "date": "",
                "is_estimated": True,
                "source": "Stage2 manual_required",
            }
        },
        "monetary_policy": {},
        "fund_flow": {},
    }
    task = {
        "task_id": "macro.cpi",
        "category": "macro_indicators",
        "indicator_key": "cpi",
        "expected_period": "2026-04",
        "unit": "%",
    }
    extraction = {
        "value": 0.2,
        "unit": "%",
        "report_period": "2026-04",
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260509.html",
        "note": "deepseek_structured",
    }
    snippets = [
        {
            "url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260509.html?utm_source=tavily",
            "snippet": "2026年4月份居民消费价格同比上涨0.2%",
        }
    ]

    section = _apply_extraction(market_payload, task, extraction, snippets=snippets)

    entry = market_payload["macro_indicators"]["cpi"]
    assert section == "macro_indicators"
    assert entry["is_estimated"] is False
    assert "official_source_period_unit_match" in entry["note"]


def test_validate_general_extraction_accepts_canonical_percent_unit():
    extraction = {
        "value": 0.2,
        "unit": "百分比",
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260509.html",
    }
    task = {
        "indicator_key": "cpi",
        "unit": "%",
    }

    value, manual_required, note = _validate_general_extraction(extraction, task, snippets=[])

    assert value == 0.2
    assert manual_required is False
    assert "单位不匹配" not in note


def test_validate_general_extraction_rejects_point_percentage_point_mismatch():
    extraction = {
        "value": 51.5,
        "unit": "百分点",
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260509.html",
    }
    task = {
        "indicator_key": "pmi_production",
        "unit": "点",
    }

    value, manual_required, note = _validate_general_extraction(extraction, task, snippets=[])

    assert value == 51.5
    assert manual_required is True
    assert "单位不匹配" in note


def test_task_planner_uses_rrr_profile_for_reserve_ratio_alias(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-28"},
        "monetary_policy": {
            "reserve_ratio": {"current_value": None},
        },
        "missing_items": [],
    }

    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    task = next(t for t in tasks if t["indicator_key"] == "reserve_ratio")

    assert task["query_template_id"] == "rrr"
    assert "存款准备金率" in task["required_keywords"]
    assert any("reserve requirement" in q.lower() or "存款准备金率" in q for q in task["query_candidates_expanded"])


def test_cn10y_cdb_profile_accepts_chinabond_policy_bank_language():
    profile = SEARCH_PROFILES["CN10Y_CDB"]
    aliases = " ".join(profile["issuer_aliases"])
    required = " ".join(profile["required_keywords"])

    assert "中债估值" in aliases
    assert "政策性金融债" in aliases
    assert "国开" in required
    assert "10年" in required
    assert profile["strict_issuer_match"] is False


def test_usdcny_profile_has_separate_midpoint_and_spot_families():
    family_names = {family["name"] for family in SEARCH_PROFILES["USDCNY"]["query_families"]}

    assert {"pboc_midpoint", "cfets_spot", "onshore_spot"}.issubset(family_names)


def test_bdi_profile_prioritizes_dated_market_data_family():
    profile = SEARCH_PROFILES["bdi"]
    first_family = profile["query_families"][0]

    assert first_family["name"] == "dated_bdi_quote"
    assert "tradingeconomics.com" in first_family["preferred_domains"]
    assert "investing.com" in first_family["preferred_domains"]


def test_profiles_expose_report_usage_contract_for_high_risk_tasks():
    etf = SEARCH_PROFILES["etf"]
    assert etf["required_output_fields"] == ["recent_5d", "total_120d", "trend"]
    assert "全市场" in etf["evidence_keywords"]
    assert "data.eastmoney.com" in etf["good_url_patterns"]
    assert "caifuhao.eastmoney.com" in etf["bad_url_patterns"]

    bdi = SEARCH_PROFILES["bdi"]
    assert bdi["required_output_fields"] == ["current_value", "previous_value", "change_rate"]
    assert "Baltic Dry Index" in bdi["evidence_keywords"]
    assert "/Circulars/" in bdi["bad_url_patterns"]

    industrial = SEARCH_PROFILES["industrial"]
    assert "全国" in industrial["evidence_keywords"]
    assert "stats.gov.cn" in industrial["good_url_patterns"]


def test_realtime_quote_profiles_use_small_query_budget_with_usdcny_extract_exception():
    for key in ("BCOM", "GSG", "DXY", "CN10Y_CDB"):
        profile = SEARCH_PROFILES[key]
        assert profile["max_query_candidates"] == 3
        assert profile["extract_policy"]["use_tavily_extract"] is False
        assert profile["extract_policy"]["extract_topk"] == 0

    usdcny = SEARCH_PROFILES["USDCNY"]
    assert usdcny["max_query_candidates"] == 3
    assert usdcny["extract_policy"]["use_tavily_extract"] is True
    assert usdcny["extract_policy"]["extract_topk"] == 1
    assert usdcny["extract_policy"]["official_domains_only"] is True


def test_high_gap_quote_profiles_have_report_quality_patterns():
    bcom = SEARCH_PROFILES["BCOM"]
    assert "BCOM:IND" in bcom["evidence_keywords"]
    assert "bloomberg.com/quote/BCOM:IND" in bcom["good_url_patterns"]
    assert "BCOMX" in bcom["bad_url_patterns"]

    gsg = SEARCH_PROFILES["GSG"]
    assert "iShares S&P GSCI Commodity-Indexed Trust" in gsg["evidence_keywords"]
    assert "ishares.com/us/products" in gsg["good_url_patterns"]
    assert "fund flows" in gsg["bad_url_patterns"]

    usdcny = SEARCH_PROFILES["USDCNY"]
    assert "USD/CNY" in usdcny["evidence_keywords"]
    assert "chinamoney.com.cn" in usdcny["good_url_patterns"]
    assert "bankofchina" in usdcny["bad_url_patterns"]

    dxy = SEARCH_PROFILES["DXY"]
    assert "US Dollar Index" in dxy["evidence_keywords"]
    assert "investing.com/indices/us-dollar-index" in dxy["good_url_patterns"]
    assert "DXY news" in dxy["bad_url_patterns"]

    cn10y_cdb = SEARCH_PROFILES["CN10Y_CDB"]
    assert "CDB" in cn10y_cdb["evidence_keywords"]
    assert "chinabond.com.cn" in cn10y_cdb["good_url_patterns"]
    assert "China 10Y Treasury" in cn10y_cdb["bad_url_patterns"]


def test_daily_quote_profiles_include_run_date_and_value_page_filters():
    quote_keys = ("GC=F", "CL=F", "BZ=F", "HG=F", "BCOM", "GSG", "DXY", "bdi")
    for key in quote_keys:
        profile = SEARCH_PROFILES[key]
        joined_queries = " ".join(
            query
            for family in profile["query_families"]
            for query in family.get("queries", [])
        )
        assert "{closing_date}" in joined_queries or "{closing_date_label}" in joined_queries

    gold_bad = " ".join(SEARCH_PROFILES["GC=F"]["bad_url_patterns"]).lower()
    assert "contract specifications" in gold_bad
    assert "fact card" in gold_bad

    bcom_bad = " ".join(SEARCH_PROFILES["BCOM"]["bad_url_patterns"]).lower()
    assert "target weights" in bcom_bad
    assert "annual rebalance" in bcom_bad

    dxy_bad = " ".join(SEARCH_PROFILES["DXY"]["bad_url_patterns"]).lower()
    assert "technical analysis" in dxy_bad


def test_usdcny_extract_policy_uses_official_table_exception():
    profile = SEARCH_PROFILES["USDCNY"]
    assert profile["extract_policy"] == {
        "use_tavily_extract": True,
        "extract_topk": 1,
        "official_domains_only": True,
        "official_domains": ["chinamoney.com.cn", "cfets.com.cn"],
    }
    assert "chinamoney.com.cn" in profile["good_url_patterns"]
    assert "cfets.com.cn" in profile["good_url_patterns"]


def test_official_domain_extract_filter_rejects_suffix_spoof():
    snippets = [
        {
            "url": "https://fakechinamoney.com.cn/chinese/bkccpr/",
            "snippet": "spoofed USD/CNY table",
        },
        {
            "url": "https://www.chinamoney.com.cn/chinese/bkccpr/",
            "snippet": "official USD/CNY table",
        },
    ]

    filtered = stage2._filter_by_official_extract_domain(
        snippets,
        ["chinamoney.com.cn"],
    )

    assert [item["url"] for item in filtered] == [
        "https://www.chinamoney.com.cn/chinese/bkccpr/"
    ]


def test_task_planner_carries_quote_profile_budget_and_extract_policy(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-10"},
        "missing_items": [{"key": "BCOM"}],
    }

    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == "BCOM")

    assert task["max_query_candidates"] == 3
    assert task["extract_policy"]["use_tavily_extract"] is False
    assert task["extract_policy"]["extract_topk"] == 0


@pytest.mark.parametrize(
    ("indicator_key", "expected_family"),
    [
        ("BCOM", "dated_index_quote"),
        ("GSG", "dated_etf_quote"),
        ("DXY", "dated_index_quote"),
    ],
)
def test_high_gap_quote_dated_families_survive_profile_budget(
    tmp_path: Path,
    indicator_key: str,
    expected_family: str,
):
    payload = {
        "metadata": {"date": "2026-05-12"},
        "missing_items": [{"key": indicator_key}],
    }

    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == indicator_key)
    candidates = stage2._expand_query_candidates(task)

    assert candidates
    assert candidates[0]["family"] == expected_family
    assert any(item["family"] == expected_family for item in candidates)
    assert any("2026-05-12" in item["query"] or "2026年5月12日" in item["query"] for item in candidates)


def test_fund_flow_profiles_have_field_queries_for_all_report_windows():
    for key in ("northbound", "southbound", "etf"):
        profile = SEARCH_PROFILES[key]
        assert "recent_5d" in profile["field_queries"]
        assert "total_120d" in profile["field_queries"]
        joined = " ".join(profile["field_queries"]["recent_5d"] + profile["field_queries"]["total_120d"])
        assert "近5日" in joined
        assert "120" in joined


def test_etf_primary_query_family_is_all_market_window_search():
    profile = SEARCH_PROFILES["etf"]
    first_family = profile["query_families"][0]
    joined = " ".join(first_family["queries"])

    assert first_family["name"] == "all_market_windows"
    assert "全市场" in joined
    assert "近5日" in joined
    assert "120" in joined


def test_expand_query_candidates_applies_profile_budget_after_dedup():
    task = {
        "indicator_key": "BCOM",
        "preferred_domains": [],
        "exclude_domains": [],
        "required_keywords": [],
        "exclude_keywords": [],
        "query_families": [
            {"name": "primary", "queries": ["q1", "q2", "q2"]},
            {"name": "fallback", "queries": ["q3", "q4"]},
        ],
        "max_query_candidates": 2,
    }

    candidates = stage2._expand_query_candidates(task)

    assert [item["query"] for item in candidates] == ["q1", "q2"]


def test_expand_query_candidates_does_not_count_directed_retry_against_primary_budget():
    task = {
        "indicator_key": "BCOM",
        "preferred_domains": [],
        "exclude_domains": [],
        "required_keywords": [],
        "exclude_keywords": [],
        "query_families": [
            {"name": "primary", "queries": ["q1", "q2", "q3"]},
        ],
        "max_query_candidates": 2,
    }

    candidates = stage2._expand_query_candidates(task, directed_query_override="directed q")

    assert [item["query"] for item in candidates] == ["directed q", "q1", "q2"]
    assert candidates[0]["family"] == "directed_retry"


def test_expand_query_candidates_does_not_budget_field_scope_queries():
    task = {
        "indicator_key": "etf",
        "preferred_domains": [],
        "exclude_domains": [],
        "required_keywords": [],
        "exclude_keywords": [],
        "field_queries": {
            "recent_5d": ["recent q1", "recent q2"],
            "total_120d": ["total q1"],
        },
        "max_query_candidates": 1,
    }

    candidates = stage2._expand_query_candidates(
        task,
        field_scopes=["recent_5d", "total_120d"],
        include_primary=False,
    )

    assert [item["query"] for item in candidates] == ["recent q1", "recent q2", "total q1"]


def test_policy_profiles_distinguish_current_level_and_operation_notice():
    rrr_families = {family["name"] for family in SEARCH_PROFILES["rrr"]["query_families"]}
    mlf_families = {family["name"] for family in SEARCH_PROFILES["mlf"]["query_families"]}
    reverse_repo_families = {family["name"] for family in SEARCH_PROFILES["reverse_repo"]["query_families"]}

    assert {"current_level", "official_adjustment_notice"}.issubset(rrr_families)
    assert "official_operation_notice" in reverse_repo_families
    assert "multi_price_notice" in mlf_families


def test_macro_profiles_prioritize_national_official_releases():
    industrial = SEARCH_PROFILES["industrial"]["query_families"][0]
    industrial_sales = SEARCH_PROFILES["industrial_sales"]["query_families"][0]

    assert industrial["name"] == "official_nbs_release"
    assert industrial_sales["name"] == "official_nbs_release"
    assert "stats.gov.cn" in industrial["preferred_domains"]
    assert "stats.gov.cn" in industrial_sales["preferred_domains"]


def test_stage2_exa_fallback_is_opt_in_by_default(monkeypatch):
    monkeypatch.setattr("sys.argv", ["stage2_unified_enhancer.py", "--market-data", "market.json"])
    monkeypatch.delenv("STAGE2_ENABLE_EXA_FALLBACK", raising=False)

    args = stage2._parse_args()

    assert args.enable_exa_fallback is False
    assert stage2._should_enable_exa_fallback(args) is False


def test_stage2_exa_fallback_can_be_enabled_explicitly(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["stage2_unified_enhancer.py", "--market-data", "market.json", "--enable-exa-fallback"],
    )

    args = stage2._parse_args()

    assert args.enable_exa_fallback is True
    assert stage2._should_enable_exa_fallback(args) is True

def test_task_planner_detects_missing_and_placeholders(tmp_path: Path):
    payload = {
        "missing_items": [{"key": "cpi"}, "pmi_new_orders"],
        "macro_indicators": {"ppi": {"current_value": 7.13}},
        "monetary_policy": {"m2": {"current_value": None}},
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    indicator_keys = {t["indicator_key"] for t in tasks}
    assert {"cpi", "pmi_new_orders", "ppi", "m2"} <= indicator_keys


def test_task_planner_picks_stale_entries(tmp_path: Path):
    payload = {
        "missing_items": [],
        "macro_indicators": {
            "cpi": {"current_value": 0.8, "is_stale": True, "expected_period": "2026-01"},
        },
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    task_map = {t["indicator_key"]: t for t in tasks}
    assert "cpi" in task_map
    assert task_map["cpi"]["trigger_reason"] == "stale_data"
    assert task_map["cpi"]["expected_period"] == "2026-01"
    assert "2026-01" in task_map["cpi"]["expected_period_tokens"]


def test_task_planner_expands_expected_period_for_query_families(tmp_path: Path):
    payload = {
        "missing_items": [],
        "macro_indicators": {
            "industrial_sales": {"current_value": None, "is_stale": True, "expected_period": "2026-02"},
        },
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    task = next(t for t in tasks if t["indicator_key"] == "industrial_sales")
    assert any("2026年1-2月" in q for q in task["query_candidates_expanded"])


def test_task_planner_does_not_attach_monthly_tokens_to_daily_quotes(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-12"},
        "commodities": [{"symbol": "GC=F", "current_price": None}],
        "forex": [{"pair": "DXY", "current_rate": None}],
        "macro_indicators": {},
        "missing_items": [{"key": "GC=F"}, {"key": "DXY"}],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task_map = {task["indicator_key"]: task for task in planner.build_tasks(payload)}

    assert task_map["GC=F"]["time_context_type"] == "daily_quote"
    assert task_map["DXY"]["time_context_type"] == "daily_quote"
    assert task_map["GC=F"]["expected_period_tokens"] == []
    assert task_map["DXY"]["expected_period_tokens"] == []
    executable_queries = [
        query
        for family in task_map["GC=F"]["query_families"]
        for query in family.get("queries", [])
    ]
    joined = " ".join(executable_queries)
    assert "2026-05-12" in joined or "2026年5月12日" in joined
    assert task_map["GC=F"]["query_candidates_expanded"] == executable_queries


def test_task_planner_treats_stock_indices_as_daily_quotes(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-12"},
        "stock_indices": {"000001": {"current_value": None}},
        "missing_items": [{"key": "000001"}],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == "000001")

    assert task["time_context_type"] == "daily_quote"
    assert task["expected_period_tokens"] == []


def test_task_planner_daily_quote_context_checks_indicator_key_when_profile_differs(tmp_path: Path):
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")

    assert planner._time_context_type("legacy_primary", "GC=F", None) == "daily_quote"
    assert planner._time_context_type("legacy_primary", "GC=F", "2026-04") == "monthly_period"


def test_task_planner_gives_pmi_production_official_period_profile(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-12"},
        "macro_indicators": {
            "pmi_production": {
                "current_value": 50.0,
                "is_stale": True,
                "expected_period": "2026-04",
            }
        },
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == "pmi_production")

    assert task["query_template_id"] == "pmi_production"
    assert task["time_context_type"] == "monthly_period"
    assert "2026-04" in task["expected_period_tokens"]
    assert task["query"] != "pmi_production"
    assert any("生产指数" in query for query in task["query_candidates_expanded"])


def test_task_planner_keeps_etf_field_queries(tmp_path: Path):
    payload = {
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None}},
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    task = next(t for t in tasks if t["indicator_key"] == "etf")
    assert "recent_5d" in task["field_queries"]
    assert "total_120d" in task["field_queries"]


def test_task_planner_skips_complete_official_tushare_etf(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-28"},
        "fund_flow": {
            "etf": {
                "recent_5d": 85.6,
                "total_120d": 1250.0,
                "trend": "流入",
                "source": "tushare etf_share_size",
                "metric_basis": "etf_total_size_delta",
                "is_estimated": False,
            }
        },
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)

    assert "etf" not in {task["indicator_key"] for task in tasks}


def test_task_planner_skips_complete_tushare_dxy_proxy(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-28"},
        "forex": [
            {
                "pair": "DXY",
                "name": "美元指数（TuShare USDOLLAR.FXCM proxy）",
                "current_rate": 105.23,
                "source": "tushare fx_obasic/fx_daily FX_BASKET proxy USDOLLAR.FXCM",
            }
        ],
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)

    assert "dxy" not in {str(task["indicator_key"]).lower() for task in tasks}


def test_task_planner_keeps_estimated_etf_missing_item_for_stage2(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-28"},
        "fund_flow": {
            "etf": {
                "recent_5d": 85.6,
                "total_120d": 1250.0,
                "trend": "流入",
                "source": "fallback estimate",
                "is_estimated": True,
            }
        },
        "missing_items": [{"key": "etf", "reason": "estimated_not_allowed"}],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)

    task = next(task for task in tasks if task["indicator_key"] == "etf")
    assert task["trigger_reason"] == "missing"
    assert "recent_5d" in task["field_queries"]
    assert "total_120d" in task["field_queries"]


def test_task_planner_routes_estimated_etf_fallback_without_missing_item(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-28"},
        "fund_flow": {
            "etf": {
                "recent_5d": 85.6,
                "total_120d": 1250.0,
                "trend": "娴佸叆",
                "source": "legacy daily_info estimated fallback",
                "is_estimated": True,
            }
        },
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)

    etf_tasks = [task for task in tasks if task["indicator_key"] == "etf"]
    assert len(etf_tasks) == 1
    assert etf_tasks[0]["trigger_reason"] == "estimated_fallback"
    assert "recent_5d" in etf_tasks[0]["field_queries"]
    assert "total_120d" in etf_tasks[0]["field_queries"]


def test_task_planner_passes_report_usage_contract_to_task(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-28"},
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None}},
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == "etf")

    assert task["required_output_fields"] == ["recent_5d", "total_120d", "trend"]
    assert "全市场" in task["evidence_keywords"]
    assert "data.eastmoney.com" in task["good_url_patterns"]
    assert "caifuhao.eastmoney.com" in task["bad_url_patterns"]


def test_apply_extraction_etf_complete_writeback_clears_stale_estimate_flag():
    payload = {
        "metadata": {"date": "2026-03-06"},
        "fund_flow": {
            "etf": {
                "recent_5d": 85.6,
                "total_120d": 1250.0,
                "trend": "流入",
                "source": "tushare daily_info fallback",
                "is_estimated": True,
            }
        },
    }
    task = {"indicator_key": "etf", "task_id": "fund_flow.etf"}
    extraction = {
        "value": 85.0,
        "recent_5d": 85.0,
        "total_120d": 1200.0,
        "trend": "inflow",
        "source_url": "https://data.eastmoney.com/etf",
        "metric_basis": "net_flow_sum",
        "window_evidence": "direct_daily_series",
        "note": "stage2 verified windows",
    }

    assert _apply_extraction(payload, task, extraction) == "fund_flow"
    assert payload["fund_flow"]["etf"]["recent_5d"] == pytest.approx(85.0)
    assert payload["fund_flow"]["etf"]["total_120d"] == pytest.approx(1200.0)
    assert payload["fund_flow"]["etf"]["is_estimated"] is False
    assert payload["fund_flow"]["etf"]["source_tier"] == "tier2"
    assert payload["fund_flow"]["etf"]["metric_basis"] == "net_flow_sum"
    assert payload["fund_flow"]["etf"]["window_evidence"] == "direct_daily_series"


def test_apply_extraction_etf_non_structured_source_remains_estimated():
    payload = {
        "metadata": {"date": "2026-03-06"},
        "fund_flow": {
            "etf": {
                "recent_5d": None,
                "total_120d": None,
                "trend": "",
                "source": "",
                "is_estimated": False,
            }
        },
    }
    task = {"indicator_key": "etf", "task_id": "fund_flow.etf"}
    extraction = {
        "value": 85.0,
        "recent_5d": 85.0,
        "total_120d": 1200.0,
        "trend": "inflow",
        "source_url": "https://fund.eastmoney.com/a/202605191234567.html",
        "metric_basis": "net_flow_sum",
        "window_evidence": "direct_daily_series",
        "note": "news page repeats ETF window numbers",
    }

    assert _apply_extraction(payload, task, extraction) == "fund_flow"
    etf = payload["fund_flow"]["etf"]
    assert etf["recent_5d"] == pytest.approx(85.0)
    assert etf["total_120d"] == pytest.approx(1200.0)
    assert etf["source_tier"] == "unknown"
    assert etf["window_evidence"] == "direct_daily_series"
    assert etf["is_estimated"] is True
    assert "fund_flow_estimated_gate" in etf["note"]


def test_apply_extraction_etf_structured_source_without_window_evidence_remains_estimated():
    payload = {
        "metadata": {"date": "2026-03-06"},
        "fund_flow": {
            "etf": {
                "recent_5d": None,
                "total_120d": None,
                "trend": "",
                "source": "",
                "is_estimated": False,
            }
        },
    }
    task = {"indicator_key": "etf", "task_id": "fund_flow.etf"}
    extraction = {
        "value": 85.0,
        "recent_5d": 85.0,
        "total_120d": 1200.0,
        "trend": "inflow",
        "source_url": "https://data.eastmoney.com/etf/",
        "metric_basis": "net_flow_sum",
        "note": "stage2 extracted values without direct window proof",
    }

    assert _apply_extraction(payload, task, extraction) == "fund_flow"
    etf = payload["fund_flow"]["etf"]
    assert etf["source_tier"] == "tier2"
    assert etf["window_evidence"] == "unknown"
    assert etf["is_estimated"] is True
    assert "fund_flow_estimated_gate" in etf["note"]


def test_augment_fund_flow_metadata_infers_direct_window_from_snippets():
    extraction = {
        "value": 85.0,
        "unit": "亿元",
        "recent_5d": 85.0,
        "total_120d": 1200.0,
        "trend": "inflow",
        "source_url": "https://data.eastmoney.com/etf/",
        "confidence": 0.9,
        "note": "deepseek_structured",
    }
    task = {"indicator_key": "etf"}
    snippets = [
        {
            "url": "https://data.eastmoney.com/etf/",
            "content": "A股ETF全市场近5日资金净流入85亿元，近120日累计净流入1200亿元。",
        }
    ]

    _augment_extraction_metadata(extraction, task, snippets)

    assert extraction["metric_basis"] == "net_flow_sum"
    assert extraction["window_evidence"] == "direct_window"


def test_augment_fund_flow_metadata_does_not_mix_source_url_with_tier3_amounts():
    extraction = {
        "value": 5.0,
        "unit": "亿元",
        "recent_5d": 5.0,
        "total_120d": 120.0,
        "trend": "inflow",
        "source_url": "https://data.eastmoney.com/hsgt/",
        "confidence": 0.9,
        "note": "deepseek_structured",
    }
    task = {"indicator_key": "northbound", "task_id": "fund_flow.northbound"}
    snippets = [
        {
            "url": "https://data.eastmoney.com/hsgt/",
            "content": "北向资金 东方财富沪深港通近5日近120日净流入统计页面。",
        },
        {
            "url": "https://data.10jqka.com.cn/hgt/hgtb/",
            "content": "北向资金近5日净流入5.0亿元，近120日累计净流入120.0亿元。",
        },
    ]

    _augment_extraction_metadata(extraction, task, snippets)

    assert extraction["metric_basis"] == "net_flow_sum"
    assert extraction["window_evidence"] == "unknown"

    payload = {
        "metadata": {"date": "2026-03-06"},
        "fund_flow": {"northbound": {"recent_5d": None, "total_120d": None}},
    }
    assert _apply_extraction(payload, task, extraction) == "fund_flow"
    northbound = payload["fund_flow"]["northbound"]
    assert northbound["source_tier"] == "tier2"
    assert northbound["window_evidence"] == "unknown"
    assert northbound["is_estimated"] is True
    assert stage2._post_writeback_manual_reason(payload, "northbound") == "estimated_not_allowed"


def test_apply_extraction_etf_preserves_explicit_estimate_flag():
    payload = {
        "metadata": {"date": "2026-03-06"},
        "fund_flow": {
            "etf": {
                "recent_5d": None,
                "total_120d": None,
                "is_estimated": False,
            }
        },
    }
    task = {"indicator_key": "etf", "task_id": "fund_flow.etf"}
    extraction = {
        "value": 85.0,
        "recent_5d": 85.0,
        "total_120d": 1200.0,
        "trend": "inflow",
        "source_url": "https://data.eastmoney.com/etf",
        "is_estimated": True,
    }

    assert _apply_extraction(payload, task, extraction) == "fund_flow"
    assert payload["fund_flow"]["etf"]["is_estimated"] is True


def test_task_planner_dedupes_rrr_and_reserve_ratio_aliases(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-28"},
        "monetary_policy": {
            "rrr": {"current_value": None},
            "reserve_ratio": {"current_value": None},
        },
        "missing_items": [
            {"key": "rrr", "reason": "missing"},
            {"key": "reserve_ratio", "reason": "missing"},
        ],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    rrr_tasks = [task for task in tasks if task["query_template_id"] == "rrr"]

    assert len(rrr_tasks) == 1
    assert rrr_tasks[0]["indicator_key"] == "rrr"


def test_task_planner_dedupe_prefers_stale_reason(tmp_path: Path):
    payload = {
        "missing_items": [{"key": "cpi", "reason": "manual_missing"}],
        "macro_indicators": {
            "cpi": {"current_value": 7.13, "is_stale": True, "expected_period": "2026-01"},
        },
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    cpi_tasks = [t for t in tasks if t["indicator_key"] == "cpi"]
    assert len(cpi_tasks) == 1
    assert cpi_tasks[0]["trigger_reason"] == "stale_data"


def test_flag_fund_flow_anomalies_marks_zero_values():
    payload = {
        "fund_flow": {
            "northbound": {"recent_5d": 0, "total_120d": None, "source": "legacy_raw"},
            "southbound": {"recent_5d": 10.5, "total_120d": 20.1, "source": "legacy_raw"},
        }
    }
    flagged = _flag_fund_flow_anomalies(payload)
    assert "northbound" in flagged
    assert payload["fund_flow"]["northbound"]["source"] == "异常零值-需核查"
    assert payload["fund_flow"]["southbound"]["source"] in ("legacy_raw", "tavily+deepseek")


def test_gap_monitor_pending_only_incomplete(tmp_path: Path):
    pending = ["a", "b"]
    path = tmp_path / "gap.json"
    _gap_monitor(pending, path, manual_required=["b"])
    data = json.load(path.open())
    assert data["pending_tasks"] == pending
    assert data["manual_required"] == ["b"]


def test_merge_missing_items_flatten_metadata():
    payload = {
        "metadata": {
            "missing_items": {
                "macro": [{"key": "cpi"}],
                "fund_flow": ["northbound"],
            }
        }
    }
    _merge_missing_items(payload)
    assert "missing_items" in payload
    keys = {it["key"] if isinstance(it, dict) else it for it in payload["missing_items"]}
    assert {"cpi", "northbound"} <= keys


def test_compute_derived_metrics_spread_and_trend():
    payload = {
        "monetary_policy": {"m1": {"current_value": 5}, "m2": {"current_value": 8}, "dr007": {"history": [2.1, 2.2]}},
        "commodities": [{"daily_change": 1.0}, {"daily_change": -0.5}],
    }
    _compute_derived_metrics(payload)
    derived = payload["derived_metrics"]
    assert derived["m1_m2_spread"] == -3.0
    assert "commodity_trend" in derived


def test_candidate_query_quality_prefers_trusted_period_and_issuer():
    task = {
        "indicator_key": "reverse_repo",
        "preferred_domains": ["pbc.gov.cn"],
        "required_keywords": ["逆回购", "中标利率"],
        "exclude_keywords": [],
        "issuer": "中国人民银行",
        "issuer_aliases": ["人民银行", "PBOC"],
        "expected_period_tokens": ["2026-02", "2026年2月"],
        "max_age_days": 30,
    }
    candidate = {
        "required_keywords": [],
        "exclude_keywords": [],
        "preferred_domains": ["pbc.gov.cn"],
    }
    official_snippets = [
        {
            "url": "https://www.pbc.gov.cn/notice/2026-02-18.html",
            "content": "2026年2月 人民银行公开市场业务交易公告 7天逆回购中标利率为1.40%",
            "score": 0.61,
        }
    ]
    noisy_snippets = [
        {
            "url": "https://example.com/forecast",
            "content": "reverse repo forecast 1.40% without issuer or target period",
            "score": 0.99,
        }
    ]
    official = _candidate_query_quality(task, candidate, official_snippets)
    noisy = _candidate_query_quality(task, candidate, noisy_snippets)
    assert official["quality_score"] > noisy["quality_score"]


def test_candidate_query_quality_strict_keywords_rejects_unrelated_snippets():
    task = {
        "indicator_key": "GSG",
        "preferred_domains": ["ishares.com", "investing.com"],
        "required_keywords": ["gsg", "ishares", "quote"],
        "exclude_keywords": [],
        "issuer": "iShares/BlackRock",
        "issuer_aliases": ["iShares", "BlackRock"],
        "expected_period_tokens": [],
        "max_age_days": 7,
        "strict_required_keywords": True,
    }
    candidate = {
        "preferred_domains": ["investing.com"],
        "required_keywords": ["gsg", "ishares", "quote"],
        "exclude_keywords": [],
    }
    noisy_snippets = [
        {
            "url": "https://www.investing.com/etfs/ishares-s-p-global-telecom",
            "content": "iShares Global Telecom ETF quote latest",
            "score": 0.95,
        }
    ]
    quality = _candidate_query_quality(task, candidate, noisy_snippets)
    assert quality["snippets"] == []
    assert quality["usable_count"] == 0
    assert quality["unusable_reason"] == "strict_keyword_miss"


def test_candidate_query_quality_penalizes_bad_url_patterns_and_prefers_usage_evidence():
    task = {
        "indicator_key": "etf",
        "preferred_domains": ["data.eastmoney.com"],
        "good_url_patterns": ["data.eastmoney.com"],
        "bad_url_patterns": ["caifuhao.eastmoney.com", "/news/", "单只", "费率"],
        "evidence_keywords": ["全市场", "A股ETF", "近5日", "近120日", "净流入", "累计", "合计"],
    }
    candidate = {"query": "A股ETF 全市场 近5日 近120日 净流入 合计", "preferred_domains": task["preferred_domains"]}
    good_snippets = [
        {
            "url": "https://data.eastmoney.com/fund/etf.html",
            "title": "A股ETF资金流向",
            "content": "全市场A股ETF近5日净流入85亿元，近120日累计净流入1200亿元，资金流向合计为流入。",
            "score": 0.72,
        }
    ]
    noisy_snippets = [
        {
            "url": "https://caifuhao.eastmoney.com/news/202604280001",
            "title": "单只ETF规模创新高",
            "content": "某单只ETF费率优惠，规模创新高，未披露全市场近5日或近120日合计净流入。",
            "score": 0.96,
        }
    ]

    good = _candidate_query_quality(task, candidate, good_snippets)
    noisy = _candidate_query_quality(task, candidate, noisy_snippets)

    assert good["quality_score"] > noisy["quality_score"]
    assert good["usage_evidence_score"] > noisy["usage_evidence_score"]
    assert noisy["bad_url_hit_count"] >= 1


def test_candidate_query_quality_prefers_value_bearing_quote_over_contract_spec():
    task = {
        "indicator_key": "GC=F",
        "preferred_domains": ["cmegroup.com", "tradingeconomics.com"],
        "required_keywords": ["gold", "comex"],
        "exclude_keywords": ["contract specifications", "fact card"],
        "evidence_keywords": ["settlement", "price", "$/oz", "closing"],
        "good_url_patterns": ["tradingeconomics.com/commodity/gold"],
        "bad_url_patterns": ["contractSpecs", "fact-card"],
        "expected_period_tokens": [],
        "issuer": "COMEX/CME",
        "issuer_aliases": ["CME", "COMEX"],
    }
    candidate = {"query": "COMEX gold futures price 2026-05-12 closing", "preferred_domains": task["preferred_domains"]}
    value_snippets = [
        {
            "url": "https://tradingeconomics.com/commodity/gold",
            "title": "Gold futures",
            "content": "COMEX gold futures settled at 4730.70 USD per troy ounce on 2026-05-12.",
            "score": 0.71,
        }
    ]
    spec_snippets = [
        {
            "url": "https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html",
            "title": "Gold Futures Contract Specs",
            "content": "Contract unit is 100 troy ounces. Minimum price fluctuation is 0.10.",
            "score": 0.92,
        }
    ]

    value_quality = _candidate_query_quality(task, candidate, value_snippets)
    spec_quality = _candidate_query_quality(task, candidate, spec_snippets)

    assert value_quality["value_evidence_score"] > 0
    assert spec_quality["value_evidence_score"] == 0
    assert value_quality["quality_score"] > spec_quality["quality_score"]


def test_candidate_query_quality_keeps_low_score_value_evidence_over_high_score_overview():
    task = {
        "indicator_key": "BCOM",
        "required_output_fields": ["current_price"],
        "evidence_keywords": ["level", "last price", "points"],
        "expected_period_tokens": [],
    }
    candidate = {"query": "Bloomberg Commodity Index BCOM level 2026-05-12"}
    snippets = [
        {
            "url": "https://example.com/market-data/bcom",
            "title": "BCOM quote",
            "content": "BCOM last price was 101.25 points on 2026-05-12.",
            "score": 0.28,
        },
        {
            "url": "https://example.com/news/bcom-overview",
            "title": "Bloomberg Commodity Index overview",
            "content": "Bloomberg Commodity Index tracks diversified commodity futures markets.",
            "score": 0.91,
        },
    ]

    quality = _candidate_query_quality(task, candidate, snippets)

    assert quality["unusable_reason"] is None
    assert any(snippet["url"] == "https://example.com/market-data/bcom" for snippet in quality["snippets"])
    assert quality["value_evidence_score"] > 0


def test_candidate_query_quality_marks_value_evidence_miss_for_trusted_but_unusable_page():
    task = {
        "indicator_key": "BCOM",
        "preferred_domains": ["bloomberg.com"],
        "required_keywords": ["BCOM", "Bloomberg Commodity Index"],
        "exclude_keywords": ["target weights", "annual rebalance"],
        "evidence_keywords": ["level", "last price", "points"],
        "good_url_patterns": ["bloomberg.com/quote/BCOM:IND"],
        "bad_url_patterns": ["target-weights", "annual-rebalance"],
        "expected_period_tokens": [],
        "issuer": "Bloomberg",
        "issuer_aliases": ["Bloomberg"],
    }
    candidate = {"query": "Bloomberg Commodity Index BCOM level 2026-05-12", "preferred_domains": task["preferred_domains"]}
    snippets = [
        {
            "url": "https://www.bloomberg.com/company/press/bloomberg-commodity-index-2026-target-weights/",
            "title": "Bloomberg Commodity Index 2026 Target Weights",
            "content": "Bloomberg announced target weights for the annual rebalance.",
            "score": 0.88,
        }
    ]

    quality = _candidate_query_quality(task, candidate, snippets)

    assert quality["unusable_reason"] == "value_evidence_miss"
    assert quality["usable_count"] == 0


def test_value_evidence_rejects_methodology_and_rebalance_number_pages():
    task = {
        "indicator_key": "BCOM",
        "unit": "points",
        "evidence_keywords": ["level", "last price", "points"],
        "required_output_fields": ["current_price"],
    }
    methodology_snippet = {
        "url": "https://assets.bbhub.io/professional/sites/10/BCOM-Methodology.pdf",
        "title": "Bloomberg Commodity Index Methodology and Rulebook",
        "content": (
            "The methodology describes calculation rules, target weights, annual rebalance, "
            "contract specs, and index level procedures. Section 4.2 uses a base level of "
            "100 points and applies 2/3 liquidity and 1/3 production weights."
        ),
        "score": 0.93,
    }

    assert stage2._value_evidence_score(methodology_snippet, task) == 0

    quality = _candidate_query_quality(
        task,
        {"query": "Bloomberg Commodity Index BCOM level methodology"},
        [methodology_snippet],
    )
    assert quality["unusable_reason"] == "value_evidence_miss"
    assert quality["value_evidence_score"] == 0


def test_candidate_query_quality_penalizes_bad_etf_results_below_clean_data_page():
    task = {
        "indicator_key": "etf",
        "preferred_domains": ["data.eastmoney.com"],
        "good_url_patterns": ["data.eastmoney.com"],
        "bad_url_patterns": ["caifuhao.eastmoney.com", "/news/", "单只", "费率"],
        "evidence_keywords": ["全市场", "A股ETF", "近5日", "近120日", "净流入", "累计", "合计"],
    }
    candidate = {"query": "A股ETF 全市场 近5日 近120日 净流入 合计", "preferred_domains": task["preferred_domains"]}
    clean = _candidate_query_quality(
        task,
        candidate,
        [
            {
                "url": "https://data.eastmoney.com/fund/etf.html",
                "content": "全市场A股ETF近5日净流入85亿元，近120日累计净流入1200亿元。",
                "score": 0.64,
            }
        ],
    )
    all_bad = _candidate_query_quality(
        task,
        candidate,
        [
            {
                "url": "https://caifuhao.eastmoney.com/news/202604280001",
                "content": "单只ETF费率优惠，规模创新高。",
                "score": 0.99,
            },
            {
                "url": "https://caifuhao.eastmoney.com/news/202604280002",
                "content": "单只ETF营销文章，未披露全市场合计窗口。",
                "score": 0.98,
            },
            {
                "url": "https://caifuhao.eastmoney.com/news/202604280003",
                "content": "单只ETF申购热度上升，未披露全市场窗口。",
                "score": 0.97,
            },
            {
                "url": "https://caifuhao.eastmoney.com/news/202604280004",
                "content": "单只ETF规模创新高，未披露近5日和120日合计。",
                "score": 0.96,
            },
        ],
    )

    assert all_bad["trusted_count"] == 0
    assert all_bad["bad_url_hit_count"] == 4
    assert clean["quality_score"] > all_bad["quality_score"]


def test_candidate_query_quality_filters_bdi_old_circular_when_data_page_exists():
    task = {
        "indicator_key": "bdi",
        "preferred_domains": ["tradingeconomics.com", "balticexchange.com"],
        "good_url_patterns": ["tradingeconomics.com"],
        "bad_url_patterns": ["/Circulars/", "2018"],
        "evidence_keywords": ["BDI", "Baltic Dry Index", "latest", "points"],
    }
    candidate = {"query": "BDI Baltic Dry Index latest value", "preferred_domains": task["preferred_domains"]}
    snippets = [
        {
            "url": "https://www.balticexchange.com/en/data-services/market-information0/dry-services/Circulars/2018.html",
            "content": "Baltic Exchange circular archive 2018 for dry services.",
            "score": 0.93,
        },
        {
            "url": "https://tradingeconomics.com/commodity/baltic",
            "content": "Baltic Dry Index latest value is 1350 points with daily change.",
            "score": 0.71,
        },
    ]

    quality = _candidate_query_quality(task, candidate, snippets)

    assert quality["usable_count"] == 1
    assert quality["snippets"][0]["url"] == "https://tradingeconomics.com/commodity/baltic"
    assert quality["bad_url_hit_count"] == 1


def test_validate_fund_flow_direction_outflow():
    extraction = {"value": 12.0, "unit": "亿元", "note": "近5日净流出，总览"}
    val, manual, note = _validate_fund_flow_extraction(extraction, indicator_key="northbound")
    assert val == -12.0
    assert manual is False
    assert "方向" not in (note or "")


def test_validate_fund_flow_missing_unit_marks_manual():
    extraction = {"value": 5, "unit": "", "note": "净流入"}
    val, manual, note = _validate_fund_flow_extraction(extraction, indicator_key="northbound")
    assert manual is True
    assert "单位缺失" in (note or "")
    assert val == 5


def test_validate_fund_flow_placeholder_100_marks_manual():
    extraction = {"value": 100.0, "unit": "亿元", "note": "净流入"}
    val, manual, note = _validate_fund_flow_extraction(extraction, indicator_key="northbound")
    assert val == 100.0
    assert manual is True
    assert "疑似占位值" in (note or "")


def test_apply_extraction_writes_to_array_sections():
    payload = {
        "metadata": {"date": "2026-02-06"},
        "macro_indicators": {},
        "monetary_policy": {},
        "forex": [{"pair": "USDCNY", "current_rate": None, "source": ""}],
        "commodities": [{"symbol": "CL=F", "current_price": None, "source": ""}],
        "bonds": [{"symbol": "CN10Y", "current_yield": None, "source": ""}],
    }
    task_fx = {"indicator_key": "USDCNY", "task_id": "t-fx"}
    task_cmdty = {"indicator_key": "CL=F", "task_id": "t-cmdty"}
    task_bond = {"indicator_key": "CN10Y", "task_id": "t-bond"}

    cat_fx = _apply_extraction(payload, task_fx, {"value": 7.12, "note": "ok", "source_url": "https://example.com"})
    cat_cmdty = _apply_extraction(payload, task_cmdty, {"value": 72.5, "note": "ok", "source_url": "https://example.com"})
    cat_bond = _apply_extraction(payload, task_bond, {"value": 2.15, "note": "ok", "source_url": "https://example.com"})

    assert cat_fx == "forex"
    assert cat_cmdty == "commodities"
    assert cat_bond == "bonds"
    assert payload["forex"][0]["current_rate"] == pytest.approx(7.12)
    assert payload["commodities"][0]["current_price"] == pytest.approx(72.5)
    assert payload["bonds"][0]["current_yield"] == pytest.approx(2.15)


def test_apply_extraction_upserts_forex_when_section_missing_item():
    payload = {
        "metadata": {"date": "2026-02-06"},
        "macro_indicators": {},
        "monetary_policy": {},
        "forex": [],
        "commodities": [],
        "bonds": [],
    }
    task_fx = {"indicator_key": "USDCNY", "task_id": "t-fx-upsert"}
    category = _apply_extraction(
        payload,
        task_fx,
        {"value": 6.98, "note": "ok", "source_url": "https://example.com"},
    )
    assert category == "forex_upsert"
    assert payload["forex"]
    assert payload["forex"][0]["pair"] == "USDCNY"
    assert payload["forex"][0]["current_rate"] == pytest.approx(6.98)



def test_apply_extraction_bdi_trusted_source_clears_estimated_and_missing():
    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        "metadata": {
            "date": today,
            "missing_items": {"macro_indicators": [{"key": "bdi", "reason": "estimated_not_allowed"}]},
        },
        "missing_items": ["bdi"],
        "macro_indicators": {
            "bdi": {
                "indicator_name": "BDI",
                "current_value": None,
                "unit": "points",
                "date": today,
                "is_estimated": True,
                "source": "tavily+deepseek",
            }
        },
        "monetary_policy": {},
        "forex": [],
        "commodities": [],
        "bonds": [],
    }
    task = {"indicator_key": "bdi", "task_id": "t-bdi"}

    category = _apply_extraction(
        payload,
        task,
        {
            "value": 2233.0,
            "unit": "points",
            "as_of_date": today,
            "source_url": "https://www.tradingeconomics.com/commodity/baltic",
            "note": "verified",
        },
    )
    _update_missing_items(payload, "bdi")

    assert category == "macro_indicators"
    assert payload["macro_indicators"]["bdi"]["is_estimated"] is False
    assert payload["missing_items"] == []
    assert payload["metadata"]["missing_items"] == {}
def test_flag_fund_flow_anomalies_marks_placeholder_pair():
    payload = {
        "fund_flow": {
            "northbound": {"recent_5d": 100.0, "total_120d": 100.0, "source": "tavily+deepseek"},
        }
    }
    flagged = _flag_fund_flow_anomalies(payload)
    assert "northbound" in flagged
    assert payload["fund_flow"]["northbound"]["source"] == "异常零值-需核查"
    assert "疑似占位值" in payload["fund_flow"]["northbound"]["note"]


def test_execute_tasks_legacy_mcp_backend_still_searches(tmp_path: Path):
    # 历史 mcp backend 配置应被忽略，仍走 tavily 搜索
    payload = {"fund_flow": {"northbound": {"recent_5d": None, "total_120d": None}}}
    task = {
        "task_id": "t1",
        "indicator_key": "northbound",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "mcp",
        "preferred_domains": [],
        "time_range": None,
        "query": None,
        "unit": "亿元",
        "issuer": None,
        "retry_count": 0,
        "created_at": 0,
    }

    class DummyClient:
        def __init__(self):
            self.called = 0

        async def search(self, *args, **kwargs):
            self.called += 1
            return {
                "results": [
                    {
                        "url": "https://data.eastmoney.com/hsgt/",
                        "snippet": "北向资金近5日净流入 12.3 亿元，近120日累计 456.7 亿元",
                        "content": "北向资金近5日净流入 12.3 亿元，近120日累计 456.7 亿元",
                        "score": 0.9,
                    }
                ]
            }

    class DummyExtractor:
        async def extract(self, *args, **kwargs):
            return {
                "value": 12.3,
                "unit": "亿元",
                "source_url": "https://data.eastmoney.com/hsgt/",
                "confidence": 0.9,
                "manual_required": False,
                "recent_5d": 12.3,
                "total_120d": 456.7,
                "trend": "inflow",
            }

    client = DummyClient()
    completed, failures, _ = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            client,
            None,
            DummyExtractor(),
            tmp_path / "log.jsonl",
            cache_ttl=10,
            fund_flow_backend="mcp",
        )
    )
    assert client.called == 1
    assert completed
    assert not failures


def test_execute_tasks_keeps_fund_flow_gate_blocker_after_estimated_writeback(tmp_path: Path):
    payload = {
        "metadata": {
            "date": "2026-03-06",
            "missing_items": {"fund_flow": [{"key": "etf", "reason": "estimated_not_allowed"}]},
        },
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None, "is_estimated": False}},
        "missing_items": ["etf"],
    }
    task = {
        "task_id": "fund_flow.etf",
        "indicator_key": "etf",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "preferred_domains": ["data.eastmoney.com"],
        "time_range": None,
        "query": "A股ETF资金流向",
        "unit": "亿元",
        "issuer": "沪深交易所",
        "retry_count": 0,
        "created_at": 0,
    }

    class DummyClient:
        async def search(self, *args, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://data.eastmoney.com/etf/",
                        "snippet": "A股ETF资金流向结构化入口。",
                        "content": "A股ETF资金流向结构化入口。",
                        "score": 0.9,
                    }
                ]
            }

    class DummyExtractor:
        async def extract(self, *args, **kwargs):
            return {
                "value": 85.0,
                "unit": "亿元",
                "source_url": "https://data.eastmoney.com/etf/",
                "confidence": 0.9,
                "manual_required": False,
                "manual_reason": None,
                "recent_5d": 85.0,
                "total_120d": 1200.0,
                "trend": "inflow",
                "note": "deepseek_structured 流入",
            }

    completed, failures, results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            DummyClient(),
            None,
            DummyExtractor(),
            tmp_path / "gate_after_writeback.jsonl",
            cache_ttl=10,
            disable_extract=True,
            extraction_backend="deepseek",
        )
    )

    assert not completed
    assert failures
    assert failures[0]["manual_required"] is True
    assert failures[0]["manual_reason"] == "estimated_not_allowed"
    assert results[0]["manual_required"] is True
    assert results[0]["manual_reason"] == "estimated_not_allowed"
    assert payload["fund_flow"]["etf"]["is_estimated"] is True
    assert payload["metadata"]["missing_items"]["fund_flow"] == [
        {"key": "etf", "reason": "estimated_not_allowed"}
    ]
    assert payload["missing_items"] == ["etf"]


def test_lc_execute_tasks_keeps_fund_flow_gate_blocker_after_estimated_writeback(tmp_path: Path):
    if stage2.run_tasks_lc is None:
        pytest.skip("langchain pipeline unavailable")

    payload = {
        "metadata": {
            "date": "2026-03-06",
            "missing_items": {"fund_flow": [{"key": "etf", "reason": "estimated_not_allowed"}]},
        },
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None, "is_estimated": False}},
        "missing_items": ["etf"],
    }
    task = {
        "task_id": "fund_flow.etf",
        "indicator_key": "etf",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "preferred_domains": ["data.eastmoney.com"],
        "time_range": None,
        "query": "A股ETF资金流向",
        "unit": "亿元",
        "issuer": "沪深交易所",
        "created_at": 0,
    }

    class DummyClient:
        async def search(self, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://data.eastmoney.com/etf/",
                        "snippet": "A股ETF资金流向结构化入口。",
                        "content": "A股ETF资金流向结构化入口。",
                        "score": 0.9,
                    }
                ]
            }

        async def extract(self, **kwargs):
            return {"status": 422, "results": []}

    class DummyExtractor:
        async def extract(self, *args, **kwargs):
            return {
                "value": 85.0,
                "unit": "亿元",
                "source_url": "https://data.eastmoney.com/etf/",
                "confidence": 0.9,
                "recent_5d": 85.0,
                "total_120d": 1200.0,
                "trend": "inflow",
                "note": "deepseek_structured 流入",
            }

    completed, failures, results = asyncio.run(
        stage2.run_tasks_lc(
            [task],
            payload,
            DummyClient(),
            DummyExtractor(),
            tmp_path / "lc_gate_after_writeback.jsonl",
            cache_ttl=10,
            max_retries=1,
            fund_flow_backend="tavily",
            forex_backend="tavily",
            lc_max_concurrency=1,
            deepseek_timeout=None,
            llm_hard_timeout=None,
        )
    )

    assert not completed
    assert failures
    assert failures[0]["manual_required"] is True
    assert failures[0]["manual_reason"] == "estimated_not_allowed"
    assert results[0]["manual_required"] is True
    assert results[0]["manual_reason"] == "estimated_not_allowed"
    assert payload["fund_flow"]["etf"]["is_estimated"] is True
    assert payload["missing_items"] == ["etf"]


def test_execute_tasks_force_refresh_ignores_existing_value_skip(tmp_path: Path):
    payload = {
        "macro_indicators": {
            "cpi": {
                "current_value": 1.2,
                "is_stale": True,
                "expected_period": "2026-02",
            }
        },
        "missing_items": [{"key": "cpi", "reason": "stale_data"}],
    }
    task = {
        "task_id": "t-force-refresh",
        "indicator_key": "cpi",
        "stage_phase": "essential",
        "search_backend": "tavily",
        "preferred_domains": ["stats.gov.cn"],
        "query": "中国CPI 最新公布 国家统计局",
        "unit": "%",
        "issuer": "国家统计局",
        "retry_count": 0,
        "created_at": 0,
        "trigger_reason": "stale_data",
        "force_refresh": True,
    }

    class DummyClient:
        def __init__(self):
            self.called = 0

        async def search(self, *args, **kwargs):
            self.called += 1
            return {
                "results": [
                    {
                        "url": "https://www.stats.gov.cn/cpi",
                        "snippet": "国家统计局公布 CPI 同比上涨 0.9%",
                        "content": "国家统计局公布 CPI 同比上涨 0.9%",
                        "score": 0.95,
                    }
                ]
            }

    class DummyExtractor:
        async def extract(self, *args, **kwargs):
            return {
                "value": 0.9,
                "unit": "%",
                "source_url": "https://www.stats.gov.cn/cpi",
                "confidence": 0.9,
                "manual_required": False,
                "manual_reason": None,
            }

    client = DummyClient()
    completed, failures, results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            client,
            None,
            DummyExtractor(),
            tmp_path / "force_refresh.jsonl",
            cache_ttl=10,
            disable_extract=True,
            extraction_backend="deepseek",
        )
    )
    assert client.called == 1
    assert completed
    assert not failures
    assert results[0]["result_type"] == "search_success"
    assert results[0]["extraction"].get("note") != "existing_value"


def test_execute_tasks_usdcny_extract_uses_official_domain_before_topk(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-12"},
        "forex": [{"pair": "USDCNY", "current_rate": None, "source": ""}],
        "missing_items": [{"key": "USDCNY"}],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == "USDCNY")

    class DummyClient:
        def __init__(self):
            self.extract_inputs = []

        async def search(self, *args, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://www.investing.com/currencies/usd-cny",
                        "snippet": "USD/CNY 7.18 onshore spot rate",
                        "content": "USD/CNY 7.18 onshore spot rate",
                        "score": 0.99,
                    },
                    {
                        "url": "https://www.chinamoney.com.cn/chinese/bkccpr/",
                        "snippet": "ChinaMoney USD/CNY onshore spot rate 7.12",
                        "content": "ChinaMoney USD/CNY onshore spot rate 7.12",
                        "score": 0.75,
                    },
                ]
            }

        async def extract(self, **kwargs):
            self.extract_inputs.append(kwargs["search_results"])
            return {
                "results": [
                    {
                        "url": "https://www.chinamoney.com.cn/chinese/bkccpr/",
                        "content": "ChinaMoney USD/CNY onshore spot rate 7.12",
                        "score": 0.75,
                    }
                ]
            }

    class DummyExtractor:
        async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
            assert any("chinamoney.com.cn" in (s.get("url") or "") for s in snippets)
            return {
                "value": 7.12,
                "unit": "",
                "source_url": "https://www.chinamoney.com.cn/chinese/bkccpr/",
                "confidence": 0.9,
                "manual_required": False,
                "manual_reason": None,
            }

    client = DummyClient()
    completed, failures, _ = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            client,
            None,
            DummyExtractor(),
            tmp_path / "usdcny_extract.jsonl",
            cache_ttl=10,
            extraction_backend="deepseek",
        )
    )

    assert completed or failures
    assert client.extract_inputs
    assert all(len(items) == 1 for items in client.extract_inputs)
    assert all("chinamoney.com.cn" in items[0]["url"] for items in client.extract_inputs)


def test_execute_tasks_usdcny_extract_skips_when_official_filter_empty(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-12"},
        "forex": [{"pair": "USDCNY", "current_rate": None, "source": ""}],
        "missing_items": [{"key": "USDCNY"}],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == "USDCNY")

    class DummyClient:
        def __init__(self):
            self.extract_called = False

        async def search(self, *args, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://fakechinamoney.com.cn/chinese/bkccpr/",
                        "snippet": "USD/CNY 7.1234 fake official-looking table",
                        "content": "USD/CNY 7.1234 fake official-looking table",
                        "score": 0.99,
                    },
                    {
                        "url": "https://www.investing.com/currencies/usd-cny",
                        "snippet": "USD/CNY market quote 7.19",
                        "content": "USD/CNY market quote 7.19",
                        "score": 0.88,
                    },
                ]
            }

        async def extract(self, **kwargs):
            self.extract_called = True
            raise AssertionError("extract should not run without official snippets")

    class DummyExtractor:
        def __init__(self):
            self.called = False

        async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
            self.called = True
            return {
                "value": 7.18,
                "unit": "",
                "source_url": "https://fakechinamoney.com.cn/chinese/bkccpr/",
                "confidence": 0.95,
                "manual_required": False,
                "manual_reason": None,
            }

    client = DummyClient()
    extractor = DummyExtractor()
    stats = {}
    completed, failures, websearch_results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            client,
            None,
            extractor,
            tmp_path / "usdcny_extract_no_official.jsonl",
            cache_ttl=10,
            extraction_backend="deepseek",
            stats=stats,
        )
    )

    assert not completed
    assert failures
    assert stats["regex_hits"] == 0
    assert client.extract_called is False
    assert extractor.called is False
    assert websearch_results[-1]["extraction"]["value"] is None
    rows = [
        json.loads(line)
        for line in (tmp_path / "usdcny_extract_no_official.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows
    assert rows[-1]["manual_required"] is True
    assert rows[-1]["manual_reason"] == "skipped_deepseek:official_domain_filter_empty"
    assert rows[-1]["extraction_skipped_reason"] == "official_domain_filter_empty"
    assert rows[-1]["extract_skipped_reason"] == "official_domain_filter_empty"
    assert payload["forex"][0].get("current_rate") is None


def test_execute_tasks_refreshes_value_diagnostics_after_final_snippet_filtering(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-13"},
        "commodities": [{"symbol": "BCOM", "current_price": None, "source": ""}],
        "missing_items": [{"key": "BCOM"}],
    }
    task = {
        "task_id": "bcom-final-diagnostics",
        "indicator_key": "BCOM",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "query": "BCOM last price level",
        "queries": ["BCOM last price level"],
        "unit": "points",
        "issuer": "Bloomberg",
        "preferred_domains": [],
        "required_output_fields": ["current_price"],
        "evidence_keywords": ["last price", "level", "points"],
        "retry_count": 0,
        "created_at": 0,
        "trigger_reason": "missing",
        "max_age_days": 30,
        "extract_policy": {"use_tavily_extract": True, "extract_topk": 1},
    }

    class DummyClient:
        async def search(self, *args, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://example.com/bcom-old-quote",
                        "title": "BCOM quote",
                        "content": "BCOM last price was 101.25 points on 2025-01-01.",
                        "score": 0.72,
                    }
                ]
            }

        async def extract(self, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://example.com/bcom-methodology",
                        "content": (
                            "2026-05-13 BCOM methodology calculation weights rebalance "
                            "rulebook uses a 100 baseline."
                        ),
                        "score": 0.95,
                    }
                ]
            }

    class DummyExtractor:
        def __init__(self):
            self.snippets = None

        async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
            self.snippets = snippets
            return {
                "value": None,
                "unit": unit_hint,
                "source_url": None,
                "confidence": 0.0,
                "manual_required": True,
                "manual_reason": "no_value",
                "llm_latency_ms": 0,
            }

    extractor = DummyExtractor()
    completed, failures, websearch_results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            DummyClient(),
            None,
            extractor,
            tmp_path / "bcom_final_diagnostics.jsonl",
            cache_ttl=10,
            extraction_backend="deepseek",
            stats={},
        )
    )

    assert not completed
    assert failures
    assert extractor.snippets
    assert [s["url"] for s in extractor.snippets] == ["https://example.com/bcom-methodology"]

    final_task = websearch_results[-1]["task"]
    assert final_task["value_evidence_score"] == 0
    assert final_task["usage_evidence_score"] == 0
    assert final_task["score_stats"]["score_count"] == 1
    assert final_task["score_stats"]["score_max"] == 0.95
    assert "value_evidence=0" in final_task["selected_reason"]
    assert "value_evidence=8" not in final_task["selected_reason"]
    assert "score_max=0.95" in final_task["selected_reason"]
    assert "score_max=0.72" not in final_task["selected_reason"]
    assert websearch_results[-1]["raw_results"][0]["url"] == "https://example.com/bcom-methodology"

    rows = [
        json.loads(line)
        for line in (tmp_path / "bcom_final_diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["value_evidence_score"] == 0
    assert rows[-1]["usage_evidence_score"] == 0
    assert rows[-1]["score_count"] == 1
    assert rows[-1]["score_max"] == 0.95
    assert "value_evidence=0" in rows[-1]["selected_reason"]
    assert "value_evidence=8" not in rows[-1]["selected_reason"]
    assert "score_max=0.95" in rows[-1]["selected_reason"]
    assert "score_max=0.72" not in rows[-1]["selected_reason"]


def test_execute_tasks_keeps_low_score_value_evidence_before_deepseek(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-13"},
        "commodities": [{"symbol": "BCOM", "current_price": None, "source": ""}],
        "missing_items": [{"key": "BCOM"}],
    }
    task = {
        "task_id": "bcom-final-value-evidence",
        "indicator_key": "BCOM",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "query": "BCOM last price level",
        "queries": ["BCOM last price level"],
        "unit": "points",
        "issuer": "Bloomberg",
        "preferred_domains": [],
        "required_output_fields": ["current_price"],
        "evidence_keywords": ["last price", "level", "points"],
        "retry_count": 0,
        "created_at": 0,
        "trigger_reason": "missing",
        "max_age_days": 30,
        "extract_policy": {"use_tavily_extract": True, "extract_topk": 1},
    }

    class DummyClient:
        async def search(self, *args, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://example.com/bcom-search",
                        "title": "BCOM quote search result",
                        "content": "BCOM last price page for 2026-05-13.",
                        "score": 0.72,
                    },
                ]
            }

        async def extract(self, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://example.com/bcom-quote",
                        "content": "BCOM last price was 101.25 points on 2026-05-13.",
                        "score": 0.28,
                    },
                    {
                        "url": "https://example.com/bcom-overview",
                        "content": "Bloomberg Commodity Index tracks diversified commodity futures markets.",
                        "score": 0.95,
                    },
                ]
            }

    class DummyExtractor:
        def __init__(self):
            self.snippets = None

        async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
            self.snippets = snippets
            return {
                "value": None,
                "unit": unit_hint,
                "source_url": None,
                "confidence": 0.0,
                "manual_required": True,
                "manual_reason": "no_value",
                "llm_latency_ms": 0,
            }

    extractor = DummyExtractor()
    completed, failures, websearch_results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            DummyClient(),
            None,
            extractor,
            tmp_path / "bcom_final_value_evidence.jsonl",
            cache_ttl=10,
            extraction_backend="deepseek",
            stats={},
        )
    )

    assert not completed
    assert failures
    assert extractor.snippets
    assert any(s["url"] == "https://example.com/bcom-quote" for s in extractor.snippets)

    final_task = websearch_results[-1]["task"]
    assert final_task["value_evidence_score"] > 0
    assert "value_evidence=0" not in final_task["selected_reason"]

    rows = [
        json.loads(line)
        for line in (tmp_path / "bcom_final_value_evidence.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["value_evidence_score"] > 0
    assert "value_evidence=0" not in rows[-1]["selected_reason"]


def test_execute_tasks_skip_existing_value_clears_missing_items_and_marks_result_type(tmp_path: Path):
    payload = {
        "fund_flow": {
            "northbound": {"recent_5d": 10.0, "total_120d": 20.0, "source": "tushare"}
        },
        "missing_items": [{"key": "northbound", "reason": "manual_missing"}],
        "metadata": {"missing_items": {"fund_flow": [{"key": "northbound"}]}},
    }
    task = {
        "task_id": "t-skip-existing",
        "indicator_key": "northbound",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "preferred_domains": [],
        "query": "北向资金 月度净流入",
        "unit": "亿元",
        "issuer": None,
        "retry_count": 0,
        "created_at": 0,
        "trigger_reason": "missing",
    }

    class NeverCalledClient:
        async def search(self, *args, **kwargs):  # pragma: no cover - 不应执行
            raise AssertionError("search should not be called")

    completed, failures, results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            NeverCalledClient(),
            None,
            object(),
            tmp_path / "skip_existing.jsonl",
            cache_ttl=10,
        )
    )
    assert completed
    assert not failures
    assert results[0]["result_type"] == "skipped_existing"
    assert payload["missing_items"] == []
    assert payload["metadata"]["missing_items"] == {}


def test_execute_tasks_etf_field_retry_fills_missing_windows(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-03-06"},
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None, "source": ""}},
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == "etf")
    stats = {}

    class DummyClient:
        async def search(self, query, **kwargs):
            if "近120日" in query or "年内累计" in query:
                snippet = "A股ETF近120日累计净流入1200亿元"
            elif "近5日" in query:
                snippet = "A股ETF近5日净流入85亿元"
            else:
                snippet = "A股ETF近5日净流入85亿元"
            return {
                "results": [
                    {
                        "url": "https://data.eastmoney.com/etf",
                        "snippet": snippet,
                        "content": snippet,
                        "score": 0.88,
                    }
                ]
            }

    class DummyExtractor:
        def __init__(self):
            self.calls = 0

        async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "value": None,
                    "unit": "亿元",
                    "source_url": "https://data.eastmoney.com/etf",
                    "confidence": 0.9,
                    "note": "primary_missing_windows",
                    "manual_required": True,
                    "manual_reason": "fund_flow_window_missing",
                    "recent_5d": None,
                    "total_120d": None,
                    "trend": "inflow",
                }
            text = " ".join(str(s.get("content") or s.get("snippet") or "") for s in snippets)
            if "近120日" in text or "累计" in text:
                return {
                    "value": 1200.0,
                    "unit": "亿元",
                    "source_url": "https://data.eastmoney.com/etf",
                    "confidence": 0.9,
                    "note": "field_total",
                    "manual_required": False,
                    "manual_reason": None,
                    "recent_5d": None,
                    "total_120d": 1200.0,
                    "trend": "inflow",
                }
            return {
                "value": 85.0,
                "unit": "亿元",
                "source_url": "https://data.eastmoney.com/etf",
                "confidence": 0.9,
                "note": "field_recent",
                "manual_required": True,
                "manual_reason": "fund_flow_window_missing",
                "recent_5d": 85.0,
                "total_120d": None,
                "trend": "inflow",
            }

    completed, failures, _ = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            DummyClient(),
            None,
            DummyExtractor(),
            tmp_path / "field_retry_log.jsonl",
            cache_ttl=10,
            disable_extract=True,
            extraction_backend="deepseek",
            stats=stats,
        )
    )
    assert completed
    assert not failures
    assert payload["fund_flow"]["etf"]["recent_5d"] == pytest.approx(85.0)
    assert payload["fund_flow"]["etf"]["total_120d"] == pytest.approx(1200.0)
    assert payload["fund_flow"]["etf"]["trend"] == "流入"
    assert payload["fund_flow"]["etf"]["window_evidence"] == "direct_window"
    assert payload["fund_flow"]["etf"]["is_estimated"] is False
    assert stats["field_retry_count"] == 2
    assert stats["field_retry_merged_count"] == 2
    assert stats["field_retry_missing_fields"]["etf"] == ["recent_5d", "total_120d"]


def test_execute_tasks_field_retry_tier3_sources_do_not_clear_fund_flow_gate(tmp_path: Path):
    payload = {
        "metadata": {
            "date": "2026-03-06",
            "missing_items": {"fund_flow": [{"key": "northbound", "reason": "estimated_not_allowed"}]},
        },
        "fund_flow": {"northbound": {"recent_5d": None, "total_120d": None, "is_estimated": False}},
        "missing_items": ["northbound"],
    }
    task = {
        "task_id": "fund_flow.northbound",
        "indicator_key": "northbound",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "preferred_domains": ["data.eastmoney.com", "10jqka.com.cn"],
        "time_range": None,
        "query": "北向资金 沪深港通 东方财富",
        "field_queries": {
            "recent_5d": ["北向资金 近5日 净流入 亿元 同花顺"],
            "total_120d": ["北向资金 近120日 累计净流入 亿元 同花顺"],
        },
        "required_keywords": ["北向资金"],
        "evidence_keywords": ["北向资金", "近5日", "近120日", "净流入", "累计"],
        "good_url_patterns": ["data.eastmoney.com", "hkex.com.hk"],
        "bad_url_patterns": ["个股", "十大活跃股"],
        "unit": "亿元",
        "issuer": None,
        "created_at": 0,
    }

    class DummyClient:
        async def search(self, query, **kwargs):
            if "近120日" in query:
                return {
                    "results": [
                        {
                            "url": "https://data.eastmoney.com/hsgt/",
                            "snippet": "东方财富沪深港通近120日净流入统计页面。",
                            "content": "东方财富沪深港通近120日净流入统计页面。",
                            "score": 0.95,
                        },
                        {
                            "url": "https://data.10jqka.com.cn/hgt/hgtb/",
                            "snippet": "北向资金近120日累计净流入456.7亿元",
                            "content": "北向资金近120日累计净流入456.7亿元",
                            "score": 0.9,
                        },
                    ]
                }
            elif "近5日" in query:
                return {
                    "results": [
                        {
                            "url": "https://data.eastmoney.com/hsgt/",
                            "snippet": "东方财富沪深港通近5日净流入统计页面。",
                            "content": "东方财富沪深港通近5日净流入统计页面。",
                            "score": 0.95,
                        },
                        {
                            "url": "https://data.10jqka.com.cn/hgt/hgtb/",
                            "snippet": "北向资金近5日净流入12.3亿元",
                            "content": "北向资金近5日净流入12.3亿元",
                            "score": 0.9,
                        },
                    ]
                }
            snippet = "东方财富沪深港通入口，北向资金今日净流入12.3亿元，未披露近5日和近120日窗口。"
            url = "https://data.eastmoney.com/hsgt/"
            return {"results": [{"url": url, "snippet": snippet, "content": snippet, "score": 0.9}]}

    class DummyExtractor:
        async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
            text = " ".join(str(s.get("content") or s.get("snippet") or "") for s in snippets)
            source_url = snippets[0].get("url")
            if "456.7" in text:
                return {
                    "value": 456.7,
                    "unit": "亿元",
                    "source_url": "https://data.eastmoney.com/hsgt/",
                    "confidence": 0.9,
                    "total_120d": 456.7,
                    "trend": "inflow",
                    "note": f"field_total 流入 model_url_spoofed_from:{source_url}",
                }
            if "12.3" in text and "未披露" not in text:
                return {
                    "value": 12.3,
                    "unit": "亿元",
                    "source_url": "https://data.eastmoney.com/hsgt/",
                    "confidence": 0.9,
                    "recent_5d": 12.3,
                    "trend": "inflow",
                    "note": f"field_recent 流入 model_url_spoofed_from:{source_url}",
                }
            return {
                "value": 12.3,
                "unit": "亿元",
                "source_url": source_url,
                "confidence": 0.9,
                "recent_5d": None,
                "total_120d": None,
                "trend": "inflow",
                "note": "primary_missing_windows 流入",
            }

    completed, failures, results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            DummyClient(),
            None,
            DummyExtractor(),
            tmp_path / "field_retry_tier3_gate.jsonl",
            cache_ttl=10,
            disable_extract=True,
            extraction_backend="deepseek",
        )
    )

    assert not completed
    assert failures
    assert failures[0]["manual_required"] is True
    assert failures[0]["manual_reason"] == "estimated_not_allowed"
    northbound = payload["fund_flow"]["northbound"]
    assert northbound["source_url"] == "https://data.eastmoney.com/hsgt/"
    assert northbound["field_retry_evidence"]["recent_5d"]["source_tier"] == "tier3"
    assert northbound["field_retry_evidence"]["total_120d"]["source_tier"] == "tier3"
    assert northbound["is_estimated"] is True
    assert results[0]["manual_required"] is True


def test_execute_tasks_field_retry_ignores_window_length_numbers_as_value_evidence(tmp_path: Path):
    payload = {
        "metadata": {
            "date": "2026-03-06",
            "missing_items": {"fund_flow": [{"key": "northbound", "reason": "estimated_not_allowed"}]},
        },
        "fund_flow": {"northbound": {"recent_5d": None, "total_120d": None, "is_estimated": False}},
        "missing_items": ["northbound"],
    }
    task = {
        "task_id": "fund_flow.northbound",
        "indicator_key": "northbound",
        "stage_phase": "assets",
        "search_backend": "tavily",
        "fund_flow_backend": "tavily",
        "preferred_domains": ["data.eastmoney.com", "10jqka.com.cn"],
        "time_range": None,
        "query": "北向资金 沪深港通 东方财富",
        "field_queries": {
            "recent_5d": ["北向资金 近5日 净流入 亿元 同花顺"],
            "total_120d": ["北向资金 近120日 累计净流入 亿元 同花顺"],
        },
        "required_keywords": ["北向资金"],
        "evidence_keywords": ["北向资金", "近5日", "近120日", "净流入", "累计"],
        "good_url_patterns": ["data.eastmoney.com", "hkex.com.hk"],
        "bad_url_patterns": ["个股", "十大活跃股"],
        "unit": "亿元",
        "issuer": None,
        "created_at": 0,
    }

    class DummyClient:
        async def search(self, query, **kwargs):
            if "近120日" in query:
                return {
                    "results": [
                        {
                            "url": "https://data.eastmoney.com/hsgt/",
                            "snippet": "北向资金 东方财富沪深港通近120日净流入统计页面。",
                            "content": "北向资金 东方财富沪深港通近120日净流入统计页面。",
                            "score": 0.95,
                        },
                        {
                            "url": "https://data.10jqka.com.cn/hgt/hgtb/",
                            "snippet": "北向资金近120日累计净流入120.0亿元",
                            "content": "北向资金近120日累计净流入120.0亿元",
                            "score": 0.9,
                        },
                    ]
                }
            if "近5日" in query:
                return {
                    "results": [
                        {
                            "url": "https://data.eastmoney.com/hsgt/",
                            "snippet": "北向资金 东方财富沪深港通近5日净流入统计页面。",
                            "content": "北向资金 东方财富沪深港通近5日净流入统计页面。",
                            "score": 0.95,
                        },
                        {
                            "url": "https://data.10jqka.com.cn/hgt/hgtb/",
                            "snippet": "北向资金近5日净流入5.0亿元",
                            "content": "北向资金近5日净流入5.0亿元",
                            "score": 0.9,
                        },
                    ]
                }
            snippet = "东方财富沪深港通入口，北向资金今日净流入5.0亿元，未披露近5日和近120日窗口。"
            url = "https://data.eastmoney.com/hsgt/"
            return {"results": [{"url": url, "snippet": snippet, "content": snippet, "score": 0.9}]}

    class DummyExtractor:
        async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
            text = " ".join(str(s.get("content") or s.get("snippet") or "") for s in snippets)
            source_url = snippets[0].get("url")
            if "120.0亿元" in text:
                return {
                    "value": 120.0,
                    "unit": "亿元",
                    "source_url": "https://data.eastmoney.com/hsgt/",
                    "confidence": 0.9,
                    "total_120d": 120.0,
                    "trend": "inflow",
                    "note": f"field_total 流入 model_url_spoofed_from:{source_url}",
                }
            if "5.0亿元" in text and "未披露" not in text:
                return {
                    "value": 5.0,
                    "unit": "亿元",
                    "source_url": "https://data.eastmoney.com/hsgt/",
                    "confidence": 0.9,
                    "recent_5d": 5.0,
                    "trend": "inflow",
                    "note": f"field_recent 流入 model_url_spoofed_from:{source_url}",
                }
            return {
                "value": 5.0,
                "unit": "亿元",
                "source_url": source_url,
                "confidence": 0.9,
                "recent_5d": None,
                "total_120d": None,
                "trend": "inflow",
                "note": "primary_missing_windows 流入",
            }

    completed, failures, results = asyncio.run(
        _execute_tasks(
            [task],
            payload,
            DummyClient(),
            None,
            DummyExtractor(),
            tmp_path / "field_retry_window_length_gate.jsonl",
            cache_ttl=10,
            disable_extract=True,
            extraction_backend="deepseek",
        )
    )

    assert not completed
    assert failures
    assert failures[0]["manual_reason"] == "estimated_not_allowed"
    northbound = payload["fund_flow"]["northbound"]
    assert northbound["field_retry_evidence"]["recent_5d"]["source_tier"] == "tier3"
    assert northbound["field_retry_evidence"]["total_120d"]["source_tier"] == "tier3"
    assert northbound["is_estimated"] is True
    assert results[0]["manual_required"] is True
