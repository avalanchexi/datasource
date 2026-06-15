# 批次 C3:Stage2 执行层拆分 — 设计文档

> Spec for the 2026-06 refactor, batch C3(REFACTOR_PLAN §6 / TODOS C3)。
> Status: 2026-06-15 设计批准(brainstorming 产出)。前置 PR-C2 已 squash 合入并推送 main `fcb661f`。
> 起点:worktree `.worktrees/codex-batch-c3-stage2-execution-split`, branch `codex/batch-c3-stage2-execution-split`, HEAD `fcb661f`;baseline `1169 passed, 3 skipped`。
> 执行以 C3 implementation plan 为准;本 spec 锁定边界、风险和验收,不直接授权代码改动。

## 1. 目的与定位

C3 继续 Stage2 巨石拆分,目标是把 `scripts/stage2_unified_enhancer.py` 中仍停留在主脚本的执行层下沉到 `src/datasource/engines/stage2/`。C2 已完成 common / cli / query_planner / structured_runner / diagnostics / validation / extraction_apply 的机械搬移,但 `_execute_tasks` 仍留在主脚本并承担任务生命周期主循环。

C3 的职责是把执行层变成独立模块,同时保持 CLI/main 编排、run 输出、policy/quality/observability 仍在主脚本。此 PR 是机械拆分,不是行为优化:搜索、抽取、fallback、fund_flow gate、forex gate、structured provider rollback、manual_required 语义都必须逐字保留。

## 2. 范围

**In scope**
- 新建 `src/datasource/engines/stage2/execution.py`。
- 机械搬移执行层:
  - `_execute_tasks`
  - `_try_structured_provider`
  - `_DeepSeekCircuitBreaker`
  - `_is_deepseek_timeout`
  - `_mark_stale_refresh_failure`
- 为避免 `src` 反向 import 主脚本,一并搬移执行层直接依赖的 glue:
  - `_is_placeholder_number`
  - `_has_non_placeholder_value`
  - `_append_task_log`
  - `_update_missing_items`
- 主脚本继续 re-export 以上符号,现有 tests 从 `scripts.stage2_unified_enhancer` import 的路径保持可用。
- `main()` 继续调用主脚本全局 `_execute_tasks` 名称,保留 `tests/test_stage2_unified.py` 对 `stage2._execute_tasks` 的 monkeypatch 行为。
- 扩展 characterization / import identity / replay datetime freeze。

**Out of scope**
- 不拆 `_execute_tasks` 内部嵌套 helper 到多个模块;本 PR 只做执行层整块搬移。
- 不改 `_execute_tasks` / `_try_structured_provider` 签名。
- 不重写 queue、failover、search candidate、Tavily extract、DeepSeek、regex fallback、field retry 或 writeback 逻辑。
- 不回收 `extraction_apply` 对 `scripts.stage2_5_injector.py` 的 fund_flow helper 跨脚本 import;这是 C4。
- 不做 `_safe_number` 与 `utils/coercion` 语义合一;继续延后。
- 不做 main 入口瘦身到 <=30 行;这是 C 批次终态。

## 3. 目标结构

### `src/datasource/engines/stage2/execution.py`

该模块成为 Stage2 执行层的唯一归宿。它依赖 C1/C2 已拆模块与外部 adapter/provider,但不得 import `scripts.stage2_unified_enhancer`。

模块应包含:
- 执行入口:`_execute_tasks(...)`
- structured 执行车道:`_try_structured_provider(...)`
- DeepSeek 执行控制:`_DeepSeekCircuitBreaker`, `_is_deepseek_timeout`
- force-refresh finalization helper:`_mark_stale_refresh_failure`
- 执行 glue:`_is_placeholder_number`, `_has_non_placeholder_value`, `_append_task_log`, `_update_missing_items`

`_execute_tasks` 内部 helper 保持原闭包结构。原因是这些 helper 共享 `stats`, `active_search_backend`, `failover_reason`, `active_tavily_limit_metadata`, DeepSeek breaker, extract cooldown trackers, queue, client/exa/extractor 等状态。进一步拆散会把本 PR 从机械搬移变成行为重构。

### `scripts/stage2_unified_enhancer.py`

主脚本保留 CLI/main/orchestration:
- argparse/env/cache/client/extractor 初始化
- Stage2TaskPlanner / task filter / task-file resume
- output json / websearch result / observability / quality / policy / source conflict writes
- gap monitor / derived metrics / summary printing

主脚本从 `datasource.engines.stage2.execution` re-export C3 moved names,与 C1/C2 风格一致。`main()` 继续使用脚本全局 `_execute_tasks`,不改成 `stage2_execution._execute_tasks` 直调,以保持既有 monkeypatch 合同。

## 4. 设计决策

**推荐方案:执行层整块搬移到 `execution.py`。**

这是最低风险方案。`_execute_tasks` 当前约 2600 行,但其内部 helper 以闭包状态耦合。把整块搬到 `execution.py` 可以消除主脚本巨石压力,建立执行层边界,同时不改变任何执行语义。

**拒绝方案 A:只搬 `_execute_tasks`,让 `execution.py` import 主脚本 glue。**

这会产生 `src` -> `scripts` 反向依赖,违反 C2 后的依赖方向约束,也会让后续 C4/C5 更难拆。

**拒绝方案 B:把 `_execute_tasks` 内部五段拆成多个模块。**

这可能是终态方向,但不是 C3。queue/retry/failover/field retry 的状态共享复杂,在本 PR 内分拆会扩大行为风险,也会让 replay mismatch 难定位。

## 5. 执行层生命周期边界

C3 plan 应把 `_execute_tasks` 按生命周期做 characterization,但实现搬移仍保持整块:

1. stats/backend 初始化:统计字段、Tavily/Exa active backend、DeepSeek semaphore/breaker、extract cooldown tracker。
2. pre-search lane:existing-value skip、structured-provider-first、Tavily unavailable / Exa failover fast switch。
3. search/extract lane:Tavily/Exa search candidates、query quality、Tavily extract、422 cooldown、official extract domain filter、DeepSeek/regex fallback。
4. validation/writeback lane:fund_flow field retry、general/fund_flow validation、manual_required 判定、`_apply_extraction`、post-writeback blocker、missing-items cleanup。
5. finalization lane:queue drain、force-refresh stale markers、`result_type` finalization、websearch result normalization。

这些阶段是测试和 plan 的结构语言,不是本 PR 内要引入的新函数边界。

## 6. 必须冻结不动的业务热点

- structured provider fallback、snapshot rollback、policy gate、success record schema。
- Tavily quota/rate/payment failover 与 environment proxy fast switch。
- Exa failover metadata、query attempts、manual_required records。
- candidate query quality、post-filter query switch、low-score gate。
- Tavily extract official-domain filter、422 cooldown、extract global disable/cooldown stats。
- DeepSeek retry、hard timeout、circuit breaker、regex fallback。
- fund_flow field retry、source tier/window evidence/metric basis、estimated/manual gate。
- forex zero-placeholder prevention indirectly reached through `_apply_extraction`.
- writeback 后 post-writeback manual blockers 与 missing-items cleanup。
- force-refresh stale failure markers and result_type finalization。

## 7. Tests and Characterization

C3 must start with tests before code movement.

**New or changed tests**
- Extend `tests/test_stage2_c2_split_characterization.py`:
  - import `datasource.engines.stage2.execution` as `EXECUTION`
  - add C3 moved/export list for `_execute_tasks`, `_try_structured_provider`, `_DeepSeekCircuitBreaker`, `_is_deepseek_timeout`, `_mark_stale_refresh_failure`, `_is_placeholder_number`, `_has_non_placeholder_value`, `_append_task_log`, `_update_missing_items`
  - assert monolith re-export objects are identical to execution module objects after the move
  - flip the existing `_try_structured_provider` "stays in monolith for C3" assertion into an execution-module identity assertion
- Add phase-level characterization around representative existing tests or a dedicated lightweight test table. It should lock:
  - skip existing value path
  - structured success path
  - structured fallback -> search path
  - DeepSeek timeout/circuit breaker path
  - fund_flow field retry / manual gate path
  - force-refresh stale finalization path
- Extend `tests/test_stage2_replay_harness.py::_freeze_stage2_datetime` to include `datasource.engines.stage2.execution`.

**Replay constraints**
- Do not set `STAGE2_REPLAY_UPDATE_GOLDEN`.
- Replay golden must be byte-stable. Any mismatch stops execution and is reported; do not regenerate fixtures in C3.
- `time.perf_counter` currently patches the shared `time` module. If implementation ever switches to `from time import perf_counter`, the plan must add an explicit execution-module freeze. C3 should keep `import time` style.

## 8. Verification Commands

C3 plan should include at least:

```bash
bash scripts/env_probe.sh
bash run_clean.sh python -m pytest tests/test_stage2_c2_split_characterization.py -q
env -u STAGE2_REPLAY_UPDATE_GOLDEN bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q
bash run_clean.sh python -m pytest tests/test_stage2_structured_integration.py tests/test_stage2_structured_golden.py -q
bash run_clean.sh python -m pytest tests/test_stage2_fallbacks.py -q
bash run_clean.sh python -m pytest tests/test_stage2_unified.py -k "execute_tasks or deepseek_circuit_breaker or gap_monitor_pending_only_incomplete" -q
bash run_clean.sh python -m pytest tests/test_stage2_unified_pipeline.py tests/test_deepseek_defaults.py -q
bash run_clean.sh python -m py_compile scripts/stage2_unified_enhancer.py src/datasource/engines/stage2/*.py
bash run_clean.sh python -m flake8 src/datasource/engines/stage2/
bash run_clean.sh python -m pytest -q
```

Expected baseline from C3 worktree before implementation:`1169 passed, 3 skipped`.

## 9. Documentation and Carry-forward

- Update `optimization/20260610_refactor_plan/TODOS.md` only if the implementation plan includes a final documentation task; do not churn it during spec-only work unless needed.
- Keep C4 carry-forward explicit:
  - Stage2.5 fund_flow helper extraction remains C4.
  - `extraction_apply.py` cross-script fund_flow import remains marked `# C4-cleanup`.
- Keep C3 carry-forward for terminal C cleanup explicit:
  - main entry <=30 lines remains terminal cleanup, not C3.

## 10. Risk and Mitigation

| Risk | Mitigation |
|---|---|
| `execution.py` accidentally imports `scripts.stage2_unified_enhancer` | plan must run `rg "stage2_unified_enhancer" src/datasource/engines/stage2/execution.py` and fail on match |
| replay observes wall-clock datetime in new module | add `stage2_execution` to `_freeze_stage2_datetime` loop |
| `main()` monkeypatch contract breaks | keep `main()` calling script-global `_execute_tasks`; identity tests prove re-export |
| queue/failover behavior drifts | move `_execute_tasks` body mechanically; do not split inner helpers |
| fund_flow/forex gates drift | rely on existing extraction_apply/validation modules unchanged plus replay/fallback/structured tests |
| golden fixtures get overwritten | verification commands explicitly unset `STAGE2_REPLAY_UPDATE_GOLDEN`; mismatch stops |

## 11. Acceptance Criteria

- `src/datasource/engines/stage2/execution.py` exists and contains the C3 execution-layer symbols.
- `scripts/stage2_unified_enhancer.py` re-exports C3 moved names as the exact same objects.
- No `src/datasource/engines/stage2/execution.py` import from `scripts.stage2_unified_enhancer`.
- `_execute_tasks` and `_try_structured_provider` signatures are unchanged.
- Replay harness golden remains unchanged and byte-stable.
- Focused Stage2 execution tests and full `pytest -q` pass with no count regression from baseline.
- No changes to `data/runs`, `data/trend_history`, replay golden files, or live-search behavior.
