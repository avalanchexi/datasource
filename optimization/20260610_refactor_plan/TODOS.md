# 重构进度跟踪(TODOS)

> 基于 `REFACTOR_PLAN.md` v2(2026-06-11)。每个 PR 合入 main 时更新本文件;状态以本文件为准,细节看对应 spec/plan。
>
> 图例:`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成 · `[!]` 阻塞(附原因)

## 总览

| 批次 | 内容 | PR 数 | 状态 | 前置 |
|---|---|---|---|---|
| 规划 | 方案 v2 + 工作流 | - | ✅ 完成 | - |
| 批次 0 | 功能有效性审计 | 1 | ✅ 完成 | - |
| 批次 A | 仓库清理 | 1 | ✅ 完成(squash `72dc42c`) | - |
| 批次 B | 脚本命名收敛 | 1 | ✅ 完成(shim 删除延期至 C 后) | - |
| 批次 C | 巨石拆分(含 C-0.5/C0/C7 终态)| 8 | ✅ 完成(C-0.5/C0/C1/C2/C3/C4/C5/C6/C7 全部合入 main)| B |
| 批次 D | run 目录契约 | 2 | ✅ 完成(D1/D2 合入 main,含 D2 minor-hardening)| C |
| 批次 E | 兜底产品化 | 3 | 🚧 进行中(E1/E3 已合入 main;E2 worktree 评审通过待补 etf)| E1 可与 C 并行;E2/E3 依赖 D1 |
| 批次 F | stage3 入口瘦身(全局验收2 补口)| 1 | 🚧 worktree 完成、评审通过,待合入 main(F1 through `b985872`;stage4_risk_review 豁免)| C/D |

**当前状态(2026-06-20 状态校正 @ main `83d3bc6`):验收1、5 达成;验收2 待 F1 合入 main;验收3 代码级 producer 清理 PASS、首个 live whitelist smoke 前向观察;验收4 前向观察。剩余:E2-etf 补丁 / F1 merge / 前向观察 gates / coupling doc PR 收口。**

---

## 规划阶段(已完成)

- [x] 第一轮方案三件套(README / REFACTOR_PLAN / TEST_PLAN)— 2026-06-10
- [x] v2 修订:新增批次 0、C-0.5、§11 执行工作流、并行排期 — commit `3be4aa2`
- [x] §11.1 worktree 执行协议 + §11.2 plan 精准性检查清单 — commit `f0c427d`
- [x] 批次 0 spec:`docs/superpowers/specs/2026-06-11-batch0-validity-audit-design.md`
- [x] 批次 0 可执行计划(worktree 版):`docs/superpowers/plans/2026-06-11-batch0-validity-audit.md`

## 批次 0 — 功能有效性审计(REFACTOR_PLAN §3)

- [x] **PR-0**:Codex 在 worktree `codex/batch0-validity-audit` 执行审计计划(9+1 任务)
  - [x] Codex 执行完成并回报(四档计数 / watchlist 档位 / unreachable 列表 / 测试 / 隔离断言)
  - [x] Claude 评审(计划符合度 + 产物完整性),并修复动态 import 与零语句 coverage 盲区
  - [x] 合入 main + `git worktree remove`
- [x] 基于 `AUDIT_RESULTS.md` 修订批次 A 处置表(评审方动作)

## 批次 A — 仓库清理(§4,1 个 PR)

- [x] 生成 PR-A 执行计划(从 HEAD 8759371,过 §11.2 清单):`docs/superpowers/plans/2026-06-11-batch-a-repo-cleanup.md`;规划期已定死全部判断(MCP 链路因混合测试依赖延期、新增 pytest.ini 防 archive 测试被收集、pre-commit 仅 compileall——flake8 现存 ~3500 违规)
- [x] 批次 A 处置表已按批次 0 审计结果修订:保护 Stage2 structured provider 动态加载集群,删除前增加 `tests/ examples/ scripts/ docs/ optimization/` 引用复核闸;`pring_result_contract` 因批次 D2 依赖移出删除候选(评审修正)
- [x] **PR-A**:根目录散件 / archive 双目录合并 / legacy 脚本归档 / MCP 链路延期 / optimization 归档 / logs 治理 / 最小 pre-commit
  - [x] Codex 执行 → Claude 评审(1 Important 修复 `11db191`)→ squash 合入 main `72dc42c` → worktree/分支已清理
- [ ] MCP 链路(mcp_adapter/mcp_tools)归档延期:依赖 test_fund_flow_pipeline.py MCP 段下线(PR-A 评审记录)

## 批次 B — 脚本命名收敛(§5,1 个 PR)

- [x] brainstorming 定稿(scripts/utility 与 scripts/archive 拆分定档):spec `docs/superpowers/specs/2026-06-12-batch-b-script-naming-design.md`
- [x] 生成 PR-B 执行计划(从 HEAD 72dc42c):`docs/superpowers/plans/2026-06-12-batch-b-script-naming.md`;shim 清单按活文档引用实测定死为 8 个,测试修改锁定 2 文件(执行期确认 `test_fund_flow_pipeline.py` 第二组 `sys.path` 行漏计,已按机械路径修正处理)
- [x] **PR-B**:非主链脚本移入 `scripts/tools/` + 旧路径 shim + 活文档命令引用同步
  - [x] Codex 执行 → Claude 评审 → 合入 main(commits `d92624b`/`104cf2d`/`2c2dbd8`/`aeb0ecd`/`7e65ccd`/`5c88b5f`/`7e81f97`)
  - [x] shim 删除(8 个:trend_history_backfill/trend_history_scan/sanitize_market_data/compare_stage2_runs/stage2_health_check/stage2_low_score_audit/setup_stage2_search_env/run_snapshot)——随 PR-C7 终态合入 main

## 批次 C — 巨石拆分(§6,5–7 个 PR,核心)

- [x] PR-C-0.5 spec + 执行计划已生成(2026-06-12,可与批次 B 并行执行,零文件交叠):`docs/superpowers/plans/2026-06-12-batch-c05-stage2-replay-harness.md`
- [x] **PR-C-0.5**:Stage2 replay harness(replay fakes + 录制 oracle + golden byte-stable)— **任何搬移前的硬前置**
  - [x] Codex 执行 → Claude 评审 → 合入 main `7aad7df`(全量 1013 passed)
- [x] **PR-C0**:forex 证据判定族合一(先 characterization tests,后合一;两侧语义差异记录在 PR)
  - [x] brainstorming 定稿:`docs/superpowers/specs/2026-06-13-batch-c0-forex-evidence-consolidation-design.md`(纯保行为 + 共享底层 + 三样全入 + 跨侧参数化 characterization)
  - [x] 执行计划 `docs/superpowers/plans/2026-06-13-batch-c0-review-followups.md` → Codex 执行 → Claude 评审 → squash 合入 main(§3 矩阵入 commit body)
- [x] **PR-C1**:Stage2 拆分 — errors / snippet_filters / evidence / regex_extraction
  - [x] spec:`docs/superpowers/specs/2026-06-13-batch-c1-stage2-split-design.md`(纯机械搬移 + 4 簇 + evidence→snippet_filters 单向 + 跨模块 characterization)
  - [x] 执行计划:`docs/superpowers/plans/2026-06-13-batch-c1-stage2-split.md`(从 HEAD `0187b00` 现生成,7 Task;已含实跑真值 + 偏离声明)
  - [x] 评审补救计划:`docs/superpowers/plans/2026-06-13-batch-c1-review-followups.md` → Codex 执行 → squash 合入 main
- [x] **PR-C2**:Stage2 拆分 — extraction_apply / structured_runner / query_planner / diagnostics / validation / cli
  - [x] Codex 在 worktree `codex/batch-c2-stage2-split` 执行完成:新增 common/cli/query_planner/structured_runner/diagnostics/validation/extraction_apply 模块,主脚本保留 re-export;fixture replay、CLI help diff、全量 pytest byte-stable 通过
  - [x] C2 偏离/留痕: `_try_structured_provider` 未移入 structured_runner,按 C3 carry-forward 与 `_execute_tasks` 同车道切;`_STAGE2_BACKEND_SUMMARY_KEYS`/`_FUND_FLOW_BOUNDS` 随依赖模块 re-export;extraction_apply 复制 Stage2.5 fund_flow 跨脚本 import 并标 `C4-cleanup`
- [x] **PR-C3**:`_execute_tasks` 执行车道拆分
  - [x] 新增 `src/datasource/engines/stage2/execution.py`;`_execute_tasks`/`_try_structured_provider`/DeepSeek 执行件/执行 glue 已机械搬移,主脚本保留 re-export 与 monkeypatch 合同
  - [x] 阶段级 characterization、replay datetime tie-in、replay byte-stable 与全量 pytest 通过
  - [x] C3 carry-forward 已由 PR-C7 收尾(stage2 入口瘦到 14 行,main+glue 搬入 engines/stage2/cli)
- [x] **PR-C4**:Stage2.5 拆分 — common / schema_coercion / manual_official(行为冻结区,单独评审)/ fund_flow / gap_sync
  - [x] 新增 `src/datasource/engines/stage2_5/` 包;主脚本保留 re-export;Stage2.5 contract replay + Stage2 replay harness + 全量 pytest 通过
  - [x] 回收 C2 `C4-cleanup`:Stage2 `extraction_apply`/`execution` fund_flow helper 改指 `engines.stage2_5.fund_flow`;无跨脚本 import 残留
- [x] **PR-C5**:Stage2.5 拆分 — entry_mergers / trend_backfill / core / cli(续接 `engines/stage2_5/`) — squash `0c8f14b`
- [x] (可选)**PR-C6**:stage1_data_collector 瘦身 → `engines/stage1/collector.py`(108 行 re-export+main)— 已合入 main
- [x] **PR-C7(C 终态)**:stage2/2.5 入口瘦身 ≤30(main+10 glue+CRITICAL_EXTRACT_KEYS → `engines/stage2/cli`,延迟 import 破 cli⇄execution 环)+ 删 8 个 batch-B shim + 全面 repoint(含 utils-alias)+ 文档同步 — 已合入 main(stage2 866→14、stage2.5 245→9;评审 replay byte-stable 非假绿)
- [x] 每个 PR:生成计划 → Codex 执行 → fixture replay 全绿 → Claude 评审 → 合入

## 批次 D — run 目录契约(§7,2 个 PR)

- [x] **PR-D1**:原子写(`atomic_write_json`/`atomic_write_text`)+ `RunPaths.data_dir_whitelist()` + `run_dir_audit` 工具 + 删 backup 污染 — 已合入 main
- [x] **PR-D2**:写盘前 contract 校验(stage1/2/2.5/3 hard-fail + `--no-validate-output`/`DATASOURCE_NO_VALIDATE_OUTPUT=1` 逃生门;两 contract 对齐真实输出;含 minor-hardening:base.py lint + field_validator 兼容)— 已合入 main
- [ ] 合入后首个交易日 live smoke:run 目录文件数 == 白名单数(前向观察)

## 批次 E — 兜底产品化(§8,2–3 个 PR)

- [x] **PR-E1**:macro `previous_value/change_rate` 从 event_history 正确回填(修双重转义 report_period 正则 + 周期锚定宁缺勿错 + change_rate 分口径[同比类 pp 差/水平值百分比]+ `value_source=event_history_backfill`)— 已合入 main
- [~] **PR-E2**:`config/manual_fallback_policies.json`(非 yaml:项目无 PyYAML 显式依赖,见 spec §2)+ manual 模板 provenance-only 预填(数值不预填)— worktree 完成、评审通过**待补 etf policy**(补丁已给)→ 补完合
- [x] **PR-E3**:`reserve_ratio` 错口径源屏蔽(删 trading_economics cash-reserve-ratio + 搜索/校验拒该 URL)+ `BCOM` 固定 quote 守卫测试 — 已合入 main `83d3bc6`
- [ ] 验收观察(连续 5 个交易日):macro compare 类 manual = 0;日常手填 ≤ {etf}(前向观察)

## 全局验收(收尾)

> **2026-06-20 状态校正 @ main `83d3bc6`**:
- [x] 跨模块耦合审计(2026-06-17,C7 后):`src/` 对 `scripts` 零 import,反向分层耦合彻底消解;C4 fund_flow reclaim + C7 入口瘦身已清掉"模块 import 脚本私名"模式。无清理 PR,留痕收口。(复盘复测 **PASS**)
- [~] `scripts/` 全部入口 ≤300(stage2/2.5 ≤30):main 当前 stage2=14 / stage2.5=9 / stage1=111 / stage4_report=216 ✅;**stage3=867 仍待 PR-F1 合入后达标**。F1 branch `codex/batch-f1-stage3-slim` 已实现到 `b985872`、测试/评审通过,待 merge;**stage4_risk_review 豁免**——它是有意 standalone、运行时不 import datasource 包的只读 review gate(由 `test_run_path_does_not_import_datasource_package` 强制,run_paths/run_lock 经 importlib 按 path 加载),engines-relocate 会破该契约,故"全部入口 ≤300"细化为"有 engines 逻辑的 stage 入口(1/2/2.5/3)≤300"。
- [~] run 目录无白名单外文件、无 `.bak`/时间戳副本/`_new` 产生:**代码级 producer 清理 PASS**(`src/` 内零 producer,D1/D2 已清;旧 run 目录的 stray 是 D1 前遗留);**首个 live run-dir whitelist smoke 仍为前向观察**。
- [ ] `stage2_effective_hit_rate` 不低于重构前 5 日均值 - 5pp:**前向观察**(重构后无 live run,数据驱动非代码驱动,合入后跟踪)。
- [x] 文档同步:`SCRIPTS.md` / `CLAUDE.md` / `AGENTS.md` 与新结构一致(复盘 **PASS**,新结构关键词 14 处命中)。

## 待执行队列(交 Codex,2026-06-20)

- [ ] E2 补 etf policy 补丁(fund_flow / is_estimated:true / metric_basis:estimated_net_flow / window_evidence:news_summary)+ 测试 → 合 E2
- [ ] F1 merge:`codex/batch-f1-stage3-slim` through `b985872` 已完成实现/测试/评审,待合入 main
- [ ] 耦合审计 §11.2 反向依赖核查 + TODOS 体检单(docstring 已合,Task2 doc PR 状态校正待合)
- [ ] 前向观察 gate:D1/D2 首个 live run 目录白名单 smoke + E 批 5 日 macro-compare-manual=0 + hit-rate
