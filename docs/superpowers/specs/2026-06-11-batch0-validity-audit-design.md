# 批次 0:功能有效性审计 — 设计文档

> Spec for the 2026-06 refactor, batch 0. Parent strategy: `optimization/20260610_refactor_plan/REFACTOR_PLAN.md` §3.
> Status: approved direction from 2026-06-11 brainstorming session (Claude Code plans / Codex executes, superpowers conventions).

## 目的

在批次 A(仓库清理)删除任何代码之前,把删除依据从"grep 无引用"升级为"运行时证明无用",并把 REFACTOR_PLAN §1.2 中"有效性存疑"的模块(`analyzers/`、`comparators/`、`mappers/`、`warnings/`、MCP 链路、双份 yahoo_finance 等)逐一定档。

## 产出

| 产物 | 路径 | 说明 |
|---|---|---|
| 审计工具 | `optimization/20260610_refactor_plan/audit/import_graph.py`、`merge_audit.py`、`test_audit_tools.py` | 一次性工具,不进 `scripts/`,自带 pytest |
| 静态可达性 | `optimization/20260610_refactor_plan/audit/import_reachability.json` | 以 `scripts/*.py`(排除 legacy)为入口的 import 可达集 |
| 运行时覆盖 | `optimization/20260610_refactor_plan/audit/coverage.json` | 离线回放 Stage2.5→3→4 的 coverage 数据 |
| 合并结论 | `optimization/20260610_refactor_plan/audit/used_unused.json` + `AUDIT_RESULTS.md` | 全模块四档分级 + §1.2 疑似清单逐项定档 + 对批次 A 处置表的修订建议 |

## 分级口径(四档)

| 档位 | 判定 | 含义 |
|---|---|---|
| `runtime_used` | 离线回放 coverage ≥ 20% | 每日报告路径实际执行 |
| `imported_only` | coverage > 0 且 < 20% | 仅被 import(顶层 def 执行),函数体未跑 |
| `reachable_not_run` | coverage 无记录,但静态可达 | 可能被 Stage1/Stage2/tools 等未回放路径使用,**不可直接删** |
| `unreachable` | 静态不可达 | 批次 A 删除候选 |

20% 阈值是启发式,写入报告并对边缘模块人工复核;`reachable_not_run` 档在报告中标注"由哪个入口可达",供人工判断该入口本身是否常用。

## 方法

1. **静态可达性**:`ast` 解析 `src/datasource/` + `scripts/` 全部 import(含相对导入解析、`from X import y` 的符号/子模块双候选,按已知模块集过滤),从非 legacy 入口 BFS。已知盲区:`importlib` 动态导入、字符串拼接导入——在报告"局限性"一节明示。
2. **运行时覆盖**:以 `data/runs/20260522/` 为夹具复制到一次性 scratch 目录 `data/runs/19990101/`,在 `coverage --parallel-mode` 下依次回放 Stage2.5 → Stage3 → Stage4 report generator,全部显式路径参数。**完全离线**:无网络调用、不触碰真实当日 run 目录、trend_history 用 `--trend-history-base-dir` 指向 scratch 副本。Stage1/Stage2 需网络,本批仅静态分析,运行时覆盖可在下一次正常每日流水线 opt-in 搭车(非本批范围)。
3. **合并分级**:coverage 文件路径 ↔ 模块名映射后与可达集合并,产出四档 JSON 与人读报告。

## 边界与错误处理

- Stage3 回放若被 policy gate 阻断(夹具年代久导致 stale 判定漂移):回退方案是直接用 `20260522/market_data_complete.json` 原件作为 Stage3 输入,跳过 Stage2.5 重产物——审计要的是覆盖面,不是产物正确性。
- `coverage` 包不在依赖里:装入 `.venv`(`pip install coverage`),不进 `requirements.txt`(一次性工具)。
- scratch 目录使用 `data/runs/19990101/`(永不与真实交易日冲突);运行结束删除;`.run.lock` 落在 scratch 内,随目录清理。
- 隔离验证:运行前打时间戳标记,结束后断言 `data/trend_history/` 与 `data/runs/2026*` 无新于标记的文件。

## 非目标

- 本批不删除任何代码(删除在批次 A,依据本批结论)。
- 不判定 `scripts/` 下工具脚本的"人工使用频率"(静态无法判定,报告中列为 entry 并标注 usage unknown)。
- 不建长期 coverage 基础设施(那是批次 C-0.5 replay harness 的事,口径不同)。

## 成功标准

1. `used_unused.json` 覆盖 `src/datasource/` 全部模块,无遗漏档。
2. REFACTOR_PLAN §1.2 每个疑似模块在 `AUDIT_RESULTS.md` 有档位 + 证据(coverage% 或可达路径)。
3. 审计运行不改变任何真实数据(隔离断言通过)。
4. 批次 A 处置表据结论修订完成(由 Claude Code 在评审阶段执行)。
