# Stage2 LangChain 版需求文档

## 目标
- 基于 LangChain 重写 Stage2 搜索+抽取流水线，保持现有输入/输出兼容。
- 数据获取优先级：MCP（手工/外部）→ Tavily 搜索 → DeepSeek LLM 抽取 → regex 兜底。
- 提升稳健性：并发可控、超时降级、可观测性（可选 LangSmith）。
- 最终产物不变：`*_market_data_stage2.json`、`websearch_results*.json`、`gap_monitor*.json`、`stage_task_log.jsonl`。

## 约束
- 不改变 Stage1/Stage3/报告接口。
- 兼容原有 CLI 参数；新增参数需有默认值保证旧流程可用。
- Python ≥3.10；新增依赖：`langchain`, `langchain-community`, `tavily-python`, `openai`, `httpx`（可选 `langsmith`）。

## 功能需求
1. 任务执行管线（LCEL/Runnable）
   - 输入：单个任务（indicator_key、query、preferred_domains、unit、issuer 等）。
   - 步骤：Tavily 搜索 → LLM 抽取 → 解析 → 校验(issuer/domains/unit) → 结果/manual_required。
   - Fallback：LLM 失败/超时/低置信度 → regex 兜底。

2. 配置开关（CLI）
   - `--extraction-backend {langchain,deepseek,regex}`，默认 langchain。
   - `--lc-max-concurrency`（默认 3），`--lc-timeout`（默认 8s，LLM 超时），`--langsmith` 开关。
   - 透传模型/BASE URL/API KEY：`--deepseek-model`、`--deepseek-base-url`、`DEEPSEEK_API_KEY` 环境变量。

3. 日志与产物
   - task_log：增加 `extraction_backend=langchain`、`llm_error`、`llm_latency_ms`。
   - websearch_results：保持结构（task + extraction + raw_results[:3]），note 标记 langchain/fallback。
   - gap_monitor：逻辑不变。

4. 并发与超时
   - Tavily 搜索并发可控；LLM 抽取并发由 `lc-max-concurrency` 控制；全局/单次 timeout 配置。

5. 校验规则
   - 若 source_url 域名不在 preferred_domains → 降置信度或 manual_required。
   - 若 issuer_hint 不匹配 → manual_required。
   - fund_flow 置信度 <0.5 或无值 → manual_required。

6. 兼容性
   - 若无 LangChain 依赖或无 DeepSeek Key，可自动退回 regex 模式（不阻塞执行）。

## 验收标准
- 在 `--extraction-backend=langchain` 下，Stage2 产物可被 Stage3/报告直接消费，gap_monitor 不超过旧实现水平。
- 执行时间无显著劣化（默认并发=3、timeout=8s 场景）。
- 日志与 websearch_results 格式兼容现有消费者。

## 非功能
- 不改 Stage1 数据源；不引入新存储。
- 不强制接入 LangSmith（默认关闭）。
