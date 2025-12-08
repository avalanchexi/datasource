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

    - 已对 LC 分支补充：score>=0.5 过滤、域名/新鲜度过滤、extract 422 回退、llm_hard_timeout 包装；默认禁用，需 `--allow-langchain` 才能启用。

20) **并发/速率上限**：配置 Tavily max_concurrency、DeepSeek semaphore、队列消费者数，防止配额/超额。

21) **回归对比自动化**：提供脚本对比新运行与 20251202/20251203 基线的成功率、请求量、延迟、人工缺口，输出表格/JSON。

22) **资金流零值兜底**: 若 Tavily 返回 0 且无方向，直接标人工，不写入 market_data，避免污染；note 说明“零值+方向缺失”。

23) **队列实现策略**：采用内置 `asyncio.Queue` 轻量生产者/消费者，不引入外部 MQ。理由：Stage2 任务量小（几十条）、批处理短、部署简单；外部 MQ 仅在跨机分布式或千级任务时再评估。

24) **gap_monitor 精简**：仅记录真实失败/低置信度任务；移除 MCP/占位文案；资金流零值无方向直接标人工并写明原因。

25) **Tavily extract 兼容**：对 422 进行容错（仅传必需字段、失败回退 search-only、note 标记 `tavily_extract_422`）；资金流/汇率/商品按需 `extract_depth=advanced`、`include_raw_content`=True(top1)。

26) **宏观/低时效 profile 收紧**：宏观/货币指标使用 time_range=year/month、max_results<=6，必要时设置 max_age_days；保持单位/issuer 以提升校验。

27) **回归对比脚本**：新增 `scripts/compare_stage2_runs.py`，对比两次 Stage2 日志（成功率、cache_hit、score_filtered_drop、timeout/retry、tavily_extract_calls、per-type 成功率、延迟）。

28) **文档同步**：更新 README/AGENTS/SCRIPTS 中的 Stage2 默认参数与运行示例（fund_flow_backend=tavily、deepseek-reasoner、timeout=10s、max_results/topic/language/search_depth），注明需 `PYTHONPATH=./src`。

29) **Stage2 等待时间压缩（诊断→修复→验收）**：聚焦 DeepSeek/Tavily 阶段耗时过长问题，先做可观测诊断，再实施修复并回归。
    - 诊断：收集近两次 Stage2 日志的 `avg_elapsed_ms/95p`、`timeout_count/retry_count`、`tavily_extract_calls`、`queue_dead_letters`，按任务类型拆分耗时；若日志缺 95p，先补统计。
    - 修复措施候选：减少 DeepSeek 参与度（regex/fast_mode）、限定 `deepseek_max_concurrency`、启用/调优队列并发与重试、压缩 Tavily extract（禁用或 top1+raw_content）、清空代理或验证代理可用性。
    - 验收：同日重复跑两次 Stage2，平均耗时下降 ≥20%，95p 下降 ≥15%，超时次数较基线下降 ≥50%；成功率不低于原始基线。
    - 回归输出：在 `logs/stage2_unified_log_*.json` 补充/对比延迟统计，生成一页总结（可复用 compare_stage2_runs.py）。

## 代码层面的可行优化（建议，落地需评估）
- **Tavily extract 422 兜底**：在 `tavily_client.extract` 捕获 4xx/422 时自动回退“search-only”，并在 `_execute_tasks` 将 `note` 标记 `tavily_extract_422`，避免重复调用同 URL 的 extract。
- **DeepSeek 超时硬控**：在 `_do_extract` 使用 `asyncio.wait_for` 包裹 `extractor.extract` 并尊重 CLI `--llm-hard-timeout`（当前部分路径未生效）；超时立即返回 regex_fallback，减少 30s 阻塞。
- **资金流方向判定增强**：在 `_validate_fund_flow_extraction`/regex 路径增加关键词表（流入/净买入/净流出/卖出）和数值正负修正，避免“未能识别流入/流出方向”触发人工。
- **缓存 key 扩展**：将 `time_range/topic/language/search_depth/extract_depth` 纳入 tavily cache key，避免参数变化导致缓存命中率下降或脏读。
- **跳过已有值与占位识别**：`_has_non_placeholder_value` 增加对非 0 但缺趋势字段的判定；若仅缺 `trend` 可单独补方向，不再全量 DeepSeek。
- **队列重试退避**：在 queue 消费者中对超时/429 使用指数退避（例如 0.5s,1s,2s），防止持续打爆配额。
- **日志 95P 延迟输出**：在 summary 里对 `elapsed_ms` 计算 p50/p95，便于压缩等待时间的回归对比。

- **Tavily extract 422 优化细化**：
  - 输入约束：`extract` 仅传前 1–2 条高分 URL，过滤 PDF/失效/无 content 链接；对无法解析的 URL 直接跳过 extract。
  - 失败降级：捕获 422 时立即回退 search-only，不再重试；在 `task_log`/`websearch_results` note 标记 `tavily_extract_422`，避免后续重复调用同 URL。
  - 参数收紧：默认 `extract_depth=basic`，`include_raw_content=False`；高噪声任务再显式开启 raw_content(top1)。
  - 观测与开关：summary 增加 `tavily_extract_422_count`；提供 CLI 开关 `--disable-extract` 与 `--extract-topk`（已有）组合，方便快速绕过。
  - 配额/限流退避：extract 遇 422 视作软拒绝，单独限制并发(1–2)与重试(0)，并对后续任务短暂 sleep(0.5–1s) 退避，防止连续触发配额。
  - 预校验：若 `results` 为空或缺 url/snippet/content/score，则跳过 extract，直接进入 regex/LLM 抽取，避免格式 422。

- **DeepSeek 超时与模型降级（代码层优化）**：
  - 默认模型切换为 `deepseek-chat`（兼容性更好，响应相对快），CLI 默认值与 README/AGENTS 同步；`--deepseek-model` 仍可覆盖。
  - Timeout 收紧：`--deepseek-timeout` 默认 8s，`--llm-hard-timeout` 默认 10s，超过立即回退 regex，不再二次重试。
  - 并发保护：`deepseek_max_concurrency` 默认 1；关键指标仍可通过 `--deepseek-serial-keys` 串行，避免限流导致的排队超时。
  - 搜索失败即跳过 LLM：当 Tavily search 无结果或 extract 422/异常时，直接走 regex/人工，不再调用 DeepSeek，减少空跑等待。
  - 输入裁剪：对传入 DeepSeek 的 snippets 只保留前 1–2 条高分文本，避免长上下文导致响应超时。

  - **CLI 提示（422/降级）**：保留 `--disable-extract` 快捷关闭 Tavily extract；如需开启，建议配合 `--extract-topk 1`，出现 422 自动 search-only；LangChain 默认禁用，必须显式加 `--allow-langchain`。

30) **暂缓使用 LangChain 抽取**：
    - 默认不启用 `--extraction-backend langchain`，文档示例移除该选项。
    - 若用户强制开启，入口先检查依赖；缺失则友好报错退出，不进入耗时流程。
    - 在代码中增加保护：langchain 分支与主流程保持相同超时/并发/过滤参数，避免与 DeepSeek 路径不一致导致长时间悬挂。

31) **配置一致性与回归验证补齐**：
    - 文档同步：AGENTS/README/脚本示例更新默认值（deepseek-chat、timeout 8/10s、禁用 langchain、快速模式说明）。
    - 观测指标：summary 增加 p50/p95、tavily_extract_422_count、DeepSeek timeout_count；task_log/websearch_results note 标记 422/深度超时类型。
    - 回归测试：补最小测试/脚本覆盖超时、422、regex 快速模式路径，避免改完无自动验证。

32) **数据准确性兜底增强**：
    - 资金流方向判定：在 `_validate_fund_flow_extraction`/regex 路径增加方向关键词修正，减少 manual_required。
    - trend 补全：已有数值但缺 trend 时轻量填充，避免重复触发 LLM。
    - DeepSeek 不可用时自动 fallback：当无 key 或两次超时，直接切 regex，提供明确 CLI 开关。

33) **健康检查补充**：
    - 在 AGENTS/README 增加 DeepSeek/Tavily ping 脚本入口，便于运行前诊断网络/密钥。
    - 可选：在 preflight 或单独脚本输出 ping 结果，失败则阻断后续 Stage2。

34) **DeepSeek 短路与 regex 兜底**：当 Tavily search 无结果或 extract 返回 422/异常时，跳过 DeepSeek 直接走 regex/人工，note 标明 skip 原因；资金流 regex 补充方向推断，修正正负号以减少 manual_required。
