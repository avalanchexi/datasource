# Stage2 Report Value Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Stage2.5 manual search pressure by making Stage2 queries, candidate selection, and DeepSeek extraction target report-writeable values instead of merely topical search hits.

**Architecture:** Keep the existing Stage1 -> Stage2 -> Stage2.5 contract and the 2026-05-10 Stage2 efficiency baseline. Add report-value hardening inside the existing planner, search profiles, candidate scoring, extraction agent, and diagnostics without relaxing evidence gates or changing Stage2.5 schema.

**Tech Stack:** Python 3, pytest, existing Tavily client, existing DeepSeekExtractionAgent, existing Stage2TaskPlanner, existing JSON run artifacts.

---

## Scope Check

This plan covers one subsystem: Stage2 report-value retrieval and extraction. It intentionally does not alter Stage2.5 manual JSON schema, Stage3 policy gates, Stage4 rendering, Exa fallback defaults, or Tavily daily-run policy.

## Current Status

- Tasks 1-5 have been implemented and committed before the Task 6 documentation pass.
- Task 6 documentation updates cover `AGENTS.md`, `CLAUDE.md`, and this plan handoff.
- The detailed task checklists below preserve the original TDD execution recipe for auditability. They are not the current TODO source after implementation; use this status section plus the final verification checklist in Task 6 for remaining work.
- This Task 6 pass is documentation-only: do not run real Stage2, Tavily, or DeepSeek. Focused pytest, py_compile, `git diff --check`, and `git status --short` remain the final local acceptance commands, but they should be reported separately when actually executed.
- The plan file itself is part of the Task 6 documentation output and should be included in the final docs commit with `AGENTS.md` and `CLAUDE.md`.

## Execution Environment

This plan was authored from a Windows-native Codex worktree, but implementation is expected to run in the Ubuntu project environment through Claude Code. All executable commands in this plan therefore use Ubuntu/bash syntax and the repository wrapper:

```bash
bash run_clean.sh python ...
```

Do not use Windows PowerShell syntax such as `$env:PYTHONPATH=...`, backtick line continuations, or `.\.venv\Scripts\python.exe` when executing this plan in Ubuntu. Before starting Task 1 in a fresh Ubuntu checkout, prepare the environment with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
cp .env.example .env
```

`run_clean.sh` sources `scripts/runtime_env.sh`, activates `.venv/bin/activate`, clears proxy variables, and sets `PYTHONPATH=./src`. If the Ubuntu environment intentionally uses system Python instead of `.venv`, set `ALLOW_SYSTEM_PYTHON=1` explicitly; otherwise `run_clean.sh` should hard fail rather than silently drift.

If Claude Code executes from a separate Ubuntu checkout rather than the Windows-mounted worktree, first copy or commit this plan file into that checkout before starting Task 1. The implementation steps assume the code, tests, `AGENTS.md`, `CLAUDE.md`, and `.env.example` are edited in the same Git working tree where the commands run.

## File Structure

- Modify: `src/datasource/engines/stage2_task_planner.py`
  - Owns run-date and expected-period query context, rendered task metadata, and whether a task should carry monthly period tokens.
- Modify: `src/datasource/config/search_profiles.py`
  - Owns report-value query families, `pmi_production`, bad/good URL patterns, evidence keywords, and profile-level extract policy.
- Modify: `scripts/stage2_unified_enhancer.py`
  - Owns candidate quality scoring, value-evidence diagnostics, Tavily extract policy application, ETF field retry metrics, and Stage2 summary fields.
- Modify: `src/datasource/engines/deepseek_reasoner.py`
  - Owns DeepSeek prompt schema, max token budget, JSON parse failure classification, and extraction result shape.
- Modify: `.env.example`
  - Documents optional `DEEPSEEK_EXTRACT_MAX_TOKENS` for Ubuntu/CI/runtime configuration parity.
- Modify: `tests/test_stage2_unified.py`
  - Owns regression coverage for planner/profile/candidate/ETF behavior.
- Modify: `tests/test_deepseek_defaults.py`
  - Owns regression coverage for DeepSeek token defaults and JSON truncation classification.
- Modify: `AGENTS.md`
  - Documents durable Stage2 operational rules for report-value hardening.
- Modify: `CLAUDE.md`
  - Keeps quick reminders aligned with `AGENTS.md`.

## Task 1: Split Daily Quote and Monthly Period Query Context

**Files:**
- Modify: `tests/test_stage2_unified.py`
- Modify: `src/datasource/engines/stage2_task_planner.py`
- Modify: `src/datasource/config/search_profiles.py`

- [ ] **Step 1: Write failing tests for time context and pmi_production**

Add these tests after `test_task_planner_expands_expected_period_for_query_families` in `tests/test_stage2_unified.py`:

```python
def test_task_planner_does_not_attach_monthly_tokens_to_daily_quotes(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-12"},
        "commodities": [{"symbol": "GC=F", "current_price": None}],
        "forex": [{"pair": "DXY", "current_rate": None}],
        "macro_indicators": {},
        "missing_items": [{"key": "GC=F"}, {"key": "DXY"}],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task_map = {task["indicator_key"]: task for task in planner.build_tasks(payload)}

    assert task_map["GC=F"]["time_context_type"] == "daily_quote"
    assert task_map["DXY"]["time_context_type"] == "daily_quote"
    assert task_map["GC=F"]["expected_period_tokens"] == []
    assert task_map["DXY"]["expected_period_tokens"] == []
    joined = " ".join(task_map["GC=F"]["query_candidates_expanded"])
    assert "2026-05-12" in joined or "2026年5月12日" in joined


def test_task_planner_gives_pmi_production_official_period_profile(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-05-12"},
        "macro_indicators": {
            "pmi_production": {
                "current_value": 50.0,
                "is_stale": True,
                "expected_period": "2026-04",
            }
        },
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == "pmi_production")

    assert task["query_template_id"] == "pmi_production"
    assert task["time_context_type"] == "monthly_period"
    assert "2026-04" in task["expected_period_tokens"]
    assert task["query"] != "pmi_production"
    assert any("生产指数" in query for query in task["query_candidates_expanded"])
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_stage2_unified.py::test_task_planner_does_not_attach_monthly_tokens_to_daily_quotes \
  tests/test_stage2_unified.py::test_task_planner_gives_pmi_production_official_period_profile -q
```

Expected: both tests fail. The first fails because quote tasks still receive monthly `expected_period_tokens`. The second fails because `pmi_production` falls back to `legacy_primary`.

- [ ] **Step 3: Implement time-context helpers in Stage2TaskPlanner**

In `src/datasource/engines/stage2_task_planner.py`, add this constant near the imports:

```python
DAILY_QUOTE_KEYS = {
    "GC=F",
    "CL=F",
    "BZ=F",
    "HG=F",
    "BCOM",
    "GSG",
    "DXY",
    "USDCNY",
    "USDCNH",
    "US10Y",
    "CN10Y",
    "CN10Y_CDB",
    "bdi",
}
```

Replace `_build_query_context()` with:

```python
    def _build_query_context(self, payload: Dict[str, Any]) -> Dict[str, object]:
        meta = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        date_val = meta.get("date") or meta.get("end_date") or meta.get("start_date")
        dt = self._parse_date_value(str(date_val)) if date_val else None
        if not dt:
            dt = datetime.now()
        ref_year = dt.year
        ref_month = dt.month
        ref_day = dt.day
        if ref_month == 1:
            report_year, report_month = ref_year - 1, 12
        else:
            report_year, report_month = ref_year, ref_month - 1
        return {
            "ref_year": ref_year,
            "ref_month": ref_month,
            "ref_month2": f"{ref_month:02d}",
            "ref_day": ref_day,
            "ref_day2": f"{ref_day:02d}",
            "ref_ym": f"{ref_year}{ref_month:02d}",
            "ref_date": dt.strftime("%Y-%m-%d"),
            "ref_date_label": f"{ref_year}年{ref_month}月{ref_day}日",
            "closing_date": dt.strftime("%Y-%m-%d"),
            "closing_date_label": f"{ref_year}年{ref_month}月{ref_day}日",
            "report_year": report_year,
            "report_month": report_month,
            "report_month2": f"{report_month:02d}",
            "report_ym": f"{report_year}{report_month:02d}",
            "expected_year": report_year,
            "expected_month": report_month,
            "expected_month2": f"{report_month:02d}",
            "expected_ym": f"{report_year}{report_month:02d}",
            "expected_period_label": f"{report_year}年{report_month}月",
            "expected_period_range_label": f"{report_year}年1-{report_month}月",
        }
```

Add these methods inside `Stage2TaskPlanner` before `_new_task()`:

```python
    def _time_context_type(self, profile_key: str, indicator_key: str, expected_period: Optional[str]) -> str:
        if expected_period:
            return "monthly_period"
        normalized = profile_key or indicator_key
        return "daily_quote" if normalized in DAILY_QUOTE_KEYS else "monthly_period"

    def _expected_period_tokens_for(
        self,
        time_context_type: str,
        expected_period: Optional[str],
        task_context: Dict[str, object],
    ) -> List[str]:
        if time_context_type == "daily_quote" and not expected_period:
            return []
        tokens = [
            str(task_context.get("expected_period_label") or "").strip(),
            str(task_context.get("expected_period_range_label") or "").strip(),
            f"{task_context.get('expected_year')}年{task_context.get('expected_month2')}月",
            f"{task_context.get('expected_year')}-{task_context.get('expected_month2')}",
        ]
        return [token for token in tokens if token and "None" not in token]
```

In `_new_task()`, replace the inline `expected_period_tokens` block with:

```python
        time_context_type = self._time_context_type(profile_key, indicator_key, expected_period)
        expected_period_tokens = self._expected_period_tokens_for(
            time_context_type,
            expected_period,
            task_context,
        )
```

Add this field to the returned task dictionary after `"force_refresh": trigger_reason == "stale_data",`:

```python
            "time_context_type": time_context_type,
```

- [ ] **Step 4: Add pmi_production search profile**

In `src/datasource/config/search_profiles.py`, add this profile immediately after `pmi_new_orders`:

```python
    "pmi_production": _profile(
        query="中国PMI生产指数 最新公布 国家统计局",
        domains=["stats.gov.cn", "eastmoney.com", "caixin.com"],
        unit="点",
        issuer="国家统计局",
        issuer_aliases=["统计局", "NBS"],
        query_families=[
            {
                "name": "official_nbs_pmi_production_site",
                "queries": [
                    "site:stats.gov.cn {expected_period_label} 制造业 PMI 生产指数",
                    "国家统计局 {expected_period_label} 采购经理指数 生产指数",
                    "中国制造业PMI 生产指数 {expected_period_label} 国家统计局",
                ],
                "preferred_domains": ["stats.gov.cn", "data.stats.gov.cn"],
                "required_keywords": ["PMI", "生产指数", "采购经理指数"],
            }
        ],
        required_keywords=["PMI", "生产指数", "采购经理指数"],
        evidence_keywords=["PMI", "生产指数", "采购经理指数", "国家统计局"],
        good_url_patterns=["stats.gov.cn", "data.stats.gov.cn"],
        bad_url_patterns=["财新", "行业PMI", "地方"],
        report_usage="Stage4 macro table requires national NBS PMI production sub-index for the expected period",
        max_age_days=35,
        **_MACRO_DEFAULTS,
    ),
```

- [ ] **Step 5: Run the Task 1 tests and commit**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_stage2_unified.py::test_task_planner_does_not_attach_monthly_tokens_to_daily_quotes \
  tests/test_stage2_unified.py::test_task_planner_gives_pmi_production_official_period_profile -q
```

Expected: `2 passed`.

Commit:

```bash
git add tests/test_stage2_unified.py src/datasource/engines/stage2_task_planner.py src/datasource/config/search_profiles.py
git commit -m "feat: split stage2 quote and period query context"
```

## Task 2: Make Search Profiles Prefer Report-Writeable Values

**Files:**
- Modify: `tests/test_stage2_unified.py`
- Modify: `src/datasource/config/search_profiles.py`

- [ ] **Step 1: Write failing profile tests**

Add these tests after `test_high_gap_quote_profiles_have_report_quality_patterns`:

```python
def test_daily_quote_profiles_include_run_date_and_value_page_filters():
    quote_keys = ("GC=F", "CL=F", "BZ=F", "HG=F", "BCOM", "GSG", "DXY", "bdi")
    for key in quote_keys:
        profile = SEARCH_PROFILES[key]
        joined_queries = " ".join(
            query
            for family in profile["query_families"]
            for query in family.get("queries", [])
        )
        assert "{closing_date}" in joined_queries or "{closing_date_label}" in joined_queries

    gold_bad = " ".join(SEARCH_PROFILES["GC=F"]["bad_url_patterns"]).lower()
    assert "contract specifications" in gold_bad
    assert "fact card" in gold_bad

    bcom_bad = " ".join(SEARCH_PROFILES["BCOM"]["bad_url_patterns"]).lower()
    assert "target weights" in bcom_bad
    assert "annual rebalance" in bcom_bad


def test_usdcny_extract_policy_uses_official_table_exception():
    profile = SEARCH_PROFILES["USDCNY"]
    assert profile["extract_policy"] == {
        "use_tavily_extract": True,
        "extract_topk": 1,
        "official_domains_only": True,
    }
    assert "chinamoney.com.cn" in profile["good_url_patterns"]
    assert "cfets.com.cn" in profile["good_url_patterns"]
```

- [ ] **Step 2: Run the new profile tests and verify they fail**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_stage2_unified.py::test_daily_quote_profiles_include_run_date_and_value_page_filters \
  tests/test_stage2_unified.py::test_usdcny_extract_policy_uses_official_table_exception -q
```

Expected in the pre-implementation baseline: both tests fail because quote queries still relied on `latest`, and `USDCNY` was snippet-only from the 2026-05-10 optimization.

- [ ] **Step 3: Add date-aware quote families and page filters**

In `_apply_report_usage_profiles()` in `src/datasource/config/search_profiles.py`, add this block before the existing `BCOM` prepend block:

```python
    daily_quote_families = {
        "GC=F": {
            "name": "dated_market_quote",
            "queries": [
                "COMEX gold futures GC=F price {closing_date} closing",
                "COMEX gold futures settlement price {closing_date_label}",
                "site:tradingeconomics.com gold futures {closing_date} price",
            ],
            "bad": ["contract specifications", "fact card", "settlement procedures", "contract specs"],
        },
        "CL=F": {
            "name": "dated_market_quote",
            "queries": [
                "WTI crude oil futures CL=F price {closing_date} closing",
                "NYMEX WTI crude futures settlement price {closing_date_label}",
                "site:tradingeconomics.com crude oil {closing_date} price",
            ],
            "bad": ["contract specifications", "fact card", "settlement procedures", "contract specs"],
        },
        "BZ=F": {
            "name": "dated_market_quote",
            "queries": [
                "Brent crude futures BZ=F price {closing_date} closing",
                "ICE Brent crude futures settlement price {closing_date_label}",
                "site:tradingeconomics.com brent crude oil {closing_date} price",
            ],
            "bad": ["contract specifications", "fact card", "settlement procedures", "contract specs"],
        },
        "HG=F": {
            "name": "dated_market_quote",
            "queries": [
                "COMEX copper futures HG=F price {closing_date} closing",
                "COMEX copper futures settlement price {closing_date_label}",
                "site:tradingeconomics.com copper futures {closing_date} price",
            ],
            "bad": ["contract specifications", "fact card", "settlement procedures", "contract specs"],
        },
        "BCOM": {
            "name": "dated_index_quote",
            "queries": [
                "Bloomberg Commodity Index BCOM level {closing_date}",
                "BCOM:IND Bloomberg Commodity Index quote {closing_date}",
                "Bloomberg Commodity Index current level {closing_date_label}",
            ],
            "bad": ["target weights", "annual rebalance", "2026 weights", "index methodology"],
        },
        "GSG": {
            "name": "dated_etf_quote",
            "queries": [
                "GSG ETF price {closing_date} iShares",
                "iShares GSG ETF market price {closing_date_label}",
                "NYSEARCA GSG last price {closing_date}",
            ],
            "bad": ["fund flows", "net inflow", "net outflow", "AUM change", "holding", "portfolio"],
        },
        "DXY": {
            "name": "dated_index_quote",
            "queries": [
                "DXY US Dollar Index {closing_date} closing level",
                "US Dollar Index DXY current quote {closing_date}",
                "ICE US Dollar Index DXY latest level {closing_date_label}",
            ],
            "bad": ["forecast", "analysis", "outlook", "opinion", "technical analysis"],
        },
        "bdi": {
            "name": "dated_bdi_quote",
            "queries": [
                "Baltic Dry Index BDI {closing_date} latest value",
                "BDI Baltic Dry Index {closing_date_label} points",
                "Trading Economics Baltic Dry Index {closing_date} value",
            ],
            "bad": ["/Circulars/", "/faqs", "market-announcements", "methodology"],
        },
    }
    for key, spec in daily_quote_families.items():
        _prepend_profile_family(
            key,
            {
                "name": spec["name"],
                "queries": spec["queries"],
                "preferred_domains": SEARCH_PROFILES[key]["preferred_domains"],
                "required_keywords": SEARCH_PROFILES[key]["required_keywords"],
                "exclude_keywords": spec["bad"],
            },
        )
        SEARCH_PROFILES[key]["bad_url_patterns"] = _dedupe_preserve(
            list(SEARCH_PROFILES[key].get("bad_url_patterns") or []) + list(spec["bad"])
        )
```

- [ ] **Step 4: Change USDCNY extract policy to official-table exception**

In the existing `SEARCH_PROFILES["USDCNY"].update(...)` block in `_apply_report_usage_profiles()`, replace the `extract_policy` line with:

```python
            "extract_policy": {
                "use_tavily_extract": True,
                "extract_topk": 1,
                "official_domains_only": True,
            },
```

- [ ] **Step 5: Update the old snippet-only quote profile test**

Replace `test_realtime_quote_profiles_use_snippet_extraction_and_small_query_budget()` with:

```python
def test_realtime_quote_profiles_use_small_query_budget_with_usdcny_extract_exception():
    for key in ("BCOM", "GSG", "DXY", "CN10Y_CDB"):
        profile = SEARCH_PROFILES[key]
        assert profile["max_query_candidates"] == 3
        assert profile["extract_policy"]["use_tavily_extract"] is False
        assert profile["extract_policy"]["extract_topk"] == 0

    usdcny = SEARCH_PROFILES["USDCNY"]
    assert usdcny["max_query_candidates"] == 3
    assert usdcny["extract_policy"]["use_tavily_extract"] is True
    assert usdcny["extract_policy"]["extract_topk"] == 1
    assert usdcny["extract_policy"]["official_domains_only"] is True
```

- [ ] **Step 6: Run profile tests and commit**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_stage2_unified.py::test_daily_quote_profiles_include_run_date_and_value_page_filters \
  tests/test_stage2_unified.py::test_usdcny_extract_policy_uses_official_table_exception \
  tests/test_stage2_unified.py::test_realtime_quote_profiles_use_small_query_budget_with_usdcny_extract_exception -q
```

Expected: `3 passed`.

Commit:

```bash
git add tests/test_stage2_unified.py src/datasource/config/search_profiles.py
git commit -m "feat: target stage2 quote searches at report values"
```

## Task 3: Add Value-Evidence Candidate Scoring and Diagnostics

**Files:**
- Modify: `tests/test_stage2_unified.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: Write failing candidate-quality tests**

Add these tests after `test_candidate_query_quality_penalizes_bad_url_patterns_and_prefers_usage_evidence`:

```python
def test_candidate_query_quality_prefers_value_bearing_quote_over_contract_spec():
    task = {
        "indicator_key": "GC=F",
        "preferred_domains": ["cmegroup.com", "tradingeconomics.com"],
        "required_keywords": ["gold", "comex"],
        "exclude_keywords": ["contract specifications", "fact card"],
        "evidence_keywords": ["settlement", "price", "$/oz", "closing"],
        "good_url_patterns": ["tradingeconomics.com/commodity/gold"],
        "bad_url_patterns": ["contractSpecs", "fact-card"],
        "expected_period_tokens": [],
        "issuer": "COMEX/CME",
        "issuer_aliases": ["CME", "COMEX"],
    }
    candidate = {"query": "COMEX gold futures price 2026-05-12 closing", "preferred_domains": task["preferred_domains"]}
    value_snippets = [
        {
            "url": "https://tradingeconomics.com/commodity/gold",
            "title": "Gold futures",
            "content": "COMEX gold futures settled at 4730.70 USD per troy ounce on 2026-05-12.",
            "score": 0.71,
        }
    ]
    spec_snippets = [
        {
            "url": "https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html",
            "title": "Gold Futures Contract Specs",
            "content": "Contract unit is 100 troy ounces. Minimum price fluctuation is 0.10.",
            "score": 0.92,
        }
    ]

    value_quality = _candidate_query_quality(task, candidate, value_snippets)
    spec_quality = _candidate_query_quality(task, candidate, spec_snippets)

    assert value_quality["value_evidence_score"] > 0
    assert spec_quality["value_evidence_score"] == 0
    assert value_quality["quality_score"] > spec_quality["quality_score"]


def test_candidate_query_quality_marks_value_evidence_miss_for_trusted_but_unusable_page():
    task = {
        "indicator_key": "BCOM",
        "preferred_domains": ["bloomberg.com"],
        "required_keywords": ["BCOM", "Bloomberg Commodity Index"],
        "exclude_keywords": ["target weights", "annual rebalance"],
        "evidence_keywords": ["level", "last price", "points"],
        "good_url_patterns": ["bloomberg.com/quote/BCOM:IND"],
        "bad_url_patterns": ["target-weights", "annual-rebalance"],
        "expected_period_tokens": [],
        "issuer": "Bloomberg",
        "issuer_aliases": ["Bloomberg"],
    }
    candidate = {"query": "Bloomberg Commodity Index BCOM level 2026-05-12", "preferred_domains": task["preferred_domains"]}
    snippets = [
        {
            "url": "https://www.bloomberg.com/company/press/bloomberg-commodity-index-2026-target-weights/",
            "title": "Bloomberg Commodity Index 2026 Target Weights",
            "content": "Bloomberg announced target weights for the annual rebalance.",
            "score": 0.88,
        }
    ]

    quality = _candidate_query_quality(task, candidate, snippets)

    assert quality["unusable_reason"] == "value_evidence_miss"
    assert quality["usable_count"] == 0
```

- [ ] **Step 2: Run the candidate-quality tests and verify they fail**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_stage2_unified.py::test_candidate_query_quality_prefers_value_bearing_quote_over_contract_spec \
  tests/test_stage2_unified.py::test_candidate_query_quality_marks_value_evidence_miss_for_trusted_but_unusable_page -q
```

Expected: failures because `_candidate_query_quality()` does not return `value_evidence_score` and does not mark `value_evidence_miss`.

- [ ] **Step 3: Implement value-evidence helper**

In `scripts/stage2_unified_enhancer.py`, add this helper near `_usage_evidence_score()`:

```python
def _value_evidence_score(snippet: Dict[str, Any], task: Dict[str, Any]) -> int:
    blob = _snippet_blob(snippet).lower()
    if not blob:
        return 0
    unit = str(task.get("unit") or "").lower()
    indicator = str(task.get("indicator_key") or "").lower()
    numeric_hits = len(re.findall(r"(?<!\d)(?:\d{1,4}(?:,\d{3})*|\d+)(?:\.\d+)?(?!\d)", blob))
    if numeric_hits == 0:
        return 0
    score = min(numeric_hits, 3)
    if unit and unit.replace("$", "usd") in blob.replace("$", "usd"):
        score += 2
    if any(token in blob for token in ("price", "level", "last", "settle", "settlement", "收盘", "结算", "点位", "报价")):
        score += 2
    if any(token in blob for token in ("contract unit", "minimum price fluctuation", "contract specifications", "fact card", "target weights", "annual rebalance")):
        score -= 4
    if indicator and indicator in blob:
        score += 1
    return max(0, score)
```

- [ ] **Step 4: Wire value-evidence scoring into candidate quality**

In `_candidate_query_quality()`, initialize `value_evidence_score = 0` beside `usage_evidence_score = 0`.

Inside the `for snippet in usable:` loop, add:

```python
        value_score = _value_evidence_score(snippet, task)
        value_evidence_score += value_score
```

When appending `scored_usable`, include:

```python
                "value_score": value_score,
```

When filtering out bad hits, recompute:

```python
        value_evidence_score = sum(int(item["value_score"]) for item in kept)
```

After the strict issuer check and before high-score filtering, add:

```python
    if usable and not unusable_reason and task.get("required_output_fields") and value_evidence_score <= 0:
        unusable_reason = "value_evidence_miss"
        usable = []
```

In `quality_score`, add:

```python
        + value_evidence_score * 18.0
```

In the returned dictionary, add:

```python
        "value_evidence_score": value_evidence_score,
```

- [ ] **Step 5: Add diagnostics counter for value_evidence_miss**

In `_execute_tasks()`, initialize:

```python
    stats.setdefault("value_evidence_drop_count", 0)
```

Where `skip_deepseek_reason` is set from `quality.get("unusable_reason")`, add:

```python
                            if skip_deepseek_reason == "value_evidence_miss":
                                stats["value_evidence_drop_count"] += 1
```

In the `task_for_log` dictionary, add:

```python
                        "value_evidence_score": task_for_log.get("value_evidence_score", 0),
```

In the Stage2 summary dictionary, add:

```python
        "value_evidence_drop_count": exec_stats.get("value_evidence_drop_count", 0),
```

- [ ] **Step 6: Run candidate-quality tests and commit**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_stage2_unified.py::test_candidate_query_quality_prefers_value_bearing_quote_over_contract_spec \
  tests/test_stage2_unified.py::test_candidate_query_quality_marks_value_evidence_miss_for_trusted_but_unusable_page -q
```

Expected: `2 passed`.

Commit:

```bash
git add tests/test_stage2_unified.py scripts/stage2_unified_enhancer.py
git commit -m "feat: score stage2 candidates by value evidence"
```

## Task 4: Harden DeepSeek JSON Schema and Truncation Classification

**Files:**
- Modify: `tests/test_deepseek_defaults.py`
- Modify: `src/datasource/engines/deepseek_reasoner.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing DeepSeek extraction tests**

Add these tests after `test_stage2_cli_uses_parallel_deepseek_defaults` in `tests/test_deepseek_defaults.py`:

```python
def test_deepseek_agent_uses_configurable_extract_max_tokens(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_EXTRACT_MAX_TOKENS", raising=False)
    agent = DeepSeekExtractionAgent(api_key="test-key")
    assert agent.extract_max_tokens == 900

    monkeypatch.setenv("DEEPSEEK_EXTRACT_MAX_TOKENS", "1200")
    agent = DeepSeekExtractionAgent(api_key="test-key")
    assert agent.extract_max_tokens == 1200


def test_deepseek_schema_hint_keeps_non_fund_flow_core_small() -> None:
    hint = DeepSeekExtractionAgent._schema_hint(is_fund_flow=False)
    assert "recent_5d" not in hint
    assert "total_120d" not in hint
    assert "value" in hint
    assert "source_url" in hint
    assert "manual_required" in hint


def test_deepseek_classifies_unterminated_json_as_truncated() -> None:
    exc = json.JSONDecodeError("Unterminated string starting at", '{"value": "abc', 10)
    assert DeepSeekExtractionAgent._json_error_reason(exc) == "deepseek_json_truncated"
```

Add `import json` at the top of `tests/test_deepseek_defaults.py`.

- [ ] **Step 2: Run the DeepSeek tests and verify they fail**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_deepseek_defaults.py::test_deepseek_agent_uses_configurable_extract_max_tokens \
  tests/test_deepseek_defaults.py::test_deepseek_schema_hint_keeps_non_fund_flow_core_small \
  tests/test_deepseek_defaults.py::test_deepseek_classifies_unterminated_json_as_truncated -q
```

Expected: failures because the agent has no `extract_max_tokens`, `_schema_hint`, or `_json_error_reason`.

- [ ] **Step 3: Add token budget and schema helpers**

In `src/datasource/engines/deepseek_reasoner.py`, change `__init__` to:

```python
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek-v4-pro",
        base_url: Optional[str] = None,
        extract_max_tokens: Optional[int] = None,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
        raw_tokens = extract_max_tokens or os.getenv("DEEPSEEK_EXTRACT_MAX_TOKENS") or 900
        try:
            self.extract_max_tokens = max(300, int(raw_tokens))
        except (TypeError, ValueError):
            self.extract_max_tokens = 900
        self._client: Optional[Any] = None
```

Add these static methods before `extract()`:

```python
    @staticmethod
    def _schema_hint(is_fund_flow: bool) -> str:
        fields = [
            '"value": float|null',
            '"unit": str|null',
            '"source_url": str|null',
            '"as_of_date": "YYYY-MM-DD"|null',
            '"report_period": "YYYY-MM"|null',
            '"manual_required": bool',
            '"manual_reason": str|null',
        ]
        if is_fund_flow:
            fields.extend(
                [
                    '"recent_5d": float|null',
                    '"total_120d": float|null',
                    '"trend": "inflow"|"outflow"|"unknown"',
                ]
            )
        return "{" + ", ".join(fields) + "}"

    @staticmethod
    def _json_error_reason(exc: json.JSONDecodeError) -> str:
        text = str(exc).lower()
        if "unterminated string" in text or "expecting value" in text and exc.pos > 0:
            return "deepseek_json_truncated"
        return "deepseek_json_parse_error"
```

- [ ] **Step 4: Use the smaller schema and token budget**

In `extract()`, replace the current `schema_hint = (...)` block with:

```python
        schema_hint = self._schema_hint(is_fund_flow)
```

Replace `max_tokens=650,` with:

```python
                max_tokens=self.extract_max_tokens,
```

Split JSON parsing from network fallback by replacing:

```python
            data = json.loads(content)
```

with:

```python
            try:
                data = json.loads(content)
            except json.JSONDecodeError as exc:
                reason = self._json_error_reason(exc)
                return {
                    "value": None,
                    "unit": unit_hint,
                    "source_url": first_url,
                    "issuer_match": False,
                    "confidence": 0.0,
                    "note": reason,
                    "as_of_date": None,
                    "report_period": None,
                    "manual_required": True,
                    "manual_reason": reason,
                    "recent_5d": None,
                    "total_120d": None,
                    "trend": "unknown",
                }
```

- [ ] **Step 5: Document the optional token setting**

In `.env.example`, below `DEEPSEEK_MODEL=deepseek-v4-pro`, add:

```bash
# Optional: max tokens for Stage2 DeepSeek extraction JSON output.
DEEPSEEK_EXTRACT_MAX_TOKENS=900
```

- [ ] **Step 6: Run DeepSeek tests and commit**

Run:

```bash
bash run_clean.sh python -m pytest \
  tests/test_deepseek_defaults.py::test_deepseek_agent_uses_configurable_extract_max_tokens \
  tests/test_deepseek_defaults.py::test_deepseek_schema_hint_keeps_non_fund_flow_core_small \
  tests/test_deepseek_defaults.py::test_deepseek_classifies_unterminated_json_as_truncated -q
```

Expected: `3 passed`.

Commit:

```bash
git add tests/test_deepseek_defaults.py src/datasource/engines/deepseek_reasoner.py .env.example
git commit -m "feat: harden deepseek stage2 extraction schema"
```

## Task 5: Improve ETF Field Retry Observability

**Files:**
- Modify: `tests/test_stage2_unified.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: Extend the existing ETF field retry test**

In `test_execute_tasks_etf_field_retry_fills_missing_windows`, add a `stats` dictionary before calling `_execute_tasks()`:

```python
    stats = {}
```

Pass it into `_execute_tasks()`:

```python
            stats=stats,
```

Add these assertions after the existing payload assertions:

```python
    assert stats["field_retry_count"] == 2
    assert stats["field_retry_merged_count"] == 2
    assert stats["field_retry_missing_fields"]["etf"] == ["recent_5d", "total_120d"]
```

- [ ] **Step 2: Run the ETF test and verify it fails**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage2_unified.py::test_execute_tasks_etf_field_retry_fills_missing_windows -q
```

Expected: failure on missing `field_retry_merged_count` and `field_retry_missing_fields`.

- [ ] **Step 3: Add retry metrics**

In `_execute_tasks()`, after `stats.setdefault("field_retry_count", 0)`, add:

```python
    stats.setdefault("field_retry_merged_count", 0)
    stats.setdefault("field_retry_missing_fields", {})
```

Inside `_retry_fund_flow_fields()`, after `missing_fields` is populated and before `field_attempts`, add:

```python
        stats["field_retry_missing_fields"][task["indicator_key"]] = list(missing_fields)
```

After `extraction[field_scope] = value`, add:

```python
            stats["field_retry_merged_count"] += 1
```

In the Stage2 summary dictionary, add:

```python
        "field_retry_merged_count": exec_stats.get("field_retry_merged_count", 0),
        "field_retry_missing_fields": exec_stats.get("field_retry_missing_fields", {}),
```

- [ ] **Step 4: Run ETF test and commit**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage2_unified.py::test_execute_tasks_etf_field_retry_fills_missing_windows -q
```

Expected: `1 passed`.

Commit:

```bash
git add tests/test_stage2_unified.py scripts/stage2_unified_enhancer.py
git commit -m "feat: expose stage2 field retry merge metrics"
```

## Task 6: Documentation and Final Verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/plans/2026-05-13-stage2-report-value-hardening.md`

- [x] **Step 1: Update AGENTS.md Stage2 rules**

In `AGENTS.md`, section `6. Stage2 搜索/抽取规则`, add these bullets near the existing query-profile and diagnostics bullets:

```markdown
- 日频 quote 类任务（商品、DXY、BDI、BCOM/GSG 等）使用 `closing_date/ref_date` 模板，不继承宏观 `expected_period_tokens`；月度宏观/政策任务才使用 `expected_period/report_period` 期次 token。
- Stage2 候选排序以报告可写值为目标：可信域名、关键词和 issuer 命中后，还要优先包含目标单位、日期/期次和可解析数字的片段；规格页、fact card、年度权重公告、预测/分析页应通过 `bad_url_patterns` 或 `value_evidence_miss` 降级。
- `USDCNY` 是 quote profile 的受控例外：为了读取 ChinaMoney/CFETS 表格页，可对官方候选启用 Tavily extract top1；其他 noisy quote profile 仍默认 snippet-only。
- DeepSeek JSON 解析失败需区分 `deepseek_json_truncated` 与普通 `no_value`，避免把模型输出截断误判为网页无数据。
- ETF 主抽取缺 `recent_5d` 或 `total_120d` 时必须触发 field-level retry，并在 summary 中记录 `field_retry_merged_count` 与 `field_retry_missing_fields`。
```

- [x] **Step 2: Update CLAUDE.md quick reminders**

In `CLAUDE.md`, add the concise reminder under the Stage2 high-frequency notes:

```markdown
- Stage2 quote 搜索看 `time_context_type`：`daily_quote` 不带宏观月度 token，`monthly_period` 才带 `expected_period_tokens`。若 `retrieval_hit` 高但写回低，优先看 `value_evidence_miss`、`deepseek_json_truncated`、`field_retry_merged_count`。
```

- [ ] **Step 3: Run focused regression tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage2_unified.py tests/test_deepseek_defaults.py -q
```

Expected: all tests pass. The baseline before this plan was `62 passed, 1 warning`; after implementation the count increases by the new tests and keeps a single Pydantic deprecation warning unless unrelated dependencies change it. This documentation-only Task 6 pass does not run Tavily, DeepSeek, or real Stage2.

- [ ] **Step 4: Run syntax checks**

Run:

```bash
bash run_clean.sh python -m py_compile \
  src/datasource/engines/stage2_task_planner.py \
  src/datasource/config/search_profiles.py \
  scripts/stage2_unified_enhancer.py \
  src/datasource/engines/deepseek_reasoner.py
```

Expected: command exits 0 with no output.

- [ ] **Step 5: Inspect final diff**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` exits 0. `git status --short` lists only the files in this plan.

- [ ] **Step 6: Commit documentation and verification**

Commit docs and any final test-only adjustments:

```bash
git add AGENTS.md CLAUDE.md tests/test_stage2_unified.py tests/test_deepseek_defaults.py
git add docs/superpowers/plans/2026-05-13-stage2-report-value-hardening.md
git commit -m "docs: document stage2 report value hardening"
```

If there are no doc-only, plan, or test-only changes left at this point, skip this commit and record in the handoff that Task 6 verification passed with no final commit needed. If the operator requested no commit, leave changes uncommitted and report the modified files.

## Self-Review

Spec coverage:

- Daily quote vs monthly period context is covered by Task 1.
- `pmi_production` profile is covered by Task 1.
- Date-aware quote queries, concept-page filters, and USDCNY official extract exception are covered by Task 2.
- Value-bearing candidate scoring and diagnostics are covered by Task 3.
- DeepSeek schema reduction, configurable token budget, and JSON truncation classification are covered by Task 4.
- ETF field retry observability is covered by Task 5.
- Durable operator documentation and regression verification are covered by Task 6.

Placeholder scan:

- The plan contains no unresolved placeholder markers, no unspecified test command, and no code step without a concrete snippet.

Type consistency:

- New planner field is consistently named `time_context_type`.
- New quality field is consistently named `value_evidence_score`.
- New skip reason is consistently named `value_evidence_miss`.
- New DeepSeek reasons are consistently named `deepseek_json_truncated` and `deepseek_json_parse_error`.
- New ETF metrics are consistently named `field_retry_merged_count` and `field_retry_missing_fields`.
