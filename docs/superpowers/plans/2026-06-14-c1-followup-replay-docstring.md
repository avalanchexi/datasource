# PR-C1 评审尾项:replay harness 前向卫生 docstring 补回 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `tests/test_stage2_replay_harness.py` 的 `_freeze_stage2_datetime` helper 补回一段前向卫生 docstring(C1 实现时丢失),提醒 C2–C5 移动写时间戳代码时必须扩展冻结循环;纯测试侧、零行为变更。

**Architecture:** 单文件、单函数的 docstring 新增。该 helper 在 replay 全链路测试中统一冻结 stage2 主脚本 + 三个拆分/工具模块的 `datetime`,使 golden byte-stable;它取代了 C1 评审中删掉的生产侧测试缝 `_sync_runtime_datetime_globals`。本 plan **只加 docstring,不改签名、不改冻结逻辑、不改调用点、不重算 golden**。

**Tech Stack:** Python;pytest(含 async replay harness,需 `pytest-asyncio`);git;本机 Windows + WSL(Linux `.venv`)。

---

## 背景与定位(Codex 零上下文必读)

**这是什么。** PR-C1(`refactor: split stage2 helper modules`,squash 提交 `e59f307`)已合入并推送 main。评审(Claude)给出两个 Minor:

1. **Minor #2(死别名)= 不存在,本 plan 不处理。** 规划方已核验 merged main:`grep` 主脚本 `_stage2_errors_module / _stage2_snippet_filters_module / _policy_rules_module / _sync_runtime_datetime_globals` **零匹配**。Fix A 实际把这些别名连同 sync 函数一起删净了。评审是从历史计划文本("L35-37 保留不动")推断,与实际代码不符。**Codex 不要去找/删这些别名——它们已不存在。**

2. **Minor #1(本 plan 唯一目标)= helper 缺 docstring。** `_freeze_stage2_datetime` 当前(`tests/test_stage2_replay_harness.py` L365)**没有任何 docstring**。C1 评审 followup 计划原本要求它带一段说明 + C2–C5 前向卫生提醒,但实际实现把 docstring 丢了。本 plan 把这段 docstring 补回,且**改写为匹配当前实现的循环写法**(当前用 `for module in (...)` 元组,不是计划里旧的 `setattr(<new_module>, ...)` 单行写法)。

**为什么值得做(不是纯洁癖)。** 该 helper 的冻结集 `{stage2, errors, snippet_filters, policy_rules}` 是当前所有时间戳来源的完整覆盖,replay golden 的确定性依赖它。C2–C5 若把写时间戳(`datetime.now/utcnow/today`)的代码搬进新的 stage2 拆分模块**却忘了把新模块加进冻结循环**,replay 会因未冻结的时间源而非确定性失败——而且会是难排查的偶发 golden mismatch。docstring 把这条约束写在代码旁,是低成本的前向防呆。

**为什么不动签名(规划方决定,Codex 不得擅自改回)。** 评审提到可"对齐签名"到旧计划的 `(monkeypatch, stage2_module, fixed_dt_cls)`。**本 plan 明确拒绝该改动**:当前签名 `(stage2, monkeypatch)` 把 `fixed_now`/`FixedDatetime` 内聚进 helper,自洽且调用点更干净(评审自己也认 "arguably cleaner")。回退是设计退步,且无 parity 收益(未来 C2–C5 plan 按实际代码写)。**Codex 只加 docstring,签名、参数顺序、`FixedDatetime` 构造、冻结循环一律逐字不动。**

## 硬约束(违反即停-回报)

- **只动一个文件、一处**:`tests/test_stage2_replay_harness.py` 的 `_freeze_stage2_datetime` 函数体首行插入 docstring。**禁止**改该函数的签名、`from ... import` 三行、`fixed_now`、`FixedDatetime` 类、`for module in (...)` 循环、`monkeypatch.setattr` 行;**禁止**改调用点(L513 `_freeze_stage2_datetime(stage2, monkeypatch)`);**禁止**碰本文件任何其它函数/测试;**禁止**碰任何 `src/` 生产代码。
- **零行为变更 / 零 golden 重算**:docstring 不改变任何运行时行为。**绝不**设 `STAGE2_REPLAY_UPDATE_GOLDEN=1`,**绝不**改写 `tests/fixtures/stage2_replay/golden/` 下任何文件。若验证时出现 golden mismatch → **停-回报**(说明你误改了 docstring 以外的东西)。
- **离线**:本 plan 全部验证离线(pytest / flake8),零真实 API。**不重跑 Stage2 真实搜索**(Tavily 每日一次);**不碰** `data/runs/YYYYMMDD`(当日)与 `data/trend_history`;**不手删** `.run.lock`。
- **行为冻结区不触碰**:official manual override allowlist(mlf/USDCNY/BCOM)、fund_flow 估算 gate、forex 零值防占位、Stage3 三路 gate——本 plan diff 不得涉及(本来就不在改动范围内,列此防误伤)。

## 环境头(Codex 零上下文必读)

- **执行通道**:本机 Windows。**Bash 工具在本机损坏**(MSYS `dofork`/`errno 11` fork 失败),**不要用 Bash 工具跑 git/pytest**。每条 shell 命令经 `wsl -e bash -lc '...'` 进入 Linux 侧(`.venv` 是 Linux venv)。需要快速看 git 状态时也可用 PowerShell 工具跑 `git`(只读查询),但 **pytest/flake8 一律走 WSL + `run_clean.sh`**。
- **当前 checkout 即工作区(按用户要求不新建隔离 worktree)**:`/mnt/d/cursor/datasource`,分支 `main`,tip 应为 `e59f307`。
- **默认分支保护**:`main` 是默认分支,**先建小分支再改**(Task 1 Step 1),不要直接在 `main` 上 commit。
- **测试命令**:一律 `bash run_clean.sh python -m pytest ...`,不直跑 pytest(`run_clean.sh` 负责 `.env`/`PYTHONPATH=./src`/清代理/激活 `.venv`)。本 plan 要跑 **async replay harness**,需 `pytest-asyncio`;若缺,先 `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V` bootstrap dev 依赖,再跑;仍不行 → **停-回报**。
- **Commit 规范**:Conventional(`docs:` 或 `test:`)。本 plan 只一个 commit。

---

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `tests/test_stage2_replay_harness.py` | Modify | 在 `_freeze_stage2_datetime`(L365)函数体首行插入 docstring;其余逐字不动 |

无新建文件、无生产代码改动。

---

## Task 0:确认起点与 baseline(只读)

**Files:** 无

- [ ] **Step 1: 确认当前 checkout 在 main 且 tip 正确、工作树干净**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD && git status --short'
```
Expected:分支 `main`;short SHA `e59f307`;`git status --short` 只可能含 `.gstack/`(untracked)、`.claude/settings.local.json`、`docs/superpowers/...`(本 plan 等计划文档,untracked)。若有其它**已跟踪文件**的未提交改动 → **停-回报**。

- [ ] **Step 2: 确认目标函数当前无 docstring、签名为 `(stage2, monkeypatch)`**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && sed -n "365,386p" tests/test_stage2_replay_harness.py'
```
Expected:第一行是 `def _freeze_stage2_datetime(stage2, monkeypatch):`,**紧接着是 `from datasource.engines.stage2 import errors as stage2_errors`**(即无 docstring)。若已有 docstring 或签名不同 → **停-回报**(代码与本 plan 假设不符)。

- [ ] **Step 3: baseline 跑 replay + characterization(确认现态全绿、能跑 async、golden 一致)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py tests/test_stage2_split_characterization.py -q 2>&1 | tail -8'
```
Expected:全 PASS(`test_stage2_replay_harness.py` 收集 **2 个** test:`test_replay_execute_tasks_chains`、`test_replay_full_main`,均 pass;characterization 全用例 pass)。记录 passed 总数。
若报 `pytest-asyncio` 缺失/async 收集错 → 先按环境头 bootstrap dev 依赖再重跑本 step;仍失败 → **停-回报**。

---

## Task 1:补回 docstring + 验证 + 提交

**Files:**
- Modify: `tests/test_stage2_replay_harness.py`(`_freeze_stage2_datetime` 函数体首行插入 docstring)

- [ ] **Step 1: 建小分支**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git switch -c codex/c1-followup-replay-docstring'
```
Expected:`Switched to a new branch 'codex/c1-followup-replay-docstring'`。已存在同名分支 → **停-回报**。

- [ ] **Step 2: 插入 docstring(精确替换)**

用编辑工具把这段(当前 L365–366,逐字):
```python
def _freeze_stage2_datetime(stage2, monkeypatch):
    from datasource.engines.stage2 import errors as stage2_errors
```
替换为(在 `def` 行后插入 docstring,`from` 行原样保留):
```python
def _freeze_stage2_datetime(stage2, monkeypatch):
    """冻结 stage2 主脚本及所有读取 datetime 的拆分/工具模块的时间,使 replay golden byte-stable。

    取代 C1 评审中删除的生产侧测试缝 _sync_runtime_datetime_globals():datetime 冻结改由
    测试侧统一 monkeypatch。当前冻结集 = 下面 `for module in (...)` 元组列出的 4 个模块
    (stage2 主脚本 + engines.stage2.errors + engines.stage2.snippet_filters +
    utils.policy_rules),覆盖当前全部时间戳来源。

    前向卫生(C2–C5 必读):后续若把写时间戳(datetime.now/utcnow/today)的代码搬进新的
    stage2 拆分模块,必须把该模块也加进下面的 `for module in (...)` 元组,否则未冻结的
    时间源会让 replay 输出非确定性、表现为偶发 golden mismatch。
    """
    from datasource.engines.stage2 import errors as stage2_errors
```
> ⚠️ 仅此一处。`from datasource.engines.stage2 import snippet_filters as stage2_snippet_filters`、`from datasource.utils import policy_rules`、`fixed_now = ...`、`class FixedDatetime(...)`、`for module in (...)` 循环、`monkeypatch.setattr(module, "datetime", FixedDatetime)`、以及调用点 L513 **全部逐字不动**。

- [ ] **Step 3: 确认只改了 docstring(diff 自检)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager diff --stat && echo "---" && git --no-pager diff'
```
Expected:`--stat` 仅 `tests/test_stage2_replay_harness.py | N +`(纯新增,N≈8–9 行,**0 删除**);`diff` 全部为 docstring 的 `+` 行,**无任何已有代码行的删除/修改**。出现删除行或改到 docstring 以外 → **停-回报**并 `git checkout -- tests/test_stage2_replay_harness.py` 回退重做。

- [ ] **Step 4: replay + characterization 仍全绿且 golden 一致(关键)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py tests/test_stage2_split_characterization.py -q 2>&1 | tail -8'
```
Expected:passed 数 = Task 0 Step 3 baseline(replay 2 passed,characterization 全绿)。
**关键**:**绝不**带 `STAGE2_REPLAY_UPDATE_GOLDEN`。若出现 golden mismatch/byte 变化 → **停-回报**(docstring 不可能改行为,说明 Step 2 误改了别处);**不要**重算 golden。

- [ ] **Step 5: flake8 不增违规**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m flake8 tests/test_stage2_replay_harness.py 2>&1 | tail -5'
```
Expected:无输出(无新违规;docstring 行注意 ≤ 项目行宽,上文已按 ~95 列内书写)。若报行过长(E501)→ 在不改语义前提下把超长行折成两行,重跑本 step。

- [ ] **Step 6: 提交**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git add tests/test_stage2_replay_harness.py && git commit -m "docs: restore forward-hygiene docstring on _freeze_stage2_datetime (PR-C1 review)"'
```
Expected:1 file changed,纯新增行。

---

## Task 2(可选,需用户显式同意后再执行):合入 main + 推送

> 本 plan 的交付物是 Task 1 提交在 `codex/c1-followup-replay-docstring` 分支上的修复。是否合入/推送 main 由**用户决定**;未获显式同意前 **Codex 不得执行本 Task**。

**Files:** 主 checkout `/mnt/d/cursor/datasource`

- [ ] **Step 1: 确认分支只有这一个 commit、可 fast-forward**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager log --oneline main..codex/c1-followup-replay-docstring'
```
Expected:恰好 1 行(本次 docs commit)。多于 1 行 → **停-回报**。

- [ ] **Step 2: fast-forward 合入 main**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git switch main && git merge --ff-only codex/c1-followup-replay-docstring'
```
Expected:`Fast-forward`,无 conflict。非 ff(main 已前进)→ **停-回报**,不要 force。

- [ ] **Step 3: 推送 + 清理分支**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git push origin main && git branch -d codex/c1-followup-replay-docstring'
```
Expected:fast-forward push 成功;本地分支删除。rejected → **停-回报**,不要 force。

- [ ] **Step 4: 隔离断言 + 回报**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git log --oneline -3 && git status --short'
```
Expected:`git log` 顶部是本次 docs commit;`git status` 仅 `.gstack/`/`.claude/settings.local.json`/计划文档(untracked)。
回报:commit SHA、replay 2 passed + golden 一致确认、是否已推送 main。

---

## Self-Review(规划方自查)

- **Spec 覆盖**:Minor #1 → Task 1(补 docstring + diff 自检 + replay/golden 不变 + flake8);Minor #2 → 背景节明确"不存在,不处理"。✅
- **Placeholder 扫描**:无 TBD;Step 2 给出完整 old/new 代码块;每条命令带 Expected 与停-回报分支。✅
- **一致性**:helper 名 `_freeze_stage2_datetime`、调用点 L513、冻结模块集 `{stage2, errors, snippet_filters, policy_rules}` 与文件实际(L365–385)对齐;docstring 文案描述的 `for module in (...)` 循环与实现写法一致(非旧计划的 `setattr(<new_module>, ...)` 单行写法)。✅
- **零行为变更**:仅新增 docstring;Task 1 Step 4 明确"golden mismatch 即停-回报、不重算"。✅
- **范围最小**:单文件单处;明确拒绝改签名/调用点/冻结逻辑,列入硬约束。✅
