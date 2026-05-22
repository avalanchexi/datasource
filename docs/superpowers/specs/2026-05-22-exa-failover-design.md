# Exa Failover for Stage2 Search

Date: 2026-05-22

## Context

Stage2 currently treats Tavily as the only active search backend. The project already has an Exa adapter, `exa-py` in dependencies, and partial Exa fallback wiring, but the active behavior does not meet the desired operating model:

- `EXA_API_KEY` can be present and `exa-py` can be importable.
- Exa fallback is currently opt-in through `--enable-exa-fallback` or `STAGE2_ENABLE_EXA_FALLBACK=1`.
- Tavily quota or rate-limit errors still fast-switch remaining tasks to `manual_required`.
- `fund_flow` tasks are currently excluded from Exa fallback.
- Existing source labels can still write `tavily+deepseek` even when Exa produced the snippets.

The goal is to keep Tavily first, but when Tavily reaches its usage limit or is otherwise quota/rate unavailable, Exa should replace Tavily's Stage2 search capability for the rest of the run, including fund-flow tasks. Exa does not replace DeepSeek extraction, Stage2.5 injection, trend history, or quality gates.

The real Exa API key must remain in local environment configuration only. It must not be committed or written into project documentation.

## Goals

1. Keep Tavily-first behavior during normal runs.
2. Automatically switch the current Stage2 run to Exa when Tavily returns quota, rate-limit, or payment-related unavailable errors.
3. Retry the current failed task with Exa, then run all remaining tasks with Exa without issuing more Tavily calls.
4. Include `fund_flow` tasks in Exa failover, while preserving all existing source tier, window evidence, metric basis, and estimated-value gates.
5. Preserve DeepSeek and regex extraction behavior by feeding them normalized snippets regardless of search backend.
6. Make Exa success and failure auditable through structured diagnostics.
7. Avoid increasing DeepSeek truncation or timeout risk when Exa returns long page contents.

## Non-Goals

1. Do not make Exa the default primary search backend.
2. Do not use Exa failover for environment failures such as SOCKS dependency errors, proxy pollution, DNS failure, or TLS failure.
3. Do not loosen `fund_flow` quality gates.
4. Do not add a second set of Exa-specific search profiles.
5. Do not store the real Exa API key in code, docs, tests, fixtures, commits, or logs.

## Chosen Approach

Use a search backend failover state machine:

```text
tavily_active -> exa_active
```

Stage2 starts in `tavily_active`. If Tavily search or extract raises a quota/rate/payment unavailable signal, Stage2 switches the run to `exa_active`. The task that observed the Tavily limit is retried immediately with Exa. Remaining tasks go directly to Exa and no longer call Tavily.

This is intentionally different from the existing manual fast-switch path. Tavily quota should no longer mean "the rest of the run is manual"; it should mean "the rest of the run uses Exa, and only Exa failures become manual."

## Trigger Rules

Fail over to Exa only for Tavily usage-limit or billing-style unavailability:

- HTTP `402`
- HTTP `403`
- HTTP `429`
- message contains `quota`
- message contains `rate limit`
- message contains `payment`

Do not fail over to Exa for:

- `environment_proxy_error`
- missing SOCKS support
- DNS failure
- TLS or certificate failure
- generic connection failures that indicate the local environment may be broken

Those environment failures should keep the existing fast-fail behavior because they can also affect Exa and DeepSeek.

Tavily extract `422` is not a global Exa trigger. It remains an extract-specific condition handled by existing extract cooldown and direct-snippet extraction paths. If a `422` response also contains quota/rate/payment semantics, the quota/rate/payment branch wins.

## Architecture

### AsyncExaClient

`src/datasource/adapters/exa_client.py` remains the only Exa SDK boundary.

Responsibilities:

- Call `Exa.search(...)` through `exa-py`.
- Map Exa results to Tavily-compatible snippets:

```json
{
  "url": "...",
  "title": "...",
  "snippet": "...",
  "content": "...",
  "score": null,
  "published_date": "..."
}
```

- Use current SDK-compatible parameters:
  - `query`
  - `num_results`
  - `include_domains`
  - `exclude_domains`
  - `start_published_date`
  - `end_published_date`
  - `start_crawl_date`
  - `end_crawl_date`
  - `type`
  - `contents`
- Truncate long `text`, `summary`, and `highlights` before returning snippets to Stage2.
- Expose structured error metadata:
  - `exa_error_type`
  - `exa_http_status`
  - `exa_error_tag`
  - `exa_error_message`
  - `exa_request_id` when available

The adapter should not know Stage2 task semantics beyond returning normalized snippets and structured errors.

### Stage2 Unified Enhancer

`scripts/stage2_unified_enhancer.py` owns the failover state:

```text
active_search_backend: tavily | exa
failover_reason: quota_or_rate_limit | None
failover_started_at_task_id: str | None
```

Behavior:

1. Start with `active_search_backend=tavily`.
2. On Tavily quota/rate/payment error:
   - set `active_search_backend=exa`
   - set `failover_reason=quota_or_rate_limit`
   - increment failover counters
   - retry the current task with Exa
3. For every later task:
   - skip Tavily search and extract
   - call Exa search directly
4. If Exa succeeds:
   - continue through existing snippet filtering, DeepSeek/regex extraction, validation, writeback, `websearch_results`, and task logs
5. If Exa fails or returns no usable snippets:
   - write the existing manual-required skeleton
   - include structured Exa diagnostics

Exa should be automatically available for failover when `EXA_API_KEY` is set and `exa-py` is importable. The existing `--enable-exa-fallback` flag can remain for compatibility, but Tavily quota failover should not require it.

### Search Profiles

Do not add Exa-specific profiles in the first implementation.

Exa reuses existing task fields:

- `query`
- `query_families`
- `field_queries`
- `preferred_domains`
- `exclude_domains`
- `max_age_days`
- `max_results`
- `required_keywords`
- `issuer`
- `issuer_aliases`
- `expected_period_tokens`
- `required_output_fields`
- `evidence_keywords`

Tavily-only fields such as `topic`, `language`, `time_range`, `search_depth`, `days`, and `auto_parameters` are ignored by Exa unless they have already influenced query construction.

## DeepSeek Compatibility

DeepSeek extraction already consumes `snippets: List[dict]`, not Tavily API responses directly. The Exa integration should preserve this contract.

Required snippet fields:

- `url`
- `title`
- `snippet`
- `content`
- `score`
- `published_date`

Important constraints:

- `source_url` returned by DeepSeek must still come from snippet `url`.
- Exa `content` must be bounded so DeepSeek prompt size stays stable.
- Exa mode does not call Tavily extract.
- Exa `contents={text/highlights/summary}` supplies the evidence that Tavily search plus Tavily extract used to provide.
- Exa `score=None` is normal and should not be treated as low score.

Quality filtering in Exa mode should rely primarily on:

- preferred domain match
- issuer match
- expected period match
- required keywords
- output field evidence
- numeric value evidence
- bad URL patterns

## Fund Flow Compatibility

Exa failover includes `fund_flow` tasks: `northbound`, `southbound`, `etf`, and `margin`.

This only changes the search provider. It does not change the definition of a trusted fund-flow value.

A fund-flow value is trusted only when all existing gates pass:

- `recent_5d` is present and non-placeholder
- `total_120d` is present and non-placeholder
- `source_tier` is `tier1` or `tier2`
- `window_evidence` is one of:
  - `direct_window`
  - `direct_daily_series`
  - `direct_balance_delta`
- `metric_basis` is not:
  - `news_net_flow`
  - `estimated_net_flow`
- suspicious zero values are rejected

If Exa finds only news summaries, single-day values, quarterly summaries, year-to-date descriptions, or values without direct target-window evidence, the pipeline should still mark the result as `is_estimated=true` and block with `estimated_not_allowed` or `fund_flow_window_missing`.

## Source Labels and Audit Fields

When Exa supplies snippets, write source labels that reflect Exa:

- DeepSeek extraction: `exa+deepseek`
- regex extraction: `exa_regex`

Do not write `tavily+deepseek` for Exa-backed results.

Task logs and `websearch_results_auto.json` should include:

- `search_backend`
- `search_backend_state`
- `search_note`
- `failover_reason`
- `failover_from_backend`
- `failover_started_at_task_id`
- `exa_query`
- `exa_domains`
- `exa_result_count`
- `exa_usable_count`
- `exa_error_tag`
- `exa_http_status`
- `exa_error_message`

Stage2 summary should include:

- `search_backend_final`
- `tavily_to_exa_failover`
- `tavily_to_exa_failover_count`
- `exa_failover_success`
- `exa_failover_empty`
- `exa_failover_error`
- `exa_error_breakdown`
- `exa_error_samples`

This avoids repeating the historical `exa_error=20` but no actionable details problem.

## Error Handling

### Tavily quota/rate/payment

- Switch global state to `exa_active`.
- Retry the current task with Exa.
- Run remaining tasks with Exa.
- Preserve the original Tavily error in task diagnostics.

### Exa unavailable or missing key

- If Tavily hits quota and Exa is unavailable, write manual skeletons for affected tasks.
- Record `exa_unavailable` with the exact reason:
  - missing key
  - missing dependency
  - SDK import failure
  - API error
  - empty result

### Exa empty or unusable results

- Keep existing manual-required behavior.
- Record query, domains, date filters, raw result count, usable count, and filtering reason.

### Environment proxy errors

- Keep existing fast-fail behavior.
- Do not switch to Exa.

### DeepSeek truncation or timeout

- Keep existing `deepseek_json_truncated`, timeout, circuit-breaker, and regex fallback behavior.
- Exa snippets must be truncated before DeepSeek sees them.

## Configuration

Required for failover:

- `EXA_API_KEY` in the local environment
- `exa-py` importable in the active Python environment

Do not commit real keys.

`.env.example` should continue to use an empty placeholder:

```dotenv
EXA_API_KEY=
```

The existing `--enable-exa-fallback` and `STAGE2_ENABLE_EXA_FALLBACK` can remain, but Tavily quota failover should automatically enable Exa when the key and dependency are present.

## Testing

Focused tests should cover:

1. Tavily `429` on the current task switches state to `exa_active`, retries the current task with Exa, and does not call Tavily for later tasks.
2. Tavily `402/403/payment/quota/rate limit` all trigger failover.
3. Tavily `environment_proxy_error` does not trigger Exa and still fast-fails.
4. Tavily extract `422` does not trigger global Exa failover.
5. Exa-backed non-fund-flow success flows through DeepSeek and writes `exa+deepseek`.
6. Exa-backed regex fallback writes `exa_regex`.
7. Exa-backed fund-flow task can write values only when direct window evidence and source tier rules pass.
8. Exa-backed fund-flow task with weak news evidence remains blocked by `estimated_not_allowed`.
9. Exa `score=None` does not trigger `low_score_all`.
10. Exa overlong content is truncated before DeepSeek.
11. Exa error metadata appears in task logs, websearch results, and summary.
12. `EXA_API_KEY` presence enables quota failover without `--enable-exa-fallback`.
13. Missing `EXA_API_KEY` after Tavily quota writes manual skeletons with `exa_unavailable`.
14. Existing Stage2.5 and policy gate tests for `fund_flow_window_missing` and `estimated_not_allowed` still pass.

## Rollout

1. Implement failover state and Exa diagnostics behind the existing Stage2 execution path.
2. Keep Tavily-first as the default.
3. Run targeted Stage2 fallback and Exa tests.
4. Run fund-flow quality gate tests.
5. Update `AGENTS.md` and `CLAUDE.md` only with stable operating rules after implementation behavior is verified.

## Acceptance Criteria

1. Tavily quota/rate/payment failure no longer turns the rest of the run into immediate `manual_required` when Exa is configured.
2. The current Tavily-failed task and all remaining tasks use Exa after failover.
3. No additional Tavily calls occur after failover.
4. DeepSeek receives bounded, normalized snippets and continues to enforce source URL evidence.
5. Fund-flow results from Exa remain subject to existing gates.
6. Stage2 summary and per-task logs explain Exa success, empty results, and errors with actionable detail.
7. Reports and downstream artifacts no longer label Exa-backed values as `tavily+deepseek`.
8. Real API keys are not committed.
