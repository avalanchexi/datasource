# PR-E3 执行计划:reserve_ratio 错口径源屏蔽 + BCOM 固定 quote 守卫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 从 `trading_economics` provider 删 `reserve_ratio`(屏蔽 7.50% cash-reserve-ratio 错口径源),并在搜索/抽取校验中拒绝该 URL,让 PBoC `official_china` 失败时转 manual/搜索而非回退错值;为已实现的 BCOM 固定 quote provider 加守卫测试防回归。

**Architecture:** 减法 + 守卫,不新建 provider、不改 official_china/market_quote_pages 逻辑。`trading_economics.supported_keys=set(URLS)`,删 URLS 条目即从 registry 摘除 reserve_ratio。BCOM 已唯一源 + 拒 BCOMTR,只加测试锁住。

**Tech Stack:** Python;pytest;git worktree;Windows + WSL。

> Spec:`docs/superpowers/specs/2026-06-19-batch-e3-reserve-ratio-source-design.md`(§2 源码事实 / §4 byte-stable)。建在 main `ddccebc`;独立 worktree。provider name:`official_china`/`market_quote_pages`/`trading_economics`。

---

## 偏离声明
- §8 "改挂 PBoC provider / BCOM 评估 provider" → 实为**减法+守卫**(PBoC/BCOM provider 已存在,见 spec §1)。
- **E3 是行为修正(同 E1,非行为保持)**:reserve_ratio 不再回退 7.50%。replay/structured golden 若经此回退,golden 合理变化,须逐条核对为预期修正(Task 3),不盲更。
- 搜索链路只做同一错口径 URL 的 fail-closed:移除 `rrr` 对 Trading Economics 的 trusted/issuer relax,并把 `cash-reserve-ratio` 作为 bad URL;不扩 official override allowlist。

## 环境头(零上下文)
- **Bash 工具坏**;命令经 `wsl -e bash -lc '...'`;pytest 走 `run_clean.sh`;只读 git 用 PowerShell。worktree 根执行。
- worktree:`git worktree add .worktrees/codex-batch-e3-reserve-ratio -b codex/batch-e3-reserve-ratio main` + 置备 `.env`/`.venv`/`logs`/`reports` + `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1`。
- 硬约束:不重跑真实流水线/Tavily;不碰 `data/runs`/`data/trend_history`;离线。**绝不盲目 `STAGE2_REPLAY_UPDATE_GOLDEN`**。
- Commit:Conventional。

## Task 0 — worktree + baseline + byte-stable 夹具检查
- [ ] **Step 1** 建 worktree + 全量基线:`bash run_clean.sh python -m pytest -q 2>&1 | tail -4`(记 baseline N)。
- [ ] **Step 2** 查 reserve_ratio 是否经 trading_economics 进入任何 golden/structured 夹具(决定 byte-stable):
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-e3-reserve-ratio && rg -ln "reserve_ratio" tests/fixtures tests/test_stage2_structured_golden.py tests/test_stage2_structured_integration.py 2>/dev/null; echo "---TE in fixtures---"; rg -n "cash-reserve-ratio|trading_economics.*reserve_ratio|reserve_ratio.*trading_economics" tests/ 2>/dev/null || echo "(no reserve_ratio-via-TE fixture)"'
```
记录结论:有→Task 3 走 golden 核对;无→保持 byte-stable。回报。

## Task 1 — 守卫/回归测试先行(TDD)
**Files:** Create `tests/test_e3_reserve_ratio_source.py`
- [ ] **Step 1: 写测试**:
```python
from datasource.providers.stage2_structured.registry import build_default_registry
from datasource.providers.stage2_structured import trading_economics as te
from datasource.providers.stage2_structured.market_quote_pages import QUOTE_PAGES


def _names(key):
    return [p.name for p in build_default_registry().providers_for(key)]


def test_trading_economics_no_longer_supports_reserve_ratio():
    assert "reserve_ratio" not in te.build_provider().supported_keys
    assert "reserve_ratio" not in te.URLS


def test_registry_reserve_ratio_only_official_china():
    assert _names("reserve_ratio") == ["official_china"]   # 无 trading_economics 回退


def test_trading_economics_keeps_other_keys():
    sk = te.build_provider().supported_keys
    for key in ("GC=F", "CL=F", "BZ=F", "HG=F", "reverse_repo"):
        assert key in sk, key


def test_bcom_single_fixed_quote_source():
    assert _names("BCOM") == ["market_quote_pages"]        # 无竞争源


def test_bcom_rejects_total_return_variants():
    bad = [t.lower() for t in QUOTE_PAGES["BCOM"]["bad_tokens"]]
    assert "total return" in bad and "bcomtr" in bad
```
- [ ] **Step 2: 跑红** — `bash run_clean.sh python -m pytest tests/test_e3_reserve_ratio_source.py -q`。Expected:BCOM 两条 PASS;reserve_ratio 三条 FAIL(trading_economics 仍支持)。

Review follow-up 增补:
- `rrr` search profile 不再把 `tradingeconomics.com` 当 trusted/issuer relax,`cash-reserve-ratio` 在 query quality 中 hard block。
- `_validate_general_extraction` 对 `rrr/reserve_ratio` 的 `tradingeconomics.com/china/cash-reserve-ratio` source_url 置 `manual_required=True`。

## Task 2 — 删 trading_economics 的 reserve_ratio 条目
**Files:** Modify `src/datasource/providers/stage2_structured/trading_economics.py`
- [ ] **Step 1** 删 `URLS` 中的整条:
```python
    "reserve_ratio": {
        "url": "https://tradingeconomics.com/china/cash-reserve-ratio",
        "unit": "%",
        "label": "China Cash Reserve Ratio",
        "category": "monetary_policy",
    },
```
(确认 `URLS` 内无其它处引用 `reserve_ratio`;`supported_keys=set(URLS)` 自动更新。)
- [ ] **Step 2: 跑绿** — `bash run_clean.sh python -m pytest tests/test_e3_reserve_ratio_source.py -q`(全 PASS)+ `flake8 src/datasource/providers/stage2_structured/trading_economics.py`。commit `fix: drop reserve_ratio from trading_economics (block 7.50% cash-reserve-ratio caliber) (PR-E3)`

## Task 3 — replay/structured golden 处理 + 全量
- [ ] **Step 1** 跑结构化/replay 相关:`bash run_clean.sh python -m pytest tests/test_stage2_structured_golden.py tests/test_stage2_structured_integration.py tests/test_stage2_replay_harness.py -q`。
  - Task 0=不经过 → 必须仍 byte-stable PASS(绝不更 golden)。
  - Task 0=经过 → 若 mismatch,导出 diff 逐条核对:仅 reserve_ratio 从 7.50% 结构化值变为缺失/转 manual,无其它字段漂移 → 确认后才更新对应 golden 并 commit;**任何非预期变化即停-回报**。
- [ ] **Step 2** 全量 `bash run_clean.sh python -m pytest -q 2>&1 | tail -5`(= baseline N + 新测,除 Step1 预期修正外无回归)。
- [ ] **Step 3** commit `test: lock reserve_ratio source + BCOM fixed-quote guard (PR-E3)`

## Task 4 — 文档 + TODOS
- [ ] **Step 1** CLAUDE.md / AGENTS.md:把 reserve_ratio 结构化源表述更新为"仅 `official_china` PBoC;`trading_economics` `cash-reserve-ratio`(7.50% 大行口径)已屏蔽;PBoC 失败转搜索/manual,走既有 pbc quality-replacement 通道"。SCRIPTS/structured-provider 列表把 reserve_ratio 从 trading_economics 描述移除。
- [ ] **Step 2** 跑 `pytest tests/test_manual_template.py tests/test_stage4_docs.py -q` 绿。commit `docs: reserve_ratio structured source = official_china only (PR-E3)`
- [ ] **Step 3** TODOS.md 勾 E3;commit `docs: mark PR-E3 complete in refactor TODOS`

## Task 5 — 隔离 + 回报
- [ ] 隔离:`git status --short` 仅本 PR 文件(trading_economics.py + 新测 + 文档/TODOS);无 `data/`/`reports/` 业务产物。
- [ ] 回报:commit 列表、全量 passed、Task 0 byte-stable 结论 + Task 3 golden 处理、reserve_ratio registry 只剩 official_china 确认、BCOM 守卫绿、trading_economics 其余 key 未受影响。

---

## 评审 checklist
1. `trading_economics` 删 reserve_ratio(`supported_keys`/`URLS` 均无);其余 key(GC=F/CL=F/BZ=F/HG=F/reverse_repo)仍在。
2. `registry.providers_for("reserve_ratio") == [official_china]`(无 7.50% 回退);search/validation 也拒绝 `cash-reserve-ratio` 错口径 URL;official_china/market_quote_pages 逻辑零改动。
3. BCOM 守卫:唯一源 market_quote_pages + bad_tokens 含 total return/bcomtr。
4. replay/structured golden:不经过→byte-stable;经过→diff 逐条核对为"reserve_ratio 错值→缺失"预期修正后才更新。全量无其它回归。
5. 不扩 official allowlist、不动搜索链路;文档同步。
6. 合入 main 之上 squash;清 worktree/分支。

## Self-Review
- Spec 覆盖:§3 in-scope → Task 2/4;§4 测试+byte-stable → Task 0/1/3。✅
- Placeholder:删除目标整条给出、测试全码、provider name 确定、命令带 Expected。✅
- 一致性:provider name(official_china/market_quote_pages/trading_economics)、`providers_for` 断言、分支名在 spec/plan/测试间一致。✅
- 风险:reserve_ratio 更常缺失=预期(宁缺勿错)、行为修正 golden 核对非盲更、只删一条不伤其余 key,均显式。✅
