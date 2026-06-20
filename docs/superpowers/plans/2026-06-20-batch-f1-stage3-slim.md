# PR-F1 执行计划:stage3_pring_analyzer 入口瘦身(relocate → engines/stage3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 把 `stage3_pring_analyzer.py`(867 行)的 gate/质量编排 glue 逐字搬到新 `engines/stage3/`,脚本瘦到 ≤300(re-export 薄壳 + 转发 main),repoint 4 测试文件的 monkeypatch 目标,满足"全部入口 ≤300"。

**Architecture:** C6/C7 式纯 relocate:`core.py`(helper + `_run_analysis`)+ `cli.py`(parse_args + main);逐字搬移、零业务逻辑改动;monkeypatch 必须 repoint 到搬移后 owner 模块(core/cli);golden(test_pring_scoring_golden)byte-stable 为硬门。

**Tech Stack:** Python;pytest(test_stage3_guard + pring golden);flake8/py_compile;git worktree;Windows + WSL。

> Spec:`docs/superpowers/specs/2026-06-20-batch-f1-stage3-slim-design.md`(§3 归属 / §4 repoint 表)。建在 main `83d3bc6`;独立 worktree。

---

## 偏离声明
- 纯 relocate:逐字搬 + repoint;**唯一可接受的非搬移改动 = 为破 import 环的延迟 import**(若 core↔cli 或 core↔某 util 成环,main 内延迟 import,同 C7);body 不漂移。
- golden byte-stable 硬门:**绝不更新 test_pring_scoring_golden 的 golden**。
- 不动 `calculators/pring_analyzer.py`、gate/policy utils。

## 环境头(零上下文)
- **Bash 工具坏**;命令经 `wsl -e bash -lc '...'`;pytest/flake8 走 `run_clean.sh`;只读 git 用 PowerShell。worktree 根执行。
- worktree:`git worktree add .worktrees/codex-batch-f1-stage3-slim -b codex/batch-f1-stage3-slim main` + 置备 `.env`/`.venv`/`logs`/`reports` + `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1`。
- 硬约束:不重跑真实流水线/Tavily;不碰 `data/runs`/`data/trend_history`;离线。**绝不 `STAGE2_REPLAY_UPDATE_GOLDEN`/不更 pring golden**。
- Commit:Conventional。

## Task 0 — worktree + baseline
- [ ] 建 worktree + `bash run_clean.sh python -m pytest -q 2>&1 | tail -4`(记 baseline N=1512)+ `wc -l scripts/stage3_pring_analyzer.py`(867)+ `bash run_clean.sh python scripts/stage3_pring_analyzer.py --help > /tmp/f1_help.txt 2>&1`。失败→停-回报。

## Task 1 — 新建 engines/stage3 + 逐字搬移
**Files:** Create `src/datasource/engines/stage3/__init__.py`、`core.py`、`cli.py`
- [ ] **Step 1** `core.py`:逐字搬 `MIN_COMPLETENESS_DEFAULT`(40)+ 全部 helper(43–409)+ `_run_analysis`(410–766);补 import header(F821 定):stdlib(json/os/time/asyncio?/Path/typing)+ `from datasource import get_manager`、`calculators.pring_analyzer.PringAnalyzer`、`models.market_data_contract.MarketDataContract`、`utils.contract_validation.validate_pring_result`、`utils.gate_formatting.*`、`utils.json_io.atomic_write_json`、`utils.missing_items.flatten_missing_items as _shared_flatten_missing_items`、`utils.pipeline_gate.*`、`utils.pipeline_quality_state.build_pipeline_quality_state`、`utils.policy_rules.*`、`utils.run_paths.build_run_paths_from_reference`(+ run_lock 若 helper 用)。
- [ ] **Step 2** `cli.py`:逐字搬 `parse_args`(767–832)+ `main`(833–end);`from datasource.engines.stage3.core import _run_analysis`(+ 其它 main 调的 helper);import `argparse`/`asyncio`/`from datasource.utils.run_lock import DailyRunLock, run_dir_from_artifact`;`if main 与 core 成环` → main 内延迟 import `_run_analysis`(同 C7)。`MIN_COMPLETENESS_DEFAULT` 从 core import(若 argparse default 用)。
- [ ] **Step 3** import 冒烟:`bash run_clean.sh python -c "import datasource.engines.stage3.core, datasource.engines.stage3.cli; print('NOCYCLE-OK')"`。成环→延迟 import 修。
- [ ] **Step 4** py_compile + `flake8 src/datasource/engines/stage3/`(继承长行加 per-file-ignore E501,F401/F821 仍检)。commit `refactor: relocate stage3 analysis+cli into engines/stage3 (PR-F1)`

## Task 2 — 脚本瘦为 re-export 薄壳
**Files:** Modify `scripts/stage3_pring_analyzer.py`
- [ ] **Step 1** 改为:模块 docstring + `from datasource.engines.stage3.core import (` 全部被测/被用名(`_run_analysis`、`_require_data_completeness`、`_resolve_gap_monitor_path`、`_collect_*`、`MIN_COMPLETENESS_DEFAULT` 等,`# noqa: F401`)+ `from datasource.engines.stage3.cli import main, parse_args  # noqa: F401` + `if __name__ == "__main__": main()`。目标 ≤300(实际应 ~30–60)。
- [ ] **Step 2** `wc -l scripts/stage3_pring_analyzer.py` ≤300;`bash run_clean.sh python scripts/stage3_pring_analyzer.py --help` 与 `/tmp/f1_help.txt` diff 空。commit `refactor: thin stage3 entry to re-export shim (PR-F1)`
> 中途此时 stage3 测试可能 RED(patch 未 repoint)——预期,Task 3 转绿。

## Task 3 — repoint 4 测试文件(§4 表)
**Files:** Modify `tests/test_stage3_guard.py`、`tests/test_stage_validation_wiring.py`、`tests/test_daily_writer_locks.py`(`test_pring_scoring_golden.py` 不动)
- [ ] **Step 1** `test_stage3_guard.py`:加 `from datasource.engines.stage3 import core as s3core`;把 `setattr(s3, "MarketDataContract"/"PringAnalyzer"/"get_manager", ...)` 全改 `setattr(s3core, ...)`;调用 `s3._run_analysis`/`_require_data_completeness`/`_resolve_gap_monitor_path` 全改 `s3core.*`。
- [ ] **Step 2** `test_stage_validation_wiring.py`:`setattr(stage3, "MarketDataContract"/"PringAnalyzer"/"get_manager"/"validate_pring_result"/"atomic_write_json", ...)` + 调 `_run_analysis` → 改指 `engines.stage3.core`(加 `import ... core as ...`)。
- [ ] **Step 3** `test_daily_writer_locks.py`:`setattr(stage3, "DailyRunLock", ...)`、`setattr(stage3.asyncio, "run", ...)`、`stage3.main()` → 改指 `engines.stage3.cli`(加 `from datasource.engines.stage3 import cli as stage3_cli`,patch/调用用 stage3_cli)。
- [ ] **Step 4** `test_pring_scoring_golden.py` **不动**(`from scripts.stage3_pring_analyzer import _run_analysis` 经薄壳 re-export 仍有效;纯调用无 patch)。
- [ ] **Step 5** 校验:`bash run_clean.sh python -m pytest tests/test_stage3_guard.py tests/test_pring_scoring_golden.py tests/test_stage_validation_wiring.py tests/test_daily_writer_locks.py -q`。**golden byte-stable PASS**(绝不更 golden);全绿。commit `test: repoint stage3 monkeypatches to engines/stage3 (PR-F1)`

## Task 4 — 全量验收
- [ ] 全量 `bash run_clean.sh python -m pytest -q 2>&1 | tail -5`(= baseline N,无回归)+ `py_compile` + `flake8 src/datasource/engines/stage3/`。
- [ ] `wc -l scripts/stage3_pring_analyzer.py` ≤300;`--help` diff 空;`rg "^async def _run_analysis|^def _require_data_completeness" scripts/stage3_pring_analyzer.py` 为空(逻辑已搬)。
- [ ] import 冒烟无环;`rg "from scripts|import scripts" src/datasource/engines/stage3` 为空(无反向 import)。

## Task 5 — 文档 + TODOS(含 stage4_risk_review 豁免留痕,关掉验收2)
- [ ] **Step 1** CLAUDE.md「流水线阶段→代码模块映射」把 Stage3 行更新:`stage3_pring_analyzer.py → engines/stage3/(core 编排+gate / cli)+ calculators/pring_analyzer + calculators/pring/...`;AGENTS/SCRIPTS 同步。跑 `pytest tests/test_manual_template.py tests/test_stage4_docs.py -q` 绿。commit `docs: map stage3 entry to engines/stage3 (PR-F1)`
- [ ] **Step 2(stage4_risk_review 豁免)** — 这是验收2 收尾的另一半,本 PR 一并记:
  - `optimization/20260610_refactor_plan/REFACTOR_PLAN.md` 全局验收处把"scripts/ 全部入口 ≤300"细化为:**有 engines 逻辑的 stage 入口(stage1/2/2.5/3)≤300;`stage4_risk_review.py` 为有意 standalone、不 import datasource 包的只读 review gate(由 `test_run_path_does_not_import_datasource_package` 强制),豁免 engines 瘦身**。
  - `scripts/stage4_risk_review.py` 顶部 docstring 加一句:`# 有意 standalone:本脚本不得 import datasource 包(由 test_run_path_does_not_import_datasource_package 强制),故 run_paths/run_lock 经 importlib 按 path 加载;不要将其逻辑搬入 engines/(会破该契约)。`(仅注释,不动任何代码逻辑;跑 `tests/test_stage4_risk_review.py` 确认 standalone 测试仍绿。)
  - TODOS.md 记 F1(stage3 ≤300 达成)+ stage4_risk_review 豁免(验收2 收尾)。commit `docs: slim stage3 + document stage4_risk_review standalone exemption (PR-F1)`

## Task 6 — 隔离 + 回报
- [ ] 隔离:`git status --short` 仅本 PR 文件;无 data/reports 业务产物。
- [ ] 回报:commit 列表、全量 passed、脚本行数(867→N≤300)、golden byte-stable 确认、test_stage3_guard 全绿、4 测试 repoint 完成、`--help` diff 空、无反向 import、计划外改动(理想仅 flake8/延迟-import)。

---

## 评审 checklist
1. helper + `_run_analysis` + parse_args + main 逐字搬(无 body 漂移);唯一非搬移 = 破环延迟 import(若有)。
2. 脚本 ≤300、re-export 薄壳、`--help` diff 空;`engines/stage3` 无反向 import、无环。
3. **golden byte-stable**(test_pring_scoring_golden 未更新);`test_stage3_guard` 全绿(gate 行为不变)。
4. 4 测试 repoint:patch/调用打到 core(MarketDataContract/PringAnalyzer/get_manager/validate_pring_result/atomic_write_json/_run_analysis/_require_data_completeness)与 cli(DailyRunLock/asyncio/main);golden 文件不动。
5. 不动 calculators/pring_analyzer 与 gate/policy utils;全量无回归;文档同步。
6. 合入 main 之上 squash;清 worktree/分支。

## Self-Review
- Spec 覆盖:§3 结构 → Task 1/2;§4 repoint → Task 3;§5 安全网 → Task 3/4。✅
- Placeholder:move 范围(行号)+ import header(F821)+ repoint 表 + 命令 Expected 全给;glue 精确归属交 F821(同 C-batch 惯例)。✅
- 一致性:core/cli 划分、repoint 目标(core vs cli)、golden 不动、分支名一致。✅
- 风险:假绿(值断言守)、body 漂移(golden+guard)、成环(延迟 import)、>300(全搬走),均显式。✅
