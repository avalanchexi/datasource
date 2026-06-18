import asyncio
from pathlib import Path

from datasource.providers.stage2_structured.base import (
    StructuredProviderError,
    StructuredResult,
)
from datasource.engines.stage2.diagnostics import (
    _build_stage2_summary_diagnostics,
    _stage2_effective_hit_rate,
)
from datasource.engines.stage2.execution import _execute_tasks


P0_SUCCESS = {
    "GC=F": (
        "commodities",
        {"value": 3367.8, "unit": "$/oz"},
        "https://finance.yahoo.com/quote/GC=F",
    ),
    "CL=F": (
        "commodities",
        {"value": 61.5, "unit": "$/bbl"},
        "https://finance.yahoo.com/quote/CL=F",
    ),
    "BZ=F": (
        "commodities",
        {"value": 64.8, "unit": "$/bbl"},
        "https://finance.yahoo.com/quote/BZ=F",
    ),
    "HG=F": (
        "commodities",
        {"value": 4.9, "unit": "$/lb"},
        "https://finance.yahoo.com/quote/HG=F",
    ),
    "GSG": (
        "commodities",
        {"value": 22.1, "unit": "USD"},
        "https://finance.yahoo.com/quote/GSG",
    ),
    "USDCNY": (
        "forex",
        {"value": 7.1138, "unit": ""},
        "https://www.chinamoney.com.cn/chinese/bkccpr/",
    ),
    "DXY": (
        "forex",
        {"value": 99.1, "unit": "points"},
        "https://tradingeconomics.com/united-states/currency",
    ),
    "CN10Y_CDB": (
        "bonds",
        {"value": 2.038, "unit": "%"},
        "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/more?locale=cn_ZH",
    ),
    "industrial": (
        "macro_indicators",
        {
            "value": 6.1,
            "unit": "%",
            "value_type": "yoy_month",
            "report_period": "2026-04",
        },
        "https://www.stats.gov.cn/sj/zxfb/",
    ),
    "industrial_sales": (
        "macro_indicators",
        {
            "value": 5.0,
            "unit": "%",
            "value_type": "yoy_ytd",
            "report_period": "2026-04",
        },
        "https://www.stats.gov.cn/sj/zxfb/",
    ),
    "bdi": (
        "macro_indicators",
        {"value": 1346.0, "unit": "points"},
        "https://tradingeconomics.com/commodity/baltic",
    ),
    "reverse_repo": (
        "monetary_policy",
        {"value": 1.4, "unit": "%"},
        "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125434/125798/index.html",
    ),
    "mlf": (
        "monetary_policy",
        {"value": 2.0, "unit": "%"},
        "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125437/125446/125873/index.html",
    ),
}


TASK_CATEGORIES = {
    "GC=F": "commodities",
    "CL=F": "commodities",
    "BZ=F": "commodities",
    "HG=F": "commodities",
    "BCOM": "commodities",
    "GSG": "commodities",
    "USDCNY": "forex",
    "DXY": "forex",
    "CN10Y_CDB": "bonds",
    "industrial": "macro_indicators",
    "industrial_sales": "macro_indicators",
    "bdi": "macro_indicators",
    "reverse_repo": "monetary_policy",
    "mlf": "monetary_policy",
    "etf": "fund_flow",
}


WRITEBACK_TARGETS = {
    "GC=F": "commodities",
    "CL=F": "commodities",
    "BZ=F": "commodities",
    "HG=F": "commodities",
    "GSG": "commodities",
    "USDCNY": "forex",
    "DXY": "forex",
    "CN10Y_CDB": "bonds",
    "industrial": "macro_indicators",
    "industrial_sales": "macro_indicators",
    "bdi": "macro_indicators",
    "reverse_repo": "monetary_policy",
    "mlf": "monetary_policy",
}


class GoldenRegistry:
    async def fetch(self, task, market_payload, reference_date):
        key = task["indicator_key"]
        if key not in P0_SUCCESS:
            raise StructuredProviderError(
                provider="golden",
                indicator_key=key,
                reason="missing_value",
                message="golden fixture has no structured value",
            )

        category, payload, source_url = P0_SUCCESS[key]
        tier = (
            "tier1"
            if any(
                host in source_url
                for host in (
                    "pbc.gov.cn",
                    "chinamoney.com.cn",
                    "stats.gov.cn",
                    "chinabond.com.cn",
                )
            )
            else "tier2"
        )
        return StructuredResult(
            provider="golden",
            indicator_key=key,
            category=category,
            payload=payload,
            source="golden fixture",
            source_url=source_url,
            source_tier=tier,
            as_of_date=None if "report_period" in payload else "2026-05-22",
            confidence=0.95,
        )


class ManualSearchClient:
    async def search(self, *args, **kwargs):
        return {"results": []}

    async def extract(self, *args, **kwargs):
        return {"results": []}


class ManualExtractor:
    async def extract(self, *args, **kwargs):
        return {
            "value": None,
            "unit": "",
            "manual_required": True,
            "manual_reason": "no_value",
        }


def _market_payload():
    keys = [
        "GC=F",
        "CL=F",
        "BZ=F",
        "HG=F",
        "BCOM",
        "GSG",
        "USDCNY",
        "DXY",
        "industrial",
        "industrial_sales",
        "CN10Y_CDB",
        "bdi",
        "reverse_repo",
        "mlf",
        "etf",
    ]
    return {
        "metadata": {"date": "2026-05-23"},
        "commodities": [
            {"symbol": "GC=F", "current_price": None},
            {"symbol": "CL=F", "current_price": None},
            {"symbol": "BZ=F", "current_price": None},
            {"symbol": "HG=F", "current_price": None},
            {"symbol": "BCOM", "current_price": None},
            {"symbol": "GSG", "current_price": None},
        ],
        "forex": [
            {"pair": "USDCNY", "current_rate": None},
            {"pair": "DXY", "current_rate": None},
        ],
        "bonds": [{"symbol": "CN10Y_CDB", "current_yield": None}],
        "macro_indicators": {
            "industrial": {"current_value": None, "unit": "%"},
            "industrial_sales": {"current_value": None, "unit": "%"},
            "bdi": {"current_value": None, "unit": "points"},
        },
        "monetary_policy": {
            "reverse_repo": {"current_value": None, "unit": "%"},
            "mlf": {"current_value": None, "unit": "%"},
        },
        "fund_flow": {
            "etf": {
                "recent_5d": None,
                "total_120d": None,
                "is_estimated": True,
            },
        },
        "missing_items": [{"key": key} for key in keys],
    }


def _tasks(payload):
    tasks = []
    for item in payload["missing_items"]:
        key = item["key"]
        tasks.append(
            {
                "task_id": "task-" + key,
                "indicator_key": key,
                "stage_phase": "assets",
                "category": TASK_CATEGORIES[key],
                "search_backend": "tavily",
                "unit": _unit_for_key(key),
                "preferred_domains": [],
                "created_at": 1779480000,
            }
        )
    return tasks


def _unit_for_key(key):
    if key in {"GC=F"}:
        return "$/oz"
    if key in {"CL=F", "BZ=F"}:
        return "$/bbl"
    if key == "HG=F":
        return "$/lb"
    if key in {"CN10Y_CDB", "industrial", "industrial_sales", "reverse_repo", "mlf"}:
        return "%"
    if key in {"DXY", "bdi"}:
        return "points"
    return ""


def _by_field(rows, field, value):
    return next(row for row in rows if row.get(field) == value)


def _assert_completed_structured_rows(completed):
    completed_by_key = {row.get("indicator_key"): row for row in completed}
    for key in P0_SUCCESS:
        row = completed_by_key[key]
        assert row["result_type"] == "structured_success"
        assert row["indicator_key"] == key
        assert row.get("category") == TASK_CATEGORIES[key]
        assert row["write_back_success"] is True
        assert row["write_back_target"] == WRITEBACK_TARGETS[key]
        assert row["write_back_target"] != "fallback_macro"


def _assert_structured_websearch_items(websearch):
    structured_items = {
        item["task"]["indicator_key"]: item
        for item in websearch
        if item.get("result_type") == "structured_success"
    }
    for key in P0_SUCCESS:
        item = structured_items[key]
        extraction = item["extraction"]
        assert item["search_backend"] == "structured"
        assert item["result_type"] == "structured_success"
        assert item["task"]["indicator_key"] == key
        assert extraction["indicator_key"] == key
        assert extraction["category"] == TASK_CATEGORIES[key]
        assert item["write_back_success"] is True


def _assert_payload_writeback(payload):
    for key, (category, fixture_payload, _source_url) in P0_SUCCESS.items():
        expected_value = fixture_payload["value"]
        if category == "commodities":
            entry = _by_field(payload["commodities"], "symbol", key)
            assert entry["current_price"] == expected_value
            assert entry["source"] == "structured"
            assert entry["source_url"]
        elif category == "forex":
            entry = _by_field(payload["forex"], "pair", key)
            assert entry["current_rate"] == expected_value
            assert entry["source"] == "structured"
            assert entry["source_url"]
        elif category == "bonds":
            entry = _by_field(payload["bonds"], "symbol", key)
            assert entry["current_yield"] == expected_value
            assert entry["source"] == "structured"
            assert entry["source_url"]
        elif category == "macro_indicators":
            entry = payload["macro_indicators"][key]
            assert entry["current_value"] == expected_value
            assert entry["source"] == "structured"
            assert entry["source_url"]
            if fixture_payload.get("report_period"):
                assert entry["report_period"] == "2026-04"
        elif category == "monetary_policy":
            entry = payload["monetary_policy"][key]
            assert entry["current_value"] == expected_value
            assert entry["source"] == "structured"
            assert entry["source_url"]
        else:  # pragma: no cover - P0_SUCCESS should stay on report-consumed categories.
            raise AssertionError("unsupported golden category: " + category)


def _assert_manual_required_fallbacks(completed, failures):
    structured_success_keys = {
        row.get("indicator_key")
        for row in completed
        if row.get("result_type") == "structured_success"
    }
    manual_required_keys = {
        row.get("indicator_key")
        for row in failures
        if row.get("result_type") == "manual_required"
    }

    assert "BCOM" not in structured_success_keys
    assert "etf" not in structured_success_keys
    assert {"BCOM", "etf"} <= manual_required_keys


def test_golden_20260523_structured_path_reaches_minimum_hit_rate(tmp_path: Path):
    payload = _market_payload()
    stats = {}

    completed, failures, websearch = asyncio.run(
        _execute_tasks(
            _tasks(payload),
            payload,
            ManualSearchClient(),
            None,
            ManualExtractor(),
            tmp_path / "golden_task_log.jsonl",
            cache_ttl=10,
            stats=stats,
            structured_registry=GoldenRegistry(),
            low_score_threshold=0,
        )
    )

    success_count = len(
        [
            row
            for row in completed
            if row.get("result_type") in {"structured_success", "search_success"}
        ]
    )
    failure_count = len(
        [row for row in failures if row.get("result_type") == "manual_required"]
    )
    summary = _build_stage2_summary_diagnostics(
        completed,
        failures,
        websearch,
        exec_stats=stats,
    )

    assert success_count == 13
    assert failure_count == 2
    assert _stage2_effective_hit_rate(success_count, failure_count) >= 0.70
    assert summary["structured_provider_success_count"] == 13
    assert len(summary["structured_provider_success_by_key"]) == 13
    assert "BCOM" not in summary["structured_provider_success_by_key"]
    assert "etf" not in summary["structured_provider_success_by_key"]
    _assert_completed_structured_rows(completed)
    _assert_structured_websearch_items(websearch)
    _assert_payload_writeback(payload)
    _assert_manual_required_fallbacks(completed, failures)
