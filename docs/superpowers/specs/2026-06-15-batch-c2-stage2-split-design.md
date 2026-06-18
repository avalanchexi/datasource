# 批次 C2:Stage2 拆分 — common / cli / query_planner / structured_runner / diagnostics / validation / extraction_apply — 设计文档

> Spec for the 2026-06 refactor, batch C2(REFACTOR_PLAN §6.2 第二个 Stage2 巨石拆分 PR)。
> Status: 2026-06-15 设计定稿(brainstorming 产出)。前置 PR-C-0.5(replay harness `7aad7df`)、PR-C0(forex 证据合一 `2427814`)、PR-C1(errors/snippet_filters/evidence/regex_extraction,squash `e59f307`)均已合入 main。
> 行号采自 main `e59f307`(C1 之后,5748 行);**执行以 PR 开工时从当时 HEAD 现生成的 per-PR 计划为准**(见 §6 / plan)。搬移按**函数名 + 逐字 body**,不靠绝对行号 retype。

## 1. 目的与定位

C1 把 4 个**纯叶子谓词**簇(errors/snippet_filters/evidence/regex_extraction)下沉,主脚本从 7174 → 5748 行。C2 继续把**编排核心周边**的内聚域下沉到既有新包 `src/datasource/engines/stage2/`,为 C3(`_execute_tasks` 2647 行切分)腾出干净依赖面。

与 C1 的关键区别(决定方法学):C1 簇无状态、零反向依赖;**C2 的簇会 mutate `market_payload`、贴近编排核心、且横跨两个行为冻结区**(forex 零值防占位、fund_flow gate)。因此 C2 仍坚持**纯机械搬移(body 逐字不变)**,但必须**先建一层 `common.py` 共享底座**消除 module→主脚本反向 import,再按依赖序往上搬。`_execute_tasks`(L2318–4965)是 C3 的活,**C2 绕开它**。

## 2. 范围

**In scope** — 1 个新底座 + 6 个新模块(均在既有包 `engines/stage2/`):

| 新模块 | 职责 | 簇内函数(main `e59f307` 行号) | 冻结区 | 主要依赖 |
|---|---|---|---|---|
| **common.py**(新底座) | 6 簇共享低层件:数值强转 / upsert 元表 / 任务-条目查找 | `_safe_number`(374)、`_RANGE_RULES`(382, 常量)、`_FOREX_UPSERT_META`(404, 常量)、`_COMMODITY_UPSERT_META`(413, 常量)、`_BOND_UPSERT_META`(422, 常量)、`_is_force_refresh_task`(1668)、`_entry_for_task`(1524) | — | C1 模块 / 外部 utils(向下) |
| **cli.py** | argparse + env 默认 + 入口装配件 | `_env_int_default`(5310)、`_env_float_default`(5320)、`_parse_args`(5330)、`_should_enable_exa_fallback`(5469)、`_should_initialize_exa_client`(5474)、`_build_structured_registry_for_args`(5478)、`_is_exa_sdk_available`(5490)、`_load_tasks_from_file`(5498)、`_ensure_keys`(5509)、`_callable_supports_kwarg`(5524)、`_select_proxy_for_url`(5534)、`_validate_proxies`(5549)、`_parse_task_filter`(5579) | — | 外部 / common |
| **query_planner.py** | query 质量打分 + 候选展开 + 定向重试 + 搜索窗口 | `_candidate_query_quality`(429)、`_exa_search_type`(241)、`_start_date_from_max_age`(269)、`_dedupe_candidate_queries`(2086)、`_expand_query_candidates`(2102)、`_build_directed_query`(2226)、`_should_retry_with_directed_query`(2285) | — | snippet_filters(C1)/ common |
| **structured_runner.py** | structured provider 统计 / 记账(7 个叶子累加器) | `_structured_stats`(1137)、`_structured_key_stats`(1160)、`_record_structured_attempt`(1166)、`_record_structured_latency_by_provider`(1174)、`_record_structured_success`(1187)、`_record_structured_fallback`(1202)、`_mark_structured_fallback_on_task`(1222) | — | errors(C1, `_structured_audit_fields_from_task`)/ common（**`_try_structured_provider` 不在此——它是 structured 执行车道编排器，留主脚本随 `_execute_tasks` 一并 C3 切分，见 Out of scope**） |
| **diagnostics.py** | result_type 终定 / post-writeback manual / retrieval 诊断 / summary 指标 | `_finalize_task_result_type`(1672)、`_finalize_websearch_result_type`(1680)、`_post_writeback_manual_reason`(1584)、`_post_writeback_missing_category`(1631)、`_mark_post_writeback_manual_required`(1649)、`_missing_required_output_fields`(1557)、`_nested_row_value`(1689)、`_build_retrieval_diagnostics`(1701)、`_manual_failure_layer`(1743)、`_build_manual_required_details`(1764)、`_has_diagnostic_value`(1804)、`_merge_nested_diagnostic_dict`(1808)、`_merge_diagnostic_row`(1816)、`_diagnostic_rows_for_summary`(1827)、`_stage2_effective_hit_rate`(1871)、`_stage2_summary_metric_fields`(1876)、`_build_stage2_result_count_fields`(1904)、`_format_stage2_task_count_line`(1929)、`_format_stage2_hit_rate_line`(1944)、`_structured_provider_summary_fields`(1957)、`_build_stage2_summary_diagnostics`(1994) | — | common / 外部 |
| **validation.py** | fund_flow 异常旗标 + extraction 校验 | `_detect_fund_flow_suspicious_reason`(5013)、`_flag_fund_flow_anomalies`(5036)、`_validate_fund_flow_extraction`(5069)、`_validate_general_extraction`(5125) | **fund_flow gate** | common(`_safe_number`)/ 外部 |
| **extraction_apply.py** | 抽取元数据增强 + forex 零值清洗 + 回写派发 | `_infer_report_period`(627)、`_infer_as_of_date`(635)、`_augment_extraction_metadata`(655)、`_scrub_unevidenced_forex_zeroes`(808)、`_copy_forex_compare_fields`(838)、`_apply_extraction`(866) | **forex 零值防占位** | common / evidence(C1, `_source_label_for_task`)/ 外部官方 allowlist / **跨脚本 fund_flow import(标 C4)** |

- 新文件:`engines/stage2/{common,cli,query_planner,structured_runner,diagnostics,validation,extraction_apply}.py`(包 `__init__.py` 已存在,C1 建)。
- 主脚本 `scripts/stage2_unified_enhancer.py`:删除上述 7 组本地定义,改为从对应新模块**显式 import `_私有名`**(call-site 零改,见 §4)。
- 跨模块 characterization tests 新增(先行,见 §5),冻结区函数加码逐字符核验。
- 配套 housekeeping:TODOS.md C2 状态、文档同步检查(见 §9)。

**Out of scope(本 PR 不做)**

- 任何函数体逻辑改动:纯搬移,body 逐字不变(含注释、局部变量名、空行)。
- **`_safe_number` 不并入 `utils/coercion.py`**:本 PR 仅把它从主脚本搬到 `engines/stage2/common.py`;与 `utils/coercion` 的语义合一是带行为含义的改动,延后到后续批次(C1 spec 的"结合 coercion 收敛"在此**降级为纯位置搬移**)。
- **extraction_apply 的 4 个 fund_flow helper 不搬**:`_default_fund_flow_metric_basis`/`_infer_fund_flow_source_tier`/`_infer_fund_flow_window_evidence`/`_normalize_fund_flow_estimation` 仍由 `scripts/stage2_5_injector.py` 定义,extraction_apply 复制主脚本现有 try/except 跨脚本 import;它们搬到 src 是 **C4 fund_flow 拆分**的活(本 PR 显式登记为 C4 清理钩,见 §3 决策 C)。
- `_execute_tasks`(2318–4965)切分 → C3。
- **`_try_structured_provider`(structured 执行车道编排器)→ C3**:它编排 `augment→validate→apply→post-writeback→update-missing-items→task-log`,依赖 extraction_apply/diagnostics/validation 簇 + out-of-scope glue(`_update_missing_items`/`_append_task_log`,被 `_execute_tasks` 重度使用)。搬入任何 src 模块必产生 module→主脚本反向 import;与 `_execute_tasks` 同属执行编排层,一并 C3 切分。structured_runner 本 PR 只取 7 个统计/记账叶子(`_try_structured_provider` 留主脚本经 re-import 调这 7 个)。
- 主脚本入口瘦身到 ≤30 行 → C 批次终态(C2 只缩小,不达终态行数)。
- deepseek 执行件(`_DeepSeekCircuitBreaker`/`_is_deepseek_timeout`/`_mark_stale_refresh_failure`)、io/glue(`_load_json`/`_dump_json`/`_append_task_log`/`_merge_missing_items`/`_apply_aliases`/`_compute_derived_metrics`/`_gap_monitor`/`_filter_tasks`/`_update_missing_items`/`_append_gap_monitor` 等):本 PR 不搬,留主脚本(C3/终态)。

## 3. 边界决策(brainstorming 核心结论)

| 决策 | 结论 | 依据 |
|---|---|---|
| **A. 共享底座** | 新建 `engines/stage2/common.py`,把 `_safe_number`/`_RANGE_RULES`/3 个 `_*_UPSERT_META`/`_is_force_refresh_task`/`_entry_for_task` **纯逐字搬入**;6 簇向下 import。**不**并入 utils/coercion(延后) | 6 簇都引用这些主脚本低层件(`_safe_number` 全脚本 32 处调用),直接搬簇会产生被禁止的 module→主脚本反向 import;纯搬移=零行为风险,复刻 C1 哲学 |
| **B. PR 切分** | 单个 PR-C2,7 组一次搬完;冻结区簇(extraction_apply 的 forex / validation 的 fund_flow)各自独立 commit + 评审时逐字符核验 | 与命名一致;复刻 C1"一个 PR 内 body 逐字 + 冻结区不动"的成功路径;split 成多 PR 收益不抵流程开销 |
| **C. fund_flow 跨脚本依赖** | extraction_apply 完整搬入(含 `_apply_extraction`/`_augment_extraction_metadata`),内部复制主脚本既有 try/except `from stage2_5_injector import ...`;在 plan 与代码注释显式登记为 **C4 fund_flow 搬到 src 后的清理钩** | 运行时 OK(conftest/run_clean 均把 scripts/ 上 sys.path);零行为变更;不碰 stage2_5_injector、不与 C4 冲突、不扩冻结区评审面到 Stage2.5 |
| **D. common 最终成员** | 表中为预判;**由 plan 的 `flake8 F821` 扫描定死**:任何被搬出的簇若引用某个仍在主脚本的私有件,该件即并入 common | 机械、可判定;防漏判反向 import(如 `_entry_for_task` 是否真被多簇共用) |
| **E. diagnostics 合一** | 19 函数合为单个 `diagnostics.py`(不再分 summary/diagnostics) | 同属观测/汇总/诊断聚合,内聚;再分会产生簇间横向 import |
| **F. 搬移后主脚本如何调** | 显式 `from datasource.engines.stage2.<mod> import _foo, ...` 保留 `_私有名` | call-site(含 `_execute_tasks`/`main`)零改动;diff 只在文件头 import 段 + 删除原定义 |

## 4. 目标结构与搬移机制

### 4.1 包布局(C2 后)

```
src/datasource/engines/stage2/
  __init__.py            # C1 已建
  errors.py              # C1
  snippet_filters.py     # C1
  evidence.py            # C1(import snippet_filters)
  regex_extraction.py    # C1
  common.py              # C2 新底座:_safe_number/_RANGE_RULES/3 UPSERT_META/_is_force_refresh_task/_entry_for_task
  cli.py                 # C2
  query_planner.py       # C2(import snippet_filters, common)
  structured_runner.py   # C2(import errors, common)
  diagnostics.py         # C2(import common)
  validation.py          # C2(import common)  —— fund_flow 冻结区
  extraction_apply.py    # C2(import common, evidence；跨脚本 fund_flow import 标 C4)—— forex 冻结区
```

### 4.2 搬移依赖序(plan 必须按此序,逐簇 py_compile+flake8+characterization+replay)

1. **common.py**(底座,先建):无 intra-package 依赖(只可能 import C1/外部)。建好后主脚本删原定义 + re-import;此时主脚本其它代码(含未搬的簇)对这些名的调用经 re-import 不变。
2. **cli / query_planner / structured_runner / diagnostics**(低风险,任意序):各自 import common(+ 对应 C1 模块);主脚本删原定义 + re-import。
3. **validation**(fund_flow 冻结区,独立 commit):import common;逐字搬,gate 判定 body 一字不改。
4. **extraction_apply**(forex 冻结区,独立 commit,最后):import common + evidence;复制跨脚本 fund_flow import;`_scrub_unevidenced_forex_zeroes`/`_copy_forex_compare_fields`/`_apply_extraction` body 逐字不改。

### 4.3 搬移机制(每簇统一三步,逐字)

1. **新模块** = import header(按实际引用裁剪)+ 该簇常量(逐字)+ 该簇函数(逐字,body 一字不改)+(如需)对 common/C1 模块/跨脚本 fund_flow 的 import。
2. **主脚本删除**该簇原定义(函数 + 常量),在 import 段(C1 的 4 个 re-import 块之后)追加对应 re-import 块(`# noqa: F401 (C2 re-export)`),完整名单由 plan 列出;常量(`_RANGE_RULES`/`_*_UPSERT_META`)若仍被主脚本残留代码引用,一并 re-import。
3. **不保留薄 alias、不改 call-site**:主脚本所有原调用点因 import 进同名,逐字不动。

### 4.4 入口行数

C2 后主脚本预计再减约 1500–2000 行(7 组合计),但**不达 ≤30 行终态**(那是 C3 + 终态清理后)。C2 验收只要求"减少且 CLI 行为不变",不卡终态行数。

## 5. Characterization tests(先写,TDD;replay harness 之外的第二重网)

新增 `tests/test_stage2_c2_split_characterization.py`(跨模块 before/after 断言):

1. **搬移前先落地并跑绿**:从 `scripts.stage2_unified_enhancer` import 各簇代表函数,跑固定输入表锁现行为。每模块核心覆盖:
   - common:`_safe_number`(数值/字符串/占位/None 边界)、`_is_force_refresh_task`、`_entry_for_task`(各 category 命中 + upsert meta 路径)。
   - cli:`_parse_args`(默认值快照)、`_env_int_default`/`_env_float_default`、`_parse_task_filter`、`_validate_proxies`/`_select_proxy_for_url`。
   - query_planner:`_candidate_query_quality`(打分形状)、`_expand_query_candidates`/`_dedupe_candidate_queries`、`_build_directed_query`/`_should_retry_with_directed_query`、`_exa_search_type`/`_start_date_from_max_age`。
   - structured_runner:`_structured_stats`/`_record_structured_*`(统计累加形状)、`_mark_structured_fallback_on_task`(写回字段)。
   - diagnostics:`_finalize_task_result_type`/`_finalize_websearch_result_type`、`_build_retrieval_diagnostics`/`_manual_failure_layer`/`_build_manual_required_details`、`_stage2_effective_hit_rate`/`_stage2_summary_metric_fields`、`_post_writeback_manual_reason`/`_missing_required_output_fields`。
   - **validation(冻结区,加码)**:`_validate_fund_flow_extraction`/`_flag_fund_flow_anomalies`/`_detect_fund_flow_suspicious_reason` 的 gate 判定逐项锁(估算/窗口/source_tier 触发与否);`_validate_general_extraction`。
   - **extraction_apply(冻结区,加码)**:`_scrub_unevidenced_forex_zeroes`(零值保留 vs 转 manual 的每条分支)、`_copy_forex_compare_fields`、`_apply_extraction`(macro/monetary/fund_flow/forex/commodities/bonds/upsert/fallback 各回写路径 + official non-estimated 标记)、`_augment_extraction_metadata`、`_infer_report_period`/`_infer_as_of_date`。
2. **搬移后**:import 改指向 `datasource.engines.stage2.<mod>`(或经主脚本 re-export,二者皆可,断言两路一致 + `is` 身份),同一输入表、同一 expected,**逐项不变**。
3. **import-surface 断言**:7 个新模块 export 全部应迁名 + 主脚本仍可调同名(re-export 生效),防漏迁/拼写漂移。
4. 不改任何现有测试;新测试进默认 `pytest -q`(全离线、秒级)。

> 已有回归网(不替代 characterization):C-0.5 replay harness(`tests/test_stage2_replay_harness.py`,端到端 byte-stable)兜底整体行为。**datetime tie-in**:若任一 C2 模块读 `datetime.now/utcnow/today`(诊断/汇总可能),必须把该模块加进 replay harness 的 `_freeze_stage2_datetime` 冻结循环,否则 replay 非确定性——这正是 C1 followup 前向卫生 docstring 警示的场景。plan 须含此检查(grep 各新模块的 datetime 用法 + replay byte-stable 兜底)。

## 6. 执行流程框架(给 Codex;exact code 由 plan 从 HEAD 现生成)

> 环境头与 worktree 协议见 REFACTOR_PLAN §11 / §11.1;plan 须内联完整环境头(Codex 零上下文)。

1. **Task 0 置备**:worktree `.worktrees/codex-batch-c2-stage2-split`(分支 `codex/batch-c2-stage2-split`)← from main(当时 HEAD);按 §11.1 配方置备 `.env`/`.venv`/`logs`/`reports`;baseline `bash run_clean.sh python -m pytest -q` 全绿(含 C-0.5 replay harness、C1 characterization)。
2. 写 characterization tests(主脚本现函数),跑绿 = 锁现行为(冻结区加码)。
3. 按 §4.2 依赖序建模块:common 先 → cli/query_planner/structured_runner/diagnostics → validation(独立 commit)→ extraction_apply(独立 commit,最后)。
4. 每建一个模块:迁常量 + 迁函数(逐字)→ 主脚本删原定义 + 加 re-import → `py_compile` + `flake8`(F401/F811/F821)→ 局部跑 characterization + replay harness。
5. 全部迁完:characterization 改指向新模块断言逐项不变;全量 `pytest -q` + `py_compile` + `flake8 src/` + replay harness **byte-stable**;主脚本 `--help` diff 为空。
6. 收尾:隔离断言(主 checkout 数据零变更)、临时产物清理、完成回报;更新 TODOS.md C2 行。

## 7. 行为冻结约束(diff 只允许"搬移 + import"变化)

- **函数体逐字不变**:7 组所有函数 body 一字不改(含注释、空行、局部名)。评审 diff 只允许:新模块新增、主脚本删除原定义 + 新增 re-import 段。
- **零 call-site 改动**:主脚本对这些函数/常量的调用点全部保持原样(靠同名 re-import)。
- **冻结区单独评审**:forex 零值防占位(`_scrub_unevidenced_forex_zeroes`/`_copy_forex_compare_fields` + `_apply_extraction` 的 forex 分支)、fund_flow gate(`_validate_fund_flow_extraction`/`_flag_fund_flow_anomalies`/`_detect_fund_flow_suspicious_reason`)逐字符核验;official override allowlist 逻辑本身在 `utils/source_trust`(外部),C2 不搬不改,仅 extraction_apply 调用它。
- **依赖单向无环**:common → 无 intra(只可能 C1/外部);6 簇 → common(+ 对应 C1);**不得出现 module→主脚本反向 import**;extraction_apply → `scripts/stage2_5_injector` 是既有跨脚本依赖的复制(标 C4),plan 须 import-time 冒烟确认不成环(stage2_5_injector 不得 import 任何 C2 新模块)。
- **`_safe_number` 仅搬位置**:不并入 utils/coercion,不改其实现。
- 验证**全离线**:不重跑 Stage2 真实搜索(Tavily 每日一次);不触碰当日 `data/runs/YYYYMMDD` 与 `data/trend_history`;不手删 `.run.lock`。

## 8. 验收

1. characterization tests 搬移前锁绿、搬移后逐项不变(冻结区加码项全绿);import-surface + `is` 身份断言通过。
2. `pytest -q` 全绿(passed 数 = baseline + 新 characterization 用例);`python -m py_compile src/datasource/engines/stage2/*.py scripts/stage2_unified_enhancer.py` 通过;`flake8 src/` 无新增违规(尤其 F401/F811/F821)。
3. C-0.5 replay harness 仍 byte-stable;`scripts/stage2_unified_enhancer.py --help` 与基线 diff 为空。
4. 主脚本中已搬组无本地定义(`rg "^def _safe_number|^def _apply_extraction|^def _validate_fund_flow_extraction|^def _candidate_query_quality|^def _parse_args|^def _record_structured_success|^def _build_retrieval_diagnostics" scripts/stage2_unified_enhancer.py` 为空),仅剩 re-import;`_RANGE_RULES`/`_*_UPSERT_META` 亦无本地定义。**`_try_structured_provider` 仍应在主脚本**(`rg "^async def _try_structured_provider"` 命中——它是 C3 范围,不在本 PR 搬出)。
5. 依赖图:`common`/`cli`/`query_planner`/`structured_runner`/`diagnostics`/`validation` 无 module→主脚本反向 import;`extraction_apply` 仅对 `scripts/stage2_5_injector` 有既有跨脚本依赖(标 C4),无环。
6. 主脚本行数较 C1 后基线(5748)显著下降(预计 −1500+);CLI 行为不变(本 PR 不卡 ≤30 行终态)。
7. import-time 冒烟:`python -c "import scripts.stage2_unified_enhancer"`(或经 conftest 路径)无 ImportError、无循环 import。

## 9. 前置 / housekeeping 状态

- ✅ **PR-C-0.5 / PR-C0 / PR-C1 已合入** main(replay harness + forex 证据合一 + 4 簇拆分)。
- ✅ **C1 followup**(replay harness 前向卫生 docstring):若已合入,`_freeze_stage2_datetime` 的扩展点说明已就位;C2 据此扩冻结循环(如有新 datetime 源)。
- ⬜ **TODOS.md C2 行**:`[ ] PR-C2` → 执行中/完成(随 PR 合入更新);"当前焦点" → PR-C3。
- ⬜ **文档同步检查**:本 PR 仅搬内部私有函数 + 常量,不改 CLI/命令引用 → `SCRIPTS.md`/`CLAUDE.md`/`AGENTS.md` 命令示例预计零改动;plan 收尾跑 `tests/test_manual_template.py`/`test_stage4_docs.py` 确认无命令漂移。

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 搬簇产生 module→主脚本反向 import(`_safe_number`/upsert meta/`_is_force_refresh_task`) | 决策 A:先建 common 底座;plan flake8 F821 扫描定死 common 成员;依赖序 common 先行 |
| 漏迁某函数 / 拼写漂移 → NameError | import-surface 断言 + flake8 F821 + py_compile;characterization 覆盖每模块核心谓词 |
| 冻结区 body 被"顺手"微调(forex 零值 / fund_flow gate) | §7 冻结:body 逐字;冻结簇独立 commit + 评审逐字符核验;characterization 加码锁每条 gate 分支 |
| extraction_apply 跨脚本 fund_flow import 成环 | plan import-time 冒烟;确认 stage2_5_injector 不 import 任何 C2 新模块;方向与现状(主脚本→stage2_5_injector)一致 |
| C2 模块读 datetime 致 replay 非确定性 | datetime tie-in:grep 各新模块 datetime 用法,需要则扩 `_freeze_stage2_datetime` 冻结循环;replay byte-stable 兜底 |
| `_safe_number` 被误并入 utils/coercion / 误改实现 | §2/§7 定死仅搬位置;plan 不含 coercion 合一步骤 |
| 行号漂移 | plan 从开工 HEAD 现生成;搬移按函数名 + 逐字 body |
| `_apply_extraction`(270 行,多 category 回写)搬移引入差异 | characterization 覆盖全部回写路径 + replay harness 端到端 byte-stable;extraction_apply 最后搬、独立 commit 便于二分定位 |
