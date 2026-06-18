# PR-C2 评审补救 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 C2 评审唯一 Important 项——cli.py 的 `_legacy_monolith_global` shim(全 PR 唯一非机械逻辑改动),让 `_build_structured_registry_for_args`/`_validate_proxies` 回到真正纯机械搬移(直读模块全局),并把 4 行既有测试的 monkeypatch 目标跟随被搬全局改指向 cli;然后从当前 main `9228cd5` squash 合入、清理 worktree。

**Architecture:** 两处都是零行为影响的代码卫生修复。删掉 cli 里 `sys.modules` 回查主脚本全局的 shim + 两个 `_DEFAULT_*` 缓存,把两个函数 body 还原成 base `9228cd5` 的原始直读版本(纯搬移自然态);既有测试原本 patch 主脚本全局,改为 patch cli 模块(与 `tests/test_stage2_replay_harness.py` 已有做法一致)。**不改任何 Stage2 业务逻辑、不重算 golden、不动其它 6 个新模块。**

**Tech Stack:** Python;pytest(含 async replay harness,需 pytest-asyncio);git worktree;本机 Windows + WSL(Linux `.venv`)。

> 评审记录:`_legacy_monolith_global`(`cli.py:39–50`)+ 调用点(`_build_structured_registry_for_args` L224、`_validate_proxies` L301)是 C2 唯一超出 `# noqa` 的逻辑改动,生产等价但引入 C2 模块→主脚本运行时软反向耦合,违反 spec §7 精神且未披露。本计划彻底移除它。

---

## 环境头(Codex 零上下文必读)

- **执行通道**:本机 Windows,**Bash 工具损坏**(MSYS `dofork`/`errno 11`)。每条 shell 命令经 `wsl -e bash -lc '...'`;只读 git 查询可用 PowerShell,但 **pytest/flake8/py_compile 一律 WSL + `run_clean.sh`**(负责 `.env`/`PYTHONPATH=./src`/清代理/激活 `.venv`)。
- **两个 checkout**:
  - 主 checkout(好 `.venv`):`/mnt/d/cursor/datasource`(分支 `main`,tip 应为 `9228cd5`)。
  - C2 实现 worktree:`/mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split`(分支 `codex/batch-c2-stage2-split`,tip `9514814`)。
- async replay harness 需 `pytest-asyncio`;若 worktree `.venv` 缺,先 `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V` bootstrap,再跑;仍不行 → **停-回报**。
- **这是 C2 评审收尾,不是重做 C2**:七模块抽取已完成并评审通过(冻结区逐字节、`_try_structured_provider` 正确留 C3、依赖无环、`is` 身份齐全)。Codex **只做**本计划的去 shim + 测试 repoint + 合入/清理,**严禁**改动模块抽取结构、冻结区(forex 零值防占位 / fund_flow gate)、`_safe_number`、`_try_structured_provider`、或重算 golden。
- **硬约束**:不重跑 Stage2 真实搜索(Tavily 每日一次);不碰当日 `data/runs/YYYYMMDD` 与 `data/trend_history`;不手删 `.run.lock`。本计划全程离线。
- **零数据影响已确认**:shim 在未被 patch 时 `default is original`,返回本地全局,生产路径与直读等价。去 shim + 测试 repoint 不改采集/搜索/抽取/写回行为,由 characterization `is` 身份 + replay byte-stable + 全量回归兜底。
- **Commit 规范**:Conventional(`refactor:`)。

---

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `src/datasource/engines/stage2/cli.py` | Modify | 删 `_legacy_monolith_global` + `_DEFAULT_HTTPX`/`_DEFAULT_BUILD_DEFAULT_REGISTRY`;`_build_structured_registry_for_args`/`_validate_proxies` 还原为直读 `build_default_registry`/`httpx`;若 `sys` 仅为 shim 引入则删其 import |
| `tests/test_stage2_proxy_validation.py` | Modify | `monkeypatch.setattr` 的 `httpx` 目标从主脚本改为 cli(L23) |
| `tests/test_stage2_structured_integration.py` | Modify | `monkeypatch.setattr` 的 `build_default_registry` 目标从主脚本改为 cli(L585/595/608) |
| (squash commit body) | 新建 | 记录 C2 七模块抽取 + 评审补救 |
| worktree + 分支 | 删除 | 收尾 |

---

## Task 0:确认起点与 baseline

**Files:** 无(只读校验)

- [ ] **Step 1: 确认 tips**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git rev-parse --short main && git -C .worktrees/codex-batch-c2-stage2-split rev-parse --short HEAD'
```
Expected:`9228cd5`(main)与 `9514814`(worktree)。任一不符 → **停-回报**。

- [ ] **Step 2: baseline(确认现态全绿、能跑 async)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && bash run_clean.sh python -m pytest tests/test_stage2_proxy_validation.py tests/test_stage2_structured_integration.py tests/test_stage2_replay_harness.py tests/test_stage2_c2_split_characterization.py -q 2>&1 | tail -5'
```
Expected:全 PASS。若报 `pytest-asyncio` 缺失 → 先按环境头 bootstrap,再重跑;仍失败 → **停-回报**。

- [ ] **Step 3: 取原始函数 body(还原参照)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && git show 9228cd5:scripts/stage2_unified_enhancer.py | sed -n "/^def _build_structured_registry_for_args/,/^def /p; /^def _validate_proxies/,/^def /p"'
```
Expected:打印两个函数在搬移前的原始 body(直读 `build_default_registry`/`httpx`,无 `_legacy_monolith_global`)。这是 Task 1 还原的逐字参照(仅允许 `# noqa` 行长标记差异)。

---

## Task 1:cli.py 去 shim,还原两个函数为直读全局

**Files:**
- Modify: `src/datasource/engines/stage2/cli.py`

- [ ] **Step 1: 删 shim 与 `_DEFAULT_*` 缓存**

删除 `cli.py` 中:
```python
_DEFAULT_HTTPX = httpx
_DEFAULT_BUILD_DEFAULT_REGISTRY = build_default_registry


def _legacy_monolith_global(name: str, default: Any, original: Any) -> Any:
    """Honor tests and callers that monkeypatch the old script module globals."""  # noqa: E501
    if default is not original:
        return default
    for module_name in ("scripts.stage2_unified_enhancer", "stage2_unified_enhancer"):  # noqa: E501
        module = sys.modules.get(module_name)
        if module is None:
            continue
        value = getattr(module, name, default)
        if value is not default:
            return value
    return default
```

- [ ] **Step 2: 还原 `_build_structured_registry_for_args` 为直读**

把:
```python
def _build_structured_registry_for_args(args: argparse.Namespace) -> Any:
    if getattr(args, "disable_structured_providers", False):
        return None
    registry_builder = _legacy_monolith_global(
        "build_default_registry",
        build_default_registry,
        _DEFAULT_BUILD_DEFAULT_REGISTRY,
    )
    if registry_builder is None:
        return None
    try:
        return registry_builder()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] structured provider registry init failed, fallback to search: {exc}")  # noqa: E501
        return None
```
改为(对齐 Task 0 Step 3 的原始 body):
```python
def _build_structured_registry_for_args(args: argparse.Namespace) -> Any:
    if getattr(args, "disable_structured_providers", False):
        return None
    if build_default_registry is None:
        return None
    try:
        return build_default_registry()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] structured provider registry init failed, fallback to search: {exc}")  # noqa: E501
        return None
```

- [ ] **Step 3: 还原 `_validate_proxies` 为直读 `httpx`**

把该函数里 `httpx_client = _legacy_monolith_global("httpx", httpx, _DEFAULT_HTTPX)` 删除,并把函数体内所有 `httpx_client` 改回 `httpx`(对齐 Task 0 Step 3 原始 body;逐字一致,仅 `# noqa` 行长可保留)。还原后该函数应直接判 `if httpx is None:`、调 `httpx.get(...)` 等。

- [ ] **Step 4: 残留引用 + 未用 import 校验**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && (grep -rn "_legacy_monolith_global\|_DEFAULT_HTTPX\|_DEFAULT_BUILD_DEFAULT_REGISTRY" src/ tests/ && echo "STILL-REFERENCED(BAD)" || echo "NO-REF(OK)") && bash run_clean.sh python -m py_compile src/datasource/engines/stage2/cli.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage2/cli.py'
```
Expected:`NO-REF(OK)`;py_compile 无输出;flake8 干净。**若 flake8 报 `sys` 未用(F401)**:删 `cli.py` 顶部的 `import sys`(它仅为 shim 引入);若报 `httpx`/`build_default_registry` 未用,说明还原没接上 → 排查。重跑本步直到干净。

---

## Task 2:4 行测试 monkeypatch 改指向 cli

**Files:**
- Modify: `tests/test_stage2_proxy_validation.py`
- Modify: `tests/test_stage2_structured_integration.py`

> 理由:被 patch 的全局 `httpx`/`build_default_registry` 已随函数搬到 cli;patch 目标跟随被搬符号,与 `tests/test_stage2_replay_harness.py` 已有做法一致。这是"跟随搬移"而非掩盖行为。

- [ ] **Step 1: test_stage2_proxy_validation.py**

确保文件顶部 import 有 `from datasource.engines.stage2 import cli as stage2_cli`(无则加,别名与 replay harness 一致)。把(约 L23):
```python
    monkeypatch.setattr(stage2, "httpx", FakeHttpx)
```
改为:
```python
    monkeypatch.setattr(stage2_cli, "httpx", FakeHttpx)
```

- [ ] **Step 2: test_stage2_structured_integration.py**

确保文件顶部 import 有 `from datasource.engines.stage2 import cli as stage2_cli`(无则加)。把三处(约 L585/595/608):
```python
    monkeypatch.setattr(stage2, "build_default_registry", lambda: registry)
    ...
    monkeypatch.setattr(stage2, "build_default_registry", lambda: object())
    ...
    monkeypatch.setattr(stage2, "build_default_registry", boom)
```
分别改为 `monkeypatch.setattr(stage2_cli, "build_default_registry", ...)`(三处,各保持原 lambda/对象/`boom` 实参不变)。

- [ ] **Step 3: 确认无残留 `stage2, "httpx"`/`stage2, "build_default_registry"` patch**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && grep -rn "setattr(stage2, \"httpx\"\|setattr(stage2, \"build_default_registry\"" tests/ && echo "STILL-PATCHING-MONOLITH(BAD)" || echo "REPOINTED(OK)"'
```
Expected:`REPOINTED(OK)`。

---

## Task 3:验证 + 提交

**Files:** 无

- [ ] **Step 1: 定向 + 全量回归**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && bash run_clean.sh python -m pytest tests/test_stage2_proxy_validation.py tests/test_stage2_structured_integration.py tests/test_stage2_replay_harness.py tests/test_stage2_c2_split_characterization.py -q 2>&1 | tail -8'
```
Expected:全 PASS(characterization 的 `is` 身份不受影响;两个被改测试仍验证同一逻辑)。失败 → **停-回报**。然后全量:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && bash run_clean.sh python -m pytest -q 2>&1 | tail -5 && bash run_clean.sh python -m py_compile src/datasource/engines/stage2/*.py scripts/stage2_unified_enhancer.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage2/'
```
Expected:`1169 passed, 3 skipped`(数不降);py_compile 无输出;flake8 干净。failed → **停-回报**。

- [ ] **Step 2: 提交**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c2-stage2-split && git add src/datasource/engines/stage2/cli.py tests/test_stage2_proxy_validation.py tests/test_stage2_structured_integration.py && git commit -m "refactor: drop _legacy_monolith_global shim; repoint moved-global monkeypatches to cli (PR-C2 review)"'
```
Expected:3 files changed。

---

## Task 4:squash 合入 main(基 = 当前 main `9228cd5`)

**Files:** 主 checkout `/mnt/d/cursor/datasource`

- [ ] **Step 1: 主 checkout 干净且在 main**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git switch main && git rev-parse --short HEAD && git status --short'
```
Expected:`9228cd5`;`git status --short` 仅可能 `.gstack/`/`.claude/settings.local.json`/`docs/superpowers/`(untracked 计划文档)。其它已跟踪改动 → **停-回报**。

- [ ] **Step 2: squash-merge 分支**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git merge --squash codex/batch-c2-stage2-split && git --no-pager diff --cached --stat'
```
Expected:`Squash commit -- not updating HEAD`,无 conflict。staged 应为:`scripts/stage2_unified_enhancer.py`、`src/datasource/engines/stage2/{common,cli,query_planner,structured_runner,diagnostics,validation,extraction_apply}.py`、`tests/test_stage2_c2_split_characterization.py`、`tests/test_stage2_replay_harness.py`、`tests/test_stage2_proxy_validation.py`、`tests/test_stage2_structured_integration.py`、`optimization/20260610_refactor_plan/TODOS.md`。**不应**含 docstring 重复(`9228cd5` 已在 main)。意外文件/conflict → **停-回报**。

- [ ] **Step 3: 写 commit body 并提交**

用文件写入工具把下列内容写入 `/mnt/d/cursor/datasource/.git-c2-squash-msg.txt`:
```text
refactor: split stage2 enhancer into common/cli/query_planner/structured_runner/diagnostics/validation/extraction_apply (PR-C2)

把 scripts/stage2_unified_enhancer.py(C1 后 5748 行)中 7 组内聚域机械抽取到
src/datasource/engines/stage2/{common,cli,query_planner,structured_runner,
diagnostics,validation,extraction_apply}.py,主脚本以 re-export 保持 zero
call-site churn。common 为共享底座(_safe_number/_RANGE_RULES/三个 UPSERT_META/
_is_force_refresh_task/_entry_for_task);依赖单向无环。

范围决策:
- _try_structured_provider(structured 执行车道编排器)留主脚本,随 _execute_tasks
  一并 C3 切分(它依赖 extraction_apply/diagnostics/validation 簇 + out-of-scope
  glue,搬入必产生反向 import)。
- _safe_number 仅搬位置到 common,未并入 utils/coercion(延后)。
- extraction_apply 保留 Stage2.5 fund_flow 跨脚本 import,标 # C4-cleanup。

评审补救(零行为影响):
- 删除 cli 的 _legacy_monolith_global shim,_build_structured_registry_for_args/
  _validate_proxies 还原为直读模块全局(纯搬移自然态)。
- 两个既有测试的 monkeypatch 目标随被搬全局从主脚本改指向 cli
  (test_stage2_proxy_validation / test_stage2_structured_integration),与
  replay harness 已有做法一致。

验证:characterization(is 身份 + import-surface)+ replay harness byte-stable +
全量回归 1169 passed, 3 skipped;冻结区(forex 零值防占位 / fund_flow gate)逐字节不变。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
再提交并清理:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git commit -F .git-c2-squash-msg.txt && rm -f .git-c2-squash-msg.txt'
```
Expected:提交成功,main tip 前进一格。

- [ ] **Step 4: 零-diff 校验(main vs 分支,全树)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager diff main codex/batch-c2-stage2-split'
```
Expected:**空输出**(main 基线自 `9228cd5` 未动,squash 完整捕获分支全部改动)。非空 → **停-回报**(不要继续清理分支)。

---

## Task 5:全量复跑(主 checkout)+ 推送 + 清理

**Files:** 无

- [ ] **Step 1: 主 checkout 全量回归(好 venv,权威)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m pytest -q 2>&1 | tail -5'
```
Expected:全绿,`1169 passed, 3 skipped`。failed → **停-回报**(可 `git reset --hard 9228cd5` 回退本次 squash 后回报)。

- [ ] **Step 2: 推送 main**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git push origin main'
```
Expected:fast-forward 成功。rejected → **停-回报**,不要 force。

- [ ] **Step 3: 清理 worktree + 分支**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree remove .worktrees/codex-batch-c2-stage2-split --force && git worktree prune && git branch -D codex/batch-c2-stage2-split'
```
Expected:worktree 移除、分支删除,无报错。(远端若有同名分支:`git push origin --delete codex/batch-c2-stage2-split`;无则跳过。)

- [ ] **Step 4: 隔离断言 + 回报**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree list && git log --oneline -3 && git status --short'
```
Expected:worktree 列表无 `codex-batch-c2-stage2-split`;`git log` 顶部是 C2 squash 提交;`git status` 仅 `.gstack/`/`.claude/settings.local.json`/计划文档。
**回报**:squash SHA、shim 已删(grep NO-REF)、4 行测试 repoint 清单、replay byte-stable + 全量 passed 数、零-diff 结论、已删 worktree/分支。

---

## Self-Review(规划方自查)

- **评审项覆盖**:唯一 Important(shim)→ Task 1(删 shim + 还原直读)+ Task 2(测试 repoint);合入/清理 → Task 3–5。✅
- **Placeholder 扫描**:无 TBD;Task 1/2 给完整 old/new 代码;Task 0 Step 3 给原始 body 提取命令作还原参照;commit body 全文;每命令带 Expected 与停-回报分支。✅
- **一致性**:别名 `stage2_cli` 在 Task 2 两文件一致;还原目标对齐 base `9228cd5`;squash 基 `9228cd5` 在 Task 4/5 一致;worktree 路径/分支名全程一致;`1169 passed, 3 skipped` 基线一致。✅
- **零行为 / 不越界**:仅删 shim + 还原直读 + 测试 patch 目标跟随被搬全局;不动其它 6 模块、冻结区、`_safe_number`、`_try_structured_provider`、golden。✅
