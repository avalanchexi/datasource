# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Start Here**: Review [AGENTS.md](AGENTS.md) for repository layout and coding standards.

## Quick Reference

### Most Common Command (Automated Report Generation)
```bash
# Daily Run Playbook - Full pipeline from AGENTS.md
# Set target date (or use current date)
DATE=$(date +%Y%m%d)  # Linux/Mac
# DATE=20251123       # Windows manual override

# Activate environment
source .venv/bin/activate && source .env  # Linux/Mac
# .venv\Scripts\activate && set -a && type .env | findstr /V "^#" | findstr /V "^$" > temp.env && for /f "tokens=*" %a in (temp.env) do set %a  # Windows

# Stage 1: Collect raw data from APIs
python scripts/stage1_data_collector.py --date $DATE --output data/${DATE}_market_data.json

# Stage 2: WebSearch enhancement (covers fund_flow/commodities/forex/bonds)
PYTHONPATH=. python scripts/stage2_unified_enhancer.py \
  --market-data data/${DATE}_market_data.json \
  --output data/${DATE}_market_data_stage2.json \
  --execute-search \
  --fund-flow-backend tavily \
  --cache-backend sqlite \
  --cache-path reports/tavily_cache.sqlite \
  --websearch-results reports/websearch_results_${DATE}_auto.json \
  --log-output logs/stage2_unified_log_${DATE}.json \
  --gap-monitor reports/gap_monitor_${DATE}.json

# Note: For gap retry, use --tasks key1,key2,... to filter specific indicators
# Example: --tasks USDCNY,northbound,etf

# Stage 2 Price Fallback (optional, for commodities/bonds if needed)
PYTHONPATH=. python scripts/fill_market_data_from_yahoo.py \
  --input data/${DATE}_market_data_stage2.json \
  --output data/${DATE}_market_data_stage2_filled.json

# WebSearch Injection (closes the loop)
python inject_websearch_data_test.py \
  data/${DATE}_market_data_stage2_filled.json \
  reports/websearch_results_${DATE}_auto.json \
  data/${DATE}_market_data_complete.json

# For manual gaps: edit websearch_results_${DATE}.json and re-run injection

# Stage 3: Pring Analysis
PYTHONPATH=. python scripts/stage3_pring_analyzer.py \
  --market-data data/${DATE}_market_data_complete.json \
  --output data/${DATE}_pring_result.json

# Report Generation
PYTHONPATH=. python tests/scripts/generate_simple_report_test.py \
  data/${DATE}_market_data_complete.json \
  data/${DATE}_pring_result.json \
  reports/${DATE}背景扫描120.md

# Verification
# - gap_monitor should be empty or minimal
# - Report should not contain "N/A（待 WebSearch）"
cat reports/gap_monitor_${DATE}.json  # Should be [] or {}
powershell -Command "(Get-Item 'reports/${DATE}背景扫描120.md').Length"  # Expect ~4800-5200 bytes
```

### Environment Setup
```bash
# Windows
python -m venv .venv && .venv\Scripts\activate
# Linux/WSL
python -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt && pip install -e . && pip install -e ".[dev]"
cp .env.example .env
# Edit .env to add your TUSHARE_TOKEN, TAVILY_API_KEY, DEEPSEEK_API_KEY
python -c "from datasource import get_manager; print('OK')"  # Verify installation
```

### Testing
```bash
# Quick validation (from AGENTS.md)
datasource-test                              # CLI entry point
pytest -q                                    # Quick pytest run

# Focused test suites
python tests/test_datasource.py              # Core integration tests
python tests/simple_test.py                  # Simple tests
python tests/test_na_filling.py              # N/A filling tests

# Quality checks (run before commits)
black src/ tests/ scripts/                   # Code formatting
flake8 src/                                  # Linting
mypy src/datasource/                         # Type checking
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

## V4.0+ Multi-Stage Pipeline (4 stages, ~3-5min)

### Pipeline Overview

| Stage | Script | Time | Completeness | Output |
|-------|--------|------|-------------|--------|
| 1 | `stage1_data_collector.py` | 30-40s | 25-42% | market_data.json |
| 2 | `stage2_unified_enhancer.py` (Tavily+DeepSeek) | 90-150s | **85-95%** | market_data_stage2.json |
| 2+ | `inject_websearch_data_test.py` (optional補完) | 10-20s | **95%+** | market_data_complete.json |
| 3 | `stage3_pring_analyzer.py` | 15-25s | Analysis | pring_result.json |
| 4 | `generate_simple_report_test.py` | 10-15s | Report | DATE背景扫描120.md |
| 验证 | powershell file size check | 5s | Validation | - |

### Stage Details

**Stage 1**: API data collection via DataSourceManager
- ✅ Stock indices (000001, 000300, 000016, 399001, 399006, 000905, 000688)
- ✅ US indices (SPX, DJI, IXIC via international_finance_adapter)
- ✅ Forex basics (USDCNY, DXY via AKShare/TuShare)
- ✅ US10Y yield (via international_finance_adapter)
- ⚠️ Placeholders: macro (PPI, PMI, Industrial, BDI, CPI), monetary (RRR, Repo, MLF, TSF, M2), fund_flow, CN bonds, commodities

**Stage 2**: Unified enhancer with multi-backend support
- **Search**: Tavily API for real-time data (forex, bonds, commodities, fund flows, macro, monetary)
- **Extraction**: DeepSeek LLM (via OpenAI-compatible API) or LangChain pipeline, with regex fallback
- **Cache**: SQLite-based cache for Tavily results (default TTL: 3600s)
- **Output**: Enriched market_data_stage2.json + websearch_results_auto.json + gap_monitor.json
- **Backends**:
  - `--fund-flow-backend`: tavily (default) | mcp | hybrid
  - `--extraction-backend`: deepseek (default) | langchain | regex
- **LangChain Mode** (experimental):
  ```bash
  --extraction-backend langchain \
  --lc-max-concurrency 3 \
  --lc-timeout 8.0
  ```
  Provides structured extraction with retry, timeout, and automatic regex fallback

**Stage 2+**: WebSearch injection (补完)
- Fill remaining gaps via manual WebSearch or MCP tools
- Use `inject_websearch_data_test.py` to merge custom websearch_results JSON
- Handles: forex, bonds, commodities, macro, monetary, fund_flow categories

**Stage 3**: Pring Three-Layer Analysis (`PringAnalyzer`)
- Layer 1: Inventory Cycle (PPI, PMI, commodities) → 60 points max
- Layer 2: Monetary Cycle (RRR, M2, bonds) → 100 points max
- Layer 3: Final Pring Six-Stage determination (Stage I-VI)
- Output: Detailed pring_result.json with stage, scores, and confidence

**Stage 4**: Markdown report generation
- 9 sections: 核心结论, 股票市场, 商品与黄金, 债券市场, 外汇市场, 宏观经济指标, 货币政策, Pring三层框架, 资金流向
- Uses Jinja2 templates from `templates/`
- Chinese output requires `PYTHONIOENCODING=utf-8` on Windows

**验证**: `powershell -Command "(Get-Item 'reports\DATE背景扫描120.md').Length"` → expect ~4800-5200 bytes

## Stage2 Configuration Guide

### Search & Extraction Backends

**Fund Flow Backend** (`--fund-flow-backend`):
- `tavily` (default): Direct Tavily search with DeepSeek/regex extraction, marks source as `tavily+deepseek`
- `mcp`: Skip online search, gap_monitor records pending status, awaits MCP/manual injection
- `hybrid` (recommended): Tries Tavily first, marks `manual_required` on failure/zero-value for MCP/manual補完

**Extraction Backend** (`--extraction-backend`):
- `deepseek` (default): OpenAI-compatible DeepSeek API for structured extraction
- `langchain`: LangChain pipeline with Tavily + DeepSeek, auto-fallback to regex on timeout/error
- `regex`: Pure regex extraction from snippets (fast but lower confidence, no LLM required)

### Data Priority & MCP Integration (from AGENTS.md)

**Fund Flow Data Priority**:
1. **MCP WebSearch** (primary): Real-time data from 东方财富网、同花顺、每日经济新闻
2. **Anomaly Detection**: Zero/empty values trigger immediate re-verification

**Requirements**:
- 北向/南向/ETF/融资融券: Use MCP WebSearch for real-time acquisition, avoid AKShare
- Zero/missing data: Must mark as "异常零值-需核查" with source annotation in note
- Source annotation: "MCP WebSearch实时获取" or "异常零值-需核查"

**Data Format**:
```python
{
    'recent_5d': 123.45,       # 近5日流向(亿元) - must be parseable number
    'total_120d': 456.78,      # 近120日累计(亿元) - not descriptive text
    'trend': '流入' or '流出',
    'source': 'MCP WebSearch实时获取' or '异常零值-需核查',
    'note': '来源:东方财富网'  # Optional, detailed provenance
}
```

### MCP Tool Usage Guidelines

- **WebSearch**: For real-time financial data (fund flows, commodities, forex, bonds, news)
- **WebFetch**: For direct API calls (Yahoo Finance, specific endpoints)
- **Fallback Logic**: 实时类数据全部由 MCP WebSearch 获取；若 WebSearch 不可用，记录提示并等待人工补数
- **Data Annotation**: All MCP-sourced data must be clearly labeled in reports
- **Error Handling**: Log MCP failures and auto-switch to fallback sources

### Key Parameters

```bash
# Core
--market-data FILE              # Input JSON from Stage1
--output FILE                   # Output market_data_stage2.json
--execute-search                # Execute Tavily searches (vs. dry-run)
--tasks KEY1,KEY2,...           # Filter to specific indicators (e.g., USDCNY,US10Y)

# Caching
--cache-backend sqlite|memory|none
--cache-path PATH               # SQLite DB path (default: reports/tavily_cache.sqlite)
--cache-ttl SECONDS             # Cache TTL (default: 3600)

# LangChain mode
--lc-max-concurrency N          # Max concurrent LangChain tasks (default: 3)
--lc-timeout SECONDS            # Per-task timeout (default: 8.0)

# DeepSeek
--deepseek-timeout SECONDS      # DeepSeek API timeout (default: 10)
--deepseek-max-concurrency N    # Max concurrent DeepSeek calls (default: 2)
--deepseek-model MODEL          # Model name (default: deepseek-chat)
--deepseek-base-url URL         # API base URL (default: https://api.deepseek.com/v1)

# Outputs
--websearch-results FILE        # Save websearch results JSON (auto-generated)
--log-output FILE               # Stage2 summary log
--gap-monitor FILE              # Unsatisfied indicators list
--task-file FILE                # Task definitions (for resume, future)
```

### Environment Variables

```bash
# Required
TAVILY_API_KEY=your-tavily-key
DEEPSEEK_API_KEY=your-deepseek-key  # Optional for regex-only mode
TUSHARE_TOKEN=your-tushare-token

# Optional
STAGE2_SEARCH_BACKEND=tavily  # Default search backend
```

### Retry & Gap Handling

If Stage2 produces gaps (`gap_monitor.json` not empty):

1. **Retry specific indicators** (from AGENTS.md):
   ```bash
   # Example gap list: USDCNY,USDCNH,DXY,GC=F,CL=F,BZ=F,HG=F,BCOM,GSG,US10Y,CN10Y,CN10Y_CDB,northbound,southbound,etf,rrr,reverse_repo,mlf,000016
   PYTHONPATH=. python scripts/stage2_unified_enhancer.py \
     --market-data data/${DATE}_market_data.json \
     --tasks USDCNY,northbound,etf \
     --execute-search
   ```

2. **MCP補数 workflow** (for fund flow gaps):
   - If gap_monitor shows `northbound/southbound/etf` pending
   - Manually create/edit `data/websearch_results_${DATE}.json`
   - Format per fund flow data schema with "MCP WebSearch实时获取" source
   - Run `inject_websearch_data_test.py` → Stage3 → Report generation

3. **Switch to regex fallback** (if DeepSeek unstable):
   ```bash
   --extraction-backend regex
   ```

### Proxy Configuration (from AGENTS.md)

**Recommended**: Direct connection without proxy for production

**If proxy required**:
```bash
# Set in .env or export
export HTTP_PROXY=http://127.0.0.1:10809
export HTTPS_PROXY=http://127.0.0.1:10809
export NO_PROXY="localhost,127.0.0.1,::1,10.0.0.0/8,192.168.0.0/16"

# Verify Tavily connectivity
python - <<'PY'
import httpx
print(httpx.get('https://api.tavily.com', timeout=5, proxies=None).status_code)
PY
```

**Disable proxy completely**:
```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  python scripts/stage2_unified_enhancer.py ...
```

**Priority**: CLI `--http-proxy/--https-proxy` > environment variables

### Stage2 Data Acquisition Priority (from AGENTS.md)

**Priority Order**:
1. **MCP 优先**: `--fund-flow-backend mcp` or `--forex-backend mcp` → Skip online search, mark pending for MCP injection
2. **Tavily 次之**: `--fund-flow-backend tavily` → Direct Tavily search
3. **Hybrid**: `--fund-flow-backend hybrid` → MCP→Tavily fallback (Tavily first, mark manual_required on failure)
4. **WebSearch 最后补充**: Tavily fails → Use `websearch_results_${DATE}.json` (manual/MCP WebSearch) + `inject_websearch_data_test.py`
5. **行情兜底**: Run `scripts/fill_market_data_from_yahoo.py` after Stage2, then WebSearch injection for commodities/bonds/forex gaps

### LangChain Extraction Mode (from AGENTS.md)

**Enable**:
```bash
--extraction-backend langchain
```

**Dependencies**: `langchain`, `langchain-community`, `tavily-python`, `openai` (install via `pip install -e ".[dev]"`)

**Configuration**:
```bash
--lc-max-concurrency 3    # Max concurrent LangChain tasks (default: 3)
--lc-timeout 8.0           # Per-task timeout in seconds (default: 8.0)
--deepseek-model deepseek-chat        # DeepSeek model name
--deepseek-base-url https://api.deepseek.com/v1  # API base URL
```

**Behavior**:
- task_log adds: `extraction_backend`, `llm_latency_ms`, `llm_error`
- websearch_results marks extraction backend
- Auto-fallback to regex on DeepSeek timeout/error

**Priority**: MCP → Tavily+DeepSeek(LangChain) → Manual/WebSearch JSON injection

## Code Standards (from AGENTS.md)

### Coding Style & Naming
- **Python Version**: Support Python ≥3.7
- **Indentation**: Four-space indentation, UTF-8 files
- **Naming Conventions**:
  - `lower_snake_case` for modules, variables, and functions
  - `CamelCase` for classes
  - `UPPER_SNAKE_CASE` for constants (when required)
- **Comments**: Comment only to clarify non-obvious intent

### Architecture Principles
- **Async-First**: All data ops use async/await, align with `DataSourceManager`
- **Thin Adapters**: API wrappers only; business logic in engines/calculators
- **Config-Driven**: Configure behavior through `indices_config.py` rather than embedding literals
- **Model Contracts**: Always reference `src/datasource/models/market_data_contract.py` and `pring_result_contract.py` for field schemas

### Platform Support
- **Windows Primary**: Use Windows path handling; prefix `PYTHONIOENCODING=utf-8` for Chinese output
- **Cross-platform**: Ensure compatibility with Linux/WSL

### Development Practices
- **No Temp Scripts**: Modify existing scripts, don't create new ones
- **Security**: Keep secrets out of repo; use `.env` for credentials, never commit secrets
- **Reports**: Generated markdown reports go to `reports/` and require review before merging
- **Templates**: Stay in `templates/` directory

### Commit Guidelines
- **Format**: Follow Conventional Commits (`feat:`, `fix:`, `refactor:`) scoped to a single logical change
- **Pull Requests**:
  - Outline scope, link issues
  - Enumerate commands run
  - Include before/after snippets for template or report changes
  - Run quality checks: `black src/ tests/ scripts/`, `flake8 src/`, `mypy src/datasource/`
  - Document any skipped checks

## AI Execution Workflow

When user requests "生成报告" or "执行背景扫描报告生成：DATE":

### Todo List Template (V4.0+)
```json
[
  {"content": "STAGE 1: API数据收集", "status": "pending", "activeForm": "API数据收集中(30-40s)"},
  {"content": "STAGE 2: Tavily+DeepSeek增强(自动化)", "status": "pending", "activeForm": "Tavily+DeepSeek增强中(90-150s)"},
  {"content": "检查gap_monitor并补全(如需)", "status": "pending", "activeForm": "检查并补全缺失数据"},
  {"content": "STAGE 3: Pring三层框架分析", "status": "pending", "activeForm": "Pring分析中(15-25s)"},
  {"content": "STAGE 4: Markdown报告生成", "status": "pending", "activeForm": "报告生成中(10-15s)"},
  {"content": "验证报告数据完整性", "status": "pending", "activeForm": "验证数据完整性中"}
]
```

### Stage2 Automated Coverage (via Tavily)

Stage2 unified enhancer automatically searches for **~35 indicators** across 6 categories:

**Forex (6)**: USDCNY, USDCNH, EURCNY, JPYCNY, DXY, USDX
**Commodities (9)**: Gold (GC=F, XAUUSD), Oil (CL=F, BZ=F), Copper (HG=F), BCOM, GSG, Silver, Platinum
**Bonds (3)**: US10Y, CN10Y, CN10Y_CDB (政金债)
**Macro (5)**: PPI, PMI, Industrial Production, BDI, CPI
**Monetary (6)**: RRR, Reverse Repo 7D, MLF, TSF Growth, M1 Growth, M2 Growth
**Fund Flows (4)**: Northbound (北向), Southbound (南向), ETF, Margin Trading (融资融券)

**How it works**:
1. Tavily searches with optimized queries (defined in `src/datasource/config/search_profiles.py`)
2. DeepSeek extracts structured data from search snippets (value, unit, issuer, date)
3. Results cached in SQLite for efficiency
4. Gaps tracked in `gap_monitor.json` for manual補完

**Manual補完** (only if gaps remain):
- Check `reports/gap_monitor_DATE.json` for missing indicators
- Use Claude's WebSearch tool or MCP to gather data
- Format as `websearch_results_DATE.json` following schema in `inject_websearch_data_test.py`
- Run injection script to merge

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
6. Add tests in `tests/`

### Adding New Indicators to Stage2

1. Define search profile in `src/datasource/config/search_profiles.py`:
   ```python
   {
       "indicator_key": "MY_INDICATOR",
       "query": "search query with keywords",
       "category": "macro|monetary|forex|bonds|commodities|fund_flow",
       "unit": "expected unit (%, CNY, etc.)",
       "issuer": "authoritative source name",
       "confidence_threshold": 0.6
   }
   ```
2. Add field to `MarketDataContract` in `src/datasource/models/market_data_contract.py`
3. Update `inject_websearch_data_test.py` mapping if needed
4. Run Stage2 with `--tasks MY_INDICATOR` to test

### Debugging Pipeline Failures

```bash
# Check Stage1 completeness
python -c "import json; d=json.load(open('data/DATE_market_data.json')); \
  print(f\"Completeness: {d['metadata']['completeness']}%\")"

# Check Stage2 gaps
cat reports/gap_monitor_DATE.json | python -m json.tool

# Review Stage2 task log for specific indicator
grep 'USDCNY' logs/stage_task_log.jsonl | python -m json.tool

# Test individual stages
python scripts/stage1_data_collector.py --date 20251123 --output data/test.json
PYTHONPATH=. python scripts/stage2_unified_enhancer.py \
  --market-data data/test.json --tasks USDCNY --execute-search --extraction-backend regex
PYTHONPATH=. python scripts/stage3_pring_analyzer.py \
  --market-data data/test_complete.json --output data/test_pring.json
```

### Handling Network/API Issues

**Tavily timeout/errors**:
```bash
# Switch to regex-only mode (no DeepSeek)
--extraction-backend regex

# Increase timeout
--deepseek-timeout 15

# Disable proxy if interfering
env -u http_proxy -u https_proxy python scripts/stage2_unified_enhancer.py ...
```

**DeepSeek API errors**:
```bash
# Fallback to regex extraction
--extraction-backend regex

# Or use LangChain mode with auto-fallback
--extraction-backend langchain --lc-timeout 10
```

**API rate limits (Stage1)**:
- AKShare/TuShare rate limits are handled automatically by `RateLimiter` in adapters
- Check `.env` for `AKSHARE_RATE_LIMIT` and `TUSHARE_RATE_LIMIT` settings
- Wait time is logged; increase rate limit values if needed

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

## Project Structure & Key Files

```
datasource/
├── src/datasource/              # Core library
│   ├── __init__.py             # Main exports: get_manager()
│   ├── manager.py              # DataSourceManager (singleton)
│   ├── adapters/               # Thin API wrappers (AKShare, TuShare, InternationalFinance)
│   ├── calculators/            # Technical indicators, Pring analyzer, bond calc
│   ├── engines/                # Data engines, Stage2 LangChain pipeline
│   │   └── stage2_lc_pipeline.py  # LangChain-based extraction (experimental)
│   ├── config/                 # Configuration management
│   │   └── indices_config.py   # A_SHARE_INDICES, US_INDICES, TECHNICAL_PARAMS
│   ├── models/                 # Pydantic contracts
│   │   ├── market_data_contract.py   # MarketDataContract (THE schema)
│   │   └── pring_result_contract.py  # PringResultContract
│   └── utils/                  # Rate limiter, retry logic
├── scripts/                    # Pipeline stages & utilities
│   ├── stage1_data_collector.py      # Stage1: API collection
│   ├── stage2_unified_enhancer.py    # Stage2: Tavily+DeepSeek enhancement
│   ├── stage3_pring_analyzer.py      # Stage3: Pring analysis
│   ├── stage4_report_generator.py    # Stage4: Markdown generation
│   ├── fill_market_data_from_yahoo.py  # Commodity/bond price fallback
│   └── utility/                # Helper scripts
│       └── background_scan_120d_generator.py  # Legacy 120d generator
├── tests/                      # Tests & integration scripts
│   ├── test_datasource.py      # Core integration tests
│   └── scripts/                # Test runners
│       ├── run_pring_analysis_test.py        # Stage3 wrapper
│       └── generate_simple_report_test.py    # Stage4 wrapper
├── docs/                       # Documentation
│   ├── 系统技术文档.md          # Complete technical reference (1600+ lines)
│   ├── stage2_unified_runbook.md  # Stage2 operational guide
│   ├── stage2_langchain_plan.md   # LangChain integration design
│   └── AI背景扫描报告执行完整手册.md  # AI execution guide
├── inject_websearch_data_test.py  # WebSearch result injection script
├── data/                       # Intermediate JSON files
├── reports/                    # Generated markdown reports
│   ├── tavily_cache.sqlite     # Tavily search cache
│   └── gap_monitor_*.json      # Missing indicators tracker
└── logs/                       # Execution logs
    └── stage_task_log.jsonl    # Per-task execution log
```

## Key Documentation

### Technical References
- **`AGENTS.md`** - **START HERE**: Repository layout, coding standards, commit guidelines, Daily Run Playbook
- `docs/系统技术文档.md` - Complete technical reference (1600+ lines)
- `docs/stage2_unified_runbook.md` - Stage2 Tavily+DeepSeek operational guide
- `docs/stage2_langchain_plan.md` - LangChain integration design (experimental)
- `docs/AI背景扫描报告执行完整手册.md` - AI report generation manual
- `docs/资金流向数据获取优化说明.md` - Fund flow data acquisition optimization (referenced in AGENTS.md)

### Schemas & Contracts
- `src/datasource/models/market_data_contract.py` - **THE authoritative schema** for all market data
  - ALWAYS reference before creating JSON or modifying data structures
  - Defines: StockIndex, Forex, Commodity, BondYield, MacroIndicator, MonetaryPolicy, FundFlowData
  - **Critical**: Fund flow fields (`recent_5d`, `total_120d`) must contain parseable numbers, not descriptive text
- `src/datasource/models/pring_result_contract.py` - Pring analysis output schema
- `src/datasource/config/indices_config.py` - Symbol mappings, technical parameters

### Configuration Files
- `.env` - Credentials (TUSHARE_TOKEN, TAVILY_API_KEY, DEEPSEEK_API_KEY)
- `src/datasource/config/search_profiles.py` - Stage2 search query definitions

### Code Locations (from AGENTS.md)
**Fund Flow MCP Integration**:
- `scripts/utility/background_scan_120d_generator.py`:
  - `BackgroundScan120DGeneratorFixed._get_fund_flow_websearch()` (lines 318-359)
  - `BackgroundScan120DGeneratorFixed.collect_fund_flow_data()` (lines 361-545)
  - `BackgroundScan120DGeneratorFixed.generate_fund_flow_table()` (lines 648-728)
