# Tavily 查询稳定性优化需求

## 背景
- Stage2 当前一次完整执行约 21 个 Tavily 请求，DeepSeek 抽取常见 503/timeout，导致商品/外汇命中率偏低。
- 资金流向任务在 hybrid 模式下策略性跳过 Tavily，应继续保留 MCP/人工优先。

## 目标
- 在不减少查询数量的前提下，提高成功率、减少 503/timeout、降低噪声解析错误。

## 必须遵循
- 资金流向 northbound/southbound/etf 继续使用 MCP/人工补数，不改策略。
- 保持 AGENTS.md 优先级：实时数据首选 WebSearch/MCP，禁用 AKShare 兜底。

## 建议配置（默认批量跑）
- 直连 Tavily：命令前加 `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY`，或 `--http-proxy "" --https-proxy ""`。
- DeepSeek 调优：`--deepseek-max-concurrency 1 --deepseek-timeout 25 --max-retries 3`。
- 抽取后端兜底：可选 `--extraction-backend regex`（数值任务稳定）或 `--extraction-backend langchain`（如已安装）。
- 域名白名单：在任务模板/配置中优先 `reuters.com,bloomberg.com,investing.com,ft.com`。
- 时间窗：保持 `time_range=day` 且 `max_age_days<=2`。

## 针对易失败项的单独批次
- 命令示例：
  ```bash
  python scripts/stage2_unified_enhancer.py \
    --market-data data/20251125_market_data.json \
    --output data/20251125_market_data_stage2.json \
    --tasks BCOM,GSG,USDCNY,USDCNH \
    --execute-search --fund-flow-backend hybrid \
    --cache-backend sqlite --cache-path reports/tavily_cache.sqlite \
    --websearch-results reports/websearch_results_20251125_auto.json \
    --log-output logs/stage2_unified_log_20251125.json \
    --gap-monitor reports/gap_monitor_20251125.json \
    --deepseek-max-concurrency 1 --deepseek-timeout 25 --max-retries 3 \
    --deepseek-serial-keys BCOM,GSG,USDCNY,USDCNH
  ```

## 失败兜底流程
1) 查看 `reports/search_tasks_stage2.jsonl` 过滤失败任务。 
2) 低并发 + regex 再跑一次。 
3) 仍失败：在 `reports/websearch_results_YYYYMMDD_manual.json` 写入数值+来源，执行注入脚本。

## 监控与验收
- gap_monitor 应仅含资金流向类（manual_required），其他任务成功率提升到 >80%。
- 日志关注 DeepSeek 503/timeout；若持续出现，优先切换直连或延长 timeout。
