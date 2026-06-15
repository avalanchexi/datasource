# PR-C3 Stage2 Execution Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Stage2 execution lane from `scripts/stage2_unified_enhancer.py` into `src/datasource/engines/stage2/execution.py` with no behavior change.

**Architecture:** Keep the CLI/main orchestration in `scripts/stage2_unified_enhancer.py`, and create one execution module that owns `_execute_tasks`, `_try_structured_provider`, DeepSeek execution controls, and the minimal glue those functions directly need. The main script re-exports moved names and still calls the script-global `_execute_tasks`, preserving existing monkeypatch contracts.

**Tech Stack:** Python 3, pytest, flake8, Stage2 replay golden harness, existing `datasource.engines.stage2` split modules.

---

## File Structure

- Create: `src/datasource/engines/stage2/execution.py`
  - Owns `_execute_tasks`, `_try_structured_provider`, `_DeepSeekCircuitBreaker`, `_is_deepseek_timeout`, `_mark_stale_refresh_failure`, `_is_placeholder_number`, `_has_non_placeholder_value`, `_append_task_log`, `_update_missing_items`.
  - Imports only from existing `datasource.*` modules and existing adapters/providers. It must not import `scripts.stage2_unified_enhancer`.
- Modify: `scripts/stage2_unified_enhancer.py`
  - Remove the moved function/class bodies.
  - Import and re-export C3 moved names from `datasource.engines.stage2.execution`.
  - Keep CLI/main/orchestration, `main()` call shape, `import time`, and the script-global `_execute_tasks` name.
- Modify: `tests/test_stage2_c2_split_characterization.py`
  - Add execution module import-surface and identity assertions.
  - Replace the old "execute lane stays in monolith for C3" guard with "execute lane moved to execution module".
  - Add lightweight phase-marker characterization for `_execute_tasks`.
- Modify: `tests/test_stage2_replay_harness.py`
  - Add `datasource.engines.stage2.execution` to `_freeze_stage2_datetime`.
- Create: `.flake8`
  - Add a narrow per-file-ignore for `src/datasource/engines/stage2/execution.py:E501,E131`, because C3 mechanically moves the existing 3000-line execution body without reformatting it.
  - Do not ignore F401/F821; flake8 must still catch real import and undefined-name issues.
- Modify: `optimization/20260610_refactor_plan/TODOS.md`
  - Mark PR-C3 complete after implementation and verification only.

## Hard Constraints

- No `_execute_tasks` or `_try_structured_provider` signature changes.
- No rewrite of queue, failover, Tavily extract, DeepSeek, regex fallback, field retry, writeback, fund_flow gates, forex gates, or structured provider rollback.
- No internal split of `_execute_tasks` helper closures.
- No golden regeneration. Do not set `STAGE2_REPLAY_UPDATE_GOLDEN`.
- If replay golden mismatches, stop and report. Do not update fixtures.
- If `src/datasource/engines/stage2/execution.py` imports `scripts.stage2_unified_enhancer`, stop and fix the dependency direction.
- Keep `extraction_apply.py`'s existing `# C4-cleanup` fund_flow cross-script import untouched.
- Keep `_safe_number` vs coercion consolidation out of scope.

---

### Task 0: Worktree and Baseline Guard

**Files:**
- Read: `docs/superpowers/specs/2026-06-15-batch-c3-stage2-execution-split-design.md`
- Read: `scripts/stage2_unified_enhancer.py`
- Read: `tests/test_stage2_c2_split_characterization.py`
- Read: `tests/test_stage2_replay_harness.py`

- [ ] **Step 1: Verify branch and base**

Run:

```bash
git branch --show-current
git rev-parse --short HEAD
git merge-base --is-ancestor fcb661f HEAD && echo BASE_OK
```

Expected:

```text
codex/batch-c3-stage2-execution-split
<current C3 branch head>
BASE_OK
```

- [ ] **Step 2: Verify only planned local changes exist**

Run:

```bash
git status --short
```

Expected at the start of implementation:

```text
```

If the plan/spec docs are uncommitted, commit them before code movement. If unrelated files appear, do not stage them.

- [ ] **Step 3: Record the original execution block for mechanical comparison**

Run:

```bash
git show fcb661f:scripts/stage2_unified_enhancer.py > /tmp/c3_original_stage2.py
bash run_clean.sh python - <<'PY'
import ast
from pathlib import Path

moved_names = [
    "_is_placeholder_number",
    "_has_non_placeholder_value",
    "_append_task_log",
    "_try_structured_provider",
    "_update_missing_items",
    "_DeepSeekCircuitBreaker",
    "_is_deepseek_timeout",
    "_mark_stale_refresh_failure",
    "_execute_tasks",
]

text = Path("/tmp/c3_original_stage2.py").read_text(encoding="utf-8")
tree = ast.parse(text)
lines = text.splitlines(keepends=True)
blocks = []
found = []
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in moved_names:
        found.append(node.name)
        blocks.append("".join(lines[node.lineno - 1:node.end_lineno]).rstrip())
if found != moved_names:
    raise SystemExit(f"unexpected moved names/order: {found}")
Path("/tmp/c3_original_moved_defs.py").write_text("\n\n\n".join(blocks) + "\n", encoding="utf-8")
PY
wc -l /tmp/c3_original_moved_defs.py
```

Expected:

```text
2998 /tmp/c3_original_moved_defs.py
```

- [ ] **Step 4: Re-run the focused baseline**

Run:

```bash
bash scripts/env_probe.sh
bash run_clean.sh python -m py_compile scripts/stage2_unified_enhancer.py src/datasource/engines/stage2/*.py
bash run_clean.sh python -m pytest tests/test_stage2_c2_split_characterization.py -q
env -u STAGE2_REPLAY_UPDATE_GOLDEN bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q
```

Expected:

```text
env_probe: OK
py_compile: exit 0
tests/test_stage2_c2_split_characterization.py: pass
tests/test_stage2_replay_harness.py: pass
```

- [ ] **Step 5: Commit nothing**

Task 0 is a guard task. It should leave the worktree unchanged.

---

### Task 1: Add C3 Characterization Tests First

**Files:**
- Modify: `tests/test_stage2_c2_split_characterization.py`
- Modify: `tests/test_stage2_replay_harness.py`

- [ ] **Step 1: Add `inspect` and the execution module import**

In `tests/test_stage2_c2_split_characterization.py`, change the imports near the top to include `inspect`:

```python
import importlib
import inspect
import sys
```

Then add the execution module import after the existing `EXTRACTION_APPLY` import:

```python
EXECUTION = importlib.import_module("datasource.engines.stage2.execution")
```

- [ ] **Step 2: Add the C3 moved-name list**

Add this block after `C2_MOVED_NAMES`:

```python
C3_MOVED_NAMES = [
    "_execute_tasks",
    "_try_structured_provider",
    "_DeepSeekCircuitBreaker",
    "_is_deepseek_timeout",
    "_mark_stale_refresh_failure",
    "_is_placeholder_number",
    "_has_non_placeholder_value",
    "_append_task_log",
    "_update_missing_items",
]


ALL_STAGE2_MOVED_NAMES = C2_MOVED_NAMES + C3_MOVED_NAMES
```

- [ ] **Step 3: Add execution exports to the identity table**

Add this entry to `C2_MODULE_EXPORTS`:

```python
    EXECUTION: C3_MOVED_NAMES,
```

The dictionary name can remain `C2_MODULE_EXPORTS` for this PR to avoid broad test churn; the new entry makes it the cross-batch export table.

- [ ] **Step 4: Expand the monolith import-surface test**

Change:

```python
@pytest.mark.parametrize("name", C2_MOVED_NAMES)
def test_import_surface_monolith(name):
    assert hasattr(ENH, name), f"monolith should still expose {name}"
```

to:

```python
@pytest.mark.parametrize("name", ALL_STAGE2_MOVED_NAMES)
def test_import_surface_monolith(name):
    assert hasattr(ENH, name), f"monolith should still expose {name}"
```

- [ ] **Step 5: Replace the old C3 carry-forward guard**

Replace `test_execute_lane_stays_in_monolith_for_c3` with:

```python
def test_execute_lane_moved_to_execution_module_for_c3():
    assert ENH._execute_tasks is EXECUTION._execute_tasks
    assert ENH._try_structured_provider is EXECUTION._try_structured_provider
    assert ENH._DeepSeekCircuitBreaker is EXECUTION._DeepSeekCircuitBreaker
    assert ENH._execute_tasks.__module__ == "datasource.engines.stage2.execution"
    assert (
        ENH._try_structured_provider.__module__
        == "datasource.engines.stage2.execution"
    )
```

- [ ] **Step 6: Add phase-marker characterization**

Add this test after `test_execute_lane_moved_to_execution_module_for_c3`:

```python
def test_execute_tasks_retains_execution_phase_markers():
    source = inspect.getsource(EXECUTION._execute_tasks)
    phase_markers = {
        "skip_existing_value": [
            "_has_non_placeholder_value",
            "skipped_existing",
        ],
        "structured_success": [
            "_try_structured_provider",
            "structured_records is not None",
        ],
        "structured_fallback_to_search": [
            "_try_structured_provider",
            "_expand_query_candidates",
        ],
        "deepseek_timeout_circuit_breaker": [
            "_is_deepseek_timeout",
            "deepseek_circuit_breaker",
        ],
        "fund_flow_field_retry_manual_gate": [
            "field_retry_count",
            "fund_flow_window_missing",
        ],
        "force_refresh_stale_finalization": [
            "_mark_stale_refresh_failure",
            "stale_refresh_failed",
        ],
    }
    for phase, markers in phase_markers.items():
        for marker in markers:
            assert marker in source, f"{phase} lost marker {marker}"
```

- [ ] **Step 7: Keep the moved-name count explicit**

Replace `test_moved_names_list_is_stable` with:

```python
def test_moved_names_list_is_stable():
    assert len(C2_MOVED_NAMES) == 65
    assert len(C2_MOVED_NAMES) == len(set(C2_MOVED_NAMES))
    assert len(C3_MOVED_NAMES) == 9
    assert len(C3_MOVED_NAMES) == len(set(C3_MOVED_NAMES))
    assert len(ALL_STAGE2_MOVED_NAMES) == 74
    assert len(ALL_STAGE2_MOVED_NAMES) == len(set(ALL_STAGE2_MOVED_NAMES))
```

- [ ] **Step 8: Add execution datetime freeze**

In `tests/test_stage2_replay_harness.py::_freeze_stage2_datetime`, add:

```python
    from datasource.engines.stage2 import execution as stage2_execution
```

Then include `stage2_execution` in the freeze loop:

```python
    for module in (
        stage2,
        stage2_errors,
        stage2_execution,
        stage2_query_planner,
        stage2_snippet_filters,
        policy_rules,
    ):
        monkeypatch.setattr(module, "datetime", FixedDatetime)
```

- [ ] **Step 9: Run the new tests and confirm they fail for the expected reason**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage2_c2_split_characterization.py::test_import_surface_monolith -q
env -u STAGE2_REPLAY_UPDATE_GOLDEN bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py::test_replay_full_main -q
```

Expected failure before Task 2:

```text
ModuleNotFoundError: No module named 'datasource.engines.stage2.execution'
```

If the failure is anything else, stop and fix the characterization patch before moving code.

- [ ] **Step 10: Do not commit yet**

These tests are intentionally red until Task 2 creates `execution.py`.

---

### Task 2: Mechanically Move the Execution Layer

**Files:**
- Create: `src/datasource/engines/stage2/execution.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: Extract the exact current bodies with an AST range mover**

Run this command from the C3 worktree:

```bash
bash run_clean.sh python - <<'PY'
import ast
from pathlib import Path

source_path = Path("scripts/stage2_unified_enhancer.py")
target_path = Path("src/datasource/engines/stage2/execution.py")

moved_names = [
    "_is_placeholder_number",
    "_has_non_placeholder_value",
    "_append_task_log",
    "_try_structured_provider",
    "_update_missing_items",
    "_DeepSeekCircuitBreaker",
    "_is_deepseek_timeout",
    "_mark_stale_refresh_failure",
    "_execute_tasks",
]

header = '''"""Task execution helpers for Stage2."""
from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from datasource.adapters.tavily_client import AsyncTavilyClient

try:  # pragma: no cover - optional dependency
    from datasource.adapters.exa_client import AsyncExaClient
except Exception:  # noqa: W0703
    AsyncExaClient = None  # type: ignore

try:  # pragma: no cover - structured providers are optional
    from datasource.providers.stage2_structured import StructuredProviderError
except Exception:  # noqa: W0703
    StructuredProviderError = None  # type: ignore

from datasource.engines.deepseek_reasoner import DeepSeekExtractionAgent
from datasource.engines.stage2.common import _is_force_refresh_task, _safe_number
from datasource.engines.stage2.diagnostics import (
    _build_manual_required_details,
    _build_retrieval_diagnostics,
    _finalize_task_result_type,
    _finalize_websearch_result_type,
    _mark_post_writeback_manual_required,
    _post_writeback_manual_reason,
)
from datasource.engines.stage2.errors import (
    _build_environment_proxy_error_records,
    _is_environment_proxy_error,
    _is_tavily_quota_error,
    _is_tavily_quota_response,
    _structured_audit_fields_from_task,
    _tavily_error_metadata,
)
from datasource.engines.stage2.evidence import (
    _field_retry_window_evidence,
    _final_snippet_diagnostics,
    _resolve_field_retry_evidence_source,
    _selected_reason_from_diagnostics,
)
from datasource.engines.stage2.extraction_apply import (
    _apply_extraction,
    _augment_extraction_metadata,
    _default_fund_flow_metric_basis,
    _infer_fund_flow_source_tier,
    _infer_fund_flow_window_evidence,
)
from datasource.engines.stage2.query_planner import (
    _build_directed_query,
    _candidate_query_quality,
    _exa_search_type,
    _expand_query_candidates,
    _should_retry_with_directed_query,
    _start_date_from_max_age,
)
from datasource.engines.stage2.regex_extraction import (
    _extract_flow_value,
    _refine_extraction_value,
    _regex_fallback,
)
from datasource.engines.stage2.snippet_filters import (
    _filter_by_domain,
    _filter_by_official_extract_domain,
    _official_extract_domains,
    _prefer_fresh_snippets,
    _prefer_latest_report_snippets,
    _score_stats,
)
from datasource.engines.stage2.structured_runner import (
    _mark_structured_fallback_on_task,
    _record_structured_attempt,
    _record_structured_fallback,
    _record_structured_success,
    _structured_stats,
)
from datasource.engines.stage2.validation import (
    _validate_fund_flow_extraction,
    _validate_general_extraction,
)
from datasource.utils.coercion import is_stage2_number_placeholder
from datasource.utils.key_aliases import canonical_monetary_key
from datasource.utils.missing_items import remove_missing_item
from datasource.utils.note_utils import append_note_text as _append_note
'''

reexport = '''from datasource.engines.stage2.execution import (  # noqa: F401 (C3 re-export)
    _DeepSeekCircuitBreaker,
    _append_task_log,
    _execute_tasks,
    _has_non_placeholder_value,
    _is_deepseek_timeout,
    _is_placeholder_number,
    _mark_stale_refresh_failure,
    _try_structured_provider,
    _update_missing_items,
)
'''

text = source_path.read_text(encoding="utf-8")
tree = ast.parse(text)
lines = text.splitlines(keepends=True)

ranges = []
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in moved_names:
        ranges.append((node.lineno - 1, node.end_lineno, node.name))

found = [name for _, _, name in sorted(ranges)]
if found != moved_names:
    raise SystemExit(f"unexpected moved names/order: {found}")

blocks = ["".join(lines[start:end]).rstrip() for start, end, _ in ranges]
new_lines = list(lines)
for start, end, _ in sorted(ranges, reverse=True):
    del new_lines[start:end]

new_text = "".join(new_lines)
marker = "try:  # pragma: no cover - 可选依赖\\n    import httpx\\n"
if reexport not in new_text:
    if marker not in new_text:
        raise SystemExit("could not find insertion marker for C3 re-export")
    new_text = new_text.replace(marker, reexport + "\\n" + marker, 1)

target_path.write_text(header.rstrip() + "\\n\\n\\n" + "\\n\\n\\n".join(blocks) + "\\n", encoding="utf-8")
source_path.write_text(new_text, encoding="utf-8")
PY
```

Expected:

```text
exit 0
```

- [ ] **Step 2: Verify the moved block is byte-identical apart from the module header**

Run:

```bash
bash run_clean.sh python - <<'PY'
import ast
from pathlib import Path

moved_names = [
    "_is_placeholder_number",
    "_has_non_placeholder_value",
    "_append_task_log",
    "_try_structured_provider",
    "_update_missing_items",
    "_DeepSeekCircuitBreaker",
    "_is_deepseek_timeout",
    "_mark_stale_refresh_failure",
    "_execute_tasks",
]

text = Path("src/datasource/engines/stage2/execution.py").read_text(encoding="utf-8")
tree = ast.parse(text)
lines = text.splitlines(keepends=True)
blocks = []
found = []
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in moved_names:
        found.append(node.name)
        blocks.append("".join(lines[node.lineno - 1:node.end_lineno]).rstrip())
if found != moved_names:
    raise SystemExit(f"unexpected moved names/order: {found}")
Path("/tmp/c3_current_moved_defs.py").write_text("\n\n\n".join(blocks) + "\n", encoding="utf-8")
PY
diff -u /tmp/c3_original_moved_defs.py /tmp/c3_current_moved_defs.py
```

Expected:

```text
```

The diff must be empty. If it is not empty, stop and inspect before continuing.

- [ ] **Step 3: Verify the main script no longer owns C3 bodies**

Run:

```bash
rg -n "^(class _DeepSeekCircuitBreaker|def _execute_tasks|async def _execute_tasks|def _try_structured_provider|async def _try_structured_provider|def _is_deepseek_timeout|def _mark_stale_refresh_failure|def _is_placeholder_number|def _has_non_placeholder_value|def _append_task_log|def _update_missing_items)" scripts/stage2_unified_enhancer.py
```

Expected:

```text
```

- [ ] **Step 4: Verify the execution module owns C3 bodies**

Run:

```bash
rg -n "^(class _DeepSeekCircuitBreaker|def _execute_tasks|async def _execute_tasks|def _try_structured_provider|async def _try_structured_provider|def _is_deepseek_timeout|def _mark_stale_refresh_failure|def _is_placeholder_number|def _has_non_placeholder_value|def _append_task_log|def _update_missing_items)" src/datasource/engines/stage2/execution.py
```

Expected key lines:

```text
...:def _is_placeholder_number(val: Any) -> bool:
...:def _has_non_placeholder_value(market_payload: Dict[str, Any], indicator_key: str) -> (bool, Optional[float]):
...:def _append_task_log(task_log_path: Path, record: Dict[str, Any]) -> None:
...:async def _try_structured_provider(
...:def _update_missing_items(market_payload: Dict[str, Any], indicator_key: str) -> None:
...:class _DeepSeekCircuitBreaker:
...:def _is_deepseek_timeout(exc: Exception) -> bool:
...:def _mark_stale_refresh_failure(extraction: Dict[str, Any], task: Dict[str, Any]) -> None:
...:async def _execute_tasks(
```

- [ ] **Step 5: Keep `main()` monkeypatch contract unchanged**

Run:

```bash
rg -n "_execute_tasks\\(" scripts/stage2_unified_enhancer.py
```

Expected: `main()` still calls `_execute_tasks(` directly through the script global imported from `execution.py`; it must not call `stage2_execution._execute_tasks(`.

- [ ] **Step 6: Do not commit until Task 3 passes compile/import checks**

Task 2 leaves the worktree modified.

---

### Task 3: Import Convergence and Dependency Direction Checks

**Files:**
- Modify as needed: `src/datasource/engines/stage2/execution.py`
- Modify as needed: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: Run compile checks**

Run:

```bash
bash run_clean.sh python -m py_compile scripts/stage2_unified_enhancer.py src/datasource/engines/stage2/*.py
```

Expected:

```text
exit 0
```

If a name is missing in `execution.py`, add the import from an existing `datasource.engines.stage2.*` module or `datasource.utils.*`. Do not import `scripts.stage2_unified_enhancer`.

- [ ] **Step 2: Run flake8 for the split modules**

Run:

```bash
bash run_clean.sh python -m flake8 src/datasource/engines/stage2/
```

Expected:

```text
exit 0
```

If flake8 reports unused imports in `execution.py`, remove only the unused import lines. Do not alter function bodies to satisfy flake8.

If flake8 reports only E501/E131 from the mechanically moved `_execute_tasks` body, add this repo-level config rather than reformatting the moved body:

```ini
[flake8]
per-file-ignores =
    src/datasource/engines/stage2/execution.py:E501,E131
```

This per-file ignore must not include F401 or F821.

- [ ] **Step 3: Verify import direction**

Run:

```bash
rg -n "stage2_unified_enhancer" src/datasource/engines/stage2/execution.py
```

Expected:

```text
```

- [ ] **Step 4: Verify import-time smoke**

Run:

```bash
bash run_clean.sh python - <<'PY'
import importlib

enh = importlib.import_module("scripts.stage2_unified_enhancer")
execution = importlib.import_module("datasource.engines.stage2.execution")
names = [
    "_execute_tasks",
    "_try_structured_provider",
    "_DeepSeekCircuitBreaker",
    "_is_deepseek_timeout",
    "_mark_stale_refresh_failure",
    "_is_placeholder_number",
    "_has_non_placeholder_value",
    "_append_task_log",
    "_update_missing_items",
]
for name in names:
    assert getattr(enh, name) is getattr(execution, name), name
print("C3_IMPORT_IDENTITY_OK")
PY
```

Expected:

```text
C3_IMPORT_IDENTITY_OK
```

- [ ] **Step 5: Commit the mechanical move and tests**

Run:

```bash
git add scripts/stage2_unified_enhancer.py src/datasource/engines/stage2/execution.py tests/test_stage2_c2_split_characterization.py tests/test_stage2_replay_harness.py
git diff --cached --stat
git commit -m "refactor: move stage2 execution lane"
```

Expected: commit succeeds with only the four listed files staged.

---

### Task 4: C3 Characterization and Replay Verification

**Files:**
- Read: `tests/test_stage2_c2_split_characterization.py`
- Read: `tests/test_stage2_replay_harness.py`
- Read: `tests/fixtures/stage2_replay/`

- [ ] **Step 1: Run split characterization**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage2_c2_split_characterization.py -q
```

Expected:

```text
pass
```

- [ ] **Step 2: Run replay with golden update disabled**

Run:

```bash
env -u STAGE2_REPLAY_UPDATE_GOLDEN bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q
```

Expected:

```text
pass
```

If this command reports a golden mismatch, stop immediately and report the mismatch. Do not set `STAGE2_REPLAY_UPDATE_GOLDEN`.

- [ ] **Step 3: Verify no replay fixtures changed**

Run:

```bash
git status --short -- tests/fixtures/stage2_replay data/runs data/trend_history
```

Expected:

```text
```

- [ ] **Step 4: Commit only if Task 4 required a fix**

If Task 4 required no code changes, do not create a commit. If it required a scoped fix, run:

```bash
git add scripts/stage2_unified_enhancer.py src/datasource/engines/stage2/execution.py tests/test_stage2_c2_split_characterization.py tests/test_stage2_replay_harness.py
git commit -m "test: lock stage2 execution replay split"
```

Expected: commit succeeds only when there were Task 4 fixes.

---

### Task 5: Focused Execution-Lane Regression Suite

**Files:**
- Read: `tests/test_stage2_structured_integration.py`
- Read: `tests/test_stage2_structured_golden.py`
- Read: `tests/test_stage2_fallbacks.py`
- Read: `tests/test_stage2_unified.py`
- Read: `tests/test_stage2_unified_pipeline.py`
- Read: `tests/test_deepseek_defaults.py`

- [ ] **Step 1: Run structured provider coverage**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage2_structured_integration.py tests/test_stage2_structured_golden.py -q
```

Expected:

```text
pass
```

- [ ] **Step 2: Run fallback coverage**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage2_fallbacks.py -q
```

Expected:

```text
pass
```

- [ ] **Step 3: Run targeted unified execution tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k "execute_tasks or deepseek_circuit_breaker or gap_monitor_pending_only_incomplete" -q
```

Expected:

```text
pass
```

- [ ] **Step 4: Run pipeline/defaults tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage2_unified_pipeline.py tests/test_deepseek_defaults.py -q
```

Expected:

```text
pass
```

- [ ] **Step 5: Commit only if Task 5 required a fix**

If Task 5 required no code changes, do not create a commit. If it required a scoped fix, run:

```bash
git add scripts/stage2_unified_enhancer.py src/datasource/engines/stage2/execution.py tests/
git commit -m "fix: preserve stage2 execution lane behavior"
```

Expected: commit succeeds only when there were Task 5 fixes.

---

### Task 6: Full Verification

**Files:**
- Read: entire repo test surface

- [ ] **Step 1: Run full pytest**

Run:

```bash
bash run_clean.sh python -m pytest -q
```

Expected baseline-or-better:

```text
1169 passed, 3 skipped
```

Warnings count may differ only if pytest reports the same warning categories from baseline. Any failure or lower pass count stops the task.

- [ ] **Step 2: Run final compile and flake8**

Run:

```bash
bash run_clean.sh python -m py_compile scripts/stage2_unified_enhancer.py src/datasource/engines/stage2/*.py
bash run_clean.sh python -m flake8 src/datasource/engines/stage2/
```

Expected:

```text
both commands exit 0
```

- [ ] **Step 3: Verify no unintended generated data changed**

Run:

```bash
git status --short -- data/runs data/trend_history tests/fixtures/stage2_replay reports logs
```

Expected:

```text
```

- [ ] **Step 4: Verify code diff scope**

Run:

```bash
git diff --name-only fcb661f...HEAD
git diff --name-only
```

Expected committed diff files:

```text
docs/superpowers/specs/2026-06-15-batch-c3-stage2-execution-split-design.md
docs/superpowers/plans/2026-06-15-batch-c3-stage2-execution-split.md
.flake8
scripts/stage2_unified_enhancer.py
src/datasource/engines/stage2/execution.py
tests/test_stage2_c2_split_characterization.py
tests/test_stage2_replay_harness.py
```

Expected uncommitted diff files before Task 7:

```text
```

---

### Task 7: Documentation Closeout

**Files:**
- Modify: `optimization/20260610_refactor_plan/TODOS.md`

- [ ] **Step 1: Update the Batch C summary line**

In `optimization/20260610_refactor_plan/TODOS.md`, change:

```markdown
| 批次 C | 巨石拆分(含 C-0.5/C0) | 5–7 | 🚧 进行中(C-0.5/C0/C1/C2 完成;下一步 C3) | B |
```

to:

```markdown
| 批次 C | 巨石拆分(含 C-0.5/C0) | 5–7 | 🚧 进行中(C-0.5/C0/C1/C2/C3 完成;下一步 C4) | B |
```

- [ ] **Step 2: Update current focus**

Change:

```markdown
**当前焦点:PR-C3(`_execute_tasks` 执行车道拆分)——从 C2 合入后的 HEAD 现生成 brainstorm/spec/plan。**
```

to:

```markdown
**当前焦点:PR-C4(Stage2.5 schema/manual/fund_flow/gap_sync 拆分)——从 C3 合入后的 HEAD 现生成 brainstorm/spec/plan。**
```

- [ ] **Step 3: Mark PR-C3 complete and preserve carry-forward**

Replace the PR-C3 block with:

```markdown
- [x] **PR-C3**:`_execute_tasks` 执行车道拆分
  - [x] 新增 `src/datasource/engines/stage2/execution.py`;`_execute_tasks`/`_try_structured_provider`/DeepSeek 执行件/执行 glue 已机械搬移,主脚本保留 re-export 与 monkeypatch 合同
  - [x] 阶段级 characterization、replay datetime tie-in、replay byte-stable 与全量 pytest 通过
  - [ ] C3 carry-forward: `_execute_tasks` 内部闭包 helper 暂不继续拆;终态 main 入口 <=30 行仍留 C 批次收尾
```

Keep the PR-C4 and later blocks unchanged.

- [ ] **Step 4: Run documentation diff check**

Run:

```bash
git diff -- optimization/20260610_refactor_plan/TODOS.md
```

Expected: only the C summary/current focus/PR-C3 block changes above.

- [ ] **Step 5: Commit documentation**

Run:

```bash
git add optimization/20260610_refactor_plan/TODOS.md
git commit -m "docs: mark C3 execution split complete"
```

Expected:

```text
commit succeeds
```

---

### Task 8: Final Review, Merge, Push, and Worktree Cleanup

**Files:**
- Read: all changed files

- [ ] **Step 1: Run final status and log**

Run:

```bash
git status --short
git log --oneline --decorate --max-count=8
```

Expected:

```text
git status: clean
HEAD includes docs spec, refactor execution split, docs closeout commits
```

- [ ] **Step 2: Run final code review command set**

Run:

```bash
git diff --stat fcb661f...HEAD
git diff --check fcb661f...HEAD
rg -n "stage2_unified_enhancer" src/datasource/engines/stage2/execution.py
```

Expected:

```text
diff --check: exit 0
rg: no matches
```

- [ ] **Step 3: Merge into main**

Run from the main checkout:

```bash
cd /mnt/d/cursor/datasource
git status --short
git fetch origin
git switch main
git merge --ff-only codex/batch-c3-stage2-execution-split
```

Expected:

```text
main fast-forwards to the C3 branch head
```

If `git status --short` in the main checkout shows the pre-existing untracked superpowers docs or `.gstack/`, leave them unstaged. If tracked files other than `.claude/settings.local.json` are modified, stop and report.

- [ ] **Step 4: Re-run merge checkout smoke**

Run from `/mnt/d/cursor/datasource`:

```bash
bash run_clean.sh python -m py_compile scripts/stage2_unified_enhancer.py src/datasource/engines/stage2/*.py
env -u STAGE2_REPLAY_UPDATE_GOLDEN bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q
bash run_clean.sh python -m pytest tests/test_stage2_c2_split_characterization.py -q
```

Expected:

```text
all pass
```

- [ ] **Step 5: Push**

Run:

```bash
git push origin main
```

Expected:

```text
origin/main updated to the C3 merge commit/fast-forward head
```

- [ ] **Step 6: Remove the C3 worktree and branch**

Run:

```bash
git worktree remove /mnt/d/cursor/datasource/.worktrees/codex-batch-c3-stage2-execution-split
git branch -d codex/batch-c3-stage2-execution-split
```

Expected:

```text
worktree removed
branch deleted
```

- [ ] **Step 7: Final report**

Report:

```text
C3 merged and pushed.
Verification:
- replay harness: pass
- C2/C3 split characterization: pass
- full pytest in worktree: 1169 passed, 3 skipped
- py_compile/flake8: pass
Main pushed: <final sha>
```
