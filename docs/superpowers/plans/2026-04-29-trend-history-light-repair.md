# Trend History Light Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lightly repair the trend_history diagnostics path and official manual override URL parsing without changing report-generation flow, storage format, or quality gate semantics.

**Architecture:** Keep `data/trend_history/min` as JSON storage. Add non-blocking quality diagnostics to `scan_trend_history()`, add a shared gap snapshot writer, call it after Stage1 and Stage2.5 trend writes, and tighten official override URL evidence extraction so decimal numbers are not treated as bare domains. Documentation must separate official manual override from estimated-value policy allowlisting.

**Tech Stack:** Python stdlib JSON/pathlib/re/urllib, existing pytest suite, existing Stage1/Stage2.5 scripts, Markdown docs.

---

## Scope Guard

This plan is intentionally narrow:

- Do not change the Stage1 -> Stage2 -> Stage2.5 -> Stage3 -> Stage4 workflow.
- Do not change `config/policy_rules.yaml` `estimated_allowlist_keys`.
- Do not add `BCOM`, `USDCNY`, or `mlf` to the estimated allowlist.
- Do not change `trend_history` storage format.
- Do not relax Stage3 or Stage4 gates.
- Do not tune DeepSeek timeout or Ubuntu environment setup in this plan.

## File Structure

- Modify: `src/datasource/utils/trend_history_store.py`
  - Add scan-time quality summaries for each series/event JSON.
  - Add `write_trend_history_gap_snapshot()` as the shared writer for `data/runs/YYYYMMDD/trend_history_gap.json`.
- Modify: `scripts/stage1_data_collector.py`
  - Replace duplicated pre-scan write code with the shared helper.
  - Refresh `trend_history_gap.json` again after Stage1 partial trend write.
- Modify: `scripts/stage2_5_injector.py`
  - Tighten `BARE_DOMAIN_START_RE`.
  - Import and call `write_trend_history_gap_snapshot()` after Stage2.5 final/post-write trend updates.
- Modify: `tests/test_trend_history_store.py`
  - Cover quality diagnostics and shared snapshot writing.
- Modify: `tests/test_websearch_injector.py`
  - Cover BCOM official override with a decimal in note text.
- Modify: `tests/test_stage25_contract_replay.py`
  - Cover Stage2.5 refreshing run-scoped `trend_history_gap.json`.
- Modify: `AGENTS.md`
  - Clarify official manual override vs estimated allowlist.
- Modify: `CLAUDE.md`
  - Same terminology clarification for Claude Code operators.

---

### Task 1: Add Trend History Quality Diagnostics

**Files:**
- Modify: `src/datasource/utils/trend_history_store.py:494-559`
- Test: `tests/test_trend_history_store.py`

- [ ] **Step 1: Write the failing scan quality test**

Append this test to `tests/test_trend_history_store.py`:

```python
from datasource.utils.trend_history_store import scan_trend_history


def test_scan_trend_history_reports_estimated_and_partial_ratios(tmp_path: Path):
    base_dir = tmp_path / "trend"
    write_series_record(
        "commodities",
        "BCOM",
        SeriesRecord(
            date="2026-04-27",
            value=131.48,
            unit="points",
            source="manual",
            source_timestamp=None,
            market_calendar="GLOBAL",
            is_estimated=True,
            is_partial=False,
        ),
        base_dir=base_dir,
    )
    write_series_record(
        "commodities",
        "BCOM",
        SeriesRecord(
            date="2026-04-28",
            value=132.0,
            unit="points",
            source="manual",
            source_timestamp=None,
            market_calendar="GLOBAL",
            is_estimated=False,
            is_partial=True,
        ),
        base_dir=base_dir,
    )

    result = scan_trend_history("2026-04-28", base_dir=base_dir)

    quality = result["series"]["quality"]
    bcom = next(item for item in quality if item["category"] == "commodities" and item["symbol"] == "BCOM")
    assert bcom["count"] == 2
    assert bcom["estimated_count"] == 1
    assert bcom["estimated_ratio"] == 0.5
    assert bcom["partial_count"] == 1
    assert bcom["partial_ratio"] == 0.5
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
python -m pytest tests/test_trend_history_store.py::test_scan_trend_history_reports_estimated_and_partial_ratios -q
```

Expected: FAIL with `KeyError: 'quality'`.

- [ ] **Step 3: Add quality summary helper**

In `src/datasource/utils/trend_history_store.py`, add this helper above `scan_trend_history()`:

```python
def _quality_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(items)
    estimated_count = sum(1 for item in items if isinstance(item, dict) and bool(item.get("is_estimated")))
    partial_count = sum(1 for item in items if isinstance(item, dict) and bool(item.get("is_partial")))
    return {
        "count": total,
        "estimated_count": estimated_count,
        "estimated_ratio": round(estimated_count / total, 4) if total else 0.0,
        "partial_count": partial_count,
        "partial_ratio": round(partial_count / total, 4) if total else 0.0,
    }
```

- [ ] **Step 4: Add non-blocking quality arrays to scan output**

Update the `results` initialization in `scan_trend_history()`:

```python
results: Dict[str, Any] = {
    "date": target_date,
    "series": {"missing": [], "insufficient": [], "stale": [], "quality": []},
    "events": {"missing": [], "insufficient": [], "quality": []},
}
```

After validating non-empty `values`, append:

```python
summary = _quality_summary([item for item in values if isinstance(item, dict)])
summary.update({"category": category, "symbol": path.stem})
results["series"]["quality"].append(summary)
```

After validating non-empty `events`, append:

```python
summary = _quality_summary([item for item in events if isinstance(item, dict)])
summary.update({"indicator": path.stem})
results["events"]["quality"].append(summary)
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
python -m pytest tests/test_trend_history_store.py::test_scan_trend_history_reports_estimated_and_partial_ratios -q
```

Expected: PASS.

- [ ] **Step 6: Run existing trend history tests**

Run:

```bash
python -m pytest tests/test_trend_history_store.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/datasource/utils/trend_history_store.py tests/test_trend_history_store.py
git commit -m "fix: add trend history quality diagnostics"
```

---

### Task 2: Add a Shared Trend Gap Snapshot Writer

**Files:**
- Modify: `src/datasource/utils/trend_history_store.py`
- Test: `tests/test_trend_history_store.py`

- [ ] **Step 1: Write the failing snapshot writer test**

Append this test to `tests/test_trend_history_store.py`:

```python
from datasource.utils.trend_history_store import write_trend_history_gap_snapshot


def test_write_trend_history_gap_snapshot_writes_run_file(tmp_path: Path):
    base_dir = tmp_path / "trend"
    output_path = tmp_path / "data" / "runs" / "20260428" / "trend_history_gap.json"
    write_series_record(
        "forex",
        "USDCNY",
        SeriesRecord(
            date="2026-04-28",
            value=6.86,
            unit=None,
            source="manual",
            source_timestamp=None,
            market_calendar="GLOBAL",
            is_estimated=False,
            is_partial=False,
        ),
        base_dir=base_dir,
    )

    payload = write_trend_history_gap_snapshot("2026-04-28", output_path, base_dir=base_dir)

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved == payload
    assert saved["date"] == "2026-04-28"
    assert any(item["category"] == "forex" and item["symbol"] == "USDCNY" for item in saved["series"]["quality"])
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
python -m pytest tests/test_trend_history_store.py::test_write_trend_history_gap_snapshot_writes_run_file -q
```

Expected: FAIL with import error for `write_trend_history_gap_snapshot`.

- [ ] **Step 3: Implement the shared writer**

Add this function below `scan_trend_history()` in `src/datasource/utils/trend_history_store.py`:

```python
def write_trend_history_gap_snapshot(
    target_date: str,
    output_path: Path,
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    """Write a run-scoped trend_history gap snapshot and return its payload."""
    payload = scan_trend_history(target_date, base_dir=base_dir)
    _safe_json_write(output_path, payload)
    return payload
```

- [ ] **Step 4: Run the snapshot writer test**

Run:

```bash
python -m pytest tests/test_trend_history_store.py::test_write_trend_history_gap_snapshot_writes_run_file -q
```

Expected: PASS.

- [ ] **Step 5: Run the trend history test file**

Run:

```bash
python -m pytest tests/test_trend_history_store.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/datasource/utils/trend_history_store.py tests/test_trend_history_store.py
git commit -m "fix: write run scoped trend history gap snapshots"
```

---

### Task 3: Refresh Trend Gap Snapshot After Stage1 and Stage2.5 Writes

**Files:**
- Modify: `scripts/stage1_data_collector.py:36,2324-2331,2362-2367`
- Modify: `scripts/stage2_5_injector.py:19,1641-1691`
- Test: `tests/test_stage25_contract_replay.py`

- [ ] **Step 1: Write the failing Stage2.5 snapshot refresh test**

Append this test to `tests/test_stage25_contract_replay.py`:

```python
def test_stage25_refreshes_trend_history_gap_snapshot_after_final_write(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "data" / "runs" / "20260427"
    run_dir.mkdir(parents=True)
    market_path = run_dir / "market_data_stage2.json"
    manual_path = run_dir / "websearch_results_manual.json"
    output_path = run_dir / "market_data_complete.json"
    trend_base = tmp_path / "trend_history" / "min"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-04-27", "data_completeness": 1.0},
                "missing_items": [],
                "macro_indicators": {},
                "monetary_policy": {},
                "fund_flow": {},
                "commodities": [],
                "forex": [],
                "bonds": [],
                "stock_indices": [
                    {
                        "symbol": "000300",
                        "name": "CSI 300",
                        "current_price": 4000.0,
                        "change_5d": 1.0,
                        "change_120d": 2.0,
                        "source": "tushare",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        backfill_trend=False,
        trend_history_base_dir=trend_base,
        gap_monitor_path=run_dir / "gap_monitor.json",
    )

    gap_path = run_dir / "trend_history_gap.json"
    assert gap_path.exists()
    gap = json.loads(gap_path.read_text(encoding="utf-8"))
    assert gap["date"] == "2026-04-27"
    assert any(
        item["category"] == "stock_indices" and item["symbol"] == "000300"
        for item in gap["series"]["quality"]
    )
```

- [ ] **Step 2: Run the failing Stage2.5 test**

Run:

```bash
python -m pytest tests/test_stage25_contract_replay.py::test_stage25_refreshes_trend_history_gap_snapshot_after_final_write -q
```

Expected: FAIL because `trend_history_gap.json` is not written by Stage2.5.

- [ ] **Step 3: Update Stage1 import**

Change `scripts/stage1_data_collector.py:36` from:

```python
from datasource.utils.trend_history_store import scan_trend_history, write_from_market_data, load_series_values
```

to:

```python
from datasource.utils.trend_history_store import (
    write_trend_history_gap_snapshot,
    write_from_market_data,
    load_series_values,
)
```

- [ ] **Step 4: Replace Stage1 pre-scan duplication**

Replace `scripts/stage1_data_collector.py:2324-2331` with:

```python
# Pre-scan trend_history gaps before Stage1 collection
try:
    gap_output = run_paths.trend_history_gap
    write_trend_history_gap_snapshot(trading_date, gap_output)
    print(f"[INFO] trend_history scan saved: {gap_output}")
except Exception as exc:  # noqa: BLE001
    print(f"[WARN] trend_history scan failed: {exc}")
```

- [ ] **Step 5: Refresh Stage1 gap snapshot after partial write**

After the Stage1 partial write print in `scripts/stage1_data_collector.py:2365`, add:

```python
        write_trend_history_gap_snapshot(trading_date, run_paths.trend_history_gap)
        print(f"[INFO] trend_history scan refreshed: {run_paths.trend_history_gap}")
```

The block should remain inside the existing `try` that writes trend history, so a scan refresh failure is reported by the existing warning and does not stop Stage1.

- [ ] **Step 6: Update Stage2.5 import**

Change `scripts/stage2_5_injector.py:19` from:

```python
from datasource.utils.trend_history_store import write_from_market_data, DEFAULT_BASE_DIR, SERIES_WINDOWS
```

to:

```python
from datasource.utils.trend_history_store import (
    write_trend_history_gap_snapshot,
    write_from_market_data,
    DEFAULT_BASE_DIR,
    SERIES_WINDOWS,
)
```

- [ ] **Step 7: Refresh Stage2.5 gap snapshot after trend writes**

In `scripts/stage2_5_injector.py`, after the post-write backfill block and before the unified quality artifact refresh comment, add:

```python
    if not disable_trend_history_write and trend_base_dir is not None:
        try:
            write_trend_history_gap_snapshot(
                run_paths.date,
                run_paths.trend_history_gap,
                base_dir=trend_base_dir,
            )
            print(f"  - trend_history gap snapshot refreshed: {run_paths.trend_history_gap}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] trend_history gap snapshot refresh failed: {exc}")
```

This is diagnostic only. It must not alter `market_data`, `quality_metrics`, or Stage3/Stage4 gates.

- [ ] **Step 8: Run the Stage2.5 snapshot refresh test**

Run:

```bash
python -m pytest tests/test_stage25_contract_replay.py::test_stage25_refreshes_trend_history_gap_snapshot_after_final_write -q
```

Expected: PASS.

- [ ] **Step 9: Run focused Stage2.5 replay tests**

Run:

```bash
python -m pytest tests/test_stage25_contract_replay.py -q
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add scripts/stage1_data_collector.py scripts/stage2_5_injector.py tests/test_stage25_contract_replay.py
git commit -m "fix: refresh trend history gap snapshots after writes"
```

---

### Task 4: Fix Official Override Bare Domain Parsing

**Files:**
- Modify: `scripts/stage2_5_injector.py:109-111`
- Test: `tests/test_websearch_injector.py`

- [ ] **Step 1: Write the failing BCOM decimal regression test**

Append this helper-level test near the other manual official helper tests in `tests/test_websearch_injector.py`:

```python
def test_manual_official_helper_ignores_decimal_numbers_in_note():
    assert injector._collect_http_like_evidence(
        "BCOM level 131.4824 with official https://www.bloomberg.com/quote/BCOM:IND"
    ) == ["https://www.bloomberg.com/quote/BCOM:IND"]
    assert injector._is_manual_official_value(
        "commodities",
        "BCOM",
        {
            "name": "Bloomberg Commodity Index",
            "current_price": 131.4824,
            "source_url": "https://www.bloomberg.com/quote/BCOM:IND",
            "note": "BCOM level 131.4824, Bloomberg official quote",
        },
    ) is True
```

- [ ] **Step 2: Run the failing BCOM regression test**

Run:

```bash
python -m pytest tests/test_websearch_injector.py::test_manual_official_helper_ignores_decimal_numbers_in_note -q
```

Expected: FAIL because `_collect_http_like_evidence()` includes `131.4824`.

- [ ] **Step 3: Tighten bare domain regex**

Change `BARE_DOMAIN_START_RE` in `scripts/stage2_5_injector.py` from:

```python
BARE_DOMAIN_START_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9./:-])(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?=[:/]|$|[\s,;|)\]}<>\"'，；）】》、」』”’｝］〉])"
)
```

to:

```python
BARE_DOMAIN_START_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9./:-])(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z0-9-]*[A-Za-z][A-Za-z0-9-]*(?=[:/]|$|[\s,;|)\]}<>\"'，；）】》、」』”’｝］〉])"
)
```

The final domain segment must contain at least one ASCII letter. Numeric decimals such as `131.4824` no longer match. Existing bare domains such as `www.pbc.gov.cn/path` still match and remain blocking evidence.

- [ ] **Step 4: Run the BCOM regression test**

Run:

```bash
python -m pytest tests/test_websearch_injector.py::test_manual_official_helper_ignores_decimal_numbers_in_note -q
```

Expected: PASS.

- [ ] **Step 5: Run official override helper tests**

Run:

```bash
python -m pytest tests/test_websearch_injector.py -k "manual_official_helper or third_party_bcom or third_party_usdcny or etf_eastmoney" -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/stage2_5_injector.py tests/test_websearch_injector.py
git commit -m "fix: ignore decimal values in official url evidence"
```

---

### Task 5: Clarify Documentation Terminology

**Files:**
- Modify: `AGENTS.md:164-166`
- Modify: `CLAUDE.md:139-153`

- [ ] **Step 1: Update AGENTS.md official override wording**

Replace `AGENTS.md:164-166` with:

```markdown
- official manual override 与 policy estimated allowlist 是两套概念，不能混用：
  - official manual override 仅适用于代码 `OFFICIAL_MANUAL_SOURCES` 中的指标：`monetary_policy.mlf`、`forex.USDCNY`、`commodities.BCOM`。这些指标在 `_manual.json` 显式 `is_estimated=True` 时，只有提供可信官方 HTTPS `source_url` 证据才会正规化为 `is_estimated=False`，并追加 `manual_official_not_estimated`。
  - policy estimated allowlist 来自 `config/policy_rules.yaml` 的 `estimated_allowlist_keys`，表示“仍是估算值但允许参与评分”。当前不要把 `BCOM`、`USDCNY`、`mlf` 加入该列表；它们应通过 official manual override 转为非估算，或继续被 gate 阻断。
- official override 要求显式 URL 字段是单个字符串 URL；混入说明文字、多个 URL、非 HTTPS、非法端口、untrusted/spoof/conflicting URL 都不能触发 override。ETF/fund_flow 不在 official override 中，估算仍受 gate 约束。
- 普通 manual 来源不要因为不是官方域名就默认改成 estimated 或 blocked；是否 official override 只影响显式估算值能否被正规化。
```

- [ ] **Step 2: Update CLAUDE.md official override wording**

Replace `CLAUDE.md:139-140` with:

```markdown
- official manual override 与 policy estimated allowlist 是两套概念：
  - official manual override 代码表为 `OFFICIAL_MANUAL_SOURCES`，当前包含 `monetary_policy.mlf`、`forex.USDCNY`、`commodities.BCOM`。这些指标只有在 `_manual.json` 显式 `is_estimated=True` 且提供可信官方 HTTPS `source_url` 时，才会正规化为 `is_estimated=False` 并追加 `manual_official_not_estimated`。
  - policy estimated allowlist 来自 `config/policy_rules.yaml` 的 `estimated_allowlist_keys`，当前为 `CN10Y_CDB`、`bdi`；它表示“仍是估算值但允许参与评分”，不要用它来放行 BCOM/USDCNY/MLF。
- official override 要求显式 URL 字段是单个字符串 URL；混入说明文字、多个 URL、非 HTTPS、非法端口、untrusted/spoof/conflicting URL 均不触发。ETF/fund_flow 不在 official override；普通 manual 来源不会因为不是官方域名而默认改成 estimated/blocked。
```

Replace the `CLAUDE.md:153` sentence with:

```markdown
- 解法：官方口径用带可信单个 HTTPS `source_url` 的 Stage2.5 manual 重新注入；只有 official manual override 指标（代码为准，当前 `monetary_policy.mlf`、`forex.USDCNY`、`commodities.BCOM`）可触发 `manual_official_not_estimated` 并把显式 `is_estimated=True` 正规化为 `False`。这不同于 `config/policy_rules.yaml` 的 `estimated_allowlist_keys`（当前 `CN10Y_CDB`、`bdi`），后者表示估算值仍可参与评分。显式 URL 字段必须是单个字符串 URL，混入说明文字、多个 URL、非 HTTPS、非法端口、untrusted/spoof/conflicting URL 均不触发；ETF/fund_flow 不在 official override，普通 manual 来源不会因为不是官方域名而默认改成 estimated/blocked。
```

- [ ] **Step 3: Search for misleading allowlist phrasing**

Run:

```bash
Select-String -Path 'AGENTS.md','CLAUDE.md' -Pattern 'official override.*allowlist|official manual override 仅用于 allowlist|official allowlist'
```

Expected: no results that conflate official override with `estimated_allowlist_keys`.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: clarify official override terminology"
```

---

### Task 6: Focused Validation

**Files:**
- Verify: changed files from Tasks 1-5

- [ ] **Step 1: Run the focused tests**

Run:

```bash
python -m pytest tests/test_trend_history_store.py tests/test_stage25_contract_replay.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run official override focused tests**

Run:

```bash
python -m pytest tests/test_websearch_injector.py -k "manual_official_helper or third_party_bcom or third_party_usdcny or etf_eastmoney" -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run syntax checks**

Run:

```bash
python -m py_compile src/datasource/utils/trend_history_store.py scripts/stage1_data_collector.py scripts/stage2_5_injector.py
```

Expected: command exits with status 0.

- [ ] **Step 4: Verify no whitespace damage**

Run:

```bash
git diff --check
```

Expected: no output and status 0.

- [ ] **Step 5: Inspect diff scope**

Run:

```bash
git diff --stat
```

Expected: only these files changed:

```text
AGENTS.md
CLAUDE.md
scripts/stage1_data_collector.py
scripts/stage2_5_injector.py
src/datasource/utils/trend_history_store.py
tests/test_stage25_contract_replay.py
tests/test_trend_history_store.py
tests/test_websearch_injector.py
```

- [ ] **Step 6: Commit final validation note if needed**

If previous tasks were committed individually and no additional code changed, do not create another commit. If validation required small fixes, commit only those fixes:

```bash
git add <fixed-files>
git commit -m "test: cover trend history light repair"
```

---

## Self-Review

**Spec coverage:** The plan covers all approved scope: trend_history diagnostics and gap refresh, official override regex, and documentation terminology. It explicitly excludes Stage2 timeout and Ubuntu environment work.

**Placeholder scan:** No placeholders are required by this plan. All code snippets, commands, and expected outcomes are concrete.

**Type consistency:** New helper signatures use `Path`, `Dict[str, Any]`, and existing `DEFAULT_BASE_DIR`. Test imports reference functions defined in earlier tasks. Stage2.5 uses existing `run_paths.date` and `run_paths.trend_history_gap`.
