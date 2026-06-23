# Stage2 Summary Hardening Design

## Goal

Defensively harden the three minor observations raised in the code review of the
Stage2 summary taxonomy unification work (branch `codex/stage2-summary-taxonomy-unification`,
baseline HEAD `5a05536`). All three were proven not to occur for realistic inputs;
this work makes the code robust and self-documenting anyway, with **no behavior change
for any input that the current pipeline produces**.

## Background

Code review of `src/datasource/engines/stage2/diagnostics.py` flagged three minor items:

1. **dr007 in `_MONETARY_KEYS`** — added during implementation; additive and tested.
2. **`_task_identity` collapse** — two forced tasks lacking `task_id` but sharing
   `indicator_key` would collapse into one identity, under-counting `forced`.
3. **stale state machine order dependence** — `_build_stale_refresh_fields` processes
   `failures` before `completed_tasks`, so a contradictory task (present in `failures`
   as `manual_required` AND in `completed_tasks` as `skipped_existing`) resolves to
   `skipped`, depending on iteration order.

Evidence gathered during review:

- `src/datasource/engines/stage2_task_planner.py:587` assigns every task a unique
  `task_id = str(uuid.uuid4())`. `execution.py` reads `task["task_id"]` directly
  (not `.get`), so a missing `task_id` is an invariant violation, not a normal path.
  Therefore observation #2 is unreachable in practice.
- A contradictory "failed AND skipped" task (observation #3) does not occur: a task is
  either completed or failed in a run, and `skipped_existing` is not produced for a task
  that also ends `manual_required`.
- dr007 is a money-market rate; bucketing it as `monetary_policy` is semantically correct.

## Non-Goals

- No behavior change for realistic inputs. Every existing test in
  `tests/test_stage2_unified.py` must remain green with unchanged expectations.
- Do not touch `_build_stage2_category_breakdown`, the `cli.py` wiring, the summary JSON
  keys, exit-code semantics, or any `stage2_effective_*` metric.
- Do not change `_task_category` logic (the dr007 entry stays).

## Design

### #3 — `_build_stale_refresh_fields`: explicit precedence + monotonic upgrade

Replace the order-dependent transitions with an explicit terminal-state precedence and
an upgrade-only rule, so the result is independent of which list is iterated first.

Precedence (rank): `success (3) > failed (2) > skipped (1) > pending (0)`.

Rationale for `failed > skipped`: for a *stale forced-refresh* task, ending as
`skipped_existing` is itself suspect (it should have been refreshed), while
`manual_required` is the actionable signal an operator must see. A `skipped` classification
must not be able to hide a `failed` one. `success` always wins (the refresh ultimately
produced a fresh value); `pending` is the floor.

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
    # task_id is a planner-guaranteed unique uuid (stage2_task_planner.py:587) and is
    # read directly by execution.py; the indicator_key fallback in _task_identity is only
    # a graceful degradation for the (unreachable) no-task_id path and may under-count.
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

This preserves the partition invariant `forced == success + skipped + failed + pending`
(each identity is in exactly one terminal state) and keeps every existing expectation:

- retry (`failed` then `success`) → `success` (rank 3 beats 2). Unchanged.
- normal `skipped_existing` from `pending` → `skipped`. Unchanged.
- the contradictory `failed + skipped` case now deterministically resolves to `failed`
  regardless of list order (previously `skipped` could win).

### #2 — `_task_identity`: document the invariant, no logic change

There is no fallback that is both unique and stable across the `tasks`, `completed_tasks`,
and `failures` lists when `task_id` is absent: `completed_tasks`/`failures` hold freshly
built `task_record` dicts (different objects sharing only the `task_id` uuid), so
object-identity fallbacks cannot merge a task across lists, and switching the fallback to
a "guaranteed unique" value would break the retry de-duplication that the helper exists to
provide. The only meaningful defense is documenting the invariant. The comment added in the
`_build_stale_refresh_fields` body above covers this; keep `_task_identity` itself unchanged:

```python
def _task_identity(task: Dict[str, Any]) -> str:
    # task_id is planner-guaranteed unique; indicator_key is a graceful fallback only.
    return str(task.get("task_id") or task.get("indicator_key") or "")
```

### #1 — dr007: keep, document intent

Keep `dr007` (and the `canonical_monetary_key`-derived `dr007_rate`) in `_MONETARY_KEYS`.
Add a clarifying comment so a future reader does not re-flag it as scope creep:

```python
# Fallback set only; the primary path reads the task's own canonical category.
# dr007 is a money-market rate intentionally bucketed as monetary_policy.
_MONETARY_KEYS = {
    ...
    "dr007",
    ...
}
```

## Testing Design

Add to `tests/test_stage2_unified.py` (pure function, no I/O):

```python
def test_stale_refresh_fields_failed_outranks_skipped_order_independent():
    tasks = [{"task_id": "t1", "indicator_key": "mlf", "force_refresh": True}]
    completed = [
        {"task_id": "t1", "indicator_key": "mlf", "force_refresh": True,
         "result_type": "skipped_existing"},
    ]
    failures = [
        {"task_id": "t1", "indicator_key": "mlf", "force_refresh": True,
         "result_type": "manual_required"},
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

All pre-existing stale/retry tests
(`test_stale_refresh_fields_count_structured_success_and_partition`,
`test_stale_refresh_fields_dedupes_retry_terminal_state_by_task_id`) must pass unchanged.

## Acceptance Criteria

1. `_build_stale_refresh_fields` is order-independent: the new
   `failed_outranks_skipped` test passes, and the existing retry test (`success` wins)
   stays green.
2. The partition invariant `forced == success + skipped + failed + pending` holds.
3. `_task_identity` and `_task_category`/dr007 logic are unchanged except for comments.
4. No change to category breakdown, cli wiring, summary keys, or effective metrics.
5. Verification passes:

```bash
bash run_clean.sh python -m pytest -q tests/test_stage2_unified.py
bash run_clean.sh python -m py_compile src/datasource/engines/stage2/diagnostics.py
bash run_clean.sh flake8 src/datasource/engines/stage2/diagnostics.py
bash run_clean.sh python -m pytest -q
```

## Implementation Risk

Low. The only behavioral change is in the contradiction case (`failed + skipped`), which
does not occur in practice; the change makes its resolution deterministic and documented.
The risk to avoid is altering the precedence so an existing expectation flips — verified
above that retry→`success` and normal→`skipped` are preserved.
