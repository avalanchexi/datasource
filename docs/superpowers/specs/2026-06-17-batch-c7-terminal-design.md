# 批次 C7(C 终态):入口瘦身 + shim 清理 + 文档同步 — 设计文档

> Spec for the 2026-06 refactor, batch C 终态收尾(REFACTOR_PLAN 全局验收 §)。
> Status: 2026-06-17 设计批准(brainstorming 产出)。前置 C1–C6 已合入 main(Stage1/2/2.5 逻辑已下沉 `engines/stage{1,2,2_5}/`;C6 待合入则以其合入后 HEAD 为开工基)。
> 行号采自开工时 HEAD;搬移按函数名 + 逐字 body。

## 1. 目的与定位

一个 PR 关闭批次 C 所有收尾债务:① 删 batch-B 延期的 8 个转发 shim;② 文档同步(模块映射/命令路径到新结构);③ 两个入口脚本瘦到 ≤30 行(`stage2_unified_enhancer.py` 866→≤30、`stage2_5_injector.py` 245→≤30)。完成后 `scripts/` 三大入口皆为薄壳,逻辑/名称全在 `src/`。

**这是 C-split 量级、批次 C 最高风险的 PR**:入口瘦身要去掉 re-export 块并把 `main()`(~490 行)+ io/glue 搬入 src,从而逼迫**全面 repoint 测试 import 与 monkeypatch 目标**——尤其 canonical 的 Stage2 replay harness 与 Stage2.5 contract replay 深度 monkeypatch 脚本模块。纯搬移 + repoint,零业务逻辑改动。

## 2. 范围

**In scope**(四条工作线,各自独立 commit):
1. **shim 删除 + 活引用 repoint + 文档同步**:删 8 个 batch-B `runpy` 转发 shim(`scripts/{trend_history_backfill,trend_history_scan,sanitize_market_data,compare_stage2_runs,stage2_health_check,stage2_low_score_audit,setup_stage2_search_env,run_snapshot}.py`);每个删前 repoint 活引用(`tests/test_sanitize_market_data.py` → `scripts/tools/market_data_sanitize.py`,及其它实测命中)到 `scripts/tools/<新名>`;`CLAUDE.md`/`AGENTS.md`/`SCRIPTS.md`/`README.md` 模块映射 + 命令路径同步到 `engines/stage{1,2,2_5}/` + `scripts/tools/`。
2. **stage2.5 入口瘦身**:`stage2_5_injector.py` 去 C4/C5 re-export 块 → ≤30 行 forwarder(`main` 已 C5 在 `engines/stage2_5/cli.py`,脚本仅 `from datasource.engines.stage2_5.cli import main` + `if __name__`);repoint stage2.5 侧测试(`test_websearch_injector`/`test_stage25_contract_replay`/`test_daily_writer_locks`/`test_forex_evidence_characterization`)的 `from scripts.stage2_5_injector import …` 与 `monkeypatch.setattr(injector, …)` → `datasource.engines.stage2_5.*`。
3. **stage2 入口瘦身**:把 `main()`(~490 行,485–974)+ 10 个 io/glue(`_load_json`/`_merge_missing_items`/`_apply_aliases`/`_warn_disable_extract_on_critical_tasks`/`_check_task_completeness`/`_dump_json`/`_append_gap_monitor`/`_filter_tasks`/`_compute_derived_metrics`/`_gap_monitor`)逐字搬到 `engines/stage2/cli.py`(F821 定 glue 精确归宿);去 re-export 块;`stage2_unified_enhancer.py` → ≤30 行 forwarder;repoint stage2 侧测试(`test_stage2_unified`/`test_stage2_fallbacks`/`test_stage2_structured_integration`/`test_stage2_structured_golden`/`test_stage2_replay_harness`)的 import 与 monkeypatch → `engines.stage2.*`。
4. (文档同步并入工作线 1。)

**Out of scope**:任何业务逻辑改动(纯搬移 + repoint);重算任何 golden;batch-A MCP 归档(另线);batch D/E。

## 3. 中央风险:canonical replay/contract 深度 monkeypatch ⚠️

- `tests/test_stage2_replay_harness.py`(byte-stable 金标)`import scripts.stage2_unified_enhancer as stage2`,patch `stage2.AsyncTavilyClient`/`DeepSeekExtractionAgent`/`build_default_registry`/`_execute_tasks`/`datetime`/`time.perf_counter`,并调 `stage2.main()`。main 搬到 `engines/stage2/cli.py` + 脚本去 re-export 后,这些 patch/调用全失效 → **必须全部 repoint 到 `engines.stage2.cli.*` 并改调 `cli.main()`**,且 **golden 仍 byte-stable、四链路覆盖/extract-count 等断言不假绿**。
- `tests/test_stage25_contract_replay.py` 同理(patch `injector.*` + `injector.inject_websearch_data`)。
- **纪律(C5 教训最大化)**:repoint 后**绝不** `STAGE2_REPLAY_UPDATE_GOLDEN`;golden mismatch / 假绿(patch 未触达但断言通过)即停-回报。被搬到 cli 的 main 读 cli 命名空间的 `AsyncTavilyClient` 等,故 patch 目标与 `cli.main()` 调用同模块,单点可达。

## 3.5 fan-out 勘探结论(执行必读;选定 stage2 全 ≤30)

3 个 read-only agent 勘探出两处原决策未覆盖的硬问题,**选定方案:stage2 入口全 ≤30(丢 C1/C2/C3 re-export 块 + 全面 repoint)**:

- **R-cycle(必破)**:`engines/stage2/execution.py:29` 已 `from datasource.engines.stage2.cli import _callable_supports_kwarg`。C7 让 cli 再 import `_execute_tasks` from execution → **cli⇄execution 环**。**解法(选 b)**:在 `main()` 体内**延迟 import** `_execute_tasks`(`from datasource.engines.stage2.execution import _execute_tasks` 放进 main,匹配 `stage2_lc_pipeline` 既有延迟-import 模式);不动 `_callable_supports_kwarg`。
- **R-move**:搬入 `engines/stage2/cli.py` 的不止 11 个符号——还有常量 **`CRITICAL_EXTRACT_KEYS`(272–282)**(仅 `_warn_disable_extract_on_critical_tasks` 用,无其它 consumer)。cli import header 见 plan(agent C §2:加 asyncio/sys/datetime + `datasource.*` 一批 + 6 个 sibling import + main 内延迟 `_execute_tasks`)。
- **R-import-repoint(表 A)**:9 测试文件的 `from scripts.stage2X import NAME` + `import as` 属性访问,逐名 repoint 到 canonical engines 模块(plan 附全表)。
- **R-utils-alias(易漏)**:测试经脚本别名访问的这些**不是 engines 名,是脚本对 utils 的别名**,薄壳带不了 → repoint 到 `datasource.utils.*`:
  - stage2 侧:`stage2._FOREX_DAILY_EVIDENCE_MARKERS`/`_FOREX_120D_EVIDENCE_MARKERS`→`utils.forex_evidence.STAGE2_FOREX_*`;`_FOREX_COMPARE_FIELD_EVIDENCE_KEYS`→`utils.forex_evidence`;`stage2._append_note`→`utils.note_utils.append_note_text`。
  - stage2.5 侧:`stage25.FOREX_DAILY/120D_CHANGE_SOURCE_MARKERS`/`*_EVIDENCE_KEYS`→`utils.forex_evidence`;`stage25._append_note_once`→`utils.note_utils.append_note_once`;`stage25._append_note`→`utils.note_utils.append_note_to_entry`。
  - ⚠️ **`_append_note` 两侧语义不同**(stage2=`append_note_text`、stage2.5=`append_note_to_entry`),repoint 各指各的,勿混。
- **R-monkeypatch(表 B)**:main 进 cli 后,`test_stage2_replay_harness` 的 `stage2.{AsyncTavilyClient,DeepSeekExtractionAgent,_execute_tasks,build_default_registry,main,datetime,time}` 全 repoint 到 `stage2_cli`(`build_default_registry`/部分已指 stage2_cli);`stage2.main()`→`stage2_cli.main()`;`_freeze_stage2_datetime` 基类与冻结循环把 `stage2` 换/加 `stage2_cli`。`test_stage2_unified.py:436` `_execute_tasks` patch、L459 `main()` 调用同样 →`stage2_cli`(需加 `from datasource.engines.stage2 import cli as stage2_cli`)。stage2.5 侧 setattr/main 调用 C5 已 repoint,不动。
- **lc_pipeline 不受影响**:`stage2_lc_pipeline.py:40` 延迟-import 的 9 名都不在 C7 move 集。

## 4. 目标结构

```
src/datasource/engines/stage2/cli.py     # 现有 arg-helpers + 新增 main(~490) + 10 io/glue(F821 定)
src/datasource/engines/stage2_5/cli.py   # C5 已含 main(不动)
scripts/stage2_unified_enhancer.py       # ≤30 行:from ...engines.stage2.cli import main + if __name__
scripts/stage2_5_injector.py             # ≤30 行:from ...engines.stage2_5.cli import main + if __name__
scripts/{8 shim}.py                       # 删除
```
依赖方向不变(向下);脚本仅 import cli;import-time 冒烟无环。

## 5. plan 时并行勘探(read-only fan-out,产出三张映射表)
- **表 A — import-repoint**:9 个测试文件每个 `from scripts.stage2X import NAME`,NAME → 其 canonical engines 模块(grep 定义位置)。
- **表 B — monkeypatch-repoint**:replay harness + contract replay + 其它 `setattr(stage2|injector, "X", …)`/`import as` 的每个 patch 目标 → owning 模块(尤其 `main`/`_execute_tasks`/`AsyncTavilyClient`/`DeepSeekExtractionAgent`/`build_default_registry`/`datetime`/`time`);含 `script.main()` 调用改 `cli.main()`。
- **表 C — main + 10 glue 归宿**:每个 glue 的 import header(F821)+ 是否被 execution.py(C3)等反向需要(若是 → 归 cli 仍向下,因 execution 不 import cli;确认无环)。

## 6. Tests / 安全网
- 两 replay/contract harness repoint 后 **byte-stable 且非假绿**(canonical 网);9 测试文件 import repoint 后全绿。
- import-time 冒烟(脚本 forwarder + cli 无环);py_compile + `flake8 src/`(cli 新增 main/glue 可能需 per-file-ignore 继承码,F401/F821 仍检)。
- 两入口 `--help` diff 空;两脚本 ≤30 行;8 shim 删净(`rg` 无残留 scripts/旧名)。
- 文档命令契约 `test_manual_template`/`test_stage4_docs` 绿。
- `pytest -q` 全量无回归(基线 = C6 合入后 passed 数)。

## 7. 执行序(commit)
shim+doc(线1)→ stage2.5 thin(线2)→ stage2 thin(线3,最大,replay repoint 单独 commit)。**线 2/3 中途,未 repoint 的 replay/contract 与 import 测试会 RED——预期**(同 C5),用 py_compile/import 冒烟/非 patch 子集校验,repoint commit 后转绿。

## 8. 验收
- `scripts/stage2_unified_enhancer.py` + `scripts/stage2_5_injector.py` 各 ≤30 行,仅 import cli.main + `if __name__`;`rg "^async def main|^def _load_json|^def _gap_monitor" scripts/stage2_unified_enhancer.py` 为空。
- 8 shim 文件删除;无 `scripts/<旧名>` 残留引用(tests/docs/code);活引用改指 `scripts/tools/`。
- 文档模块映射/命令路径与新结构(`engines/stage{1,2,2_5}/` + `tools/`)一致。
- 两 replay/contract byte-stable 且非假绿;9 测试文件 + monkeypatch repoint 完成;全量无回归;两 `--help` diff 空。
- 无 module→脚本反向 import;import 冒烟无环。

## 9. 风险与缓解
| 风险 | 缓解 |
|---|---|
| replay/contract harness repoint 假绿(byte-stable 失真) | §3 纪律:不更新 golden;专项确认 patch 经 cli 命名空间触达 `cli.main()`;四链路/extract-count/never-called 断言仍触发 |
| 9 文件 import repoint 漏名 → ImportError/NameError | 表 A 全名映射 + F821/import 冒烟兜底 |
| main+glue 搬迁引入 body 差异 | 逐字搬移 + replay byte-stable + `is` 身份(可选)|
| glue 被 execution.py 反向需要成环 | 表 C 确认方向;import 冒烟 |
| shim 删除破活引用(test_sanitize_market_data 等) | 线1 每个 shim 删前 grep 活引用并 repoint 到 tools/ |
| 中途 RED 被误判 | §7 声明预期 RED;Codex 勿停 |
