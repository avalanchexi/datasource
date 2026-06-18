# PR-E1 执行计划:macro previous_value/change_rate 从 event_history 正确回填

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 修正 macro compare 字段的 event_history 回填(正则 bug + 前值选取宁缺勿错 + change_rate 分口径 + value_source 标注),消除 cpi/ppi/pmi/industrial 等 compare 缺口反复落 manual。

**Architecture:** 核心改 `src/datasource/engines/stage2_5/trend_backfill.py` 的 `_calc_prev_from_event_history` + 新增 caliber registry/dispatch;两个调用点(`_apply_macro_entry` merge 时、`_backfill_trend_changes` post-write)传入指标自身周期/单位并标 `value_source`。纯回填正确性修复,只在 pv/cr 缺失时触发,不动既有正确值、不动 is_estimated。

**Tech Stack:** Python;pytest(合成 event_history 隔离);git worktree;Windows + WSL。

> Spec:`docs/superpowers/specs/2026-06-19-batch-e1-macro-backfill-design.md`(§3 算法 / §4 byte-stable 注意)。建在 main `2dae81e`;worktree 支线。

---

## 偏离声明
- TDD:registry/dispatch、函数重写、标注均先测后码;合成 event_history 隔离,不碰真实 `data/trend_history`。
- **E1 是行为修正(非 C/D 的行为保持)**:回填输出会从"错/空"变"对"。若 replay golden 夹具触发 macro 回填,golden **合理变化**,须逐条核对为预期修正(§ Task 4),不盲更。
- 只在 pv/cr **缺失**时回填;不覆盖 Stage2/manual 既有正确值;不动 `is_estimated`。

## 环境头(零上下文)
- **Bash 工具坏**;命令经 `wsl -e bash -lc '...'`;pytest 走 `run_clean.sh`;只读 git 用 PowerShell。worktree 根执行。
- worktree:`git worktree add .worktrees/codex-batch-e1-macro-backfill -b codex/batch-e1-macro-backfill main` + 置备 `.env`/`.venv`/`logs`/`reports` + `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1`。
- 硬约束:不重跑真实流水线/Tavily;**不碰真实 `data/trend_history`**(测试用 tmp `base_dir`);不删 `.run.lock`;离线。
- Commit:Conventional。

## Task 0 — worktree + baseline + replay 夹具 macro 回填检查
- [ ] **Step 1** 建 worktree + 全量基线:`... bash run_clean.sh python -m pytest -q 2>&1 | tail -4`(记 baseline N=D2 后数,1489)。
- [ ] **Step 2** 查 replay 夹具是否触发 macro 回填(决定 byte-stable):
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-batch-e1-macro-backfill && rg -n "macro_indicators|previous_value|_calc_prev_from_event_history" tests/test_stage25_contract_replay.py tests/fixtures 2>/dev/null | head; echo "---"; rg -ln "macro" tests/fixtures/stage25* 2>/dev/null || echo "(no stage25 macro fixtures found)"'
```
记录:replay 夹具的 macro 是否有缺 pv/cr 场景。**有→Task 4 走 golden 核对路径;无→保持 byte-stable。** 回报此结论。

## Task 1 — caliber registry + dispatch(TDD)
**Files:** Modify `src/datasource/engines/stage2_5/trend_backfill.py`;Create `tests/test_stage25_macro_backfill.py`
- [ ] **Step 1: 测试先行**
```python
from datasource.engines.stage2_5.trend_backfill import _macro_change_rate, MACRO_CHANGE_RATE_CALIBER


def test_yoy_pp_uses_point_difference():
    assert _macro_change_rate("ppi", 2.8, 0.5) == (2.3, None)
    assert _macro_change_rate("cpi", 1.2, 1.0)[0] == 0.2


def test_level_uses_percentage():
    assert _macro_change_rate("bdi", 2818.0, 2916.0)[0] == round((2818-2916)/2916*100, 4)


def test_level_div_by_zero_returns_none():
    assert _macro_change_rate("bdi", 5.0, 0.0) == (None, "change_rate_pct_div_by_zero")


def test_unknown_key_infers_by_unit():
    assert _macro_change_rate("xx", 3.0, 2.0, unit="%") == (1.0, "caliber_inferred")
    assert _macro_change_rate("xx", 300.0, 200.0, unit="点")[1] == "caliber_inferred"
```
- [ ] **Step 2: 跑红**:`bash run_clean.sh python -m pytest tests/test_stage25_macro_backfill.py -q`(ImportError)。
- [ ] **Step 3: 实现**(加到 trend_backfill.py,`_calc_prev_from_event_history` 之前):
```python
MACRO_CHANGE_RATE_CALIBER = {
    "cpi": "yoy_pp", "ppi": "yoy_pp", "pmi": "yoy_pp",
    "pmi_new_orders": "yoy_pp", "pmi_production": "yoy_pp",
    "gdp": "yoy_pp", "industrial": "yoy_pp", "industrial_sales": "yoy_pp",
    "bdi": "level_pct",
}


def _macro_change_rate(indicator, current, previous, *, unit=None):
    """Return (change_rate, note). note ∈ {None, 'caliber_inferred', 'change_rate_pct_div_by_zero'}."""
    caliber = MACRO_CHANGE_RATE_CALIBER.get(indicator)
    inferred = caliber is None
    if caliber is None:
        caliber = "yoy_pp" if str(unit or "").strip() == "%" else "level_pct"
    if caliber == "yoy_pp":
        return round(current - previous, 4), ("caliber_inferred" if inferred else None)
    if abs(previous) < 1e-12:
        return None, "change_rate_pct_div_by_zero"
    return round((current - previous) / abs(previous) * 100, 4), ("caliber_inferred" if inferred else None)
```
- [ ] **Step 4: 跑绿** + `flake8` 该文件。commit `feat: add macro change_rate caliber registry/dispatch (PR-E1)`

## Task 2 — 重写 `_calc_prev_from_event_history`(正则修复 + 周期锚定 + 宁缺勿错)(TDD)
**Files:** Modify `src/datasource/engines/stage2_5/trend_backfill.py`;`tests/test_stage25_macro_backfill.py`
- [ ] **Step 1: 测试先行**(用 tmp 合成 event_history;`_load_event_history` 从 `base_dir` 读):
```python
import json
from pathlib import Path
from datasource.engines.stage2_5.trend_backfill import _calc_prev_from_event_history


def _write_events(base: Path, indicator: str, events):
    # 与 _load_event_history 读取路径一致(plan 执行时按真实读取布局对齐)
    d = base / "events"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{indicator}.json").write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")


def test_cpi_picks_strict_prior_not_current(tmp_path):
    _write_events(tmp_path, "cpi", [
        {"report_period": "2026-04", "value": 0.8, "unit": "%"},
        {"report_period": "2026-05", "value": 1.0, "unit": "%"},
        {"report_period": "2026-06", "value": 1.2, "unit": "%"},
    ])
    r = _calc_prev_from_event_history("cpi", 1.2, "2026-06-10", base_dir=tmp_path,
                                      current_period="2026-06", unit="%")
    assert r["previous_value"] == 1.0          # 严格前期,非当前 1.2
    assert r["change_rate"] == 0.2             # pp 差
    assert r["value_source"] == "event_history_backfill"


def test_industrial_report_period_regex_fixed(tmp_path):
    _write_events(tmp_path, "industrial", [
        {"report_period": "2026-03", "value": 5.7, "unit": "%"},
        {"report_period": "2026-04", "value": 4.1, "unit": "%"},
    ])
    r = _calc_prev_from_event_history("industrial", 4.1, "2026-05-10", base_dir=tmp_path,
                                      current_period="2026-04", unit="%")
    assert r["previous_value"] == 5.7
    assert r["change_rate"] == round(4.1 - 5.7, 4)


def test_guard_no_strict_prior_returns_none(tmp_path):
    _write_events(tmp_path, "cpi", [{"report_period": "2026-06", "value": 1.2, "unit": "%"}])
    r = _calc_prev_from_event_history("cpi", 1.2, "2026-06-10", base_dir=tmp_path,
                                      current_period="2026-06", unit="%")
    assert r["previous_value"] is None and r["reason"] == "no_previous_value"
```
> 注:`_write_events` 的落盘布局必须与 `_load_event_history` 实际读取一致——Step 2 执行时先读 `_load_event_history` 源码对齐路径/文件名,再定稿夹具写法。
- [ ] **Step 2: 跑红**。
- [ ] **Step 3: 实现** — 替换 `_calc_prev_from_event_history`(签名加 `current_period`/`unit`;正则 `\\d`→`\d`;统一周期解析;周期锚定 + 宁缺勿错;改用 `_macro_change_rate`):
```python
def _calc_prev_from_event_history(
    indicator, current_value, reference_date, *,
    base_dir: Path = DEFAULT_BASE_DIR,
    current_period: Optional[str] = None,
    unit: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """为宏观指标从事件序列回推 previous_value 与 change_rate（宁缺勿错）。"""
    result = {"previous_value": None, "change_rate": None, "reason": None,
              "value_source": None, "caliber_note": None}
    if current_value is None:
        return result
    events = _load_event_history(indicator, base_dir=base_dir)
    if not events:
        result["reason"] = "trend_history_missing"
        return result

    def _parse_date(date_text):
        if not date_text:
            return None
        text = str(date_text)[:10]
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y%m%d", "%Y%m"):
            try:
                dt = datetime.strptime(text, fmt)
                if fmt in ("%Y-%m", "%Y%m"):
                    return datetime(dt.year, dt.month, 1)
                return dt
            except Exception:
                continue
        return None

    anchored = _parse_date(current_period)
    anchor = anchored or _parse_date(reference_date) or datetime.now()
    parsed = []
    for event in events:
        if not isinstance(event, dict):
            continue
        period_text = (event.get("report_period")
                       or event.get("release_date") or event.get("date"))
        dt = _parse_date(period_text)
        val = _coerce_float(event.get("value"))
        if dt is None or val is None:
            continue
        parsed.append((dt, val))
    if not parsed:
        result["reason"] = "no_previous_value"
        return result
    parsed.sort(key=lambda x: x[0])

    if anchored is not None:
        candidates = [(d, v) for (d, v) in parsed if d < anchor]
    else:
        candidates = [(d, v) for (d, v) in parsed
                      if d <= anchor and abs(v - float(current_value)) >= 1e-6]
    if not candidates:
        result["reason"] = "no_previous_value"
        return result

    prev_val = candidates[-1][1]
    result["previous_value"] = prev_val
    change_rate, note = _macro_change_rate(
        indicator, float(current_value), float(prev_val), unit=unit
    )
    if change_rate is None and note == "change_rate_pct_div_by_zero":
        result["reason"] = "change_rate_pct_div_by_zero"
    else:
        result["change_rate"] = change_rate
    result["value_source"] = "event_history_backfill"
    if note == "caliber_inferred":
        result["caliber_note"] = note
    return result
```
> 不删 `_calc_change_rate_pct`(forex/商品/债券路径仍用)。原 industrial 专用分支与通用分支合并为上面统一逻辑。
- [ ] **Step 4: 跑绿** + flake8。commit `fix: anchor macro backfill to indicator period; fix report_period regex; fail-closed (PR-E1)`

## Task 3 — 调用点传周期/单位 + value_source 标注 + 契约字段
**Files:** Modify `entry_mergers.py`、`trend_backfill.py`(`_backfill_trend_changes`)、`src/datasource/models/market_data_contract.py`
- [ ] **Step 1** `entry_mergers._apply_macro_entry`(~239 调用处):传 `current_period=entry.get("report_period") or entry.get("date") or entry.get("as_of_date")`、`unit=entry.get("unit")`;应用回填后,若 `hist_prev.get("value_source")` 存在且 entry 无既有非 backfill `value_source`,设 `entry["value_source"] = "event_history_backfill"`;`hist_prev.get("caliber_note")` 存在则 `_append_note(entry, "caliber_inferred")`。
- [ ] **Step 2** `_backfill_trend_changes` macro 段(~1165 调用处):同样传 `current_period`/`unit`,回填后设 `indicator["value_source"]="event_history_backfill"`(仅当本次回填了 pv/cr 且无既有非 backfill 来源)。
- [ ] **Step 3** `market_data_contract.MacroIndicatorData` 加 `value_source: Optional[str] = None`(extra=ignore 下非必须,但保持契约忠实)。
- [ ] **Step 4** 校验:`bash run_clean.sh python -m pytest tests/test_stage25_macro_backfill.py tests/test_contract_validation.py -q` + flake8。commit `feat: tag macro backfill value_source; pass period/unit from callers (PR-E1)`

## Task 4 — replay golden 处理 + 全量
- [ ] **Step 1** 跑 replay/contract:`bash run_clean.sh python -m pytest tests/test_stage25_contract_replay.py tests/test_stage2_replay_harness.py -q`。
  - **Task 0 结论=不触发 macro 回填** → 必须仍 byte-stable PASS(绝不 update golden)。
  - **Task 0 结论=触发** → 若 golden mismatch,导出 diff 人工逐条核对:仅 macro pv/cr 从错/空变为"正确严格前期 + 正确口径",无其它字段漂移 → 确认后才 `STAGE2_REPLAY_UPDATE_GOLDEN` 重生 golden 并 commit;**任何非预期字段变化即停-回报**。
- [ ] **Step 2** 全量:`bash run_clean.sh python -m pytest -q 2>&1 | tail -5`(= baseline N + 新单测,除 Step1 预期 golden 修正外无回归)。
- [ ] **Step 3** commit `test: macro backfill regression + replay golden (expected-correction or byte-stable) (PR-E1)`

## Task 5 — 文档
- [ ] **Step 1** CLAUDE.md:把"Stage2.5 中 `macro_indicators.change_rate` 统一为百分比口径(`(current-previous)/abs(previous)*100`)"改为"同比%/指数类(cpi/ppi/pmi/pmi_*/gdp/industrial/industrial_sales)用 pp 差(`cur−prev`);水平值(bdi)用 `(cur-prev)/abs(prev)*100`;回填来源标 `value_source=event_history_backfill`,不动 is_estimated"。AGENTS.md 资金流/Stage2.5 段同步一句。
- [ ] **Step 2** 跑 `pytest tests/test_manual_template.py tests/test_stage4_docs.py -q` 确认文档契约绿。commit `docs: document per-type macro change_rate caliber + value_source (PR-E1)`

## Task 6 — TODOS + 隔离 + 回报
- [ ] TODOS.md 勾 E1;commit `docs: mark PR-E1 complete in refactor TODOS`。
- [ ] 隔离断言:`git status --short` 仅本 PR 文件;无 `data/`/`data/trend_history`/`reports/` 改动。
- [ ] 回报:commit 列表、全量 passed、Task 0 的 replay 夹具结论 + Task 4 golden 处理结果、新单测覆盖(cpi/ppi/bdi/industrial/guard/registry)、value_source 标注、计划外改动。

---

## 评审 checklist
1. 正则 `\\d`→`\d`;前值周期锚定 + 取不到严格前期返回 None(宁缺勿错,不把当前值当 previous)。
2. change_rate 分口径(registry yoy_pp/level_pct + unit fallback 标 caliber_inferred);单测逐口径断言。
3. 回填标 `value_source=event_history_backfill`,`is_estimated` 不变;仅在 pv/cr 缺失时回填,不覆盖既有正确值。
4. replay golden:不触发→byte-stable;触发→diff 逐条核对为预期修正后才更新。全量无其它回归。
5. `_calc_change_rate_pct` 未删(其它路径仍用);两个调用点都传 period/unit。
6. CLAUDE/AGENTS 口径表述已修正;合入在 main 之上 squash;清 worktree/分支。

## Self-Review
- Spec 覆盖:§2 四修复 → Task 1/2/3/5;§3 算法 → Task 2(完整函数);§4 测试+byte-stable → Task 0/2/4。✅
- Placeholder:registry/dispatch/重写函数全码;夹具写法注明"先对齐 `_load_event_history` 路径";命令带 Expected。✅
- 一致性:`_macro_change_rate`/`MACRO_CHANGE_RATE_CALIBER`/`value_source`/`current_period`/分支名在 spec/plan/测试间一致。✅
- 风险:宁缺勿错 guard、行为修正的 golden 核对(非盲更)、隔离 base_dir、不删 `_calc_change_rate_pct`,均显式。✅
