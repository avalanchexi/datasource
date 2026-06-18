# PR-C4 执行计划:Stage2.5 注入器拆分 — common / schema_coercion / manual_official / fund_flow / gap_sync

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `scripts/stage2_5_injector.py`(4211 行)的 4 个低层簇 + 一个 common 底座纯机械搬移到新包 `src/datasource/engines/stage2_5/`,主脚本 re-export 保持 zero call-site churn;并回收 C2 遗留的 `# C4-cleanup`(extraction_apply 跨脚本 fund_flow import 改指 src)。

**Architecture:** 纯逐字搬移(body 一字不改,只搬位置 + import 转发)。先建 `common.py` 底座消除 module→主脚本反向 import,再按依赖序搬 fund_flow → schema_coercion → gap_sync → manual_official(冻结,最后,独立 commit)。`inject_websearch_data` 编排器与 entry-mergers/trend-backfill/cli 留主脚本(C5)。

**Tech Stack:** Python(≥3.7);pytest(含 Stage2.5 contract replay、Stage2 replay harness);flake8 / py_compile;git worktree;本机 Windows + WSL(Linux `.venv`)。

> Spec:`docs/superpowers/specs/2026-06-16-batch-c4-stage25-split-design.md`。
> 行号采自 main `3fa900b`;**搬移按函数名 + 逐字 body,不靠绝对行号 retype**;命令在 worktree 根执行。
> 执行者:Codex(零上下文)。逐 checkbox 勾选;卡住即停-回报,不擅自改计划。

---

## 规划方有意偏离(评审请勿误判为占位/疏漏)

1. **搬移函数体未内联**(沿用 C1–C3 既定做法):纯逐字搬移,body 一字不改。正确性由 characterization(§Task1/7)+ `is` 身份断言 + Stage2.5 contract replay byte-stable + `py_compile`/`flake8` 多重保证。
2. **import header / `# noqa` 由 flake8 收敛**;但跨模块私有依赖是硬性的:§搬移簇清单明确每个新模块必须 import 的 common 名;外部 `src` import 复制主脚本现有 import 行。
3. **characterization expected 由 Codex 在 Task 1 实跑取真**(同 C2/C3,本机规划期无执行通道):value-table expected 由 Codex 运行主脚本现函数取真后写死。强保证靠 `is` 身份 + contract replay byte-stable。
4. **common 成员由 flake8 F821 定死**:§5 seed 为预判;任何被搬簇引用、仍在主脚本的低层私有件,F821 命中即并入 common(不反向 import 主脚本)。

---

## 统一环境头(Codex 必读,零上下文)

- **执行通道**:本机 Windows,**Bash 工具损坏**(MSYS `dofork`/`errno 11`)。每条 shell 命令经 `wsl -e bash -lc '...'`;只读 git 查询可用 PowerShell,但 **pytest/flake8/py_compile 一律 WSL + `run_clean.sh`**。命令默认从 worktree 根执行。
- async/replay 需 `pytest-asyncio`;缺则先 `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V` bootstrap;仍不行 → 停-回报。
- **硬约束**:Tavily 每日一次,**不重跑 Stage2 真实搜索**;不碰当日 `data/runs/YYYYMMDD` 与 `data/trend_history`;不手删 `.run.lock`。本 PR 全程离线。
- **行为冻结区**(diff 只允许 import/位置变化,body 逐字):official manual override allowlist(mlf/USDCNY/BCOM)、fund_flow gate(source_tier/window_evidence/metric_basis/estimated 规则)、schema coercion 的 manual_required/is_estimated 语义、gap/missing-items 双层同步。
- **本 PR 额外冻结**:5 组函数体逐字不变;不并入 `utils/coercion`(仅搬位置);不动 `inject_websearch_data` 及 C5 簇;不重算 Stage2.5 contract replay golden。
- **Commit 规范**:Conventional(`test:`/`refactor:`),小步频提;manual_official(冻结)与 fund_flow(冻结门控)各独立 commit。

---

## 搬移簇清单(权威;按名搬移,body 逐字。行号 = main `3fa900b` 定位锚)

> 常量随簇;每模块"必须 import"列跨模块私有依赖(common);外部 src import 复制主脚本现有行。

**common.py**(底座,先建;无 intra-package 依赖):
- url-evidence:`_extract_domain`(252)、`_normalize_parseable_http_url`(398)、`_is_url_evidence_terminator`(417)、`_collect_http_like_evidence`(421)、`_extract_embedded_http_url`(445)、`_iter_http_like_evidence`(453)、`_extract_source_url`(467)、`_attach_source_url`(479)、`_is_https_url_evidence`(556)、`_extract_domains_from_payload`(560)、`_extract_domains_from_evidence`(569)
- numeric:`_is_placeholder_numeric`(690)、`_has_valid_value`(694)、`_coerce_float`(2135)、`_pct_change`(2154)、`_same_numeric_value`(2164)、`_calc_change_rate_pct`(2172)、`_calc_previous_from_change_rate_pct`(2187)、`_coerce_percent`(2992)、`_coerce_bool`(3001)
- 必须 import:外部(复制主脚本被 body 引用的 import,如 `urlparse`、`is_stage2_number_placeholder`/`is_legacy_713_placeholder` from utils.coercion)。
- ⚠️ 这是 seed;Task 2 flake8 跑后,若某簇(Task 3–6)F821 命中其它低层件,回到本模块补搬。

**fund_flow.py**(冻结门控,独立 commit;import common):
- `_normalize_fund_flow_payload`(1038)、`_default_fund_flow_metric_basis`(1050)、`_normalize_source_tier`(1100)、`_normalize_window_evidence`(1107)、`_domain_matches`(1115)、`_parse_url_domain_path`(1119)、`_path_matches_prefix`(1135)、`_is_fund_flow_tier2_structured_source`(1145)、`_infer_fund_flow_source_tier`(1153)、`_infer_fund_flow_window_evidence`(1165)、`_fund_flow_has_trusted_window`(1212)、`_normalize_fund_flow_estimation`(1221)
- **reclaim 4 名**(被 Stage2 extraction_apply/execution 共用):`_default_fund_flow_metric_basis`、`_infer_fund_flow_source_tier`、`_infer_fund_flow_window_evidence`、`_normalize_fund_flow_estimation`。
- 必须 import:由 F821 确认的 common 名 + 外部(复制主脚本被 body 引用者)。

**schema_coercion.py**(import common,可能 import fund_flow):
- `_normalize_keyed_list`(362)、`_normalize_monetary_payload`(378)、`_copy_payload_metadata_fields`(492)、`_copy_source_url`(498)、`_coerce_stage2_results_to_schema`(1242)
- 必须 import:F821 确认的 common 名;若 `_coerce_stage2_results_to_schema` 调 `_normalize_fund_flow_payload` 等,则 `from datasource.engines.stage2_5.fund_flow import ...`(故 fund_flow 先建)。

**gap_sync.py**(import common):
- `_collect_missing_source_urls`(650)、`_remove_missing_item`(698)、`_remove_top_missing`(723)、`_remove_top_missing_on_skip`(744)、`_is_missing_item_filled`(754)、`_refresh_stage2_gap_monitor`(804)、`_refresh_stage2_notes`(815)、`_cleanup_metadata_missing`(827)、`_append_missing_item`(856)、`_collect_unresolved_gap_items`(3952)、`_rewrite_gap_monitor_after_injection`(3993)
- 必须 import:F821 确认的 common 名 + 外部(`append_missing_item` from utils.missing_items 等,复制主脚本现有 import)。
- ⚠️ 主脚本本地 `_append_missing_item`(856)与 utils 的 `append_missing_item` 是两个不同名;不要混。

**manual_official.py**(冻结区,独立 commit,**最后**;import common):
- `_should_preserve_existing_official_source`(504)、`_normalize_manual_official_key`(512)、`_iter_url_like_evidence`(518)、`_iter_explicit_url_evidence`(527)、`_has_multi_value_explicit_url_evidence`(534)、`_has_invalid_explicit_url_evidence`(541)、`_single_trusted_explicit_https_url`(578)、`_official_domain_matches`(613)、`_is_manual_official_value`(619)、`_apply_manual_official_estimation_rule`(637)、`_is_trusted_monetary_manual_quality_override`(2339)
- 必须 import:F821 确认的 common 名 + 外部(`is_official_source_url` from utils.source_trust 等,复制主脚本现有 import)。**body 一字不改**(allowlist 正规化/URL 校验)。

> ⚠️ **不搬**(留主脚本,C5/core):`inject_websearch_data`(1602)、`inject_websearch_results`(2083)、`_apply_macro_entry`(2389)/`_apply_monetary_entry`(2636)/`_apply_fund_flow_entry`(2816)/`_merge_*_entry`/`_build_*_entry`、trend backfill(3026–3934)、`parse_args`(4537)/`main`(4618)/`_default_cli_paths`(4528)、`InjectionSummary`(167)、`_policy_rules`(238)/`_is_estimated_allowlisted_entry`(245)/`_append_non_blocking_warning`(269)/`_collect_gc_non_blocking_warnings`(294)/`_derive_date_compact`(351)/`_enforce_quality_blockers`(862)/`_apply_pipeline_quality_state`(956)/`_write_unified_quality_artifacts`(979)/`_cleanup_monetary_aliases`(1020)/`_post_injection_validation`(2087)/`_format_source_label`(2202)/`_create_*_placeholder`/`_apply_macro_entry` 等(除非 F821 证明被 C4 簇引用 → 并入 common)。
> ⚠️ **不并入 utils/coercion**:仅搬位置,实现不改。

---

## Task 0 — worktree 置备 + baseline

**Files:** 无(只读置备)

- [ ] **Step 1: 置备 worktree(从当时 main HEAD)**

```bash
wsl -e bash -lc 'MAIN=/mnt/d/cursor/datasource; BR=codex/batch-c4-stage25-split; WT="$MAIN/.worktrees/codex-batch-c4-stage25-split"; cd "$MAIN" && git fetch && git worktree add "$WT" -b "$BR" main && cp "$MAIN/.env" "$WT/.env" && mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv" && cd "$WT" && DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V'
```
Expected:Python 版本(≥3.7);`.venv` bootstrap 成功。失败 → 停-回报。

- [ ] **Step 2: baseline 全量 + 行数**

```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && bash run_clean.sh python -m pytest -q 2>&1 | tail -5 && echo "---" && wc -l scripts/stage2_5_injector.py'
```
Expected:`1179 passed, 3 skipped`(记录为 baseline N);行数 4211。失败 → 停-回报。

---

## Task 1 — characterization tests(先写,锁现行为)

**Files:**
- Create: `tests/test_stage25_c4_split_characterization.py`

- [ ] **Step 1: 建 characterization(对主脚本现函数)**

新建 `tests/test_stage25_c4_split_characterization.py`,从 `stage2_5_injector` import 现函数,跑固定输入表锁现行为。强保证(import-surface + 后续 `is` 身份)由规划方定死;value-table expected 由 Codex 实跑取真(Step 2)。骨架:
```python
"""C4 Stage2.5 拆分 characterization:搬移前后逐项不变 + is 身份。全离线。
value-table expected 由 Codex 实跑主脚本现函数取真(锁现行为)。"""
import importlib
import pytest

INJ = importlib.import_module("stage2_5_injector")  # scripts/ 在 sys.path(conftest)

C4_MOVED_NAMES = [
    # common
    "_extract_domain", "_normalize_parseable_http_url", "_is_url_evidence_terminator",
    "_collect_http_like_evidence", "_extract_embedded_http_url", "_iter_http_like_evidence",
    "_extract_source_url", "_attach_source_url", "_is_https_url_evidence",
    "_extract_domains_from_payload", "_extract_domains_from_evidence",
    "_is_placeholder_numeric", "_has_valid_value", "_coerce_float", "_pct_change",
    "_same_numeric_value", "_calc_change_rate_pct", "_calc_previous_from_change_rate_pct",
    "_coerce_percent", "_coerce_bool",
    # fund_flow
    "_normalize_fund_flow_payload", "_default_fund_flow_metric_basis", "_normalize_source_tier",
    "_normalize_window_evidence", "_domain_matches", "_parse_url_domain_path",
    "_path_matches_prefix", "_is_fund_flow_tier2_structured_source",
    "_infer_fund_flow_source_tier", "_infer_fund_flow_window_evidence",
    "_fund_flow_has_trusted_window", "_normalize_fund_flow_estimation",
    # schema_coercion
    "_normalize_keyed_list", "_normalize_monetary_payload", "_copy_payload_metadata_fields",
    "_copy_source_url", "_coerce_stage2_results_to_schema",
    # gap_sync
    "_collect_missing_source_urls", "_remove_missing_item", "_remove_top_missing",
    "_remove_top_missing_on_skip", "_is_missing_item_filled", "_refresh_stage2_gap_monitor",
    "_refresh_stage2_notes", "_cleanup_metadata_missing", "_append_missing_item",
    "_collect_unresolved_gap_items", "_rewrite_gap_monitor_after_injection",
    # manual_official (frozen)
    "_should_preserve_existing_official_source", "_normalize_manual_official_key",
    "_iter_url_like_evidence", "_iter_explicit_url_evidence",
    "_has_multi_value_explicit_url_evidence", "_has_invalid_explicit_url_evidence",
    "_single_trusted_explicit_https_url", "_official_domain_matches",
    "_is_manual_official_value", "_apply_manual_official_estimation_rule",
    "_is_trusted_monetary_manual_quality_override",
]


@pytest.mark.parametrize("name", C4_MOVED_NAMES)
def test_import_surface_monolith(name):
    assert hasattr(INJ, name), f"主脚本应仍可调 {name}"
```
> **Codex 必做 value-table 覆盖**(每项实跑取真;冻结簇加码):
> - common:`_coerce_float`/`_coerce_percent`/`_is_placeholder_numeric`/`_has_valid_value`(数值/占位/None 边界)、`_calc_change_rate_pct`/`_pct_change`(分母 0 边界)、`_extract_domain`/`_normalize_parseable_http_url`/`_is_https_url_evidence`(url 解析)。
> - **fund_flow(冻结门控,加码)**:`_default_fund_flow_metric_basis`/`_infer_fund_flow_source_tier`/`_infer_fund_flow_window_evidence`(各 source_tier/window_evidence 触发分支:tier1/tier2 域名、`direct_window/direct_daily_series/direct_balance_delta`)、`_fund_flow_has_trusted_window`、`_normalize_fund_flow_estimation`(estimated 保持/清除分支)。
> - schema_coercion:`_coerce_stage2_results_to_schema`(给定一份 minimal Stage2 results,断言输出 schema 关键字段 + manual_required/is_estimated 保留)、`_normalize_monetary_payload`/`_normalize_keyed_list`。
> - gap_sync:`_refresh_stage2_gap_monitor`、`_is_missing_item_filled`、`_remove_missing_item`/`_append_missing_item`(metadata 双层)、`_rewrite_gap_monitor_after_injection`。
> - **manual_official(冻结,加码)**:`_single_trusted_explicit_https_url`(单一/多个/非 HTTPS/非法端口/spoof URL 各分支)、`_is_manual_official_value`、`_apply_manual_official_estimation_rule`(is_estimated True→False 正规化 + marker)、`_is_trusted_monetary_manual_quality_override`(PBoC override 触发/拒绝)。

- [ ] **Step 2: 实跑取真 + 跑绿**

对每个 value-table 项先取真值:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && bash run_clean.sh python -c "import sys; sys.path.insert(0,\"scripts\"); import stage2_5_injector as m; print(repr(m._coerce_float(\"1,234.5\")))"'
```
(其余函数同法)。然后:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && bash run_clean.sh python -m pytest tests/test_stage25_c4_split_characterization.py -q 2>&1 | tail -5'
```
Expected:全绿(锁现行为)。

- [ ] **Step 3: commit** — `test: add C4 stage2.5 split characterization (lock pre-move behavior)`

---

## Task 2 — 建包 + common.py(底座,先建)

**Files:**
- Create: `src/datasource/engines/stage2_5/__init__.py`、`src/datasource/engines/stage2_5/common.py`
- Modify: `scripts/stage2_5_injector.py`

- [ ] **Step 1: 建包** — `src/datasource/engines/stage2_5/__init__.py`:
  ```python
  """Stage2.5 注入器内聚子模块(批次 C4/C5 巨石拆分)。"""
  ```
- [ ] **Step 2: 建 common.py** — import header(stdlib + 复制主脚本被 body 引用的外部 import:`urlparse`、`from datasource.utils.coercion import is_stage2_number_placeholder, is_legacy_713_placeholder` 等按 F821)+ **逐字搬入** common 簇(见清单,body 一字不改)。
- [ ] **Step 3: 主脚本删原定义 + re-import** — 删 common 簇原定义;在主脚本 import 段之后插入(完整名单,`# noqa: F401 (C4 re-export)`):
  ```python
  from datasource.engines.stage2_5.common import (  # noqa: F401 (C4 re-export)
      _extract_domain, _normalize_parseable_http_url, _is_url_evidence_terminator,
      _collect_http_like_evidence, _extract_embedded_http_url, _iter_http_like_evidence,
      _extract_source_url, _attach_source_url, _is_https_url_evidence,
      _extract_domains_from_payload, _extract_domains_from_evidence,
      _is_placeholder_numeric, _has_valid_value, _coerce_float, _pct_change,
      _same_numeric_value, _calc_change_rate_pct, _calc_previous_from_change_rate_pct,
      _coerce_percent, _coerce_bool,
  )
  ```
- [ ] **Step 4: 校验**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && bash run_clean.sh python -m py_compile src/datasource/engines/stage2_5/common.py scripts/stage2_5_injector.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage2_5/common.py && bash run_clean.sh python -m pytest tests/test_stage25_c4_split_characterization.py tests/test_stage25_contract_replay.py -q 2>&1 | tail -5'
```
Expected:py_compile 无输出;flake8 无 F401/F811/F821;characterization + contract replay 全绿。F821 → 按 §清单尾 F821 规则补搬入 common 或补 import。
- [ ] **Step 5: commit** — `refactor: extract stage2.5 common base module (PR-C4)`

---

## Task 3 — fund_flow.py + 回收 `# C4-cleanup`(冻结门控,独立 commit)

**Files:**
- Create: `src/datasource/engines/stage2_5/fund_flow.py`
- Modify: `scripts/stage2_5_injector.py`、`src/datasource/engines/stage2/extraction_apply.py`、`src/datasource/engines/stage2/execution.py`

- [ ] **Step 1: 建 fund_flow.py** — import header(F821 确认的 common 名 + 外部)+ **逐字搬入** fund_flow 簇 12 函数(见清单)。**gate body 一字不改**。
- [ ] **Step 2: 主脚本删原定义 + re-import**(12 名,`# noqa: F401 (C4 re-export)`)。
- [ ] **Step 3: 回收 extraction_apply 跨脚本 import** — 把 `src/datasource/engines/stage2/extraction_apply.py` 的这段(L45–60):
  ```python
  try:
      # C4-cleanup: move shared fund_flow gate helpers out of scripts/stage2_5_injector.py.  # noqa: E501
      from scripts.stage2_5_injector import (
          _default_fund_flow_metric_basis,
          _infer_fund_flow_source_tier,
          _infer_fund_flow_window_evidence,
          _normalize_fund_flow_estimation,
      )
  except ImportError:  # pragma: no cover - direct script execution keeps scripts/ on sys.path  # noqa: E501
      # C4-cleanup: keep the existing direct-execution fallback until the shared module exists.  # noqa: E501
      from stage2_5_injector import (  # type: ignore
          _default_fund_flow_metric_basis,
          _infer_fund_flow_source_tier,
          _infer_fund_flow_window_evidence,
          _normalize_fund_flow_estimation,
      )
  ```
  替换为(删 try/except + `# C4-cleanup`,改指 src):
  ```python
  from datasource.engines.stage2_5.fund_flow import (
      _default_fund_flow_metric_basis,
      _infer_fund_flow_source_tier,
      _infer_fund_flow_window_evidence,
      _normalize_fund_flow_estimation,
  )
  ```
- [ ] **Step 4: 回收 execution.py 间接依赖** — `src/datasource/engines/stage2/execution.py` 当前从 extraction_apply import 3 个 fund_flow 名(L51–57):
  ```python
  from datasource.engines.stage2.extraction_apply import (
      _apply_extraction,
      _augment_extraction_metadata,
      _default_fund_flow_metric_basis,
      _infer_fund_flow_source_tier,
      _infer_fund_flow_window_evidence,
  )
  ```
  改为:extraction_apply 块只留 `_apply_extraction, _augment_extraction_metadata`,3 个 fund_flow 名改从 canonical 源 import:
  ```python
  from datasource.engines.stage2.extraction_apply import (
      _apply_extraction,
      _augment_extraction_metadata,
  )
  from datasource.engines.stage2_5.fund_flow import (
      _default_fund_flow_metric_basis,
      _infer_fund_flow_source_tier,
      _infer_fund_flow_window_evidence,
  )
  ```
- [ ] **Step 5: 全 repo 无残留跨脚本 fund_flow import**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && (rg -n "C4-cleanup|stage2_5_injector import _default_fund_flow|stage2_5_injector import \(" src/ && echo "RESIDUE(BAD)" || echo "NO-RESIDUE(OK)")'
```
Expected:`NO-RESIDUE(OK)`(extraction_apply 不再跨脚本 import,`# C4-cleanup` 已删)。
- [ ] **Step 6: import-time 冒烟(防环)+ 校验**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && bash run_clean.sh python -c "import scripts.stage2_5_injector; import datasource.engines.stage2.extraction_apply; import datasource.engines.stage2.execution; print(\"IMPORT-OK\")" && bash run_clean.sh python -m py_compile src/datasource/engines/stage2_5/fund_flow.py src/datasource/engines/stage2/extraction_apply.py src/datasource/engines/stage2/execution.py scripts/stage2_5_injector.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage2_5/fund_flow.py src/datasource/engines/stage2/extraction_apply.py src/datasource/engines/stage2/execution.py && bash run_clean.sh python -m pytest tests/test_stage25_c4_split_characterization.py tests/test_stage25_contract_replay.py tests/test_stage2_replay_harness.py -q 2>&1 | tail -6'
```
Expected:`IMPORT-OK`(无循环 import);py_compile/flake8 干净;characterization + Stage2.5 contract replay + Stage2 replay harness 全绿(证明 extraction_apply/execution repoint 后行为不变)。成环/失败 → 停-回报。
- [ ] **Step 7: commit** — `refactor: extract stage2.5 fund_flow gate module; reclaim extraction_apply cross-script import (PR-C4)`

---

## Task 4 — schema_coercion.py

**Files:**
- Create: `src/datasource/engines/stage2_5/schema_coercion.py`
- Modify: `scripts/stage2_5_injector.py`

- [ ] **Step 1: 建 schema_coercion.py** — import header(F821 确认的 common 名;若 `_coerce_stage2_results_to_schema` 调 fund_flow 簇则 `from datasource.engines.stage2_5.fund_flow import ...`)+ **逐字搬入** 5 函数。
- [ ] **Step 2: 主脚本删原定义 + re-import**(5 名)。
- [ ] **Step 3: 校验**(同 Task 2 Step 4 三连,换 `schema_coercion.py`;含 characterization + contract replay)。Expected:全绿。
- [ ] **Step 4: commit** — `refactor: extract stage2.5 schema_coercion module (PR-C4)`

---

## Task 5 — gap_sync.py

**Files:**
- Create: `src/datasource/engines/stage2_5/gap_sync.py`
- Modify: `scripts/stage2_5_injector.py`

- [ ] **Step 1: 建 gap_sync.py** — import header(F821 确认的 common 名 + 外部 `from datasource.utils.missing_items import append_missing_item` 等复制主脚本现有行)+ **逐字搬入** 11 函数。
- [ ] **Step 2: 主脚本删原定义 + re-import**(11 名)。
- [ ] **Step 3: 校验**(三连,换 `gap_sync.py`)。Expected:全绿。
- [ ] **Step 4: commit** — `refactor: extract stage2.5 gap_sync module (PR-C4)`

---

## Task 6 — manual_official.py(冻结区,独立 commit,最后)

**Files:**
- Create: `src/datasource/engines/stage2_5/manual_official.py`
- Modify: `scripts/stage2_5_injector.py`

- [ ] **Step 1: 建 manual_official.py** — import header(F821 确认的 common 名 + 外部 `from datasource.utils.source_trust import is_official_source_url` 等复制主脚本现有行)+ **逐字搬入** 11 函数。**allowlist 正规化 / URL 校验 body 一字不改**。
- [ ] **Step 2: 主脚本删原定义 + re-import**(11 名)。
- [ ] **Step 3: 校验**(三连,换 `manual_official.py`)。**额外**:characterization 中 manual_official 加码项逐项绿。Expected:全绿。
- [ ] **Step 4: commit** — `refactor: extract stage2.5 manual_official module — allowlist verbatim (PR-C4)`

---

## Task 7 — characterization 切新模块 + datetime tie-in + 全量验收

**Files:**
- Modify: `tests/test_stage25_c4_split_characterization.py`
- Modify(条件):Stage2.5 contract replay 的 datetime 冻结处

- [ ] **Step 1: 追加新模块直连 + `is` 身份断言**
```python
import importlib
COMMON = importlib.import_module("datasource.engines.stage2_5.common")
FF = importlib.import_module("datasource.engines.stage2_5.fund_flow")
SC = importlib.import_module("datasource.engines.stage2_5.schema_coercion")
GS = importlib.import_module("datasource.engines.stage2_5.gap_sync")
MO = importlib.import_module("datasource.engines.stage2_5.manual_official")

def test_new_modules_export_moved_names():
    assert hasattr(COMMON, "_coerce_float")
    assert hasattr(FF, "_infer_fund_flow_window_evidence")
    assert hasattr(SC, "_coerce_stage2_results_to_schema")
    assert hasattr(GS, "_rewrite_gap_monitor_after_injection")
    assert hasattr(MO, "_apply_manual_official_estimation_rule")

def test_moved_fn_identity_via_monolith():
    assert INJ._coerce_float is COMMON._coerce_float
    assert INJ._infer_fund_flow_window_evidence is FF._infer_fund_flow_window_evidence
    assert INJ._coerce_stage2_results_to_schema is SC._coerce_stage2_results_to_schema
    assert INJ._rewrite_gap_monitor_after_injection is GS._rewrite_gap_monitor_after_injection
    assert INJ._apply_manual_official_estimation_rule is MO._apply_manual_official_estimation_rule

def test_extraction_apply_uses_canonical_fund_flow():
    # C2 cross-script reclaim:Stage2 extraction_apply 与 Stage2.5 注入器同一对象
    EA = importlib.import_module("datasource.engines.stage2.extraction_apply")
    assert EA._default_fund_flow_metric_basis is FF._default_fund_flow_metric_basis
```

- [ ] **Step 2: datetime tie-in 检查**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && grep -rnE "datetime\.(now|utcnow|today)" src/datasource/engines/stage2_5/*.py || echo "NO-DATETIME-NOW (OK)"'
```
**若命中**:在 Stage2.5 contract replay(`tests/test_stage25_contract_replay.py`)的 datetime 冻结处补该模块(参 `_freeze_stage2_datetime` 模式);重跑 contract replay 确认 byte-stable。**若 `NO-DATETIME-NOW`**:跳过。

- [ ] **Step 3: 全量验收**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && bash run_clean.sh python -m pytest -q 2>&1 | tail -8 && bash run_clean.sh python -m py_compile src/datasource/engines/stage2_5/*.py scripts/stage2_5_injector.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage2_5/ && wc -l scripts/stage2_5_injector.py'
```
Expected:pytest 全绿(passed = baseline N + 新 characterization);py_compile 无输出;flake8 干净;主脚本行数较 4211 显著下降。contract replay 非 byte-stable / 任一 fail → 停-回报(逐簇 revert 定位)。

- [ ] **Step 4: 残留校验(5 组主脚本无本地定义)**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && rg -n "^def _coerce_float|^def _coerce_stage2_results_to_schema|^def _apply_manual_official_estimation_rule|^def _infer_fund_flow_window_evidence|^def _rewrite_gap_monitor_after_injection" scripts/stage2_5_injector.py || echo "NO-LOCAL-DEF (OK)"; rg -n "^def inject_websearch_data|^def _apply_macro_entry|^def main" scripts/stage2_5_injector.py && echo "RETAINED-IN-MONOLITH (OK)"'
```
Expected:第一条 `NO-LOCAL-DEF`;第二条命中 3 个(C5 簇仍在主脚本)。

- [ ] **Step 5: commit** — `test: assert C4 stage2.5 split modules behave identically post-move (is-identity + cross-script reclaim)`

---

## Task 8 — 文档同步 + 隔离断言 + 回报(尾任务)

**Files:**
- Modify: `optimization/20260610_refactor_plan/TODOS.md`

- [ ] **Step 1: TODOS.md** — C4 行 `[ ]` → `[x]`(附 squash SHA 占位),"当前焦点"改为 PR-C5,并在 C5 行补注"engines/stage2_5/ 续接 entry_mergers/trend_backfill/core/cli";commit `docs: mark PR-C4 complete in refactor TODOS`。
- [ ] **Step 2: 命令漂移检查**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && bash run_clean.sh python -m pytest tests/test_manual_template.py tests/test_stage4_docs.py -q 2>&1 | tail -3'
```
Expected:全绿(本 PR 不改文档命令示例)。
- [ ] **Step 3: 隔离断言**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c4-stage25-split && git status --short && ls /mnt/d/cursor/datasource/data/runs/ 2>/dev/null | tail -3'
```
Expected:`git status` 只含本 PR 新增/修改(6 新文件含 `__init__` + 主脚本 + extraction_apply + execution + 新测试 + TODOS.md);无 `data/`/`reports/`/`logs/` 业务产物。
- [ ] **Step 4: 临时产物清理 + 完成回报**
  - 实际 commit 列表;全量 passed 数(baseline → after);主脚本行数(4211 → ?);
  - 6 模块依赖图确认(common 无 intra;fund_flow/schema_coercion/gap_sync/manual_official → common;无 module→主脚本反向、无环);
  - **cross-script reclaim 确认**:`# C4-cleanup` 已删、extraction_apply/execution 改指 `engines.stage2_5.fund_flow`、`is` 身份跨包成立、import-time 冒烟 OK;
  - datetime tie-in 结论;contract replay + Stage2 replay harness byte-stable;
  - 冻结簇(manual_official/fund_flow)characterization 加码逐项绿;
  - 任何计划外改动(理想为 flake8/F821 机械收敛)逐条列出。

---

## 评审方(Claude)checklist

1. **计划符合度**:8 Task 逐项完成;独立验证"计划外改动"仅限 flake8/F821 机械收敛。
2. **冻结区 diff**:5 组 body 逐字未变(`git diff` 只见位置移动 + import);**重点逐字符核验** manual_official(allowlist 正规化/URL 校验)与 fund_flow gate(source_tier/window_evidence/estimated 规则);`_coerce_float` 等未并入 utils/coercion。
3. **cross-script reclaim**:`# C4-cleanup` 全删;extraction_apply + execution 改从 `engines.stage2_5.fund_flow` import;`EA._default_fund_flow_metric_basis is FF._default_fund_flow_metric_basis`;import-time 冒烟无环。
4. **依赖图**:common 无 intra;4 簇 → common(+ schema_coercion 可能 → fund_flow);无 module→主脚本反向;注入器不 import engines/stage2;`engines/stage2/extraction_apply → engines/stage2_5/fund_flow` 单向无环。
5. **测试**:characterization before/after 逐项一致 + import-surface(全 ~55 名)+ `is` 身份(5 模块 + 跨包 reclaim);Stage2.5 contract replay byte-stable;Stage2 replay harness 绿;datetime tie-in 正确。
6. **合入**:默认 squash;合入前 `git diff main 分支` 空;合入后 `git worktree remove` + 删分支;下一步生成 C5 plan(engines/stage2_5/ 续接)。

---

## Self-Review(规划方自查)

- **Spec 覆盖**:§2 In-scope 5 模块 → Task 2–6;决策 A(新包)→ Task 2 建包;决策 B(fund_flow 只 gate)→ Task 3 清单 + "不搬"列 entry;决策 C(common 底座)→ Task 2 先行 + F821 规则;决策 D(reclaim)→ Task 3 Step 3–6;决策 F(冻结独立 commit)→ Task 3/6;§7 characterization + datetime → Task 1/7;§8 验证 → Task 3/7;§11 验收 → Task 7/8。✅ 全覆盖。
- **Placeholder 扫描**:无 TBD;value-table expected 由 Codex 实跑(§偏离 3 声明);common 成员 F821 收敛(§偏离 4 声明);repoint 给完整 old/new;commit 文案全给。✅
- **一致性**:模块名/函数名/re-import 名单在清单、Task、characterization `C4_MOVED_NAMES`、`is` 身份断言间一致;依赖序 common→fund_flow→schema_coercion→gap_sync→manual_official 一致;worktree `.worktrees/codex-batch-c4-stage25-split` + 分支 `codex/batch-c4-stage25-split` 全程一致;baseline `1179 passed, 3 skipped` 一致。✅
- **离线 / 冻结**:全程无真实 API;冻结簇 body 逐字 + 独立 commit + 加码 characterization;coercion 仅搬位置。✅
