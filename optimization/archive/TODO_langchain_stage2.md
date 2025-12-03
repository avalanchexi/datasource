# TODO: LangChain 版 Stage2 开发清单

## 准备
- [x] 安装依赖：`langchain`, `langchain-community`, `tavily-python`, `openai`, `httpx`（可选 `langsmith`）。
- [x] 确认 `.env` 中 `DEEPSEEK_API_KEY`、`TAVILY_API_KEY`；如需 LangSmith，配置 `LANGCHAIN_TRACING_V2` 等。

## 开发
- [x] 新建 `src/datasource/engines/stage2_lc_pipeline.py`
  - [x] 封装 Tavily Runnable（调用 AsyncTavilyClient 或 LC Tavily 工具，保留缓存/代理参数）。
  - [x] 封装 DeepSeek ChatModel（ChatOpenAI base_url 可配，timeout 可配）。
  - [x] Regex fallback Runnable。
  - [x] 校验/回写函数：域名、issuer、unit 检查；fund_flow 置信度阈值；manual_required 标记。
  - [x] `run_tasks(tasks, market_payload, config)` 返回 completed/failures/websearch_results。

- [x] 在 `scripts/stage2_unified_enhancer.py` 增加 LC 入口
  - [x] CLI 参数：`--extraction-backend {langchain,deepseek,regex}`，`--lc-max-concurrency`，`--lc-timeout`，`--langsmith`，透传 DeepSeek 模型/base_url。
  - [x] 当 extraction-backend=langchain 时调用 LC 管线，否则保持现有逻辑。
  - [x] task_log 增加字段：`extraction_backend`、`llm_error`、`llm_latency_ms`。
  - [x] websearch_results note 标记 `langchain` 或 `regex_fallback`。

- [ ] 兼容/降级
  - [x] 无 key 或导入失败时自动切换 regex；不中断执行。（DeepSeek 缺失自动降级；Tavily 仍为硬依赖）
  - [x] Gap_monitor 逻辑保持；failed/manual_required 写入。

## 测试与验证
- [ ] 单元/离线：用固定 snippets 对比 LC 抽取 vs 旧抽取输出。
- [ ] 在线冒烟：选择 forex/bonds/fund_flow 小批任务运行，确认无长时间阻塞，成功率不少于旧版。
- [ ] 重新跑全流程 Stage2→注入→Stage3→报告，验证无 N/A 缺口，产物格式兼容。

## 文档
- [x] 更新 `docs/stage2_unified_runbook.md`，说明 LC 模式及参数。
- [x] 在 AGENTS.md 添加“Stage2 LangChain 模式”提示。

## 完成标准
- Stage3/报告可直接消费 LC 模式输出；task_log/websearch_results/gap_monitor 与旧版兼容。
- 默认并发=3、timeout=8s 情况下性能不劣化；失败任务不多于旧实现。

## 待修复/优化
- [x] 去重 CLI 参数定义（`--lc-max-concurrency`、`--lc-timeout` 重复）。
- [x] task_log 记录 DeepSeek 延迟、错误信息；websearch_results 增加 note 标记抽取后端。
- [x] 当缺少密钥或 DeepSeek 异常时自动降级至 regex；日志写明降级原因。
