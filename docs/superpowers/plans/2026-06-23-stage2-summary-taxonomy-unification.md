# Stage2 Summary Taxonomy Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Stage2 CLI/JSON category breakdown and stale-refresh accounting reconcile with the canonical `stage2_effective_*` metrics, via three new pure helpers and two format helpers in `diagnostics.py`, wired into `cli.py`.

**Architecture:** Pure presentation/statistics layer. All counting logic moves out of `cli.py` inline loops into testable pure functions in `src/datasource/engines/stage2/diagnostics.py`. `cli.py` only calls the helpers and prints. No pipeline behavior, data values, exit code, or `stage2_effective_*` metric changes.

**Tech Stack:** Python 3.7+, pytest. Run everything through `bash run_clean.sh` (loads `.venv` + `.env`, sets `PYTHONPATH=./src`, clears proxies).

**Spec:** `docs/superpowers/specs/2026-06-23-stage2-summary-taxonomy-unification-design.md`

---

## Background the implementer needs

- The Stage2 summary is assembled in `src/datasource/engines/stage2/cli.py` inside `_run_stage2` (around lines 845-1013) and written to the run log JSON by `_dump_json(summary, log_output)`.
- A task dict carries a canonical `category` (one of `forex`, `commodities`, `bonds`, `macro_indicators`, `monetary_policy`, `fund_flow`), set throughout `execution.py`. The OLD code in `cli.py` ignored it and re-derived category from `indicator_key` only — which had no `monetary_policy` bucket. The fix reads the task's own `category` first.
- Completed tasks have `result_type` in `{"search_success", "structured_success", "skipped_existing"}`. Failures carry `result_type == "manual_required"`.
- The authoritative count helper already exists: `diagnostics._build_stage2_result_count_fields(completed_tasks, failures)` returns `stage2_effective_success`, `task_search_success`, `task_structured_success`, `task_skipped_existing`, `stage2_effective_failure`, etc. The new breakdown must reconcile **to** these.
- `_is_force_refresh_task` (in `common.py`) is the canonical "is this a stale/forced refresh task" predicate (`force_refresh` OR `trigger_reason == "stale_data"`).
- New unit tests live in `tests/test_stage2_unified.py`. That file already does `from datasource.engines.stage2 import diagnostics as stage2_diagnostics`, so new tests call `stage2_diagnostics._helper(...)` directly — **do not** touch the `SimpleNamespace` block.

## File Structure

- Modify `src/datasource/engines/stage2/diagnostics.py` — add imports + `_task_category`, `_new_category_counts`, `_build_stage2_category_breakdown`, `_build_stale_refresh_fields`, `_format_stage2_category_line`, `_format_stage2_stale_line`.
- Modify `src/datasource/engines/stage2/cli.py` — remove the inline category/stale code, call the new helpers, change the summary dict keys, replace the print lines, fix the now-unused import.
- Modify `tests/test_stage2_unified.py` — add focused unit tests for each helper.
- Modify `AGENTS.md` and `CLAUDE.md` — update the Stage2 summary metric description.

---

### Task 1: `_task_category` helper

**Files:**
- Modify: `src/datasource/engines/stage2/diagnostics.py` (imports near top + new code after the imports block, before `_missing_required_output_fields`)
- Test: `tests/test_stage2_unified.py`

- [ ] **Step 1: Update imports in `diagnostics.py`**

Replace the existing line:

```python
from datasource.engines.stage2.common import _entry_for_task, _safe_number
```

with:

```python
from datasource.engines.stage2.common import (
    _BOND_UPSERT_META,
    _COMMODITY_UPSERT_META,
    _FOREX_UPSERT_META,
    _entry_for_task,
    _is_force_refresh_task,
    _safe_number,
)
from datasource.utils.key_aliases import canonical_monetary_key
```

- [ ] **Step 2: Write the failing test**

Add to the end of `tests/test_stage2_unified.py`:

```python
def test_task_category_reads_task_category_field_for_monetary():
    task = {"category": "monetary_policy", "indicator_key": "reverse_repo"}
    assert stage2_diagnostics._task_category(task) == "monetary_policy"


def test_task_category_normalizes_macro_alias():
    assert stage2_diagnostics._task_category({"category": "macro"}) == "macro_indicators"


def test_task_category_falls_back_to_indicator_key():
    assert stage2_diagnostics._task_category({"indicator_key": "reverse_repo"}) == "monetary_policy"
    assert stage2_diagnostics._task_category({"indicator_key": "northbound"}) == "fund_flow"
    assert stage2_diagnostics._task_category({"indicator_key": "DXY"}) == "forex"
    assert stage2_diagnostics._task_category({"indicator_key": "GC=F"}) == "commodities"
    assert stage2_diagnostics._task_category({"indicator_key": "CN10Y_CDB"}) == "bonds"


def test_task_category_defaults_to_macro_indicators():
    assert stage2_diagnostics._task_category({"indicator_key": "cpi"}) == "macro_indicators"
    assert stage2_diagnostics._task_category({"category": "all", "indicator_key": "cpi"}) == "macro_indicators"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k task_category -v`
Expected: FAIL with `AttributeError: module ... has no attribute '_task_category'`

- [ ] **Step 4: Write minimal implementation**

In `diagnostics.py`, immediately after the imports block (before `def _missing_required_output_fields`), add:

```python
_CANONICAL_CATEGORIES = (
    "forex",
    "commodities",
    "bonds",
    "macro_indicators",
    "monetary_policy",
    "fund_flow",
)
_FUND_FLOW_KEYS = {"northbound", "southbound", "etf", "margin"}
# Fallback set only; the primary path reads the task's own canonical category.
_MONETARY_KEYS = {
    "reserve_ratio",
    "rrr",
    "mlf",
    "mlf_rate",
    "reverse_repo",
    "reverse_repo_7d",
    "m0",
    "m1",
    "m2",
    "tsf",
    "tsf_growth",
}


def _task_category(task: Dict[str, Any]) -> str:
    cat = (
        task.get("quality_gap_category")
        or task.get("category")
        or task.get("stage_phase")
    )
    if cat in {None, "", "assets", "essential", "all"}:
        cat = None
    if cat:
        cat = str(cat)
        if cat == "macro":
            cat = "macro_indicators"
        return cat if cat in _CANONICAL_CATEGORIES else "macro_indicators"
    ind = str(task.get("indicator_key") or "")
    if ind in _FUND_FLOW_KEYS:
        return "fund_flow"
    if ind in _FOREX_UPSERT_META:
        return "forex"
    if ind in _COMMODITY_UPSERT_META:
        return "commodities"
    if ind in _BOND_UPSERT_META:
        return "bonds"
    if ind in _MONETARY_KEYS or canonical_monetary_key(ind) in _MONETARY_KEYS:
        return "monetary_policy"
    return "macro_indicators"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k task_category -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add src/datasource/engines/stage2/diagnostics.py tests/test_stage2_unified.py
git commit -m "feat: add _task_category canonical bucket helper for Stage2 summary"
```

---

### Task 2: `_build_stage2_category_breakdown` helper

**Files:**
- Modify: `src/datasource/engines/stage2/diagnostics.py` (add after `_task_category`)
- Test: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write the failing test**

Add to the end of `tests/test_stage2_unified.py`:

```python
def _sample_stage2_rows():
    completed = [
        {"indicator_key": "reverse_repo", "category": "monetary_policy", "result_type": "structured_success"},
        {"indicator_key": "DXY", "category": "forex", "result_type": "structured_success"},
        {"indicator_key": "etf", "category": "fund_flow", "result_type": "search_success"},
        {"indicator_key": "northbound", "category": "fund_flow", "result_type": "skipped_existing"},
        {"indicator_key": "southbound", "category": "fund_flow", "result_type": "skipped_existing"},
    ]
    failures = [
        {"indicator_key": "mlf", "category": "monetary_policy", "result_type": "manual_required"},
        {"indicator_key": "cpi", "category": "macro_indicators", "result_type": "manual_required"},
    ]
    tasks = completed + failures
    return tasks, completed, failures


def test_category_breakdown_reconciles_with_result_count_fields():
    tasks, completed, failures = _sample_stage2_rows()
    breakdown = stage2_diagnostics._build_stage2_category_breakdown(tasks, completed, failures)
    counts = stage2_diagnostics._build_stage2_result_count_fields(completed, failures)

    assert sum(c["effective_success"] for c in breakdown.values()) == counts["stage2_effective_success"]
    assert sum(c["search_success"] for c in breakdown.values()) == counts["task_search_success"]
    assert sum(c["structured_success"] for c in breakdown.values()) == counts["task_structured_success"]
    assert sum(c["skipped_existing"] for c in breakdown.values()) == counts["task_skipped_existing"]
    assert sum(c["manual_required"] for c in breakdown.values()) == counts["stage2_effective_failure"]
    assert sum(c["total"] for c in breakdown.values()) == len(tasks)


def test_category_breakdown_does_not_count_stage1_skipped_as_success():
    tasks, completed, failures = _sample_stage2_rows()
    breakdown = stage2_diagnostics._build_stage2_category_breakdown(tasks, completed, failures)

    assert breakdown["fund_flow"]["effective_success"] == 1
    assert breakdown["fund_flow"]["skipped_existing"] == 2
    assert breakdown["monetary_policy"]["effective_success"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k category_breakdown -v`
Expected: FAIL with `AttributeError: ... '_build_stage2_category_breakdown'`

- [ ] **Step 3: Write minimal implementation**

In `diagnostics.py`, immediately after `_task_category`, add:

```python
def _new_category_counts() -> Dict[str, int]:
    return {
        "total": 0,
        "effective_success": 0,
        "search_success": 0,
        "structured_success": 0,
        "skipped_existing": 0,
        "manual_required": 0,
    }


def _build_stage2_category_breakdown(
    tasks: List[Dict[str, Any]],
    completed_tasks: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    breakdown: Dict[str, Dict[str, int]] = {}

    def _bucket(task: Dict[str, Any]) -> Dict[str, int]:
        return breakdown.setdefault(_task_category(task), _new_category_counts())

    for task in tasks:
        _bucket(task)["total"] += 1
    for task in completed_tasks:
        counts = _bucket(task)
        result_type = task.get("result_type")
        if result_type == "search_success":
            counts["search_success"] += 1
            counts["effective_success"] += 1
        elif result_type == "structured_success":
            counts["structured_success"] += 1
            counts["effective_success"] += 1
        elif result_type == "skipped_existing":
            counts["skipped_existing"] += 1
    for task in failures:
        if task.get("result_type") == "manual_required":
            _bucket(task)["manual_required"] += 1
    return breakdown
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k category_breakdown -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/datasource/engines/stage2/diagnostics.py tests/test_stage2_unified.py
git commit -m "feat: add _build_stage2_category_breakdown reconciled with effective metrics"
```

---

### Task 3: `_build_stale_refresh_fields` helper

**Files:**
- Modify: `src/datasource/engines/stage2/diagnostics.py` (add after `_build_stage2_category_breakdown`)
- Test: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write the failing test**

Add to the end of `tests/test_stage2_unified.py`:

```python
def test_stale_refresh_fields_count_structured_success_and_partition():
    tasks = [
        {"indicator_key": "reverse_repo", "force_refresh": True},
        {"indicator_key": "mlf", "trigger_reason": "stale_data"},
        {"indicator_key": "m1", "force_refresh": True},
        {"indicator_key": "m2", "force_refresh": True},
        {"indicator_key": "cpi"},
    ]
    completed = [
        {"indicator_key": "reverse_repo", "force_refresh": True, "result_type": "structured_success"},
        {"indicator_key": "m1", "force_refresh": True, "result_type": "skipped_existing"},
    ]
    failures = [
        {"indicator_key": "mlf", "trigger_reason": "stale_data", "result_type": "manual_required"},
        {"indicator_key": "m2", "force_refresh": True, "result_type": "manual_required"},
    ]
    fields = stage2_diagnostics._build_stale_refresh_fields(tasks, completed, failures)

    assert fields["task_stale_refresh_forced"] == 4
    assert fields["task_stale_refresh_success"] == 1  # structured_success counts
    assert fields["task_stale_refresh_skipped"] == 1
    assert fields["task_stale_refresh_failed"] == 2
    assert fields["task_stale_refresh_pending"] == 0
    assert (
        fields["task_stale_refresh_forced"]
        == fields["task_stale_refresh_success"]
        + fields["task_stale_refresh_skipped"]
        + fields["task_stale_refresh_failed"]
        + fields["task_stale_refresh_pending"]
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k stale_refresh -v`
Expected: FAIL with `AttributeError: ... '_build_stale_refresh_fields'`

- [ ] **Step 3: Write minimal implementation**

In `diagnostics.py`, immediately after `_build_stage2_category_breakdown`, add:

```python
def _build_stale_refresh_fields(
    tasks: List[Dict[str, Any]],
    completed_tasks: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> Dict[str, int]:
    forced = sum(1 for t in tasks if _is_force_refresh_task(t))
    success = sum(
        1
        for t in completed_tasks
        if _is_force_refresh_task(t)
        and t.get("result_type") in {"search_success", "structured_success"}
    )
    skipped = sum(
        1
        for t in completed_tasks
        if _is_force_refresh_task(t) and t.get("result_type") == "skipped_existing"
    )
    failed = sum(1 for t in failures if _is_force_refresh_task(t))
    pending = max(0, forced - success - skipped - failed)
    return {
        "task_stale_refresh_forced": forced,
        "task_stale_refresh_success": success,
        "task_stale_refresh_failed": failed,
        "task_stale_refresh_skipped": skipped,
        "task_stale_refresh_pending": pending,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k stale_refresh -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/datasource/engines/stage2/diagnostics.py tests/test_stage2_unified.py
git commit -m "feat: add _build_stale_refresh_fields with full forced-task partition"
```

---

### Task 4: category / stale format helpers

**Files:**
- Modify: `src/datasource/engines/stage2/diagnostics.py` (add after `_build_stale_refresh_fields`)
- Test: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write the failing test**

Add to the end of `tests/test_stage2_unified.py`:

```python
def test_format_category_line_sums_effective_success_and_shows_monetary():
    summary = {
        "stage2_category_breakdown": {
            "monetary_policy": {"total": 7, "effective_success": 6, "search_success": 0,
                                "structured_success": 6, "skipped_existing": 0, "manual_required": 1},
            "fund_flow": {"total": 3, "effective_success": 1, "search_success": 1,
                          "structured_success": 0, "skipped_existing": 2, "manual_required": 0},
        }
    }
    line = stage2_diagnostics._format_stage2_category_line(summary)
    assert "monetary_policy" in line
    assert "合计有效成功 7" in line  # 6 + 1
    assert "跳过已有 2" in line


def test_format_stale_line_shows_full_partition():
    summary = {
        "task_stale_refresh_forced": 10,
        "task_stale_refresh_success": 1,
        "task_stale_refresh_skipped": 0,
        "task_stale_refresh_failed": 4,
        "task_stale_refresh_pending": 5,
    }
    line = stage2_diagnostics._format_stage2_stale_line(summary)
    assert "stale强制刷新 10 项" in line
    assert "成功 1" in line
    assert "其它 5" in line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k "format_category_line or format_stale_line" -v`
Expected: FAIL with `AttributeError: ... '_format_stage2_category_line'`

- [ ] **Step 3: Write minimal implementation**

In `diagnostics.py`, immediately after `_build_stale_refresh_fields`, add:

```python
def _format_stage2_category_line(summary: Dict[str, Any]) -> str:
    breakdown = summary.get("stage2_category_breakdown", {}) or {}
    ordered = sorted(
        breakdown.items(),
        key=lambda kv: (-kv[1].get("effective_success", 0), kv[0]),
    )
    parts = [
        f"{cat} {counts.get('effective_success', 0)}/{counts.get('total', 0)}"
        for cat, counts in ordered
    ]
    search = sum(c.get("search_success", 0) for c in breakdown.values())
    structured = sum(c.get("structured_success", 0) for c in breakdown.values())
    skipped = sum(c.get("skipped_existing", 0) for c in breakdown.values())
    manual = sum(c.get("manual_required", 0) for c in breakdown.values())
    effective = sum(c.get("effective_success", 0) for c in breakdown.values())
    return (
        f"  分类型(有效成功/总数): {', '.join(parts)}\n"
        f"    其中 搜索链路 {search}, 结构化 {structured}, 跳过已有 {skipped}, "
        f"待人工 {manual} (合计有效成功 {effective})\n"
        f"    注: fund_flow 有效成功仅计 Stage2 写回(如 etf); "
        f"northbound/southbound 为 Stage1 数据,列在\"跳过已有\""
    )


def _format_stage2_stale_line(summary: Dict[str, Any]) -> str:
    return (
        f"  stale强制刷新 {summary['task_stale_refresh_forced']} 项 "
        f"(成功 {summary['task_stale_refresh_success']}, "
        f"跳过 {summary['task_stale_refresh_skipped']}, "
        f"待人工 {summary['task_stale_refresh_failed']}, "
        f"其它 {summary['task_stale_refresh_pending']})"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k "format_category_line or format_stale_line" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/datasource/engines/stage2/diagnostics.py tests/test_stage2_unified.py
git commit -m "feat: add Stage2 category/stale summary format helpers"
```

---

### Task 5: Wire helpers into `cli.py` and drop the inline code

**Files:**
- Modify: `src/datasource/engines/stage2/cli.py` (import block ~41-49; summary assembly ~849-874; summary dict ~887-949; print block ~1003-1008)

- [ ] **Step 1: Update the `common` import (line 41)**

`_is_force_refresh_task` becomes unused in `cli.py` after this task (it is only used at line 872, removed below). Change:

```python
from datasource.engines.stage2.common import _is_force_refresh_task, _safe_number
```

to:

```python
from datasource.engines.stage2.common import _safe_number
```

- [ ] **Step 2: Add the new helpers to the `diagnostics` import (lines 42-49)**

Change the import block to:

```python
from datasource.engines.stage2.diagnostics import (
    _STAGE2_BACKEND_SUMMARY_KEYS,
    _build_stage2_category_breakdown,
    _build_stage2_result_count_fields,
    _build_stage2_summary_diagnostics,
    _build_stale_refresh_fields,
    _format_stage2_category_line,
    _format_stage2_hit_rate_line,
    _format_stage2_stale_line,
    _format_stage2_task_count_line,
    _structured_provider_summary_fields,
)
```

- [ ] **Step 3: Replace the inline category + stale block (current lines 848-874)**

Delete this entire block:

```python
    # per-type 成功率统计
    def _indicator_category(ind: str) -> str:
        if ind in {"northbound", "southbound", "etf", "margin"}:
            return "fund_flow"
        if ind in {"USDCNY", "USDCNH", "DXY", "EURUSD", "GBPUSD", "USDJPY"}:
            return "forex"
        if ind in {"GC=F", "CL=F", "BZ=F", "HG=F", "BCOM", "GSG"}:
            return "commodities"
        if ind in {"US10Y", "CN10Y", "CN10Y_CDB"}:
            return "bonds"
        return "macro"

    success_by_cat = {}
    incremental_success_by_cat = {}
    total_by_cat = {}
    for t in tasks:
        cat = _indicator_category(t["indicator_key"])
        total_by_cat[cat] = total_by_cat.get(cat, 0) + 1
    for t in completed_tasks:
        cat = _indicator_category(t["indicator_key"])
        success_by_cat[cat] = success_by_cat.get(cat, 0) + 1
        if t.get("result_type") == "search_success":
            incremental_success_by_cat[cat] = incremental_success_by_cat.get(cat, 0) + 1
    result_count_fields = _build_stage2_result_count_fields(completed_tasks, failures)
    stale_refresh_forced = sum(1 for t in tasks if _is_force_refresh_task(t))
    stale_refresh_success = sum(1 for t in completed_tasks if t.get("force_refresh") and t.get("result_type") == "search_success")
    stale_refresh_failed = sum(1 for t in failures if t.get("force_refresh"))
```

and replace it with:

```python
    result_count_fields = _build_stage2_result_count_fields(completed_tasks, failures)
    category_breakdown = _build_stage2_category_breakdown(tasks, completed_tasks, failures)
    stale_refresh_fields = _build_stale_refresh_fields(tasks, completed_tasks, failures)
```

- [ ] **Step 4: Replace the three stale lines in the summary dict (current lines 887-889)**

Change:

```python
        "task_stale_refresh_forced": stale_refresh_forced,
        "task_stale_refresh_success": stale_refresh_success,
        "task_stale_refresh_failed": stale_refresh_failed,
```

to:

```python
        **stale_refresh_fields,
```

- [ ] **Step 5: Replace the three flat category keys in the summary dict (current lines 947-949)**

Change:

```python
        "success_by_category": success_by_cat,
        "search_success_by_category": incremental_success_by_cat,
        "total_by_category": total_by_cat,
```

to:

```python
        "stage2_category_breakdown": category_breakdown,
```

- [ ] **Step 6: Replace the print block (current lines 1003-1008)**

Change:

```python
    if summary.get("success_by_category"):
        print(f"  分类型成功: {summary['success_by_category']} / {summary['total_by_category']}")
        print(f"  分类型搜索链路成功: {summary.get('search_success_by_category', {})} / {summary['total_by_category']}")
    print(
        f"  stale强制刷新 {summary['task_stale_refresh_forced']} 项 "
        f"(成功 {summary['task_stale_refresh_success']}, 失败 {summary['task_stale_refresh_failed']})"
    )
```

to:

```python
    if summary.get("stage2_category_breakdown"):
        print(_format_stage2_category_line(summary))
    print(_format_stage2_stale_line(summary))
```

- [ ] **Step 7: Verify no dangling references remain**

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -v`
Then: `bash run_clean.sh python -m py_compile src/datasource/engines/stage2/cli.py src/datasource/engines/stage2/diagnostics.py`
Then: `bash run_clean.sh flake8 src/datasource/engines/stage2/cli.py src/datasource/engines/stage2/diagnostics.py`
Expected: tests PASS; py_compile silent (exit 0); flake8 no F401/F811/F841 (no unused `_is_force_refresh_task`, no leftover `success_by_cat`).

- [ ] **Step 8: Run the broader Stage2 regression**

Run: `bash run_clean.sh python -m pytest -q tests/test_stage2_unified.py tests/test_stage2_structured_integration.py tests/test_stage2_structured_golden.py tests/test_stage2_c2_split_characterization.py`
Expected: PASS. Note (already verified): no test asserts on the removed flat keys `success_by_category`/`search_success_by_category`/`total_by_category`. `test_stage2_c2_split_characterization.py` only checks that the source markers `_mark_stale_refresh_failure` and the note string `"stale_refresh_failed"` exist — both live in `execution.py` (untouched), so they stay green.

- [ ] **Step 9: Commit**

```bash
git add src/datasource/engines/stage2/cli.py
git commit -m "refactor: wire Stage2 summary category/stale helpers, drop inline counters"
```

---

### Task 6: Update docs

**Files:**
- Modify: `AGENTS.md`, `CLAUDE.md`

- [ ] **Step 1: Update the Stage2 summary description**

In both `AGENTS.md` (section "## 6. Stage2 搜索/抽取规则" summary metrics paragraph) and `CLAUDE.md` (the "Stage2 summary 中 ..." bullet under "Stage2/Stage2.5 搜索优化要点"), add one sentence stating:

> 分类型口径用嵌套 `stage2_category_breakdown`（每个 canonical category 含 `effective_success/search_success/structured_success/skipped_existing/manual_required/total`）取代旧的扁平 `success_by_category/search_success_by_category/total_by_category`；`fund_flow.effective_success` 只计 Stage2 写回（如 etf），Stage1 带来的 northbound/southbound 计入 `skipped_existing`。`stale强制刷新` 现按 `forced == 成功 + 跳过 + 待人工 + 其它` 完整切分，`成功` 含 structured_success。

Keep `stage2_effective_hit_rate` described as the authoritative daily success metric (unchanged).

- [ ] **Step 2: Run the doc-contract tests (safety check)**

Run: `bash run_clean.sh python -m pytest -q tests/test_manual_template.py tests/test_stage4_docs.py`
Expected: PASS (these assert runbook command examples; this edit changes none, so they must stay green).

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: describe stage2_category_breakdown and stale partition in summary"
```

---

### Task 7: Full regression gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `bash run_clean.sh python -m pytest -q`
Expected: PASS (no regressions). If any test references the removed flat keys, fix that test to read `stage2_category_breakdown` and re-run.

- [ ] **Step 2: Optional live smoke (only if a Stage2 run is available)**

If a fresh `data/runs/<DATE_NH>/market_data_stage2.json` run log is produced, confirm in the log JSON that `stage2_category_breakdown` is present, the per-category `effective_success` sums to `stage2_effective_success`, a `monetary_policy` bucket appears when monetary tasks ran, and `task_stale_refresh_forced == success + skipped + failed + pending`. Do not trigger a Stage2 run solely for this (Tavily daily limit) — piggyback on a normal daily run.

---

## Self-Review

**1. Spec coverage:**
- `_task_category` (spec §A) → Task 1.
- `_build_stage2_category_breakdown` (spec §B) → Task 2.
- `_build_stale_refresh_fields` (spec §C) → Task 3.
- Console format / print (spec §E) → Task 4 (helpers) + Task 5 step 6 (wiring).
- `cli.py` wiring + JSON contract removal/addition (spec §D) → Task 5.
- Reconciliation invariants 1-6 → Task 2 test; invariant 7 → Task 3 test.
- Testing design (spec) → Tasks 1-4 tests.
- Documentation (spec) → Task 6.
- Acceptance criteria → Tasks 5, 7 (+ optional live smoke).
No gaps.

**2. Placeholder scan:** No TBD/TODO/"add error handling"; every code step shows full code.

**3. Type consistency:** Helper names are stable across tasks (`_task_category`, `_build_stage2_category_breakdown`, `_build_stale_refresh_fields`, `_format_stage2_category_line`, `_format_stage2_stale_line`). Breakdown dict shape (`total/effective_success/search_success/structured_success/skipped_existing/manual_required`) is identical in the helper (Task 2), the format helper (Task 4), and the tests. Stale field key names (`task_stale_refresh_forced/success/failed/skipped/pending`) match across Task 3 helper, Task 4 format helper, and Task 5 wiring.
