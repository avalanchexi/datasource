# Stage2 Hit-Rate Structured Provider Design

Date: 2026-05-24

## Context

The 2026-05-23 Stage2 run exposed a structural hit-rate problem:

- Stage2 true writeback hit rate was 11.8% on the actionable task set.
- Retrieval was high, but extraction/writeback was low.
- Common failure reasons included `no_value`, `deepseek_json_truncated`, strict keyword misses, mixed-source quote pages, and incomplete fund-flow windows.
- Tavily-to-Exa failover solves search availability, but it does not solve the core problem that many known daily or official values are being treated as open-ended web extraction tasks.

The desired metric is Stage2-only true writeback success before Stage2.5 manual injection. Stage2.5 should remain the last resort, not the mechanism that makes Stage2 appear healthy.

## Goals

1. Raise Stage2 true writeback hit rate to at least 70% on the 2026-05-23 golden task set.
2. Treat 70% as the minimum acceptance line, not the target ceiling; prefer 80%-90% when stable sources make that feasible.
3. Add structured data providers before Tavily/Exa search for indicators that have stable official or high-confidence structured sources.
4. Preserve existing Stage2 artifacts and downstream contracts:
   - `market_data_stage2.json`
   - `websearch_results_auto.json`
   - `stage2_unified_log.json`
   - `gap_monitor.json`
5. Preserve all Stage3 policy gates, especially fund-flow window evidence and estimated-value handling.
6. Reduce unnecessary DeepSeek usage by skipping LLM extraction when a structured provider already returns a validated value.
7. Keep every automatic writeback auditable by source URL, date or period, unit, source tier, and backend.

## Non-Goals

1. Do not count Stage2.5 manual injection toward the Stage2 hit-rate target.
2. Do not relax quality gates to inflate hit rate.
3. Do not silently substitute approximate TuShare interfaces for indicators that AGENTS.md says must stay Stage2 or Stage2.5 driven.
4. Do not accept broad news, research summaries, or annual pages as verified daily/window values.
5. Do not make BCOM a hard P0 dependency for the 70% gate, because its stable structured source is less reliable than the other failure items.
6. Do not change Stage3, Stage4, trend-history, or report-generation contracts.

## Chosen Approach

Use Stage2 structured-provider-first execution with search fallback.

```text
Stage2 task planner
  -> structured provider registry
     -> success: validate + write back + audit
     -> failure: Tavily-first search
          -> Tavily unavailable: Exa failover
          -> snippets: existing filter + DeepSeek/regex extraction
```

This keeps the existing Tavily/Exa/DeepSeek path intact, but it stops spending search and LLM calls on values that can be fetched deterministically from trusted structured sources.

## Architecture

Add a Stage2 structured provider package:

```text
src/datasource/providers/stage2_structured/
  base.py
  registry.py
  yahoo_finance.py
  official_china.py
  chinabond.py
  trading_economics.py
  eastmoney_etf.py
```

The package has one responsibility: fetch and normalize report-ready Stage2 values for a known indicator key. It should not own task planning, final writeback policy, Stage3 validation, or search backend state.

Stage2 remains the orchestrator:

1. Build actionable tasks as today.
2. Ask the registry whether a structured provider supports the task.
3. If the provider succeeds, pass the normalized payload through the existing Stage2 writeback and validation path.
4. If the provider fails, record diagnostics and continue to the existing Tavily-first search flow.
5. If Tavily hits quota/rate/payment limits, use the existing Tavily-to-Exa failover state for the search fallback path.

Structured providers are enabled by default for normal Stage2 runs. A diagnostic opt-out such as `--disable-structured-providers` should exist so search-only regressions can still be isolated.

## Provider Interface

```python
from dataclasses import dataclass, field
from typing import Optional, Set


@dataclass
class StructuredResult:
    indicator_key: str
    category: str
    payload: dict
    source: str
    source_url: str
    source_tier: str
    as_of_date: Optional[str] = None
    report_period: Optional[str] = None
    is_estimated: bool = False
    confidence: float = 1.0
    diagnostics: dict = field(default_factory=dict)


class Stage2StructuredProvider:
    supported_keys: Set[str]

    async def fetch(self, task, market_payload, reference_date) -> StructuredResult:
        ...
```

Required success fields:

- `indicator_key`
- `category`
- normalized `payload` matching existing Stage2 writeback expectations
- `source`
- `source_url`
- `source_tier`
- `as_of_date` or `report_period`
- `is_estimated`
- provider diagnostics

Provider failure is not fatal. It returns a structured failure reason or raises a provider-specific exception that Stage2 converts into diagnostics and fallback-to-search.

## P0 Provider Coverage

P0 is selected to cover the 2026-05-23 failure set and reach the minimum 70% Stage2 writeback gate without relying on BCOM.

1. `YahooFinanceProvider`
   - `commodities.GC=F`
   - `commodities.CL=F`
   - `commodities.BZ=F`
   - `commodities.HG=F`
   - `commodities.GSG`
   - Purpose: stable daily quote values with date, price, and unit.

2. `OfficialChinaProvider`
   - `monetary_policy.reverse_repo`
   - `monetary_policy.mlf`
   - `forex.USDCNY`
   - `macro_indicators.industrial`
   - `macro_indicators.industrial_sales`
   - Optional if cheap in the same provider: `monetary_policy.reserve_ratio`
   - Purpose: official or official-adjacent China monetary, FX, and macro values.

3. `ChinaBondProvider`
   - `bonds.CN10Y_CDB`
   - Purpose: policy-bank 10Y yield from a stable bond yield source.

4. `TradingEconomicsProvider`
   - `macro_indicators.bdi`
   - `forex.DXY`
   - Purpose: current daily/market quote values when official open sources are not practical.

5. `EastMoneyETFProvider`
   - `fund_flow.etf`
   - Purpose: attempt structured ETF window data, but only write non-estimated values when strict fund-flow evidence passes.

6. `BCOM`
   - Not a P0 hard dependency.
   - Keep search fallback for this iteration.
   - Add as P1 only if a stable structured source is confirmed during implementation.

## Trusted Source Model

The trusted source set can be moderately expanded, but it must remain explicit and auditable.

`Tier 1` sources are official, exchange, central-bank, statistics-bureau, or index-provider sources. These can write `is_estimated=false` when date or period and unit are valid.

Examples:

- PBoC
- National Bureau of Statistics
- CFETS or ChinaMoney
- ChinaBond
- SSE, SZSE, HKEX
- recognized official index-provider pages when available

`Tier 2` sources are high-confidence structured data providers with parseable quote or table data. These can write `is_estimated=false` for normal market quotes when the page exposes the target value, date, and unit.

Examples:

- Yahoo Finance structured quote data
- Trading Economics structured pages
- EastMoney structured tables
- Investing, MarketWatch, Nasdaq, or similar structured market-data pages if added to an explicit allowlist

`Tier 3` sources are news, articles, research notes, summaries, or pages that describe a value without exposing a direct structured field. These are allowed as search fallback context or manual references, but they do not release strict gates by themselves.

For `fund_flow`, Tier 3 never proves `recent_5d` or `total_120d`. ETF fund flow can be non-estimated only when the provider has direct window evidence:

- `window_evidence=direct_window`
- `window_evidence=direct_daily_series`
- `window_evidence=direct_balance_delta`

and `metric_basis` is not `news_net_flow` or `estimated_net_flow`.

## Data Flow

For each actionable Stage2 task:

1. Stage2 builds the task using the current planner.
2. `StructuredProviderRegistry` checks providers in deterministic order.
3. If no provider supports the task, Stage2 goes directly to search fallback.
4. If a provider supports the task, Stage2 calls it with the task, current market payload, and reference date.
5. A successful provider result is validated for:
   - required fields
   - numeric parseability
   - source URL
   - date or period freshness
   - unit compatibility
   - source tier
   - indicator-specific policy gates
6. Valid structured results are written through the existing Stage2 writeback path.
7. Stage2 records a `websearch_results_auto.json` compatible entry:
   - `search_backend="structured"`
   - `result_type="structured_success"`
   - `source_url`
   - `source_tier`
   - `provider`
   - `as_of_date` or `report_period`
   - normalized payload
8. Invalid or failed provider results record diagnostics and then fall back to Tavily/Exa/DeepSeek search.

Provider success should be visible in the same downstream places where search success is visible today, rather than becoming a hidden side channel.

## Metrics and Logs

Keep the existing summary fields, but make them reflect Stage2 true writeback success. Structured successes should count as successful Stage2 writebacks, not as retrieval-only wins.

Add explicit structured-provider counters:

- `structured_provider_attempt_count`
- `structured_provider_success_count`
- `structured_provider_fallback_to_search_count`
- `structured_provider_success_by_key`
- `structured_provider_error_breakdown`
- `structured_provider_latency_ms_by_provider`
- `stage2_effective_hit_rate`

`stage2_effective_hit_rate` should be calculated from actionable Stage2 writebacks:

```text
successful_stage2_writebacks / actionable_stage2_tasks
```

It should exclude tasks skipped because valid existing values were already present. It should include both structured-provider successes and search/extraction successes.

The existing `retrieval_diagnostics.retrieval_hit_rate` remains useful, but it is not the acceptance metric.

## DeepSeek Compatibility

Structured providers reduce DeepSeek load; they do not replace the search extraction contract.

If structured provider succeeds:

- DeepSeek is not called for that task.
- No snippets are required.
- The normalized payload must still pass existing writeback validation.

If structured provider fails:

- The existing Tavily/Exa snippet contract remains unchanged.
- DeepSeek still receives normalized snippets with `url`, `title`, `snippet`, `content`, `score`, and `published_date`.
- `source_url` returned by DeepSeek must still come from snippet URLs.
- Tavily-to-Exa failover remains search-backend state and is not affected by structured provider attempts.

This design should improve DeepSeek stability because fewer deterministic quote and official-value tasks reach the LLM path.

## Error Handling

Provider failure categories:

- `unsupported_key`
- `timeout`
- `http_error`
- `parse_error`
- `missing_value`
- `missing_source_url`
- `stale_value`
- `unit_mismatch`
- `value_out_of_range`
- `policy_gate_blocked`

Failure behavior:

1. Record provider, key, failure reason, and source URL if available.
2. Do not write partial structured payloads.
3. Fall back to Tavily-first search.
4. If Tavily is quota/rate/payment unavailable, use Exa failover.
5. If search extraction also fails, emit the existing `manual_required` skeleton.

Provider network calls should use short bounded timeouts between 10 and 15 seconds per provider attempt. CI tests should use fixtures or mocks, not live network calls.

## Acceptance Criteria

1. On the 2026-05-23 golden Stage2 task set, `stage2_effective_hit_rate >= 0.70` without Stage2.5 injection.
2. The implementation should continue improving beyond 70% where stable sources allow it; an 80%-90% result is preferred if it does not weaken source quality.
3. Every structured-provider success is auditable in `websearch_results_auto.json` and `stage2_unified_log.json`.
4. Stage3 fund-flow gates remain strict. ETF cannot pass as non-estimated without direct window evidence.
5. Tavily-to-Exa failover still works when Tavily returns quota/rate/payment unavailable errors.
6. DeepSeek extraction still works for search fallback tasks.
7. Existing Stage2.5 schema and downstream Stage3/Stage4 contracts do not change.

## Testing Plan

Unit tests:

- Registry dispatches supported keys to the correct provider.
- Unsupported keys skip structured providers and fall back to search.
- Each P0 provider parses fixture data into the expected normalized payload.
- Provider failures produce structured diagnostics and do not write partial values.
- Fund-flow ETF rejects missing windows, news-only values, and estimated window values.
- Source tier classification accepts explicit Tier 1 and Tier 2 domains and rejects Tier 3 for strict gates.

Stage2 integration tests:

- Structured provider success writes the same market-data shape that search extraction writes today.
- `websearch_results_auto.json` contains backend `structured` records.
- Structured failures fall back to Tavily search.
- Tavily quota/rate/payment failure after provider fallback switches the search backend to Exa.
- DeepSeek is not called for provider-success tasks.
- DeepSeek is still called for search-fallback tasks.

Golden run validation:

- Use the 2026-05-23 task set as the main acceptance case.
- Run Stage2 without Stage2.5 injection.
- Assert `stage2_effective_hit_rate >= 0.70`.
- Review remaining manual-required tasks and classify them by provider gap, source limitation, search extraction failure, or legitimate quality blocker.

## Rollout

1. Add the provider interface, registry, source-tier rules, and tests.
2. Implement P0 providers with fixture-based unit tests.
3. Wire the registry into `scripts/stage2_unified_enhancer.py` before search fallback.
4. Add metrics and artifact fields.
5. Run the 2026-05-23 golden Stage2 validation.
6. Only consider P1 providers, including BCOM, after P0 reaches the minimum acceptance gate without quality regressions.

## Risks

1. Structured pages can change markup or availability.
   - Mitigation: keep providers isolated, fixture-tested, and fallback to search on parse failure.
2. Some Tier 2 sources may expose delayed or subscription-limited data.
   - Mitigation: require date, unit, and source diagnostics; treat stale values as failure.
3. ETF fund-flow data may remain incomplete.
   - Mitigation: preserve strict fund-flow gates and do not count weak evidence as a clean hit.
4. Metrics can become confusing if retrieval hit rate and writeback hit rate are mixed.
   - Mitigation: add `stage2_effective_hit_rate` and keep it as the acceptance metric.
