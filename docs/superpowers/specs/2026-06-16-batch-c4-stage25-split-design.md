# 批次 C4:Stage2.5 注入器拆分 — common / schema_coercion / manual_official / fund_flow / gap_sync — 设计文档

> Spec for the 2026-06 refactor, batch C4(REFACTOR_PLAN §6 / TODOS C4)。
> Status: 2026-06-16 设计批准(brainstorming 产出)。前置 PR-C3 已 fast-forward 合入并推送 main `3fa900b`。
> 起点:从开工时 main HEAD 现生成 per-PR plan(行号采自 main `3fa900b`,搬移按函数名 + 逐字 body,不靠绝对行号 retype)。
> 这是 Stage2.5 拆分的**第一半**;C5 接手 entry_mergers / trend_backfill / core / cli。

## 1. 目的与定位

`scripts/stage2_5_injector.py`(4211 行,~120 函数)是 Stage2.5 主入口巨石。C4 把其中**低层、内聚**的 4 个簇下沉到新包 `src/datasource/engines/stage2_5/`(与 `engines/stage2/` 平行),并建一个 `common` 底座消除反向 import。编排器 `inject_websearch_data` 与 entry-mergers/trend-backfill/cli 留主脚本,由 C5 接手。

C4 额外交付:**回收 C2 遗留的 `# C4-cleanup`** —— Stage2 的 `extraction_apply.py` 当前跨脚本 `from (scripts.)stage2_5_injector import` 4 个 fund_flow helper;C4 把这 4 个 helper 搬到 `engines/stage2_5/fund_flow.py`,`extraction_apply` 改从该 src 模块 import 并删除跨脚本 fallback 与 `# C4-cleanup` 注释。

本 PR 是机械拆分,不是行为优化:schema coercion、official manual override allowlist、fund_flow gate、gap/missing-items 同步语义逐字保留。

## 2. 范围

**In scope** — 新包 `engines/stage2_5/` + 5 文件(common 底座 + 4 命名簇):

| 新模块 | 职责 | 冻结区 | 主要依赖 |
|---|---|---|---|
| `common.py`(底座) | 跨簇低层:numeric coerce / url-evidence / domain helpers | — | 外部 utils + stdlib(向下) |
| `schema_coercion.py` | Stage2 results → schema 强转 + payload 归一化 | — | common |
| `manual_official.py` | 官方 URL 证据校验 + manual override allowlist 应用 | **official override allowlist(mlf/USDCNY/BCOM)** | common + utils/source_trust |
| `fund_flow.py` | fund_flow gate/归一化/source-tier/window-evidence(**含 4 个 reclaim helper**) | **fund_flow gate** | common |
| `gap_sync.py` | gap_monitor + missing_items 同步 | — | common + utils/missing_items |

- 新包 `src/datasource/engines/stage2_5/__init__.py`(docstring)。
- 主脚本删除上述簇本地定义,改为从新模块**显式 re-import `_私有名`**(call-site 零改;现有 `scripts.stage2_5_injector` import 路径保持可用)。
- `extraction_apply.py`(Stage2/C2)repoint 到 `engines.stage2_5.fund_flow`,删 `# C4-cleanup`。
- characterization 新增(先行,见 §7),冻结簇加码。
- TODOS.md C4 状态 + 文档同步检查。

**Out of scope(本 PR 不做)**

- 任何函数体逻辑改动:纯搬移,body 逐字不变(含注释、局部名、空行)。
- C5 簇:`inject_websearch_data` 编排器、`_apply_*_entry`/`_merge_*_entry`/`_build_*_entry`(entry_mergers)、`_calc_change_from_*`/`_backfill_*`/`_run_post_write_trend_backfill`(trend_backfill)、`parse_args`/`main`/`_default_cli_paths`(cli)、`InjectionSummary`、quality 编排(`_enforce_quality_blockers`/`_apply_pipeline_quality_state`/`_write_unified_quality_artifacts`)、`_post_injection_validation` 等 → 留主脚本(C5)。
- **C4 fund_flow 只收 gate/归一化簇**(1038–1242);`_apply_fund_flow_entry`/`_build_fund_flow_note`/`_is_suspicious_fund_flow_pair`/`_infer_trend`/`_infer_asset_trend` 是 entry 应用 → C5 entry_mergers。
- **不并入 utils/coercion**:Stage2.5 的 `_coerce_float`/`_coerce_percent` 等仅从主脚本搬到 `engines/stage2_5/common.py`(纯位置);与 `utils/coercion` 语义合一延后。
- 不拆簇内函数到更细模块;不重算 Stage2.5 contract replay golden;不做 main 入口瘦身(C 批次终态)。

## 3. 设计决策(brainstorming 核心结论)

| 决策 | 结论 | 依据 |
|---|---|---|
| **A. 目标包** | 新建 `engines/stage2_5/`,与 `engines/stage2/` 平行 | 边界清晰、与 Stage2 拆分一致;utils/ 已有几十模块,schema_coercion/manual_official 是 Stage2.5 专用逻辑非通用 util |
| **B. fund_flow 边界** | C4 fund_flow = gate/归一化簇(含 4 reclaim helper);entry 应用归 C5 | 与 C5 entry_mergers 统一所有 `_apply_*`/`_merge_*`;C4 fund_flow 保持"冻结门控 + reclaim"单一职责 |
| **C. 共享底座** | 新建 `engines/stage2_5/common.py`,纯逐字搬入跨簇低层件(numeric/url/domain);成员由 plan flake8 F821 定死 | 4 簇 + C5 残留都引用这些低层件;直接搬簇会产生 module→主脚本反向 import(同 C2 决策 A) |
| **D. cross-script reclaim** | 4 fund_flow helper 搬到 `engines/stage2_5/fund_flow`;`extraction_apply` 改指该 src 模块,删 `# C4-cleanup`;repo 内所有跨脚本 importer 一并 repoint | 消除 C2 遗留的 src→scripts 反向依赖;注入器不 import `engines/stage2/*`,故无环 |
| **E. 依赖方向** | 显式 `from datasource.engines.stage2_5.<mod> import _私有名` 保留 `_私有名`;call-site 零改 | 与 C1–C3 风格一致,零行为风险 |
| **F. PR 切分** | 单个 C4 PR;`manual_official`(冻结)与 `fund_flow`(冻结门控)各独立 commit + 评审逐字符核验 | 与 C2 validation/extraction_apply 一致;official allowlist 最安全敏感 |

## 4. 目标结构

```
src/datasource/engines/stage2_5/
  __init__.py            # docstring
  common.py              # 跨簇底座:numeric coerce / url-evidence / domain(F821 定)
  schema_coercion.py     # _coerce_stage2_results_to_schema + payload 归一化
  manual_official.py     # 官方 URL 证据 + allowlist 应用(冻结)
  fund_flow.py           # gate/归一化 + 4 reclaim helper(冻结门控)
  gap_sync.py            # gap_monitor + missing_items 同步
```

依赖序(plan 按此建模块):common → fund_flow → schema_coercion → gap_sync → manual_official(冻结,最后,独立 commit)。

**cross-package 边**:`engines/stage2/extraction_apply.py` → `engines/stage2_5/fund_flow`(替换原 scripts 反向 import)。注入器不 import `engines/stage2/*`,plan 用 import-time 冒烟确认无环。

## 5. 模块成员(行号 = main `3fa900b` 定位锚;最终由 plan F821 定死 common)

> common 为预判;任何被搬簇引用、仍定义在主脚本的低层私有件,F821 命中即并入 common(不反向 import 主脚本)。

- **common(seed)**:`_extract_domain`(252)、url-evidence(`_normalize_parseable_http_url`(398)/`_is_url_evidence_terminator`(417)/`_collect_http_like_evidence`(421)/`_extract_embedded_http_url`(445)/`_iter_http_like_evidence`(453)/`_extract_source_url`(467)/`_attach_source_url`(479)/`_is_https_url_evidence`(556)/`_extract_domains_from_payload`(560)/`_extract_domains_from_evidence`(569))、numeric(`_is_placeholder_numeric`(690)/`_has_valid_value`(694)/`_coerce_float`(2135)/`_pct_change`(2154)/`_same_numeric_value`(2164)/`_calc_change_rate_pct`(2172)/`_calc_previous_from_change_rate_pct`(2187)/`_coerce_percent`(2992)/`_coerce_bool`(3001))。
- **schema_coercion**:`_normalize_keyed_list`(362)、`_normalize_monetary_payload`(378)、`_copy_payload_metadata_fields`(492)、`_copy_source_url`(498)、`_coerce_stage2_results_to_schema`(1242)。
- **manual_official(冻结)**:`_should_preserve_existing_official_source`(504)、`_normalize_manual_official_key`(512)、`_iter_url_like_evidence`(518)、`_iter_explicit_url_evidence`(527)、`_has_multi_value_explicit_url_evidence`(534)、`_has_invalid_explicit_url_evidence`(541)、`_single_trusted_explicit_https_url`(578)、`_official_domain_matches`(613)、`_is_manual_official_value`(619)、`_apply_manual_official_estimation_rule`(637)、`_is_trusted_monetary_manual_quality_override`(2339)。
- **fund_flow(冻结门控)**:`_normalize_fund_flow_payload`(1038)、`_default_fund_flow_metric_basis`(1050)、`_normalize_source_tier`(1100)、`_normalize_window_evidence`(1107)、`_domain_matches`(1115)、`_parse_url_domain_path`(1119)、`_path_matches_prefix`(1135)、`_is_fund_flow_tier2_structured_source`(1145)、`_infer_fund_flow_source_tier`(1153)、`_infer_fund_flow_window_evidence`(1165)、`_fund_flow_has_trusted_window`(1212)、`_normalize_fund_flow_estimation`(1221)。**reclaim 4 名**:`_default_fund_flow_metric_basis`/`_infer_fund_flow_source_tier`/`_infer_fund_flow_window_evidence`/`_normalize_fund_flow_estimation`。
- **gap_sync**:`_collect_missing_source_urls`(650)、`_remove_missing_item`(698)、`_remove_top_missing`(723)、`_remove_top_missing_on_skip`(744)、`_is_missing_item_filled`(754)、`_refresh_stage2_gap_monitor`(804)、`_refresh_stage2_notes`(815)、`_cleanup_metadata_missing`(827)、`_append_missing_item`(856)、`_collect_unresolved_gap_items`(3952)、`_rewrite_gap_monitor_after_injection`(3993)。

> 留主脚本(C5/core,本 PR 不动):`inject_websearch_data`(1602)、`_apply_*_entry`/`_merge_*_entry`/`_build_*_entry`、trend backfill(3026–3934)、`parse_args`/`main`/`_default_cli_paths`、`InjectionSummary`(167)、`_policy_rules`(238)/`_is_estimated_allowlisted_entry`(245)/`_append_non_blocking_warning`(269)/`_collect_gc_non_blocking_warnings`(294)/`_derive_date_compact`(351)/`_enforce_quality_blockers`(862)/`_apply_pipeline_quality_state`(956)/`_write_unified_quality_artifacts`(979)/`_cleanup_monetary_aliases`(1020)/`_post_injection_validation`(2087)/`_format_source_label`(2202) 等(除非 F821 证明被 C4 簇引用 → 并入 common)。

## 6. 必须冻结不动的业务热点

- official manual override allowlist:`is_estimated=True`→`False` 正规化、单一可信 HTTPS URL 校验、多 URL/非法 URL 拒绝、`manual_official_not_estimated` marker、`reserve_ratio` PBoC quality override —— 全部 body 逐字。
- fund_flow gate:source_tier/window_evidence/metric_basis 推断、`direct_window/direct_daily_series/direct_balance_delta` 白名单、estimated 保持规则 —— body 逐字。
- schema coercion 的 manual_required/is_estimated/estimation_method 保留语义。
- gap/missing-items 双层(metadata dict + 顶层 list)同步语义。

## 7. Tests and Characterization

C4 先写测试再搬代码。

- 扩展 `tests/test_stage2_c2_split_characterization.py`(或新建 `tests/test_stage25_c4_split_characterization.py`):
  - import 5 新模块,加 C4 moved/export 名单;
  - before/after value-table 锁现行为(**manual_official/fund_flow 加码**:官方 URL 单/多/非法证据、allowlist 正规化、source_tier/window_evidence 每条触发分支);
  - `is` 身份断言(主脚本 re-export 与新模块同一对象);import-surface(全部 moved 名)。
- `tests/test_stage25_contract_replay.py` 为 canonical 端到端网:**byte-stable**,绝不设 `STAGE2_REPLAY_UPDATE_GOLDEN`,mismatch 即停-回报。
- Stage2 侧回归:`extraction_apply` repoint 后跑 `tests/test_stage2_replay_harness.py` + extraction_apply 相关测试,确认跨包 import 生效且行为不变。
- datetime tie-in:若任一新模块读 `datetime.now/utcnow/today`,在对应 replay/contract harness 的 datetime 冻结处补该模块(参 C1-followup `_freeze_stage2_datetime` 模式)。

## 8. Verification Commands(plan 内联完整版)

```bash
bash run_clean.sh python -m pytest tests/test_stage25_contract_replay.py -q          # byte-stable
bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q             # extraction_apply repoint 不破
bash run_clean.sh python -m pytest <c4 characterization> -q
bash run_clean.sh python -m py_compile src/datasource/engines/stage2_5/*.py src/datasource/engines/stage2/extraction_apply.py scripts/stage2_5_injector.py
bash run_clean.sh python -m flake8 src/datasource/engines/stage2_5/
bash run_clean.sh python -c "import scripts.stage2_5_injector; import datasource.engines.stage2.extraction_apply; print('IMPORT-OK')"   # 防环
bash run_clean.sh python -m pytest -q                                                  # 全量,无回归
```
C4 worktree baseline(实现前):`1179 passed, 3 skipped`。

## 9. Documentation and Carry-forward

- C5 carry-forward(`engines/stage2_5/` 续接):entry_mergers(`_apply_*_entry`/`_merge_*_entry`/`_build_*_entry`)、trend_backfill(`_calc_change_from_*`/`_backfill_*`)、core(`inject_websearch_data`)、cli(`parse_args`/`main`)。
- C4 完成后 `# C4-cleanup` 即回收;extraction_apply 不再跨脚本 import。
- `_safe_number`/Stage2.5 coercion 与 `utils/coercion` 合一:继续延后。
- main 入口瘦身:C 批次终态。

## 10. Risk and Mitigation

| 风险 | 缓解 |
|---|---|
| 搬簇产生 module→主脚本反向 import | 决策 C:先建 common 底座;plan flake8 F821 定 common 成员;依赖序 common 先行 |
| `extraction_apply → engines.stage2_5.fund_flow` 成环 | 注入器不 import engines/stage2;plan import-time 冒烟(§8)失败即停 |
| 冻结区 body 被微调(allowlist / fund_flow gate) | §6 冻结 + 独立 commit + 评审逐字符;characterization 加码锁每条分支 |
| 漏 repoint 某跨脚本 importer | plan grep `rg "stage2_5_injector import" -n`,把所有 fund_flow helper importer 一并改指 src |
| contract replay 非 byte-stable | §8 不设 UPDATE_GOLDEN;mismatch 停-回报,逐簇 revert 定位 |
| 新模块读 datetime 致 replay 漂移 | datetime tie-in 检查 + 冻结循环补模块 |
| 行号漂移 | plan 从开工 HEAD 现生成;按函数名 + 逐字 body |

## 11. Acceptance Criteria

- `engines/stage2_5/{__init__,common,schema_coercion,manual_official,fund_flow,gap_sync}.py` 存在,含 C4 簇符号;主脚本 re-export 为同一对象(`is`)。
- 无 `engines/stage2_5/*` import `scripts.stage2_5_injector`;`extraction_apply.py` 从 `engines.stage2_5.fund_flow` import 且无 `# C4-cleanup`/无跨脚本 import;import-time 冒烟通过、无环。
- 冻结簇(manual_official/fund_flow gate)body 逐字未变;characterization 加码项逐项绿。
- `tests/test_stage25_contract_replay.py` byte-stable;`tests/test_stage2_replay_harness.py` 绿(extraction_apply repoint 后)。
- `pytest -q` 全绿(passed = baseline + 新 characterization);py_compile/flake8 干净。
- 主脚本 4 簇无本地定义(仅 re-import);行数显著下降;CLI 行为不变。
- `data/runs`、`data/trend_history`、replay/contract golden、live-search 行为零变更。
