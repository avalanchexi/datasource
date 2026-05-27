# Fund Flow Downgrade Gate Design

Date: 2026-05-27

## Context

The 2026-05-27 daily report run showed that the remaining work after Stage2 is
not primarily a search hit-rate problem. Stage2 reached a reasonable automatic
baseline, but Stage3 and Stage4 still blocked on stricter report-readiness
rules:

- policy and quality state were split across `gap_monitor.json`,
  `quality_metrics.json`, and `policy_evaluation.json`
- Stage3 had a fund-flow escape hatch, but Stage4 did not
- ETF fund-flow windows could not be verified through a clean direct source
- manual patches to `market_data_complete.json` were used to get through
  Stage4

The problematic part is not that ETF was unavailable. The problem is that the
pipeline lacked a formal, auditable production path for this exact situation:
generate the report, keep ETF marked as estimated, and disclose the degraded
fund-flow evidence instead of changing the data to appear non-estimated.

## Goals

1. Restore stable daily report generation when only fund-flow window evidence is
   unavailable.
2. Keep fund-flow downgrade narrow: it applies only to fund-flow quality
   blockers and unresolved gap items.
3. Preserve the truth of the data. ETF news, summaries, or extrapolations remain
   `is_estimated=true`.
4. Make Stage3 and Stage4 use one shared effective-gate vocabulary.
5. Prevent fallback Pring results from becoming formal reports by default.
6. Keep non-fund-flow gates strict.
7. Leave room for a second phase covering readiness diagnostics, BDI business-day
   freshness, Stage2.5 key refresh, and ETF preflight.

## Non-Goals

1. Do not relax non-fund-flow blockers such as `rrr`, stale BDI, compare gaps,
   missing source URLs, or non-allowlisted estimates.
2. Do not let `--allow-estimated` bypass compare gaps, stale critical fields, or
   policy blockers.
3. Do not promote ETF news, year-to-date summaries, quarterly summaries,
   single-day extrapolations, `news_net_flow`, or `estimated_net_flow` into
   trusted direct-window evidence.
4. Do not modify `market_data_complete.json` in Stage4.
5. Do not make direct calls to `generate_report()` part of the production
   workflow.
6. Do not include broad debug bypasses such as `--skip-gap-check` in the normal
   command path.

## Chosen Approach

Implement phase 1 as a shared gate layer plus a formal fund-flow downgrade flag.

```text
market_data_complete.json
  -> build_pipeline_quality_state()
  -> shared effective gate helpers
      -> Stage3 gate
      -> Stage4 gate
      -> gap-monitor filtering
  -> report generation with estimated fund-flow disclosure preserved
```

The downgrade changes only gate interpretation. It never rewrites fund-flow
values, source metadata, `metric_basis`, `window_evidence`, or `is_estimated`.

## Component Design

### Shared Gate Helper

Add `src/datasource/utils/pipeline_gate.py`.

It should own:

- `FUND_FLOW_DOWNGRADE_REASONS`
- `filter_effective_quality_blockers(state, allow_fund_flow_downgrade=False)`
- `filter_effective_gap_items(market_payload, quality_state, gap_items,
  allow_fund_flow_downgrade=False)`
- `collect_fund_flow_downgraded_items(state)`
- `assert_no_fallback_pring_result(pring_payload,
  allow_fallback_report=False)`

The downgrade reason set should cover only fund-flow-specific readiness issues:

- `fund_flow_window_missing`
- fund-flow `estimated_not_allowed`
- existing fund-flow placeholder, zero, or missing-value reasons used by Stage3

The helper should not know official manual override rules, source-tier
classification internals, or ETF provider details. Those remain owned by
Stage2.5 and structured providers.

### Stage3 Adapter

Keep the existing `--skip-fund-flow-check` flag for compatibility.

Internally, Stage3 should map it to:

```text
allow_fund_flow_downgrade = True
```

Stage3 should use the shared helper instead of maintaining its own
`FUND_FLOW_SKIP_REASONS`. If fund-flow blockers are filtered, Stage3 should
write a visible metadata warning or `fund_flow_downgraded_items` field into
`pring_result.json`.

Stage3 still blocks on:

- non-fund-flow quality blockers
- non-fund-flow unresolved gap-monitor items
- low completeness
- stale critical fields
- compare gaps
- policy redlist entries

### Stage4 Adapter

Add `--allow-fund-flow-downgrade`.

Stage4 should:

1. load `market_data_complete.json`
2. load `pring_result.json`
3. build unified quality state
4. filter quality blockers and gap items with the shared helper
5. reject fallback Pring results unless an explicit debug-only future flag is
   added
6. enforce `metadata.ai_websearch_enhanced=true`
7. enforce market and Pring dates match
8. generate the report only after the effective blockers are clear

Stage4 should not change any market data value. ETF remains estimated if the
input says it is estimated.

### Report Disclosure

Report rendering should continue showing estimated fund-flow values as estimated.
If ETF is downgraded, the report should retain enough context for a reader to
understand that the value was included with weaker evidence:

- source URL
- `metric_basis`
- `window_evidence`
- `estimation_method` when present
- existing estimated appendix or quality warning section

If the current report generator already includes the item in the estimated
appendix, this phase should preserve that behavior rather than inventing a new
report section.

## Data Flow

1. Stage2.5 writes `market_data_complete.json` and the usual run artifacts:
   `gap_monitor.json`, `quality_metrics.json`, and `policy_evaluation.json`.
2. Stage3 builds live quality state from `market_data_complete.json`.
3. Stage3 filters only eligible fund-flow blockers when
   `--skip-fund-flow-check` is passed.
4. Stage3 writes the Pring result and records downgrade metadata if any
   fund-flow blockers were filtered.
5. Stage4 builds live quality state from the same market data.
6. Stage4 filters only eligible fund-flow blockers when
   `--allow-fund-flow-downgrade` is passed.
7. Stage4 filters `gap_monitor` pending/manual items through the same effective
   gate helper.
8. Stage4 refuses fallback Pring results by default.
9. Stage4 generates the Markdown report without mutating source data.

## CLI Contract

Daily report generation may use:

```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated \
  --skip-fund-flow-check

bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md" \
  --allow-fund-flow-downgrade
```

The Stage3 flag remains named `--skip-fund-flow-check` for compatibility. The
Stage4 flag should use the clearer production wording
`--allow-fund-flow-downgrade`.

## Error Handling

- If any non-fund-flow blocker remains, Stage3 and Stage4 fail.
- If `pring_result.fallback_used=true`, Stage4 fails by default.
- If `gap_monitor` contains unresolved non-fund-flow pending or manual items,
  Stage4 fails.
- If ETF is estimated but has no source URL, Stage4 should still fail through
  the existing source evidence rules.
- If a fund-flow item is downgraded, the downgrade must be visible in metadata
  or warnings.
- If Stage4 receives `--allow-fund-flow-downgrade` but there are no fund-flow
  blockers, the command should behave normally and not add noise.

## Testing

Add focused tests before implementation:

1. Shared helper filters only eligible fund-flow blockers.
2. Shared helper does not filter `macro_indicators.bdi`,
   `monetary_policy.reserve_ratio`, compare gaps, stale critical fields, or
   commodity/bond blockers.
3. Stage3 with `--skip-fund-flow-check` uses the shared helper and records
   downgrade metadata.
4. Stage4 without `--allow-fund-flow-downgrade` blocks an estimated ETF
   fund-flow item.
5. Stage4 with `--allow-fund-flow-downgrade` allows that ETF item while keeping
   it estimated.
6. Stage4 with the same flag still blocks a simultaneous non-fund-flow blocker.
7. Stage4 rejects `pring_result.fallback_used=true`.
8. The report estimated appendix still includes fund-flow ETF when ETF remains
   estimated.

## Phase 2 Follow-Ups

These are intentionally out of scope for phase 1:

1. A `pipeline_readiness` command that summarizes Stage3 and Stage4 blockers in
   one place.
2. BDI freshness based on report date and business-day rules instead of
   `datetime.now()` calendar age.
3. Stage2.5 key-scoped force refresh, for example
   `--force-refresh-keys macro_indicators.bdi`.
4. Stage1 or post-Stage1 ETF availability preflight.
5. Audit tooling that compares effective Stage3 and Stage4 blockers for the
   same payload and flags rule drift.

## Acceptance Criteria

1. A run with only ETF fund-flow window or fund-flow estimate blockers can
   generate a report through Stage4 when `--allow-fund-flow-downgrade` is set.
2. The same run fails Stage4 without the downgrade flag.
3. ETF remains `is_estimated=true` when its evidence is estimated.
4. A simultaneous non-fund-flow blocker still fails Stage3 or Stage4.
5. Fallback Pring results do not become formal reports by default.
6. Stage3 and Stage4 use shared helper behavior for effective blockers.
7. Tests cover the helper, Stage3, Stage4, and report disclosure behavior.
