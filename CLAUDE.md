# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Start Here**: Review [AGENTS.md](AGENTS.md) for repository layout and coding standards.

## Quick Reference

### Most Common Command (Report Generation)
```bash
# Full pipeline - replace DATE with target date (e.g., 20251119)
python scripts/stage1_data_collector.py --date DATE --output data/DATE_market_data.json
python scripts/stage2a_mcp_enhancer.py --market-data data/DATE_market_data.json --output data/DATE_market_data_enhanced.json
# [AI WebSearch补全 - see "AI Execution Workflow" section]
python inject_websearch_data_test.py data/DATE_market_data_enhanced.json data/websearch_results_DATE.json data/DATE_market_data_complete.json
python tests/scripts/run_pring_analysis_test.py data/DATE_market_data_complete.json data/DATE_pring_result.json
python tests/scripts/generate_simple_report_test.py data/DATE_market_data_complete.json data/DATE_pring_result.json reports/DATE背景扫描120.md
```

### Environment Setup
```bash
python -m venv .venv && .venv\Scripts\activate  # Windows
pip install -r requirements.txt && pip install -e . && pip install -e ".[dev]"
cp .env.example .env
python -c "from datasource import get_manager; print('OK')"  # Verify
```

### Testing
```bash
pytest -q                           # Quick test
python tests/test_datasource.py     # Core integration tests
black src/ tests/ scripts/ && flake8 src/ && mypy src/  # Quality checks
```

## Project Overview

Unified financial data integration framework with automatic failover between AKShare, TuShare, and International Finance data sources. Features async support, caching, rate limiting, Pring six-stage analysis with V4.0 three-layer framework, and automated 120-day background scan report generation.

**Core Components**:
- **DataSourceManager** (`src/datasource/manager.py`): Singleton with automatic failover
- **Pring Analyzer** (`src/datasource/calculators/pring_analyzer.py`): Three-layer framework (Inventory → Monetary → Pring)
- **Configuration** (`src/datasource/config/indices_config.py`): All symbols and parameters
- **Contracts** (`src/datasource/models/`): `MarketDataContract`, `PringResultContract`

## Architecture

### Layered Design
```
Adapters (src/datasource/adapters/)     → Thin API wrappers with rate limiting
Management (src/datasource/manager.py)  → Singleton DataSourceManager with failover
Config (config/indices_config.py)       → A_SHARE_INDICES, TECHNICAL_PARAMS, REPORT_CONFIG
Models (models/)                        → MarketDataContract, PringResultContract
Calculators (calculators/)              → Technical indicators, Pring analyzer
Scripts (scripts/)                      → Pipeline stages, utilities in scripts/utility/
```

### Key Patterns

**DataSourceManager** returns `DataResponse` with: `data` (DataFrame), `source`, `error`, `metadata`
```python
from datasource import get_manager
manager = get_manager()  # Singleton
response = await manager.get_forex_data("DXY", start, end)
if response.error:
    logger.error(f"Failed: {response.error}")
else:
    df = response.data
```

**Async-First**: Use `asyncio.gather()` for parallel fetches
```python
results = await asyncio.gather(*[
    manager.get_index_daily("000300", start, end),
    manager.get_forex_data("DXY", start, end),
    manager.get_bond_yield_data("US10Y", start, end)
])
```

## V3.3+ Multi-Stage Pipeline (6 stages, ~5-6min)

### Pipeline Overview

| Stage | Script | Time | Completeness | Output |
|-------|--------|------|-------------|--------|
| 1 | `stage1_data_collector.py` | 30-40s | 25-42% | market_data.json |
| 2a | `stage2a_mcp_enhancer.py` | 60-90s | 50-60% | market_data_enhanced.json |
| **AI补全** | Manual WebSearch + `inject_websearch_data_test.py` | 2-3min | **95%** | market_data_complete.json |
| 2 | `tests/scripts/run_pring_analysis_test.py` | 15-25s | Analysis | pring_result.json |
| 3 | `tests/scripts/generate_simple_report_test.py` | 10-15s | Report | DATE背景扫描120.md |
| 验证 | powershell file size check | 5s | Validation | - |

### Stage Details

**Stage 1**: API data collection (stock indices ✅, forex ✅, US10Y ✅; macro/monetary/fund_flow → placeholders)

**Stage 2a**: MCP enhancement for bonds (CN10Y, CN10Y_CDB) and commodities

**AI补全 (CRITICAL)**: WebSearch 14 queries for:
- Macro (5): PPI, PMI, Industrial, BDI, CPI
- Monetary (5): RRR, Reverse Repo, MLF, TSF, M2
- Fund flows (4): 北向资金, 南向资金, ETF, 融资融券

**Stage 2**: Pring Three-Layer Analysis
- Layer 1: Inventory Cycle → 60 points max
- Layer 2: Monetary Cycle → 100 points max
- Layer 3: Final Pring Six-Stage determination

**Stage 3**: Markdown report (9 sections: 核心结论, 股票市场, 商品与黄金, 债券市场, 外汇市场, 宏观经济指标, 货币政策, Pring三层框架, 资金流向)

**验证**: `powershell -Command "(Get-Item 'reports\DATE背景扫描120.md').Length"` → expect ~4800 bytes

## Code Standards

- **Async-First**: All data ops use async/await
- **Config-Driven**: No hardcoding, use `indices_config.py`
- **Thin Adapters**: API wrappers only; business logic in engines/calculators
- **Windows Primary**: Use Windows path handling; prefix `PYTHONIOENCODING=utf-8` for Chinese output
- **No Temp Scripts**: Modify existing scripts, don't create new ones
- **Security**: Use `.env` for credentials, never commit secrets

## AI Execution Workflow

When user requests "生成报告" or "执行背景扫描报告生成：DATE":

### Todo List Template
```json
[
  {"content": "STAGE 1: 数据收集(API)", "status": "pending", "activeForm": "数据收集中(30-40s)"},
  {"content": "STAGE 2a: MCP Essential增强(债券+商品)", "status": "pending", "activeForm": "MCP Essential增强中(60-90s)"},
  {"content": "AI WebSearch补全所有缺失数据", "status": "pending", "activeForm": "AI数据补全中(2-3分钟)"},
  {"content": "STAGE 2: Pring三层框架分析", "status": "pending", "activeForm": "Pring分析中(15-25s)"},
  {"content": "STAGE 3: Markdown报告生成", "status": "pending", "activeForm": "报告生成中(10-15s)"},
  {"content": "验证报告数据完整性", "status": "pending", "activeForm": "验证数据完整性中"}
]
```

### AI补全 WebSearch Queries (14 total)

**Macro (5)**:
- "中国PPI 最新数据 国家统计局"
- "中国制造业PMI 最新数据 国家统计局"
- "工业增加值 同比增长 国家统计局"
- "波罗的海干散货指数 BDI investing.com"
- "中国CPI 最新数据 国家统计局"

**Monetary (5)**:
- "存款准备金率 最新 央行"
- "7天逆回购利率 央行"
- "MLF利率 中期借贷便利 央行"
- "社会融资规模存量增速 央行"
- "M2货币供应量增速 央行"

**Fund Flows (4)**:
- "北向资金 流入 东方财富网"
- "南向资金 流入 同花顺"
- "ETF资金流向 股票ETF 债券ETF"
- "融资融券余额 两融"

## Critical Data Validation

### WebSearch JSON Format (CRITICAL)

Fund flow fields must contain parseable numbers, not descriptive text:

**✅ CORRECT**:
```json
{
  "fund_flow": {
    "northbound": {
      "recent_5d": "94",           // Parseable number
      "total_120d": "13000",       // Pure digits or "1.3万亿"
      "note": "详细描述放这里"
    }
  }
}
```

**❌ WRONG**:
```json
{
  "fund_flow": {
    "northbound": {
      "recent_5d": "波动",         // No numbers - causes N/A
      "total_120d": "净流入"       // Descriptive text - causes N/A
    }
  }
}
```

### Field Name Validation

Always reference `src/datasource/models/market_data_contract.py` before creating JSON:
- Use `total_120d` (not `recent_120d`)
- All Pydantic model required fields must be present

### Data Anomaly Detection
- Commodity prices in realistic ranges (Gold: $1500-$5000)
- No identical values across all items in a category (indicates placeholders)

## Common Workflows

### Adding New Data Sources

1. Create adapter in `src/datasource/adapters/` inheriting `BaseDataSource`
2. Implement async methods with rate limiting
3. Register in `DataSourceManager.__init__()`
4. Add config to `.env.example` and `indices_config.py`
5. Export in `src/datasource/__init__.py`
6. Add tests

### Debugging Stage Failures

```bash
# Inspect intermediate JSON completeness
python -c "import json; d=json.load(open('data/test.json')); print(d['metadata']['completeness'])"

# Test individual stages
python scripts/stage1_data_collector.py --date 20251113 --output data/test.json
python scripts/stage2a_mcp_enhancer.py --market-data data/test.json --output data/test_enhanced.json
```

### Fund Flow Data Sources

- 北向资金: https://data.eastmoney.com/hsgt/
- 南向资金: https://data.10jqka.com.cn/hgt/
- 融资融券: http://www.sse.com.cn/market/stockdata/statistic/

## Import Patterns

```python
# ✅ Correct - package imports
from datasource import get_manager
from datasource.calculators.pring_analyzer import PringAnalyzer
from datasource.config.indices_config import A_SHARE_INDICES
from datasource.models.market_data_contract import MarketDataContract

# ❌ Avoid - path manipulation (only for standalone scripts)
import sys, os
sys.path.insert(0, ...)
```

## Key Documentation

- `docs/系统技术文档.md` - Complete technical reference (1600+ lines)
- `docs/手动更新资金流向数据指南.md` - Manual fund flow update guide
- `docs/Stage2数据获取设计分析.md` - Stage 2 macro data issue analysis
