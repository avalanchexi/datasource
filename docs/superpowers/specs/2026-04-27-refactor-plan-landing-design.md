# 2026-04-27 Refactor Plan Landing Design

## 背景

本设计用于落地 `optimization/20260427_refactor_plan/` 下的重构方案。该目录中的 `README.md`、`DECISIONS.md`、`TEST_PLAN.md`、`TODOS.md` 和 `REFACTOR_PLAN_REVIEW.md` 是本轮权威输入。

当前 worktree 将被合并到主干，因此本轮落地按当前 worktree 作为集成基线处理。实现采用严格串行批次，不额外设计多 worktree 并行，不回滚已有用户改动，不做全仓格式化，不夹带无关重命名。

## 目标

将 2026-04-27 重构方案分批落地，并通过确定性测试护栏降低静默回归风险。

核心目标：

- 保持 Stage1 -> Stage4 主流程和数据来源优先级不变。
- 将重复且隐式的工具逻辑收口为可测试契约。
- 在 Pring 拆分前建立 golden 和 score boundary 测试。
- 建立 monetary key alias 与 `missing_items` 兼容迁移规则。
- 保证 fixture replay 不污染真实 `data/trend_history/min`。
- 用 `run_paths.py` 现有能力做路径契约验收，而不是重建路径系统。

## 非目标

以下内容不进入本轮实现：

- `PipelineStateContract` / `run_manifest.json` 状态机。
- Stage2 / Stage2.5 大文件模块化拆分。
- pre-commit 质量门禁。
- live Tavily/API 输出的每批次 byte-level diff 验收。
- 无关格式化、无关归档、无关行为改写。

## 落地顺序

### PR1: 语义分层 utils 抽取

范围：

- 新建或完善 `src/datasource/utils/coercion.py`。
- 新建或完善 `src/datasource/utils/json_io.py`。
- 新建或完善 `src/datasource/utils/text_markers.py`。
- 替换 Stage2、Stage2.5、诊断脚本和报告生成中行为完全一致的重复 helper。

边界：

- 只抽取语义相同的 helper，不做 blanket DRY。
- 普通占位符、fund-flow 数值解析、legacy `7.13` 占位符必须保持独立契约。
- 严格 JSON 加载和可选诊断 JSON 加载必须保持独立契约。
- 不加入 pre-commit，不做全仓格式化。

完成门禁：

- `tests/test_utils_coercion.py` 覆盖 `None`、空字符串、`N/A`、`0`、legacy `7.13` 等语义。
- `tests/test_utils_json_io.py` 覆盖严格读写和可选诊断读取。
- 受影响脚本的现有测试通过，或记录明确的非代码阻塞原因。

### PR2: Pring golden tests

范围：

- 新建 `tests/test_pring_scoring_golden.py`。
- 新建 `tests/fixtures/pring_golden/`。
- 基于稳定 fixture 覆盖 Pring score boundary 和 full-result golden replay。

边界：

- 不拆 `src/datasource/calculators/pring_analyzer.py`。
- 不调整评分阈值。
- 不改变报告摘要口径。

完成门禁：

- 每个关键 `_score_*` 函数的阈值两侧都有测试。
- full-result golden 能检测最终阶段、置信度、评分和报告侧摘要漂移。
- PR4 启动前 PR2 必须通过。

### PR3: Canonical key registry 与 missing_items 兼容迁移

范围：

- 新建 `src/datasource/utils/key_aliases.py` 或等价位置。
- 定义 monetary canonical key registry 和 alias normalizer。
- Stage2、Stage2.5、Stage3、Stage4 使用同一 normalizer 读取旧键、新键和混合键。
- `metadata.missing_items` 作为 canonical source。
- 顶层 `missing_items` 和 `gap_monitor` 保留为兼容读取或派生视图。
- Stage2.5 增加 `trend_history_base_dir` 或 `disable_trend_history_write`，使测试不会写真实趋势历史目录。

边界：

- 不使用 Pydantic `Field(alias=...)` 解决 `monetary_policy` dict key alias。
- 规范输出只保留 canonical key。
- 旧 `_manual.json` 仍必须可读。
- Stage3/Stage4 gate 不因迁移丢失旧顶层或 `gap_monitor` 阻断能力。

完成门禁：

- `tests/test_monetary_key_registry.py` 覆盖旧键、新键、混合键和冲突优先级。
- `tests/test_missing_items_compat.py` 覆盖 metadata canonical source、顶层兼容和 `gap_monitor` 兼容。
- `tests/test_stage25_contract_replay.py` 覆盖 Stage2.5 manual replay。
- fixture replay 不写 `data/trend_history/min`。

### PR4: Pring analyzer 拆分

范围：

- 新建 `src/datasource/calculators/pring/` 包。
- 将 scoring、leading indicator、summary、stage allocation 拆到独立模块。
- `PringAnalyzer` 保留编排职责。

边界：

- 必须在 PR2 golden 通过后启动。
- 拆分是纯迁移，不改阈值、不改最终阶段判断、不改报告摘要。
- import 路径更新只服务于拆分后的模块结构。

完成门禁：

- PR2 golden 全部通过。
- Stage3 相关现有测试通过。
- full-result golden 输出不漂移。

### PR5: run_paths 契约验收与文档一致性

范围：

- 验证 `src/datasource/utils/run_paths.py` 已有契约。
- 补 `tests/test_run_paths_consistency.py`。
- 对齐 `AGENTS.md`、`CLAUDE.md`、`README.md`、`SCRIPTS.md` 中 Stage1 -> Stage4 默认路径和显式参数示例。

边界：

- 不重建路径抽象。
- 不新增 `scripts/_cli_common.py` 作为本批必要工作。
- 文档以 `AGENTS.md` 为准，其他文档只做一致性同步。

完成门禁：

- 默认路径和显式路径覆盖 Stage1、Stage2、Stage2.5、Stage3、Stage4。
- 文档命令与实际 CLI 参数一致。

### PR6: 卫生归档

范围：

- 完成 legacy、archive、temp 相关卫生归档。
- 为归档目录补简短 README。

边界：

- 只做归档说明和文件位置整理。
- 不夹带行为改动。
- 不删除仍被当前命令或测试引用的脚本。

完成门禁：

- 被归档脚本无当前主流程引用。
- 文档能说明 legacy/archive 的用途和风险。

## 数据流

本轮不改变主数据流：

```text
market_data_stage2.json + websearch_results_manual.json
  -> Stage2.5 market_data_complete.json
  -> Stage3 pring_result.json
  -> Stage4 markdown report
```

本轮改变的是数据流内部的契约边界：

- Stage2 和 Stage2.5 共享可测试 helper，而不是复制隐式逻辑。
- Monetary key 通过同一 registry 规范化。
- `missing_items` 写入以 `metadata` 为准，旧顶层和 `gap_monitor` 继续兼容。
- Stage2.5 测试写入 trend history 时必须使用临时目录或禁写开关。

## 错误处理

原则是兼容读取、规范写入、显式阻断。

- Pipeline 必需 JSON 使用严格读取，文件缺失或非法 JSON 直接失败。
- 诊断类 JSON 使用可选读取，缺失时返回 `None`，但不得吞掉主流程错误。
- 数值占位符保持细分语义，避免 `0`、`None`、`N/A` 和 legacy `7.13` 被误合并。
- 旧 alias、新 canonical key 和混合 key 均可读取；规范输出只保留 canonical key。
- key 冲突按 registry 中固定优先级处理，并由测试固定。
- Stage3/Stage4 同时兼容旧顶层 `missing_items`、`metadata.missing_items` 和 `gap_monitor`。

## 测试策略

测试分三层：

1. 单元测试：coercion、json_io、text_markers、key registry、Pring score boundary。
2. Fixture replay：Stage2.5 -> Stage3 -> Stage4，覆盖旧键、新键、混合键和 missing item 兼容来源。
3. Golden 测试：Pring full-result replay，保护评分、阶段、置信度和摘要不漂移。

每批次使用 deterministic fixture replay 和 targeted unit tests。live Stage1 -> Stage4 只作为全部落地后的发布前 smoke，不作为每批 byte-level diff gate。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 占位符 helper 合并导致 legacy `7.13` 语义丢失 | PR1 增加独立 coercion 测试，禁止把不同语义合并成单个 helper |
| Pring 拆分导致阈值漂移 | PR2 先补 score boundary 和 full-result golden，PR4 后必须保持输出不变 |
| key alias 漏掉旧 manual 字段 | PR3 registry 测试覆盖旧键、新键和混合键 |
| missing_items 迁移导致 Stage3/4 gate 失效 | PR3 fixture replay 覆盖 metadata、顶层和 gap_monitor 三类来源 |
| Stage2.5 测试污染真实 trend history | PR3 增加临时目录或禁写开关，测试强制使用隔离路径 |
| 当前 dirty worktree 混入无关改动 | 每批开始前检查相关文件状态，每批只触碰设计范围内文件 |

## 完成定义

本轮落地完成必须满足：

- PR1 到 PR6 按顺序完成，或每个未完成批次有明确阻塞说明。
- 两个 critical silent gap 已由测试覆盖：占位符语义和 Pring 阈值漂移。
- PR3 已建立 key registry、`missing_items` 兼容迁移和 trend_history 测试隔离。
- PR4 拆分后 Pring golden 不漂移。
- PR5 文档命令与实际路径契约一致。
- PR6 不改变行为，只完成卫生归档。
- 全部文档同步以 `AGENTS.md` 为准。
