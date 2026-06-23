# Stage2 Summary Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Defensively harden three minor code-review observations in `diagnostics.py` — make stale state classification order-independent and document two invariants — with no behavior change for realistic inputs.

**Architecture:** Rewrite `_build_stale_refresh_fields` to use an explicit terminal-state precedence (`success>failed>skipped>pending`) with monotonic upgrade instead of order-dependent transitions, then add invariant-documenting comments to `_task_identity` and `_MONETARY_KEYS`. Single file plus one new unit test.

**Tech Stack:** Python 3.7+, pytest. Run everything through `bash run_clean.sh` (loads `.venv` + `.env`, sets `PYTHONPATH=./src`, clears proxies).

**Branch:** Apply on `codex/stage2-summary-taxonomy-unification` (worktree at `.worktrees/stage2-summary-taxonomy-unification`), the same branch that holds the Stage2 summary taxonomy work (baseline HEAD `5a05536`).

**Spec:** `docs/superpowers/specs/2026-06-24-stage2-summary-hardening-design.md`

---

## Background the implementer needs

- `src/datasource/engines/stage2/diagnostics.py` currently has `_build_stale_refresh_fields`
  (~lines 121-161). It builds a `states` dict keyed by `_task_identity(task)` and classifies
  each forced/stale task as `pending` / `failed` / `skipped` / `success`. The current code sets
  `failed` in the `failures` loop, then in the `completed_tasks` loop lets `skipped_existing`
  overwrite `failed` (it only guards against overwriting `success`). That makes the
  contradictory "failed AND skipped" case resolve to `skipped` purely because `failures` is
  iterated before `completed_tasks`.
- `_task_identity` (~lines 75-76) is `str(task.get("task_id") or task.get("indicator_key") or "")`.
  `task_id` is a planner-guaranteed unique uuid (`stage2_task_planner.py:587`), so the
  `indicator_key` fallback is unreachable in practice; it stays only as graceful degradation.
- `_MONETARY_KEYS` (~lines 30-43) contains `"dr007"`; dr007 is a money-market rate intentionally
  bucketed as `monetary_policy`.
- Existing stale tests live in `tests/test_stage2_unified.py`:
  `test_stale_refresh_fields_count_structured_success_and_partition` and
  `test_stale_refresh_fields_dedupes_retry_terminal_state_by_task_id`. Both must stay green with
  unchanged expectations. New tests call `stage2_diagnostics._helper(...)` directly (the file
  already imports `from datasource.engines.stage2 import diagnostics as stage2_diagnostics`).

## File Structure

- Modify `src/datasource/engines/stage2/diagnostics.py` — rewrite `_build_stale_refresh_fields`,
  add `_STALE_STATE_RANK` + `_upgrade_stale_state`, add two comments.
- Modify `tests/test_stage2_unified.py` — add one order-independence test.

---

### Task 1: Make stale state classification order-independent

**Files:**
- Modify: `src/datasource/engines/stage2/diagnostics.py` (`_build_stale_refresh_fields` ~121-161)
- Test: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_stage2_unified.py`, immediately after
`test_stale_refresh_fields_dedupes_retry_terminal_state_by_task_id`:

```python
def test_stale_refresh_fields_failed_outranks_skipped_order_independent():
    tasks = [{"task_id": "t1", "indicator_key": "mlf", "force_refresh": True}]
    completed = [
        {
            "task_id": "t1",
            "indicator_key": "mlf",
            "force_refresh": True,
            "result_type": "skipped_existing",
        },
    ]
    failures = [
        {
            "task_id": "t1",
            "indicator_key": "mlf",
            "force_refresh": True,
            "result_type": "manual_required",
        },
    ]
    fields = stage2_diagnostics._build_stale_refresh_fields(tasks, completed, failures)

    assert fields["task_stale_refresh_forced"] == 1
    assert fields["task_stale_refresh_failed"] == 1
    assert fields["task_stale_refresh_skipped"] == 0
    assert fields["task_stale_refresh_success"] == 0
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

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k failed_outranks_skipped -v`
Expected: FAIL — current code returns `task_stale_refresh_skipped == 1` and
`task_stale_refresh_failed == 0` (skipped overwrote failed because `completed_tasks` is
processed after `failures`).

- [ ] **Step 3: Rewrite `_build_stale_refresh_fields`**

In `diagnostics.py`, replace the entire current `_build_stale_refresh_fields` function with
the precedence-based version. Add `_STALE_STATE_RANK` and `_upgrade_stale_state` directly
above it:

```python
_STALE_STATE_RANK = {"pending": 0, "skipped": 1, "failed": 2, "success": 3}


def _upgrade_stale_state(
    states: Dict[str, str], identity: str, new_state: str
) -> None:
    if identity not in states:
        return
    if _STALE_STATE_RANK[new_state] > _STALE_STATE_RANK[states[identity]]:
        states[identity] = new_state


def _build_stale_refresh_fields(
    tasks: List[Dict[str, Any]],
    completed_tasks: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> Dict[str, int]:
    # task_id is a planner-guaranteed unique uuid (stage2_task_planner.py) and is read
    # directly by execution.py; the indicator_key fallback in _task_identity is only a
    # graceful degradation for the (unreachable) no-task_id path and may under-count.
    # Terminal state uses an explicit precedence so the result does not depend on which
    # input list is iterated first: success > failed > skipped > pending.
    states: Dict[str, str] = {}
    for task in tasks:
        identity = _task_identity(task)
        if identity and _is_force_refresh_task(task):
            states.setdefault(identity, "pending")

    for task in failures:
        _upgrade_stale_state(states, _task_identity(task), "failed")

    for task in completed_tasks:
        result_type = task.get("result_type")
        if result_type in {"search_success", "structured_success"}:
            _upgrade_stale_state(states, _task_identity(task), "success")
        elif result_type == "skipped_existing":
            _upgrade_stale_state(states, _task_identity(task), "skipped")

    forced = len(states)
    success = sum(1 for state in states.values() if state == "success")
    skipped = sum(1 for state in states.values() if state == "skipped")
    failed = sum(1 for state in states.values() if state == "failed")
    pending = sum(1 for state in states.values() if state == "pending")
    return {
        "task_stale_refresh_forced": forced,
        "task_stale_refresh_success": success,
        "task_stale_refresh_failed": failed,
        "task_stale_refresh_skipped": skipped,
        "task_stale_refresh_pending": pending,
    }
```

- [ ] **Step 4: Run the new test plus the existing stale tests**

Run: `bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k stale_refresh -v`
Expected: PASS — the new `failed_outranks_skipped` test passes, and the pre-existing
`test_stale_refresh_fields_count_structured_success_and_partition` (forced=4, success=1,
skipped=1, failed=2, pending=0) and `test_stale_refresh_fields_dedupes_retry_terminal_state_by_task_id`
(retry → success=1) both still pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/datasource/engines/stage2/diagnostics.py tests/test_stage2_unified.py
git commit -m "fix: make Stage2 stale-refresh state classification order-independent"
```

---

### Task 2: Document the task_id and dr007 invariants (comments only)

**Files:**
- Modify: `src/datasource/engines/stage2/diagnostics.py` (`_task_identity` ~75-76; `_MONETARY_KEYS` ~30-43)

- [ ] **Step 1: Comment `_task_identity`**

In `diagnostics.py`, change:

```python
def _task_identity(task: Dict[str, Any]) -> str:
    return str(task.get("task_id") or task.get("indicator_key") or "")
```

to:

```python
def _task_identity(task: Dict[str, Any]) -> str:
    # task_id is planner-guaranteed unique; indicator_key is a graceful fallback only.
    return str(task.get("task_id") or task.get("indicator_key") or "")
```

- [ ] **Step 2: Comment the dr007 entry in `_MONETARY_KEYS`**

In `diagnostics.py`, the comment line above `_MONETARY_KEYS` currently reads:

```python
# Fallback set only; the primary path reads the task's own canonical category.
_MONETARY_KEYS = {
```

Change it to:

```python
# Fallback set only; the primary path reads the task's own canonical category.
# dr007 is a money-market rate intentionally bucketed as monetary_policy.
_MONETARY_KEYS = {
```

- [ ] **Step 3: Verify nothing broke**

Run: `bash run_clean.sh python -m py_compile src/datasource/engines/stage2/diagnostics.py`
Then: `bash run_clean.sh flake8 src/datasource/engines/stage2/diagnostics.py`
Then: `bash run_clean.sh python -m pytest -q tests/test_stage2_unified.py -k "task_category or stale_refresh or category_breakdown"`
Expected: py_compile silent (exit 0); flake8 no findings; all selected tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/datasource/engines/stage2/diagnostics.py
git commit -m "docs: document task_id invariant and dr007 monetary bucketing in diagnostics"
```

---

### Task 3: Full regression gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `bash run_clean.sh python -m pytest -q`
Expected: PASS, matching the pre-hardening baseline (1498 passed, 3 skipped, only pre-existing
Pydantic/NumPy deprecation warnings). No new failures.

- [ ] **Step 2: Confirm scope is unchanged where it must be**

Run: `bash run_clean.sh python -m pytest -q tests/test_stage2_unified.py -k "category_breakdown or format_category or format_stale"`
Expected: PASS — confirms the category breakdown and format helpers are untouched by the
hardening.

---

## Self-Review

**1. Spec coverage:**
- #3 order-independent stale precedence (spec §"#3") → Task 1 (rewrite + test).
- #2 `_task_identity` invariant comment (spec §"#2") → Task 2 step 1.
- #1 dr007 comment (spec §"#1") → Task 2 step 2.
- Testing design (new `failed_outranks_skipped` test; existing tests unchanged) → Task 1 steps 1-4.
- Acceptance criteria (order independence, partition invariant, no breakdown/cli/effective change,
  full verification) → Tasks 1-3.
No gaps.

**2. Placeholder scan:** No TBD/TODO/vague steps; every code step shows complete code.

**3. Type consistency:** `_STALE_STATE_RANK` (dict[str,int]), `_upgrade_stale_state(states, identity, new_state)`, and `_build_stale_refresh_fields(tasks, completed_tasks, failures)` are used identically in the implementation and referenced consistently. The five returned keys (`task_stale_refresh_forced/success/failed/skipped/pending`) match the Task 1 test assertions exactly.
