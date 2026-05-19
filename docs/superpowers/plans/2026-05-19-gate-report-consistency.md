# Gate Report Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Stage2.5, Stage3, Stage4, and docs consistently treat extrapolated fund-flow values as estimates while keeping allowlisted BDI/CN10Y_CDB estimates visible and dated.

**Architecture:** Add conservative fund-flow source/window classification in Stage2.5, then carry that metadata through the shared pipeline quality state. Stage3 and Stage4 continue using the shared quality state, while `simple_report` renders allowlisted estimates as reportable values instead of placeholders.

**Tech Stack:** Python 3, pytest, JSON pipeline artifacts, existing `run_clean.sh`/`run_preflight.sh` wrappers.

---

## Scope Check

This plan implements the approved `docs/superpowers/specs/2026-05-19-gate-report-consistency-design.md`. It does not change Tavily search profiles, DeepSeek prompts, or add data-source adapters.

## File Structure

- Modify `scripts/stage2_5_injector.py`: classify manual fund-flow source tier and window evidence, then normalize weak fund-flow values to `is_estimated=true`.
- Modify `src/datasource/utils/pipeline_quality_state.py`: attach diagnostic details to estimated fund-flow blockers while preserving existing blocker behavior.
- Modify `src/datasource/generators/simple_report.py`: keep allowlisted estimated macro dates visible and mark estimated fund-flow amounts in the table.
- Modify `tests/test_websearch_injector.py`: cover Stage2.5 fund-flow normalization and trusted direct-window pass-through.
- Modify `tests/test_pipeline_quality_state.py`: cover fund-flow estimated blockers with details.
- Modify `tests/test_stage3_guard.py`: cover Stage3 blocking estimated fund flow even when `allow_estimated=True`.
- Modify `tests/test_simple_report_integration.py`: cover BDI estimated date display and estimated fund-flow table markers.
- Modify `AGENTS.md` and `CLAUDE.md`: document trusted source tiers and the fund-flow estimate rule.

---

### Task 1: Stage2.5 Fund-Flow Source And Window Classification

**Files:**
- Modify: `tests/test_websearch_injector.py`
- Modify: `scripts/stage2_5_injector.py`

- [ ] **Step 1: Write failing tests for weak and trusted fund-flow manual payloads**

Append these tests near the existing fund-flow Stage2.5 tests in `tests/test_websearch_injector.py`, after `test_stage25_preserves_manual_source_url_and_fund_flow_metric_basis`.

```python
def test_apply_fund_flow_entry_forces_news_summary_estimated_when_marked_false():
    entry = {"type": "etf", "recent_5d": None, "total_120d": None}
    payload = {
        "recent_5d": -50.0,
        "total_120d": -9000.0,
        "trend": "流出",
        "source": "新浪财经 ETF季度报告 2026Q1 全市场 ETF 净赎回 9211 亿元",
        "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
        "metric_basis": "news_net_flow",
        "window_evidence": "news_summary",
        "is_estimated": False,
    }

    updated = injector._apply_fund_flow_entry(entry, "etf", payload)

    assert updated is True
    assert entry["recent_5d"] == -50.0
    assert entry["total_120d"] == -9000.0
    assert entry["source_tier"] == "tier3"
    assert entry["window_evidence"] == "news_summary"
    assert entry["metric_basis"] == "news_net_flow"
    assert entry["is_estimated"] is True
    assert entry["estimation_method"] == "fund_flow_manual_window_not_direct"
    assert "fund_flow_estimated_gate" in entry["note"]


def test_apply_fund_flow_entry_keeps_structured_direct_window_not_estimated():
    entry = {"type": "northbound", "recent_5d": None, "total_120d": None}
    payload = {
        "recent_5d": 85.6,
        "total_120d": 1250.0,
        "trend": "流入",
        "source": "东方财富 沪深港通日频净买入序列求和",
        "source_url": "https://data.eastmoney.com/hsgt/hsgtV2.html",
        "metric_basis": "net_flow_sum",
        "window_evidence": "direct_daily_series",
        "is_estimated": False,
    }

    updated = injector._apply_fund_flow_entry(entry, "northbound", payload)

    assert updated is True
    assert entry["recent_5d"] == 85.6
    assert entry["total_120d"] == 1250.0
    assert entry["source_tier"] == "tier2"
    assert entry["window_evidence"] == "direct_daily_series"
    assert entry["metric_basis"] == "net_flow_sum"
    assert entry["is_estimated"] is False
    assert "fund_flow_estimated_gate" not in entry["note"]
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_websearch_injector.py::test_apply_fund_flow_entry_forces_news_summary_estimated_when_marked_false \
  tests/test_websearch_injector.py::test_apply_fund_flow_entry_keeps_structured_direct_window_not_estimated \
  -q
```

Expected: the first test fails because `source_tier`, `window_evidence`, or forced `is_estimated=True` is missing.

- [ ] **Step 3: Add classifier constants and helpers**

In `scripts/stage2_5_injector.py`, add this block after `_default_fund_flow_metric_basis`.

```python
FUND_FLOW_TIER1_DOMAINS = (
    "hkex.com.hk",
    "sse.com.cn",
    "szse.cn",
)
FUND_FLOW_TIER2_DOMAINS = (
    "data.eastmoney.com",
    "eastmoney.com",
    "fund.eastmoney.com",
)
FUND_FLOW_TIER3_DOMAINS = (
    "finance.sina.com.cn",
    "sina.com.cn",
    "stcn.com",
    "cs.com.cn",
    "cls.cn",
    "10jqka.com.cn",
)
FUND_FLOW_DIRECT_WINDOW_EVIDENCE = {
    "direct_window",
    "direct_daily_series",
    "direct_balance_delta",
}
FUND_FLOW_WEAK_WINDOW_EVIDENCE = {
    "news_summary",
    "derived",
    "unknown",
}
FUND_FLOW_ESTIMATED_METRIC_BASIS = {
    "news_net_flow",
    "estimated_net_flow",
}


def _normalize_source_tier(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text in {"tier1", "tier2", "tier3", "unknown"}:
        return text
    return None


def _normalize_window_evidence(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    allowed = FUND_FLOW_DIRECT_WINDOW_EVIDENCE | FUND_FLOW_WEAK_WINDOW_EVIDENCE
    if text in allowed:
        return text
    return None


def _domain_matches(domain: str, suffixes: Any) -> bool:
    return bool(domain) and any(domain == suffix or domain.endswith(f".{suffix}") for suffix in suffixes)


def _infer_fund_flow_source_tier(payload: Dict[str, Any]) -> str:
    explicit = _normalize_source_tier(payload.get("source_tier"))
    if explicit:
        return explicit

    url = _extract_source_url(payload)
    domain = _extract_domain(url)
    if _domain_matches(domain, FUND_FLOW_TIER1_DOMAINS):
        return "tier1"
    if _domain_matches(domain, FUND_FLOW_TIER2_DOMAINS):
        return "tier2"
    if _domain_matches(domain, FUND_FLOW_TIER3_DOMAINS):
        return "tier3"
    return "unknown"


def _infer_fund_flow_window_evidence(key: str, payload: Dict[str, Any], metric_basis: str) -> str:
    explicit = _normalize_window_evidence(payload.get("window_evidence"))
    if explicit:
        return explicit

    metric = str(metric_basis or "").strip().lower()
    if metric == "estimated_net_flow":
        return "derived"
    if metric == "news_net_flow":
        return "news_summary"

    text = " ".join(
        str(payload.get(field) or "")
        for field in ("source", "note", "estimation_method", "description")
    ).lower()
    if any(token in text for token in ("季度", "q1", "q2", "q3", "q4", "年内", "年度", "单日", "外推")):
        return "news_summary"
    if key == "margin" and metric == "balance_delta" and any(token in text for token in ("余额", "balance")):
        return "direct_balance_delta"
    if ("近5日" in text or "5日" in text or "5-day" in text) and ("120" in text or "一百二十" in text):
        return "direct_window"
    return "unknown"


def _fund_flow_has_trusted_window(source_tier: str, window_evidence: str, metric_basis: str) -> bool:
    metric = str(metric_basis or "").strip().lower()
    if metric in FUND_FLOW_ESTIMATED_METRIC_BASIS:
        return False
    if source_tier not in {"tier1", "tier2"}:
        return False
    return window_evidence in FUND_FLOW_DIRECT_WINDOW_EVIDENCE


def _append_note_once(note: str, addition: str) -> str:
    if not addition:
        return note
    if addition in note:
        return note
    if note:
        return f"{note}；{addition}"
    return addition


def _normalize_fund_flow_estimation(entry: Dict[str, Any], payload: Dict[str, Any]) -> None:
    source_tier = str(entry.get("source_tier") or "unknown")
    window_evidence = str(entry.get("window_evidence") or "unknown")
    metric_basis = str(entry.get("metric_basis") or "")
    trusted = _fund_flow_has_trusted_window(source_tier, window_evidence, metric_basis)

    if trusted:
        if "is_estimated" not in payload:
            entry["is_estimated"] = False
        return

    entry["is_estimated"] = True
    entry.setdefault("estimation_method", "fund_flow_manual_window_not_direct")
    note_addition = (
        "fund_flow_estimated_gate:"
        f"source_tier={source_tier},"
        f"window_evidence={window_evidence},"
        f"metric_basis={metric_basis or 'unknown'}"
    )
    entry["note"] = _append_note_once(str(entry.get("note") or ""), note_addition)
```

- [ ] **Step 4: Wire the classifier into `_apply_fund_flow_entry`**

In `scripts/stage2_5_injector.py`, replace the block that starts with `_copy_payload_metadata_fields(` and ends immediately before `if existing_suspicious:` in `_apply_fund_flow_entry` with this exact block.

```python
    entry["metric_basis"] = _default_fund_flow_metric_basis(key, payload)
    entry["source_tier"] = _infer_fund_flow_source_tier(payload)
    entry["window_evidence"] = _infer_fund_flow_window_evidence(
        key,
        payload,
        entry["metric_basis"],
    )
    _normalize_fund_flow_estimation(entry, payload)
    if existing_suspicious:
        entry['note'] = (
            f"覆盖Stage2可疑占位值；{entry['note']}" if entry.get('note') else "覆盖Stage2可疑占位值"
        )
    return True
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_websearch_injector.py::test_apply_fund_flow_entry_forces_news_summary_estimated_when_marked_false \
  tests/test_websearch_injector.py::test_apply_fund_flow_entry_keeps_structured_direct_window_not_estimated \
  tests/test_websearch_injector.py::test_stage25_preserves_manual_source_url_and_fund_flow_metric_basis \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add scripts/stage2_5_injector.py tests/test_websearch_injector.py
git commit -m "fix: normalize manual fund flow estimates"
```

---

### Task 2: Unified Quality State Details And Stage3 Blocking

**Files:**
- Modify: `tests/test_pipeline_quality_state.py`
- Modify: `tests/test_stage3_guard.py`
- Modify: `tests/test_websearch_injector.py`
- Modify: `src/datasource/utils/pipeline_quality_state.py`

- [ ] **Step 1: Add pipeline quality-state test for fund-flow estimate details**

Append this test after `test_pipeline_quality_state_flags_fund_flow_window_missing_for_missing_or_zero_values` in `tests/test_pipeline_quality_state.py`.

```python
def test_pipeline_quality_state_blocks_estimated_fund_flow_with_diagnostics_when_allow_estimated():
    payload = _base_payload()
    payload["fund_flow"] = {
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
    }

    state = build_pipeline_quality_state(payload, allow_estimated=True)

    blocker = next(
        row
        for row in state["quality_blockers"]
        if row["category"] == "fund_flow"
        and row["key"] == "etf"
        and row["reason"] == "estimated_not_allowed"
    )
    assert blocker["details"] == {
        "source_tier": "tier3",
        "window_evidence": "news_summary",
        "metric_basis": "news_net_flow",
    }
    assert state["policy_evaluation"]["block_stage3"] is True
    assert "etf" in state["gap_monitor_view"]["manual_required"]
```

- [ ] **Step 2: Add Stage3 guard test for estimated fund flow**

Append this test after `test_require_data_completeness_does_not_skip_fund_flow_missing_source_url` in `tests/test_stage3_guard.py`.

```python
def test_require_data_completeness_blocks_estimated_fund_flow_even_with_allow_estimated():
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

    with pytest.raises(RuntimeError) as exc:
        s3._require_data_completeness(payload, 0.8, allow_estimated=True)

    assert "fund_flow.etf:estimated_not_allowed" in str(exc.value)
```

- [ ] **Step 3: Update the existing Stage2.5 exact blocker assertion**

In `tests/test_websearch_injector.py`, replace the exact dict membership assertion inside `test_manual_etf_eastmoney_estimate_stays_estimated_and_blocked` with this helper-style assertion.

```python
    blockers = output["metadata"].get("quality_blockers", [])
    etf_blocker = next(
        item
        for item in blockers
        if item.get("category") == "fund_flow"
        and item.get("key") == "etf"
        and item.get("reason") == "estimated_not_allowed"
    )
    assert etf_blocker["details"]["metric_basis"] == "estimated_net_flow"
```

- [ ] **Step 4: Run the focused failing tests**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_pipeline_quality_state.py::test_pipeline_quality_state_blocks_estimated_fund_flow_with_diagnostics_when_allow_estimated \
  tests/test_stage3_guard.py::test_require_data_completeness_blocks_estimated_fund_flow_even_with_allow_estimated \
  -q
```

Expected: the pipeline quality-state test fails because `details` is missing from the `estimated_not_allowed` blocker.

- [ ] **Step 5: Add estimated blocker details to pipeline quality state**

In `src/datasource/utils/pipeline_quality_state.py`, add this helper before `build_pipeline_quality_state`.

```python
def _estimated_issue_details(category: str, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if category != "fund_flow":
        return None
    details: Dict[str, Any] = {}
    for field in ("source_tier", "window_evidence", "metric_basis"):
        value = entry.get(field)
        if value not in (None, ""):
            details[field] = value
    return details or None
```

Then replace the `if entry.get("is_estimated") is True:` block inside `build_pipeline_quality_state` with this version.

```python
        if entry.get("is_estimated") is True:
            allowed, reasons = is_estimated_allowlisted(category, key, entry, rules=rules)
            if not allowed:
                issue = add_issue(
                    category,
                    key,
                    "estimated_not_allowed",
                    details=_estimated_issue_details(category, entry),
                )
                blocker_key = f"{category}.{key}"
                if blocker_key not in estimated_blockers:
                    estimated_blockers.append(blocker_key)
                estimated_blocker_reasons[blocker_key] = reasons
                if issue not in quality_blockers:
                    quality_blockers.append(issue)
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_pipeline_quality_state.py::test_pipeline_quality_state_blocks_estimated_fund_flow_with_diagnostics_when_allow_estimated \
  tests/test_stage3_guard.py::test_require_data_completeness_blocks_estimated_fund_flow_even_with_allow_estimated \
  tests/test_websearch_injector.py::test_manual_etf_eastmoney_estimate_stays_estimated_and_blocked \
  tests/test_websearch_injector.py::test_stage25_preserves_manual_source_url_and_fund_flow_metric_basis \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/datasource/utils/pipeline_quality_state.py tests/test_pipeline_quality_state.py tests/test_stage3_guard.py tests/test_websearch_injector.py
git commit -m "fix: carry fund flow estimate diagnostics through gates"
```

---

### Task 3: Stage4 Report Display For Allowlisted Estimates And Estimated Fund Flow

**Files:**
- Modify: `tests/test_simple_report_integration.py`
- Modify: `src/datasource/generators/simple_report.py`

- [ ] **Step 1: Add report test for BDI estimated date display**

Append this test after `test_quality_gate_does_not_red_flag_estimated_allowlist_items` in `tests/test_simple_report_integration.py`.

```python
def test_report_shows_bdi_estimated_date_instead_of_pending_websearch(tmp_path: Path):
    market = _base_market()
    market["metadata"]["date"] = "2026-05-19"
    market["macro_indicators"] = {
        "bdi": {
            "indicator_name": "BDI",
            "current_value": 2017.0,
            "previous_value": 2031.0,
            "change_rate": -0.69,
            "unit": "points",
            "date": "2026-05-18",
            "source": "websearch_manual(TradingEconomics Baltic Dry Index)",
            "source_url": "https://tradingeconomics.com/commodity/baltic",
            "is_estimated": True,
        }
    }
    pring = {
        "final_stage": "stage 4",
        "confidence": 0.725,
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
    assert "| BDI | 2017.0points(估) | 2031.0points(估) | -0.7points(估) | points | 2026-05-18 |" in text
    assert "N/A（待 WebSearch）" not in text
```

- [ ] **Step 2: Strengthen existing fund-flow appendix test with table markers**

In `tests/test_simple_report_integration.py`, extend `test_report_estimated_appendix_includes_fund_flow_etf` by adding these assertions after reading `text`.

```python
    assert "| ETF资金流 | 85.60(估) | 1250.00(估) | 流入 | fallback estimate | estimated fallback pending official source |" in text
```

- [ ] **Step 3: Run the focused failing tests**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_simple_report_integration.py::test_report_shows_bdi_estimated_date_instead_of_pending_websearch \
  tests/test_simple_report_integration.py::test_report_estimated_appendix_includes_fund_flow_etf \
  -q
```

Expected: the BDI test fails because `_pick_release_date` returns no date for estimated macro entries. The fund-flow test fails because amounts do not include `(估)`.

- [ ] **Step 4: Allow estimated entries to keep explicit dates**

In `src/datasource/generators/simple_report.py`, replace `_is_placeholder_entry` with this version.

```python
def _is_placeholder_entry(entry: dict) -> bool:
    if entry.get("current_value") in (None, "N/A"):
        return True
    source = str(entry.get("source", ""))
    return "待MCP" in source or "待 WebSearch" in source
```

- [ ] **Step 5: Mark estimated fund-flow amounts**

In `src/datasource/generators/simple_report.py`, replace the local `_format_flow_amount` function inside the fund-flow section with this version.

```python
    def _format_flow_amount(value, *, is_estimated=False):
        if value is None:
            return 'N/A'
        suffix = "(估)" if is_estimated else ""
        try:
            return f"{float(value):.2f}{suffix}"
        except Exception:
            return f"{value}{suffix}"
```

Then replace the fund-flow report row loop with this version.

```python
    for key, flow in market_data['fund_flow'].items():
        is_flow_estimated = bool(flow.get("is_estimated"))
        report += (
            f"| {_flow_label(key)} | {_format_flow_amount(flow.get('recent_5d'), is_estimated=is_flow_estimated)} | "
            f"{_format_flow_amount(flow.get('total_120d'), is_estimated=is_flow_estimated)} | {flow.get('trend', 'N/A')} | "
            f"{flow.get('source', '-')} | {flow.get('note', '-') or '-'} |\n"
        )
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_simple_report_integration.py::test_report_shows_bdi_estimated_date_instead_of_pending_websearch \
  tests/test_simple_report_integration.py::test_report_estimated_appendix_includes_fund_flow_etf \
  -q
```

Expected: both selected tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/datasource/generators/simple_report.py tests/test_simple_report_integration.py
git commit -m "fix: render allowlisted estimates consistently"
```

---

### Task 4: Stage2.5 Replay-Style Contract Test For The 2026-05-19 Failure Mode

**Files:**
- Modify: `tests/test_stage25_contract_replay.py`

- [ ] **Step 1: Add replay-style test**

Append this test to `tests/test_stage25_contract_replay.py`.

```python
def test_stage25_20260519_like_fund_flow_extrapolations_do_not_clear_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "data" / "runs" / "20260519"
    run_dir.mkdir(parents=True)
    market_path = run_dir / "market_data_stage2.json"
    manual_path = run_dir / "websearch_results_manual.json"
    output_path = run_dir / "market_data_complete.json"

    market_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "date": "2026-05-19",
                    "data_completeness": 0.9,
                    "missing_items": {"fund_flow": [{"key": "etf"}]},
                },
                "missing_items": ["etf"],
                "macro_indicators": {},
                "monetary_policy": {},
                "bonds": [],
                "forex": [],
                "commodities": [],
                "stock_indices": [],
                "fund_flow": {
                    "etf": {
                        "type": "etf",
                        "recent_5d": None,
                        "total_120d": None,
                        "trend": "待WebSearch补充",
                        "source": "placeholder",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manual_path.write_text(
        json.dumps(
            {
                "fund_flow": {
                    "etf": {
                        "recent_5d": -50.0,
                        "total_120d": -9000.0,
                        "trend": "流出",
                        "source": "新浪财经 ETF季度报告 2026Q1 全市场 ETF 净赎回 9211 亿元",
                        "source_url": "https://finance.sina.com.cn/wm/2026-05-06/doc-inhwxhnr3468401.shtml",
                        "metric_basis": "news_net_flow",
                        "is_estimated": False,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from scripts import stage2_5_injector as injector

    injector.inject_websearch_data(
        market_path,
        manual_path,
        output_path,
        backfill_trend=False,
        disable_trend_history_write=True,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    flow = output["fund_flow"]["etf"]
    blockers = output["metadata"].get("quality_blockers", [])

    assert flow["is_estimated"] is True
    assert flow["source_tier"] == "tier3"
    assert flow["window_evidence"] == "news_summary"
    assert any(
        item.get("category") == "fund_flow"
        and item.get("key") == "etf"
        and item.get("reason") == "estimated_not_allowed"
        for item in blockers
    )

    gap_payload = json.loads((run_dir / "gap_monitor.json").read_text(encoding="utf-8"))
    assert "etf" in gap_payload.get("manual_required", [])
    policy_payload = json.loads((run_dir / "policy_evaluation.json").read_text(encoding="utf-8"))
    assert policy_payload.get("block_stage3") is True
```

- [ ] **Step 2: Run the replay-style test**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_stage25_contract_replay.py::test_stage25_20260519_like_fund_flow_extrapolations_do_not_clear_gate \
  -q
```

Expected: pass after Tasks 1 and 2.

- [ ] **Step 3: Commit Task 4**

```bash
git add tests/test_stage25_contract_replay.py
git commit -m "test: replay fund flow estimate gate"
```

---

### Task 5: Documentation Sync

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update AGENTS.md Stage2.5 rules**

In `AGENTS.md`, add these bullets in section `5.4 Stage2.5 WebSearch/manual 注入`, after the existing bullet that distinguishes official override allowlist from `estimated_allowlist_keys`.

```markdown
- fund_flow 的 `source_url` 只证明来源存在，不自动证明 5日/120日窗口真实可用。只有 Tier1/Tier2 结构化来源且 `window_evidence` 为 `direct_window`、`direct_daily_series` 或 `direct_balance_delta` 时，才允许 `is_estimated=false`。
- fund_flow Tier1 来源包括 HKEX/SSE/SZSE 等官方或交易所结构化入口；Tier2 包括可解析目标窗口的东方财富数据页；新闻、研报、季度/年度摘要和单日描述属于 Tier3，不能把外推窗口标成非估算。
- fund_flow 手工补数若使用 `news_net_flow`、`estimated_net_flow`、单日外推、季度/年度摘要或无法证明目标窗口，Stage2.5 会强制 `is_estimated=true` 并写入 `estimated_not_allowed` blocker；不得为了通过 gate 手工改成 `false`。
```

- [ ] **Step 2: Update AGENTS.md fund-flow standard**

In `AGENTS.md`, add these bullets in section `8. Fund Flow Data Standard`.

```markdown
- `metric_basis=net_flow_sum` 仅用于目标窗口内日频净流入求和；`balance_delta` 用于余额类窗口差值；`news_net_flow` 和 `estimated_net_flow` 均不能作为真实窗口值通过 gate。
- ETF 全市场资金流目前没有稳定官方开放入口；新闻或季度报告可作为备注和估算依据，但默认 `is_estimated=true`。
```

- [ ] **Step 3: Update CLAUDE.md quick reminders**

In `CLAUDE.md`, update the Stage2.5 or gate reminder area by adding this paragraph near the existing `--allow-estimated` explanation.

```markdown
**fund_flow 估算规则**: `source_url` 不等于窗口真实值。北向/南向/ETF/融资融券只有在结构化来源直接覆盖 5日/120日窗口时才能 `is_estimated=false`；新闻、季度/年度摘要、单日外推、`news_net_flow`、`estimated_net_flow` 一律保持估算并由 gate 阻断或降级展示。
```

- [ ] **Step 4: Verify docs contain the new rule**

Run:

```bash
rg -n "fund_flow.*source_url|news_net_flow|estimated_net_flow|窗口真实值" AGENTS.md CLAUDE.md
```

Expected: output includes matches from both `AGENTS.md` and `CLAUDE.md`.

- [ ] **Step 5: Commit Task 5**

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: document fund flow estimate gate"
```

---

### Task 6: Full Focused Verification

**Files:**
- No new file changes expected unless a focused test exposes a mismatch.

- [ ] **Step 1: Run focused test suite for changed behavior**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_websearch_injector.py \
  tests/test_pipeline_quality_state.py \
  tests/test_stage3_guard.py \
  tests/test_simple_report_integration.py \
  tests/test_stage25_contract_replay.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run broader smoke tests**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_stage4_docs.py \
  tests/test_stage2_unified.py \
  tests/test_policy_rules.py \
  tests/test_fix_estimated_verified.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run syntax check for modified modules**

Run:

```bash
bash run_clean.sh python -m py_compile \
  scripts/stage2_5_injector.py \
  scripts/stage3_pring_analyzer.py \
  scripts/stage4_report_generator.py \
  src/datasource/utils/pipeline_quality_state.py \
  src/datasource/generators/simple_report.py
```

Expected: command exits with status 0 and prints no syntax errors.

- [ ] **Step 4: Confirm git status is clean after commits**

Run:

```bash
git status --short
```

Expected: no output.
