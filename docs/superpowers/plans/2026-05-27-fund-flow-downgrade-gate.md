# Fund Flow Downgrade Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a narrow, auditable fund-flow downgrade path so Stage4 can generate a daily report when ETF fund-flow window evidence is unavailable, while keeping ETF marked estimated and preserving all non-fund-flow gates.

**Architecture:** Create one shared gate helper in `src/datasource/utils/pipeline_gate.py`, then have Stage3 and Stage4 consume it for effective quality blockers and gap-monitor filtering. Stage3 keeps the existing compatibility flag, while Stage4 gets a production-named `--allow-fund-flow-downgrade` flag and rejects fallback Pring results by default.

**Tech Stack:** Python 3.7+, argparse, pytest, existing `build_pipeline_quality_state()` quality-state model, existing Stage3/Stage4 scripts.

---

## File Structure

- Create: `src/datasource/utils/pipeline_gate.py`
  - Owns reusable effective-gate filtering, fund-flow downgrade item collection, gap-monitor filtering, and fallback Pring rejection.
- Create: `tests/test_pipeline_gate.py`
  - Tests the helper in isolation using real `build_pipeline_quality_state()` output.
- Modify: `scripts/stage3_pring_analyzer.py`
  - Replaces local fund-flow blocker filtering with shared helper and records downgrade metadata in `pring_result.json`.
- Modify: `tests/test_stage3_guard.py`
  - Adds coverage for Stage3 fund-flow downgrade and downgrade metadata.
- Modify: `scripts/stage4_report_generator.py`
  - Adds `--allow-fund-flow-downgrade`, uses shared helper for quality/gap gates, and rejects fallback Pring results.
- Modify: `tests/test_stage4_docs.py`
  - Adds Stage4 downgrade, non-fund-flow strictness, and fallback-result tests.
- Modify: `tests/test_simple_report_integration.py`
  - Extends existing estimated fund-flow disclosure test with evidence fields.
- Modify: `AGENTS.md`
  - Documents the new production command and the narrow downgrade semantics.
- Modify: `CLAUDE.md`
  - Documents the same operational rule in the quick runbook and pitfalls.

---

### Task 1: Shared Pipeline Gate Helper

**Files:**
- Create: `src/datasource/utils/pipeline_gate.py`
- Create: `tests/test_pipeline_gate.py`

- [ ] **Step 1: Write the failing helper tests**

Create `tests/test_pipeline_gate.py` with this full content:

```python
# -*- coding: utf-8 -*-

import pytest

from datasource.utils.pipeline_gate import (
    assert_no_fallback_pring_result,
    collect_fund_flow_downgraded_items,
    filter_effective_gap_items,
    filter_effective_quality_blockers,
)
from datasource.utils.pipeline_quality_state import build_pipeline_quality_state


def _base_payload():
    return {
        "metadata": {"date": "2026-05-27", "data_completeness": 1.0},
        "missing_items": [],
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }


def _estimated_etf_payload():
    payload = _base_payload()
    payload["fund_flow"] = {
        "etf": {
            "recent_5d": -200.0,
            "total_120d": -1500.0,
            "trend": "流出",
            "source": "websearch_manual",
            "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
            "metric_basis": "news_net_flow",
            "source_tier": "tier3",
            "window_evidence": "news_summary",
            "is_estimated": True,
        }
    }
    return payload


def test_filter_effective_quality_blockers_downgrades_only_fund_flow_estimate():
    payload = _estimated_etf_payload()
    payload["macro_indicators"]["industrial"] = {
        "current_value": 5.2,
        "previous_value": None,
        "change_rate": None,
        "source_url": "https://example.com/industrial",
        "is_estimated": False,
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)

    strict = filter_effective_quality_blockers(state)
    downgraded = filter_effective_quality_blockers(
        state,
        allow_fund_flow_downgrade=True,
    )

    assert {"category": "fund_flow", "key": "etf", "reason": "estimated_not_allowed", "details": {
        "source_tier": "tier3",
        "window_evidence": "news_summary",
        "metric_basis": "news_net_flow",
    }} in strict
    assert {"category": "macro_indicators", "key": "industrial", "reason": "missing_compare_values"} in strict
    assert {"category": "macro_indicators", "key": "industrial", "reason": "missing_compare_values"} in downgraded
    assert not any(
        item["category"] == "fund_flow" and item["key"] == "etf"
        for item in downgraded
    )


def test_filter_effective_quality_blockers_keeps_fund_flow_missing_source_url():
    payload = _base_payload()
    payload["fund_flow"] = {
        "etf": {
            "recent_5d": -200.0,
            "total_120d": -1500.0,
            "trend": "流出",
            "source": "websearch_manual",
            "metric_basis": "news_net_flow",
            "source_tier": "tier3",
            "window_evidence": "news_summary",
            "is_estimated": True,
        }
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)

    downgraded = filter_effective_quality_blockers(
        state,
        allow_fund_flow_downgrade=True,
    )

    assert {"category": "fund_flow", "key": "etf", "reason": "missing_source_url"} in downgraded


def test_filter_effective_quality_blockers_downgrades_missing_fund_flow_windows():
    payload = _base_payload()
    payload["fund_flow"] = {
        "etf": {
            "recent_5d": None,
            "total_120d": None,
            "trend": "待核查",
            "source": "websearch_manual",
            "source_url": "https://data.eastmoney.com/etf/",
            "is_estimated": False,
        }
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)

    downgraded = filter_effective_quality_blockers(
        state,
        allow_fund_flow_downgrade=True,
    )

    assert downgraded == []


def test_filter_effective_gap_items_uses_downgraded_quality_state():
    payload = _estimated_etf_payload()
    payload["macro_indicators"]["industrial"] = {
        "current_value": 5.2,
        "previous_value": None,
        "change_rate": None,
        "source_url": "https://example.com/industrial",
        "is_estimated": False,
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)
    gap_items = [
        {"category": "fund_flow", "key": "etf"},
        {"category": "macro_indicators", "key": "industrial"},
    ]

    strict = filter_effective_gap_items(payload, state, gap_items)
    downgraded = filter_effective_gap_items(
        payload,
        state,
        gap_items,
        allow_fund_flow_downgrade=True,
    )

    assert strict == gap_items
    assert downgraded == [{"category": "macro_indicators", "key": "industrial"}]


def test_filter_effective_gap_items_keeps_absent_fund_flow_item():
    payload = _base_payload()
    state = build_pipeline_quality_state(payload, allow_estimated=True)
    gap_items = [{"category": "fund_flow", "key": "etf"}]

    unresolved = filter_effective_gap_items(
        payload,
        state,
        gap_items,
        allow_fund_flow_downgrade=True,
    )

    assert unresolved == gap_items


def test_collect_fund_flow_downgraded_items_returns_only_downgradable_items():
    payload = _estimated_etf_payload()
    payload["fund_flow"]["northbound"] = {
        "recent_5d": 12.3,
        "total_120d": 456.7,
        "trend": "流入",
        "source": "websearch_manual",
        "is_estimated": False,
    }
    state = build_pipeline_quality_state(payload, allow_estimated=True)

    items = collect_fund_flow_downgraded_items(state)

    assert items == [
        {
            "category": "fund_flow",
            "key": "etf",
            "reason": "estimated_not_allowed",
            "details": {
                "source_tier": "tier3",
                "window_evidence": "news_summary",
                "metric_basis": "news_net_flow",
            },
        }
    ]


def test_assert_no_fallback_pring_result_blocks_by_default():
    with pytest.raises(RuntimeError) as exc:
        assert_no_fallback_pring_result({"fallback_used": True})

    assert "fallback_used=true" in str(exc.value)


def test_assert_no_fallback_pring_result_can_be_allowed_explicitly():
    assert_no_fallback_pring_result(
        {"fallback_used": True},
        allow_fallback_report=True,
    )
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_pipeline_gate.py
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'datasource.utils.pipeline_gate'`.

- [ ] **Step 3: Implement the shared helper**

Create `src/datasource/utils/pipeline_gate.py` with this full content:

```python
# -*- coding: utf-8 -*-
"""Shared effective quality gates for Stage3/Stage4 report readiness."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple


FUND_FLOW_DOWNGRADE_REASONS = frozenset(
    {
        "fund_flow_window_missing",
        "estimated_not_allowed",
        "missing_or_zero_value",
        "missing_value",
        "placeholder_value",
    }
)


def _is_fund_flow_downgrade_issue(issue: Any) -> bool:
    if not isinstance(issue, dict):
        return False
    return (
        str(issue.get("category") or "").lower() == "fund_flow"
        and str(issue.get("reason") or "") in FUND_FLOW_DOWNGRADE_REASONS
    )


def filter_effective_quality_blockers(
    quality_state: Dict[str, Any],
    *,
    allow_fund_flow_downgrade: bool = False,
) -> List[Dict[str, Any]]:
    blockers = quality_state.get("quality_blockers") or []
    if not isinstance(blockers, list):
        return []
    normalized = [item for item in blockers if isinstance(item, dict)]
    if not allow_fund_flow_downgrade:
        return normalized
    return [
        item
        for item in normalized
        if not _is_fund_flow_downgrade_issue(item)
    ]


def collect_fund_flow_downgraded_items(
    quality_state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    blockers = quality_state.get("quality_blockers") or []
    if not isinstance(blockers, list):
        return []
    return [
        dict(item)
        for item in blockers
        if _is_fund_flow_downgrade_issue(item)
    ]


def filter_effective_gap_items(
    market_payload: Dict[str, Any],
    quality_state: Dict[str, Any],
    gap_items: Any,
    *,
    allow_fund_flow_downgrade: bool = False,
) -> List[Any]:
    if not isinstance(gap_items, list):
        return []

    blocker_pairs = {
        (str(issue.get("category") or "").lower(), str(issue.get("key") or "").lower())
        for issue in filter_effective_quality_blockers(
            quality_state,
            allow_fund_flow_downgrade=allow_fund_flow_downgrade,
        )
        if isinstance(issue, dict)
    }

    unresolved: List[Any] = []
    for item in gap_items:
        matches = _matching_payload_entries(market_payload, item)
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
    if pring_payload.get("fallback_used") is True:
        raise RuntimeError(
            "Stage4 fallback Pring result blocked report generation: fallback_used=true"
        )


def _gap_item_label(item: Any) -> str:
    if isinstance(item, dict):
        for field in ("key", "indicator_key", "symbol", "pair", "task", "type", "name", "field"):
            value = item.get(field)
            if value not in (None, ""):
                return str(value)
        return str(item)
    return str(item)


def _gap_item_category(item: Any) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    category = item.get("category")
    return str(category) if category not in (None, "") else None


def _payload_entries(market_payload: Dict[str, Any]) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for category in ("macro_indicators", "monetary_policy", "fund_flow"):
        rows = market_payload.get(category)
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
        rows = market_payload.get(category)
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


def _matching_payload_entries(
    market_payload: Dict[str, Any],
    gap_item: Any,
) -> List[Tuple[str, str]]:
    label = _gap_item_label(gap_item).strip()
    category = _gap_item_category(gap_item)
    if "." in label and category is None:
        maybe_category, maybe_key = label.split(".", 1)
        if maybe_category and maybe_key:
            category = maybe_category
            label = maybe_key
    label_norm = label.lower()
    category_norm = category.lower() if category else None

    matches: List[Tuple[str, str]] = []
    for entry_category, entry_key in _payload_entries(market_payload):
        if category_norm and entry_category.lower() != category_norm:
            continue
        if entry_key.lower() == label_norm:
            matches.append((entry_category, entry_key))
    return matches
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_pipeline_gate.py
```

Expected: PASS for all tests in `tests/test_pipeline_gate.py`.

- [ ] **Step 5: Commit the shared helper**

Run:

```bash
git add src/datasource/utils/pipeline_gate.py tests/test_pipeline_gate.py
git commit -m "feat: add shared pipeline gate helper"
```

Expected: commit succeeds and includes only the helper and its tests.

---

### Task 2: Stage3 Uses Shared Fund-Flow Downgrade Gate

**Files:**
- Modify: `scripts/stage3_pring_analyzer.py`
- Modify: `tests/test_stage3_guard.py`

- [ ] **Step 1: Add failing Stage3 guard tests**

Append these tests to `tests/test_stage3_guard.py`:

```python
def test_require_data_completeness_skips_estimated_fund_flow_when_requested():
    payload = {
        "metadata": {"data_completeness": 0.95},
        "missing_items": [],
        "fund_flow": {
            "etf": {
                "recent_5d": -50.0,
                "total_120d": -9000.0,
                "trend": "流出",
                "source": "websearch_manual",
                "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
                "metric_basis": "news_net_flow",
                "source_tier": "tier3",
                "window_evidence": "news_summary",
                "is_estimated": True,
            }
        },
    }

    s3._require_data_completeness(
        payload,
        0.8,
        allow_estimated=True,
        skip_fund_flow_check=True,
    )


def test_run_analysis_records_fund_flow_downgrade_metadata(tmp_path: Path, monkeypatch):
    market_payload = {
        "metadata": {
            "date": "2026-05-27",
            "data_completeness": 1.0,
            "ai_websearch_enhanced": True,
        },
        "missing_items": [],
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {
            "etf": {
                "recent_5d": -200.0,
                "total_120d": -1500.0,
                "trend": "流出",
                "source": "websearch_manual",
                "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
                "metric_basis": "news_net_flow",
                "source_tier": "tier3",
                "window_evidence": "news_summary",
                "is_estimated": True,
            }
        },
    }
    run_dir = tmp_path / "data" / "runs" / "20260527"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "gap_monitor.json").write_text(
        json.dumps(
            {
                "manual_required": [{"category": "fund_flow", "key": "etf"}],
                "pending_tasks": [{"category": "fund_flow", "key": "etf"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    market_path = tmp_path / "market.json"
    output_path = tmp_path / "pring.json"
    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")

    class DummyContract:
        def __init__(self, **payload):
            self.metadata = payload.get("metadata", {})
            self.macro_indicators = payload.get("macro_indicators", {})
            self.monetary_policy = payload.get("monetary_policy", {})

    class DummyAnalyzer:
        def __init__(self, *args, **kwargs):
            pass

        async def analyze_pring_stage(self, days):
            return {"stage": "Expansion", "confidence": 0.9}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(s3, "MarketDataContract", DummyContract)
    monkeypatch.setattr(s3, "PringAnalyzer", DummyAnalyzer)
    monkeypatch.setattr(s3, "get_manager", lambda: object())

    result = asyncio.run(
        s3._run_analysis(
            market_path=market_path,
            output_path=output_path,
            allow_estimated=True,
            skip_fund_flow_check=True,
            skip_gap_check=False,
            allow_fallback=False,
        )
    )

    downgraded = result["metadata"]["fund_flow_downgraded_items"]
    assert downgraded == [
        {
            "category": "fund_flow",
            "key": "etf",
            "reason": "estimated_not_allowed",
            "details": {
                "source_tier": "tier3",
                "window_evidence": "news_summary",
                "metric_basis": "news_net_flow",
            },
        }
    ]
    warning_codes = [
        row.get("code")
        for row in result["metadata"].get("non_blocking_warnings", [])
    ]
    assert "fund_flow_downgraded" in warning_codes
    assert output_path.exists()
```

- [ ] **Step 2: Run the Stage3 tests to verify they fail**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage3_guard.py::test_require_data_completeness_skips_estimated_fund_flow_when_requested \
  tests/test_stage3_guard.py::test_run_analysis_records_fund_flow_downgrade_metadata
```

Expected: first test fails because Stage3 still keeps local skip reasons that omit fund-flow `estimated_not_allowed`; second test fails because downgrade metadata is not written.

- [ ] **Step 3: Import the shared helper in Stage3**

Modify the imports near the existing `build_pipeline_quality_state` import in `scripts/stage3_pring_analyzer.py`:

```python
from datasource.utils.pipeline_gate import (
    collect_fund_flow_downgraded_items,
    filter_effective_quality_blockers,
)
```

Remove the local `FUND_FLOW_SKIP_REASONS` constant and the local `_filtered_quality_blockers()` function from `scripts/stage3_pring_analyzer.py`.

- [ ] **Step 4: Replace Stage3 quality blocker filtering**

In `_require_data_completeness()`, replace the local-filter call with:

```python
    quality_blockers = filter_effective_quality_blockers(
        quality_state,
        allow_fund_flow_downgrade=skip_fund_flow_check,
    )
```

In `_run_analysis()`, replace the local-filter call that builds `live_quality_blocker_keys` with:

```python
    live_quality_blocker_keys = _quality_blocker_keys(
        filter_effective_quality_blockers(
            live_quality_state,
            allow_fund_flow_downgrade=skip_fund_flow_check,
        )
    )
    fund_flow_downgraded_items = (
        collect_fund_flow_downgraded_items(live_quality_state)
        if skip_fund_flow_check
        else []
    )
```

- [ ] **Step 5: Record Stage3 downgrade metadata and warning**

After `pring_result["metadata"].update({...})` and before `non_blocking_warnings` is copied into `pring_result`, add:

```python
    if fund_flow_downgraded_items:
        pring_result["metadata"]["fund_flow_downgraded_items"] = fund_flow_downgraded_items
        _append_non_blocking_warning(
            market_payload,
            {
                "level": "warning",
                "code": "fund_flow_downgraded",
                "key": "*",
                "message": (
                    "fund_flow blockers downgraded for report generation: "
                    + ", ".join(
                        sorted(
                            {
                                f"{item.get('category')}.{item.get('key')}:{item.get('reason')}"
                                for item in fund_flow_downgraded_items
                            }
                        )
                    )
                ),
            },
        )
```

- [ ] **Step 6: Run the Stage3 tests to verify they pass**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage3_guard.py::test_require_data_completeness_does_not_skip_fund_flow_missing_source_url \
  tests/test_stage3_guard.py::test_require_data_completeness_blocks_estimated_fund_flow_even_with_allow_estimated \
  tests/test_stage3_guard.py::test_require_data_completeness_skips_estimated_fund_flow_when_requested \
  tests/test_stage3_guard.py::test_run_analysis_records_fund_flow_downgrade_metadata
```

Expected: all selected tests pass. The first two prove strict behavior remains when the downgrade is absent or when source URL is missing.

- [ ] **Step 7: Commit the Stage3 adapter**

Run:

```bash
git add scripts/stage3_pring_analyzer.py tests/test_stage3_guard.py
git commit -m "feat: route stage3 fund flow downgrade through shared gate"
```

Expected: commit succeeds and includes only Stage3 changes and Stage3 tests.

---

### Task 3: Stage4 Production Downgrade Flag

**Files:**
- Modify: `scripts/stage4_report_generator.py`
- Modify: `tests/test_stage4_docs.py`

- [ ] **Step 1: Add failing Stage4 tests**

Append these tests to `tests/test_stage4_docs.py`:

```python
def _write_stage4_payloads(tmp_path, *, market_extra, pring_extra=None, gap_payload=None):
    data_dir = tmp_path / "data" / "runs" / "20260527"
    reports_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    reports_dir.mkdir()
    market_path = data_dir / "market_data_complete.json"
    pring_path = data_dir / "pring_result.json"
    gap_path = data_dir / "gap_monitor.json"
    output_path = reports_dir / "out.md"

    market_payload = {
        "metadata": {"ai_websearch_enhanced": True, "date": "2026-05-27"},
        "macro_indicators": {},
        "monetary_policy": {},
        "bonds": [],
        "forex": [],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
    }
    market_payload.update(market_extra)
    pring_payload = {"metadata": {"analysis_date": "2026-05-27"}, "fallback_used": False}
    if pring_extra:
        pring_payload.update(pring_extra)
    if gap_payload is None:
        gap_payload = {"pending_tasks": [], "manual_required": []}

    market_path.write_text(json.dumps(market_payload, ensure_ascii=False), encoding="utf-8")
    pring_path.write_text(json.dumps(pring_payload, ensure_ascii=False), encoding="utf-8")
    gap_path.write_text(json.dumps(gap_payload, ensure_ascii=False), encoding="utf-8")
    return market_path, pring_path, output_path


def _estimated_etf_market_extra():
    return {
        "fund_flow": {
            "etf": {
                "recent_5d": -200.0,
                "total_120d": -1500.0,
                "trend": "流出",
                "source": "websearch_manual",
                "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
                "metric_basis": "news_net_flow",
                "source_tier": "tier3",
                "window_evidence": "news_summary",
                "is_estimated": True,
            }
        }
    }


def test_stage4_blocks_estimated_fund_flow_without_downgrade_flag(tmp_path, monkeypatch):
    market_path, pring_path, output_path = _write_stage4_payloads(
        tmp_path,
        market_extra=_estimated_etf_market_extra(),
        gap_payload={"pending_tasks": [], "manual_required": []},
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
            str(output_path),
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    message = str(exc.value)
    assert "fund_flow.etf" in message
    assert "estimated_not_allowed" in message


def test_stage4_allows_estimated_fund_flow_with_downgrade_flag(tmp_path, monkeypatch):
    market_path, pring_path, output_path = _write_stage4_payloads(
        tmp_path,
        market_extra=_estimated_etf_market_extra(),
        gap_payload={
            "pending_tasks": [{"category": "fund_flow", "key": "etf"}],
            "manual_required": [{"category": "fund_flow", "key": "etf"}],
        },
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
            "--allow-fund-flow-downgrade",
        ],
    )

    stage4.main()

    assert called == [(market_path, pring_path, output_path)]
    market_payload = json.loads(market_path.read_text(encoding="utf-8"))
    assert market_payload["fund_flow"]["etf"]["is_estimated"] is True


def test_stage4_downgrade_flag_still_blocks_non_fund_flow_quality_issue(tmp_path, monkeypatch):
    market_extra = _estimated_etf_market_extra()
    market_extra["macro_indicators"] = {
        "industrial": {
            "current_value": 5.2,
            "previous_value": None,
            "change_rate": None,
            "source_url": "https://example.com/industrial",
            "is_estimated": False,
        }
    }
    market_path, pring_path, output_path = _write_stage4_payloads(
        tmp_path,
        market_extra=market_extra,
        gap_payload={
            "pending_tasks": [
                {"category": "fund_flow", "key": "etf"},
                {"category": "macro_indicators", "key": "industrial"},
            ],
            "manual_required": [],
        },
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
            str(output_path),
            "--allow-fund-flow-downgrade",
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    message = str(exc.value)
    assert "macro_indicators.industrial" in message
    assert "missing_compare_values" in message


def test_stage4_rejects_fallback_pring_result_by_default(tmp_path, monkeypatch):
    market_path, pring_path, output_path = _write_stage4_payloads(
        tmp_path,
        market_extra={},
        pring_extra={"fallback_used": True},
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
            str(output_path),
        ],
    )

    with pytest.raises(RuntimeError) as exc:
        stage4.main()

    assert "fallback_used=true" in str(exc.value)
```

- [ ] **Step 2: Run the Stage4 tests to verify they fail**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage4_docs.py::test_stage4_blocks_estimated_fund_flow_without_downgrade_flag \
  tests/test_stage4_docs.py::test_stage4_allows_estimated_fund_flow_with_downgrade_flag \
  tests/test_stage4_docs.py::test_stage4_downgrade_flag_still_blocks_non_fund_flow_quality_issue \
  tests/test_stage4_docs.py::test_stage4_rejects_fallback_pring_result_by_default
```

Expected: at least the downgrade-flag test fails because `--allow-fund-flow-downgrade` is not recognized; the fallback test fails because Stage4 does not reject fallback Pring results yet.

- [ ] **Step 3: Import shared helpers in Stage4**

Modify the imports in `scripts/stage4_report_generator.py`:

```python
from datasource.utils.pipeline_gate import (
    assert_no_fallback_pring_result,
    filter_effective_gap_items,
    filter_effective_quality_blockers,
)
```

- [ ] **Step 4: Add the Stage4 CLI flag**

In `parse_args()`, after the `--gap-monitor` argument, add:

```python
    parser.add_argument(
        "--allow-fund-flow-downgrade",
        action="store_true",
        help="允许仅对 fund_flow 窗口/估算阻断做正式降级，其他质量阻断仍失败",
    )
```

- [ ] **Step 5: Use shared quality filtering in Stage4**

Change `_assert_stage4_quality_gate()` to accept the downgrade flag:

```python
def _assert_stage4_quality_gate(
    market_payload: Dict[str, Any],
    *,
    allow_fund_flow_downgrade: bool = False,
) -> None:
    quality_state = build_pipeline_quality_state(
        market_payload,
        stage="stage4",
        allow_estimated=True,
    )
    quality_blockers = filter_effective_quality_blockers(
        quality_state,
        allow_fund_flow_downgrade=allow_fund_flow_downgrade,
    )
    policy_blocked = bool(quality_blockers)

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

- [ ] **Step 6: Use shared gap filtering and fallback rejection in Stage4 main**

In `main()`, replace the two `_unresolved_gap_items(...)` calls with:

```python
        pending = filter_effective_gap_items(
            market_payload,
            quality_state,
            pending,
            allow_fund_flow_downgrade=args.allow_fund_flow_downgrade,
        )
        manual = filter_effective_gap_items(
            market_payload,
            quality_state,
            manual,
            allow_fund_flow_downgrade=args.allow_fund_flow_downgrade,
        )
```

After `metadata.ai_websearch_enhanced` is checked and before `_assert_stage4_quality_gate(...)`, add:

```python
    assert_no_fallback_pring_result(pring_payload)
```

Change the Stage4 quality call to:

```python
    _assert_stage4_quality_gate(
        market_payload,
        allow_fund_flow_downgrade=args.allow_fund_flow_downgrade,
    )
```

- [ ] **Step 7: Run the Stage4 tests to verify they pass**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage4_docs.py::test_stage4_blocks_estimated_fund_flow_without_downgrade_flag \
  tests/test_stage4_docs.py::test_stage4_allows_estimated_fund_flow_with_downgrade_flag \
  tests/test_stage4_docs.py::test_stage4_downgrade_flag_still_blocks_non_fund_flow_quality_issue \
  tests/test_stage4_docs.py::test_stage4_rejects_fallback_pring_result_by_default \
  tests/test_stage4_docs.py::test_stage4_ignores_stale_gap_when_live_quality_state_is_clean
```

Expected: all selected Stage4 tests pass.

- [ ] **Step 8: Commit the Stage4 adapter**

Run:

```bash
git add scripts/stage4_report_generator.py tests/test_stage4_docs.py
git commit -m "feat: allow stage4 fund flow downgrade"
```

Expected: commit succeeds and includes only Stage4 changes and Stage4 tests.

---

### Task 4: Report Disclosure Regression

**Files:**
- Modify: `tests/test_simple_report_integration.py`

- [ ] **Step 1: Strengthen the estimated fund-flow report test**

In `tests/test_simple_report_integration.py`, update `test_report_estimated_appendix_includes_fund_flow_etf()` so the ETF entry includes explicit evidence fields:

```python
    market["fund_flow"] = {
        "etf": {
            "recent_5d": 85.6,
            "total_120d": 1250.0,
            "trend": "流入",
            "source": "fallback estimate",
            "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
            "note": "estimated fallback pending official source; metric_basis=news_net_flow; window_evidence=news_summary",
            "metric_basis": "news_net_flow",
            "window_evidence": "news_summary",
            "estimation_method": "fund_flow_manual_window_not_direct",
            "is_estimated": True,
        }
    }
```

Keep these assertions and add the two evidence assertions:

```python
    assert "估计值提醒" in text
    assert "资金流:ETF资金流" in text
    assert "news_net_flow" in text
    assert "news_summary" in text
    assert "| ETF资金流 | 85.60(估) | 1250.00(估) | 流入 | fallback estimate | estimated fallback pending official source; metric_basis=news_net_flow; window_evidence=news_summary |" in text
```

- [ ] **Step 2: Run the report disclosure test**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_simple_report_integration.py::test_report_estimated_appendix_includes_fund_flow_etf
```

Expected: PASS.

- [ ] **Step 3: Commit the report regression test**

Run:

```bash
git add tests/test_simple_report_integration.py
git commit -m "test: preserve fund flow downgrade disclosure"
```

Expected: commit succeeds and includes only the report disclosure test.

---

### Task 5: Runbook Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the Stage3/Stage4 commands in `AGENTS.md`**

In `AGENTS.md`, update the Stage3 command block to include the existing fund-flow downgrade compatibility flag:

```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated \
  --skip-fund-flow-check
```

Update the Stage4 command block to include:

```bash
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md" \
  --allow-fund-flow-downgrade
```

- [ ] **Step 2: Add the narrow downgrade rule to `AGENTS.md`**

Add this bullet near the fund-flow gate rules:

```markdown
- `--allow-fund-flow-downgrade` 仅用于 Stage4 正式报告中的 fund_flow 降级：它只过滤 fund_flow 的窗口缺失和估算阻断，不会修改 `market_data_complete.json`，也不得把 ETF 新闻外推、季度/年度摘要、单日外推、`news_net_flow` 或 `estimated_net_flow` 改成 `is_estimated=false`。非 fund_flow 阻断、缺 source_url、fallback Pring、日期不匹配仍必须失败。
```

- [ ] **Step 3: Update `CLAUDE.md` quick runbook**

In the Stage4 command section of `CLAUDE.md`, include:

```bash
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md" \
  --allow-fund-flow-downgrade
```

Add this operational pitfall:

```markdown
**fund_flow 正式降级**: ETF 等 fund_flow 窗口不可验证时，Stage3 可用 `--skip-fund-flow-check`，Stage4 用 `--allow-fund-flow-downgrade`。该路径只允许报告继续生成，不改变数据真实性；ETF 仍保持 `is_estimated=true` 并进入估算披露。缺 `source_url`、非 fund_flow 阻断、`fallback_used=true`、日期不匹配仍会阻断。
```

- [ ] **Step 4: Run documentation checks**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_stage4_docs.py::test_claude_stage4_command_uses_named_args
```

Expected: PASS.

- [ ] **Step 5: Commit the docs**

Run:

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: document fund flow downgrade workflow"
```

Expected: commit succeeds and includes only runbook documentation.

---

### Task 6: Final Verification

**Files:**
- Verify: all files changed in Tasks 1-5

- [ ] **Step 1: Run focused tests**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_pipeline_gate.py \
  tests/test_stage3_guard.py \
  tests/test_stage4_docs.py \
  tests/test_simple_report_integration.py::test_report_estimated_appendix_includes_fund_flow_etf
```

Expected: all selected tests pass.

- [ ] **Step 2: Run syntax checks**

Run:

```bash
bash run_clean.sh python -m py_compile \
  src/datasource/utils/pipeline_gate.py \
  scripts/stage3_pring_analyzer.py \
  scripts/stage4_report_generator.py
```

Expected: command exits with code 0 and prints no syntax errors.

- [ ] **Step 3: Inspect the diff for scope**

Run:

```bash
git diff --stat HEAD
git diff --name-only HEAD
```

Expected: only these paths are changed after the task commits:

```text
AGENTS.md
CLAUDE.md
scripts/stage3_pring_analyzer.py
scripts/stage4_report_generator.py
src/datasource/utils/pipeline_gate.py
tests/test_pipeline_gate.py
tests/test_stage3_guard.py
tests/test_stage4_docs.py
tests/test_simple_report_integration.py
```

- [ ] **Step 4: Report completion**

Summarize:

```text
- shared helper added
- Stage3 uses shared helper and records downgrade metadata
- Stage4 supports --allow-fund-flow-downgrade and rejects fallback results
- ETF remains estimated in report disclosure
- focused tests and py_compile passed
```
