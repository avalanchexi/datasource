# Stage2 Summary Effective Hit Rate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Stage2 JSON and CLI summaries lead with `stage2_effective_hit_rate` while preserving legacy Tavily/Exa search-only fields.

**Architecture:** Keep the existing Stage2 script structure, but extract two small pure helper boundaries inside `scripts/stage2_unified_enhancer.py`: one for Stage2 result-count metric fields and one for CLI summary line formatting. `main()` will use those helpers when building the summary JSON and printing the terminal summary. Documentation will point operators to `stage2_effective_hit_rate` for daily success and `search_success_rate_incremental` only for search-chain diagnosis.

**Tech Stack:** Python 3.10, pytest, existing Stage2 unified enhancer script, Markdown runbooks.

---

## File Structure

- Modify `scripts/stage2_unified_enhancer.py`
  - Owns Stage2 result counting, JSON summary fields, and terminal summary output.
  - Add `_stage2_summary_metric_fields(...)`, `_build_stage2_result_count_fields(...)`, `_format_stage2_task_count_line(...)`, and `_format_stage2_hit_rate_line(...)` near existing summary helpers.
  - Update `main()` summary construction to use the new metric fields and write `stage2_effective_failure` plus `stage2_effective_denominator`.
  - Update terminal output so `Stage2有效命中率` appears before search-only rate.

- Modify `tests/test_stage2_unified.py`
  - Owns focused regression coverage for Stage2 helper behavior.
  - Add tests proving search-only fields remain search-only and structured-provider success counts only in effective fields.
  - Add tests for terminal summary formatting.

- Modify `AGENTS.md`
  - Owns authoritative operational runbook.
  - Clarify that `stage2_effective_hit_rate` is the daily success metric and `search_success_rate_incremental` is search-chain-only.
  - Mention the new denominator fields.

- Modify `CLAUDE.md`
  - Owns Claude Code quick reference.
  - Mirror the Stage2 summary rule from `AGENTS.md` in concise form.

- Modify `README_STAGE2_SNIPPET.md`
  - Owns short Stage2 snippet documentation.
  - Add the same operator guidance in the quick-reference bullets.

---

### Task 1: Add Pure Metric Helper Tests

**Files:**
- Modify: `tests/test_stage2_unified.py`
- Later implementation target: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: Add failing tests for Stage2 result-count metric fields**

In `tests/test_stage2_unified.py`, insert these tests after `test_stage2_summary_includes_tavily_limit_error_diagnostics`:

```python
def test_stage2_effective_hit_rate_uses_success_plus_failure_denominator():
    assert stage2._stage2_effective_hit_rate(12, 5) == pytest.approx(12 / 17)


def test_stage2_result_count_fields_preserve_search_only_and_effective_metrics():
    completed = (
        [{"result_type": "structured_success"} for _ in range(12)]
        + [{"result_type": "skipped_existing"} for _ in range(2)]
    )
    failures = [{"result_type": "manual_required"} for _ in range(5)]

    fields = stage2._build_stage2_result_count_fields(completed, failures)

    assert fields["task_search_success"] == 0
    assert fields["task_structured_success"] == 12
    assert fields["task_search_failed"] == 5
    assert fields["task_skipped_existing"] == 2
    assert fields["stage2_effective_success"] == 12
    assert fields["stage2_effective_failure"] == 5
    assert fields["stage2_effective_denominator"] == 17
    assert fields["stage2_effective_hit_rate"] == pytest.approx(12 / 17)
    assert fields["search_success_rate_incremental"] == 0.0
```

- [ ] **Step 2: Run the new metric tests and verify the expected failure**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_unified.py::test_stage2_effective_hit_rate_uses_success_plus_failure_denominator \
  tests/test_stage2_unified.py::test_stage2_result_count_fields_preserve_search_only_and_effective_metrics
```

Expected:

```text
FAILED tests/test_stage2_unified.py::test_stage2_result_count_fields_preserve_search_only_and_effective_metrics
AttributeError: module 'scripts.stage2_unified_enhancer' has no attribute '_build_stage2_result_count_fields'
```

The first test can pass immediately because `_stage2_effective_hit_rate` already exists. The second test must fail before the helper is added.

- [ ] **Step 3: Implement metric helpers**

In `scripts/stage2_unified_enhancer.py`, directly after `_stage2_effective_hit_rate`, add:

```python
def _stage2_summary_metric_fields(
    *,
    search_success_count: int,
    structured_success_count: int,
    search_failed_count: int,
) -> Dict[str, Any]:
    search_denominator = search_success_count + search_failed_count
    search_success_rate_incremental = (
        search_success_count / search_denominator if search_denominator else 0.0
    )
    stage2_effective_success = search_success_count + structured_success_count
    stage2_effective_failure = search_failed_count
    stage2_effective_denominator = stage2_effective_success + stage2_effective_failure
    return {
        "task_search_success": search_success_count,
        "task_structured_success": structured_success_count,
        "task_search_failed": search_failed_count,
        "stage2_effective_success": stage2_effective_success,
        "stage2_effective_failure": stage2_effective_failure,
        "stage2_effective_denominator": stage2_effective_denominator,
        "stage2_effective_hit_rate": _stage2_effective_hit_rate(
            stage2_effective_success,
            stage2_effective_failure,
        ),
        "search_success_rate_incremental": search_success_rate_incremental,
    }


def _build_stage2_result_count_fields(
    completed_tasks: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> Dict[str, Any]:
    skipped_existing_count = sum(
        1 for task in completed_tasks if task.get("result_type") == "skipped_existing"
    )
    search_success_count = sum(
        1 for task in completed_tasks if task.get("result_type") == "search_success"
    )
    structured_success_count = sum(
        1 for task in completed_tasks if task.get("result_type") == "structured_success"
    )
    search_failed_count = sum(
        1 for task in failures if task.get("result_type") == "manual_required"
    )
    fields = _stage2_summary_metric_fields(
        search_success_count=search_success_count,
        structured_success_count=structured_success_count,
        search_failed_count=search_failed_count,
    )
    fields["task_skipped_existing"] = skipped_existing_count
    return fields
```

- [ ] **Step 4: Run the metric tests and verify they pass**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_unified.py::test_stage2_effective_hit_rate_uses_success_plus_failure_denominator \
  tests/test_stage2_unified.py::test_stage2_result_count_fields_preserve_search_only_and_effective_metrics
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "test: cover stage2 effective summary metrics"
```

Expected:

```text
[feat/stage2-structured-provider-hit-rate <hash>] test: cover stage2 effective summary metrics
```

---

### Task 2: Use Metric Helpers in JSON Summary

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Test: `tests/test_stage2_unified.py`

- [ ] **Step 1: Replace ad hoc count calculation in `main()`**

In `scripts/stage2_unified_enhancer.py`, find this block inside `main()`:

```python
    skipped_existing_count = sum(1 for t in completed_tasks if t.get("result_type") == "skipped_existing")
    search_success_count = sum(1 for t in completed_tasks if t.get("result_type") == "search_success")
    structured_success_count = sum(1 for t in completed_tasks if t.get("result_type") == "structured_success")
    search_failed_count = sum(1 for t in failures if t.get("result_type") == "manual_required")
```

Replace it with:

```python
    result_count_fields = _build_stage2_result_count_fields(completed_tasks, failures)
    skipped_existing_count = result_count_fields["task_skipped_existing"]
    search_success_count = result_count_fields["task_search_success"]
    structured_success_count = result_count_fields["task_structured_success"]
    search_failed_count = result_count_fields["task_search_failed"]
```

- [ ] **Step 2: Remove duplicate rate calculations in `main()`**

In the same function, remove this block:

```python
    incremental_denominator = search_success_count + search_failed_count
    search_success_rate_incremental = (
        search_success_count / incremental_denominator if incremental_denominator else 0.0
    )
    stage2_effective_success_count = search_success_count + structured_success_count
    stage2_effective_hit_rate = _stage2_effective_hit_rate(
        stage2_effective_success_count,
        search_failed_count,
    )
```

Do not remove `search_success_count`, `structured_success_count`, or `search_failed_count`; those local variables are still used for category and stale-refresh diagnostics.

- [ ] **Step 3: Update the summary dictionary to include helper fields**

In the `summary = { ... }` literal, replace these entries:

```python
        "task_skipped_existing": skipped_existing_count,
        "task_search_success": search_success_count,
        "task_structured_success": structured_success_count,
        "task_search_failed": search_failed_count,
        "stage2_effective_success": stage2_effective_success_count,
        "stage2_effective_hit_rate": stage2_effective_hit_rate,
```

With this single expansion:

```python
        **result_count_fields,
```

Also remove this later entry from the same dictionary because it is already included in `result_count_fields`:

```python
        "search_success_rate_incremental": search_success_rate_incremental,
```

After the change, the summary JSON will contain:

```python
"task_skipped_existing"
"task_search_success"
"task_structured_success"
"task_search_failed"
"stage2_effective_success"
"stage2_effective_failure"
"stage2_effective_denominator"
"stage2_effective_hit_rate"
"search_success_rate_incremental"
```

- [ ] **Step 4: Run focused Stage2 summary tests**

Run:

```bash
.venv/bin/pytest -q tests/test_stage2_unified.py
```

Expected:

```text
tests/test_stage2_unified.py ... passed
```

The exact number of tests can differ as the file evolves. There must be zero failures.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "fix: write stage2 effective summary denominator"
```

Expected:

```text
[feat/stage2-structured-provider-hit-rate <hash>] fix: write stage2 effective summary denominator
```

---

### Task 3: Add CLI Summary Formatting Helpers

**Files:**
- Modify: `tests/test_stage2_unified.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: Add failing tests for terminal summary lines**

In `tests/test_stage2_unified.py`, insert these tests after `test_stage2_result_count_fields_preserve_search_only_and_effective_metrics`:

```python
def test_stage2_task_count_line_labels_effective_and_search_success_separately():
    line = stage2._format_stage2_task_count_line(
        {
            "task_total": 18,
            "task_completed": 14,
            "stage2_effective_success": 12,
            "task_structured_success": 12,
            "task_search_success": 0,
            "task_search_failed": 5,
            "task_skipped_existing": 2,
        },
        pending_manual_count=4,
    )

    assert line == (
        "  任务总数: 18, legacy完成: 14, Stage2有效成功: 12, "
        "结构化源成功: 12, 搜索链路成功: 0, 搜索失败: 5, 跳过已有值: 2, 待人工: 4"
    )
    assert "真实搜索成功" not in line


def test_stage2_hit_rate_line_prioritizes_effective_rate_and_labels_search_only_rate():
    line = stage2._format_stage2_hit_rate_line(
        {
            "stage2_effective_success": 12,
            "stage2_effective_denominator": 17,
            "stage2_effective_hit_rate": 12 / 17,
            "task_search_success": 0,
            "task_search_failed": 5,
            "search_success_rate_incremental": 0.0,
        }
    )

    assert line == "  Stage2有效命中率: 70.6% (12/17); 搜索链路命中率: 0.0% (0/5)"
    assert "增量命中率" not in line
```

- [ ] **Step 2: Run the new CLI formatting tests and verify the expected failure**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_unified.py::test_stage2_task_count_line_labels_effective_and_search_success_separately \
  tests/test_stage2_unified.py::test_stage2_hit_rate_line_prioritizes_effective_rate_and_labels_search_only_rate
```

Expected:

```text
FAILED tests/test_stage2_unified.py::test_stage2_task_count_line_labels_effective_and_search_success_separately
AttributeError: module 'scripts.stage2_unified_enhancer' has no attribute '_format_stage2_task_count_line'
FAILED tests/test_stage2_unified.py::test_stage2_hit_rate_line_prioritizes_effective_rate_and_labels_search_only_rate
AttributeError: module 'scripts.stage2_unified_enhancer' has no attribute '_format_stage2_hit_rate_line'
```

- [ ] **Step 3: Implement CLI formatting helpers**

In `scripts/stage2_unified_enhancer.py`, directly after `_build_stage2_result_count_fields`, add:

```python
def _format_stage2_task_count_line(
    summary: Dict[str, Any],
    *,
    pending_manual_count: int,
) -> str:
    return (
        f"  任务总数: {summary['task_total']}, legacy完成: {summary['task_completed']}, "
        f"Stage2有效成功: {summary['stage2_effective_success']}, "
        f"结构化源成功: {summary['task_structured_success']}, "
        f"搜索链路成功: {summary['task_search_success']}, "
        f"搜索失败: {summary['task_search_failed']}, "
        f"跳过已有值: {summary['task_skipped_existing']}, 待人工: {pending_manual_count}"
    )


def _format_stage2_hit_rate_line(summary: Dict[str, Any]) -> str:
    effective_success = summary["stage2_effective_success"]
    effective_denominator = summary["stage2_effective_denominator"]
    search_success = summary["task_search_success"]
    search_denominator = summary["task_search_success"] + summary["task_search_failed"]
    return (
        f"  Stage2有效命中率: {summary['stage2_effective_hit_rate'] * 100:.1f}% "
        f"({effective_success}/{effective_denominator}); "
        f"搜索链路命中率: {summary['search_success_rate_incremental'] * 100:.1f}% "
        f"({search_success}/{search_denominator})"
    )
```

- [ ] **Step 4: Update terminal output in `main()`**

In `scripts/stage2_unified_enhancer.py`, replace this Stage2 Summary task-count print block:

```python
    print(
        f"  任务总数: {summary['task_total']}, legacy完成: {summary['task_completed']}, "
        f"真实搜索成功: {summary['task_search_success']}, 搜索失败: {summary['task_search_failed']}, "
        f"跳过已有值: {summary['task_skipped_existing']}, 待人工: {len(pending_manual)}"
    )
```

With:

```python
    print(_format_stage2_task_count_line(summary, pending_manual_count=len(pending_manual)))
```

Then replace this later print block:

```python
    print(
        f"  增量命中率: {summary['search_success_rate_incremental']*100:.1f}% ; "
        f"stale强制刷新 {summary['task_stale_refresh_forced']} 项 "
        f"(成功 {summary['task_stale_refresh_success']}, 失败 {summary['task_stale_refresh_failed']})"
    )
```

With:

```python
    print(_format_stage2_hit_rate_line(summary))
    print(
        f"  stale强制刷新 {summary['task_stale_refresh_forced']} 项 "
        f"(成功 {summary['task_stale_refresh_success']}, 失败 {summary['task_stale_refresh_failed']})"
    )
```

- [ ] **Step 5: Run the CLI formatting tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_unified.py::test_stage2_task_count_line_labels_effective_and_search_success_separately \
  tests/test_stage2_unified.py::test_stage2_hit_rate_line_prioritizes_effective_rate_and_labels_search_only_rate
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Check that the old standalone CLI label is gone from the script**

Run:

```bash
rg -n "增量命中率|真实搜索成功" scripts/stage2_unified_enhancer.py
```

Expected: no output.

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "fix: clarify stage2 summary hit rate output"
```

Expected:

```text
[feat/stage2-structured-provider-hit-rate <hash>] fix: clarify stage2 summary hit rate output
```

---

### Task 4: Update Operator Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `README_STAGE2_SNIPPET.md`

- [ ] **Step 1: Update `AGENTS.md` Stage2 summary guidance**

In `AGENTS.md`, replace the Stage2 summary paragraph that starts with `Stage2 summary 口径：` with:

```markdown
Stage2 summary 口径：`task_completed/task_total` 仅表示 legacy completion；日常判断 Stage2 是否达标优先看 `stage2_effective_hit_rate`，并用 `stage2_effective_success/stage2_effective_failure/stage2_effective_denominator` 审计分子分母。`stage2_effective_hit_rate` 包含 structured-provider 成功 + 搜索抽取成功，不含 `skipped_existing` 与 Stage2.5 manual 注入。搜索链路增量命中率只看 `task_search_success/task_search_failed/search_success_rate_incremental`；`search_success_rate_incremental=0.0` 只表示 Tavily/Exa 搜索链路未写回，不代表 Stage2 总命中率为 0，需同时看 `task_structured_success`、`structured_provider_success_count`。结构化源排障看 `structured_provider_attempt_count/structured_provider_success_count/structured_provider_fallback_to_search_count/structured_provider_error_breakdown`、`retrieval_diagnostics`、`manual_reason_breakdown`；已有值跳过看 `task_skipped_existing`，quota/rate/payment failover 看 `search_backend_final`、`tavily_to_exa_failover`、`tavily_to_exa_failover_count`、`exa_failover_success`、`exa_failover_empty`、`exa_failover_error`、`exa_unavailable`、`exa_error_breakdown`、`exa_error_samples`，同时保留查看 `tavily_unavailable_reason=quota_or_rate_limit`。若 `retrieval_hit` 高但写回低，优先看 `value_evidence_miss`、`deepseek_json_truncated/deepseek_json_parse_error`、`field_retry_merged_count`、`field_retry_missing_fields`。
```

- [ ] **Step 2: Update `CLAUDE.md` quick-reference guidance**

In `CLAUDE.md`, replace the Stage2 summary bullet that starts with `- Stage2 summary 中` with:

```markdown
- Stage2 summary 中 `task_completed/task_total` 只是 legacy completion；日常判断 Stage2 是否达标优先看 `stage2_effective_hit_rate`，并用 `stage2_effective_success/stage2_effective_failure/stage2_effective_denominator` 审计分子分母。该指标包含 structured-provider 成功 + 搜索抽取成功，不含 `skipped_existing` 与 Stage2.5 manual 注入。搜索链路增量命中率只看 `task_search_success/task_search_failed/search_success_rate_incremental`；`search_success_rate_incremental=0.0` 只表示 Tavily/Exa 搜索链路未写回，不代表 Stage2 总命中率为 0。结构化源看 `task_structured_success`、`structured_provider_attempt_count/structured_provider_success_count/structured_provider_fallback_to_search_count/structured_provider_error_breakdown`。Exa failover 看 `search_backend_final`、`tavily_to_exa_failover_count`、`exa_failover_success/empty/error`、`exa_unavailable`、`exa_error_breakdown`、`exa_error_samples`；其他失败分类结合 `retrieval_diagnostics`、`manual_reason_breakdown`、`field_retry_merged_count/field_retry_missing_fields`。
```

- [ ] **Step 3: Update `README_STAGE2_SNIPPET.md` metric bullets**

In `README_STAGE2_SNIPPET.md`, under `## 观测指标（summary/log）`, replace the three hit-rate bullets with:

```markdown
- Stage2 总命中率：优先看 `stage2_effective_hit_rate`，并用 `stage2_effective_success/stage2_effective_failure/stage2_effective_denominator` 审计分子分母；它包含 structured-provider 成功和搜索抽取成功，不包含 `task_skipped_existing` 或 Stage2.5 manual 注入
- 搜索链路增量命中率：看 `task_search_success`、`task_search_failed`、`search_success_rate_incremental`；该口径只诊断 Tavily/Exa 搜索链路
- 若 `search_success_rate_incremental=0.0` 且 `task_structured_success` 或 `structured_provider_success_count` 大于 0，说明 Stage2 成功主要来自结构化源，不代表 Stage2 总命中率为 0
```

- [ ] **Step 4: Check documentation no longer leads with the old Chinese label**

Run:

```bash
rg -n "增量命中率" AGENTS.md CLAUDE.md README_STAGE2_SNIPPET.md scripts/stage2_unified_enhancer.py
```

Expected: no output.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add AGENTS.md CLAUDE.md README_STAGE2_SNIPPET.md
git commit -m "docs: clarify stage2 effective hit rate metric"
```

Expected:

```text
[feat/stage2-structured-provider-hit-rate <hash>] docs: clarify stage2 effective hit rate metric
```

---

### Task 5: Verification and Artifact Assertion

**Files:**
- Read: `logs/runs/20260523/stage2_unified_log_structured.json`
- Verify: `scripts/stage2_unified_enhancer.py`
- Verify: `src/datasource/providers/stage2_structured/*.py`
- Verify: tests under `tests/`

- [ ] **Step 1: Run focused tests**

Run:

```bash
.venv/bin/pytest -q tests/test_stage2_unified.py tests/test_stage2_structured_providers.py
```

Expected:

```text
passed
```

There must be zero failures.

- [ ] **Step 2: Run syntax check**

Run:

```bash
.venv/bin/python -m py_compile scripts/stage2_unified_enhancer.py src/datasource/providers/stage2_structured/*.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Assert the existing structured Stage2 artifact using the accepted metric contract**

Run:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path

p = Path("logs/runs/20260523/stage2_unified_log_structured.json")
d = json.load(p.open(encoding="utf-8"))

effective_success = d["stage2_effective_success"]
effective_failure = d.get("stage2_effective_failure")
effective_denominator = d.get("stage2_effective_denominator")
if effective_failure is None:
    effective_failure = d["task_search_failed"]
if effective_denominator is None:
    effective_denominator = effective_success + effective_failure

print("stage2_effective_hit_rate=", d["stage2_effective_hit_rate"])
print("stage2_effective_success=", effective_success)
print("stage2_effective_failure=", effective_failure)
print("stage2_effective_denominator=", effective_denominator)
print("task_search_success=", d["task_search_success"])
print("search_success_rate_incremental=", d["search_success_rate_incremental"])
print("task_structured_success=", d["task_structured_success"])

assert d["task_search_success"] == 0
assert d["search_success_rate_incremental"] == 0.0
assert d["task_structured_success"] == 12
assert effective_success == 12
assert effective_failure == 5
assert effective_denominator == 17
assert d["stage2_effective_hit_rate"] >= 0.70
PY
```

Expected:

```text
stage2_effective_hit_rate= 0.7058823529411765
stage2_effective_success= 12
stage2_effective_failure= 5
stage2_effective_denominator= 17
task_search_success= 0
search_success_rate_incremental= 0.0
task_structured_success= 12
```

This is a read-only assertion. It does not rerun Stage2 or consume Tavily.

- [ ] **Step 4: Run full regression**

Run:

```bash
.venv/bin/pytest -q
```

Expected:

```text
passed
```

Warnings are acceptable if they match existing Pydantic/runtime warnings and there are zero failures.

- [ ] **Step 5: Check diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected:

```text
```

`git diff --check` must exit 0. `git status --short` should show only the intended files if commits have not yet been made, or no output if all task commits are complete.

---

## Self-Review Checklist

- Spec coverage:
  - Metric contract is implemented by Task 1 and Task 2.
  - CLI summary presentation is implemented by Task 3.
  - Documentation is implemented by Task 4.
  - Verification and artifact assertion are implemented by Task 5.

- Placeholder scan:
  - This plan contains no deferred placeholder markers, no vague validation instruction, and no deferred implementation instruction.

- Type consistency:
  - Helper names are consistent across tests and implementation steps:
    - `_stage2_summary_metric_fields`
    - `_build_stage2_result_count_fields`
    - `_format_stage2_task_count_line`
    - `_format_stage2_hit_rate_line`
  - Field names are consistent with the spec:
    - `stage2_effective_success`
    - `stage2_effective_failure`
    - `stage2_effective_denominator`
    - `stage2_effective_hit_rate`
    - `search_success_rate_incremental`
