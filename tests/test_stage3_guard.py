#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage3 前置校验单元测试：
- 数据完整性达到阈值且无缺口应通过
- 缺口或完整性不足应直接抛 RuntimeError
"""

import pytest
from pathlib import Path
import asyncio
import json

import scripts.stage3_pring_analyzer as s3


def test_require_data_completeness_pass():
    payload = {
        "metadata": {"data_completeness": 0.85},
        "missing_items": [],
    }
    # 不应抛异常
    s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_fail_on_missing():
    payload = {
        "metadata": {"data_completeness": 0.85},
        "missing_items": ["cpi", {"key": "pmi_new_orders"}],
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_fail_on_low_score():
    payload = {
        "metadata": {"data_completeness": 0.5},
        "missing_items": [],
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_fail_on_estimated():
    payload = {
        "metadata": {"data_completeness": 0.9},
        "missing_items": [],
        "bonds": [
            {"symbol": "CN10Y_CDB", "current_yield": 1.97, "is_estimated": True},
        ],
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8, allow_estimated=False)


def test_require_data_completeness_fail_on_missing_compare_values():
    payload = {
        "metadata": {"data_completeness": 0.9},
        "missing_items": [],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": None,
                "change_rate": None,
                "is_estimated": False,
            }
        },
    }
    with pytest.raises(RuntimeError):
        s3._require_data_completeness(payload, 0.8)


def test_resolve_gap_monitor_prefers_dated_file(tmp_path: Path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    dated = reports / "gap_monitor_20260209.json"
    explicit = reports / "custom_gap.json"
    dated.write_text('{"manual_required": []}', encoding="utf-8")
    explicit.write_text('{"manual_required": ["USDCNY"]}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    payload = {"metadata": {"date": "2026-02-09"}}
    resolved = s3._resolve_gap_monitor_path(payload, explicit_gap_path=explicit)
    assert resolved == Path("reports/gap_monitor_20260209.json")


def test_resolve_gap_monitor_uses_explicit_when_dated_missing(tmp_path: Path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    explicit = reports / "custom_gap.json"
    explicit.write_text('{"manual_required": []}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    payload = {"metadata": {"date": "2026-02-09"}}
    resolved = s3._resolve_gap_monitor_path(payload, explicit_gap_path=explicit)
    assert resolved == explicit


def test_run_analysis_reports_all_blockers_once(tmp_path: Path, monkeypatch):
    market_payload = {
        "metadata": {
            "date": "2026-02-09",
            "data_completeness": 0.5,
            "ai_websearch_enhanced": False,
        },
        "missing_items": ["cpi"],
    }
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "policy_evaluation_20260209.json").write_text(
        json.dumps({"block_stage3": True, "redlist": ["mlf"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (reports_dir / "gap_monitor_20260209.json").write_text(
        json.dumps({"manual_required": ["USDCNY"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "pring.json"
    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            s3._run_analysis(
                market_path=market_path,
                output_path=output_path,
                allow_fallback=False,
                skip_gap_check=False,
            )
        )
    msg = str(exc.value)
    assert "policy:" in msg
    assert "completeness:" in msg
    assert "gap_monitor(" in msg
    assert "stage2:" in msg
