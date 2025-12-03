# Stage2 LangChain 化方案（草案）

目标：将现有 Stage2 搜索+抽取链路升级为基于 LangChain 的可组合、可观测流水线，保持现有输入/输出契约，提升稳健性与扩展性。

## 范围
- 替换 Tavily + DeepSeek 抽取段为 LangChain Runnable/LCEL 管线。
- 保持 CLI、产物（market_data_stage2.json、websearch_results*.json、gap_monitor、task_log）兼容。
- 先覆盖核心指标（forex、bonds、fund_flow），再逐步扩展。

## 设计概述
1) 模型与工具
   - ChatModel: DeepSeek (OpenAI 兼容)，通过 LangChain `ChatOpenAI` 配置 `base_url` / `api_key` / `timeout`。
   - Search Tool: Tavily 官方 LangChain 工具，或自定义 Runnable 调用 AsyncTavilyClient。
   - Regex Fallback: LangChain Runnable（简单函数）作为抽取兜底。

2) LCEL 管线（单任务）
   TavilySearch → DeepSeekExtract → OutputParser → 校验(issuer/domains/unit) → Result/ManualFlag。

3) 并发与超时
   - 使用 `await runnable.abatch(tasks, config={"max_concurrency": N, "timeout": T})` 控制并发/超时。
   - DeepSeek 超时后自动切换 Regex Fallback，并在注记中写入 `deepseek_timeout`。

4) 友好观测
   - 可选集成 LangSmith：记录每个任务的 Tavily 请求、LLM 输出、解析结果；默认关闭，调试时开启。

5) 兼容性与落地
   - 输入：沿用 `SEARCH_PROFILES`、任务生成逻辑不变。
   - 输出：保持 websearch_results 结构（task + extraction + raw_results[:3]），task_log 字段新增 `extraction_backend=langchain`、`llm_error`。
   - CLI 新增参数：`--extraction-backend {langchain,regex,deepseek_raw}`，`--lc-max-concurrency`，`--lc-timeout`，`--langsmith` 开关。

## 实施步骤
1) 新建模块 `src/datasource/engines/stage2_lc_pipeline.py`
   - 封装 Tavily Runnable、DeepSeek ChatModel、Regex Fallback、校验/写回函数。
   - 提供异步 `run_tasks(tasks, config, market_payload)` 返回 completed/failures/websearch_results。

2) 修改 stage2_unified_enhancer (可开关)
   - 当 `--extraction-backend=langchain` 时调用 LC 管线；否则沿用旧路径。
   - 在 CLI 中加入相关参数并透传。

3) 日志/产物
   - task_log 增加 `extraction_backend=langchain`、`llm_error`；
   - websearch_results 同结构，note 标记 `langchain`；
   - gap_monitor 逻辑不变。

4) 回归验证
   - 离线回归：使用固定 snippets，对比旧抽取 vs LC 抽取结果；
   - 在线冒烟：forex/bonds/fund_flow 核心任务小批量并发，确认无超时阻塞；
   - 报告生成链路保持无改动。

5) 迭代扩展
   - 增加指标感知 Prompt（利用 issuer/unit/time_range）；
   - 添加域名校验可选强约束（不在白名单则降置信度）；
   - 支持多模型路由（如 GPT-4o-mini 备用）。

## 风险与缓解
- 网络/服务不可达：保留 regex fallback；不可用时自动降级。
- 依赖膨胀：LangChain 仅用于 Stage2 抽取，避免侵入 Stage1/3。
- 性能：控制 `lc-max-concurrency`，并设置合理 timeout（建议 8–12s）。

