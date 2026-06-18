# PR-C4 合入 Implementation Plan(squash → main + 推送 + 清理)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已评审通过(Ready to merge,无 Critical/Important)的 C4 分支 squash 合入 main、推送、清理 worktree/分支;commit body 如实记录 cross-script reclaim 与 black inert reformat 偏离。

**Architecture:** 纯集成动作,无代码改动。C4 在 worktree 已完成(8 commits,token 等价 + `is` 身份 + contract replay byte-stable + 170 passed,reviewer 判 Ready to merge)。本计划只做 squash 合入 + 零-diff 校验 + 全量复跑 + push + 清理。**不改任何代码,不重算 golden。**

**Tech Stack:** git worktree;pytest;本机 Windows + WSL(Linux `.venv`)。

---

## 环境头(Codex 零上下文必读)

- **执行通道**:本机 Windows,**Bash 工具损坏**(MSYS `dofork`/`errno 11`)。每条 shell 命令经 `wsl -e bash -lc '...'`;只读 git 查询可用 PowerShell,但 **pytest 一律 WSL + `run_clean.sh`**。
- **两个 checkout**:
  - 主 checkout(好 `.venv`):`/mnt/d/cursor/datasource`(分支 `main`,tip 应为 `3fa900b`)。
  - C4 worktree:`/mnt/d/cursor/datasource/.worktrees/codex/batch-c4-stage25-split`(注意嵌套 `codex/` 目录;分支 `codex/batch-c4-stage25-split`,tip `e15a230`)。
- **硬约束**:不重跑 Stage2 真实搜索(Tavily 每日一次);不碰当日 `data/runs/YYYYMMDD` 与 `data/trend_history`;不手删 `.run.lock`。全程离线。
- **这是合入收尾,不是改 C4**:评审无 Critical/Important;两个 Minor(docstring 重排 / f-string 拼接 split)与 black inert reformat 均行为零影响,**不需要任何代码修复**。Codex 只做合入/清理。
- **Commit 规范**:Conventional(`refactor:`)。

---

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| (squash commit body) | 新建 | 记录 C4 七组机械搬移 + cross-script reclaim + black inert reformat 偏离 |
| 主 checkout `main` | 推进 | squash 合入 |
| worktree + 分支 | 删除 | 收尾 |

无源码改动。

---

## Task 0:确认起点 + 分支态健康(只读)

**Files:** 无

- [ ] **Step 1: 确认 tips**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git rev-parse --short main && git rev-parse --short codex/batch-c4-stage25-split'
```
Expected:`3fa900b`(main)与 `e15a230`(分支)。任一不符 → **停-回报**。

- [ ] **Step 2: 分支 worktree 快速冒烟(确认现态绿、能跑)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex/batch-c4-stage25-split && bash run_clean.sh python -m pytest tests/test_stage25_c4_split_characterization.py tests/test_stage25_contract_replay.py tests/test_stage2_replay_harness.py -q 2>&1 | tail -5'
```
Expected:全 PASS(characterization + Stage2.5 contract replay byte-stable + Stage2 replay harness)。失败 → **停-回报**(不要合入)。

---

## Task 1:squash-merge 分支(基 = 当前 main `3fa900b`)

**Files:** 主 checkout `/mnt/d/cursor/datasource`

- [ ] **Step 1: 主 checkout 干净且在 main**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git switch main && git rev-parse --short HEAD && git status --short'
```
Expected:`3fa900b`;`git status --short` 仅可能 `.gstack/`/`.claude/settings.local.json`/`docs/superpowers/`(untracked 计划文档)。其它已跟踪改动 → **停-回报**。

- [ ] **Step 2: squash-merge**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git merge --squash codex/batch-c4-stage25-split && git --no-pager diff --cached --stat'
```
Expected:`Squash commit -- not updating HEAD`,无 conflict。staged 文件应为:`scripts/stage2_5_injector.py`、`src/datasource/engines/stage2_5/{__init__,common,fund_flow,schema_coercion,gap_sync,manual_official}.py`、`src/datasource/engines/stage2/extraction_apply.py`、`src/datasource/engines/stage2/execution.py`、`tests/test_stage25_c4_split_characterization.py`、`tests/test_stage25_contract_replay.py`、`optimization/20260610_refactor_plan/TODOS.md`。意外文件 / conflict → **停-回报**。

---

## Task 2:写 commit body 并提交

**Files:** 主 checkout

- [ ] **Step 1: 用文件写入工具写 commit body**

把下列内容逐字写入 `/mnt/d/cursor/datasource/.git-c4-squash-msg.txt`:
```text
refactor: split stage2.5 injector into common/schema_coercion/manual_official/fund_flow/gap_sync (PR-C4)

把 scripts/stage2_5_injector.py(4211 行)的 4 个低层簇 + 一个 common 底座机械
抽取到新包 src/datasource/engines/stage2_5/,主脚本以 re-export 保持 zero
call-site churn。common 为底座(url-evidence + numeric coerce);
schema_coercion/manual_official/fund_flow/gap_sync 各取一域;依赖单向无环
(4 簇 → common;注入器不 import engines/stage2)。

范围/决策:
- 新建 engines/stage2_5/ 包,与 engines/stage2/ 平行。
- fund_flow 只收 gate/归一化簇;entry 应用(_apply_fund_flow_entry 等)留 C5。
- coerce helpers 仅搬位置,未并入 utils/coercion(延后)。
- manual_official(official override allowlist mlf/USDCNY/BCOM)与 fund_flow gate
  为行为冻结区,token 等价、各独立 commit。

cross-script reclaim(回收 C2 遗留 # C4-cleanup):
- 4 个 fund_flow helper 搬入 engines/stage2_5/fund_flow;extraction_apply 与
  execution 改从该 canonical src 模块 import,删除 scripts/stage2_5_injector
  跨脚本 import 与 # C4-cleanup 标记;跨包 is 身份成立、import 无环。

已知偏离(行为零影响,评审已核验):
- 搬移文件经 black 格式化,引入 inert 的换行/grouping 括号/magic trailing comma/
  docstring 重缩进;diff 因此不是纯位置 relocation。reviewer 以 token 等价 +
  is 身份 + contract replay byte-stable + 170 passed 证明行为完全保留。
- 两个 Minor:schema_coercion/gap_sync docstring 重排、_refresh_stage2_notes
  f-string 拼接 split——均 inert。

验证:characterization(is 身份 + import-surface + 跨包 reclaim)+ Stage2.5
contract replay byte-stable + Stage2 replay harness 绿 + 全量回归无回归。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

- [ ] **Step 2: 提交并清理临时文件**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git commit -F .git-c4-squash-msg.txt && rm -f .git-c4-squash-msg.txt'
```
Expected:提交成功,main tip 前进一格。

- [ ] **Step 3: 零-diff 校验(main vs 分支,全树)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager diff main codex/batch-c4-stage25-split'
```
Expected:**空输出**(squash 完整捕获分支全部改动)。非空 → **停-回报**(不要清理分支)。

---

## Task 3:全量复跑(主 checkout)+ 推送 + 清理

**Files:** 无

- [ ] **Step 1: 主 checkout 全量回归(好 venv,权威)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m pytest -q 2>&1 | tail -5'
```
Expected:全绿,`1179 passed, 3 skipped`(C4 baseline = 1179;新增 characterization 计入分支自测,主 checkout 全量数以实际为准且不低于 1179)。failed → **停-回报**(可 `git reset --hard 3fa900b` 回退本次 squash 后回报)。

- [ ] **Step 2: 推送 main**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git push origin main'
```
Expected:fast-forward 成功。rejected → **停-回报**,不要 force。

- [ ] **Step 3: 清理 worktree + 分支**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree remove .worktrees/codex/batch-c4-stage25-split --force && git worktree prune && git branch -D codex/batch-c4-stage25-split'
```
Expected:worktree 移除、分支删除,无报错。(远端若有同名分支:`git push origin --delete codex/batch-c4-stage25-split`;无则跳过。)

- [ ] **Step 4: 隔离断言 + 回报**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree list && git log --oneline -3 && git status --short'
```
Expected:worktree 列表无 `codex/batch-c4-stage25-split`;`git log` 顶部是 C4 squash 提交;`git status` 仅 `.gstack/`/`.claude/settings.local.json`/计划文档。
**回报**:squash SHA、`git diff main 分支` 空确认、全量 passed 数、`# C4-cleanup` 已删确认、已删 worktree/分支。

---

## Self-Review(规划方自查)

- **覆盖**:评审 Ready-to-merge、无 fix → 本计划只做合入(Task 1)+ commit body 记录偏离(Task 2)+ 复跑/push/清理(Task 3)。✅
- **Placeholder 扫描**:无 TBD;commit body 全文;每命令带 Expected 与停-回报分支。✅
- **一致性**:worktree 嵌套路径 `.worktrees/codex/batch-c4-stage25-split`、分支名、squash 基 `3fa900b`、baseline `1179 passed, 3 skipped` 全程一致;staged 文件清单与评审 diff 一致。✅
- **零代码改动**:本计划不碰源码、不重算 golden;两个 Minor + black reformat 均 inert,仅在 commit body 如实登记。✅
