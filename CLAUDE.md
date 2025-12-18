# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 沟通约定：与用户的交互和问题说明优先使用中文，命令保持原文。

## Project Overview

Unified financial data integration framework with automatic failover between AKShare, TuShare, and International Finance data sources. Features async support, caching, rate limiting, Pring six-stage analysis with V4.0 three-layer framework, and automated 120-day background scan report generation.

## Quick Reference

### Environment Setup
```bash
# Create virtual environment
python -m venv .venv && source .venv/bin/activate  # Linux/WSL
# python -m venv .venv && .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt && pip install -e . && pip install -e ".[dev]"

# Configure credentials
cp .env.example .env
# Edit .env: TUSHARE_TOKEN, TAVILY_API_KEY, DEEPSEEK_API_KEY

# Verify installation
python -c "from datasource import get_manager; print('OK')"
```

### Preflight Check (Run Before Pipeline)
```bash
# Validates API keys and clears proxy - MUST run before Stage1
set -a; source .env; set +a
for k in TAVILY_API_KEY DEEPSEEK_API_KEY TUSHARE_TOKEN; do
  v=${!k-}; [ -n "$v" ] && [ ${#v} -ge 20 ] || { echo "Missing/short $k"; exit 1; }
done
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

# Optional health check (verifies API connectivity)
PYTHONPATH=./src python3 scripts/stage2_health_check.py
```

### Testing
```bash
pytest -q                                # Quick pytest run
pytest tests/test_file.py::test_name -v  # Run single test
python tests/test_datasource.py          # Core integration tests
black src/ tests/ scripts/ && flake8 src/ && mypy src/datasource/  # Quality checks
```

### Daily Report Pipeline (V4.0)

**⚠️ Critical Rule**: Stage2 Tavily search/extract 每日只能运行一次。失败或 422 后不要重试 Stage2，改用 Stage2.5 手工注入补数。

**Full pipeline (~3-5 min total)**:
```bash
DATE=$(date +%Y%m%d)  # or DATE=20251209
source .venv/bin/activate && source .env

# Stage 1: API data collection (30-40s)
python scripts/stage1_data_collector.py --date $DATE --output data/${DATE}_market_data.json

# Stage 2: Tavily+DeepSeek enhancement (90-150s) - 当日只跑1次！
PYTHONPATH=. python scripts/stage2_unified_enhancer.py \
  --market-data data/${DATE}_market_data.json \
  --output data/${DATE}_market_data_stage2.json \
  --execute-search --fund-flow-backend tavily \
  --cache-backend sqlite --cache-path reports/tavily_cache.sqlite \
  --websearch-results reports/websearch_results_${DATE}_auto.json \
  --gap-monitor reports/gap_monitor_${DATE}.json

# Stage 2+ (optional): Yahoo price fallback for commodities/bonds
PYTHONPATH=. python scripts/fill_market_data_from_yahoo.py \
  --input data/${DATE}_market_data_stage2.json \
  --output data/${DATE}_market_data_stage2_filled.json

# Stage 2.5: WebSearch injection (closes data gaps)
python inject_websearch_data_test.py \
  data/${DATE}_market_data_stage2_filled.json \
  reports/websearch_results_${DATE}_auto.json \
  data/${DATE}_market_data_complete.json

# Stage 3: Pring analysis (15-25s)
PYTHONPATH=. python scripts/stage3_pring_analyzer.py \
  --market-data data/${DATE}_market_data_complete.json \
  --output data/${DATE}_pring_result.json \
  --allow-estimated

# Stage 4: Report generation (10-15s)
PYTHONPATH=. python tests/scripts/generate_simple_report_test.py \
  data/${DATE}_market_data_complete.json \
  data/${DATE}_pring_result.json \
  reports/${DATE}背景扫描120.md

# Verification
cat reports/gap_monitor_${DATE}.json  # Should be [] or {}
```

**Fast mode (regex, no LLM, 30-60s)**:
```bash
PYTHONPATH=. python scripts/stage2_unified_enhancer.py \
  --market-data data/${DATE}_market_data.json \
  --output data/${DATE}_market_data_stage2.json \
  --execute-search --extraction-backend regex --disable-extract
```

**Retry specific gaps**:
```bash
PYTHONPATH=. python scripts/stage2_unified_enhancer.py \
  --market-data data/${DATE}_market_data.json \
  --tasks USDCNY,northbound,etf --execute-search
```

**Post-injection completeness check** (must be ≥80%):
```bash
python -c "
import json
d = json.load(open('data/${DATE}_market_data_complete.json'))
comp = d.get('metadata',{}).get('data_completeness', 0)
print(f'数据完整度: {comp*100:.1f}%')
if comp < 0.8:
    nulls = [f'{cat}.{k}' for cat in ['macro_indicators','monetary_policy','stock_indices']
             for k,v in d.get(cat,{}).items() if isinstance(v,dict) and v.get('current_value') is None]
    print(f'WARNING: Null字段需补充: {nulls}')
"
```

**Stage2.5 Manual Injection** (when Stage2 fails or has gaps):
```bash
# 1. Create/edit manual JSON with real numeric values
# File: reports/websearch_results_${DATE}_manual.json
# Must follow WebSearch JSON Schema (see below)

# 2. Inject and verify
python inject_websearch_data_test.py \
  data/${DATE}_market_data_stage2.json \
  reports/websearch_results_${DATE}_manual.json \
  data/${DATE}_market_data_complete.json

# 3. Verify gaps cleared
cat reports/gap_monitor_${DATE}.json  # Should be [] or {}
```

## Architecture

```
src/datasource/
├── manager.py              # DataSourceManager singleton with failover
├── adapters/               # Thin API wrappers (AKShare, TuShare, InternationalFinance)
├── calculators/            # Technical indicators, Pring analyzer
├── models/                 # MarketDataContract, PringResultContract (THE schemas)
├── config/indices_config.py # All symbols and parameters
└── engines/                # Stage2 LangChain pipeline (experimental)

scripts/
├── stage1_data_collector.py      # API collection
├── stage2_unified_enhancer.py    # Tavily+DeepSeek enhancement
├── stage3_pring_analyzer.py      # Pring three-layer analysis
└── fill_market_data_from_yahoo.py # Price fallback
```

### Key Patterns

**DataSourceManager** returns `DataResponse` with: `data`, `source`, `error`, `metadata`
```python
from datasource import get_manager
manager = get_manager()  # Singleton
response = await manager.get_forex_data("DXY", start, end)
```

**Async-First**: Use `asyncio.gather()` for parallel fetches.

## WebSearch JSON Schema

All fields must contain **parseable numbers**, not descriptive text.

| Category | Required Fields | Example |
|----------|----------------|---------|
| commodities | `symbol`, `name`, `current_price`, `unit` | `{"symbol": "GC=F", "name": "COMEX黄金", "current_price": 2650.5, "unit": "$/oz"}` |
| forex | `pair`, `name`, `current_rate` | `{"pair": "USDCNY", "name": "USD/CNY在岸", "current_rate": 7.248}` |
| bonds | `symbol`, `name`, `current_yield` | `{"symbol": "US10Y", "name": "美国10年期国债", "current_yield": 4.18}` |
| fund_flow | `recent_5d`, `total_120d`, `trend`, `source` | `{"recent_5d": 85.6, "total_120d": 1250.0, "trend": "流入", "source": "MCP WebSearch实时获取"}` |

**Critical**: `recent_5d`/`total_120d` must be numbers (not "波动"/"净流入"). Reference `src/datasource/models/market_data_contract.py` for authoritative schema.

## Stage2 Configuration

### Backends
- **Fund Flow** (`--fund-flow-backend`): `tavily` (default) | `mcp` | `hybrid`
- **Extraction** (`--extraction-backend`): `deepseek` (default) | `langchain` | `regex`

### Key Parameters
```bash
--execute-search              # Execute searches (vs dry-run)
--tasks KEY1,KEY2,...         # Filter specific indicators
--cache-backend sqlite        # Enable SQLite caching
--extraction-backend regex    # Fast mode, no LLM
--disable-extract             # Skip Tavily extract (avoids 422 errors)
--deepseek-timeout 8          # API timeout (seconds)
```

### Environment Variables
```bash
TAVILY_API_KEY=your-key       # Required for Stage2
DEEPSEEK_API_KEY=your-key     # Required for LLM extraction
TUSHARE_TOKEN=your-token      # Required for Stage1
```

## Code Standards

- **Python**: ≥3.7, 4-space indent, UTF-8
- **Naming**: `lower_snake_case` (functions/vars), `CamelCase` (classes), `UPPER_SNAKE_CASE` (constants)
- **Async-First**: All data ops use async/await
- **Thin Adapters**: API wrappers only; business logic in engines/calculators
- **Config-Driven**: Use `indices_config.py`, avoid hardcoded values
- **Commits**: Conventional (`feat:`, `fix:`, `refactor:`)
- **Windows**: Prefix `PYTHONIOENCODING=utf-8` for Chinese output
- **Data Integrity**: 严禁从历史 `reports/*.md` 中抓取或复用数据；所有数据必须来自 API 实时获取或 stage 计算产出
- **Tavily Throttling**: 同日 Stage2 只跑 1 次；422/失败后改用 Stage2.5 手工注入

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Stage2 DeepSeek timeout | `--extraction-backend regex --disable-extract` |
| Tavily extract 422 | Add `--disable-extract` or `--extract-topk 1`; don't retry Stage2 same day |
| Stage3 completeness <80% | Check macro/monetary/stock_indices nulls, re-inject |
| Report shows N/A | Check gap_monitor, ensure numeric fields |
| Proxy issues | Prefix: `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY ...` |
| SyntaxError on startup | `python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py` |
| KeyError in injection | Check WebSearch JSON has all required fields per schema above |

## Key Documentation

- **AGENTS.md**: Coding standards, daily run playbook, fund flow data standard, Stage2.5 detailed workflow
- **docs/系统技术文档.md**: Complete technical reference (1600+ lines)
- **src/datasource/models/market_data_contract.py**: THE authoritative data schema (Pydantic models for all data types)
