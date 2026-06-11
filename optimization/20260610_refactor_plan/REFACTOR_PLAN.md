# 2026-06-10 重构主方案

> 状态:v2(2026-06-11 修订)。所有行号/体积数据采自 2026-06-10 工作区(main @ f7dfdc8);**行号仅用于评审定位,执行以各 PR 开工时从当时 HEAD 生成的 per-PR 计划为准**(见 §11 执行工作流)。
>
> v2 变更:新增批次 0(功能有效性审计)、C-0.5(replay harness 前置 PR)、§11 Claude 规划 / Codex 执行工作流;排期改为 Codex 并行化。

## 1. 现状盘点(问题 → 证据)

### 1.1 巨石入口脚本(用户问题 1 的主体)

CLAUDE.md 声称 "每个 `scripts/stageN_*.py` 只是薄入口,真正逻辑在 `src/datasource/` 下",实际:

| 脚本 | 行数 | 体积 | 备注 |
|---|---|---|---|
| `scripts/stage2_unified_enhancer.py` | 7077 | 336KB | `_execute_tasks` 单函数 ~2600 行(L3792–L6439) |
| `scripts/stage2_5_injector.py` | 4355 | 189KB | `inject_websearch_data` ~480 行;`_backfill_trend_changes` ~340 行 |
| `scripts/stage1_data_collector.py` | 2300 | 106KB | 次优先级 |
| `scripts/stage3_pring_analyzer.py` | ~800 | 33KB | 已基本符合"薄入口" |

两脚本间存在**成对重复实现**(各自维护一份、易漂移):forex 证据判定族(`_is_forex_*` / `_has_forex_*`,Stage2 约 L1901–L2313,Stage2.5 约 L3406–L3645)、`_contains_ytd_marker`、`_append_note`、URL/数值 coercion 散件。

### 1.2 死代码与散落产物(用户问题 1 其余部分)

- 根目录:`generate_report_simple.py`(15KB 旧版报告脚本)、`generate_simple_report.py`(2 行 re-export shim)、`update_fund_flow_20251112.bat`(2025-11 一次性脚本)、`diff_latest.txt`(0 字节)、`data_quality_report.md` / `final_analysis_report.md`(历史一次性报告)、`restore_env_vars.ps1`、`README_STAGE2_SNIPPET.md`。
- `archive/unused_py/` 已随 PR-A 合并至 `archive/py_unused/`,当前保留单一死代码归档目录。
- 原 `scripts/legacy/mcp_data_enhancer.py` 已随 PR-A 归档至 `archive/py_unused/legacy/mcp_data_enhancer.py`;MCP adapter/tools 仍延期,`src/datasource/mcp_adapter.py` + `utils/mcp_tools.py` 仅被归档 legacy 脚本与测试引用(CLAUDE.md 已声明"当前流程不使用旧版外部补数链路")。
- `utils/yahoo_finance.py` 与 `providers/stage2_structured/yahoo_finance.py` 双份并存,需确认归属后删一份或合并。
- `optimization/` 下 10 个历史目录(2025-11 至 2026-04)全部摊在工作区。

### 1.3 数据存储位置混乱(用户问题 2)

单日 run 目录(`data/runs/20260522/`)实测 19 个文件,其中非契约文件:

- `market_data.json.bak`、`market_data_stage2.json.bak` — 写入端手工备份。
- `market_data_stage2_20260522172652820099.json` — 微秒时间戳副本,无消费方。
- `trend_history_gap.json` 与 `trend_history_gap_new.json` 并存 — "_new" 后缀演化痕迹。

另:`logs/` 85 个文件无轮转;`reports/` 历史 md 同时被规则禁止读取(只写不读,适合移出热目录);`data/` 下 cache/offline/samples/trend_history 无 README 说明各自生命周期。

### 1.4 脚本命名混乱(用户问题 3)

`scripts/` 24 个脚本至少 6 种命名风格:`stageN_*`、`check_*`、`backfill_trend_history_event_dates` vs `trend_history_backfill`(同领域两种词序)、`fix_*`、`sanitize_*`、`recap_*`、`*_analysis`、`run_*`、`setup_*`、`compare_*`、`gap_monitor_to_manual_template`。
"生成报告"入口存在于三处且名字两两相近:根目录 `generate_report_simple.py` / `generate_simple_report.py`、`scripts/stage4_report_generator.py`、`tests/scripts/generate_simple_report_test.py`。

### 1.5 Stage2 常驻缺口依赖 Stage2.5(用户问题 4)

近期常驻 manual 集合:`mlf`、`etf`、`BCOM`、`CN10Y_CDB`、`reserve_ratio`(tradingeconomics 7.50% 大行口径 vs 报告口径 6.30% 加权平均的陷阱)、`industrial`/`industrial_sales` 的 `previous_value`/`change_rate`。2026-05-22 run 的 `gap_monitor.json` 已收敛到只剩 `etf` — structured-provider-first 路线有效,但兜底流程仍是"每天手写 JSON"。

按可消除性分类:

| 类别 | 指标 | 性质 | 重构动作 |
|---|---|---|---|
| 结构性无解 | `mlf`(多重价位无统一利率)、`CN10Y_CDB`(无稳定 API 口径)、`etf`(120 日窗口不可验证) | 数据源现实 | 兜底**产品化**(批次 E),不再每日手写 |
| 可自动化 | macro `previous_value`/`change_rate` | trend_history 已存数据 | 自动回填(批次 E) |
| 可加源 | `reserve_ratio` 官方口径、`BCOM` | 缺 provider/错口径 provider | structured provider 增补 + 错口径屏蔽(批次 E) |

### 1.6 日报 JSON 缺校验关卡(用户问题 5)

`models/market_data_contract.py`、`pring_result_contract.py` 契约存在,但各阶段**写盘前没有统一 schema 校验**;文件清单无白名单约束,因此 1.3 的杂散文件得以累积。

## 2. 目标与非目标

**目标**

1. `scripts/` 全部回到"薄入口"(<300 行),逻辑下沉 `src/datasource/`,两脚本间重复实现合一。
2. run 目录文件白名单 + 原子写,消灭 `.bak`/时间戳副本/`_new` 文件。
3. 脚本命名统一为 `stageN_*`(流水线)与 `tools/*`(运维工具)两层。
4. 常驻 manual 缺口从"每日手写"变为"declarative 配置 + 自动回填",目标把日常 Stage2.5 手填量压到 `etf` 一项以内。
5. 每阶段产物写盘前过 contract 校验,失败 hard fail。

**非目标(本轮不做)**

- 完整 PipelineStateContract 状态机(仍按 2026-04-27 TODOS 延期,批次 D 只做其子集)。
- Stage1 采集逻辑重写(只做必要的入口瘦身)。
- 全仓库 black 格式化(避免 churn,沿用 scoped 策略)。
- 任何业务口径/gate 行为变更(forex 零值防占位、fund_flow 估算规则、official override allowlist 三项范围等全部原样保留)。

## 3. 批次 0 — 功能有效性审计(P0,先行,~1 天,1 个 PR)

> 2026-06-11 新增。批次 A 的删除依据从"grep 无引用"升级为"运行时证明无用",同时把 1.2 中"有效性存疑"模块清零。

**方法(全离线,无网络/API 依赖,不触碰真实 run 目录与 trend_history):**

1. **静态可达性**:用 `ast` 解析 `src/datasource/` + `scripts/` 全部 import,以 `scripts/*.py`(排除 legacy/archive)为入口做可达性分析,产出 `reachable / unreachable` 模块清单。
2. **运行时覆盖**:以 `data/runs/20260522/` 为夹具,复制到一次性 scratch 目录 `data/runs/19990101/`,在 `coverage` 下回放 Stage2.5(`--trend-history-base-dir` 指向 scratch 副本)→ Stage3 → Stage4 report generator(全部显式路径参数),产出模块级 executed 清单。Stage1/Stage2 需网络,只做静态分析,运行时覆盖可在下一次正常每日流水线上 opt-in 搭车。
3. **合并分级**:`runtime_used`(回放执行,coverage≥20%)/ `imported_only`(仅被导入)/ `reachable_not_run`(静态可达但未回放,可能属 Stage1/2/tools 路径,不可直接删)/ `unreachable`(静态不可达,删除候选)四档,输出 `AUDIT_RESULTS.md` + 机器可读 `used_unused.json`。

**审计工具放 `optimization/20260610_refactor_plan/audit/`(一次性工具,不进 `scripts/`),自带局部 pytest。**

**验收**:1.2 节每个"疑似"模块在结果中有明确档位;`analyzers/comparators/mappers/warnings` 四目录逐模块定档;批次 A 处置表据此修订。

详细任务见 `docs/superpowers/plans/2026-06-11-batch0-validity-audit.md`(writing-plans 规格,Codex 可直接执行)。

## 4. 批次 A — 仓库清理(P0,~0.5 天,1 个 PR)

纯删除/移动,零行为风险。**前置:批次 0 审计结论。**

批次 0 审计结果已合入: `runtime_used=29 / imported_only=4 / reachable_not_run=36 / unreachable=24`。批次 A 删除/移动必须遵守以下闸:

- `unreachable` 只证明从顶层流水线入口不可达,不证明测试、示例或人工脚本未使用。删除/移动前必须对目标路径和 dotted module 跑 `rg` 复核 `tests/`、`examples/`、`scripts/`、`docs/`、`optimization/` 引用;发现有效引用时先更新/下线引用或延期。
- Stage2 structured provider 集群经 `registry.py` 的 `import_module()` 动态加载,已被批次 0 修正为 `reachable_not_run`;批次 A 禁止删除 `src/datasource/providers/stage2_structured/*`。
- 空 `__init__.py` 与纯 docstring 文件不再因 coverage 100% 视为运行时使用;批次 A 判断以 `AUDIT_RESULTS.md` 的四档结果为准。

处置表:

| 对象 | 处置 |
|---|---|
| `generate_report_simple.py`(根) | 移入 `archive/`(先 grep 确认无引用) |
| `generate_simple_report.py`(根,shim) | 保留一个版本周期后删除;PR 内在文件头加 deprecation 注释指向 `scripts/stage4_report_generator.py` |
| `update_fund_flow_20251112.bat`、`diff_latest.txt`、`restore_env_vars.ps1` | 删除 |
| `data_quality_report.md`、`final_analysis_report.md` | 移入 `docs/history/` 或删除 |
| `README_STAGE2_SNIPPET.md` | 内容并入 `SCRIPTS.md` 后删除 |
| `archive/unused_py/` | ✅ PR-A 已并入 `archive/py_unused/`,保留单一目录 |
| `scripts/legacy/` | ✅ PR-A 已归档至 `archive/py_unused/legacy/` |
| MCP 链路(`src/datasource/mcp_adapter.py`,`src/datasource/utils/mcp_tools.py`) | **延期**:虽经批次 0 定档 `unreachable`,但 `tests/test_fund_flow_pipeline.py` 是混合测试(活的 Stage1 资金流用例 + 两处 MCPToolAdapter 用例),PR-A 不做测试手术;待该测试 MCP 段独立下线后再归档 |
| 批次 0 `unreachable` 源码集群:`agents/`(含 `background_scan/`),`analyzers/`,`comparators/`,`mappers/`,`warnings/`,`trackers/`,`generators/report_generator.py`,`engines/data_engine.py`,`utils/data_completion.py`,`calculators/{bond_calculator,economic_cycle_analyzer,fund_flow_calculator}.py`,`calculators/pring/leading_indicator.py` | ✅ PR-A 已归档至 `archive/py_unused/datasource/`;MCP adapter/tools 延期项见上行,不包含在本归档集群 |
| `models/pring_result_contract.py` | **保留,不进删除候选**。虽经批次 0 审计为 `unreachable`(当前仅 legacy 脚本引用),但批次 D2 计划将其接线为 `pring_result.json` 写盘校验(见 §7);提前删除会让 D2 计划踩空 |
| `src/datasource/providers/stage2_structured/*` | **保留**。经动态 import 审计为 `reachable_not_run`,是 Stage2 structured-provider-first 生产路径,不得作为批次 A 删除候选 |
| `utils/yahoo_finance.py` vs `providers/stage2_structured/yahoo_finance.py` | `utils/yahoo_finance.py` 为 `imported_only`,providers 版为动态可达;批次 A 不删除二者。仅记录 TODO,待批次 C 结合 adapter/fund_flow 路径收敛 |
| `optimization/2025*`、`optimization/202601*`、`optimization/archive/` 等已完结目录 | 移入 `optimization/archive/`(目录已存在),只留 `20260427_refactor_plan`(含未完成 TODOS)与本计划 |
| `logs/` | 加 `.gitignore` 规则(若未覆盖)+ 在 `run_clean.sh` 或日志初始化处加 30 天清理;历史文件一次性清空 |
| `.pip-temp/`、`__pycache__/`(根) | 删除 + gitignore |

收尾:引入最小 `.pre-commit-config.yaml`(只跑 `flake8 src/` + `python -m py_compile`,不做格式化),兑现 2026-04-27 延期的 Pre-commit 项的"初始 no-format 模式"。

## 5. 批次 B — 脚本命名收敛(P1,~1 天,1 个 PR)

约定:**流水线主链保持 `stageN_<verb>.py` 不变**(文档/肌肉记忆成本高,不动);非主链脚本移入 `scripts/tools/` 并按 `<domain>_<verb>.py` 重命名:

| 现名 | 新名 |
|---|---|
| `backfill_trend_history_event_dates.py` | `tools/trend_history_backfill_event_dates.py` |
| `trend_history_backfill.py` | `tools/trend_history_backfill.py` |
| `trend_history_scan.py` | `tools/trend_history_scan.py` |
| `backfill_fund_flow_series.py` | `tools/fund_flow_backfill_series.py` |
| `fund_flow_analysis.py` | `tools/fund_flow_analysis.py` |
| `index_trend_analysis.py` | `tools/index_trend_analysis.py` |
| `fix_estimated_verified.py` | `tools/estimated_fix_verified.py`(或确认废弃→archive) |
| `sanitize_market_data.py` | `tools/market_data_sanitize.py` |
| `recap_consistency_check.py` | `tools/recap_consistency_check.py` |
| `compare_stage2_runs.py` | `tools/stage2_compare_runs.py` |
| `stage2_health_check.py` / `stage2_low_score_audit.py` / `check_stage2_inputs.py` / `setup_stage2_search_env.py` | `tools/stage2_*.py` 统一前缀 |
| `check_monthly_freshness.py` | 保留原位(每日流水线必跑,见 CLAUDE.md)|
| `gap_monitor_to_manual_template.py` | `tools/manual_template_from_gap_monitor.py`(批次 E 将增强它) |
| `run_snapshot.py` | `tools/run_snapshot.py` |

迁移策略:旧路径留 6 行 shim(打印 deprecation + `runpy` 转发)一个版本周期;同 PR 更新 `SCRIPTS.md`、`CLAUDE.md`、`AGENTS.md` 中全部命令引用。`grep -r "scripts/<旧名>"` 清零为合入条件。

## 6. 批次 C — Stage2 / Stage2.5 巨石拆分(P1,核心,5–7 个 PR)

原则:**纯机械搬移,不改任何函数体逻辑**;每个 PR 拆一个内聚域,合入条件是 fixture replay 全绿 + 入口脚本 import 转发保持 CLI 行为不变。

### 6.0 最先行 PR(C-0.5):Stage2 replay harness(2026-06-11 新增)

TEST_PLAN 中 C1–C5 的验收依赖"mock Tavily/DeepSeek/Exa 网络层做 fixture replay",**该脚手架当前不存在,是批次 C 的未计价前置工作量**。C-0.5 单独成 PR,在任何搬移开始前落地:

- `tests/fixtures/stage2_replay/` 夹具:取一个完整 run 的 `market_data.json` + `search_tasks_stage2.jsonl` + `websearch_results/` 缓存。
- mock 层:Tavily/DeepSeek/Exa client 的录制回放桩(以 `websearch_results/` 缓存为录制源),不发任何真实请求。
- 断言面:`market_data_stage2.json` 逐字段 + summary 关键指标(`stage2_effective_hit_rate`、`task_structured_success`、`manual_reason_breakdown`)。
- 验收:对未拆分的现状代码跑通 replay 且结果稳定(连续两次 byte-stable,时间戳字段豁免)。

### 6.1 先行 PR(C0):共享重复代码合一

把 Stage2/Stage2.5 成对重复的 forex 证据判定族抽到 `src/datasource/utils/forex_evidence.py`(单一实现 + 两侧引用)。这是后续拆分的去重前提,且已有 `tests/test_*forex*` 回归覆盖(参考近期 commit 5935d84、32b6635、756250d 均在改这一族)。同时合一 `_contains_ytd_marker`(→ `utils/text_markers.py` 已存在,直接并入)、`_append_note` 族(→ `utils/gate_formatting.py` 或新 `utils/note_utils.py`)。

### 6.2 Stage2 拆分目标布局(C1–C3)

新包 `src/datasource/engines/stage2/`,按现有函数簇机械归位:

| 新模块 | 迁入内容(现行号区间) |
|---|---|
| `errors.py` | Tavily 错误分类/quota 判定/环境代理错误(L301–L585) |
| `snippet_filters.py` | 域名/官方域/关键词/新鲜度过滤 + 评分统计(L181–L299, L815–L1101) |
| `evidence.py` | value/usage evidence、source_url 证据、field-retry 证据(L996–L1051, L1670–L1899) |
| `forex_compare.py` | forex compare 写回/清洗(L1901–L2313;判定函数已在 C0 下沉 utils) |
| `regex_extraction.py` | regex fallback / structured value / flow value 抽取(L1297–L1551) |
| `extraction_apply.py` | `_apply_extraction` + metadata 增强(L1553–L1668, L2314–L2584) |
| `structured_runner.py` | structured provider 统计与执行(L2585–L2935) |
| `query_planner.py` | candidate 扩展/定向重试 query(L3560–L3791) |
| `diagnostics.py` | retrieval diagnostics / summary 字段 / manual_required details(L3163–L3498) |
| `executor.py` | `_execute_tasks` 主体(L3792–L6439)— 见 6.3 |
| `validation.py` | fund_flow / general extraction 校验(L6487–L6783) |
| `cli.py` | `_parse_args`/env 默认值/main 装配(L6784–L7077) |

`scripts/stage2_unified_enhancer.py` 最终形态:`from datasource.engines.stage2.cli import main` + `sys.exit(asyncio.run(main()))`,≤30 行。

### 6.3 `_execute_tasks`(2600 行)的拆法

不在搬移 PR 里重写;单独一个 PR(C3),按任务生命周期切成 executor 内的私有协作函数:`_run_structured_phase` → `_run_search_phase`(Tavily/Exa failover)→ `_run_extract_phase`(DeepSeek/regex)→ `_writeback_phase`(写回 + manual_required 判定)→ `_finalize_task_record`。切分线以现函数内既有的阶段注释/局部变量边界为准,**先加阶段级 characterization test**(用 `data/runs/` 现成 fixture 回放 `search_tasks_stage2.jsonl` → 比对 `market_data_stage2.json` 与 summary 字段)再动刀。

### 6.4 Stage2.5 拆分目标布局(C4–C5)

新包 `src/datasource/injectors/stage25/`:

| 新模块 | 迁入内容 |
|---|---|
| `schema_coercion.py` | `_coerce_stage2_results_to_schema`(L1232–L1591) |
| `manual_official.py` | official override allowlist / URL evidence 判定(L378–L668)— **行为冻结区**,迁移后跑 `test_stage25_contract_replay` + allowlist 三项专项用例 |
| `fund_flow.py` | fund_flow 归一化/tier/window 推断(L1018–L1231) |
| `entry_mergers.py` | macro/monetary/fund_flow/stock/bond/commodity/forex 各 `_apply_*`/`_merge_*`(L2380–L2982, L4260–L4707) |
| `trend_backfill.py` | trend_history 回填族(L3017–L4259) |
| `gap_sync.py` | missing_items 同步/gap_monitor 重写/quality blockers(L670–L1017, L4114–L4259) |
| `core.py` | `inject_websearch_data` 主流程(L1592–L2073) |
| `cli.py` | 参数与装配(L4708–L4798+) |

`stage1_data_collector.py` 的瘦身列为 C 批次可选尾巴(C6),优先级最低。

## 7. 批次 D — run 目录契约(P1,2 个 PR)

**D1:原子写 + 文件白名单。**
- `utils/json_io.py` 增加 `atomic_write_json`(tmp + `os.replace`),全流水线写盘统一走它;删除 `_dump_json(backup=True)` 的 `.bak` 路径与时间戳副本逻辑(Stage2 enhancer L750)。
- `utils/run_paths.py` 定义 run 目录白名单(现 19 文件收敛为:`market_data.json`、`market_data_stage2.json`、`market_data_complete.json`、`pring_result.json`、`stage4_risk_review.json`、`policy_evaluation.json`、`gap_monitor.json`、`quality_metrics.json`、`quality_trend.csv`、`run_snapshot.json`、`source_conflicts.json`、`search_tasks_stage2.jsonl`、`trend_history_gap.json`、`websearch_results_auto.json`、`websearch_results_manual.json`、`websearch_results/`、`.run.lock`)。
- `trend_history_gap_new.json` 消费方查清后并回 `trend_history_gap.json`,删 `_new` 写出点。
- 新工具 `scripts/tools/run_dir_audit.py`:列出白名单外文件;`test_run_paths_consistency.py` 扩展断言白名单。

**D2:写盘前 contract 校验。**
- 各阶段写 `market_data*.json` / `pring_result.json` 前过 `models/market_data_contract.py` / `pring_result_contract.py` 校验,失败 hard fail(带 `--no-validate-output` 逃生门,默认开校验)。
- 校验失败信息写入 `quality_metrics.json`,与现 observability 汇合。
- 这是 2026-04-27 PipelineStateContract 延期项的**收缩子集**;完整 run_manifest 状态机继续延期,在 TODOS 保留。

## 8. 批次 E — Stage2.5 兜底产品化(P2,2–3 个 PR)

**E1:compare 字段自动回填扩面。** `_calc_change_from_trend_history` / `_calc_prev_from_event_history` 已存在,但 macro `previous_value` 仍常落 manual。将 event_history 自动回填扩展到 `industrial`/`industrial_sales`/cpi/ppi/pmi 等月度指标的 `previous_value`/`change_rate`(口径沿用现 `(cur-prev)/abs(prev)*100`),回填值标 `value_source=event_history_backfill`,不动 `is_estimated`。验收:连续 5 个交易日流水线中 macro compare 类 manual 条目为 0。

**E2:常驻缺口 declarative 配置。** 新增 `config/manual_fallback_policies.yaml`,声明每个常驻缺口的兜底策略(key、口径说明、官方 URL 模板、`is_estimated` 终值、note marker、有效期/复核周期),增强 `tools/manual_template_from_gap_monitor.py`:从 gap_monitor + 该配置直接生成**预填的** manual 骨架(当前只生成空骨架)。`mlf` 多重价位、`CN10Y_CDB` 估算口径、`etf` 降级披露、`reserve_ratio` 6.30% 加权口径全部入册——把"老司机记忆"变成配置。

**E3:错口径源屏蔽 + provider 增补。** structured provider 层为 `reserve_ratio` 屏蔽 tradingeconomics `cash-reserve-ratio`(7.50% 大行口径,曾产生 2026-05-29 报告的假"偏紧"信号),改挂 PBoC 官方页 provider(沿用现 `official_china.py` 模式);`BCOM` 评估固定 quote 页 provider。注意 official override allowlist 仍只有 `mlf/USDCNY/BCOM` 三项,本批**不扩 allowlist**,`reserve_ratio` 走既有的"单一 pbc.gov.cn HTTPS URL quality replacement"通道。

## 9. 依赖与排期(v2:Codex 并行化)

```
批次0(1d) ──► A(0.5d) ──► B(1d) ──► C-0.5 harness(1-2d) ──► C0(1d) ──► C1..C3 Stage2(3-4d) ──► C4..C5 Stage2.5(2-3d)
                                                                            │
   worktree 并行支线:                                                       └──► D1(1d) ──► D2(1d)
   E1(1d) 与 C 并行(只动 trend_backfill 既有函数,worktree 隔离)
   D1 可与 C4 并行;E2/E3(2d) 依赖 D1 白名单定稿
```

串行总量约 13–17 个工作日、12–15 个 PR;Codex 并行执行(E1/D1 走 git worktree 支线)下日历时间约 **8–10 天**。每个 PR 合入条件:`pytest -q` 全绿 + 批次专属回归(见 TEST_PLAN.md)+ `SCRIPTS.md`/`CLAUDE.md`/`AGENTS.md` 同步更新。

## 10. 风险与回滚

| 风险 | 缓解 |
|---|---|
| Stage2 拆分破坏当日流水线 | 拆分 PR 全部 fixture replay 验证;合入后第一个交易日流水线视为 live smoke,失败即 revert 单个 PR(机械搬移 PR 可独立 revert) |
| forex 证据合一(C0)两侧语义其实有微差 | 先写 characterization tests 锁住两侧现行为,diff 出真实差异再决定保留哪侧;有差异则在 C0 中维持两个入口函数共享底层 |
| 行为冻结区(official allowlist、fund_flow gate)被无意改动 | 这些模块迁移 PR 单独成 PR、diff 只允许 import/路径变化;review checklist 显式列出 |
| Tavily 每日一次限制导致无法重复 live 验证 | 一律 fixture replay;live 只挂当日正常流水线 |
| 旧脚本路径被外部引用(cron/笔记/用户习惯) | 批次 B 的 shim 保留一个版本周期;deprecation 输出指明新路径 |

## 11. 执行工作流(2026-06-11 新增):Claude 规划,Codex 执行

双 agent 均使用 superpowers 规则集,角色分工固化如下:

| 阶段 | 责任方 | 产物与约定 |
|---|---|---|
| Spec(设计) | Claude Code(brainstorming 技能) | `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`,每个子项目一份,用户评审通过后进入 plan |
| Plan(执行计划) | Claude Code(writing-plans 技能) | `docs/superpowers/plans/YYYY-MM-DD-<topic>.md`;**该 PR 开工时从当时 HEAD 现生成**(行号/上下文保鲜);bite-sized 任务、TDD、精确路径/完整代码/精确命令+预期输出、无占位符 |
| Execute(执行) | Codex(executing-plans 技能) | 在 **git worktree**(`.worktrees/codex-<topic>`,分支 `codex/<topic>`)中执行;逐 checkbox 勾选;卡住即停并回报,不擅自改计划 |
| Review(评审) | Claude Code | 两段式:① 计划符合度(每个任务是否按计划完成、有无越界改动);② 代码质量与行为冻结区检查(见 §10);**并独立验证执行者自报的偏差清单,不只信回报摘要**(批次 A 实例:自报"若干质量修复"实为 18 个计划外 commit) |
| Merge | 用户或 Claude Code(经用户确认) | **默认 squash 合入**(批次 A 实证:25 个 commit 含 3 个中间态测试断链);合入前验证分支与合入内容零 diff;下一个 PR 的 plan 才开始生成 |

**每份 plan 必须包含统一环境头**(Codex 零上下文,不依赖其主动读 CLAUDE.md):

- 执行通道:本机 Windows 上必须经 `wsl -e bash -lc '...'` 进入 Linux 侧;`.venv` 是 Linux venv。
- 所有流水线脚本经 `bash run_clean.sh python scripts/...` 执行,不直跑。
- 测试命令:`bash run_clean.sh python -m pytest -q`(或局部路径)。
- 硬约束:Tavily 每日一次,**任何验证不得重跑 Stage2 真实搜索**;不触碰真实 `data/runs/YYYYMMDD`(当日)与 `data/trend_history`(用 `--trend-history-base-dir` 隔离);不手删 `.run.lock`。
- 行为冻结区清单:official manual override allowlist(mlf/USDCNY/BCOM 三项)、fund_flow 估算 gate、forex 零值防占位、Stage3 三路 gate——这些区域 diff 只允许 import/路径变化。
- Commit 规范:Conventional(`feat:/fix:/refactor:/docs:/test:`),小步频提。

### 11.1 Worktree 执行协议(2026-06-11 增补)

每个 PR 在独立 git worktree 中执行(superpowers `using-git-worktrees` 约定;`.worktrees/` 已在 `.gitignore`)。**关键事实:本仓库 `.gitignore` 忽略 `.env`、`.venv/`、`data/`、`logs/`、`reports/`——新建 worktree 中这些全部不存在**,置备是每份 plan 的 Task 0,标准配方:

```bash
MAIN=/mnt/d/cursor/datasource            # 主 checkout(唯一持有 .env/.venv/data 的地方)
BR=codex/<topic>
WT="$MAIN/.worktrees/codex-<topic>"
cd "$MAIN" && git worktree add "$WT" -b "$BR"
cp "$MAIN/.env" "$WT/.env"
mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv"
# <按 plan 声明复制该 PR 需要的 untracked 数据输入(只读源,绝对路径仅指向 $MAIN)>
cd "$WT" && DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V   # 空 .venv 触发 bootstrap
bash run_clean.sh python -m pytest -q    # baseline 必须与主 checkout 一致,否则停-回报
```

收尾:评审通过合入后由评审方 `git worktree remove "$WT"` + 删除分支;失败回滚 = 直接弃 worktree,主 checkout 零污染。

### 11.2 Plan 精准性检查清单(writing plan 全盘思考规则,2026-06-11 增补)

每份 per-PR plan 发布前,规划方必须以"零上下文 Codex 在干净 worktree 中执行"为视角逐条命令走查:

1. **路径可达性**:命令引用的每个路径在 worktree 中存在吗?gitignored 资产(`.env/.venv/data/logs/reports`)默认**不存在**,所需项必须在 Task 0 置备;绝对路径只允许指向主 checkout 的只读源。
2. **CWD 显式化**:所有命令默认从 worktree 根执行;任何例外单独注明。
3. **失败分支**:每条命令有 Expected;可能失败的步骤写明"若失败→回退方案或停-回报",不留给执行者即兴判断。
4. **验证离线**:所有验证命令零真实 API 调用;禁止以"重跑 Stage2"作为验证手段。
5. **首尾完整**:首任务 = worktree 置备 + baseline 测试;尾任务 = 隔离断言(主 checkout 数据零变更)+ 临时产物清理 + 完成回报。
6. **依赖封闭**:新增工具依赖(如 coverage)只装 `.venv`,不改 `requirements.txt`/`setup.py`,除非 plan 显式声明。
7. **行号保鲜**:从当时 HEAD 现生成,不引用已漂移的行号;涉及搬移的代码块直接给完整代码,不写"同 Task N"。
8. **writing-plans 自带三查**:spec 覆盖度、placeholder 扫描、跨任务类型/签名一致性。
