# Tavily 432/433 Exa Failover Audit Design

Date: 2026-05-23

## Context

The 2026-05-22 full pipeline run showed Stage2 receiving Tavily HTTP 432 errors:

```text
Client error '432 ' for url 'https://api.tavily.com/search'
```

Preflight passed and Tavily was reachable, but Stage2 did not classify 432 as a quota or payment limit. The backend state stayed on Tavily, Exa did not take over, and all incremental search tasks failed into manual-required output. Stage2.5 recovered most non-fund-flow fields from manual data, but Stage3 correctly blocked because `fund_flow.etf.recent_5d` and `fund_flow.etf.total_120d` were still missing.

Tavily's OpenAPI schema identifies HTTP 432 as key/plan limit exceeded and HTTP 433 as PayGo limit exceeded. These should be treated as Tavily unavailable quota/payment states for the existing Exa failover path.

## Goals

- Treat Tavily HTTP 432 and 433 as failover-triggering Tavily limit errors.
- Keep the current Tavily-first behavior and switch to Exa only after Tavily becomes unavailable due to quota, rate limit, or payment/plan limit.
- Apply Exa takeover to the current task and all remaining Stage2 tasks, including fund flow tasks.
- Preserve existing DeepSeek, regex extraction, post-filtering, Stage2.5 injection, and Stage3 policy gates.
- Improve failure diagnostics so the next run can be audited from Stage2 logs and `websearch_results_auto.json`.
- Preserve the strict ETF fund-flow gate: missing 5-day or 120-day ETF windows must still block Stage3.

## Non-Goals

- Do not loosen fund-flow quality gates.
- Do not mark estimated ETF fund-flow windows as non-estimated.
- Do not add a new search provider or replace the existing Exa client.
- Do not perform a broad extraction or search-backend refactor.
- Do not rerun Tavily repeatedly after a same-run quota/payment limit is detected.

## Architecture

Stage2 keeps the current search state machine:

```text
tavily_active -> exa_active
```

The transition is triggered only by Tavily limit failures:

- HTTP status: 402, 403, 429, 432, 433
- Response text containing existing quota, rate-limit, billing, or payment markers

Environment and connectivity failures remain separate:

- DNS failures
- TLS errors
- SOCKS or proxy errors
- generic network timeouts

Those errors must not trigger Exa. They continue to produce manual-required diagnostics or the existing environment-error path.

## Components

### Tavily Limit Classifier

Update the shared classifier used by search and extract paths so that:

- Exceptions with `.response.status_code in {402, 403, 429, 432, 433}` return true.
- Payload responses with `status` equal to any of those codes return true.
- Text-only messages still match the existing quota/rate-limit/payment markers.

The classifier should use one shared constant for these statuses to prevent search and extract paths drifting.

### Structured Tavily Diagnostics

Add a small diagnostics helper for Tavily HTTP errors. It should return only safe fields:

- `tavily_http_status`
- `tavily_error_message` or a truncated response-text summary
- request id fields when present in headers, such as `x-request-id` or provider-specific equivalents
- exception type

The helper must not log API keys or full request payloads.

### Failover Output

When a Tavily limit failure occurs:

- If Exa is available, activate `exa_active` and run the current task through Exa query candidates.
- If Exa succeeds, write normal Exa-backed search/extraction output with `search_backend_state=exa_active`.
- If Exa is unavailable, empty, or errors, write a manual-required skeleton with Tavily diagnostics and Exa diagnostics.
- Remaining tasks in the same Stage2 run should use Exa directly after the state transition.

The same result should be visible in:

- `logs/runs/YYYYMMDD/stage2_unified_log.json`
- `data/runs/YYYYMMDD/gap_monitor.json`
- `data/runs/YYYYMMDD/websearch_results_auto.json`

## ETF Fund Flow Gate

ETF fund-flow validation stays strict:

- `recent_5d` must be present and backed by acceptable window evidence.
- `total_120d` must be present and backed by acceptable window evidence.
- `--allow-estimated` must not bypass missing ETF windows.

When ETF windows are missing, the system should keep emitting:

- `manual_required=true`
- `manual_reason` including `fund_flow_window_missing`
- policy blockers for both `recent_5d` and `total_120d`

This is expected behavior, not a Stage3 bug.

## Data Flow

1. Stage2 starts in `tavily_active`.
2. Tavily search or extract raises/returns a limit error.
3. The classifier marks it as a Tavily limit failure.
4. Stage2 records structured Tavily diagnostics.
5. Stage2 activates Exa if an Exa client is available.
6. The current task is retried through Exa query candidates.
7. Remaining tasks run through Exa without probing Tavily again.
8. DeepSeek or regex extraction consumes Exa snippets through existing code paths.
9. Stage2 writes websearch results, summary diagnostics, gap monitor, quality metrics, and policy evaluation.
10. Stage2.5 and Stage3 continue enforcing their existing gates.

## Error Handling

- Tavily 432/433: treated as limit failures and eligible for Exa failover.
- Tavily 402/403/429: unchanged, still eligible for Exa failover.
- Exa missing key or missing dependency: output manual-required skeleton, increment `exa_unavailable`.
- Exa empty results: output manual-required skeleton, increment `exa_failover_empty`.
- Exa provider error: output manual-required skeleton with `exa_error_tag`, status, and request id if available.
- Environment/proxy/DNS/TLS errors: do not activate Exa.

## Testing

Add or update focused tests for:

- `_is_tavily_quota_error` returns true for HTTP 432 and 433 exceptions.
- `_is_tavily_quota_response` returns true for payload statuses 432 and 433.
- Tavily search 432 activates Exa and sets `search_backend_final=exa`.
- Tavily extract 433 activates Exa through the extract fallback path.
- Tavily limit failure with no Exa writes manual-required skeletons into websearch results.
- ETF fund flow with missing `recent_5d` and `total_120d` remains blocked by policy/Stage3 behavior even when `--allow-estimated` is used.

Verification should include the existing Stage2 fallback tests plus the smallest Stage3/policy test needed for ETF gate behavior.

## Acceptance Criteria

- A simulated Tavily 432 search failure causes `tavily_to_exa_failover=true`.
- A simulated Tavily 433 extract failure causes `tavily_to_exa_failover=true`.
- Same-run tasks after failover use Exa rather than Tavily.
- `websearch_results_auto.json` contains auditable manual-required skeletons when Exa cannot satisfy a task.
- Tavily diagnostics include status and safe error details without secrets.
- ETF fund-flow missing windows still block Stage3.
- Existing tests continue to pass.
