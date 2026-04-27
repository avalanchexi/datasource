#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import scripts.stage2_5_injector as injector


def test_stage25_replay_normalizes_legacy_monetary_key_and_disables_trend_write(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    market_path = tmp_path / "market_data_stage2.json"
    manual_path = tmp_path / "websearch_results_manual.json"
    output_path = tmp_path / "market_data_complete.json"
    trend_base = tmp_path / "isolated_trend_history" / "min"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "date": "2026-04-27",
                    "data_completeness": 0.5,
                    "missing_items": {"monetary_policy": [{"key": "mlf_rate"}]},
                },
                "missing_items": ["mlf_rate"],
                "monetary_policy": {
                    "mlf_rate": {
                        "policy_name": "MLF rate",
                        "current_value": None,
                        "change_from_120d": None,
                        "unit": "%",
                        "source": "placeholder",
                        "is_estimated": True,
                    }
                },
                "macro_indicators": {},
                "fund_flow": {},
                "commodities": [],
                "forex": [],
                "bonds": [],
                "stock_indices": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "monetary_policy": {
                    "mlf": {
                        "policy_name": "MLF rate",
                        "current_value": 2.0,
                        "change_from_120d": 0.1,
                        "unit": "%",
                        "date": "2026-04",
                        "source": "manual https://example.com/mlf",
                        "source_url": "https://example.com/mlf",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        backfill_trend=False,
        gap_monitor_path=tmp_path / "gap_monitor.json",
        trend_history_base_dir=trend_base,
        disable_trend_history_write=True,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))

    assert "mlf" in output["monetary_policy"]
    assert "mlf_rate" not in output["monetary_policy"]
    assert output["monetary_policy"]["mlf"]["current_value"] == 2.0
    assert output["missing_items"] == []
    assert output["metadata"].get("missing_items") in (None, {})
    assert not trend_base.exists()
    assert not (tmp_path / "data" / "trend_history" / "min").exists()
