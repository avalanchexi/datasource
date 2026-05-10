# Stage2 快速运行说明（Tavily + DeepSeek / Regex 快速模式）

## 依赖
- Python 3.10+
- 必需环境变量：`TAVILY_API_KEY`、`DEEPSEEK_API_KEY`
- 推荐：`PYTHONPATH=./src`

## 典型命令
```bash
PYTHONPATH=./src \
TAVILY_API_KEY=xxx DEEPSEEK_API_KEY=yyy \
python3 scripts/stage2_unified_enhancer.py \
  --market-data data/runs/20251203/market_data.json \
  --output data/runs/20251203/market_data_stage2.json \
  --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend regex \
  --disable-extract \
  --deepseek-timeout 8 \
  --llm-hard-timeout 10 \
  --deepseek-max-concurrency 0 \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --log-output logs/runs/20251203/stage2_unified_log.json \
  --gap-monitor data/runs/20251203/gap_monitor.json \
  --websearch-results data/runs/20251203/websearch_results_auto.json \
  --task-log logs/runs/20251203/stage_task_log.jsonl
```
  - 速度优先：保持 `--extraction-backend regex --disable-extract`，约 30–60 秒。
  - 精度优先：改为 `--extraction-backend deepseek --deepseek-model deepseek-v4-pro --deepseek-timeout 30 --llm-hard-timeout 35 --deepseek-max-concurrency 3 --queue-concurrency 3`（默认启用 queue）。
  - Tavily extract 422/配额压力：保留 `--disable-extract` 或收紧 `--extract-topk 1`，先 search-only 再 regex 兜底。
  - LangChain 默认禁用，如需实验需显式加 `--allow-langchain`。

## 关键默认值
- `--fund-flow-backend` 默认 `tavily`
- `--deepseek-model` 默认 `deepseek-v4-pro`
- `--deepseek-timeout` 默认 `30s`
- `--llm-hard-timeout` 默认 `35s`
- `--deepseek-max-concurrency` 默认 `3`，Stage2 extraction queue 默认开启，`--queue-concurrency` 默认 `3`
- Tavily extract 默认启用，可用 `--disable-extract` 或遇 422 自动回退 search-only（有计数）
- 实时类查询：language=chinese, topic=news, time_range=day, max_results<=8, search_depth=advanced
- 宏观/低时效：time_range=year/month, max_results<=6, search_depth=basic
- LangChain 默认禁用，如需实验需加 `--allow-langchain`；示例不再提供 langchain 选项。

## 观测指标（summary/log）
- score_filtered_drop、domain_filtered_drop、extract_calls、tavily_extract_calls、tavily_extract_422_count
- timeout_count、retry_count、cache_hit_rate、avg_elapsed_ms、p50_elapsed_ms、p95_elapsed_ms
- success_by_category / total_by_category
- 增量命中率：task_search_success、task_search_failed、task_skipped_existing、search_success_rate_incremental

## 兼容提醒
- 无 MCP 跳过逻辑；资金流统一 Tavily，零值且无方向直接标人工。
- 默认禁用 LangChain；需显式传 `--extraction-backend langchain` 且依赖齐全才启用。
