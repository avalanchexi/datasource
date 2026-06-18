# PR-C6(可选)执行计划:Stage1 采集器瘦身 — MarketDataCollector → engines/stage1/

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 把 `scripts/stage1_data_collector.py`(~2561 行)的 god-class `MarketDataCollector` + 模块级 helper 纯机械搬移到新包 `src/datasource/engines/stage1/`,脚本瘦为 ≤300 行薄 entry + re-export;同步 repoint 24 处 `get_manager` 测试 monkeypatch。

**Architecture:** relocate-only(body 逐字,类同一对象,行为天然保持),不拆 god-class 内部、不 dedup trend 副本。`MarketDataCollector.__init__` 移到新模块后在新命名空间查 `get_manager`,故测试对 `scripts.stage1_data_collector.get_manager` 的 patch 须 repoint 到 collector 模块(C5 同类问题)。

**Tech Stack:** Python;pytest;flake8/py_compile;git worktree;Windows + WSL。

> Spec:`docs/superpowers/specs/2026-06-17-batch-c6-stage1-slim-design.md`。行号采自 main `0c8f14b`(C6 worktree 从此分支,行号当前有效)。
> 执行者:Codex(零上下文)。逐 checkbox;卡住即停-回报。

---

## 规划方有意偏离(评审勿误判)
1. **类/函数体未内联**(沿用 C1–C5):逐字搬移;正确性由既有 stage1 单测 + `is` 身份 + py_compile/flake8 保证。
2. **唯一测试改动 = 24 处 get_manager repoint**(C5 同类必要改动):caller(`__init__`)移出脚本,脚本命名空间 patch 不再触达。
3. **安全网比 C1–C5 轻且无 replay**:Stage1 走 live TuShare,不在测试内跑真实 API;靠纯搬移 + is 身份 + 既有单测。这是 relocate-only(而非拆 god-class)的理由。

---

## 统一环境头(零上下文)
- **Bash 工具损坏**;命令经 `wsl -e bash -lc '...'`;pytest/flake8/py_compile 走 `run_clean.sh`;只读 git 可用 PowerShell。worktree 根执行。
- 硬约束:**不跑真实 TuShare/Stage1 采集**(单测用既有 fake/mock);不碰当日 `data/runs`/`data/trend_history`;不删 `.run.lock`;全程离线。
- 冻结:类/helper body 逐字;不拆 god-class 内部;不 dedup `_calc_change_from_trend_history`;不并入 utils/coercion;不改 manager/adapters/calculators。
- Commit:Conventional(`refactor:`/`test:`)。

---

## 搬移清单(权威;行号 = main `0c8f14b`)

**→ `src/datasource/engines/stage1/collector.py`**(逐字搬入):
- 类:`MarketDataCollector`(44–2307,~45 方法,含 `__init__`/`collect_*`/`_fetch_*_from_tushare`/`_calculate_*`/freshness/completeness)
- 别名:`Stage1DataCollector = MarketDataCollector`(2308)
- 模块级 helper:`_calc_change_from_trend_history`(2311)、`_is_missing_change`(2365)、`_backfill_stage1_trend`(2374)、`_normalize_date_str`(2453)、`_resolve_last_trading_day`(2467)
- import header:复制脚本现有 import 中**类/helper body 实际引用**的项(`asyncio`/`json`/`os`/`defaultdict`/`datetime,timedelta`/`typing`/`Path`/`shutil`/`pandas as pd`/`numpy as np`/`lru_cache` + `from datasource import get_manager` + `TechnicalIndicatorCalculator` + `models.market_data_contract` 名 + `utils.trend_history_store` 名 + `utils.run_paths.build_run_paths`)。由 flake8 F401/F821 收敛。

**留 `scripts/stage1_data_collector.py`**(薄 entry):`main()`(2445–2560)+ `if __name__ == '__main__'`(2561)+ re-export 块 + main 自身所需 import(`asyncio`/`argparse`/`json`/`Path` 等)。

> ⚠️ **不搬/不改**:`main` body 逐字保留在脚本。**不拆** god-class 内部方法。**不 dedup** `_calc_change_from_trend_history`(与 Stage2.5 trend_backfill 独立副本,随类搬移)。

---

## Task 0 — worktree + baseline
**Files:** 无
- [ ] **Step 1: 置备 worktree(从 main `0c8f14b`)**
```bash
wsl -e bash -lc 'MAIN=/mnt/d/cursor/datasource; WT="$MAIN/.worktrees/codex-batch-c6-stage1-slim"; cd "$MAIN" && git fetch && git worktree add "$WT" -b codex/batch-c6-stage1-slim 0c8f14b && cp "$MAIN/.env" "$WT/.env" && mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv" && cd "$WT" && DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V'
```
Expected:Python ≥3.7;venv bootstrap 成功。失败 → 停-回报。
- [ ] **Step 2: baseline 全量 + stage1 单测 + 行数 + --help**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c6-stage1-slim && bash run_clean.sh python -m pytest -q 2>&1 | tail -5 && echo "---" && bash run_clean.sh python -m pytest tests/test_stage1_data_collector.py tests/test_stage1_hsgt_window.py -q 2>&1 | tail -3 && echo "---" && wc -l scripts/stage1_data_collector.py && bash run_clean.sh python scripts/stage1_data_collector.py --help > /tmp/c6_help_baseline.txt 2>&1; echo "help exit=$?"'
```
Expected:全量绿(记 baseline N);两 stage1 测试文件绿;行数 ~2561;`--help` exit=0 存 `/tmp/c6_help_baseline.txt`。失败 → 停-回报。

---

## Task 1 — 建包 + collector.py + 瘦脚本(类移出 → stage1 单测中途 RED 预期)
**Files:**
- Create: `src/datasource/engines/stage1/__init__.py`、`src/datasource/engines/stage1/collector.py`
- Modify: `scripts/stage1_data_collector.py`

- [ ] **Step 1: 建包** — `__init__.py`:
```python
"""Stage1 采集器内聚模块(批次 C6 入口瘦身)。"""
```
- [ ] **Step 2: 建 collector.py** — import header(见搬移清单)+ **逐字搬入** `MarketDataCollector` 类 + `Stage1DataCollector` 别名 + 5 个模块级 helper(body 一字不改)。
- [ ] **Step 3: 瘦脚本** — 删除脚本中类 + 别名 + 5 helper 的本地定义;在脚本 import 段后插入 re-export:
```python
from datasource.engines.stage1.collector import (  # noqa: F401 (C6 re-export)
    MarketDataCollector,
    Stage1DataCollector,
    _calc_change_from_trend_history,
    _is_missing_change,
    _backfill_stage1_trend,
    _normalize_date_str,
    _resolve_last_trading_day,
)
```
`FundFlowData` 若 `main`/re-export 需要,保留脚本现有 `from datasource.models.market_data_contract import ... FundFlowData ...`(测试 `from scripts.stage1_data_collector import FundFlowData` 依赖);删脚本内类搬走后无用的 import(如 `from datasource import get_manager`、`TechnicalIndicatorCalculator`、仅类用的 trend_history_store 名)——以 flake8 F401 为准,re-export 用的留 + `# noqa: F401`,纯无用的删。保留 `main` 与 `if __name__` 逐字。
- [ ] **Step 4: 校验(类已移、import 无环)**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c6-stage1-slim && bash run_clean.sh python -m py_compile src/datasource/engines/stage1/collector.py scripts/stage1_data_collector.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage1/ && bash run_clean.sh python -c "import scripts.stage1_data_collector as s; from datasource.engines.stage1 import collector as c; print(s.MarketDataCollector is c.MarketDataCollector, s.Stage1DataCollector is c.MarketDataCollector)"'
```
Expected:py_compile 无输出;flake8 `engines/stage1/` 干净;末行 `True True`(re-export 同一对象 + 别名)。
> ⚠️ **此时 `test_stage1_data_collector.py` 多数用例 RED 是预期**(它们 patch `scripts.stage1_data_collector.get_manager`,类已移到 collector,patch 不再触达)。Task 2 repoint 后转绿。Codex 勿因此停-回报。
- [ ] **Step 5: commit** — `refactor: relocate MarketDataCollector to engines/stage1 (PR-C6)`

---

## Task 2 — repoint 24 处 get_manager 测试 patch
**Files:** Modify `tests/test_stage1_data_collector.py`
- [ ] **Step 1: 全量替换 patch target**
把 `tests/test_stage1_data_collector.py` 中所有(24 处)
```python
monkeypatch.setattr("scripts.stage1_data_collector.get_manager", ...)
```
改为
```python
monkeypatch.setattr("datasource.engines.stage1.collector.get_manager", ...)
```
(lambda 实参不变;`test_stage1_hsgt_window.py` 用 `MarketDataCollector.__new__` + 实例方法 patch + `sys.modules["tushare"]`,**位置无关,不改**。)
- [ ] **Step 2: 确认无残留 + 两测试文件绿**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c6-stage1-slim && (grep -n "scripts.stage1_data_collector.get_manager" tests/ -r && echo "RESIDUE(BAD)" || echo "REPOINTED(OK)") && bash run_clean.sh python -m pytest tests/test_stage1_data_collector.py tests/test_stage1_hsgt_window.py -q 2>&1 | tail -4'
```
Expected:`REPOINTED(OK)`;两测试文件全绿。
- [ ] **Step 3: 兜底 grep 其它 script-global patch**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c6-stage1-slim && grep -rn "setattr(\"scripts.stage1_data_collector\." tests/ || echo "NO-OTHER-SCRIPT-GLOBAL-PATCH (OK)"'
```
Expected:`NO-OTHER-SCRIPT-GLOBAL-PATCH (OK)`(仅 get_manager,已 repoint);若有其它名 → 按同规则 repoint 到 collector 并回报。
- [ ] **Step 4: commit** — `test: repoint stage1 get_manager monkeypatch to collector module (PR-C6)`

---

## Task 3 — is-identity 断言 + 全量验收
**Files:** Modify `tests/test_stage1_data_collector.py`(追加轻量 is-identity)
- [ ] **Step 1: 追加 is-identity / import-surface 断言**
在 `tests/test_stage1_data_collector.py` 末尾追加:
```python
def test_c6_collector_reexport_is_canonical():
    import scripts.stage1_data_collector as s
    from datasource.engines.stage1 import collector as c
    assert s.MarketDataCollector is c.MarketDataCollector
    assert s.Stage1DataCollector is c.MarketDataCollector
    for name in ("_calc_change_from_trend_history", "_is_missing_change",
                 "_backfill_stage1_trend", "_normalize_date_str", "_resolve_last_trading_day"):
        assert getattr(s, name) is getattr(c, name), name
```
- [ ] **Step 2: 全量验收**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c6-stage1-slim && bash run_clean.sh python -m pytest -q 2>&1 | tail -6 && bash run_clean.sh python -m py_compile src/datasource/engines/stage1/*.py scripts/stage1_data_collector.py && bash run_clean.sh python -m flake8 src/datasource/engines/stage1/ && bash run_clean.sh python scripts/stage1_data_collector.py --help > /tmp/c6_help_after.txt 2>&1 && diff /tmp/c6_help_baseline.txt /tmp/c6_help_after.txt && echo "HELP-DIFF-EMPTY" && wc -l scripts/stage1_data_collector.py'
```
Expected:全量绿(= baseline N + 新 is-identity 用例);py_compile/flake8 干净;`HELP-DIFF-EMPTY`;脚本行数 **≤300**。失败 → 停-回报。
- [ ] **Step 3: 残留校验**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c6-stage1-slim && rg -n "^class MarketDataCollector|^def _backfill_stage1_trend|^def _calc_change_from_trend_history" scripts/stage1_data_collector.py || echo "NO-LOCAL-DEF (OK)"; rg -n "^async def main|^if __name__" scripts/stage1_data_collector.py && echo "MAIN-RETAINED (OK)"'
```
Expected:第一条 `NO-LOCAL-DEF`;第二条命中 2 个(main + if __name__ 仍在脚本)。
- [ ] **Step 4: 临时产物清理 + commit** — `rm -f /tmp/c6_help_baseline.txt /tmp/c6_help_after.txt`;commit `test: assert C6 collector relocation behaves identically (is-identity)`

---

## Task 4 — 文档 + 隔离 + 回报
**Files:** Modify `optimization/20260610_refactor_plan/TODOS.md`
- [ ] **Step 1: TODOS.md** — C6 行 `[ ]`→`[x]`(附 squash SHA 占位);"当前焦点"按实际(C 终态/全局验收);commit `docs: mark PR-C6 complete in refactor TODOS`。
- [ ] **Step 2: 命令漂移检查**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c6-stage1-slim && bash run_clean.sh python -m pytest tests/test_manual_template.py tests/test_stage4_docs.py -q 2>&1 | tail -3'
```
Expected:全绿(本 PR 不改文档命令示例;`scripts/stage1_data_collector.py` 路径不变)。
- [ ] **Step 3: 隔离断言 + 回报**
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-c6-stage1-slim && git status --short && ls /mnt/d/cursor/datasource/data/runs/ 2>/dev/null | tail -3'
```
Expected:`git status` 只含本 PR 新增/修改(`engines/stage1/{__init__,collector}.py` + 脚本 + 两测试文件 + TODOS.md);无业务产物。
**回报**:commit 列表、全量 passed(baseline → after)、脚本行数(2561 → ≤300)、collector 依赖图无环、24 处 get_manager repoint 确认、`is` 身份(含别名 + 5 helper)、`--help` diff 空、计划外改动(理想仅 flake8 收敛)。

---

## 评审方 checklist
1. 类 + 5 helper body 逐字未变(`git diff` 只见位置 + import + re-export);`main` 逐字留脚本;不拆 god-class、未 dedup trend 副本。
2. 24 处 get_manager repoint 到 `datasource.engines.stage1.collector.get_manager`;无残留 `scripts.stage1_data_collector.get_manager`;两 stage1 测试文件绿。
3. 依赖图:collector → manager/adapters/calculators/models/utils(向下);不 import 脚本、不 import engines/stage2(_5);import 冒烟无环。
4. `is` 身份(`MarketDataCollector` + `Stage1DataCollector` 别名 + 5 helper);re-export 完整(`MarketDataCollector`/`Stage1DataCollector`/`FundFlowData` 经脚本可 import)。
5. 脚本 ≤300 行;`--help` diff 空;全量无回归。
6. 合入:squash;`git diff main 分支` 空;清 worktree/分支。

---

## Self-Review
- Spec 覆盖:§2 in-scope → Task 1(collector + 瘦脚本);§5 get_manager repoint → Task 2;§6 is-identity/单测 → Task 0/2/3;§7 执行序(中途 RED)→ Task 1 注;§10 验收 → Task 3/4。✅
- Placeholder:无 TBD;re-export 块完整代码;repoint 规则化 + grep 兜底;is-identity 测试给全;命令带 Expected/停-回报。✅
- 一致性:worktree `.worktrees/codex-batch-c6-stage1-slim` + 分支 `codex/batch-c6-stage1-slim`;collector 模块路径 `datasource.engines.stage1.collector`;`Stage1DataCollector` 别名 + 5 helper 名在搬移清单/re-export/is-identity 间一致。✅
- 安全网诚实声明(无 replay,relocate-only 兜底);中途 RED 预期已写明(防 Codex 误停)。✅
