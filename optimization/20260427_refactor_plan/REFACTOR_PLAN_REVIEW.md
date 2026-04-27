# 重构计划与工程评审

| 字段 | 值 |
|---|---|
| 生成日期 | 2026-04-27 |
| 生成方式 | `/office-hours`（Phase 1 初步分析） + `/plan-eng-review`（Phase 2 工程评审与修订） |
| 评审对象 | datasource 项目（统一金融数据集成框架）的可重构方面 |
| 当前分支 | main |
| 状态 | REVIEWED — 已按 2026-04-27 二次工程评审修订，执行前仍需与 4/9 方案对账 |

> **重要前置事项**：本计划尚未与项目内已有的两份相关文档对账：
> 1. `optimization/20260409_plan_a_refactor/ANALYSIS.md`（4/9 已开工的 Plan A 重构包）
> 2. `docs/报告生成流程重构方案.md`（标题直接命中"重构方案"）
>
> 在执行 PR1 之前，必须先打开这两份并与本计划对账，避免重复劳动或方向冲突。

---

## 目录

- [一、Phase 1：初步重构分析（`/office-hours`）](#一phase-1初步重构分析office-hours)
- [二、Phase 2：工程评审（`/plan-eng-review`）](#二phase-2工程评审plan-eng-review)
- [三、最终执行计划（PR1–PR6）](#三最终执行计划pr1pr6)
- [四、相关文件清单（按 PR 分组）](#四相关文件清单按-pr-分组)
- [五、已有规划文档清单（必先对账）](#五已有规划文档清单必先对账)
- [六、风险登记 / Failure Modes](#六风险登记--failure-modes)
- [七、TODOS](#七todos)

---

## 一、Phase 1：初步重构分析（`/office-hours`）

### 总体扫描结果

| 维度 | 数据 |
|---|---|
| `scripts/stage*.py` 总行数 | 10 297 |
| `src/datasource/` 总行数 | 22 531 |
| 单文件 TOP1 / TOP2 / TOP3 | `pring_analyzer.py` 2174 行 / `tushare_adapter.py` 1506 行 / `simple_report.py` 1137 行 |
| 巨型脚本 | `stage2_unified_enhancer.py` 3713 行 / 68 函数；`stage2_5_injector.py` 3197 行 / 80 函数 |
| 测试文件数 | 23 |
| legacy/archive 待清理脚本 | 14 |

### 初版条目（按优先级，**未经评审**）

#### A. 高优先级 — 真正在咬人

- **A1**：拆分 `scripts/stage2_unified_enhancer.py` (3713 行) 与 `scripts/stage2_5_injector.py` (3197 行) 两个巨型脚本，按职责切到 `src/datasource/stage2/` 与 `src/datasource/stage25/`
- **A2**：跨文件重复工具函数下沉（`_load_json` × 5、`_to_float` × 2、`_parse_amount` × 2、`_contains_ytd_marker` × 2、`_is_placeholder_*` × 2 但**语义不同**）
- **A3**：拆分 `src/datasource/calculators/pring_analyzer.py` (2174 行) 上帝类，把 13 个 `_score_*` 抽为纯函数

#### B. 中优先级 — 设计债务

- **B1**：`missing_items` 双层结构合并为单一来源（CLAUDE.md "Operational Pitfalls" 已经把它写成手册，说明咬过人）
- **B2**：`monetary_policy` 键名 alias（`reverse_repo_7d` → `reverse_repo` 等）统一下沉；Phase 1 曾建议 Pydantic `Field(alias=...)`，Phase 2 已改为 canonical key registry
- **B3**：拆分 `src/datasource/adapters/tushare_adapter.py` (1506 行 / 45 函数)

#### C. 低优先级 — 卫生清理

- **C1**：legacy/archive 目录策略明确化（git status 显示 R rename 还在 staged）
- **C2**：`scripts/utility/`、`scripts/temp/`、`scripts/archive_unused/` 三个目录边界统一

#### D. 长期 — 让重构变安全

- **D1**：补 unit test（23 个测试 vs ~33 000 行核心代码）
- **D2**：`pre-commit` 把 black/flake8/mypy 强制化

### Phase 1 推荐执行顺序（**未经评审**）

A2 → D1 局部 → A1（一次拆一个职责）→ A3 → B1 → 其余。

---

## 二、Phase 2：工程评审（`/plan-eng-review`）

### Step 0 — Scope Challenge

#### 关键修订（推翻 Phase 1 几个判断）

1. **Beck 检验失败**：A1 / A3 是纯结构调整，没有附带要解锁的功能。`make the change easy, then make the easy change` 的前提是有"easy change" 在等。当前流水线**能跑、有产出、有 CLAUDE.md 指南**，纯重构不是道德义务。
2. **复杂度阈值触发**：A1 + A3 + B1 全做 → 触动 ≥ 8 个文件、新增 ≥ 4 个模块包。**这是 over-scope**。
3. **Layer 1 检查通过**：没有建议引入 Prefect/Dagster 是对的，"三枚 innovation token" 不该花在编排器上，保持 boring。
4. **Phase 1 被忽略的更高 ROI 项**：
   - `src/datasource/utils/run_paths.py` 的实际使用一致性
   - Pydantic contract 已存在但被 `_apply_macro_entry` 等直 dict 操作旁路
   - CLI 参数在 5 个 stage 各自定义，重复

#### 条目修订表

| 原条目 | 修订决定 |
|---|---|
| A1 拆 stage2 / stage2.5 | **降级到 P3 / defer**。除非有新功能要嵌入 |
| A2 提取重复工具 | **保留 P1**，但**不要直接合并** placeholder 函数 |
| A3 拆 pring_analyzer | **降级到 P2**，且**必须 golden-file 回归测试先行** |
| B1 missing_items 单一来源 | **保留 P1**，需兼容旧数据重放 |
| B2 Pydantic alias | **改写为 P1 canonical key registry**。`monetary_policy` 是 dict，`Field(alias=...)` 不会规范化 dict key |
| B3 拆 tushare_adapter | **删除**。1506 行可读，45 函数对应 ~10 endpoint，是 essential complexity |
| C1 / C2 archive 清理 | 保留 P3，纯卫生 |
| D1 测试 | **重新定位**：不是独立 workstream，是 A2 / A3 / B1 的**前置条件** |
| D2 pre-commit | **拆出 PR1**，作为后续独立质量门禁 |

#### 新增条目

- **N1**：审计 `run_paths.py` 是否被所有 stage 一致使用
- **N2**：新增 canonical key registry + alias normalizer，统一 Stage2 / Stage2.5 / search_profiles / Stage3 的货币政策 key 口径
- **N3**：补 `run_paths.py` 契约测试与文档一致性；`cli_common` 不作为本轮核心目标

### 1. Architecture Review

#### 1.1 [P1] (confidence: 9/10) monetary_policy alias 不能靠 Pydantic `Field(alias=...)` 解决

`src/datasource/models/market_data_contract.py` 中 `monetary_policy` 是 `Dict[str, MonetaryPolicyData]`。Pydantic 字段 alias 只作用于 model field，不会把 dict key `reverse_repo_7d` 自动改成 `reverse_repo`。

```
 Stage2/search key       Stage2.5/manual key       Stage3 read key
 reverse_repo_7d ─┐      mlf_rate ─────────┐
 rrr ─────────────┼────▶ canonical registry ├────▶ reverse_repo / mlf / reserve_ratio / tsf
 tsf_growth ──────┘                         │
 canonical key ─────────────────────────────┘
```

**生产失败场景**：Stage2 生成 `mlf_rate`，Stage2.5 写成 `mlf`，search_profiles 又把 `mlf` 指向 `mlf_rate`，最终同一指标在不同 stage 里出现双 key 或漏清理。

**修订建议**：PR3 新增 canonical key registry 与 alias normalizer。Pydantic contract 仍可用于值校验，但不要把 `Field(alias=...)` 当作 dict key normalizer。

#### 1.2 [P1] (confidence: 9/10) `missing_items` 双层结构是数据契约违反

CLAUDE.md "Operational Pitfalls" 三段连续讲这个坑——文档在补救设计漏洞。

```
              metadata.missing_items (dict, by category)
                    │
                    ▼
              ┌──────────────┐
              │ 写入入口很多 │ ← Stage1, Stage2, Stage2.5
              └──────────────┘
                    │
   顶层 missing_items (list) ◀── ❌ 没有单向派生关系
                    │              ❌ Stage3 policy gate 读这层
                    │              ❌ inject 脚本只更新 metadata 层
                    ▼
            block_stage3=True 神秘阻断
```

**修订建议**：渐进收敛。`metadata.missing_items` 作为 canonical source，顶层 `missing_items` 与 `gap_monitor` 保持兼容派生。不要在 PR3 直接删除 `_remove_top_missing` / `_remove_top_missing_on_skip`，先把它们收口到一个同步/派生 helper 并保留旧 run replay 测试。

**风险**：旧 `data/runs/*/market_data_complete.json` 可能被 Stage3 重放。需要 ~30 行的"宽松解析、严格写出"兼容层。

#### 1.3 [P2] (confidence: 7/10) Stage 间数据边界不严

脚本之间通过 JSON 文件传递但没有契约校验，Stage3 读 `pring_result.json` 假设 Stage2.5 写的字段一定存在。**建议**：每个 stage 入口加 5 行 Pydantic 校验。

### 2. Code Quality Review

#### 2.1 [P1] (confidence: 10/10) 两个 placeholder 函数**不能直接合并**

```python
# scripts/stage2_unified_enhancer.py:402
def _is_placeholder_number(val):
    ...
    return abs(num) < 1e-9            # 仅判定 0 / None / 空

# scripts/stage2_5_injector.py:302
def _is_placeholder_numeric(value):
    ...
    if abs(numeric) < 1e-9: return True
    return abs(numeric - 7.13) < 1e-3  # ★ 把 USDCNY 历史 mock 值 7.13 也当占位
```

**这是有业务含义的差异**。Stage2.5 知道 7.13 是上游遗留 mock，需要被替换。Stage2 不在乎。

**正确的统一方式**（Phase 1 的"直接合并"会引入 silent bug）：

```python
# src/datasource/utils/coercion.py
LEGACY_MOCK_VALUES = (7.13,)  # USDCNY 历史 mock；之后新增的写在这

def is_zero_or_missing(val) -> bool:
    """Stage2 用：仅判 None / 空 / 0"""

def is_placeholder_or_legacy_mock(val) -> bool:
    """Stage2.5 用：is_zero_or_missing OR 命中 LEGACY_MOCK_VALUES"""
```

#### 2.2 [P1] (confidence: 9/10) 重复工具函数

| 函数 | 出现位置 |
|---|---|
| `_load_json` | `stage2_unified`、`stage2_low_score_audit`、`recap_consistency_check`、`backfill_fund_flow_series`、`legacy/stage2_mcp_enhancer`（5 处） |
| `_to_float` | `engines/deepseek_reasoner`、`generators/simple_report`（2 处） |
| `_parse_amount` | `scripts/utility/fund_flow_daily_sync`、`models/market_data_contract`（2 处） |
| `_contains_ytd_marker` | `stage2_unified:992`、`stage2_5_injector:1475`（一字不差） |

**修订建议**：建 `utils/coercion.py`、`utils/json_io.py`、`utils/text_markers.py`，但按语义分层抽取。严格 JSON 读取、容错 JSON 读取、普通 float、资金流金额、普通 placeholder、legacy mock placeholder 必须分别有契约测试。

#### 2.3 [P2] (confidence: 8/10) `pring_analyzer.py` 是上帝类，但拆分前必须有金标准

13 个 `_score_*` 方法 (`pring_analyzer.py:651-826`) 是天然拆分线。但这是**报告输出的核心评分引擎**，行为不能漂移。

执行顺序锁定：

1. 从 `data/runs/20260424/market_data_complete.json` 与 `pring_result.json` 复制最小 fixture 到 `tests/fixtures/pring_golden/`
2. 加 `tests/test_pring_scoring_golden.py`，每个 `_score_*` 覆盖阈值两侧
3. 加 full-result golden replay，固定输入输出零漂移后再拆分

**不做 1+2 就拆分是赌博**。

#### 2.4 [P3] (confidence: 6/10) CLI 参数 5 处重复

stage1 / 2 / 2.5 / 3 / 4 都有 `--date / --output / --log-output / --market-data`。这是真重复，但当前优先级低于 alias、missing_items、Pring golden 和 run_paths 契约验收。本轮不抽 `scripts/_cli_common.py`，后续如继续收敛 CLI 再单独做小 PR。

### 3. Test Review

#### 3.1 测试框架

- **运行时**：Python (pyproject.toml + requirements.txt)
- **框架**：pytest（CLAUDE.md `pytest -q`）
- **现有测试**：23 个 `test_*.py`

#### 3.2 重构动作的测试需求

```
重构动作                                         测试需求
[+] A2 utils/coercion.py
  ├── is_zero_or_missing(val)                  ★★★ None/""/N/A/0/小负数/正/字符串数字/带 % 字符串
  ├── is_placeholder_or_legacy_mock(val)       ★★★ 上述 + 7.13 + 7.130 + 7.13001 + 7.14（边界）
  └── LEGACY_MOCK_VALUES 常量                  ★

[+] A2 utils/json_io.py
  ├── load_json_safe(path)                     ★★  正常/不存在/空文件/损坏 JSON
  └── dump_json(payload, path, backup=True)    ★★  备份生成 / 原子性（.tmp + rename）

[+] B1 missing_items 单一来源
  ├── derive_top_missing_items(metadata)       ★★★ 空/单 category/多 category/重复 key
  ├── 兼容旧格式：宽松读，严格写                ★★★ 集成：v0 JSON → v1 结构
  └── Stage3 policy gate 行为不变              ★★★ 黄金回归：现有 test_policy_rules.py

[+] A3 pring_analyzer 拆分（如果做）
  ├── 13 个 _score_* 方法                      ★★★ 黄金 fixture：当前 prod 输出留存为基线
  ├── _evaluate_leading_indicator 整链路       ★★★ 集成：3 套真实 market_data → 同一 pring_result.json
  └── pring stage 推断                         ★★

CRITICAL REGRESSION（必加，无 AskUserQuestion 跳过）：
[!] 7.13 占位检测的合并语义                    ★★★ 集成：USDCNY=7.13 + 旧 _manual.json → Stage2.5 应替换；
                                                            USDCNY=7.13 + 新 source_url → 应被覆盖
[!] missing_items 双层 → canonical + compat 后旧数据兼容
                                                    ★★★ 集成：tests/fixtures 旧 JSON 重放，Stage3/4 gate 行为不变

COVERAGE: 重构后必须新增 ~12 个测试
QUALITY:  ★★★ 占主导（基础设施层不能省）
```

#### 3.3 关键 gap：pring_analyzer 没有 score-level 单测

当前只有端到端 `test_enhanced_pring.py`。单个 `_score_ppi_indicator` 喂特定值的断言**没有**——这是 A3 必须先补的洞。

### 4. Performance Review

日批 ETL，runtime 被 Tavily（每天 1 次硬上限）和 TuShare（API rate limit）主导。

- **N+1 / DB**：N/A，无数据库
- **Memory**：JSON 最大 ~5MB，零压力
- **Cache**：已有 `data/cache/tavily_cache.sqlite` 跨日复用 ✓
- **慢路径**：DeepSeek 抽取已有 `--deepseek-timeout 12` 硬切断
- **测试 IO 副作用**：Stage2.5 fixture replay 不能写真实 `data/trend_history/min`

**修订建议**：增加 `trend_history_base_dir` 或 `disable_trend_history_write`，测试使用 `tmp_path` 隔离趋势历史写入。性能风险不是 CPU，而是非确定性 IO 副作用。

### NOT in scope

| 项 | 原因 |
|---|---|
| ~~B3 拆 tushare_adapter.py~~ | 1506 行可读、45 endpoint 函数有清晰对应。拆分只是把端点散到 5 个文件加 import 复杂度。Brooks: 这是 essential complexity |
| ~~引入 Prefect/Dagster~~ | "三枚 innovation token" 中没有一枚该花在编排器上 |
| ~~mypy 严格化全仓~~ | CLAUDE.md 已声明 `mypy src/datasource/`，scripts/ 不强制，当前合理 |
| ~~Async/await 化 Stage1 数据采集~~ | TuShare 限流主导，并发收益微乎其微 |
| ~~引入 ORM 包装 trend_history JSON~~ | 文件 < 1MB，文件即数据库够用 |

### What already exists（不要重建）

| 已有 | 状态 | 角色 |
|---|---|---|
| `src/datasource/utils/run_paths.py` | 存在 | **N1 审计**：确认所有 stage 都通过它构造路径 |
| `src/datasource/models/market_data_contract.py` | 存在但不能解决 dict key alias | 用于值校验；key 规范化交给 canonical registry |
| `src/datasource/utils/quality_metrics.py` | 存在 | Stage2 已用 |
| `src/datasource/utils/policy_rules.py` | 存在 | Stage3 阻断逻辑实现位置，B1 改顶层 missing_items 时改这里 |
| `src/datasource/utils/observability.py` | 存在 | Stage2 用，但未必所有 stage 都接入 |
| `src/datasource/utils/retry.py` / `rate_limiter.py` | 存在 | 通用基础设施已有 |
| `tests/integration/test_enhanced_pring.py` | 存在但随机/打印较多 | 不能直接作为 golden baseline；只作历史参考 |

---

## 三、最终执行计划（PR1–PR6）

| 批次 | 内容 | 改动文件数 | 风险 | 努力 (CC) |
|---|---|---|---|---|
| **PR1** | 语义分层 utils：coercion / json_io / text_markers + 配套单测 | ~5 | 低 | ~1 h |
| **PR2** | pring_analyzer 黄金 fixture + score-level 单测（PR4 硬前置） | ~3 | 低 | ~1.5 h |
| **PR3** | canonical key registry + missing_items 兼容迁移 + Stage2.5 trend_history 测试隔离 | ~6 | 中（数据兼容） | ~3 h |
| **PR4** | A3 pring_analyzer 拆分（依赖 PR2） | ~5 | 中 | ~2 h |
| **PR5** | run_paths 契约验收 + docs/AGENTS/CLAUDE 命令一致性 | ~3 | 低 | ~45 min |
| **PR6** | 卫生：C1 / C2 归档 | ~20 (rename) | 极低 | ~30 min |
| **follow-up** | pre-commit 质量门禁 | ~1 | 低 | ~20 min |
| **defer** | A1 stage2 / 2.5 拆分；PipelineStateContract / run_manifest | — | — | 等测试护栏稳定后再做 |

**验证策略**：每个 PR 跑 deterministic fixture replay + targeted unit tests。live Stage1 -> Stage4 只作为发布前 smoke，不作为每 PR byte-level diff gate，避免实时 API/Tavily 非确定性与同日消耗约束。

### Worktree Parallelization

| Step | Modules touched | Depends on |
|---|---|---|
| PR1 utils | `src/datasource/utils/`, selected scripts | — |
| PR2 Pring golden | `tests/`, `tests/fixtures/` | — |
| PR3 key/missing compat | `src/datasource/utils/`, `scripts/stage2_5_injector.py`, Stage3/4 gates | PR1 |
| PR4 Pring split | `src/datasource/calculators/pring*` | PR2 |
| PR5 run_paths docs/tests | `src/datasource/utils/run_paths.py`, docs, tests | — |

Parallel lanes:

- Lane A: PR1 -> PR3（shared Stage2.5 behavior）
- Lane B: PR2 -> PR4（Pring scoring and module split）
- Lane C: PR5（independent path contract/docs）

Launch PR1, PR2, and PR5 in parallel worktrees if needed. Do not parallelize PR1 and PR3.

---

## 四、相关文件清单（按 PR 分组）

### PR1 — 语义分层 utils 抽取

**新建**：

- `src/datasource/utils/coercion.py`
- `src/datasource/utils/json_io.py`
- `src/datasource/utils/text_markers.py`
- `tests/test_utils_coercion.py`
- `tests/test_utils_json_io.py`

**修改**（删重复定义，改 import）：

- `scripts/stage2_unified_enhancer.py` — `_load_json` (L81)、`_dump_json` (L472)、`_is_placeholder_number` (L402)、`_contains_ytd_marker` (L992)
- `scripts/stage2_5_injector.py` — `_is_placeholder_numeric` (L302)、`_contains_ytd_marker` (L1475)
- `scripts/stage2_low_score_audit.py` — `_load_json` (L36)
- `scripts/recap_consistency_check.py` — `_load_json` (L33)
- `scripts/backfill_fund_flow_series.py` — `_load_json` (L18)
- `src/datasource/engines/deepseek_reasoner.py` — `_to_float` (L241)
- `src/datasource/generators/simple_report.py` — `_to_float` (L54)
- `scripts/utility/fund_flow_daily_sync.py` — `_parse_amount` (L32)，只在确认与 `FundFlowData._parse_amount` 语义一致后委托
- `src/datasource/models/market_data_contract.py` — `_parse_amount` (L86) 保留入口，内部可委托金额解析 helper

**不做**：

- 不新增 `.pre-commit-config.yaml`。
- 不把 strict JSON load 与 optional JSON load 合并。
- 不把普通 `_to_float` 与资金流金额解析合并。

### PR2 — pring 黄金 fixture（A3 前置）

**新建**：

- `tests/test_pring_scoring_golden.py`
- `tests/fixtures/pring_golden/`

**只读参考**：

- `src/datasource/calculators/pring_analyzer.py:651-826`
- `tests/integration/test_enhanced_pring.py`
- `data/runs/*/market_data_complete.json`
- `data/runs/*/pring_result.json`

### PR3 — canonical key registry + missing_items 兼容迁移

**修改**：

- 新建 `src/datasource/utils/key_aliases.py` 或等价位置，定义 monetary canonical key registry 与 alias normalizer
- `src/datasource/config/search_profiles.py` — 使用同一 registry，消除 `mlf -> mlf_rate` 与 Stage2.5 `mlf_rate -> mlf` 的冲突
- `scripts/stage2_5_injector.py` — 用 registry 规范化 manual / Stage2 输入；保留顶层 missing_items 兼容清理 helper，但收口到统一同步函数
- `scripts/stage2_unified_enhancer.py` — 写入/读取 missing_items 时以 metadata 为 canonical，顶层为兼容派生
- `scripts/stage3_pring_analyzer.py` 与 `stage4_report_generator.py` — 保持兼容读取旧顶层/gap_monitor，新增 canonical fixture replay
- `scripts/stage2_5_injector.py` — 增加 `trend_history_base_dir` 或 `disable_trend_history_write`，测试不得写真实 `data/trend_history/min`

**新建测试**：

- `tests/test_monetary_key_registry.py`
- `tests/test_missing_items_compat.py`
- `tests/test_stage25_contract_replay.py`
- Stage3/Stage4 fixture replay：旧键、新键、混合 key、旧顶层 missing_items、metadata missing_items、gap_monitor 均覆盖

**关键文档同步更新**：

- `CLAUDE.md` / `AGENTS.md` 关于 alias、missing_items、gap_monitor 的说明

### PR4 — pring_analyzer 拆分（依赖 PR2）

**新建**：

- `src/datasource/calculators/pring/__init__.py`
- `src/datasource/calculators/pring/scoring.py`（13 个 `_score_*` 改纯函数）
- `src/datasource/calculators/pring/leading_indicator.py`
- `src/datasource/calculators/pring/summaries.py`（`_build_*_summary_text`）
- `src/datasource/calculators/pring/stage_allocations.py`（`_build_stage_allocations`、`_shift_stage`）

**修改**：

- `src/datasource/calculators/pring_analyzer.py` — 缩减为 `PringAnalyzer` 主类 + 调用拆分模块
- `src/datasource/__init__.py`、`scripts/stage3_pring_analyzer.py` — import 路径

### PR5 — run_paths 契约验收 + 文档一致性

**修改/验证**：

- `src/datasource/utils/run_paths.py`
- `scripts/stage{1,2_unified,2_5,3,4}_*.py` —— 检查路径拼接
- `AGENTS.md` / `CLAUDE.md` / `README.md` 中 Stage1 -> 4 默认路径和显式参数示例

**新建**：

- `tests/test_run_paths_consistency.py`

**不做**：

- 不在本 PR 抽 `scripts/_cli_common.py`。CLI common 可以作为后续小 PR，但不是当前路径契约验收的必要条件。

### PR6 — 卫生归档

- `scripts/legacy/`（10+ 文件，git status 已是 R）
- `scripts/archive/`（5 文件）
- `scripts/temp/`（已空）
- 加 `scripts/legacy/README.md`、`scripts/archive/README.md` 一行说明

---

## 五、已有规划文档清单（必先对账）

### 最高优先级 — 疑似已开工的相关重构

- **`optimization/20260409_plan_a_refactor/ANALYSIS.md`** ← **执行 PR1 前必读**
- `optimization/20260409_plan_a_refactor/CODEX_EXECUTE.md`
- `optimization/20260409_plan_a_refactor/ITERATION_LOG.md`
- `docs/报告生成流程重构方案.md` ← 名字直接命中"重构方案"
- `docs/2026-04-08_市场背景扫描工具优化改造计划.md`

### 近期活跃的优化项目（参考其工作流）

- `optimization/20260409_output_layout_reorg/{README, CHANGELOG, TODOS}.md`
- `optimization/20260107_daily_report_optimization/{需求, todos, 复盘模板}.md`
- `optimization/20251219_exa_fallback/`
- `optimization/20251211_search_profiles/`
- `optimization/20251124_tavily_efficiency/`

### 已归档（仅作历史背景）

- `optimization/archive/stage2_*_plan.md`、`stage3_*.md`
- `optimization/archive/V3.3*`、`V4.1*`

### 项目根 / docs 顶层

- `CLAUDE.md`（"Operational Pitfalls" 段是 PR3 必读）
- `AGENTS.md`
- `SCRIPTS.md`
- `docs/系统技术文档.md`（Pring 六阶段原理参考）

---

## 六、风险登记 / Failure Modes

| Failure 场景 | 当前测试 | 当前错误处理 | 用户可见性 | 评级 |
|---|---|---|---|---|
| `_is_placeholder_*` 合并语义改错，7.13 不再被识别为占位 | 待补 `test_utils_coercion.py` | 当前无统一契约 | silent：Stage2.5 不再替换老 USDCNY mock | **CRITICAL GAP** |
| `missing_items` canonical + compat 迁移后 Stage3/4 gate 规则未跟进 | 待补 fixture replay | 可能被旧顶层或 gap_monitor 阻断 | 部分可见：Stage3/4 报错，但定位成本高 | **HIGH** |
| `_score_ppi_indicator` 等拆分后阈值漂移 | 待补 score-level golden | 当前无 score-level guard | silent：报告口径变了，没人发现 | **CRITICAL GAP** |
| canonical key registry 漏掉旧 `_manual.json` 字段名 | 待补 Stage2.5 manual replay | 可能重复 key 或漏清理 | 部分可见：Stage3 阻断或报告 N/A | **HIGH** |
| Stage2.5 fixture replay 写真实 trend_history | 待补 test-safe base_dir/disable write | 当前会写默认目录 | silent：测试污染真实趋势历史 | **HIGH** |
| `run_paths.py` 默认路径/显式路径不一致 | 已有部分 Stage3/4 测试，待补全 | FileNotFoundError 或错误文件被读 | 立刻爆错，属于好的失败模式 | LOW |

**两个 CRITICAL GAP 都直接对应"重构前必须补测试"**。这是不可让步的。

---

## 七、TODOS

本轮明确延期项已单独写入 `TODOS.md`：

- PipelineStateContract / `run_manifest.json` 状态机。
- pre-commit 质量门禁。
- Stage2 / Stage2.5 大文件拆分。

本计划与 `optimization/20260409_plan_a_refactor/ANALYSIS.md`、`docs/报告生成流程重构方案.md` 的对账仍是 PR1 前置动作。

---

## Completion Summary

- **Step 0 Scope Challenge**：大幅修订 — A1/B3 降级或删除，B2 从 Pydantic alias 改为 canonical key registry
- **Architecture Review**：3 个 issues，全部已决策
- **Code Quality Review**：2 个核心 issues，PR1 改为语义分层，pre-commit 拆出
- **Test Review**：fixture replay + Pring golden 作为硬前置，live run 降为发布前 smoke
- **Performance Review**：1 个测试 IO 副作用问题，要求 Stage2.5 trend_history 写入隔离
- **NOT in scope**：5 项
- **What already exists**：7 项已识别
- **TODOS**：3 项，已写入本目录 `TODOS.md`
- **Failure modes**：2 个 CRITICAL silent gap
- **Lake Score**：完整版 = 配套测试 + 数据兼容层。两条都纳入 P1 = 2/2

---

## 下一步

1. **打开 `optimization/20260409_plan_a_refactor/ANALYSIS.md` + `docs/报告生成流程重构方案.md`** — 与本计划对账
2. 如果方向重合，把本文档合并到 20260409 包；如果方向不同，本目录独立推进
3. 对账完成后，从 **PR1**（语义分层 utils/coercion + json_io + text_markers，不含 pre-commit）启动
4. 并行可开 **PR2**（Pring golden）与 **PR5**（run_paths 契约验收）

## 相关产物

- `README.md`: 本目录索引。
- `DECISIONS.md`: 本轮工程评审 D1-D12 决策记录。
- `TEST_PLAN.md`: fixture replay 与 Pring golden 测试计划。
- `TODOS.md`: 本轮明确延期的后续事项。

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | issues_open | mode: SELECTIVE_EXPANSION, 1 critical gap |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | clean | 9 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 1 | issues_open | score: 5/10 -> 8/10, TTHW: 15min -> 5min |

- **UNRESOLVED:** 3 unresolved decisions remain in older optional CEO/DX reviews.
- **VERDICT:** ENG CLEARED — ready to revise the execution plan and implement the refactor sequence above.
