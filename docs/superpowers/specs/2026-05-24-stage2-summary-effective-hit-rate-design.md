# Stage2 Summary Effective Hit Rate Design

## Goal

Fix Stage2 summary observability so operators and automation read the correct Stage2 hit-rate metric after structured-provider-first was added.

The current implementation can produce a successful Stage2 structured-provider run while legacy search-only fields still show `task_search_success=0` and `search_success_rate_incremental=0.0`. Those legacy fields are useful for Tavily/Exa search-chain diagnosis, but they are misleading when treated as total Stage2 hit rate. The fix keeps legacy search semantics intact and makes `stage2_effective_hit_rate` the primary success metric everywhere Stage2 is summarized.

## Non-Goals

- Do not change structured-provider fetch, parse, validation, fallback, or registry behavior.
- Do not change Tavily-first / Exa failover state machine behavior.
- Do not change DeepSeek extraction or regex fallback behavior.
- Do not change Stage2.5 manual injection, fund-flow gate, Stage3 gate, or report generation behavior.
- Do not make `task_search_success` count structured-provider success.

## Current Problem

The Stage2 run log can contain all of the following at the same time:

```json
{
  "task_search_success": 0,
  "search_success_rate_incremental": 0.0,
  "task_structured_success": 12,
  "stage2_effective_success": 12,
  "stage2_effective_hit_rate": 0.7058823529411765,
  "structured_provider_success_count": 12,
  "manual_required": ["CN10Y_CDB", "BCOM", "mlf", "etf"]
}
```

This is internally valid:

- `task_search_success` means Tavily/Exa search extraction success.
- `task_structured_success` means structured-provider writeback success.
- `stage2_effective_hit_rate` means Stage2 writeback success across structured providers plus search extraction.

The operational problem is presentation. CLI output and some human review paths still lead with `增量命中率` / search-only fields, so a healthy structured-provider run can be misread as a 0% Stage2 run.

## Metric Contract

Keep these legacy search-chain fields unchanged:

- `task_search_success`: count of tasks completed by search extraction.
- `task_search_failed`: count of actionable tasks that ended as `manual_required`.
- `search_success_rate_incremental`: `task_search_success / (task_search_success + task_search_failed)`.
- `search_success_by_category`: category breakdown for search extraction only.

Use these as the primary Stage2 writeback fields:

- `task_structured_success`: count of tasks completed by structured providers.
- `stage2_effective_success`: `task_structured_success + task_search_success`.
- `stage2_effective_failure`: count of actionable tasks that ended as `manual_required`.
- `stage2_effective_denominator`: `stage2_effective_success + stage2_effective_failure`.
- `stage2_effective_hit_rate`: `stage2_effective_success / stage2_effective_denominator`.

Use these structured-provider diagnostics for audit:

- `structured_provider_attempt_count`
- `structured_provider_success_count`
- `structured_provider_fallback_to_search_count`
- `structured_provider_success_by_key`
- `structured_provider_error_breakdown`

`task_completed/task_total` remains legacy completion accounting and is not the Stage2 hit-rate denominator.

## CLI Summary Design

The Stage2 CLI summary should lead with effective Stage2 writeback metrics:

```text
[Stage2 Summary]
  任务总数: 18, legacy完成: 14, Stage2有效成功: 12, 结构化源成功: 12, 搜索链路成功: 0, 搜索失败: 5, 跳过已有值: 2, 待人工: 4
  Stage2有效命中率: 70.6% (12/17); 搜索链路命中率: 0.0% (0/5)
```

The exact numbers depend on the run. The important behavior is:

- `Stage2有效命中率` appears before search-only hit rate.
- `搜索链路命中率` is clearly labeled as search-only.
- The old standalone label `增量命中率` is no longer used as the main Stage2 success statement.
- The output shows numerator and denominator so operators can audit the rate without opening JSON.

The existing warning for pending manual tasks remains unchanged.

## JSON Summary Design

The summary JSON should continue writing current fields and add explicit denominator fields:

```json
{
  "task_search_success": 0,
  "task_structured_success": 12,
  "task_search_failed": 5,
  "stage2_effective_success": 12,
  "stage2_effective_failure": 5,
  "stage2_effective_denominator": 17,
  "stage2_effective_hit_rate": 0.7058823529411765,
  "search_success_rate_incremental": 0.0
}
```

The denominator fields are intentionally redundant. They make artifact review safer and prevent scripts from reconstructing the denominator incorrectly from `task_total`, `task_completed`, or `task_skipped_existing`.

## Testing Design

Add focused unit coverage in `tests/test_stage2_unified.py`.

Required test cases:

1. Effective hit-rate helper returns `12 / 17` for 12 successes and 5 failures.
2. Stage2 summary metric assembly preserves search-only semantics while counting structured success in effective fields:
   - `task_search_success == 0`
   - `search_success_rate_incremental == 0.0`
   - `task_structured_success == 12`
   - `stage2_effective_success == 12`
   - `stage2_effective_failure == 5`
   - `stage2_effective_denominator == 17`
   - `stage2_effective_hit_rate == 12 / 17`
3. CLI text formatting prioritizes effective hit rate:
   - output contains `Stage2有效命中率`
   - output contains `搜索链路命中率`
   - output does not contain standalone `增量命中率`

If the current summary construction is too deeply embedded in `main()`, extract a small pure helper that computes and formats summary metrics from counts. The helper should not perform I/O and should be covered by unit tests.

## Documentation Design

Update the following docs only if the implementation changes their exact wording:

- `AGENTS.md`
- `CLAUDE.md`
- `README_STAGE2_SNIPPET.md`

The documented operator rule should be:

- Daily Stage2 success: read `stage2_effective_hit_rate`.
- Search-chain diagnosis: read `search_success_rate_incremental`.
- `search_success_rate_incremental=0.0` does not mean Stage2 total hit rate is 0 when `task_structured_success` or `structured_provider_success_count` is non-zero.

## Acceptance Criteria

The fix is accepted when all are true:

1. For the structured-provider golden log shape, effective rate is `12 / 17 = 70.6%` and search-chain rate remains `0 / 5 = 0.0%`.
2. Stage2 CLI summary leads with `Stage2有效命中率`.
3. JSON summary contains `stage2_effective_failure` and `stage2_effective_denominator`.
4. Existing Tavily/Exa search diagnostics remain readable and search-only.
5. Focused tests pass:

```bash
.venv/bin/pytest -q tests/test_stage2_unified.py tests/test_stage2_structured_providers.py
```

6. Syntax check passes:

```bash
.venv/bin/python -m py_compile scripts/stage2_unified_enhancer.py src/datasource/providers/stage2_structured/*.py
```

7. Full regression can be run before final completion:

```bash
.venv/bin/pytest -q
```

## Implementation Risk

The main risk is accidentally changing the meaning of `task_search_success` or `search_success_rate_incremental`. Those fields must stay search-only. Existing dashboards and troubleshooting docs rely on them to diagnose Tavily/Exa and DeepSeek behavior separately from structured-provider success.

The second risk is overfitting to the 2026-05-23 artifact. The implementation should compute denominators from task result types, not from fixed task names or fixed counts.
