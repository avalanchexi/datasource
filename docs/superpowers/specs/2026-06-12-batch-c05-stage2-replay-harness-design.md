# 批次 C-0.5:Stage2 replay harness — 设计文档

> Spec for the 2026-06 refactor, batch C-0.5(REFACTOR_PLAN §6.0)。批次 C 任何搬移开始前的硬前置。
> Status: 2026-06-12 设计定稿;**2026-06-12 加固修订**(brainstorming 实测后:换供数 run、用真实录制任务、补确定性守卫)。**纯新增**(夹具 + 测试),不改任何现有代码,零行为风险;与批次 B 零文件交叠,可并行执行。

## 目的

在拆分 `stage2_unified_enhancer.py`(7077 行)之前,用确定性离线回放把现行为锁死:C1–C5 每个搬移 PR 直接复用本 harness 验证"拆分前后输出 byte-stable"。

## 关键事实(规划期实测,HEAD 311325b;供数事实复核于 2026-06-12)

1. `_execute_tasks` **全注入式**(L3792:`client/exa_client/extractor/structured_registry` 均为参数),现有测试已用本地 fake 调它(`tests/test_stage2_structured_integration.py`、`tests/test_stage2_unified.py` L4082+ 有接口契约范例:Tavily fake 需 `async search(**kw)`/`async extract(...)`;DeepSeek fake 需 `async extract(snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None)`)。
2. CLI 支持 `--resume-from-task-file`(喂固定任务集,跳过规划扫描)及显式 `--output/--websearch-results/--task-file/--task-log/--gap-monitor` 路径——main 级回放可全程指向 tmp 目录。
3. main() 在 L7178/L7211 构造 `AsyncTavilyClient`/`DeepSeekExtractionAgent`(模块顶层导入名),`build_default_registry` 已有 monkeypatch 先例(test_stage2_structured_integration L585)——三个 monkeypatch 锚点齐全。
4. **录制数据按 run 取材;`result_type` 是 oracle**:`data/runs/<DATE>/websearch_results/*.json` 每文件含 `task`(完整上下文,实测 40+ 字段含 `required_output_fields/trigger_reason/force_refresh/query_families` 等驱动 gate 的字段)、`raw_results`(搜索原始返回)、`extraction`(抽取输出)、`result_type`——回放后逐任务断言 `result_type`/`extraction` 与录制一致。
5. **`use_queue` 默认 True**(argparse L6891),main() 默认走 asyncio.Queue 并发消费(concurrency 3)→ `websearch_results` 列表**完成顺序非确定**。`_execute_tasks` 直调默认 `use_queue=False`(L3808)为串行。

## 供数 run 选型(2026-06-12 实测,21 个 per-task run 全扫)

- **20260522 弃用**:退化 run,仅 4 文件 / 2 指标(northbound、southbound)/ 全 `skipped_existing`,零真实链路,作 oracle 几乎无价值。
- **无单一 run 同含 4 链路**,分两个时代:
  - 结构化时代(20260525+):有 `structured_success`+`manual_required`+`skipped_existing`,但 `search_success≈0`(结构化优先短路搜索);
  - 搜索时代(20260424/20260521):有真实 `search_success`,但 `structured_success=0`。
- **选型**:主供数 **20260527**(`structured_success 13 / manual_required 3 / skipped_existing 2`,全 18 指标);从 **20260424** 借 **1 条 `search_success` 记录**补搜索链路。回放时 fake registry 对借入的搜索指标返回"无 provider",逼现行代码走搜索链路,由搜索 fake 回放借入记录的 `raw_results`+`extraction` → `search_success`。

## 架构:两层回放

**Level 1 — 链路特征化(`_execute_tasks` 级)**:夹具任务集为**真实录制任务**(20260527 全量 + 借入搜索任务),覆盖四条 result_type:结构化命中、搜索命中、manual_required、skipped_existing;另指定 1 个结构化指标令 fake registry behavior=`parse_error`,演示"结构化解析失败→回退搜索/manual"。fake 层从录制供数,断言每任务 `result_type/manual_reason/写回字段` 与 golden 一致。直调默认串行(`use_queue=False`),顺序确定。

**Level 2 — 端到端(main() 级)**:monkeypatch 三锚点(`stage2.AsyncTavilyClient`/`stage2.DeepSeekExtractionAgent`/`stage2.build_default_registry`)+ `--resume-from-task-file` + **`--no-use-queue`**(强制串行,消除并发顺序抖动)+ deepseek 并发 1,跑完整 main,断言:
- `market_data_stage2.json` 与 golden byte-stable(易变字段归一化后);
- summary 关键指标相等:`stage2_effective_hit_rate`、`task_structured_success`、`task_search_success/failed`、`manual_reason_breakdown`;
- 录制任务的 `result_type`/`extraction.value/source_url` 与录制完全一致(oracle)。

**Golden 管理**:`STAGE2_REPLAY_UPDATE_GOLDEN=1` 重新生成。进入 golden 前先用 `sort_results()` 对 `websearch_results` 等结果列表按 `task_id/indicator_key` 排序(消除列表顺序抖动);`normalize()` 只剔除 `VOLATILE_FIELDS` 并稳定 dict 键序,不重排普通业务列表。`VOLATILE_FIELDS` 内容由"连跑两次 capture 对 diff"实证得出,每项须注释来由,不许凭感觉加。

## 范围与产物

- 新增:`tests/fixtures/stage2_replay/`(`recorded/*.json` 取自 20260527 + 借入搜索记录、`tasks.jsonl`(从录制 `task` 派生)、`market_data_input.json`、`structured_responses.json`(从结构化录制派生)、`golden/`、`_build_fixtures.py`)+ `tests/test_stage2_replay_harness.py`。
- 构建期守卫:载入所选记录时,结构化记录若缺可重建 `StructuredResult` 的字段(`source_url/source_tier/payload`)即 **fail loud**;四条 result_type 若任一不可达即 **fail loud**。
- 进默认 `pytest -q`(全离线、秒级)。
- **不改任何现有源码/测试**;golden 锁的是"当前代码对既定夹具的输出"(锁行为,非锁正确性),这正是拆分回归所需。

## 验收

1. 同一夹具连跑两次,产物 byte-identical(归一化后);
2. 录制任务回放 oracle 全中(`result_type` 与 `extraction.value/source_url`);
3. `pytest -q` 全绿且新增用例被默认收集;
4. 四链路覆盖确认:summary/outcome 中 `structured_success ≥ 1` 且 `search_success ≥ 1` 且 `manual_required ≥ 1` 且 `skipped_existing ≥ 1`。

## 风险

| 风险 | 缓解 |
|---|---|
| fake 接口与真实 client 契约漂移 | 接口照抄现有测试锚点(test_stage2_unified L4082+);Level-2 oracle 断言兜底 |
| 归一化清单过宽掩盖真实回归 | 先按 `task_id` 排序列表;每个 VOLATILE 字段必须注释实证来由;评审逐项核 |
| 选用 run 链路覆盖不足 | 主用 20260527 全 18 指标 + 借搜索记录;构建期守卫断言四 result_type 均可达,否则 fail loud |
| 结构化记录不可回放 | 构建期断言结构化记录含 `source_url/source_tier/payload`,缺则 fail loud,换记录/run |
| main 并发致顺序抖动 | Level-2 强制 `--no-use-queue` + deepseek 并发 1;结果列表进入 golden 前用 `sort_results()` 按 `task_id/indicator_key` 排序 |
| 与批次 B 并行的合并次序 | 零文件交叠;后合入方 rebase 即可 |
