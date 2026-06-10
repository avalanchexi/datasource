import argparse
import inspect
import json
from pathlib import Path

import pytest

import scripts.stage2_5_injector as stage2_5
import scripts.stage3_pring_analyzer as stage3
import scripts.stage4_report_generator as stage4_report
import scripts.stage4_risk_review as stage4_risk


class SpyLock:
    calls = []

    def __init__(self, run_dir, owner, *args, **kwargs):
        self.run_dir = Path(run_dir)
        self.owner = owner
        SpyLock.calls.append((self.run_dir, owner))

    def acquire(self):
        return self

    def __enter__(self):
        SpyLock.calls.append(("entered", self.owner))
        return self

    def __exit__(self, exc_type, exc, tb):
        SpyLock.calls.append(("exited", self.owner))
        return False


class OrderedSpyLock:
    calls = []
    order = []

    def __init__(self, run_dir, owner, *args, **kwargs):
        self.run_dir = Path(run_dir)
        self.owner = owner
        OrderedSpyLock.calls.append((self.run_dir, owner))

    def acquire(self):
        return self

    def __enter__(self):
        OrderedSpyLock.order.append("lock_entered")
        OrderedSpyLock.calls.append(("entered", self.owner))
        return self

    def __exit__(self, exc_type, exc, tb):
        OrderedSpyLock.order.append("lock_exited")
        OrderedSpyLock.calls.append(("exited", self.owner))
        return False


@pytest.fixture(autouse=True)
def reset_spy_lock():
    SpyLock.calls = []
    OrderedSpyLock.calls = []
    OrderedSpyLock.order = []
    yield
    SpyLock.calls = []
    OrderedSpyLock.calls = []
    OrderedSpyLock.order = []


def test_stage2_5_main_acquires_daily_lock(tmp_path, monkeypatch):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    input_path = run_dir / "market_data_stage2.json"
    manual_path = run_dir / "websearch_results_manual.json"
    output_path = run_dir / "market_data_complete.json"
    run_dir.mkdir(parents=True)
    input_path.write_text("{}", encoding="utf-8")
    manual_path.write_text("{}", encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        stage2_5,
        "parse_args",
        lambda: argparse.Namespace(
            market_data_path=str(input_path),
            websearch_path=str(manual_path),
            output_path=str(output_path),
            gap_monitor_path=None,
            trend_history_base_dir=None,
            backfill_trend=True,
            date=None,
            override_stale=True,
            force_override=False,
            disable_trend_history_write=False,
        ),
    )
    monkeypatch.setattr(stage2_5, "DailyRunLock", SpyLock)

    def fake_inject_websearch_data(**kwargs):
        calls.append(kwargs)
        return Path(kwargs["output_path"])

    monkeypatch.setattr(stage2_5, "inject_websearch_data", fake_inject_websearch_data)

    stage2_5.main()

    assert SpyLock.calls[0] == (run_dir.resolve(), "stage2_5_injector")
    assert ("entered", "stage2_5_injector") in SpyLock.calls
    assert calls
    assert calls[0]["output_path"] == output_path.resolve()


def test_stage3_main_acquires_daily_lock(tmp_path, monkeypatch):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    market_path = run_dir / "market_data_complete.json"
    output_path = run_dir / "pring_result.json"
    run_dir.mkdir(parents=True)
    market_path.write_text("{}", encoding="utf-8")
    run_calls = []

    monkeypatch.setattr(
        stage3,
        "parse_args",
        lambda: argparse.Namespace(
            market_data=str(market_path),
            output=str(output_path),
            days=120,
            allow_fallback=False,
            min_completeness=0.8,
            allow_estimated=True,
            skip_gap_check=False,
            skip_fund_flow_check=True,
            legacy_stage_rules=False,
            gap_monitor=None,
        ),
    )
    monkeypatch.setattr(stage3, "DailyRunLock", SpyLock)

    def fake_asyncio_run(awaitable):
        run_calls.append(awaitable)
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        return {"final_stage": "test"}

    monkeypatch.setattr(stage3.asyncio, "run", fake_asyncio_run)

    stage3.main()

    assert SpyLock.calls[0] == (run_dir.resolve(), "stage3_pring_analyzer")
    assert ("entered", "stage3_pring_analyzer") in SpyLock.calls
    assert run_calls


def test_stage4_report_main_acquires_daily_lock(tmp_path, monkeypatch):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    report_path = tmp_path / "reports" / "2026-06-10-背景扫描120.md"
    market_path = run_dir / "market_data_complete.json"
    pring_path = run_dir / "pring_result.json"
    gap_path = run_dir / "gap_monitor.json"
    market_path.parent.mkdir(parents=True)
    market_path.write_text(
        json.dumps({"metadata": {"ai_websearch_enhanced": True, "date": "2026-06-10"}}),
        encoding="utf-8",
    )
    pring_path.write_text(
        json.dumps({"metadata": {"analysis_date": "2026-06-10"}}),
        encoding="utf-8",
    )
    gap_path.write_text(json.dumps({"pending_tasks": [], "manual_required": []}), encoding="utf-8")
    calls = []
    run_paths = argparse.Namespace(
        data_dir=run_dir.resolve(),
        pring_result=pring_path,
        report_markdown=report_path,
        gap_monitor=gap_path,
    )

    monkeypatch.setattr(
        stage4_report,
        "parse_args",
        lambda: argparse.Namespace(
            market_data=str(market_path),
            pring_result=str(pring_path),
            output=str(report_path),
            gap_monitor=str(gap_path),
            allow_fund_flow_downgrade=True,
        ),
    )
    monkeypatch.setattr(stage4_report, "DailyRunLock", OrderedSpyLock)
    monkeypatch.setattr(stage4_report, "build_run_paths_from_reference", lambda *a, **k: run_paths)
    original_json_load = stage4_report.json.load

    def tracking_json_load(handle):
        OrderedSpyLock.order.append("json_load")
        return original_json_load(handle)

    def tracking_build_pipeline_quality_state(*args, **kwargs):
        OrderedSpyLock.order.append("quality_state")
        return {}

    monkeypatch.setattr(stage4_report.json, "load", tracking_json_load)
    monkeypatch.setattr(stage4_report, "build_pipeline_quality_state", tracking_build_pipeline_quality_state)
    monkeypatch.setattr(stage4_report, "filter_effective_gap_items", lambda *a, **k: [])
    monkeypatch.setattr(stage4_report, "filter_effective_quality_blockers", lambda *a, **k: [])
    monkeypatch.setattr(stage4_report, "assert_no_fallback_pring_result", lambda *a, **k: None)
    monkeypatch.setattr(stage4_report, "_assert_stage4_quality_gate", lambda *a, **k: None)

    def fake_generate_report(market, pring, output):
        OrderedSpyLock.order.append("generate_report")
        calls.append((Path(market), Path(pring), Path(output)))

    monkeypatch.setattr(stage4_report, "generate_report", fake_generate_report)

    stage4_report.main()

    assert OrderedSpyLock.calls[0] == (run_dir.resolve(), "stage4_report_generator")
    assert ("entered", "stage4_report_generator") in OrderedSpyLock.calls
    assert OrderedSpyLock.order.index("lock_entered") < OrderedSpyLock.order.index("json_load")
    assert OrderedSpyLock.order.index("lock_entered") < OrderedSpyLock.order.index("quality_state")
    assert OrderedSpyLock.order.index("lock_entered") < OrderedSpyLock.order.index("generate_report")
    assert calls == [(market_path, pring_path, report_path)]


def test_stage4_risk_review_main_acquires_daily_lock(tmp_path, monkeypatch):
    run_dir = tmp_path / "data" / "runs" / "20260610"
    market_path = run_dir / "market_data_complete.json"
    gap_path = run_dir / "gap_monitor.json"
    quality_path = run_dir / "quality_metrics.json"
    output_path = tmp_path / "reports" / "stage4_risk_review.json"
    review = {
        "metadata": {
            "blocker_count": 0,
            "review_required_count": 0,
            "info_count": 0,
        }
    }

    monkeypatch.setattr(
        stage4_risk,
        "parse_args",
        lambda: argparse.Namespace(
            date=None,
            market_data=str(market_path),
            gap_monitor=str(gap_path),
            quality_metrics=str(quality_path),
            output=str(output_path),
            allow_fund_flow_downgrade=False,
        ),
    )
    monkeypatch.setattr(stage4_risk, "DailyRunLock", OrderedSpyLock)

    def fake_load_json(path, *, required):
        OrderedSpyLock.order.append(f"load:{Path(path).name}")
        return {"metadata": {"date": "2026-06-10"}} if required else {}

    def fake_build_review(*args, **kwargs):
        OrderedSpyLock.order.append("build_review")
        return review

    monkeypatch.setattr(stage4_risk, "_load_json", fake_load_json)
    monkeypatch.setattr(stage4_risk, "build_review", fake_build_review)

    stage4_risk.main()

    assert OrderedSpyLock.calls[0] == (run_dir.resolve(), "stage4_risk_review")
    assert ("entered", "stage4_risk_review") in OrderedSpyLock.calls
    assert OrderedSpyLock.order.index("lock_entered") < OrderedSpyLock.order.index(
        "load:market_data_complete.json"
    )
    assert OrderedSpyLock.order.index("lock_entered") < OrderedSpyLock.order.index("build_review")
    assert output_path.exists()
    assert OrderedSpyLock.calls.index(("entered", "stage4_risk_review")) < OrderedSpyLock.calls.index(
        ("exited", "stage4_risk_review")
    )
