# Stage2.5 Feedback Stage2 Query Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed the 2026-05-26 Stage2.5 manual-success evidence back into Stage2 so `BCOM`, `mlf`, `CN10Y_CDB`, and `etf` behave better without relaxing quality gates.

**Architecture:** Keep Stage2 structured-provider-first with search fallback. Add one search-profile/filter improvement for BCOM and ETF, one official-provider semantic fix for MLF, and one explicit allowlisted CDB estimator provider that runs after ChinaBond direct parsing fails. All outputs continue through existing Stage2 writeback and `build_pipeline_quality_state()` contracts.

**Tech Stack:** Python 3.10, pytest, existing Stage2 unified enhancer, existing structured provider registry, existing quality-state utilities.

---

## File Structure

- Modify `src/datasource/config/search_profiles.py`
  - Owns Stage2 query families, good URL patterns, bad URL patterns, evidence keywords, and per-profile query budgets.
  - Add BCOM Investing historical-data query family and URL patterns.
  - Add ETF individual-stock page bad URL patterns.

- Modify `scripts/stage2_unified_enhancer.py`
  - Owns search candidate post-filtering and Stage2 task execution diagnostics.
  - Add ETF scope-mismatch detection in `_candidate_query_quality()` so all-bad ETF candidates become unusable with `search_result_scope_mismatch`.

- Modify `src/datasource/providers/stage2_structured/official_china.py`
  - Owns official PBoC/NBS/ChinaMoney structured extraction.
  - Convert official MLF multi-price notices from provider failure into an official reference result.

- Create `src/datasource/providers/stage2_structured/cdb_estimator.py`
  - Owns the allowlisted `CN10Y_CDB` estimated fallback only.
  - Uses `CN10Y` plus configured CDB spread when direct ChinaBond parsing fails.

- Modify `src/datasource/providers/stage2_structured/registry.py`
  - Owns provider dispatch order.
  - Register `cdb_estimator` immediately after `chinabond`.

- Modify `tests/test_stage2_unified.py`
  - Regression coverage for BCOM profile and ETF scope mismatch.

- Modify `tests/test_stage2_structured_providers.py`
  - Regression coverage for MLF official multi-price reference and CN10Y_CDB estimator.

- Modify `tests/test_pipeline_quality_state.py`
  - Regression coverage that the new Stage2 outputs still match quality-state gates.

- Modify `AGENTS.md` and `CLAUDE.md`
  - Keep the daily-run runbook aligned with the new Stage2 behavior.

---

### Task 1: BCOM Investing Profile and ETF Scope Filtering

**Files:**
- Modify: `tests/test_stage2_unified.py`
- Modify: `src/datasource/config/search_profiles.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: Add failing BCOM and ETF tests**

In `tests/test_stage2_unified.py`, insert these tests after `test_search_profile_hardening_for_high_gap_quotes()`:

```python
def test_bcom_profile_includes_investing_historical_close_family():
    bcom = SEARCH_PROFILES["BCOM"]
    family_names = [family["name"] for family in bcom["query_families"]]

    assert family_names[0] == "investing_historical_close"
    assert any(
        "Bloomberg Commodity historical data" in query
        for family in bcom["query_families"]
        for query in family["queries"]
    )
    assert "investing.com/indices/bloomberg-commodity-historical-data" in bcom["good_url_patterns"]
    assert "ca.investing.com/indices/bloomberg-commodity-historical-data" in bcom["good_url_patterns"]
    assert "BCOMTR" in bcom["bad_url_patterns"]


def test_candidate_query_quality_accepts_bcom_investing_historical_close():
    task = {
        "indicator_key": "BCOM",
        "unit": "points",
        "preferred_domains": ["investing.com", "ca.investing.com"],
        "required_keywords": ["Bloomberg Commodity Index"],
        "exclude_keywords": ["BCOMTR", "GSCI", "GSG", "methodology"],
        "evidence_keywords": ["Bloomberg Commodity Index", "historical data", "close", "points"],
        "good_url_patterns": [
            "investing.com/indices/bloomberg-commodity-historical-data",
            "ca.investing.com/indices/bloomberg-commodity-historical-data",
        ],
        "bad_url_patterns": ["BCOMTR", "GSCI", "GSG", "methodology", "weights"],
        "required_output_fields": ["current_price"],
    }
    candidate = {
        "query": "Bloomberg Commodity Index historical data close 2026-05-22",
        "preferred_domains": task["preferred_domains"],
        "required_keywords": ["Bloomberg Commodity Index"],
        "exclude_keywords": ["BCOMTR", "GSCI", "GSG", "methodology"],
    }
    quality = _candidate_query_quality(
        task,
        candidate,
        [
            {
                "url": "https://ca.investing.com/indices/bloomberg-commodity-historical-data",
                "title": "Bloomberg Commodity Historical Data",
                "content": "Bloomberg Commodity Index historical data showed the close at 138.6635 points on 2026-05-22.",
                "score": 0.71,
            }
        ],
    )

    assert quality["unusable_reason"] is None
    assert quality["usable_count"] == 1
    assert quality["good_url_hit_count"] == 1
    assert quality["value_evidence_score"] > 0


def test_candidate_query_quality_marks_etf_stockdata_scope_mismatch():
    task = {
        "indicator_key": "etf",
        "preferred_domains": ["data.eastmoney.com"],
        "good_url_patterns": ["data.eastmoney.com/fund/etf"],
        "bad_url_patterns": ["data.eastmoney.com/stockdata/", "/stockdata/", "个股", "单只"],
        "evidence_keywords": ["全市场", "A股ETF", "近5日", "近120日", "累计", "合计"],
        "required_output_fields": ["recent_5d", "total_120d", "trend"],
    }
    candidate = {
        "query": "A股ETF 全市场 近5日 资金净流入 合计 亿元 东方财富",
        "preferred_domains": ["data.eastmoney.com"],
    }
    quality = _candidate_query_quality(
        task,
        candidate,
        [
            {
                "url": "https://data.eastmoney.com/stockdata/688796.html",
                "title": "个股资金流向",
                "content": "688796个股资金流向显示主力净流入1.2亿元，未披露全市场A股ETF近5日或近120日合计窗口。",
                "score": 0.83,
            }
        ],
    )

    assert quality["unusable_reason"] == "search_result_scope_mismatch"
    assert quality["usable_count"] == 0
    assert quality["bad_url_hit_count"] == 1
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_unified.py::test_bcom_profile_includes_investing_historical_close_family \
  tests/test_stage2_unified.py::test_candidate_query_quality_accepts_bcom_investing_historical_close \
  tests/test_stage2_unified.py::test_candidate_query_quality_marks_etf_stockdata_scope_mismatch
```

Expected:

```text
FAILED tests/test_stage2_unified.py::test_bcom_profile_includes_investing_historical_close_family
FAILED tests/test_stage2_unified.py::test_candidate_query_quality_marks_etf_stockdata_scope_mismatch
```

The BCOM historical-close quality test may pass before implementation if the local scoring is already permissive; the profile and ETF scope tests must fail.

- [ ] **Step 3: Add BCOM profile and ETF bad URL patterns**

In `src/datasource/config/search_profiles.py`, inside `_apply_report_usage_profiles()`, directly after the existing `_prepend_profile_family("BCOM", {"name": "bloomberg_index_quote", ...})` block, insert:

```python
    _prepend_profile_family(
        "BCOM",
        {
            "name": "investing_historical_close",
            "queries": [
                "Bloomberg Commodity Index historical data close {closing_date}",
                "Bloomberg Commodity historical data last price {closing_date}",
                "Investing Bloomberg Commodity Index historical data {closing_date_label}",
            ],
            "preferred_domains": ["investing.com", "ca.investing.com"],
            "required_keywords": ["Bloomberg Commodity Index", "historical data"],
            "exclude_keywords": [
                "BCOMTR",
                "BCOMX",
                "GCOM",
                "GSG",
                "GSCI",
                "methodology",
                "weights",
                "sub-index",
                "subindex",
            ],
        },
    )
```

In the following `SEARCH_PROFILES["BCOM"].update(...)` block, replace the `evidence_keywords`, `good_url_patterns`, and `bad_url_patterns` values with:

```python
            "evidence_keywords": [
                "BCOM:IND",
                "Bloomberg Commodity Index",
                "BCOM",
                "level",
                "last price",
                "historical data",
                "close",
                "points",
            ],
            "good_url_patterns": [
                "bloomberg.com/quote/BCOM:IND",
                "tradingeconomics.com",
                "stockcharts.com",
                "investing.com/indices/bloomberg-commodity-historical-data",
                "ca.investing.com/indices/bloomberg-commodity-historical-data",
            ],
            "bad_url_patterns": _dedupe_preserve(
                list(SEARCH_PROFILES["BCOM"].get("bad_url_patterns") or [])
                + [
                    "BCOMTR",
                    "BCOMX",
                    "GCOM",
                    "GSG",
                    "GSCI",
                    "sub-index",
                    "subindex",
                    "target weights",
                    "annual rebalance",
                    "methodology",
                ]
            ),
```

In the `SEARCH_PROFILES["etf"].update(...)` block, replace `bad_url_patterns` with:

```python
            "bad_url_patterns": [
                "caifuhao.eastmoney.com",
                "/news/",
                "data.eastmoney.com/stockdata/",
                "/stockdata/",
                "个股",
                "单只",
                "十大持仓",
                "费率",
                "规模创新高",
            ],
```

- [ ] **Step 4: Add ETF scope mismatch detection**

In `scripts/stage2_unified_enhancer.py`, inside `_candidate_query_quality()`, directly after this existing block:

```python
    if any(item["bad_hits"] for item in scored_usable) and any(not item["bad_hits"] for item in scored_usable):
        kept = [item for item in scored_usable if not item["bad_hits"]]
        usable = [item["snippet"] for item in kept]
        usable_scores = _score_usable(usable)
        scored_usable = usable_scores["scored"]
```

insert:

```python
    if (
        str(task.get("indicator_key") or "").lower() == "etf"
        and scored_usable
        and all(item["bad_hits"] for item in scored_usable)
    ):
        unusable_reason = "search_result_scope_mismatch"
        usable = []
        usable_scores = _score_usable(usable)
        scored_usable = usable_scores["scored"]
```

- [ ] **Step 5: Run Task 1 tests and verify they pass**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_unified.py::test_bcom_profile_includes_investing_historical_close_family \
  tests/test_stage2_unified.py::test_candidate_query_quality_accepts_bcom_investing_historical_close \
  tests/test_stage2_unified.py::test_candidate_query_quality_marks_etf_stockdata_scope_mismatch \
  tests/test_stage2_unified.py::test_candidate_query_quality_penalizes_bad_etf_results_below_clean_data_page
```

Expected:

```text
4 passed
```

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add src/datasource/config/search_profiles.py scripts/stage2_unified_enhancer.py tests/test_stage2_unified.py
git commit -m "fix: harden stage2 bcom and etf search profiles"
```

Expected:

```text
[stage25-feedback-stage2-queries <hash>] fix: harden stage2 bcom and etf search profiles
```

---

### Task 2: Official MLF Multi-Price Reference Result

**Files:**
- Modify: `tests/test_stage2_structured_providers.py`
- Modify: `src/datasource/providers/stage2_structured/official_china.py`
- Modify: `tests/test_pipeline_quality_state.py`

- [ ] **Step 1: Change the MLF multi-price provider test to expect a result**

In `tests/test_stage2_structured_providers.py`, replace `test_official_china_provider_reports_mlf_multi_price_without_unified_rate()` with:

```python
@pytest.mark.asyncio
async def test_official_china_provider_returns_mlf_multi_price_reference_result():
    list_html = (
        '<a href="./2026052217453752767/index.html">'
        "2026年5月中期借贷便利招标公告</a>"
    )
    detail_html = "开展6000亿元中期借贷便利（MLF）操作，固定数量、利率招标、多重价位中标方式。"

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.MLF_URL:
            return list_html
        return detail_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "mlf", "ref_date": "2026-05-23"}, {}, "2026-05-23")

    extraction = result.to_extraction()
    assert result.provider == "official_china"
    assert result.source_url.startswith("https://www.pbc.gov.cn/")
    assert extraction["value"] == 2.0
    assert extraction["unit"] == "%"
    assert extraction["is_estimated"] is False
    assert extraction["change_from_120d"] == 0.0
    assert "多重价位" in extraction["manual_reason"]
    assert "参考值" in extraction["manual_reason"]
    assert "展示参考值" in extraction["diagnostics"]["note"]
```

Add this period-mismatch test after it:

```python
@pytest.mark.asyncio
async def test_official_china_provider_rejects_mlf_multi_price_wrong_month():
    list_html = (
        '<a href="./2026052217453752767/index.html">'
        "2026年5月中期借贷便利招标公告</a>"
    )
    detail_html = "开展6000亿元中期借贷便利（MLF）操作，固定数量、利率招标、多重价位中标方式。"

    async def fetch_text(url, params=None):
        if url == OfficialChinaProvider.MLF_URL:
            return list_html
        return detail_html

    provider = OfficialChinaProvider(fetch_text=fetch_text)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "mlf", "ref_date": "2026-06-03"}, {}, "2026-06-03")

    assert exc_info.value.reason == "period_mismatch"
```

- [ ] **Step 2: Add MLF quality-state regression**

In `tests/test_pipeline_quality_state.py`, add this test after `test_pipeline_quality_state_blocks_disallowed_estimated_values_even_with_allow_estimated()`:

```python
def test_pipeline_quality_state_accepts_official_mlf_multi_price_reference():
    payload = _base_payload()
    payload["monetary_policy"]["mlf"] = {
        "policy_name": "MLF 中期借贷便利（多重价位中标，参考值）",
        "current_value": 2.0,
        "change_from_120d": 0.0,
        "unit": "%",
        "date": "2026-05-22",
        "source": "Official China structured source",
        "source_url": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125437/125446/125873/2026052217453752767/index.html",
        "is_estimated": False,
        "note": "多重价位中标，无统一利率；展示参考值",
    }

    state = build_pipeline_quality_state(payload, allow_estimated=True)

    assert {"category": "monetary_policy", "key": "mlf", "reason": "estimated_not_allowed"} not in state["quality_blockers"]
    assert {"category": "monetary_policy", "key": "mlf", "reason": "missing_compare_values"} not in state["quality_blockers"]
```

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_structured_providers.py::test_official_china_provider_returns_mlf_multi_price_reference_result \
  tests/test_stage2_structured_providers.py::test_official_china_provider_rejects_mlf_multi_price_wrong_month \
  tests/test_pipeline_quality_state.py::test_pipeline_quality_state_accepts_official_mlf_multi_price_reference
```

Expected:

```text
FAILED tests/test_stage2_structured_providers.py::test_official_china_provider_returns_mlf_multi_price_reference_result
```

The quality-state test may pass before implementation because it directly constructs the final payload; the provider test must fail before the provider is changed.

- [ ] **Step 4: Implement official MLF reference semantics**

In `src/datasource/providers/stage2_structured/official_china.py`, add this constant after `RESERVE_RATIO_URL`:

```python
MLF_MULTI_PRICE_REFERENCE_RATE = 2.0
```

In `_parse_monetary_result()`, replace the current `if value is None:` block with:

```python
        if value is None:
            if key == "mlf" and self._is_mlf_multi_price_notice(html):
                operation_date = self._parse_date(html) or self._parse_date_from_url(url)
                target_date = self._target_operation_date(task)
                if operation_date is None:
                    raise StructuredProviderError(
                        provider=self.name,
                        indicator_key=raw_key,
                        reason="period_mismatch",
                        message="PBoC MLF multi-price notice does not expose a parseable operation date",
                        diagnostics={"url": url, "evidence_text": self._evidence(html)},
                    )
                if target_date and not self._operation_date_matches(key, operation_date, target_date):
                    raise StructuredProviderError(
                        provider=self.name,
                        indicator_key=raw_key,
                        reason="period_mismatch",
                        message="PBoC MLF notice month does not match the task period",
                        diagnostics={
                            "url": url,
                            "operation_date": operation_date,
                            "target_date": target_date,
                            "evidence_text": self._evidence(html),
                        },
                    )
                return self._build_mlf_multi_price_reference(
                    raw_key=raw_key,
                    html=html,
                    url=url,
                    operation_date=operation_date,
                )
            return None
```

Add these methods before `_parse_usdcny_result()`:

```python
    @staticmethod
    def _is_mlf_multi_price_notice(html):
        normalized = OfficialChinaProvider._normalize_text(html)
        return (
            "中期借贷便利" in normalized
            and any(marker in normalized for marker in ("多重价位", "利率招标", "无统一利率"))
        )

    def _build_mlf_multi_price_reference(self, raw_key, html, url, operation_date):
        operation_amount = self._parse_operation_amount(html)
        note = "多重价位中标，无统一利率；展示参考值；manual_official_not_estimated"
        payload = {
            "value": MLF_MULTI_PRICE_REFERENCE_RATE,
            "unit": "%",
            "is_estimated": False,
            "policy_name": "MLF 中期借贷便利（多重价位中标，参考值）",
            "previous_value": MLF_MULTI_PRICE_REFERENCE_RATE,
            "change_rate": 0.0,
            "change_from_120d": 0.0,
            "manual_reason": "多重价位，参考值，口径不适用",
            "note": note,
        }
        if operation_amount is not None:
            payload["operation_amount"] = operation_amount
        return StructuredResult(
            provider=self.name,
            indicator_key=raw_key,
            category="monetary_policy",
            payload=payload,
            source="Official China structured source",
            source_url=url,
            source_tier=classify_structured_source_tier(url),
            as_of_date=operation_date,
            confidence=0.9,
            diagnostics={
                "evidence_text": self._evidence(html),
                "canonical_indicator_key": "mlf",
                "multi_price_reference": True,
                "reference_rate": MLF_MULTI_PRICE_REFERENCE_RATE,
                "note": note,
            },
        )
```

- [ ] **Step 5: Run Task 2 tests and verify they pass**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_structured_providers.py::test_official_china_provider_returns_mlf_multi_price_reference_result \
  tests/test_stage2_structured_providers.py::test_official_china_provider_rejects_mlf_multi_price_wrong_month \
  tests/test_pipeline_quality_state.py::test_pipeline_quality_state_accepts_official_mlf_multi_price_reference
```

Expected:

```text
3 passed
```

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add src/datasource/providers/stage2_structured/official_china.py tests/test_stage2_structured_providers.py tests/test_pipeline_quality_state.py
git commit -m "fix: return official mlf reference result"
```

Expected:

```text
[stage25-feedback-stage2-queries <hash>] fix: return official mlf reference result
```

---

### Task 3: CN10Y_CDB Allowlisted Estimator Provider

**Files:**
- Create: `src/datasource/providers/stage2_structured/cdb_estimator.py`
- Modify: `src/datasource/providers/stage2_structured/registry.py`
- Modify: `tests/test_stage2_structured_providers.py`
- Modify: `tests/test_pipeline_quality_state.py`

- [ ] **Step 1: Add CDB estimator imports and tests**

In `tests/test_stage2_structured_providers.py`, add this import after the `ChinaBondProvider` import:

```python
from datasource.providers.stage2_structured.cdb_estimator import CDBEstimatorProvider
```

Add these tests after `test_chinabond_provider_rejects_unreasonable_yield_value()`:

```python
@pytest.mark.asyncio
async def test_cdb_estimator_provider_uses_cn10y_proxy_plus_spread():
    provider = CDBEstimatorProvider(default_spread_bp=10.0)
    market_payload = {
        "bonds": [
            {
                "symbol": "CN10Y",
                "current_yield": 1.7484,
                "change_5d_bp": -1.01,
                "change_120d_bp": -10.62,
                "date": "2026-05-25",
                "source_url": "https://yield.chinabond.com.cn/cn10y",
            }
        ]
    }

    result = await provider.fetch({"indicator_key": "CN10Y_CDB"}, market_payload, "2026-05-26")

    extraction = result.to_extraction()
    assert result.provider == "cdb_estimator"
    assert result.source_url.startswith("https://yield.chinabond.com.cn/")
    assert extraction["value"] == pytest.approx(1.8484)
    assert extraction["current_yield"] == pytest.approx(1.8484)
    assert extraction["change_5d_bp"] == pytest.approx(-1.01)
    assert extraction["change_120d_bp"] == pytest.approx(-10.62)
    assert extraction["is_estimated"] is True
    assert extraction["estimation_method"] == "CN10Y plus observed CDB spread"
    assert extraction["metric_basis"] == "cn10y_proxy_plus_spread"


@pytest.mark.asyncio
async def test_cdb_estimator_provider_fails_without_cn10y_proxy():
    provider = CDBEstimatorProvider(default_spread_bp=10.0)

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "CN10Y_CDB"}, {"bonds": []}, "2026-05-26")

    assert exc_info.value.reason == "missing_cn10y_proxy"


@pytest.mark.asyncio
async def test_default_registry_orders_cdb_estimator_after_chinabond():
    provider_names = [
        provider.name
        for provider in build_default_registry().providers_for("CN10Y_CDB")
    ]

    assert provider_names[:2] == ["chinabond", "cdb_estimator"]
```

- [ ] **Step 2: Add CDB quality-state regression**

In `tests/test_pipeline_quality_state.py`, add this test after the MLF quality-state test from Task 2:

```python
def test_pipeline_quality_state_allows_cn10y_cdb_estimated_fallback():
    payload = _base_payload()
    payload["bonds"] = [
        {
            "symbol": "CN10Y_CDB",
            "name": "10年期国开债收益率",
            "current_yield": 1.8484,
            "change_5d_bp": -1.01,
            "change_120d_bp": -10.62,
            "unit": "%",
            "date": "2026-05-26",
            "source": "CN10Y proxy plus configured CDB spread",
            "source_url": "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/more?locale=cn_ZH",
            "is_estimated": True,
            "estimation_method": "CN10Y plus observed CDB spread",
            "metric_basis": "cn10y_proxy_plus_spread",
        }
    ]

    state = build_pipeline_quality_state(payload, allow_estimated=True)

    assert {"category": "bonds", "key": "CN10Y_CDB", "reason": "estimated_not_allowed"} not in state["quality_blockers"]
    assert "bonds.CN10Y_CDB" not in state["policy_evaluation"]["estimated_blockers"]
```

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_structured_providers.py::test_cdb_estimator_provider_uses_cn10y_proxy_plus_spread \
  tests/test_stage2_structured_providers.py::test_cdb_estimator_provider_fails_without_cn10y_proxy \
  tests/test_stage2_structured_providers.py::test_default_registry_orders_cdb_estimator_after_chinabond \
  tests/test_pipeline_quality_state.py::test_pipeline_quality_state_allows_cn10y_cdb_estimated_fallback
```

Expected:

```text
ERROR tests/test_stage2_structured_providers.py
```

The expected error is `ModuleNotFoundError: No module named 'datasource.providers.stage2_structured.cdb_estimator'`.

- [ ] **Step 4: Create the estimator provider**

Create `src/datasource/providers/stage2_structured/cdb_estimator.py` with:

```python
"""Estimated fallback provider for the 10Y CDB yield."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.chinabond import ChinaBondProvider
from datasource.providers.stage2_structured.source_tiers import classify_structured_source_tier


class CDBEstimatorProvider(Stage2StructuredProvider):
    name = "cdb_estimator"
    supported_keys = {"CN10Y_CDB"}

    def __init__(
        self,
        *,
        default_spread_bp: float = 10.0,
        source_url: str = ChinaBondProvider.source_url,
    ) -> None:
        self.default_spread_bp = float(default_spread_bp)
        self.source_url = source_url

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        if key != "CN10Y_CDB":
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="unsupported_key",
                message="CDB estimator provider does not support {0}".format(key),
            )

        cn10y = self._find_cn10y_entry(market_payload)
        proxy_yield = self._safe_number(cn10y.get("current_yield") or cn10y.get("current_value"))
        if proxy_yield is None:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="missing_cn10y_proxy",
                message="CN10Y_CDB estimator requires an existing CN10Y yield",
                diagnostics={"source_url": self.source_url},
            )

        spread_bp = self._spread_bp(task, market_payload)
        estimated_yield = round(proxy_yield + spread_bp / 100.0, 4)
        change_5d = self._safe_number(cn10y.get("change_5d_bp"))
        change_120d = self._safe_number(cn10y.get("change_120d_bp"))
        note = (
            "CN10Y_CDB estimated from CN10Y proxy plus configured CDB spread; "
            "cn10y_proxy_change_basis"
        )
        payload = {
            "value": estimated_yield,
            "current_yield": estimated_yield,
            "unit": "%",
            "change_5d_bp": change_5d,
            "change_120d_bp": change_120d,
            "is_estimated": True,
            "estimation_method": "CN10Y plus observed CDB spread",
            "metric_basis": "cn10y_proxy_plus_spread",
            "note": note,
        }
        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category="bonds",
            payload=payload,
            source="CN10Y proxy plus configured CDB spread",
            source_url=self.source_url,
            source_tier=classify_structured_source_tier(self.source_url),
            as_of_date=str(cn10y.get("date") or cn10y.get("as_of_date") or reference_date),
            confidence=0.65,
            diagnostics={
                "proxy_symbol": "CN10Y",
                "proxy_yield": proxy_yield,
                "spread_bp": spread_bp,
                "estimated_yield": estimated_yield,
                "estimation_method": "CN10Y plus observed CDB spread",
                "source_url": self.source_url,
            },
        )

    @staticmethod
    def _find_cn10y_entry(market_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        for entry in market_payload.get("bonds") or []:
            if isinstance(entry, Mapping) and str(entry.get("symbol") or "") == "CN10Y":
                return entry
        return {}

    def _spread_bp(self, task: Mapping[str, Any], market_payload: Mapping[str, Any]) -> float:
        for value in (
            task.get("cdb_spread_bp"),
            market_payload.get("metadata", {}).get("cn10y_cdb_spread_bp")
            if isinstance(market_payload.get("metadata"), Mapping)
            else None,
        ):
            parsed = self._safe_number(value)
            if parsed is not None:
                return parsed
        return self.default_spread_bp

    @staticmethod
    def _safe_number(value: Any) -> Optional[float]:
        try:
            if value in (None, "", "N/A"):
                return None
            return float(value)
        except Exception:
            return None


def build_provider() -> CDBEstimatorProvider:
    return CDBEstimatorProvider()
```

- [ ] **Step 5: Register the estimator after ChinaBond**

In `src/datasource/providers/stage2_structured/registry.py`, replace:

```python
    module_names = (
        "chinabond",
        "tushare_etf",
```

with:

```python
    module_names = (
        "chinabond",
        "cdb_estimator",
        "tushare_etf",
```

- [ ] **Step 6: Run Task 3 tests and verify they pass**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_structured_providers.py::test_cdb_estimator_provider_uses_cn10y_proxy_plus_spread \
  tests/test_stage2_structured_providers.py::test_cdb_estimator_provider_fails_without_cn10y_proxy \
  tests/test_stage2_structured_providers.py::test_default_registry_orders_cdb_estimator_after_chinabond \
  tests/test_pipeline_quality_state.py::test_pipeline_quality_state_allows_cn10y_cdb_estimated_fallback
```

Expected:

```text
4 passed
```

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add src/datasource/providers/stage2_structured/cdb_estimator.py src/datasource/providers/stage2_structured/registry.py tests/test_stage2_structured_providers.py tests/test_pipeline_quality_state.py
git commit -m "feat: add cn10y cdb estimator fallback"
```

Expected:

```text
[stage25-feedback-stage2-queries <hash>] feat: add cn10y cdb estimator fallback
```

---

### Task 4: Documentation and Focused Verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update AGENTS.md Stage2 and data-standard notes**

In `AGENTS.md`, add these reusable bullets to the Stage2/search or data-standard sections where the related indicators are already described:

```markdown
- `BCOM` Stage2 search may use Investing Bloomberg Commodity historical-data pages when the snippet proves the Bloomberg Commodity Index close/last price, date, numeric value and source URL. `BCOMTR`、`BCOMX`、`GSCI/GSG`、methodology、weights、sub-index 页面仍必须拒绝。
- `mlf` 的 PBoC 多重价位公告可由 Stage2 官方结构化源写成非估算参考值：`current_value=2.00`、`is_estimated=false`，note 必须包含“多重价位中标/无统一利率/展示参考值”，且公告月份必须匹配任务月份。
- `CN10Y_CDB` 在 ChinaBond 直采和搜索均失败时，可使用显式 `CN10Y + observed CDB spread` 估算兜底；必须保留 `is_estimated=true`、`estimation_method`、ChinaBond 或等效 `source_url`，只能因为 `estimated_allowlist_keys` 中包含 `CN10Y_CDB` 才释放 estimated gate。
- `fund_flow.etf` 搜索 fallback 必须过滤 `data.eastmoney.com/stockdata/*`、个股页、单只 ETF 页和新闻页；这些页面应记录 `search_result_scope_mismatch`，不得释放 `fund_flow_window_missing`。
```

- [ ] **Step 2: Update CLAUDE.md quick reminder**

In `CLAUDE.md`, add this concise reminder near the Stage2 daily-run reminders:

```markdown
- Stage2.5 feedback loop: BCOM can use Investing historical close; MLF PBoC multi-price notices become official reference results; CN10Y_CDB estimator stays `is_estimated=true`; ETF stockdata/individual pages are scope mismatches and must not release fund-flow gates.
```

- [ ] **Step 3: Run focused verification**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_stage2_unified.py \
  tests/test_stage2_structured_providers.py \
  tests/test_pipeline_quality_state.py \
  tests/test_policy_rules.py
```

Expected:

```text
all selected tests pass
```

The exact count can change because this plan adds tests. Failures in these selected files must be fixed before committing.

- [ ] **Step 4: Run static syntax check for touched Python files**

Run:

```bash
.venv/bin/python -m py_compile \
  scripts/stage2_unified_enhancer.py \
  src/datasource/config/search_profiles.py \
  src/datasource/providers/stage2_structured/official_china.py \
  src/datasource/providers/stage2_structured/cdb_estimator.py \
  src/datasource/providers/stage2_structured/registry.py
```

Expected:

```text
command exits 0 with no output
```

- [ ] **Step 5: Review git diff for quality-gate regressions**

Run:

```bash
git diff --check
git diff --stat
git diff -- AGENTS.md CLAUDE.md src/datasource/config/search_profiles.py scripts/stage2_unified_enhancer.py src/datasource/providers/stage2_structured
```

Expected:

```text
git diff --check exits 0
```

Manually verify the diff preserves:

- no Stage2.5 counting in `stage2_effective_hit_rate`
- `CN10Y_CDB` output remains `is_estimated=true`
- ETF `fund_flow_window_missing` is not bypassed
- MLF official reference is limited to PBoC provider output

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: document stage2 feedback optimizations"
```

Expected:

```text
[stage25-feedback-stage2-queries <hash>] docs: document stage2 feedback optimizations
```

---

## Final Verification

After all tasks are committed, run:

```bash
.venv/bin/python -c "from datasource import get_manager; print('OK')"
.venv/bin/pytest -q \
  tests/test_stage2_unified.py \
  tests/test_stage2_structured_providers.py \
  tests/test_pipeline_quality_state.py \
  tests/test_policy_rules.py
git status --short
```

Expected:

```text
OK
all selected tests pass
git status --short prints nothing
```

If `src/datasource_integration.egg-info/*` changes after editable install or test execution, restore only those generated metadata files before final status:

```bash
git restore src/datasource_integration.egg-info/PKG-INFO src/datasource_integration.egg-info/SOURCES.txt src/datasource_integration.egg-info/entry_points.txt src/datasource_integration.egg-info/requires.txt
```
