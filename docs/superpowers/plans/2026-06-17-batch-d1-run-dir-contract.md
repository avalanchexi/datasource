# PR-D1 执行计划:run 目录契约 — atomic_write_json + 文件白名单 + run_dir_audit

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 消灭 `data/runs/YYYYMMDD/` 的 `.bak`/时间戳副本/`_new` 杂散文件:统一 `atomic_write_json`、删 `dump_json` backup、以 RunPaths 为白名单单一来源、加 `run_dir_audit` 诊断工具。纯写入机制 + 工具,输出内容逐字不变。

**Architecture:** `json_io` 加 `atomic_write_json`/`atomic_write_text`(tmp+`os.replace`),删 backup 污染;全 run 目录写盘点切过去并删自带 `.bak`;RunPaths 扩白名单 + `data_dir_whitelist()`;`scripts/tools/run_dir_audit.py` 列白名单外文件(诊断,D2 才 hard-fail)。

**Tech Stack:** Python;pytest;flake8/py_compile;git worktree;Windows + WSL。

> Spec:`docs/superpowers/specs/2026-06-17-batch-d1-run-dir-contract-design.md`(§4 迁移表 / §5 白名单 / §3 安全确认必读)。worktree 支线,从开工 main HEAD 起。

---

## 偏离声明
- TDD:json_io / whitelist / audit 三处先写测试再实现(或先改断言锁新行为)。
- 删 backup 安全已确认(§3:`.bak` 无消费者);唯一连带 = `test_utils_json_io.py` 的 backup 断言需改。
- 原子写不改输出内容;replay/contract byte-stable 是硬门(绝不更新 golden)。

## 环境头(零上下文)
- **Bash 工具坏**;命令经 `wsl -e bash -lc '...'`;pytest/flake8 走 `run_clean.sh`;只读 git 可用 PowerShell。worktree 根执行。
- worktree:从开工 main HEAD 建 `.worktrees/codex-batch-d1-run-dir-contract`(分支 `codex/batch-d1-run-dir-contract`)+ 置备 `.env`/`.venv`/`logs`/`reports` + `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1`。
- 硬约束:不重跑真实流水线/Tavily;不碰当日 `data/runs`/`data/trend_history`;不删 `.run.lock`;全程离线。**绝不 `STAGE2_REPLAY_UPDATE_GOLDEN`**。
- Commit:Conventional(`feat:`/`refactor:`/`test:`/`docs:`)。

## Task 0 — worktree + baseline
```bash
wsl -e bash -lc 'MAIN=/mnt/d/cursor/datasource; WT="$MAIN/.worktrees/codex-batch-d1-run-dir-contract"; cd "$MAIN" && git fetch && git worktree add "$WT" -b codex/batch-d1-run-dir-contract main && cp "$MAIN/.env" "$WT/.env" && mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv" && cd "$WT" && DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -m pytest -q 2>&1 | tail -5'
```
Expected:全绿(记 baseline N)。失败 → 停-回报。

## Task 1 — json_io:atomic_write_json + atomic_write_text + 删 backup
**Files:** Modify `src/datasource/utils/json_io.py`、`tests/test_utils_json_io.py`
- [ ] **Step 1: 改测试锁新行为(TDD)** — `tests/test_utils_json_io.py` 删 backup 相关断言(L43-75 引用 `.bak` 的用例),改为:
```python
def test_atomic_write_json_writes_and_no_bak(tmp_path):
    from datasource.utils.json_io import atomic_write_json, load_json_strict
    p = tmp_path / "x.json"
    atomic_write_json({"a": 1}, p)
    atomic_write_json({"a": 2}, p)
    assert load_json_strict(p) == {"a": 2}
    assert not (p.with_name(p.name + ".bak")).exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert sorted(q.name for q in tmp_path.iterdir()) == ["x.json"]
```
（若仍保留 `dump_json` 测试,断言它=atomic 且不产 `.bak`。）
- [ ] **Step 2: 跑红** — `bash run_clean.sh python -m pytest tests/test_utils_json_io.py -q`(`atomic_write_json` 未定义 → 红)。
- [ ] **Step 3: 实现** — `json_io.py`:
```python
import os

def atomic_write_json(payload, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)

def atomic_write_text(text, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
```
`dump_json` 改为委托(删 backup/.bak/时间戳):
```python
def dump_json(payload, path):  # backup 参数移除
    atomic_write_json(payload, path)
```
（删掉旧 `shutil`/`datetime` backup 代码;若 `shutil`/`datetime` 不再用则删 import。）
- [ ] **Step 4: 跑绿** — `bash run_clean.sh python -m pytest tests/test_utils_json_io.py -q && bash run_clean.sh python -m flake8 src/datasource/utils/json_io.py`。
- [ ] **Step 5: commit** — `feat: add atomic_write_json/atomic_write_text; drop dump_json backup pollution (PR-D1)`

## Task 2 — RunPaths 白名单单一来源
**Files:** Modify `src/datasource/utils/run_paths.py`、`tests/test_run_paths_consistency.py`
- [ ] **Step 1: RunPaths 补属性 + 白名单** — 在 `RunPaths` 加缺的 data_dir 属性:
```python
    @property
    def source_conflicts(self) -> Path:
        return self.data_dir / "source_conflicts.json"

    @property
    def stage4_risk_review(self) -> Path:
        return self.data_dir / "stage4_risk_review.json"

    @property
    def quality_trend(self) -> Path:
        return self.data_dir / "quality_trend.csv"

    @property
    def stage2_log_data(self) -> Path:  # 实际落 data_dir(口径不一致,白名单按实际)
        return self.data_dir / "stage2_log.json"

    @property
    def run_lock(self) -> Path:
        return self.data_dir / ".run.lock"

    def data_dir_whitelist(self) -> set[str]:
        return {
            self.market_data.name, self.market_data_stage2.name, self.market_data_complete.name,
            self.pring_result.name, self.search_tasks_stage2.name,
            self.websearch_results_auto.name, self.websearch_results_manual.name,
            self.gap_monitor.name, self.quality_metrics.name, self.quality_trend.name,
            self.policy_evaluation.name, self.run_snapshot.name, self.source_conflicts.name,
            self.stage4_risk_review.name, self.trend_history_gap.name, self.recap_facts.name,
            self.stage2_log_data.name, self.run_lock.name,
        }
```
- [ ] **Step 2: test_run_paths_consistency 断言白名单** — 加:
```python
def test_data_dir_whitelist_matches_expected():
    from datasource.utils.run_paths import build_run_paths
    wl = build_run_paths("2026-06-10").data_dir_whitelist()
    expected = {
        "market_data.json","market_data_stage2.json","market_data_complete.json","pring_result.json",
        "search_tasks_stage2.jsonl","websearch_results_auto.json","websearch_results_manual.json",
        "gap_monitor.json","quality_metrics.json","quality_trend.csv","policy_evaluation.json",
        "run_snapshot.json","source_conflicts.json","stage4_risk_review.json","trend_history_gap.json",
        "recap_facts.json","stage2_log.json",".run.lock",
    }
    assert wl == expected
```
- [ ] **Step 3: 校验** — `bash run_clean.sh python -m pytest tests/test_run_paths_consistency.py -q && bash run_clean.sh python -m flake8 src/datasource/utils/run_paths.py`。
- [ ] **Step 4: commit** — `feat: extend RunPaths as run-dir whitelist source (PR-D1)`

## Task 3 — 全 run 目录写盘点切原子写 + 删 .bak
**Files:** §4 迁移表所列(scripts/ + src/)
- [ ] **Step 1: 按 §4 迁移表逐个改** — 每处 `json.dump(...)`/`dump_json(...,backup=True)`/自带 `.tmp`+`.bak` → `atomic_write_json(payload, path)`(csv → `atomic_write_text`);删所有自带 `.bak`(stage1:84-89、stage3:726、stage4_report:211);`engines/stage2/cli.py` 的 `_dump_json` 改委托 `atomic_write_json`、去 backup 形参。**不动** `run_lock.py` 的 `.run.lock` 写。
- [ ] **Step 2: grep 兜底无遗漏** —
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-d1-run-dir-contract && rg -n "json\.dump\(|with_suffix.*\.bak|copy2.*\.bak" scripts/ src/datasource/engines src/datasource/utils -g'!archive/**' | rg -v "run_lock|test_" || echo "NO-RAW-RUNDIR-WRITE (review hits)"'
```
确认剩余命中只是 `.run.lock`/非 run 目录(如 data/trend_history series 可保留)/已用 atomic。
- [ ] **Step 3: 校验** — `bash run_clean.sh python -m py_compile $(...changed...) && bash run_clean.sh python -m flake8 src/datasource/ && bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py tests/test_stage25_contract_replay.py -q`(replay/contract **byte-stable**;原子写不改内容)。
- [ ] **Step 4: commit** — `refactor: route all run-dir writes through atomic_write_json; drop bespoke .bak (PR-D1)`

## Task 4 — run_dir_audit 工具 + 测试
**Files:** Create `scripts/tools/run_dir_audit.py`、`tests/test_run_dir_audit.py`
- [ ] **Step 1: 测试先行** — `tests/test_run_dir_audit.py`:
```python
def test_audit_flags_bak_and_timestamp(tmp_path, monkeypatch):
    import scripts.tools.run_dir_audit as audit
    d = tmp_path / "data" / "runs" / "20260610"; d.mkdir(parents=True)
    (d / "market_data.json").write_text("{}", encoding="utf-8")
    (d / "market_data.json.bak").write_text("{}", encoding="utf-8")
    (d / "market_data_20260610085557.json").write_text("{}", encoding="utf-8")
    stray = audit.find_stray_files("2026-06-10", base=tmp_path)
    assert set(stray) == {"market_data.json.bak", "market_data_20260610085557.json"}
```
- [ ] **Step 2: 实现** — `scripts/tools/run_dir_audit.py`:`find_stray_files(date, base=Path("."))` = `set(实际文件名) - RunPaths.data_dir_whitelist()`;`main()` argparse `--date`/`--strict`,打印 `OK: N files` 或逐行 `STRAY:`,`--strict` 且有 stray 退非零。只读不删。
- [ ] **Step 3: 校验** — `bash run_clean.sh python -m pytest tests/test_run_dir_audit.py -q && bash run_clean.sh python -m py_compile scripts/tools/run_dir_audit.py`。
- [ ] **Step 4: commit** — `feat: add run_dir_audit diagnostic tool (PR-D1)`

## Task 5 — 全量 + 文档同步
- [ ] **Step 1: 全量** — `bash run_clean.sh python -m pytest -q 2>&1 | tail -5`(= baseline N + 新用例,无回归)+ `bash run_clean.sh python -m flake8 src/`。失败 → 停-回报。
- [ ] **Step 2: 文档** — `SCRIPTS.md` 加 `run_dir_audit` 工具条目(`bash run_clean.sh python scripts/tools/run_dir_audit.py --date YYYY-MM-DD`);CLAUDE/AGENTS 轻量记 run 目录白名单契约 + 原子写。跑 `pytest tests/test_manual_template.py tests/test_stage4_docs.py -q` 确认命令契约绿。
- [ ] **Step 3: commit** — `docs: document run_dir_audit + run-dir whitelist contract (PR-D1)`

## Task 6 — 隔离断言 + 回报
- [ ] TODOS.md 勾 D1(`run 目录契约 D1`);commit `docs: mark PR-D1 complete in refactor TODOS`。
- [ ] 隔离断言:`git status --short` 只含本 PR 文件;无 `data/`/`reports/` 业务产物。
- [ ] 回报:commit 列表、全量 passed、迁移点清单(grep 兜底结果)、白名单集合、`run_dir_audit` 对脏目录验证、replay/contract byte-stable、计划外改动。

---

## 评审 checklist
1. `atomic_write_json`/`atomic_write_text` 原子(tmp+os.replace);`dump_json` 无 backup;全 run 目录写盘点已切(grep 无残留 `json.dump(` run 目录写,除 `.run.lock`)。
2. 删 backup 无破坏:无 `.bak` 消费者;`test_utils_json_io` 已改;replay/contract byte-stable(内容不变)。
3. RunPaths 白名单 = §5 全集;`data_dir_whitelist()` 与属性一致;`run_dir_audit` 对 `.bak`/时间戳正确标记。
4. 不动 `.run.lock` 写;不迁移 stage2_log 位置;D2(hard-fail)不在本 PR。
5. 全量无回归;文档同步;命令契约绿。
6. 合入:squash;`git diff main 分支` 空;清 worktree/分支。

## Self-Review
- Spec 覆盖:§2 in-scope → Task 1-5;§3 安全(test_utils_json_io)→ Task 1;§4 迁移表 → Task 3;§5 白名单 → Task 2;§6 工具 → Task 4;§7 测试 → Task 1/2/4。✅
- Placeholder:无 TBD;json_io/whitelist/audit 给完整代码;迁移表 + grep 兜底;命令带 Expected。✅
- 一致性:`atomic_write_json`/`data_dir_whitelist`/分支名/白名单集合在 spec/plan/测试间一致。✅
- 风险:删 backup 安全确认、replay byte-stable 硬门、grep 兜底、不动 lock,均显式。✅
