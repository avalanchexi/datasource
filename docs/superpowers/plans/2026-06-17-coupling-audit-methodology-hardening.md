# 跨模块耦合审计收口 + 方法论加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 把 C4/C7/F1 三次教训固化进重构方法论清单(① 反向依赖/跨脚本 import 漏判;② relocate 类 PR 的 byte-for-byte vs black-after-move 格式约定),记录 C7 后跨模块耦合审计的体检单(src→scripts 反向耦合=0),并顺手清一个 cosmetic docstring。**纯文档/注释改动,零代码逻辑、零测试逻辑。**

**Architecture:** 三处文档/注释编辑:① `optimization/20260610_refactor_plan/REFACTOR_PLAN.md` §11.2 plan 精准性清单加两条(反向依赖核查 + relocate 格式约定);② 同目录 `TODOS.md` 记审计体检单;③ `src/datasource/engines/stage2_5/schema_coercion.py` 一句 docstring 文案。无运行时行为变化。

**Tech Stack:** Markdown / Python docstring;pytest(仅跑文档契约测试确认无漂移);git;Windows + WSL。

> 背景:C7 跨模块耦合审计结论——C7 合入后 `src/` 对 `scripts` **零 import**(反向分层耦合彻底消解);C4 reclaim + C7 瘦身 + lc_pipeline 修复已清掉"模块延迟/直接 import 脚本私名"模式。无清理 PR 可做;本计划只固化教训 + 留痕。

---

## 环境头(Codex 零上下文必读)
- **Bash 工具坏**;命令经 `wsl -e bash -lc '...'`;pytest 走 `run_clean.sh`;只读 git 可用 PowerShell。
- **落地基**:本计划是 doc/注释级,**待 C6/C7 合入 main 后**在最新 main 上开小分支执行(schema_coercion.py 的 docstring 在 C4 引入、C7 不动,合入后存在于 main)。若 C6/C7 尚未合入,先合入再做本计划。
- 硬约束:不改任何代码逻辑/测试逻辑;不碰 `data/`;全程离线。
- Commit:Conventional(`docs:`/`refactor:`)。

---

## Task 0:确认起点
- [ ] **Step 1** 确认 C6/C7 已合入 main(`git --no-pager log --oneline -4 main` 含 PR-C6、PR-C7 squash);在最新 main 开分支 `codex/coupling-audit-followup`。
- [ ] **Step 2** baseline:`bash run_clean.sh python -m pytest tests/test_manual_template.py tests/test_stage4_docs.py -q 2>&1 | tail -3` 全绿(文档契约基线)。

## Task 1:REFACTOR_PLAN §11.2 加两条方法论(反向依赖核查 + relocate 格式约定)
**Files:** Modify `optimization/20260610_refactor_plan/REFACTOR_PLAN.md`
- [ ] **Step 1** 在 §11.2「plan 精准性检查清单」末尾新增一条(逐字):
```markdown
- **反向依赖核查(C4/C7 教训)**:任何"搬模块 / 瘦入口 / 删 re-export / 把脚本私名移走"的 plan,必须先枚举**谁 import 了被动的东西**——`grep -rn "from <被动模块> import\|import <被动模块>" src/ scripts/ tests/`、并查 `src/` 内是否有函数体内**延迟 import 脚本私名**(`grep -rn "from scripts\.\|import scripts\." src/`)。只看正向调用图会漏判反向依赖方:C4 漏了 `extraction_apply` 跨脚本 import fund_flow helper;C7 漏了 `stage2_lc_pipeline` 延迟 import 脚本私名。fan-out 勘探与 plan 都要把这步列为强制项。
```
- [ ] **Step 1b** 在 §11.2 同一清单再加一条(逐字):
```markdown
- **relocate/搬移类 PR 的格式约定(C 批 vs F1 教训)**:搬移代码默认 **byte-for-byte(逐字搬)**,便于用 is-identity/token/AST 等价秒验行为保持;搬移文件继承的非 black 风格用 per-file flake8 ignore(如 E501),**搬移 PR 内不跑 black**。仅当该模块有 byte-stable 行为网(golden / characterization / replay)能独立证等价时,才允许 **black-after-move**(engines/ 代码 black 化更干净、免 per-file ignore);此时 plan 必须**显式声明走 black-after-move** + 评审改用 golden/replay byte-stable 判定(而非 byte-identity)。**禁止"跑了 black 又按 byte-identity 评审"导致 body-check DRIFT 无法判定。** 先例:C1–C7 走 byte-for-byte;F1(stage3)走 black-after-move(golden 证等价)。
```
- [ ] **Step 2** 校验:`wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m pytest tests/test_manual_template.py tests/test_stage4_docs.py -q 2>&1 | tail -3'`(REFACTOR_PLAN 非 runbook,预期不触发命令契约;确认仍绿)。commit `docs: add reverse-dependency check + relocate-format convention to §11.2 (C4/C7/F1 lessons)`。

## Task 2:TODOS 记审计体检单
**Files:** Modify `optimization/20260610_refactor_plan/TODOS.md`
- [ ] **Step 1** 在「全局验收(收尾)」相关处加一行:
```markdown
- [x] 跨模块耦合审计(2026-06-17,C7 后):`src/` 对 `scripts` 零 import,反向分层耦合彻底消解;C4 fund_flow reclaim + C7 入口瘦身已清掉"模块 import 脚本私名"模式。无清理 PR,留痕收口。
```
- [ ] **Step 2** commit `docs: record post-C7 cross-module coupling audit (clean) in TODOS`。

## Task 3:schema_coercion docstring cosmetic tidy
**Files:** Modify `src/datasource/engines/stage2_5/schema_coercion.py`
- [ ] **Step 1** 把 `_coerce_stage2_results_to_schema` docstring 里的 `stage2_5_injector 期望的 schema`(约 L110)改为 `Stage2.5 期望的 schema`(仅文案,语义不变)。
- [ ] **Step 2** 校验:`bash run_clean.sh python -m py_compile src/datasource/engines/stage2_5/schema_coercion.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage2_5/schema_coercion.py`。commit `docs: tidy schema_coercion docstring reference (PR follow-up)`。

## Task 4:验收 + 合入 + 回报
- [ ] **Step 1** 全量快测(确认 docstring 改动零影响):`bash run_clean.sh python -m pytest -q 2>&1 | tail -5` 全绿(数与 C7 合入后持平)。
- [ ] **Step 2** ff/squash 合入 main(本 PR 仅 3 文件 doc/注释,可 ff):`git switch main && git merge --ff-only codex/coupling-audit-followup`(非 ff 则 squash);push;`git branch -d codex/coupling-audit-followup`。
- [ ] **Step 3** 回报:commit 列表、§11.2 新增项确认、TODOS 体检单确认、全量 passed 持平。

---

## Self-Review
- 覆盖:方法论加固两条(反向依赖核查 + relocate 格式约定)→ Task 1(Step 1/1b);审计留痕 → Task 2;trivial docstring → Task 3;合入 → Task 4。✅
- Placeholder:无 TBD;三处编辑给逐字内容;命令带 Expected。✅
- 一致性:分支名 `codex/coupling-audit-followup`;落地在 C6/C7 合入后 main;纯 doc/注释零逻辑。✅
- 比例:doc 级小 PR,无 worktree ceremony(可直接在 main 小分支做)。✅
