# Stage2 单指标运行流程示例（USDCNY）

本示例展示了 Stage2 对单个指标的处理链路、参数、产物与卡点。

## 1. 运行命令
```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  bash -lc "source .venv/bin/activate && set -a && source .env && set +a && \
  PYTHONPATH=. python scripts/stage2_unified_enhancer.py \
    --market-data data/20251121_market_data.json \
    --output data/20251121_market_data_stage2_usdcny.json \
    --execute-search \
    --tasks USDCNY \
    --fund-flow-backend hybrid \
    --cache-backend sqlite --cache-path reports/tavily_cache.sqlite \
    --websearch-results reports/websearch_results_20251121_usdcny.json \
    --log-output logs/stage2_unified_log_20251121_usdcny.json \
    --gap-monitor reports/gap_monitor_20251121_usdcny.json \
    --deepseek-timeout 8 --deepseek-max-concurrency 2 \
    --extraction-backend regex"  # 本次为演示，强制 regex 兜底
```

关键参数：
- `--tasks USDCNY` 只跑一个外汇任务，便于观察。 
- `--extraction-backend regex` 关闭 DeepSeek，直接 regex 兜底（DeepSeek 网络不稳时建议如此）。
- 代理全部禁用以避免坏代理阻塞。

## 2. 数据流与交互
1) **Tavily 搜索**：发送查询“美元 人民币 在岸 汇率 最新 报价”，返回 snippets。
2) **抽取阶段**：因 `regex` 模式，直接从 snippets 提取首个数值；若缺发布机构/单位，置信度低并标记 manual_required。
3) **写回**：结果写入 `data/20251121_market_data_stage2_usdcny.json`（仅该指标被更新），并记录 task_log/websearch_results/gap_monitor。

## 3. 运行结果
- task 总数 1，成功 0，失败/待人工 1（USDCNY）。
- gap_monitor: `reports/gap_monitor_20251121_usdcny.json` 列出 USDCNY 需人工补数。
- task_log 记录（节选）:
  ```json
  {
    "indicator_key": "USDCNY",
    "search_backend": "tavily",
    "extraction_backend": "regex",
    "confidence": 0.35,
    "source_url": "https://jp.reuters.com/markets/us/",
    "note": "regex_only 缺少发布机构(SAFE/在岸即期)",
    "manual_required": true
  }
  ```

## 4. 可观察的卡点
- DeepSeek 未使用（本次强制 regex）；若设为 deepseek，需保证到 `https://api.deepseek.com` 的网络通路，否则会超时转 regex。
- Tavily 命中但未能抽到高置信度（缺发布机构），导致 manual_required。

## 5. 补数与下一步
- 用 WebSearch/MCP 手工填入 `data/websearch_results_20251121.json` 中的 `forex.USDCNY` 字段，再运行：
  ```bash
  python inject_websearch_data_test.py \
    data/20251121_market_data_stage2.json \
    data/websearch_results_20251121.json \
    data/20251121_market_data_complete.json
  ```
- 或重跑 Stage2：
  - 若网络已畅通，使用 `--extraction-backend deepseek --deepseek-timeout 15 --deepseek-max-concurrency 2 --tasks USDCNY`。
  - 仍失败可切换 `--extraction-backend regex` 生成低置信度占位，再由人工确认。

## 6. Stage2 运行逻辑速览
- **任务生成** → Tavily 搜索 → DeepSeek/regex 抽取 → 校验与写回 → websearch_results、task_log、gap_monitor → 输出 stage2 JSON。
- fund_flow/forex 后端可选：`mcp` 跳过在线直接待人工，`tavily` 直接搜索，`hybrid` 预留 MCP→Tavily 降级。

## 7. 文件产物
- `data/20251121_market_data_stage2_usdcny.json`：仅 USDCNY 任务后的 stage2 输出。
- `reports/websearch_results_20251121_usdcny.json`：该任务的抽取结果 + 原始 snippets（最高 3 条）。
- `logs/stage2_unified_log_20251121_usdcny.json`：Stage2 汇总信息。
- `reports/gap_monitor_20251121_usdcny.json`：未补齐任务列表。
- `logs/stage_task_log.jsonl`：全量任务日志，可搜索 task_id/indicator_key 查看细节。

