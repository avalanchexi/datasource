# Stage 2 一体化重构方案（Tavily + DeepSeek）

_撰写日期：2025-11-19_

## 1. 背景动因
- Stage 3 依赖完整的宏观与货币指标（PPI、CPI、PMI+新订单、GDP、工业增加值、TSF、M2、M1、DR007、RRR、逆回购）以及大宗商品、利率、资金流向等行情，但当前 Stage 2 仍可能把 None/0/7.13 占位透传到 market_data_stage2.json（详见 docs/pring优化需求.md:4-29）。
- 旧版 Stage 2/Stage 2a 采用分离式补数：Stage 2a 手工补宏观、Stage 2 再补行情，既重复又易错，而且强依赖 MCP 专用 WebSearch，导致 M1、PMI 新订单等关键字段长期挂空。
- 亟需一个可以在 MCP 之外独立运行的统一 Stage 2，一次完成所有缺口的搜索、解析、写回，并继续遵守“基金流向只能通过 MCP WebSearch”这一合规要求。

## 2. 目标与非目标
### 目标
1. **Stage 2 一体化**：取消 Stage 2a，改为单一 Stage 2 Pipeline，内部划分 Phase-E（Essential）与 Phase-A（Assets）两个阶段，保证只跑一次 CLI 即可填满 Stage 3 所需字段。
2. **搜索栈替换**：以 Tavily Search + DeepSeek 抽取替代原 MCP WebSearch 逻辑，提供统一的查询规划、并发控制与结果缓存。
3. **自动补数机制**：Stage 1 或 Stage 2 标记缺口时自动生成结构化任务，实时触发 Tavily 搜索直至拿到真实数据。
4. **可追溯性**：所有字段必须包含 source、
ote、stage_task_id；搜索—解析—写入全过程需记录 JSON 日志便于审计。

### 非目标
- 不修改 Stage 1 采集逻辑（仍由其生成占位与 missing_items）。
- 不改变 Stage 3/Stage 4 的计算、渲染流程，只保证输入真实可靠。
- 不触碰基金流向脚本 scripts/utility/background_scan_120d_generator.py 的 MCP 专属通道。

## 3. Stage 3 需求对照表
| Stage 3 层级 | 必备字段 | Stage 2 一体化职责 | 备注 |
| --- | --- | --- | --- |
| 库存周期 | ppi, pmi_headline, pmi_new_orders, industrial_output, gdp, di, manufacturing_sales | Phase-E 填满并校验同比/环比；若 TuShare 已有高置信值可直接沿用，缺口转 Tavily 任务 | di 无本地源，必须 WebSearch |
| 货币周期 | m1, m2, m1_m2_spread, 	sf, dr007, 
rr, 
everse_repo, policy_bias | Phase-E 输出基础值，Phase-A 计算剪刀差、DR007 均值等派生字段 | 任一字段为 0/None 即中止 |
| 价格信号 | cpi, ppi, commodity_trend | Phase-E 校验 CPI/PPI，Phase-A 输出大宗趋势说明 | CPI/PPI 优先 TuShare，失败再回退 Tavily |
| 债券与利率 | CN10Y, CN10Y_CDB, UST10Y, CN2Y | Phase-A 使用 Tavily+DeepSeek 获取收益率、bp 变动、发布日期 | 获取失败时写 gap_monitor 并报错 |
| 商品 | GC=F, CL=F, BZ=F, HG=F, BCOM, GSG | Phase-A 必须填入最新价格/涨跌，彻底替换 7.13 占位 | Yahoo/MCP 可作为辅助 fallback |
| 资金流向 | 北向/南向/ETF/融资融券 | Phase-A 继续调用 MCP WebSearch；Tavily 仅做异常复核 | 必须标注 “MCP WebSearch实时获取” |
| 元数据 | metadata.ai_websearch_enhanced, stage2_notes, gap_monitor, stage_task_log | Stage 2 输出阶段标志、缺口清单、任务日志 | Stage 3 若无标志则拒绝执行 |

## 4. 一体化架构
`
Stage 1 JSON（含占位 + missing_items）
   ↓
Stage 2 Unified Pipeline
   Phase-E（Essential Macro & Monetary）
       · 占位扫描器
       · Tavily 查询规划器
       · Async Tavily Client + DeepSeek 抽取
       · 校验/落盘（stage2_phase_e.json）
   Phase-A（Assets, Fund Flow & Metadata）
       · 任务调度器（债券/商品/资金流向/派生字段）
       · Tavily + DeepSeek / MCP Fund Flow
       · Gap Monitor + Notes + Cache
   ↓
market_data_stage2.json + stage2_unified_log.json + reports/search_tasks_stage2.jsonl
`

## 5. 统一机制设计
### 5.1 占位扫描与自动任务
- _scan_stage2_placeholders() 读取 Stage 1 的 missing_items、字段 stage 标签与上一轮 stage_task_log，生成 SearchTaskContract（含 	ask_id、stage_phase、indicator_key、query_template_id、preferred_domains、
etry_count、source_hint）。
- 任务以 JSONL 写入 
eports/search_tasks_stage2.jsonl，CLI 默认自动消费，并支持 --task-file、--resume 以人工重跑。
- Stage 1 若新增缺口，Stage 2 在 Phase-E 前重扫一次任务表，实现“遇到 Stage 需获取的数据即刻搜索”。

### 5.2 Tavily/DeepSeek 功能单元设计
- **任务构建**：Stage 2 的 SearchTaskPlanner 读取 Stage 1 missing_items，并按指标类别生成 SearchTaskContract 队列（区分 Phase-E 与 Phase-A）。
- **TavilyFetcherUnit**：针对每个任务拼装 query/topic/search_depth/include_domains/time_range 参数，通过 AsyncTavilyClient 并发请求可信站点，默认使用信号量 4 控制并发，可由 CLI 覆盖。
- **DeepSeekExtractionUnit**：接收 Tavily 结果，结合 Trusted Source Profile 生成提示词并调用 DeepSeek 函数接口，解析 
alue/unit/period/source_url/confidence，低置信度任务会附带 
ollow_up_query 触发二次搜索。
- **结果落盘**：ResultAssembler 将解析后的字段写回内存模型，同时把成功与失败记录序列化到 websearch_results_auto.json、stage_task_log.jsonl；若任务仍失败则更新 missing_items 的 
ote 并标记 status=pending_manual。
- **并发写入**：所有落盘操作都通过 syncio.Queue 排队，保证并发抓取与 JSON 写入互不阻塞；完成后 Stage 2 会生成带来源说明的 stage2_notes 供 Stage 3/4 使用。

### 5.3 Phase-E（宏观&货币）
1. 依任务表构建 Tavily 查询（	opic=news/economy、	ime_range=month），使用 AsyncTavilyClient 并发请求并通过信号量限流。
2. 将结果传入 DeepSeekExtractionAgent，以函数调用形式输出 
alue、unit、period、source_url、confidence。
3. 对数值执行区间、同比校验，合格后写入 market_data.macro_indicators/monetary_policy，并记录 stage_task_id 与 source。
4. 失败任务自动重试（默认 2 次），仍失败则记入 missing_items，状态设为 pending_manual。
5. Phase-E 完成后落盘 stage2_phase_e_snapshot.json 并写 metadata.phase_e_passed=true。

### 5.4 Phase-A（行情&资金流向&元数据）
1. 延续 Phase-E 结果并加载剩余任务，优先处理 category in {bonds, commodities}。
2. 债券/商品统一使用 	opic=finance、search_depth=advanced、include_raw_content=true，DeepSeek 抽取 current_value、d1_change、d5_trend、date；必要时调用 Yahoo/MCP WebFetch 辅助。
3. 资金流向保持 MCP 专属：调用 BackgroundScan120DGeneratorFixed 原有方法；如结果为 0/None，自动生成 Tavily 校验任务并标记 source='异常零值-需核查'。
4. Phase-A 负责派生字段（m1_m2_spread、dr007_5d_avg、commodity_trend 等）与 stage2_notes 汇总。
5. 所有任务完成后输出最终 market_data_stage2.json 并写 metadata.ai_websearch_enhanced=true、metadata.stage2_completed_at。

### 5.5 缓存与回溯
- 维护 	avily_cache.sqlite（键：indicator_key+period）；CLI 暴露 --cache-ttl、--no-cache，命中时记 cache_hit=true。
- stage_task_log.jsonl 记录任务输入、输出、重试情况，可用于审计与回放。

## 6. Tavily + DeepSeek 集成要点
### 6.1 API & 认证
- 所有搜索调用 POST https://api.tavily.com/search，请求头 Authorization: Bearer tvly-***；可配置 query、	opic、search_depth、max_results、include_raw_content、	ime_range、country、include_domains、exclude_domains 等。
- 记录 
equest_id、
esponse_time 到 stage_task_log，方便追溯。

### 6.2 异步执行
- AsyncTavilyClient 维护全局 iohttp session，通过 syncio.gather(..., return_exceptions=True) 并发请求，syncio.Semaphore 控制并发（默认 4）；429/5xx 触发指数退避并降低并发。

### 6.3 DeepSeek 抽取
- DeepSeekExtractionAgent 使用函数调用模板，输出 {value, unit, period, source_url, confidence, raw_snippet}，低置信度时附带 
ollow_up_query。

## 7. 指标 → 可信数据源 → Tavily 参数映射
| 指标 | 首选数据口径 | 备选/辅助口径 | Tavily 建议参数 | 说明 |
| --- | --- | --- | --- | --- |
| 工业增加值 (industrial) | 国家统计局《工业生产主要数据》 | 财新、证券时报对官方稿件的逐字转载 | query="中国 工业增加值 同比 最新", 	opic="news", search_depth="basic", 	ime_range="month", include_domains=["stats.gov.cn","cs.com.cn"], include_raw_content=true | 解析“同比增长 X%”句式，DeepSeek 校验区间 [-10, 20] |
| 工业企业营收 (industrial_sales) | 国家统计局《规模以上工业企业效益情况》 | 人民日报、新华社财经稿 | query="规模以上 工业企业 营业收入 同比", 	opic="news", search_depth="advanced", 	ime_range="quarter", include_domains=["stats.gov.cn","people.com.cn"], include_raw_content=true | 原文常含表格，需抓 raw_content |
| BDI 指数 (di) | Baltic Exchange 官方日报 | Investing.com、TradingEconomics、东方财富全球行情 | query="BDI 指数 最新 点位", 	opic="finance", search_depth="advanced", 	ime_range="week", include_domains=["balticexchange.com","investing.com","eastmoney.com"], max_results=4 | 结果需包含日期+点位，允许多源验证 |
| 存款准备金率 (
rr) | 中国人民银行官网公告 | 新华社、央视新闻 | query="央行 存款准备金率 调整 日期", 	opic="news", 	ime_range="3month", include_domains=["pbc.gov.cn","xinhuanet.com","gov.cn"], include_raw_content=true | 解析“上/下调 X 个百分点”描述 |
| 7 天逆回购 (
everse_repo) | 央行公开市场操作公告 | 上海证券报、人民日报 | query="公开市场 7天 逆回购 利率", 	opic="news", 	ime_range="month", include_domains=["pbc.gov.cn","people.com.cn","cnstock.com"] | 解析“操作利率为 X%”句式 |
| MLF 利率 (mlf) | 央行官网/国新办稿 | 新华社财经 | query="MLF 1年期 利率 最新", 	opic="news", search_depth="advanced", 	ime_range="3month", include_domains=["pbc.gov.cn","news.cn"], include_raw_content=true | 公告多为 PDF，需 raw_content |
| PMI 新订单 (pmi_new_orders) | 国家统计局 PMI 月报 | 财新 PMI | query="PMI 新订单 指数 最新", 	opic="news", 	ime_range="month", include_domains=["stats.gov.cn","caixin.com"], max_results=5 | TuShare 常缺该分项 |
| GDP (gdp) | 国家统计局季度 GDP 公告 | 央视财经、经济参考报 | query="中国 GDP 同比 最新", 	opic="news", 	ime_range="quarter", include_domains=["stats.gov.cn","cctv.com"], include_raw_content=true | 若 TuShare 已返回则任务跳过 |
| PMI 生产 (pmi_production) | 国家统计局 PMI 报告 | 财新 PMI | 同 PMI 新订单 | --- |
| DR007（兜底） | TuShare repo_daily（首选） | 中国外汇交易中心公告 | 当 TuShare 失败时：query="DR007 加权利率 最新", 	opic="finance", 	ime_range="week", include_domains=["chinabond.com.cn","cfets.com.cn"] | 需返回日度均值 |
| 北向/南向资金 | **MCP WebSearch（东方财富、同花顺）** | Tavily 仅异常复核 | query="北向资金 实时 净流入", 	opic="finance", 	ime_range="day", include_domains=["eastmoney.com","10jqka.com.cn"], max_results=3 | 仅在 MCP 得到零值时触发 |
| CN10Y 国债 | 中国债券信息网（中债登） | 东方财富债券、Investing.com | query="中国10年期国债 收益率", 	opic="finance", search_depth="advanced", include_domains=["chinabond.com.cn","eastmoney.com","investing.com"], include_raw_content=true | 输出当前收益率、bp 变化、日期 |
| CN10Y 国开债 | 中国债券信息网政策性金融债 | 东方财富 | 同上，但 query="10年期 国开债 收益率" | --- |
| 商品 GC=F/CL=F/BZ=F/HG=F | CME 官方 / Investing.com / Yahoo Finance | 东方财富全球行情 | 	opic="finance", search_depth="advanced", include_domains=["investing.com","finance.yahoo.com","eastmoney.com"], 	ime_range="day", include_raw_content=true | DeepSeek 抽取现价、日变动、5 日趋势 |
| BCOM 指数 / GSG ETF | 彭博/雅虎 | 东方财富 | query="BCOM index latest" / "GSG ETF price", 其余参数同上 | 需要美元报价 |

（表中字段可在未来通过 config/search_profiles.py 配置化；此处列出默认口径。）

## 8. 开发实施步骤
1. **构建搜索与推理基建**：在 src/datasource/adapters/ 实现 AsyncTavilyClient（认证、并发、退避、缓存统计），在 src/datasource/engines/ 实现 DeepSeekExtractionAgent（函数调用模板+字段校验），并把上述指标映射沉淀到 config/search_profiles.py。
2. **统一 Stage 2 CLI**：将 scripts/stage2_mcp_enhancer.py 升级为 stage2_unified_enhancer.py，新增 --phase/-p、--search-backend、--task-file、--cache-ttl 等参数，引入 Stage2TaskPlanner 扫描 Stage 1 missing_items 生成 SearchTaskContract，Phase-E/Phase-A 共用任务队列。
3. **接入数据写回与派生逻辑**：在增强器中落地 Tavily/DeepSeek 结果，补齐宏观/货币字段并写 stage_task_id、source、
ote；Phase-A 完成债券、商品、资金流向（调用 MCP WebSearch）及 m1_m2_spread、dr007_5d_avg、commodity_trend 等派生字段。
4. **日志、缓存与回溯**：实现 	avily_cache.sqlite 与 CacheManager，CLI 支持 --no-cache 与 TTL；统一输出 stage2_unified_log.json、stage_task_log.jsonl、gap_monitor.json，Stage 3 在入口校验 metadata.ai_websearch_enhanced 与 gap 状态。
5. **测试与灰度**：新增 	ests/test_stage2_unified_pipeline.py 等单/集成测试；通过 STAGE2_SEARCH_BACKEND 环境变量控制灰度上线，保留 MCP fallback；发布密钥轮换、失败重跑、任务审计 Runbook。

## 9. Tavily + DeepSeek 错误与质量控制
- **阈值**：当 Tavily 结果 score < 0.55 且域名不在 source_hint 白名单时自动触发二次搜索；若 3 次仍失败则把任务标记为 manual_required。
- **交叉验证**：关键宏观指标至少需要两个不同域名的证据；DeepSeek 抽取后再以正则二次校验，防止引用转载错误。
- **零值处理**：资金流向若返回 0 或 None，按照 AGENTS 规范写 source='异常零值-需核查' 与 
ote，待人工补数。

## 10. 落地路线图
（与前述目标保持一致，此处省略细节，交付节奏按 Phase-E → Phase-A → 报告更新排序。）

## 11. 测试、上线与参考资料
- 单/集成/性能测试策略同前；上线前需在灰度环境验证 metadata.ai_websearch_enhanced 标志、gap_monitor 清零以及 Stage 3/4 报告无 7.13/None。
- 参考资料：docs/pring优化需求.md、Tavily API 文档、Tavily 最佳实践、社区贴《DeepSeek R1 + Tavily Search》（2025-02）。

## 12. 公开问题解答
- **Tavily/DeepSeek 参数规范**：Stage 2 默认调用 Tavily Search 官方接口（参考 https://docs.tavily.com/documentation/api-reference/introduction ），核心参数为 `query`（必填）、`topic`（可选）、`search_depth`（basic/advanced）、`include_domains`/`exclude_domains`、`time_range` 与 `max_results`。Stage2TaskPlanner 会按 `config/search_profiles.py` 为指标赋默认 query 与可信域名；执行时 `stage2_unified_enhancer` 将 `stage_phase=assets` 的任务提升到 `search_depth=advanced`，其余为 basic。DeepSeek 抽取阶段当前使用 OpenAI 兼容 chat 接口，模型名默认为 `deepseek-chat`，如无密钥则回退 regex 抽取。
- **环境变量与密钥管理**：在 `.env` 中配置 `TAVILY_API_KEY=<your-tavily-key>`、`DEEPSEEK_API_KEY=<your-deepseek-key>`，不要将真实密钥写入仓库或报告。Stage 2 CLI（`scripts/stage2_unified_enhancer.py`）会从环境变量读取；`scripts/utility/background_scan_120d_generator.py` 按合规要求仍只使用 MCP WebSearch，不读取上述密钥。
- **任务日志字段**：Stage 2 产物 `logs/stage_task_log.jsonl` 建议至少包含 `task_id`、`indicator_key`、`stage_phase`、`search_backend`、`confidence`、`source_url`、`note`、`created_at`、`finished_at`，若 Tavily 返回 `response_id` / `request_id` 可一并记录；抽取错误时应附带 `error` 字段，便于审计与重跑。

## 13. 当前落地状态与差距（2025-11-20）
- 已落地骨架：Tavily/DeepSeek 客户端、任务规划器、统一 CLI（支持缓存、派生指标、fund_flow 零值合规标注）、基本日志与任务 JSONL。
- 实测问题：在无公网/代理环境下 Tavily 请求超时，9 个任务均未完成；stage_task_log 仅有 error 占位，gap_monitor 未清空。
- 待补关键项：代理/超时配置、重试与 manual_required 标志、request_id/耗时日志、任务级重跑 (--resume/--tasks)、fund_flow 异常提示 MCP 复跑、httpx/DeepSeek mock 测试、运行手册里的网络调试章节。
- 参考 TODO：见 `docs/stage2_debug_todos.md`（已按现状拆解可执行子任务与代码指针）。
