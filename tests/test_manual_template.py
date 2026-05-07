import json
from pathlib import Path
from typing import Any, Iterable


TEMPLATE = Path("data/runs/templates/manual_template.json")


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
        "current_value",
        "current_price",
        "current_rate",
        "current_yield",
        "recent_5d",
        "total_120d",
    }
    for item in _walk_values(payload):
        if any(isinstance(item.get(field), (int, float)) for field in numeric_fields):
            evidence = " ".join(
                str(item.get(field) or "")
                for field in ("source_url", "sourceUrl", "url", "source", "note")
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
        payload["fund_flow"]["etf"],
    ]
    for item in official_paths:
        assert item["is_estimated"] is False
