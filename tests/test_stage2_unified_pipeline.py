import asyncio
import json
from pathlib import Path

from datasource.engines.stage2_task_planner import Stage2TaskPlanner
from scripts import stage2_unified_enhancer as s


class DummyClient:
    async def search(self, query: str, **kwargs):
        return {
            "results": [
                {"content": f"{query} 最新公布 2.3%", "url": f"https://example.com/{query}"},
            ]
        }


class DummyExtractor:
    async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None):
        return {
            "value": 2.3,
            "unit": unit_hint or "%",
            "source_url": "https://stats.gov.cn/data",
            "confidence": 0.9,
            "note": "dummy",
            "issuer_match": True,
        }


def test_unified_pipeline_write_back(tmp_path: Path):
    payload = {
        "metadata": {"date": "2025-11-01"},
        "macro_indicators": {"cpi": {"indicator_name": "CPI", "current_value": None, "unit": "%", "date": "", "source": ""}},
        "monetary_policy": {"m1": {"policy_name": "M1", "current_value": 5.0, "unit": "%", "date": "", "source": ""}, "m2": {"policy_name": "M2", "current_value": 7.0, "unit": "%", "date": "", "source": ""}},
        "commodities": [{"daily_change": 1.0}],
        "missing_items": ["cpi"],
        "fund_flow": {"northbound": {"recent_5d": 0, "total_120d": None, "source": "MCP raw"}},
    }
    market_path = tmp_path / "market.json"
    market_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl", fund_flow_backend="hybrid")
    tasks = planner.build_tasks(payload)

    completed, failures, web_results = asyncio.run(
        s._execute_tasks(
            tasks,
            payload,
            DummyClient(),
            None,
            DummyExtractor(),
            tmp_path / "task_log.jsonl",
            cache_ttl=60,
        )
    )
    flagged = s._flag_fund_flow_anomalies(payload)
    s._compute_derived_metrics(payload)

    # CPI should be filled
    assert payload["macro_indicators"]["cpi"]["current_value"] == 2.3
    # missing_items removed
    assert payload.get("missing_items", []) == []
    # derived metric m1-m2 spread
    assert payload["derived_metrics"]["m1_m2_spread"] == -2.0
    # fund flow either filled or标注异常
    assert payload["fund_flow"]["northbound"]["source"] in ("异常零值-需核查", "tavily+deepseek")
    if payload["fund_flow"]["northbound"]["source"] != "异常零值-需核查":
        assert "northbound" not in flagged
    # logs and web results emitted
    assert completed and web_results
    # fund flow可能因单位校验进入manual_required
    assert len(failures) <= 1
import pytest

pytest.importorskip("langchain_core")
