# Pipeline Audit Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shared gate/audit layer so Stage2.5, Stage3, Stage4, report rendering, and manual evidence checks use consistent production rules.

**Architecture:** Add a shared `pipeline_gates` utility that computes effective blockers from `build_pipeline_quality_state()` and gap monitor data. Stage3, Stage4, report rendering, and the new audit scripts consume that utility instead of maintaining separate gate behavior.

**Tech Stack:** Python 3.10, pytest, existing `datasource.utils.pipeline_quality_state`, existing `datasource.utils.policy_rules`, existing CLI scripts under `scripts/`.

---

## Worktree And Parallel Execution

Primary coordination worktree:

```text
/mnt/d/cursor/datasource/.worktrees/pipeline-audit-governance
branch: feature/pipeline-audit-governance
```

Baseline already verified in this worktree:

```bash
. .venv/bin/activate && python -c "from datasource import get_manager; print('OK')"
. .venv/bin/activate && pytest -q tests/test_policy_rules.py tests/test_pipeline_quality_state.py tests/test_stage4_docs.py tests/test_stage3_guard.py
```

Expected current baseline:

```text
OK
48 passed, 3 warnings
```

Parallel workers should create their own branches or worktrees from commit `8250793` or from the merged result of Task 1. Do not edit the same file from two agents at the same time. If parallel agents are used, use this dependency order:

```text
Task 1 -> Task 2, Task 3, Task 4
Task 2 -> Task 5
Task 1 -> Task 6, Task 7
Task 2 + Task 3 + Task 5 + Task 6 + Task 7 -> Task 8
Task 8 -> Task 9
```

Suggested agents:

- Agent A: Task 1 and Task 2.
- Agent B: Task 3.
- Agent C: Task 6.
- Agent D: Task 7.
- Agent E: Task 5 and Task 8 after upstream tasks land.
- Agent F: Task 9 after all source changes land.

## File Structure

Create:

- `src/datasource/utils/pipeline_gates.py` - shared effective gate filtering, gap monitor resolution, and fallback Pring assertion.
- `src/datasource/utils/pipeline_audit.py` - rule inventory and stage consistency audit.
- `src/datasource/utils/manual_evidence_audit.py` - manual source URL and evidence checks that extend, but do not redefine, existing gate rules.
- `scripts/audit_pipeline_rules.py` - CLI wrapper for rule inventory.
- `scripts/audit_pipeline_consistency.py` - CLI wrapper for effective-stage audit.
- `scripts/audit_manual_evidence.py` - CLI wrapper for manual evidence audit.
- `tests/test_pipeline_gates.py` - shared helper tests.
- `tests/test_pipeline_audit.py` - inventory and rule drift tests.
- `tests/test_manual_evidence_audit.py` - manual evidence audit tests.

Modify:

- `scripts/stage3_pring_analyzer.py` - use shared gate helpers while preserving existing CLI behavior.
- `scripts/stage4_report_generator.py` - add `--skip-fund-flow-check`, fallback result rejection, manual/pipeline audit integration.
- `src/datasource/utils/pipeline_quality_state.py` - pass report date into estimated allowlist checks.
- `src/datasource/utils/policy_rules.py` - add BDI weekend grace semantics.
- `config/policy_rules.yaml` - replace temporary BDI `max_age_days: 4` with explicit weekend grace.
- `src/datasource/generators/simple_report.py` - consume unified quality state for report quality issues.
- `AGENTS.md` - production runbook update.
- `CLAUDE.md` - quick-run and pitfall update.
- Existing tests in `tests/test_stage3_guard.py`, `tests/test_stage4_docs.py`, `tests/test_policy_rules.py`, `tests/test_pipeline_quality_state.py`.

---

### Task 1: Shared Gate Helpers

**Files:**
- Create: `src/datasource/utils/pipeline_gates.py`
- Create: `tests/test_pipeline_gates.py`

- [ ] **Step 1: Write failing tests for effective blocker filtering**

Create `tests/test_pipeline_gates.py`:

```python
import pytest

from datasource.utils.pipeline_gates import (
    FUND_FLOW_SKIP_REASONS,
    assert_no_fallback_pring_result,
    effective_gap_items,
    effective_quality_blockers,
    gap_item_label,
)


def test_fund_flow_skip_reasons_are_explicit():
    assert FUND_FLOW_SKIP_REASONS == {
        "fund_flow_window_missing",
        "estimated_not_allowed",
    }


def test_effective_quality_blockers_filters_only_fund_flow_skip_reasons():
    blockers = [
        {"category": "fund_flow", "key": "etf", "reason": "fund_flow_window_missing"},
        {"category": "fund_flow", "key": "northbound", "reason": "estimated_not_allowed"},
        {"category": "commodities", "key": "BCOM", "reason": "estimated_not_allowed"},
        {"category": "macro_indicators", "key": "industrial", "reason": "missing_compare_values"},
    ]

    assert effective_quality_blockers(blockers, skip_fund_flow_check=True) == [
        {"category": "commodities", "key": "BCOM", "reason": "estimated_not_allowed"},
        {"category": "macro_indicators", "key": "industrial", "reason": "missing_compare_values"},
    ]


def test_effective_quality_blockers_keeps_fund_flow_source_url_issues():
    blockers = [
        {"category": "fund_flow", "key": "northbound", "reason": "missing_source_url"},
    ]

    assert effective_quality_blockers(blockers, skip_fund_flow_check=True) == blockers


def test_gap_item_label_prefers_category_and_key():
    assert gap_item_label({"category": "fund_flow", "key": "etf"}) == "fund_flow.etf"
    assert gap_item_label({"symbol": "BCOM"}) == "BCOM"
    assert gap_item_label("bdi") == "bdi"


def test_effective_gap_items_filters_matching_fund_flow_quality_blockers():
    market_payload = {
        "fund_flow": {
            "etf": {"recent_5d": None, "total_120d": None},
        },
        "macro_indicators": {
            "bdi": {"current_value": 2991.0},
        },
    }
    quality_blockers = [
        {"category": "fund_flow", "key": "etf", "reason": "fund_flow_window_missing"},
        {"category": "macro_indicators", "key": "bdi", "reason": "estimated_not_allowed"},
    ]
    gap_items = [
        {"category": "fund_flow", "key": "etf"},
        {"category": "macro_indicators", "key": "bdi"},
        "missing_unknown",
    ]

    assert effective_gap_items(
        market_payload,
        quality_blockers,
        gap_items,
        skip_fund_flow_check=True,
    ) == [
        {"category": "macro_indicators", "key": "bdi"},
        "missing_unknown",
    ]


def test_assert_no_fallback_pring_result_blocks_by_default():
    with pytest.raises(RuntimeError) as exc:
        assert_no_fallback_pring_result({"fallback_used": True})

    assert "fallback_used=true" in str(exc.value)


def test_assert_no_fallback_pring_result_allows_debug_override():
    assert_no_fallback_pring_result({"fallback_used": True}, allow_fallback_report=True)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_pipeline_gates.py
```

Expected:

```text
ERROR tests/test_pipeline_gates.py
ModuleNotFoundError: No module named 'datasource.utils.pipeline_gates'
```

- [ ] **Step 3: Implement `pipeline_gates.py`**

Create `src/datasource/utils/pipeline_gates.py`:

```python
# -*- coding: utf-8 -*-
"""Shared effective gate helpers for Stage3, Stage4, and audit tools."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


FUND_FLOW_SKIP_REASONS = {
    "fund_flow_window_missing",
    "estimated_not_allowed",
}


def is_fund_flow_skippable_issue(issue: Any) -> bool:
    if not isinstance(issue, dict):
        return False
    return (
        issue.get("category") == "fund_flow"
        and issue.get("reason") in FUND_FLOW_SKIP_REASONS
    )


def effective_quality_blockers(
    blockers: Iterable[Any],
    *,
    skip_fund_flow_check: bool = False,
) -> List[Dict[str, Any]]:
    rows = [item for item in blockers or [] if isinstance(item, dict)]
    if not skip_fund_flow_check:
        return rows
    return [item for item in rows if not is_fund_flow_skippable_issue(item)]


def gap_item_key(item: Any) -> str:
    if isinstance(item, dict):
        for field in ("key", "indicator_key", "symbol", "pair", "task", "type", "name", "field"):
            value = item.get(field)
            if value not in (None, ""):
                return str(value)
        return ""
    return str(item)


def gap_item_category(item: Any) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    value = item.get("category")
    return str(value) if value not in (None, "") else None


def gap_item_label(item: Any) -> str:
    key = gap_item_key(item)
    category = gap_item_category(item)
    if category and key:
        return f"{category}.{key}"
    return key


def payload_entries(market_payload: Dict[str, Any]) -> List[Tuple[str, str]]:
    payload = market_payload if isinstance(market_payload, dict) else {}
    entries: List[Tuple[str, str]] = []
    for category in ("macro_indicators", "monetary_policy", "fund_flow"):
        rows = payload.get(category)
        if not isinstance(rows, dict):
            continue
        for key, entry in rows.items():
            if isinstance(entry, dict):
                entries.append((category, str(key)))

    key_fields = {
        "bonds": ("symbol", "name"),
        "forex": ("pair", "name"),
        "commodities": ("symbol", "name"),
        "stock_indices": ("symbol", "name", "ts_code", "code"),
    }
    for category, fields in key_fields.items():
        rows = payload.get(category)
        if not isinstance(rows, list):
            continue
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            for field in fields:
                value = entry.get(field)
                if value not in (None, ""):
                    entries.append((category, str(value)))
    return entries


def matching_payload_entries(
    market_payload: Dict[str, Any],
    gap_item: Any,
) -> List[Tuple[str, str]]:
    label = gap_item_key(gap_item).strip()
    category = gap_item_category(gap_item)
    if "." in label and category is None:
        maybe_category, maybe_key = label.split(".", 1)
        if maybe_category and maybe_key:
            category = maybe_category
            label = maybe_key

    label_norm = label.lower()
    category_norm = category.lower() if category else None
    matches: List[Tuple[str, str]] = []
    for entry_category, entry_key in payload_entries(market_payload):
        if category_norm and entry_category.lower() != category_norm:
            continue
        if entry_key.lower() == label_norm:
            matches.append((entry_category, entry_key))
    return matches


def quality_blocker_pairs(blockers: Iterable[Any]) -> Set[Tuple[str, str]]:
    pairs: Set[Tuple[str, str]] = set()
    for issue in blockers or []:
        if not isinstance(issue, dict):
            continue
        category = str(issue.get("category") or "").lower()
        key = str(issue.get("key") or "").lower()
        if category and key:
            pairs.add((category, key))
    return pairs


def effective_gap_items(
    market_payload: Dict[str, Any],
    quality_blockers: Iterable[Any],
    gap_items: Any,
    *,
    skip_fund_flow_check: bool = False,
) -> List[Any]:
    if not isinstance(gap_items, list):
        return []

    effective_blockers = effective_quality_blockers(
        quality_blockers,
        skip_fund_flow_check=skip_fund_flow_check,
    )
    blocker_pairs = quality_blocker_pairs(effective_blockers)

    unresolved: List[Any] = []
    for item in gap_items:
        if skip_fund_flow_check and gap_item_category(item) == "fund_flow":
            key = gap_item_key(item).lower()
            skipped_pair = ("fund_flow", key)
            raw_pairs = quality_blocker_pairs(
                issue for issue in quality_blockers or [] if is_fund_flow_skippable_issue(issue)
            )
            if skipped_pair in raw_pairs:
                continue

        matches = matching_payload_entries(market_payload, item)
        if not matches:
            unresolved.append(item)
            continue
        if any((category.lower(), key.lower()) in blocker_pairs for category, key in matches):
            unresolved.append(item)
    return unresolved


def assert_no_fallback_pring_result(
    pring_payload: Dict[str, Any],
    *,
    allow_fallback_report: bool = False,
) -> None:
    if allow_fallback_report:
        return
    if isinstance(pring_payload, dict) and pring_payload.get("fallback_used") is True:
        raise RuntimeError(
            "Stage4 blocked fallback Pring result: fallback_used=true. "
            "Re-run Stage3 without --allow-fallback for production reports."
        )
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_pipeline_gates.py
```

Expected:

```text
7 passed
```

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/datasource/utils/pipeline_gates.py tests/test_pipeline_gates.py
git commit -m "feat: add shared pipeline gate helpers"
```

---

### Task 2: Stage4 Gate Parity And Fallback Rejection

**Files:**
- Modify: `scripts/stage4_report_generator.py`
- Modify: `tests/test_stage4_docs.py`

- [ ] **Step 1: Add failing Stage4 tests**

Append to `tests/test_stage4_docs.py`:

```python
def test_stage4_skip_fund_flow_check_allows_etf_only_gap(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "runs" / "20260525"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()

    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"
    output_path = reports_dir / "out.md"

    market_path.write_text(
        """
{
  "metadata": {"ai_websearch_enhanced": true, "date": "2026-05-25", "data_completeness": 0.974},
  "fund_flow": {
    "etf": {"type": "etf", "recent_5d": null, "total_120d": null, "source": "异常零值-需核查"}
  }
}
""".strip(),
        encoding="utf-8",
    )
    pring_path.write_text(
        '{"metadata": {"analysis_date": "2026-05-25"}, "fallback_used": false}',
        encoding="utf-8",
    )
    gap_path.write_text(
        '{"pending_tasks": ["etf"], "manual_required": ["etf"]}',
        encoding="utf-8",
    )

    called = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stage4, "generate_report", lambda *args: called.append(args))
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(output_path),
            "--skip-fund-flow-check",
        ],
    )

    stage4.main()

    assert called == [(market_path, pring_path, output_path)]


def test_stage4_skip_fund_flow_check_does_not_allow_non_fund_flow_gap(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "runs" / "20260525"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()

    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"

    market_path.write_text(
        """
{
  "metadata": {"ai_websearch_enhanced": true, "date": "2026-05-25", "data_completeness": 0.974},
  "macro_indicators": {
    "industrial": {"current_value": 4.1, "source": "websearch_manual", "source_url": "https://example.com/industrial"}
  }
}
""".strip(),
        encoding="utf-8",
    )
    pring_path.write_text(
        '{"metadata": {"analysis_date": "2026-05-25"}, "fallback_used": false}',
        encoding="utf-8",
    )
    gap_path.write_text(
        '{"pending_tasks": ["industrial"], "manual_required": ["industrial"]}',
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(reports_dir / "out.md"),
            "--skip-fund-flow-check",
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    assert "industrial" in str(exc.value)


def test_stage4_blocks_fallback_pring_by_default(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "runs" / "20260525"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()

    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"

    market_path.write_text(
        '{"metadata": {"ai_websearch_enhanced": true, "date": "2026-05-25", "data_completeness": 0.974}}',
        encoding="utf-8",
    )
    pring_path.write_text(
        '{"metadata": {"analysis_date": "2026-05-25"}, "fallback_used": true}',
        encoding="utf-8",
    )
    gap_path.write_text('{"pending_tasks": [], "manual_required": []}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(reports_dir / "out.md"),
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    assert "fallback_used=true" in str(exc.value)


def test_stage4_allows_fallback_report_only_with_debug_flag(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "runs" / "20260525"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()

    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"
    output_path = reports_dir / "out.md"

    market_path.write_text(
        '{"metadata": {"ai_websearch_enhanced": true, "date": "2026-05-25", "data_completeness": 0.974}}',
        encoding="utf-8",
    )
    pring_path.write_text(
        '{"metadata": {"analysis_date": "2026-05-25"}, "fallback_used": true}',
        encoding="utf-8",
    )
    gap_path.write_text('{"pending_tasks": [], "manual_required": []}', encoding="utf-8")

    called = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stage4, "generate_report", lambda *args: called.append(args))
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(output_path),
            "--allow-fallback-report",
        ],
    )

    stage4.main()

    assert called == [(market_path, pring_path, output_path)]
```

- [ ] **Step 2: Run Stage4 tests and verify they fail**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_stage4_docs.py
```

Expected:

```text
FAILED tests/test_stage4_docs.py::test_stage4_skip_fund_flow_check_allows_etf_only_gap
FAILED tests/test_stage4_docs.py::test_stage4_blocks_fallback_pring_by_default
```

- [ ] **Step 3: Modify Stage4 imports and parser**

In `scripts/stage4_report_generator.py`, add imports:

```python
from datasource.utils.pipeline_gates import (
    assert_no_fallback_pring_result,
    effective_gap_items,
    effective_quality_blockers,
)
```

Add parser arguments:

```python
    parser.add_argument(
        "--skip-fund-flow-check",
        action="store_true",
        help="跳过 fund_flow 窗口/估算 blocker；生产仅允许资金流缺口临时降级，不跳过其他 gate",
    )
    parser.add_argument(
        "--allow-fallback-report",
        action="store_true",
        help="允许 fallback_used=true 的 Pring 结果生成报告（仅调试用，生产禁止）",
    )
```

- [ ] **Step 4: Update Stage4 quality and gap functions**

Change `_assert_stage4_quality_gate` signature and blocker calculation:

```python
def _assert_stage4_quality_gate(
    market_payload: Dict[str, Any],
    *,
    skip_fund_flow_check: bool = False,
) -> None:
    quality_state = build_pipeline_quality_state(
        market_payload,
        stage="stage4",
        allow_estimated=True,
    )
    quality_blockers = effective_quality_blockers(
        quality_state.get("quality_blockers") or [],
        skip_fund_flow_check=skip_fund_flow_check,
    )
    policy = quality_state.get("policy_evaluation") or {}
    policy_blocked = bool(policy.get("block_stage3")) and bool(quality_blockers)

    if not quality_blockers and not policy_blocked:
        return

    details = [format_quality_issue(issue) for issue in quality_blockers]
    if policy_blocked and not details:
        details.append("policy_evaluation.block_stage3 true")

    raise RuntimeError(
        format_gate_blocks(
            "Stage4 unified quality gate blocked report generation:",
            [GateBlock("unified_quality", details)],
        )
    )
```

Change `_unresolved_gap_items` signature and implementation:

```python
def _unresolved_gap_items(
    market_payload: Dict[str, Any],
    quality_state: Dict[str, Any],
    gap_items: Any,
    *,
    skip_fund_flow_check: bool = False,
) -> List[Any]:
    return effective_gap_items(
        market_payload,
        quality_state.get("quality_blockers") or [],
        gap_items,
        skip_fund_flow_check=skip_fund_flow_check,
    )
```

- [ ] **Step 5: Wire Stage4 main**

In `main()`, update gap filtering and fallback assertion:

```python
        pending = _unresolved_gap_items(
            market_payload,
            quality_state,
            pending,
            skip_fund_flow_check=args.skip_fund_flow_check,
        )
        manual = _unresolved_gap_items(
            market_payload,
            quality_state,
            manual,
            skip_fund_flow_check=args.skip_fund_flow_check,
        )
```

Before the `_assert_stage4_quality_gate` call in `main()`, add:

```python
    assert_no_fallback_pring_result(
        pring_payload,
        allow_fallback_report=args.allow_fallback_report,
    )
```

Call quality gate with the skip option:

```python
    _assert_stage4_quality_gate(
        market_payload,
        skip_fund_flow_check=args.skip_fund_flow_check,
    )
```

- [ ] **Step 6: Run Stage4 tests**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_stage4_docs.py tests/test_pipeline_gates.py
```

Expected:

```text
tests pass
```

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add scripts/stage4_report_generator.py tests/test_stage4_docs.py
git commit -m "fix: align stage4 gate semantics"
```

---

### Task 3: BDI Business-Day Freshness

**Files:**
- Modify: `src/datasource/utils/policy_rules.py`
- Modify: `src/datasource/utils/pipeline_quality_state.py`
- Modify: `config/policy_rules.yaml`
- Modify: `tests/test_policy_rules.py`
- Modify: `tests/test_pipeline_quality_state.py`

- [ ] **Step 1: Add failing BDI policy tests**

Append to `tests/test_policy_rules.py`:

```python
def test_bdi_allowlist_accepts_friday_value_on_monday_with_weekend_grace():
    rules = {
        "estimated_allowlist_keys": ["bdi"],
        "bdi_estimated_allow_conditions": {
            "trusted_domains": ["tradingeconomics.com"],
            "max_age_days": 2,
            "weekend_grace": True,
            "value_range": [200.0, 10000.0],
            "unit_keywords": ["points"],
        },
    }
    ok, reasons = is_estimated_allowlisted(
        "macro_indicators",
        "bdi",
        {
            "current_value": 2991.0,
            "unit": "points",
            "date": "2026-05-22",
            "as_of_date": "2026-05-22",
            "source_url": "https://tradingeconomics.com/commodity/baltic",
            "is_estimated": True,
        },
        rules=rules,
        report_date="2026-05-25",
    )

    assert ok is True
    assert reasons == []


def test_bdi_allowlist_blocks_friday_value_on_tuesday_without_holiday_grace():
    rules = {
        "estimated_allowlist_keys": ["bdi"],
        "bdi_estimated_allow_conditions": {
            "trusted_domains": ["tradingeconomics.com"],
            "max_age_days": 2,
            "weekend_grace": True,
            "value_range": [200.0, 10000.0],
            "unit_keywords": ["points"],
        },
    }
    ok, reasons = is_estimated_allowlisted(
        "macro_indicators",
        "bdi",
        {
            "current_value": 2991.0,
            "unit": "points",
            "date": "2026-05-22",
            "as_of_date": "2026-05-22",
            "source_url": "https://tradingeconomics.com/commodity/baltic",
            "is_estimated": True,
        },
        rules=rules,
        report_date="2026-05-26",
    )

    assert ok is False
    assert "bdi_date_stale:4d" in reasons
```

Append to `tests/test_pipeline_quality_state.py`:

```python
def test_pipeline_quality_state_passes_report_date_to_bdi_allowlist():
    payload = {
        "metadata": {"date": "2026-05-25"},
        "macro_indicators": {
            "bdi": {
                "current_value": 2991.0,
                "previous_value": 2964.0,
                "change_rate": 0.91,
                "unit": "points",
                "date": "2026-05-22",
                "as_of_date": "2026-05-22",
                "source_url": "https://tradingeconomics.com/commodity/baltic",
                "is_estimated": True,
            }
        },
    }
    rules = {
        "estimated_allowlist_keys": ["bdi"],
        "bdi_estimated_allow_conditions": {
            "trusted_domains": ["tradingeconomics.com"],
            "max_age_days": 2,
            "weekend_grace": True,
            "value_range": [200.0, 10000.0],
            "unit_keywords": ["points"],
        },
    }

    state = build_pipeline_quality_state(payload, policy_rules=rules, stage="stage3")

    assert state["quality_blockers"] == []
```

- [ ] **Step 2: Run BDI tests and verify they fail**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_policy_rules.py::test_bdi_allowlist_accepts_friday_value_on_monday_with_weekend_grace tests/test_policy_rules.py::test_bdi_allowlist_blocks_friday_value_on_tuesday_without_holiday_grace tests/test_pipeline_quality_state.py::test_pipeline_quality_state_passes_report_date_to_bdi_allowlist
```

Expected:

```text
TypeError: is_estimated_allowlisted() got an unexpected keyword argument 'report_date'
```

- [ ] **Step 3: Implement report-date-aware BDI checks**

In `src/datasource/utils/policy_rules.py`, add:

```python
def _coerce_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    return _parse_date(value)


def _bdi_weekend_grace_applies(entry_dt: datetime, report_dt: datetime) -> bool:
    return report_dt.weekday() == 0 and entry_dt.weekday() == 4 and (report_dt - entry_dt).days == 3
```

Update `check_bdi_estimated_allow` signature and date block:

```python
def check_bdi_estimated_allow(
    entry: Dict[str, Any],
    rules: Optional[Dict[str, Any]] = None,
    *,
    report_date: Any = None,
) -> Tuple[bool, List[str]]:
```

Replace the existing age check with:

```python
    max_age_days = int(cfg.get("max_age_days") or 2)
    dt = _parse_date(entry.get("as_of_date") or entry.get("date") or entry.get("report_period"))
    report_dt = _coerce_datetime(report_date) or datetime.now()
    if dt is None:
        reasons.append("bdi_date_missing")
    else:
        age = (report_dt - dt).days
        weekend_grace = bool(cfg.get("weekend_grace", False))
        if age > max_age_days and not (
            weekend_grace and _bdi_weekend_grace_applies(dt, report_dt)
        ):
            reasons.append(f"bdi_date_stale:{age}d")
```

Update `is_estimated_allowlisted` signature:

```python
def is_estimated_allowlisted(
    category: str,
    key: str,
    entry: Optional[Dict[str, Any]] = None,
    *,
    rules: Optional[Dict[str, Any]] = None,
    report_date: Any = None,
) -> Tuple[bool, List[str]]:
```

Update the BDI call:

```python
        ok, reasons = check_bdi_estimated_allow(entry, rules, report_date=report_date)
```

- [ ] **Step 4: Pass report date from quality state**

In `src/datasource/utils/pipeline_quality_state.py`, add helper near the top:

```python
def _payload_report_date(payload: Dict[str, Any]) -> Any:
    metadata = payload.get("metadata") if isinstance(payload, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    for field in ("date", "end_date", "start_date"):
        value = metadata.get(field) or payload.get(field)
        if value not in (None, ""):
            return value
    return None
```

Inside `build_pipeline_quality_state`, immediately after `payload = market_payload if isinstance(market_payload, dict) else {}`, add:

```python
    report_date = _payload_report_date(payload)
```

Update the allowlist call:

```python
            allowed, reasons = is_estimated_allowlisted(
                category,
                key,
                entry,
                rules=rules,
                report_date=report_date,
            )
```

- [ ] **Step 5: Update policy config**

In `config/policy_rules.yaml`, change the BDI rule to:

```yaml
bdi_estimated_allow_conditions: {"trusted_domains": ["balticexchange.com", "tradingeconomics.com", "investing.com", "eastmoney.com"], "max_age_days": 2, "weekend_grace": true, "value_range": [200.0, 10000.0], "unit_keywords": ["点", "point", "points"]}
```

- [ ] **Step 6: Run BDI tests**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_policy_rules.py tests/test_pipeline_quality_state.py
```

Expected:

```text
tests pass
```

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add src/datasource/utils/policy_rules.py src/datasource/utils/pipeline_quality_state.py config/policy_rules.yaml tests/test_policy_rules.py tests/test_pipeline_quality_state.py
git commit -m "fix: use business-day freshness for bdi"
```

---

### Task 4: Stage3 Uses Shared Gate Helpers

**Files:**
- Modify: `scripts/stage3_pring_analyzer.py`
- Modify: `tests/test_stage3_guard.py`

- [ ] **Step 1: Add Stage3 parity test**

Append to `tests/test_stage3_guard.py`:

```python
def test_stage3_skip_fund_flow_check_keeps_non_fund_flow_blockers():
    payload = {
        "metadata": {"date": "2026-05-25", "data_completeness": 0.95, "ai_websearch_enhanced": True},
        "macro_indicators": {
            "industrial": {
                "current_value": 4.1,
                "source_url": "https://example.com/industrial",
            }
        },
        "fund_flow": {
            "etf": {"recent_5d": None, "total_120d": None},
        },
    }

    with pytest.raises(RuntimeError) as exc:
        s3._require_data_completeness(
            payload,
            0.8,
            allow_estimated=True,
            skip_fund_flow_check=True,
        )

    message = str(exc.value)
    assert "macro_indicators.industrial missing_compare_values" in message
    assert "fund_flow.etf fund_flow_window_missing" not in message
```

- [ ] **Step 2: Run Stage3 parity test**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_stage3_guard.py::test_stage3_skip_fund_flow_check_keeps_non_fund_flow_blockers
```

Expected:

```text
PASS
```

This may already pass. The goal is to lock behavior before refactoring.

- [ ] **Step 3: Replace local fund-flow filtering with shared helper**

In `scripts/stage3_pring_analyzer.py`, add:

```python
from datasource.utils.pipeline_gates import (
    effective_quality_blockers,
    gap_item_key as _shared_gap_item_key,
    gap_item_label as _shared_gap_item_label,
)
```

Change `_filtered_quality_blockers` to:

```python
def _filtered_quality_blockers(
    quality_state: Dict[str, Any],
    *,
    skip_fund_flow_check: bool,
) -> List[Dict[str, Any]]:
    return effective_quality_blockers(
        quality_state.get("quality_blockers") or [],
        skip_fund_flow_check=skip_fund_flow_check,
    )
```

Change `_gap_item_key` body to:

```python
def _gap_item_key(item: Any) -> str:
    return _shared_gap_item_key(item)
```

Change `_item_label` body to:

```python
def _item_label(item: Any) -> str:
    return _shared_gap_item_label(item)
```

- [ ] **Step 4: Run Stage3 tests**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_stage3_guard.py tests/test_pipeline_gates.py
```

Expected:

```text
tests pass
```

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add scripts/stage3_pring_analyzer.py tests/test_stage3_guard.py
git commit -m "refactor: share stage3 gate filtering"
```

---

### Task 5: Report Quality Section Uses Unified State

**Files:**
- Modify: `src/datasource/generators/simple_report.py`
- Modify: `tests/test_simple_report_integration.py`

- [ ] **Step 1: Add failing report-quality test**

Append to `tests/test_simple_report_integration.py`:

```python
def test_report_quality_section_uses_unified_state_for_manual_source_url(tmp_path):
    market = _base_market()
    market["commodities"] = [
        {
            "symbol": "GC=F",
            "name": "COMEX Gold",
            "current_price": 2650.5,
            "unit": "$/oz",
            "source": "websearch_manual",
        }
    ]
    pring = {
        "metadata": {"analysis_date": market["metadata"]["date"]},
        "fallback_used": False,
        "pending_websearch": [],
    }
    m = tmp_path / "m.json"
    p = tmp_path / "p.json"
    out = tmp_path / "o.md"
    _write_json(m, market)
    _write_json(p, pring)

    generate_report(m, p, out)

    text = out.read_text(encoding="utf-8")
    assert "commodities.GC=F" in text
    assert "缺失（缺少来源URL）" in text
```

- [ ] **Step 2: Run report test and verify it fails**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_simple_report_integration.py::test_report_quality_section_uses_unified_state_for_manual_source_url
```

Expected:

```text
FAILED
```

- [ ] **Step 3: Import unified quality state**

In `src/datasource/generators/simple_report.py`, add:

```python
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state
```

Add or update reason labels:

```python
QUALITY_REASON_LABELS.update(
    {
        "missing_source_url": "缺少来源URL",
        "primary_value_missing": "当前值缺失",
        "missing_compare_values": "缺少对比值",
        "fund_flow_window_missing": "资金流窗口缺失",
    }
)
```

- [ ] **Step 4: Replace `_collect_quality_issues` implementation**

Replace `_collect_quality_issues` with:

```python
def _collect_quality_issues(market_data: dict, policy_rules: Optional[dict] = None) -> list[dict]:
    state = build_pipeline_quality_state(
        market_data,
        policy_rules=policy_rules,
        stage="stage4",
        allow_estimated=True,
    )
    issues: list[dict] = []
    for issue in state.get("quality_blockers") or []:
        if not isinstance(issue, dict):
            continue
        details = issue.get("details")
        field = ""
        if isinstance(details, dict):
            field = str(details.get("field") or "")
        issues.append(
            {
                "category": issue.get("category"),
                "key": issue.get("key"),
                "field": field or _default_quality_field(issue.get("category"), issue.get("reason")),
                "reason": issue.get("reason") or "manual_incomplete",
                "detail": details or "",
            }
        )
    return issues
```

Add helper above it:

```python
def _default_quality_field(category: Any, reason: Any) -> str:
    reason_text = str(reason or "")
    category_text = str(category or "")
    if reason_text == "missing_source_url":
        return "source_url"
    if reason_text == "missing_compare_values":
        return "previous_value/change_rate" if category_text == "macro_indicators" else "change_from_120d"
    if reason_text == "fund_flow_window_missing":
        return "recent_5d/total_120d"
    if reason_text == "primary_value_missing":
        return "current_value"
    return "value"
```

- [ ] **Step 5: Run report tests**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_simple_report_integration.py tests/test_pipeline_quality_state.py
```

Expected:

```text
tests pass
```

- [ ] **Step 6: Commit Task 5**

Run:

```bash
git add src/datasource/generators/simple_report.py tests/test_simple_report_integration.py
git commit -m "refactor: use unified quality state in reports"
```

---

### Task 6: Pipeline Rule Inventory And Consistency Audit

**Files:**
- Create: `src/datasource/utils/pipeline_audit.py`
- Create: `scripts/audit_pipeline_rules.py`
- Create: `scripts/audit_pipeline_consistency.py`
- Create: `tests/test_pipeline_audit.py`

- [ ] **Step 1: Write audit tests**

Create `tests/test_pipeline_audit.py`:

```python
from datasource.utils.pipeline_audit import build_pipeline_audit, build_rule_inventory


def test_rule_inventory_lists_shared_quality_rules():
    inventory = build_rule_inventory()
    rule_ids = {item["rule_id"] for item in inventory["rules"]}

    assert "missing_source_url" in rule_ids
    assert "fund_flow_window_missing" in rule_ids
    assert "estimated_not_allowed" in rule_ids


def test_pipeline_audit_reports_no_drift_when_only_fund_flow_is_skipped():
    market_payload = {
        "metadata": {"date": "2026-05-25", "ai_websearch_enhanced": True, "data_completeness": 0.95},
        "fund_flow": {
            "etf": {"recent_5d": None, "total_120d": None},
        },
    }
    gap_payload = {"pending_tasks": ["etf"], "manual_required": ["etf"]}
    pring_payload = {"metadata": {"analysis_date": "2026-05-25"}, "fallback_used": False}

    audit = build_pipeline_audit(
        market_payload,
        pring_payload=pring_payload,
        gap_payload=gap_payload,
        skip_fund_flow_check=True,
    )

    assert audit["errors"] == []
    assert audit["stage3_effective_blockers"] == []
    assert audit["stage4_effective_blockers"] == []


def test_pipeline_audit_errors_on_fallback_result():
    market_payload = {
        "metadata": {"date": "2026-05-25", "ai_websearch_enhanced": True, "data_completeness": 0.95},
    }
    pring_payload = {"metadata": {"analysis_date": "2026-05-25"}, "fallback_used": True}

    audit = build_pipeline_audit(
        market_payload,
        pring_payload=pring_payload,
        gap_payload={"pending_tasks": [], "manual_required": []},
        skip_fund_flow_check=False,
    )

    assert audit["errors"] == [
        {
            "code": "fallback_pring_result",
            "message": "Stage4 blocked fallback Pring result: fallback_used=true. Re-run Stage3 without --allow-fallback for production reports.",
        }
    ]
```

- [ ] **Step 2: Run audit tests and verify they fail**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_pipeline_audit.py
```

Expected:

```text
ModuleNotFoundError: No module named 'datasource.utils.pipeline_audit'
```

- [ ] **Step 3: Implement `pipeline_audit.py`**

Create `src/datasource/utils/pipeline_audit.py`:

```python
# -*- coding: utf-8 -*-
"""Pipeline audit helpers for rule inventory and stage consistency."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from datasource.utils.pipeline_gates import (
    assert_no_fallback_pring_result,
    effective_gap_items,
    effective_quality_blockers,
)
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state


def build_rule_inventory() -> Dict[str, Any]:
    return {
        "rules": [
            {
                "rule_id": "primary_value_missing",
                "source_module": "datasource.utils.pipeline_quality_state",
                "consumers": ["stage2_5", "stage3", "stage4", "report", "audit"],
                "blockable": True,
                "fund_flow_skip_allowed": False,
            },
            {
                "rule_id": "missing_compare_values",
                "source_module": "datasource.utils.pipeline_quality_state",
                "consumers": ["stage2_5", "stage3", "stage4", "report", "audit"],
                "blockable": True,
                "fund_flow_skip_allowed": False,
            },
            {
                "rule_id": "critical_stale",
                "source_module": "datasource.utils.pipeline_quality_state",
                "consumers": ["stage2_5", "stage3", "stage4", "report", "audit"],
                "blockable": True,
                "fund_flow_skip_allowed": False,
            },
            {
                "rule_id": "missing_source_url",
                "source_module": "datasource.utils.pipeline_quality_state",
                "consumers": ["stage2_5", "stage3", "stage4", "report", "audit"],
                "blockable": True,
                "fund_flow_skip_allowed": False,
            },
            {
                "rule_id": "estimated_not_allowed",
                "source_module": "datasource.utils.pipeline_quality_state",
                "consumers": ["stage2_5", "stage3", "stage4", "report", "audit"],
                "blockable": True,
                "fund_flow_skip_allowed": True,
            },
            {
                "rule_id": "fund_flow_window_missing",
                "source_module": "datasource.utils.pipeline_quality_state",
                "consumers": ["stage2_5", "stage3", "stage4", "report", "audit"],
                "blockable": True,
                "fund_flow_skip_allowed": True,
            },
            {
                "rule_id": "manual_official_not_estimated",
                "source_module": "scripts.stage2_5_injector",
                "consumers": ["stage2_5", "audit"],
                "blockable": False,
                "fund_flow_skip_allowed": False,
            },
        ]
    }


def _fallback_error(pring_payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    try:
        assert_no_fallback_pring_result(pring_payload or {})
    except RuntimeError as exc:
        return {"code": "fallback_pring_result", "message": str(exc)}
    return None


def build_pipeline_audit(
    market_payload: Dict[str, Any],
    *,
    pring_payload: Optional[Dict[str, Any]] = None,
    gap_payload: Optional[Dict[str, Any]] = None,
    skip_fund_flow_check: bool = False,
) -> Dict[str, Any]:
    state = build_pipeline_quality_state(
        market_payload,
        stage="stage4",
        allow_estimated=True,
    )
    raw_blockers = list(state.get("quality_blockers") or [])
    stage3_effective = effective_quality_blockers(
        raw_blockers,
        skip_fund_flow_check=skip_fund_flow_check,
    )
    stage4_effective = effective_quality_blockers(
        raw_blockers,
        skip_fund_flow_check=skip_fund_flow_check,
    )

    gap = gap_payload or {}
    pending = effective_gap_items(
        market_payload,
        raw_blockers,
        gap.get("pending_tasks", []),
        skip_fund_flow_check=skip_fund_flow_check,
    )
    manual = effective_gap_items(
        market_payload,
        raw_blockers,
        gap.get("manual_required", []),
        skip_fund_flow_check=skip_fund_flow_check,
    )

    errors: List[Dict[str, str]] = []
    fallback = _fallback_error(pring_payload)
    if fallback:
        errors.append(fallback)
    if stage3_effective != stage4_effective:
        errors.append(
            {
                "code": "rule_drift",
                "message": "Stage3 and Stage4 effective quality blockers differ",
            }
        )

    return {
        "raw_quality_blockers": raw_blockers,
        "stage3_effective_blockers": stage3_effective,
        "stage4_effective_blockers": stage4_effective,
        "effective_gap_monitor": {
            "pending_tasks": pending,
            "manual_required": manual,
        },
        "errors": errors,
        "warnings": [],
    }
```

- [ ] **Step 4: Implement CLI wrappers**

Create `scripts/audit_pipeline_rules.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasource.utils.pipeline_audit import build_rule_inventory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write pipeline audit rule inventory")
    parser.add_argument("--output", required=True, help="Output JSON path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_rule_inventory(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] audit rule inventory written: {output}")


if __name__ == "__main__":
    main()
```

Create `scripts/audit_pipeline_consistency.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasource.utils.pipeline_audit import build_pipeline_audit


def _load_json(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit pipeline gate consistency")
    parser.add_argument("--market-data", required=True)
    parser.add_argument("--pring-result", default=None)
    parser.add_argument("--gap-monitor", default=None)
    parser.add_argument("--skip-fund-flow-check", action="store_true")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    market_payload = _load_json(args.market_data)
    pring_payload = _load_json(args.pring_result)
    gap_payload = _load_json(args.gap_monitor)
    audit = build_pipeline_audit(
        market_payload,
        pring_payload=pring_payload,
        gap_payload=gap_payload,
        skip_fund_flow_check=args.skip_fund_flow_check,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] pipeline audit written: {output}")
    if audit.get("errors"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run audit tests**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_pipeline_audit.py tests/test_pipeline_gates.py
```

Expected:

```text
tests pass
```

- [ ] **Step 6: Commit Task 6**

Run:

```bash
git add src/datasource/utils/pipeline_audit.py scripts/audit_pipeline_rules.py scripts/audit_pipeline_consistency.py tests/test_pipeline_audit.py
git commit -m "feat: add pipeline gate audit"
```

---

### Task 7: Manual Evidence Audit

**Files:**
- Create: `src/datasource/utils/manual_evidence_audit.py`
- Create: `scripts/audit_manual_evidence.py`
- Create: `tests/test_manual_evidence_audit.py`

- [ ] **Step 1: Write manual evidence tests**

Create `tests/test_manual_evidence_audit.py`:

```python
from datasource.utils.manual_evidence_audit import audit_manual_evidence


def test_manual_evidence_errors_on_source_provider_mismatch():
    manual = {
        "commodities": [
            {
                "symbol": "BCOM",
                "current_price": 138.6635,
                "source": "Investing.com BCOM historical data",
                "source_url": "https://www.bloomberg.com/quote/BCOM:IND",
            }
        ]
    }

    result = audit_manual_evidence(manual)

    assert result["errors"] == [
        {
            "code": "source_provider_mismatch",
            "path": "commodities.BCOM",
            "message": "source mentions investing.com but source_url host is www.bloomberg.com",
        }
    ]


def test_manual_evidence_errors_on_missing_url_for_numeric_manual_value():
    manual = {
        "macro_indicators": {
            "industrial": {
                "current_value": 4.1,
                "source": "国家统计局",
            }
        }
    }

    result = audit_manual_evidence(manual)

    assert result["errors"][0]["code"] == "missing_source_url"
    assert result["errors"][0]["path"] == "macro_indicators.industrial"


def test_manual_evidence_errors_on_non_https_source_url():
    manual = {
        "monetary_policy": {
            "reserve_ratio": {
                "current_value": 6.3,
                "source": "PBoC",
                "source_url": "http://www.pbc.gov.cn/rrr",
            }
        }
    }

    result = audit_manual_evidence(manual)

    assert result["errors"][0]["code"] == "invalid_source_url"
    assert result["errors"][0]["path"] == "monetary_policy.reserve_ratio"


def test_manual_evidence_warns_on_previous_value_without_note():
    manual = {
        "macro_indicators": {
            "industrial": {
                "current_value": 4.1,
                "previous_value": 5.7,
                "source": "国家统计局",
                "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963731.html",
            }
        }
    }

    result = audit_manual_evidence(manual)

    assert result["warnings"] == [
        {
            "code": "previous_value_without_evidence_note",
            "path": "macro_indicators.industrial",
            "message": "previous_value/change_rate supplied without note or previous_source_url",
        }
    ]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_manual_evidence_audit.py
```

Expected:

```text
ModuleNotFoundError: No module named 'datasource.utils.manual_evidence_audit'
```

- [ ] **Step 3: Implement manual evidence audit module**

Create `src/datasource/utils/manual_evidence_audit.py`:

```python
# -*- coding: utf-8 -*-
"""Manual evidence audit rules that extend existing pipeline gates."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse


PROVIDER_MARKERS = {
    "investing.com": ("investing.com", "investing"),
    "bloomberg.com": ("bloomberg.com", "bloomberg", "彭博"),
    "stats.gov.cn": ("stats.gov.cn", "国家统计局"),
    "pbc.gov.cn": ("pbc.gov.cn", "中国人民银行", "央行", "pboc"),
    "tradingeconomics.com": ("tradingeconomics.com", "trading economics"),
}


def _parse_https_url(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, str) or not value.strip():
        return False, ""
    text = value.strip()
    if re.search(r"\s", text):
        return False, ""
    parsed = urlparse(text)
    try:
        parsed.port
    except ValueError:
        return False, ""
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False, ""
    return True, parsed.hostname.lower().rstrip(".")


def _has_numeric_value(entry: Dict[str, Any]) -> bool:
    fields = (
        "current_value",
        "current_price",
        "current_rate",
        "current_yield",
        "recent_5d",
        "total_120d",
    )
    for field in fields:
        value = entry.get(field)
        if isinstance(value, (int, float)) and value != 0:
            return True
        if isinstance(value, str):
            try:
                float(value.replace(",", ""))
                return True
            except ValueError:
                continue
    return False


def _iter_manual_entries(manual_payload: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    for entry in manual_payload.get("commodities", []) or []:
        if isinstance(entry, dict):
            yield f"commodities.{entry.get('symbol') or entry.get('name') or 'unknown'}", entry
    for entry in manual_payload.get("forex", []) or []:
        if isinstance(entry, dict):
            yield f"forex.{entry.get('pair') or entry.get('name') or 'unknown'}", entry
    for entry in manual_payload.get("bonds", []) or []:
        if isinstance(entry, dict):
            yield f"bonds.{entry.get('symbol') or entry.get('name') or 'unknown'}", entry
    for entry in manual_payload.get("stock_indices", []) or []:
        if isinstance(entry, dict):
            yield f"stock_indices.{entry.get('symbol') or entry.get('name') or 'unknown'}", entry
    for category in ("macro_indicators", "monetary_policy", "fund_flow"):
        rows = manual_payload.get(category) or {}
        if not isinstance(rows, dict):
            continue
        for key, entry in rows.items():
            if isinstance(entry, dict):
                yield f"{category}.{key}", entry


def _source_mentions_provider(source_text: str) -> List[str]:
    text = source_text.lower()
    providers: List[str] = []
    for provider, markers in PROVIDER_MARKERS.items():
        if any(marker.lower() in text for marker in markers):
            providers.append(provider)
    return providers


def _provider_matches_host(provider: str, host: str) -> bool:
    return host == provider or host.endswith("." + provider)


def audit_manual_evidence(
    manual_payload: Dict[str, Any],
    *,
    market_payload: Dict[str, Any] | None = None,
    stage2_log: Dict[str, Any] | None = None,
) -> Dict[str, List[Dict[str, str]]]:
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    for path, entry in _iter_manual_entries(manual_payload if isinstance(manual_payload, dict) else {}):
        if not _has_numeric_value(entry):
            continue

        source_url = entry.get("source_url") or entry.get("url")
        ok_url, host = _parse_https_url(source_url)
        if not source_url:
            errors.append(
                {
                    "code": "missing_source_url",
                    "path": path,
                    "message": "numeric manual value requires source_url",
                }
            )
            continue
        if not ok_url:
            errors.append(
                {
                    "code": "invalid_source_url",
                    "path": path,
                    "message": "source_url must be a single HTTPS URL",
                }
            )
            continue

        source_text = " ".join(str(entry.get(field) or "") for field in ("source", "note"))
        providers = _source_mentions_provider(source_text)
        mismatched = [
            provider for provider in providers if not _provider_matches_host(provider, host)
        ]
        if mismatched:
            provider = mismatched[0]
            errors.append(
                {
                    "code": "source_provider_mismatch",
                    "path": path,
                    "message": f"source mentions {provider} but source_url host is {host}",
                }
            )

        if (
            ("previous_value" in entry or "change_rate" in entry)
            and not entry.get("previous_source_url")
            and not entry.get("note")
        ):
            warnings.append(
                {
                    "code": "previous_value_without_evidence_note",
                    "path": path,
                    "message": "previous_value/change_rate supplied without note or previous_source_url",
                }
            )

    return {"errors": errors, "warnings": warnings}
```

- [ ] **Step 4: Implement CLI wrapper**

Create `scripts/audit_manual_evidence.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasource.utils.manual_evidence_audit import audit_manual_evidence


def _load_json(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit manual evidence source URLs")
    parser.add_argument("--manual-data", required=True)
    parser.add_argument("--market-data", default=None)
    parser.add_argument("--stage2-log", default=None)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = audit_manual_evidence(
        _load_json(args.manual_data),
        market_payload=_load_json(args.market_data),
        stage2_log=_load_json(args.stage2_log),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] manual evidence audit written: {output}")
    if result.get("errors"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run manual evidence tests**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_manual_evidence_audit.py
```

Expected:

```text
4 passed
```

- [ ] **Step 6: Commit Task 7**

Run:

```bash
git add src/datasource/utils/manual_evidence_audit.py scripts/audit_manual_evidence.py tests/test_manual_evidence_audit.py
git commit -m "feat: audit manual evidence URLs"
```

---

### Task 8: Stage4 Audit Integration And Documentation

**Files:**
- Modify: `scripts/stage4_report_generator.py`
- Modify: `tests/test_stage4_docs.py`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `tests/test_manual_template.py`
- Modify: `tests/test_stage4_docs.py`

- [ ] **Step 1: Add Stage4 manual audit blocking test**

Append to `tests/test_stage4_docs.py`:

```python
def test_stage4_blocks_manual_evidence_audit_errors(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "runs" / "20260525"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()

    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"
    audit_path = data_dir / "manual_evidence_audit.json"

    market_path.write_text(
        '{"metadata": {"ai_websearch_enhanced": true, "date": "2026-05-25", "data_completeness": 0.974}}',
        encoding="utf-8",
    )
    pring_path.write_text(
        '{"metadata": {"analysis_date": "2026-05-25"}, "fallback_used": false}',
        encoding="utf-8",
    )
    gap_path.write_text('{"pending_tasks": [], "manual_required": []}', encoding="utf-8")
    audit_path.write_text(
        '{"errors": [{"code": "source_provider_mismatch", "path": "commodities.BCOM", "message": "bad url"}], "warnings": []}',
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stage4_report_generator.py",
            "--market-data",
            str(market_path),
            "--pring-result",
            str(pring_path),
            "--output",
            str(reports_dir / "out.md"),
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    assert "manual_evidence_audit" in str(exc.value)
    assert "commodities.BCOM" in str(exc.value)
```

- [ ] **Step 2: Run Stage4 audit test and verify it fails**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_stage4_docs.py::test_stage4_blocks_manual_evidence_audit_errors
```

Expected:

```text
FAILED
```

- [ ] **Step 3: Add Stage4 audit file checks**

In `scripts/stage4_report_generator.py`, add helper:

```python
def _assert_json_audit_clean(path: Path, audit_name: str) -> None:
    if not path.exists():
        return
    payload = json.load(path.open("r", encoding="utf-8"))
    errors = payload.get("errors") or []
    if errors:
        raise RuntimeError(
            f"{audit_name} contains blocking errors ({path}): {errors}"
        )
```

After the `_assert_pring_matches_market(market_payload, pring_payload)` call, add:

```python
    _assert_json_audit_clean(run_paths.manual_evidence_audit, "manual_evidence_audit")
    _assert_json_audit_clean(run_paths.pipeline_audit, "pipeline_audit")
```

If `RunPaths` does not define these properties yet, add local paths:

```python
    manual_audit_path = run_paths.run_dir / "manual_evidence_audit.json"
    pipeline_audit_path = run_paths.run_dir / "pipeline_audit.json"
    _assert_json_audit_clean(manual_audit_path, "manual_evidence_audit")
    _assert_json_audit_clean(pipeline_audit_path, "pipeline_audit")
```

- [ ] **Step 4: Update docs**

In `AGENTS.md`, update the Stage4 command to include the fund-flow skip only in the explicit ETF downgrade path:

```bash
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md" \
  --skip-fund-flow-check
```

Add this production rule text:

```markdown
- 生产禁止使用 `--allow-fallback`、`--skip-gap-check` 或直接调用 `generate_report()` 生成正式报告。
- 若仅剩 ETF/fund_flow 窗口缺口，可在 Stage3 和 Stage4 同时使用 `--skip-fund-flow-check`；该参数只过滤 fund_flow 窗口/估算 blocker，不绕过其他 gate。
- 任意 `config/policy_rules.yaml` 或 `_manual.json` 修改后，必须按 Stage2.5 -> Stage3 -> Stage4 顺序重跑。
- Stage4 默认拒绝 `pring_result.fallback_used=true`；`--allow-fallback-report` 仅调试用，生产禁止。
- manual `source_url` 必须是支持该值的证据 URL，不得填品牌入口、占位 URL 或与 `source` 声称平台不一致的 URL。
```

In `CLAUDE.md`, mirror the same high-frequency reminders under Operational Pitfalls.

- [ ] **Step 5: Run docs and Stage4 tests**

Run:

```bash
. .venv/bin/activate && pytest -q tests/test_stage4_docs.py tests/test_manual_template.py
```

Expected:

```text
tests pass
```

- [ ] **Step 6: Commit Task 8**

Run:

```bash
git add scripts/stage4_report_generator.py tests/test_stage4_docs.py AGENTS.md CLAUDE.md tests/test_manual_template.py
git commit -m "docs: document production audit gates"
```

---

### Task 9: Final Verification And 2026-05-25 Replay Checks

**Files:**
- No source changes unless verification finds a bug.
- May update run artifacts only if the user explicitly wants regenerated artifacts committed.

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
. .venv/bin/activate && pytest -q \
  tests/test_pipeline_gates.py \
  tests/test_policy_rules.py \
  tests/test_pipeline_quality_state.py \
  tests/test_stage3_guard.py \
  tests/test_stage4_docs.py \
  tests/test_pipeline_audit.py \
  tests/test_manual_evidence_audit.py \
  tests/test_simple_report_integration.py \
  tests/test_manual_template.py
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 2: Run import and compile checks**

Run:

```bash
. .venv/bin/activate && python -c "from datasource import get_manager; print('OK')"
. .venv/bin/activate && python -m py_compile \
  src/datasource/utils/pipeline_gates.py \
  src/datasource/utils/pipeline_audit.py \
  src/datasource/utils/manual_evidence_audit.py \
  scripts/audit_pipeline_rules.py \
  scripts/audit_pipeline_consistency.py \
  scripts/audit_manual_evidence.py \
  scripts/stage4_report_generator.py \
  scripts/stage3_pring_analyzer.py
```

Expected:

```text
OK
```

- [ ] **Step 3: Run audit tools against current 2026-05-25 artifacts if present**

Run from repo root:

```bash
DATE_NH=20260525
. .venv/bin/activate && python scripts/audit_pipeline_rules.py \
  --output "data/runs/${DATE_NH}/audit_rule_inventory.json"
. .venv/bin/activate && python scripts/audit_manual_evidence.py \
  --manual-data "data/runs/${DATE_NH}/websearch_results_manual.json" \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --stage2-log "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --output "data/runs/${DATE_NH}/manual_evidence_audit.json"
. .venv/bin/activate && python scripts/audit_pipeline_consistency.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json" \
  --skip-fund-flow-check \
  --output "data/runs/${DATE_NH}/pipeline_audit.json"
```

Expected for the pre-fix 2026-05-25 artifacts:

```text
manual evidence audit reports BCOM source/source_url mismatch
pipeline audit reports fallback_pring_result while pring_result.fallback_used=true
```

If these expected pre-fix errors appear, do not commit regenerated artifacts unless the user asks for artifact commits.

- [ ] **Step 4: Document verification outcome in final response**

Include:

- worktree path
- branch name
- tests run
- audit tool result summary
- whether 2026-05-25 artifacts were regenerated

- [ ] **Step 5: Commit any verification-only docs if created**

Only run this if a verification note is intentionally added:

```bash
git add docs/superpowers/plans/2026-05-25-pipeline-audit-governance.md
git commit -m "docs: add pipeline audit implementation plan"
```

---

## Final Handoff Checklist

Before claiming the implementation complete:

- [ ] `git status --short` shows only intended changes.
- [ ] Focused regression suite passes.
- [ ] Stage4 blocks `fallback_used=true` by default.
- [ ] Stage4 accepts ETF-only fund-flow gap only with `--skip-fund-flow-check`.
- [ ] BDI Friday-on-Monday test passes.
- [ ] Manual evidence audit catches BCOM source/provider mismatch.
- [ ] `AGENTS.md` and `CLAUDE.md` mention production/debug command boundaries.
- [ ] No command sessions are still running.
