# 2026-06-10 Refactor Plan

本目录收纳 2026-06-10 重构方案(第二轮),承接 2026-04-27 重构(PR1 utils 抽取、PR3 missing_items canonical 化)落地后被明确延期的事项,并扩展覆盖仓库清理、数据存储契约与 Stage2.5 兜底产品化。

## Files

- `REFACTOR_PLAN.md`: 主方案 — 现状盘点 + 五个批次(A 清理 / B 命名收敛 / C 巨石拆分 / D run 目录契约 / E 兜底产品化)的详细设计。
- `TEST_PLAN.md`: 各批次回归策略与验收命令。
- `TODOS.md`: 进度跟踪(每个 PR 合入时更新;**了解重构进度看这里**)。

## Execution Model (v2, 2026-06-11)

双 agent 走 superpowers 规则集:**Claude Code 负责 brainstorming(spec)与 writing-plans(per-PR 执行计划),Codex 负责 executing-plans 执行**,Claude Code 两段式评审后合入。Spec 在 `docs/superpowers/specs/`,plan 在 `docs/superpowers/plans/`,plan 在对应 PR 开工时从当时 HEAD 现生成。详见 `REFACTOR_PLAN.md` §11。

批次序列:**0(功能有效性审计)→ A 清理 → B 命名收敛 → C-0.5 replay harness → C 巨石拆分 → D run 目录契约 → E 兜底产品化**(E1/D1 可 worktree 并行)。

## Current Direction

- 严格 **behavior-preserving** 优先:批次 A/B/C 不改任何业务行为,仅移动/删除/拆分;批次 D/E 才引入新行为,且各自独立开关。
- 批次 C(Stage2 7077 行 / Stage2.5 4355 行拆分)是 2026-04-27 评审 TODOS 中的 P2-L 延期项,其声明的前置条件(Pring golden tests、canonical key registry、Stage2.5 contract replay)**现已全部满足**,可以启动。
- 每个批次独立成 PR 序列,任何批次可单独中止而不阻塞其他批次(C 依赖 B 的入口命名定稿,D/E 依赖 C 的模块边界,详见主方案依赖图)。
- 沿用 2026-04-27 的测试策略:deterministic fixture replay 为主,live Stage1→Stage4 只作发布前 smoke;Tavily 每日一次的约束意味着 **live 验证只能挂在当日正常流水线上**,不允许为重构单独重跑 Stage2。

## Relationship To 2026-04-27 Plan

| 2026-04-27 延期项 | 本轮归属 |
|---|---|
| Split Stage2 And Stage2.5 Large Scripts (P2, L) | 批次 C(本轮核心) |
| PipelineStateContract / run_manifest.json (P2, L) | 批次 D(收缩为 run 目录契约 + 文件白名单 + 原子写,完整状态机仍延期) |
| Pre-commit Quality Gate (P2, S) | 批次 A 末尾顺带引入(仅 scoped no-format 校验模式) |
