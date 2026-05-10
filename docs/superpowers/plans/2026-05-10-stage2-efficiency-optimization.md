# Stage2 Efficiency Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Stage2 runtime and Stage2.5 manual-search pressure while preserving the existing Tavily, DeepSeek, and quality-gate behavior.

**Architecture:** Keep the current Stage2 pipeline shape: task planning stays in `Stage2TaskPlanner`, Tavily search stays first, DeepSeek extraction remains schema-gated, and Stage2.5 remains the fallback for unresolved gaps. The change is limited to safer defaults, a profile-level query budget, tighter search profiles for the delivered high-gap quote indicators (`BCOM`, `GSG`, `USDCNY`, `DXY`, `CN10Y_CDB`), and focused regression tests.

**Tech Stack:** Python, argparse, pytest, existing Tavily client, existing DeepSeek extraction agent, existing Stage2 task planner.

---

## File Structure

- Modify: `tests/test_deepseek_defaults.py`
  - Owns regression coverage for CLI defaults and DeepSeek model defaults.
- Modify: `tests/test_stage2_unified.py`
  - Owns regression coverage for Stage2 query expansion, search profile contracts, and task planner behavior.
- Modify: `scripts/stage2_unified_enhancer.py`
  - Owns CLI defaults, queue execution flags, and query candidate expansion.
- Modify: `src/datasource/config/search_profiles.py`
  - Owns Tavily query families, required evidence, URL quality filters, extract policy, and per-profile search budgets.
- Modify: `src/datasource/engines/stage2_task_planner.py`
  - Copies profile-level search-budget metadata into generated Stage2 tasks.
- Modify: `AGENTS.md`
  - Keeps the documented Stage2 command aligned with the new DeepSeek concurrency default.

## Task 1: Lock DeepSeek Default Concurrency

**Files:**
- Modify: `tests/test_deepseek_defaults.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: Write the failing default-concurrency tests**

Add these tests after `test_stage2_cli_deepseek_timeouts_match_v4_pro_latency` in `tests/test_deepseek_defaults.py`:

```python
def test_stage2_cli_uses_parallel_deepseek_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["stage2_unified_enhancer.py", "--market-data", "market_data.json"],
    )

    args = stage2_unified_enhancer._parse_args()

    assert args.use_queue is True
    assert args.queue_concurrency == 3
    assert args.deepseek_max_concurrency == 3


def test_stage2_cli_can_disable_queue_explicitly(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stage2_unified_enhancer.py",
            "--market-data",
            "market_data.json",
            "--no-use-queue",
        ],
    )

    args = stage2_unified_enhancer._parse_args()

    assert args.use_queue is False
    assert args.queue_concurrency == 3
    assert args.deepseek_max_concurrency == 3
```

- [ ] **Step 2: Run the failing tests**

Run:

```powershell
pytest tests/test_deepseek_defaults.py::test_stage2_cli_uses_parallel_deepseek_defaults tests/test_deepseek_defaults.py::test_stage2_cli_can_disable_queue_explicitly -q
```

Expected before implementation: at least one failure because `use_queue` is currently false by default, `--no-use-queue` is not registered, and `deepseek_max_concurrency` defaults to `1`.

- [ ] **Step 3: Update CLI defaults**

In `scripts/stage2_unified_enhancer.py`, replace the existing `--deepseek-max-concurrency` and `--use-queue` definitions with:

```python
    parser.add_argument("--deepseek-max-concurrency", type=int, default=3, help="DeepSeek并发上限")
```

```python
    parser.add_argument(
        "--use-queue",
        dest="use_queue",
        action="store_true",
        default=True,
        help="开启 extraction 阶段 asyncio.Queue 消费模式（默认开启）",
    )
    parser.add_argument(
        "--no-use-queue",
        dest="use_queue",
        action="store_false",
        help="关闭 extraction 阶段 asyncio.Queue 消费模式，按任务串行抽取",
    )
```

Keep this existing line unchanged:

```python
    parser.add_argument("--queue-concurrency", type=int, default=3, help="Queue 消费者并发数")
```

- [ ] **Step 4: Run the default-concurrency tests again**

Run:

```powershell
pytest tests/test_deepseek_defaults.py::test_stage2_cli_uses_parallel_deepseek_defaults tests/test_deepseek_defaults.py::test_stage2_cli_can_disable_queue_explicitly -q
```

Expected after implementation: both tests pass.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add tests/test_deepseek_defaults.py scripts/stage2_unified_enhancer.py
git commit -m "feat: default stage2 deepseek concurrency to three"
```

Expected: one commit containing only the default-concurrency test and CLI default change.

## Task 2: Add Query Candidate Budget Plumbing

**Files:**
- Modify: `tests/test_stage2_unified.py`
- Modify: `src/datasource/config/search_profiles.py`
- Modify: `src/datasource/engines/stage2_task_planner.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: Write the failing query-budget tests**

In `tests/test_stage2_unified.py`, add these tests after `test_etf_primary_query_family_is_all_market_window_search`:

```python
def test_expand_query_candidates_applies_profile_budget_after_dedup():
    task = {
        "indicator_key": "BCOM",
        "preferred_domains": [],
        "exclude_domains": [],
        "required_keywords": [],
        "exclude_keywords": [],
        "query_families": [
            {"name": "primary", "queries": ["q1", "q2", "q2"]},
            {"name": "fallback", "queries": ["q3", "q4"]},
        ],
        "max_query_candidates": 2,
    }

    candidates = stage2._expand_query_candidates(task)

    assert [item["query"] for item in candidates] == ["q1", "q2"]


def test_expand_query_candidates_does_not_budget_field_scope_queries():
    task = {
        "indicator_key": "etf",
        "preferred_domains": [],
        "exclude_domains": [],
        "required_keywords": [],
        "exclude_keywords": [],
        "field_queries": {
            "recent_5d": ["recent q1", "recent q2"],
            "total_120d": ["total q1"],
        },
        "max_query_candidates": 1,
    }

    candidates = stage2._expand_query_candidates(
        task,
        field_scopes=["recent_5d", "total_120d"],
        include_primary=False,
    )

    assert [item["query"] for item in candidates] == ["recent q1", "recent q2", "total q1"]
```

- [ ] **Step 2: Run the failing query-budget tests**

Run:

```powershell
pytest tests/test_stage2_unified.py::test_expand_query_candidates_applies_profile_budget_after_dedup tests/test_stage2_unified.py::test_expand_query_candidates_does_not_budget_field_scope_queries -q
```

Expected before implementation: the first test fails because `_expand_query_candidates()` currently returns all primary candidates.

- [ ] **Step 3: Extend the search profile schema**

In `src/datasource/config/search_profiles.py`, add this parameter to `_profile()` immediately after `extract_policy`:

```python
    max_query_candidates: int | None = None,
```

Add this field to the dictionary returned by `_profile()` immediately after `"extract_policy": extract_policy or {},`:

```python
        "max_query_candidates": max_query_candidates,
```

- [ ] **Step 4: Carry the profile budget into tasks**

In `src/datasource/engines/stage2_task_planner.py`, add this field to the task dictionary returned by `_new_task()`, immediately after `"extract_policy": profile.get("extract_policy", {}),`:

```python
            "max_query_candidates": profile.get("max_query_candidates"),
```

- [ ] **Step 5: Apply the budget in query expansion**

In `scripts/stage2_unified_enhancer.py`, replace the final line of `_expand_query_candidates()`:

```python
    return _dedupe_candidate_queries(candidates)
```

with:

```python
    deduped = _dedupe_candidate_queries(candidates)
    if include_primary and not field_scopes:
        limit_raw = task.get("max_query_candidates")
        try:
            limit = int(limit_raw) if limit_raw is not None else 0
        except (TypeError, ValueError):
            limit = 0
        if limit > 0 and len(deduped) > limit:
            return deduped[:limit]
    return deduped
```

- [ ] **Step 6: Run the query-budget tests again**

Run:

```powershell
pytest tests/test_stage2_unified.py::test_expand_query_candidates_applies_profile_budget_after_dedup tests/test_stage2_unified.py::test_expand_query_candidates_does_not_budget_field_scope_queries -q
```

Expected after implementation: both tests pass.

- [ ] **Step 7: Commit Task 2**

Run:

```powershell
git add tests/test_stage2_unified.py src/datasource/config/search_profiles.py src/datasource/engines/stage2_task_planner.py scripts/stage2_unified_enhancer.py
git commit -m "feat: add stage2 query candidate budgets"
```

Expected: one commit containing the budget field, planner propagation, query expansion logic, and tests.

## Task 3: Tune High-Gap Tavily Profiles

**Files:**
- Modify: `tests/test_stage2_unified.py`
- Modify: `src/datasource/config/search_profiles.py`

- [ ] **Step 1: Write failing profile-contract tests**

In `tests/test_stage2_unified.py`, add these tests after `test_profiles_expose_report_usage_contract_for_high_risk_tasks`:

```python
def test_realtime_quote_profiles_use_snippet_extraction_and_small_query_budget():
    for key in ("BCOM", "GSG", "USDCNY", "DXY", "CN10Y_CDB"):
        profile = SEARCH_PROFILES[key]

        assert profile["max_query_candidates"] == 3
        assert profile["extract_policy"]["use_tavily_extract"] is False


def test_high_gap_quote_profiles_have_report_quality_patterns():
    bcom = SEARCH_PROFILES["BCOM"]
    assert "BCOM:IND" in bcom["evidence_keywords"]
    assert "bloomberg.com/quote/BCOM:IND" in bcom["good_url_patterns"]
    assert "BCOMX" in bcom["bad_url_patterns"]

    gsg = SEARCH_PROFILES["GSG"]
    assert "iShares S&P GSCI Commodity-Indexed Trust" in gsg["evidence_keywords"]
    assert "ishares.com/us/products" in gsg["good_url_patterns"]
    assert "fund flows" in gsg["bad_url_patterns"]

    usdcny = SEARCH_PROFILES["USDCNY"]
    assert "USD/CNY" in usdcny["evidence_keywords"]
    assert "chinamoney.com.cn" in usdcny["good_url_patterns"]
    assert "bankofchina" in usdcny["bad_url_patterns"]

    dxy = SEARCH_PROFILES["DXY"]
    assert "US Dollar Index" in dxy["evidence_keywords"]
    assert "investing.com/indices/us-dollar-index" in dxy["good_url_patterns"]
    assert "DXY news" in dxy["bad_url_patterns"]

    cn10y_cdb = SEARCH_PROFILES["CN10Y_CDB"]
    assert "CDB" in cn10y_cdb["evidence_keywords"]
    assert "chinabond.com.cn" in cn10y_cdb["good_url_patterns"]
    assert "China 10Y Treasury" in cn10y_cdb["bad_url_patterns"]
```

- [ ] **Step 2: Run the failing profile-contract tests**

Run:

```powershell
pytest tests/test_stage2_unified.py::test_realtime_quote_profiles_use_snippet_extraction_and_small_query_budget tests/test_stage2_unified.py::test_high_gap_quote_profiles_have_report_quality_patterns -q
```

Expected before implementation: failures on `max_query_candidates`, missing URL quality patterns, and existing `use_tavily_extract=True` on these profiles.

- [ ] **Step 3: Add focused BCOM profile tuning**

In `src/datasource/config/search_profiles.py`, inside `_apply_report_usage_profiles()` after the BDI update block and before policy-rate profile rewrites, add:

```python
    _prepend_profile_family(
        "BCOM",
        {
            "name": "bloomberg_index_quote",
            "queries": [
                "BCOM:IND Bloomberg Commodity Index quote latest level",
                "Bloomberg Commodity Index BCOM latest level",
                "BCOM Bloomberg Commodity Index current quote",
            ],
            "preferred_domains": ["bloomberg.com", "tradingeconomics.com", "stockcharts.com"],
            "required_keywords": ["BCOM", "Bloomberg Commodity Index"],
            "exclude_keywords": ["BCOMX", "GCOM", "GSG", "GSCI", "sub-index", "subindex"],
        },
    )
    SEARCH_PROFILES["BCOM"].update(
        {
            "max_query_candidates": 3,
            "evidence_keywords": ["BCOM:IND", "Bloomberg Commodity Index", "BCOM", "level", "last price"],
            "good_url_patterns": ["bloomberg.com/quote/BCOM:IND", "tradingeconomics.com", "stockcharts.com"],
            "bad_url_patterns": ["BCOMX", "GCOM", "GSG", "GSCI", "sub-index", "subindex"],
            "extract_policy": {"use_tavily_extract": False, "extract_topk": 0},
        }
    )
```

- [ ] **Step 4: Add focused GSG profile tuning**

Add this block immediately after the BCOM block:

```python
    _prepend_profile_family(
        "GSG",
        {
            "name": "ishares_current_quote",
            "queries": [
                "iShares S&P GSCI Commodity-Indexed Trust GSG current quote",
                "NYSEARCA GSG iShares S&P GSCI Commodity-Indexed Trust price",
                "GSG ETF latest price iShares BlackRock",
            ],
            "preferred_domains": ["ishares.com", "blackrock.com", "investing.com"],
            "required_keywords": ["GSG", "iShares"],
            "exclude_keywords": ["fund flows", "net inflow", "net outflow", "AUM change"],
        },
    )
    SEARCH_PROFILES["GSG"].update(
        {
            "max_query_candidates": 3,
            "evidence_keywords": ["GSG", "iShares S&P GSCI Commodity-Indexed Trust", "market price", "NAV"],
            "good_url_patterns": ["ishares.com/us/products", "blackrock.com", "investing.com/etfs"],
            "bad_url_patterns": ["fund flows", "net inflow", "net outflow", "AUM change", "holding", "portfolio"],
            "extract_policy": {"use_tavily_extract": False, "extract_topk": 0},
        }
    )
```

- [ ] **Step 5: Add focused USDCNY profile tuning**

Add this block immediately after the GSG block:

```python
    _prepend_profile_family(
        "USDCNY",
        {
            "name": "onshore_current_quote",
            "queries": [
                "USD/CNY onshore spot rate latest China Foreign Exchange Trade System",
                "USD/CNY current rate ChinaMoney latest",
                "USDCNY onshore spot quote latest",
            ],
            "preferred_domains": ["chinamoney.com.cn", "cfets.com.cn", "investing.com", "tradingeconomics.com"],
            "required_keywords": ["USD/CNY", "USDCNY"],
            "exclude_keywords": ["bankofchina", "Bank of China", "cash selling", "bank note", "currency converter"],
        },
    )
    SEARCH_PROFILES["USDCNY"].update(
        {
            "max_query_candidates": 3,
            "evidence_keywords": ["USD/CNY", "USDCNY", "onshore", "spot", "central parity"],
            "good_url_patterns": ["chinamoney.com.cn", "cfets.com.cn", "investing.com/currencies/usd-cny"],
            "bad_url_patterns": ["bankofchina", "boc.cn", "cash selling", "bank note", "currency converter"],
            "extract_policy": {"use_tavily_extract": False, "extract_topk": 0},
        }
    )
```

- [ ] **Step 6: Add focused DXY profile tuning**

Add this block immediately after the USDCNY block:

```python
    _prepend_profile_family(
        "DXY",
        {
            "name": "index_current_quote",
            "queries": [
                "US Dollar Index DXY current quote latest",
                "DXY US Dollar Index latest value Investing.com",
                "ICE US Dollar Index DXY latest level",
            ],
            "preferred_domains": ["investing.com", "tradingeconomics.com", "theice.com", "marketwatch.com"],
            "required_keywords": ["DXY", "US Dollar Index"],
            "exclude_keywords": ["DXY news", "forecast", "analysis", "outlook"],
        },
    )
    SEARCH_PROFILES["DXY"].update(
        {
            "max_query_candidates": 3,
            "evidence_keywords": ["DXY", "US Dollar Index", "latest", "last", "level"],
            "good_url_patterns": [
                "investing.com/indices/us-dollar-index",
                "tradingeconomics.com",
                "marketwatch.com/investing/index/dxy",
            ],
            "bad_url_patterns": ["DXY news", "forecast", "analysis", "outlook", "opinion"],
            "extract_policy": {"use_tavily_extract": False, "extract_topk": 0},
        }
    )
```

- [ ] **Step 7: Add focused CN10Y_CDB profile tuning**

Add this block immediately after the DXY block:

```python
    _prepend_profile_family(
        "CN10Y_CDB",
        {
            "name": "policy_bank_yield_quote",
            "queries": [
                "CDB 10Y bond yield ChinaBond latest",
                "China Development Bank 10 year bond yield latest",
                "policy bank bond 10Y yield China latest",
            ],
            "preferred_domains": ["chinabond.com.cn", "chinamoney.com.cn", "cfets.com.cn", "eastmoney.com"],
            "required_keywords": ["CDB", "10Y", "yield"],
            "exclude_keywords": ["China 10Y Treasury", "government bond", "sovereign bond"],
        },
    )
    SEARCH_PROFILES["CN10Y_CDB"].update(
        {
            "max_query_candidates": 3,
            "evidence_keywords": ["CDB", "China Development Bank", "policy bank", "10Y", "yield"],
            "good_url_patterns": ["chinabond.com.cn", "chinamoney.com.cn", "cfets.com.cn", "eastmoney.com"],
            "bad_url_patterns": ["China 10Y Treasury", "government bond", "sovereign bond", "CN10Y"],
            "extract_policy": {"use_tavily_extract": False, "extract_topk": 0},
        }
    )
```

- [ ] **Step 8: Run the profile-contract tests again**

Run:

```powershell
pytest tests/test_stage2_unified.py::test_realtime_quote_profiles_use_snippet_extraction_and_small_query_budget tests/test_stage2_unified.py::test_high_gap_quote_profiles_have_report_quality_patterns -q
```

Expected after implementation: both tests pass.

- [ ] **Step 9: Commit Task 3**

Run:

```powershell
git add tests/test_stage2_unified.py src/datasource/config/search_profiles.py
git commit -m "feat: tune stage2 high-gap search profiles"
```

Expected: one commit containing only profile-contract tests and profile tuning.

## Task 4: Align Stage2 Documentation

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Update the documented precision-first Stage2 command**

In `AGENTS.md`, in section `5.3 Stage2 Tavily+DeepSeek 增强`, replace:

```bash
  --deepseek-max-concurrency 1 \
```

with:

```bash
  --deepseek-max-concurrency 3 \
```

Leave `--queue-retry-limit 0` unchanged.

- [ ] **Step 2: Update the documented fast补缺 command only if it still invokes DeepSeek**

In the fast mode example, keep this line unchanged because that example uses regex and `--disable-extract`:

```bash
  --deepseek-max-concurrency 1 \
```

Rationale: fast补缺 bypasses DeepSeek extraction, so changing the displayed value there does not reduce runtime and could confuse the intended regex-only path.

- [ ] **Step 3: Commit Task 4**

Run:

```powershell
git add AGENTS.md
git commit -m "docs: document stage2 deepseek concurrency default"
```

Expected: one documentation-only commit.

## Task 5: Run Focused Regression Suite

**Files:**
- Existing files only.

- [ ] **Step 1: Run DeepSeek default tests**

Run:

```powershell
pytest tests/test_deepseek_defaults.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run Stage2 unified tests**

Run:

```powershell
pytest tests/test_stage2_unified.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run Stage2 fallback tests**

Run:

```powershell
pytest tests/test_stage2_fallbacks.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Run Stage2 pipeline tests**

Run:

```powershell
pytest tests/test_stage2_unified_pipeline.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Compile changed modules**

Run:

```powershell
python -m py_compile scripts/stage2_unified_enhancer.py src/datasource/config/search_profiles.py src/datasource/engines/stage2_task_planner.py
```

Expected: no output and exit code `0`.

- [ ] **Step 6: Commit verification note only if the repo uses verification commits**

Do not create a verification-only commit in this repo unless the user explicitly asks for that workflow. Record the exact commands and outcomes in the final response instead.

## Self-Review

**Spec coverage:** DeepSeek default concurrency is covered by Task 1. Tavily keyword and search-task optimization is covered by Tasks 2 and 3. Stage2.5 volume reduction is addressed by tighter report-quality patterns, snippet-only extraction for known Tavily extract 422 profiles, and candidate budgets. Documentation alignment is covered by Task 4. Verification is covered by Task 5.

**Placeholder scan:** This plan contains exact file paths, exact tests, exact implementation snippets, exact commands, and expected outcomes.

**Type consistency:** The new profile key is named `max_query_candidates` in tests, `_profile()`, planner output, and `_expand_query_candidates()`.
