# 批次 C0:forex 证据判定族合一 — 设计文档

> Spec for the 2026-06 refactor, batch C0(REFACTOR_PLAN §6.1)。批次 C 巨石拆分的**去重前置**。
> Status: 2026-06-13 设计定稿(brainstorming 产出)。前置 PR-C-0.5(replay harness)已合入 main `7aad7df`(全量 1013 passed)。
> 决策基线:**纯保行为合一**(只保证输出逐项不变,不统一两侧语义口径);**helper 三样全入**(forex 判定族 + `_contains_ytd_marker` 收尾 + `_append_note` 族);**跨侧参数化 characterization tests 先行**。
> 行号采自 main `7aad7df`(C-0.5 仅新增 tests/fixtures/docs,未触碰两脚本,行号有效);**执行以 PR 开工时从当时 HEAD 现生成的 per-PR 计划为准**。

## 1. 目的与定位

`scripts/stage2_unified_enhancer.py`(7077 行)与 `scripts/stage2_5_injector.py`(4355 行)各自维护一份 **forex 证据判定族**(`_is_forex_*` / `_has_forex_*` / `_is_valid_forex_*` 等),逻辑高度重叠却已漂移。C0 把这一族下沉到单一共享模块、两侧引用,作为后续 C1–C5 机械拆分的**去重前提**。

C0 是 §10 风险表点名的高风险去重项:"forex 证据合一两侧语义其实有微差——先写 characterization tests 锁住两侧现行为,diff 出真实差异再决定保留哪侧;有差异则维持两个入口函数共享底层"。本设计据此把策略固化为**纯保行为 + 共享底层 + 保留分歧**。

## 2. 范围

**In scope**
- forex 证据判定族 → 新建 `src/datasource/utils/forex_evidence.py`,两脚本引用。
- `_append_note` 族 → 新建 `src/datasource/utils/note_utils.py`(`gate_formatting.py` 是 gate-block 专用,**不混入**)。
- `_contains_ytd_marker` 收尾:两侧已是 `contains_ytd_marker`(`utils/text_markers.py`)的薄包装,C0 去掉两个本地 alias、call site 直调(或保留 alias,二选一,零行为风险)。
- characterization tests 新增(先行)。
- 配套 housekeeping:TODOS.md 状态修正、本地 main 同步(已完成)、prunable worktree 清理。

**Out of scope(本 PR 不做)**
- 任何 absence / 数值强转 / 字段口径的**语义统一**(纯保行为,只记录差异)。
- consumers / orchestration 函数迁移:Stage2 `_scrub_unevidenced_forex_zeroes`、`_copy_forex_compare_fields`;Stage2.5 `_should_backfill_forex_*`、`_usable_forex_*`、`_copy_valid_forex_*_change_evidence`、`_is_zero_*`。这些是写回/回填编排,留待 C1/C4 随引擎/注入器拆分迁移。C0 只下沉**无状态谓词/校验器**。
- `_execute_tasks`、Stage2/Stage2.5 其它任何拆分。

## 3. 两侧差异矩阵(C0 核心交付,必须写进 PR 描述)

所有差异都从**两个 ROOT 分歧**派生。Codex 执行时须把本矩阵补全(含常量值 diff 结论)并贴进 PR。

### ROOT-1 · absence 文本判定(根因)

| 维度 | Stage2 `_is_forex_absence_text` (L1939) | Stage2.5 `_is_forex_daily_change_absence_text` (L3406) |
|---|---|---|
| 空串 / `n/a` / `na` / `unknown` / `pending` / `-` / `--` | **不算** absence → `False` | **算** absence → `True` |
| "no change" 消歧 | 有(`_is_forex_no_change_absence_text` + 复杂 carve-out) | **无该概念** |
| 正向 token 集 | `missing/without/unavailable/not available/no data/no value/no window/no evidence/deepseek no value/no deepseek key/failed/failure/error/invalid` + 中文 `缺少/缺失/不可得/不可用/未披露/没有数据/没有窗口/没有证据/没有值/无数据/无窗口/无证据/无值/失败` | 正则 `reason\s*=`、`(missing\|no)[_\s-]` + `deepseek_no_value/missing_previous_value/missing_value/no_previous_value/no_value/failed/failure/error/invalid/unavailable/not_available/not-available/not available/缺失/失败` |

> 影响:该谓词是所有 `_is_valid_*` 校验器和 `_has_*_computed_marker` 的 early-out 依据,口径不同 → 同一输入两侧可能给出不同 evidence 判定。这是"族"无法直接合一的根因。

### ROOT-2 · 数值强转(根因)

- Stage2 base_price 校验用 `_safe_number` (L760);Stage2.5 用 `_coerce_float` (L2125)。
- **Codex 必须 diff 两实现**并在 PR 记录是否行为等价(尤其 `"1,234"` 千分位、`"7.13"` 占位、`None`、`"abc"`、`""` 等边界);若不等价,base_price 校验在共享模块中按各侧注入对应 coerce,**不统一**。

### 派生差异(由 ROOT 决定)

- 结构:Stage2 **字段泛化**(函数带 `field` 参,`daily_change`/`change_120d` 共用一套);Stage2.5 **字段拆分**(daily/120d 各一套,无 `field` 参)。
- `_is_valid_*` 校验器、`_has_*_computed_marker` body 近乎一致,只在"调用哪个 absence / 哪个 coerce / `reject_daily_prefix` 是参数还是内联"上分叉。

### 常量 diff(执行期审计项)

| Stage2 常量 | Stage2.5 对应 | 须确认 |
|---|---|---|
| `_FOREX_DAILY_EVIDENCE_MARKERS` | `FOREX_DAILY_CHANGE_SOURCE_MARKERS` | 值是否一致 |
| `_FOREX_120D_EVIDENCE_MARKERS` | `FOREX_120D_CHANGE_SOURCE_MARKERS` | 值是否一致 |
| `_FOREX_COMPARE_FIELD_EVIDENCE_KEYS` | `FOREX_DAILY_CHANGE_EVIDENCE_KEYS` / `FOREX_120D_CHANGE_EVIDENCE_KEYS` | 键集是否一致 |
| `_FOREX_COMPARE_TEXT_FIELDS` / `_FOREX_COMPARE_EVIDENCE_TOKENS` / `FOREX_COMPARE_FIELDS` | (Stage2 专有) | 直接迁入 |

值一致 → 合一为单一常量;不一致 → 两套并存 + 注释来由。

## 4. 目标结构(方案 B:共享底层 + 保留分歧)

§10 原话"维持两个入口函数共享底层"即方案 B。共享 SHAPE 原语去重,ROOT 分歧以**注入依赖**保留两侧行为。Fallback A(纯逐字搬移不参数化)仅在评审认为注入式 restructure 风险过高时回退。

### `src/datasource/utils/forex_evidence.py`(新建)

- **共享 SHAPE 原语(注入 `is_absence` / `coerce`)**:
  - `normalize_compare_text(text)`、`join_compare_evidence_text(payload, fields)`
  - `is_valid_source_url(value, *, is_absence)`
  - `is_valid_base_date(value, *, is_absence)`
  - `is_valid_base_price(value, *, is_absence, coerce)`
  - `has_computed_marker(value, markers, *, is_absence, reject_daily_prefix=False)`
- **两套 absence 谓词(显式命名,行为各自冻结)**:
  - `is_compare_absence_text`(Stage2 口径) + `is_no_change_evidence` / `is_no_change_absence_text` / `is_compare_absence_text_for_field(text, field)` / `has_positive_compare_text` / `has_negative_compare_marker` / `has_field_specific_evidence` / `has_structured_compare_evidence` / `has_compare_evidence`(Stage2 字段泛化族)
  - `is_daily_change_absence_text`(Stage2.5 口径) + daily/120d 的 `has_*_change_computed_marker` / `has_*_change_evidence`(Stage2.5 族)
- **常量集中**(按 §3 常量 diff 结论合一或并存)。
- 命名以"职责 + 侧别可辨"为准(避免 `field` 与 `daily/120d` 两风格冲突);具体名以 plan 为准。

### 两脚本侧

- 各自保留**薄 alias**(`_is_forex_absence_text = forex_evidence.is_compare_absence_text` 等)以最小化 call-site churn,**行为零变**;coerce 函数(`_safe_number`/`_coerce_float`)C0 可留在脚本作为注入实参(是否并入 `utils/coercion.py` 不在 C0 强求)。
- 两脚本不得保留 forex 判定族的**私有副本实现**(除薄 alias / import)。

### `src/datasource/utils/note_utils.py`(新建)

| 函数 | 来源 | 行为(保留,不合并) |
|---|---|---|
| `append_note_text(note, extra)` | Stage2 `_append_note` (L2986) | 空格分隔;`tail in base` 去重;空→`None`;纯函数返回 `Optional[str]` |
| `append_note_to_entry(entry, message)` | Stage2.5 `_append_note` (L3638) | 改 `entry["note"]`;"；"分隔;不去重;返回 `None` |
| `append_note_once(note, addition)` | Stage2.5 `_append_note_once` (L1201) | "；"分隔;`addition in note` 去重;返回 `str` |

> 如实标注:三者行为不同,这是**迁移 + 命名区分 + 文档化差异**,非真合并。共置目的是消除"两脚本各藏一份易漂移"。

### `src/datasource/utils/text_markers.py`(已存在)

去掉两侧 `_contains_ytd_marker` 薄 alias,call site 直调 `contains_ytd_marker`(或保留 alias)。零行为风险。

## 5. Characterization tests(先写,TDD)

新增 `tests/test_forex_evidence_characterization.py`(仓库现**零** forex 专测,这是 PR 标题"先 characterization tests"的核心交付):

1. **搬移前先落地并跑绿**:从两侧脚本 import 现函数,跑同一输入表,断言各自**当前**输出 = 锁住现行为。
2. **跨侧参数化**:`pytest.mark.parametrize` 跑 (input) × (side),把两侧 expected 并列于同一用例表 → 差异成为**可执行文档**(直接映射 §3 矩阵)。
3. **输入表显式覆盖 ROOT 分歧**:空串、各哨兵(`n/a`/`na`/`unknown`/`pending`/`-`/`--`)、`no change`/`unchanged`/`无变化`/`没有变化`、computed marker(含 `daily_*` 前缀拒绝、negative 前缀)、`_safe_number` vs `_coerce_float` 边界(`"1,234"`/`"7.13"`/`None`/`"abc"`/`""`)、各 evidence-key 组合、source_url/base_date/base_price 合法与非法值。
4. **搬移后**:把 import 改指向 `forex_evidence.py`(经各侧 alias),断言输出**逐项不变**(同一表、同一 expected)。
5. 不改任何现有测试;新测试进默认 `pytest -q`(全离线、秒级)。

> 已有间接覆盖(回归网,不替代 characterization):C-0.5 replay harness(`tests/test_stage2_replay_harness.py`,Stage2 端到端 byte-stable)、`tests/test_stage25_contract_replay.py`(Stage2.5 注入回放)。

## 6. 执行流程框架(给 Codex;exact code 由 writing-plans 从 HEAD 现生成)

> 环境头与 worktree 协议见 REFACTOR_PLAN §11 / §11.1;plan 须内联完整环境头(Codex 零上下文)。

1. **Task 0 置备**:worktree `.worktrees/codex-batch-c0-forex-evidence`(分支 `codex/batch-c0-forex-evidence`)← from main `7aad7df`;按 §11.1 配方置备 `.env`/`.venv`/`logs`/`reports`;baseline `bash run_clean.sh python -m pytest -q` 全绿(含 C-0.5 replay harness)。
2. 写 characterization tests(两侧现函数),跑绿 = 锁现行为。
3. 建 `forex_evidence.py`:先迁常量 + 完成 §3 常量 diff 审计(产出矩阵草稿)。
4. 迁谓词族(§4),两脚本改 import / 薄 alias。
5. 建 `note_utils.py`,迁三个 note 函数 + 改 call site;ytd alias 收尾。
6. 重跑:characterization tests + 全量 `pytest -q` + C-0.5 replay harness + `test_stage25_contract_replay`,**全绿且 byte-stable**。
7. 把 §3 差异矩阵补全写进 PR 描述。
8. 收尾:隔离断言(主 checkout 数据零变更)、临时产物清理、完成回报。

## 7. 行为冻结约束(diff 只允许 import/路径/alias 变化的区域)

- **输出零变化**:由 characterization tests + C-0.5 replay + `test_stage25_contract_replay` 三重证明。
- **不统一 absence / coerce 口径**:有分歧一律保留两套并文档化;不得"顺手"对齐。
- **forex 零值防占位**(CLAUDE.md 冻结区):`_scrub_unevidenced_forex_zeroes` 逻辑不改;即便它留在脚本,其依赖谓词的输出必须与现状逐项一致。
- 两侧必须都 import 共享模块,不留私有副本。
- 验证**全离线**:不重跑 Stage2 真实搜索(Tavily 每日一次);不触碰当日 `data/runs/YYYYMMDD` 与 `data/trend_history`;不手删 `.run.lock`。
- consumers / orchestration 本 PR 不动(见 §2 out of scope)。

## 8. 验收

1. characterization tests 搬移前锁绿、搬移后逐项不变。
2. `pytest -q` 全绿;C-0.5 replay 与 `test_stage25_contract_replay` 仍 byte-stable。
3. 两脚本中 forex 判定族 / `_append_note` 族无本地实现(`rg "def _is_forex|def _has_forex|def _is_valid_forex|def _append_note" scripts/` 仅剩 alias 或为空)。
4. PR 描述含完整 §3 差异矩阵(ROOT-1 / ROOT-2 + 常量 diff 结论 + `_safe_number` vs `_coerce_float` 等价性结论)。
5. `note_utils.py` 三函数行为与原实现逐项一致(用例覆盖各自分隔符/去重/返回语义)。

## 9. 前置 / housekeeping 状态

- ✅ **PR-C-0.5 已合入** main `7aad7df`(canonical harness,1013 passed)。
- ✅ **本地 main 已同步** `7e81f97 → 7aad7df`(ff-only):丢弃的本地 C-0.5 草稿安全存于 `git stash@{0}`(可恢复);`settings.local.json` 4 条本地权限保留;`.gstack/` 原样未动。
- ⬜ **TODOS.md 状态修正**(随本 spec 提交):PR-B → 完成(shim 删除仍延期到 C 批次后);PR-C-0.5 → 完成;"当前焦点" → PR-C0。
- ⬜ **prunable worktree `codex/batch-c05-spec-hardening` 清理**(`git worktree remove` + 分支按需);不阻塞 C0(C0 用新 worktree)。

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 注入式 restructure(方案 B)改了行为 | characterization tests 搬移前锁、搬移后逐项断言;三重回归网兜底;必要时回退 Fallback A |
| 归一不彻底,某侧 absence/coerce 被悄悄对齐 | §7 显式禁止;PR 差异矩阵 + characterization 表逐项核;评审 diff 只允许 import/alias 变化 |
| 常量值两侧实际不同却被合一 | §3 常量 diff 为执行期硬审计项,不一致则并存 |
| `_append_note` 同名不同物被误"合并"为一个函数 | §4 强制三个独立命名函数 + 各自用例;禁止合并签名 |
| forex 零值防占位行为漂移 | 冻结区,`_scrub_unevidenced_forex_zeroes` 不改;replay 兜底 |
| 行号漂移 | plan 从 HEAD 现生成;搬移块给完整代码 |
