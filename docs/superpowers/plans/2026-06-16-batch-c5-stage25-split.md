# PR-C5 执行计划:Stage2.5 注入器拆分(收尾)— trend_backfill / entry_mergers / core / cli

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** 把 `scripts/stage2_5_injector.py`(3315 行)剩余执行层拆到 `engines/stage2_5/` 的 4 个模块(复用并扩展 C4 common),主脚本 re-export 保持入口与现有 import 可用;同步处理 ~56 处测试 monkeypatch repoint。

**Architecture:** 纯逐字搬移,**唯一非逐字偏离**=被测试 monkeypatch 的跨模块调用改 module-qualified(§module-qualify 清单)。依赖序 common(扩展)→ trend_backfill → entry_mergers → core → cli。`inject_websearch_data` 整块搬入 core(不拆内部)。**因 caller 全部移出脚本,patched-path 测试在搬移中途会 RED,直到 Task 7 统一 repoint 后才全绿**(见执行序说明)。

**Tech Stack:** Python;pytest(含 Stage2.5 contract replay);flake8/py_compile;git worktree;Windows + WSL。

> Spec:`docs/superpowers/specs/2026-06-16-batch-c5-stage25-split-design.md`。行号采自 main `a0d182a`(C5 worktree 即从此分支,行号当前有效)。
> **本计划的模块归属/行号/repoint 映射来自 4 个只读分析 agent 的并行勘探**(已完成);执行为**单序列**(搬移共享同一 monolith + 依赖序,不可并行)。

---

## 规划方有意偏离(评审勿误判)

1. **函数体未内联**(沿用 C1–C4):逐字搬移,正确性由 characterization + `is` 身份 + contract replay byte-stable + py_compile/flake8 保证。
2. **唯一逻辑面改动 = module-qualified 跨模块调用**(§module-qualify):被 test patch 的 helper 跨模块调用从 bare 改 `module.fn(...)`,使单一 patch 目标可达。其余 body 逐字。
3. **patched-path 测试中途 RED 是预期**:caller 移出脚本后,`monkeypatch.setattr(injector, …)` 暂不可达,直到 Task 7 统一 repoint。中途用 py_compile/flake8/import 冒烟/`is` 身份 + 非 monkeypatch 子集校验;全量绿在 Task 7 后。**Codex 遇到这些 RED 不要停-回报**(下列已声明),其它 RED 才停。
4. **R1/R2 修正已并入**(见下);common 成员/边缘归属仍以 flake8 F821 收敛。

---

## 统一环境头(零上下文)

- **Bash 工具损坏**;命令经 `wsl -e bash -lc '...'`;pytest/flake8/py_compile 走 `run_clean.sh`。worktree 根执行。
- baseline:从 main `a0d182a` 建 worktree `.worktrees/codex-batch-c5-stage25-split`(分支 `codex/batch-c5-stage25-split`);置备 `.env`/`.venv`/`logs`/`reports`;`DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1`。
- 硬约束:不重跑 Stage2 真实搜索;不碰当日 `data/runs`/`data/trend_history`;不删 `.run.lock`;全程离线。
- 冻结:不并入 utils/coercion;不重算 contract golden;main ≤30 行瘦身留终态;C4/C1–C3 模块逻辑不动。
- Commit:Conventional;小步频提。

---

## R1 / R2(必须遵守)

**R1 不要搬这 5 个**(已在 C4 `common.py`,monolith 仅 import):`_apply_pipeline_quality_state`、`_is_estimated_allowlisted_entry`、`_policy_rules`、`_issue_signature`、`_merge_quality_issues`。

**R2 防环归属**:
- → **common.py**(扩展):`_format_source_label`(1016)、`_update_metadata_only`(1034)、`_merge_same_value_report_fields`(1075)+ 常量 `DEFAULT_SOURCE_LABEL`(161)、`SOURCE_ANOMALY_LABEL`(162)。
- → **trend_backfill.py**:`_infer_trend`(1649)、`_infer_asset_trend`(1671)(+簇私有 `_TREND_CONF_RANK` 2267、forex `partial` 块 2108–2148)。
- 留 entry_mergers:`_is_suspicious_fund_flow_pair`(1658)、`_build_fund_flow_note`(1725)。

---

## 搬移簇清单(权威;行号 = a0d182a)

**common.py 扩展**:逐字搬入 R2 的 3 函数 + 2 常量(从 monolith 1016/1034/1075/161/162)。主脚本删原定义 + 从 common re-import。

**trend_backfill.py**:`_parse_date`(1748)、`_load_series_records`(1763)、`_calc_change_from_trend_history`(1802)、`_calc_daily_change_from_trend_history`(1888)、`_load_event_history`(1937)、`_calc_change_from_event_history`(1949)、`_calc_prev_from_event_history`(2010)、`_should_backfill_numeric`(2099)、forex `partial` 块(2108–2148)、`_is_zero_change_value`(2151)、`_should_backfill_forex_daily_change`(2156)、`_should_backfill_forex_120d_change`(2165)、`_usable_forex_change_value`(2174)、`_is_zero_derived_forex_trend`(2185)、`_usable_forex_raw_trend`(2199)、`_backfill_cdb_proxy_changes_from_cn10y`(2205)、`_remove_note_markers`(2244)、`_record_backfill_issue`(2254)、`_TREND_CONF_RANK`(2267)、`_merge_trend_confidence`(2274)、`_derive_trend_confidence`(2283)、`_backfill_trend_changes`(2306)、`_run_post_write_trend_backfill`(2647)、`_sync_backfill_issues_to_logs`(2671)、**+R2** `_infer_trend`(1649)、`_infer_asset_trend`(1671)。
- import:stdlib(json/re/`functools.partial`/`datetime,timedelta`/Path/typing)+ 外部(`trend_history_store`:DEFAULT_BASE_DIR/SERIES_WINDOWS;`fund_flow_series`:apply_override/compute_rollup/load_daily_series;`run_paths`;`forex_evidence` 族;`note_utils` 别名)+ `from ...common import _coerce_float,_calc_change_rate_pct,_has_valid_value,_apply_pipeline_quality_state,_merge_quality_issues`(按 F821)+ `from ...gap_sync import _refresh_stage2_gap_monitor,_refresh_stage2_notes,_cleanup_metadata_missing,_rewrite_gap_monitor_after_injection`。

**entry_mergers.py**:`_apply_macro_entry`(1145)、`_create_monetary_placeholder`(1349)、`_create_macro_placeholder`(1369)、`_apply_monetary_entry`(1392)、`_apply_fund_flow_entry`(1572)、`_is_suspicious_fund_flow_pair`(1658)、`_build_fund_flow_note`(1725)、`_merge_stock_index_entry`(2726)、`_build_stock_index_entry`(2752)、`_merge_bond_entry`(2779)、`_merge_commodity_entry`(2859)、`_merge_forex_entry`(2970)、`_build_forex_entry`(3092)。
- import:stdlib(`datetime`/Path/`typing.Any,Dict,Optional`)+ 外部(`FundFlowData`、DEFAULT_BASE_DIR)+ `from ...common import _coerce_float,_coerce_bool,_coerce_percent,_is_placeholder_numeric,_same_numeric_value,_has_valid_value,_calc_change_rate_pct,_calc_previous_from_change_rate_pct,_pct_change,_format_source_label,_merge_same_value_report_fields,_update_metadata_only,DEFAULT_SOURCE_LABEL,SOURCE_ANOMALY_LABEL,_contains_ytd_marker`(按 F821)+ `from ...schema_coercion import _copy_source_url,_copy_payload_metadata_fields` + `from ...manual_official import _has_rrr_type_conflict,_normalize_rrr_type,_is_trusted_monetary_manual_quality_override,_should_preserve_existing_official_source,_apply_manual_official_estimation_rule` + `from ...fund_flow import _normalize_source_tier,_default_fund_flow_metric_basis,_infer_fund_flow_source_tier,_infer_fund_flow_window_evidence,_normalize_fund_flow_estimation` + `from datasource.engines.stage2_5 import trend_backfill`(module import,供 module-qualified)+ 从 trend_backfill import 非 patched 的 `_infer_trend,_infer_asset_trend,_usable_forex_change_value,_usable_forex_raw_trend,_merge_trend_confidence,_derive_trend_confidence,_copy_valid_forex_daily_change_evidence,_copy_valid_forex_120d_change_evidence`(按 F821)。
- **InjectionSummary 类型注解**:`summary: Optional[InjectionSummary]` 出现在 1/4/5 → `from ...core import InjectionSummary` 会成环。改为 `from __future__ import annotations` + 字符串注解,或 `InjectionSummary` 也下沉 common。**首选**:entry_mergers 顶 `from __future__ import annotations`,注解保持 `Optional[InjectionSummary]` 但延迟求值,并 `from ...core import InjectionSummary` 仅在 `TYPE_CHECKING` 块——避免运行时环。(plan 执行时按 F821/import 冒烟确认。)

**core.py**:`InjectionSummary`(164 dataclass)、`_append_non_blocking_warning`(236)、`_collect_gc_non_blocking_warnings`(261)、`_derive_date_compact`(318)、`_enforce_quality_blockers`(329)、`_write_unified_quality_artifacts`(423)、`_cleanup_monetary_aliases`(464)、`inject_websearch_data`(483)、`inject_websearch_results`(964)、`_post_injection_validation`(968)。
- import:stdlib(json/`datetime`/Path/`dataclasses`/typing)+ 外部(`trend_history_store`:write_from_market_data/write_trend_history_gap_snapshot/DEFAULT_BASE_DIR;`quality_metrics.build_quality_metrics`;`key_aliases.normalize_monetary_section`+MONETARY_KEY_MAP;`policy_rules.get_non_blocking_warning_rules`;`run_paths`)+ `from ...common import _apply_pipeline_quality_state,_is_estimated_allowlisted_entry,_policy_rules,_has_valid_value,_coerce_float,_extract_domain,_attach_source_url` + `from ...gap_sync import _append_missing_item,_remove_missing_item,_remove_top_missing,_remove_top_missing_on_skip,_cleanup_metadata_missing,_refresh_stage2_gap_monitor,_refresh_stage2_notes,_collect_missing_source_urls` + `from ...schema_coercion import _coerce_stage2_results_to_schema,_normalize_keyed_list,_normalize_monetary_payload` + `from ...fund_flow import _normalize_fund_flow_payload` + `from datasource.engines.stage2_5 import entry_mergers, trend_backfill`(module import,供 inject 调 entry_mergers.* 与 module-qualified trend_backfill.*)。

**cli.py**:`_default_cli_paths`(3174)、`parse_args`(3183)、`main`(3264)、`if __name__`(3313)。
- import:stdlib(argparse/sys/Path)+ `from ...run_lock import DailyRunLock,run_dir_from_artifact` + `from ...run_paths import build_run_paths_from_reference` + `from datasource.engines.stage2_5 import core`(供 `core.inject_websearch_data`)。`main` 保留 `owner="stage2_5_injector"`。

> **不搬/留主脚本**:仅 re-export 段 + 薄 `main` 转发(`from ...cli import main`)+ `if __name__=="__main__": main()`。

---

## module-qualify 清单(本 PR 唯一逻辑面改动;精确行 a0d182a)

搬移后将这些**跨模块**调用从 bare 改 `<module>.<fn>(...)`:
- entry_mergers 体内 → `trend_backfill.`:`_calc_change_from_trend_history`(2805/2898/2992/3109)、`_calc_daily_change_from_trend_history`(2998/3115)、`_calc_change_from_event_history`(1529)、`_calc_prev_from_event_history`(1277)。
- core `inject_websearch_data` 体内 → `trend_backfill.`:`_backfill_trend_changes`(793)、`_run_post_write_trend_backfill`(919)、`_sync_backfill_issues_to_logs`(955)。
- cli `main` 体内 → `core.`:`inject_websearch_data`(3293)。
- **不改(intra-module)**:trend_backfill 内 `_calc_change_from_trend_history`(2333/2381/2456/2506)/`_backfill_trend_changes`(2658/2660);core 内 `inject_websearch_results`→inject(965)。

---

## 测试 monkeypatch repoint 规则(Task 7;~56 处)

测试文件加 `from datasource.engines.stage2_5 import trend_backfill, core, cli, gap_sync`;把 `monkeypatch.setattr(injector|stage2_5, "X", ...)` 的目标按 owning module 改:

| 符号 | 新目标模块 |
|---|---|
| `_calc_change_from_trend_history`、`_calc_daily_change_from_trend_history`、`_calc_change_from_event_history`、`_calc_prev_from_event_history`、`_backfill_trend_changes`、`_run_post_write_trend_backfill`、`_backfill_cdb_proxy_changes_from_cn10y`、`_sync_backfill_issues_to_logs` | `trend_backfill` |
| `inject_websearch_data`、`inject_websearch_results`、`_enforce_quality_blockers`、`write_from_market_data` | `core` |
| `parse_args`、`DailyRunLock` | `cli` |
| `_refresh_stage2_gap_monitor`、`_refresh_stage2_notes`、`_cleanup_metadata_missing` | `gap_sync`(C4) |
| autouse `datetime`(`test_stage25_contract_replay.py:35`) | 冻结扩到 `trend_backfill`+`entry_mergers`+`core`(三模块都 setattr `datetime`) |

涉及文件:`test_websearch_injector.py`(~49)、`test_stage25_contract_replay.py`(L35 + 371–375)、`test_daily_writer_locks.py`(80/94/100 + `stage2_5.main()` 保持可调,因 main 经脚本 re-export)。**完整逐行清单见 4-agent 分析(grep `setattr(injector`/`setattr(stage2_5` 校验)**。
> 字面量类不动:`test_fund_flow_pipeline.py`/`test_manual_template.py`/`test_run_lock.py` 的 `"stage2_5_injector"` 字符串、`owner="stage2_5_injector"`。

---

## 执行序(关键:moves 先,repoint 后)

Task 0 置备 → Task 1 characterization(锁现行为)→ **Task 2–6 顺序搬移(common→trend_backfill→entry_mergers→core→cli)+ module-qualify** → **Task 7 统一 repoint 测试 + datetime 冻结扩展** → Task 8 切新模块 `is` 身份 + 全量 → Task 9 文档/隔离/回报。

> ⚠️ **Task 4 起,`test_websearch_injector.py`/`test_stage25_contract_replay.py`/`test_daily_writer_locks.py` 中 patch trend/inject 的用例会 RED**(caller 已 module-qualified,patch 还在 injector 命名空间)。**这是预期**;Task 2–6 用 py_compile + flake8 + import 冒烟 + characterization `is` 身份 + 不 patch 这些 helper 的测试子集校验。Task 7 repoint 后全量必须绿。

---

## Task 0 — worktree + baseline
```bash
wsl -e bash -lc 'MAIN=/mnt/d/cursor/datasource; WT="$MAIN/.worktrees/codex-batch-c5-stage25-split"; cd "$MAIN" && git fetch && git worktree add "$WT" -b codex/batch-c5-stage25-split a0d182a && cp "$MAIN/.env" "$WT/.env" && mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv" && cd "$WT" && DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -m pytest -q 2>&1 | tail -5'
```
Expected:全绿(记 baseline N);失败 → 停-回报。

## Task 1 — characterization(先写,锁现行为)
- [ ] 新建 `tests/test_stage25_c5_split_characterization.py`:import-surface(全 C5 moved 名,见簇清单)+ value-table(common 扩展件 + trend_backfill `_calc_*`/`_backfill_trend_changes` 形状 + entry `_merge_*`/`_apply_*` 关键写回 + **forex backfill/entry-writeback 加码**);expected 由 Codex 实跑现函数取真。
- [ ] 跑绿 + commit `test: add C5 stage2.5 split characterization`。

## Task 2 — 扩展 common.py(R2 共享件)
- [ ] common.py 逐字搬入 `_format_source_label`/`_update_metadata_only`/`_merge_same_value_report_fields` + `DEFAULT_SOURCE_LABEL`/`SOURCE_ANOMALY_LABEL`(补对应 import)。主脚本删原定义 + 从 common re-import。
- [ ] py_compile + flake8 + characterization + contract replay 绿 → commit `refactor: move shared report-field helpers to stage2_5 common (PR-C5)`。

## Task 3 — trend_backfill.py(含 R2 `_infer_trend`/`_infer_asset_trend`)
- [ ] 建模块逐字搬入(见簇清单)+ import header。主脚本删原定义 + re-import(全名)。
- [ ] py_compile + flake8 + import 冒烟 + characterization `is` 身份(部分)。**此时 entry_mergers 仍在主脚本**,patch trend 的测试仍走主脚本绿——可跑 `test_websearch_injector.py` 确认仍绿(若已 RED 说明 re-import 漏名)。
- [ ] commit `refactor: extract stage2.5 trend_backfill module (PR-C5)`。

## Task 4 — entry_mergers.py(+ module-qualify trend 调用)
- [ ] 建模块逐字搬入 + import header;**按 §module-qualify 把 1277/1529/2805/2898/2992/2998/3109/3115 改 `trend_backfill.`**。主脚本删原定义 + re-import。
- [ ] py_compile + flake8 + import 冒烟 + characterization `is` 身份。**预期**:patch `_calc_*` 的 websearch/contract 用例此后 RED(Task 7 修);其余绿。
- [ ] commit `refactor: extract stage2.5 entry_mergers module; module-qualify trend calls (PR-C5)`。

## Task 5 — core.py(+ module-qualify 793/919/955)
- [ ] 建模块逐字搬入 + import header(`entry_mergers`/`trend_backfill` 用 module import);**inject 体内 793/919/955 改 `trend_backfill.`**。主脚本删原定义 + re-import。
- [ ] py_compile + flake8 + import 冒烟 + `is` 身份。
- [ ] commit `refactor: extract stage2.5 core orchestrator module (PR-C5)`。

## Task 6 — cli.py(+ module-qualify 3293)+ 主脚本瘦为入口
- [ ] 建 cli.py 逐字搬入 `_default_cli_paths`/`parse_args`/`main`/`if __name__`;**main 内 3293 改 `core.inject_websearch_data(...)`**;保留 `owner="stage2_5_injector"`。主脚本删原定义 + `from ...cli import main` re-export + 保留 `if __name__=="__main__": main()`。
- [ ] py_compile + flake8 + import 冒烟(`python -c "import scripts.stage2_5_injector; import datasource.engines.stage2.extraction_apply; print('OK')"` 无环)。
- [ ] commit `refactor: extract stage2.5 cli module (PR-C5)`。

## Task 7 — 测试 monkeypatch repoint + datetime 冻结扩展(全量转绿)
- [ ] 按 §repoint 规则改全部 `setattr(injector|stage2_5, X, ...)` 目标;给三测试文件加 `from datasource.engines.stage2_5 import trend_backfill, core, cli, gap_sync`;`test_stage25_contract_replay.py` autouse datetime 冻结扩到 trend_backfill+entry_mergers+core。
- [ ] 跑 `test_websearch_injector.py test_stage25_contract_replay.py test_daily_writer_locks.py -q` → 全绿。**专项确认**:contract replay 的"trend 读应被跳过/never called"断言仍触发(`_fail_trend_read` 仍生效)——若假绿(patch 未达)→ 停-回报。
- [ ] commit `test: repoint stage2.5 monkeypatches to split modules (PR-C5)`。

## Task 8 — 切新模块 `is` 身份 + 全量验收
- [ ] characterization 追加新模块直连 + `is` 身份(`INJ._inject... is core...` 等;trend/entry/cli 代表)+ cross-module-qualify 生效断言(patch `trend_backfill._calc_change_from_trend_history` 后经 `_merge_forex_entry` 可达)。
- [ ] 全量:`bash run_clean.sh python -m pytest -q`(= baseline + 新 characterization;无回归)+ `py_compile src/datasource/engines/stage2_5/*.py scripts/stage2_5_injector.py` + `flake8 src/datasource/engines/stage2_5/` + 残留校验(`rg "^def inject_websearch_data|^def _backfill_trend_changes|^def _apply_macro_entry|^def main" scripts/stage2_5_injector.py` → 仅可能命中薄 main 转发;`inject_websearch_data` 等应 NO-LOCAL-DEF)。
- [ ] contract replay byte-stable。失败 → 停-回报。commit `test: assert C5 split modules behave identically (is-identity + qualified-patch reach)`。

## Task 9 — 文档 + 隔离 + 回报
- [ ] TODOS.md C5 `[x]`,"当前焦点"→ 全局验收/终态(main ≤30 行瘦身);commit `docs: mark PR-C5 complete in refactor TODOS`。
- [ ] `pytest tests/test_manual_template.py tests/test_stage4_docs.py -q`(命令漂移)。
- [ ] 隔离断言 + 回报:commit 列表、全量 passed、主脚本行数(3315→?)、6 模块依赖图无环、module-qualify 与 repoint 清单、contract replay byte-stable + "never called" 断言仍触发确认、R1/R2 落实确认、计划外改动(理想仅 flake8/F821)。

---

## 评审方 checklist
1. R1 五函数未被重搬;R2 归属(common/trend_backfill)落实、无环(import 冒烟过)。
2. 冻结区 body 逐字(diff 只见位置 + import + §module-qualify 列出的有限 call-site);module-qualify 仅限清单 8+3+1 处。
3. repoint:~56 处目标正确;**contract replay "never called" 断言仍触发**(非假绿);`is` 身份 + qualified-patch-reach 断言通过。
4. 依赖 DAG 单向(common→trend_backfill→entry_mergers→core→cli);注入器不 import engines/stage2;无 module→主脚本反向。
5. 主脚本剩 re-export + 薄 main + `if __name__`;CLI 行为不变;contract replay byte-stable;全量无回归。
6. 合入:squash;`git diff main 分支` 空;清 worktree/分支;C 批次进入终态(main ≤30 行瘦身 + 全局验收)。

## Self-Review
- Spec 覆盖:§2 四模块 → Task 3–6;R1/R2 → Task 2/3 + 簇清单;§4 module-qualify → Task 4/5/6 + 清单;repoint → Task 7;datetime → Task 7;§8/§9 验收 → Task 8/9。✅
- Placeholder:无 TBD;value-table 由 Codex 实跑;repoint 规则化 + 4-agent 逐行兜底;module-qualify 精确行。✅
- 一致性:模块名/归属/行号/repoint 映射与 spec + 4-agent 分析一致;依赖序一致;worktree/分支名一致。✅
- 关键风险显式:中途 RED 声明、contract replay 假绿防护、两处防环归属、datetime 三模块冻结。✅
