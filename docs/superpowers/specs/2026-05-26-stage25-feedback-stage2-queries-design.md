# Stage2.5 Feedback to Stage2 Query Optimization Design

Date: 2026-05-26

## Context

The 2026-05-26 daily run completed through an emergency reporting path, but the Stage2 and Stage2.5 artifacts show a useful optimization loop.

Stage2 built 18 tasks. The effective Stage2 hit rate was 70.6%:

- `stage2_effective_success = 12`
- `stage2_effective_failure = 5`
- `stage2_effective_denominator = 17`
- `task_structured_success = 12`
- `task_search_success = 0`
- Tavily hit a quota or rate/payment limit and the run switched to Exa.

The remaining automated gaps were not one generic search failure. They split into four distinct classes:

- `BCOM`: the Stage2 search profile did not include the Investing historical-data source that Stage2.5 used successfully.
- `mlf`: the PBoC structured provider found the official multi-price MLF notice, but treated "no unified rate" as a Stage2 failure instead of returning the report-ready reference semantics.
- `CN10Y_CDB`: the ChinaBond direct provider failed to parse a 10Y CDB yield, then Exa returned no usable results. Stage2.5 used an estimated `CN10Y + observed CDB spread` value, which is allowed only because `CN10Y_CDB` is in the estimated allowlist.
- `etf`: the TuShare ETF window provider correctly failed closed because an exchange/date row was missing, while search fallback drifted into EastMoney individual-stock flow pages.

The goal is to feed these Stage2.5 findings back into Stage2 so the next run needs less manual work, while keeping the current quality gates authoritative.

## Goals

1. Improve Stage2 task behavior using the 2026-05-26 Stage2.5 evidence, without counting Stage2.5 injection as Stage2 success.
2. Keep Stage2 structured-provider-first execution and targeted search fallback.
3. Add auditable Stage2 behavior for the four observed gaps: `BCOM`, `mlf`, `CN10Y_CDB`, and `etf`.
4. Preserve the existing quality contracts from `build_pipeline_quality_state()`, `policy_rules`, `gap_monitor`, `quality_metrics`, and `policy_evaluation`.
5. Make failures more diagnostic: a future ETF miss should say whether it is a structured window gap or search-result scope mismatch, not only `no_value`.
6. Add focused tests so the query/profile/provider changes cannot silently relax Stage3 or Stage4 gates.

## Non-Goals

1. Do not relax Stage3 or Stage4 quality gates to improve hit rate.
2. Do not count Stage2.5 manual injection toward `stage2_effective_hit_rate`.
3. Do not reuse historical `reports/*.md` as data.
4. Do not make ETF fund-flow pass without direct window evidence.
5. Do not turn arbitrary news articles into official non-estimated values.
6. Do not add `reserve_ratio`, ETF, BCOM, or other non-approved keys to `estimated_allowlist_keys`.
7. Do not make the emergency `--skip-fund-flow-check` or `tests/scripts/generate_simple_report_test.py` path part of normal acceptance.

## Chosen Approach

Use Stage2.5 as a feedback signal, then implement the lessons as tested Stage2 behavior:

```text
Stage2 artifacts
  search_tasks_stage2.jsonl
  stage_task_log.jsonl
  websearch_results_auto.json
        +
Stage2.5 artifact
  websearch_results_manual.json
        ↓
manual-vs-stage2 diagnosis
        ↓
Stage2 improvements
  profile gap
  provider semantic gap
  estimated fallback gap
  gate-preserving filter gap
        ↓
next Stage2 run
  structured-provider-first
  targeted search fallback
  allowlisted estimated fallback where explicit
  unchanged quality gates
```

The immediate implementation should harden the four known gaps directly. A lightweight read-only audit helper can be added as supporting tooling, but the helper must not mutate profiles or market data.

## Quality Coordination Contract

Stage2 hit-rate optimization is subordinate to the existing project quality system.

All automatic Stage2 outputs must remain explainable by:

- `src/datasource/utils/pipeline_quality_state.py`
- `src/datasource/utils/policy_rules.py`
- `config/policy_rules.yaml`
- `data/runs/YYYYMMDD/gap_monitor.json`
- `data/runs/YYYYMMDD/quality_metrics.json`
- `data/runs/YYYYMMDD/policy_evaluation.json`

The quality contract is:

1. `stage2_effective_hit_rate` measures Stage2 automation only. It is not a Stage3 readiness signal by itself.
2. Stage2 success must still leave downstream blockers visible when required: `missing_compare_values`, `estimated_not_allowed`, `fund_flow_window_missing`, `missing_source_url`, and stale redlist issues.
3. `--allow-estimated` does not bypass `compare_gaps`, `estimated_not_allowed`, `stale_redlist`, or fund-flow window blockers.
4. Any Stage2 writeback with a real value must include a traceable `source_url` or the quality state must continue to flag it.
5. Any fund-flow writeback must preserve `source_tier`, `window_evidence`, `metric_basis`, and `is_estimated` semantics.
6. `gap_monitor.json`, `quality_metrics.json`, and `policy_evaluation.json` must be refreshed after Stage2 writes.

Expected quality-state behavior by indicator:

| Indicator | Allowed Stage2 result | Required quality state |
| --- | --- | --- |
| `BCOM` | Non-estimated market quote from a recognized structured or historical-data source, with date/value/source URL. | No `primary_value_missing`; no source URL blocker. Commodity window warnings remain if change fields are unsupported or mismatched. |
| `mlf` | Non-estimated PBoC official multi-price reference result only when sourced from PBoC official MLF notice. | No `estimated_not_allowed`; no `missing_compare_values` if `change_from_120d` is supplied. |
| `CN10Y_CDB` | Explicit estimated value only for this allowlisted key, with `is_estimated=true`, `estimation_method`, and ChinaBond or equivalent evidence URL. | No `estimated_not_allowed` for `CN10Y_CDB`; the estimated nature remains visible for report disclosure. |
| `etf` | Non-estimated only with direct full-window evidence. Otherwise manual-required remains. | `fund_flow_window_missing` remains when `recent_5d` or `total_120d` is missing, zero placeholder, or not directly evidenced. |

## Indicator Designs

### BCOM: Profile Gap

Stage2.5 succeeded with Investing historical data:

- source URL pattern: Investing Bloomberg Commodity historical-data page
- value: dated close
- unit: points

Stage2 should add an `investing_historical_close` query family to `SEARCH_PROFILES["BCOM"]`.

Required profile behavior:

- Query for `Bloomberg Commodity Index historical data`, `BCOM historical close`, `last price`, and the run reference date or latest available market date.
- Add Investing historical-data URL patterns to `good_url_patterns`.
- Keep strict negative filters for `BCOMTR`, `BCOMX`, `GCOM`, `GSG`, `GSCI`, target weights, methodology, annual rebalance, and sub-index pages.
- Require evidence for the Bloomberg Commodity Index itself, not a related total-return index or commodity ETF.
- Keep `source_url`, value date, and numeric value mandatory for writeback.

Expected failure behavior:

- If results are methodology pages or related symbols only, Stage2 records `manual_required` with a reason such as `bcom_scope_mismatch` or `strict_keyword_miss`.
- If a quote is stale beyond the profile freshness window, Stage2 records a freshness failure rather than writing a stale current value.

### MLF: Provider Semantic Gap

The PBoC structured provider already reaches the relevant official notice. The failure is semantic: a multi-price MLF notice has no unified winning rate, but the report has an established reference display path for this case.

Stage2 should let the official provider return a report-ready reference result when all conditions are true:

- Hostname is `pbc.gov.cn`.
- The official notice is an MLF or medium-term lending facility notice.
- The text includes multi-price or equivalent markers such as `多重价位`, `利率招标`, or `无统一利率`.
- The operation month matches the Stage2 reference month.

Required output semantics:

- `current_value = 2.0` only as the configured reference display value.
- `is_estimated = false` because the official source establishes the reference semantics, not because a model guessed it.
- `note` must include markers like `多重价位中标`, `无统一利率`, and `展示参考值`.
- `source_url` must be the PBoC official notice URL.
- `change_from_120d` must be supplied from trend history or an explicit unchanged-reference rule; otherwise the quality state can still flag missing compare values.

Expected failure behavior:

- Non-official news snippets cannot trigger this official non-estimated normalization.
- If the official notice is not period-matched, Stage2 must fall back to search/manual-required.

### CN10Y_CDB: Estimated Fallback Gap

`CN10Y_CDB` has no fully stable direct structured source in the current pipeline. Stage2.5 used an estimated `CN10Y + observed CDB spread` value. That pattern should become an explicit Stage2 fallback, not an implicit manual workaround.

Stage2 should add a CDB estimator fallback after direct ChinaBond parsing and search fallback fail.

Required preconditions:

- The task key is exactly `CN10Y_CDB`.
- A same-day or latest-available `CN10Y` value exists in market data.
- The spread source is explicit: configured spread basis, trend-history spread, or another auditable policy-bank spread source.
- A ChinaBond or equivalent source URL is present for evidence and disclosure.

Required output semantics:

- `current_yield` is computed from `CN10Y + spread_bp`.
- `change_5d_bp` and `change_120d_bp` are inherited from the proxy or computed from available trend history, with a note explaining the basis.
- `is_estimated = true`.
- `estimation_method = "CN10Y plus observed CDB spread"` or an equivalent explicit method.
- `source_url` points to the bond source used for evidence.

Quality coordination:

- This is allowed only because `CN10Y_CDB` is in `estimated_allowlist_keys`.
- The output must never be normalized to non-estimated unless a real direct CDB yield source is parsed.
- The report should still disclose the estimate.

### ETF: Gate-Preserving Filter Gap

ETF is intentionally different from the other three. The goal is not to make ETF pass more easily. The goal is to prevent false-positive search work and improve diagnostics.

Current observed issue:

- TuShare `etf_share_size` failed closed because one required exchange/date row was missing.
- Search fallback selected `data.eastmoney.com/stockdata/688796.html`, an individual-stock flow page, because the URL domain matched EastMoney.

Required changes:

- Add `data.eastmoney.com/stockdata/`, individual-stock paths, single-code pages, and similar routes to ETF bad URL patterns.
- Require ETF scope evidence beyond the domain: `ETF`, `全市场`, `合计`, and a window phrase such as `近5日`, `近120日`, `累计`, or direct daily-series fields.
- Record scope mismatch as `search_result_scope_mismatch` or equivalent in task logs.
- Preserve TuShare provider diagnostics such as missing trade date, missing exchange, date count, row count, and `policy_gate_blocked`.

Quality coordination:

- If TuShare or another structured provider cannot prove full windows, `fund_flow_window_missing` remains.
- Search snippets about news, individual ETF products, annual summaries, or stock flow pages cannot release the fund-flow gate.
- `is_estimated=false` is allowed only with `window_evidence` in `direct_window`, `direct_daily_series`, or `direct_balance_delta`, and with `metric_basis` not in `news_net_flow` or `estimated_net_flow`.

## Diagnostic Helper

Add a lightweight read-only diagnostic helper as supporting tooling if it remains small.

Inputs:

- `search_tasks_stage2.jsonl`
- `stage_task_log.jsonl`
- `websearch_results_auto.json`
- `websearch_results_manual.json`

Output:

- A JSON or markdown summary mapping manual success back to Stage2 failure mode:
  - `profile_gap`
  - `provider_semantic_gap`
  - `estimated_fallback_gap`
  - `gate_preserving_filter_gap`

Constraints:

- It must not mutate profiles, run data, trend history, or reports.
- It must not read historical report markdown as source data.
- It is optional for the first implementation if the four direct fixes and tests are clear.

## Error Handling

Stage2 remains fail-closed.

- BCOM rejects related indexes, methodology pages, weights pages, and stale quotes.
- MLF rejects non-PBoC sources for official non-estimated normalization.
- CN10Y_CDB estimator rejects missing CN10Y, missing spread basis, missing source URL, or any key other than `CN10Y_CDB`.
- ETF rejects individual-stock pages, single-fund pages without full-market evidence, news summaries, and any result without direct window proof.
- Any post-writeback quality blocker must be reflected in the generated run artifacts.

## Testing

Use focused tests in existing suites.

### `tests/test_stage2_unified.py`

- BCOM profile includes Investing historical-data query family and good URL patterns.
- BCOM filtering rejects BCOMTR, BCOMX, GSG/GSCI, methodology, weights, and sub-index pages.
- ETF candidate filtering rejects `data.eastmoney.com/stockdata/*` even when the domain and generic numeric evidence look strong.
- ETF scope mismatch is recorded distinctly from generic `no_value`.
- Stage2 effective metrics continue to exclude Stage2.5 manual injection.

### `tests/test_stage2_structured_providers.py`

- PBoC MLF multi-price notice returns the reference-result semantics only from official PBoC content.
- PBoC MLF period mismatch fails closed.
- CN10Y_CDB estimator returns `is_estimated=true`, `estimation_method`, source URL, and proxy-change note when direct provider fails and CN10Y plus spread is available.
- CN10Y_CDB estimator fails closed when CN10Y or spread basis is missing.

### `tests/test_pipeline_quality_state.py` or targeted integration tests

- CN10Y_CDB estimated fallback is allowlisted and does not create `estimated_not_allowed`.
- ETF missing windows still create `fund_flow_window_missing`.
- MLF official reference result avoids `estimated_not_allowed` but still requires compare/change fields.
- Any automatic value without `source_url` remains blocked.

### Replay Fixture

Add or reuse a compact 2026-05-26-style fixture containing:

- Stage2 BCOM strict keyword miss, Stage2.5 Investing success.
- Stage2 MLF multi-price provider failure, Stage2.5 official reference success.
- Stage2 CN10Y_CDB empty fallback, Stage2.5 estimated success.
- Stage2 ETF TuShare window miss and individual-stock search drift.

The fixture should verify behavior without spending Tavily quota.

## Acceptance Criteria

1. The new design improves Stage2 behavior for `BCOM`, `mlf`, `CN10Y_CDB`, and `etf` without using Stage2.5 as a counted success.
2. `BCOM` can use Investing historical close when evidence is valid.
3. `mlf` can return an official PBoC multi-price reference result without becoming estimated.
4. `CN10Y_CDB` can use an explicit allowlisted estimated fallback and stays visibly estimated.
5. `etf` remains blocked unless direct window evidence exists; individual-stock EastMoney pages are filtered out.
6. `gap_monitor.json`, `quality_metrics.json`, and `policy_evaluation.json` remain consistent with `build_pipeline_quality_state()`.
7. Tests cover both successful writebacks and fail-closed cases.
8. No historical report markdown is used as a data source.

## Implementation Notes

Implementation should start with tests around profile/provider/quality behavior, then make the smallest Stage2 changes needed to satisfy them. The execution plan should not broaden into unrelated report-generation or Stage3 gate changes.
