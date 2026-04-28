# Tavily Hit-Rate Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Improve Stage2 Tavily search hit-rate by making keywords and candidate selection match the exact report fields that Stage3/Stage4 consume. A result is successful only when it can provide the value, window, period, unit, and source needed downstream.

**Architecture:** Keep the existing Tavily-first, one-search-run-per-day contract. Add usage-aware metadata to `search_profiles`, propagate it through `Stage2TaskPlanner`, and use it inside `stage2_unified_enhancer` to rank and filter Tavily results after search but before extract/DeepSeek. Do not add extra live Tavily retries in validation.

**Tech Stack:** Python 3.12 project code, pytest, existing Tavily REST adapter, existing Stage2 DeepSeek/regex extraction path, PowerShell on Windows.

---

## Official Tavily Guidance Applied

Tavily docs to keep open while implementing:

- Search API: https://docs.tavily.com/documentation/api-reference/endpoint/search
- Search best practices: https://docs.tavily.com/documentation/best-practices/best-practices-search
- Extract API: https://docs.tavily.com/documentation/api-reference/endpoint/extract
- Extract best practices: https://docs.tavily.com/documentation/best-practices/best-practices-extract
- Examples hub: https://docs.tavily.com/examples/hub

Design translation for this repo:

- Use multiple focused query families and field-specific queries instead of one broad query.
- Keep `time_range`, `topic`, `max_results`, `search_depth`, `include_domains`, and `exclude_domains` explicit per task.
- Post-filter and re-rank by trusted domain, page type, snippet evidence, score, issuer, and period before extraction.
- Extract only from curated URLs. Query-focused Tavily extract is a later adapter enhancement; this plan does not enable more live Tavily consumption.

## File Structure

Modify these files only:

- `src/datasource/config/search_profiles.py`
  - Owns keyword families, field queries, domain preferences, and the new report-usage contract.
- `src/datasource/engines/stage2_task_planner.py`
  - Renders profile metadata into task dictionaries and dedupes alias tasks by profile key.
- `scripts/stage2_unified_enhancer.py`
  - Scores Tavily candidate results with URL/page/evidence signals before extraction.
- `tests/test_stage2_unified.py`
  - Adds regression coverage for profile metadata, planner propagation, use-case scoring, and alias dedupe.

Run unchanged fallback tests:

- `tests/test_stage2_fallbacks.py`

Do not modify:

- `src/datasource/adapters/tavily_client.py`
- `scripts/stage2_5_injector.py`
- `scripts/stage3_pring_analyzer.py`
- `scripts/stage4_report_generator.py`

## Current Failure Model

Past Stage2 failures are not simply bad keywords. Several searches return high `score_max` but still become report misses because the page is not usable for the downstream field:

- Commodity/DXY searches can prefer analysis pages, PDFs, FAQ pages, or ETF marketing pages instead of quote/data pages.
- BDI can hit old Baltic Exchange circular/FAQ pages instead of current index value pages.
- ETF can hit a single fund product article instead of all-market ETF flow windows.
- Industrial indicators can hit local/provincial articles instead of national NBS releases.
- `reserve_ratio` and `rrr` can duplicate a single monetary-policy need.

The implementation must therefore optimize for report usability, not raw Tavily score.

## Task 1: Add Report-Usage Metadata To Profiles And Tasks

- [x] Add failing tests in `tests/test_stage2_unified.py`.

Append these tests near the existing profile/planner tests:

```python
def test_profiles_expose_report_usage_contract_for_high_risk_tasks():
    etf = SEARCH_PROFILES["etf"]
    assert etf["required_output_fields"] == ["recent_5d", "total_120d", "trend"]
    assert "鍏ㄥ競鍦? in etf["evidence_keywords"]
    assert "data.eastmoney.com" in etf["good_url_patterns"]
    assert "caifuhao.eastmoney.com" in etf["bad_url_patterns"]

    bdi = SEARCH_PROFILES["bdi"]
    assert bdi["required_output_fields"] == ["current_value", "previous_value", "change_rate"]
    assert "Baltic Dry Index" in bdi["evidence_keywords"]
    assert "/Circulars/" in bdi["bad_url_patterns"]

    industrial = SEARCH_PROFILES["industrial"]
    assert "鍏ㄥ浗" in industrial["evidence_keywords"]
    assert "stats.gov.cn" in industrial["good_url_patterns"]


def test_task_planner_passes_report_usage_contract_to_task(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-28"},
        "fund_flow": {"etf": {"recent_5d": None, "total_120d": None}},
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    task = next(t for t in planner.build_tasks(payload) if t["indicator_key"] == "etf")

    assert task["required_output_fields"] == ["recent_5d", "total_120d", "trend"]
    assert "鍏ㄥ競鍦? in task["evidence_keywords"]
    assert "data.eastmoney.com" in task["good_url_patterns"]
    assert "caifuhao.eastmoney.com" in task["bad_url_patterns"]
```

- [x] Run the focused tests and confirm they fail for missing metadata keys.

Command:

```powershell
python -m pytest tests/test_stage2_unified.py -q
```

Expected failure:

```text
KeyError: 'required_output_fields'
```

- [x] Extend `_profile` in `src/datasource/config/search_profiles.py`.

Add these parameters to `_profile`:

```python
    required_output_fields: Optional[List[str]] = None,
    evidence_keywords: Optional[List[str]] = None,
    good_url_patterns: Optional[List[str]] = None,
    bad_url_patterns: Optional[List[str]] = None,
    report_usage: Optional[str] = None,
```

Add these keys to the returned dictionary:

```python
        "required_output_fields": list(required_output_fields or []),
        "evidence_keywords": list(evidence_keywords or []),
        "good_url_patterns": list(good_url_patterns or []),
        "bad_url_patterns": list(bad_url_patterns or []),
        "report_usage": report_usage,
```

- [x] Add usage metadata to high-risk profiles in `src/datasource/config/search_profiles.py`.

Use these exact field contracts:

```python
required_output_fields=["current_value", "previous_value", "change_rate"]
```

for `industrial`, `industrial_sales`, and `bdi`.

Use:

```python
required_output_fields=["current_value"]
```

for `USDCNY`, `USDCNH`, `DXY`, `US10Y`, `CN10Y`, `CN10Y_CDB`, `rrr`, `reverse_repo`, and `mlf`.

Use:

```python
required_output_fields=["recent_5d", "total_120d", "trend"]
```

for `northbound`, `southbound`, and `etf`.

Add these exact profile metadata values:

```python
# etf
evidence_keywords=["鍏ㄥ競鍦?, "A鑲TF", "杩?鏃?, "杩?20鏃?, "鍑€娴佸叆", "鍑€娴佸嚭", "绱", "鍚堣", "璧勯噾娴佸悜"],
good_url_patterns=["data.eastmoney.com", "fund.eastmoney.com"],
bad_url_patterns=["caifuhao.eastmoney.com", "/news/", "鍗曞彧", "璐圭巼", "瑙勬ā鍒涙柊楂?],
report_usage="Stage4 fund_flow table requires recent_5d, total_120d, trend, source_url",

# bdi
evidence_keywords=["BDI", "Baltic Dry Index", "latest", "Index", "points", "娉㈢綏鐨勬捣骞叉暎璐ф寚鏁?],
good_url_patterns=["tradingeconomics.com", "investing.com/indices", "data.eastmoney.com/cjsj"],
bad_url_patterns=["/Circulars/", "/faqs", "market-announcements", "2018"],
report_usage="Stage4 macro table and Pring macro score require current_value plus comparable previous/change",

# industrial
evidence_keywords=["鍏ㄥ浗", "鍥藉缁熻灞€", "瑙勬ā浠ヤ笂宸ヤ笟", "澧炲姞鍊?, "鍚屾瘮"],
good_url_patterns=["stats.gov.cn", "data.stats.gov.cn"],
bad_url_patterns=["鐪?, "甯?, "鍦板尯", "鍥尯"],
report_usage="Stage4 macro table requires national NBS period value, not local industrial news",

# industrial_sales
evidence_keywords=["鍏ㄥ浗", "鍥藉缁熻灞€", "瑙勬ā浠ヤ笂宸ヤ笟浼佷笟", "钀ヤ笟鏀跺叆", "鍒╂鼎鎬婚", "鍚屾瘮"],
good_url_patterns=["stats.gov.cn", "data.stats.gov.cn"],
bad_url_patterns=["鐪?, "甯?, "鍦板尯", "鍥尯"],
report_usage="Stage4 macro table requires national industrial-enterprise sales/revenue period value",
```

- [x] Propagate metadata in `src/datasource/engines/stage2_task_planner.py`.

Add these keys to the task returned by `_new_task`:

```python
            "required_output_fields": profile.get("required_output_fields", []),
            "evidence_keywords": profile.get("evidence_keywords", []),
            "good_url_patterns": profile.get("good_url_patterns", []),
            "bad_url_patterns": profile.get("bad_url_patterns", []),
            "report_usage": profile.get("report_usage"),
```

- [x] Re-run tests.

Command:

```powershell
python -m pytest tests/test_stage2_unified.py -q
```

Expected output includes:

```text
passed
```

## Task 2: Score Candidate Results By URL Type And Report Evidence

- [x] Add failing tests in `tests/test_stage2_unified.py`.

Append these tests near the existing `_candidate_query_quality` tests:

```python
def test_candidate_query_quality_penalizes_bad_url_patterns_and_prefers_usage_evidence():
    task = {
        "indicator_key": "etf",
        "preferred_domains": ["data.eastmoney.com", "fund.eastmoney.com", "eastmoney.com"],
        "good_url_patterns": ["data.eastmoney.com", "fund.eastmoney.com"],
        "bad_url_patterns": ["caifuhao.eastmoney.com", "/news/", "鍗曞彧", "璐圭巼"],
        "evidence_keywords": ["鍏ㄥ競鍦?, "A鑲TF", "杩?鏃?, "杩?20鏃?, "鍑€娴佸叆", "绱", "鍚堣"],
    }
    candidate = {"query": "A鑲TF 鍏ㄥ競鍦?杩?鏃?杩?20鏃?鍑€娴佸叆 鍚堣", "preferred_domains": task["preferred_domains"]}
    good_snippets = [
        {
            "url": "https://data.eastmoney.com/fund/etf.html",
            "title": "A鑲TF璧勯噾娴佸悜",
            "content": "鍏ㄥ競鍦篈鑲TF杩?鏃ュ噣娴佸叆85浜垮厓锛岃繎120鏃ョ疮璁″噣娴佸叆1200浜垮厓锛岃祫閲戞祦鍚戝悎璁′负娴佸叆銆?,
            "score": 0.72,
        }
    ]
    noisy_snippets = [
        {
            "url": "https://caifuhao.eastmoney.com/news/202604280001",
            "title": "鍗曞彧ETF瑙勬ā鍒涙柊楂?,
            "content": "鏌愬崟鍙狤TF璐圭巼浼樻儬锛岃妯″垱鏂伴珮锛屾湭鎶湶鍏ㄥ競鍦鸿繎5鏃ユ垨杩?20鏃ュ悎璁″噣娴佸叆銆?,
            "score": 0.96,
        }
    ]

    good = _candidate_query_quality(task, candidate, good_snippets)
    noisy = _candidate_query_quality(task, candidate, noisy_snippets)

    assert good["quality_score"] > noisy["quality_score"]
    assert good["usage_evidence_score"] > noisy["usage_evidence_score"]
    assert noisy["bad_url_hit_count"] >= 1


def test_candidate_query_quality_filters_bdi_old_circular_when_data_page_exists():
    task = {
        "indicator_key": "bdi",
        "preferred_domains": ["tradingeconomics.com", "balticexchange.com"],
        "good_url_patterns": ["tradingeconomics.com"],
        "bad_url_patterns": ["/Circulars/", "2018"],
        "evidence_keywords": ["BDI", "Baltic Dry Index", "latest", "points"],
    }
    candidate = {"query": "BDI Baltic Dry Index latest value", "preferred_domains": task["preferred_domains"]}
    snippets = [
        {
            "url": "https://www.balticexchange.com/en/data-services/market-information0/dry-services/Circulars/2018.html",
            "content": "Baltic Exchange circular archive 2018 for dry services.",
            "score": 0.93,
        },
        {
            "url": "https://tradingeconomics.com/commodity/baltic",
            "content": "Baltic Dry Index latest value is 1350 points with daily change.",
            "score": 0.71,
        },
    ]

    quality = _candidate_query_quality(task, candidate, snippets)

    assert quality["usable_count"] == 1
    assert quality["snippets"][0]["url"] == "https://tradingeconomics.com/commodity/baltic"
    assert quality["bad_url_hit_count"] == 1
```

- [x] Run the focused tests and confirm they fail for missing quality fields.

Command:

```powershell
python -m pytest tests/test_stage2_unified.py -q
```

Expected failure:

```text
KeyError: 'usage_evidence_score'
```

- [x] Implement pattern/evidence helpers in `scripts/stage2_unified_enhancer.py`.

Place these helpers above `_candidate_query_quality`:

```python
def _pattern_hits(value: str, patterns: Optional[List[str]]) -> List[str]:
    text = str(value or "").lower()
    hits: List[str] = []
    for pattern in patterns or []:
        needle = str(pattern or "").strip()
        if needle and needle.lower() in text:
            hits.append(needle)
    return hits


def _usage_evidence_score(snippet: Dict[str, Any], keywords: Optional[List[str]]) -> int:
    blob = _snippet_blob(snippet).lower()
    return sum(1 for keyword in keywords or [] if str(keyword or "").strip().lower() in blob)
```

- [x] Extend `_candidate_query_quality` scoring after the existing domain, keyword, period, and issuer filtering.

Add this logic after `usable` is computed and before `trusted_count`:

```python
    good_url_patterns = candidate.get("good_url_patterns") or task.get("good_url_patterns") or []
    bad_url_patterns = candidate.get("bad_url_patterns") or task.get("bad_url_patterns") or []
    evidence_keywords = candidate.get("evidence_keywords") or task.get("evidence_keywords") or []

    scored_usable: List[Dict[str, Any]] = []
    bad_url_hit_count = 0
    good_url_hit_count = 0
    usage_evidence_score = 0
    for snippet in usable:
        url_blob = f"{snippet.get('url') or ''} {_snippet_blob(snippet)}"
        bad_hits = _pattern_hits(url_blob, bad_url_patterns)
        good_hits = _pattern_hits(url_blob, good_url_patterns)
        evidence_score = _usage_evidence_score(snippet, evidence_keywords)
        bad_url_hit_count += len(bad_hits)
        good_url_hit_count += len(good_hits)
        usage_evidence_score += evidence_score
        scored_usable.append(
            {
                "snippet": snippet,
                "bad_hits": bad_hits,
                "good_hits": good_hits,
                "evidence_score": evidence_score,
            }
        )

    if any(item["bad_hits"] for item in scored_usable) and any(not item["bad_hits"] for item in scored_usable):
        usable = [item["snippet"] for item in scored_usable if not item["bad_hits"]]
        usage_evidence_score = sum(item["evidence_score"] for item in scored_usable if not item["bad_hits"])
        good_url_hit_count = sum(len(item["good_hits"]) for item in scored_usable if not item["bad_hits"])
```

Change the `quality_score` expression to include the new signals:

```python
        + usage_evidence_score * 12.0
        + good_url_hit_count * 25.0
        - bad_url_hit_count * 60.0
```

Add these fields to the returned dict:

```python
        "usage_evidence_score": usage_evidence_score,
        "good_url_hit_count": good_url_hit_count,
        "bad_url_hit_count": bad_url_hit_count,
```

Extend `selected_reason`:

```python
            f"usage_evidence={usage_evidence_score} "
            f"good_url={good_url_hit_count} bad_url={bad_url_hit_count} "
```

- [x] Carry the new diagnostics into candidate attempt metadata.

In `_run_search_candidates`, add these keys to `attempt_meta`:

```python
                    "usage_evidence_score": quality.get("usage_evidence_score"),
                    "good_url_hit_count": quality.get("good_url_hit_count"),
                    "bad_url_hit_count": quality.get("bad_url_hit_count"),
```

Add these keys to `payload`:

```python
                    "usage_evidence_score": quality.get("usage_evidence_score", 0),
                    "good_url_hit_count": quality.get("good_url_hit_count", 0),
                    "bad_url_hit_count": quality.get("bad_url_hit_count", 0),
```

When updating `task_for_log`, add:

```python
                                "usage_evidence_score": best_payload.get("usage_evidence_score", 0),
                                "good_url_hit_count": best_payload.get("good_url_hit_count", 0),
                                "bad_url_hit_count": best_payload.get("bad_url_hit_count", 0),
```

- [x] Re-run tests.

Command:

```powershell
python -m pytest tests/test_stage2_unified.py tests/test_stage2_fallbacks.py -q
```

Expected output includes:

```text
passed
```

## Task 3: Optimize Keywords By Report Usage Scenario

- [x] Add failing tests in `tests/test_stage2_unified.py`.

Append these tests near the profile tests:

```python
def test_fund_flow_profiles_have_field_queries_for_all_report_windows():
    for key in ("northbound", "southbound", "etf"):
        profile = SEARCH_PROFILES[key]
        assert "recent_5d" in profile["field_queries"]
        assert "total_120d" in profile["field_queries"]
        joined = " ".join(profile["field_queries"]["recent_5d"] + profile["field_queries"]["total_120d"])
        assert "杩?鏃? in joined
        assert "120" in joined


def test_policy_profiles_distinguish_current_level_and_operation_notice():
    rrr_families = {family["name"] for family in SEARCH_PROFILES["rrr"]["query_families"]}
    mlf_families = {family["name"] for family in SEARCH_PROFILES["mlf"]["query_families"]}
    reverse_repo_families = {family["name"] for family in SEARCH_PROFILES["reverse_repo"]["query_families"]}

    assert {"current_level", "official_adjustment_notice"}.issubset(rrr_families)
    assert "official_operation_notice" in reverse_repo_families
    assert "multi_price_notice" in mlf_families


def test_macro_profiles_prioritize_national_official_releases():
    industrial = SEARCH_PROFILES["industrial"]["query_families"][0]
    industrial_sales = SEARCH_PROFILES["industrial_sales"]["query_families"][0]

    assert industrial["name"] == "official_nbs_release"
    assert industrial_sales["name"] == "official_nbs_release"
    assert "stats.gov.cn" in industrial["preferred_domains"]
    assert "stats.gov.cn" in industrial_sales["preferred_domains"]
```

- [x] Run tests and confirm failures identify missing families or field queries.

Command:

```powershell
python -m pytest tests/test_stage2_unified.py -q
```

Expected failure examples:

```text
AssertionError: assert 'recent_5d' in {}
AssertionError: assert {'current_level', 'official_adjustment_notice'}...
```

- [x] Update fund-flow profiles in `src/datasource/config/search_profiles.py`.

For `northbound`, add:

```python
field_queries={
    "recent_5d": [
        "鍖楀悜璧勯噾 杩?鏃?鍑€娴佸叆 鍚堣 浜垮厓 涓滄柟璐㈠瘜",
        "{ref_year}骞磠ref_month}鏈?鍖楀悜璧勯噾 杩?鏃?娌繁娓€?鍑€涔板叆 鍚堣 浜垮厓",
    ],
    "total_120d": [
        "鍖楀悜璧勯噾 杩?20鏃?绱鍑€娴佸叆 鍚堣 浜垮厓 涓滄柟璐㈠瘜",
        "{ref_year}骞?鍖楀悜璧勯噾 120鏃?绱鍑€涔板叆 娌繁娓€?浜垮厓",
    ],
},
evidence_keywords=["鍖楀悜璧勯噾", "娌繁娓€?, "杩?鏃?, "杩?20鏃?, "绱", "鍚堣", "鍑€娴佸叆", "鍑€涔板叆"],
good_url_patterns=["data.eastmoney.com", "hkex.com.hk"],
bad_url_patterns=["涓偂", "鍗佸ぇ娲昏穬鑲?, "榫欒檸姒?],
```

For `southbound`, add:

```python
field_queries={
    "recent_5d": [
        "鍗楀悜璧勯噾 杩?鏃?鍑€娴佸叆 鍚堣 浜挎腐鍏?涓滄柟璐㈠瘜",
        "{ref_year}骞磠ref_month}鏈?鍗楀悜璧勯噾 杩?鏃?娓偂閫?鍑€涔板叆 鍚堣 浜挎腐鍏?,
    ],
    "total_120d": [
        "鍗楀悜璧勯噾 杩?20鏃?绱鍑€娴佸叆 鍚堣 浜挎腐鍏?涓滄柟璐㈠瘜",
        "{ref_year}骞?鍗楀悜璧勯噾 120鏃?绱鍑€涔板叆 娓偂閫?浜挎腐鍏?,
    ],
},
evidence_keywords=["鍗楀悜璧勯噾", "娓偂閫?, "杩?鏃?, "杩?20鏃?, "绱", "鍚堣", "鍑€娴佸叆", "鍑€涔板叆"],
good_url_patterns=["data.eastmoney.com", "hkex.com.hk"],
bad_url_patterns=["涓偂", "鍗佸ぇ鎴愪氦鑲?, "榫欒檸姒?],
```

For `etf`, replace the broad queries with all-market field queries:

```python
field_queries={
    "recent_5d": [
        "A鑲TF 鍏ㄥ競鍦?杩?鏃?璧勯噾鍑€娴佸叆 鍚堣 浜垮厓 涓滄柟璐㈠瘜",
        "{ref_year}骞磠ref_month}鏈?A鑲TF 鍏ㄥ競鍦?杩?鏃?璧勯噾娴佸悜 鍑€娴佸叆 鍚堣",
    ],
    "total_120d": [
        "A鑲TF 鍏ㄥ競鍦?杩?20鏃?绱鍑€娴佸叆 鍚堣 浜垮厓 涓滄柟璐㈠瘜",
        "{ref_year}骞?A鑲TF 鍏ㄥ競鍦?120鏃?绱璧勯噾鍑€娴佸叆 鍚堣",
    ],
},
```

- [x] Update macro profiles.

For `industrial`, make the first query family:

```python
{
    "name": "official_nbs_release",
    "queries": [
        "鍥藉缁熻灞€ {expected_year}骞磠expected_month}鏈?瑙勬ā浠ヤ笂宸ヤ笟澧炲姞鍊?鍚屾瘮 鍏ㄥ浗",
        "stats.gov.cn {expected_year}骞磠expected_month}鏈?瑙勬ā浠ヤ笂宸ヤ笟澧炲姞鍊?鍚屾瘮",
    ],
    "preferred_domains": ["stats.gov.cn", "data.stats.gov.cn"],
    "required_keywords": ["瑙勬ā浠ヤ笂宸ヤ笟", "澧炲姞鍊?, "鍚屾瘮"],
}
```

For `industrial_sales`, make the first query family:

```python
{
    "name": "official_nbs_release",
    "queries": [
        "鍥藉缁熻灞€ {expected_year}骞?-{expected_month}鏈?瑙勬ā浠ヤ笂宸ヤ笟浼佷笟 钀ヤ笟鏀跺叆 鍚屾瘮",
        "stats.gov.cn {expected_year}骞?-{expected_month}鏈?瑙勬ā浠ヤ笂宸ヤ笟浼佷笟 鍒╂鼎 钀ヤ笟鏀跺叆",
    ],
    "preferred_domains": ["stats.gov.cn", "data.stats.gov.cn"],
    "required_keywords": ["瑙勬ā浠ヤ笂宸ヤ笟浼佷笟", "钀ヤ笟鏀跺叆", "鍚屾瘮"],
}
```

- [x] Update monetary policy profiles.

For `rrr`, use these two query family names:

```python
{
    "name": "current_level",
    "queries": [
        "閲戣瀺鏈烘瀯 鍔犳潈骞冲潎 瀛樻鍑嗗閲戠巼 褰撳墠姘村钩 鏈€鏂?涓浗浜烘皯閾惰",
        "China reserve requirement ratio current level PBOC latest",
    ],
    "preferred_domains": ["pbc.gov.cn", "tradingeconomics.com", "ceicdata.com"],
    "required_keywords": ["瀛樻鍑嗗閲戠巼", "reserve requirement ratio", "rrr"],
}
```

```python
{
    "name": "official_adjustment_notice",
    "queries": [
        "涓浗浜烘皯閾惰 鍐冲畾 涓嬭皟 閲戣瀺鏈烘瀯 瀛樻鍑嗗閲戠巼 鍏憡",
        "浜烘皯閾惰 闄嶅噯 瀛樻鍑嗗閲戠巼 鏈€鏂?鍏憡",
    ],
    "preferred_domains": ["pbc.gov.cn", "xinhuanet.com"],
    "required_keywords": ["瀛樻鍑嗗閲戠巼", "浜烘皯閾惰"],
}
```

For `reverse_repo`, ensure the official family is named:

```python
"name": "official_operation_notice"
```

and includes:

```python
"浜烘皯閾惰 鍏紑甯傚満 7澶╂湡閫嗗洖璐?鎿嶄綔 涓爣鍒╃巼 鏈€鏂?
```

For `mlf`, ensure the official family is named:

```python
"name": "multi_price_notice"
```

and includes:

```python
"浜烘皯閾惰 涓湡鍊熻捶渚垮埄 鎿嶄綔鍏憡 澶氶噸浠蜂綅 涓爣鍒╃巼鍖洪棿 鏈€鏂?
"浜烘皯閾惰 MLF 澶氶噸浠蜂綅 涓爣鍒╃巼 鍔犳潈骞冲潎鍒╃巼"
```

- [x] Re-run tests.

Command:

```powershell
python -m pytest tests/test_stage2_unified.py tests/test_stage2_fallbacks.py -q
```

Expected output includes:

```text
passed
```

## Task 4: Deduplicate Alias Tasks By Search Profile Key

- [x] Add failing test in `tests/test_stage2_unified.py`.

Append near `test_task_planner_uses_rrr_profile_for_reserve_ratio_alias`:

```python
def test_task_planner_dedupes_rrr_and_reserve_ratio_aliases(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-28"},
        "monetary_policy": {
            "rrr": {"current_value": None},
            "reserve_ratio": {"current_value": None},
        },
        "missing_items": [
            {"key": "rrr", "reason": "missing"},
            {"key": "reserve_ratio", "reason": "missing"},
        ],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")
    tasks = planner.build_tasks(payload)
    rrr_tasks = [task for task in tasks if task["query_template_id"] == "rrr"]

    assert len(rrr_tasks) == 1
    assert rrr_tasks[0]["indicator_key"] == "rrr"
```

- [x] Run test and confirm duplicate alias behavior fails.

Command:

```powershell
python -m pytest tests/test_stage2_unified.py -q
```

Expected failure:

```text
AssertionError: assert 2 == 1
```

- [x] Update dedupe in `src/datasource/engines/stage2_task_planner.py`.

Replace the dedupe key inside `build_tasks`:

```python
            key = task["indicator_key"]
```

with:

```python
            key = task.get("query_template_id") or task["indicator_key"]
```

Change replacement lookup from indicator key equality to the same profile key:

```python
                    if (old_task.get("query_template_id") or old_task.get("indicator_key")) == key:
```

Add canonical-key preference when scores tie:

```python
            should_replace = score > seen[key]
            should_replace = should_replace or (
                score == seen[key] and task.get("indicator_key") == task.get("query_template_id")
            )
            if should_replace:
```

Keep the existing priority order:

```python
priority = {"stale_data": 3, "placeholder": 2, "missing": 1}
```

- [x] Re-run focused tests.

Command:

```powershell
python -m pytest tests/test_stage2_unified.py tests/test_stage2_fallbacks.py -q
```

Expected output includes:

```text
passed
```

## Task 5: Final Verification Without Live Tavily Calls

- [x] Run the focused pytest suite.

Command:

```powershell
python -m pytest tests/test_stage2_unified.py tests/test_stage2_fallbacks.py -q
```

Expected output:

```text
passed
```

- [x] Compile changed Python files.

Command:

```powershell
python -m py_compile src/datasource/config/search_profiles.py src/datasource/engines/stage2_task_planner.py scripts/stage2_unified_enhancer.py
```

Expected output:

```text

```

- [x] Check whitespace.

Command:

```powershell
git diff --check
```

Expected output:

```text

```

- [x] Confirm no live Tavily output files were created by validation.

Command:

```powershell
git status --short
```

Expected output should list only edited source/test files and this plan file.

## Completion Criteria

- Stage2 profile keywords are tied to Stage4/Pring field usage, not generic market search terms.
- ETF, northbound, and southbound have field-specific queries for both `recent_5d` and `total_120d`.
- BDI and macro profiles avoid old circulars, local articles, and non-data pages through explicit pattern signals.
- `_candidate_query_quality` reports `usage_evidence_score`, `good_url_hit_count`, and `bad_url_hit_count`.
- Alias tasks such as `reserve_ratio` and `rrr` are not double-searched in the same Stage2 run.
- `tests/test_stage2_unified.py tests/test_stage2_fallbacks.py` pass.
- No live Tavily call is required to verify this implementation.
