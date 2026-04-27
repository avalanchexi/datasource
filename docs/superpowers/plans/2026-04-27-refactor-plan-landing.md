# 2026-04-27 Refactor Plan Landing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the approved `optimization/20260427_refactor_plan/` design as six serial, test-gated batches on the current integration worktree.

**Architecture:** Keep the Stage1 -> Stage4 pipeline behavior unchanged while extracting shared contracts into small utility modules, adding deterministic Pring and Stage2.5 replay tests, then performing behavior-preserving module splits. `metadata.missing_items` becomes the canonical missing-data source while legacy top-level `missing_items` and `gap_monitor` remain compatibility views.

**Tech Stack:** Python 3, pytest, existing `bash run_clean.sh` project entrypoint, `src/datasource` package, Stage scripts under `scripts/`.

---

## Scope Check

This is a master execution plan for six serial batches that were already approved in the design. Each batch is independently testable, but the order is mandatory:

1. PR1 utility extraction.
2. PR2 Pring golden tests.
3. PR3 key registry and missing-data compatibility.
4. PR4 Pring module split.
5. PR5 run path contract and docs alignment.
6. PR6 hygiene archive.

Do not parallelize these tasks in this worktree. The current worktree is the integration baseline that will be merged to main.

## File Structure

Create:

- `src/datasource/utils/coercion.py`: numeric conversion and distinct missing-value predicates.
- `src/datasource/utils/json_io.py`: strict JSON read/write and optional diagnostic JSON read.
- `src/datasource/utils/text_markers.py`: shared YTD marker detection.
- `src/datasource/utils/key_aliases.py`: monetary canonical keys, alias normalizer, conflict resolution helpers.
- `src/datasource/utils/missing_items.py`: canonical metadata missing-items helpers plus legacy compatibility flattening.
- `tests/test_utils_coercion.py`: utility predicate contract tests.
- `tests/test_utils_json_io.py`: JSON IO behavior tests.
- `tests/test_pring_scoring_golden.py`: Pring score boundary and golden replay tests.
- `tests/fixtures/pring_golden/market_data_complete.json`: fixed golden input copied from `data/runs/20260424/market_data_complete.json`.
- `tests/fixtures/pring_golden/pring_result.json`: fixed golden output copied from `data/runs/20260424/pring_result.json`.
- `tests/test_monetary_key_registry.py`: monetary key alias tests.
- `tests/test_missing_items_compat.py`: canonical and legacy missing-items tests.
- `tests/test_stage25_contract_replay.py`: Stage2.5 replay tests using isolated trend history.
- `src/datasource/calculators/pring/__init__.py`: Pring split package.
- `src/datasource/calculators/pring/scoring.py`: pure scoring helpers.
- `src/datasource/calculators/pring/leading_indicator.py`: leading indicator helpers.
- `src/datasource/calculators/pring/summaries.py`: summary text helpers.
- `src/datasource/calculators/pring/stage_allocations.py`: stage allocation and stage shifting helpers.
- `tests/test_run_paths_consistency.py`: path contract tests.
- `scripts/legacy/README.md`: legacy script directory note.
- `scripts/archive/README.md`: archive directory note.

Modify:

- `scripts/stage2_unified_enhancer.py`: import shared JSON, numeric, text marker, missing-items helpers.
- `scripts/stage2_5_injector.py`: import shared numeric, text marker, key alias, missing-items helpers; add trend-history test isolation.
- `scripts/stage2_low_score_audit.py`: use optional diagnostic JSON loader.
- `scripts/recap_consistency_check.py`: use optional diagnostic JSON loader.
- `scripts/backfill_fund_flow_series.py`: use strict JSON loader.
- `src/datasource/engines/stage2_task_planner.py`: use legacy `7.13` aware predicate.
- `src/datasource/engines/deepseek_reasoner.py`: use shared `to_float`.
- `src/datasource/generators/simple_report.py`: use shared `to_float`.
- `src/datasource/config/search_profiles.py`: import monetary canonical registry for `ALIASES`.
- `scripts/stage3_pring_analyzer.py`: use shared missing-items flattening and key alias lookup.
- `scripts/stage4_report_generator.py`: keep explicit `gap_monitor` gate and add tests only if needed.
- `src/datasource/calculators/pring_analyzer.py`: after PR2, delegate extracted Pring helpers to the new modules.
- `AGENTS.md`, `CLAUDE.md`, `README.md`, `SCRIPTS.md`: align path examples in PR5 only.

## Task 0: Baseline Guard

**Files:**
- Read: `docs/superpowers/specs/2026-04-27-refactor-plan-landing-design.md`
- Read: `optimization/20260427_refactor_plan/DECISIONS.md`
- Read: `optimization/20260427_refactor_plan/TEST_PLAN.md`
- Read: `optimization/20260427_refactor_plan/REFACTOR_PLAN_REVIEW.md`

- [ ] **Step 1: Check the integration baseline**

Run:

```bash
git status --short
git rev-parse --short HEAD
```

Expected: the worktree may contain existing unrelated changes. Record the current `HEAD` and do not revert unrelated files.

- [ ] **Step 2: Confirm fixture source files exist**

Run:

```bash
Test-Path data/runs/20260424/market_data_complete.json
Test-Path data/runs/20260424/pring_result.json
```

Expected: both commands print `True`.

- [ ] **Step 3: Run current focused tests before edits**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_websearch_injector.py tests/test_stage3_guard.py tests/test_stage4_docs.py -q
```

Expected: PASS. If a test fails before edits, save the failing test name and error text in the task notes before continuing.

## Task 1: PR1 Utility Contracts

**Files:**
- Create: `src/datasource/utils/coercion.py`
- Create: `src/datasource/utils/json_io.py`
- Create: `src/datasource/utils/text_markers.py`
- Create: `tests/test_utils_coercion.py`
- Create: `tests/test_utils_json_io.py`

- [ ] **Step 1: Write failing coercion tests**

Create `tests/test_utils_coercion.py`:

```python
import pytest

from datasource.utils.coercion import (
    is_legacy_713_placeholder,
    is_stage2_number_placeholder,
    is_stage2_task_placeholder,
    to_float,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("", None),
        ("N/A", None),
        ("1.25", 1.25),
        (2, 2.0),
        ("abc", None),
    ],
)
def test_to_float_returns_none_for_non_numeric(value, expected):
    assert to_float(value) == expected


@pytest.mark.parametrize("value", [None, "", "N/A", 0, 0.0, "0", "0.0000000001", "abc"])
def test_stage2_number_placeholder_matches_stage2_and_stage25_semantics(value):
    assert is_stage2_number_placeholder(value) is True


@pytest.mark.parametrize("value", [1, "1.2", -0.1])
def test_stage2_number_placeholder_accepts_non_zero_numbers(value):
    assert is_stage2_number_placeholder(value) is False


@pytest.mark.parametrize("value", [7.13, "7.13", 7.1300001])
def test_legacy_713_placeholder_is_separate_contract(value):
    assert is_legacy_713_placeholder(value) is True


@pytest.mark.parametrize("value", [None, 0, 0.0, 7.13, "7.13"])
def test_stage2_task_placeholder_keeps_legacy_713_semantics(value):
    assert is_stage2_task_placeholder(value) is True


@pytest.mark.parametrize("value", ["", "N/A", "abc", 1.0])
def test_stage2_task_placeholder_does_not_copy_stage25_non_numeric_semantics(value):
    assert is_stage2_task_placeholder(value) is False
```

- [ ] **Step 2: Run coercion tests to verify failure**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_utils_coercion.py -q
```

Expected: FAIL because `datasource.utils.coercion` does not exist.

- [ ] **Step 3: Implement coercion utilities**

Create `src/datasource/utils/coercion.py`:

```python
"""Shared numeric coercion helpers with explicit pipeline semantics."""

from __future__ import annotations

from typing import Any, Optional


def to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def is_legacy_713_placeholder(value: Any) -> bool:
    numeric = to_float(value)
    if numeric is None:
        return False
    return abs(numeric - 7.13) < 1e-6


def is_stage2_number_placeholder(value: Any) -> bool:
    """Stage2/Stage2.5 numeric gate: empty, non-numeric, or zero are invalid."""
    if value in (None, "", "N/A"):
        return True
    numeric = to_float(value)
    if numeric is None:
        return True
    return abs(numeric) < 1e-9


def is_stage2_task_placeholder(value: Any) -> bool:
    """Stage2 task planner gate: only None, zero, and legacy 7.13 trigger tasks."""
    if value in (None, 0, 0.0):
        return True
    return is_legacy_713_placeholder(value)
```

- [ ] **Step 4: Write failing JSON IO tests**

Create `tests/test_utils_json_io.py`:

```python
import json

import pytest

from datasource.utils.json_io import dump_json, load_json_optional, load_json_strict


def test_load_json_strict_reads_dict(tmp_path):
    path = tmp_path / "payload.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert load_json_strict(path) == {"a": 1}


def test_load_json_strict_fails_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_json_strict(tmp_path / "missing.json")


def test_load_json_optional_returns_none_for_missing_or_invalid(tmp_path):
    assert load_json_optional(tmp_path / "missing.json") is None
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{bad", encoding="utf-8")
    assert load_json_optional(invalid) is None


def test_dump_json_creates_parent_and_backup(tmp_path):
    path = tmp_path / "nested" / "payload.json"
    dump_json({"a": 1}, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
    dump_json({"a": 2}, path, backup=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}
    assert (path.with_name(path.name + ".bak")).exists()
```

- [ ] **Step 5: Implement JSON IO utilities**

Create `src/datasource/utils/json_io.py`:

```python
"""JSON IO helpers with strict and diagnostic read modes."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def load_json_strict(path: Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as fp:
        return json.load(fp)


def load_json_optional(path: Path) -> Optional[Any]:
    target = Path(path)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None


def dump_json(payload: Any, path: Path, backup: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup and target.exists():
        backup_path = target.with_name(target.name + ".bak")
        timestamp_path = target.with_name(f"{target.stem}_{datetime.now():%Y%m%d%H%M%S}{target.suffix}")
        shutil.copy2(target, backup_path)
        shutil.copy2(target, timestamp_path)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 6: Implement text marker utility**

Create `src/datasource/utils/text_markers.py`:

```python
"""Shared text marker predicates."""

from __future__ import annotations

import re


def contains_ytd_marker(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(token in lowered for token in ["累计", "年初至今", "ytd", "year-to-date"]):
        return True
    return bool(re.search(r"1\s*(?:-|—|~|至|到)\s*\d{1,2}\s*月", lowered))
```

- [ ] **Step 7: Run utility tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_utils_coercion.py tests/test_utils_json_io.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit PR1 utility contracts**

Run:

```bash
git add src/datasource/utils/coercion.py src/datasource/utils/json_io.py src/datasource/utils/text_markers.py tests/test_utils_coercion.py tests/test_utils_json_io.py
git commit -m "refactor: add shared utility contracts"
```

## Task 2: PR1 Wire Shared Utilities Without Behavior Changes

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Modify: `scripts/stage2_5_injector.py`
- Modify: `scripts/stage2_low_score_audit.py`
- Modify: `scripts/recap_consistency_check.py`
- Modify: `scripts/backfill_fund_flow_series.py`
- Modify: `src/datasource/engines/stage2_task_planner.py`
- Modify: `src/datasource/engines/deepseek_reasoner.py`
- Modify: `src/datasource/generators/simple_report.py`

- [ ] **Step 1: Replace Stage2 local JSON and numeric helpers**

In `scripts/stage2_unified_enhancer.py`, add imports:

```python
from datasource.utils.coercion import is_stage2_number_placeholder
from datasource.utils.json_io import dump_json, load_json_strict
from datasource.utils.text_markers import contains_ytd_marker
```

Replace local helper bodies:

```python
def _load_json(path: Path) -> Dict[str, Any]:
    return load_json_strict(path)


def _is_placeholder_number(val: Any) -> bool:
    return is_stage2_number_placeholder(val)


def _dump_json(payload: Dict[str, Any], path: Path, backup: bool = False) -> None:
    dump_json(payload, path, backup=backup)


def _contains_ytd_marker(text: str) -> bool:
    return contains_ytd_marker(text)
```

- [ ] **Step 2: Replace Stage2.5 numeric and text helpers**

In `scripts/stage2_5_injector.py`, add imports:

```python
from datasource.utils.coercion import is_stage2_number_placeholder
from datasource.utils.text_markers import contains_ytd_marker
```

Replace helper bodies:

```python
def _is_placeholder_numeric(value: Any) -> bool:
    return is_stage2_number_placeholder(value)


def _contains_ytd_marker(text: str) -> bool:
    return contains_ytd_marker(text)
```

- [ ] **Step 3: Replace optional diagnostic JSON readers**

In `scripts/stage2_low_score_audit.py` and `scripts/recap_consistency_check.py`, import:

```python
from datasource.utils.json_io import load_json_optional
```

Use this body for each local `_load_json`:

```python
def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    payload = load_json_optional(path)
    return payload if isinstance(payload, dict) else None
```

- [ ] **Step 4: Replace strict fund-flow backfill reader**

In `scripts/backfill_fund_flow_series.py`, import:

```python
from datasource.utils.json_io import load_json_strict
```

Use:

```python
def _load_json(path: Path) -> Dict[str, Any]:
    return load_json_strict(path)
```

- [ ] **Step 5: Replace Stage2 task planner legacy predicate**

In `src/datasource/engines/stage2_task_planner.py`, import:

```python
from datasource.utils.coercion import is_stage2_task_placeholder
```

Change the static method body:

```python
@staticmethod
def _is_placeholder(value: Any) -> bool:
    return is_stage2_task_placeholder(value)
```

- [ ] **Step 6: Replace simple float helpers**

In `src/datasource/engines/deepseek_reasoner.py` and `src/datasource/generators/simple_report.py`, import:

```python
from datasource.utils.coercion import to_float
```

Use this wrapper where local callers still reference `_to_float`:

```python
def _to_float(value: Any) -> Optional[float]:
    return to_float(value)
```

For `DeepSeekReasoner._to_float`, keep it as a static method:

```python
@staticmethod
def _to_float(value: Any) -> Optional[float]:
    return to_float(value)
```

- [ ] **Step 7: Run PR1 focused tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_utils_coercion.py tests/test_utils_json_io.py tests/test_stage2_unified.py tests/test_stage2_fallbacks.py tests/test_websearch_injector.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit PR1 wiring**

Run:

```bash
git add scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py scripts/stage2_low_score_audit.py scripts/recap_consistency_check.py scripts/backfill_fund_flow_series.py src/datasource/engines/stage2_task_planner.py src/datasource/engines/deepseek_reasoner.py src/datasource/generators/simple_report.py
git commit -m "refactor: reuse shared utility contracts"
```

## Task 3: PR2 Pring Golden Tests

**Files:**
- Create: `tests/test_pring_scoring_golden.py`
- Create: `tests/fixtures/pring_golden/market_data_complete.json`
- Create: `tests/fixtures/pring_golden/pring_result.json`
- Read: `src/datasource/calculators/pring_analyzer.py`

- [ ] **Step 1: Copy fixed golden fixtures**

Run:

```bash
New-Item -ItemType Directory -Force tests/fixtures/pring_golden
Copy-Item data/runs/20260424/market_data_complete.json tests/fixtures/pring_golden/market_data_complete.json
Copy-Item data/runs/20260424/pring_result.json tests/fixtures/pring_golden/pring_result.json
```

Expected: both fixture files exist under `tests/fixtures/pring_golden/`.

- [ ] **Step 2: Write score boundary tests**

Create `tests/test_pring_scoring_golden.py` with this initial content:

```python
import asyncio
import json
from pathlib import Path

import pytest

from scripts.stage3_pring_analyzer import _run_analysis
from datasource.calculators.pring_analyzer import PringAnalyzer


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "pring_golden"


@pytest.fixture()
def analyzer():
    return PringAnalyzer(data_manager=None)


@pytest.mark.parametrize(
    "value, multiplier",
    [
        (None, 0.5),
        (0.5, 1.0),
        (-1.0, 0.7),
        (-1.01, 0.3),
    ],
)
def test_score_ppi_indicator_boundaries(analyzer, value, multiplier):
    score, _ = analyzer._score_ppi_indicator(value, 10, {})
    assert score == pytest.approx(10 * multiplier)


@pytest.mark.parametrize(
    "value, multiplier",
    [
        (None, 0.5),
        (50.5, 1.0),
        (50.0, 0.85),
        (48.0, 0.55),
        (47.99, 0.25),
    ],
)
def test_score_pmi_indicator_boundaries(analyzer, value, multiplier):
    score, _ = analyzer._score_pmi_indicator(value, 10, {})
    assert score == pytest.approx(10 * multiplier)


@pytest.mark.parametrize(
    "change, multiplier",
    [
        (None, 0.5),
        (-0.5, 1.0),
        (-0.25, 0.8),
        (-0.01, 0.6),
        (0.0, 0.4),
        (0.01, 0.2),
    ],
)
def test_score_rrr_change_boundaries(analyzer, change, multiplier):
    score, _ = analyzer._score_rrr_change(change, 10)
    assert score == pytest.approx(10 * multiplier)


@pytest.mark.parametrize(
    "value, multiplier",
    [
        (None, 0.5),
        (10.0, 1.0),
        (8.0, 0.8),
        (6.0, 0.5),
        (5.99, 0.2),
    ],
)
def test_score_tsf_growth_boundaries(analyzer, value, multiplier):
    score, _ = analyzer._score_tsf_growth(value, 10)
    assert score == pytest.approx(10 * multiplier)
```

- [ ] **Step 3: Run boundary tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_pring_scoring_golden.py -q
```

Expected: PASS. These tests use current private methods before the PR4 split.

- [ ] **Step 4: Add full-result golden replay**

Append to `tests/test_pring_scoring_golden.py`:

```python
def _strip_dynamic_fields(payload):
    if isinstance(payload, dict):
        cleaned = {}
        for key, value in payload.items():
            if key in {"analysis_date", "analysis_time", "runtime_sec"}:
                continue
            cleaned[key] = _strip_dynamic_fields(value)
        return cleaned
    if isinstance(payload, list):
        return [_strip_dynamic_fields(item) for item in payload]
    return payload


def test_pring_full_result_golden_replay(tmp_path, monkeypatch):
    market_src = FIXTURE_DIR / "market_data_complete.json"
    expected_src = FIXTURE_DIR / "pring_result.json"
    market_path = tmp_path / "data" / "runs" / "20260424" / "market_data_complete.json"
    output_path = tmp_path / "data" / "runs" / "20260424" / "pring_result.json"
    gap_path = tmp_path / "data" / "runs" / "20260424" / "gap_monitor.json"
    policy_path = tmp_path / "data" / "runs" / "20260424" / "policy_evaluation.json"

    market_path.parent.mkdir(parents=True, exist_ok=True)
    market_path.write_text(market_src.read_text(encoding="utf-8"), encoding="utf-8")
    gap_path.write_text('{"pending_tasks": [], "manual_required": []}', encoding="utf-8")
    policy_path.write_text('{"block_stage3": false, "redlist": [], "stale_redlist": []}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    result = asyncio.run(
        _run_analysis(
            market_path=market_path,
            output_path=output_path,
            gap_monitor_path=gap_path,
            allow_estimated=True,
        )
    )
    expected = json.loads(expected_src.read_text(encoding="utf-8"))

    result_clean = _strip_dynamic_fields(result)
    expected_clean = _strip_dynamic_fields(expected)

    assert result_clean["final_stage"] == expected_clean["final_stage"]
    assert result_clean["confidence"] == pytest.approx(expected_clean["confidence"])
    assert result_clean["recommendation"] == expected_clean["recommendation"]
    assert result_clean["layer_1_inventory_cycle"] == expected_clean["layer_1_inventory_cycle"]
    assert result_clean["layer_2_monetary_cycle"] == expected_clean["layer_2_monetary_cycle"]
    assert result_clean["layer_3_pring_final"] == expected_clean["layer_3_pring_final"]
```

- [ ] **Step 5: Run PR2 tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_pring_scoring_golden.py tests/test_stage3_guard.py -q
```

Expected: PASS. If golden replay fails because fixture output reflects an older committed algorithm, inspect the diff and update only `tests/fixtures/pring_golden/pring_result.json` from the current algorithm output after confirming the algorithm itself was not changed in this task.

- [ ] **Step 6: Commit PR2**

Run:

```bash
git add tests/test_pring_scoring_golden.py tests/fixtures/pring_golden/market_data_complete.json tests/fixtures/pring_golden/pring_result.json
git commit -m "test: add pring golden coverage"
```

## Task 4: PR3 Key Registry, Missing Items, And Trend-History Isolation

**Files:**
- Create: `src/datasource/utils/key_aliases.py`
- Create: `src/datasource/utils/missing_items.py`
- Create: `tests/test_monetary_key_registry.py`
- Create: `tests/test_missing_items_compat.py`
- Modify: `src/datasource/config/search_profiles.py`
- Modify: `scripts/stage2_unified_enhancer.py`
- Modify: `scripts/stage2_5_injector.py`
- Modify: `scripts/stage3_pring_analyzer.py`

- [ ] **Step 1: Write monetary registry tests**

Create `tests/test_monetary_key_registry.py`:

```python
from datasource.utils.key_aliases import (
    MONETARY_ALIASES,
    canonical_monetary_key,
    normalize_monetary_section,
)


def test_registry_contains_old_and_canonical_keys():
    assert MONETARY_ALIASES["reverse_repo_7d"] == "reverse_repo"
    assert MONETARY_ALIASES["mlf_rate"] == "mlf"
    assert MONETARY_ALIASES["tsf_growth"] == "tsf"
    assert MONETARY_ALIASES["rrr"] == "reserve_ratio"
    assert canonical_monetary_key("m1_growth") == "m1"


def test_normalize_monetary_section_keeps_canonical_value_over_empty_alias():
    section = {
        "mlf_rate": {"current_value": None, "source": "old"},
        "mlf": {"current_value": 2.0, "source": "new"},
    }
    normalized = normalize_monetary_section(section)
    assert list(normalized) == ["mlf"]
    assert normalized["mlf"]["current_value"] == 2.0
    assert normalized["mlf"]["source"] == "new"


def test_normalize_monetary_section_uses_alias_when_canonical_missing():
    section = {"reverse_repo_7d": {"current_value": 1.4}}
    normalized = normalize_monetary_section(section)
    assert "reverse_repo" in normalized
    assert "reverse_repo_7d" not in normalized
    assert normalized["reverse_repo"]["current_value"] == 1.4
```

- [ ] **Step 2: Implement key registry**

Create `src/datasource/utils/key_aliases.py`:

```python
"""Canonical key registry and alias normalizers."""

from __future__ import annotations

from typing import Any, Dict

from datasource.utils.coercion import is_stage2_number_placeholder


MONETARY_ALIASES: Dict[str, str] = {
    "reverse_repo_7d": "reverse_repo",
    "reverse_repo": "reverse_repo",
    "mlf_rate": "mlf",
    "mlf": "mlf",
    "tsf_growth": "tsf",
    "tsf": "tsf",
    "m1_growth": "m1",
    "m1": "m1",
    "m2_growth": "m2",
    "m2": "m2",
    "rrr": "reserve_ratio",
    "reserve_ratio": "reserve_ratio",
    "dr007_rate": "dr007",
    "dr007": "dr007",
}


def canonical_monetary_key(key: Any) -> str:
    text = str(key)
    return MONETARY_ALIASES.get(text, text)


def _has_value(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return not is_stage2_number_placeholder(entry)
    return not is_stage2_number_placeholder(entry.get("current_value"))


def normalize_monetary_section(section: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for raw_key, value in (section or {}).items():
        canonical = canonical_monetary_key(raw_key)
        if canonical not in normalized:
            normalized[canonical] = value
            continue
        existing = normalized[canonical]
        if _has_value(value) and not _has_value(existing):
            normalized[canonical] = value
    return normalized
```

- [ ] **Step 3: Write missing-items compatibility tests**

Create `tests/test_missing_items_compat.py`:

```python
from datasource.utils.missing_items import (
    append_missing_item,
    flatten_missing_items,
    remove_missing_item,
    sync_top_level_missing_items,
)


def test_flatten_missing_items_reads_metadata_and_top_level():
    payload = {
        "metadata": {"missing_items": {"macro_indicators": [{"key": "cpi"}, "ppi"]}},
        "missing_items": ["USDCNY", {"indicator_key": "CN10Y"}],
    }
    assert flatten_missing_items(payload) == ["USDCNY", "CN10Y", "cpi", "ppi"]


def test_append_missing_item_writes_metadata_and_legacy_view():
    payload = {"metadata": {"missing_items": {}}, "missing_items": []}
    append_missing_item(payload, "monetary_policy", "mlf", "estimated_not_allowed")
    assert payload["metadata"]["missing_items"]["monetary_policy"] == [{"key": "mlf", "reason": "estimated_not_allowed"}]
    assert payload["missing_items"] == ["mlf"]


def test_remove_missing_item_cleans_both_views():
    payload = {
        "metadata": {"missing_items": {"macro_indicators": [{"key": "cpi"}, {"key": "ppi"}]}},
        "missing_items": ["cpi", "ppi"],
    }
    remove_missing_item(payload, "macro_indicators", "cpi")
    assert payload["metadata"]["missing_items"] == {"macro_indicators": [{"key": "ppi"}]}
    assert payload["missing_items"] == ["ppi"]


def test_remove_missing_item_clears_last_legacy_view_item():
    payload = {
        "metadata": {"missing_items": {"macro_indicators": [{"key": "cpi"}]}},
        "missing_items": ["cpi"],
    }
    remove_missing_item(payload, "macro_indicators", "cpi")
    assert payload["metadata"]["missing_items"] == {}
    assert payload["missing_items"] == []


def test_sync_top_level_missing_items_derives_legacy_view_from_metadata():
    payload = {
        "metadata": {"missing_items": {"fund_flow": [{"key": "etf"}], "macro_indicators": ["cpi"]}},
        "missing_items": ["stale_old"],
    }
    sync_top_level_missing_items(payload)
    assert payload["missing_items"] == ["etf", "cpi"]


def test_sync_top_level_missing_items_preserves_legacy_top_level_when_metadata_empty():
    payload = {"metadata": {}, "missing_items": ["USDCNY", {"key": "CN10Y"}]}
    sync_top_level_missing_items(payload)
    assert payload["missing_items"] == ["USDCNY", "CN10Y"]
```

- [ ] **Step 4: Implement missing-items helpers**

Create `src/datasource/utils/missing_items.py`:

```python
"""Missing-items compatibility helpers.

metadata.missing_items is canonical. Top-level missing_items is a legacy view.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _item_key(item: Any) -> str | None:
    if isinstance(item, dict):
        key = item.get("key") or item.get("indicator_key")
        return str(key) if key else None
    return str(item) if item else None


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def flatten_missing_items(payload: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    top = payload.get("missing_items", [])
    if isinstance(top, list):
        for item in top:
            key = _item_key(item)
            if key:
                values.append(key)
    metadata_missing = payload.get("metadata", {}).get("missing_items", {})
    if isinstance(metadata_missing, dict):
        for items in metadata_missing.values():
            if not isinstance(items, list):
                continue
            for item in items:
                key = _item_key(item)
                if key:
                    values.append(key)
    return _dedupe(values)


def sync_top_level_missing_items(payload: Dict[str, Any]) -> None:
    metadata_missing = payload.get("metadata", {}).get("missing_items", {})
    if not isinstance(metadata_missing, dict) or not metadata_missing:
        payload["missing_items"] = flatten_missing_items(payload)
        return
    values: List[str] = []
    for items in metadata_missing.values():
        if not isinstance(items, list):
            continue
        for item in items:
            key = _item_key(item)
            if key:
                values.append(key)
    payload["missing_items"] = _dedupe(values)


def append_missing_item(payload: Dict[str, Any], category: str, key: str, reason: str) -> None:
    metadata = payload.setdefault("metadata", {})
    missing = metadata.setdefault("missing_items", {})
    rows = missing.setdefault(category, [])
    if key not in {_item_key(item) for item in rows}:
        rows.append({"key": key, "reason": reason})
    sync_top_level_missing_items(payload)


def remove_missing_item(payload: Dict[str, Any], category: str, key: str) -> None:
    metadata = payload.setdefault("metadata", {})
    missing = metadata.get("missing_items")
    if isinstance(missing, dict) and isinstance(missing.get(category), list):
        rows = [item for item in missing[category] if _item_key(item) != key]
        if rows:
            missing[category] = rows
        else:
            missing.pop(category, None)
    top = payload.get("missing_items", [])
    if isinstance(top, list):
        payload["missing_items"] = [item for item in top if _item_key(item) != key]
    if isinstance(missing, dict) and missing:
        sync_top_level_missing_items(payload)
```

- [ ] **Step 5: Wire registry into config and Stage2.5**

In `src/datasource/config/search_profiles.py`, import:

```python
from datasource.utils.key_aliases import MONETARY_ALIASES
```

Change the monetary portion of `ALIASES` so it uses the registry:

```python
ALIASES.update(MONETARY_ALIASES)
```

In `scripts/stage2_5_injector.py`, import:

```python
from datasource.utils.key_aliases import MONETARY_ALIASES, canonical_monetary_key, normalize_monetary_section
from datasource.utils.missing_items import append_missing_item, flatten_missing_items, remove_missing_item, sync_top_level_missing_items
```

Replace `MONETARY_KEY_MAP` with:

```python
MONETARY_KEY_MAP = MONETARY_ALIASES
```

Normalize input after loading market data and websearch schema:

```python
market_data["monetary_policy"] = normalize_monetary_section(market_data.get("monetary_policy", {}))
websearch_data["monetary_policy"] = normalize_monetary_section(websearch_data.get("monetary_policy", {}))
sync_top_level_missing_items(market_data)
```

When deriving category from a Stage2 task key, canonicalize monetary keys:

```python
if cat == "monetary_policy":
    key = canonical_monetary_key(key)
```

- [ ] **Step 6: Wire missing-items helpers into Stage2 and Stage3**

In `scripts/stage2_unified_enhancer.py`, import:

```python
from datasource.utils.missing_items import flatten_missing_items, remove_missing_item, sync_top_level_missing_items
```

Change `_merge_missing_items`:

```python
def _merge_missing_items(market_payload: Dict[str, Any]) -> None:
    sync_top_level_missing_items(market_payload)
```

Change `_update_missing_items`:

```python
def _update_missing_items(market_payload: Dict[str, Any], indicator_key: str) -> None:
    metadata_missing = market_payload.get("metadata", {}).get("missing_items", {})
    if isinstance(metadata_missing, dict):
        for category in list(metadata_missing.keys()):
            remove_missing_item(market_payload, category, indicator_key)
    else:
        market_payload["missing_items"] = [key for key in flatten_missing_items(market_payload) if key != indicator_key]
```

In `scripts/stage3_pring_analyzer.py`, import:

```python
from datasource.utils.missing_items import flatten_missing_items
```

Change `_flatten_missing_items`:

```python
def _flatten_missing_items(market_payload: Dict[str, Any]) -> List[str]:
    return flatten_missing_items(market_payload)
```

- [ ] **Step 7: Add trend-history isolation to Stage2.5**

In `scripts/stage2_5_injector.py`, update functions that write trend history to accept `trend_history_base_dir`.

Use this signature pattern:

```python
def inject_websearch_data(
    market_data_path: Path,
    websearch_path: Path,
    output_path: Path,
    *,
    backfill_trend: bool = True,
    date_override: Optional[str] = None,
    gap_monitor_path: Optional[Path] = None,
    override_stale: bool = True,
    force_override: bool = False,
    trend_history_base_dir: Optional[Path] = None,
    disable_trend_history_write: bool = False,
) -> Path:
```

Thread `trend_history_base_dir` through the backfill helpers so tests never read or write the real tree when a temporary base is provided. Change the `_backfill_trend_changes` signature from:

```python
def _backfill_trend_changes(market_data: Dict[str, Any]) -> Dict[str, int]:
```

to:

```python
def _backfill_trend_changes(market_data: Dict[str, Any], *, base_dir: Path = DEFAULT_BASE_DIR) -> Dict[str, int]:
```

Inside that function, change every `_calc_change_from_trend_history(...)`, `_calc_daily_change_from_trend_history(...)`, `_calc_change_from_event_history(...)`, and `_calc_prev_from_event_history(...)` call to pass `base_dir=base_dir`.

Update post-write backfill:

```python
def _run_post_write_trend_backfill(
    market_data: Dict[str, Any],
    output_path: Path,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Dict[str, int]:
    stats = _backfill_trend_changes(market_data, base_dir=base_dir)
    return stats
```

When writing trend history, use:

```python
if not disable_trend_history_write:
    write_from_market_data(
        market_data,
        is_partial=False,
        source_path=Path(output_path),
        base_dir=trend_history_base_dir or DEFAULT_BASE_DIR,
    )
```

When calling `_run_post_write_trend_backfill`, use:

```python
_run_post_write_trend_backfill(
    market_data,
    Path(output_path),
    base_dir=trend_history_base_dir or DEFAULT_BASE_DIR,
)
```

Add CLI args:

```python
parser.add_argument("--trend-history-base-dir", default=None, help="测试/回放用 trend_history 根目录")
parser.add_argument("--disable-trend-history-write", action="store_true", help="禁用 trend_history 写入")
```

Pass them from `main()`:

```python
trend_history_base_dir=Path(args.trend_history_base_dir).resolve() if args.trend_history_base_dir else None,
disable_trend_history_write=args.disable_trend_history_write,
```

- [ ] **Step 8: Write Stage2.5 replay test**

Create `tests/test_stage25_contract_replay.py`:

```python
import json
from pathlib import Path

import scripts.stage2_5_injector as injector


def test_stage25_replay_normalizes_monetary_aliases_and_uses_tmp_trend_history(tmp_path: Path):
    market = {
        "metadata": {
            "date": "2026-04-24",
            "data_completeness": 0.85,
            "ai_websearch_enhanced": True,
            "missing_items": {"monetary_policy": [{"key": "mlf_rate"}]},
        },
        "missing_items": ["mlf_rate"],
        "macro_indicators": {},
        "monetary_policy": {"mlf_rate": {"policy_name": "MLF", "current_value": None, "unit": "%"}},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }
    manual = {
        "monetary_policy": {
            "mlf": {
                "policy_name": "MLF",
                "current_value": 2.0,
                "change_from_120d": 0.0,
                "unit": "%",
                "date": "2026-04",
                "source": "https://www.pbc.gov.cn/",
                "source_url": "https://www.pbc.gov.cn/",
            }
        }
    }
    market_path = tmp_path / "market_data_stage2.json"
    manual_path = tmp_path / "websearch_results_manual.json"
    output_path = tmp_path / "market_data_complete.json"
    trend_dir = tmp_path / "trend_history"
    market_path.write_text(json.dumps(market, ensure_ascii=False), encoding="utf-8")
    manual_path.write_text(json.dumps(manual, ensure_ascii=False), encoding="utf-8")

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        trend_history_base_dir=trend_dir,
        disable_trend_history_write=True,
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert "mlf" in saved["monetary_policy"]
    assert "mlf_rate" not in saved["monetary_policy"]
    assert saved["monetary_policy"]["mlf"]["current_value"] == 2.0
    assert saved.get("missing_items") == []
    assert not trend_dir.exists()
```

- [ ] **Step 9: Run PR3 tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_monetary_key_registry.py tests/test_missing_items_compat.py tests/test_stage25_contract_replay.py tests/test_websearch_injector.py tests/test_stage3_guard.py tests/test_stage4_docs.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit PR3**

Run:

```bash
git add src/datasource/utils/key_aliases.py src/datasource/utils/missing_items.py tests/test_monetary_key_registry.py tests/test_missing_items_compat.py tests/test_stage25_contract_replay.py src/datasource/config/search_profiles.py scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py scripts/stage3_pring_analyzer.py
git commit -m "refactor: add key registry and missing item compatibility"
```

## Task 5: PR4 Pring Module Split

**Files:**
- Create: `src/datasource/calculators/pring/__init__.py`
- Create: `src/datasource/calculators/pring/scoring.py`
- Create: `src/datasource/calculators/pring/leading_indicator.py`
- Create: `src/datasource/calculators/pring/summaries.py`
- Create: `src/datasource/calculators/pring/stage_allocations.py`
- Modify: `src/datasource/calculators/pring_analyzer.py`
- Test: `tests/test_pring_scoring_golden.py`

- [ ] **Step 1: Re-run PR2 golden before splitting**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_pring_scoring_golden.py -q
```

Expected: PASS. Stop if this fails.

- [ ] **Step 2: Create scoring module**

Create `src/datasource/calculators/pring/scoring.py`:

```python
"""Pure Pring scoring helpers."""

from __future__ import annotations

from typing import Optional, Tuple


def score_ppi_indicator(value: Optional[float], weight: float) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "PPI缺失，按中性处理"
    if value >= 0.5:
        return weight, "PPI转正，企业补库意愿增强"
    if value >= -1.0:
        return weight * 0.7, "PPI降幅收窄，价格端改善"
    return weight * 0.3, "PPI深度通缩，库存压力仍大"


def score_cpi_indicator(value: Optional[float], weight: float) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "CPI缺失，按中性处理"
    if 0 <= value <= 3:
        return weight, "CPI温和运行，内需韧性可接受"
    if -0.5 <= value < 0:
        return weight * 0.6, "轻微通缩，需求仍偏弱"
    if 3 < value <= 5:
        return weight * 0.6, "温和通胀，库存去化继续"
    return weight * 0.3, "高通胀或深度通缩波动，压制补库"


def score_pmi_indicator(value: Optional[float], weight: float) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "PMI缺失，按中性处理"
    if value >= 50.5:
        return weight, "PMI站稳荣枯线上方，补库动能充足"
    if value >= 50.0:
        return weight * 0.85, "PMI略高于荣枯线，补库初显"
    if value >= 48.0:
        return weight * 0.55, "PMI仍在收缩区，景气承压"
    return weight * 0.25, "PMI深度低于荣枯线，库存主动去化"


def score_rrr_change(change: Optional[float], weight: float) -> Tuple[float, str]:
    if change is None:
        return weight * 0.5, "缺少降准幅度，按中性处理"
    if change <= -0.5:
        return weight, "年内累计降准≥50bp，货币环境显著宽松"
    if change <= -0.25:
        return weight * 0.8, "累计降准25-50bp，宽松力度偏强"
    if change < 0:
        return weight * 0.6, "小幅降准，流动性边际改善"
    if change == 0:
        return weight * 0.4, "无降准调整，维持中性"
    return weight * 0.2, "准备金率上调或回升，呈现偏紧"
```

For the remaining score helpers, move the existing method bodies from `src/datasource/calculators/pring_analyzer.py` into functions with these names and unchanged branch logic:

```python
score_industrial_value_indicator
score_industrial_sales_indicator
score_gdp_indicator
score_bdi_indicator
score_policy_rate_change
score_dr007_change
score_tsf_growth
score_m2_growth
score_m1_growth
score_m1_m2_spread
```

- [ ] **Step 3: Delegate scoring methods from PringAnalyzer**

In `src/datasource/calculators/pring_analyzer.py`, import:

```python
from datasource.calculators.pring import scoring
```

Replace each `_score_*` method body with a one-line delegation. Example:

```python
def _score_ppi_indicator(self, value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    return scoring.score_ppi_indicator(value, weight)
```

Use the same wrapper pattern for all score methods so existing tests and internal callers keep working.

- [ ] **Step 4: Create summary module and delegate summary methods**

Create `src/datasource/calculators/pring/summaries.py`:

```python
"""Pring report-facing summary text helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def extract_highlights(details: Dict[str, str], preferred_keys: List[str], limit: int = 3) -> List[str]:
    highlights: List[str] = []
    for key in preferred_keys:
        comment = details.get(key)
        if comment:
            highlights.append(f"{key}{comment}")
            if len(highlights) >= limit:
                break
    return highlights


def build_inventory_summary_text(details: Dict[str, str], stage: str, bias: str) -> str:
    prefix = f"{stage}，{bias}。"
    highlights = extract_highlights(
        details,
        ["PPI同比", "PMI综合", "PMI新订单", "PMI生产", "工业增加值", "工业营收", "GDP同比"],
    )
    if highlights:
        return prefix + "关键驱动：" + "；".join(highlights)
    return prefix + "指标数据待WebSearch补全。"


def build_monetary_summary_text(details: Dict[str, str], stage: str, equity_bias: str, bond_bias: str) -> str:
    prefix = f"{stage}，权益偏向{equity_bias}，债券偏向{bond_bias}。"
    highlights = extract_highlights(
        details,
        ["降准幅度", "7天逆回购", "DR007变化", "M1-M2剪刀差", "M1增速", "TSF增速", "M2增速"],
    )
    if highlights:
        return prefix + "流动性信号：" + "；".join(highlights)
    return prefix + "货币指标待补数。"


def build_stage_summary_text(final_stage: Any, confidence: float, inventory_stage: str, monetary_stage: str, leading_summary: str) -> str:
    return (
        f"{final_stage.to_display_format()}（置信度{confidence:.0%}）。"
        f"库存周期：{inventory_stage}，货币周期：{monetary_stage}。"
        f"领先指标：{leading_summary}"
    )
```

Delegate `_extract_highlights`, `_build_inventory_summary_text`, `_build_monetary_summary_text`, and `_build_stage_summary_text` from `PringAnalyzer` to this module.

- [ ] **Step 5: Create stage allocation module and delegate**

Create `src/datasource/calculators/pring/stage_allocations.py` by extracting the complete dictionary currently returned by `PringAnalyzer._build_stage_allocations()` into `build_stage_allocations(pring_stage_enum)`. The extracted function must return six keys: `STAGE_I`, `STAGE_II`, `STAGE_III`, `STAGE_IV`, `STAGE_V`, and `STAGE_VI`. Do not edit any Chinese description, allocation text, focus asset list, or allocation percentage while moving the dictionary.

Add this temporary assertion inside the new function until the golden test passes, then keep it because it protects the contract:

```python
expected = {
    pring_stage_enum.STAGE_I,
    pring_stage_enum.STAGE_II,
    pring_stage_enum.STAGE_III,
    pring_stage_enum.STAGE_IV,
    pring_stage_enum.STAGE_V,
    pring_stage_enum.STAGE_VI,
}
assert set(allocations) == expected
return allocations
```

In `PringAnalyzer._build_stage_allocations`, delegate:

```python
def _build_stage_allocations(self) -> Dict[PringStage, Dict[str, Any]]:
    return stage_allocations.build_stage_allocations(PringStage)
```

Keep `_shift_stage` on `PringAnalyzer` unless a later edit can move it without changing callers.

- [ ] **Step 6: Run golden after each module delegation**

Run after scoring delegation:

```bash
bash run_clean.sh python -m pytest tests/test_pring_scoring_golden.py -q
```

Run after summary and stage allocation delegation:

```bash
bash run_clean.sh python -m pytest tests/test_pring_scoring_golden.py tests/test_stage3_guard.py -q
```

Expected: PASS after each run.

- [ ] **Step 7: Commit PR4**

Run:

```bash
git add src/datasource/calculators/pring src/datasource/calculators/pring_analyzer.py tests/test_pring_scoring_golden.py
git commit -m "refactor: split pring analyzer helpers"
```

## Task 6: PR5 Run Path Contract And Docs Consistency

**Files:**
- Create: `tests/test_run_paths_consistency.py`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `SCRIPTS.md`

- [ ] **Step 1: Write path contract tests**

Create `tests/test_run_paths_consistency.py`:

```python
from pathlib import Path

import pytest

from datasource.utils.run_paths import (
    build_run_paths,
    build_run_paths_from_reference,
    infer_date_from_path,
    normalize_run_date,
)


def test_normalize_run_date_accepts_dashed_and_compact():
    assert normalize_run_date("2026-04-27") == "2026-04-27"
    assert normalize_run_date("20260427") == "2026-04-27"


def test_normalize_run_date_rejects_invalid():
    with pytest.raises(ValueError):
        normalize_run_date("2026/04/27")


def test_build_run_paths_defaults():
    paths = build_run_paths("2026-04-27")
    assert paths.market_data == Path("data/runs/20260427/market_data.json")
    assert paths.market_data_stage2 == Path("data/runs/20260427/market_data_stage2.json")
    assert paths.market_data_complete == Path("data/runs/20260427/market_data_complete.json")
    assert paths.pring_result == Path("data/runs/20260427/pring_result.json")
    assert paths.gap_monitor == Path("data/runs/20260427/gap_monitor.json")
    assert paths.stage2_log == Path("logs/runs/20260427/stage2_unified_log.json")
    assert paths.report_markdown == Path("reports/2026-04-27-背景扫描120.md")


def test_build_run_paths_from_payload_metadata_date():
    payload = {"metadata": {"date": "2026-04-27"}}
    paths = build_run_paths_from_reference(payload=payload)
    assert paths.market_data_complete == Path("data/runs/20260427/market_data_complete.json")


def test_infer_date_from_path_supports_run_dir_and_report_name():
    assert infer_date_from_path("data/runs/20260427/market_data.json") == "2026-04-27"
    assert infer_date_from_path("reports/2026-04-27-背景扫描120.md") == "2026-04-27"
```

- [ ] **Step 2: Run path tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_run_paths_consistency.py tests/test_stage4_docs.py -q
```

Expected: PASS.

- [ ] **Step 3: Align docs to AGENTS command contract**

Search docs for stale Stage commands:

```bash
Select-String -Path AGENTS.md,CLAUDE.md,README.md,SCRIPTS.md -Pattern "stage2_5_injector|stage3_pring_analyzer|stage4_report_generator|gap-monitor|market_data_complete"
```

Edit only command examples so these defaults and explicit paths are consistent:

```bash
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"

bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated

bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md"
```

- [ ] **Step 4: Run docs/path verification**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_run_paths_consistency.py tests/test_stage4_docs.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit PR5**

Run:

```bash
git add tests/test_run_paths_consistency.py AGENTS.md CLAUDE.md README.md SCRIPTS.md
git commit -m "test: validate run path contract"
```

## Task 7: PR6 Hygiene Archive

**Files:**
- Modify/Create: `scripts/legacy/README.md`
- Modify/Create: `scripts/archive/README.md`
- Review: files under `scripts/legacy/`
- Review: files under `scripts/archive/`

- [ ] **Step 1: Verify archived scripts are not imported by active tests or stage scripts**

Run:

```bash
Select-String -Path scripts/*.py,src/datasource/**/*.py,tests/**/*.py -Pattern "scripts.legacy|scripts.archive|fill_market_data_from_yahoo|background_scan_unified|run_background_scan_pipeline" -ErrorAction SilentlyContinue
```

Expected: no active import that requires moving a script back into the active path.

- [ ] **Step 2: Add legacy README**

Create or update `scripts/legacy/README.md`:

```markdown
# Legacy Scripts

This directory contains retired or emergency-only scripts that are not part of the default Stage1 -> Stage4 daily run.

Use the active commands documented in `AGENTS.md` first. Legacy scripts may depend on older data sources or fallback paths and must not write final report data without a current source review.
```

- [ ] **Step 3: Add archive README**

Create or update `scripts/archive/README.md`:

```markdown
# Archived Scripts

This directory contains historical scripts kept for reference. They are excluded from the standard daily pipeline.

Do not use archived scripts for production data generation unless the script is reviewed, moved back to an active location, and covered by current tests or runbook documentation.
```

- [ ] **Step 4: Run smoke tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_run_paths_consistency.py tests/test_websearch_injector.py tests/test_stage3_guard.py tests/test_stage4_docs.py tests/test_pring_scoring_golden.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit PR6**

Run:

```bash
git add scripts/legacy/README.md scripts/archive/README.md
git commit -m "docs: document archived scripts"
```

## Final Verification

- [ ] **Step 1: Run all focused refactor tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_utils_coercion.py tests/test_utils_json_io.py tests/test_monetary_key_registry.py tests/test_missing_items_compat.py tests/test_stage25_contract_replay.py tests/test_pring_scoring_golden.py tests/test_run_paths_consistency.py tests/test_websearch_injector.py tests/test_stage3_guard.py tests/test_stage4_docs.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broad smoke tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage2_unified.py tests/test_stage2_fallbacks.py tests/test_policy_rules.py tests/test_simple_report_integration.py -q
```

Expected: PASS.

- [ ] **Step 3: Run compile check for touched code**

Run:

```bash
bash run_clean.sh python -m py_compile src/datasource/utils/*.py src/datasource/calculators/pring_analyzer.py src/datasource/calculators/pring/*.py scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py scripts/stage3_pring_analyzer.py scripts/stage4_report_generator.py
```

Expected: no output and exit code 0.

- [ ] **Step 4: Record live smoke as release-only**

Do not run live Tavily/API as part of each batch. After all commits land and API keys are available, run the AGENTS release smoke:

```bash
bash run_preflight.sh
bash run_clean.sh python scripts/stage3_pring_analyzer.py --market-data data/runs/20260424/market_data_complete.json --output data/runs/20260424/pring_result.json --allow-estimated
bash run_clean.sh python scripts/stage4_report_generator.py --market-data data/runs/20260424/market_data_complete.json --pring-result data/runs/20260424/pring_result.json --output reports/2026-04-24-背景扫描120.md
```

Expected: Stage3 and Stage4 complete using existing fixed data. This is not a replacement for the deterministic tests above.
