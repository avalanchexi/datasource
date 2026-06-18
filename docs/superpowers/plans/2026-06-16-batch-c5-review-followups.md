# PR-C5 评审补救 + 合入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** 消除 C5 评审两处 Minor(① 瘦身后主脚本 F401/E501 lint 回归;② core.py 的 inert print 局部变量提取偏离),然后从 main `a0d182a` squash 合入 C5、推送、清理。

**Architecture:** 两处都是零行为影响的代码卫生。① 主脚本现为 re-export shim,孤儿 import 加 `# noqa: F401` + 折行(**不删**——`test_forex_evidence_characterization.py` 经 injector 访问 `FOREX_*`/`_append_note`/`_contains_ytd_marker` 等,删会破测试)。② 把 core.py `inject_websearch_data`/`_post_injection_validation` 的 print 块还原为 base `a0d182a` 逐字(只保留允许的 `trend_backfill.` module-qualify),恢复"verbatim + qualify only"。**不改业务逻辑、不重算 contract golden。**

**Tech Stack:** Python;pytest;flake8;git worktree;Windows + WSL。

> 评审结论:Ready to merge — With fixes(无 Critical/Important);全量 `1424 passed, 3 skipped`(reviewer 已实跑)。

---

## 环境头(Codex 零上下文必读)

- **Bash 工具损坏**;命令经 `wsl -e bash -lc '...'`;pytest/flake8 走 `run_clean.sh`;只读 git 查询可用 PowerShell。
- **两个 checkout**:主 `/mnt/d/cursor/datasource`(分支 `main`,tip `a0d182a`);C5 worktree `/mnt/d/cursor/datasource/.worktrees/codex/batch-c5-stage25-split`(嵌套 `codex/` 目录;分支 `codex/batch-c5-stage25-split`,tip `2f78d7f`)。
- 硬约束:不重跑 Stage2 真实搜索;不碰当日 `data/runs`/`data/trend_history`;不删 `.run.lock`;全程离线。
- **这是 C5 评审收尾,不是重做 C5**:5 模块抽取 + repoint 已评审通过(冻结区逐字、no-cycle、contract replay 非假绿、`is` 身份齐全)。Codex 只做本计划两处卫生修复 + 合入/清理,**严禁**改模块抽取结构、module-qualify 清单、repoint、业务逻辑或重算 golden。
- Commit:Conventional(`refactor:`/`test:`)。

---

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `scripts/stage2_5_injector.py`(worktree) | Modify | 孤儿 re-export import 加 `# noqa: F401` + 折行 E501;**不删** |
| `src/datasource/engines/stage2_5/core.py`(worktree) | Modify | `inject_websearch_data`/`_post_injection_validation` 的 print 块还原为 base 逐字 |
| (squash commit body) | 新建 | 记录 C5 抽取 + 两处补救 |
| worktree + 分支 | 删除 | 收尾 |

---

## Task 0:确认起点 + baseline

- [ ] **Step 1: 确认 tips**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git rev-parse --short main && git rev-parse --short codex/batch-c5-stage25-split'
```
Expected:`a0d182a`(main)、`2f78d7f`(分支)。不符 → 停-回报。

- [ ] **Step 2: baseline 全量(确认现态绿)**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex/batch-c5-stage25-split && bash run_clean.sh python -m pytest -q 2>&1 | tail -5'
```
Expected:`1424 passed, 3 skipped`。失败 → 停-回报。

---

## Task 1:Minor ① — 主脚本孤儿 import 加 `# noqa: F401` + 折行(不删)

**Files:** Modify `scripts/stage2_5_injector.py`(worktree)

> ⚠️ **不要 drop 任何 import**:`test_forex_evidence_characterization.py` 经 `import scripts.stage2_5_injector as stage25` 访问 `stage25.FOREX_DAILY_CHANGE_SOURCE_MARKERS`/`FOREX_120D_CHANGE_SOURCE_MARKERS`/`FOREX_DAILY_CHANGE_EVIDENCE_KEYS`/`FOREX_120D_CHANGE_EVIDENCE_KEYS`/`_append_note`/`_append_note_once`/`_contains_ytd_marker`/`_copy_valid_forex_daily_change_evidence`/`_has_forex_daily_change_evidence`/`_is_forex_daily_change_absence_text`(test L23/48/52/66/95/99/144/152/167/170/174-185/191/193)。这些来自主脚本的 `forex_evidence`/`note_utils`/`text_markers` import,删除会破该测试。主脚本现为 re-export shim,这些 import 是**有意 re-export**,标 noqa 即可。

- [ ] **Step 1: 列出 flake8 违规**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex/batch-c5-stage25-split && bash run_clean.sh python -m flake8 scripts/stage2_5_injector.py 2>&1 | tail -60'
```
记录每条 F401/E501 的行号。

- [ ] **Step 2: 对每条 F401 加 `# noqa: F401`,对 E501 长 import 折行**
对所有被 F401 标记的 import:若为单名 `from x import y`,行尾加 `  # noqa: F401`;若为括号多名块 `from x import (\n ... \n)`,在块内每个未用名行尾或块首行加 `# noqa: F401`(与文件内既有 `# noqa: F401 (C4 re-export)` 风格一致——见现有 `from datasource.engines.stage2_5.common import (  # noqa: F401 (C4 re-export)`)。对 E501 的长 `from ... import (` 行,改为多行括号形式消除超长。**典型对象**(以 Step 1 实际为准):`from datasource.utils.forex_evidence import (...)`、`from datasource.utils.note_utils import (...)`、`from datasource.utils.text_markers import contains_ytd_marker`、`from datasource.utils.trend_history_store import (...)`、`from datasource.utils.fund_flow_series import ...`、`from datasource.utils.quality_metrics import ...`、`from datasource.utils.key_aliases import (...)`、`from datasource.utils.policy_rules import (...)`、`from datasource.utils.run_lock import ...`、`from datasource.utils.run_paths import ...`、`from datasource.models.market_data_contract import FundFlowData`。
> 统一动作:**保留 import(re-export)+ 标 noqa**;不判定哪些"真死"(真正删除留 C 批次终态 main≤30 行瘦身)。

- [ ] **Step 3: 校验 flake8 干净 + 全量不回归**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex/batch-c5-stage25-split && bash run_clean.sh python -m flake8 scripts/stage2_5_injector.py && bash run_clean.sh python -m pytest tests/test_forex_evidence_characterization.py tests/test_websearch_injector.py -q 2>&1 | tail -5'
```
Expected:flake8 无输出;两测试全绿(证明 re-export 未被破)。

- [ ] **Step 4: commit** — `refactor: noqa/wrap re-export imports in thinned stage2.5 injector (PR-C5 review)`

---

## Task 2:Minor ② — core.py print 块还原为 base 逐字

**Files:** Modify `src/datasource/engines/stage2_5/core.py`(worktree)

> 评审记录:`inject_websearch_data` 的诊断 print 块把 `payload.get(...)` 内联表达式提了局部(`macro_label`/`macro_value`/`macro_unit`、`policy_*`、`fund_flow_entry`),`_post_injection_validation` 把 print 循环变量 `field`→`estimated_field`。inert(仅 stdout,无断言),但超出"verbatim + qualify only"。还原为 base。

- [ ] **Step 1: 取 base 两函数原文作参照**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex/batch-c5-stage25-split && git show a0d182a:scripts/stage2_5_injector.py | sed -n "/^def inject_websearch_data/,/^def inject_websearch_results/p; /^def _post_injection_validation/,/^def /p"'
```
Expected:打印 base 两函数体(print 块为内联 `payload.get(...)`、循环变量 `field`)。

- [ ] **Step 2: 把 core.py 两函数的 print 块还原为 base 逐字**
将 core.py 的 `inject_websearch_data`/`_post_injection_validation` 体内被提取的局部变量改回 base 的内联 print 形式,循环变量改回 `field`。**唯一允许保留的非 base 差异 = §C5 module-qualify 的 3 处 `trend_backfill.`**(`_backfill_trend_changes`/`_run_post_write_trend_backfill`/`_sync_backfill_issues_to_logs`);其余逐字对齐 base。

- [ ] **Step 3: 校验仅剩 qualify 差异**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex/batch-c5-stage25-split && git show a0d182a:scripts/stage2_5_injector.py | sed -n "/^def inject_websearch_data/,/^def inject_websearch_results/p" > /tmp/base_inject.txt && sed -n "/^def inject_websearch_data/,/^def inject_websearch_results/p" src/datasource/engines/stage2_5/core.py > /tmp/c5_inject.txt && diff /tmp/base_inject.txt /tmp/c5_inject.txt; echo "---"; rm -f /tmp/base_inject.txt /tmp/c5_inject.txt'
```
Expected:diff 仅显示 `trend_backfill.` 限定符前缀差异(`_backfill_trend_changes`/`_run_post_write_trend_backfill`/`_sync_backfill_issues_to_logs` 3 处)+ 可能的 black 行宽/noqa;**无局部变量提取、无 `estimated_field` 重命名残留**。若还有其它差异 → 继续还原。

- [ ] **Step 4: 校验 py_compile + 全量不回归 + contract replay byte-stable**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex/batch-c5-stage25-split && bash run_clean.sh python -m py_compile src/datasource/engines/stage2_5/core.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage2_5/core.py && bash run_clean.sh python -m pytest tests/test_stage25_contract_replay.py tests/test_websearch_injector.py tests/test_daily_writer_locks.py -q 2>&1 | tail -6'
```
Expected:py_compile/flake8 干净;contract replay byte-stable + 三测试全绿(还原 print 不改行为)。

- [ ] **Step 5: commit** — `refactor: restore verbatim print blocks in stage2.5 core inject (PR-C5 review)`

---

## Task 3:分支全量回归

- [ ] **Step 1: worktree 全量**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex/batch-c5-stage25-split && bash run_clean.sh python -m pytest -q 2>&1 | tail -5'
```
Expected:`1424 passed, 3 skipped`(数持平)。failed → 停-回报。

---

## Task 4:squash 合入 main(基 = `a0d182a`)

- [ ] **Step 1: 主 checkout 干净且在 main**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git switch main && git rev-parse --short HEAD && git status --short'
```
Expected:`a0d182a`;`git status` 仅 `.gstack/`/`.claude/settings.local.json`/`docs/superpowers/`(untracked)。其它已跟踪改动 → 停-回报。

- [ ] **Step 2: squash-merge + staged 范围**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git merge --squash codex/batch-c5-stage25-split && git --no-pager diff --cached --stat'
```
Expected:无 conflict;staged = `scripts/stage2_5_injector.py`、`src/datasource/engines/stage2_5/{common,trend_backfill,entry_mergers,core,cli}.py`、`tests/{test_stage25_c5_split_characterization,test_websearch_injector,test_stage25_contract_replay,test_daily_writer_locks}.py`、`optimization/20260610_refactor_plan/TODOS.md`。意外文件/conflict → 停-回报。

- [ ] **Step 3: 写 commit body 并提交**

用文件写入工具把下列内容写入 `/mnt/d/cursor/datasource/.git-c5-squash-msg.txt`:
```text
refactor: split stage2.5 injector into trend_backfill/entry_mergers/core/cli (PR-C5)

把 scripts/stage2_5_injector.py(3315 行)剩余执行层机械抽取到
src/datasource/engines/stage2_5/{trend_backfill,entry_mergers,core,cli}.py,
并扩展 common.py;主脚本瘦为 re-export shim + 薄 main 转发。这是 Stage2.5
拆分收尾(续 C4)。依赖单向无环:common <- trend_backfill <- entry_mergers
<- core <- cli;注入器不 import engines/stage2。

范围/决策:
- R1:_apply_pipeline_quality_state/_is_estimated_allowlisted_entry/_policy_rules/
  _issue_signature/_merge_quality_issues 已在 C4 common,未重搬。
- R2 防环:_format_source_label/_merge_same_value_report_fields/_update_metadata_only
  +常量归 common;_infer_trend/_infer_asset_trend 归 trend_backfill;
  entry_mergers->core 经 TYPE_CHECKING 仅类型引用 InjectionSummary。
- 唯一非逐字改动 = 被测试 monkeypatch 的跨模块调用改 module-qualified
  (entry->trend 8 处、core->trend 3 处、cli->core 1 处)。
- ~56 处测试 monkeypatch 按 owning module repoint;contract replay 的
  "trend 读应被跳过"断言经 module-qualified + 模块 patch 仍真实触发(非假绿)。
- coerce/report-field helper 仅搬位置,未并入 utils/coercion;main <=30 行
  瘦身留 C 批次终态。

评审两处补救(零行为影响):
- 瘦身后主脚本孤儿 re-export import 加 # noqa: F401 + 折行(不删:
  test_forex_evidence_characterization 经 injector 访问 FOREX_*/_append_note 等)。
- core.py inject/_post_injection_validation 的 inert print 局部变量提取还原为
  base 逐字,恢复 verbatim+qualify-only。

验证:characterization(is 身份 + qualified-patch-reach)+ Stage2.5 contract
replay byte-stable + 全量 1424 passed, 3 skipped。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
再提交并清理:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git commit -F .git-c5-squash-msg.txt && rm -f .git-c5-squash-msg.txt'
```
Expected:提交成功,main tip 前进一格。

- [ ] **Step 4: 零-diff 校验**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager diff main codex/batch-c5-stage25-split'
```
Expected:**空输出**。非空 → 停-回报(不清理分支)。

---

## Task 5:全量复跑(主 checkout)+ 推送 + 清理

- [ ] **Step 1: 主 checkout 全量回归**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m pytest -q 2>&1 | tail -5'
```
Expected:`1424 passed, 3 skipped`。failed → 停-回报(可 `git reset --hard a0d182a` 回退后回报)。

- [ ] **Step 2: 推送**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git push origin main'
```
Expected:fast-forward 成功。rejected → 停-回报,不 force。

- [ ] **Step 3: 清理 worktree + 分支**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree remove .worktrees/codex/batch-c5-stage25-split --force && git worktree prune && git branch -D codex/batch-c5-stage25-split'
```
Expected:移除、删除,无报错。远端同名分支若有:`git push origin --delete codex/batch-c5-stage25-split`。

- [ ] **Step 4: 隔离断言 + 回报**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree list && git log --oneline -3 && git status --short'
```
Expected:无 `codex/batch-c5-stage25-split` worktree;`git log` 顶部 C5 squash;`git status` 仅 untracked 杂项。
**回报**:squash SHA、两处补救确认(noqa-not-drop + print 还原)、`git diff main 分支` 空、全量 1424 passed、已删 worktree/分支。

---

## Self-Review(规划方自查)
- 覆盖:Minor ① → Task 1(noqa+wrap,不删 + 防破 forex 测试);Minor ② → Task 2(还原 print,仅留 qualify 差异);合入/清理 → Task 3–5。✅
- Placeholder:无 TBD;noqa 规则化 + flake8 实测兜底;print 还原给 base 提取命令 + diff 校验;commit body 全文。✅
- 一致性:worktree 嵌套路径、分支名、squash 基 `a0d182a`、baseline `1424 passed, 3 skipped` 全程一致;module-qualify 3 处与 C5 plan 一致。✅
- 零行为/不越界:仅 noqa + print 还原;不动抽取结构/repoint/业务逻辑/golden;真正删死 import 留终态。✅
