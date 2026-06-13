# PR-C0 评审后续补救 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 兑现 PR-C0 评审的 1 个 Important 过程项(§3 差异矩阵写入 squash commit body)+ 1 个 Minor 防御注释,然后 squash 合入 main、更新 TODOS、清理 worktree。

**Architecture:** C0 实现已在分支 `codex/batch-c0-forex-evidence`(tip `35b3145`)完成并评审通过。本计划只做"评审收尾":一处注释(分支上)→ squash 合入(matrix 入 commit body)→ 文档状态 → 清理。**不改任何 forex 判定逻辑**。

**Tech Stack:** Python 3.x;pytest;git worktree;本机 Windows + WSL(Linux `.venv`)。

---

## 环境头(Codex 零上下文必读)

- **执行通道**:本机 Windows,**每条 shell 命令经 `wsl -e bash -lc '...'` 进入 Linux 侧**(不要用坏的 MSYS bash;不要用 PowerShell 跑 pytest)。`.venv` 是 Linux venv。
- **两个 checkout**:
  - 主 checkout(好 `.venv`):`/mnt/d/cursor/datasource`(分支 `main`,tip `5b1d692`)。
  - 实现 worktree:`/mnt/d/cursor/datasource/.worktrees/codex-batch-c0-forex-evidence`(分支 `codex/batch-c0-forex-evidence`,tip `35b3145`)。
- **测试命令**:一律 `bash run_clean.sh python -m pytest ...`,**不要直跑 `pytest`**——`run_clean.sh` 负责 `source .env` / `PYTHONPATH=./src` / 清主动代理 / 激活 `.venv`(空 `.venv` 时按环境变量 bootstrap)。在对应 checkout 根目录执行。
  - **worktree 的 `.venv` 是 system-Python fallback,缺 `pytest-asyncio`**,全量收集会出现环境性 async failures。故本计划**在 worktree 只跑纯同步的 `tests/test_forex_evidence_characterization.py`**(该文件无 async,系统 Python 即可);若 `run_clean.sh` 报 venv 缺失,加前缀 `ALLOW_SYSTEM_PYTHON=1`。
  - **全量回归只在主 checkout(`/mnt/d/cursor/datasource`,好 `.venv`)跑**(Task 3)。
- **这是"评审收尾",不是重做 C0**:5 个实现文件的 forex 合一已完成并通过评审;Codex **只做**本计划的「加一处注释 + squash 合入 + 文档/清理」,**严禁**重写/重排 forex 判定族、note 族、常量或 consumer。
- **硬约束**:不重跑 Stage2 真实搜索(Tavily 每日一次);不触碰 `data/runs/YYYYMMDD`(当日)与 `data/trend_history`;不手删 `.run.lock`;不改 forex 判定族/note 族/consumer 的任何行为(本计划只加注释 + 合入 + 文档)。
- **行为冻结区**:`official manual override allowlist(mlf/USDCNY/BCOM)`、`fund_flow gate`、`forex 零值防占位`、`Stage3 三路 gate`——本计划 diff **不得**触及它们。
- **Commit 规范**:Conventional(`refactor:/docs:/chore:`),小步频提。

---

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `src/datasource/utils/forex_evidence.py` | Modify(worktree,+5 行注释) | 在 `has_forex_computed_marker` 内钉住 negative-prefix 前提 |
| (squash commit message) | 新建(主 checkout) | 承载 §3 两侧差异矩阵(durable 记录) |
| `optimization/20260610_refactor_plan/TODOS.md` | Modify(主 checkout) | PR-C0 → 完成 |
| worktree + 分支 | 删除 | 收尾清理 |

---

## Task 0:确认起点与 baseline

**Files:** 无(只读校验)

- [ ] **Step 1: 确认两个 checkout 的 tip**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git rev-parse --short main && git -C .worktrees/codex-batch-c0-forex-evidence rev-parse --short HEAD'
```
Expected: 第一行 `5b1d692`(或更新,但不应落后);第二行 `35b3145`。
若 worktree tip 不是 `35b3145` → **停-回报**(分支已被改动,本计划基线失效)。

- [ ] **Step 2: worktree 上 forex characterization baseline(纯同步,必绿)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c0-forex-evidence && ALLOW_SYSTEM_PYTHON=1 bash run_clean.sh python -m pytest tests/test_forex_evidence_characterization.py -q'
```
Expected: 该文件全部用例 PASS,`0 failed`(只收这一个文件,无 async,故不受 worktree 缺 pytest-asyncio 影响)。
失败处理:用例 `failed` → **停-回报**(基线已坏);仅环境/venv 错(无法启动 pytest)→ 记录该错并**停-回报**(本计划依赖 worktree 可跑该文件)。

---

## Task 1:加 negative-prefix 前提注释(分支上)

**Files:**
- Modify: `/mnt/d/cursor/datasource/.worktrees/codex-batch-c0-forex-evidence/src/datasource/utils/forex_evidence.py:349-350`

> 这是**非行为**变更(仅注释)。不新增测试;以"既有 forex characterization 仍绿"为验证。

- [ ] **Step 1: 插入注释**

把 `has_forex_computed_marker` 内这段(当前 L349–L350):
```python
    tokens = set(re.split(r"[^a-z0-9_]+", text))
    negative_prefixes = ("failed", "failure", "error", "invalid", "unavailable")
```
改为:
```python
    tokens = set(re.split(r"[^a-z0-9_]+", text))
    # NOTE(PR-C0): the negative-prefix skip below assumes no entry in `markers`
    # itself starts with one of these prefixes. All STAGE2_*/STAGE25_* marker
    # tuples satisfy this today. If a future marker begins with
    # failed/failure/error/invalid/unavailable, the `token == marker_token`
    # branch would be wrongly skipped here, diverging from the pre-C0 Stage2.5
    # `_has_forex_*_change_computed_marker` (which gated only the endswith branch).
    negative_prefixes = ("failed", "failure", "error", "invalid", "unavailable")
```

- [ ] **Step 2: 校验注释未改行为(forex characterization 仍绿)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c0-forex-evidence && ALLOW_SYSTEM_PYTHON=1 bash run_clean.sh python -m pytest tests/test_forex_evidence_characterization.py -q'
```
Expected: 与 Task 0 Step 2 相同,全 PASS,`0 failed`(注释为非行为变更,行为锁不应有任何变化)。

- [ ] **Step 3: 校验 diff 仅这一处注释**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c0-forex-evidence && git --no-pager diff --stat'
```
Expected: 仅 `src/datasource/utils/forex_evidence.py | 6 +++++` 一个文件。
若有其它文件 → **停-回报**。

- [ ] **Step 4: 在分支提交**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c0-forex-evidence && git add src/datasource/utils/forex_evidence.py && git commit -m "docs: pin negative-prefix assumption in forex computed-marker helper"'
```
Expected: 1 file changed。分支 tip 前进一格。

---

## Task 2:squash 合入 main(§3 矩阵入 commit body)

**Files:** 主 checkout `/mnt/d/cursor/datasource`(分支 `main`)

- [ ] **Step 1: 主 checkout 干净 + 在 main**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git status --short && git rev-parse --abbrev-ref HEAD'
```
Expected: 末行 `main`;`git status --short` 仅可能有 `.gstack/`(untracked,可忽略)与 `.claude/settings.local.json`。**若有其它未提交改动 → 停-回报**(不要在脏树上 squash)。

- [ ] **Step 2: squash-merge 分支(staged,不自动 commit)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git merge --squash codex/batch-c0-forex-evidence'
```
Expected: `Squash commit -- not updating HEAD`,且无 conflict(main 的 `5b1d692` 只动 plan 文档,不碰 5 个实现文件)。
若报 conflict → **停-回报**。

- [ ] **Step 3: 确认 staged 范围正是 6 文件(5 实现 + 1 注释同文件)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager diff --cached --stat'
```
Expected: 恰好这 5 个文件:
```
scripts/stage2_5_injector.py
scripts/stage2_unified_enhancer.py
src/datasource/utils/forex_evidence.py
src/datasource/utils/note_utils.py
tests/test_forex_evidence_characterization.py
```
(注释并入 `forex_evidence.py`,所以仍是 5 个。)若多出文件 → **停-回报**。

- [ ] **Step 4: 用 §3 矩阵 commit body 提交**

先用**文件写入工具**(不经 shell,避免引号转义)把下列内容**逐字**写入
`/mnt/d/cursor/datasource/.git-c0-squash-msg.txt`:

```text
refactor: consolidate forex evidence family into shared utils (PR-C0)

把 Stage2/Stage2.5 成对的 forex 证据判定族下沉到
src/datasource/utils/forex_evidence.py,_append_note 族下沉到
src/datasource/utils/note_utils.py。纯保行为合一(方案 B):共享 SHAPE 原语注入
is_absence/coerce;两套谓词以 stage2_/stage25_ 命名分别保留。跨侧 characterization
tests 先写后搬,锁住现行为。

§3 两侧语义差异矩阵(保留,不统一):
- absence 文本判定:Stage2(is_stage2_forex_absence_text)与 Stage2.5
  (is_stage25_forex_daily_change_absence_text)口径不同——空串/N/A/unknown/pending
  在 Stage2 视为"非缺失"、在 Stage2.5 视为"缺失";Stage2 含 "no change" 消歧,
  Stage2.5 无。两套谓词分别保留,未统一。
- 数值强转:Stage2 _safe_number 严格(拒 "1,234"/"7.13%"),Stage2.5 _coerce_float
  宽松(接受并抽取数字)。经 functools.partial 注入各侧 coerce 保留,未统一。
  证据:tests/test_forex_evidence_characterization.py::
  test_forex_number_coercion_keeps_stage_specific_semantics。
- marker 常量:STAGE2_* 与 STAGE25_* 两侧取值不同,未合并(两套独立常量)。
  证据:test_forex_marker_constants_are_not_accidentally_merged。
- evidence key tuples:两侧相同,已集中到共享 FOREX_COMPARE_FIELD_EVIDENCE_KEYS。
- note 三函数(append_note_text / append_note_once / append_note_to_entry):
  分隔符/去重/返回语义各不相同,仅迁移共置,未合并。
  证据:test_note_helper_semantics_are_distinct。

consumers/orchestration(_scrub_unevidenced_forex_zeroes / _copy_forex_compare_fields /
_should_backfill_forex_* / _usable_forex_* 等)未搬移,留待 C1/C4。
行为冻结区(forex 零值防占位)逻辑零改动。

验证:forex characterization + 236 focused + 1039 full(主 .venv)全绿;
duplicate-helper grep gates 为空;constant audit ok。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

再提交并清理临时文件:
Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git commit -F .git-c0-squash-msg.txt && rm -f .git-c0-squash-msg.txt'
```
Expected: 提交成功,main tip 前进一格(squash commit);临时文件已删。

- [ ] **Step 5: 零 diff 校验(5 实现文件,main vs 分支)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager diff main codex/batch-c0-forex-evidence -- src/datasource/utils/forex_evidence.py src/datasource/utils/note_utils.py scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py tests/test_forex_evidence_characterization.py'
```
Expected: **空输出**(squash 已完整捕获分支的全部实现改动)。
若非空 → **停-回报**(squash 漏内容,不要继续清理分支)。

---

## Task 3:全量回归 + TODOS 状态

**Files:**
- Modify: `/mnt/d/cursor/datasource/optimization/20260610_refactor_plan/TODOS.md`

- [ ] **Step 1: 主 checkout 全量回归(好 .venv)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m pytest -q'
```
Expected: 全绿(基线 `1039 passed, 3 skipped` 量级;passed 数不应低于该基线)。
若有 failed → **停-回报**(squash 引入回归)。

- [ ] **Step 2: 把 PR-C0 标完成**

把 `optimization/20260610_refactor_plan/TODOS.md` 中这段:
```markdown
- [~] **PR-C0**:forex 证据判定族合一(先 characterization tests,后合一;两侧语义差异记录在 PR)
  - [x] brainstorming 定稿:`docs/superpowers/specs/2026-06-13-batch-c0-forex-evidence-consolidation-design.md`(纯保行为 + 共享底层 + 三样全入 + 跨侧参数化 characterization)
  - [ ] 生成 PR-C0 执行计划(从 HEAD 现生成)→ Codex 执行 → Claude 评审 → 合入
```
改为:
```markdown
- [x] **PR-C0**:forex 证据判定族合一(先 characterization tests,后合一;两侧语义差异记录在 PR)
  - [x] brainstorming 定稿:`docs/superpowers/specs/2026-06-13-batch-c0-forex-evidence-consolidation-design.md`(纯保行为 + 共享底层 + 三样全入 + 跨侧参数化 characterization)
  - [x] 执行计划 `docs/superpowers/plans/2026-06-13-batch-c0-review-followups.md` → Codex 执行 → Claude 评审 → squash 合入 main(§3 矩阵入 commit body)
```

同时把总览表的批次 C 行:
```markdown
| 批次 C | 巨石拆分(含 C-0.5/C0) | 5–7 | 🚧 进行中(C-0.5 完成;C0 设计定稿) | B |
```
改为:
```markdown
| 批次 C | 巨石拆分(含 C-0.5/C0) | 5–7 | 🚧 进行中(C-0.5/C0 完成;下一步 C1) | B |
```

同时把"当前焦点"行:
```markdown
**当前焦点:PR-C0(forex 证据判定族合一)——设计定稿,待生成执行计划。**
```
改为:
```markdown
**当前焦点:PR-C1(Stage2 拆分 errors/snippet_filters/evidence/regex_extraction)——待 brainstorming/计划。**
```

- [ ] **Step 3: 提交 TODOS**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git add optimization/20260610_refactor_plan/TODOS.md && git commit -m "docs: mark PR-C0 complete in refactor TODOS"'
```
Expected: 1 file changed。

---

## Task 4:推送 + 清理 worktree/分支

**Files:** 无(git 管理操作)

- [ ] **Step 1: 推送 main**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git push origin main'
```
Expected: 远端 main 更新到本地 tip(fast-forward)。若 rejected(远端有新提交)→ **停-回报**,不要 force。

- [ ] **Step 2: 移除 worktree**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree remove .worktrees/codex-batch-c0-forex-evidence --force && git worktree prune'
```
Expected: worktree 目录移除,无报错。

- [ ] **Step 3: 删除已并入的分支(本地 + 远端)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git branch -D codex/batch-c0-forex-evidence'
```
Expected: `Deleted branch codex/batch-c0-forex-evidence`。
(远端若存在同名分支再删:`git push origin --delete codex/batch-c0-forex-evidence`;不存在则跳过。)

- [ ] **Step 4: 隔离断言 + 完成回报**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree list && git log --oneline -3 && git status --short'
```
Expected: worktree 列表无 `codex-batch-c0-forex-evidence`;`git log` 顶部是 TODOS 提交 + C0 squash 提交;`git status` 仅 `.gstack/`/`.claude/settings.local.json`。
回报:squash SHA、全量 pytest 结果、零-diff 校验结论、已删 worktree/分支。

---

## Self-Review(规划方自查)

- **Spec 覆盖**:Important 过程项(§3 矩阵)→ Task 2 Step 4 commit body 全文落地;Minor(negative-prefix 注释)→ Task 1;squash 合入 → Task 2;TODOS → Task 3;worktree 清理 → Task 4。✅ 全覆盖。
- **Placeholder 扫描**:无 TBD/TODO;矩阵正文、注释正文、TODOS 改文均给完整文本;命令均带 Expected 与失败分支。✅
- **一致性**:文件路径、分支名(`codex/batch-c0-forex-evidence`)、tip(`35b3145`/`5b1d692`/`4904f15`)、5 文件清单跨 Task 一致;零-diff 校验显式限定 5 实现文件(规避 main `5b1d692` plan-doc 提交造成的非空噪声)。✅
- **离线**:无任何真实 API 调用;pytest 全离线。✅
