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
  --market-data data/20251203_market_data.json \
  --output data/20251203_market_data_stage2_new.json \
  --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend regex \
  --disable-extract \
  --deepseek-timeout 8 \
  --llm-hard-timeout 10 \
  --deepseek-max-concurrency 1 \
  --log-output logs/stage2_unified_log_20251203_new.json \
  --gap-monitor reports/gap_monitor_20251203_new.json \
  --websearch-results reports/websearch_results_20251203_new.json \
  --task-log logs/stage_task_log_new.jsonl
```
  - 速度优先：保持 `--extraction-backend regex --disable-extract`，约 30–60 秒。
  - 精度优先：改为 `--extraction-backend deepseek --deepseek-model deepseek-chat --deepseek-timeout 8 --llm-hard-timeout 10 --deepseek-max-concurrency 1`（预计 3–5 分钟）。
  - Tavily extract 422/配额压力：保留 `--disable-extract` 或收紧 `--extract-topk 1`，先 search-only 再 regex 兜底。
  - LangChain 默认禁用，如需实验需显式加 `--allow-langchain`。

## 关键默认值
- `--fund-flow-backend` 默认 `tavily`
- `--deepseek-model` 默认 `deepseek-chat`
- `--deepseek-timeout` 默认 `8s`
- `--llm-hard-timeout` 默认 `10s`
- Tavily extract 默认启用，可用 `--disable-extract` 或遇 422 自动回退 search-only（有计数）
- 实时类查询：language=chinese, topic=news, time_range=day, max_results<=8, search_depth=advanced
- 宏观/低时效：time_range=year/month, max_results<=6, search_depth=basic
- LangChain 默认禁用，如需实验需加 `--allow-langchain`；示例不再提供 langchain 选项。

## 观测指标（summary/log）
- score_filtered_drop、domain_filtered_drop、extract_calls、tavily_extract_calls、tavily_extract_422_count
- timeout_count、retry_count、cache_hit_rate、avg_elapsed_ms、p50_elapsed_ms、p95_elapsed_ms
- success_by_category / total_by_category

## 兼容提醒
- 无 MCP 跳过逻辑；资金流统一 Tavily，零值且无方向直接标人工。
- 默认禁用 LangChain；需显式传 `--extraction-backend langchain` 且依赖齐全才启用。
