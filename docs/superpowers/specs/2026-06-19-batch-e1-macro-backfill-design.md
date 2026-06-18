# 批次 E1:macro previous_value/change_rate 从 event_history 正确回填 — 设计文档

> Spec for the 2026-06 refactor, batch E1(REFACTOR_PLAN §8,经源码+真实数据勘探后修正了 §8 的"扩面"框架)。
> Status: 2026-06-19 设计批准(brainstorming 产出)。建在 main `2dae81e`(C7+D1+D2 已合);worktree 支线,独立可并行。

## 1. 目的与定位(修正 §8)

让 macro `previous_value`/`change_rate` 从 `event_history` **正确**自动回填,消除 cpi/ppi/pmi/industrial 等 compare 缺口反复落 manual。**不是简单"扩面"** —— 源码+真实数据(20260610)勘探发现现有回填**会产出错值**,必须先修正确性:

- `industrial`/`industrial_sales` 的 report_period 正则被**双重转义**(`r"20\\d{2}-\\d{2}$"`),永远匹配不上 → 回填恒返回 None → 一直落 manual(§8/notes 反复点名的常驻缺口,根因在此)。
- 通用分支前值选取靠"latest≈current 退一格"的启发式,对 cpi/gdp 把**当前值当成 previous**(回填 pv=当前、change=0),静默错值。
- `_calc_change_rate_pct` 一律用百分比 `(cur-prev)/abs(prev)*100`,对同比%指标(cpi/ppi/pmi)产出 460% 这类废值。

**纯回填正确性修复 + 标注;不动 Stage2/manual 既有正确值(只补缺失),不动 is_estimated。**

## 2. 范围

**In scope**(核心改 `src/datasource/engines/stage2_5/trend_backfill.py`,两个调用点 `_apply_macro_entry`(merge 时)+ `_backfill_trend_changes`(post-write)自动受益):
1. **正则修复**:`_calc_prev_from_event_history` 内 report_period 正则 `r"20\\d{2}-\\d{2}$"` → `r"20\d{2}-\d{2}$"`。
2. **前值选取修正(宁缺勿错)**:锚定指标自身当前期(`report_period`/`date`/`as_of_date`),从 event_history 取**周期严格早于当前期**的最近一期值作 `previous_value`;**取不到严格前期 → 返回 None(reason=no_previous_value),留 manual,绝不把当前值/重复值当 previous**。指标无可解析当前期时退回 `reference_date` 为上界,并丢弃 value≈current 的事件后取最近一期(同样取不到则 None)。
3. **change_rate 分口径**:新增 caliber dispatch:
   - **同比%/指数类(pp 差)**:`change_rate = round(cur - prev, 4)`。registry:`cpi`/`ppi`/`pmi`/`pmi_new_orders`/`pmi_production`/`gdp`/`industrial`/`industrial_sales`。
   - **水平值(百分比)**:`change_rate = round((cur-prev)/abs(prev)*100, 4)`(prev=0 → None,reason=change_rate_pct_div_by_zero)。registry:`bdi`。
   - 分类用**显式 registry**(`MACRO_CHANGE_RATE_CALIBER: Dict[str, str]`,值 `"yoy_pp"`/`"level_pct"`);未登记 key 退回 unit 推断(`unit=="%"` → yoy_pp,否则 level_pct),并在回填 note 记 `caliber_inferred`。
4. **标注**:回填出的 `previous_value`/`change_rate` 标 `value_source=event_history_backfill`(写在 entry 字段;若已有非 backfill 来源不覆盖);**不动 `is_estimated`**。
5. **文档**:修 CLAUDE.md "macro_indicators.change_rate 统一为百分比口径" → 改为"同比%/指数类用 pp 差(cur−prev),水平值用 `(cur-prev)/abs(prev)*100`";registry 列表入文档。

**Out of scope**
- 不改 Stage2 抽取/manual 写入的既有正确值(回填只在 pv/cr **缺失**时触发)。
- 不扩 official override allowlist;不碰 E2(manual_fallback_policies.yaml)/E3(reserve_ratio 源屏蔽)。
- monetary_policy `change_from_120d` 回填(本批不动,保持现状)。
- event_history 数据本身的补录(假设已有,§8 前提)。

## 3. 关键算法:前值选取(宁缺勿错)
```
parse cur_period from indicator.report_period | indicator.date | indicator.as_of_date  (月度按 YYYY-MM)
events = load_event_history(key); 解析每条 period(report_period 优先,否则 release_date|date)+ value
candidates = [(p, v) for (p, v) in events if p is not None and v is not None and p < cur_period]
if cur_period is None:  # 无可解析当前期 → 退回 reference_date 上界 + 丢弃 value≈current
    candidates = [(p, v) for (p, v) in events if p <= ref_dt and not (abs(v - current) < 1e-6)]
if not candidates: return {previous_value: None, change_rate: None, reason: "no_previous_value"}
previous_value = max(candidates by period).value
change_rate = caliber_dispatch(key, current, previous_value, unit)
```

## 4. 测试(回归网)
- **单测** `tests/test_stage25_macro_backfill.py`(新):
  - cpi/ppi(yoy_pp):合成 event_history,断言取到**严格前期**(非当前值)+ `change_rate == round(cur-prev,4)`(pp);
  - bdi(level_pct):断言 `change_rate == round((cur-prev)/abs(prev)*100,4)`;prev=0 → None;
  - industrial(report_period,正则修复后):断言能匹配 `2026-04` 类周期并回填;
  - guard:无严格前期 → `previous_value is None`(留 manual);
  - registry:未登记 key 按 unit 推断 + `caliber_inferred` note;
  - 回填项带 `value_source=event_history_backfill`,`is_estimated` 不变。
- **隔离**:全部用 `--trend-history-base-dir`/`base_dir` 指向 tmp 合成 event_history,**不碰真实 `data/trend_history`**。
- **byte-stable 注意(E1 是行为修正,与 C/D 不同)**:先查 `tests/test_stage25_contract_replay.py` 夹具是否触发 macro 回填(夹具 macro 是否有缺 pv/cr 的场景):
  - **不触发** → golden 保持 byte-stable,照常断言;
  - **触发** → golden 合理变化,必须**逐条核对 diff = 预期修正**(正确前期 + 正确口径),确认后才更新 golden;**不盲目 `STAGE2_REPLAY_UPDATE_GOLDEN`**。
- 全量 `pytest -q` 无回归(除上面 replay golden 的预期修正)。
- 文档契约 `test_manual_template`/`test_stage4_docs` 绿(改了 CLAUDE 口径表述)。

## 5. 验收
- 正则修复;前值选取锚定周期 + 宁缺勿错;change_rate 分口径(registry + unit fallback);回填标 `value_source=event_history_backfill`,`is_estimated` 不变。
- 新单测全绿;industrial/cpi/ppi/pmi/bdi 各口径回填正确;guard 生效。
- replay golden:不触发则 byte-stable;触发则 diff 经逐条核对为预期修正。
- CLAUDE.md 口径表述已修正 + registry 入文档;全量无回归。
- (§8 "连续 5 交易日 macro compare manual=0" 属**前向观察**,合入后跟踪,非本 PR 内可算。)

## 6. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 回填错值喂 Stage3 评分 | §3 宁缺勿错:周期锚定 + 取不到严格前期返回 None;单测覆盖 cpi/gdp 误填场景 |
| 口径分类错 | 显式 registry 为准 + unit fallback 标 `caliber_inferred`;单测逐指标断言 |
| 行为变化破坏既有 golden 被误判 | §4:先查夹具是否触发,触发则逐条核对为预期修正,不盲更 golden |
| 误覆盖 Stage2/manual 既有正确值 | 仅在 pv/cr 缺失时回填;`value_source` 已存非 backfill 来源不覆盖 |
| 碰真实 trend_history | 测试一律 `base_dir`/`--trend-history-base-dir` 指向 tmp |
