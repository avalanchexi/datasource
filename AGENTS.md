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
