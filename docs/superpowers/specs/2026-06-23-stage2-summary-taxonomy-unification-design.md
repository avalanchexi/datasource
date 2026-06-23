# Stage2 Summary Taxonomy Unification Design

## Goal

Make the Stage2 CLI/JSON **category breakdown** and **stale-refresh accounting** reconcile
with the already-canonical `stage2_effective_*` taxonomy, so a reader can answer
"how many indicators did Stage2 actually succeed on, and where" from a single,
self-consistent source.

This is a pure presentation/statistics-layer fix. It does not change any pipeline
behavior, data values, exit code, or the `stage2_effective_*` / `search_*` metrics
that the 2026-05-24 work already made authoritative.

## Non-Goals (hard boundaries)

- **Do not** change Stage2 exit-code semantics (`return 1 if pending_manual or task_failed`
  at the end of `_run_stage2`). That is tracked separately.
- **Do not** redefine `stage2_effective_success / stage2_effective_failure /
  stage2_effective_denominator / stage2_effective_hit_rate / search_success_rate_incremental /
  task_search_success / task_structured_success`. They are correct; the new breakdown must
  reconcile **to** them, never replace them.
- **Do not** change structured-provider fetch/parse/validation/fallback/registry behavior.
- **Do not** change Tavily-first / Exa failover, DeepSeek extraction, or regex fallback.
- **Do not** change `market_data*.json` values, Stage2.5 injection, fund-flow gate,
  Stage3 gate, or report generation.
- **Do not** rename the existing stale keys `task_stale_refresh_forced /
  task_stale_refresh_success / task_stale_refresh_failed` (consumed by
  `scripts/tools/stage2_compare_runs.py`). Their **values** may be corrected; new keys may be added.

## Current Problem

The 2026-06-23 run produced a Stage2 summary with at least five internally inconsistent
"success" views in one log:

| # | Symptom | Today's numbers |
|---|---------|-----------------|
| 1 | `success_by_category` sum (12) > authoritative `stage2_effective_success` (10) | counts every completed task incl. 2 `skipped_existing` and all `structured_success` |
| 2 | No `monetary_policy` bucket; `reverse_repo` success invisible | monetary keys fold into `macro` |
| 3 | fund_flow shown as "3/3" but Stage2 only wrote `etf` | northbound/southbound are Stage1 data, entered as `skipped_existing` |
| 4 | stale `forced=10` but only `success=1 + failed=4 = 5` accounted | success counter ignores `structured_success`; partition incomplete |
| 5 | Three denominators on screen (20 / 22 / 11) with the category line using the inflated #1 numerator | category line and effective line disagree |

Authoritative reconciliation for the same run:
`task_total=22`, `task_completed=12`, `task_failed=10`, `task_skipped_existing=2`,
`task_search_success=1`, `task_structured_success=9`, `stage2_effective_success=10`,
`stage2_effective_failure=10`, `stage2_effective_denominator=20`, `stage2_effective_hit_rate=0.5`.

### Root cause (exact locations)

- `src/datasource/engines/stage2/cli.py:849-870` — local `_indicator_category` knows only
  `{fund_flow, forex, commodities, bonds, macro}` (no `monetary_policy`) and **ignores the
  task's own `category` field**; `success_by_cat` increments for **every** `completed_tasks`
  entry regardless of `result_type`.
- `src/datasource/engines/stage2/cli.py:872-874` — `stale_refresh_success` counts only
  `result_type == "search_success"` (misses `structured_success`); `forced` uses
  `_is_force_refresh_task` while `success`/`failed` use the bare `t.get("force_refresh")`.
- `src/datasource/engines/stage2/cli.py:947-949, 1003-1008` — JSON keys
  `success_by_category / search_success_by_category / total_by_category` and the printed
  `分类型成功` / `stale强制刷新` lines are derived from the above.

Confirmed facts that drive the design:

- Tasks already carry a canonical `category` (set throughout `execution.py`, e.g. line 354
  `task.get("category") or task.get("stage_phase")`, and read by `_entry_for_task` in
  `common.py:69`). Canonical category names are
  `{forex, commodities, bonds, macro_indicators, monetary_policy, fund_flow}`.
- `result_type` for completed tasks is one of `search_success`, `structured_success`,
  `skipped_existing`; failures carry `manual_required`
  (see `diagnostics._build_stage2_result_count_fields`).
- `write_back_by_category` (from `exec_stats`) is already an honest "actually written" view
  and is **kept unchanged**.

### Consumer / compatibility boundary

- `success_by_category`, `search_success_by_category`, `total_by_category`:
  **no test and no tool consume them** (verified by grep over `tests/` and
  `scripts/tools/stage2_compare_runs.py`). Free to replace.
- `scripts/tools/stage2_compare_runs.py` reads `task_stale_refresh_forced/success/failed`
  via `dict.get(k)` (missing key tolerated). Keep those three names; new keys are non-breaking.

## Design

### A. New pure helper: `_task_category(task)` (in `diagnostics.py`)

```python
_CANONICAL_CATEGORIES = (
    "forex", "commodities", "bonds",
    "macro_indicators", "monetary_policy", "fund_flow",
)
_FUND_FLOW_KEYS = {"northbound", "southbound", "etf", "margin"}
# Fallback only; prefer the monetary key registry in utils/key_aliases if one is exported.
_MONETARY_KEYS = {
    "reserve_ratio", "rrr", "mlf", "mlf_rate",
    "reverse_repo", "reverse_repo_7d", "m0", "m1", "m2", "tsf", "tsf_growth",
}

def _task_category(task: Dict[str, Any]) -> str:
    cat = task.get("quality_gap_category") or task.get("category") or task.get("stage_phase")
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

The `_FOREX_UPSERT_META / _COMMODITY_UPSERT_META / _BOND_UPSERT_META` maps live in
`common.py`; import them into `diagnostics.py` (reuse, do not duplicate the literals).
`canonical_monetary_key` lives in `datasource.utils.key_aliases` (already imported by
`common.py`); import it in `diagnostics.py` directly from `datasource.utils.key_aliases`.

Step 1 (read the task's own category) is what fixes problems #2 and #3: the planner
already tags `reverse_repo` as `monetary_policy` and `northbound/southbound` as `fund_flow`,
so they land in the correct bucket and skipped Stage1 data is never counted as a Stage2
success.

### B. New pure helper: `_build_stage2_category_breakdown(tasks, completed_tasks, failures)` (in `diagnostics.py`)

Returns a dict keyed by canonical category; each value is:

```json
{
  "total": 7,
  "effective_success": 6,
  "search_success": 1,
  "structured_success": 5,
  "skipped_existing": 0,
  "manual_required": 1
}
```

Counting rules (reconcile-by-construction):

- For each task in `tasks`: `breakdown[cat]["total"] += 1`.
- For each task in `completed_tasks`, by `result_type`:
  - `search_success` → `search_success += 1` and `effective_success += 1`
  - `structured_success` → `structured_success += 1` and `effective_success += 1`
  - `skipped_existing` → `skipped_existing += 1` (NOT effective_success)
- For each task in `failures` with `result_type == "manual_required"` → `manual_required += 1`.

Only categories that appear are emitted (no empty buckets). Use `_task_category` for every
task.

### C. New pure helper: `_build_stale_refresh_fields(tasks, completed_tasks, failures)` (in `diagnostics.py`)

Uses `_is_force_refresh_task` (imported from `common.py`) **consistently** for forced,
success, skipped, and failed — fixing the mixed `force_refresh` / `_is_force_refresh_task`
predicate. Returns:

```python
{
  "task_stale_refresh_forced": forced,          # name preserved
  "task_stale_refresh_success": success,        # name preserved; now incl. structured_success
  "task_stale_refresh_failed": failed,          # name preserved
  "task_stale_refresh_skipped": skipped,        # new
  "task_stale_refresh_pending": pending,        # new = forced - success - skipped - failed
}
```

- `success` = forced ∩ completed ∩ `result_type in {"search_success", "structured_success"}`
- `skipped` = forced ∩ completed ∩ `result_type == "skipped_existing"`
- `failed`  = forced ∩ failures (`result_type == "manual_required"`)
- `pending` = `forced - success - skipped - failed` (clamped at 0)

Invariant: `forced == success + skipped + failed + pending`.

### D. `cli.py` wiring

- Delete `_indicator_category` and the `success_by_cat / incremental_success_by_cat /
  total_by_cat` loops (`cli.py:849-870`).
- Compute `category_breakdown = _build_stage2_category_breakdown(tasks, completed_tasks, failures)`
  and `stale_fields = _build_stale_refresh_fields(tasks, completed_tasks, failures)`.
- In the `summary` dict:
  - Remove `success_by_category`, `search_success_by_category`, `total_by_category`.
  - Add `"stage2_category_breakdown": category_breakdown`.
  - Replace the three inline stale assignments with `**stale_fields`.
- Keep `write_back_by_category` exactly as is.
- Add `_build_stage2_category_breakdown`, `_build_stale_refresh_fields`, `_task_category`
  to the existing `from datasource.engines.stage2.diagnostics import (...)`.

### E. Console output (replace `cli.py:1003-1008`)

```text
  分类型(有效成功/总数): monetary_policy 6/7, commodities 2/2, fund_flow 1/3, macro_indicators 1/6, forex 0/2, bonds 0/2
    其中 搜索链路 1, 结构化 9, 跳过已有 2, 待人工 10 (合计有效成功 10)
  注: fund_flow 有效成功仅计 Stage2 写回(如 etf); northbound/southbound 为 Stage1 数据,列在"跳过已有"
  stale强制刷新 10 项 (成功 1, 跳过 0, 待人工 9, 其它 0)
```

Numbers are illustrative; format requirements:

- The category line shows `effective_success/total` per category, sorted by
  `effective_success` desc then category name.
- A `monetary_policy` bucket appears whenever a monetary task ran.
- The roll-up line states search/structured/skipped/manual totals and "合计有效成功 N"
  where `N == stage2_effective_success`.
- The stale line shows the full partition `(成功 S, 跳过 K, 待人工 F, 其它 P)` with
  `forced == S + K + F + P`.

The existing pending-manual `[WARN]` line and all other summary lines stay unchanged.

## Reconciliation Invariants (must hold and be tested)

Let `B = stage2_category_breakdown` and `S = summary`:

1. `sum(c["effective_success"] for c in B.values()) == S["stage2_effective_success"]`
2. `sum(c["search_success"] for c in B.values()) == S["task_search_success"]`
3. `sum(c["structured_success"] for c in B.values()) == S["task_structured_success"]`
4. `sum(c["skipped_existing"] for c in B.values()) == S["task_skipped_existing"]`
5. `sum(c["manual_required"] for c in B.values()) == S["stage2_effective_failure"]`
6. `sum(c["total"] for c in B.values()) == S["task_total"]`
7. `S["task_stale_refresh_forced"] == success + skipped + failed + pending`

## Testing Design

Add focused unit coverage in `tests/test_stage2_unified.py` (pure functions, no I/O):

1. `_task_category`:
   - task with `category="monetary_policy"`, `indicator_key="reverse_repo"` → `monetary_policy`
     (not `macro`/`macro_indicators`).
   - task with no category, `indicator_key="reverse_repo"` → `monetary_policy` (fallback set).
   - `northbound` → `fund_flow`; `DXY` → `forex`; `GC=F` → `commodities`; `CN10Y_CDB` → `bonds`.
   - unknown key, no category → `macro_indicators`.
   - task `category="macro"` normalizes to `macro_indicators`.
2. `_build_stage2_category_breakdown` on a synthetic set that mirrors 2026-06-23
   (incl. `skipped_existing` northbound/southbound and a `structured_success` reverse_repo):
   - all six reconciliation invariants 1-6 hold against the matching
     `_build_stage2_result_count_fields` output.
   - fund_flow `effective_success == 1`, `skipped_existing == 2`.
   - `monetary_policy` bucket present with `effective_success >= 1`.
3. `_build_stale_refresh_fields`:
   - a forced task completed via `structured_success` counts in `success`.
   - invariant 7 holds.
4. CLI format helper (extract the category/stale formatting into a pure
   `_format_stage2_category_line(...)` / `_format_stage2_stale_line(...)` if needed for
   testability): output contains `monetary_policy`, states `合计有效成功 N` equal to
   `stage2_effective_success`, and never counts skipped as success.

Run before completion:

```bash
bash run_clean.sh python -m pytest -q tests/test_stage2_unified.py
bash run_clean.sh python -m py_compile src/datasource/engines/stage2/cli.py src/datasource/engines/stage2/diagnostics.py
bash run_clean.sh python -m pytest -q
```

## Documentation

Update only if wording actually changes:

- `AGENTS.md` and `CLAUDE.md`: in the Stage2 summary description, note that
  `stage2_category_breakdown` (nested per canonical category with
  `effective_success/search_success/structured_success/skipped_existing/manual_required/total`)
  replaces the flat `success_by_category/search_success_by_category/total_by_category`, and that
  `fund_flow.effective_success` counts only Stage2 writebacks (Stage1-provided
  northbound/southbound appear under `skipped_existing`). The authoritative daily success metric
  remains `stage2_effective_hit_rate`.

## Acceptance Criteria

The fix is accepted when all are true:

1. For the 2026-06-23 log shape, `sum(effective_success)` across
   `stage2_category_breakdown == 10`, a non-empty `monetary_policy` bucket is present, and
   `fund_flow.effective_success == 1`.
2. All seven reconciliation invariants hold in tests.
3. The stale line/JSON fully partition forced tasks
   (`forced == success + skipped + failed + pending`), with `structured_success` counted.
4. Console summary leads (unchanged) with `Stage2有效命中率`, and the new category line's
   "合计有效成功" equals `stage2_effective_success`.
5. JSON no longer contains the flat `success_by_category/search_success_by_category/
   total_by_category`; it contains `stage2_category_breakdown` and the five stale keys.
6. `tests/test_stage2_unified.py`, full `pytest -q`, and `py_compile` pass.
7. `scripts/tools/stage2_compare_runs.py` still runs against a new summary log
   (stale key names preserved).

## Implementation Risk

- The main risk is recomputing category counts in a way that no longer reconciles with
  `stage2_effective_*`. Mitigation: derive counts only from `result_type` and the task's
  `category`, and assert the reconciliation invariants in tests rather than hardcoding the
  2026-06-23 numbers.
- Secondary risk is overfitting to today's run. Tests must use synthetic inputs and check
  invariants, not fixed indicator names or fixed totals beyond what reconciliation requires.
