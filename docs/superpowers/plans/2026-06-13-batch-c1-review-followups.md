# PR-C1 评审偏差补救 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 C1 分支上消除评审两处偏差(B 重复 helper、A 生产测试缝),然后 squash 合入 main、清理 worktree。

**Architecture:** 两处都是零数据获取影响的代码卫生修复。B:主脚本删 `_structured_audit_fields_from_task` 本地副本,前向 import 自 errors.py(唯一定义)。A:删 main() 的 `_sync_runtime_datetime_globals`,把 replay 的 datetime 冻结改由 harness 的 test-side helper 统一 monkeypatch。**不改任何 forex/Stage2 业务逻辑,不重算 golden。**

**Tech Stack:** Python;pytest(含 async replay harness);git worktree;本机 Windows + WSL(Linux `.venv`)。

---

## 环境头(Codex 零上下文必读)

- **执行通道**:本机 Windows,**每条 shell 命令经 `wsl -e bash -lc '...'`**(不要用坏 MSYS bash;不要 PowerShell 跑 pytest)。
- **两个 checkout**:
  - 主 checkout(好 `.venv`):`/mnt/d/cursor/datasource`(分支 `main`,tip 应为 `0187b00`)。
  - C1 实现 worktree:`/mnt/d/cursor/datasource/.worktrees/codex-batch-c1-stage2-split`(分支 `codex/batch-c1-stage2-split`,tip `0f7cbdb`)。
- **测试命令**:一律 `bash run_clean.sh python -m pytest ...`,**不要直跑 pytest**(`run_clean.sh` 负责 `.env`/`PYTHONPATH=./src`/清代理/激活 `.venv`)。
  - 本计划要跑 **async replay harness**,需 `pytest-asyncio`。若 worktree `.venv` 缺它,用 `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V` 先 bootstrap(装 dev 依赖),再跑;仍不行 → **停-回报**。
- **这是 C1 评审收尾,不是重做 C1**:四模块抽取已完成并评审通过;Codex **只做**本计划两处修复 + 合入/清理,**严禁**改动模块抽取结构、forex 族、业务逻辑或重算 golden。
- **硬约束**:不重跑 Stage2 真实搜索(Tavily 每日一次);不碰 `data/runs/YYYYMMDD`(当日)与 `data/trend_history`;不手删 `.run.lock`。
- **行为冻结区**:official manual override allowlist(mlf/USDCNY/BCOM)、fund_flow gate、forex 零值防占位、Stage3 三路 gate——本计划 diff 不得触及。
- **零数据影响已确认**:B 两份逐字节相同;A 生产路径 no-op(只服务 replay 测试)。两处修复不改变采集/搜索/抽取/写回行为,由 replay byte-stable + 全量回归兜底。
- **Commit 规范**:Conventional(`refactor:/test:/docs:`),小步频提。

---

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `scripts/stage2_unified_enhancer.py` | Modify | B:删本地 `_structured_audit_fields_from_task` 定义、加入 errors import 块;A:删 `_sync_runtime_datetime_globals` 定义 + main() 调用 |
| `src/datasource/engines/stage2/errors.py` | 不变 | `_structured_audit_fields_from_task` 唯一定义(L217)保留 |
| `tests/test_stage2_replay_harness.py` | Modify | A:加 `_freeze_stage2_datetime` helper + `test_replay_full_main` 改调它 |
| (squash commit body) | 新建 | 记录 C1 抽取 + 两处偏差补救 |
| worktree + 分支 | 删除 | 收尾 |

---

## Task 0:确认起点与 baseline

**Files:** 无(只读校验)

- [ ] **Step 1: 确认 tips**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git rev-parse --short main && git -C .worktrees/codex-batch-c1-stage2-split rev-parse --short HEAD'
```
Expected: `0187b00`(main)与 `0f7cbdb`(worktree)。两者任一不符 → **停-回报**。

- [ ] **Step 2: baseline 跑 characterization + replay(确认现态全绿,且 worktree 能跑 async)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c1-stage2-split && bash run_clean.sh python -m pytest tests/test_stage2_split_characterization.py tests/test_stage2_replay_harness.py -q'
```
Expected: 全 PASS(characterization 全用例 + replay 7 passed)。
若报 `pytest-asyncio` 缺失/async 收集错 → 先 `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V` bootstrap,再重跑本 step;仍失败 → **停-回报**。

---

## Task 1:偏差 B — 前向 import 去重 `_structured_audit_fields_from_task`

**Files:**
- Modify: `.worktrees/codex-batch-c1-stage2-split/scripts/stage2_unified_enhancer.py`(import 块 L38-51;删 L1231-1242 定义)

> 行为恒等:errors.py L217 的定义与脚本 L1231 的定义逐字节相同;改为 import 后产出不变。

- [ ] **Step 1: 把 helper 加进 errors import 块**

把脚本中这段(L38-51):
```python
from datasource.engines.stage2.errors import (  # noqa: F401 (C1 re-export)
    _TAVILY_LIMIT_STATUSES,
    _TAVILY_ERROR_TEXT_LIMIT,
    _TAVILY_REQUEST_ID_HEADERS,
    _coerce_http_status,
    _safe_header_value,
    _sanitize_tavily_error_text,
    _tavily_error_metadata,
    _is_tavily_quota_error,
    _text_indicates_quota_or_rate_limit,
    _is_tavily_quota_response,
    _is_environment_proxy_error,
    _build_environment_proxy_error_records,
)
```
改为(在 `_build_environment_proxy_error_records,` 后加一行):
```python
from datasource.engines.stage2.errors import (  # noqa: F401 (C1 re-export)
    _TAVILY_LIMIT_STATUSES,
    _TAVILY_ERROR_TEXT_LIMIT,
    _TAVILY_REQUEST_ID_HEADERS,
    _coerce_http_status,
    _safe_header_value,
    _sanitize_tavily_error_text,
    _tavily_error_metadata,
    _is_tavily_quota_error,
    _text_indicates_quota_or_rate_limit,
    _is_tavily_quota_response,
    _is_environment_proxy_error,
    _build_environment_proxy_error_records,
    _structured_audit_fields_from_task,
)
```

- [ ] **Step 2: 删脚本本地重复定义**

删除脚本中这整段(原 L1231-1242,含尾随空行,使前后只留一个空行分隔):
```python
def _structured_audit_fields_from_task(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: task[key]
        for key in (
            "structured_provider_attempted",
            "structured_provider_fallback_reason",
            "structured_provider_latency_ms",
            "structured_provider_diagnostics",
            "structured_provider_name",
        )
        if key in task
    }
```
(删后下一个定义 `def _mark_structured_fallback_on_task(...)` 与上一段之间保持两个空行。)

- [ ] **Step 3: 校验只剩一个定义、import 生效**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c1-stage2-split && grep -rn "def _structured_audit_fields_from_task" scripts/ src/ && echo "---" && bash run_clean.sh python -c "import sys; sys.path.insert(0,\"scripts\"); import stage2_unified_enhancer as s; from datasource.engines.stage2 import errors as e; print(s._structured_audit_fields_from_task is e._structured_audit_fields_from_task)"'
```
Expected:`grep` 仅 1 行(`src/datasource/engines/stage2/errors.py:217:...`),脚本 0 行;末行 `True`(脚本名与 errors 同一对象)。
若脚本仍出现定义,或末行非 `True` → **停-回报**。

- [ ] **Step 4: characterization + replay 仍绿**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c1-stage2-split && bash run_clean.sh python -m pytest tests/test_stage2_split_characterization.py tests/test_stage2_replay_harness.py -q'
```
Expected: 全 PASS(replay 仍 7 passed)。失败 → **停-回报**。

- [ ] **Step 5: 提交**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c1-stage2-split && git add scripts/stage2_unified_enhancer.py && git commit -m "refactor: dedup _structured_audit_fields_from_task via forward import (PR-C1 review)"'
```
Expected: 1 file changed。

---

## Task 2:偏差 A — 删生产测试缝,datetime 冻结移到 replay harness

**Files:**
- Modify: `.worktrees/codex-batch-c1-stage2-split/scripts/stage2_unified_enhancer.py`(删 `_sync_runtime_datetime_globals` 定义 L243-247 + main() 调用 L5616)
- Modify: `.worktrees/codex-batch-c1-stage2-split/tests/test_stage2_replay_harness.py`(加 helper + 改 `test_replay_full_main`)

> 生产路径 no-op(正常运行 `datetime=datetime`);删后由测试侧统一冻结。

- [ ] **Step 1: 删 main() 里的调用**

把脚本 `async def main()` 开头这两行(L5615-5616):
```python
async def main() -> int:
    _sync_runtime_datetime_globals()
    args = _parse_args()
```
改为(删去调用行):
```python
async def main() -> int:
    args = _parse_args()
```

- [ ] **Step 2: 删 `_sync_runtime_datetime_globals` 定义**

删除脚本这整段(原 L243-247,含其前后空行,使删后上下两个定义间保持两个空行):
```python
def _sync_runtime_datetime_globals() -> None:
    """Keep extracted helpers aligned with tests that monkeypatch module datetime."""
    _stage2_errors_module.datetime = datetime
    _stage2_snippet_filters_module.datetime = datetime
    _policy_rules_module.datetime = datetime
```
注:脚本顶部 L35-37 的 `import ... as _stage2_errors_module / _stage2_snippet_filters_module / _policy_rules_module` **保留不动**(其它处可能仍引用;即便不引用也无害,本计划不动它们以缩小 diff)。

- [ ] **Step 3: 在 replay harness 加 test-side 冻结 helper**

在 `tests/test_stage2_replay_harness.py` 中、`def test_replay_full_main(` 之前,插入这个模块级 helper:
```python
def _freeze_stage2_datetime(monkeypatch, stage2_module, fixed_dt_cls):
    """Freeze datetime across the stage2 monolith and every split module that reads
    datetime, so replay output stays byte-stable. 取代旧的生产侧
    _sync_runtime_datetime_globals。后续 C2-C5 若把写时间戳的代码搬进新模块,
    在此处补 monkeypatch.setattr(<new_module>, "datetime", fixed_dt_cls)。"""
    from datasource.engines.stage2 import errors as _errors_mod
    from datasource.engines.stage2 import snippet_filters as _snip_mod
    from datasource.utils import policy_rules as _policy_mod

    for target in (stage2_module, _errors_mod, _snip_mod, _policy_mod):
        monkeypatch.setattr(target, "datetime", fixed_dt_cls)
```

- [ ] **Step 4: `test_replay_full_main` 改调 helper**

把该测试里这一行(原 L499):
```python
    monkeypatch.setattr(stage2, "datetime", FixedDatetime)
```
改为:
```python
    _freeze_stage2_datetime(monkeypatch, stage2, FixedDatetime)
```
(其上 `fixed_now = ...` 与 `class FixedDatetime(stage2.datetime): ...` 保持不变。)

- [ ] **Step 5: replay 全绿且 byte-stable**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c1-stage2-split && bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q'
```
Expected: **7 passed**(含 Level-1 `test_replay_execute_tasks_chains` 与 Level-2 `test_replay_full_main`)。
**关键**:若出现 golden 不一致/byte 变化或任一 replay fail → **停-回报**(说明 datetime 覆盖面假设有误,例如还有别的模块写时间戳未冻结);不要去重算 golden。

- [ ] **Step 6: 提交**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c1-stage2-split && git add scripts/stage2_unified_enhancer.py tests/test_stage2_replay_harness.py && git commit -m "test: move replay datetime freeze to harness helper; drop prod sync (PR-C1 review)"'
```
Expected: 2 files changed。

---

## Task 3:分支全量回归

**Files:** 无

- [ ] **Step 1: worktree 全量 pytest**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c1-stage2-split && bash run_clean.sh python -m pytest -q'
```
Expected: 全绿,passed 数 ≥ C1 基线 `1072`(本计划未加/删测试,数应持平 1072;replay/characterization 含其中)。
若 worktree venv 跑不了全量(async 等)→ 先按环境头 bootstrap;仍不行 → 记录并在 Task 4 合入后于主 checkout 复跑(见 Task 5 Step 1 备注)。failed → **停-回报**。

---

## Task 4:squash 合入 main

**Files:** 主 checkout `/mnt/d/cursor/datasource`

- [ ] **Step 1: 主 checkout 干净且在 main**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git rev-parse --abbrev-ref HEAD && git status --short'
```
Expected: `main`;`git status --short` 仅可能 `.gstack/`(untracked)与 `.claude/settings.local.json`。其它未提交改动 → **停-回报**。

- [ ] **Step 2: squash-merge 分支**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git merge --squash codex/batch-c1-stage2-split'
```
Expected: `Squash commit -- not updating HEAD`,无 conflict(main 自 `0187b00` 未动,分支基线即 `0187b00`)。conflict → **停-回报**。

- [ ] **Step 3: 确认 staged 范围**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager diff --cached --stat'
```
Expected: 这些文件:`scripts/stage2_unified_enhancer.py`、`src/datasource/engines/stage2/{__init__,errors,evidence,regex_extraction,snippet_filters}.py`、`tests/test_stage2_split_characterization.py`、`tests/test_stage2_replay_harness.py`、`optimization/20260610_refactor_plan/TODOS.md`。无意外文件 → 否则 **停-回报**。

- [ ] **Step 4: 写 commit body 文件并提交**

先用**文件写入工具**(免引号转义)把下列内容逐字写入 `/mnt/d/cursor/datasource/.git-c1-squash-msg.txt`:

```text
refactor: split stage2 enhancer into errors/snippet_filters/regex_extraction/evidence (PR-C1)

把 scripts/stage2_unified_enhancer.py(7174→~6100 行)中四个内聚域机械抽取到
src/datasource/engines/stage2/{errors,snippet_filters,regex_extraction,evidence}.py,
主脚本以 re-export 保持 zero call-site churn。依赖图:errors/snippet_filters/
regex_extraction 仅 stdlib;evidence→snippet_filters 单向;四模块无反向 import。
characterization 跨模块锁行为(搬前锁、搬后逐项不变)。

评审两处偏差已补救(零数据获取影响,纯代码卫生):
- _structured_audit_fields_from_task 不再重复:主脚本删本地副本,前向 import
  自 errors.py(唯一定义),两处对象同一。
- 删 main() 的 _sync_runtime_datetime_globals 生产测试缝:datetime 冻结改由
  replay harness 的 _freeze_stage2_datetime helper 在测试侧统一 monkeypatch
  (stage2 + errors + snippet_filters + policy_rules)。

验证:characterization + replay harness 7 passed(byte-stable)+ 全量回归绿。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

再提交并清理临时文件:
Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git commit -F .git-c1-squash-msg.txt && rm -f .git-c1-squash-msg.txt'
```
Expected: 提交成功,main tip 前进一格。

- [ ] **Step 5: 零-diff 校验(main vs 分支,全树)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git --no-pager diff main codex/batch-c1-stage2-split'
```
Expected: **空输出**(main 基线自 `0187b00` 未动,squash 完整捕获分支全部改动)。非空 → **停-回报**(不要继续清理分支)。

---

## Task 5:全量复跑(主 checkout)+ 推送 + 清理

**Files:** 无

- [ ] **Step 1: 主 checkout 全量回归(好 venv,权威)**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && bash run_clean.sh python -m pytest -q'
```
Expected: 全绿,passed ≥ `1072`。failed → **停-回报**(合入引入回归,需排查或 `git reset --hard 0187b00` 回退本次 squash 后回报)。

- [ ] **Step 2: 推送 main**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git push origin main'
```
Expected: fast-forward 成功。rejected → **停-回报**,不要 force。

- [ ] **Step 3: 清理 worktree + 分支**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree remove .worktrees/codex-batch-c1-stage2-split --force && git worktree prune && git branch -D codex/batch-c1-stage2-split'
```
Expected: worktree 移除、分支删除,无报错。(远端若有同名分支再删:`git push origin --delete codex/batch-c1-stage2-split`;无则跳过。)

- [ ] **Step 4: 隔离断言 + 回报**

Run:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource && git worktree list && git log --oneline -3 && git status --short'
```
Expected: worktree 列表无 `codex-batch-c1-stage2-split`;`git log` 顶部是 C1 squash 提交;`git status` 仅 `.gstack/`/`.claude/settings.local.json`。
回报:squash SHA、两处偏差修复确认、replay 7 passed、全量 passed 数、零-diff 结论、已删 worktree/分支。

---

## Self-Review(规划方自查)

- **Spec 覆盖**:偏差 B → Task 1(前向 import + 删副本 + 同一对象校验);偏差 A → Task 2(删 sync def+调用 + test-side helper + replay 验证);合入/清理 → Task 3-5。✅ 全覆盖。
- **Placeholder 扫描**:无 TBD;两处 import/删除/helper 均给完整代码;commit body 全文;命令带 Expected 与停-回报分支。✅
- **一致性**:helper 名 `_freeze_stage2_datetime` 在 Task 2 Step 3 定义、Step 4 调用一致;模块路径 `datasource.engines.stage2.errors`/`.snippet_filters`/`datasource.utils.policy_rules` 与脚本 L35-37 实际 import 对齐;`_structured_audit_fields_from_task` 唯一定义落 errors.py L217。✅
- **离线**:无真实 API;replay/全量全离线。✅
- **零 golden 重算**:Task 2 Step 5 明确"出现 golden 变化即停-回报",不允许重算。✅
