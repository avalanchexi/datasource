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
