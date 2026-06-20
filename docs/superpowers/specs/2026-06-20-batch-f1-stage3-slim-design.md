# 批次 F1:stage3_pring_analyzer 入口瘦身(relocate 到 engines/stage3)— 设计文档

> Spec for the 2026-06 refactor, batch F1(全局验收复盘补口:验收2 "全部入口 ≤300" 对 stage3 未达成)。
> Status: 2026-06-20 设计批准(复盘 + 源码深挖产出)。建在 main `83d3bc6`;独立 PR。C6/C7 同模式 relocate。

## 1. 目的与定位

`scripts/stage3_pring_analyzer.py` 现 **867 行**,塞着可下沉的 gate/质量编排 glue(`_run_analysis` ~356 行 + ~20 个 `_collect_*`/`_policy_*`/`_require_data_completeness`/`_resolve_gap_monitor_path` helper + parse_args + main),违反全局验收"scripts 全部入口 ≤300"。C 批只下沉了 stage1/2/2.5,stage3 入口从未纳入。

F1 = **C6/C7 式 relocate**:把这些 glue 逐字搬到新 `engines/stage3/`,脚本瘦到 ≤300(re-export 薄壳 + 转发 main),repoint 测试 monkeypatch 目标。**纯搬移 + repoint,零业务逻辑改动**;不动真正算法 `calculators/pring_analyzer.py`(已在 src)。

> **验收2 完整收尾(批次 F)= 本 PR 两件事**:① stage3 relocate(本 spec 主体);② `stage4_risk_review.py` **不做 relocate**——它是有意 standalone、不 import datasource 包的只读 review gate(由 `test_run_path_does_not_import_datasource_package` 强制;用 importlib 按 path 加载 run_paths/run_lock),engines-relocate 会破该契约,故**豁免** engines 瘦身,仅在本 PR 文档/REFACTOR_PLAN 留痕 + 脚本加 standalone 缘由注释(见 plan Task 5)。"全部入口 ≤300"细化为"有 engines 逻辑的 stage 入口(1/2/2.5/3)≤300"。

## 2. 关键源码事实(深挖)
- `engines/stage3` **不存在** → 本 PR 新建包(同 C6 新建 engines/stage1)。
- 脚本结构:常量 `MIN_COMPLETENESS_DEFAULT`(40);helper(43–409,约 20 个);`_run_analysis`(410–766);`parse_args`(767–832);`main`(833–end)+ `if __name__`。
- 脚本 deps(搬移代码要读):`get_manager`、`calculators.pring_analyzer.PringAnalyzer`、`models.market_data_contract.MarketDataContract`、`utils.contract_validation.validate_pring_result`、`utils.gate_formatting.*`、`utils.json_io.atomic_write_json`、`utils.missing_items.flatten_missing_items`、`utils.pipeline_gate.*`、`utils.pipeline_quality_state.build_pipeline_quality_state`、`utils.policy_rules.*`、`utils.run_lock.{DailyRunLock,run_dir_from_artifact}`、`utils.run_paths.build_run_paths_from_reference`。
- **测试 repoint 面(4 文件)**:
  - `test_stage3_guard.py`(`import ... as s3`):`setattr(s3, "MarketDataContract"/"PringAnalyzer"/"get_manager", ...)`(429-431/641-643/747-749)+ 调 `s3._run_analysis`/`_require_data_completeness`/`_resolve_gap_monitor_path`(~15+)。
  - `test_stage_validation_wiring.py`(`as stage3`):`setattr(stage3, "MarketDataContract"/"PringAnalyzer"/"get_manager"/"validate_pring_result"/"atomic_write_json", ...)`(77-81)+ 调 `stage3._run_analysis`(84)。
  - `test_pring_scoring_golden.py`:`from scripts.stage3_pring_analyzer import _run_analysis` + 调用(**golden,字节稳定,无 patch**)。
  - `test_daily_writer_locks.py`(`as stage3`):`setattr(stage3, "DailyRunLock", ...)`(139)、`setattr(stage3.asyncio, "run", ...)`(147)、调 `stage3.main()`(149)。

## 3. 目标结构 + 归属
```
src/datasource/engines/stage3/__init__.py
src/datasource/engines/stage3/core.py   # MIN_COMPLETENESS_DEFAULT + ~20 helper + _run_analysis(逐字)
src/datasource/engines/stage3/cli.py    # parse_args + main(逐字);main 内调 core._run_analysis
scripts/stage3_pring_analyzer.py        # re-export 薄壳(from ...engines.stage3.core import *)+ from ...cli import main + if __name__;≤300
```
- **owner 划分(决定 repoint 目标)**:`_run_analysis` + helper 读 `MarketDataContract/PringAnalyzer/get_manager/validate_pring_result/atomic_write_json` → 这些在 **core** 命名空间;`main` 读 `DailyRunLock/asyncio` + 调 `_run_analysis` → 在 **cli** 命名空间。glue 精确归属与 import header 由 F821 定(同 C-batch)。
- `MIN_COMPLETENESS_DEFAULT` 放 core(若 cli 的 argparse default 也用,cli 从 core import)。

## 4. 测试 repoint(C6/C7 教训:patch 必须打到搬移后 owner 模块)
- `test_stage3_guard.py`:加 `from datasource.engines.stage3 import core as s3core`;`setattr(s3, X)`(MarketDataContract/PringAnalyzer/get_manager)→ `setattr(s3core, X)`;调用 `s3._run_analysis`/`_require_data_completeness`/`_resolve_gap_monitor_path` → `s3core.*`。
- `test_stage_validation_wiring.py`:patch 5 个属性 + 调 `_run_analysis` → 全指 `engines.stage3.core`。
- `test_daily_writer_locks.py`:`DailyRunLock`/`asyncio`/`main()` → 指 `engines.stage3.cli`。
- `test_pring_scoring_golden.py`:`from scripts.stage3_pring_analyzer import _run_analysis` **可不动**(re-export 薄壳保留该名);它只调用不 patch → re-export 即工作。**golden 字节稳定为硬门**。

## 5. 测试 / 安全网
- `_run_analysis` + helper 逐字搬(可选 AST/token 等价自检);**golden(test_pring_scoring_golden)byte-stable**(绝不更 golden,mismatch 即停)。
- `test_stage3_guard`(gate 三路/completeness/redlist 全覆盖)repoint 后全绿——relocate-only 行为不变的强证据。
- import-time 冒烟(脚本薄壳 + engines/stage3 无环);py_compile + `flake8`(逐字搬的继承长行可 per-file-ignore E501,F401/F821 仍检)。
- 脚本 ≤300 行;`--help` diff 空;全量 `pytest -q` 无回归。

## 6. 验收
- `scripts/stage3_pring_analyzer.py` ≤300 行,仅 re-export + 转发 main + `if __name__`;`_run_analysis`/helper/parse_args/main 已在 `engines/stage3/`。
- 4 测试文件 repoint 完成;golden byte-stable;`test_stage3_guard` 全绿;全量无回归;`--help` diff 空。
- 无 engines/stage3→scripts 反向 import;不动 calculators/pring_analyzer 与 gate/policy utils。

## 7. 风险与缓解
| 风险 | 缓解 |
|---|---|
| monkeypatch 假绿(patch 未触达搬移后 _run_analysis)| §4:patch 改指 core/cli;`test_stage3_guard` 的值断言(block/redlist)会真实触发,不会假绿 |
| 搬移引入 body 差异 | 逐字搬 + golden byte-stable + test_stage3_guard |
| glue 反向被 engines 其它模块需要成环 | F821/import 冒烟;engines/stage3 是新包,无反向 import |
| 脚本仍 >300 | 把 _run_analysis+helper+parse_args+main 都搬走,薄壳必 ≤300(实测复核)|
