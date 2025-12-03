# Stage 2 一体化运行手册（Tavily + DeepSeek）

## 1. 运行前检查
- 执行 `python scripts/setup_stage2_search_env.py`：校验 `TAVILY_API_KEY` / `DEEPSEEK_API_KEY` 是否配置且 Tavily 连通性正常。
- 确认 `.env` 中 `STAGE2_SEARCH_BACKEND=tavily`（灰度可切换为 mcp 仅用于灾备）。
- 清理过期缓存（可选）：删除 `reports/tavily_cache.sqlite` 或使用 `--no-cache`。

## 2. 典型命令
```bash
python scripts/stage2_unified_enhancer.py \
  --market-data data/market_data_stage1.json \
  --phase all \
  --fund-flow-backend tavily \  # 可选 mcp|tavily|hybrid
  --execute-search \
  --cache-backend sqlite \
  --cache-path reports/tavily_cache.sqlite \
  --task-file reports/search_tasks_stage2.jsonl \
  --websearch-results reports/websearch_results_auto.json
```

### LangChain 抽取模式（Tavily + DeepSeek）
> 适用于需要并发控制与可观测的 DeepSeek 抽取链路，默认仍可回退 regex。
```bash
python scripts/stage2_unified_enhancer.py \
  --market-data data/market_data_stage1.json \
  --output data/market_data_stage2_lc.json \
  --execute-search \
  --extraction-backend langchain \
  --lc-max-concurrency 3 \
  --lc-timeout 8.0 \
  --fund-flow-backend tavily \
  --websearch-results reports/websearch_results_auto.json \
  --task-log logs/stage_task_log.jsonl
```
日志/产物新增：
- task_log 增加 `extraction_backend`、`llm_latency_ms`、`llm_error` 字段，便于定位 DeepSeek 超时/失败。
- websearch_results 增加 `extraction_backend` 标记（langchain/regex/deepseek），保留前三条片段审计。
- 若 DeepSeek 抛错或超时，会自动回退 regex 占位并标记 `deepseek_error:*`，同时写 `llm_error`。
- 如果缺少 `DEEPSEEK_API_KEY` 且选择了 deepseek/langchain，会自动降级为 `extraction_backend=regex`，继续执行 Tavily+regex 兜底。

### fund_flow_backend 选择
- `tavily`（默认）：直接用 Tavily+DeepSeek 抽取资金流；抽取失败或零值会标记 `manual_required`。
- `mcp`: 跳过在线搜索，任务记为待人工/MCP；`gap_monitor` 列出 pending，保留占位。
- `hybrid`: 预留 MCP→Tavily 降级流程（当前 MCP 未实现，带注记“已降级 Tavily”）。

## 3. 关键产物 & 阻断条件
- `reports/search_tasks_stage2.jsonl`：生成的搜索任务；可用 `--task-file` / `--resume` 重跑（后续补充）。
- `logs/stage_task_log.jsonl`：每条任务的输入/输出/置信度/错误。
- `reports/websearch_results_auto.json`：抽取结果+前三条原始片段，便于审计。
- `reports/gap_monitor.json`：仍待补字段列表；Stage3 在 `metadata.ai_websearch_enhanced` 缺失或 gap 非空时应阻断。
- 资金流向零值/空值被标注为 `source="异常零值-需核查"` 并写 note，需人工补数；MCP 结果强制标注 `MCP WebSearch实时获取`。
- 若 gap_monitor 仍列任务或资金流向为零值，可使用 `--resume-from-task-file reports/search_tasks_stage2.jsonl --tasks <task_ids>` 重试非 fund flow 任务，资金流向则需跑 `scripts/utility/background_scan_120d_generator.py`。

## 4. 密钥轮换
- 将新密钥写入 `.env` 或 CI Secret（TAVILY_API_KEY / DEEPSEEK_API_KEY）。
- 运行 `source .venv/bin/activate && python scripts/setup_stage2_search_env.py` 确认生效。
- 若切换 Tavily 项目导致旧缓存不可用，删除 `reports/tavily_cache.sqlite` 以避免混用。

## 6. 代理与网络调试 (WSL 示例)
```bash
export HTTP_PROXY=http://127.0.0.1:10809
export HTTPS_PROXY=http://127.0.0.1:10809
export NO_PROXY="localhost,127.0.0.1,::1,10.0.0.0/8,192.168.0.0/16"
export no_proxy="$NO_PROXY"
python scripts/setup_stage2_search_env.py  # 验证 Tavily 连通性
```
若 httpx 版本不支持 proxies 参数，客户端会自动使用环境变量代理。

## 5. 灰度与回退
- 环境变量 `STAGE2_SEARCH_BACKEND` 可设为 `tavily`（默认）或 `mcp`（仅当 Tavily 不可用时）。代码当前以 Tavily 为主，资金流向仍固定 MCP。
- `--no-cache` 可禁用缓存验证实时性；`--cache-ttl` 控制命中窗口。
- 搜索失败达到 3 次会记录 `manual_required`（后续补充）；现阶段可通过任务文件手动重跑。

---

## 7. 规划中的优化（Tavily + DeepSeek 异步与降级）
目标：保持深度抽取但减少超时/阻塞，优先级 MCP → Tavily → DeepSeek → regex 兜底。

设计要点（TODO）：
- 并发：Tavily 搜索与 DeepSeek 抽取分层异步（示例并发 Tavily=4，DeepSeek=3）。
- 超时/重试：Tavily 8–10s，重试 1–2 次；DeepSeek 6–8s，重试 1 次，超时立即降级 regex。
- 开关：新增 CLI `--extraction-backend [deepseek|regex]`，`--deepseek-timeout`，`--deepseek-model`，`--deepseek-base-url`，`--deepseek-max-concurrency`。
- 降级：DeepSeek 失败→regex；失败任务写 gap_monitor，websearch_results 标记 deepseek_timeout。
- 日志：task_log 记录 extraction_backend、deepseek_error；websearch_results 保留前 3 条 snippets 与抽取结果。
- 精准重跑：gap_monitor 缺口用 `--tasks` + 可选 `--extraction-backend regex` 快速补占位。
- 额外兜底：Stage2 后可运行 `scripts/fill_market_data_from_yahoo.py`，再用 WebSearch 注入，保证 Stage3 输入完整。
