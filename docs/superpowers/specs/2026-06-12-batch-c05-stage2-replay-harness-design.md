# 批次 C-0.5:Stage2 replay harness — 设计文档

> Spec for the 2026-06 refactor, batch C-0.5(REFACTOR_PLAN §6.0)。批次 C 任何搬移开始前的硬前置。
> Status: 2026-06-12 设计定稿。**纯新增**(夹具 + 测试),不改任何现有代码,零行为风险;与批次 B 零文件交叠,可并行执行。

## 目的

在拆分 `stage2_unified_enhancer.py`(7077 行)之前,用确定性离线回放把现行为锁死:C1–C5 每个搬移 PR 直接复用本 harness 验证"拆分前后输出 byte-stable"。

## 关键事实(规划期实测,HEAD 311325b)

1. `_execute_tasks` **全注入式**(L3792:`client/exa_client/extractor/structured_registry` 均为参数),现有测试已用本地 fake 调它(`tests/test_stage2_structured_integration.py`、`tests/test_stage2_unified.py` L4082+ 有接口契约范例:Tavily fake 需 `async search(**kw)`/`async extract(...)`;DeepSeek fake 需 `async extract(snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None)`)。
2. CLI 支持 `--resume-from-task-file`(喂固定任务集,跳过规划扫描)及显式 `--output/--websearch-results/--task-file/--task-log/--gap-monitor` 路径——main 级回放可全程指向 tmp 目录。
3. main() 在 L7178/L7211 构造 `AsyncTavilyClient`/`DeepSeekExtractionAgent`(模块顶层导入名),`build_default_registry` 已有 monkeypatch 先例(test_stage2_structured_integration L585)——三个 monkeypatch 锚点齐全。
4. **录制数据现成且自带 oracle**:`data/runs/20260522/websearch_results/*.json` 每文件含 `task`(完整上下文+query 候选)、`raw_results`(搜索原始返回)、`extraction`(DeepSeek 输出)、`result_type`——回放后逐任务断言 `result_type`/`extraction` 与录制一致。

## 架构:两层回放

**Level 1 — 链路特征化(`_execute_tasks` 级)**:fixture 任务集(录制的 4 个搜索任务 + 手工构造的结构化任务:structured 命中、fund_flow gate 阻断、structured 解析失败回退搜索、无录制→manual_required),fake 层从夹具供数,断言每任务 `result_type/manual_reason/写回字段` 与 golden 一致。

**Level 2 — 端到端(main() 级)**:monkeypatch 三锚点(`stage2.AsyncTavilyClient`/`stage2.DeepSeekExtractionAgent`/`stage2.build_default_registry`)+ `--resume-from-task-file` 跑完整 main,断言:
- `market_data_stage2.json` 与 golden byte-stable(易变字段归一化后);
- summary 关键指标相等:`stage2_effective_hit_rate`、`task_structured_success`、`manual_reason_breakdown`、`task_search_success/failed`;
- 4 个录制任务的 `result_type`/`extraction.value/source_url` 与录制完全一致(oracle)。

**Golden 管理**:`STAGE2_REPLAY_UPDATE_GOLDEN=1` 重新生成;易变字段(时间戳、elapsed/latency、uuid task_id 等)进显式 `VOLATILE_FIELDS` 归一化清单——清单内容由"连跑两次 capture 对 diff"实证得出,每项须注释来由,不许凭感觉加。

## 范围与产物

- 新增:`tests/fixtures/stage2_replay/`(`tasks.jsonl`、`market_data_input.json`、`recorded/*.json`、`structured_responses.json`、`golden/`)+ `tests/test_stage2_replay_harness.py`。
- 进默认 `pytest -q`(全离线、秒级)。
- **不改任何现有源码/测试**;不追求复刻 20260522 全量生产 run(结构化源无网络录制),golden 锁的是"当前代码对既定夹具的输出",这正是拆分回归所需。

## 验收

1. 同一夹具连跑两次,产物 byte-identical(归一化后);
2. 4 个录制任务回放 oracle 全中;
3. `pytest -q` 全绿且新增用例被默认收集;
4. 双链路覆盖确认:summary 中 `task_structured_success ≥ 1` 且 `task_search_success ≥ 1` 且 `manual_required ≥ 1`。

## 风险

| 风险 | 缓解 |
|---|---|
| fake 接口与真实 client 契约漂移 | 接口照抄现有测试锚点(test_stage2_unified L4082+);Level-2 oracle 断言兜底 |
| 归一化清单过宽掩盖真实回归 | 每个 VOLATILE 字段必须注释实证来由;评审逐项核 |
| 与批次 B 并行的合并次序 | 零文件交叠;后合入方 rebase 即可 |
