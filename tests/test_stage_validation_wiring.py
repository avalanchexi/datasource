import asyncio
import json
import os
import sys
from pathlib import Path

import scripts.stage3_pring_analyzer as stage3
from datasource.engines.stage2_5 import cli as stage25_cli
from datasource.engines.stage2_5 import trend_backfill


def _write_stage3_inputs(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "data" / "runs" / "20260209"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "gap_monitor.json").write_text(
        json.dumps({"manual_required": [], "pending_tasks": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    market_payload = {
        "metadata": {
            "date": "2026-02-09",
            "data_completeness": 1.0,
            "ai_websearch_enhanced": True,
        },
        "missing_items": [],
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "pring.json"
    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")
    return market_path, output_path


def test_stage3_validates_pring_result_before_main_output_write(tmp_path, monkeypatch):
    market_path, output_path = _write_stage3_inputs(tmp_path)
    events = []

    class DummyContract:
        def __init__(self, **payload):
            self.metadata = payload.get("metadata", {})
            self.macro_indicators = payload.get("macro_indicators", {})
            self.monetary_policy = payload.get("monetary_policy", {})

    class DummyAnalyzer:
        def __init__(self, *args, **kwargs):
            pass

        async def analyze_pring_stage(self, days):
            return {"stage": "Expansion", "confidence": 0.9}

    def fake_validate(payload):
        events.append(("validate", payload.get("stage")))
        assert ("write", output_path) not in events

    def fake_write(payload, path):
        events.append(("write", Path(path)))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stage3, "MarketDataContract", DummyContract)
    monkeypatch.setattr(stage3, "PringAnalyzer", DummyAnalyzer)
    monkeypatch.setattr(stage3, "get_manager", lambda: object())
    monkeypatch.setattr(stage3, "validate_pring_result", fake_validate)
    monkeypatch.setattr(stage3, "atomic_write_json", fake_write)

    result = asyncio.run(
        stage3._run_analysis(
            market_path=market_path,
            output_path=output_path,
            allow_fallback=False,
            skip_gap_check=False,
        )
    )

    assert result["stage"] == "Expansion"
    assert events[0] == ("validate", "Expansion")
    assert events[1] == ("write", output_path)


def test_stage25_no_validate_output_sets_env_before_core(tmp_path, monkeypatch):
    run_dir = tmp_path / "data" / "runs" / "20260209"
    run_dir.mkdir(parents=True, exist_ok=True)
    market_path = run_dir / "market_data_stage2.json"
    websearch_path = run_dir / "websearch_results_manual.json"
    output_path = run_dir / "market_data_complete.json"
    market_path.write_text("{}", encoding="utf-8")
    websearch_path.write_text("{}", encoding="utf-8")
    seen_env = []

    class DummyLock:
        def acquire(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_inject_websearch_data(**kwargs):
        seen_env.append(os.getenv("DATASOURCE_NO_VALIDATE_OUTPUT"))

    monkeypatch.delenv("DATASOURCE_NO_VALIDATE_OUTPUT", raising=False)
    monkeypatch.setattr(stage25_cli, "DailyRunLock", lambda *args, **kwargs: DummyLock())
    monkeypatch.setattr(stage25_cli.core, "inject_websearch_data", fake_inject_websearch_data)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stage2_5_injector.py",
            str(market_path),
            str(websearch_path),
            str(output_path),
            "--no-validate-output",
        ],
    )

    try:
        stage25_cli.main()
    finally:
        os.environ.pop("DATASOURCE_NO_VALIDATE_OUTPUT", None)

    assert seen_env == ["1"]


def test_stage25_post_write_backfill_validates_before_contract_write(
    tmp_path, monkeypatch
):
    output_path = tmp_path / "market_data_complete.json"
    events = []
    market_data = {
        "metadata": {"date": "2026-02-09"},
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }

    def fake_validate(payload):
        events.append(("validate", payload))
        assert not any(event[0] == "write" for event in events)

    def fake_write(payload, path):
        events.append(("write", Path(path)))

    monkeypatch.setattr(
        trend_backfill,
        "_backfill_trend_changes",
        lambda *args, **kwargs: {"forex": 0},
    )
    monkeypatch.setattr(
        trend_backfill, "_refresh_stage2_gap_monitor", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(
        trend_backfill, "_refresh_stage2_notes", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        trend_backfill, "_cleanup_metadata_missing", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        trend_backfill, "_apply_pipeline_quality_state", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(
        trend_backfill, "validate_market_data", fake_validate, raising=False
    )
    monkeypatch.setattr(trend_backfill, "atomic_write_json", fake_write)

    stats = trend_backfill._run_post_write_trend_backfill(
        market_data, output_path, base_dir=tmp_path / "trend_history"
    )

    assert stats == {"forex": 0}
    assert events[0][0] == "validate"
    assert events[1] == ("write", output_path)
