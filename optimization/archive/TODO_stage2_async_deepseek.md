# TODO: Stage2 Tavily + DeepSeek 异步与降级

## 目标
- 最大化 Tavily+DeepSeek 自动获取成功率，减少超时阻塞。
- 优先级：MCP → Tavily → DeepSeek → regex 兜底，保证 Stage3 数据完整。

## 必做项
1) 参数化抽取后端
   - CLI: `--extraction-backend [deepseek|regex]`（默认 deepseek）。
   - CLI: `--deepseek-timeout <sec>`，`--deepseek-model`（默认 deepseek-chat），`--deepseek-base-url`，`--deepseek-max-concurrency`。
2) 并发与超时
   - Tavily 搜索并发（示例 4），DeepSeek 抽取并发（示例 3），用 `asyncio.Semaphore` 控制。
   - DeepSeek 超时 6–8s，重试 0–1 次；超时/错误立即降级 regex。
3) 降级与记录
   - DeepSeek 失败→regex 兜底，task_log 记录 `extraction_backend`、`deepseek_error`、`attempt`。
   - websearch_results 标记 `deepseek_timeout` note，gap_monitor 保留失败任务。
4) 兼容现有流程
   - 默认行为不变；若无 DeepSeek key 仍走 regex。
   - fund_flow/forex backend 行为保持，同时支持新的抽取开关。
5) 连通性与代理
   - DeepSeek client 支持 base_url/timeout，直连为默认；代理需显式传入。

## 可选项
- 增加 `--no-deepseek` 快速模式，仅 regex。
- 对 gap_monitor 缺口自动二次尝试（低并发、短超时）。

## 验收
- 在正常网络下：Stage2 成功率显著提升，执行时间可控，无大规模超时；主要指标字段不再批量落入 regex/手工。
- 在受限网络下：流程仍能完成，失败任务被正确标记并可重跑；报告生成不阻塞。
