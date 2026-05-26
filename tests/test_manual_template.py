import json
from pathlib import Path
from typing import Any, Iterable


TEMPLATE = (
    Path(__file__).resolve().parents[1] / "data/runs/templates/manual_template.json"
)
FUND_FLOW_GUIDE = Path(__file__).resolve().parents[1] / "docs/手动更新资金流向数据指南.md"
CLAUDE_GUIDE = Path(__file__).resolve().parents[1] / "CLAUDE.md"
LC_PIPELINE = Path(__file__).resolve().parents[1] / "src/datasource/engines/stage2_lc_pipeline.py"


def _walk_values(value: Any) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def test_manual_template_is_valid_json() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert "_rules" in payload


def test_manual_template_has_industrial_yoy_month_shape() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    industrial = payload["macro_indicators"]["industrial"]
    assert industrial["current_value"] == industrial["yoy_month"]
    assert industrial["value_type"] == "yoy_month"
    assert "1-2月" in industrial["_note"]


def test_manual_template_bdi_mentions_secondary_constraints() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    text = json.dumps(payload["macro_indicators"]["bdi"], ensure_ascii=False)
    for token in ("trusted_domains", "max_age_days", "value_range", "unit_keywords"):
        assert token in text


def test_manual_template_numeric_examples_have_url_evidence() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    missing = []
    numeric_fields = {
        "change_rate",
        "current_value",
        "current_price",
        "current_rate",
        "current_yield",
        "previous_value",
        "recent_5d",
        "total_120d",
        "yoy_month",
    }
    for item in _walk_values(payload):
        if any(isinstance(item.get(field), (int, float)) for field in numeric_fields):
            evidence = " ".join(
                str(item.get(field) or "")
                for field in ("source_url", "source", "note")
            )
            if "http://" not in evidence and "https://" not in evidence:
                missing.append(item)
    assert missing == []


def test_manual_template_official_examples_are_not_estimated() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    official_paths = [
        payload["macro_indicators"]["industrial"],
        payload["forex"][0],
        payload["commodities"][0],
        payload["fund_flow"]["northbound"],
        payload["fund_flow"]["southbound"],
    ]
    for item in official_paths:
        assert item["is_estimated"] is False


def test_manual_template_etf_fund_flow_is_estimate_only() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    etf = payload["fund_flow"]["etf"]
    note = etf["_note"].lower()

    assert etf["is_estimated"] is True
    assert etf["metric_basis"] == "estimated_net_flow"
    assert etf["window_evidence"] == "news_summary"
    assert "estimate-only" in note
    assert "will not clear the gate" in note


def test_fund_flow_manual_guide_uses_standard_run_path_contract() -> None:
    text = FUND_FLOW_GUIDE.read_text(encoding="utf-8")

    assert "DATE_NH=${DATE//-/}" in text
    assert "bash run_clean.sh python scripts/stage2_5_injector.py" in text
    assert "bash run_clean.sh python scripts/stage3_pring_analyzer.py" in text
    assert "bash run_clean.sh python scripts/stage4_report_generator.py" in text
    assert "data/runs/${DATE_NH}/market_data_stage2.json" in text
    assert "data/runs/${DATE_NH}/websearch_results_manual.json" in text
    assert "data/runs/${DATE_NH}/market_data_complete.json" in text
    assert "data/${DATE}_market_data_stage2.json" not in text
    assert "data/runs/${DATE}/" not in text
    assert "PYTHONPATH=. python scripts/stage3_pring_analyzer.py" not in text
    assert "PYTHONPATH=. python scripts/stage4_report_generator.py" not in text
    assert '"collection_date": "${DATE}"' in text
    assert "2025-12-09" not in text


def test_claude_daily_pipeline_uses_run_clean_contract() -> None:
    text = CLAUDE_GUIDE.read_text(encoding="utf-8")

    assert "bash run_preflight.sh" in text
    assert "bash run_clean.sh python scripts/stage1_data_collector.py" in text
    assert "bash run_clean.sh python scripts/stage2_unified_enhancer.py" in text
    assert "source .venv/bin/activate && source .env" not in text
    assert "PYTHONPATH=./src python scripts/stage2_unified_enhancer.py" not in text


def test_lc_pipeline_passes_indicator_key_to_fund_flow_validation() -> None:
    text = LC_PIPELINE.read_text(encoding="utf-8")

    assert "_validate_fund_flow_extraction(" in text
    assert 'indicator_key=task["indicator_key"]' in text
