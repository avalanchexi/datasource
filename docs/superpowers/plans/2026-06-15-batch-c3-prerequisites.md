# PR-C3 预置 / Carry-forward 备忘（非完整实施计划）

> **这是什么**：C3 的前置约束与从 C2 结转的待办登记。**不是**可执行实施计划——按本仓库惯例,完整 C3 plan 必须在 **C3 開工时从当时 HEAD(C2 合入后)现生成**(`_execute_tasks` 行号在 C2 后会大幅下移)。本备忘只保证 C2 期间做出的范围决策不丢失,供 C3 brainstorm→spec→plan 消费。
> **状态**:2026-06-15 创建(C2 执行中,停在 Task 4 后修正 Task 5)。前置 PR-C2 尚未合入 main。

## C3 范围（来自 REFACTOR_PLAN §6 / TODOS C3 行）

- **PR-C3**:`_execute_tasks`(C2 后仍在主脚本,~2600 行)按**任务生命周期**切五段;**先加阶段级 characterization test**,再切。

## 从 C2 结转的硬性待办（C3 必须接手）

1. **`_try_structured_provider`（async,structured 执行车道编排器)→ 与 `_execute_tasks` 一并在 C3 切分。**
   - 背景:C2 brainstorming 发现它不是 structured_runner 叶子,而是执行车道编排器,`fetch→_augment_extraction_metadata→_validate_*→_apply_extraction→_post_writeback_manual_reason→_update_missing_items→_append_task_log`。
   - 依赖:C2 已搬的 extraction_apply / diagnostics / validation 簇(向下,re-import 可达)+ **out-of-scope glue `_update_missing_items` / `_append_task_log`**(被 `_execute_tasks` 重度使用)。
   - C2 决策:留主脚本(零反向 import),C3 处理。C3 切分时需决定:把 `_update_missing_items`/`_append_task_log` 等 glue 与执行车道一起下沉到新执行模块,还是另立 io/glue 模块。`_try_structured_provider` 与 `_execute_tasks` 的 search 链路共享同一套 apply/validate/post-writeback/missing-items/task-log 调用,适合作为执行层的两条车道一起切。

2. **deepseek 执行件 → C3**:`_DeepSeekCircuitBreaker`(class)、`_is_deepseek_timeout`、`_mark_stale_refresh_failure` 仅被 `_execute_tasks` 使用(C2 未搬),随执行层一并切分。

3. **io/glue 归宿待定(C3/终态)**:`_load_json`/`_dump_json`/`_append_task_log`/`_merge_missing_items`/`_apply_aliases`/`_warn_disable_extract_on_critical_tasks`/`_check_task_completeness`/`_is_placeholder_number`/`_has_non_placeholder_value`/`_compute_derived_metrics`/`_update_missing_items`/`_append_gap_monitor`/`_filter_tasks`/`_gap_monitor`——C2 留主脚本。其中被执行车道调用的(`_update_missing_items`/`_append_task_log`/`_dump_json` 等)在 C3 一并处理;纯 main 装配用的(`_load_json`/`_check_task_completeness`/`_warn_*`)可留到主脚本入口瘦身(终态)。

4. **`main` 入口瘦身到 ≤30 行 → C 批次终态**(C3 之后),非 C3 单独目标。

## 延后项（非 C3 硬性,登记防遗忘）

- **`_safe_number` ↔ `utils/coercion.py` 语义合一**:C2 仅把 `_safe_number` 从主脚本搬到 `engines/stage2/common.py`(纯位置),**未**并入 `utils/coercion`。语义合一是带行为含义的改动,需 characterization 证明等价,排期独立(C3 顺带或更后均可,不绑定 C3)。
- **extraction_apply 跨脚本 fund_flow import → C4 清理**:C2 的 `extraction_apply.py` 复制了 `from (scripts.)stage2_5_injector import _default_fund_flow_metric_basis/...` 跨脚本 import,带 `# C4-cleanup` 注释。**C4(Stage2.5 拆分 fund_flow)** 把这 4 个 helper 搬到 src 模块后,回收 extraction_apply 的跨脚本 import 改指向 src。

## C3 plan 生成时的前置约束（開工时照办）

- 从 **C2 合入后的 main HEAD** 现生成,按函数名 + 逐字 body,不靠绝对行号。
- **先加阶段级 characterization test**(任务生命周期五段),再切;复用 C-0.5 replay harness 作 canonical 端到端网,byte-stable。
- **datetime tie-in**:`_execute_tasks`/`_try_structured_provider` 用 `datetime.now()`/`time.perf_counter()`;切分后若新执行模块读 datetime,扩 replay harness 的 `_freeze_stage2_datetime` 冻结循环(C1-followup docstring 已留扩展点)。
- 冻结区:执行车道里仍会调 forex 零值防占位 / fund_flow gate / official allowlist(这些逻辑在 C2 模块/外部,C3 只搬调用方),body 逐字、call-site 零改。
- 依赖方向:新执行模块 → C2 模块(extraction_apply/diagnostics/validation/structured_runner/query_planner/common)+ C1 模块 + 外部,单向无环;不得反向 import 主脚本残留。

## 关联

- C2 spec:`docs/superpowers/specs/2026-06-15-batch-c2-stage2-split-design.md`(§2 Out of scope 列了 `_execute_tasks`/`_try_structured_provider`→C3)。
- C2 plan:`docs/superpowers/plans/2026-06-15-batch-c2-stage2-split.md`(Task 5 修正说明 + "不搬"清单)。
- TODOS:`optimization/20260610_refactor_plan/TODOS.md`(C3 行;C2 合入时由 Codex 勾选 C2 完成、焦点转 C3,届时把本备忘要点并入 C3 行)。
