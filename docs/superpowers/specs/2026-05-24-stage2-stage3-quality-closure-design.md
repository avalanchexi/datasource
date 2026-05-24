# Stage2 / Stage3 Quality Closure Design

Date: 2026-05-24

## Context

The latest 2026-05-23 rerun shows Stage2 now meets the minimum hit-rate goal:

- `stage2_effective_hit_rate = 70.6%`
- `stage2_effective_success = 12`
- `stage2_effective_denominator = 17`
- `task_structured_success = 12`
- `task_search_success = 0`
- Tavily quota failover is working: `search_backend_final = exa`, `tavily_to_exa_failover = true`, `exa_failover_error = 0`

The remaining failure is not the overall Stage2 hit rate. Stage3 blocks because it validates stricter report-readiness requirements:

- macro `previous_value/change_rate`
- monetary `change_from_120d`
- non-allowlisted estimated values
- fund-flow `recent_5d/total_120d` windows

The immediate blockers after Stage2.5 manual injection are:

- `macro_indicators.industrial`: `missing_compare_values`
- `macro_indicators.industrial_sales`: `missing_compare_values`
- `macro_indicators.bdi`: `missing_compare_values`
- `monetary_policy.reverse_repo`: `missing_compare_values`
- `monetary_policy.reserve_ratio`: `missing_compare_values`
- `monetary_policy.reserve_ratio`: `estimated_not_allowed`
- `fund_flow.etf`: missing `recent_5d`
- `fund_flow.etf`: missing `total_120d`

## Root Causes

1. Stage2.5 does not merge compare fields when the incoming manual value equals an existing structured value.
   - Manual JSON can contain valid `previous_value`, `change_rate`, or `change_from_120d`.
   - If the existing `current_value` is already present and numerically equal, Stage2.5 currently performs metadata-only updates and skips these compare fields.
   - A forced override proves the compare blockers disappear, leaving ETF as the only hard blocker.

2. ETF fund-flow still lacks a verified window source in the Stage2 path.
   - `EastMoneyETFProvider` correctly refuses to release the gate unless the secid is verified as full-market ETF scope.
   - Search snippets currently return individual stock or news pages, which do not prove 5-day or 120-day ETF windows.
   - TuShare `etf_share_size` can produce an SSE+SZSE total-size delta window when the 121 trading-day series is available; this is an acceptable `direct_balance_delta` basis, not a news-flow estimate.

3. `reserve_ratio` can be downgraded to an estimated blocker when a Tier2 structured page or stale metadata overrides a trusted non-estimated manual value.
   - Stage3 is correct to block non-allowlisted estimated monetary values.
   - The fix is to preserve or apply trusted non-estimated evidence, not to add `reserve_ratio` to the estimated allowlist.

4. Search failover availability does not guarantee extraction/writeback success.
   - Exa fallback is functioning.
   - The remaining search-only misses are high-difficulty sources: `BCOM`, `CN10Y_CDB`, `mlf`, and `etf`.
   - Stage2 hit-rate improvement should continue through structured providers and targeted search query hardening, but Stage3 readiness requires compare/window closure.

## Goals

1. Keep Stage2 effective hit rate at or above 70% on the 2026-05-23 rerun set, and improve it where stable sources allow.
2. Let Stage3 pass only when all strict quality gates are satisfied by real, auditable data.
3. Preserve the distinction between:
   - Stage2 effective hit rate
   - search-chain hit rate
   - Stage2.5 manual injection
   - Stage3 quality readiness
4. Merge manual compare fields into existing Stage2 structured values without requiring `--force-override` for same-value updates.
5. Add a real ETF window path using TuShare `etf_share_size` when the full window is available.
6. Keep ETF and fund-flow gates strict when no direct window evidence exists.
7. Update `AGENTS.md`, `CLAUDE.md`, and relevant project docs so the operational runbook matches the implementation.

## Non-Goals

1. Do not relax Stage3 gate behavior.
2. Do not let `--allow-estimated` bypass `compare_gaps`, `estimated_not_allowed`, `stale_redlist`, or fund-flow window requirements.
3. Do not count Stage2.5 manual injection toward Stage2 effective hit rate.
4. Do not accept EastMoney ETF data as full-market unless its scope is verified.
5. Do not mark ETF news, quarterly summaries, annual summaries, single-day extrapolations, or `estimated_net_flow` as non-estimated window data.
6. Do not add `reserve_ratio` to `estimated_allowlist_keys` as a shortcut.
7. Do not reuse historical `reports/*.md` as data sources.

## Chosen Approach

Use a quality-closure pipeline:

```text
Stage1
  -> Stage2 structured-provider-first
      -> Tavily search
      -> Exa failover when Tavily quota/rate/payment limit is hit
  -> Stage2.5 partial manual merge
      -> merge current values and compare/window fields
      -> preserve trusted non-estimated official evidence
  -> Stage3 strict quality gate
      -> pass only when compare/window/estimated blockers are clear
```

This keeps the current strict policy intact while closing the specific gaps that prevent a valid Stage3 run.

## Component Design

### Stage2.5 Partial Merge

Update the same-value path in `_apply_macro_entry()` and `_apply_monetary_entry()`.

When existing `current_value` is non-placeholder and the incoming value is numerically equal, Stage2.5 should still merge missing report-readiness fields:

- macro:
  - `previous_value`
  - `change_rate`
  - `value_type`
  - `yoy_month`
  - `yoy_ytd`
  - `report_period`
  - `source_url`
  - `is_estimated`
- monetary:
  - `change_from_120d`
  - `previous_value` and `change_rate` when supplied as aliases for 120-day comparison
  - `rrr_type`
  - `source_url`
  - `is_estimated`

The merge must not overwrite a real current value with `None`. It should also avoid duplicating stale note markers such as repeated `reason=no_previous_value`.

### Reserve Ratio Evidence Handling

For `reserve_ratio`, same-value manual updates should be able to change `is_estimated` from `true` to `false` when the payload provides a trusted source URL and explicit `is_estimated=false`.

The official manual override allowlist remains separate from the estimated allowlist. This work should not change the estimated allowlist. The output must be non-estimated only because the source evidence says it is non-estimated.

### ETF TuShare Window Provider

Add a Stage2 structured provider for `fund_flow.etf` using TuShare `etf_share_size`. The provider should reuse the existing Stage1 calculation rules where practical, but it must expose the result through the Stage2 structured-provider contract so Stage2 metrics and audit logs remain consistent.

1. Load the latest 121 open A-share trading dates ending at the run reference date.
2. For each date, fetch SSE and SZSE ETF `total_size`.
3. Require both exchanges to return usable positive values for each included date.
4. Convert `total_size` from 万元 to 亿元.
5. Compute:
   - `recent_5d = latest_total_size - total_size_5_sessions_ago`
   - `total_120d = latest_total_size - total_size_120_sessions_ago`
6. Return:
   - `metric_basis = etf_total_size_delta`
   - `window_evidence = direct_balance_delta`
   - `source = TuShare etf_share_size`
   - `source_url = https://tushare.pro/document/2`
   - `source_tier = tier2`
   - `is_estimated = false`

If any date or exchange is missing, the provider must fail with diagnostics and fall back to existing search/manual handling. It must not synthesize a partial non-estimated window.

Add `tushare.pro` to the structured source-tier classifier as a Tier2 structured API source. This is scoped to direct API/table data and does not make arbitrary TuShare-related text pages trusted fund-flow evidence.

### EastMoney ETF Scope

Keep `EastMoneyETFProvider` blocked by default unless a full-market ETF secid is explicitly verified.

If future work verifies a full-market secid, it may be added through an explicit allowlist and should still require:

- at least 120 usable rows
- no malformed latest rows
- `metric_basis` not in `news_net_flow` or `estimated_net_flow`
- `window_evidence = direct_daily_series`
- Tier2 structured path classification

### Stage2 Search Hardening

Continue improving search fallback for hard gaps without making search the primary path:

- `BCOM`: avoid BCOMTR, GSG, sub-index, and total-return pages unless explicitly requested.
- `CN10Y_CDB`: prefer ChinaBond and policy-bank yield wording; keep estimated yield rules intact.
- `mlf`: reject operation amounts in 亿元 when the required value is an interest rate in `%`; keep multi-price MLF display semantics.
- `etf`: field retries may collect evidence, but they cannot release the gate without direct window data.

### Metrics

Keep Stage2 summary fields explicit:

- `stage2_effective_hit_rate`
- `stage2_effective_success`
- `stage2_effective_failure`
- `stage2_effective_denominator`
- `task_structured_success`
- `task_search_success`
- `search_success_rate_incremental`
- `task_skipped_existing`

Add or preserve diagnostics that explain why Stage3 still blocks:

- same-value manual merge count
- partial compare-field merge count
- ETF TuShare window success/failure reason
- fund-flow window evidence
- estimated blocker reasons

## Data Flow

1. Stage2 writes validated structured/search values to `market_data_stage2.json`.
2. Stage2 writes structured and search records to `websearch_results_auto.json`.
3. Stage2.5 reads manual or auto results.
4. For each matching entry:
   - write current value if missing or stale
   - merge missing compare/window fields even when current value is unchanged
   - recompute quality state
   - refresh `gap_monitor.json`, `quality_metrics.json`, and `policy_evaluation.json`
5. Stage3 reads `market_data_complete.json` and the run-scoped quality artifacts.
6. Stage3 proceeds only if unified quality and gap monitor blockers are clear.

## Error Handling

- Same-value partial merge should never hide a conflict. If the incoming compare fields imply a different current value or incompatible value type, keep the existing blocker and record a diagnostic.
- ETF TuShare provider should fail closed when any exchange/date is missing.
- ETF search fallback should continue to produce `manual_required` skeletons when it cannot prove windows.
- `reserve_ratio` should remain blocked when source evidence is missing, estimated, or untrusted.
- Tavily quota/rate/payment failover behavior remains unchanged: switch the current Stage2 run to Exa and continue the existing search fallback path.

## Testing

Add focused tests before implementation:

1. Stage2.5 macro same-value merge:
   - existing `industrial.current_value = 4.1`
   - manual payload also `4.1` with `previous_value/change_rate`
   - output has compare fields and no `missing_compare_values`

2. Stage2.5 monetary same-value merge:
   - existing `reverse_repo.current_value = 1.4`
   - manual payload has `change_from_120d = 0`
   - output clears monetary compare blocker

3. Reserve ratio non-estimated merge:
   - existing `reserve_ratio.is_estimated = true`
   - manual payload has trusted URL and `is_estimated = false`
   - output is not estimated and Stage3 has no `estimated_not_allowed`

4. ETF TuShare success:
   - 121 open dates
   - both exchanges return positive `total_size`
   - output has `recent_5d`, `total_120d`, `direct_balance_delta`, and `is_estimated=false`

5. ETF TuShare failure:
   - one exchange or date missing
   - provider fails closed and leaves `fund_flow_window_missing`

6. End-to-end quality replay:
   - Stage2 output plus manual payload clears all non-ETF blockers
   - ETF TuShare fixture clears ETF blocker
   - Stage3 gate passes in the fixture scenario

## Verification

Run focused tests first:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_websearch_injector.py \
  tests/test_stage2_structured_providers.py \
  tests/test_pipeline_quality_state.py
```

Then rerun the 2026-05-23 pipeline slice:

```bash
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data /mnt/d/cursor/datasource/data/runs/20260523/market_data.json \
  --output data/runs/20260523/market_data_stage2_quality_closure.json \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend deepseek \
  --deepseek-timeout 30 \
  --llm-hard-timeout 35 \
  --deepseek-max-concurrency 3 \
  --queue-retry-limit 0 \
  --no-cache \
  --enable-exa-fallback \
  --websearch-results data/runs/20260523/websearch_results_auto_quality_closure.json \
  --log-output logs/runs/20260523/stage2_unified_log_quality_closure.json \
  --gap-monitor data/runs/20260523/gap_monitor_quality_closure.json
```

```bash
bash run_clean.sh python scripts/stage2_5_injector.py \
  data/runs/20260523/market_data_stage2_quality_closure.json \
  /mnt/d/cursor/datasource/data/runs/20260523/websearch_results_manual.json \
  data/runs/20260523/market_data_complete_quality_closure.json \
  --gap-monitor data/runs/20260523/gap_monitor_quality_closure_manual.json
```

```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data data/runs/20260523/market_data_complete_quality_closure.json \
  --output data/runs/20260523/pring_result_quality_closure.json \
  --allow-estimated
```

Acceptance:

- Stage2 effective hit rate is at least 70%.
- `search_backend_final=exa` still appears when Tavily returns quota/rate/payment limits.
- Stage2.5 clears compare blockers when manual compare fields are present.
- Stage3 passes when ETF TuShare full-window data is available.
- If ETF full-window data is unavailable, Stage3 blocks with only ETF window diagnostics and does not silently generate a report.

## Documentation Updates

Update:

- `AGENTS.md`
- `CLAUDE.md`
- relevant `docs/superpowers/plans/*` or runbook notes if implementation changes operator commands

The docs must state:

- Stage2 effective hit rate excludes Stage2.5 manual injection.
- Stage2.5 can merge compare fields into same-value existing records.
- ETF can pass only with direct window evidence.
- TuShare `etf_share_size` ETF total-size delta is a scale-window basis, not a news net-flow basis.
- `--allow-estimated` does not bypass quality blockers.
