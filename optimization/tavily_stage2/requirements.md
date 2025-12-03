# Stage2 命中率与 Tavily 成本优化需求（2025-12-03）

## 目标
- 命中率：将 Stage2 任务成功率从最近平均 ~42% 提升到 ≥80%，资金流/利率/商品类任务人工缺口占比 <10%。
- 成本：单次 Stage2 总 Tavily 请求数压缩 ≥30%，峰值延迟下降（平均 elapsed_ms 下降 20%）。

## 范围
- 触达模块：`scripts/stage2_unified_enhancer.py`、`src/datasource/adapters/tavily_client.py`、`src/datasource/config/search_profiles.py`、LC 管道（如适用）。
- 任务类型优先级：资金流 > 汇率/商品/利率 > 指数/宏观。

## 需求条目
1) **Tavily 参数增强**：search 支持 `language`, `topic`, `time_range`, `max_results`, `chunks_per_source`, `auto_parameters`；按指标类型自动填充默认值（实时类 language=chinese, topic=news, time_range=day, max_results<=10）。
2) **相关性提升**：对搜索结果先行 `score>=0.5` 过滤，空则回退全量；计数写入日志。
3) **二步抽取**：为高噪声任务启用 search→extract 流程；extract 可选 `advanced`，仅 top-N URL，必要时 `include_raw_content`（限 top1）。
4) **深度/范围策略**：资金流/汇率/商品/债券默认 `search_depth=advanced`；宏观/低时效指标仍用 basic。
5) **资金流兜底**：降级路径保留零值检测；extract/raw_content 辅助识别流入/流出和“亿”单位，note 标注来源与异常。
6) **配置化**：在 `SEARCH_PROFILES` 增加新参数字段；运行时根据 profile 选择参数，避免硬编码。
7) **缓存与去重**：确保 tavily cache key 覆盖新参数；summary 输出 cache_hit_rate，避免重复请求。
8) **观测与日志**：日志/summary 新增字段：`score_filtered_drop`、`extract_calls`、各类型成功率、平均/95P 延迟。

## 非目标（本迭代不做）
- 改动 Stage1/Stage3 逻辑。
- 引入新外部数据源或修改 MCP 流程。

## 成功指标与验收
- 最近两次回归（同一日数据）成功率≥80%，资金流三项不再“异常零值-需核查”。
- Tavily 请求量（search+extract）较 12-03 基线减少 ≥30%。
- 日志中无缺失 query/domains/unit/issuer 警告；cache_hit_rate>30%。

## 里程碑
- M1：参数透传与 profile 扩充完毕，日志字段落地（+1 天）。
- M2：二步抽取/score 过滤上线，资金流兜底完成（+2 天）。
- M3：回归对比 12-02/12-03 基线，提交指标报告（+3 天）。


## 新增需求（队列 & 提示词优化）
9) **抽取队列化改造**：搜索完成后将待抽取任务写入消息队列（轻量实现可用 asyncio 队列或本地持久化队列），独立消费者执行 DeepSeek/Tavily extract：
   - 并发与速率：可配置最大并发；出现超时/429 时自动退避。
   - 重试策略：超时/网络错误重试 N 次；超限入死信队列并记录 task_id。
   - 状态回写：task_log / gap_monitor 区分“排队/重试中”与“真正失败”，避免过早计入失败。
   - 观测：记录队列长度、重试次数、死信计数。

10) **提示词（query）优化**：按 Tavily Best Practices 收敛查询以提高相关性、减少调用：
    - 单一意图、长度<400 字符；实时类明确时间窗（"最新"、"近5日"）、参数 `topic=news`、`time_range=day`。
    - 精简 `include_domains` 至 2–4 个权威站点；中文任务统一 `language=chinese`。
    - 在 query 中写出单位/发布机构关键词（如 “亿元 上交所/港交所”、“% 央行/中债”）。
    - 高噪声指标使用 `search_depth=advanced` 替代堆砌关键词；复杂场景走“search→extract”两步。
    - 避免在查询里放“请提取/LLM 指令”，保持实体+指标+时间窗的描述。


11) **模型选择**：抽取默认模型由 `deepseek-chat` 切换为 `deepseek-reasoner`（V3.2，思考模式/think 模式），通过 CLI `--deepseek-model` 默认值与配置文件统一；本迭代不使用 Speciale 等实验模型。

12) **去除 MCP 依赖**：Stage2 默认不再使用 MCP 路径。资金流/外汇任务统一走 Tavily（或 tavily→手工）流程：
    - CLI 默认 `--fund-flow-backend tavily`，`hybrid` 仅表示 Tavily 失败后人工补数，不再有 MCP 分支。
    - 移除 `_execute_tasks` 中 `backend=mcp/hybrid` 的跳过逻辑，资金流任务直接搜索/抽取/校验。
    - 日志与 gap_monitor 不再写入 “backend=mcp，等待外部MCP注入”，改为真实失败/低置信度标记。
    - 文档与帮助信息同步更新，明确当前无内置 MCP 数据源。

13) **DeepSeek 超时与重试优化**：将抽取超时默认由 8s 提升至 10–12s（V3.2 think 模式），并增加一次轻量重试（仅超时/网络错误触发）；不再为 Speciale 单独配置。

14) **CLI 与默认值一致性**：更新 Stage2 CLI 帮助与 README/AGENTS：fund_flow_backend=tavily，deepseek-reasoner，deepseek-timeout=10–12s，max_results/topic/language/search_depth 新默认写明。

15) **健康检查脚本**：新增快速自检（密钥、代理、缓存路径可写、Tavily/DeepSeek ping），在运行 Stage2 前提醒缺失配置。

16) **缓存策略**：cache key 覆盖新增参数；TTL 建议 6–12h；启动时清理过期；summary 输出 cache_hit_rate。

17) **日志可观测性**：日志/summary 增加 DeepSeek timeout_count/retry_count，per-type 成功率（fund_flow/forex/commodities/bonds/macro），95P 延迟。

18) **Search Profiles 审查**：提示词长度<400，补全时间窗/单位/发行人/域名；实时类明确“最新/近5日”。

19) **LC 分支同步**：LangChain 抽取路径也应用 score 过滤、参数透传、二步抽取、超时/重试策略。

20) **并发/速率上限**：配置 Tavily max_concurrency、DeepSeek semaphore、队列消费者数，防止配额/超额。

21) **回归对比自动化**：提供脚本对比新运行与 20251202/20251203 基线的成功率、请求量、延迟、人工缺口，输出表格/JSON。

22) **资金流零值兜底**: 若 Tavily 返回 0 且无方向，直接标人工，不写入 market_data，避免污染；note 说明“零值+方向缺失”。

23) **队列实现策略**：采用内置 `asyncio.Queue` 轻量生产者/消费者，不引入外部 MQ。理由：Stage2 任务量小（几十条）、批处理短、部署简单；外部 MQ 仅在跨机分布式或千级任务时再评估。

24) **gap_monitor 精简**：仅记录真实失败/低置信度任务；移除 MCP/占位文案；资金流零值无方向直接标人工并写明原因。

25) **Tavily extract 兼容**：对 422 进行容错（仅传必需字段、失败回退 search-only、note 标记 `tavily_extract_422`）；资金流/汇率/商品按需 `extract_depth=advanced`、`include_raw_content`=True(top1)。

26) **宏观/低时效 profile 收紧**：宏观/货币指标使用 time_range=year/month、max_results<=6，必要时设置 max_age_days；保持单位/issuer 以提升校验。

27) **回归对比脚本**：新增 `scripts/compare_stage2_runs.py`，对比两次 Stage2 日志（成功率、cache_hit、score_filtered_drop、timeout/retry、tavily_extract_calls、per-type 成功率、延迟）。

28) **文档同步**：更新 README/AGENTS/SCRIPTS 中的 Stage2 默认参数与运行示例（fund_flow_backend=tavily、deepseek-reasoner、timeout=10s、max_results/topic/language/search_depth），注明需 `PYTHONPATH=./src`。
