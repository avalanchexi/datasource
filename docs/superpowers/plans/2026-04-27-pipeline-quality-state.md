# Pipeline Quality State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one authoritative quality-state calculation path for Stage2.5, Stage3, and Stage4, while correcting source tracing and window metric semantics.

**Architecture:** Create `datasource.utils.pipeline_quality_state` as a pure, read-only state calculator. Stage2.5 writes the calculated state back to run artifacts; Stage3 and Stage4 recalculate from the current input and block on that result instead of trusting stale JSON fields. Window metric fixes stay close to the existing Stage1/Stage2.5 calculation points and report rendering.

**Tech Stack:** Python, pytest, existing `scripts/stage2_5_injector.py`, `scripts/stage3_pring_analyzer.py`, `scripts/stage4_report_generator.py`, `src/datasource/utils`, `src/datasource/generators/simple_report.py`.

---

## File Structure

- Create: `src/datasource/utils/pipeline_quality_state.py`
  - Owns `build_pipeline_quality_state(...)`, source URL checks, window semantic checks, missing/manual/blocker normalization, and policy-compatible state output.
- Create: `tests/test_pipeline_quality_state.py`
  - Unit tests for stale state cleanup, missing compare values, source URL issues, estimated-policy blocking, and window metric issues.
- Modify: `scripts/stage2_5_injector.py`
  - Replace ad hoc final quality state writing with `build_pipeline_quality_state(...)`.
  - Preserve `source_url` and `metric_basis` when merging manual/WebSearch data.
  - Stop writing `change_5d` into commodity `daily_change` and `change_120d` into commodity `ytd_change`.
  - Stop converting unknown forex changes to `0.0`.
- Modify: `scripts/stage3_pring_analyzer.py`
  - Use `build_pipeline_quality_state(...)` for the Stage3 gate.
  - Keep existing CLI and error aggregation shape.
- Modify: `scripts/stage4_report_generator.py`
  - Use `build_pipeline_quality_state(...)` before report generation.
  - Verify `pring_result.metadata.analysis_date` matches market data date.
- Modify: `src/datasource/generators/simple_report.py`
  - Render commodity header as `近120日变化` when `ytd_change` is absent and `change_120d` is used.
- Modify: `src/datasource/models/market_data_contract.py`
  - Allow `None` for unavailable stock/forex window changes and preserve fund-flow `metric_basis`.
- Modify: `scripts/stage1_data_collector.py`
  - Correct `_calculate_change(..., 120)` to use true `t-120` baseline and return `None` when the window is unavailable.
  - Write `metric_basis` for TuShare-derived fund-flow windows.
- Modify: `tests/test_websearch_injector.py`
  - Extend existing Stage2.5 tests for source URL preservation, metric basis, and corrected window behavior.
- Modify: `tests/test_stage3_guard.py`
  - Update Stage3 guard tests to exercise the unified quality state.
- Modify: `tests/test_stage4_docs.py`
  - Add Stage4 blocking tests for stale internal quality state and date mismatch.
- Modify: `tests/test_simple_report_integration.py`
  - Add commodity table header and fallback rendering coverage.
- Modify: `tests/test_stage1_data_collector.py`
  - Add `_calculate_change` off-by-one coverage.

---

### Task 1: Add Unified Pipeline Quality State Module

**Files:**
- Create: `src/datasource/utils/pipeline_quality_state.py`
- Create: `tests/test_pipeline_quality_state.py`

- [ ] **Step 1: Write failing tests for core state calculation**

Add this file:

```python
# tests/test_pipeline_quality_state.py
# -*- coding: utf-8 -*-

from datasource.utils.pipeline_quality_state import build_pipeline_quality_state


def _base_payload():
    return {
        "metadata": {
            "date": "2026-04-27",
            "data_completeness": 1.0,
            "missing_items": {"macro_indicators": [{"key": "industrial"}]},
            "quality_blockers": [{"category": "monetary_policy", "key": "mlf", "reason": "old"}],
        },
        "missing_items": ["industrial"],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": 5.0,
                "change_rate": 4.0,
                "is_estimated": False,
                "source": "websearch_manual(https://example.com/industrial)",
                "source_url": "https://example.com/industrial",
            }
        },
        "monetary_policy": {
            "mlf": {
                "current_value": 2.0,
                "change_from_120d": 0.0,
                "is_estimated": False,
                "source": "websearch_manual(https://example.com/mlf)",
                "source_url": "https://example.com/mlf",
            }
        },
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }


def test_pipeline_quality_state_ignores_stale_missing_when_values_are_complete():
    state = build_pipeline_quality_state(_base_payload(), allow_estimated=False)

    assert state["missing_items"] == {}
    assert state["quality_blockers"] == []
    assert state["manual_required"] == []
    assert state["policy_evaluation"]["block_stage3"] is False
    assert state["gap_monitor_view"]["manual_required"] == []


def test_pipeline_quality_state_blocks_missing_compare_values():
    payload = _base_payload()
    payload["macro_indicators"]["industrial"]["previous_value"] = None
    payload["macro_indicators"]["industrial"]["change_rate"] = None

    state = build_pipeline_quality_state(payload, allow_estimated=False)

    assert {"category": "macro_indicators", "key": "industrial", "reason": "missing_compare_values"} in state["quality_blockers"]
    assert state["missing_items"]["macro_indicators"][0]["key"] == "industrial"
    assert "industrial" in state["gap_monitor_view"]["manual_required"]


def test_pipeline_quality_state_requires_source_url_for_manual_values():
    payload = _base_payload()
    payload["commodities"] = [
        {
            "symbol": "GC=F",
            "name": "COMEX黄金",
            "current_price": 3450.0,
            "daily_change": 1.2,
            "source": "websearch_manual",
        }
    ]

    state = build_pipeline_quality_state(payload, allow_estimated=False)

    assert {"category": "commodities", "key": "GC=F", "reason": "missing_source_url"} in state["source_url_issues"]
    assert {"category": "commodities", "key": "GC=F", "reason": "missing_source_url"} in state["quality_blockers"]


def test_pipeline_quality_state_blocks_disallowed_estimated_values_even_with_allow_estimated():
    payload = _base_payload()
    payload["monetary_policy"]["m2"] = {
        "current_value": 7.1,
        "change_from_120d": 0.2,
        "is_estimated": True,
        "source_url": "https://example.com/m2",
    }

    state = build_pipeline_quality_state(payload, allow_estimated=True)

    assert {"category": "monetary_policy", "key": "m2", "reason": "estimated_not_allowed"} in state["quality_blockers"]
    assert "monetary_policy.m2" in state["policy_evaluation"]["estimated_blockers"]


def test_pipeline_quality_state_flags_commodity_window_mismatch():
    payload = _base_payload()
    payload["commodities"] = [
        {
            "symbol": "GC=F",
            "current_price": 3450.0,
            "daily_change": 2.0,
            "daily_change_basis": "change_5d",
            "ytd_change": 12.0,
            "ytd_change_basis": "change_120d",
            "source_url": "https://example.com/gold",
        }
    ]

    state = build_pipeline_quality_state(payload, allow_estimated=False)

    reasons = {row["reason"] for row in state["window_metric_issues"]}
    assert "daily_change_from_change_5d" in reasons
    assert "ytd_change_from_change_120d" in reasons
```

- [ ] **Step 2: Run the tests and verify import failure**

Run:

```bash
python -m pytest -q tests/test_pipeline_quality_state.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'datasource.utils.pipeline_quality_state'`.

- [ ] **Step 3: Implement the minimal state calculator**

Create `src/datasource/utils/pipeline_quality_state.py`:

```python
# -*- coding: utf-8 -*-
"""Authoritative quality-state calculation for Stage2.5/Stage3/Stage4."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from datasource.utils.coercion import is_legacy_713_placeholder, is_stage2_number_placeholder
from datasource.utils.policy_rules import is_estimated_allowlisted, load_policy_rules


NUMERIC_MISSING = (None, "", "N/A")
URL_RE = re.compile(r"https?://[^\s|;，,）)]+")


def _safe_float(value: Any) -> Optional[float]:
    if value in NUMERIC_MISSING:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _has_valid_value(value: Any, *, allow_zero: bool = False) -> bool:
    number = _safe_float(value)
    if number is None:
        return False
    if allow_zero:
        return True
    return abs(number) > 1e-9


def _item_key(item: Any) -> Optional[str]:
    if isinstance(item, dict):
        value = item.get("key") or item.get("indicator_key")
    else:
        value = item
    if value in (None, ""):
        return None
    return str(value)


def _append_unique(rows: List[Dict[str, str]], category: str, key: str, reason: str) -> None:
    row = {"category": str(category), "key": str(key), "reason": str(reason)}
    if row not in rows:
        rows.append(row)


def _source_text(entry: Dict[str, Any]) -> str:
    parts = []
    for field in ("source_url", "url", "source", "note"):
        value = entry.get(field)
        if value not in (None, ""):
            parts.append(str(value))
    return " ".join(parts)


def _has_source_url(entry: Dict[str, Any]) -> bool:
    if entry.get("source_url") or entry.get("url"):
        return True
    return bool(URL_RE.search(_source_text(entry)))


def _looks_websearch_or_manual(entry: Dict[str, Any]) -> bool:
    text = _source_text(entry).lower()
    return any(marker in text for marker in ("websearch", "manual", "tavily", "deepseek", "http://", "https://"))


def _iter_entries(payload: Dict[str, Any]) -> Iterable[Tuple[str, str, Dict[str, Any], str]]:
    for key, entry in (payload.get("macro_indicators") or {}).items():
        if isinstance(entry, dict):
            yield "macro_indicators", str(key), entry, "current_value"
    for key, entry in (payload.get("monetary_policy") or {}).items():
        if isinstance(entry, dict):
            yield "monetary_policy", str(key), entry, "current_value"
    for item in payload.get("bonds", []) or []:
        if isinstance(item, dict):
            yield "bonds", str(item.get("symbol") or ""), item, "current_yield"
    for item in payload.get("forex", []) or []:
        if isinstance(item, dict):
            yield "forex", str(item.get("pair") or ""), item, "current_rate"
    for item in payload.get("commodities", []) or []:
        if isinstance(item, dict):
            yield "commodities", str(item.get("symbol") or ""), item, "current_price"
    for item in payload.get("stock_indices", []) or []:
        if isinstance(item, dict):
            yield "stock_indices", str(item.get("symbol") or ""), item, "current_price"
    for key, entry in (payload.get("fund_flow") or {}).items():
        if isinstance(entry, dict):
            yield "fund_flow", str(key), entry, "recent_5d"


def _add_missing(missing: Dict[str, List[Dict[str, str]]], category: str, key: str, reason: str) -> None:
    rows = missing.setdefault(category, [])
    row = {"key": str(key), "reason": str(reason)}
    if row not in rows:
        rows.append(row)


def _collect_compare_and_value_blockers(payload: Dict[str, Any], missing: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, str]]:
    blockers: List[Dict[str, str]] = []
    for key, entry in (payload.get("macro_indicators") or {}).items():
        if not isinstance(entry, dict):
            continue
        if not _has_valid_value(entry.get("current_value"), allow_zero=True):
            _append_unique(blockers, "macro_indicators", key, "missing_value")
            _add_missing(missing, "macro_indicators", key, "missing_value")
            continue
        if entry.get("previous_value") is None or entry.get("change_rate") is None:
            _append_unique(blockers, "macro_indicators", key, "missing_compare_values")
            _add_missing(missing, "macro_indicators", key, "missing_compare_values")

    for key, entry in (payload.get("monetary_policy") or {}).items():
        if not isinstance(entry, dict):
            continue
        if not _has_valid_value(entry.get("current_value"), allow_zero=True):
            _append_unique(blockers, "monetary_policy", key, "missing_value")
            _add_missing(missing, "monetary_policy", key, "missing_value")
            continue
        if entry.get("change_from_120d") is None:
            _append_unique(blockers, "monetary_policy", key, "missing_compare_values")
            _add_missing(missing, "monetary_policy", key, "missing_compare_values")

    for category, key, entry, value_field in _iter_entries(payload):
        if not key:
            continue
        if category in {"macro_indicators", "monetary_policy", "fund_flow"}:
            continue
        value = entry.get(value_field)
        if is_legacy_713_placeholder(value) or is_stage2_number_placeholder(value):
            _append_unique(blockers, category, key, "placeholder_value")
            _add_missing(missing, category, key, "placeholder_value")
        elif not _has_valid_value(value):
            _append_unique(blockers, category, key, "missing_or_zero_value")
            _add_missing(missing, category, key, "missing_or_zero_value")

    for key, entry in (payload.get("fund_flow") or {}).items():
        if not isinstance(entry, dict):
            continue
        if not _has_valid_value(entry.get("recent_5d")) or not _has_valid_value(entry.get("total_120d")):
            _append_unique(blockers, "fund_flow", key, "fund_flow_window_missing")
            _add_missing(missing, "fund_flow", key, "fund_flow_window_missing")
    return blockers


def _collect_source_url_issues(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    for category, key, entry, value_field in _iter_entries(payload):
        if not key:
            continue
        has_value = _has_valid_value(entry.get(value_field), allow_zero=category in {"macro_indicators", "monetary_policy"})
        if category == "fund_flow":
            has_value = _has_valid_value(entry.get("recent_5d")) or _has_valid_value(entry.get("total_120d"))
        if has_value and _looks_websearch_or_manual(entry) and not _has_source_url(entry):
            _append_unique(issues, category, key, "missing_source_url")
    return issues


def _collect_estimated_blockers(payload: Dict[str, Any], rules: Dict[str, Any]) -> List[Dict[str, str]]:
    blockers: List[Dict[str, str]] = []
    for category, key, entry, value_field in _iter_entries(payload):
        if not key or not entry.get("is_estimated"):
            continue
        if not _has_valid_value(entry.get(value_field), allow_zero=True):
            continue
        allowed, reasons = is_estimated_allowlisted(category, key, entry, rules=rules)
        if not allowed:
            reason = "estimated_not_allowed"
            if reasons:
                reason = reason + ":" + "|".join(reasons)
            _append_unique(blockers, category, key, reason)
    return blockers


def _collect_stale_redlist(payload: Dict[str, Any], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    critical = {str(k).lower() for k in rules.get("critical_stale_keys", ["cpi", "ppi", "pmi", "m1", "m2", "tsf"])}
    stale: List[Dict[str, Any]] = []
    if not bool(rules.get("block_on_stale", True)):
        return stale
    for category in ("macro_indicators", "monetary_policy"):
        section = payload.get(category) or {}
        if not isinstance(section, dict):
            continue
        for key, entry in section.items():
            if isinstance(entry, dict) and entry.get("is_stale") and str(key).lower() in critical:
                stale.append(
                    {
                        "category": category,
                        "key": str(key),
                        "date": entry.get("date"),
                        "expected_period": entry.get("expected_period"),
                        "reason": entry.get("stale_reason") or "actual_period_behind_expected",
                    }
                )
    return stale


def _collect_window_metric_issues(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    for item in payload.get("commodities", []) or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("symbol") or "")
        if item.get("daily_change_basis") == "change_5d":
            _append_unique(issues, "commodities", key, "daily_change_from_change_5d")
        if item.get("ytd_change_basis") == "change_120d":
            _append_unique(issues, "commodities", key, "ytd_change_from_change_120d")
    for item in payload.get("forex", []) or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("pair") or "")
        if item.get("daily_change") == 0.0 and str(item.get("source") or "").lower() in {"占位", "placeholder"}:
            _append_unique(issues, "forex", key, "daily_change_placeholder_zero")
    for key, flow in (payload.get("fund_flow") or {}).items():
        if not isinstance(flow, dict):
            continue
        if not flow.get("metric_basis"):
            _append_unique(issues, "fund_flow", str(key), "metric_basis_missing")
    return issues


def _to_gap_view(missing: Dict[str, List[Dict[str, str]]], blockers: List[Dict[str, str]]) -> Dict[str, List[Any]]:
    manual: List[str] = []
    for rows in missing.values():
        for row in rows:
            key = row.get("key")
            if key and key not in manual:
                manual.append(key)
    return {
        "pending_tasks": [],
        "manual_required": manual,
        "data_quality_issues": list(blockers),
    }


def build_pipeline_quality_state(
    market_payload: Dict[str, Any],
    *,
    policy_rules: Optional[Dict[str, Any]] = None,
    stage: str = "stage3",
    allow_estimated: bool = False,
) -> Dict[str, Any]:
    rules = policy_rules or load_policy_rules()
    missing: Dict[str, List[Dict[str, str]]] = {}
    blockers = _collect_compare_and_value_blockers(market_payload, missing)
    source_url_issues = _collect_source_url_issues(market_payload)
    estimated_blockers = _collect_estimated_blockers(market_payload, rules)
    stale_redlist = _collect_stale_redlist(market_payload, rules)
    window_metric_issues = _collect_window_metric_issues(market_payload)

    for row in source_url_issues + estimated_blockers + window_metric_issues:
        _append_unique(blockers, row["category"], row["key"], row["reason"])
        _add_missing(missing, row["category"], row["key"], row["reason"])
    for row in stale_redlist:
        key = str(row.get("key"))
        category = str(row.get("category"))
        _append_unique(blockers, category, key, "stale_critical_item")
        _add_missing(missing, category, key, "stale_critical_item")

    estimated_labels = [f"{row['category']}.{row['key']}" for row in estimated_blockers]
    policy_evaluation = {
        "generated_at": datetime.now().isoformat(),
        "date": (market_payload.get("metadata") or {}).get("date"),
        "block_stage3": bool(blockers),
        "redlist": [{"category": row["category"], "key": row["key"], "reason": row["reason"]} for row in blockers],
        "stale_redlist": stale_redlist,
        "estimated_blockers": estimated_labels,
        "allow_estimated": bool(allow_estimated),
        "stage": stage,
    }
    return {
        "missing_items": missing,
        "quality_blockers": blockers,
        "manual_required": _to_gap_view(missing, blockers)["manual_required"],
        "policy_evaluation": policy_evaluation,
        "gap_monitor_view": _to_gap_view(missing, blockers),
        "source_url_issues": source_url_issues,
        "window_metric_issues": window_metric_issues,
        "warnings": [],
    }
```

- [ ] **Step 4: Run the module tests**

Run:

```bash
python -m pytest -q tests/test_pipeline_quality_state.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/datasource/utils/pipeline_quality_state.py tests/test_pipeline_quality_state.py
git commit -m "feat: add pipeline quality state calculator"
```

---

### Task 2: Wire Unified State Into Stage2.5 Outputs

**Files:**
- Modify: `scripts/stage2_5_injector.py`
- Modify: `tests/test_websearch_injector.py`

- [ ] **Step 1: Write failing tests for Stage2.5 writeback**

Append to `tests/test_websearch_injector.py`:

```python
def test_stage25_writes_unified_quality_state_files(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    market_path = tmp_path / "market_data_stage2.json"
    manual_path = tmp_path / "websearch_results_manual.json"
    output_path = tmp_path / "market_data_complete.json"
    market_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "date": "2026-04-27",
                    "data_completeness": 0.5,
                    "missing_items": {"macro_indicators": [{"key": "industrial"}]},
                    "quality_blockers": [{"category": "macro_indicators", "key": "industrial", "reason": "old"}],
                },
                "missing_items": ["industrial"],
                "macro_indicators": {
                    "industrial": {
                        "indicator_name": "工业增加值",
                        "current_value": None,
                        "previous_value": None,
                        "change_rate": None,
                        "unit": "%",
                        "source": "占位",
                    }
                },
                "monetary_policy": {},
                "fund_flow": {},
                "commodities": [],
                "forex": [],
                "bonds": [],
                "stock_indices": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "macro_indicators": {
                    "industrial": {
                        "indicator_name": "工业增加值",
                        "current_value": 5.2,
                        "previous_value": 5.0,
                        "change_rate": 4.0,
                        "unit": "%",
                        "date": "2026-03",
                        "source": "国家统计局 https://example.com/industrial",
                        "source_url": "https://example.com/industrial",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        backfill_trend=False,
        gap_monitor_path=tmp_path / "data" / "runs" / "20260427" / "gap_monitor.json",
        disable_trend_history_write=True,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    gap = json.loads((tmp_path / "data" / "runs" / "20260427" / "gap_monitor.json").read_text(encoding="utf-8"))
    policy = json.loads((tmp_path / "data" / "runs" / "20260427" / "policy_evaluation.json").read_text(encoding="utf-8"))

    assert output["metadata"].get("missing_items") == {}
    assert output["missing_items"] == []
    assert output["metadata"].get("quality_blockers") == []
    assert gap.get("manual_required") == []
    assert gap.get("pending_tasks") == []
    assert policy["block_stage3"] is False


def test_stage25_preserves_manual_source_url_and_fund_flow_metric_basis(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    market_path = tmp_path / "market_data_stage2.json"
    manual_path = tmp_path / "websearch_results_manual.json"
    output_path = tmp_path / "market_data_complete.json"
    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-04-27", "data_completeness": 0.8},
                "missing_items": [],
                "macro_indicators": {},
                "monetary_policy": {},
                "fund_flow": {
                    "northbound": {"type": "northbound", "recent_5d": None, "total_120d": None, "source": "占位"}
                },
                "commodities": [
                    {"symbol": "GC=F", "name": "COMEX黄金", "current_price": None, "source": "占位"}
                ],
                "forex": [],
                "bonds": [],
                "stock_indices": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "commodities": [
                    {
                        "symbol": "GC=F",
                        "name": "COMEX黄金",
                        "current_price": 3450.5,
                        "unit": "$/oz",
                        "source": "manual https://example.com/gold",
                        "source_url": "https://example.com/gold",
                    }
                ],
                "fund_flow": {
                    "northbound": {
                        "recent_5d": 85.6,
                        "total_120d": 1250.0,
                        "trend": "流入",
                        "source": "manual https://example.com/north",
                        "source_url": "https://example.com/north",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        backfill_trend=False,
        gap_monitor_path=tmp_path / "gap_monitor.json",
        disable_trend_history_write=True,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["commodities"][0]["source_url"] == "https://example.com/gold"
    assert output["fund_flow"]["northbound"]["source_url"] == "https://example.com/north"
    assert output["fund_flow"]["northbound"]["metric_basis"] == "net_flow_sum"
```

- [ ] **Step 2: Run the new Stage2.5 tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_websearch_injector.py::test_stage25_writes_unified_quality_state_files tests/test_websearch_injector.py::test_stage25_preserves_manual_source_url_and_fund_flow_metric_basis
```

Expected: FAIL because `quality_blockers` is not driven by the unified state and `source_url`/`metric_basis` are not preserved for all merged entries.

- [ ] **Step 3: Import and add helpers in Stage2.5**

In `scripts/stage2_5_injector.py`, add imports near the existing utils imports:

```python
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state
from datasource.utils.quality_metrics import build_quality_metrics
```

Add helpers near `_rewrite_gap_monitor_after_injection`:

```python
def _apply_pipeline_quality_state(market_data: Dict[str, Any], *, allow_estimated: bool = False) -> Dict[str, Any]:
    state = build_pipeline_quality_state(
        market_data,
        policy_rules=_policy_rules(),
        stage="stage2_5",
        allow_estimated=allow_estimated,
    )
    metadata = market_data.setdefault("metadata", {})
    metadata["missing_items"] = state["missing_items"]
    metadata["quality_blockers"] = state["quality_blockers"]
    metadata["source_url_issues"] = state["source_url_issues"]
    metadata["window_metric_issues"] = state["window_metric_issues"]
    metadata["manual_required"] = state["manual_required"]
    if not state["missing_items"]:
        metadata["missing_items"] = {}
    market_data["missing_items"] = list(state["manual_required"])
    if not market_data["missing_items"]:
        market_data["missing_items"] = []
    return state


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _write_quality_state_artifacts(
    market_data: Dict[str, Any],
    state: Dict[str, Any],
    *,
    date_override: Optional[str],
    gap_monitor_path: Optional[Path],
) -> None:
    run_paths = build_run_paths_from_reference(date=date_override, payload=market_data, fallback_to_today=True)
    target_gap = gap_monitor_path or run_paths.gap_monitor
    gap_payload = dict(state["gap_monitor_view"])
    gap_payload["generated_at"] = datetime.now().isoformat()
    _write_json_atomic(target_gap, gap_payload)
    quality_payload = build_quality_metrics(market_data)
    quality_payload["missing_items"] = state["missing_items"]
    quality_payload["quality_blockers"] = state["quality_blockers"]
    quality_payload["source_url_issues"] = state["source_url_issues"]
    quality_payload["window_metric_issues"] = state["window_metric_issues"]
    _write_json_atomic(run_paths.quality_metrics, quality_payload)
    _write_json_atomic(run_paths.policy_evaluation, state["policy_evaluation"])
```

- [ ] **Step 4: Preserve `source_url` and `metric_basis` in merge functions**

In `_apply_fund_flow_entry(...)`, before `return True`, add:

```python
    if payload.get("source_url"):
        entry["source_url"] = payload.get("source_url")
    elif payload.get("url"):
        entry["source_url"] = payload.get("url")
    if payload.get("metric_basis"):
        entry["metric_basis"] = payload.get("metric_basis")
    elif key in ("northbound", "southbound"):
        entry["metric_basis"] = "net_flow_sum"
    elif key == "margin":
        entry["metric_basis"] = "balance_delta"
    elif key == "etf":
        entry["metric_basis"] = "estimated_net_flow" if payload.get("is_estimated") else "net_flow_sum"
```

In `_merge_commodity_entry(...)`, before `return merged`, add:

```python
    if payload.get("source_url") or payload.get("url"):
        merged["source_url"] = payload.get("source_url") or payload.get("url")
    if payload.get("is_estimated") is not None:
        merged["is_estimated"] = _coerce_bool(payload.get("is_estimated"))
    if payload.get("metric_basis"):
        merged["metric_basis"] = payload.get("metric_basis")
```

In `_merge_forex_entry(...)`, before `return merged`, add:

```python
    if payload.get("source_url") or payload.get("url"):
        merged["source_url"] = payload.get("source_url") or payload.get("url")
    if payload.get("is_estimated") is not None:
        merged["is_estimated"] = _coerce_bool(payload.get("is_estimated"))
```

In `_merge_bond_entry(...)`, before `return merged`, add the same preservation block for `source_url`, `is_estimated`, `estimation_method`, and `metric_basis`:

```python
    if payload.get("source_url") or payload.get("url"):
        merged["source_url"] = payload.get("source_url") or payload.get("url")
    for field in ("estimation_method", "metric_basis", "confidence"):
        if payload.get(field) is not None:
            merged[field] = payload.get(field)
    if payload.get("is_estimated") is not None:
        merged["is_estimated"] = _coerce_bool(payload.get("is_estimated"))
```

- [ ] **Step 5: Replace final Stage2.5 artifact refresh with unified state**

In `inject_websearch_data(...)`, after trend backfill and before the final output write, replace the ad hoc quality blocker call:

```python
    _cleanup_metadata_missing(metadata, market_data)
    quality_blockers = _enforce_quality_blockers(market_data)
```

with:

```python
    _cleanup_metadata_missing(metadata, market_data)
    quality_state = _apply_pipeline_quality_state(market_data, allow_estimated=False)
    quality_blockers = quality_state["quality_blockers"]
```

After writing `market_data_complete.json`, replace the `write_quality_metrics(...)` and `evaluate_policy(...)` blocks with:

```python
    try:
        _write_quality_state_artifacts(
            market_data,
            quality_state,
            date_override=date_override,
            gap_monitor_path=gap_monitor_path,
        )
        print("  - unified quality state refreshed")
    except Exception as exc:  # noqa: BLE001
        print(f"  - unified quality state refresh failed: {exc}")
```

Keep `_sync_backfill_issues_to_logs(...)`, but update it in the next step so it does not reintroduce stale `gap_monitor` state.

- [ ] **Step 6: Make gap monitor rewrite use unified state**

Replace `_rewrite_gap_monitor_after_injection(...)` body after `target_path` resolution with:

```python
    state = build_pipeline_quality_state(
        market_data,
        policy_rules=_policy_rules(),
        stage="stage2_5",
        allow_estimated=False,
    )
    payload = dict(state["gap_monitor_view"])
    payload["generated_at"] = datetime.now().isoformat()
    if extra_issues:
        payload["data_quality_issues"] = _merge_quality_issues(payload.get("data_quality_issues", []), extra_issues)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_path
```

- [ ] **Step 7: Run Stage2.5 focused tests**

Run:

```bash
python -m pytest -q tests/test_websearch_injector.py tests/test_stage25_contract_replay.py tests/test_pipeline_quality_state.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add scripts/stage2_5_injector.py tests/test_websearch_injector.py tests/test_stage25_contract_replay.py
git commit -m "feat: write unified quality state from stage25"
```

---

### Task 3: Correct Window Metric Semantics

**Files:**
- Modify: `src/datasource/models/market_data_contract.py`
- Modify: `scripts/stage1_data_collector.py`
- Modify: `scripts/stage2_5_injector.py`
- Modify: `tests/test_stage1_data_collector.py`
- Modify: `tests/test_websearch_injector.py`

- [ ] **Step 1: Write failing tests for 120-day baseline and Stage2.5 windows**

Append to `tests/test_stage1_data_collector.py`:

```python
def test_calculate_change_uses_true_t_minus_window_baseline():
    import pandas as pd
    from scripts.stage1_data_collector import Stage1DataCollector

    df = pd.DataFrame({"close": list(range(1, 123))})
    collector = Stage1DataCollector.__new__(Stage1DataCollector)

    assert collector._calculate_change(df, 120) == round(((122 / 2) - 1) * 100, 1)


def test_calculate_change_returns_none_when_window_unavailable():
    import pandas as pd
    from scripts.stage1_data_collector import Stage1DataCollector

    df = pd.DataFrame({"close": list(range(1, 121))})
    collector = Stage1DataCollector.__new__(Stage1DataCollector)

    assert collector._calculate_change(df, 120) is None
```

Append to `tests/test_websearch_injector.py`:

```python
def test_merge_commodity_entry_does_not_put_5d_into_daily_or_120d_into_ytd(monkeypatch):
    existing = {
        "symbol": "GC=F",
        "name": "COMEX黄金",
        "current_price": None,
        "daily_change": None,
        "ytd_change": None,
        "source": "占位",
    }
    payload = {
        "symbol": "GC=F",
        "current_price": "3450.0",
        "source": "manual https://example.com/gold",
        "source_url": "https://example.com/gold",
    }

    monkeypatch.setattr(
        injector,
        "_calc_change_from_trend_history",
        lambda *args, **kwargs: {
            "change_5d": 1.5,
            "change_120d": 12.3,
            "reason_5d": None,
            "reason_120d": None,
            "base_5d_estimated": False,
            "base_120d_estimated": False,
        },
    )

    merged = injector._merge_commodity_entry(existing, payload, is_manual=True)

    assert merged["daily_change"] is None
    assert merged["ytd_change"] is None
    assert merged["change_120d"] == pytest.approx(12.3)
    assert merged["change_120d_basis"] == "trend_history"
    assert "daily_change_basis" not in merged
    assert "ytd_change_basis" not in merged


def test_build_forex_entry_keeps_unknown_changes_as_none(monkeypatch):
    monkeypatch.setattr(
        injector,
        "_calc_change_from_trend_history",
        lambda *args, **kwargs: {"change_120d": None, "reason_120d": "trend_history_missing"},
    )
    monkeypatch.setattr(
        injector,
        "_calc_daily_change_from_trend_history",
        lambda *args, **kwargs: {"change_1d": None, "reason_1d": "trend_history_missing"},
    )

    entry = injector._build_forex_entry(
        {"pair": "USDCNY", "current_rate": "7.1", "source": "manual https://example.com/fx", "source_url": "https://example.com/fx"}
    )

    assert entry["daily_change"] is None
    assert entry["change_120d"] is None
```

- [ ] **Step 2: Run window tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_stage1_data_collector.py::test_calculate_change_uses_true_t_minus_window_baseline tests/test_stage1_data_collector.py::test_calculate_change_returns_none_when_window_unavailable tests/test_websearch_injector.py::test_merge_commodity_entry_does_not_put_5d_into_daily_or_120d_into_ytd tests/test_websearch_injector.py::test_build_forex_entry_keeps_unknown_changes_as_none
```

Expected: FAIL because `_calculate_change` uses `iloc[-days]`, commodities map windows into the wrong fields, and forex unknown windows become `0.0`.

- [ ] **Step 3: Fix Stage1 `_calculate_change`**

In `scripts/stage1_data_collector.py`, replace `_calculate_change` with:

```python
    def _calculate_change(self, df: pd.DataFrame, days: int) -> Optional[float]:
        """计算指定交易日窗口涨跌幅，days=120 表示 current vs t-120。"""
        try:
            if len(df) <= days:
                return None
            latest = df.iloc[-1]['close']
            previous = df.iloc[-(days + 1)]['close']
            if previous in (None, 0):
                return None
            return round(((latest / previous) - 1) * 100, 1)
        except Exception:
            return None
```

The file already imports `Optional` in `from typing import Dict, Any, List, Optional, Tuple`, so no import change is needed.

- [ ] **Step 4: Update contract fields that can now be unknown**

In `src/datasource/models/market_data_contract.py`, change `StockIndexData`, `ForexData`, and `FundFlowData` fields:

```python
class StockIndexData(BaseModel):
    """股票指数数据"""
    symbol: str
    name: str
    current_price: float
    change_5d: Optional[float] = None
    change_120d: Optional[float] = None
    above_ma50: bool
    above_ma200: bool
    ma50_slope: float
    volatility_30d: float
    trend_score: int
    trend_label: str
    source: str


class ForexData(BaseModel):
    """汇率数据"""
    pair: str
    name: str
    current_rate: float
    daily_change: Optional[float] = None
    change_120d: Optional[float] = None
    trend: str
    source: str
    source_url: Optional[str] = None


class FundFlowData(BaseModel):
    """资金流向数据"""

    type: str
    recent_5d: Optional[float] = None
    total_120d: Optional[float] = None
    trend: str
    source: str
    note: Optional[str] = None
    stage_task_id: Optional[str] = None
    source_url: Optional[str] = None
    metric_basis: Optional[str] = None
```

- [ ] **Step 5: Write fund-flow `metric_basis` in Stage1**

In `scripts/stage1_data_collector.py`, add `metric_basis` to each `FundFlowData(...)` construction:

```python
            fund_flow_dict[flow['key']] = FundFlowData(
                type=flow['type'],
                recent_5d=None,
                total_120d=None,
                trend='待获取',
                source='待WebSearch补充',
                note='需要WebSearch/Tavily实时获取',
                metric_basis=None,
            )
```

For northbound and southbound:

```python
                metric_basis='net_flow_sum',
```

For margin:

```python
                metric_basis="balance_delta",
```

For ETF proxy:

```python
                metric_basis="estimated_net_flow",
```

- [ ] **Step 6: Fix Stage2.5 commodity merge**

In `_merge_commodity_entry(...)`, replace the trend-history change block with:

```python
        merged['daily_change'] = _coerce_percent(payload.get('daily_change'))
        hist_120d = _coerce_float(hist_changes.get('change_120d'))
        payload_ytd = _coerce_percent(payload.get('ytd_change'))
        if payload_ytd is not None:
            merged['ytd_change'] = payload_ytd
            merged['ytd_change_basis'] = payload.get("ytd_change_basis") or "year_to_date"
        else:
            merged['ytd_change'] = existing.get('ytd_change')
        if hist_120d is not None:
            merged['change_120d'] = hist_120d
            merged['change_120d_basis'] = "trend_history"
            used_hist_120d = True
        if merged.get('daily_change') is None:
            merged['daily_change'] = existing.get('daily_change')
```

Also update the trend inference call:

```python
    trend_window_value = merged.get("ytd_change")
    if trend_window_value is None:
        trend_window_value = merged.get("change_120d")
    merged['trend'] = _infer_asset_trend(raw_trend, merged.get('daily_change'), trend_window_value, "commodity")
```

- [ ] **Step 7: Fix Stage2.5 commodity backfill loop**

In `_backfill_trend_changes(...)`, replace the commodity `ytd_change` and `daily_change` backfill section with:

```python
        if _should_backfill_numeric(comm.get("change_120d")):
            if hist.get("change_120d") is not None:
                comm["change_120d"] = round(float(hist["change_120d"]), 2)
                comm["change_120d_basis"] = "trend_history"
                stats["commodities"] += 1
                used_hist_120d = True
            else:
                comm["change_120d"] = None
                reason = hist.get("reason_120d") or "trend_history_missing"
                _record_backfill_issue(metadata, "commodities", symbol, "change_120d", reason)
                _append_note(comm, f"reason={reason}")
        if comm.get("daily_change") is None:
            daily_hist = _calc_daily_change_from_trend_history("commodities", symbol, current, base_dir=base_dir, reference_date=reference_date)
            if daily_hist.get("change_1d") is not None:
                comm["daily_change"] = round(float(daily_hist["change_1d"]), 2)
                comm["daily_change_basis"] = "change_1d"
                stats["commodities"] += 1
                used_hist_5d = True
            else:
                comm["daily_change"] = None
                reason = daily_hist.get("reason_1d") or "trend_history_missing"
                _record_backfill_issue(metadata, "commodities", symbol, "daily_change", reason)
                _append_note(comm, f"reason={reason}")
```

- [ ] **Step 8: Fix forex merge/build fallback values**

In `_merge_forex_entry(...)`, replace fallback assignments that end in `orig.get(..., 0.0)` with `orig.get(...)`.

In `_build_forex_entry(...)`, replace:

```python
        if daily_change is None:
            daily_change = daily_hist.get('change_1d') or 0.0
        if change_120d is None:
            change_120d = hist_changes.get('change_120d') or 0.0

    daily_change_val = daily_change or 0.0
    change_120d_val = change_120d or 0.0
```

with:

```python
        if daily_change is None:
            daily_change = daily_hist.get('change_1d')
        if change_120d is None:
            change_120d = hist_changes.get('change_120d')

    daily_change_val = daily_change
    change_120d_val = change_120d
```

- [ ] **Step 9: Make stock report rendering tolerate unavailable windows**

In `src/datasource/generators/simple_report.py`, replace the stock index row:

```python
        report += f"| {idx['name']} | {idx['current_price']:.2f} | {idx['change_5d']:+.2f}% | {idx['change_120d']:+.1f}% | {above_ma50} | {above_ma200} | {idx['trend_label']} |\n"
```

with:

```python
        change_5d_text = _fmt_change_cell(idx.get("change_5d"), digits=2, suffix="%")
        change_120d_text = _fmt_change_cell(idx.get("change_120d"), digits=1, suffix="%")
        report += f"| {idx['name']} | {idx['current_price']:.2f} | {change_5d_text} | {change_120d_text} | {above_ma50} | {above_ma200} | {idx['trend_label']} |\n"
```

- [ ] **Step 10: Run window test set**

Run:

```bash
python -m pytest -q tests/test_stage1_data_collector.py tests/test_websearch_injector.py::test_merge_commodity_entry_does_not_put_5d_into_daily_or_120d_into_ytd tests/test_websearch_injector.py::test_build_forex_entry_keeps_unknown_changes_as_none tests/test_pipeline_quality_state.py tests/test_simple_report_integration.py
```

Expected: PASS.

- [ ] **Step 11: Commit Task 3**

```bash
git add src/datasource/models/market_data_contract.py scripts/stage1_data_collector.py scripts/stage2_5_injector.py src/datasource/generators/simple_report.py tests/test_stage1_data_collector.py tests/test_websearch_injector.py tests/test_pipeline_quality_state.py tests/test_simple_report_integration.py
git commit -m "fix: correct window metric semantics"
```

---

### Task 4: Replace Stage3 Gates With Unified State

**Files:**
- Modify: `scripts/stage3_pring_analyzer.py`
- Modify: `tests/test_stage3_guard.py`

- [ ] **Step 1: Add failing Stage3 unified-state tests**

Append to `tests/test_stage3_guard.py`:

```python
def test_require_data_completeness_uses_unified_state_to_ignore_stale_missing():
    payload = {
        "metadata": {
            "data_completeness": 1.0,
            "missing_items": {"macro_indicators": [{"key": "industrial"}]},
            "quality_blockers": [{"category": "macro_indicators", "key": "industrial", "reason": "old"}],
        },
        "missing_items": ["industrial"],
        "macro_indicators": {
            "industrial": {
                "current_value": 5.2,
                "previous_value": 5.0,
                "change_rate": 4.0,
                "is_estimated": False,
                "source_url": "https://example.com/industrial",
            }
        },
        "monetary_policy": {},
        "fund_flow": {},
        "commodities": [],
        "forex": [],
        "bonds": [],
        "stock_indices": [],
    }

    s3._require_data_completeness(payload, 0.8)


def test_require_data_completeness_blocks_source_url_issue_from_unified_state():
    payload = {
        "metadata": {"data_completeness": 1.0},
        "missing_items": [],
        "macro_indicators": {},
        "monetary_policy": {},
        "fund_flow": {},
        "commodities": [
            {
                "symbol": "GC=F",
                "current_price": 3450.0,
                "source": "websearch_manual",
            }
        ],
        "forex": [],
        "bonds": [],
        "stock_indices": [],
    }

    with pytest.raises(RuntimeError) as exc:
        s3._require_data_completeness(payload, 0.8)
    assert "missing_source_url" in str(exc.value)
```

- [ ] **Step 2: Run Stage3 tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_stage3_guard.py::test_require_data_completeness_uses_unified_state_to_ignore_stale_missing tests/test_stage3_guard.py::test_require_data_completeness_blocks_source_url_issue_from_unified_state
```

Expected: first test fails because old missing fields are trusted; second fails because source URL issues are not part of the Stage3 gate.

- [ ] **Step 3: Import and use unified state in Stage3**

In `scripts/stage3_pring_analyzer.py`, add:

```python
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state
```

At the top of `_require_data_completeness(...)`, after metadata and rules are available, add:

```python
    state = build_pipeline_quality_state(
        market_payload,
        policy_rules=policy_rules,
        stage="stage3",
        allow_estimated=allow_estimated,
    )
    state_blockers = state.get("quality_blockers") or []
    if state_blockers:
        details = "; ".join(
            f"{row.get('category')}.{row.get('key')}:{row.get('reason')}"
            for row in state_blockers
            if isinstance(row, dict)
        )
        raise RuntimeError(f"统一质量状态阻断 Stage3: {details}")
```

Then replace:

```python
    missing_items = _flatten_missing_items(market_payload)
```

with:

```python
    missing_items = list(state.get("manual_required") or [])
```

- [ ] **Step 4: Simplify policy file redlist behavior in `_run_analysis`**

Keep loading `policy_evaluation.json` for compatibility, but do not let stale file redlists override a clean calculated state. Replace the block:

```python
                if policy_payload.get("block_stage3") and (blocking_redlist or stale_redlist):
                    blockers.append(
                        f"policy: redlist={blocking_redlist}, stale_redlist={stale_redlist}"
                    )
```

with:

```python
                calculated_state = build_pipeline_quality_state(
                    market_payload,
                    policy_rules=policy_rules,
                    stage="stage3",
                    allow_estimated=allow_estimated,
                )
                if calculated_state["policy_evaluation"].get("block_stage3"):
                    blockers.append(
                        "policy: "
                        f"redlist={calculated_state['policy_evaluation'].get('redlist', [])}, "
                        f"stale_redlist={calculated_state['policy_evaluation'].get('stale_redlist', [])}"
                    )
                elif policy_payload.get("block_stage3"):
                    _append_non_blocking_warning(
                        market_payload,
                        {
                            "level": "warning",
                            "code": "stale_policy_evaluation_ignored",
                            "key": "*",
                            "message": "policy_evaluation.json 与现算状态不一致，已按现算状态放行",
                        },
                    )
```

- [ ] **Step 5: Run Stage3 focused tests**

Run:

```bash
python -m pytest -q tests/test_stage3_guard.py tests/test_pipeline_quality_state.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add scripts/stage3_pring_analyzer.py tests/test_stage3_guard.py
git commit -m "feat: gate stage3 with unified quality state"
```

---

### Task 5: Add Stage4 Unified Preflight And Report Date Check

**Files:**
- Modify: `scripts/stage4_report_generator.py`
- Modify: `tests/test_stage4_docs.py`

- [ ] **Step 1: Add failing Stage4 tests**

Append to `tests/test_stage4_docs.py`:

```python
def test_stage4_blocks_unified_quality_state_even_when_gap_monitor_empty(tmp_path, monkeypatch):
    market_path = tmp_path / "market_data_complete.json"
    pring_path = tmp_path / "pring_result.json"
    output_path = tmp_path / "report.md"
    gap_path = tmp_path / "gap_monitor.json"
    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-04-27", "ai_websearch_enhanced": True, "data_completeness": 1.0},
                "missing_items": [],
                "macro_indicators": {},
                "monetary_policy": {},
                "fund_flow": {},
                "commodities": [{"symbol": "GC=F", "current_price": 3450.0, "source": "websearch_manual"}],
                "forex": [],
                "bonds": [],
                "stock_indices": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pring_path.write_text(json.dumps({"metadata": {"analysis_date": "2026-04-27"}}, ensure_ascii=False), encoding="utf-8")
    gap_path.write_text(json.dumps({"pending_tasks": [], "manual_required": []}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(stage4, "generate_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        stage4,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "market_data": str(market_path),
                "pring_result": str(pring_path),
                "output": str(output_path),
                "gap_monitor": str(gap_path),
            },
        )(),
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()
    assert "missing_source_url" in str(exc.value)


def test_stage4_blocks_pring_market_date_mismatch(tmp_path, monkeypatch):
    market_path = tmp_path / "market_data_complete.json"
    pring_path = tmp_path / "pring_result.json"
    output_path = tmp_path / "report.md"
    gap_path = tmp_path / "gap_monitor.json"
    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-04-27", "ai_websearch_enhanced": True, "data_completeness": 1.0},
                "missing_items": [],
                "macro_indicators": {},
                "monetary_policy": {},
                "fund_flow": {},
                "commodities": [],
                "forex": [],
                "bonds": [],
                "stock_indices": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pring_path.write_text(json.dumps({"metadata": {"analysis_date": "2026-04-26"}}, ensure_ascii=False), encoding="utf-8")
    gap_path.write_text(json.dumps({"pending_tasks": [], "manual_required": []}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(stage4, "generate_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        stage4,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "market_data": str(market_path),
                "pring_result": str(pring_path),
                "output": str(output_path),
                "gap_monitor": str(gap_path),
            },
        )(),
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()
    assert "Pring结果日期" in str(exc.value)
```

If `tests/test_stage4_docs.py` does not already import `json` or `pytest`, add:

```python
import json
import pytest
```

- [ ] **Step 2: Run Stage4 tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_stage4_docs.py
```

Expected: FAIL for the new tests because Stage4 does not recalculate unified quality state and does not check Pring date.

- [ ] **Step 3: Implement Stage4 preflight helper**

In `scripts/stage4_report_generator.py`, add imports:

```python
from typing import Any, Dict, Optional
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state
from datasource.utils.policy_rules import load_policy_rules
```

Replace the existing `from typing import Optional` import with the expanded import above.

Add helper functions before `main()`:

```python
def _market_date(payload: Dict[str, Any]) -> Optional[str]:
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    value = metadata.get("date") or metadata.get("end_date") or metadata.get("start_date")
    return str(value) if value else None


def _assert_stage4_quality_gate(market_payload: Dict[str, Any]) -> None:
    state = build_pipeline_quality_state(
        market_payload,
        policy_rules=load_policy_rules(),
        stage="stage4",
        allow_estimated=True,
    )
    blockers = state.get("quality_blockers") or []
    if blockers or state["policy_evaluation"].get("block_stage3"):
        details = "; ".join(
            f"{row.get('category')}.{row.get('key')}:{row.get('reason')}"
            for row in blockers
            if isinstance(row, dict)
        )
        raise RuntimeError(f"Stage4 质量门阻断: {details}")


def _assert_pring_matches_market(market_payload: Dict[str, Any], pring_payload: Dict[str, Any]) -> None:
    market_date = _market_date(market_payload)
    pring_date = (pring_payload.get("metadata") or {}).get("analysis_date")
    if market_date and pring_date and str(market_date) != str(pring_date):
        raise RuntimeError(f"Pring结果日期与market data不一致: market={market_date}, pring={pring_date}")
```

- [ ] **Step 4: Use the Stage4 helper in `main()`**

Replace:

```python
    # ai_websearch_enhanced 校验
    meta = json.load(market_path.open("r", encoding="utf-8")).get("metadata", {})
    if not meta.get("ai_websearch_enhanced"):
        raise RuntimeError("metadata.ai_websearch_enhanced 未设置，Stage4 已阻断。请先完成 Stage2。")
```

with:

```python
    market_payload = json.load(market_path.open("r", encoding="utf-8"))
    pring_payload = json.load(pring_path.open("r", encoding="utf-8"))
    meta = market_payload.get("metadata", {})
    if not meta.get("ai_websearch_enhanced"):
        raise RuntimeError("metadata.ai_websearch_enhanced 未设置，Stage4 已阻断。请先完成 Stage2。")
    _assert_stage4_quality_gate(market_payload)
    _assert_pring_matches_market(market_payload, pring_payload)
```

- [ ] **Step 5: Run Stage4 focused tests**

Run:

```bash
python -m pytest -q tests/test_stage4_docs.py tests/test_pipeline_quality_state.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add scripts/stage4_report_generator.py tests/test_stage4_docs.py
git commit -m "feat: gate stage4 with unified quality state"
```

---

### Task 6: Update Commodity Report Window Header

**Files:**
- Modify: `src/datasource/generators/simple_report.py`
- Modify: `tests/test_simple_report_integration.py`

- [ ] **Step 1: Add failing report test**

Append to `tests/test_simple_report_integration.py`:

```python
def test_commodity_report_uses_120d_header_when_ytd_missing(tmp_path: Path):
    market = _base_market()
    market["commodities"] = [
        {
            "symbol": "GC=F",
            "name": "COMEX黄金",
            "current_price": 3450.0,
            "unit": "$/oz",
            "daily_change": None,
            "change_120d": 12.3,
            "change_120d_basis": "trend_history",
            "trend": "上行",
            "source": "websearch_manual(https://example.com/gold)",
            "source_url": "https://example.com/gold",
        }
    ]
    pring = {
        "final_stage": "第Ⅲ阶段",
        "confidence": 0.61,
        "recommendation": "中性",
        "layer_1_inventory_cycle": {},
        "layer_2_monetary_cycle": {},
        "layer_3_pring_final": {},
        "metadata": {"analysis_method": "Pring V4.0", "min_completeness": 0.8},
        "pending_websearch": [],
        "fallback_used": False,
    }
    m = tmp_path / "m.json"
    p = tmp_path / "p.json"
    out = tmp_path / "o.md"
    _write_json(m, market)
    _write_json(p, pring)

    generate_report(m, p, out)

    text = out.read_text(encoding="utf-8")
    assert "| 品种 | 最新报价 | 日涨跌 | 近120日变化 | 趋势方向 |" in text
    assert "| COMEX黄金 | 3450.00 $/oz | N/A（待 WebSearch） | +12.30% | 上行 |" in text
    assert "年内涨跌" not in text
```

- [ ] **Step 2: Run the report test and verify failure**

Run:

```bash
python -m pytest -q tests/test_simple_report_integration.py::test_commodity_report_uses_120d_header_when_ytd_missing
```

Expected: FAIL because the header still says `年内涨跌` and the value is read from `ytd_change`.

- [ ] **Step 3: Add commodity window selector**

In `src/datasource/generators/simple_report.py`, before the commodity report string, add:

```python
    commodity_uses_120d = any(
        isinstance(comm, dict)
        and comm.get("ytd_change") is None
        and comm.get("change_120d") is not None
        for comm in commodities
    )
    commodity_window_header = "近120日变化" if commodity_uses_120d else "年内涨跌"
```

Replace the commodity table header:

```python
| 品种 | 最新报价 | 日涨跌 | 年内涨跌 | 趋势方向 |
```

with an f-string block:

```python
    report += f"""

---

## 三、商品与黄金

| 品种 | 最新报价 | 日涨跌 | {commodity_window_header} | 趋势方向 |
|------|----------|--------|----------|----------|
"""
```

- [ ] **Step 4: Render `change_120d` when `ytd_change` is absent**

Replace:

```python
        ytd_change = _fmt_change_cell(
            comm.get("ytd_change"),
            digits=2,
            suffix="%",
            low_confidence=low_confidence,
        )
```

with:

```python
        window_value = comm.get("ytd_change")
        if window_value is None and commodity_uses_120d:
            window_value = comm.get("change_120d")
        ytd_change = _fmt_change_cell(
            window_value,
            digits=2,
            suffix="%",
            low_confidence=low_confidence,
        )
```

- [ ] **Step 5: Run report tests**

Run:

```bash
python -m pytest -q tests/test_simple_report_integration.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add src/datasource/generators/simple_report.py tests/test_simple_report_integration.py
git commit -m "fix: label commodity 120d window in reports"
```

---

### Task 7: Add Replay Coverage For Stage2.5 -> Stage3 -> Stage4

**Files:**
- Modify: `tests/test_stage25_contract_replay.py`

- [ ] **Step 1: Add replay test**

Append to `tests/test_stage25_contract_replay.py`:

```python
def test_stage25_outputs_are_accepted_by_unified_quality_state(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    market_path = tmp_path / "market_data_stage2.json"
    manual_path = tmp_path / "websearch_results_manual.json"
    output_path = tmp_path / "market_data_complete.json"
    gap_path = tmp_path / "data" / "runs" / "20260427" / "gap_monitor.json"
    market_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "date": "2026-04-27",
                    "data_completeness": 0.8,
                    "ai_websearch_enhanced": False,
                    "missing_items": {"macro_indicators": [{"key": "industrial"}]},
                },
                "missing_items": ["industrial"],
                "macro_indicators": {
                    "industrial": {
                        "indicator_name": "工业增加值",
                        "current_value": None,
                        "previous_value": None,
                        "change_rate": None,
                        "unit": "%",
                        "source": "占位",
                    }
                },
                "monetary_policy": {},
                "fund_flow": {
                    "northbound": {"type": "northbound", "recent_5d": None, "total_120d": None, "source": "占位"}
                },
                "commodities": [
                    {"symbol": "GC=F", "name": "COMEX黄金", "current_price": None, "source": "占位"}
                ],
                "forex": [],
                "bonds": [],
                "stock_indices": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "macro_indicators": {
                    "industrial": {
                        "indicator_name": "工业增加值",
                        "current_value": 5.2,
                        "previous_value": 5.0,
                        "change_rate": 4.0,
                        "unit": "%",
                        "source": "国家统计局 https://example.com/industrial",
                        "source_url": "https://example.com/industrial",
                    }
                },
                "fund_flow": {
                    "northbound": {
                        "recent_5d": 85.6,
                        "total_120d": 1250.0,
                        "trend": "流入",
                        "source": "东方财富 https://example.com/north",
                        "source_url": "https://example.com/north",
                    }
                },
                "commodities": [
                    {
                        "symbol": "GC=F",
                        "name": "COMEX黄金",
                        "current_price": 3450.5,
                        "unit": "$/oz",
                        "source": "manual https://example.com/gold",
                        "source_url": "https://example.com/gold",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        backfill_trend=False,
        gap_monitor_path=gap_path,
        disable_trend_history_write=True,
    )

    from datasource.utils.pipeline_quality_state import build_pipeline_quality_state

    output = json.loads(output_path.read_text(encoding="utf-8"))
    state = build_pipeline_quality_state(output, stage="stage3", allow_estimated=False)
    gap = json.loads(gap_path.read_text(encoding="utf-8"))

    assert state["quality_blockers"] == []
    assert state["manual_required"] == []
    assert gap["manual_required"] == []
    assert output["metadata"]["ai_websearch_enhanced"] is True
```

- [ ] **Step 2: Run replay tests**

Run:

```bash
python -m pytest -q tests/test_stage25_contract_replay.py tests/test_pipeline_quality_state.py
```

Expected: PASS.

- [ ] **Step 3: Commit Task 7**

```bash
git add tests/test_stage25_contract_replay.py
git commit -m "test: replay unified quality state after stage25"
```

---

### Task 8: Final Verification

**Files:**
- No new files unless prior tasks exposed focused fixes.

- [ ] **Step 1: Run focused quality-state suite**

Run:

```bash
python -m pytest -q tests/test_pipeline_quality_state.py tests/test_websearch_injector.py tests/test_stage25_contract_replay.py tests/test_stage3_guard.py tests/test_stage4_docs.py tests/test_simple_report_integration.py tests/test_stage1_data_collector.py
```

Expected: PASS.

- [ ] **Step 2: Run existing smoke suite used during investigation**

Run:

```bash
python -m pytest -q tests/test_stage3_guard.py tests/test_missing_items_compat.py tests/test_stage25_contract_replay.py
```

Expected: PASS.

- [ ] **Step 3: Run syntax check**

Run:

```bash
python -m py_compile src/datasource/utils/pipeline_quality_state.py scripts/stage2_5_injector.py scripts/stage3_pring_analyzer.py scripts/stage4_report_generator.py scripts/stage1_data_collector.py src/datasource/generators/simple_report.py
```

Expected: exit code 0.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git status --short
git log --oneline -8
```

Expected: working tree clean after all task commits; recent commits correspond to Tasks 1-7.
