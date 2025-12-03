# Stage2 快速运行说明（Tavily + DeepSeek）

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
  --log-output logs/stage2_unified_log_20251203_new.json \
  --gap-monitor reports/gap_monitor_20251203_new.json \
  --websearch-results reports/websearch_results_20251203_new.json \
  --task-log logs/stage_task_log_new.jsonl
```

## 关键默认值
- `--fund-flow-backend` 默认 `tavily`
- `--deepseek-model` 默认 `deepseek-reasoner`
- `--deepseek-timeout` 默认 `12s`
- 实时类查询：language=chinese, topic=news, time_range=day, max_results<=8, search_depth=advanced
- 宏观/低时效：time_range=year/month, max_results<=6, search_depth=basic

## 观测指标（summary/log）
- score_filtered_drop、domain_filtered_drop、extract_calls、tavily_extract_calls
- timeout_count、retry_count、cache_hit_rate、avg_elapsed_ms
- success_by_category / total_by_category

## 兼容提醒
- 无 MCP 跳过逻辑；资金流统一 Tavily，零值且无方向直接标人工。
- LangChain 分支需安装 `langchain-core`，否则使用 deepseek 默认抽取。
