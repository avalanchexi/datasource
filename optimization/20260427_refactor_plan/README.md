# 2026-04-27 Refactor Plan

本目录收纳 2026-04-27 重构方案及工程评审配套文档。

## Files

- `REFACTOR_PLAN_REVIEW.md`: 主方案与 gstack review report。
- `DECISIONS.md`: 本轮 `/plan-eng-review` 的 D1-D12 决策记录。
- `TEST_PLAN.md`: 可供后续 QA / fixture replay 使用的测试计划。
- `TODOS.md`: 本轮明确延期、但仍有持续价值的后续事项。

## Current Direction

本轮工程评审选择收缩原方案：

- PR3 不使用 Pydantic `Field(alias=...)` 解决 dict key alias，改为 canonical key registry + alias normalizer + compatibility replay。
- `missing_items` 渐进迁移，`metadata` 作为 canonical source，顶层 `missing_items` 与 `gap_monitor` 保持兼容派生。
- PR1 只做语义分层 utils 抽取，pre-commit 单独延期。
- Pring golden tests 是任何 Pring 拆分前的硬前置。
- 每 PR 使用 deterministic fixture replay，live Stage1 -> Stage4 只作为发布前 smoke。
