# PR-C7(C 终态)执行计划:入口瘦身(stage2/2.5 ≤30)+ shim 清理 + 文档同步

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 关闭批次 C 收尾:删 8 个 batch-B shim + 文档同步;`stage2_unified_enhancer.py`(866→≤30)与 `stage2_5_injector.py`(245→≤30)瘦为薄壳——逻辑/名称全在 `engines/stage{2,2_5}/`。

**Architecture:** 纯搬移 + repoint(零业务逻辑改动),唯一逻辑面改动 = 破 cli⇄execution 环(`main()` 内延迟 import `_execute_tasks`)。把 stage2 `main`+10 glue+`CRITICAL_EXTRACT_KEYS` 搬进 `engines/stage2/cli.py`,丢两脚本的 re-export 块,全面 repoint 9 测试文件的 import/属性/monkeypatch(含 utils-alias)。canonical replay/contract harness 的 patch 目标全 repoint 且 **byte-stable 非假绿**。

**Tech Stack:** Python;pytest(replay/contract harness);flake8/py_compile;git worktree;Windows + WSL。

> Spec:`docs/superpowers/specs/2026-06-17-batch-c7-terminal-design.md`(§3.5 fan-out 结论必读)。行号采自 main `0c8f14b`(stage2/2.5 不受 C6 影响;开工从 C6 合入后 HEAD 起,行号一致)。

---

## 有意偏离声明(评审勿误判)
1. **唯一逻辑面改动 = R-cycle 破环**:`main()` 内延迟 import `_execute_tasks`(原为模块顶层名)。其余 main/glue body 逐字。
2. **全面 repoint(import + 属性 + monkeypatch + utils-alias)是 ≤30 的必然代价**(用户选定全 ≤30);映射由 fan-out 三表定死(下附)。
3. **中途 RED 预期**(同 C5):Task 3/4 之间,未 repoint 的 stage2 测试会 RED;用 py_compile/import 冒烟/非 stage2 子集校验,Task 4 后全绿。Codex 勿因预期 RED 停。
4. characterization/golden 不重算;byte-stable 是硬门。

---

## 环境头(零上下文)
- **Bash 工具坏**;命令经 `wsl -e bash -lc '...'`;pytest/flake8/py_compile 走 `run_clean.sh`;只读 git 可用 PowerShell。worktree 根执行。
- worktree:从开工 main HEAD 建 `.worktrees/codex-batch-c7-terminal`(分支 `codex/batch-c7-terminal`);置备 `.env`/`.venv`/`logs`/`reports` + `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1`。
- 硬约束:不重跑 Stage2 真实搜索;不碰当日 `data/runs`/`data/trend_history`;不删 `.run.lock`;全程离线。**绝不 `STAGE2_REPLAY_UPDATE_GOLDEN`**。
- Commit:Conventional;每条工作线一 commit。

---

## 三张映射表(fan-out 勘探;权威)

### 表 A — import-repoint(`from scripts.stage2X import NAME` → engines 模块)
stage2(`datasource.engines.stage2.<mod>`):`_execute_tasks`/`_DeepSeekCircuitBreaker`/`_update_missing_items`→`execution`;`_apply_extraction`/`_augment_extraction_metadata`/`_is_forex_absence_text`/`_has_forex_compare_evidence`→`extraction_apply`;`_candidate_query_quality`/`_expand_query_candidates`→`query_planner`;`_flag_fund_flow_anomalies`/`_validate_fund_flow_extraction`/`_validate_general_extraction`→`validation`;`_is_tavily_quota_error`/`_is_tavily_quota_response`/`_tavily_error_metadata`/`_is_environment_proxy_error`/`_build_environment_proxy_error_records`→`errors`;`_build_stage2_summary_diagnostics`/`_stage2_effective_hit_rate`/`_build_retrieval_diagnostics`/`_build_manual_required_details`/`_build_stage2_result_count_fields`/`_format_stage2_task_count_line`/`_format_stage2_hit_rate_line`/`_post_writeback_manual_reason`/`_mark_post_writeback_manual_required`/`_STAGE2_BACKEND_SUMMARY_KEYS`→`diagnostics`;`_filter_by_official_extract_domain`/`_filter_by_domain`/`_prefer_fresh_snippets`→`snippet_filters`;`_value_evidence_score`→`evidence`;`_safe_number`→`common`;`_build_structured_registry_for_args`/`_parse_args`/`_should_enable_exa_fallback`/`_should_initialize_exa_client`→`cli`。
**移入 cli 的(本 PR 搬)**:`main`/`_compute_derived_metrics`/`_gap_monitor`/`_merge_missing_items`/`_load_json`/`_dump_json`/`_apply_aliases`/`_warn_disable_extract_on_critical_tasks`/`_check_task_completeness`/`_append_gap_monitor`/`_filter_tasks`/`CRITICAL_EXTRACT_KEYS`→`engines.stage2.cli`。
stage2.5(`datasource.engines.stage2_5.<mod>`):`inject_websearch_data`/`inject_websearch_results`/`InjectionSummary`/`_enforce_quality_blockers`/`_collect_gc_non_blocking_warnings`→`core`;`_coerce_float`/`_is_placeholder_numeric`/`_apply_pipeline_quality_state`/`_extract_domain`/`_extract_source_url`/`_iter_url_like_evidence`→`common`;`_apply_*_entry`/`_merge_*_entry`/`_build_*_entry`/`_create_monetary_placeholder`/`_contains_ytd_marker`→`entry_mergers`;`_coerce_stage2_results_to_schema`→`schema_coercion`;`_backfill_*`/`_run_post_write_trend_backfill`/`_sync_backfill_issues_to_logs`/`_should_backfill_forex_daily_change`/`_has_forex_*_change_*`/`_copy_valid_forex_daily_change_evidence`/`_is_forex_daily_change_absence_text`→`trend_backfill`;`_is_missing_item_filled`/`_remove_top_missing_on_skip`/`_rewrite_gap_monitor_after_injection`→`gap_sync`;`_is_manual_official_value`/`_official_domain_matches`→`manual_official`;`main`/`parse_args`→`cli`。

### 表 A' — UTILS-ALIAS(repoint 到 `datasource.utils.*`,非 engines)
- `stage2._FOREX_DAILY_EVIDENCE_MARKERS`→`utils.forex_evidence.STAGE2_FOREX_DAILY_EVIDENCE_MARKERS`;`_FOREX_120D_EVIDENCE_MARKERS`→`...STAGE2_FOREX_120D_EVIDENCE_MARKERS`;`_FOREX_COMPARE_FIELD_EVIDENCE_KEYS`→`utils.forex_evidence.FOREX_COMPARE_FIELD_EVIDENCE_KEYS`;`stage2._append_note`→`utils.note_utils.append_note_text`。
- `stage25.FOREX_DAILY_CHANGE_SOURCE_MARKERS`→`utils.forex_evidence.STAGE25_FOREX_DAILY_CHANGE_SOURCE_MARKERS`;`...120D...`同理;`FOREX_DAILY/120D_CHANGE_EVIDENCE_KEYS`→`utils.forex_evidence`;`stage25._append_note_once`→`utils.note_utils.append_note_once`;`stage25._append_note`→`utils.note_utils.append_note_to_entry`。
- ⚠️ `_append_note` 两侧不同函数,勿混。

### 表 B — monkeypatch / main()-call repoint(仅 stage2 侧需改;stage2.5 侧 C5 已 repoint)
`tests/test_stage2_replay_harness.py`:L514 `stage2`→`stage2_cli`(AsyncTavilyClient)、L517→`stage2_cli`(DeepSeekExtractionAgent)、L520→`stage2_cli`(build_default_registry;L523 已 stage2_cli)、L458/526 `stage2.time`→保 `import time` 的 engines 模块(`execution`)、L557 `asyncio.run(stage2.main())`→`stage2_cli.main()`;`_freeze_stage2_datetime`(365–395):`FixedDatetime` 基类与 `fixed_now` 改自 `stage2_cli.datetime`,冻结循环把 `stage2` 换为 `stage2_cli`(`main`/`_gap_monitor`/`_append_gap_monitor` 的 `datetime.now()` 现读 cli 命名空间)。
`tests/test_stage2_unified.py`:加 `from datasource.engines.stage2 import cli as stage2_cli`;L436 `setattr(stage2,"_execute_tasks",…)`→`stage2_cli`;L459 `asyncio.run(stage2.main())`→`stage2_cli.main()`。
> `monkeypatch.setenv/delenv`(API keys / breaker)位置无关,不改。`stage2._execute_tasks(...)` 直调(replay:462 + test_stage2_unified 多处)用**直接 import** 的 `_execute_tasks`(改 import 自 `engines.stage2.execution`)。

### 表 C — main+glue 搬入 cli.py 的 import header(新增)
(a) stdlib:`asyncio`、`sys`、`from datetime import datetime`(cli 已有 argparse/inspect/json/os/Path/typing/urlparse/logger/httpx/load_dotenv/AsyncExaClient/build_default_registry)。
(b) `datasource.*`(复制脚本现有 import 行):`Stage2TaskPlanner`、`write_quality_metrics`、`build_observability_log`/`write_observability_log`、`run_tasks_lc`(try/except 包装)、`evaluate_policy`/`write_policy_evaluation`/`load_policy_rules`、`build_run_paths_from_reference`、`write_run_snapshot`、`resolve_websearch_results`/`write_source_conflicts`、`normalize_monetary_section`、`sync_top_level_missing_view`、`dump_json`/`load_json_strict`、`AsyncTavilyClient`、`MemoryCache`/`SQLiteCache`、`DeepSeekExtractionAgent`。
(c) sibling(engines.stage2.*):`from .common import _safe_number,_is_force_refresh_task`;`from .snippet_filters import _percentile`;`from .validation import _flag_fund_flow_anomalies`;`from .diagnostics import _build_stage2_result_count_fields,_build_stage2_summary_diagnostics,_format_stage2_hit_rate_line,_format_stage2_task_count_line,_structured_provider_summary_fields,_STAGE2_BACKEND_SUMMARY_KEYS`。**`_execute_tasks` 不在顶层 import——main 内延迟 import 破环**。

---

## Task 0 — worktree + baseline
```bash
wsl -e bash -lc 'MAIN=/mnt/d/cursor/datasource; WT="$MAIN/.worktrees/codex-batch-c7-terminal"; cd "$MAIN" && git fetch && git worktree add "$WT" -b codex/batch-c7-terminal main && cp "$MAIN/.env" "$WT/.env" && mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv" && cd "$WT" && DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -m pytest -q 2>&1 | tail -5 && wc -l scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py && bash run_clean.sh python scripts/stage2_unified_enhancer.py --help > /tmp/c7_s2_help.txt 2>&1; bash run_clean.sh python scripts/stage2_5_injector.py --help > /tmp/c7_s25_help.txt 2>&1; echo done'
```
Expected:全绿(记 baseline N);行数 866/245;两 `--help` 存盘。失败 → 停-回报。

## Task 1 — shim 删除 + 活引用 repoint + 文档同步
- [ ] **Step 1** 逐个 shim:确认是 `runpy` 转发器并查其 tools/ 新名(`rg -n "tools / |run_path" scripts/<name>.py`);grep 活引用 `rg -n "scripts/<name>|scripts\.<name>|<name>\.py" tests/ src/ *.md docs/ README.md SCRIPTS.md AGENTS.md CLAUDE.md`。
- [ ] **Step 2** repoint 活引用到 `scripts/tools/<新名>`:已知 `tests/test_sanitize_market_data.py` L6 → `scripts/tools/market_data_sanitize.py`(spec 名);其余按 grep 实测改。
- [ ] **Step 3** 删 8 个 shim:`scripts/{trend_history_backfill,trend_history_scan,sanitize_market_data,compare_stage2_runs,stage2_health_check,stage2_low_score_audit,setup_stage2_search_env,run_snapshot}.py`。
- [ ] **Step 4** 文档同步:`CLAUDE.md`/`AGENTS.md`/`SCRIPTS.md`/`README.md` 模块映射(Stage1→`engines/stage1/`、Stage2→`engines/stage2/`、Stage2.5→`engines/stage2_5/`)+ 命令路径(诊断工具等指 `scripts/tools/`)同步。
- [ ] **Step 5** 校验:`rg "scripts/(trend_history_backfill|trend_history_scan|sanitize_market_data|compare_stage2_runs|stage2_health_check|stage2_low_score_audit|setup_stage2_search_env|run_snapshot)\.py" tests/ src/ . -g'!optimization/archive/**'` 无活引用残留;`pytest tests/test_sanitize_market_data.py tests/test_manual_template.py tests/test_stage4_docs.py -q` 绿。commit `refactor: drop batch-B path shims + sync docs to engines/stage{1,2,2_5} (PR-C7)`。

## Task 2 — stage2.5 入口 ≤30
- [ ] **Step 1** `stage2_5_injector.py`:删 C4/C5 re-export 块,保留/收为薄壳:`from datasource.engines.stage2_5.cli import main` + `if __name__ == "__main__": asyncio.run(main())`(+ 必要 `import asyncio`)。目标 ≤30 行。
- [ ] **Step 2** repoint 4 个 stage2.5 测试文件的 `from scripts.stage2_5_injector import NAME`/`import as injector|stage25|stage2_5` 属性访问 → 表 A(stage2.5 段)+ 表 A'(stage25 utils-alias)。`test_daily_writer_locks`/`test_stage25_contract_replay`/`test_websearch_injector` 的 setattr/main 调用 C5 已 repoint(核对仍指 engines)。
- [ ] **Step 3** 校验:`py_compile` + `flake8 src/` + `pytest tests/test_websearch_injector.py tests/test_stage25_contract_replay.py tests/test_daily_writer_locks.py tests/test_forex_evidence_characterization.py -q`(contract replay byte-stable、非假绿)。commit `refactor: thin stage2_5 injector entry to <=30 lines; repoint imports (PR-C7)`。

## Task 3 — stage2:搬 main+glue+CONST 进 cli + 破环
- [ ] **Step 1** `engines/stage2/cli.py`:加表 C 的 import header;**逐字搬入** `main`(485–972)+ 10 glue(285–479,见 spec/表)+ `CRITICAL_EXTRACT_KEYS`(272–282)。
- [ ] **Step 2** **破环**:把 main 体内对 `_execute_tasks` 的两处调用前置一行 `from datasource.engines.stage2.execution import _execute_tasks`(置于 main 函数体顶部,延迟 import);不在 cli 顶层 import execution。
- [ ] **Step 3** import-time 冒烟:`bash run_clean.sh python -c "import datasource.engines.stage2.cli; import datasource.engines.stage2.execution; print('NOCYCLE-OK')"`。Expected `NOCYCLE-OK`。成环 → 停-回报。
- [ ] **Step 4** py_compile + `flake8 src/datasource/engines/stage2/cli.py`(继承长行可 per-file-ignore E501,F401/F821 仍检)。commit `refactor: move stage2 main+glue into engines/stage2/cli; break cli<->execution cycle (PR-C7)`。
> ⚠️ 此后 stage2 脚本仍有 main/glue 副本?**不**——Step 1 是"搬"(从脚本删原定义)。脚本此时缺 main → Task 4 收尾薄壳。中途 stage2 测试 RED 预期。

## Task 4 — stage2:丢 re-export + 薄壳 + 全面 repoint + replay harness
- [ ] **Step 1** `stage2_unified_enhancer.py` 删 C1/C2/C3 re-export 块(34–200)+ 残余,收为薄壳:`from datasource.engines.stage2.cli import main` + `if __name__: asyncio.run(main())`(+ `import asyncio`)。目标 ≤30 行。
- [ ] **Step 2** repoint 5 个 stage2 测试文件的 import + 属性访问 → 表 A(stage2 段)+ 表 A'(stage2 utils-alias):`test_stage2_unified`/`test_stage2_fallbacks`/`test_stage2_structured_integration`/`test_stage2_structured_golden`/`test_stage2_replay_harness`/`test_forex_evidence_characterization`(stage2 侧)。`import scripts.stage2_unified_enhancer as stage2` + `stage2.X` 改为从对应 engines/utils 模块直接 import(并改调用点)。
- [ ] **Step 3** **replay harness repoint(表 B)**:`test_stage2_replay_harness.py` 按表 B 改 `stage2.*`→`stage2_cli.*`、`stage2.main()`→`stage2_cli.main()`、`_freeze_stage2_datetime` 基类/循环改 `stage2_cli`、`stage2.time`→`execution`;`test_stage2_unified.py` 加 `stage2_cli` import、L436/459 repoint。
- [ ] **Step 4** 校验(关键):`bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py tests/test_stage2_unified.py tests/test_stage2_fallbacks.py tests/test_stage2_structured_integration.py tests/test_stage2_structured_golden.py tests/test_forex_evidence_characterization.py -q`。**replay byte-stable 且非假绿**(四链路/extract-count/outcome 断言仍触发);**绝不** `STAGE2_REPLAY_UPDATE_GOLDEN`。golden mismatch/假绿 → 停-回报。commit `refactor: thin stage2 enhancer entry to <=30 lines; repoint imports+monkeypatches+utils-aliases (PR-C7)`。

## Task 5 — 全量验收
- [ ] `bash run_clean.sh python -m pytest -q`(= baseline N,无回归)+ `py_compile src/datasource/engines/stage2/*.py scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py` + `flake8 src/datasource/engines/stage2/`。
- [ ] 两 `--help` diff:`diff /tmp/c7_s2_help.txt <(bash run_clean.sh python scripts/stage2_unified_enhancer.py --help 2>&1)` 空;stage2.5 同理。
- [ ] 行数:`wc -l scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py` 均 **≤30**。
- [ ] 残留:`rg "^async def main|^def _load_json|^def _gap_monitor|noqa: F401 \(C[123] re-export\)" scripts/stage2_unified_enhancer.py || echo "NO-LOCAL/NO-REEXPORT (OK)"`;import 冒烟 `python -c "import scripts.stage2_unified_enhancer; import scripts.stage2_5_injector; import datasource.engines.stage2.cli; print('OK')"`。
- [ ] commit `test: assert C7 entries thinned + repointed (replay byte-stable, no cycle)`。失败 → 停-回报。

## Task 6 — 文档 TODOS + 隔离 + 回报
- [ ] TODOS.md 勾全局验收"入口 ≤300/stage2-2.5 ≤30"+"文档同步"+"8 shim 删除";commit `docs: mark C terminal (entry slim + shim cleanup + doc sync) complete`。
- [ ] 隔离断言 + 回报:commit 列表、全量 passed、两脚本行数、8 shim 删净、replay/contract byte-stable 非假绿、cli⇄execution 破环确认(NOCYCLE-OK)、import/属性/monkeypatch/utils-alias repoint 完成、计划外改动(理想仅 flake8/延迟-import)。

---

## 评审 checklist
1. 唯一逻辑改动 = main 内延迟 import `_execute_tasks`(破环);main/glue/CONST body 逐字;无其它 body 漂移。
2. 两脚本 ≤30 行、无 re-export 块、无本地 main/glue;`--help` diff 空。
3. **replay/contract byte-stable 且非假绿**(patch 经 `stage2_cli`/engines 命名空间真正触达;四链路/never-called 断言仍触发)。
4. 表 A/A'/B repoint 完整:9 文件 import/属性/monkeypatch/utils-alias 全部指 engines/utils;`_append_note` 两侧分别正确;无残留 `scripts.stage2X` 名引用。
5. cli⇄execution 无环(import 冒烟);8 shim 删净无活引用残留;文档映射/命令路径与新结构一致。
6. 合入:squash;`git diff main 分支` 空;清 worktree/分支;批次 C 收官。

## Self-Review
- Spec 覆盖:§2 四线 → Task 1–4;§3.5 R-cycle/R-utils-alias/表 A/B/C → Task 1–4 内联;§6 安全网 → Task 4/5;§8 验收 → Task 5/6。✅
- Placeholder:无 TBD;三表内联为权威;repoint 规则化 + grep 兜底;commit 文案全给。✅
- 一致性:worktree `.worktrees/codex-batch-c7-terminal`/分支名;表 A/A'/B/C 与 fan-out 一致;`_append_note` 冲突显式;中途 RED 声明。✅
- 风险:R-cycle 破环 + replay 非假绿 + utils-alias 两侧分指 + 中途 RED 预期,均显式。✅
