# Gate And Report Consistency Design

## Goal

Fix the credibility gap found in the 2026-05-19 daily pipeline run before optimizing Stage2 extraction.

The immediate problem is not only that Stage2 produced many `manual_required` items. The higher-risk issue is that low-confidence manual fund-flow values were marked `is_estimated=false` to pass the policy gate, while the final report still claimed 100% completeness. This design makes Stage2.5, Stage3, and Stage4 speak the same quality language:

- Estimated fund-flow windows cannot be converted into trusted data by changing a flag.
- Allowlisted estimates such as BDI and CN10Y_CDB remain visible, dated, sourced, and marked as estimates.
- `quality_metrics`, `gap_monitor`, `policy_evaluation`, and the report appendix reflect the same blockers and warnings.

## Scope

In scope:

- Stage2.5 manual injection normalization.
- Pipeline quality-state calculation.
- Stage3 gate behavior for estimated fund-flow entries.
- Stage4 report display for allowlisted estimates and low-confidence fund-flow values.
- Documentation updates to `AGENTS.md` and `CLAUDE.md`.
- Tests covering the 2026-05-19 failure mode.

Out of scope:

- Tavily query tuning.
- DeepSeek prompt or schema changes.
- New direct data adapters.
- Rewriting historical reports.
- Backfilling `trend_history` from generated reports.

Stage2 extraction reliability gets its own follow-up design after this quality fix lands.

## Trusted Entry Classification

Manual values are evaluated using both source credibility and window evidence. `source_url` is necessary, but it is not sufficient. A valid URL proves provenance; it does not prove that a 5-day or 120-day window was directly observed.

### Tier 1: Official Or Structured Primary Source

Tier 1 values can be treated as real values when the target field and target window are directly available.

- CN10Y_CDB: `https://yield.chinabond.com.cn/gkh/yield` directly publishes the ChinaBond policy-bank yield curve, including the 10-year CDB tenor. A direct 10-year value from this page is `is_estimated=false`.
- Margin: `https://www.sse.com.cn/market/othersdata/margin/sum/` is an official SSE margin summary source. It is only a full-market margin value if combined with the matching SZSE-side data or another verified full-market source.
- Stock Connect: HKEX is authoritative for Stock Connect quota mechanics and definitions. It is a primary source for mechanism and formula checks, but it only supports Northbound/Southbound window values if a parseable historical net-buy series is available.

### Tier 2: High-Trust Secondary Market Data

Tier 2 values may enter the report if they directly provide the target field and window. If they only provide current values or summaries, the entry remains weak evidence or estimated.

- Eastmoney Stock Connect pages can support Northbound/Southbound values when the needed daily or historical net-buy series is directly parsed.
- MacroMicro or TradingEconomics BDI pages remain acceptable secondary sources for BDI, but public pages are still treated as `is_estimated=true` under the existing BDI allowlist.

### Tier 3: News, Research, Period Summaries

Tier 3 sources cannot turn extrapolated fund-flow windows into real values.

- ETF news articles, weekly notes, quarterly summaries, or yearly cumulative comments are evidence for a manual note, not proof of a 5-day or 120-day window.
- A single-day Northbound/Southbound value cannot become a 5-day or 120-day value without being marked estimated.
- Quarter-to-date or year-to-date wording cannot be silently mapped to the report windows.

## Data Semantics

The existing fields remain valid, but their meanings become stricter.

- `is_estimated=true`: the value is derived, proxied, extrapolated, or taken from a non-target window. Fund-flow entries with this flag do not pass Stage3 because fund flow is not in `estimated_allowlist_keys`.
- `metric_basis`: describes the calculation basis. It does not override `is_estimated`.
- `source_url`: required for manual numeric values, but not sufficient for trusted window evidence.
- `estimation_method`: required when a manual entry is estimated or forcibly normalized to estimated.
- `confidence`: optional display metadata; it does not affect the gate unless a later design explicitly makes it part of policy.

Recommended `metric_basis` values:

- `net_flow_sum`: target-window daily net-flow sum.
- `balance_delta`: balance change over the target window.
- `news_net_flow`: news or research source reports a net-flow figure, but not necessarily the target pipeline window.
- `estimated_net_flow`: extrapolated, proxied, or formula-derived flow.

## Gate Rules

Fund-flow entries only pass as trusted when all of the following are true:

- A `source_url` or embedded URL evidence exists.
- The source class is Tier 1 or Tier 2.
- `window_evidence` is one of `direct_window`, `direct_daily_series`, or `direct_balance_delta`.
- The relevant numeric fields are non-null and non-placeholder.
- The value is not a suspicious zero or known placeholder.

If a manual fund-flow payload says `is_estimated=false` but uses Tier 3 evidence, summary-period evidence, single-day extrapolation, or `metric_basis` such as `news_net_flow`/`estimated_net_flow`, Stage2.5 overrides it to `is_estimated=true`, appends an explanatory note, and records a blocker.

BDI and CN10Y_CDB remain special cases:

- BDI keeps `is_estimated=true` on public secondary pages. If it satisfies the existing allowlist conditions, it does not block Stage3 and the report displays its value, source, and date with an estimate marker.
- CN10Y_CDB is `is_estimated=false` only when the direct 10-year CDB yield comes from ChinaBond. CN10Y plus spread remains `is_estimated=true` and must carry `estimation_method`.

`--allow-estimated` does not broaden the gate. It only permits policy allowlist estimates and does not allow fund-flow extrapolations.

## Component Design

### Stage2.5 Injector

Add a source and window classifier before applying manual fund-flow values.

Derived fields:

- `source_tier`: `tier1`, `tier2`, `tier3`, or `unknown`.
- `window_evidence`: `direct_window`, `direct_daily_series`, `direct_balance_delta`, `news_summary`, `derived`, or `unknown`.

Normalization behavior:

- Keep trusted fund-flow values as `is_estimated=false`.
- Force weak or extrapolated fund-flow values to `is_estimated=true`.
- Preserve the original source and `source_url`.
- Add `estimation_method` if absent.
- Append note text explaining why the value was normalized.

### Pipeline Quality State

Use one quality state as the source of truth for:

- `metadata.quality_blockers`
- `metadata.manual_required`
- `quality_metrics.json`
- `gap_monitor.json`
- `policy_evaluation.json`

Fund-flow estimates produce `estimated_not_allowed` with details containing `source_tier`, `window_evidence`, and `metric_basis`. Reusing the existing reason keeps reporting simple while adding enough diagnostic context.

### Stage3

Stage3 continues to consume the unified quality state. With `--allow-estimated`, it only filters policy-allowlisted estimates. Fund-flow estimates remain blockers.

### Stage4

Report rendering changes:

- Allowlisted estimated macro/bond values are no longer treated as placeholders.
- BDI with `date` displays that date instead of `N/A（待 WebSearch）`.
- CN10Y_CDB direct ChinaBond values display as normal values; spread-derived values display `(估)`.
- Fund-flow estimated values display estimate markers and explanatory notes if Stage4 is forced to run.
- The appendix lists all estimated values, including fund-flow estimates, not only BDI and CN10Y_CDB.

## Error Handling

- Missing `source_url`: keep the existing blocker.
- Unknown source domain: classify as `source_tier=unknown`; fund-flow cannot be promoted to trusted.
- Conflicting manual metadata: `metric_basis` and `window_evidence` win over a user-supplied `is_estimated=false`.
- Partial official source: a one-exchange margin value cannot be labeled as full-market margin unless paired with the missing side.
- BDI allowlist failure: block as a quality issue rather than hiding it as a completed manual value.
- CN10Y_CDB fallback spread: keep estimated and explain the calculation.

## Migration

No manual JSON schema break is required. The new fields are optional and can be inferred:

- `source_tier`
- `window_evidence`
- `confidence`
- `estimation_method`

Old manual files are read normally. When inference is uncertain, the classifier chooses the conservative result.

The design does not rewrite historical reports and does not backfill `trend_history` from reports.

## Tests

Focused tests should cover:

- Stage2.5 normalizes fund-flow news or period-summary payloads from `is_estimated=false` to `is_estimated=true`.
- Stage2.5 preserves direct trusted fund-flow windows when source and window evidence are valid.
- Pipeline quality state blocks estimated fund-flow values even with `allow_estimated=True`.
- BDI allowlisted estimates retain dates in Stage4.
- CN10Y_CDB direct ChinaBond values can be non-estimated; spread-derived values remain estimated.
- A 2026-05-19 replay fixture does not produce a clean quality state when fund-flow windows are extrapolated.

## Acceptance Criteria

Using the 2026-05-19 run as a replay target:

- BDI displays `2026-05-18` instead of `N/A（待 WebSearch）`.
- News, quarterly, yearly, or single-day extrapolated fund-flow values are marked estimated or blocked.
- Stage3 does not pass fund-flow estimates via `--allow-estimated`.
- `quality_metrics`, `gap_monitor`, and `policy_evaluation` agree on blockers.
- The report appendix shows all estimated values and low-confidence fund-flow warnings.
- No Stage2 Tavily/DeepSeek behavior changes are included in this implementation.

## Source References

- Eastmoney Stock Connect data center: `https://data.eastmoney.com/hsgt/hsgtV2.html`
- HKEX Stock Connect explanation: `https://www.hkex.com.hk/Mutual-Market/Connect-Hub/Stock-Connect?sc_lang=en`
- SSE margin summary: `https://www.sse.com.cn/market/othersdata/margin/sum/`
- ChinaBond CDB yield curve: `https://yield.chinabond.com.cn/gkh/yield`
- ChinaBond yield-curve methodology: `https://indices.chinabond.com.cn/cbweb-mn/int/int_yield_syl_doc`
- Baltic Exchange indices: `https://www.balticexchange.com/en/data-services/market-information0/indices.html`
- Baltic Exchange FAQ: `https://www.balticexchange.com/en/who-we-are/faqs.html`
- MacroMicro BDI series: `https://en.macromicro.me/series/760/baltic-dry-index`
- Eastmoney ETF tracking article example: `https://finance.eastmoney.com/a/202509223519694198.html`
