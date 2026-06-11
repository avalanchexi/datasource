# 批次 B:脚本命名收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `scripts/` 收敛为两层(主链 + `scripts/tools/`),消灭 `utility/`、`archive/` 历史层级;8 个有活文档引用的旧路径留 runpy shim 一个版本周期。

**Architecture:** 纯移动/改名 + 两个测试文件的精确行级修改 + 活文档同步,零业务行为变更。所有判断已在规划期定死(基于 HEAD `72dc42c` 实测);任何"Expected 空输出"不空 → 停止回报,不要即兴处理。**文档修复只允许出现在 Task 4 的原子 commit 内,不得自行新增计划外 commit。**

**Tech Stack:** git mv、runpy shim、pytest、sed。无新依赖。

**Spec:** `docs/superpowers/specs/2026-06-12-batch-b-script-naming-design.md`(已评审)。

---

## 环境头(必读)

- 所有命令在 WSL/Linux shell、worktree 根目录执行;主 checkout `/mnt/d/cursor/datasource` 记为 `$MAIN`,只读取材。
- `.gitignore` 忽略 `.env/.venv/data/logs/reports`,worktree 中不存在,Task 0 置备。
- Python 一律 `bash run_clean.sh python ...`。零网络(Task 0 pip bootstrap 除外)。
- **主链七脚本与其内容一律不动**:`stage1_data_collector.py`、`stage2_unified_enhancer.py`、`stage2_5_injector.py`、`stage3_pring_analyzer.py`、`stage4_risk_review.py`、`stage4_report_generator.py`、`check_monthly_freshness.py`;shell 基建(`runtime_env.sh` 等)不动。
- 测试修改仅限本计划明示的两个文件共 4 行;其余测试一律不动。

---

### Task 0: 置备 worktree

- [ ] **Step 1: 创建并置备**

```bash
MAIN=/mnt/d/cursor/datasource
WT="$MAIN/.worktrees/codex-batch-b-script-naming"
cd "$MAIN"
git worktree add "$WT" -b codex/batch-b-script-naming
cp "$MAIN/.env" "$WT/.env"
mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv"
mkdir -p "$WT/data/runs/20260522" "$WT/data/trend_history"
cp "$MAIN/data/runs/20260522/market_data_stage2.json" \
   "$MAIN/data/runs/20260522/websearch_results_manual.json" \
   "$MAIN/data/runs/20260522/market_data_complete.json" \
   "$MAIN/data/runs/20260522/gap_monitor.json" \
   "$WT/data/runs/20260522/"
cp -r "$MAIN/data/trend_history/min" "$WT/data/trend_history/min"
cd "$WT"
DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V
```

Expected: `[OK] .venv bootstrap complete` + Python 版本。

- [ ] **Step 2: baseline**

```bash
bash run_clean.sh python -m pytest -q 2>&1 | tail -3
```

Expected: 全绿(参考:1011 passed, 3 skipped)。失败 → 停止回报。

> 以下所有命令在 `$WT` 根执行。

### Task 1: 移动改名(18 个)+ 两个测试的行级修改(原子提交)

**Files:** Create: `scripts/tools/__init__.py`(空文件);Move: 下表 19 项;Modify: `tests/test_fix_estimated_verified.py`(1 行)、`tests/test_fund_flow_pipeline.py`(3 行)

- [ ] **Step 1: 建包 + git mv(逐条执行,完整映射表)**

```bash
mkdir -p scripts/tools && touch scripts/tools/__init__.py && git add scripts/tools/__init__.py
git mv scripts/backfill_trend_history_event_dates.py scripts/tools/trend_history_backfill_event_dates.py
git mv scripts/trend_history_backfill.py             scripts/tools/trend_history_backfill.py
git mv scripts/trend_history_scan.py                 scripts/tools/trend_history_scan.py
git mv scripts/backfill_fund_flow_series.py          scripts/tools/fund_flow_backfill_series.py
git mv scripts/fund_flow_analysis.py                 scripts/tools/fund_flow_analysis.py
git mv scripts/index_trend_analysis.py               scripts/tools/index_trend_analysis.py
git mv scripts/fix_estimated_verified.py             scripts/tools/estimated_fix_verified.py
git mv scripts/sanitize_market_data.py               scripts/tools/market_data_sanitize.py
git mv scripts/recap_consistency_check.py            scripts/tools/recap_consistency_check.py
git mv scripts/compare_stage2_runs.py                scripts/tools/stage2_compare_runs.py
git mv scripts/stage2_health_check.py                scripts/tools/stage2_health_check.py
git mv scripts/stage2_low_score_audit.py             scripts/tools/stage2_low_score_audit.py
git mv scripts/check_stage2_inputs.py                scripts/tools/stage2_check_inputs.py
git mv scripts/setup_stage2_search_env.py            scripts/tools/stage2_setup_search_env.py
git mv scripts/gap_monitor_to_manual_template.py     scripts/tools/manual_template_from_gap_monitor.py
git mv scripts/run_snapshot.py                       scripts/tools/run_snapshot.py
git mv scripts/utility/manual_fund_flow_updater.py   scripts/tools/fund_flow_manual_updater.py
git mv scripts/utility/fund_flow_daily_sync.py       scripts/tools/fund_flow_daily_sync.py
```

- [ ] **Step 2: 测试修改(精确 4 行,不许多改)**

`tests/test_fix_estimated_verified.py` 第 7 行:

```python
import scripts.fix_estimated_verified as fixer
```

改为

```python
import scripts.tools.estimated_fix_verified as fixer
```

`tests/test_fund_flow_pipeline.py` 三处:

L159:`updater_path = PROJECT_ROOT / "scripts" / "utility" / "manual_fund_flow_updater.py"` → `updater_path = PROJECT_ROOT / "scripts" / "tools" / "fund_flow_manual_updater.py"`

L199:`sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "utility"))` → `sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "tools"))`

L240:`from manual_fund_flow_updater import update_fund_flow` → `from fund_flow_manual_updater import update_fund_flow`

(L164 的 spec 模块名字符串 `"manual_fund_flow_updater"` 不改——importlib spec 名任意。)

- [ ] **Step 3: 验证 + commit**

```bash
bash run_clean.sh python -m pytest tests/test_fix_estimated_verified.py tests/test_fund_flow_pipeline.py -q 2>&1 | tail -2
for t in trend_history_backfill_event_dates trend_history_backfill trend_history_scan fund_flow_backfill_series fund_flow_analysis index_trend_analysis estimated_fix_verified market_data_sanitize recap_consistency_check stage2_compare_runs stage2_health_check stage2_low_score_audit stage2_check_inputs stage2_setup_search_env manual_template_from_gap_monitor run_snapshot fund_flow_manual_updater fund_flow_daily_sync; do
  bash run_clean.sh python scripts/tools/$t.py --help >/dev/null 2>&1 && echo "$t OK" || echo "$t HELP-FAIL(若该脚本本无 --help 且直跑есть副作用,记录后继续)"
done
git add -A && git commit -m "refactor: move non-pipeline scripts into scripts/tools with domain-first names"
```

Expected: 两个测试文件全绿;`--help` 大多数 OK(个别无 argparse 的工具报 HELP-FAIL 属预期,记录文件名即可,不算失败)。

### Task 2: 为 8 个有活文档引用的旧路径建 runpy shim

**Files:** Create: `scripts/trend_history_backfill.py`、`scripts/trend_history_scan.py`、`scripts/sanitize_market_data.py`、`scripts/compare_stage2_runs.py`、`scripts/stage2_health_check.py`、`scripts/stage2_low_score_audit.py`、`scripts/setup_stage2_search_env.py`、`scripts/run_snapshot.py`

- [ ] **Step 1: 按模板逐个创建**(`<OLD>`=旧文件名,`<NEW>`=tools 下新文件名,映射:trend_history_backfill→trend_history_backfill.py、trend_history_scan→trend_history_scan.py、sanitize_market_data→market_data_sanitize.py、compare_stage2_runs→stage2_compare_runs.py、stage2_health_check→stage2_health_check.py、stage2_low_score_audit→stage2_low_score_audit.py、setup_stage2_search_env→stage2_setup_search_env.py、run_snapshot→run_snapshot.py)

```python
"""DEPRECATED path shim (refactor batch B, 2026-06): moved to scripts/tools/<NEW>.

Forwarder kept one release cycle; removal tracked in
optimization/20260610_refactor_plan/TODOS.md.
"""

import runpy
import sys
from pathlib import Path

_NEW = Path(__file__).resolve().parent / "tools" / "<NEW>"
print("[DEPRECATED] scripts/<OLD> -> scripts/tools/<NEW>; forwarding.", file=sys.stderr)
runpy.run_path(str(_NEW), run_name="__main__")
```

- [ ] **Step 2: shim 冒烟(转发 + 退出码)**

```bash
for s in trend_history_backfill trend_history_scan sanitize_market_data compare_stage2_runs stage2_health_check stage2_low_score_audit setup_stage2_search_env run_snapshot; do
  out=$(bash run_clean.sh python scripts/$s.py --help 2>&1); code=$?
  echo "$s exit=$code deprecated=$(echo "$out" | grep -c DEPRECATED)"
done
```

Expected: 每行 `deprecated=1`;exit 码与 Task 1 Step 3 中对应新路径直跑一致(argparse 的 `--help` 为 0)。

- [ ] **Step 3: Commit**

```bash
git add scripts/*.py && git commit -m "feat: add deprecation shims for relocated tool scripts"
```

### Task 3: 归档 utility 死脚本与 scripts/archive

**Files:** Move: `scripts/utility/` 剩余 7 个 → `archive/py_unused/scripts_utility/`;`scripts/archive/`(6 文件 + README)→ `archive/py_unused/scripts_archive/`

- [ ] **Step 1: 归档**

```bash
mkdir -p archive/py_unused/scripts_utility archive/py_unused/scripts_archive
git mv scripts/utility/background_scan_120d_generator.py scripts/utility/background_scan_validator.py \
       scripts/utility/calculate_na_data.py scripts/utility/generate_background_scan.py \
       scripts/utility/generate_network_report.py scripts/utility/tushare_pro_report_patch.py \
       scripts/utility/validate_data_quality.py \
       archive/py_unused/scripts_utility/
git mv scripts/archive/ai_auto_executor.py scripts/archive/cn10y_chart.py \
       scripts/archive/cn10y_interactive_chart.py scripts/archive/fetch_csi_indices_snapshot.py \
       scripts/archive/generate_index_charts.py scripts/archive/README.md \
       archive/py_unused/scripts_archive/
rmdir scripts/utility scripts/archive 2>/dev/null || true
rm -rf scripts/utility/__pycache__ scripts/archive/__pycache__ 2>/dev/null || true; rmdir scripts/utility scripts/archive 2>/dev/null || true
ls scripts/
```

Expected: `scripts/` 只剩主链 7 脚本 + 8 个 shim + shell 基建(`runtime_env.sh`/`bootstrap_venv.sh`/`env_probe.sh`)+ `__init__.py` + `tools/`;无 `utility`/`archive`/`legacy`。
(若 `scripts/archive` 中有上表未列的文件,停止回报——HEAD 漂移。)

- [ ] **Step 2: py 引用闸 + commit**

```bash
grep -rnE "scripts/(utility|archive)/|scripts\.(utility|archive)\.|scripts\.(fix_estimated_verified|gap_monitor_to_manual_template|backfill_trend_history_event_dates|backfill_fund_flow_series|check_stage2_inputs|compare_stage2_runs|sanitize_market_data|setup_stage2_search_env)\b" \
  src scripts tests --include='*.py' 2>/dev/null
```

Expected: 空输出(exit 1)。

```bash
git commit -m "refactor: archive dead utility and self-archived scripts dirs"
```

### Task 4: 活文档同步(单一原子 commit)

**Files:** Modify: `SCRIPTS.md`、`CLAUDE.md`、`AGENTS.md`、`README.md`(其余 runbook 经核实无旧路径引用,不动)

- [ ] **Step 1: 全局路径替换(8 对,作用于上述 4 个文件)**

```bash
for f in SCRIPTS.md CLAUDE.md AGENTS.md README.md; do
  sed -i \
    -e 's|scripts/trend_history_scan\.py|scripts/tools/trend_history_scan.py|g' \
    -e 's|scripts/trend_history_backfill\.py|scripts/tools/trend_history_backfill.py|g' \
    -e 's|scripts/run_snapshot\.py|scripts/tools/run_snapshot.py|g' \
    -e 's|scripts/stage2_health_check\.py|scripts/tools/stage2_health_check.py|g' \
    -e 's|scripts/stage2_low_score_audit\.py|scripts/tools/stage2_low_score_audit.py|g' \
    -e 's|scripts/compare_stage2_runs\.py|scripts/tools/stage2_compare_runs.py|g' \
    -e 's|scripts/setup_stage2_search_env\.py|scripts/tools/stage2_setup_search_env.py|g' \
    -e 's|scripts/sanitize_market_data\.py|scripts/tools/market_data_sanitize.py|g' \
    "$f"
done
```

- [ ] **Step 2: 两处结构性改写(精确替换)**

`AGENTS.md`(原 L18)把

```
- Long jobs: `scripts/`（含 `trend_history_scan.py`, `trend_history_backfill.py`, `run_snapshot.py`）；历史/低频脚本已归档至 `archive/py_unused/legacy/`，当前保留但不属于 Stage1-4 主流程的手工辅助脚本见 `scripts/utility/`；`scripts/archive/` 为归档/手工分析脚本，不跑正常 Stage1-4。
```

改为

```
- Long jobs: `scripts/tools/`（含 `trend_history_scan.py`, `trend_history_backfill.py`, `run_snapshot.py` 等运维工具，`<domain>_<verb>` 命名）；历史/低频脚本统一归档至 `archive/py_unused/`（`legacy/`、`scripts_utility/`、`scripts_archive/` 子目录），不跑正常 Stage1-4。
```

`SCRIPTS.md` 把章节标题

```
### 6. sanitize_market_data.py ✅ SUPPORT
```

改为

```
### 6. market_data_sanitize.py（原 sanitize_market_data.py）✅ SUPPORT
```

- [ ] **Step 3: md 文档闸 + 契约测试 + commit**

```bash
grep -rnE "scripts/(trend_history_scan|trend_history_backfill|run_snapshot|stage2_health_check|stage2_low_score_audit|compare_stage2_runs|setup_stage2_search_env|sanitize_market_data|fix_estimated_verified|gap_monitor_to_manual_template|backfill_trend_history_event_dates|backfill_fund_flow_series|check_stage2_inputs|fund_flow_analysis|index_trend_analysis|recap_consistency_check)\.py|scripts/(utility|archive)/" \
  SCRIPTS.md CLAUDE.md AGENTS.md README.md docs/AI报告生成标准流程_V3.3.md docs/AI背景扫描报告执行完整手册.md templates/AI_EXECUTION_CHECKLIST.md docs/手动更新资金流向数据指南.md 2>/dev/null
bash run_clean.sh python -m pytest tests/test_manual_template.py tests/test_stage4_docs.py -q 2>&1 | tail -2
```

Expected: grep 空输出(exit 1);契约测试全绿。

```bash
git add SCRIPTS.md CLAUDE.md AGENTS.md README.md && git commit -m "docs: point runbooks at scripts/tools paths"
```

### Task 5: 计划状态同步

**Files:** Modify: `optimization/20260610_refactor_plan/TODOS.md`

- [ ] **Step 1: TODOS 更新**

批次 B 小节:`- [ ] 生成 PR-B 执行计划` 改 `[x]`;`- [ ] **PR-B**:...` 与子项 `Codex 执行 → Claude 评审 → 合入` 改 `[~]`;`- [ ] shim 保留一个版本周期后删除(到期提醒)` 改为:

```
- [ ] shim 删除(8 个:trend_history_backfill/trend_history_scan/sanitize_market_data/compare_stage2_runs/stage2_health_check/stage2_low_score_audit/setup_stage2_search_env/run_snapshot)——到期条件:批次 C 全部合入后
```

- [ ] **Step 2: Commit**

```bash
git add optimization/20260610_refactor_plan/TODOS.md && git commit -m "docs: track batch-b progress and shim expiry"
```

### Task 6: 终验 + 回报(留在分支,不合并)

- [ ] **Step 1: 终验**

```bash
bash run_clean.sh python -m pytest -q 2>&1 | tail -3
bash run_clean.sh python -m pytest optimization/20260610_refactor_plan/audit -q 2>&1 | tail -2
bash run_clean.sh python -m compileall -q src/datasource scripts && echo "compileall OK"
git status --short
```

Expected: 全绿(数量应与 baseline 一致——本批不增删测试,只改 4 行);`compileall OK`;status 干净。

- [ ] **Step 2: 回报**

留在 `codex/batch-b-script-naming` 分支。回报:各 Task SHA、baseline/终验 pytest 输出、Task 3 Step 2 与 Task 4 Step 3 两道闸的实际输出、HELP-FAIL 记录清单、偏差清单。

**后续(评审方,不在本计划):** 评审 → squash 合入 → worktree/分支清理 → TODOS 勾选。
