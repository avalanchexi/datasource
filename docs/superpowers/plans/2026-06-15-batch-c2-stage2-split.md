# PR-C2 执行计划:Stage2 拆分 — common / cli / query_planner / structured_runner / diagnostics / validation / extraction_apply

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 C1 之后主脚本(5748 行)里 7 组内聚域(1 新底座 common + 6 命名模块)纯机械搬移到 `src/datasource/engines/stage2/`,主脚本以 re-export 保持 zero call-site churn,行为零变更。

**Architecture:** 纯逐字搬移(函数 body 一字不改,只搬位置 + import 转发)。先建 `common.py` 底座消除 module→主脚本反向 import,再按依赖序往上搬 6 模块;两个行为冻结区(extraction_apply 的 forex 零值防占位、validation 的 fund_flow gate)各自独立 commit + 逐字符核验。`_execute_tasks`(2647 行)留 C3,本 PR 绕开。

**Tech Stack:** Python(≥3.7,async);pytest(含 async replay harness,需 pytest-asyncio);flake8 / py_compile;git worktree;本机 Windows + WSL(Linux `.venv`)。

> Spec:`docs/superpowers/specs/2026-06-15-batch-c2-stage2-split-design.md`。
> 行号采自 main `e59f307`(C1 squash 后);**搬移按函数名 + 逐字 body,不靠绝对行号 retype**;plan 命令在 worktree 根(`$WT`)执行,例外单独注明。
> 执行者:Codex(零上下文)。逐 checkbox 勾选;卡住即停-回报,不擅自改计划。

---

## 规划方有意偏离(评审请勿误判为占位/疏漏)

1. **搬移函数体未内联**(沿用 C1 既定做法):本 PR 是纯逐字搬移,要求 body 一字不改。指令为"按函数名整体搬入、body 逐字不变",而非把 ~3000 行抄进本 plan——抄写反而引入转写风险。正确性由 characterization(§Task1/9)+ `is` 身份断言 + replay harness byte-stable + `py_compile`/`flake8` 多重保证。
2. **import header / `# noqa: F401` 未逐字定死**:新模块 import header 与未用告警压制依各簇实际引用,由 `flake8`(F401/F811/F821)反馈收敛——机械、可判定。**但跨模块私有依赖是硬性的**:§搬移簇清单明确每个新模块**必须** import 的 common 名 / C1 模块名 / 跨脚本 fund_flow 名;外部 `src` import 直接复制主脚本现有 import 行(逐字)。
3. **characterization expected 由 Codex 在 Task 1 实跑取真**(与 C1 不同):C1 的核心 expected 由规划方离线预计算;本 PR 规划方**本会话无执行通道**(本机 Bash 工具损坏,且不在规划期跑项目 venv),故 Task 1 的 value-table expected 由 Codex 运行**当前主脚本现函数**取真后写死(锁现行为——现函数输出即真值)。强保证由 **`is` 身份断言**(搬后对象与主脚本 re-export 为同一函数,行为恒等)+ import-surface + replay byte-stable 兜底;value-table 主要为冻结区分支加码留痕。

---

## 统一环境头(Codex 必读,零上下文)

- **执行通道**:本机 Windows 上必须经 `wsl -e bash -lc '...'` 进入 Linux 侧;`.venv` 是 Linux venv。**不要用 Bash 工具**(本机 MSYS `dofork`/`errno 11` 损坏);只读 git 查询可用 PowerShell,但 **pytest/flake8/py_compile 一律 WSL + `run_clean.sh`**。所有命令默认从 worktree 根 `$WT` 执行。
- **流水线/测试**:一律 `bash run_clean.sh python -m pytest -q`、`bash run_clean.sh python -m flake8 ...`、`bash run_clean.sh python -m py_compile ...`,不直跑。需 async replay harness → 需 `pytest-asyncio`;缺则先 `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V` bootstrap dev 依赖,仍不行 → 停-回报。
- **硬约束**:Tavily 每日一次,**任何验证不得重跑 Stage2 真实搜索**;不触碰当日 `data/runs/YYYYMMDD` 与 `data/trend_history`;不手删 `.run.lock`。本 PR **全部验证离线**(pytest / py_compile / flake8 / replay harness),零真实 API。
- **行为冻结区**(diff 只允许 import/位置变化,body 逐字):forex 零值防占位(`_scrub_unevidenced_forex_zeroes`/`_copy_forex_compare_fields` + `_apply_extraction` 的 forex 分支)、fund_flow gate(`_validate_fund_flow_extraction`/`_flag_fund_flow_anomalies`/`_detect_fund_flow_suspicious_reason`)。official override allowlist 在 `utils/source_trust`(外部),本 PR **不搬不改**,仅 extraction_apply 调用它。
- **本 PR 额外冻结**:7 组的**函数体逐字不变**(含注释、空行、局部变量名)。允许的 diff 仅:新模块新增、主脚本删除原定义 + 新增 re-import 段。**禁止**顺手改 body、禁止改 call-site、禁止把 `_safe_number` 并入 `utils/coercion`(本 PR 仅搬位置)、禁止把 4 个 fund_flow helper 从 `stage2_5_injector` 搬走(那是 C4)。
- **Commit 规范**:Conventional(`test:`/`refactor:`),小步频提(每模块一个 refactor commit + characterization 一个 test commit);冻结区两模块各自独立 commit。

---

## 搬移簇清单(权威;按名搬移,body 逐字。行号 = main `e59f307` 定位锚)

> 常量标 `[C]`,其余为函数。每模块"必须 import"列出**跨模块私有依赖**(common / C1 模块 / 跨脚本);外部 `src` import 复制主脚本现有行。

**common.py**(底座,先建;无 intra-package 依赖):
- `_safe_number`(374)、`_RANGE_RULES`(382)`[C]`、`_FOREX_UPSERT_META`(404)`[C]`、`_COMMODITY_UPSERT_META`(413)`[C]`、`_BOND_UPSERT_META`(422)`[C]`、`_is_force_refresh_task`(1668)、`_entry_for_task`(1524)
- 必须 import:无新模块依赖;`_entry_for_task` 用到 `canonical_monetary_key`(复制主脚本 `from datasource.utils.key_aliases import canonical_monetary_key`)与本模块内 `_*_UPSERT_META`。

**cli.py**:
- `_env_int_default`(5310)、`_env_float_default`(5320)、`_parse_args`(5330)、`_should_enable_exa_fallback`(5469)、`_should_initialize_exa_client`(5474)、`_build_structured_registry_for_args`(5478)、`_is_exa_sdk_available`(5490)、`_load_tasks_from_file`(5498)、`_ensure_keys`(5509)、`_callable_supports_kwarg`(5524)、`_select_proxy_for_url`(5534)、`_validate_proxies`(5549)、`_parse_task_filter`(5579)
- 必须 import:flake8 F821 收敛(预期仅 argparse/os/typing + 可选 providers/exa——复制主脚本现有可选 import 行)。

**query_planner.py**(import snippet_filters + common):
- `_candidate_query_quality`(429)、`_exa_search_type`(241)、`_start_date_from_max_age`(269)、`_dedupe_candidate_queries`(2086)、`_expand_query_candidates`(2102)、`_build_directed_query`(2226)、`_should_retry_with_directed_query`(2285)
- 必须 import:`from datasource.engines.stage2.common import _safe_number`(若 F821 命中)+ 由 F821 确认的 `snippet_filters` 名(如 `_snippet_blob`/`_strict_indicator_tokens` 等);`_start_date_from_max_age` 的 datetime/timedelta 复制主脚本现有 import。

**structured_runner.py**（7 个叶子统计/记账 helper;import errors + common）:
- `_structured_stats`(1137)、`_structured_key_stats`(1160)、`_record_structured_attempt`(1166)、`_record_structured_latency_by_provider`(1174)、`_record_structured_success`(1187)、`_record_structured_fallback`(1202)、`_mark_structured_fallback_on_task`(1222)
- 必须 import:`from datasource.engines.stage2.errors import _structured_audit_fields_from_task`(C1,`_mark_structured_fallback_on_task` 用)+ 由 F821 确认的 common 名。这 7 个是纯 stats/task-dict 累加器,**不需**外部 structured providers import。
- ⚠️ **`_try_structured_provider`(1238, async)不搬,留主脚本 → C3**(2026-06-15 计划冲突补救):它是 structured 执行车道编排器(`augment→validate→apply→post-writeback→update-missing-items→task-log`),依赖 Task 6/7/8 簇 + out-of-scope glue(`_update_missing_items`/`_append_task_log`,被 `_execute_tasks` 重度使用),搬入必产生 module→主脚本反向 import。留主脚本后经 re-import 调这 7 个 helper(向下)+ 调 Task 6/7/8 搬走的簇(re-import,向下)+ 调本地 glue,零反向 import;与 `_execute_tasks` 一并 C3 切分。

**diagnostics.py**(import common):
- `_finalize_task_result_type`(1672)、`_finalize_websearch_result_type`(1680)、`_post_writeback_manual_reason`(1584)、`_post_writeback_missing_category`(1631)、`_mark_post_writeback_manual_required`(1649)、`_missing_required_output_fields`(1557)、`_nested_row_value`(1689)、`_build_retrieval_diagnostics`(1701)、`_manual_failure_layer`(1743)、`_build_manual_required_details`(1764)、`_has_diagnostic_value`(1804)、`_merge_nested_diagnostic_dict`(1808)、`_merge_diagnostic_row`(1816)、`_diagnostic_rows_for_summary`(1827)、`_stage2_effective_hit_rate`(1871)、`_stage2_summary_metric_fields`(1876)、`_build_stage2_result_count_fields`(1904)、`_format_stage2_task_count_line`(1929)、`_format_stage2_hit_rate_line`(1944)、`_structured_provider_summary_fields`(1957)、`_build_stage2_summary_diagnostics`(1994)
- 必须 import:由 F821 确认的 common 名(预期 `_safe_number`/`_entry_for_task`)。

**validation.py**(import common;**fund_flow gate 冻结区,独立 commit**):
- `_detect_fund_flow_suspicious_reason`(5013)、`_flag_fund_flow_anomalies`(5036)、`_validate_fund_flow_extraction`(5069)、`_validate_general_extraction`(5125)
- 必须 import:`from datasource.engines.stage2.common import _safe_number`(若 F821 命中)+ 由 F821 确认的外部名(如 `is_estimated_allowlisted` 复制主脚本现有 import)。

**extraction_apply.py**(import common + evidence;**forex 冻结区,独立 commit,最后**):
- `_infer_report_period`(627)、`_infer_as_of_date`(635)、`_augment_extraction_metadata`(655)、`_scrub_unevidenced_forex_zeroes`(808)、`_copy_forex_compare_fields`(838)、`_apply_extraction`(866)
- 必须 import:`from datasource.engines.stage2.common import _safe_number, _is_force_refresh_task, _FOREX_UPSERT_META, _COMMODITY_UPSERT_META, _BOND_UPSERT_META`(按 F821 实际)+ `from datasource.engines.stage2.evidence import _source_label_for_task`(C1)+ 外部(复制主脚本现有:`should_mark_official_non_estimated`、`is_estimated_allowlisted`、`canonical_monetary_key`、`forex_evidence` 族、`note_utils` 等被 body 引用者)+ **跨脚本 fund_flow import(逐字复制主脚本 L164–177 的 try/except 段)**:
  ```python
  try:
      from .stage2_5_injector import (
          _default_fund_flow_metric_basis,
          _infer_fund_flow_source_tier,
          _infer_fund_flow_window_evidence,
          _normalize_fund_flow_estimation,
      )
  except ImportError:  # pragma: no cover
      from stage2_5_injector import (  # type: ignore
          _default_fund_flow_metric_basis,
          _infer_fund_flow_source_tier,
          _infer_fund_flow_window_evidence,
          _normalize_fund_flow_estimation,
      )
  ```
  > ⚠️ `extraction_apply.py` 在 `src/` 下,`from .stage2_5_injector` 的相对 import 在该位置**不成立**(stage2_5_injector 在 scripts/)。Codex 落地时:把上面第一支改为 `from scripts.stage2_5_injector import ...`,保留 `except ImportError: from stage2_5_injector import ...` 兜底(运行时 conftest/run_clean 把 scripts/ 上 sys.path)。在该 import 段上方加注释 `# C4-cleanup: fund_flow helpers move to a src module in PR-C4; cross-script import is temporary.`。**import-time 冒烟必须确认不成环**(Task 8 Step)。

> ⚠️ **不搬**(留主脚本,C3/终态):`_execute_tasks`(2318)、`_try_structured_provider`(1238, async — structured 执行车道编排器,随 `_execute_tasks` 一并 C3)、`main`(5592)、`_DeepSeekCircuitBreaker`(2025)、`_is_deepseek_timeout`(2075)、`_mark_stale_refresh_failure`(2079)、io/glue(`_load_json`(192)/`_dump_json`(364)/`_append_task_log`(368)/`_merge_missing_items`(196)/`_apply_aliases`(201)/`_warn_disable_extract_on_critical_tasks`(223)/`_check_task_completeness`(276)/`_is_placeholder_number`(301)/`_has_non_placeholder_value`(305)/`_compute_derived_metrics`(1498)/`_update_missing_items`(1468)/`_append_gap_monitor`(1475)/`_filter_tasks`(1485)/`_gap_monitor`(4965))。
> ⚠️ **不并入 utils/coercion**:`_safe_number` 仅从主脚本搬到 common,实现不改。
> ⚠️ **F821 兜底规则(决策 D)**:若搬某簇后 flake8 报某名在新模块 F821 未定义、且该名仍定义在主脚本(非外部、非已搬),说明它是共享底座漏判 → **并入 common.py**(逐字搬)并在 common + 主脚本同步 re-import,**不要**反向 import 主脚本。卡住即停-回报。

---

## Task 0 — worktree 置备 + baseline(首任务)

**Files:** 无(只读置备)

- [ ] **Step 1: 置备 worktree(从当时 main HEAD)**

Run:
```bash
wsl -e bash -lc 'MAIN=/mnt/d/cursor/datasource; BR=codex/batch-c2-stage2-split; WT="$MAIN/.worktrees/codex-batch-c2-stage2-split"; cd "$MAIN" && git fetch && git worktree add "$WT" -b "$BR" main && cp "$MAIN/.env" "$WT/.env" && mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv" && cd "$WT" && DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V'
```
Expected:打印 Python 版本(≥3.7);`.venv` bootstrap 成功。失败 → 停-回报(不要 `ALLOW_SYSTEM_PYTHON=1` 绕过)。

- [ ] **Step 2: baseline 全量测试 + 记录基线指标**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && bash run_clean.sh python -m pytest -q 2>&1 | tail -5 && echo "---" && wc -l scripts/stage2_unified_enhancer.py && bash run_clean.sh python scripts/stage2_unified_enhancer.py --help > /tmp/c2_help_baseline.txt 2>&1; echo "help exit=$?"'
```
Expected:全绿(记录 passed 数 = baseline N,应 ≥ 1072);行数 5748;`--help` exit=0,输出存 `/tmp/c2_help_baseline.txt`。失败 → 停-回报(置备问题,不是本 PR 改动)。

---

## Task 1 — characterization tests(先写,锁现行为)

**Files:**
- Create: `tests/test_stage2_c2_split_characterization.py`

- [ ] **Step 1: 建 characterization(对主脚本现函数)**

新建 `tests/test_stage2_c2_split_characterization.py`,从主脚本现函数 import,跑固定输入表锁现行为。骨架(强保证部分由规划方定死;**value-table 的 expected 由 Codex 按 Step 2 实跑取真后写死**):
```python
"""C2 跨模块 characterization:搬移前后逐项不变。先对主脚本现函数锁行为,
搬移后(Task 9)断言新模块行为一致 + is 身份。全离线、秒级。
value-table expected 由 Codex 实跑主脚本现函数取真(锁现行为)。"""
import importlib
import pytest

ENH = importlib.import_module("stage2_unified_enhancer")  # scripts/ 在 sys.path(conftest)

# ---- common: _safe_number(数值/字符串/占位/None 边界)----
@pytest.mark.parametrize("raw", ["12.5", "1,234.5", "  7.1 ", "abc", None, "", "1.0%"])
def test_safe_number_locked(raw):
    # expected: 由 Codex 实跑 ENH._safe_number(raw) 取真后写死为 parametrize 第二参
    assert ENH._safe_number(raw) == EXPECTED_SAFE_NUMBER[raw]

# ---- common: _is_force_refresh_task ----
@pytest.mark.parametrize("task", [
    {"force_refresh": True}, {"force_refresh": False}, {"trigger_reason": "quality_gap"}, {},
])
def test_is_force_refresh_locked(task):
    assert ENH._is_force_refresh_task(task) == EXPECTED_FORCE_REFRESH[id(task)]

# ---- regex_extraction(C1)已覆盖;此处只覆盖 C2 簇代表函数 ----
# query_planner / structured_runner / diagnostics 代表函数(Codex 按实跑补 expected)
# ...(见 Step 2 覆盖清单)

# ---- import-surface:主脚本 re-export 生效(搬移后仍可调)----
C2_MOVED_NAMES = [
    # common
    "_safe_number", "_RANGE_RULES", "_FOREX_UPSERT_META", "_COMMODITY_UPSERT_META",
    "_BOND_UPSERT_META", "_is_force_refresh_task", "_entry_for_task",
    # cli
    "_env_int_default", "_env_float_default", "_parse_args", "_should_enable_exa_fallback",
    "_should_initialize_exa_client", "_build_structured_registry_for_args", "_is_exa_sdk_available",
    "_load_tasks_from_file", "_ensure_keys", "_callable_supports_kwarg", "_select_proxy_for_url",
    "_validate_proxies", "_parse_task_filter",
    # query_planner
    "_candidate_query_quality", "_exa_search_type", "_start_date_from_max_age",
    "_dedupe_candidate_queries", "_expand_query_candidates", "_build_directed_query",
    "_should_retry_with_directed_query",
    # structured_runner (7 leaf helpers; _try_structured_provider stays in monolith → C3)
    "_structured_stats", "_structured_key_stats", "_record_structured_attempt",
    "_record_structured_latency_by_provider", "_record_structured_success",
    "_record_structured_fallback", "_mark_structured_fallback_on_task",
    # diagnostics
    "_finalize_task_result_type", "_finalize_websearch_result_type", "_post_writeback_manual_reason",
    "_post_writeback_missing_category", "_mark_post_writeback_manual_required",
    "_missing_required_output_fields", "_nested_row_value", "_build_retrieval_diagnostics",
    "_manual_failure_layer", "_build_manual_required_details", "_has_diagnostic_value",
    "_merge_nested_diagnostic_dict", "_merge_diagnostic_row", "_diagnostic_rows_for_summary",
    "_stage2_effective_hit_rate", "_stage2_summary_metric_fields", "_build_stage2_result_count_fields",
    "_format_stage2_task_count_line", "_format_stage2_hit_rate_line",
    "_structured_provider_summary_fields", "_build_stage2_summary_diagnostics",
    # validation
    "_detect_fund_flow_suspicious_reason", "_flag_fund_flow_anomalies",
    "_validate_fund_flow_extraction", "_validate_general_extraction",
    # extraction_apply
    "_infer_report_period", "_infer_as_of_date", "_augment_extraction_metadata",
    "_scrub_unevidenced_forex_zeroes", "_copy_forex_compare_fields", "_apply_extraction",
]

@pytest.mark.parametrize("name", C2_MOVED_NAMES)
def test_import_surface_monolith(name):
    assert hasattr(ENH, name), f"主脚本应仍可调 {name}"
```
> **Codex 必做的 value-table 覆盖清单**(每项实跑主脚本现函数取 expected 写死;冻结区加码):
> - common:`_safe_number`(上表)、`_is_force_refresh_task`、`_entry_for_task`(macro/monetary/forex/commodities/bonds 命中 + upsert meta 路径,用 minimal market_payload fixture)。
> - cli:`_parse_args([])` 默认 Namespace 关键字段快照、`_env_int_default`/`_env_float_default`(present/absent/坏值)、`_parse_task_filter`、`_select_proxy_for_url`/`_validate_proxies`。
> - query_planner:`_candidate_query_quality`(给定 task+snippets 的打分 dict)、`_dedupe_candidate_queries`、`_should_retry_with_directed_query`、`_exa_search_type`、`_start_date_from_max_age`。
> - structured_runner（7 helper）:`_structured_stats`(空 stats 初值形状)、`_record_structured_attempt`/`_record_structured_success`/`_record_structured_fallback`(累加后 stats)、`_mark_structured_fallback_on_task`(写回字段)。`_try_structured_provider` **不搬(留主脚本→C3)**,本 PR 不为它加 characterization;其行为由 replay harness 端到端兜底。
> - diagnostics:`_finalize_task_result_type`/`_finalize_websearch_result_type`(各 result_type 输入)、`_build_retrieval_diagnostics`、`_manual_failure_layer`、`_stage2_effective_hit_rate`(分子分母边界)、`_post_writeback_manual_reason`、`_missing_required_output_fields`。
> - **validation(冻结区加码)**:`_validate_fund_flow_extraction`(估算/窗口/source_tier 触发与否每条分支)、`_flag_fund_flow_anomalies`、`_detect_fund_flow_suspicious_reason`、`_validate_general_extraction`。
> - **extraction_apply(冻结区加码)**:`_scrub_unevidenced_forex_zeroes`(零值保留 vs 转 manual 每条分支)、`_copy_forex_compare_fields`、`_apply_extraction`(macro/monetary/fund_flow/forex/commodities/bonds/forex_upsert/commodity_upsert/bond_upsert/fallback_macro 各返回值 + 关键写回字段 + official non-estimated 标记)、`_augment_extraction_metadata`、`_infer_report_period`/`_infer_as_of_date`。

- [ ] **Step 2: 实跑取真 + 跑绿(锁现行为)**

对每个 value-table 项,先取真值再写死:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && bash run_clean.sh python -c "import sys; sys.path.insert(0,\"scripts\"); import stage2_unified_enhancer as m; print(repr(m._safe_number(\"1,234.5\")))"'
```
(对其余函数同法取真)。然后:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && bash run_clean.sh python -m pytest tests/test_stage2_c2_split_characterization.py -q 2>&1 | tail -5'
```
Expected:全绿(锁现行为)。

- [ ] **Step 3: commit**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && git add tests/test_stage2_c2_split_characterization.py && git commit -m "test: add C2 stage2 split characterization (lock pre-move behavior)"'
```

---

## Task 2 — common.py(底座,先建)

**Files:**
- Create: `src/datasource/engines/stage2/common.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: 建 common.py** — import header(typing + `re`(若 `_safe_number` 用)+ `from datasource.utils.key_aliases import canonical_monetary_key`)+ **逐字搬入** common 簇 4 常量 + 3 函数(见清单,body 一字不改)。
- [ ] **Step 2: 主脚本删原定义 + re-import** — 删除 common 簇 7 组原定义;在 C1 的 re-import 块之后(evidence 块结束、`try: import httpx` 之前)插入:
  ```python
  from datasource.engines.stage2.common import (  # noqa: F401 (C2 re-export)
      _safe_number,
      _RANGE_RULES,
      _FOREX_UPSERT_META,
      _COMMODITY_UPSERT_META,
      _BOND_UPSERT_META,
      _is_force_refresh_task,
      _entry_for_task,
  )
  ```
- [ ] **Step 3: 校验**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && bash run_clean.sh python -m py_compile src/datasource/engines/stage2/common.py scripts/stage2_unified_enhancer.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage2/common.py && bash run_clean.sh python -m pytest tests/test_stage2_c2_split_characterization.py tests/test_stage2_replay_harness.py -q 2>&1 | tail -5'
```
Expected:py_compile 无输出;flake8 无 F401/F811/F821;characterization + replay 全绿。F821 undefined → 按 F821 兜底规则处理或补 import。

- [ ] **Step 4: commit** — `refactor: extract stage2 common base module (PR-C2)`

---

## Task 3 — cli.py

**Files:**
- Create: `src/datasource/engines/stage2/cli.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: 建 cli.py** — import header(argparse/os/typing + 复制主脚本可选 providers/exa import)+ **逐字搬入** cli 簇 13 函数。
- [ ] **Step 2: 主脚本删原定义 + 追加 re-import 块**(13 名,`# noqa: F401 (C2 re-export)`,完整名单见清单)。
- [ ] **Step 3: 校验**(同 Task 2 Step 3 三连,把 `common.py` 换成 `cli.py`)。Expected:全绿。
- [ ] **Step 4: commit** — `refactor: extract stage2 cli module (PR-C2)`

---

## Task 4 — query_planner.py

**Files:**
- Create: `src/datasource/engines/stage2/query_planner.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: 建 query_planner.py** — import header(re/datetime/timedelta/typing)+ 簇间依赖 `from datasource.engines.stage2.common import _safe_number`(按 F821)与 F821 确认的 `snippet_filters` 名 + **逐字搬入** 7 函数。
- [ ] **Step 2: 主脚本删原定义 + 追加 re-import 块**(7 名)。
- [ ] **Step 3: 校验**(三连,换 `query_planner.py`)。Expected:全绿;若 F821 报某 snippet_filters/common 名 → 补进簇间 import。
- [ ] **Step 4: commit** — `refactor: extract stage2 query_planner module (PR-C2)`

---

## Task 5 — structured_runner.py（仅 7 个叶子 helper;`_try_structured_provider` 留主脚本 → C3）

**Files:**
- Create: `src/datasource/engines/stage2/structured_runner.py`
- Modify: `scripts/stage2_unified_enhancer.py`

> ⚠️ **2026-06-15 计划冲突补救**:原计划把 `_try_structured_provider` 搬到本模块有误——它是 structured 执行车道编排器,依赖 Task 6/7/8 簇 + out-of-scope glue(`_update_missing_items`/`_append_task_log`),搬入必产生 module→主脚本反向 import。故本模块**只搬 7 个纯统计/记账叶子 helper**;`_try_structured_provider` 留主脚本(其 body 一字不动),经 re-import 调这 7 个 helper,随 `_execute_tasks` 一并 C3 切分。

- [ ] **Step 1: 建 structured_runner.py** — import header(typing 按 body)+ `from datasource.engines.stage2.errors import _structured_audit_fields_from_task`(`_mark_structured_fallback_on_task` 用)+ 按 F821 的 common 名 + **逐字搬入** 7 函数:`_structured_stats`、`_structured_key_stats`、`_record_structured_attempt`、`_record_structured_latency_by_provider`、`_record_structured_success`、`_record_structured_fallback`、`_mark_structured_fallback_on_task`。**不搬 `_try_structured_provider`**(它留主脚本;不要动它的 body)。
- [ ] **Step 2: 主脚本删这 7 个原定义 + 追加 re-import 块**(7 名,`# noqa: F401 (C2 re-export)`)。`_try_structured_provider`(仍在主脚本)对这 7 个 helper 的调用经此 re-import 解析(下一步 py_compile/replay 兜底)。
- [ ] **Step 3: 校验**(三连,换 `structured_runner.py`)。Expected:全绿(replay harness 含 structured 链路——`_try_structured_provider` 经 re-import 调 7 helper,务必 byte-stable;若 F821 报 `_try_structured_provider` 调的某 helper 未定义,说明 re-import 漏名 → 补齐 7 名)。
- [ ] **Step 4: commit** — `refactor: extract stage2 structured_runner stats helpers; keep _try_structured_provider in monolith for C3 (PR-C2)`

---

## Task 6 — diagnostics.py

**Files:**
- Create: `src/datasource/engines/stage2/diagnostics.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: 建 diagnostics.py** — import header(typing + 按 F821 的 common 名)+ **逐字搬入** 21 函数。
- [ ] **Step 2: 主脚本删原定义 + 追加 re-import 块**(21 名)。
- [ ] **Step 3: 校验**(三连,换 `diagnostics.py`)。Expected:全绿。
- [ ] **Step 4: commit** — `refactor: extract stage2 diagnostics module (PR-C2)`

---

## Task 7 — validation.py(fund_flow 冻结区,独立 commit)

**Files:**
- Create: `src/datasource/engines/stage2/validation.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: 建 validation.py** — import header(typing + `from datasource.engines.stage2.common import _safe_number` 按 F821 + 复制主脚本被 body 引用的外部 import 如 `is_estimated_allowlisted`)+ **逐字搬入** 4 函数。**fund_flow gate body 一字不改**。
- [ ] **Step 2: 主脚本删原定义 + 追加 re-import 块**(4 名)。
- [ ] **Step 3: 校验**(三连,换 `validation.py`)。**额外**:characterization 中 validation 冻结区加码项必须逐项绿。Expected:全绿。
- [ ] **Step 4: commit** — `refactor: extract stage2 validation module — fund_flow gate verbatim (PR-C2)`

---

## Task 8 — extraction_apply.py(forex 冻结区,独立 commit,最后)

**Files:**
- Create: `src/datasource/engines/stage2/extraction_apply.py`
- Modify: `scripts/stage2_unified_enhancer.py`

- [ ] **Step 1: 建 extraction_apply.py** — import header:`from datasource.engines.stage2.common import _safe_number, _is_force_refresh_task, _FOREX_UPSERT_META, _COMMODITY_UPSERT_META, _BOND_UPSERT_META`(按 F821 实际)+ `from datasource.engines.stage2.evidence import _source_label_for_task` + 复制主脚本被 body 引用的外部 import(`should_mark_official_non_estimated`、`is_estimated_allowlisted`、`canonical_monetary_key`、forex_evidence 族、note_utils 等)+ **跨脚本 fund_flow import**(见清单代码块,第一支改 `from scripts.stage2_5_injector import ...`,保留 bare 兜底,上方加 `# C4-cleanup` 注释)+ **逐字搬入** 6 函数。**forex 零值防占位 body 一字不改**。
- [ ] **Step 2: 主脚本删原定义 + 追加 re-import 块**(6 名)。
- [ ] **Step 3: import-time 冒烟(确认跨脚本 import 不成环)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && bash run_clean.sh python -c "import datasource.engines.stage2.extraction_apply as m; print(\"OK\", hasattr(m, \"_apply_extraction\"))" && bash run_clean.sh python -c "import sys; sys.path.insert(0,\"scripts\"); import stage2_unified_enhancer; print(\"MONOLITH OK\")"'
```
Expected:`OK True` + `MONOLITH OK`,无 ImportError、无循环 import。成环 → 停-回报(确认 stage2_5_injector 是否 import 了某 C2 新模块)。

- [ ] **Step 4: 校验**(三连,换 `extraction_apply.py`)。**额外**:characterization 中 extraction_apply 冻结区加码项逐项绿。Expected:全绿。
- [ ] **Step 5: commit** — `refactor: extract stage2 extraction_apply module — forex gate verbatim, cross-script fund_flow import flagged C4 (PR-C2)`

---

## Task 9 — characterization 切到新模块 + datetime tie-in + 全量验收

**Files:**
- Modify: `tests/test_stage2_c2_split_characterization.py`
- Modify(条件):`tests/test_stage2_replay_harness.py`(仅当新模块读 datetime)

- [ ] **Step 1: 追加新模块直连 + `is` 身份断言** — 在 characterization 末尾追加:
  ```python
  COMMON = importlib.import_module("datasource.engines.stage2.common")
  CLI = importlib.import_module("datasource.engines.stage2.cli")
  QP = importlib.import_module("datasource.engines.stage2.query_planner")
  SR = importlib.import_module("datasource.engines.stage2.structured_runner")
  DIAG = importlib.import_module("datasource.engines.stage2.diagnostics")
  VAL = importlib.import_module("datasource.engines.stage2.validation")
  EA = importlib.import_module("datasource.engines.stage2.extraction_apply")

  def test_new_modules_export_moved_names():
      assert hasattr(COMMON, "_safe_number") and hasattr(COMMON, "_entry_for_task")
      assert hasattr(CLI, "_parse_args")
      assert hasattr(QP, "_candidate_query_quality")
      assert hasattr(SR, "_record_structured_success")
      assert hasattr(DIAG, "_build_retrieval_diagnostics")
      assert hasattr(VAL, "_validate_fund_flow_extraction")
      assert hasattr(EA, "_apply_extraction")

  def test_try_structured_provider_stays_in_monolith():
      # structured 执行车道编排器留主脚本(→C3);不应出现在 structured_runner
      assert hasattr(ENH, "_try_structured_provider")
      assert not hasattr(SR, "_try_structured_provider")

  def test_moved_fn_identity_via_monolith():
      # 主脚本 re-export 与新模块为同一对象(zero call-site churn + 行为恒等的证明)
      assert ENH._safe_number is COMMON._safe_number
      assert ENH._parse_args is CLI._parse_args
      assert ENH._candidate_query_quality is QP._candidate_query_quality
      assert ENH._record_structured_success is SR._record_structured_success
      assert ENH._build_retrieval_diagnostics is DIAG._build_retrieval_diagnostics
      assert ENH._validate_fund_flow_extraction is VAL._validate_fund_flow_extraction
      assert ENH._apply_extraction is EA._apply_extraction
  ```

- [ ] **Step 2: datetime tie-in 检查** — grep 7 新模块的 datetime 用法:
  ```bash
  wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && grep -rnE "datetime\.(now|utcnow|today)" src/datasource/engines/stage2/{common,cli,query_planner,structured_runner,diagnostics,validation,extraction_apply}.py || echo "NO-DATETIME-NOW (OK)"'
  ```
  **若命中**:把命中的模块加进 `tests/test_stage2_replay_harness.py` 的 `_freeze_stage2_datetime` 冻结循环(`for module in (...)` 元组追加该模块 import),按 C1 followup docstring 指引;再跑 replay 确认 byte-stable。**若 `NO-DATETIME-NOW`**:replay 冻结集不变,跳过。

- [ ] **Step 3: 全量验收**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && bash run_clean.sh python -m pytest -q 2>&1 | tail -8 && bash run_clean.sh python -m py_compile src/datasource/engines/stage2/*.py scripts/stage2_unified_enhancer.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage2/ && bash run_clean.sh python scripts/stage2_unified_enhancer.py --help > /tmp/c2_help_after.txt 2>&1 && diff /tmp/c2_help_baseline.txt /tmp/c2_help_after.txt && echo "HELP-DIFF-EMPTY" && wc -l scripts/stage2_unified_enhancer.py'
```
Expected:pytest 全绿(passed = baseline N + 新 characterization 用例);py_compile 无输出;flake8 无违规;`HELP-DIFF-EMPTY`;主脚本行数较 5748 下降约 1500+。replay 非 byte-stable / 任一 fail → 停-回报(逐簇 revert 二分定位)。

- [ ] **Step 4: 残留校验(7 组主脚本无本地定义)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && rg -n "^def _safe_number|^def _apply_extraction|^def _validate_fund_flow_extraction|^def _candidate_query_quality|^def _parse_args|^def _record_structured_success|^def _build_retrieval_diagnostics|^_RANGE_RULES =|^_FOREX_UPSERT_META =" scripts/stage2_unified_enhancer.py || echo "NO-LOCAL-DEF (OK)"; rg -n "^async def _execute_tasks|^async def _try_structured_provider|^async def main|^def _gap_monitor" scripts/stage2_unified_enhancer.py && echo "RETAINED-IN-MONOLITH (OK)"'
```
Expected:第一条 `NO-LOCAL-DEF`;第二条命中 4 个(`_execute_tasks`/`_try_structured_provider`/`main`/`_gap_monitor` 仍在主脚本 = C3/终态)。

- [ ] **Step 5: commit** — `test: assert C2 split modules behave identically post-move (is-identity + import-surface)`

---

## Task 10 — 文档同步 + 隔离断言 + 回报(尾任务)

**Files:**
- Modify: `optimization/20260610_refactor_plan/TODOS.md`

- [ ] **Step 1: TODOS.md** — C2 行 `[ ]` → `[x]`(附 commit/squash SHA 占位待合入填),"当前焦点"改为 PR-C3;commit `docs: mark PR-C2 complete in refactor TODOS`。
- [ ] **Step 2: 命令漂移检查**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && bash run_clean.sh python -m pytest tests/test_manual_template.py tests/test_stage4_docs.py -q 2>&1 | tail -3'
```
Expected:全绿(本 PR 仅搬内部私有函数 + 常量,不改文档命令示例)。

- [ ] **Step 3: 隔离断言**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && git status --short && ls /mnt/d/cursor/datasource/data/runs/ 2>/dev/null | tail -3'
```
Expected:`git status` 只含本 PR 的新增/修改(7 新模块 + 主脚本 + 新测试 +(条件)replay harness + TODOS.md);无 `data/`/`reports/`/`logs/` 业务产物。

- [ ] **Step 4: 临时产物清理 + 完成回报**

清理:`rm -f /tmp/c2_help_baseline.txt /tmp/c2_help_after.txt`。
**完成回报(给评审方 Claude)**:
- 实际 commit 列表(逐条);
- 全量 pytest passed 数(baseline N → after);
- 主脚本行数(5748 → ?);
- 7 模块依赖图确认(common 无 intra;cli/diagnostics 仅 common;query_planner→snippet_filters+common;structured_runner→errors+common;validation→common;extraction_apply→common+evidence+跨脚本 stage2_5_injector[标 C4];无 module→主脚本反向、无环);
- datetime tie-in 结论(NO-DATETIME-NOW,或列出新增冻结模块);
- replay harness byte-stable 确认 + `--help` diff 空确认 + import-time 冒烟 OK;
- 冻结区两模块(validation/extraction_apply)characterization 加码项逐项绿;
- **任何计划外改动逐条列出**(理想为 flake8 逼出的 import 调整 / F821 兜底并入 common 的名;明示)。

---

## 评审方(Claude)checklist

1. **计划符合度**:10 个 Task 逐项完成;commit 列表与回报一致;独立验证"计划外改动"仅限 flake8/F821 机械收敛(不只信摘要)。
2. **冻结区 diff**:7 组函数体逐字未变(`git diff` 只见位置移动 + import);call-site 零改;**重点逐字符核验** extraction_apply 的 forex 零值分支(`_scrub_unevidenced_forex_zeroes`/`_copy_forex_compare_fields`/`_apply_extraction` forex 段)与 validation 的 fund_flow gate(`_validate_fund_flow_extraction`/`_flag_fund_flow_anomalies`/`_detect_fund_flow_suspicious_reason`);`_safe_number` 实现未变、未并入 utils/coercion。
3. **依赖图**:common 无 intra;6 模块向下 import common/对应 C1;`evidence→snippet_filters`(C1)仍单向;extraction_apply→`scripts/stage2_5_injector` 是既有跨脚本依赖的复制(标 C4),无 module→主脚本反向、无环;import-time 冒烟通过。
4. **测试**:characterization before/after 逐项一致 + import-surface(全 65 名;`_try_structured_provider` 留主脚本→C3,不计入搬移名单,另有 `test_try_structured_provider_stays_in_monolith` 断言它不在 SR)+ `is` 身份(SR 代表用 `_record_structured_success`);replay harness byte-stable;datetime tie-in 处理正确;`--help` diff 空。
5. **C4 钩登记**:extraction_apply 的跨脚本 fund_flow import 带 `# C4-cleanup` 注释,且 C4 spec/计划接手时把这 4 helper 搬到 src 后回收本 import。
6. **合入**:默认 squash;合入前验证分支与合入内容零 diff;合入后 `git worktree remove "$WT"` + 删分支;下一步生成 C3 plan。

---

## Self-Review(规划方自查)

- **Spec 覆盖**:§2 模块表 7 组 → Task 2–8 逐模块;§3 决策 A(common 底座)→ Task 2 先行;决策 B(单 PR 冻结区独立 commit)→ Task 7/8;决策 C(跨脚本 import 标 C4)→ Task 8 Step 1/3;决策 D(F821 兜底并入 common)→ 清单尾规则 + 各 Task Step 3;§5 characterization + datetime tie-in → Task 1/9;§8 验收 7 条 → Task 9 Step 3/4 + Task 10。✅ 全覆盖。
- **Placeholder 扫描**:无 TBD;value-table expected 明确由 Codex 实跑取真(§偏离 3 已声明,非占位);import header 由 flake8 收敛(机械,非占位);commit 文案全给。✅
- **一致性**:模块名/函数名/re-import 名单在清单、Task、characterization `C2_MOVED_NAMES`(65 名;`_try_structured_provider` 留主脚本→C3)、`is` 身份断言间一致;structured_runner 仅 7 helper、`_try_structured_provider` 在"不搬"列表与 Task 5 补救说明一致;依赖序 common→其余→validation→extraction_apply 在 §4.2/Task 顺序一致;worktree 路径 `.worktrees/codex-batch-c2-stage2-split` + 分支 `codex/batch-c2-stage2-split` 全程一致。✅
- **离线 / 冻结**:全程无真实 API;冻结区 body 逐字 + 独立 commit + 加码 characterization;`_safe_number` 仅搬位置。✅
