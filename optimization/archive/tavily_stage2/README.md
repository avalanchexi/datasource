# Tavily Stage2 优化需求与任务拆解（2025-12-03）

## 背景
- 近期 Stage2 Tavily 命中率在 60~76%，资金流/利率/商品存在较多 manual_required 与“异常零值-需核查”。
- Tavily 官方最佳实践建议：score 过滤、二步 search→extract、language/topic/time_range 收紧、advanced 搜索深度。

## 需求列表
1. 支持 Tavily 语言/主题/结果数等参数：`language`, `topic`, `max_results`, `auto_parameters`, `chunks_per_source`。
2. 按指标类型默认化参数：
   - 实时类（fund_flow/forex/commodities/bonds/indices）：`topic=news`, `time_range=day`, `max_results<=10`, `language=chinese`。
   - 复杂/高精度任务：`search_depth=advanced`。
3. 结果相关性提升：`score>=0.5` 过滤，空则回退原片段。
4. 二步抽取试点：search 取 top URLs → 调 Tavily `extract`（可选 advanced），再送本地抽取/regex。
5. 资金流兜底：二步抽取 + `include_raw_content`(限 top1) + note 标记；仍保留零值异常标记。
6. 配置化：在 `search_profiles` 增加新参数字段，避免硬编码。
7. 观测：日志补充 score 过滤数量、extract 调用次数、命中率统计，便于对比。

## 任务拆解 TODOs
- [ ] 在 `AsyncTavilyClient` 增加可选参数并透传（search & extract）。
- [ ] 在 `_execute_tasks`/LC 分支传入 language/topic/max_results/search_depth 按类型路由。
- [ ] 添加 `score>=0.5` 过滤与回退逻辑；日志计数。
- [ ] 实现 Tavily `extract` 调用封装；为高噪声任务启用二步流程（开关可控）。
- [ ] 更新 `SEARCH_PROFILES` 支持新字段并填充实时类默认参数。
- [ ] 资金流 special fallback：top1 raw_content + note 标记 + zero-check 保持。
- [ ] 日志与 summary 输出新增：score_drop、extract_calls、per-type 成功率。
- [ ] 回归：跑 `stage2_unified_enhancer` 对比 12-02/12-03 基线，记录命中率与人工缺口变化。

## 参考链接
- Tavily Best Practices (Search & Extract)
- 当前运行日志：`logs/stage2_unified_log_20251202.json`, `logs/stage2_unified_log_20251203.json`

