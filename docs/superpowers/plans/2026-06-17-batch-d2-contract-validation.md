# PR-D2 执行计划:写盘前 contract 校验(完整对齐 + hard-fail + --no-validate-output 逃生门)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 各阶段写 `market_data*.json`/`pring_result.json` 前过对应 Pydantic contract 校验,失败 hard-fail(不写、退非零),带 `--no-validate-output` 逃生门;先把两 contract 完整对齐真实输出。

**Architecture:** 新 `utils/contract_validation.py`(`validate_market_data`/`validate_pring_result` + `ContractValidationError`,读 env 逃生门);两 contract 按 21-run 并集补全 Optional 字段、放宽 pring 错位 required(`extra=ignore`);stage1/2/2.5/3 写盘前接线。纯校验,零产物内容改动。

**Tech Stack:** Pydantic v2;pytest(21-run fixture 网);git worktree;Windows + WSL。

> Spec:`docs/superpowers/specs/2026-06-17-batch-d2-contract-validation-design.md`(§4 对齐表权威)。**建在 D1 之上**(需 `atomic_write_json` + C7 的 `engines/stage2/cli.py`);分支序 C7→D1→D2。

---

## 偏离声明
- TDD:contract 对齐 + 校验器 + 接线均先测后码;21-run fixture 网是核心回归。
- 校验**只读 payload**(model_validate 不写回)→ 产物逐字不变、replay/contract byte-stable。
- 唯一"行为"新增 = 写盘前可能抛 `ContractValidationError`(逃生门可关)。不改任何 stage 输出内容。

## 环境头(零上下文)
- **Bash 工具坏**;命令经 `wsl -e bash -lc '...'`;pytest 走 `run_clean.sh`;只读 git 可用 PowerShell。worktree 根执行。
- worktree:从 **D1 tip** 建(若 D1 未合 main:`git worktree add .worktrees/codex-batch-d2-contract-validation -b codex/batch-d2-contract-validation codex/batch-d1-run-dir-contract`;若 D1 已合 main 则从 `main`)。置备 `.env`/`.venv`/`logs`/`reports` + `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1`。
- 硬约束:不重跑真实流水线/Tavily;不碰当日 `data/runs`(只**读** `data/runs/2026*/` 作 fixture);不删 `.run.lock`;离线。**绝不 `STAGE2_REPLAY_UPDATE_GOLDEN`**。
- Commit:Conventional。

## Task 0 — worktree + baseline + fixture 清点
```bash
wsl -e bash -lc 'MAIN=/mnt/d/cursor/datasource; WT="$MAIN/.worktrees/codex-batch-d2-contract-validation"; cd "$MAIN" && git worktree add "$WT" -b codex/batch-d2-contract-validation codex/batch-d1-run-dir-contract && cp "$MAIN/.env" "$WT/.env" && mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv" && cd "$WT" && DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -m pytest -q 2>&1 | tail -4 && ls data/runs/2026*/market_data_complete.json | wc -l && ls data/runs/2026*/pring_result.json | wc -l'
```
Expected:全绿(记 baseline N=D1 后数);两类 fixture 各 ~21 个。失败 → 停-回报。

## Task 1 — 对齐 MarketDataContract + fixture 网
**Files:** Modify `src/datasource/models/market_data_contract.py`;Create `tests/test_contract_validation.py`
- [ ] **Step 1: fixture 网先行(红)** — `tests/test_contract_validation.py`:
```python
import glob
import json
import pytest
from datasource.models.market_data_contract import MarketDataContract
from datasource.models.pring_result_contract import PringResultContract

MD = sorted(glob.glob("data/runs/2026*/market_data_complete.json"))
PR = sorted(glob.glob("data/runs/2026*/pring_result.json"))


@pytest.mark.parametrize("path", MD)
def test_real_market_data_validates(path):
    MarketDataContract.model_validate(json.load(open(path, encoding="utf-8")))


@pytest.mark.parametrize("path", PR)
def test_real_pring_result_validates(path):
    PringResultContract.model_validate(json.load(open(path, encoding="utf-8")))
```
- [ ] **Step 2: 跑红** — `bash run_clean.sh python -m pytest tests/test_contract_validation.py -q`。Expected:market_data 现已过(D1 态),pring 全 FAIL(对齐前)。
- [ ] **Step 3: 补 market_data 子模型字段**(§4;每个加在对应 class 内,Optional 真实类型):
  - `CommodityData` 加:`as_of_date: Optional[str] = None`、`confidence: Optional[float] = None`、`daily_change_basis: Optional[str] = None`、`date: Optional[str] = None`、`is_estimated: bool = False`、`trend_history_confidence: Optional[str] = None`
  - `ForexData` 加:`change_120d_base_date/change_120d_basis/daily_change_base_date/daily_change_basis/date/stage_task_id/trend_history_confidence: Optional[str] = None`、`confidence: Optional[float] = None`、`is_estimated: bool = False`
  - `BondYieldData` 加:`estimation_method/source_url/trend_history_confidence: Optional[str] = None`
  - `FundFlowData` 加:`as_of_date/claimed_source_tier/date/estimation_method/source_tier/window_evidence: Optional[str] = None`、`manual_required: bool = False`
  - `MacroIndicatorData` 加:`estimation_method/report_period/source_url: Optional[str] = None`、`confidence: Optional[float] = None`
  - `MonetaryPolicyData` 加:`estimation_method/report_period/source_url/trend_history_confidence: Optional[str] = None`、`confidence: Optional[float] = None`
- [ ] **Step 4: market_data fixture 网转绿** — `bash run_clean.sh python -m pytest tests/test_contract_validation.py -k market_data -q && bash run_clean.sh python -m flake8 src/datasource/models/market_data_contract.py`。Expected:全 PASS。
- [ ] **Step 5: commit** — `refactor: align MarketDataContract with real outputs (PR-D2)`

## Task 2 — 对齐 PringResultContract + fixture 网
**Files:** Modify `src/datasource/models/pring_result_contract.py`
- [ ] **Step 1: 放宽错位 required + 补字段**(§4):
  - `InventoryCycleLayer`:`indicators: Dict[str, Any]` → `indicators: Optional[Dict[str, Any]] = None`;加 `score_details: Dict[str, Any] = Field(default_factory=dict)`、`analysis: Optional[str] = None`、`data_source: Optional[str] = None`、`update_time: Optional[str] = None`
  - `MonetaryCycleLayer`:`indicators` → `Optional[Dict[str, Any]] = None`;加 `score_details: Dict[str, Any] = Field(default_factory=dict)`、`analysis: Optional[str] = None`、`data_source: Optional[str] = None`、`websearch_required: Dict[str, Any] = Field(default_factory=dict)`(保留 `websearch_needed`)
  - `PringFinalLayer`:`confidence: float` → `confidence: Optional[float] = None`;`asset_allocation: Dict[str, str]` → `asset_allocation: Optional[Dict[str, str]] = None`;加 `base_confidence: Optional[float] = None`、`final_confidence: Optional[float] = None`、`analysis: Optional[str] = None`
  - `PringResultContract` 顶层加(均 Optional/default):`analysis_date/commodity_bias/commodity_signal/current_stage/data_period/enhancement_notes/final_stage/inventory_cycle_stage/leading_summary/methodology/recommendation/stage_description: Optional[str] = None`;`commodity_signal_score/inventory_cycle_score/technical_score: Optional[float] = None`;`confirm_signals/deny_signals/focus_assets: List[Any] = Field(default_factory=list)`;`macro_stage: Dict[str, Any] = Field(default_factory=dict)`
- [ ] **Step 2: pring fixture 网转绿** — `bash run_clean.sh python -m pytest tests/test_contract_validation.py -q && bash run_clean.sh python -m flake8 src/datasource/models/pring_result_contract.py`。Expected:全部 21+21 PASS。失败 → 看缺哪个字段补(grep 实际 key)。
- [ ] **Step 3: commit** — `refactor: align PringResultContract with real Stage3 output (PR-D2)`

## Task 3 — contract_validation 工具 + mutation/逃生门测试
**Files:** Create `src/datasource/utils/contract_validation.py`;Modify `tests/test_contract_validation.py`
- [ ] **Step 1: 测试先行**(加到 test_contract_validation.py):
```python
import os
from datasource.utils.contract_validation import (
    validate_market_data, validate_pring_result, ContractValidationError,
)

_GOOD_MD = json.load(open(MD[-1], encoding="utf-8"))
_GOOD_PR = json.load(open(PR[-1], encoding="utf-8"))


def test_validate_market_data_ok():
    validate_market_data(_GOOD_MD)  # no raise


def test_validate_market_data_missing_required_raises():
    bad = {k: v for k, v in _GOOD_MD.items() if k != "stock_indices"}
    with pytest.raises(ContractValidationError):
        validate_market_data(bad)


def test_validate_pring_missing_required_raises():
    bad = {k: v for k, v in _GOOD_PR.items() if k != "stage"}
    with pytest.raises(ContractValidationError):
        validate_pring_result(bad)


def test_no_validate_env_bypasses(monkeypatch):
    monkeypatch.setenv("DATASOURCE_NO_VALIDATE_OUTPUT", "1")
    validate_market_data({"garbage": True})   # no raise
    validate_pring_result({"garbage": True})  # no raise
```
- [ ] **Step 2: 跑红** — `bash run_clean.sh python -m pytest tests/test_contract_validation.py -k "validate or bypass" -q`(ImportError → 红)。
- [ ] **Step 3: 实现** — `src/datasource/utils/contract_validation.py`:
```python
"""Pre-write contract validation for pipeline JSON outputs."""
from __future__ import annotations

import os
from typing import Any

from datasource.models.market_data_contract import MarketDataContract
from datasource.models.pring_result_contract import PringResultContract


class ContractValidationError(Exception):
    """Raised when a pipeline payload fails its contract before write."""


def _bypassed() -> bool:
    return os.getenv("DATASOURCE_NO_VALIDATE_OUTPUT") == "1"


def validate_market_data(payload: Any) -> None:
    if _bypassed():
        return
    try:
        MarketDataContract.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - re-raise as contract error
        raise ContractValidationError(
            f"market_data contract validation failed:\n{exc}"
        ) from exc


def validate_pring_result(payload: Any) -> None:
    if _bypassed():
        return
    try:
        PringResultContract.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise ContractValidationError(
            f"pring_result contract validation failed:\n{exc}"
        ) from exc
```
- [ ] **Step 4: 转绿** — `bash run_clean.sh python -m pytest tests/test_contract_validation.py -q && bash run_clean.sh python -m flake8 src/datasource/utils/contract_validation.py`。
- [ ] **Step 5: commit** — `feat: add pre-write contract validation util + escape hatch env (PR-D2)`

## Task 4 — 接线 stage1/2/2.5/3 + --no-validate-output
**Files:** Modify `scripts/stage1_data_collector.py`、`src/datasource/engines/stage2/cli.py`、`src/datasource/engines/stage2_5/cli.py`、`src/datasource/engines/stage2_5/core.py`、`scripts/stage3_pring_analyzer.py`
- [ ] **Step 1: flag → env(逃生门统一经 env,免穿参)** — 每个入口 argparse 加:
```python
parser.add_argument("--no-validate-output", action="store_true",
                    help="跳过写盘前 contract 校验(逃生门)")
```
main 解析后尽早:`if args.no_validate_output: os.environ["DATASOURCE_NO_VALIDATE_OUTPUT"] = "1"`(stage1/3 脚本 argparse;stage2 `engines/stage2/cli.py` `_parse_args`+`main`;stage2.5 `engines/stage2_5/cli.py` `parse_args`+`main`)。
- [ ] **Step 2: 写盘前调校验** — 在各 stage 写产物的 `atomic_write_json(payload, path)` **紧前**插一行:
  - stage1(`scripts/stage1_data_collector.py` 写 market_data.json 处):`from datasource.utils.contract_validation import validate_market_data` + `validate_market_data(market_payload)`
  - stage2(`engines/stage2/cli.py` 写 market_data_stage2.json 处,`_dump_json`/`atomic_write_json` 写主产物前):`validate_market_data(market_payload)`
  - stage2.5(`engines/stage2_5/core.py` 写 market_data_complete.json 的 `atomic_write_json` 前,~951/1026):`validate_market_data(market_data)`
  - stage3(`scripts/stage3_pring_analyzer.py` 写 pring_result.json 前,~726):`from datasource.utils.contract_validation import validate_pring_result` + `validate_pring_result(pring_result)`
  > 仅对**主契约产物**接线;websearch_results/split/log/gap_monitor 等非契约产物不接。grep 核对每个 market_data*/pring_result 写盘点已覆盖。
- [ ] **Step 3: 接线冒烟测试**(加到 test_contract_validation.py 或新 `tests/test_stage_validation_wiring.py`):断言 stage3 main 对一个缺 `stage` 的 pring payload 抛/退非零(用现有 stage3 测试夹具或 monkeypatch 写盘点),以及 `--no-validate-output` 时放行。最简:单测 `os.environ` 置位后 `validate_pring_result(bad)` 不抛(已在 Task 3);接线层补一个 stage3 集成断言(若 stage3 有可注入夹具)。
- [ ] **Step 4: 校验** — `bash run_clean.sh python -m pytest tests/test_contract_validation.py tests/test_stage3_guard.py tests/test_stage2_replay_harness.py tests/test_stage25_contract_replay.py -q && bash run_clean.sh python -m py_compile scripts/stage1_data_collector.py scripts/stage3_pring_analyzer.py src/datasource/engines/stage2/cli.py src/datasource/engines/stage2_5/cli.py src/datasource/engines/stage2_5/core.py`。Expected:全绿;replay/contract byte-stable(校验只读)。
- [ ] **Step 5: commit** — `feat: wire pre-write contract validation into stage1/2/2.5/3 with --no-validate-output (PR-D2)`

## Task 5 — 全量 + 文档
- [ ] **Step 1: 全量** — `bash run_clean.sh python -m pytest -q 2>&1 | tail -5`(= baseline N + 新用例,无回归)+ `bash run_clean.sh python -m flake8 src/datasource/models/ src/datasource/utils/contract_validation.py`。
- [ ] **Step 2: 文档** — SCRIPTS.md 各 stage 加 `--no-validate-output` 说明;CLAUDE/AGENTS 记"写盘前 contract 校验 + 逃生门 env `DATASOURCE_NO_VALIDATE_OUTPUT=1`"。跑 `pytest tests/test_manual_template.py tests/test_stage4_docs.py -q` 确认命令契约绿。
- [ ] **Step 3: commit** — `docs: document pre-write contract validation + escape hatch (PR-D2)`

## Task 6 — TODOS + 隔离 + 回报
- [ ] TODOS.md 勾 D2;commit `docs: mark PR-D2 complete in refactor TODOS`。
- [ ] 隔离断言:`git status --short` 仅本 PR 文件;无 `data/`/`reports/` 业务产物。
- [ ] 回报:commit 列表、全量 passed、21-run fixture 网绿、接线点清单(grep)、mutation/逃生门验证、replay/contract byte-stable。

---

## 评审 checklist
1. 两 contract 按 §4 完整对齐;`extra=ignore`;全部 21+21 真实 fixture 校验过(fixture 网绿)。
2. `validate_market_data`/`validate_pring_result`/`ContractValidationError` + env 逃生门;mutation(删 required/错类型)正确 fail。
3. stage1/2/2.5/3 写主契约产物前接线;`--no-validate-output` + env 生效;失败不写、退非零。
4. 校验只读 → 产物逐字不变;replay/contract byte-stable;全量无回归。
5. 未接非契约产物(websearch/log/gap_monitor);不改 stage 输出内容;不 forbid。
6. 合入:在 D1 之后;squash;清 worktree/分支。

## Self-Review
- Spec 覆盖:§2 in-scope → Task 1-5;§3 注入点 → Task 4;§4 对齐表 → Task 1/2(逐字段);§5 测试 → Task 1/2/3/4。✅
- Placeholder:无 TBD;字段声明逐条、util 全码、接线点定位 + grep 兜底;命令带 Expected。✅
- 一致性:`validate_market_data`/`validate_pring_result`/`ContractValidationError`/env 名/分支名/字段表在 spec/plan/测试间一致。✅
- 依赖:从 D1 tip 起(atomic_write_json/cli 在);C7→D1→D2 序;校验只读 byte-stable 兜底。✅
