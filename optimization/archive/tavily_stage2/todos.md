# Stage2 Tavily 优化 TODOs（执行清单）

## 0. 基线 &准备
- [x] 备份当前基线日志：`logs/stage2_unified_log_20251202.json`, `20251203.json`，作为对比。
- [x] 确认 .env 中 Tavily/DeepSeek 密钥可用，代理配置正确。
- [x] 运行健康检查脚本（已新增 `scripts/stage2_health_check.py`）：校验密钥、代理连通、缓存路径可写、Tavily/DeepSeek ping。

## 1. Tavily 客户端与参数
- [x] `AsyncTavilyClient.search`：支持 language/topic/time_range/max_results/chunks_per_source/auto_parameters，并纳入 cache key。
- [x] 新增 Tavily `extract` 封装，支持 `extract_depth`、`include_raw_content`（按需）。

## 2. 任务参数路由
- [x] `Stage2TaskPlanner` / `SEARCH_PROFILES` 增加字段：language/topic/max_results/search_depth/chunks_per_source/auto_parameters。
- [x] 实时类（fund_flow/forex/commodities/bonds/indices）默认：language=chinese, topic=news, time_range=day, max_results<=10, search_depth=advanced。
- [x] 宏观/低时效：收紧为 time_range=year/month，max_results<=6，保持 basic。

## 3. 搜索结果处理
- [x] 在 `_execute_tasks`（含 LC 分支）添加 `score>=0.5` 过滤；为空回退原 snippets；统计 `score_filtered_drop`。
- [x] 将 `max_results` 限制传入 Tavily 调用；默认 8–10。

## 4. 二步抽取
- [x] 为高噪声任务（资金流/汇率/商品）实现 search→extract：
      - search 取 topN URLs；
      - 调 Tavily extract（可 advanced），必要时 include_raw_content(top1)；
      - 结果再走本地验证/regex 兜底。
- [x] 记录 `extract_calls`、成功/失败次数。

## 5. 资金流特化
- [x] 去除 MCP 跳过分支：资金流统一 Tavily，`fund_flow_backend` 默认 tavily，hybrid=“tavily→人工”。
- [x] 资金流结果校验：方向/单位/零值保持；异常时 note 标记但不写 MCP 占位。
- [x] 若返回 0 且无方向，直接标人工，不写入 market_data，note 记录“零值+方向缺失”。

## 6. DeepSeek & 模型
- [x] 默认模型改为 `deepseek-reasoner` (V3.2 think 模式)；CLI 默认值同步，禁用 Speciale。
- [x] 超时/并发参数：超时提高到 10–12s，并发 2–3；超时/网络错误重试 1 次，仍失败则回退 regex/Tavily extract。

## 7. 队列化抽取（可选迭代）
- [x] 使用内置 `asyncio.Queue`：search 生产、extract 消费，支持重试/死信；状态回写 task_log/gap_monitor。暂不接入外部 MQ。

## 8. 日志与观测
- [x] summary/log 增加：score_filtered_drop、extract_calls、timeout_count、retry_count、per-type 成功率、95P 延迟、cache_hit_rate。
- [x] gap_monitor 仅记录真实失败/人工，移除 MCP 等占位文案。

## 9. 文档/配置
- [x] 更新 `requirements.md` 变更点、默认参数说明；`AGENTS.md`/README 同步 `--fund-flow-backend`、DeepSeek 模型默认值。
- [x] CLI/README/AGENTS/SCRIPTS 同步默认值与示例，引用 `PYTHONPATH=./src`，可参考 `README_STAGE2_SNIPPET.md`。

## 10. 回归与对比
- [x] 跑一次 Stage2（同一日数据）与 20251202/20251203 基线对比：成功率、Tavily 请求数、平均/95P 延迟、人工缺口。（已生成 `logs/stage2_unified_log_20251203_new.json`）
- [x] 根据结果调整过滤阈值、超时与重试参数。（deepseek_timeout 默认 12s，queue_retry_limit 默认 2）
- [x] 增加对比脚本，输出表格/JSON 汇总新旧运行差异。（已添加 `scripts/compare_stage2_runs.py`）

## 11. 兼容性与配置收紧
- [x] Tavily extract 422 容错：仅传必需字段，失败回退 search-only，note 标 `tavily_extract_422`，资金流/汇率/商品用 advanced+raw_content(top1)。
- [x] 宏观/低时效 profile 收紧：time_range=year/month，max_results<=6，必要时设置 max_age_days。
- [x] 回归对比脚本 `scripts/compare_stage2_runs.py` 实现并输出表格/JSON。
- [ ] 文档同步（README/AGENTS/SCRIPTS），示例命令加 `PYTHONPATH=./src`，默认参数更新。

## 12. LangChain 临时禁用与保护
- [x] 在 Stage2 入口增加检查：未显式开启则不走 langchain；缺依赖时友好报错并退出。
- [x] 文档/示例移除 `--extraction-backend langchain` 默认选项，标注为“实验/暂不使用”。
- [x] 确保 langchain 分支复用主流程的超时/并发/过滤参数，避免悬挂（score/domain/max_age 过滤、422 回退、llm_hard_timeout）。

## 13. Tavily extract 422 优化落地
- [x] 在 `tavily_client.extract` 前置校验 results：空列表或缺 url/snippet/content/score 直接跳过 extract。
- [x] 提取输入裁剪：仅传 top1–2 高分 URL，过滤 PDF/失效链接；默认 `extract_depth=basic`、`include_raw_content=False`。
- [x] 捕获 422：回退 search-only，不重试；task_log/websearch_results note 标 `tavily_extract_422`，summary 计数 `tavily_extract_422_count`。
- [x] 为 extract 增加专用并发/重试（并发固定 1，重试 0）及短退避（0.5–1s）防止配额连环触发。
- [x] CLI 提示：保留 `--disable-extract`/`--extract-topk`，更新 README/AGENTS/requirements 说明 422 降级策略。

## 14. DeepSeek 超时与模型降级落地
- [x] 默认模型改为 `deepseek-chat`（入口 CLI 默认值 & docs 同步）。
- [x] 收紧超时：`deepseek_timeout` 默认 8s，`llm_hard_timeout` 默认 10s，使用 `asyncio.wait_for` 硬控；超时立即回退 regex，不重试。
- [x] 并发保护：默认 `deepseek_max_concurrency=1`，关键指标可通过 `--deepseek-serial-keys` 串行。
- [x] Tavily 搜索失败/返回为空或 extract 异常时，跳过 DeepSeek，直接 regex/人工，避免空跑。
- [x] 输入裁剪：传入 DeepSeek 的 snippets 仅保留前 1–2 条高分文本。
- [ ] 观测：summary 增加 DeepSeek p95/p50 延迟与超时计数；task_log 记录超时类型。

## 15. 配置/验证/健康检查补齐
- [x] 文档同步：AGENTS/README/脚本示例更新默认值（deepseek-chat、timeout 8/10s、禁用 langchain、快速模式说明）。
- [x] 回归测试：新增/更新测试或脚本覆盖超时、422、regex 快速模式路径。
- [x] 健康检查：增加 Tavily/DeepSeek ping 脚本入口；可选在 preflight 中输出 ping 结果，失败阻断 Stage2。

## 16. 新增（2025-12-06）
- [x] 资金流 regex 路径补方向推断：基于 snippet 关键词流入/流出，修正正负号并写 note，降低 manual_required。
- [x] Tavily 无结果 / extract=422 时跳过 DeepSeek，直接 regex/人工，减少空跑耗时。
- [x] LangChain 保护开关：默认禁用，未显式开启时报错退出；示例命令移除 langchain（待代码护栏+文档）。
- [x] 回归与观测补齐：task_log 标记 deepseek_timeout/skip 原因；增加 422/timeout/regex 路径的最小测试或断言（测试已补）。
- [x] 文档同步：AGENTS/README/requirements 增加本次改动与 CLI 默认值更新（deepseek-chat、timeout 8/10、skip-deepseek-on-422）。
