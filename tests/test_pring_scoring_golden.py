import asyncio
import json
import shutil
from pathlib import Path

import pytest

from datasource.calculators.pring_analyzer import PringAnalyzer
from scripts.stage3_pring_analyzer import _run_analysis


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pring_golden"


@pytest.fixture
def analyzer():
    return PringAnalyzer(data_manager=None)


@pytest.mark.parametrize(
    ("value", "expected_multiplier"),
    [
        (None, 0.5),
        (0.5, 1.0),
        (0.49, 0.7),
        (-1.0, 0.7),
        (-1.01, 0.3),
    ],
)
def test_score_ppi_indicator_boundaries(analyzer, value, expected_multiplier):
    score, reason = analyzer._score_ppi_indicator(value, 10.0, entry={})

    assert score == pytest.approx(10.0 * expected_multiplier)
    assert reason


@pytest.mark.parametrize(
    ("value", "expected_multiplier"),
    [
        (None, 0.5),
        (50.5, 1.0),
        (50.49, 0.85),
        (50.0, 0.85),
        (49.99, 0.55),
        (48.0, 0.55),
        (47.99, 0.25),
    ],
)
def test_score_pmi_indicator_boundaries(analyzer, value, expected_multiplier):
    score, reason = analyzer._score_pmi_indicator(value, 10.0, entry={})

    assert score == pytest.approx(10.0 * expected_multiplier)
    assert reason


@pytest.mark.parametrize(
    ("change", "expected_multiplier"),
    [
        (None, 0.5),
        (-0.5, 1.0),
        (-0.49, 0.8),
        (-0.25, 0.8),
        (-0.24, 0.6),
        (-0.01, 0.6),
        (0.0, 0.4),
        (0.01, 0.2),
    ],
)
def test_score_rrr_change_boundaries(analyzer, change, expected_multiplier):
    score, reason = analyzer._score_rrr_change(change, 20.0)

    assert score == pytest.approx(20.0 * expected_multiplier)
    assert reason


@pytest.mark.parametrize(
    ("value", "expected_multiplier"),
    [
        (None, 0.5),
        (10.0, 1.0),
        (9.99, 0.8),
        (8.0, 0.8),
        (7.99, 0.5),
        (6.0, 0.5),
        (5.99, 0.2),
    ],
)
def test_score_tsf_growth_boundaries(analyzer, value, expected_multiplier):
    score, reason = analyzer._score_tsf_growth(value, 20.0)

    assert score == pytest.approx(20.0 * expected_multiplier)
    assert reason


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _strip_dynamic_fields(value, path=()):
    dynamic_paths = {
        ("analysis_date",),
        ("metadata", "analysis_time"),
        ("layer_1_inventory_cycle", "update_time"),
        ("runtime_sec",),
        ("metadata", "runtime_sec"),
    }
    if path in dynamic_paths:
        return None

    if isinstance(value, dict):
        stripped = {}
        for key, item in value.items():
            item_path = (*path, key)
            if item_path in dynamic_paths:
                continue
            stripped[key] = _strip_dynamic_fields(item, item_path)
        return stripped

    if isinstance(value, list):
        return [
            _strip_dynamic_fields(item, (*path, str(index)))
            for index, item in enumerate(value)
        ]

    return value


def _assert_json_stable_equal(actual, expected):
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        assert actual.keys() == expected.keys()
        for key, expected_value in expected.items():
            _assert_json_stable_equal(actual[key], expected_value)
        return

    if isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) == len(expected)
        for actual_value, expected_value in zip(actual, expected):
            _assert_json_stable_equal(actual_value, expected_value)
        return

    if isinstance(expected, float):
        assert actual == pytest.approx(expected)
        return

    assert actual == expected


def test_stage3_golden_replay_stable_fields(tmp_path, monkeypatch):
    run_dir = tmp_path / "data" / "runs" / "20260424"
    run_dir.mkdir(parents=True)
    market_path = run_dir / "market_data_complete.json"
    output_path = run_dir / "pring_result.json"
    shutil.copy2(FIXTURE_DIR / "market_data_complete.json", market_path)
    (run_dir / "gap_monitor.json").write_text(
        json.dumps({"pending_tasks": [], "manual_required": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "policy_evaluation.json").write_text(
        json.dumps(
            {"block_stage3": False, "redlist": [], "stale_redlist": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    actual = asyncio.run(
        _run_analysis(
            market_path=market_path,
            output_path=output_path,
            allow_estimated=True,
        )
    )
    expected = _load_json(FIXTURE_DIR / "pring_result.json")

    _assert_json_stable_equal(
        _strip_dynamic_fields(actual),
        _strip_dynamic_fields(expected),
    )
