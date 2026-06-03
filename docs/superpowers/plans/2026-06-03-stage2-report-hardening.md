# Stage2 Report Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 2026-06-03 report hardening issues where forex daily changes can remain placeholder zeroes, CN10Y_CDB spread provenance is too hard to pass into Stage2, and Stage2 summaries do not explain manual gaps clearly enough.

**Architecture:** Keep the pipeline boundaries intact: Stage2 discovers and writes current values, Stage2.5 enriches comparison/window fields from manual payloads and trend history, and Stage4 only renders report-facing cells defensively. Add small focused helpers instead of restructuring the large stage scripts.

**Tech Stack:** Python 3.10, pytest, existing `scripts/stage2_5_injector.py`, `scripts/stage2_unified_enhancer.py`, `src/datasource/generators/simple_report.py`, and `src/datasource/providers/stage2_structured/cdb_estimator.py`.

---

## Scope Check

This plan intentionally does not build new full external data providers for ETF fund-flow windows, PBoC MLF/RRR scraping, or BCOM historical parsing. Those are separate data-source projects. This plan makes the existing flow more correct and auditable:

- If trend history has prior forex values, Stage2.5 must replace placeholder `daily_change=0.0` with a real previous-session percentage.
- If a forex zero change lacks evidence, Stage4 must not render it as a valid `+0.00%`.
- If CN10Y_CDB is estimated, Stage2 must support explicit spread provenance as structured metadata, not only a bare flat number.
- If Stage2 leaves `manual_required`, the summary log must say which layer failed for each key.

## File Structure

- Modify: `scripts/stage2_5_injector.py`
  - Responsibility: merge manual/Stage2.5 data and backfill report-facing window fields from `data/trend_history`.
  - Add forex-specific zero-placeholder detection so `daily_change=0.0` is overwritten only when it lacks evidence.

- Modify: `src/datasource/generators/simple_report.py`
  - Responsibility: render market data into the final Markdown report.
  - Add a defensive formatter for forex change cells so unreliable zeroes render as `N/A` and pending trends render as `待补变化`.

- Modify: `src/datasource/providers/stage2_structured/cdb_estimator.py`
  - Responsibility: estimate 10Y CDB yield from CN10Y plus an explicitly sourced spread.
  - Accept nested metadata provenance fields and preserve source URL/date/note in the output diagnostics.

- Modify: `scripts/stage2_unified_enhancer.py`
  - Responsibility: run Stage2 tasks and produce logs/summaries.
  - Add `manual_required_details` so daily operators can see whether a gap came from structured provider fallback, retrieval miss, extraction failure, policy gate, or writeback miss.

- Modify tests:
  - `tests/test_websearch_injector.py`
  - `tests/test_simple_report_integration.py`
  - `tests/test_stage2_structured_providers.py`
  - `tests/test_stage2_unified.py`

---

### Task 1: Backfill Placeholder Forex Daily Changes In Stage2.5

**Files:**
- Modify: `scripts/stage2_5_injector.py:3352-3588`
- Test: `tests/test_websearch_injector.py`

- [ ] **Step 1: Write the failing test for replacing untrusted forex zeroes**

Append this test after `test_merge_forex_entry_uses_prev_session_change_for_daily` in `tests/test_websearch_injector.py`:

```python
def test_backfill_trend_changes_replaces_untrusted_zero_forex_daily_change(monkeypatch):
    market_data = {
        "metadata": {"date": "2026-06-03"},
        "bonds": [],
        "forex": [
            {
                "pair": "USDCNY",
                "name": "USD/CNY在岸",
                "current_rate": 6.8184,
                "daily_change": 0.0,
                "change_120d": 0.0,
                "trend": "待获取",
                "source": "structured",
                "note": "structured_provider:official_china",
            }
        ],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
        "macro_indicators": {},
        "monetary_policy": {},
    }

    def _fake_hist(*args, **kwargs):
        return {
            "change_5d": None,
            "change_120d": -4.18,
            "reason_5d": None,
            "reason_120d": None,
            "base_5d_estimated": False,
            "base_120d_estimated": False,
        }

    def _fake_daily_hist(*args, **kwargs):
        return {
            "change_1d": 0.024938753355723306,
            "reason_1d": None,
            "base_1d_estimated": False,
            "base_1d_date": "2026-06-01",
        }

    monkeypatch.setattr(injector, "_calc_change_from_trend_history", _fake_hist)
    monkeypatch.setattr(injector, "_calc_daily_change_from_trend_history", _fake_daily_hist)

    stats = injector._backfill_trend_changes(market_data)

    fx = market_data["forex"][0]
    assert stats["forex"] == 2
    assert fx["daily_change"] == pytest.approx(0.02)
    assert fx["daily_change_basis"] == "trend_history"
    assert fx["daily_change_base_date"] == "2026-06-01"
    assert fx["change_120d"] == pytest.approx(-4.18)
```

- [ ] **Step 2: Write the failing test for preserving explicit zeroes**

Append this second test after the previous one:

```python
def test_backfill_trend_changes_preserves_explicit_zero_forex_daily_change(monkeypatch):
    market_data = {
        "metadata": {"date": "2026-06-03"},
        "bonds": [],
        "forex": [
            {
                "pair": "USDCNY",
                "name": "USD/CNY在岸",
                "current_rate": 6.8184,
                "daily_change": 0.0,
                "daily_change_basis": "direct_daily_series",
                "daily_change_base_date": "2026-06-02",
                "change_120d": None,
                "trend": "横盘震荡",
                "source": "structured",
            }
        ],
        "commodities": [],
        "stock_indices": [],
        "fund_flow": {},
        "macro_indicators": {},
        "monetary_policy": {},
    }

    def _fake_hist(*args, **kwargs):
        return {
            "change_5d": None,
            "change_120d": -4.18,
            "reason_5d": None,
            "reason_120d": None,
            "base_5d_estimated": False,
            "base_120d_estimated": False,
        }

    def _fake_daily_hist(*args, **kwargs):
        return {
            "change_1d": 0.03,
            "reason_1d": None,
            "base_1d_estimated": False,
            "base_1d_date": "2026-06-01",
        }

    monkeypatch.setattr(injector, "_calc_change_from_trend_history", _fake_hist)
    monkeypatch.setattr(injector, "_calc_daily_change_from_trend_history", _fake_daily_hist)

    stats = injector._backfill_trend_changes(market_data)

    fx = market_data["forex"][0]
    assert stats["forex"] == 1
    assert fx["daily_change"] == pytest.approx(0.0)
    assert fx["daily_change_basis"] == "direct_daily_series"
    assert fx["daily_change_base_date"] == "2026-06-02"
    assert fx["change_120d"] == pytest.approx(-4.18)
```

- [ ] **Step 3: Run the tests and verify they fail**

Run:

```bash
bash -lc "source .venv/bin/activate && pytest -q tests/test_websearch_injector.py::test_backfill_trend_changes_replaces_untrusted_zero_forex_daily_change tests/test_websearch_injector.py::test_backfill_trend_changes_preserves_explicit_zero_forex_daily_change"
```

Expected: the first test fails because `_backfill_trend_changes()` currently only fills `daily_change` when it is `None`, and leaves untrusted `0.0` unchanged.

- [ ] **Step 4: Add forex daily-change evidence helpers**

Add these helpers below `_should_backfill_numeric()` in `scripts/stage2_5_injector.py`:

```python
FOREX_DAILY_CHANGE_SOURCE_MARKERS = (
    "direct_daily_series",
    "direct_window",
    "trend_history",
    "trend_history_direct_window",
    "trend_history_full_window",
    "fx_daily",
    "previous_value",
    "previous_rate",
    "change_1d",
)


def _entry_text(entry: Dict[str, Any], fields: Tuple[str, ...]) -> str:
    return " ".join(str(entry.get(field) or "") for field in fields)


def _has_forex_daily_change_evidence(entry: Dict[str, Any]) -> bool:
    explicit_keys = (
        "daily_change_basis",
        "daily_change_source",
        "daily_change_source_url",
        "daily_change_base_date",
        "daily_change_base_price",
    )
    if any(entry.get(key) not in (None, "") for key in explicit_keys):
        return True
    evidence_text = _entry_text(entry, ("source", "note", "manual_reason")).lower()
    return any(marker in evidence_text for marker in FOREX_DAILY_CHANGE_SOURCE_MARKERS)


def _should_backfill_forex_daily_change(entry: Dict[str, Any]) -> bool:
    value = _coerce_float(entry.get("daily_change"))
    if value is None:
        return True
    if abs(value) >= 1e-9:
        return False
    return not _has_forex_daily_change_evidence(entry)
```

Make sure `Tuple` is already imported from `typing`. If it is not imported, update the import line to include it:

```python
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
```

- [ ] **Step 5: Use the helper in `_backfill_trend_changes()`**

Replace the forex daily-change block in `scripts/stage2_5_injector.py`:

```python
        if fx.get("daily_change") is None:
            if daily_hist.get("change_1d") is not None:
                fx["daily_change"] = round(float(daily_hist["change_1d"]), 2)
                stats["forex"] += 1
                used_hist_1d = True
            else:
                fx["daily_change"] = None
                reason = daily_hist.get("reason_1d") or "trend_history_missing"
                _record_backfill_issue(metadata, "forex", symbol, "daily_change", reason)
                _append_note(fx, f"reason={reason}")
```

with:

```python
        if _should_backfill_forex_daily_change(fx):
            if daily_hist.get("change_1d") is not None:
                fx["daily_change"] = round(float(daily_hist["change_1d"]), 2)
                fx["daily_change_basis"] = "trend_history"
                if daily_hist.get("base_1d_date"):
                    fx["daily_change_base_date"] = daily_hist["base_1d_date"]
                stats["forex"] += 1
                used_hist_1d = True
            else:
                fx["daily_change"] = None
                reason = daily_hist.get("reason_1d") or "trend_history_missing"
                _record_backfill_issue(metadata, "forex", symbol, "daily_change", reason)
                _append_note(fx, f"reason={reason}")
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
bash -lc "source .venv/bin/activate && pytest -q tests/test_websearch_injector.py::test_merge_forex_entry_uses_prev_session_change_for_daily tests/test_websearch_injector.py::test_backfill_trend_changes_replaces_untrusted_zero_forex_daily_change tests/test_websearch_injector.py::test_backfill_trend_changes_preserves_explicit_zero_forex_daily_change"
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add scripts/stage2_5_injector.py tests/test_websearch_injector.py
git commit -m "fix: backfill placeholder forex daily changes"
```

Expected: commit succeeds with only those two files staged.

---

### Task 2: Render Forex Zero Changes Defensively In Reports

**Files:**
- Modify: `src/datasource/generators/simple_report.py:30-70`
- Modify: `src/datasource/generators/simple_report.py:1011-1028`
- Test: `tests/test_simple_report_integration.py`

- [ ] **Step 1: Write the failing report test for unreliable zeroes**

Append this test after `test_report_preserves_tushare_usdollar_proxy_label` in `tests/test_simple_report_integration.py`:

```python
def test_report_hides_unreliable_zero_forex_daily_change(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "change_120d": -4.18,
            "trend": "待获取",
            "source": "structured",
            "note": "structured_provider:official_china",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
        "recommendation": "neutral",
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
    assert "| USD/CNY在岸 | 6.8184 | N/A | -4.18% | 待补变化 |" in text
```

- [ ] **Step 2: Write the passing-zero report test**

Append this test after the previous one:

```python
def test_report_keeps_evidenced_zero_forex_daily_change(tmp_path: Path):
    market = _base_market()
    market["forex"] = [
        {
            "pair": "USDCNY",
            "name": "USD/CNY在岸",
            "current_rate": 6.8184,
            "daily_change": 0.0,
            "daily_change_basis": "direct_daily_series",
            "daily_change_base_date": "2026-06-02",
            "change_120d": -4.18,
            "trend": "横盘震荡",
            "source": "structured",
        }
    ]
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.71,
        "recommendation": "neutral",
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
    assert "| USD/CNY在岸 | 6.8184 | +0.00% | -4.18% | 横盘震荡 |" in text
```

- [ ] **Step 3: Run the report tests and verify the first one fails**

Run:

```bash
bash -lc "source .venv/bin/activate && pytest -q tests/test_simple_report_integration.py::test_report_hides_unreliable_zero_forex_daily_change tests/test_simple_report_integration.py::test_report_keeps_evidenced_zero_forex_daily_change"
```

Expected: `test_report_hides_unreliable_zero_forex_daily_change` fails because the current report renders `+0.00%` and keeps `待获取`.

- [ ] **Step 4: Add forex formatter helpers**

Add these constants and helpers below `DAILY_POLICY_KEYS` in `src/datasource/generators/simple_report.py`:

```python
FX_CHANGE_UNAVAILABLE_TEXT = "待补变化"
FX_ZERO_CHANGE_MISSING_MARKERS = (
    "source_latest_only",
    "no_previous_value",
    "manual_incomplete",
    "latest only",
    "no previous",
    "待获取",
    "待 websearch",
    "待mcp",
)
FX_CHANGE_SOURCE_MARKERS = (
    "direct_daily_series",
    "direct_window",
    "trend_history",
    "trend_history_direct_window",
    "trend_history_full_window",
    "fx_daily",
    "previous_value",
    "change_rate",
)
FX_PENDING_TREND_MARKERS = (
    "未知",
    "待",
    "pending",
    "unknown",
)
```

Add these helper functions below `_fmt_change_cell()`:

```python
def _entry_text(entry: dict, fields: tuple[str, ...]) -> str:
    return " ".join(str(entry.get(field) or "") for field in fields)


def _has_fx_change_source(entry: dict, field: str) -> bool:
    field_source_keys = (
        f"{field}_source",
        f"{field}_source_url",
        f"{field}_window_evidence",
        f"{field}_basis",
        f"{field}_base_date",
    )
    if any(entry.get(key) not in (None, "") for key in field_source_keys):
        return True
    if field == "change_120d" and entry.get("trend_history_confidence") not in (None, ""):
        return True
    evidence_text = _entry_text(entry, ("source", "note", "manual_reason")).lower()
    return any(marker in evidence_text for marker in FX_CHANGE_SOURCE_MARKERS)


def _is_unreliable_zero_fx_change(entry: dict, field: str) -> bool:
    num = _to_float(entry.get(field))
    if num is None or abs(num) >= 1e-12:
        return False
    quality_text = _entry_text(entry, ("note", "source", "manual_reason")).lower()
    if any(marker in quality_text for marker in FX_ZERO_CHANGE_MISSING_MARKERS):
        return True
    return not _has_fx_change_source(entry, field)


def _format_fx_change_cell(
    entry: dict,
    field: str,
    *,
    digits: int,
    suffix: str,
    low_confidence: bool = False,
) -> tuple[str, bool]:
    if _is_unreliable_zero_fx_change(entry, field):
        return "N/A", True
    text = _fmt_change_cell(
        entry.get(field),
        digits=digits,
        suffix=suffix,
        low_confidence=low_confidence,
    )
    return text, text == "N/A"


def _is_pending_fx_trend(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    return any(marker.lower() in text for marker in FX_PENDING_TREND_MARKERS)


def _format_fx_trend(entry: dict, current_rate: Optional[float], change_unavailable: bool) -> str:
    if current_rate is None:
        return "待 WebSearch"
    trend = _normalize_trend(entry.get("trend"))
    if trend and not _is_pending_fx_trend(trend):
        return trend
    if change_unavailable:
        return FX_CHANGE_UNAVAILABLE_TEXT
    return "N/A"
```

- [ ] **Step 5: Use the formatter in the forex table**

Replace the forex loop body in `src/datasource/generators/simple_report.py`:

```python
        daily_change = _fmt_change_cell(
            forex.get("daily_change"),
            digits=2,
            suffix="%",
            low_confidence=low_confidence,
        )
        change_120d = _fmt_change_cell(
            forex.get("change_120d"),
            digits=2,
            suffix="%",
            low_confidence=low_confidence,
        )
        trend = forex.get("trend") or ("待 WebSearch" if current_rate is None else "未知")
```

with:

```python
        daily_change, daily_unavailable = _format_fx_change_cell(
            forex,
            "daily_change",
            digits=2,
            suffix="%",
            low_confidence=low_confidence,
        )
        change_120d, change_120d_unavailable = _format_fx_change_cell(
            forex,
            "change_120d",
            digits=2,
            suffix="%",
            low_confidence=low_confidence,
        )
        trend = _format_fx_trend(
            forex,
            current_rate,
            daily_unavailable or change_120d_unavailable,
        )
```

- [ ] **Step 6: Run targeted report tests**

Run:

```bash
bash -lc "source .venv/bin/activate && pytest -q tests/test_simple_report_integration.py::test_report_preserves_tushare_usdollar_proxy_label tests/test_simple_report_integration.py::test_report_hides_unreliable_zero_forex_daily_change tests/test_simple_report_integration.py::test_report_keeps_evidenced_zero_forex_daily_change"
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add src/datasource/generators/simple_report.py tests/test_simple_report_integration.py
git commit -m "fix: hide unevidenced forex zero changes"
```

Expected: commit succeeds with only report renderer and report tests staged.

---

### Task 3: Accept Structured CN10Y_CDB Spread Provenance

**Files:**
- Modify: `src/datasource/providers/stage2_structured/cdb_estimator.py:60-151`
- Test: `tests/test_stage2_structured_providers.py`

- [ ] **Step 1: Write the failing metadata provenance test**

Append this test after `test_cdb_estimator_provider_uses_cn10y_proxy_plus_spread` in `tests/test_stage2_structured_providers.py`:

```python
@pytest.mark.asyncio
async def test_cdb_estimator_provider_accepts_structured_metadata_spread():
    provider = CDBEstimatorProvider()
    market_payload = {
        "metadata": {
            "cn10y_cdb_spread": {
                "bp": 7.4,
                "source_url": "https://yield.chinabond.com.cn/cbweb-czb-web/czb/moreInfo?locale=cn_ZH&nameType=1",
                "observed_date": "2026-06-02",
                "note": "10Y国开债活跃券收益率约1.774%，CN10Y为1.7036%",
            }
        },
        "bonds": [
            {
                "symbol": "CN10Y",
                "current_yield": 1.7036,
                "change_5d_bp": -3.69,
                "change_120d_bp": -19.86,
                "date": "2026-06-02",
                "source_url": "https://yield.chinabond.com.cn/cn10y",
            }
        ],
    }

    result = await provider.fetch({"indicator_key": "CN10Y_CDB"}, market_payload, "2026-06-03")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(1.7776)
    assert extraction["source_url"] == "https://yield.chinabond.com.cn/cbweb-czb-web/czb/moreInfo?locale=cn_ZH&nameType=1"
    assert extraction["diagnostics"]["spread_source"] == "metadata.cn10y_cdb_spread.bp"
    assert extraction["diagnostics"]["spread_source_url"] == "https://yield.chinabond.com.cn/cbweb-czb-web/czb/moreInfo?locale=cn_ZH&nameType=1"
    assert extraction["diagnostics"]["spread_observed_date"] == "2026-06-02"
    assert "structured_metadata_spread" in extraction["note"]
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
bash -lc "source .venv/bin/activate && pytest -q tests/test_stage2_structured_providers.py::test_cdb_estimator_provider_accepts_structured_metadata_spread"
```

Expected: fail with `StructuredProviderError: missing_cdb_spread` because only flat `metadata.cn10y_cdb_spread_bp` is currently accepted.

- [ ] **Step 3: Add a provenance object return type**

Modify the import and add this type alias near the top of `src/datasource/providers/stage2_structured/cdb_estimator.py`:

```python
from typing import Any, Dict, Mapping, Optional, Tuple

SpreadProvenance = Dict[str, Any]
```

- [ ] **Step 4: Replace `_spread_bp()` with provenance-aware helpers**

Replace `_spread_bp()` in `src/datasource/providers/stage2_structured/cdb_estimator.py` with:

```python
    def _spread_provenance(
        self,
        task: Mapping[str, Any],
        market_payload: Mapping[str, Any],
    ) -> SpreadProvenance:
        task_spread = self._safe_number(task.get("cdb_spread_bp"))
        if task_spread is not None:
            return {"bp": task_spread, "source": "task.cdb_spread_bp"}

        metadata = market_payload.get("metadata")
        if isinstance(metadata, Mapping):
            structured = metadata.get("cn10y_cdb_spread")
            if isinstance(structured, Mapping):
                structured_bp = self._safe_number(structured.get("bp"))
                if structured_bp is not None:
                    return {
                        "bp": structured_bp,
                        "source": "metadata.cn10y_cdb_spread.bp",
                        "source_url": structured.get("source_url"),
                        "observed_date": structured.get("observed_date"),
                        "note": structured.get("note"),
                    }

            metadata_spread = self._safe_number(metadata.get("cn10y_cdb_spread_bp"))
            if metadata_spread is not None:
                return {"bp": metadata_spread, "source": "metadata.cn10y_cdb_spread_bp"}

        if self.default_spread_bp is not None:
            return {"bp": self.default_spread_bp, "source": "constructor_default_spread_bp"}

        raise StructuredProviderError(
            provider=self.name,
            indicator_key=str(task.get("indicator_key") or ""),
            reason="missing_cdb_spread",
            message="CN10Y_CDB estimator requires explicit CDB spread provenance",
            diagnostics={
                "source_url": self.source_url,
                "required_spread_fields": [
                    "task.cdb_spread_bp",
                    "metadata.cn10y_cdb_spread.bp",
                    "metadata.cn10y_cdb_spread_bp",
                ],
            },
        )
```

- [ ] **Step 5: Use provenance in `fetch()`**

Replace:

```python
        spread_bp, spread_source = self._spread_bp(task, market_payload)
        estimated_yield = round(proxy_yield + spread_bp / 100.0, 4)
```

with:

```python
        spread = self._spread_provenance(task, market_payload)
        spread_bp = float(spread["bp"])
        spread_source = str(spread["source"])
        result_source_url = str(spread.get("source_url") or self.source_url)
        estimated_yield = round(proxy_yield + spread_bp / 100.0, 4)
```

Replace the `note` construction:

```python
        note = (
            "CN10Y_CDB estimated from CN10Y proxy plus configured CDB spread; "
            "cn10y_proxy_change_basis"
        )
```

with:

```python
        note_parts = [
            "CN10Y_CDB estimated from CN10Y proxy plus configured CDB spread",
            "cn10y_proxy_change_basis",
        ]
        if spread_source == "metadata.cn10y_cdb_spread.bp":
            note_parts.append("structured_metadata_spread")
        if spread.get("observed_date"):
            note_parts.append("spread_observed_date={0}".format(spread["observed_date"]))
        if spread.get("note"):
            note_parts.append(str(spread["note"]))
        note = "; ".join(note_parts)
```

Replace the `source_url` argument:

```python
            source_url=self.source_url,
```

with:

```python
            source_url=result_source_url,
```

Replace the diagnostics dictionary with:

```python
            diagnostics={
                "proxy_symbol": "CN10Y",
                "proxy_yield": proxy_yield,
                "spread_bp": spread_bp,
                "spread_source": spread_source,
                "spread_source_url": spread.get("source_url"),
                "spread_observed_date": spread.get("observed_date"),
                "estimated_yield": estimated_yield,
                "estimation_method": "CN10Y plus observed CDB spread",
                "estimation_basis": estimation_basis,
                "source_url": result_source_url,
            },
```

- [ ] **Step 6: Keep old flat metadata behavior covered**

Add this assertion to `test_cdb_estimator_provider_fails_without_explicit_spread`:

```python
    assert "metadata.cn10y_cdb_spread.bp" in exc_info.value.diagnostics["required_spread_fields"]
```

Do not remove the existing assertion for `"task.cdb_spread_bp"`.

- [ ] **Step 7: Run targeted CN10Y_CDB tests**

Run:

```bash
bash -lc "source .venv/bin/activate && pytest -q tests/test_stage2_structured_providers.py::test_cdb_estimator_provider_uses_cn10y_proxy_plus_spread tests/test_stage2_structured_providers.py::test_cdb_estimator_provider_accepts_structured_metadata_spread tests/test_stage2_structured_providers.py::test_cdb_estimator_provider_fails_without_explicit_spread"
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit Task 3**

Run:

```bash
git add src/datasource/providers/stage2_structured/cdb_estimator.py tests/test_stage2_structured_providers.py
git commit -m "feat: accept structured cdb spread provenance"
```

Expected: commit succeeds with only the CDB estimator and its tests staged.

---

### Task 4: Add Per-Key Stage2 Manual Gap Diagnostics

**Files:**
- Modify: `scripts/stage2_unified_enhancer.py:2634-2895`
- Modify: `scripts/stage2_unified_enhancer.py:6818-6905`
- Test: `tests/test_stage2_unified.py`

- [ ] **Step 1: Write the failing diagnostics test**

Append this test after `test_retrieval_diagnostics_separates_search_extract_and_writeback` in `tests/test_stage2_unified.py`:

```python
def test_manual_required_details_classify_failure_layer():
    rows = [
        {
            "indicator_key": "CN10Y_CDB",
            "manual_required": True,
            "manual_reason": "skipped_deepseek:strict_keyword_miss",
            "structured_provider_fallback_reason": "missing_cdb_spread",
            "usable_count_before_extract": 0,
            "result_type": "manual_required",
        },
        {
            "indicator_key": "reserve_ratio",
            "manual_required": True,
            "manual_reason": "Conflicting values; no_value",
            "usable_count_before_extract": 2,
            "result_type": "manual_required",
        },
        {
            "indicator_key": "etf",
            "manual_required": True,
            "manual_reason": "fund_flow_window_missing",
            "usable_count_before_extract": 1,
            "structured_provider_fallback_reason": "policy_gate_blocked",
            "result_type": "manual_required",
        },
    ]

    details = stage2._build_manual_required_details(rows)

    assert details == [
        {
            "key": "CN10Y_CDB",
            "failure_layer": "structured_provider",
            "reason": "skipped_deepseek:strict_keyword_miss",
            "structured_provider_fallback_reason": "missing_cdb_spread",
            "usable_count_before_extract": 0,
            "result_type": "manual_required",
        },
        {
            "key": "reserve_ratio",
            "failure_layer": "extraction",
            "reason": "Conflicting values; no_value",
            "structured_provider_fallback_reason": None,
            "usable_count_before_extract": 2,
            "result_type": "manual_required",
        },
        {
            "key": "etf",
            "failure_layer": "policy_gate",
            "reason": "fund_flow_window_missing",
            "structured_provider_fallback_reason": "policy_gate_blocked",
            "usable_count_before_extract": 1,
            "result_type": "manual_required",
        },
    ]
```

- [ ] **Step 2: Write the summary persistence test**

Append this test after `test_summary_diagnostics_include_failures_without_duplicate_websearch_rows`:

```python
def test_summary_diagnostics_include_manual_required_details():
    failures = [
        {
            "task_id": "manual-cdb",
            "indicator_key": "CN10Y_CDB",
            "manual_required": True,
            "manual_reason": "skipped_deepseek:strict_keyword_miss",
            "structured_provider_fallback_reason": "missing_cdb_spread",
            "usable_count_before_extract": 0,
            "result_type": "manual_required",
        }
    ]

    summary_fields = stage2._build_stage2_summary_diagnostics(
        completed_tasks=[],
        failures=failures,
        websearch_results=[],
        exec_stats={},
    )

    assert summary_fields["manual_required_details"] == [
        {
            "key": "CN10Y_CDB",
            "failure_layer": "structured_provider",
            "reason": "skipped_deepseek:strict_keyword_miss",
            "structured_provider_fallback_reason": "missing_cdb_spread",
            "usable_count_before_extract": 0,
            "result_type": "manual_required",
        }
    ]
```

- [ ] **Step 3: Run the tests and verify they fail**

Run:

```bash
bash -lc "source .venv/bin/activate && pytest -q tests/test_stage2_unified.py::test_manual_required_details_classify_failure_layer tests/test_stage2_unified.py::test_summary_diagnostics_include_manual_required_details"
```

Expected: fail because `_build_manual_required_details()` does not exist and summaries do not include `manual_required_details`.

- [ ] **Step 4: Add failure-layer classification helpers**

Add these functions below `_build_retrieval_diagnostics()` in `scripts/stage2_unified_enhancer.py`:

```python
def _manual_failure_layer(row: Dict[str, Any]) -> str:
    structured_reason = _nested_row_value(row, "structured_provider_fallback_reason")
    manual_reason = str(_nested_row_value(row, "manual_reason") or "")
    usable_count = int(_nested_row_value(row, "usable_count_before_extract") or 0)
    write_back_success = bool(_nested_row_value(row, "write_back_success"))

    if structured_reason == "policy_gate_blocked" or "fund_flow_window_missing" in manual_reason or "estimated_not_allowed" in manual_reason:
        return "policy_gate"
    if structured_reason:
        return "structured_provider"
    if usable_count <= 0:
        return "retrieval"
    if write_back_success is False and _nested_row_value(row, "result_type") == "manual_required":
        return "extraction"
    return "extraction"


def _build_manual_required_details(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in rows:
        if not bool(_nested_row_value(row, "manual_required")):
            continue
        key = (
            _nested_row_value(row, "indicator_key")
            or _nested_row_value(row, "task.indicator_key")
            or _nested_row_value(row, "task_indicator_key")
            or "unknown"
        )
        key_text = str(key)
        if key_text in seen_keys:
            continue
        seen_keys.add(key_text)
        details.append(
            {
                "key": key_text,
                "failure_layer": _manual_failure_layer(row),
                "reason": str(
                    _nested_row_value(row, "manual_reason")
                    or _nested_row_value(row, "extraction.manual_reason")
                    or _nested_row_value(row, "extraction_skipped_reason")
                    or _nested_row_value(row, "extract_skipped_reason")
                    or "manual_required"
                ),
                "structured_provider_fallback_reason": _nested_row_value(row, "structured_provider_fallback_reason"),
                "usable_count_before_extract": int(_nested_row_value(row, "usable_count_before_extract") or 0),
                "result_type": str(_nested_row_value(row, "result_type") or "manual_required"),
            }
        )
    return details
```

- [ ] **Step 5: Include details in summary diagnostics**

Modify `_build_stage2_summary_diagnostics()` so it builds `diagnostic_rows` once:

```python
    diagnostic_rows = _diagnostic_rows_for_summary(completed_tasks, failures, websearch_results)
    retrieval_diagnostics = _build_retrieval_diagnostics(diagnostic_rows)
```

Then add this field to `payload`:

```python
        "manual_required_details": _build_manual_required_details(diagnostic_rows),
```

- [ ] **Step 6: Persist details in the Stage2 log summary**

Add this key to the `summary` dictionary in `scripts/stage2_unified_enhancer.py`:

```python
        "manual_required_details": summary_diagnostics["manual_required_details"],
```

Place it next to:

```python
        "manual_reason_breakdown": summary_diagnostics["manual_reason_breakdown"],
        "manual_required": pending_manual,
```

- [ ] **Step 7: Run targeted Stage2 summary tests**

Run:

```bash
bash -lc "source .venv/bin/activate && pytest -q tests/test_stage2_unified.py::test_retrieval_diagnostics_separates_search_extract_and_writeback tests/test_stage2_unified.py::test_manual_required_details_classify_failure_layer tests/test_stage2_unified.py::test_summary_diagnostics_include_failures_without_duplicate_websearch_rows tests/test_stage2_unified.py::test_summary_diagnostics_include_manual_required_details"
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit Task 4**

Run:

```bash
git add scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "feat: explain stage2 manual gaps"
```

Expected: commit succeeds with only the Stage2 enhancer and its tests staged.

---

### Task 5: Final Verification

**Files:**
- No new files.
- Verify all files changed by Tasks 1-4.

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
bash -lc "source .venv/bin/activate && pytest -q tests/test_websearch_injector.py tests/test_simple_report_integration.py tests/test_stage2_structured_providers.py tests/test_stage2_unified.py"
```

Expected: all selected tests pass. Existing warnings about Pydantic deprecations are acceptable.

- [ ] **Step 2: Run full test suite**

Run:

```bash
bash -lc "source .venv/bin/activate && pytest -q"
```

Expected: all tests pass with the same expected skipped tests and deprecation warnings observed in the clean baseline.

- [ ] **Step 3: Verify worktree status**

Run:

```bash
git status --short --branch
```

Expected:

```text
## codex/stage2-report-hardening
```

If the branch shows only committed changes and no working tree changes, continue.

- [ ] **Step 4: Review commit series**

Run:

```bash
git log --oneline --decorate -5
```

Expected: the latest commits include:

```text
fix: backfill placeholder forex daily changes
fix: hide unevidenced forex zero changes
feat: accept structured cdb spread provenance
feat: explain stage2 manual gaps
```

- [ ] **Step 5: Summarize operator-facing behavior**

Use this exact summary in the implementation handoff:

```text
Implemented Stage2 report hardening:
- Stage2.5 now replaces unevidenced forex daily_change=0.0 placeholders from trend_history when a previous-session value exists.
- Stage4 report rendering hides unevidenced forex zero changes as N/A and marks the trend as 待补变化.
- CN10Y_CDB estimator accepts structured metadata spread provenance and emits source URL/date diagnostics.
- Stage2 logs now include manual_required_details with a per-key failure_layer for manual gaps.
```

Do not claim ETF, MLF, RRR, or BCOM are fully automated by this plan.

---

## Self-Review

- Spec coverage: The plan covers the three diagnosed issues from the 2026-06-03 run: forex daily-change display, CN10Y_CDB acquisition/provenance, and why Stage2 cannot fill every key automatically.
- Placeholder scan: The plan contains no placeholder flags or vague "add tests" instructions; every code-changing step includes the intended code.
- Type consistency: New helpers use existing `Dict[str, Any]`, `Optional`, and pytest patterns already present in the repo. The new CDB metadata shape is explicit: `metadata.cn10y_cdb_spread.bp/source_url/observed_date/note`.
