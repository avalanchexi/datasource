# PR-C7 合入 Implementation Plan(squash → main + 推送 + 清理)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 把评审通过(Stands as-is,无 Critical/Important)的 C7(C 终态:入口瘦身 + shim 清理 + 文档同步)squash 合入 main、推送、清理;commit body 如实记录入口瘦身/全面 repoint/破环/lc_pipeline repoint/.flake8。

**Architecture:** 纯集成,无代码改动。C7 已在 worktree 完成(5 commits;main 466 行字节等价、replay/contract 实跑 180 passed byte-stable 非假绿、全量 1425、NOCYCLE-OK),评审 Stands-as-is。

**Tech Stack:** git worktree;pytest;Windows + WSL。

> ⚠️ **顺序硬约束**:C7 必须**先于 D1** 合入(D1 分支建在 C7 之上,含整个 C7)。本计划先行;D1 合入(`2026-06-17-batch-d1-...` 另出指令)在 C7 合入后做。

---

## 环境头(Codex 零上下文必读)
- **Bash 工具坏**;每条命令经 `wsl -e bash -lc '...'`;pytest 走 `run_clean.sh`;只读 git 可用 PowerShell。
- **两个 checkout**:主 `/mnt/d/cursor/datasource`(分支 `main`,tip `d76b48f` = PR-C6);C7 worktree `/mnt/d/cursor/datasource/.worktrees/codex-batch-c7-terminal`(分支 `codex/batch-c7-terminal`,tip `be614ed`)。
- 硬约束:不重跑真实流水线/Tavily;不碰当日 `data/runs`/`data/trend_history`;不删 `.run.lock`;全程离线。**绝不 `STAGE2_REPLAY_UPDATE_GOLDEN`**。
- 这是合入收尾,不改 C7;Codex 只做 squash/复跑/push/清理。
- Commit:Conventional(`refactor:`)。

---

## Task 0:确认起点 + 分支态健康(只读)
- [ ] **Step 1: 确认 tips**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git rev-parse --short main && git rev-parse --short codex/batch-c7-terminal'
```
Expected:`d76b48f`(main)、`be614ed`(分支)。任一不符 → 停-回报。
- [ ] **Step 2: 分支冒烟(replay/contract + stage2_unified,确认现态绿)**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c7-terminal && bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py tests/test_stage25_contract_replay.py tests/test_stage2_unified.py -q 2>&1 | tail -4'
```
Expected:全 PASS(replay/contract byte-stable;~180 passed)。失败 → 停-回报(不合入)。

## Task 1:squash-merge(基 = `d76b48f`)
- [ ] **Step 1: 主 checkout 干净且在 main**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git switch main && git rev-parse --short HEAD && git status --short'
```
Expected:`d76b48f`;`git status` 仅 `.gstack/`/`.claude/settings.local.json`/`docs/superpowers/`(untracked)。其它已跟踪改动 → 停-回报。
- [ ] **Step 2: squash-merge + staged 范围核对**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git merge --squash codex/batch-c7-terminal && git --no-pager diff --cached --stat | tail -40'
```
Expected:无 conflict;staged 含 `.flake8`、`scripts/stage2_unified_enhancer.py`(→14 行)、`scripts/stage2_5_injector.py`(→9 行)、8 个删除的 shim、`src/datasource/engines/stage2/cli.py`、`src/datasource/engines/stage2_lc_pipeline.py`、`CLAUDE.md`/`AGENTS.md`/`SCRIPTS.md`/`README.md`/`TODOS.md` + 一批 `tests/test_stage2*`/`test_stage25*`/`test_*` repoint。意外文件/conflict → 停-回报。

## Task 2:写 commit body 并提交
- [ ] **Step 1: 用文件写入工具写 `/mnt/d/cursor/datasource/.git-c7-squash-msg.txt`**
```text
refactor: slim stage2/stage2.5 entries to <=30 lines; drop batch-B shims; sync docs (PR-C7, C terminal)

批次 C 终态收尾。scripts/stage2_unified_enhancer.py(866→14 行)、scripts/
stage2_5_injector.py(245→9 行)瘦为薄壳:main + 10 个 io/glue +
CRITICAL_EXTRACT_KEYS 搬入 src/datasource/engines/stage2/cli.py;丢 C1/C2/C3
re-export 块。删 8 个 batch-B 路径转发 shim(trend_history_backfill/
trend_history_scan/sanitize_market_data/compare_stage2_runs/stage2_health_check/
stage2_low_score_audit/setup_stage2_search_env/run_snapshot)。文档同步
CLAUDE/AGENTS/SCRIPTS/README 模块映射到 engines/stage{1,2,2_5}/ + scripts/tools/。
完成后 Stage1/2/2.5 三大入口皆薄壳,逻辑全在 src/。

唯一逻辑面改动 = 破 cli<->execution 环:main() 内延迟 import _execute_tasks
(execution.py 已 import cli 的 _callable_supports_kwarg,顶层互导会成环)。
main+glue body 逐字(评审实测 main 466 行字节等价)。

全面 repoint(丢 re-export 的必然代价):9+ 测试文件的 import/属性访问/
monkeypatch 改指 datasource.engines.stage2.* / stage2_cli;含 UTILS-ALIAS
(_FOREX_*_MARKERS/_append_note 等改指 datasource.utils.forex_evidence/note_utils,
注意 _append_note 两侧 append_note_text vs append_note_to_entry);stage2_lc_pipeline
的延迟导入也从脚本私名改指 engines 模块。.flake8 给 engines/stage2/cli.py 加
per-file-ignore E501(继承长行;F401/F821 仍检)。

验证:replay harness + stage2.5 contract replay byte-stable 且非假绿(patch 经
stage2_cli 命名空间真实触达 cli.main());characterization is-identity;全量
1425 passed, 3 skipped;import 冒烟 NOCYCLE-OK。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
- [ ] **Step 2: 提交并清理临时文件**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git commit -F .git-c7-squash-msg.txt && rm -f .git-c7-squash-msg.txt'
```
Expected:提交成功,main tip 前进一格。
- [ ] **Step 3: 零-diff 校验**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager diff main codex/batch-c7-terminal'
```
Expected:**空输出**。非空 → 停-回报(不清理分支)。

## Task 3:全量复跑(主 checkout)+ 推送 + 清理
- [ ] **Step 1: 主 checkout 全量回归**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m pytest -q 2>&1 | tail -5'
```
Expected:全绿,`1425 passed, 3 skipped`。failed → 停-回报(可 `git reset --hard d76b48f` 回退后回报)。
- [ ] **Step 2: 推送**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git push origin main'
```
Expected:fast-forward 成功。rejected → 停-回报,不 force。
- [ ] **Step 3: 清理 C7 worktree + 分支**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree remove .worktrees/codex-batch-c7-terminal --force && git worktree prune && git branch -D codex/batch-c7-terminal'
```
Expected:移除、删除,无报错。远端同名分支若有:`git push origin --delete codex/batch-c7-terminal`。
> ⚠️ **不要**删 `codex/batch-d1-run-dir-contract` worktree/分支——D1 建在 C7 之上,下一步要合 D1。
- [ ] **Step 4: 隔离断言 + 回报**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree list && git log --oneline -3 && git status --short'
```
Expected:无 `codex-batch-c7-terminal` worktree(D1 worktree 仍在);`git log` 顶部 C7 squash;`git status` 仅 untracked 杂项。
**回报**:C7 squash SHA、`git diff main 分支` 空、全量 1425 passed、已删 C7 worktree/分支、D1 worktree 保留确认。

---

## 合入后下一步(供编排)
- **D1 合入**:C7 进 main 后,D1 分支(`codex/batch-d1-run-dir-contract`,含 C7+D1)对新 main 的 delta 即只剩 D1 真改动 → 另出 D1 squash-merge 指令(基 = C7 合入后 main),`git diff main 分支` 应只剩 D1 内容。
- 耦合审计收口 plan(C6/C7 合入后做)。

## Self-Review
- 覆盖:评审 Stands-as-is、无 fix → 仅合入(Task 1)+ commit body(Task 2)+ 复跑/push/清理(Task 3)。✅
- 顺序约束:C7 先于 D1;清理时保留 D1 worktree。✅
- Placeholder:无 TBD;commit body 全文;每命令带 Expected/停-回报。✅
- 一致性:base `d76b48f`、C7 tip `be614ed`、`1425 passed, 3 skipped`、worktree/分支名全程一致。✅
