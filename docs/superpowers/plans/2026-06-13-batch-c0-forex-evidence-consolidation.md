# Batch C0 Forex Evidence Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate duplicated forex evidence predicates and note helpers into shared utility modules while preserving current Stage2 and Stage2.5 behavior byte-for-byte.

**Architecture:** Add `src/datasource/utils/forex_evidence.py` for shared predicate primitives plus two preserved predicate families: Stage2 compare evidence and Stage2.5 daily/120d evidence. Add `src/datasource/utils/note_utils.py` with three intentionally distinct note append semantics. Scripts keep compatibility names as import aliases or `functools.partial` aliases; orchestration/consumer functions stay in place for C1/C4.

**Tech Stack:** Python 3.11 via `bash run_clean.sh python`, pytest, existing scripts under `scripts/`, utilities under `src/datasource/utils/`.

---

## Non-Negotiable Constraints

- Base work starts from local `main` after the spec and execution-plan commits. Production code baseline is C-0.5 merge `7aad7df`; later main commits before the worktree are planning-only docs. Capture `BASE_SHA=$(git rev-parse --short main)` before creating the worktree and use that value in Step 0 checks.
- Do not modify `.claude/settings.local.json`, `.gstack/`, data runs, reports, golden fixtures, or archive/history docs.
- Do not touch these protected runtime areas: `pring_result_contract.py`, `providers/stage2_structured/*`, `utils/yahoo_finance.py`, `mcp_adapter.py`, `mcp_tools.py`.
- Do not move consumers/orchestration in this PR: keep `_scrub_unevidenced_forex_zeroes`, `_copy_forex_compare_fields`, `_should_backfill_forex_*`, `_usable_forex_*`, `_copy_valid_forex_*_change_evidence`, `_is_zero_*`, `_merge_forex_entry`, `_build_forex_entry` in their current scripts except for calls to aliased predicates.
- Do not semantically merge Stage2 and Stage2.5 absence/coerce behavior. Stage2 `_safe_number` remains strict `float(value)`; Stage2.5 `_coerce_float` keeps comma/percent/first-number parsing.
- Do not merge marker constants when values differ. Current audit result: evidence key tuples are equal, marker tuples differ.
- If any command produces a different result than the expected output in this plan, stop and report. Do not rewrite assertions or change semantics to make tests pass.

## File Structure

- Create `src/datasource/utils/forex_evidence.py`
  - Owns shared regex primitives, forex evidence constants, Stage2-specific predicate family, and Stage2.5-specific predicate family.
  - Accepts `is_absence` and `coerce` injections where Stage2 and Stage2.5 semantics differ.
- Create `src/datasource/utils/note_utils.py`
  - Owns three distinct note append functions. They are not equivalent and must not be collapsed.
- Create `tests/test_forex_evidence_characterization.py`
  - Locks existing Stage2 and Stage2.5 behavior before moving code.
  - Continues to pass after scripts switch to shared utilities.
- Modify `scripts/stage2_unified_enhancer.py`
  - Import `functools.partial`.
  - Import forex evidence constants/functions from `datasource.utils.forex_evidence`.
  - Replace local duplicated forex predicate bodies with alias assignments.
  - Import `append_note_text as _append_note`.
  - Replace `_contains_ytd_marker` body with alias assignment.
- Modify `scripts/stage2_5_injector.py`
  - Import `functools.partial`.
  - Import forex evidence constants/functions from `datasource.utils.forex_evidence`.
  - Replace local duplicated forex predicate/copy bodies with alias assignments.
  - Import `append_note_once as _append_note_once` and `append_note_to_entry as _append_note`.
  - Replace `_contains_ytd_marker` body with alias assignment.

## Environment Setup

- [ ] **Step 0.1: Create isolated worktree**

Run from `/mnt/d/cursor/datasource`:

```bash
git status --short
BASE_SHA=$(git rev-parse --short main)
git worktree add .worktrees/codex-batch-c0-forex-evidence -b codex/batch-c0-forex-evidence main
cd .worktrees/codex-batch-c0-forex-evidence
printf '%s\n' "$BASE_SHA"
```

Expected first command may show only main-worktree local items and must not be copied into the new worktree:

```text
M  .claude/settings.local.json
?? .gstack/
```

Expected worktree add tail:

```text
HEAD is now at <BASE_SHA> docs: plan batch c0 forex evidence consolidation
<BASE_SHA>
```

- [ ] **Step 0.2: Verify isolated worktree is clean**

Run:

```bash
git status --short
git branch --show-current
git rev-parse --short HEAD
```

Expected:

```text
codex/batch-c0-forex-evidence
<BASE_SHA recorded in Step 0.1>
```

`git status --short` must print no files. If `.claude/settings.local.json` or `.gstack/` appears inside this worktree, stop and report.

- [ ] **Step 0.3: Baseline targeted verification**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_websearch_injector.py tests/test_stage2_replay_harness.py tests/test_stage25_contract_replay.py
bash run_clean.sh python -m compileall -q scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py src/datasource/utils
```

Expected pytest summary:

```text
210 passed, 3 warnings
```

Expected compileall output: empty output, exit 0.

- [ ] **Step 0.4: Record current constant audit**

Run:

```bash
bash run_clean.sh python - <<'PY'
import scripts.stage2_unified_enhancer as s2
import scripts.stage2_5_injector as s25

pairs = [
    ("daily markers", s2._FOREX_DAILY_EVIDENCE_MARKERS, s25.FOREX_DAILY_CHANGE_SOURCE_MARKERS),
    ("120d markers", s2._FOREX_120D_EVIDENCE_MARKERS, s25.FOREX_120D_CHANGE_SOURCE_MARKERS),
    ("daily keys", s2._FOREX_COMPARE_FIELD_EVIDENCE_KEYS["daily_change"], s25.FOREX_DAILY_CHANGE_EVIDENCE_KEYS),
    ("120d keys", s2._FOREX_COMPARE_FIELD_EVIDENCE_KEYS["change_120d"], s25.FOREX_120D_CHANGE_EVIDENCE_KEYS),
]
for label, left, right in pairs:
    print(label, left == right)
    print("  stage2_only=", sorted(set(left) - set(right)))
    print("  stage25_only=", sorted(set(right) - set(left)))
PY
```

Expected exact output:

```text
daily markers False
  stage2_only= ['change 1d', 'change rate', 'direct daily series', 'direct daily window', 'direct_daily_window', 'previous close', 'previous_close', 'trend history', 'trend history direct window', 'trend history full window']
  stage25_only= ['direct_window']
120d markers False
  stage2_only= ['change rate', 'direct 120d window', 'direct window', 'direct_120d_window', 'trend history', 'trend history direct window', 'trend history full window']
  stage25_only= []
daily keys True
  stage2_only= []
  stage25_only= []
120d keys True
  stage2_only= []
  stage25_only= []
```

If marker equality becomes `True` or evidence key equality becomes `False`, stop and report.

### Task 1: Characterize Current Forex And Note Behavior

**Files:**
- Create: `tests/test_forex_evidence_characterization.py`
- Read-only anchors: `scripts/stage2_unified_enhancer.py`, `scripts/stage2_5_injector.py`

- [ ] **Step 1.1: Add characterization tests**

Create `tests/test_forex_evidence_characterization.py` with exactly this content:

```python
import pytest

import scripts.stage2_5_injector as stage25
import scripts.stage2_unified_enhancer as stage2


@pytest.mark.parametrize(
    "value,stage2_expected,stage25_expected",
    [
        ("", False, True),
        (None, False, True),
        ("N/A", False, True),
        ("no change", False, True),
        ("no change 120d value", True, True),
        ("missing previous value", True, True),
        ("direct_daily_series", False, False),
    ],
)
def test_forex_absence_predicates_keep_stage_specific_semantics(
    value, stage2_expected, stage25_expected
):
    assert stage2._is_forex_absence_text(value) is stage2_expected
    assert stage25._is_forex_daily_change_absence_text(value) is stage25_expected


@pytest.mark.parametrize(
    "value,stage2_expected,stage25_expected",
    [
        ("7.13", 7.13, 7.13),
        ("1,234", None, 1234.0),
        ("7.13%", None, 7.13),
        ("abc 7.13", None, 7.13),
        ("abc", None, None),
        ("", None, None),
        (None, None, None),
    ],
)
def test_forex_number_coercion_keeps_stage_specific_semantics(
    value, stage2_expected, stage25_expected
):
    assert stage2._safe_number(value) == stage2_expected
    assert stage25._coerce_float(value) == stage25_expected


def test_forex_marker_constants_are_not_accidentally_merged():
    assert stage2._FOREX_DAILY_EVIDENCE_MARKERS != stage25.FOREX_DAILY_CHANGE_SOURCE_MARKERS
    assert sorted(
        set(stage2._FOREX_DAILY_EVIDENCE_MARKERS)
        - set(stage25.FOREX_DAILY_CHANGE_SOURCE_MARKERS)
    ) == [
        "change 1d",
        "change rate",
        "direct daily series",
        "direct daily window",
        "direct_daily_window",
        "previous close",
        "previous_close",
        "trend history",
        "trend history direct window",
        "trend history full window",
    ]
    assert sorted(
        set(stage25.FOREX_DAILY_CHANGE_SOURCE_MARKERS)
        - set(stage2._FOREX_DAILY_EVIDENCE_MARKERS)
    ) == ["direct_window"]

    assert stage2._FOREX_120D_EVIDENCE_MARKERS != stage25.FOREX_120D_CHANGE_SOURCE_MARKERS
    assert sorted(
        set(stage2._FOREX_120D_EVIDENCE_MARKERS)
        - set(stage25.FOREX_120D_CHANGE_SOURCE_MARKERS)
    ) == [
        "change rate",
        "direct 120d window",
        "direct window",
        "direct_120d_window",
        "trend history",
        "trend history direct window",
        "trend history full window",
    ]
    assert sorted(
        set(stage25.FOREX_120D_CHANGE_SOURCE_MARKERS)
        - set(stage2._FOREX_120D_EVIDENCE_MARKERS)
    ) == []

    assert (
        stage2._FOREX_COMPARE_FIELD_EVIDENCE_KEYS["daily_change"]
        == stage25.FOREX_DAILY_CHANGE_EVIDENCE_KEYS
    )
    assert (
        stage2._FOREX_COMPARE_FIELD_EVIDENCE_KEYS["change_120d"]
        == stage25.FOREX_120D_CHANGE_EVIDENCE_KEYS
    )


@pytest.mark.parametrize(
    "extraction,field,expected",
    [
        ({"daily_change": 0.0, "daily_change_basis": "direct_daily_series"}, "daily_change", True),
        ({"daily_change": 0.0, "daily_change_basis": "failed_trend_history"}, "daily_change", False),
        ({"daily_change": 0.0, "note": "no change"}, "daily_change", True),
        ({"daily_change": 0.25}, "daily_change", True),
        ({"change_120d": 0.0, "daily_change_basis": "direct_daily_series"}, "change_120d", False),
        ({"change_120d": 0.0, "change_120d_window_evidence": "direct_120d_window"}, "change_120d", True),
        ({"change_120d": 0.0, "note": "no change 120d value"}, "change_120d", False),
    ],
)
def test_stage2_compare_evidence_cases(extraction, field, expected):
    assert stage2._has_forex_compare_evidence(extraction, field) is expected


def test_stage25_daily_evidence_copy_uses_stage25_float_coercion():
    target = {}
    source = {
        "daily_change_basis": "direct_daily_series",
        "daily_change_source_url": "https://example.com/fx",
        "daily_change_base_date": "2026-06-02",
        "daily_change_base_price": "7.13%",
    }

    stage25._copy_valid_forex_daily_change_evidence(target, source)

    assert target == {
        "daily_change_basis": "direct_daily_series",
        "daily_change_source_url": "https://example.com/fx",
        "daily_change_base_date": "2026-06-02",
        "daily_change_base_price": 7.13,
    }
    assert stage25._has_forex_daily_change_evidence(target) is True


def test_stage25_invalid_daily_evidence_is_not_preserved():
    target = {
        "daily_change_basis": "direct_daily_series",
        "daily_change_base_date": "2026-06-02",
    }
    source = {
        "daily_change_basis": "failed_trend_history",
        "daily_change_source_url": "N/A",
        "daily_change_base_date": "N/A",
        "daily_change_base_price": "N/A",
    }

    stage25._copy_valid_forex_daily_change_evidence(target, source)

    assert target == {}
    assert stage25._has_forex_daily_change_evidence(target) is False


def test_note_helper_semantics_are_distinct():
    assert stage2._append_note(None, "tail") == "tail"
    assert stage2._append_note("base", "tail") == "base tail"
    assert stage2._append_note("base tail", "tail") == "base tail"
    assert stage2._append_note("base", "") == "base"
    assert stage2._append_note(None, "") is None

    assert stage25._append_note_once("base", "tail") == "base；tail"
    assert stage25._append_note_once("base；tail", "tail") == "base；tail"

    entry = {"note": "base"}
    stage25._append_note(entry, "tail")
    stage25._append_note(entry, "tail")
    assert entry["note"] == "base；tail；tail"


def test_ytd_marker_script_compatibility_names_are_shared():
    assert stage2._contains_ytd_marker("1-2月累计同比增长") is True
    assert stage25._contains_ytd_marker("1-2月累计同比增长") is True
    assert stage2._contains_ytd_marker("同比增长") is False
    assert stage25._contains_ytd_marker("同比增长") is False
```

- [ ] **Step 1.2: Run characterization tests before moving code**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_forex_evidence_characterization.py
```

Expected:

```text
27 passed
```

- [ ] **Step 1.3: Commit characterization tests**

Run:

```bash
git add tests/test_forex_evidence_characterization.py
git commit -m "test: characterize forex evidence helpers"
```

Expected commit summary:

```text
1 file changed
create mode 100644 tests/test_forex_evidence_characterization.py
```

### Task 2: Add Shared Utility Modules

**Files:**
- Create: `src/datasource/utils/forex_evidence.py`
- Create: `src/datasource/utils/note_utils.py`
- Test: `tests/test_forex_evidence_characterization.py`

- [ ] **Step 2.1: Create note utility module**

Create `src/datasource/utils/note_utils.py` with exactly this content:

```python
"""Shared note append helpers with intentionally distinct semantics."""

from __future__ import annotations

from typing import Any, Dict, Optional


def append_note_text(note: Optional[str], extra: Optional[str]) -> Optional[str]:
    base = (note or "").strip()
    tail = (extra or "").strip()
    if not tail:
        return base or None
    if not base:
        return tail
    if tail in base:
        return base
    return f"{base} {tail}".strip()


def append_note_once(note: str, addition: str) -> str:
    if not addition:
        return note
    if addition in note:
        return note
    if note:
        return f"{note}；{addition}"
    return addition


def append_note_to_entry(entry: Dict[str, Any], message: str) -> None:
    if not message:
        return
    note = entry.get("note") or ""
    if note:
        note += "；"
    note += message
    entry["note"] = note
```

- [ ] **Step 2.2: Create forex evidence utility module**

Create `src/datasource/utils/forex_evidence.py` with exactly this content:

```python
"""Shared forex evidence predicates.

Stage2 and Stage2.5 use similar names for subtly different semantics. This module
centralizes the mechanics while preserving the two predicate families.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional, Tuple

NumberCoercer = Callable[[Any], Optional[float]]
AbsencePredicate = Callable[[Any], bool]

FOREX_COMPARE_FIELDS = ("daily_change", "change_120d")
FOREX_COMPARE_EVIDENCE_TOKENS = {
    "change_120d": ("120d", "120日", "120-day", "120 day", "direct window"),
    "daily_change": (
        "daily change",
        "day change",
        "previous close",
        "change from previous close",
        "日变化",
        "日变动",
        "日涨跌",
    ),
}
FOREX_COMPARE_TEXT_FIELDS = (
    "metric_basis",
    "change_period",
    "window_evidence",
    "estimation_method",
    "note",
    "source",
    "manual_reason",
    "manual_required_reason",
)
FOREX_COMPARE_FIELD_EVIDENCE_KEYS = {
    "daily_change": (
        "daily_change_basis",
        "daily_change_source",
        "daily_change_source_url",
        "daily_change_window_evidence",
        "daily_change_base_date",
        "daily_change_base_price",
        "base_1d_date",
        "change_1d",
        "change_1d_pct",
        "reason_1d",
        "previous_value",
        "previous_rate",
        "previous_price",
    ),
    "change_120d": (
        "change_120d_basis",
        "change_120d_source",
        "change_120d_source_url",
        "change_120d_window_evidence",
        "change_120d_base_date",
        "change_120d_base_price",
    ),
}
STAGE2_FOREX_DAILY_EVIDENCE_MARKERS = (
    "direct_daily_series",
    "direct daily series",
    "direct_daily_window",
    "direct daily window",
    "trend_history_direct_window",
    "trend history direct window",
    "trend_history_full_window",
    "trend history full window",
    "previous_close",
    "previous close",
    "change_1d",
    "change 1d",
    "change_rate",
    "change rate",
    "trend_history",
    "trend history",
)
STAGE2_FOREX_120D_EVIDENCE_MARKERS = (
    "direct_window",
    "direct window",
    "direct_120d_window",
    "direct 120d window",
    "trend_history_direct_window",
    "trend history direct window",
    "trend_history_full_window",
    "trend history full window",
    "change_rate",
    "change rate",
    "trend_history",
    "trend history",
)
STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS = (
    "direct_daily_series",
    "direct_window",
    "trend_history_direct_window",
    "trend_history_full_window",
    "change_1d",
    "change_rate",
    "trend_history",
)
STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS = (
    "direct_window",
    "trend_history_direct_window",
    "trend_history_full_window",
    "change_rate",
    "trend_history",
)
FOREX_DAILY_CHANGE_EVIDENCE_KEYS = FOREX_COMPARE_FIELD_EVIDENCE_KEYS["daily_change"]
FOREX_120D_CHANGE_EVIDENCE_KEYS = FOREX_COMPARE_FIELD_EVIDENCE_KEYS["change_120d"]


def join_forex_compare_evidence_text(extraction: Dict[str, Any]) -> str:
    return " ".join(str(extraction.get(field) or "") for field in FOREX_COMPARE_TEXT_FIELDS).lower()


def normalize_forex_compare_text(text: Any) -> str:
    return re.sub(r"[_-]+", " ", str(text or "").strip().lower())


def is_stage2_forex_no_change_absence_text(normalized_text: str) -> bool:
    return any(
        re.search(pattern, normalized_text)
        for pattern in (
            r"\bno change\s+(?:from\s+)?(?:120d|120\s+day|120日)\b",
            r"\bno change\s+(?:value|data|window|evidence)\b",
        )
    )


def is_stage2_forex_absence_text(text: Any) -> bool:
    raw = str(text or "").strip().lower()
    normalized = normalize_forex_compare_text(raw)
    if not raw:
        return False
    if is_stage2_forex_no_change_absence_text(normalized):
        return True
    if any(token in normalized for token in ("no change", "unchanged", "无变化", "没有变化")):
        non_absence = normalized
        for token in ("no change", "unchanged", "无变化", "没有变化"):
            non_absence = non_absence.replace(token, "")
        if not any(
            marker in non_absence
            for marker in (
                "missing",
                "without",
                "unavailable",
                "not available",
                "no data",
                "no value",
                "no window",
                "no evidence",
                "deepseek no value",
                "no deepseek key",
                "缺少",
                "缺失",
                "不可得",
                "不可用",
                "未披露",
                "没有数据",
                "没有窗口",
                "没有证据",
                "没有值",
                "无数据",
                "无窗口",
                "无证据",
                "无值",
            )
        ):
            return False
    return any(
        marker in normalized
        for marker in (
            "missing",
            "without",
            "unavailable",
            "not available",
            "no data",
            "no value",
            "no window",
            "no evidence",
            "deepseek no value",
            "no deepseek key",
            "missing previous value",
            "no previous value",
            "failed",
            "failure",
            "error",
            "invalid",
            "缺少",
            "缺失",
            "不可得",
            "不可用",
            "未披露",
            "没有数据",
            "没有窗口",
            "没有证据",
            "没有值",
            "无数据",
            "无窗口",
            "无证据",
            "无值",
            "失败",
        )
    )


def has_stage2_forex_no_change_evidence(text: Any) -> bool:
    normalized = normalize_forex_compare_text(text)
    if is_stage2_forex_no_change_absence_text(normalized):
        return False
    return any(token in normalized for token in ("no change", "unchanged", "无变化", "没有变化"))


def is_stage2_forex_compare_absence_text(text: Any, field: str) -> bool:
    raw = str(text or "").strip()
    normalized = normalize_forex_compare_text(raw)
    if not raw:
        return False
    if has_stage2_forex_no_change_evidence(raw):
        non_absence = normalized
        for token in ("no change", "unchanged", "无变化", "没有变化"):
            non_absence = non_absence.replace(token, "")
        if not is_stage2_forex_absence_text(non_absence):
            return False
    if is_stage2_forex_absence_text(raw):
        if field == "change_120d" and any(
            token in normalized for token in ("missing previous value", "no previous value", "reason=no previous value")
        ):
            return False
        return True
    if field == "daily_change":
        return any(
            marker in normalized
            for marker in (
                "missing previous value",
                "no previous value",
                "reason=no previous value",
                "missing daily change",
                "no daily change",
                "daily change missing",
            )
        )
    if field == "change_120d":
        return any(
            marker in normalized
            for marker in (
                "missing 120d",
                "120d missing",
                "no 120d",
                "120d no",
                "missing 120 day",
                "120 day missing",
                "missing 120日",
                "120日 缺失",
            )
        )
    return False


def is_stage25_forex_daily_change_absence_text(text: Any) -> bool:
    normalized = str(text or "").strip().lower()
    if normalized in {"", "n/a", "na", "-", "--", "unknown", "pending"}:
        return True
    return bool(
        re.search(r"\breason\s*=", normalized)
        or re.search(r"\b(?:missing|no)[_\s-]", normalized)
        or any(
            marker in normalized
            for marker in (
                "deepseek_no_value",
                "missing_previous_value",
                "missing_value",
                "no_previous_value",
                "no_value",
                "failed",
                "failure",
                "error",
                "invalid",
                "unavailable",
                "not_available",
                "not-available",
                "not available",
                "缺失",
                "失败",
            )
        )
    )


def is_valid_forex_source_url(value: Any, *, is_absence: AbsencePredicate) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if is_absence(text):
        return False
    return bool(re.fullmatch(r"https?://\S+", text, flags=re.IGNORECASE))


def is_valid_forex_base_date(value: Any, *, is_absence: AbsencePredicate) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if is_absence(text):
        return False
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{8}|\d{4}-\d{2}", text))


def is_valid_forex_base_price(
    value: Any,
    *,
    is_absence: AbsencePredicate,
    coerce: NumberCoercer,
) -> bool:
    if value is None:
        return False
    if is_absence(str(value)):
        return False
    return coerce(value) is not None


def has_forex_computed_marker(
    value: Any,
    markers: Tuple[str, ...],
    *,
    is_absence: AbsencePredicate,
    reject_daily_prefix: bool = False,
) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if is_absence(text):
        return False
    tokens = set(re.split(r"[^a-z0-9_]+", text))
    negative_prefixes = ("failed", "failure", "error", "invalid", "unavailable")
    for token in tokens:
        if reject_daily_prefix and token.startswith("daily_"):
            continue
        if token.startswith(negative_prefixes):
            continue
        for marker in markers:
            marker_token = marker.replace(" ", "_")
            if token == marker_token or token.endswith(f"_{marker_token}"):
                return True
    return False


def has_stage2_forex_positive_compare_text(evidence_text: str, field: str) -> bool:
    normalized = normalize_forex_compare_text(evidence_text)
    if has_stage2_forex_no_change_evidence(evidence_text):
        return True
    if field == "daily_change":
        tokens = FOREX_COMPARE_EVIDENCE_TOKENS.get(field, ()) + STAGE2_FOREX_DAILY_EVIDENCE_MARKERS
    elif field == "change_120d":
        tokens = FOREX_COMPARE_EVIDENCE_TOKENS.get(field, ()) + STAGE2_FOREX_120D_EVIDENCE_MARKERS
    else:
        tokens = FOREX_COMPARE_EVIDENCE_TOKENS.get(field, ())
    return any(token in evidence_text or token in normalized for token in tokens)


def has_stage2_forex_field_specific_evidence(
    payload: Dict[str, Any],
    field: str,
    *,
    coerce: NumberCoercer,
) -> bool:
    evidence_keys = FOREX_COMPARE_FIELD_EVIDENCE_KEYS.get(field, ())
    for key in evidence_keys:
        value = payload.get(key)
        if value in (None, "", "N/A"):
            continue
        if field == "daily_change":
            if key in {"daily_change_basis", "daily_change_source", "daily_change_window_evidence"}:
                if has_forex_computed_marker(
                    value,
                    STAGE2_FOREX_DAILY_EVIDENCE_MARKERS,
                    is_absence=is_stage2_forex_absence_text,
                ):
                    return True
                continue
            if key == "daily_change_source_url":
                if is_valid_forex_source_url(value, is_absence=is_stage2_forex_absence_text):
                    return True
                continue
            if key in {"daily_change_base_date", "base_1d_date"}:
                if is_valid_forex_base_date(value, is_absence=is_stage2_forex_absence_text):
                    return True
                continue
            if key == "daily_change_base_price" and is_valid_forex_base_price(
                value,
                is_absence=is_stage2_forex_absence_text,
                coerce=coerce,
            ):
                return True
            continue
        if field == "change_120d":
            if key in {"change_120d_basis", "change_120d_source", "change_120d_window_evidence"}:
                if has_forex_computed_marker(
                    value,
                    STAGE2_FOREX_120D_EVIDENCE_MARKERS,
                    is_absence=is_stage2_forex_absence_text,
                    reject_daily_prefix=True,
                ):
                    return True
                continue
            if key == "change_120d_source_url":
                if is_valid_forex_source_url(value, is_absence=is_stage2_forex_absence_text):
                    return True
                continue
            if key == "change_120d_base_date":
                if is_valid_forex_base_date(value, is_absence=is_stage2_forex_absence_text):
                    return True
                continue
            if key == "change_120d_base_price" and is_valid_forex_base_price(
                value,
                is_absence=is_stage2_forex_absence_text,
                coerce=coerce,
            ):
                return True
    return False


def has_stage2_forex_structured_compare_evidence(payload: Dict[str, Any], field: str) -> bool:
    change_period = str(payload.get("change_period") or "").strip().lower()
    window_evidence = str(payload.get("window_evidence") or "").strip().lower()
    metric_basis = str(payload.get("metric_basis") or "").strip().lower()
    if field == "daily_change":
        if change_period in {"daily", "1d", "day", "日频", "日变化"}:
            return True
        return any(
            token in window_evidence or token in metric_basis
            for token in STAGE2_FOREX_DAILY_EVIDENCE_MARKERS
        )
    if field == "change_120d":
        if change_period in {"120d", "120-day", "120 day", "120日"}:
            return True
        return any(
            token in window_evidence or token in metric_basis
            for token in STAGE2_FOREX_120D_EVIDENCE_MARKERS
        )
    return False


def has_stage2_negative_forex_compare_marker(evidence_text: str, field: str) -> bool:
    if is_stage2_forex_compare_absence_text(evidence_text, field):
        return True
    context_tokens = FOREX_COMPARE_EVIDENCE_TOKENS.get(field, ())
    ascii_negative_tokens = (
        "missing",
        "without",
        "unavailable",
        "not available",
        "no data",
        "no value",
        "no window",
        "no evidence",
    )
    chinese_negative_tokens = (
        "缺少",
        "缺失",
        "不可得",
        "不可用",
        "未披露",
        "没有数据",
        "没有窗口",
        "没有证据",
        "没有值",
        "无数据",
        "无窗口",
        "无证据",
        "无值",
    )

    for context_token in context_tokens:
        context_pattern = re.escape(context_token).replace(r"\ ", r"\s+")
        if re.search(
            rf"\bno\b[^.;,，。]*{context_pattern}[^.;,，。]*(?:data|value|window|evidence)\b",
            evidence_text,
        ):
            return True
        if re.search(
            rf"{context_pattern}[^.;,，。]*\bno\b[^.;,，。]*(?:data|value|window|evidence)\b",
            evidence_text,
        ):
            return True
        if re.search(rf"无[^.;,，。]*{context_pattern}[^.;,，。]*(?:数据|窗口|证据|值)", evidence_text):
            return True
        if re.search(rf"{context_pattern}[^.;,，。]*无[^.;,，。]*(?:数据|窗口|证据|值)", evidence_text):
            return True
        for negative_token in ascii_negative_tokens:
            negative_pattern = re.escape(negative_token).replace(r"\ ", r"\s+")
            if re.search(rf"\b{negative_pattern}\b[^.;,，。]*{context_pattern}", evidence_text):
                return True
            if re.search(rf"{context_pattern}[^.;,，。]*\b{negative_pattern}\b", evidence_text):
                return True
        for negative_token in chinese_negative_tokens:
            negative_pattern = re.escape(negative_token).replace(r"\ ", r"\s*")
            if re.search(rf"{negative_pattern}[^.;,，。]*{context_pattern}", evidence_text):
                return True
            if re.search(rf"{context_pattern}[^.;,，。]*{negative_pattern}", evidence_text):
                return True
    return False


def has_stage2_forex_compare_evidence(
    extraction: Dict[str, Any],
    field: str,
    existing_entry: Optional[Dict[str, Any]] = None,
    *,
    coerce: NumberCoercer,
) -> bool:
    parsed_value = coerce(extraction.get(field)) if field in extraction else None
    evidence_text = join_forex_compare_evidence_text(extraction)
    if has_stage2_negative_forex_compare_marker(evidence_text, field):
        return False
    if parsed_value is not None and parsed_value != 0.0:
        return True
    if has_stage2_forex_field_specific_evidence(extraction, field, coerce=coerce):
        return True
    if has_stage2_forex_structured_compare_evidence(extraction, field):
        return True
    if has_stage2_forex_positive_compare_text(evidence_text, field):
        return True
    if not existing_entry:
        return False
    existing_evidence_text = join_forex_compare_evidence_text(existing_entry)
    if has_stage2_negative_forex_compare_marker(existing_evidence_text, field):
        return False
    if has_stage2_forex_field_specific_evidence(existing_entry, field, coerce=coerce):
        return True
    if has_stage2_forex_structured_compare_evidence(existing_entry, field):
        return True
    return has_stage2_forex_positive_compare_text(existing_evidence_text, field)


def has_stage25_forex_daily_change_evidence(
    entry: Dict[str, Any],
    *,
    coerce: NumberCoercer,
) -> bool:
    for key in FOREX_DAILY_CHANGE_EVIDENCE_KEYS:
        value = entry.get(key)
        if key in {"daily_change_basis", "daily_change_source", "daily_change_window_evidence"}:
            if has_forex_computed_marker(
                value,
                STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS,
                is_absence=is_stage25_forex_daily_change_absence_text,
            ):
                return True
            continue
        if key == "daily_change_source_url":
            if is_valid_forex_source_url(value, is_absence=is_stage25_forex_daily_change_absence_text):
                return True
            continue
        if key in {"daily_change_base_date", "base_1d_date"}:
            if is_valid_forex_base_date(value, is_absence=is_stage25_forex_daily_change_absence_text):
                return True
            continue
        if key == "daily_change_base_price" and is_valid_forex_base_price(
            value,
            is_absence=is_stage25_forex_daily_change_absence_text,
            coerce=coerce,
        ):
            return True
    return False


def copy_valid_stage25_forex_daily_change_evidence(
    target: Dict[str, Any],
    source: Dict[str, Any],
    *,
    coerce: NumberCoercer,
) -> None:
    for key in FOREX_DAILY_CHANGE_EVIDENCE_KEYS:
        target.pop(key, None)

    for key in ("daily_change_basis", "daily_change_source", "daily_change_window_evidence"):
        value = source.get(key)
        if has_forex_computed_marker(
            value,
            STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS,
            is_absence=is_stage25_forex_daily_change_absence_text,
        ):
            target[key] = str(value).strip()

    source_url = source.get("daily_change_source_url")
    if is_valid_forex_source_url(source_url, is_absence=is_stage25_forex_daily_change_absence_text):
        target["daily_change_source_url"] = str(source_url).strip()

    base_date = source.get("daily_change_base_date")
    if is_valid_forex_base_date(base_date, is_absence=is_stage25_forex_daily_change_absence_text):
        target["daily_change_base_date"] = str(base_date).strip()

    base_1d_date = source.get("base_1d_date")
    if is_valid_forex_base_date(base_1d_date, is_absence=is_stage25_forex_daily_change_absence_text):
        target["base_1d_date"] = str(base_1d_date).strip()

    base_price = coerce(source.get("daily_change_base_price"))
    if base_price is not None and is_valid_forex_base_price(
        source.get("daily_change_base_price"),
        is_absence=is_stage25_forex_daily_change_absence_text,
        coerce=coerce,
    ):
        target["daily_change_base_price"] = base_price


def copy_valid_stage25_forex_120d_change_evidence(
    target: Dict[str, Any],
    source: Dict[str, Any],
    *,
    coerce: NumberCoercer,
) -> None:
    for key in FOREX_120D_CHANGE_EVIDENCE_KEYS:
        target.pop(key, None)

    for key in ("change_120d_basis", "change_120d_source", "change_120d_window_evidence"):
        value = source.get(key)
        if has_forex_computed_marker(
            value,
            STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS,
            is_absence=is_stage25_forex_daily_change_absence_text,
            reject_daily_prefix=True,
        ):
            target[key] = str(value).strip()

    source_url = source.get("change_120d_source_url")
    if is_valid_forex_source_url(source_url, is_absence=is_stage25_forex_daily_change_absence_text):
        target["change_120d_source_url"] = str(source_url).strip()

    base_date = source.get("change_120d_base_date")
    if is_valid_forex_base_date(base_date, is_absence=is_stage25_forex_daily_change_absence_text):
        target["change_120d_base_date"] = str(base_date).strip()

    base_price = coerce(source.get("change_120d_base_price"))
    if base_price is not None and is_valid_forex_base_price(
        source.get("change_120d_base_price"),
        is_absence=is_stage25_forex_daily_change_absence_text,
        coerce=coerce,
    ):
        target["change_120d_base_price"] = base_price


def has_stage25_forex_120d_change_evidence(
    entry: Dict[str, Any],
    *,
    coerce: NumberCoercer,
) -> bool:
    for key in FOREX_120D_CHANGE_EVIDENCE_KEYS:
        value = entry.get(key)
        if key in {"change_120d_basis", "change_120d_source", "change_120d_window_evidence"}:
            if has_forex_computed_marker(
                value,
                STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS,
                is_absence=is_stage25_forex_daily_change_absence_text,
                reject_daily_prefix=True,
            ):
                return True
            continue
        if key == "change_120d_source_url":
            if is_valid_forex_source_url(value, is_absence=is_stage25_forex_daily_change_absence_text):
                return True
            continue
        if key == "change_120d_base_date":
            if is_valid_forex_base_date(value, is_absence=is_stage25_forex_daily_change_absence_text):
                return True
            continue
        if key == "change_120d_base_price" and is_valid_forex_base_price(
            value,
            is_absence=is_stage25_forex_daily_change_absence_text,
            coerce=coerce,
        ):
            return True
    return False
```

- [ ] **Step 2.3: Verify utilities compile**

Run:

```bash
bash run_clean.sh python -m compileall -q src/datasource/utils/forex_evidence.py src/datasource/utils/note_utils.py
```

Expected: empty output, exit 0.

- [ ] **Step 2.4: Commit utility modules**

Run:

```bash
git add src/datasource/utils/forex_evidence.py src/datasource/utils/note_utils.py
git commit -m "refactor: add forex evidence utility helpers"
```

Expected commit summary:

```text
2 files changed
create mode 100644 src/datasource/utils/forex_evidence.py
create mode 100644 src/datasource/utils/note_utils.py
```

### Task 3: Route Stage2 Through Shared Utilities

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py`
- Test: `tests/test_forex_evidence_characterization.py`, `tests/test_stage2_replay_harness.py`

- [ ] **Step 3.1: Add Stage2 imports**

Modify `scripts/stage2_unified_enhancer.py` imports:

1. Add after `import copy`:

```python
from functools import partial
```

2. Add after `from datasource.utils.text_markers import contains_ytd_marker`:

```python
from datasource.utils.forex_evidence import (
    FOREX_COMPARE_FIELDS,
    FOREX_COMPARE_EVIDENCE_TOKENS as _FOREX_COMPARE_EVIDENCE_TOKENS,
    FOREX_COMPARE_FIELD_EVIDENCE_KEYS as _FOREX_COMPARE_FIELD_EVIDENCE_KEYS,
    FOREX_COMPARE_TEXT_FIELDS as _FOREX_COMPARE_TEXT_FIELDS,
    STAGE2_FOREX_DAILY_EVIDENCE_MARKERS as _FOREX_DAILY_EVIDENCE_MARKERS,
    STAGE2_FOREX_120D_EVIDENCE_MARKERS as _FOREX_120D_EVIDENCE_MARKERS,
    has_forex_computed_marker,
    has_stage2_forex_compare_evidence,
    has_stage2_forex_field_specific_evidence,
    has_stage2_forex_no_change_evidence,
    has_stage2_forex_positive_compare_text,
    has_stage2_forex_structured_compare_evidence,
    has_stage2_negative_forex_compare_marker,
    is_stage2_forex_absence_text,
    is_stage2_forex_compare_absence_text,
    is_stage2_forex_no_change_absence_text,
    is_valid_forex_base_date,
    is_valid_forex_base_price,
    is_valid_forex_source_url,
    join_forex_compare_evidence_text,
    normalize_forex_compare_text,
)
from datasource.utils.note_utils import append_note_text as _append_note
```

- [ ] **Step 3.2: Replace Stage2 YTD wrapper with alias**

Find:

```python
def _contains_ytd_marker(text: str) -> bool:
    return contains_ytd_marker(text)
```

Replace with:

```python
_contains_ytd_marker = contains_ytd_marker
```

- [ ] **Step 3.3: Replace Stage2 forex predicate block with aliases**

In `scripts/stage2_unified_enhancer.py`, replace the block beginning at `FOREX_COMPARE_FIELDS = ("daily_change", "change_120d")` and ending immediately before `def _scrub_unevidenced_forex_zeroes(` with exactly this alias block:

```python
_join_forex_compare_evidence_text = join_forex_compare_evidence_text
_normalize_forex_compare_text = normalize_forex_compare_text
_has_forex_positive_compare_text = has_stage2_forex_positive_compare_text
_has_forex_no_change_evidence = has_stage2_forex_no_change_evidence
_is_forex_no_change_absence_text = is_stage2_forex_no_change_absence_text
_is_forex_absence_text = is_stage2_forex_absence_text
_is_forex_compare_absence_text = is_stage2_forex_compare_absence_text
_is_valid_forex_compare_source_url = partial(
    is_valid_forex_source_url,
    is_absence=_is_forex_absence_text,
)
_is_valid_forex_compare_base_date = partial(
    is_valid_forex_base_date,
    is_absence=_is_forex_absence_text,
)
_is_valid_forex_compare_base_price = partial(
    is_valid_forex_base_price,
    is_absence=_is_forex_absence_text,
    coerce=_safe_number,
)
_has_forex_computed_marker = partial(
    has_forex_computed_marker,
    is_absence=_is_forex_absence_text,
)
_has_forex_field_specific_evidence = partial(
    has_stage2_forex_field_specific_evidence,
    coerce=_safe_number,
)
_has_forex_structured_compare_evidence = has_stage2_forex_structured_compare_evidence
_has_negative_forex_compare_marker = has_stage2_negative_forex_compare_marker
_has_forex_compare_evidence = partial(
    has_stage2_forex_compare_evidence,
    coerce=_safe_number,
)
```

- [ ] **Step 3.4: Remove Stage2 local note helper body**

Find:

```python
def _append_note(note: Optional[str], extra: Optional[str]) -> Optional[str]:
    base = (note or "").strip()
    tail = (extra or "").strip()
    if not tail:
        return base or None
    if not base:
        return tail
    if tail in base:
        return base
    return f"{base} {tail}".strip()
```

Delete that function. `_append_note` is now imported from `note_utils`.

- [ ] **Step 3.5: Run Stage2 focused tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_forex_evidence_characterization.py tests/test_stage2_replay_harness.py
bash run_clean.sh python -m compileall -q scripts/stage2_unified_enhancer.py src/datasource/utils/forex_evidence.py src/datasource/utils/note_utils.py
```

Expected pytest summary:

```text
29 passed, 3 warnings
```

Expected compileall output: empty output, exit 0.

- [ ] **Step 3.6: Audit Stage2 script no longer owns duplicate helper defs**

Run:

```bash
rg -n "def _is_forex|def _has_forex|def _is_valid_forex|def _append_note|def _contains_ytd_marker" scripts/stage2_unified_enhancer.py
```

Expected: empty output, exit 1.

- [ ] **Step 3.7: Commit Stage2 routing**

Run:

```bash
git add scripts/stage2_unified_enhancer.py
git commit -m "refactor: route stage2 forex helpers through utils"
```

Expected commit summary mentions only `scripts/stage2_unified_enhancer.py`.

### Task 4: Route Stage2.5 Through Shared Utilities

**Files:**
- Modify: `scripts/stage2_5_injector.py`
- Test: `tests/test_forex_evidence_characterization.py`, `tests/test_websearch_injector.py`, `tests/test_stage25_contract_replay.py`

- [ ] **Step 4.1: Add Stage2.5 imports**

Modify `scripts/stage2_5_injector.py` imports:

1. Add after `import json`:

```python
from functools import partial
```

2. Add after `from datasource.utils.text_markers import contains_ytd_marker`:

```python
from datasource.utils.forex_evidence import (
    FOREX_DAILY_CHANGE_EVIDENCE_KEYS,
    FOREX_120D_CHANGE_EVIDENCE_KEYS,
    STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS as FOREX_DAILY_CHANGE_SOURCE_MARKERS,
    STAGE25_FOREX_120D_CHANGE_SOURCE_MARKERS as FOREX_120D_CHANGE_SOURCE_MARKERS,
    copy_valid_stage25_forex_120d_change_evidence,
    copy_valid_stage25_forex_daily_change_evidence,
    has_forex_computed_marker,
    has_stage25_forex_120d_change_evidence,
    has_stage25_forex_daily_change_evidence,
    is_stage25_forex_daily_change_absence_text,
    is_valid_forex_base_date,
    is_valid_forex_base_price,
    is_valid_forex_source_url,
)
from datasource.utils.note_utils import (
    append_note_once as _append_note_once,
    append_note_to_entry as _append_note,
)
```

- [ ] **Step 4.2: Remove Stage2.5 local note helper bodies**

Delete this function:

```python
def _append_note_once(note: str, addition: str) -> str:
    if not addition:
        return note
    if addition in note:
        return note
    if note:
        return f"{note}；{addition}"
    return addition
```

Delete this function:

```python
def _append_note(entry: Dict[str, Any], message: str) -> None:
    if not message:
        return
    note = entry.get("note") or ""
    if note:
        note += "；"
    note += message
    entry["note"] = note
```

- [ ] **Step 4.3: Replace Stage2.5 YTD wrapper with alias**

Find:

```python
def _contains_ytd_marker(text: str) -> bool:
    return contains_ytd_marker(text)
```

Replace with:

```python
_contains_ytd_marker = contains_ytd_marker
```

- [ ] **Step 4.4: Replace Stage2.5 forex predicate/copy block with aliases**

In `scripts/stage2_5_injector.py`, replace the block beginning at `FOREX_DAILY_CHANGE_SOURCE_MARKERS = (` and ending immediately before `def _is_zero_change_value(` with exactly this alias block:

```python
_is_forex_daily_change_absence_text = is_stage25_forex_daily_change_absence_text
_is_valid_forex_daily_change_base_date = partial(
    is_valid_forex_base_date,
    is_absence=_is_forex_daily_change_absence_text,
)
_is_valid_forex_daily_change_source_url = partial(
    is_valid_forex_source_url,
    is_absence=_is_forex_daily_change_absence_text,
)
_is_valid_forex_change_base_price = partial(
    is_valid_forex_base_price,
    is_absence=_is_forex_daily_change_absence_text,
    coerce=_coerce_float,
)
_has_forex_daily_change_computed_marker = partial(
    has_forex_computed_marker,
    markers=FOREX_DAILY_CHANGE_SOURCE_MARKERS,
    is_absence=_is_forex_daily_change_absence_text,
)
_has_forex_120d_change_computed_marker = partial(
    has_forex_computed_marker,
    markers=FOREX_120D_CHANGE_SOURCE_MARKERS,
    is_absence=_is_forex_daily_change_absence_text,
    reject_daily_prefix=True,
)
_has_forex_daily_change_evidence = partial(
    has_stage25_forex_daily_change_evidence,
    coerce=_coerce_float,
)
_copy_valid_forex_daily_change_evidence = partial(
    copy_valid_stage25_forex_daily_change_evidence,
    coerce=_coerce_float,
)
_copy_valid_forex_120d_change_evidence = partial(
    copy_valid_stage25_forex_120d_change_evidence,
    coerce=_coerce_float,
)
_has_forex_120d_change_evidence = partial(
    has_stage25_forex_120d_change_evidence,
    coerce=_coerce_float,
)
```

- [ ] **Step 4.5: Run Stage2.5 focused tests**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_forex_evidence_characterization.py tests/test_websearch_injector.py tests/test_stage25_contract_replay.py
bash run_clean.sh python -m compileall -q scripts/stage2_5_injector.py src/datasource/utils/forex_evidence.py src/datasource/utils/note_utils.py
```

Expected pytest summary:

```text
235 passed, 3 warnings
```

Expected compileall output: empty output, exit 0.

- [ ] **Step 4.6: Audit Stage2.5 script no longer owns duplicate helper defs**

Run:

```bash
rg -n "def _is_forex|def _has_forex|def _is_valid_forex|def _copy_valid_forex|def _append_note|def _contains_ytd_marker" scripts/stage2_5_injector.py
```

Expected: empty output, exit 1.

- [ ] **Step 4.7: Commit Stage2.5 routing**

Run:

```bash
git add scripts/stage2_5_injector.py
git commit -m "refactor: route stage25 forex helpers through utils"
```

Expected commit summary mentions only `scripts/stage2_5_injector.py`.

### Task 5: Final Regression Gates And Review Package

**Files:**
- Read/verify only unless formatting changes are produced by `black`.

- [ ] **Step 5.1: Format touched Python files**

Run:

```bash
bash run_clean.sh python -m black tests/test_forex_evidence_characterization.py src/datasource/utils/forex_evidence.py src/datasource/utils/note_utils.py scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py
```

Expected:

```text
All done!
```

If black changes files, run the focused tests from Tasks 3 and 4 again, then commit formatting with the same logical commit if still uncommitted; if all logical commits already exist, create:

```bash
git add tests/test_forex_evidence_characterization.py src/datasource/utils/forex_evidence.py src/datasource/utils/note_utils.py scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py
git commit -m "style: format forex evidence consolidation"
```

- [ ] **Step 5.2: Run duplicate-helper grep gates**

Run:

```bash
rg -n "def _is_forex|def _has_forex|def _is_valid_forex|def _copy_valid_forex|def _append_note|def _contains_ytd_marker" scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py
rg -n "FOREX_DAILY_CHANGE_SOURCE_MARKERS = \\(|FOREX_120D_CHANGE_SOURCE_MARKERS = \\(|_FOREX_DAILY_EVIDENCE_MARKERS = \\(|_FOREX_120D_EVIDENCE_MARKERS = \\(" scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py
```

Expected for both commands: empty output, exit 1.

- [ ] **Step 5.3: Re-run constant audit from the script compatibility names**

Run:

```bash
bash run_clean.sh python - <<'PY'
import scripts.stage2_unified_enhancer as s2
import scripts.stage2_5_injector as s25

assert s2._FOREX_DAILY_EVIDENCE_MARKERS != s25.FOREX_DAILY_CHANGE_SOURCE_MARKERS
assert s2._FOREX_120D_EVIDENCE_MARKERS != s25.FOREX_120D_CHANGE_SOURCE_MARKERS
assert s2._FOREX_COMPARE_FIELD_EVIDENCE_KEYS["daily_change"] == s25.FOREX_DAILY_CHANGE_EVIDENCE_KEYS
assert s2._FOREX_COMPARE_FIELD_EVIDENCE_KEYS["change_120d"] == s25.FOREX_120D_CHANGE_EVIDENCE_KEYS
print("forex constant audit ok")
PY
```

Expected:

```text
forex constant audit ok
```

- [ ] **Step 5.4: Run C0 focused regression suite**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_forex_evidence_characterization.py \
  tests/test_websearch_injector.py \
  tests/test_stage2_replay_harness.py \
  tests/test_stage25_contract_replay.py
```

Expected:

```text
237 passed, 3 warnings
```

- [ ] **Step 5.5: Run full test suite**

Run:

```bash
bash run_clean.sh python -m pytest -q
```

Expected baseline from C-0.5 was:

```text
1013 passed, 3 skipped
```

Warnings are allowed if test status matches. If count differs only because the new characterization tests are included, expected becomes:

```text
1040 passed, 3 skipped
```

Any failure or additional skip must stop the task.

- [ ] **Step 5.6: Verify git diff scope**

Run:

```bash
git diff --stat main...HEAD
git diff --name-only main...HEAD
```

Expected changed files only:

```text
scripts/stage2_5_injector.py
scripts/stage2_unified_enhancer.py
src/datasource/utils/forex_evidence.py
src/datasource/utils/note_utils.py
tests/test_forex_evidence_characterization.py
```

- [ ] **Step 5.7: Prepare review summary**

Record these exact facts in the final implementation report:

```text
Behavior preserved:
- Stage2 empty/N/A/no change absence semantics remain distinct from Stage2.5.
- Stage2 strict _safe_number and Stage2.5 broader _coerce_float remain distinct.
- Stage2 and Stage2.5 marker constants remain distinct; evidence key tuples are shared.
- Three note helper semantics remain distinct.
- YTD marker wrappers are aliases to the shared text marker helper.

Verification:
- characterization tests
- Stage2 replay harness
- Stage2.5 contract replay
- full pytest
- duplicate-helper grep gates
```

## Self-Review

- **Spec coverage:** §2 scope maps to Tasks 2-4. §3 difference matrix is locked by Task 0.4 and Task 1 tests. §4 target files are created in Task 2 and wired in Tasks 3-4. §5 characterization comes first in Task 1. §7 freeze constraints are enforced by Tasks 5.2 and 5.6.
- **Placeholder scan:** This plan contains no placeholder markers. Every code creation step includes exact content. Every validation step includes expected output or a stop condition.
- **Type consistency:** `is_absence` receives `Any` and returns `bool`; `coerce` receives `Any` and returns `Optional[float]`. Stage2 aliases inject `_safe_number`; Stage2.5 aliases inject `_coerce_float`. Constants exported by `forex_evidence.py` match script compatibility names via import aliases.
