# 批次 C5:Stage2.5 注入器拆分(收尾)— trend_backfill / entry_mergers / core / cli — 设计文档

> Spec for the 2026-06 refactor, batch C5(REFACTOR_PLAN §6 / TODOS C5)。
> Status: 2026-06-16 设计批准(brainstorming + 4-agent 并行只读分析产出)。前置 PR-C4 已合入 main `a0d182a`(`engines/stage2_5/` 已有 common/schema_coercion/manual_official/fund_flow/gap_sync)。
> 行号采自 main `a0d182a`(C5 worktree 即从此分支),`scripts/stage2_5_injector.py` 实际 3315 行(`cat -n` 口径;PowerShell `Measure-Object` 因无尾换行报 3025)。

## 1. 目的与定位

C5 是 Stage2.5 拆分**收尾**:把注入器剩余执行层下沉到 `engines/stage2_5/` 的 4 个模块,复用并小幅扩展 C4 的 `common.py`。沿用 C1–C4 的 move + re-export(脚本保持可运行;`≤30 行入口瘦身`留 C 批次终态,不在本 PR)。纯机械搬移,**唯一允许的非逐字改动**:被测试 monkeypatch 的跨模块调用改 module-qualified(§4)。

## 2. 范围

**In scope** — 4 新模块(续 `engines/stage2_5/`)+ 扩展 common:

| 模块 | 职责 | 依赖 |
|---|---|---|
| `trend_backfill.py` | trend/event history 计算 + forex/cdb 回填 + 趋势推断 | common(C4)+ gap_sync(C4)+ utils |
| `entry_mergers.py` | macro/monetary/fund_flow/forex/bond/commodity/stock 条目应用与合并 | common + schema_coercion + manual_official + fund_flow + trend_backfill |
| `core.py` | `inject_websearch_data` 编排 + 质量产物 + 非阻塞告警 | common + schema_coercion + fund_flow + gap_sync + entry_mergers + trend_backfill |
| `cli.py` | argparse + `main` 入口 | core + utils.run_lock/run_paths |
| `common.py`(扩展) | **新增** 跨 entry/core 共享报告字段 helper(见 §3 R2) | C4 现状 |

- 主脚本 `scripts/stage2_5_injector.py`:删除上述簇本地定义,改为 re-export(保持 `from scripts.stage2_5_injector import X` / `import ... as injector` 可用)。
- **测试 monkeypatch repoint**(~56 处)+ 跨模块 module-qualified 调用(§4)。
- characterization 扩展 + Stage2.5 contract replay datetime 冻结补 3 模块。

**Out of scope**:不改业务逻辑(除 §4 module-qualify);不并入 utils/coercion;不重算 contract golden;main ≤30 行瘦身留终态。

## 3. 关键修正(4-agent 并行分析发现,spec 据此定正)

**R1 — 不要重搬已在 C4 的 5 个函数**(monolith 已无本地定义,仅 import 自 `common.py`):`_apply_pipeline_quality_state`、`_is_estimated_allowlisted_entry`、`_policy_rules`、`_issue_signature`、`_merge_quality_issues`。从 C5 任何簇清单剔除。

**R2 — 拆 4 模块会产生两处 import 环,按下列归属消解(单向无环)**:
- `_format_source_label`(1016)、`_merge_same_value_report_fields`(1075)、`_update_metadata_only`(1034)+ 常量 `DEFAULT_SOURCE_LABEL`(161)/`SOURCE_ANOMALY_LABEL`(162):被 **entry_mergers + core 双方**调用 → 若放 core 则 entry_mergers→core 与 core→entry_mergers 成环。**归 `common.py`**(双方向下 import)。
- `_infer_trend`(1649)、`_infer_asset_trend`(1671):被 **trend_backfill 的 `_backfill_trend_changes` + entry_mergers 双方**调用 → 若放 entry_mergers 则与 trend_backfill 成环。**归 `trend_backfill.py`**(entry_mergers 单向 import trend_backfill)。
- `_is_suspicious_fund_flow_pair`(1658)、`_build_fund_flow_note`(1725):仅 entry_mergers 用 → 留 entry_mergers。
- `_TREND_CONF_RANK`(2267 常量)、forex `partial` 绑定块(2108–2148):trend_backfill 簇私有 → 随 trend_backfill。

## 4. monkeypatch 契约处理(本 PR 唯一非逐字偏离)

测试 `import scripts.stage2_5_injector as injector` 后 `monkeypatch.setattr(injector, "<fn>", ...)`。caller 移出脚本后,脚本命名空间 patch 不再触达。处理:**(a)** 跨模块调用被 patch 的 helper 改 module-qualified;**(b)** 测试 patch 目标 repoint 到 owning module。

**module-qualified 改动(精确行,a0d182a)**:
- entry_mergers → `trend_backfill.`:`_calc_change_from_trend_history`(2805/2898/2992/3109)、`_calc_daily_change_from_trend_history`(2998/3115)、`_calc_change_from_event_history`(1529)、`_calc_prev_from_event_history`(1277)。
- core(`inject_websearch_data`)→ `trend_backfill.`:`_backfill_trend_changes`(793)、`_run_post_write_trend_backfill`(919)、`_sync_backfill_issues_to_logs`(955)。
- cli(`main`)→ `core.`:`inject_websearch_data`(3293)。`inject_websearch_results` wrapper(965)调 inject 为 intra-core,不改。
- trend_backfill 内部 `_calc_change_from_trend_history`(2333/2381/2456/2506)、`_backfill_trend_changes`(2658/2660)为 intra-module,不改。

**测试 repoint(~56 处)**:`test_websearch_injector.py`(49)、`test_stage25_contract_replay.py`(6,含 L35 autouse `datetime` + 371–375)、`test_daily_writer_locks.py`(3:`parse_args`/`inject_websearch_data`/`DailyRunLock` + `main()` 调用)。`injector.<fn>` → `trend_backfill`/`core`/`cli` owning module(完整映射见 plan)。`test_daily_writer_locks` 还需 `write_from_market_data`(→core)、gap_sync helper(1836–1838→gap_sync)repoint。

> 字符串字面量类(`test_fund_flow_pipeline.py`/`test_manual_template.py`/`test_run_lock.py` 的 `"stage2_5_injector"`、`owner="stage2_5_injector"`)保持不变:cli `main` 保留 `owner="stage2_5_injector"`,错误信息文本含该子串。

## 5. 依赖 DAG(全向下,无环)
```
utils/* + models/* + C4(common[扩展]/schema_coercion/manual_official/fund_flow/gap_sync)
   └─ trend_backfill(+_infer_trend/_infer_asset_trend)
        └─ entry_mergers
             └─ core(inject_websearch_data)
                  └─ cli(main)
```
注入器不 import engines/stage2;plan import-time 冒烟确认无环。

## 6. 敏感区(characterization 加码;非新冻结逻辑)
forex trend backfill(`_should_backfill_forex_*`/`_usable_forex_*`/`_backfill_trend_changes` forex 段)+ entry-writeback(`_apply_*_entry` 调 C4 manual_official/fund_flow gate)。真正 gate/allowlist 逻辑在 C4 未变;C5 搬 caller。

## 7. datetime tie-in
`datetime.now()` 在 trend_backfill(1970/2042/2704)、entry_mergers(2960)、core(326/433);均 `from datetime import datetime`。Stage2.5 contract replay 的 autouse datetime 冻结 fixture 须扩到 `trend_backfill`/`entry_mergers`/`core` 三模块。

## 8. Tests / 安全网
characterization 扩展(before/after value-table + `is` 身份 + import-surface;forex backfill/entry-writeback 加码)+ **Stage2.5 contract replay byte-stable**(canonical;repoint 后必须仍绿,且"trend 读应被跳过"的断言仍有效)+ ~56 repoint 测试全绿 + py_compile/flake8 + import 冒烟。**关键**:repoint 后必须确认 patch 真正触达(否则 contract replay 的"never called"断言会静默失真)。

## 9. 验收
- `engines/stage2_5/{trend_backfill,entry_mergers,core,cli}.py` 存在;common 扩展;主脚本 re-export 全 C5 名为同一对象(`is`)。
- 无 module→主脚本反向 import;无环(import 冒烟过);注入器不 import engines/stage2。
- module-qualified 改动仅限 §4 列出的跨模块 patched-helper 调用;其余 body 逐字。
- 测试 repoint 完成,`pytest -q` 全绿(无回归);contract replay byte-stable;py_compile/flake8 干净。
- 主脚本剩余仅 re-export + 薄 `main` 转发 + `if __name__`;CLI 行为不变。

## 10. 风险与缓解
| 风险 | 缓解 |
|---|---|
| import 环(R2 两处) | §3 归属:共享件下沉 common/trend_backfill;import 冒烟 |
| repoint 漏改 → patch 静默失真(contract replay 假绿) | plan 给完整 ~56 映射;repoint 后专项确认 contract replay "never called" 断言仍触发;`is` 身份 + module-qualified 双保 |
| `_infer_trend`/`_infer_asset_trend` 归属错致环 | R2 定 trend_backfill;F821/import 冒烟兜底 |
| 跨模块未 module-qualify → patch 不达 | §4 精确行;characterization patched-path 用例 |
| datetime 未冻全 → contract replay 漂移 | §7 三模块冻结 |
| 行号漂移 | C5 worktree 从 a0d182a;按函数名 + 逐字 body |
