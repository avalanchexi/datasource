# Stage2 Stage3 Quality Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Stage2 quality-gap aware, merge same-value Stage2.5 compare fields, add a real TuShare ETF window provider, and keep Stage3 strict while allowing it to pass when real data is available.

**Architecture:** Stage2 planning will consume the same quality blockers used by Stage2.5/Stage3 and generate `force_refresh` tasks for missing compare/window fields even when `current_value` already exists. Stage2 will write compare fields returned by structured/search extraction, Stage2.5 will merge missing compare metadata into same-value records, and an ETF structured provider will use TuShare `etf_share_size` windows before search fallback. Stage3 gates remain unchanged.

**Tech Stack:** Python 3, pytest, pandas, TuShare Pro API, existing `run_clean.sh`, existing Stage2 structured provider registry, existing Stage2.5 quality-state calculator.

---

## File Structure

- Modify `src/datasource/engines/stage2_task_planner.py`
  - Add a quality-gap scanner that uses `build_pipeline_quality_state()`.
  - Generate `force_refresh` tasks for `missing_compare_values`, `estimated_not_allowed`, and `fund_flow_window_missing`.
  - Override `required_output_fields` on quality-gap tasks so Stage2 asks for compare/window fields, not only current values.

- Modify `scripts/stage2_unified_enhancer.py`
  - Write macro compare fields and monetary `change_from_120d` from extraction payloads.
  - Preserve existing `force_refresh` behavior for quality-gap tasks.

- Modify `scripts/stage2_5_injector.py`
  - Merge missing compare fields when an incoming manual value equals an existing value.
  - Allow explicit trusted non-estimated `reserve_ratio` manual evidence to replace an existing estimated fallback without `--force-override`.

- Create `src/datasource/providers/stage2_structured/tushare_etf.py`
  - Fetch TuShare `trade_cal` and `etf_share_size`.
  - Compute ETF total-size delta windows using SSE+SZSE data.
  - Return a structured `fund_flow.etf` result with `direct_balance_delta`.

- Modify `src/datasource/providers/stage2_structured/registry.py`
  - Register `tushare_etf` before `eastmoney_etf`.

- Modify `src/datasource/providers/stage2_structured/source_tiers.py`
  - Mark `tushare.pro` as Tier2 structured API evidence.

- Modify `tests/test_stage2_unified.py`
  - Add planner and Stage2 writeback tests.

- Modify `tests/test_websearch_injector.py`
  - Add Stage2.5 same-value merge tests.

- Modify `tests/test_stage2_structured_providers.py`
  - Add TuShare ETF provider and source-tier tests.

- Modify `tests/test_stage2_structured_integration.py`
  - Add quality-gap force-refresh integration coverage.

- Modify `AGENTS.md` and `CLAUDE.md`
  - Document quality-gap-aware Stage2 task planning, Stage2.5 partial merge, and ETF TuShare window evidence.

---

### Task 1: Make Stage2 Task Planning Quality-Gap Aware

**Files:**
- Modify: `src/datasource/engines/stage2_task_planner.py`
- Test: `tests/test_stage2_unified.py`

- [x] **Step 1: Add failing planner tests**

Append these tests near the existing `Stage2TaskPlanner` tests in `tests/test_stage2_unified.py`:

```python
def test_task_planner_adds_force_refresh_task_for_macro_quality_gap(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-22"},
        "macro_indicators": {
            "industrial": {
                "indicator_name": "工业增加值",
                "current_value": 4.1,
                "previous_value": None,
                "change_rate": None,
                "unit": "%",
                "date": "2026-04",
                "report_period": "2026-04",
                "is_estimated": False,
            }
        },
        "monetary_policy": {},
        "fund_flow": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "missing_items": [],
    }

    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)

    industrial_tasks = [task for task in tasks if task["indicator_key"] == "industrial"]
    assert len(industrial_tasks) == 1
    task = industrial_tasks[0]
    assert task["trigger_reason"] == "quality_gap"
    assert task["quality_gap_reason"] == "missing_compare_values"
    assert task["quality_gap_category"] == "macro_indicators"
    assert task["force_refresh"] is True
    assert task["required_output_fields"] == ["current_value", "previous_value", "change_rate"]
    assert task["expected_period"] == "2026-04"


def test_task_planner_adds_force_refresh_task_for_monetary_quality_gap(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-22"},
        "macro_indicators": {},
        "monetary_policy": {
            "reverse_repo": {
                "policy_name": "7天逆回购利率",
                "current_value": 1.4,
                "change_from_120d": None,
                "unit": "%",
                "date": "2026-05-22",
                "is_estimated": False,
            }
        },
        "fund_flow": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "missing_items": [],
    }

    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)

    repo_tasks = [task for task in tasks if task["indicator_key"] == "reverse_repo"]
    assert len(repo_tasks) == 1
    task = repo_tasks[0]
    assert task["trigger_reason"] == "quality_gap"
    assert task["quality_gap_reason"] == "missing_compare_values"
    assert task["force_refresh"] is True
    assert task["required_output_fields"] == ["current_value", "change_from_120d"]


def test_task_planner_adds_force_refresh_task_for_etf_window_gap(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-22"},
        "macro_indicators": {},
        "monetary_policy": {},
        "fund_flow": {
            "etf": {
                "type": "etf",
                "recent_5d": None,
                "total_120d": None,
                "trend": "待获取",
                "source": "待WebSearch补充",
                "is_estimated": False,
            }
        },
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "missing_items": [],
    }

    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)

    etf_tasks = [task for task in tasks if task["indicator_key"] == "etf"]
    assert len(etf_tasks) == 1
    task = etf_tasks[0]
    assert task["trigger_reason"] == "quality_gap"
    assert task["quality_gap_reason"] == "fund_flow_window_missing"
    assert task["force_refresh"] is True
    assert task["required_output_fields"] == ["recent_5d", "total_120d", "trend"]
    assert "recent_5d" in task["field_queries"]
    assert "total_120d" in task["field_queries"]


def test_task_planner_quality_gap_wins_dedup_over_missing_item(tmp_path: Path):
    payload = {
        "metadata": {
            "date": "2026-05-22",
            "missing_items": {"macro_indicators": [{"key": "industrial", "reason": "missing_compare_values"}]},
        },
        "macro_indicators": {
            "industrial": {
                "indicator_name": "工业增加值",
                "current_value": 4.1,
                "previous_value": None,
                "change_rate": None,
                "unit": "%",
                "date": "2026-04",
                "report_period": "2026-04",
                "is_estimated": False,
            }
        },
        "monetary_policy": {},
        "fund_flow": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "missing_items": [{"key": "industrial", "reason": "manual_required"}],
    }

    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)

    industrial_tasks = [task for task in tasks if task["indicator_key"] == "industrial"]
    assert len(industrial_tasks) == 1
    assert industrial_tasks[0]["trigger_reason"] == "quality_gap"
    assert industrial_tasks[0]["force_refresh"] is True
```

- [x] **Step 2: Run planner tests and verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_unified.py::test_task_planner_adds_force_refresh_task_for_macro_quality_gap \
  tests/test_stage2_unified.py::test_task_planner_adds_force_refresh_task_for_monetary_quality_gap \
  tests/test_stage2_unified.py::test_task_planner_adds_force_refresh_task_for_etf_window_gap \
  tests/test_stage2_unified.py::test_task_planner_quality_gap_wins_dedup_over_missing_item
```

Expected: all four tests fail because `trigger_reason` is not `quality_gap` or no task is generated for existing current values.

- [x] **Step 3: Implement quality-gap scanner in Stage2 planner**

In `src/datasource/engines/stage2_task_planner.py`, add these imports:

```python
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state
from datasource.utils.key_aliases import canonical_monetary_key
```

After `DAILY_QUOTE_KEYS`, add:

```python
QUALITY_GAP_OUTPUT_FIELDS = {
    ("macro_indicators", "missing_compare_values"): ["current_value", "previous_value", "change_rate"],
    ("monetary_policy", "missing_compare_values"): ["current_value", "change_from_120d"],
    ("monetary_policy", "estimated_not_allowed"): ["current_value", "change_from_120d"],
    ("fund_flow", "fund_flow_window_missing"): ["recent_5d", "total_120d", "trend"],
}

QUALITY_GAP_REASONS = {
    "missing_compare_values",
    "estimated_not_allowed",
    "fund_flow_window_missing",
}
```

Inside `Stage2TaskPlanner`, add these methods before `_time_context_type()`:

```python
    def _quality_state(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return build_pipeline_quality_state(payload, stage="stage2")
        except Exception as exc:
            logger.warning(f"[Stage2TaskPlanner] quality state scan failed: {exc}")
            return {"quality_blockers": []}

    @staticmethod
    def _quality_gap_output_fields(category: str, reason: str, indicator_key: str) -> List[str]:
        fields = QUALITY_GAP_OUTPUT_FIELDS.get((category, reason))
        if fields:
            return list(fields)
        key = canonical_monetary_key(indicator_key)
        if category == "monetary_policy" or key != indicator_key:
            return ["current_value", "change_from_120d"]
        return []

    @staticmethod
    def _quality_gap_phase(category: str, indicator_key: str) -> str:
        if category in {"macro_indicators", "monetary_policy"}:
            return "essential"
        return "assets"

    @staticmethod
    def _entry_for_quality_gap(payload: Dict[str, Any], category: str, key: str) -> Optional[Dict[str, Any]]:
        if category in {"macro_indicators", "monetary_policy", "fund_flow"}:
            section = payload.get(category)
            if isinstance(section, dict):
                entry = section.get(key)
                if isinstance(entry, dict):
                    return entry
                canonical_key = canonical_monetary_key(key)
                entry = section.get(canonical_key)
                if isinstance(entry, dict):
                    return entry
        for item in payload.get(category, []) or []:
            if not isinstance(item, dict):
                continue
            item_key = item.get("symbol") or item.get("pair") or item.get("key")
            if str(item_key) == str(key):
                return item
        return None

    @staticmethod
    def _expected_period_for_quality_gap(entry: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(entry, dict):
            return None
        for field in ("expected_period", "report_period", "as_of_date", "date"):
            value = entry.get(field)
            if value:
                return str(value)
        return None

    def _scan_quality_gaps(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []
        state = self._quality_state(payload)
        for issue in state.get("quality_blockers") or []:
            if not isinstance(issue, dict):
                continue
            category = str(issue.get("category") or "")
            key = str(issue.get("key") or "")
            reason = str(issue.get("reason") or "")
            if not key or reason not in QUALITY_GAP_REASONS:
                continue
            indicator_key = canonical_monetary_key(key) if category == "monetary_policy" else key
            entry = self._entry_for_quality_gap(payload, category, indicator_key)
            tasks.append(
                self._new_task(
                    indicator_key,
                    self._quality_gap_phase(category, indicator_key),
                    backend=self.fund_flow_backend if category == "fund_flow" else None,
                    trigger_reason="quality_gap",
                    expected_period=self._expected_period_for_quality_gap(entry),
                    force_refresh=True,
                    quality_gap_category=category,
                    quality_gap_reason=reason,
                    quality_gap_details=issue.get("details"),
                    required_output_fields_override=self._quality_gap_output_fields(category, reason, indicator_key),
                )
            )
        return tasks
```

Change `_new_task()` signature to:

```python
    def _new_task(
        self,
        indicator_key: str,
        phase: str,
        source_hint: Optional[str] = None,
        backend: Optional[str] = None,
        trigger_reason: str = "missing",
        expected_period: Optional[str] = None,
        force_refresh: bool = False,
        quality_gap_category: Optional[str] = None,
        quality_gap_reason: Optional[str] = None,
        quality_gap_details: Optional[Any] = None,
        required_output_fields_override: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
```

Inside `_new_task()`, change the `required_output_fields` and `force_refresh` fields:

```python
            "required_output_fields": required_output_fields_override or profile.get("required_output_fields", []),
```

```python
            "force_refresh": bool(force_refresh) or trigger_reason in {"stale_data", "quality_gap"},
            "quality_gap_category": quality_gap_category,
            "quality_gap_reason": quality_gap_reason,
            "quality_gap_details": quality_gap_details,
```

In `build_tasks()`, prepend `_scan_quality_gaps(payload)` and update priority:

```python
        tasks = (
            self._scan_quality_gaps(payload)
            + self._from_missing_items(payload)
            + self._scan_placeholders(payload)
            + self._scan_estimated_fund_flow(payload)
            + self._scan_stale_entries(payload)
        )
        seen: Dict[str, int] = {}
        priority = {"quality_gap": 5, "stale_data": 4, "placeholder": 3, "missing": 2, "estimated_fallback": 1}
```

- [x] **Step 4: Run planner tests and verify pass**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_unified.py::test_task_planner_adds_force_refresh_task_for_macro_quality_gap \
  tests/test_stage2_unified.py::test_task_planner_adds_force_refresh_task_for_monetary_quality_gap \
  tests/test_stage2_unified.py::test_task_planner_adds_force_refresh_task_for_etf_window_gap \
  tests/test_stage2_unified.py::test_task_planner_quality_gap_wins_dedup_over_missing_item
```

Expected: all four tests pass.

- [x] **Step 5: Commit**

```bash
git add src/datasource/engines/stage2_task_planner.py tests/test_stage2_unified.py
git commit -m "fix: plan stage2 tasks from quality gaps"
```

---

### Task 2: Let Stage2 Write Compare Fields From Extraction

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Test: `tests/test_stage2_unified.py`

- [x] **Step 1: Add failing Stage2 writeback tests**

Append these tests near the existing `_apply_extraction` tests in `tests/test_stage2_unified.py`:

```python
def test_apply_extraction_writes_macro_compare_fields_for_quality_gap():
    payload = {
        "metadata": {"date": "2026-05-22"},
        "macro_indicators": {
            "industrial": {
                "indicator_name": "工业增加值",
                "current_value": 4.1,
                "previous_value": None,
                "change_rate": None,
                "unit": "%",
                "date": "2026-04",
                "is_estimated": False,
            }
        },
        "monetary_policy": {},
        "fund_flow": {},
    }
    task = {
        "task_id": "quality-industrial",
        "indicator_key": "industrial",
        "stage_phase": "essential",
        "search_backend": "structured",
        "trigger_reason": "quality_gap",
        "force_refresh": True,
        "expected_period": "2026-04",
    }
    extraction = {
        "value": 4.1,
        "current_value": 4.1,
        "previous_value": 5.7,
        "change_rate": -28.07,
        "value_type": "yoy_month",
        "yoy_month": 4.1,
        "unit": "%",
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963731.html",
        "note": "fixture",
        "report_period": "2026-04",
    }

    target = _apply_extraction(payload, task, extraction, snippets=[])

    assert target == "macro_indicators"
    entry = payload["macro_indicators"]["industrial"]
    assert entry["current_value"] == pytest.approx(4.1)
    assert entry["previous_value"] == pytest.approx(5.7)
    assert entry["change_rate"] == pytest.approx(-28.07)
    assert entry["value_type"] == "yoy_month"
    assert entry["yoy_month"] == pytest.approx(4.1)
    assert entry["report_period"] == "2026-04"


def test_apply_extraction_writes_monetary_change_from_120d_for_quality_gap():
    payload = {
        "metadata": {"date": "2026-05-22"},
        "macro_indicators": {},
        "monetary_policy": {
            "reverse_repo": {
                "policy_name": "7天逆回购利率",
                "current_value": 1.4,
                "change_from_120d": None,
                "unit": "%",
                "date": "2026-05-22",
                "is_estimated": False,
            }
        },
        "fund_flow": {},
    }
    task = {
        "task_id": "quality-reverse-repo",
        "indicator_key": "reverse_repo",
        "stage_phase": "essential",
        "search_backend": "structured",
        "trigger_reason": "quality_gap",
        "force_refresh": True,
    }
    extraction = {
        "value": 1.4,
        "current_value": 1.4,
        "change_from_120d": 0.0,
        "unit": "%",
        "source_url": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/125475/index.html",
        "note": "fixture",
        "as_of_date": "2026-05-22",
    }

    target = _apply_extraction(payload, task, extraction, snippets=[])

    assert target == "monetary_policy"
    entry = payload["monetary_policy"]["reverse_repo"]
    assert entry["current_value"] == pytest.approx(1.4)
    assert entry["change_from_120d"] == pytest.approx(0.0)
    assert entry["as_of_date"] == "2026-05-22"
```

- [x] **Step 2: Run writeback tests and verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_unified.py::test_apply_extraction_writes_macro_compare_fields_for_quality_gap \
  tests/test_stage2_unified.py::test_apply_extraction_writes_monetary_change_from_120d_for_quality_gap
```

Expected: both tests fail because `_apply_extraction()` currently writes current values but not compare fields.

- [x] **Step 3: Implement compare-field writeback**

In `scripts/stage2_unified_enhancer.py`, inside `_apply_extraction()` add this helper near `_write_common_fields()`:

```python
    def _copy_non_null(entry: Dict[str, Any], field: str, source_field: Optional[str] = None) -> None:
        value = extraction.get(source_field or field)
        if value is not None:
            entry[field] = value
```

In the macro branch, after `_write_period_fields(entry)`, add:

```python
        _copy_non_null(entry, "previous_value")
        _copy_non_null(entry, "change_rate")
        _copy_non_null(entry, "value_type")
        _copy_non_null(entry, "yoy_month")
        _copy_non_null(entry, "yoy_ytd")
        if extraction.get("report_period"):
            entry["report_period"] = extraction.get("report_period")
```

In the monetary branch, after `_write_period_fields(entry)`, add:

```python
        change_from_120d = extraction.get("change_from_120d")
        if change_from_120d is None:
            change_from_120d = extraction.get("change_rate")
        if change_from_120d is not None:
            entry["change_from_120d"] = change_from_120d
        _copy_non_null(entry, "rrr_type")
```

- [x] **Step 4: Run writeback tests and verify pass**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_unified.py::test_apply_extraction_writes_macro_compare_fields_for_quality_gap \
  tests/test_stage2_unified.py::test_apply_extraction_writes_monetary_change_from_120d_for_quality_gap
```

Expected: both tests pass.

- [x] **Step 5: Commit**

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "fix: write stage2 compare fields"
```

---

### Task 3: Merge Stage2.5 Quality-Closure Fields

**Files:**
- Modify: `scripts/stage2_5_injector.py`
- Test: `tests/test_websearch_injector.py`

- [x] **Step 1: Add failing Stage2.5 merge tests**

Append these tests after `_has_quality_blocker()` in `tests/test_websearch_injector.py`:

```python
def test_apply_macro_entry_same_value_merges_compare_fields():
    entry = {
        "indicator_name": "工业增加值",
        "current_value": 4.1,
        "previous_value": None,
        "change_rate": None,
        "unit": "%",
        "date": "2026-04",
        "report_period": "2026-04",
        "value_type": None,
        "is_estimated": False,
        "note": "structured_provider:official_china",
    }
    payload = {
        "indicator_name": "工业增加值",
        "current_value": 4.1,
        "previous_value": 5.7,
        "change_rate": -28.07,
        "value_type": "yoy_month",
        "yoy_month": 4.1,
        "unit": "%",
        "date": "2026-04",
        "report_period": "2026-04",
        "source": "国家统计局",
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963731.html",
        "is_estimated": False,
    }

    updated = injector._apply_macro_entry(
        "industrial",
        entry,
        payload,
        "2026-05-22",
        is_manual=True,
        trend_history_base_dir=None,
    )

    assert updated is True
    assert entry["current_value"] == pytest.approx(4.1)
    assert entry["previous_value"] == pytest.approx(5.7)
    assert entry["change_rate"] == pytest.approx(-28.07)
    assert entry["value_type"] == "yoy_month"
    assert entry["yoy_month"] == pytest.approx(4.1)
    assert entry["source_url"] == "https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963731.html"


def test_apply_monetary_entry_same_value_merges_change_and_non_estimated_flag():
    entry = {
        "policy_name": "金融机构加权平均存款准备金率",
        "current_value": 6.3,
        "change_from_120d": None,
        "unit": "%",
        "date": "2026-05-22",
        "is_estimated": True,
        "note": "structured_provider:trading_economics",
    }
    payload = {
        "policy_name": "金融机构加权平均存款准备金率",
        "current_value": 6.3,
        "change_from_120d": 0.0,
        "unit": "%",
        "date": "2026-05-22",
        "source": "中国人民银行",
        "source_url": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125434/125798/index.html",
        "is_estimated": False,
        "rrr_type": "weighted",
    }

    updated = injector._apply_monetary_entry(
        "reserve_ratio",
        entry,
        payload,
        "2026-05-22",
        is_manual=True,
        trend_history_base_dir=None,
    )

    assert updated is True
    assert entry["current_value"] == pytest.approx(6.3)
    assert entry["change_from_120d"] == pytest.approx(0.0)
    assert entry["is_estimated"] is False
    assert entry["rrr_type"] == "weighted"
    assert entry["source_url"] == "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125434/125798/index.html"


def test_apply_monetary_entry_replaces_estimated_reserve_ratio_with_trusted_manual_value():
    entry = {
        "policy_name": "金融机构加权平均存款准备金率",
        "current_value": 7.5,
        "change_from_120d": None,
        "unit": "%",
        "date": "2026-05-22",
        "is_estimated": True,
        "note": "structured_provider:trading_economics",
    }
    payload = {
        "policy_name": "金融机构加权平均存款准备金率",
        "current_value": 6.3,
        "change_from_120d": 0.0,
        "unit": "%",
        "date": "2026-05-22",
        "source": "中国人民银行",
        "source_url": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125434/125798/index.html",
        "is_estimated": False,
        "rrr_type": "weighted",
    }

    updated = injector._apply_monetary_entry(
        "reserve_ratio",
        entry,
        payload,
        "2026-05-22",
        is_manual=True,
        trend_history_base_dir=None,
    )

    assert updated is True
    assert entry["current_value"] == pytest.approx(6.3)
    assert entry["change_from_120d"] == pytest.approx(0.0)
    assert entry["is_estimated"] is False
    assert entry["rrr_type"] == "weighted"
    assert entry["source_url"] == "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125434/125798/index.html"


def test_pipeline_quality_state_clears_after_same_value_stage25_merge():
    market_data = {
        "metadata": {"date": "2026-05-22"},
        "macro_indicators": {
            "industrial": {
                "indicator_name": "工业增加值",
                "current_value": 4.1,
                "previous_value": None,
                "change_rate": None,
                "unit": "%",
                "date": "2026-04",
                "is_estimated": False,
            }
        },
        "monetary_policy": {
            "reserve_ratio": {
                "policy_name": "金融机构加权平均存款准备金率",
                "current_value": 6.3,
                "change_from_120d": None,
                "unit": "%",
                "date": "2026-05-22",
                "is_estimated": True,
            }
        },
        "fund_flow": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "missing_items": [],
    }

    injector._apply_macro_entry(
        "industrial",
        market_data["macro_indicators"]["industrial"],
        {
            "current_value": 4.1,
            "previous_value": 5.7,
            "change_rate": -28.07,
            "value_type": "yoy_month",
            "yoy_month": 4.1,
            "source_url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963731.html",
            "is_estimated": False,
        },
        "2026-05-22",
        is_manual=True,
        trend_history_base_dir=None,
    )
    injector._apply_monetary_entry(
        "reserve_ratio",
        market_data["monetary_policy"]["reserve_ratio"],
        {
            "current_value": 6.3,
            "change_from_120d": 0.0,
            "source_url": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125434/125798/index.html",
            "is_estimated": False,
        },
        "2026-05-22",
        is_manual=True,
        trend_history_base_dir=None,
    )

    state = injector._apply_pipeline_quality_state(market_data)
    blockers = state["quality_blockers"]
    assert {"category": "macro_indicators", "key": "industrial", "reason": "missing_compare_values"} not in blockers
    assert {"category": "monetary_policy", "key": "reserve_ratio", "reason": "missing_compare_values"} not in blockers
    assert {"category": "monetary_policy", "key": "reserve_ratio", "reason": "estimated_not_allowed"} not in blockers
```

- [x] **Step 2: Run merge tests and verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_websearch_injector.py::test_apply_macro_entry_same_value_merges_compare_fields \
  tests/test_websearch_injector.py::test_apply_monetary_entry_same_value_merges_change_and_non_estimated_flag \
  tests/test_websearch_injector.py::test_apply_monetary_entry_replaces_estimated_reserve_ratio_with_trusted_manual_value \
  tests/test_websearch_injector.py::test_pipeline_quality_state_clears_after_same_value_stage25_merge
```

Expected: tests fail because same-value updates do not merge compare fields, and trusted manual reserve-ratio evidence cannot replace an existing estimated fallback without `--force-override`.

- [x] **Step 3: Implement same-value partial merge**

In `scripts/stage2_5_injector.py`, add this helper after `_update_metadata_only()`:

```python
def _merge_same_value_report_fields(
    entry: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    category: str,
    key: str,
    is_manual: bool = False,
) -> bool:
    changed = False

    def set_if_present(field: str, value: Any) -> None:
        nonlocal changed
        if value is None:
            return
        if entry.get(field) != value:
            entry[field] = value
            changed = True

    if category == "macro_indicators":
        for field in ("previous_value", "change_rate", "value_type", "yoy_month", "yoy_ytd", "report_period"):
            if field in payload:
                set_if_present(field, _coerce_float(payload.get(field)) if field in {"previous_value", "change_rate", "yoy_month", "yoy_ytd"} else payload.get(field))
    elif category == "monetary_policy":
        change_value = payload.get("change_from_120d", payload.get("change_rate"))
        if change_value is not None:
            set_if_present("change_from_120d", _coerce_float(change_value))
        incoming_rrr_type = _normalize_rrr_type(payload.get("rrr_type") or payload.get("value_type"))
        if incoming_rrr_type:
            set_if_present("rrr_type", incoming_rrr_type)

    metadata_changed = _update_metadata_only(entry, payload)
    changed = changed or metadata_changed

    if is_manual and category == "monetary_policy":
        before_estimated = entry.get("is_estimated")
        before_note = entry.get("note")
        _apply_manual_official_estimation_rule(category, key, payload, entry)
        changed = changed or before_estimated != entry.get("is_estimated") or before_note != entry.get("note")

    if changed and entry.get("current_value") is not None:
        entry["is_stale"] = False
        entry["stale_reason"] = None
    return changed


TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS = {
    "reserve_ratio": ("pbc.gov.cn",),
}


def _is_trusted_monetary_manual_quality_override(
    indicator_key: str,
    entry: Dict[str, Any],
    payload: Dict[str, Any],
    incoming_current_value: Optional[float],
    *,
    is_manual: bool,
) -> bool:
    key = "reserve_ratio" if indicator_key in {"rrr", "reserve_ratio"} else indicator_key
    if not is_manual or key not in TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS:
        return False
    if incoming_current_value is None:
        return False
    if not bool(entry.get("is_estimated")):
        return False
    if "is_estimated" not in payload or _coerce_bool(payload.get("is_estimated")) is not False:
        return False
    source_url = _extract_source_url(payload)
    if not source_url:
        return False
    domain = _extract_domain(source_url)
    trusted_domains = TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS[key]
    return any(_official_domain_matches(domain, trusted_domain) for trusted_domain in trusted_domains)
```

In `_apply_macro_entry()`, replace the same-value branch:

```python
        if _same_numeric_value(original_current_value, incoming_current_value):
            changed = _merge_same_value_report_fields(
                entry,
                payload,
                category="macro_indicators",
                key=indicator_key,
                is_manual=is_manual,
            )
            if changed:
                if summary is not None:
                    summary.metadata_updated(
                        "macro_indicators",
                        indicator_key,
                        "same_numeric_value_report_fields_merged",
                        original_current_value,
                        incoming_current_value,
                    )
                return True
```

In `_apply_monetary_entry()`, compute the quality override flag immediately before the existing-value guard:

```python
    trusted_quality_override = _is_trusted_monetary_manual_quality_override(
        indicator_key,
        entry,
        payload,
        incoming_current_value,
        is_manual=is_manual,
    )
```

Then replace the existing-value guard:

```python
    if not force_override and not existing_placeholder and not (override_stale and existing_stale):
        if _same_numeric_value(original_current_value, incoming_current_value):
            changed = _merge_same_value_report_fields(
                entry,
                payload,
                category="monetary_policy",
                key=indicator_key,
                is_manual=is_manual,
            )
            if changed:
                if summary is not None:
                    summary.metadata_updated(
                        "monetary_policy",
                        indicator_key,
                        "same_numeric_value_report_fields_merged",
                        original_current_value,
                        incoming_current_value,
                    )
                return True
        if trusted_quality_override:
            if summary is not None:
                summary.metadata_updated(
                    "monetary_policy",
                    indicator_key,
                    "trusted_manual_estimated_fallback_replaced",
                    original_current_value,
                    incoming_current_value,
                )
        else:
            if summary is not None:
                if incoming_current_value is None:
                    summary.skipped_no_parseable_value("monetary_policy", indicator_key)
                else:
                    summary.skipped_existing(
                        "monetary_policy",
                        indicator_key,
                        "existing_value_present",
                        original_current_value,
                        incoming_current_value,
                    )
            return False
```

- [x] **Step 4: Run merge tests and verify pass**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_websearch_injector.py::test_apply_macro_entry_same_value_merges_compare_fields \
  tests/test_websearch_injector.py::test_apply_monetary_entry_same_value_merges_change_and_non_estimated_flag \
  tests/test_websearch_injector.py::test_apply_monetary_entry_replaces_estimated_reserve_ratio_with_trusted_manual_value \
  tests/test_websearch_injector.py::test_pipeline_quality_state_clears_after_same_value_stage25_merge
```

Expected: all four tests pass.

- [x] **Step 5: Commit**

```bash
git add scripts/stage2_5_injector.py tests/test_websearch_injector.py
git commit -m "fix: merge stage25 same-value compare fields"
```

---

### Task 4: Add TuShare ETF Structured Provider

**Files:**
- Create: `src/datasource/providers/stage2_structured/tushare_etf.py`
- Modify: `src/datasource/providers/stage2_structured/registry.py`
- Modify: `src/datasource/providers/stage2_structured/source_tiers.py`
- Test: `tests/test_stage2_structured_providers.py`

- [x] **Step 1: Add failing TuShare ETF provider tests**

Add `import pandas as pd` near the imports in `tests/test_stage2_structured_providers.py`.

Append these tests near the EastMoney ETF tests:

```python
from datasource.providers.stage2_structured.tushare_etf import TuShareETFProvider


def _trade_dates(count, start=date(2026, 1, 1)):
    return [(start + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(count)]


class FakeTuSharePro:
    def __init__(self, dates, missing_exchange=None):
        self.dates = list(dates)
        self.missing_exchange = missing_exchange
        self.calls = []

    def trade_cal(self, **kwargs):
        return pd.DataFrame({"cal_date": self.dates, "is_open": [1] * len(self.dates)})

    def etf_share_size(self, **kwargs):
        self.calls.append(kwargs)
        exchange = kwargs.get("exchange") or kwargs.get("market")
        if exchange == self.missing_exchange:
            return pd.DataFrame()
        idx = self.dates.index(kwargs["trade_date"])
        total_yi = 1000.0 + idx
        total_wan_per_exchange = total_yi * 10000.0 / 2.0
        return pd.DataFrame({"total_size": [total_wan_per_exchange]})


@pytest.mark.asyncio
async def test_tushare_etf_provider_computes_total_size_delta_windows():
    dates = _trade_dates(121)
    pro = FakeTuSharePro(dates)
    provider = TuShareETFProvider(pro_factory=lambda: pro)

    result = await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-22")

    extraction = result.to_extraction()
    assert result.provider == "tushare_etf"
    assert result.source_tier == "tier2"
    assert extraction["category"] == "fund_flow"
    assert extraction["recent_5d"] == pytest.approx(5.0)
    assert extraction["total_120d"] == pytest.approx(120.0)
    assert extraction["metric_basis"] == "etf_total_size_delta"
    assert extraction["window_evidence"] == "direct_balance_delta"
    assert extraction["is_estimated"] is False
    assert extraction["source_url"] == "https://tushare.pro/document/2"
    assert extraction["diagnostics"]["row_count"] == 121
    assert extraction["diagnostics"]["exchange_count"] == 2


@pytest.mark.asyncio
async def test_tushare_etf_provider_fails_closed_when_exchange_missing():
    dates = _trade_dates(121)
    pro = FakeTuSharePro(dates, missing_exchange="SZSE")
    provider = TuShareETFProvider(pro_factory=lambda: pro)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-22")

    assert exc_info.value.reason == "policy_gate_blocked"
    assert exc_info.value.diagnostics["missing_exchange"] == "SZSE"
    assert exc_info.value.diagnostics["window_evidence"] == "direct_balance_delta"


def test_source_tier_classifier_marks_tushare_pro_as_tier2():
    assert classify_structured_source_tier("https://tushare.pro/document/2") == "tier2"
```

- [x] **Step 2: Run provider tests and verify failure**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_computes_total_size_delta_windows \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_fails_closed_when_exchange_missing \
  tests/test_stage2_structured_providers.py::test_source_tier_classifier_marks_tushare_pro_as_tier2
```

Expected: import fails because `tushare_etf.py` does not exist, and source-tier test fails because `tushare.pro` is not Tier2.

- [x] **Step 3: Implement provider**

Create `src/datasource/providers/stage2_structured/tushare_etf.py`:

```python
"""TuShare ETF fund-flow structured provider."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional

import pandas as pd

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.source_tiers import classify_structured_source_tier


SOURCE_URL = "https://tushare.pro/document/2"
EXCHANGES = ("SSE", "SZSE")
WINDOW_DATES = 121


class TuShareETFProvider(Stage2StructuredProvider):
    name = "tushare_etf"
    supported_keys = {"etf"}

    def __init__(self, pro_factory: Optional[Callable[[], Any]] = None) -> None:
        self._pro_factory = pro_factory or _default_pro_factory

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        if key != "etf":
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="unsupported_key",
                message="TuShare ETF provider does not support {0}".format(key),
            )

        pro = self._pro_factory()
        dates = _recent_open_dates(pro, reference_date, WINDOW_DATES)
        if len(dates) < WINDOW_DATES:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="policy_gate_blocked",
                message="TuShare trade calendar did not provide 121 open dates",
                diagnostics={
                    "row_count": len(dates),
                    "required_rows": WINDOW_DATES,
                    "source_url": SOURCE_URL,
                    "window_evidence": "direct_balance_delta",
                },
            )

        totals: List[float] = []
        for trade_date in dates:
            total = _total_size_yi_for_date(pro, trade_date)
            if total is None:
                missing_exchange = getattr(pro, "_last_missing_exchange", None)
                raise StructuredProviderError(
                    provider=self.name,
                    indicator_key=key,
                    reason="policy_gate_blocked",
                    message="TuShare ETF total_size is missing for one exchange/date",
                    diagnostics={
                        "trade_date": trade_date,
                        "missing_exchange": missing_exchange,
                        "source_url": SOURCE_URL,
                        "window_evidence": "direct_balance_delta",
                    },
                )
            totals.append(total)

        recent_5d = round(totals[-1] - totals[-6], 4)
        total_120d = round(totals[-1] - totals[0], 4)
        as_of_date = _format_trade_date(dates[-1])

        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category="fund_flow",
            payload={
                "value": recent_5d,
                "recent_5d": recent_5d,
                "total_120d": total_120d,
                "trend": _trend(recent_5d),
                "unit": "亿元",
                "metric_basis": "etf_total_size_delta",
                "window_evidence": "direct_balance_delta",
                "is_estimated": False,
            },
            source="TuShare etf_share_size",
            source_url=SOURCE_URL,
            source_tier=classify_structured_source_tier(SOURCE_URL),
            as_of_date=as_of_date,
            confidence=0.92,
            diagnostics={
                "source_url": SOURCE_URL,
                "row_count": len(totals),
                "exchange_count": len(EXCHANGES),
                "window_evidence": "direct_balance_delta",
                "metric_basis": "etf_total_size_delta",
            },
        )


def _default_pro_factory():
    import tushare as ts

    token = os.getenv("TUSHARE_TOKEN")
    return ts.pro_api(token) if token else ts.pro_api()


def _recent_open_dates(pro: Any, reference_date: str, count: int) -> List[str]:
    ref_dt = _parse_reference_date(reference_date)
    lookback_days = max(30, count * 3)
    frame = pro.trade_cal(
        exchange="",
        start_date=(ref_dt - timedelta(days=lookback_days)).strftime("%Y%m%d"),
        end_date=ref_dt.strftime("%Y%m%d"),
    )
    if frame is None or getattr(frame, "empty", True):
        return []
    data = frame.copy()
    data.columns = [str(col).lower() for col in data.columns]
    if "cal_date" not in data.columns or "is_open" not in data.columns:
        return []
    open_rows = data[data["is_open"].astype(int) == 1]
    dates = sorted(str(value) for value in open_rows["cal_date"].tolist())
    return dates[-count:]


def _total_size_yi_for_date(pro: Any, trade_date: str) -> Optional[float]:
    total_wan = 0.0
    for exchange in EXCHANGES:
        try:
            frame = pro.etf_share_size(trade_date=trade_date, exchange=exchange)
        except TypeError:
            frame = pro.etf_share_size(trade_date=trade_date, market=exchange)
        if frame is None or getattr(frame, "empty", True):
            setattr(pro, "_last_missing_exchange", exchange)
            return None
        data = frame.copy()
        data.columns = [str(col).lower() for col in data.columns]
        if "total_size" not in data.columns:
            setattr(pro, "_last_missing_exchange", exchange)
            return None
        values = pd.to_numeric(data["total_size"], errors="coerce").dropna()
        values = values[values > 0]
        if values.empty:
            setattr(pro, "_last_missing_exchange", exchange)
            return None
        total_wan += float(values.sum())
    setattr(pro, "_last_missing_exchange", None)
    return total_wan / 10000.0


def _parse_reference_date(reference_date: str) -> datetime:
    text = str(reference_date or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    return datetime.now()


def _format_trade_date(value: str) -> str:
    try:
        return datetime.strptime(str(value), "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return str(value)


def _trend(value: float) -> str:
    if value > 0:
        return "流入"
    if value < 0:
        return "流出"
    return "持平"


def build_provider() -> TuShareETFProvider:
    return TuShareETFProvider()
```

Modify `src/datasource/providers/stage2_structured/registry.py` so `module_names` starts with `tushare_etf` before `eastmoney_etf`:

```python
    module_names = (
        "chinabond",
        "tushare_etf",
        "eastmoney_etf",
        "official_china",
        "trading_economics",
        "stooq",
        "yahoo_finance",
    )
```

Modify `src/datasource/providers/stage2_structured/source_tiers.py` and add `tushare.pro` to `TIER2_DOMAINS`:

```python
    "tushare.pro",
```

- [x] **Step 4: Run provider tests and verify pass**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_computes_total_size_delta_windows \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_fails_closed_when_exchange_missing \
  tests/test_stage2_structured_providers.py::test_source_tier_classifier_marks_tushare_pro_as_tier2
```

Expected: all three tests pass.

- [x] **Step 5: Commit**

```bash
git add \
  src/datasource/providers/stage2_structured/tushare_etf.py \
  src/datasource/providers/stage2_structured/registry.py \
  src/datasource/providers/stage2_structured/source_tiers.py \
  tests/test_stage2_structured_providers.py
git commit -m "feat: add tushare etf structured provider"
```

---

### Task 5: Verify Stage2 Quality-Gap Force Refresh Uses Structured Results

**Files:**
- Modify: `tests/test_stage2_structured_integration.py`

- [ ] **Step 1: Add failing integration test**

Append this registry and test to `tests/test_stage2_structured_integration.py`:

```python
class MacroCompareRegistry:
    def __init__(self):
        self.calls = 0

    def provider_for(self, indicator_key):
        return object() if indicator_key == "industrial" else None

    async def fetch(self, task, market_payload, reference_date):
        self.calls += 1
        return StructuredResult(
            provider="macro-compare-fixture",
            indicator_key=task["indicator_key"],
            category="macro_indicators",
            payload={
                "value": 4.1,
                "current_value": 4.1,
                "previous_value": 5.7,
                "change_rate": -28.07,
                "value_type": "yoy_month",
                "yoy_month": 4.1,
                "unit": "%",
                "is_estimated": False,
            },
            source="国家统计局",
            source_url="https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963731.html",
            source_tier="tier1",
            as_of_date=reference_date,
            confidence=0.95,
            diagnostics={"fixture": True},
        )


@pytest.mark.asyncio
async def test_execute_tasks_quality_gap_force_refresh_does_not_skip_existing_macro_value(tmp_path: Path):
    task = {
        "task_id": "quality-industrial",
        "indicator_key": "industrial",
        "category": "macro_indicators",
        "stage_phase": "essential",
        "search_backend": "tavily",
        "extraction_backend": "structured",
        "query": "国家统计局 工业增加值 2026年4月 同比",
        "unit": "%",
        "preferred_domains": ["stats.gov.cn"],
        "trigger_reason": "quality_gap",
        "quality_gap_reason": "missing_compare_values",
        "required_output_fields": ["current_value", "previous_value", "change_rate"],
        "force_refresh": True,
        "created_at": 1700000000,
    }
    payload = {
        "metadata": {"date": "2026-05-22", "missing_items": {"macro_indicators": [{"key": "industrial"}]}},
        "macro_indicators": {
            "industrial": {
                "indicator_name": "工业增加值",
                "current_value": 1.0,
                "previous_value": None,
                "change_rate": None,
                "unit": "%",
                "is_estimated": False,
                "source": "old",
            }
        },
        "missing_items": ["industrial"],
    }
    registry = MacroCompareRegistry()
    stats = {}

    completed, failures, websearch_results = await _execute_tasks(
        [task],
        payload,
        FailingTavilyClient(),
        None,
        None,
        tmp_path / "task_log.jsonl",
        cache_ttl=None,
        stats=stats,
        disable_extract=True,
        structured_registry=registry,
    )

    assert registry.calls == 1
    assert failures == []
    assert len(completed) == 1
    assert completed[0]["result_type"] == "structured_success"
    assert payload["macro_indicators"]["industrial"]["current_value"] == pytest.approx(4.1)
    assert payload["macro_indicators"]["industrial"]["previous_value"] == pytest.approx(5.7)
    assert payload["macro_indicators"]["industrial"]["change_rate"] == pytest.approx(-28.07)
    assert payload["macro_indicators"]["industrial"]["value_type"] == "yoy_month"
    assert payload["macro_indicators"]["industrial"]["is_estimated"] is False
    assert websearch_results[0]["result_type"] == "structured_success"
    assert stats["structured_provider"]["success"] == 1
```

- [ ] **Step 2: Run integration test and verify pass**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_structured_integration.py::test_execute_tasks_quality_gap_force_refresh_does_not_skip_existing_macro_value
```

Expected: pass after Tasks 1 and 2. Without `force_refresh=True`, this task would be skipped before structured provider lookup because `macro_indicators.industrial.current_value` already exists.

- [ ] **Step 3: Commit**

```bash
git add tests/test_stage2_structured_integration.py
git commit -m "test: cover quality gap structured refresh"
```

---

### Task 6: Update Operator Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `AGENTS.md` Stage2 rules**

In `AGENTS.md`, update the Stage2 section with this text:

```markdown
- Stage2 task planner is quality-gap aware: it reuses the same quality state used by Stage2.5/Stage3 and creates `force_refresh` tasks for `missing_compare_values`, `estimated_not_allowed`, and `fund_flow_window_missing` even when `current_value` already exists. These tasks request report-ready compare/window fields, not only current values.
- Stage2.5 same-value merge can update `previous_value/change_rate/change_from_120d/value_type/rrr_type/is_estimated/source_url` without `--force-override` when the incoming current value equals the existing Stage2 value. This is for closing Stage3 quality blockers; it does not count as Stage2 effective hit-rate success.
- Stage2.5 may replace an existing estimated `reserve_ratio` fallback without `--force-override` only when the manual payload is explicitly `is_estimated=false` and the single explicit HTTPS source URL belongs to `pbc.gov.cn`; text URLs may only provide matching evidence and multiple/conflicting text URLs are rejected. This is an estimated-fallback replacement rule, not a general official override allowlist expansion.
- ETF Stage2 structured source order includes TuShare `etf_share_size` before EastMoney/search. TuShare ETF windows use SSE+SZSE `total_size` deltas with `metric_basis=etf_total_size_delta`, `window_evidence=direct_balance_delta`, and `is_estimated=false` only when the full 121-trading-day window is available for both exchanges.
```

- [ ] **Step 2: Update `CLAUDE.md` quick reminders**

In `CLAUDE.md`, update the Stage2/Stage2.5 reminders with this text:

```markdown
- Stage2 quality-gap tasks: existing current values no longer imply the task can be skipped when Stage2.5/Stage3 still reports compare/window blockers. Check `trigger_reason=quality_gap`, `quality_gap_reason`, `force_refresh=true`, and `required_output_fields`.
- Stage2.5 same-value manual updates merge report-readiness fields. Use this for compare-field closure; do not use it to bypass ETF/fund-flow window evidence.
- Stage2.5 can replace an estimated `reserve_ratio` fallback only with explicit non-estimated manual evidence from a single PBoC HTTPS URL; keep ETF/fund-flow strict.
- ETF fund-flow can pass only through direct window evidence. TuShare `etf_share_size` is accepted as `etf_total_size_delta` scale-window evidence when SSE+SZSE full windows are present; EastMoney remains blocked unless full-market scope is verified.
```

- [ ] **Step 3: Run doc checks**

Run:

```bash
rg -n "quality-gap|same-value|etf_share_size|direct_balance_delta|stage2_effective_hit_rate" AGENTS.md CLAUDE.md
git diff --check -- AGENTS.md CLAUDE.md
```

Expected: `rg` shows the new guidance in both files, and `git diff --check` exits 0.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: document stage2 quality gap closure"
```

---

### Task 7: Focused and Full Verification

**Files:**
- Verify only; no source edits in this task.

- [ ] **Step 1: Run focused Stage2 planner/writeback tests**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_unified.py::test_task_planner_adds_force_refresh_task_for_macro_quality_gap \
  tests/test_stage2_unified.py::test_task_planner_adds_force_refresh_task_for_monetary_quality_gap \
  tests/test_stage2_unified.py::test_task_planner_adds_force_refresh_task_for_etf_window_gap \
  tests/test_stage2_unified.py::test_task_planner_quality_gap_wins_dedup_over_missing_item \
  tests/test_stage2_unified.py::test_apply_extraction_writes_macro_compare_fields_for_quality_gap \
  tests/test_stage2_unified.py::test_apply_extraction_writes_monetary_change_from_120d_for_quality_gap
```

Expected: all selected tests pass.

- [ ] **Step 2: Run focused Stage2.5 tests**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_websearch_injector.py::test_apply_macro_entry_same_value_merges_compare_fields \
  tests/test_websearch_injector.py::test_apply_monetary_entry_same_value_merges_change_and_non_estimated_flag \
  tests/test_websearch_injector.py::test_apply_monetary_entry_replaces_estimated_reserve_ratio_with_trusted_manual_value \
  tests/test_websearch_injector.py::test_pipeline_quality_state_clears_after_same_value_stage25_merge
```

Expected: all selected tests pass.

- [ ] **Step 3: Run focused structured provider tests**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_computes_total_size_delta_windows \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_fails_closed_when_exchange_missing \
  tests/test_stage2_structured_providers.py::test_source_tier_classifier_marks_tushare_pro_as_tier2 \
  tests/test_stage2_structured_integration.py::test_execute_tasks_quality_gap_force_refresh_does_not_skip_existing_macro_value
```

Expected: all selected tests pass.

- [ ] **Step 4: Run broader regression set**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_unified.py \
  tests/test_stage2_structured_providers.py \
  tests/test_stage2_structured_integration.py \
  tests/test_websearch_injector.py \
  tests/test_pipeline_quality_state.py
```

Expected: all selected files pass.

- [ ] **Step 5: Commit verification-only checkpoint if code changed during fixes**

If Task 7 required source or test edits, commit them:

```bash
git add scripts src tests AGENTS.md CLAUDE.md
git commit -m "fix: stabilize stage2 quality closure tests"
```

If no files changed, do not create an empty commit.

---

### Task 8: Rerun 2026-05-23 Pipeline Slice

**Files:**
- Verify generated artifacts under `data/runs/20260523/` and `logs/runs/20260523/`.
- Do not commit generated run artifacts unless explicitly requested.

- [ ] **Step 1: Run Stage2 with Exa fallback enabled**

Run:

```bash
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data /mnt/d/cursor/datasource/data/runs/20260523/market_data.json \
  --output data/runs/20260523/market_data_stage2_quality_closure.json \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend deepseek \
  --deepseek-timeout 30 \
  --llm-hard-timeout 35 \
  --deepseek-max-concurrency 3 \
  --queue-retry-limit 0 \
  --no-cache \
  --enable-exa-fallback \
  --websearch-results data/runs/20260523/websearch_results_auto_quality_closure.json \
  --log-output logs/runs/20260523/stage2_unified_log_quality_closure.json \
  --gap-monitor data/runs/20260523/gap_monitor_quality_closure.json
```

Expected:

- Command may exit non-zero if manual gaps remain.
- `data/runs/20260523/market_data_stage2_quality_closure.json` exists.
- `logs/runs/20260523/stage2_unified_log_quality_closure.json` exists.
- Stage2 summary includes `stage2_effective_hit_rate >= 0.70`.
- Quality-gap tasks appear with `trigger_reason=quality_gap` when compare/window gaps exist.

- [ ] **Step 2: Inspect Stage2 metrics**

Run:

```bash
jq '.summary | {
  stage2_effective_hit_rate,
  stage2_effective_success,
  stage2_effective_denominator,
  task_structured_success,
  task_search_success,
  search_backend_final,
  tavily_to_exa_failover,
  structured_provider_success_by_key,
  structured_provider_error_breakdown
}' logs/runs/20260523/stage2_unified_log_quality_closure.json
```

Expected:

- `stage2_effective_hit_rate` is at least `0.70`.
- If Tavily returns quota/rate/payment errors, `search_backend_final` is `"exa"` and `tavily_to_exa_failover` is `true`.
- `structured_provider_success_by_key` includes stable structured successes.

- [ ] **Step 3: Run Stage2.5 manual injection**

Run:

```bash
bash run_clean.sh python scripts/stage2_5_injector.py \
  data/runs/20260523/market_data_stage2_quality_closure.json \
  /mnt/d/cursor/datasource/data/runs/20260523/websearch_results_manual.json \
  data/runs/20260523/market_data_complete_quality_closure.json \
  --gap-monitor data/runs/20260523/gap_monitor_quality_closure_manual.json
```

Expected:

- Command exits 0.
- Compare blockers for `industrial`, `industrial_sales`, `bdi`, `reverse_repo`, and `reserve_ratio` are cleared when manual compare fields are present.
- Any remaining blocker is real and visible in the printed quality-blocker list.

- [ ] **Step 4: Inspect Stage2.5 quality state**

Run:

```bash
jq '.metadata.quality_blockers' data/runs/20260523/market_data_complete_quality_closure.json
jq '.fund_flow.etf' data/runs/20260523/market_data_complete_quality_closure.json
```

Expected:

- No `missing_compare_values` blockers remain for manual-covered macro/monetary keys.
- `fund_flow.etf` has real `recent_5d` and `total_120d` if TuShare full-window data was available.
- If TuShare full-window data was unavailable, ETF remains blocked with `fund_flow_window_missing`.

- [ ] **Step 5: Run Stage3**

Run:

```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data data/runs/20260523/market_data_complete_quality_closure.json \
  --output data/runs/20260523/pring_result_quality_closure.json \
  --allow-estimated
```

Expected:

- If ETF TuShare full-window data is available, command exits 0 and writes `data/runs/20260523/pring_result_quality_closure.json`.
- If ETF TuShare full-window data is unavailable, command exits 1 and the only blocker is `fund_flow.etf fund_flow_window_missing`. This is an acceptable strict-gate result.

- [ ] **Step 6: Run full test suite**

Run:

```bash
bash run_clean.sh python -m pytest -q
```

Expected: all tests pass, allowing existing skipped tests and warnings.

- [ ] **Step 7: Check working tree**

Run:

```bash
git status --short
git diff --check
```

Expected:

- Source/doc/test changes are intentional.
- Generated `data/runs/20260523/*quality_closure*` and `logs/runs/20260523/*quality_closure*` artifacts are not staged unless the user explicitly asks to keep run outputs in git.
- `git diff --check` exits 0.

---

## Self-Review Notes

Spec coverage:

- Stage2 effective hit rate remains the acceptance metric: Task 8 checks it and Tasks 1/5 keep structured successes in Stage2.
- Stage2.5 quality-state feedback into Stage2 retrieval tasks: Task 1 implements quality-gap task planning and `force_refresh`.
- Stage2 writes compare/window fields: Task 2 implements macro/monetary compare writeback; Task 4/5 cover ETF windows.
- Stage2.5 same-value compare merge: Task 3 implements and tests it.
- Stage2.5 trusted estimated-fallback replacement: Task 3 implements and tests reserve-ratio replacement only with explicit non-estimated single PBoC HTTPS evidence.
- ETF TuShare direct window evidence: Task 4 implements the provider and fails closed on missing exchange/date data.
- EastMoney strict scope is preserved: Task 4 registers TuShare before EastMoney and does not relax EastMoney allowlist.
- Documentation sync: Task 6 updates `AGENTS.md` and `CLAUDE.md`.
- Verification before completion: Tasks 7 and 8 define focused tests, broader regression tests, and rerun commands.

Type consistency:

- Quality-gap task fields are consistently named `trigger_reason`, `quality_gap_category`, `quality_gap_reason`, `quality_gap_details`, and `force_refresh`.
- ETF provider output uses existing fund-flow fields: `recent_5d`, `total_120d`, `metric_basis`, `window_evidence`, `is_estimated`, `source_url`, and `source_tier`.
- Stage2.5 merge uses existing helper names: `_coerce_float`, `_update_metadata_only`, `_apply_manual_official_estimation_rule`, and `_normalize_rrr_type`.
