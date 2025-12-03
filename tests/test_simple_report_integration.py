#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""简单报告集成测试（样本 A/B/C）
A: 正常数据，阶段Ⅲ，conf高
B: fallback_used=True，pending_websearch 填充
C: legacy 风格（只校验生成成功）
"""
from pathlib import Path
import json
import pytest

from datasource.generators.simple_report import generate_report


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _base_market():
    return {
        "metadata": {"date": "2025-11-23", "data_completeness": 0.85},
        "stock_indices": [], "commodities": [], "bonds": [], "forex": [],
        "macro_indicators": {}, "monetary_policy": {}, "fund_flow": {}
    }


def test_sample_a_generate(tmp_path: Path):
    market = _base_market()
    pring = {
        "final_stage": "第Ⅲ阶段", "confidence": 0.65, "recommendation": "超配股票",
        "layer_1_inventory_cycle": {}, "layer_2_monetary_cycle": {}, "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [], "fallback_used": False
    }
    m = tmp_path / "m.json"; p = tmp_path / "p.json"; out = tmp_path / "o.md"
    _write_json(m, market); _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")
    assert "第Ⅲ阶段" in text
    assert "超配股票" in text


def test_sample_b_fallback_pending(tmp_path: Path):
    market = _base_market()
    pring = {
        "final_stage": "第Ⅱ阶段", "confidence": 0.4, "recommendation": "低配",
        "layer_1_inventory_cycle": {}, "layer_2_monetary_cycle": {}, "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": ["m2", "ppi"], "fallback_used": True
    }
    m = tmp_path / "m.json"; p = tmp_path / "p.json"; out = tmp_path / "o.md"
    _write_json(m, market); _write_json(p, pring)
    generate_report(m, p, out)
    text = out.read_text(encoding="utf-8")
    assert "allow_fallback=TRUE" in text
    assert "m2" in text or "ppi" in text


def test_sample_c_legacy_ok(tmp_path: Path):
    market = _base_market()
    pring = {
        "final_stage": "第Ⅴ阶段", "confidence": 0.55, "recommendation": "超配大宗",
        "layer_1_inventory_cycle": {}, "layer_2_monetary_cycle": {}, "layer_3_pring_final": {},
        "metadata": {"analysis_method": "legacy", "min_completeness": 0.8},
        "pending_websearch": [], "fallback_used": False
    }
    m = tmp_path / "m.json"; p = tmp_path / "p.json"; out = tmp_path / "o.md"
    _write_json(m, market); _write_json(p, pring)
    generate_report(m, p, out)
    assert out.exists()
    assert "第Ⅴ阶段" in out.read_text(encoding="utf-8")
