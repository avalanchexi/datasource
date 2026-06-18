# PR-C6 合入 Implementation Plan(squash → main + 推送 + 清理)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 把已评审通过(Stands as-is,无 Critical/Important)的 C6 分支 squash 合入 main、推送、清理 worktree/分支;commit body 如实记录 relocate-only + 24 get_manager repoint + 两个 nested-in-main helper 抽取 + `.flake8` 继承码 per-file-ignore。

**Architecture:** 纯集成动作,无代码改动。C6 已在 worktree 完成(4 commits;`MarketDataCollector` + 3 helper 字节等价、2 个 nested-in-main helper dedent 等价、24 get_manager repoint 无残留、薄脚本 108 行、全量 1425 passed),评审 Stands-as-is。本计划只做 squash + 零-diff 校验 + 全量复跑 + push + 清理。**不改代码、不重算任何 golden。**

**Tech Stack:** git worktree;pytest;Windows + WSL。

---

## 环境头(Codex 零上下文必读)
- **Bash 工具损坏**;每条命令经 `wsl -e bash -lc '...'`;pytest 走 `run_clean.sh`;只读 git 可用 PowerShell。
- **两个 checkout**:主 `/mnt/d/cursor/datasource`(分支 `main`,tip `0c8f14b`);C6 worktree `/mnt/d/cursor/datasource/.worktrees/codex-batch-c6-stage1-slim`(连字符路径;分支 `codex/batch-c6-stage1-slim`,tip `63db690`)。
- 硬约束:**不跑真实 TuShare/Stage1 采集**;不碰当日 `data/runs`/`data/trend_history`;不删 `.run.lock`;全程离线。
- **这是合入收尾,不改 C6**:评审无 Critical/Important;两处 Minor(nested-helper 抽取 dedent 等价、`.flake8` 继承 E722 等忽略)均行为安全、不需修复。Codex 只做合入/清理。
- Commit:Conventional(`refactor:`)。

---

## File Structure
| 文件 | 动作 | 责任 |
|---|---|---|
| (squash commit body) | 新建 | 记录 C6 relocate + 24 repoint + 两处 Minor |
| 主 checkout `main` | 推进 | squash 合入 |
| worktree + 分支 | 删除 | 收尾 |

无源码改动。

---

## Task 0:确认起点 + 分支态健康(只读)
- [ ] **Step 1: 确认 tips**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git rev-parse --short main && git rev-parse --short codex/batch-c6-stage1-slim'
```
Expected:`0c8f14b`(main)、`63db690`(分支)。任一不符 → 停-回报。
- [ ] **Step 2: 分支 worktree 冒烟(stage1 单测 + is-identity)**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c6-stage1-slim && bash run_clean.sh python -m pytest tests/test_stage1_data_collector.py tests/test_stage1_hsgt_window.py -q 2>&1 | tail -4'
```
Expected:全 PASS(含 `test_c6_collector_reexport_is_canonical`)。失败 → 停-回报(不合入)。

---

## Task 1:squash-merge(基 = `0c8f14b`)
- [ ] **Step 1: 主 checkout 干净且在 main**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git switch main && git rev-parse --short HEAD && git status --short'
```
Expected:`0c8f14b`;`git status` 仅 `.gstack/`/`.claude/settings.local.json`/`docs/superpowers/`(untracked)。其它已跟踪改动 → 停-回报。
- [ ] **Step 2: squash-merge + staged 范围**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git merge --squash codex/batch-c6-stage1-slim && git --no-pager diff --cached --stat'
```
Expected:无 conflict;staged = `.flake8`、`scripts/stage1_data_collector.py`、`src/datasource/engines/stage1/{__init__,collector}.py`、`tests/test_stage1_data_collector.py`、`optimization/20260610_refactor_plan/TODOS.md`。意外文件/conflict → 停-回报。

---

## Task 2:写 commit body 并提交
- [ ] **Step 1: 用文件写入工具写 `/mnt/d/cursor/datasource/.git-c6-squash-msg.txt`**
```text
refactor: relocate Stage1 MarketDataCollector to engines/stage1 (PR-C6)

把 scripts/stage1_data_collector.py(~2562 行)的 god-class MarketDataCollector
(~2270 行)+ 模块级 helper 机械搬移到新包 src/datasource/engines/stage1/collector.py,
脚本瘦为 108 行薄 entry(re-export + main + if __name__)。达成全局验收"scripts/
入口 ≤300 行"。批次 C 巨石拆分可选收尾(stage1/2/2.5 三大入口至此全部瘦身)。

范围/决策:
- relocate-only:类 + helper body 逐字(MarketDataCollector 2060 行 + _calc_change_from_
  trend_history/_is_missing_change/_backfill_stage1_trend 字节等价);不拆 god-class
  内部、不 dedup stage1 自有的 _calc_change_from_trend_history(与 Stage2.5 独立副本)。
- 目标包 engines/stage1/(与 engines/stage2/、engines/stage2_5/ 统一)。
- 依赖单向无环:collector → manager/adapters/calculators/models/utils;不 import 脚本/
  engines.stage2(_5)。
- 24 处测试 monkeypatch 从 scripts.stage1_data_collector.get_manager repoint 到
  datasource.engines.stage1.collector.get_manager(__init__ 在新模块查 get_manager);
  无旧残留。

已知偏离(行为安全,评审已核验):
- _normalize_date_str/_resolve_last_trading_day 原为 main() 内嵌套函数,按本 PR 目标
  (模块级 + re-export)抽取到 collector 模块级;经 dedent 归一比对与原 main 内定义
  字节等价(13/24 行),纯参数 helper,行为保持;main body 相应改为 import 调用。
- .flake8 给 collector.py 加 narrow per-file-ignore(E501,F541,E306,E722,E302)——继承自
  原 god-class 的既有风格码(搬进 src/ 才被 flake8 src/ 覆盖);verbatim 搬移保留不修
  (修=改 body)。F401/F821 仍在检。god-class 内部清理(含 E722 裸 except)留未来独立项。

验证:既有 stage1 单测 + 新增 is-identity 断言 + --help diff 空 + 全量
1424→1425 passed, 3 skipped(+1 为 is-identity)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
- [ ] **Step 2: 提交并清理临时文件**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git commit -F .git-c6-squash-msg.txt && rm -f .git-c6-squash-msg.txt'
```
Expected:提交成功,main tip 前进一格。
- [ ] **Step 3: 零-diff 校验**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager diff main codex/batch-c6-stage1-slim'
```
Expected:**空输出**。非空 → 停-回报(不清理分支)。

---

## Task 3:全量复跑(主 checkout)+ 推送 + 清理
- [ ] **Step 1: 主 checkout 全量回归**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m pytest -q 2>&1 | tail -5'
```
Expected:全绿,`1425 passed, 3 skipped`。failed → 停-回报(可 `git reset --hard 0c8f14b` 回退后回报)。
- [ ] **Step 2: 推送**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git push origin main'
```
Expected:fast-forward 成功。rejected → 停-回报,不 force。
- [ ] **Step 3: 清理 worktree + 分支**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree remove .worktrees/codex-batch-c6-stage1-slim --force && git worktree prune && git branch -D codex/batch-c6-stage1-slim'
```
Expected:移除、删除,无报错。远端同名分支若有:`git push origin --delete codex/batch-c6-stage1-slim`。
- [ ] **Step 4: 隔离断言 + 回报**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree list && git log --oneline -3 && git status --short'
```
Expected:无 `codex-batch-c6-stage1-slim` worktree;`git log` 顶部 C6 squash;`git status` 仅 untracked 杂项。
**回报**:squash SHA、`git diff main 分支` 空、全量 1425 passed、脚本行数 ≤300 确认、已删 worktree/分支。

---

## Self-Review(规划方自查)
- 覆盖:评审 Stands-as-is、无 fix → 仅合入(Task 1)+ commit body 记录两 Minor(Task 2)+ 复跑/push/清理(Task 3)。✅
- Placeholder:无 TBD;commit body 全文;每命令带 Expected 与停-回报。✅
- 一致性:worktree 连字符路径 `.worktrees/codex-batch-c6-stage1-slim`、分支名、squash 基 `0c8f14b`、`1425 passed, 3 skipped`、staged 文件清单与评审 diff 一致。✅
- 零代码改动:不碰源码、不重算 golden;两 Minor 仅 commit body 如实登记。✅
