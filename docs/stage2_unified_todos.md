# Stage 2 Unified TODOs（Tavily 优先版，2025-11-20）

## 已完成
- [x] Tavily 异步客户端、DeepSeek 抽取代理落地；search profiles 为大宗/汇率/债券/宏观/基金流向补齐 query+可信域名+unit+issuer。
- [x] 任务规划器合并 Stage1 `metadata.missing_items`，去重后写 JSONL；Stage2 输出统一覆盖 `data/market_data.json`，带 `.bak` 与时间戳备份。
- [x] Stage2 校验：单位/域名白名单、资金流“亿”单位与方向调整；缺口写 `gap_monitor`，`metadata.ai_websearch_enhanced` 标记；Stage3/4 在入口强制检查 gap_empty。
- [x] 搜索缓存、代理参数、重试/任务过滤、分任务 websearch_results、任务日志 request_id/elapsed_ms。
- [x] 单元 + 集成基础测试通过（pytest）；本地 Python 缺失时需系统解释器运行。

## 待处理（高优先）
- [ ] **资金流向数据落盘**：当前 northbound/southbound/etf 仍 manual_required；用 Tavily 补价或人工填入，重跑 Stage2 清空 gap_monitor。
- [ ] **发布机构强校验**：新增 issuer_match 校验后需回归测试，确保宏观/利率结果在 snippets 中包含发布机构或记为 manual_required。
- [ ] **搜索告警清零**：再跑 `stage2_unified_enhancer --execute-search`，确认无 “缺少 query/域名/issuer” 警告；若有，补充 `config/search_profiles.py`。
- [ ] **HTTP/代理健壮性测试**：补 httpx mock 覆盖超时/403/代理失效，验证 retry + manual_required 落盘；完善运行手册的代理与密钥加载章节。
- [ ] **报告前检查**：在 Stage3 前确认 `reports/gap_monitor.json` 空、`metadata.ai_websearch_enhanced=true`，必要时手动填补并备份 `data/market_data.json`。
