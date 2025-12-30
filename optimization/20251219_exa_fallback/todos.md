# Exa 兜底接入 TODO（2025-12-19）

## 0. 预检与准备
- [x] 确认 `.env` 已配置 `EXA_API_KEY`（不要提交到仓库）
- [x] 明确 Exa SDK 版本（exa-py）并评估是否需锁定版本（当前不锁定）
- [x] 更新 `requirements.txt`（新增 exa-py）

## 1. 新增 Exa SDK 适配器
- [x] 新增 `src/datasource/adapters/exa_client.py`
- [x] 实现异步包装（`asyncio.to_thread` 或线程池）以适配现有 async pipeline
- [x] 统一输出 Tavily 兼容片段结构（url/snippet/content/score）
- [x] 处理空结果/异常，输出规范化错误（便于上层判断 `exa_empty/exa_error`）

## 2. Stage2 兜底逻辑
- [x] 在 `scripts/stage2_unified_enhancer.py` 中接入 Exa fallback
- [x] 仅对 Tavily 失败/空结果/配额类错误触发 Exa
- [x] fund_flow 指标保持 MCP/manual，不触发 Exa
- [x] 记录 `search_backend=exa`，并在 `websearch_results.note` 标记 `exa_fallback/exa_empty/exa_error`

## 3. 参数映射与兼容
- [x] `preferred_domains` → Exa `include_domains`
- [x] `max_results` → Exa `num_results`
- [x] `max_age_days` → `start_published_date`（必要时退回 `start_crawl_date`）
- [x] 数值型任务使用 `type="keyword"`（商品/汇率/债券/指数）
- [x] 不改 `search_profiles.py` 字段结构

## 4. 日志与审计
- [x] `task_log`/`websearch_results` 保持现有 schema
- [x] `raw_results` 保留 Exa 映射后的前 3 条片段
- [x] 对 Exa 兜底成功/失败统计计数（可选）

## 5. 测试与验证
- [x] 单测：Exa 结果映射为 Tavily 片段结构
- [x] 集成：模拟 Tavily 失败 → Exa 成功
- [x] 回归：fund_flow 仍不走 Exa；Stage3/报告无结构变更

## 6. 文档同步
- [x] `optimization/20251219_exa_fallback/需求.md` 更新完毕
- [x] 在 `README` 或 `AGENTS.md` 补充 Exa 兜底说明（如需）

## 7. 全链路回归（2025-12-19）
- [x] 运行 Stage1/Stage2/Stage2.5 注入基础数据
- [x] 补齐 BCOM/GSG/CN10Y_CDB（来源已记录）
- [x] 南向 5D/120D 用东财接口本地计算并注入（来源已记录）
- [x] ETF 5D/120D 用东财接口本地计算并注入（来源已记录）
- [x] 补齐 7天逆回购/MLF 利率（来源已记录）
- [x] 北向 5D/120D 采用东财历史口径估算并注入（来源已记录）
- [x] Stage3 & Report 全链路回归（2025-12-19 背景扫描120日报告）
