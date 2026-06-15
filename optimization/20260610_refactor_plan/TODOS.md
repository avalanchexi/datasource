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
| 批次 C | 巨石拆分(含 C-0.5/C0) | 5–7 | 🚧 进行中(C-0.5/C0/C1/C2 完成;下一步 C3) | B |
| 批次 D | run 目录契约 | 2 | 未开始 | C(D1 可与 C4 并行) |
| 批次 E | 兜底产品化 | 2–3 | 未开始 | E1 可与 C 并行;E2/E3 依赖 D1 |

**当前焦点:PR-C3(`_execute_tasks` 执行车道拆分)——从 C2 合入后的 HEAD 现生成 brainstorm/spec/plan。**

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
  - [ ] shim 删除(8 个:trend_history_backfill/trend_history_scan/sanitize_market_data/compare_stage2_runs/stage2_health_check/stage2_low_score_audit/setup_stage2_search_env/run_snapshot)——到期条件:批次 C 全部合入后

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
- [ ] **PR-C3**:`_execute_tasks`(2600 行)按任务生命周期切五段(先加阶段级 characterization test)
  - [ ] C3 carry-forward: `_try_structured_provider` 与 `_execute_tasks` 一并切;DeepSeek 执行件(`_DeepSeekCircuitBreaker`/`_is_deepseek_timeout`/`_mark_stale_refresh_failure`)随执行层切;io/glue 归宿待 C3/终态判断
  - [ ] C3 plan 前置:必须从 C2 合入后的 HEAD 现生成;先做阶段级 characterization、replay byte-stable、datetime tie-in;先核验候选函数出向调用图,防止把编排器误分类为 helper
- [ ] **PR-C4**:Stage2.5 拆分 — schema_coercion / manual_official(行为冻结区,单独评审)/ fund_flow / gap_sync
- [ ] **PR-C5**:Stage2.5 拆分 — entry_mergers / trend_backfill / core / cli
- [ ] (可选)**PR-C6**:stage1_data_collector 瘦身
- [ ] 每个 PR:生成计划 → Codex 执行 → fixture replay 全绿 → Claude 评审 → 合入(逐个勾选记在上面对应行)

## 批次 D — run 目录契约(§7,2 个 PR)

- [ ] **PR-D1**:原子写(`atomic_write_json`)+ run 目录文件白名单 + `run_dir_audit` 工具(可与 C4 并行,worktree 支线)
- [ ] **PR-D2**:写盘前 contract 校验(hard fail + `--no-validate-output` 逃生门)
- [ ] 合入后首个交易日 live smoke:run 目录文件数 == 白名单数

## 批次 E — 兜底产品化(§8,2–3 个 PR)

- [ ] **PR-E1**:macro `previous_value/change_rate` 从 trend_history/event_history 自动回填(可与 C 并行,worktree 支线)
- [ ] **PR-E2**:`config/manual_fallback_policies.yaml` + manual 模板预填增强
- [ ] **PR-E3**:`reserve_ratio` 错口径源屏蔽 + PBoC provider;`BCOM` 固定 quote provider
- [ ] 验收观察(连续 5 个交易日):macro compare 类 manual = 0;日常手填 ≤ {etf}

## 全局验收(收尾)

- [ ] `scripts/` 全部入口 ≤300 行(stage2/2.5 终态 ≤30 行)
- [ ] run 目录无白名单外文件;无 `.bak`/时间戳副本/`_new` 文件产生
- [ ] `stage2_effective_hit_rate` 不低于重构前 5 日均值 - 5pp
- [ ] 文档同步:`SCRIPTS.md` / `CLAUDE.md` / `AGENTS.md` 与新结构一致
