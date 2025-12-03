# Repository Guidelines

## Project Structure & Module Organization
- Core source lives in `src/datasource/`, split across adapters, managers, calculators, engines, cache helpers, and utilities; extend new integrations through this tree.
- Configuration belongs in `src/datasource/config/indices_config.py` and root `config/`.
- Tests sit in `tests/` with fixtures in `tests/test_data_sources/` and helpers consolidated in `tests/test_datasource.py`.
- Templates stay in `templates/`; generated markdown reports go to `reports/` and require review before merging.
- Long-running utilities reside in `scripts/` (notably `scripts/utility/background_scan_120d_generator.py`); reproducible demos live in `examples/`.

## Build, Test, and Development Commands
- Environment setup: `python -m venv .venv` then activate via `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Unix).
- Install deps: `pip install -r requirements.txt`, `pip install -e .`, and `pip install -e ".[dev]"`.
- Provision defaults: `cp .env.example .env` (bundled TuShare token, rate limits, cache toggles).
- Health check: `python -c "from datasource import get_manager; print('OK')"` confirms imports and entrypoints.

## Coding Style & Naming Conventions
- Support Python ≥3.7, four-space indentation, UTF-8 files.
- Favor async workflows that align with `DataSourceManager` and keep adapters thin; enforce business logic inside engines/calculators.
- Use `lower_snake_case` for modules, variables, and functions; `CamelCase` for classes; reserve constants for UPPER_SNAKE_CASE when required.
- Configure behavior through `indices_config.py` rather than embedding literals; comment only to clarify non-obvious intent.

## Testing Guidelines
- Quick validation: `datasource-test` (CLI entry) or `pytest -q`.
- Focused suites: `python tests/test_datasource.py`, `python tests/simple_test.py`, `python tests/test_na_filling.py`.
- Name new tests after the behavior under scrutiny (e.g., `test_background_scan_handles_timeout`) and keep fixtures deterministic within `tests/test_data_sources/`.

## Commit & Pull Request Guidelines
- Follow Conventional Commits (`feat:`, `fix:`, `refactor:`) scoped to a single logical change.
- PRs should outline scope, link issues, enumerate commands run, and include before/after snippets for template or report changes.
- Run `black src/ tests/ scripts/`, `flake8 src/`, and `mypy src/datasource/...` before submission; document any skipped checks.

## Security & Configuration Tips
- Keep secrets out of the repo; review `.env` before sharing artifacts.
- Respect shared cache and rate-limit policies (`TUSHARE_RATE_LIMIT`, `AKSHARE_RATE_LIMIT`).
- Set `PYTHONIOENCODING=utf-8` when generating Chinese-language output to avoid encoding regressions.

## Data Collection Standards (V2.1 MCP增强)

### Fund Flow Data Priority (新增)
**Background Scan Generator**: `scripts/utility/background_scan_120d_generator.py`

**Priority Strategy**:
1. **MCP WebSearch** (唯一通道): Real-time data from 东方财富网、同花顺、每日经济新闻等权威渠道
2. **Anomaly Detection**: 对任何 0/空值结果立即发起二次 WebSearch 复核

**Implementation Requirements**:
- 北向/南向/ETF/融资融券: 全量使用 MCP WebSearch 实时获取，禁止调用 AKShare
- 零值或缺失数据：必须标记“异常零值-需核查”，并在 note 中记录原始来源
- Data sources must be annotated: "MCP WebSearch实时获取" 或 "异常零值-需核查"
- Stage2 资金流向 CLI: `python scripts/stage2_unified_enhancer.py --fund-flow-backend {mcp|tavily|hybrid} --tasks northbound,southbound,etf --execute-search`
  - `tavily` 默认：直接搜索并填 recent_5d/total_120d，source 标记 `tavily+deepseek`
  - `mcp`：跳过搜索，gap_monitor 记录 pending，待 MCP/人工注入
  - `hybrid`: 预留 MCP→Tavily 降级，失败/零值会标记 manual_required

**Code Location**:
- Method: `BackgroundScan120DGeneratorFixed._get_fund_flow_websearch()` (lines 318-359)
- Method: `BackgroundScan120DGeneratorFixed.collect_fund_flow_data()` (lines 361-545)
- Method: `BackgroundScan120DGeneratorFixed.generate_fund_flow_table()` (lines 648-728)

**Data Format**:
```python
{
    'recent_5d': 123.45,       # 近5日流向(亿元)
    'total_120d': 456.78,      # 近120日累计(亿元)
    'trend': '流入' or '流出',
    'source': 'MCP WebSearch实时获取' or '异常零值-需核查',
    'note': '来源:东方财富网'  # Optional
}
```

**Testing**:
- Verify WebSearch priority logic
- Verify anomaly detection (zero-value handling)
- Verify source annotation in generated reports
- Verify ETF fund flow data acquisition (non-placeholder)

### MCP Tool Integration Guidelines
- **WebSearch Usage**: For real-time financial data (fund flows, commodities, forex, bonds, news)
- **WebFetch Usage**: For direct API calls (Yahoo Finance, specific endpoints)
- **Fallback Logic**: 禁用 AKShare，实时类数据全部由 MCP WebSearch 获取；若 WebSearch 暂不可用，需记录提示并等待人工补数
- **Data Annotation**: All MCP-sourced data must be clearly labeled in reports
- **Error Handling**: Log MCP failures and auto-switch to fallback sources

**See Also**: `docs/资金流向数据获取优化说明.md` for complete technical documentation

## Daily Run Playbook (Stage1→Stage3 with auto WebSearch补全)
- 设定日期：`DATE=$(date +%Y%m%d)`（如需回溯手动覆盖）。
- 激活环境：`source .venv/bin/activate && source .env`.
- **Stage1** 收集原始数据：`python scripts/stage1_data_collector.py --date $DATE --output data/${DATE}_market_data.json`.
- **Stage2** WebSearch 增强（涵盖资金流向/商品/汇率/国债）：  
  `PYTHONPATH=. python scripts/stage2_unified_enhancer.py --market-data data/${DATE}_market_data.json --output data/${DATE}_market_data_stage2.json --execute-search --fund-flow-backend hybrid --cache-backend sqlite --cache-path reports/tavily_cache.sqlite --websearch-results reports/websearch_results_${DATE}_auto.json --log-output logs/stage2_unified_log_${DATE}.json --gap-monitor reports/gap_monitor_${DATE}.json`.  
  - 若只重试缺口，用 `--tasks key1,key2,...` 过滤；失败项会写入 gap_monitor。
- **Stage2 补价兜底**（商品/债券）：`PYTHONPATH=. python scripts/fill_market_data_from_yahoo.py --input data/${DATE}_market_data_stage2.json --output data/${DATE}_market_data_stage2_filled.json`（可选，离线时忽略）。
- **WebSearch 注入闭环**：`python inject_websearch_data_test.py data/${DATE}_market_data_stage2_filled.json reports/websearch_results_${DATE}_auto.json data/${DATE}_market_data_complete.json`。未补齐的缺口可手动编辑 websearch_results_${DATE}.json 再跑一次。
- **Stage3** Pring 分析：`PYTHONPATH=. python scripts/stage3_pring_analyzer.py --market-data data/${DATE}_market_data_complete.json --output data/${DATE}_pring_result.json`.
- **报告生成**：`PYTHONPATH=. python tests/scripts/generate_simple_report_test.py data/${DATE}_market_data_complete.json data/${DATE}_pring_result.json reports/${DATE}背景扫描120.md`.
- 验证：查看 `reports/gap_monitor_${DATE}.json` 应为空；报告中不应再出现 “N/A（待 WebSearch）”。

### Stage3 估算值兜底开关（新）
- 目的：避免 Stage3 因宏观/货币/外汇等指标仅有 WebSearch 估算值而硬阻断分析。
- 使用：在 Stage3 命令追加 `--allow-estimated`，允许使用 `is_estimated=True` 的数据参与评分；仍需数值非空。
- 约束：仍建议优先填入权威来源；若指标为 None/0 依旧判定缺失。
- 相关代码：`scripts/stage3_pring_analyzer.py`、`src/datasource/calculators/pring_analyzer.py`（`allow_estimated` 参数）。

### Stage2.5 注入脚本优化（缺口自动清理）
- 脚本：`inject_websearch_data_test.py`  
  - 注入成功后会同步清理 `metadata.missing_items` 与顶层 `missing_items`，避免缺口在下次 Stage3 被反复阻断（例如 000016）。
  - 若填入了 `stock_indices`/`forex`/`bonds`/`commodities`/`fund_flow` 的实际数值，缺口会自动删除，无需额外手工清空。
  - 宏观指标若缺 `previous_value`，注入时会用 `current_value - change_rate` 反推；无变动值时退化为 `previous_value=current_value`，减少报告中的 “N/A”。

### Stage2 Tavily 运行指南（2025-12 更新）
- 资金流向/外汇默认走 Tavily，`fund-flow-backend` 默认 `tavily`；`hybrid` 表示 tavily→人工，不再有 MCP 自动通道。
- 必要密钥：`.env` 设置 `TAVILY_API_KEY`、`DEEPSEEK_API_KEY`；建议 `PYTHONPATH=./src` 运行。
- DeepSeek 默认模型 `deepseek-reasoner`，超时 12s；可用 `--use-queue` 开启 asyncio.Queue 抽取（削峰限流）。
- 实时类搜索参数：language=chinese, topic=news, time_range=day, max_results<=8, search_depth=advanced；宏观/低时效 time_range=year/month, max_results<=6, search_depth=basic。
- 命令示例：  
  `PYTHONPATH=./src python3 scripts/stage2_unified_enhancer.py --market-data data/${DATE}_market_data.json --output data/${DATE}_market_data_stage2.json --execute-search --fund-flow-backend tavily --log-output logs/stage2_unified_log_${DATE}.json --gap-monitor reports/gap_monitor_${DATE}.json --websearch-results reports/websearch_results_${DATE}.json`
  可选队列：`--use-queue --queue-concurrency 3 --queue-retry-limit 2`
### Stage2 Tavily + MCP 旧指南（如需 MCP 手工补数）
- 如仍需人工/MCP 补数，可编辑 `data/websearch_results_${DATE}.json` 后运行 `inject_websearch_data_test.py` 写回，再继续 Stage3/报告。

### Stage2 LangChain 抽取模式
- 开关：`--extraction-backend langchain`（依赖 `langchain`/`langchain-community`/`tavily-python`/`openai` 已安装）。
- 并发/超时：`--lc-max-concurrency`（默认3）、`--lc-timeout`（默认8s）；`--deepseek-model`/`--deepseek-base-url` 可透传 DeepSeek 配置。
- 记录：task_log 追加 `extraction_backend`、`llm_latency_ms`、`llm_error`；`websearch_results` 标记抽取后端。
- 优先级：专业财经 MCP→Tavily+DeepSeek(LangChain)→手工/WebSearch JSON 注入；未命中的外汇/资金流向会落入 gap_monitor，需 MCP/手工补齐再注入。

### Proxy 配置与脚本优化
- 生产环境建议不设置全局代理，默认直连外网；如确需代理，在 `.env` 中配置可用的代理后再 `source .env`。若不使用代理，可在命令前加 `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY` 确保完全禁用。
- Stage2 参数优先级：CLI `--http-proxy/--https-proxy` > 环境变量；若全局禁用代理，请不要在命令中带这些参数。
- 连通性快速自检（直连）：`python - <<'PY' import httpx; print(httpx.get('https://api.tavily.com', timeout=5, proxies=None).status_code)`；若必须代理，则在自检里显式传入 `proxies`。

### Stage2 数据获取优先级（外汇/资金流/行情）
- **MCP 优先**：若有 MCP/人工通道，`fund_flow_backend=mcp` 或 `forex_backend=mcp` 会跳过在线查询并标记待 MCP 注入。
- **Tavily 次之**：`hybrid` 表示先 MCP 再 Tavily，`tavily` 表示直接 Tavily。
- **WebSearch 最后补充**：Tavily 失败或离线时，使用 `data/websearch_results_${DATE}.json`（手工/MCP WebSearch）+ `inject_websearch_data_test.py`，脚本支持外汇、资金流、宏观、货币、商品、债券写回。
- **行情兜底**：可在 Stage2 后运行 `scripts/fill_market_data_from_yahoo.py` 再做 WebSearch 注入，补商品/债券/外汇缺口。
