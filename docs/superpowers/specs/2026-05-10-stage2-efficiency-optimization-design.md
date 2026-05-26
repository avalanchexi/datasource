# Stage2 Efficiency Optimization Design

## Goal

Improve Stage2 runtime and reduce Stage2.5 manual search pressure without weakening data-quality gates. The optimization targets three places:

- Reduce broad or wrong-scope Tavily searches for high-gap indicators.
- Make DeepSeek extraction lightly concurrent by default.
- Preserve strict evidence requirements so fewer Stage2.5 items come from avoidable extraction failures, not from relaxed acceptance.

## Current Constraints

Stage2 reads Stage1 `market_data.json`, builds tasks from missing, placeholder, stale, and estimated entries, searches through Tavily, optionally enriches snippets through Tavily extract, and then extracts structured values through DeepSeek or regex fallback.

Known bottlenecks:

- Default DeepSeek extraction is effectively serial.
- Tavily extract can trigger repeated 422/cooldown behavior.
- Several profiles return topical but non-reportable snippets, causing `manual_required` even when retrieval itself succeeded.
- Stage2.5 volume is driven mostly by missing report fields, failed extraction, strict keyword misses, and incomplete fund-flow windows.

## Approved Approach

Use a conservative default performance bump:

- Enable queue extraction by default.
- Set default `queue_concurrency` to `3`.
- Set default `deepseek_max_concurrency` to `3`.
- Keep CLI options overrideable.
- Keep Tavily extract concurrency at `1`.
- Do not parallelize Tavily candidate searches in this iteration.

Tune search profiles around Stage4 report needs:

- Tighten high-gap profiles around official/current-value evidence.
- Add or refine query families for the delivered high-gap quote profiles: `BCOM`, `GSG`, `USDCNY`, `DXY`, and `CN10Y_CDB`.
- Prefer field-level fund-flow queries for `recent_5d` and `total_120d`.
- Use `good_url_patterns`, `bad_url_patterns`, and `evidence_keywords` to improve post-filter query selection.

## Data Flow

1. `Stage2TaskPlanner` builds tasks as today.
2. Expanded query candidates are scored after domain, freshness, keyword, issuer, period, and URL-pattern checks.
3. Only selected, filtered snippets are sent to extraction.
4. Queue consumers run DeepSeek extraction concurrently up to the configured default of `3`.
5. Stage2 writes the same artifacts: task file, task log, `websearch_results_auto.json`, `gap_monitor.json`, `quality_metrics.json`, `policy_evaluation.json`, `run_snapshot.json`, and summary log.

## Error Handling

- Tavily quota/rate-limit still fast-switches remaining tasks to `manual_required`.
- Tavily extract 422 still cools down per indicator and falls back to snippets/regex.
- Low-score or strict mismatch still skips DeepSeek rather than spending LLM calls.
- Missing `source_url`, missing fund-flow windows, or stale unmatched period still remain `manual_required`.

## Testing

Focused validation should cover:

- CLI defaults: queue enabled, queue concurrency `3`, DeepSeek concurrency `3`.
- Fast mode still disables DeepSeek and uses regex.
- Search profile changes expose expected query families/evidence fields.
- Task planner output includes tuned fields for representative high-gap indicators.
- Existing Stage2 fallback tests still pass.

## Non-Goals

- No change to Stage2.5 schema.
- No relaxation of quality gates.
- No Tavily candidate-search parallelization in this iteration.
- No change to DeepSeek model default.
