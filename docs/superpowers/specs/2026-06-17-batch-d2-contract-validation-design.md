# 批次 D2:写盘前 contract 校验 — 完整对齐 + hard-fail + 逃生门 — 设计文档

> Spec for the 2026-06 refactor, batch D2(REFACTOR_PLAN §7)。
> Status: 2026-06-17 设计批准(brainstorming 产出)。建在 **D1 之上**(用 `atomic_write_json`);分支序 C7→D1→D2;一个 PR。
> 决策:`extra=ignore`(不 forbid)、完整对齐两 contract 全部观测字段、21-run fixture 回归网。

## 1. 目的与定位

各阶段写 `market_data*.json` / `pring_result.json` **前**过对应 Pydantic contract 校验,残缺/错形产物 hard-fail(不写盘、退非零),带 `--no-validate-output` 逃生门(默认开校验)。先把两个 V3.1 contract **完整对齐到真实输出**(否则 hard-fail 会当场打挂活流水线),再接线。纯校验 + contract 对齐,**不改任何 stage 输出内容、零业务逻辑改动**。

实测依据(21 个 run 全字段并集):`market_data_complete.json` 在严格校验下有 46–54 个真实合法但未建模字段、且**逐日变化**;`pring_result.json` 的 3 层 schema 与 V3.1 contract 不符(real 用 `score_details`/`base_confidence`,无 `indicators`/`asset_allocation`)。故 `extra=ignore` + 完整对齐 + 全 run fixture 网。

## 2. 范围

**In scope**
- `utils/contract_validation.py`:`validate_market_data(payload)`、`validate_pring_result(payload)`,内部 `Model.model_validate`,失败抛 `ContractValidationError`(含可读字段路径错误)。
- 完整对齐两 contract(见 §4 对齐表):补全部观测字段(Optional where conditional,真实类型)、放宽 pring 错位 required;`extra=ignore`(Pydantic 默认)。
- 接线:stage1/2/2.5 写 market_data*.json 前过 market_data 校验;stage3 写 pring_result.json 前过 pring 校验。
- 逃生门:stage1/2/2.5/3 脚本加 `--no-validate-output`(默认开)+ env `DATASOURCE_NO_VALIDATE_OUTPUT=1`。
- 测试:21-run fixture 校验网 + mutation(删 required/错类型 → fail)+ 逃生门绕过。
- 文档:SCRIPTS/AGENTS/CLAUDE 记 contract 校验 + 逃生门。

**Out of scope**
- `forbid` 严格 extra(已否决:管线 extra 常态高频变化,误杀高、维护重)。
- 迁移 contract 的 V1 `@validator`/`class Config` 到 V2(留着;deprecation 不在范围)。
- PipelineStateContract 全状态机(§7 子集)。
- 改任何 stage 输出内容 / D1 已做的原子写。
- stage4 报告 `.md`(非 JSON contract)。

## 3. 注入点与 hard-fail
- 校验在各 stage **写盘调用之前**(`atomic_write_json(payload, path)` 前 `validate_*(payload)`);失败抛 `ContractValidationError` → stage 退非零、**不写**无效产物 → 打印 Pydantic 字段错误。
- `--no-validate-output` / env=1 时跳过校验直接写(逃生门;用于 contract 暂时落后于合法新字段时不阻断运维)。
- 校验**只读 payload**,不改内容 → replay/contract golden 与产物逐字不变。

## 4. 完整对齐表(21-run 并集;新增字段一律 Optional[…]=None,真实类型;[n/21]=出现频次)

### market_data 子模型——补观测 extra(Optional)
- **CommodityData** +6:`as_of_date:str`、`confidence:float`、`daily_change_basis:str`、`date:str`、`is_estimated:bool=False`、`trend_history_confidence:str`
- **ForexData** +9:`change_120d_base_date:str`、`change_120d_basis:str`、`confidence:float`、`daily_change_base_date:str`、`daily_change_basis:str`、`date:str`、`is_estimated:bool=False`、`stage_task_id:str`、`trend_history_confidence:str`
- **BondYieldData** +3:`estimation_method:str`、`source_url:str`、`trend_history_confidence:str`
- **FundFlowData** +7:`as_of_date:str`、`claimed_source_tier:str`、`date:str`、`estimation_method:str`、`manual_required:bool=False`、`source_tier:str`、`window_evidence:str`
- **MacroIndicatorData** +4:`confidence:float`、`estimation_method:str`、`report_period:str`、`source_url:str`
- **MonetaryPolicyData** +5:`confidence:float`、`estimation_method:str`、`report_period:str`、`source_url:str`、`trend_history_confidence:str`
- **StockIndexData / FinancialNewsItem / metadata / derived_metrics**:无需改(观测 = 现契约 / 空 / 松散 Dict)。

### pring(放宽错位 required + 补观测字段)
- **InventoryCycleLayer**:`indicators`→Optional;+`score_details:Dict[str,Any]`(default_factory)、`analysis:str`、`data_source:str`、`update_time:str`(Optional)
- **MonetaryCycleLayer**:`indicators`→Optional;+`score_details:Dict[str,Any]`(default_factory)、`analysis:str`、`data_source:str`(Optional);`websearch_required:Dict[str,Any]`(default_factory),保留 `websearch_needed`(default)
- **PringFinalLayer**:`confidence`→Optional、`asset_allocation`→Optional;+`base_confidence:float`、`final_confidence:float`、`analysis:str`(Optional)
- **PringResultContract 顶层 +Optional**:`analysis_date:str`、`commodity_bias:str`、`commodity_signal:str`、`commodity_signal_score:float`、`confirm_signals:List`、`current_stage:str`、`data_period:str`、`deny_signals:List`、`enhancement_notes:str`、`final_stage:str`、`focus_assets:List`、`inventory_cycle_score:float`、`inventory_cycle_stage:str`、`leading_summary:str`、`macro_stage:Dict`、`methodology:str`、`recommendation:str`、`stage_description:str`、`technical_score:float`(均 Optional/default;`leading_indicator`/`weights_version`/`data_completeness`/`fallback_used`/`pending_websearch` 已在契约)

> 类型注:`MacroIndicatorData.current_value` 真实 `float/int` → 保持 `Optional[float]`(Pydantic int→float 强制)。always-null 字段(`forex.as_of_date`、`bonds.report_period/stage_task_id`、`monetary.stale_reason`)保持 Optional。

## 5. 测试(回归网)
- **fixture 网**(核心):遍历 `data/runs/2026*/market_data_complete.json` 全部断言 `validate_market_data` 通过;`pring_result.json` 全部断言 `validate_pring_result` 通过。防对齐不全/误杀;新建 `tests/test_contract_validation.py`。
- **mutation**:删顶层 required(如 pring 去 `stage`、market_data 去 `stock_indices`)→ `ContractValidationError`;错类型(`current_price="x"`)→ fail。
- **逃生门**:`--no-validate-output` / env=1 → 跳过校验,即使 payload 非法也写盘(单测断言不抛)。
- 全量 `pytest -q` 无回归;replay/contract byte-stable(校验只读)。
- 文档契约 `test_manual_template`/`test_stage4_docs` 绿(改了脚本 `--help`/SCRIPTS)。

## 6. 验收
- `validate_market_data`/`validate_pring_result`/`ContractValidationError` 存在;两 contract 按 §4 完整对齐;`extra=ignore`。
- 全部 21 run 的两类产物**校验通过**(fixture 网绿);mutation 正确 fail;逃生门正确绕过。
- stage1/2/2.5/3 写盘前接线;`--no-validate-output` + env 生效;失败不写、退非零、打印字段错误。
- 全量无回归;replay/contract byte-stable;文档同步。

## 7. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 对齐不全 → 真实产物被误杀 | §5 fixture 网遍历全部 21 run,CI 级回归;新字段未来出现可用逃生门临时绕过 |
| 校验改了产物内容 | 校验只读 payload(model_validate 不写回);replay/contract byte-stable 兜底 |
| pring required 放宽过度 → 失去校验价值 | 顶层 required 保留 metadata/3 层/stage/confidence/asset_signals;mutation 测试守住 |
| 接线点写法不一(各 stage) | 统一经 `validate_*(payload)` 紧邻 `atomic_write_json` 之前;grep 核对所有 market_data/pring 写盘点 |
| 依赖链漏接(D2 基) | 从 D1 tip 起;atomic_write_json/cli 已在;import 冒烟 |
| 条件字段未来再变 | extra=ignore 不误杀新字段;fixture 网随新 run 扩充 |
