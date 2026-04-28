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
    _execute_tasks,
)


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
        exec_stats={"tavily_unavailable_reason": "quota_or_rate_limit"},
    )

    assert summary_fields["tavily_unavailable_reason"] == "quota_or_rate_limit"


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


def test_bdi_profile_prioritizes_latest_market_data_family():
    profile = SEARCH_PROFILES["bdi"]
    first_family = profile["query_families"][0]

    assert first_family["name"] == "latest_market_data"
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
        "preferred_domains": ["data.eastmoney.com", "fund.eastmoney.com", "eastmoney.com"],
        "good_url_patterns": ["data.eastmoney.com", "fund.eastmoney.com"],
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


def test_candidate_query_quality_penalizes_all_bad_trusted_results_below_clean_data_page():
    task = {
        "indicator_key": "etf",
        "preferred_domains": ["data.eastmoney.com", "fund.eastmoney.com", "eastmoney.com"],
        "good_url_patterns": ["data.eastmoney.com", "fund.eastmoney.com"],
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

    assert all_bad["trusted_count"] == 4
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
                        "url": "https://example.com/northbound",
                        "snippet": "北向资金近5日净流入 12.3 亿元，近120日累计 456.7 亿元",
                        "score": 0.9,
                    }
                ]
            }

    class DummyExtractor:
        async def extract(self, *args, **kwargs):
            return {
                "value": 12.3,
                "unit": "亿元",
                "source_url": "https://example.com/northbound",
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
        async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
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
        )
    )
    assert completed
    assert not failures
    assert payload["fund_flow"]["etf"]["recent_5d"] == pytest.approx(85.0)
    assert payload["fund_flow"]["etf"]["total_120d"] == pytest.approx(1200.0)
    assert payload["fund_flow"]["etf"]["trend"] == "流入"
