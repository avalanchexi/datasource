# 批次 A:仓库清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一个 PR 完成仓库清理:移除/归档死代码与散落产物、合并 archive 双目录、归档历史 optimization 目录、logs 轮转、最小 pre-commit——全部为机械移动/删除,零业务行为变更。

**Architecture:** 所有归档统一进 `archive/py_unused/`,**保留来源子目录结构**(`root/`、`legacy/`、`datasource/<原相对路径>`、`tests/`、`examples/`)以避免同名冲突(`background_scan_120d.py` 在 `unused_py` 与 `scripts/legacy` 各有一份)。每个删除/移动决策已在规划期用 rg + 批次 0 审计(`optimization/20260610_refactor_plan/audit/used_unused.json`)核verified,执行者不做判断;若复核 grep 出现计划未预期的输出,停止并回报,不要即兴处理。

**Tech Stack:** git mv / git rm、pytest、compileall。无新依赖。

**Spec:** `optimization/20260610_refactor_plan/REFACTOR_PLAN.md` §4(已经两轮评审)。

---

## 环境头(必读)

- 所有命令在 WSL/Linux shell、**worktree 根目录**执行(Task 0 置备);主 checkout `/mnt/d/cursor/datasource` 记为 `$MAIN`,只读取材。
- `.gitignore` 忽略 `.env/.venv/data/logs/reports`,worktree 中不存在,Task 0 置备。
- Python 一律 `bash run_clean.sh python ...`,不直跑。
- **硬约束:** 零网络调用(Task 0 的 pip bootstrap 除外);不改任何业务代码行为;`models/pring_result_contract.py`、`src/datasource/providers/stage2_structured/*`、`src/datasource/utils/yahoo_finance.py`、`src/datasource/mcp_adapter.py`、`src/datasource/utils/mcp_tools.py` **本批一律不动**(最后两项因 `tests/test_fund_flow_pipeline.py` 混合测试依赖而延期,见 Task 7)。
- 规划期已核验的事实,执行时作断言复核:任何"Expected 空输出"的命令出现输出 → **停止,原样回报,不要继续该 Task**(HEAD 可能已漂移)。
- Commit 规范:Conventional,按任务内 commit 步骤小步提交。

---

### Task 0: 置备 worktree

- [ ] **Step 1: 创建并置备**

```bash
MAIN=/mnt/d/cursor/datasource
WT="$MAIN/.worktrees/codex-batch-a-repo-cleanup"
cd "$MAIN"
git worktree add "$WT" -b codex/batch-a-repo-cleanup
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

Expected: bootstrap 输出含 `[OK] .venv bootstrap complete`,随后 Python 版本。

- [ ] **Step 2: baseline**

```bash
bash run_clean.sh python -m pytest -q 2>&1 | tail -3
```

Expected: 全绿。若失败:停止,回报失败清单,不开工。

> 以下所有命令在 `$WT` 根执行。

### Task 1: 移除被误跟踪的产物与根目录一次性文件

**Files:** Delete: `.pip-temp/`(313 个被跟踪文件)、`src/datasource_integration.egg-info/`(7 个)、`update_fund_flow_20251112.bat`、`diff_latest.txt`、`restore_env_vars.ps1`;Modify: `.gitignore`

- [ ] **Step 1: git rm**

```bash
git rm -r -q .pip-temp src/datasource_integration.egg-info
git rm -q update_fund_flow_20251112.bat diff_latest.txt restore_env_vars.ps1
```

Expected: 无报错。

- [ ] **Step 2: 补 .gitignore**

在 `.gitignore` 的 `# Python cache` 区块末尾(`*.pyd` 行之后)追加两行:

```
*.egg-info/
.pip-temp/
```

- [ ] **Step 3: 验证 + commit**

```bash
git status --short | grep -v '^D ' | grep -v '.gitignore'
```

Expected: 空输出(只有删除与 .gitignore 修改)。

```bash
git add .gitignore && git commit -m "chore: remove tracked junk (.pip-temp, egg-info, one-off root scripts)"
```

### Task 2: archive 双目录合并 + scripts/legacy 归档

**Files:** Move: `archive/unused_py/*`(5 个文件)→ `archive/py_unused/`;`scripts/legacy/`(11 个文件)→ `archive/py_unused/legacy/`

规划期已核验:`scripts/legacy` 仅被自身内部与已死链路引用;`archive/py_unused` 现仅 1 个文件,与 `unused_py` 5 个文件无重名。**不要**把 legacy 文件散入 `py_unused/` 根(会与 `unused_py/background_scan_120d.py` 重名)。

- [ ] **Step 1: 合并与归档**

```bash
git mv archive/unused_py/_deleted_market_scan_data.py \
       archive/unused_py/background_scan_120d.py \
       archive/unused_py/fill_na_in_report_120d.py \
       archive/unused_py/generate_background_scan_120d_data.py \
       archive/unused_py/generate_report_120d.py \
       archive/py_unused/
mkdir -p archive/py_unused/legacy
git mv scripts/legacy/* archive/py_unused/legacy/
```

Expected: 无报错;`scripts/legacy`、`archive/unused_py` 变空目录(git 不跟踪空目录,工作区残留可 `rmdir`)。

- [ ] **Step 2: 复核无残留引用 + commit**

```bash
rmdir scripts/legacy archive/unused_py 2>/dev/null || true
grep -rn "scripts/legacy\|scripts\.legacy" src scripts tests examples --include='*.py'
```

Expected: 空输出。

```bash
git commit -m "refactor: merge archive dirs and archive scripts/legacy"
```

### Task 3: 归档 unreachable 源码集群 + 仅测死代码的测试/示例 + pytest.ini(原子提交)

**Files:**
- Move(src,保留相对路径到 `archive/py_unused/datasource/`): `agents/`(整包)、`analyzers/`、`comparators/`、`mappers/`、`warnings/`、`trackers/`、`generators/report_generator.py`、`engines/data_engine.py`、`utils/data_completion.py`、`calculators/bond_calculator.py`、`calculators/economic_cycle_analyzer.py`、`calculators/fund_flow_calculator.py`、`calculators/pring/leading_indicator.py`
- Move(测试/示例): `tests/test_na_filling.py`、`tests/run_na_filling.py`、`tests/integration/test_120d_integration.py`、`tests/integration/test_background_scan_agent.py` → `archive/py_unused/tests/`;`examples/use_background_scan_agent.py` → `archive/py_unused/examples/`
- Create: `pytest.ini`

依据:批次 0 审计 unreachable + 规划期 rg 复核。这 4 个测试文件**只**导入被归档模块(`test_fund_flow_pipeline.py` 是混合测试,**不在此列,不要动它**);`pytest.ini` 必须与测试移动同 commit——仓库无 pytest 配置,默认递归收集会把 `archive/` 下的 test_*.py 收进来导致 ImportError 爆红。

- [ ] **Step 1: 移动源码集群**

```bash
mkdir -p archive/py_unused/datasource/generators archive/py_unused/datasource/engines \
         archive/py_unused/datasource/utils archive/py_unused/datasource/calculators/pring
git mv src/datasource/agents      archive/py_unused/datasource/agents
git mv src/datasource/analyzers   archive/py_unused/datasource/analyzers
git mv src/datasource/comparators archive/py_unused/datasource/comparators
git mv src/datasource/mappers     archive/py_unused/datasource/mappers
git mv src/datasource/warnings    archive/py_unused/datasource/warnings
git mv src/datasource/trackers    archive/py_unused/datasource/trackers
git mv src/datasource/generators/report_generator.py archive/py_unused/datasource/generators/
git mv src/datasource/engines/data_engine.py         archive/py_unused/datasource/engines/
git mv src/datasource/utils/data_completion.py       archive/py_unused/datasource/utils/
git mv src/datasource/calculators/bond_calculator.py \
       src/datasource/calculators/economic_cycle_analyzer.py \
       src/datasource/calculators/fund_flow_calculator.py \
       archive/py_unused/datasource/calculators/
git mv src/datasource/calculators/pring/leading_indicator.py archive/py_unused/datasource/calculators/pring/
```

- [ ] **Step 2: 移动测试与示例**

```bash
mkdir -p archive/py_unused/tests archive/py_unused/examples
git mv tests/test_na_filling.py tests/run_na_filling.py \
       tests/integration/test_120d_integration.py \
       tests/integration/test_background_scan_agent.py \
       archive/py_unused/tests/
git mv examples/use_background_scan_agent.py archive/py_unused/examples/
rmdir examples 2>/dev/null || true
```

- [ ] **Step 3: 创建 `pytest.ini`**

```ini
[pytest]
testpaths = tests
```

(audit 工具测试仍按 TEST_PLAN 显式跑:`pytest optimization/20260610_refactor_plan/audit -q`,不受影响。)

- [ ] **Step 4: 引用闸断言(预核验过,应为空)**

```bash
grep -rnE "datasource\.(agents|analyzers|comparators|mappers|warnings|trackers)\b|engines\.data_engine|generators\.report_generator|utils\.data_completion|calculators\.(bond_calculator|economic_cycle_analyzer|fund_flow_calculator)|pring\.leading_indicator|pring import leading_indicator" \
  src scripts tests examples --include='*.py' 2>/dev/null
```

Expected: 空输出(exit 1)。有任何输出 → 停止回报。

- [ ] **Step 5: 冒烟 + 全量测试**

```bash
bash run_clean.sh python -c "import datasource; print('OK')"
bash run_clean.sh python -c "from datasource.generators.simple_report import generate_report; print('OK')"
bash run_clean.sh python -c "import datasource.calculators.pring_analyzer; print('OK')"
for s in stage1_data_collector stage2_unified_enhancer stage2_5_injector stage3_pring_analyzer stage4_report_generator; do
  bash run_clean.sh python scripts/$s.py --help >/dev/null && echo "$s OK"
done
bash run_clean.sh python -m pytest -q 2>&1 | tail -3
bash run_clean.sh python -m pytest --collect-only -q 2>/dev/null | grep -c "na_filling\|120d_integration\|background_scan_agent"
```

Expected: 三个 import OK + 5 个脚本 OK;pytest 全绿;最后一条计数为 `0`(exit 1)。

- [ ] **Step 6: Commit**

```bash
git add pytest.ini && git commit -m "refactor: archive unreachable module cluster with their dead-only tests

Batch-0 audit tier=unreachable (used_unused.json). pytest.ini added in the
same commit so archived test files are no longer collected."
```

### Task 4: 根目录报告/脚本收尾 + 活文档同步

**Files:** Move: `generate_report_simple.py` → `archive/py_unused/root/`;`data_quality_report.md`、`final_analysis_report.md` → `docs/history/`;Delete: `README_STAGE2_SNIPPET.md`(内容并入 `SCRIPTS.md`);Modify: `generate_simple_report.py`、`README.md`、`docs/系统技术文档.md`

- [ ] **Step 1: 移动与合并**

```bash
mkdir -p archive/py_unused/root docs/history
git mv generate_report_simple.py archive/py_unused/root/
git mv data_quality_report.md final_analysis_report.md docs/history/
printf '\n---\n\n' >> SCRIPTS.md
sed '1s/^# /## /' README_STAGE2_SNIPPET.md >> SCRIPTS.md
git rm -q README_STAGE2_SNIPPET.md
```

Expected: 无报错;`tail -60 SCRIPTS.md` 可见 "## Stage2 快速运行说明" 整节。

- [ ] **Step 2: shim 加 deprecation 头**

`generate_simple_report.py` 全文替换为:

```python
"""DEPRECATED shim (refactor batch A, 2026-06): use scripts/stage4_report_generator.py.

Kept one release cycle for backward compatibility; removal planned in batch B.
Import target unchanged: datasource.generators.simple_report.
"""

from datasource.generators.simple_report import generate_report

__all__ = ["generate_report"]
```

- [ ] **Step 3: 活文档同步(只改操作性提及,changelog/历史文档不动)**

`README.md`:把

```
# 历史简单报告脚本：generate_report_simple.py（诊断/回溯用，不在当前流程执行）
```

改为

```
# 历史简单报告脚本已归档：archive/py_unused/root/generate_report_simple.py（诊断/回溯用，不在当前流程执行）
```

`docs/系统技术文档.md`:把

```
- `generate_report_simple.py`：生成包含最新宏观数据的完整分析报告
```

改为

```
- `generate_report_simple.py`（已归档至 archive/py_unused/root/）：生成包含最新宏观数据的完整分析报告
```

并在其下方 `**使用流程**：` 行之后、代码块之前插入一行:

```
> 注：本节为历史流程记录；相关脚本已归档，不在当前 Stage1-4 流水线使用。
```

- [ ] **Step 4: 验证 + commit**

```bash
bash run_clean.sh python -c "import generate_simple_report; print('shim OK')"
grep -rn "README_STAGE2_SNIPPET" README.md SCRIPTS.md CLAUDE.md AGENTS.md
```

Expected: `shim OK`;grep 空输出。

```bash
git add -A && git commit -m "docs: archive root report scripts, fold stage2 snippet into SCRIPTS.md"
```

### Task 5: optimization 历史目录归档

- [ ] **Step 1: git mv(保留 20260427/20260610 两个活目录)**

```bash
git mv optimization/20251124_tavily_efficiency optimization/20251211_search_profiles \
       optimization/20251219_exa_fallback optimization/20260107_daily_report_optimization \
       optimization/20260409_output_layout_reorg optimization/20260409_plan_a_refactor \
       optimization/tavily_optimization optimization/tavily_stage2 \
       optimization/archive/
ls optimization
```

Expected: 仅剩 `20260427_refactor_plan`、`20260610_refactor_plan`、`archive`。

- [ ] **Step 2: Commit**

```bash
git commit -m "chore: consolidate completed optimization dirs into optimization/archive"
```

### Task 6: logs 轮转 + 最小 pre-commit

**Files:** Modify: `run_clean.sh`;Create: `.pre-commit-config.yaml`

- [ ] **Step 1: run_clean.sh 加 30 天日志轮转**

在 `run_clean.sh` 中,把

```bash
# shellcheck disable=SC1091
source scripts/runtime_env.sh
```

改为

```bash
# shellcheck disable=SC1091
source scripts/runtime_env.sh

# Rotate local logs older than 30 days; must never fail the wrapper.
if [ -d logs ]; then
  find logs -type f -mtime +30 -delete 2>/dev/null || true
fi
```

- [ ] **Step 2: 轮转行为验证(确定性)**

```bash
mkdir -p logs && touch -d '40 days ago' logs/_rotate_probe_old.log && touch logs/_rotate_probe_new.log
bash run_clean.sh python -c "print('wrapper OK')"
test ! -f logs/_rotate_probe_old.log && test -f logs/_rotate_probe_new.log && echo "rotate OK"
rm -f logs/_rotate_probe_new.log
```

Expected: `wrapper OK` 后 `rotate OK`(旧文件被删,新文件保留)。

- [ ] **Step 3: 创建 `.pre-commit-config.yaml`**

```yaml
# Minimal no-format quality gate (refactor batch A, 2026-06).
# flake8 hook deliberately deferred: src/ has ~3500 pre-existing violations;
# add it after a dedicated lint-cleanup pass (tracked in
# optimization/20260610_refactor_plan/TODOS.md).
repos:
  - repo: local
    hooks:
      - id: py-compile
        name: compileall src/datasource + scripts
        entry: python -m compileall -q src/datasource scripts
        language: system
        pass_filenames: false
        files: \.py$
```

(只提交配置文件;不在本计划内执行 `pre-commit install`,是否启用由维护者本地决定。)

- [ ] **Step 4: Commit**

```bash
bash run_clean.sh python -m compileall -q src/datasource scripts && echo "compileall OK"
git add run_clean.sh .pre-commit-config.yaml && git commit -m "feat: add 30-day log rotation and minimal pre-commit config"
```

### Task 7: 文档与计划状态同步

**Files:** Modify: `CLAUDE.md`、`optimization/20260610_refactor_plan/REFACTOR_PLAN.md`、`optimization/20260610_refactor_plan/TODOS.md`

- [ ] **Step 1: CLAUDE.md 模块映射改"已归档"口径**(逐处精确替换)

把 `；\`economic_cycle_analyzer\`、\`fund_flow_calculator\`、\`bond_calculator\`、\`trackers/policy_tracker\` 经批次 0 审计为流水线入口不可达` 改为 `；\`economic_cycle_analyzer\`、\`fund_flow_calculator\`、\`bond_calculator\`、\`trackers/policy_tracker\` 已按批次 0 审计归档至 \`archive/py_unused/datasource/\``(注意 Stage3 行此处是**全角分号 `；`**,其余三处替换为半角 `;`,以文件实际字符为准——替换前先 `grep -n` 确认)。

把 `;\`generators/report_generator.py\`、\`comparators/\`、\`mappers/\`、\`analyzers/\` 经批次 0 审计为流水线入口不可达` 改为 `;\`generators/report_generator.py\`、\`comparators/\`、\`mappers/\`、\`analyzers/\` 已按批次 0 审计归档至 \`archive/py_unused/datasource/\``。

把 `- **120 日背景扫描 agent** → \`agents/background_scan/\` 当前未接入 Stage1-4 流水线,经批次 0 审计为 \`unreachable\`` 改为 `- **120 日背景扫描 agent** → 已归档至 \`archive/py_unused/datasource/agents/\`(批次 0 审计 unreachable,未接入 Stage1-4 流水线)`。

把 Stage2.5 行内 `;\`utils/data_completion.py\` 经批次 0 审计为流水线入口不可达,不是 Stage2.5 主链依赖` 改为 `;\`utils/data_completion.py\` 已按批次 0 审计归档至 \`archive/py_unused/datasource/utils/\``。

- [ ] **Step 2: REFACTOR_PLAN §4 MCP 行标注延期**

把表格行

```
| `scripts/legacy/` + MCP 链路(`src/datasource/mcp_adapter.py`,`src/datasource/utils/mcp_tools.py`) | 批次 0 定档 `unreachable`;删除/移动前先 `rg` 复核 `tests/`、`examples/` 和手工脚本引用,再移入 `archive/py_unused/` 并下线对应 legacy 测试 |
```

改为

```
| `scripts/legacy/` | ✅ PR-A 已归档至 `archive/py_unused/legacy/` |
| MCP 链路(`src/datasource/mcp_adapter.py`,`src/datasource/utils/mcp_tools.py`) | **延期**:虽经批次 0 定档 `unreachable`,但 `tests/test_fund_flow_pipeline.py` 是混合测试(活的 Stage1 资金流用例 + 两处 MCPToolAdapter 用例),PR-A 不做测试手术;待该测试 MCP 段独立下线后再归档 |
```

- [ ] **Step 3: TODOS.md 更新**

批次 A 小节中 `- [ ] **PR-A**:...` 与其子项 `- [ ] Codex 执行 → Claude 评审 → 合入` 改为 `[~]`(进行中,评审合入后由评审方改 `[x]`),并在批次 A 小节末尾追加一行:

```
- [ ] MCP 链路(mcp_adapter/mcp_tools)归档延期:依赖 test_fund_flow_pipeline.py MCP 段下线(PR-A 评审记录)
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md optimization/20260610_refactor_plan/REFACTOR_PLAN.md optimization/20260610_refactor_plan/TODOS.md
git commit -m "docs: sync module map and refactor plan with batch-a archival"
```

### Task 8: 终验 + 回报(留在分支,不合并)

- [ ] **Step 1: 终验全家桶**

```bash
bash run_clean.sh python -m pytest -q 2>&1 | tail -3
bash run_clean.sh python -m pytest optimization/20260610_refactor_plan/audit -q 2>&1 | tail -2
bash run_clean.sh python -m compileall -q src/datasource scripts && echo "compileall OK"
git status --short
```

Expected: 两个 pytest 全绿;`compileall OK`;`git status` 干净(空输出)。

- [ ] **Step 2: 回报**

提交全部留在 `codex/batch-a-repo-cleanup` 分支,**不 merge、不删 worktree**。回报内容:

1. 各 Task commit SHA 列表;
2. baseline 与终验 pytest 输出(各 tail 3 行);
3. Task 3 Step 4 引用闸与 Step 5 收集计数的实际输出;
4. 偏差清单(任何"Expected 空输出"不空、或步骤被跳过的情况)。

**后续(评审方动作,不在本计划):** 两段式评审 → 合入 main → `git worktree remove` → 在 `$MAIN` 执行一次性本地清理(`find logs -type f -mtime +30 -delete`;删除根目录与 `scripts/__pycache__/` 等未跟踪缓存)→ TODOS 勾选。
