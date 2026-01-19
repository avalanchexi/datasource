# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 沟通约定：与用户的交互和问题说明优先使用中文，命令保持原文。

## Project Overview

统一金融数据集成框架，支持 TuShare、AKShare、InternationalFinance 数据源自动故障转移。集成 Tavily+DeepSeek 网络搜索增强（Exa 作为 Tavily 422/失败兜底）、Pring 六阶段经济周期分析 (V4.0 三层框架)，以及 120 日背景扫描报告自动生成。

**核心数据流**: Stage1 (API采集) → Stage2 (Tavily+DeepSeek增强) → Stage2.5 (手工注入补缺) → Stage3 (Pring分析) → Stage4 (报告生成)

## Critical Constraints

- **Tavily 每日限制**: Stage2 Tavily search/extract 每日只能运行一次。遇到 422 会自动回退 DeepSeek 从原始 snippets 抽取，但仍不要重试 Stage2；缺口改用 Stage2.5 手工注入补数
- **数据来源约束**: 严禁从历史 `reports/*.md` 中抓取或复用数据；所有数据必须来自 API 实时获取或 stage 计算产出
- **完整度要求**: Stage3 需要 `data_completeness ≥ 80%`，否则报告会有缺失

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
# Optional: EXA_API_KEY (Tavily fallback when 422/failures)

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

# Syntax pre-check (run if encountering SyntaxError on startup)
python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py
```

### Testing
```bash
pytest -q                                # Quick pytest run
pytest tests/test_file.py::test_name -v  # Run single test
python tests/test_datasource.py          # Core integration tests
black src/ tests/ scripts/ && flake8 src/ && mypy src/datasource/  # Quality checks
```

### Daily Report Pipeline (V4.0)

```bash
DATE=$(date +%Y%m%d)  # or DATE=20251209
source .venv/bin/activate && source .env

# Stage 0.5 (optional): Scan trend_history gaps
PYTHONPATH=./src python3 scripts/trend_history_scan.py --date "$DATE"

# Stage 1: API data collection
python scripts/stage1_data_collector.py --date $DATE --output data/${DATE}_market_data.json

# Stage 2: Tavily+DeepSeek enhancement (当日只跑1次！)
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

# Stage 3: Pring analysis (--allow-estimated 允许 is_estimated=True 数据参与评分)
PYTHONPATH=. python scripts/stage3_pring_analyzer.py \
  --market-data data/${DATE}_market_data_complete.json \
  --output data/${DATE}_pring_result.json \
  --allow-estimated

# Stage 4: Report generation
PYTHONPATH=. python tests/scripts/generate_simple_report_test.py \
  data/${DATE}_market_data_complete.json \
  data/${DATE}_pring_result.json \
  reports/${DATE}背景扫描120.md

# Verification
cat reports/gap_monitor_${DATE}.json  # Should be [] or {}
```

**Fast mode (regex, no LLM)**:
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
# 注入结束会自动输出 is_estimated=True 的字段清单，便于定位仍需补数的指标

# 3. Verify gaps cleared
cat reports/gap_monitor_${DATE}.json  # Should be [] or {}
```

## Architecture

核心目录结构（详见 README.md）：

| 目录 | 职责 |
|------|------|
| `src/datasource/manager.py` | DataSourceManager 单例，故障转移 |
| `src/datasource/adapters/` | API 适配器（TuShare、AKShare、Tavily、Exa） |
| `src/datasource/mcp_adapter.py` | MCP 工具适配器（方案C：生成 AI 可执行提示词） |
| `src/datasource/models/` | Pydantic 数据模型（MarketDataContract、PringResultContract） |
| `src/datasource/config/` | 配置（indices_config.py、search_profiles.py） |
| `src/datasource/engines/` | Stage2 管道（deepseek_reasoner、task_planner） |
| `src/datasource/calculators/` | 技术指标、Pring 分析器、资金流、债券计算 |
| `src/datasource/utils/` | 工具模块（data_completion、observability、policy_rules 等） |
| `config/` | 根配置（quality_thresholds.json、policy_rules.yaml） |
| `data/trend_history/` | 趋势历史滚动窗口（JSON，非 SQLite） |
| `scripts/` | Stage 脚本（stage1/2/3、trend_history_scan/backfill、run_snapshot） |

### Config Files

| 文件 | 作用 |
|------|------|
| `config/quality_thresholds.json` | 数据质量阈值（波动率、陈旧度） |
| `config/policy_rules.yaml` | 策略规则（422 阈值、关键缺失字段、最小交易日） |

### MCP Adapter (方案C)

`src/datasource/mcp_adapter.py` 为 AI 手工执行模式设计：
- 生成结构化提示词，供 AI 在对话中执行 WebSearch/WebFetch
- 不直接调用 MCP 工具，适合快速原型
- 收集 AI 执行结果并验证

### Trend History Rules
- 股指：200 交易日窗口；外汇/商品/债券：121 交易日；资金流：120 交易日
- 宏观/政策事件：6–12 条
- 写入策略：Stage1 写入 `is_partial=true`，Stage2.5 最终覆盖
- 禁止从 `reports/*.md` 反向回填
- 写入防护：过滤低质量标记（如“数值超出合理区间”“异常零值”“regex_only且缺少发布机构”）；CN10Y/CN10Y_CDB 禁止 ETF 代理写入；回补脚本跳过 `bond_etf_proxy` 来源；“真实范围”仅用于复盘展示，不作为硬性校验

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
--disable-extract             # Skip Tavily extract; force DeepSeek/regex from snippets (use when 422频发)
--deepseek-timeout 8          # API timeout (seconds)
```

### Environment Variables
```bash
TUSHARE_TOKEN=your-token      # Required for Stage1
TAVILY_API_KEY=your-key       # Required for Stage2
DEEPSEEK_API_KEY=your-key     # Required for LLM extraction
EXA_API_KEY=your-key          # Optional: Exa fallback (auto-enabled when Tavily 422/fails)
```

### Exa Fallback Behavior
当 `EXA_API_KEY` 已配置且 Tavily 返回 422 或其他失败时，Stage2 自动尝试 Exa 搜索作为兜底。Exa 结果会转换为 Tavily 兼容格式，无需额外代码改动。若 Exa 也失败，任务落入 `gap_monitor` 由 Stage2.5 手工补数。

## Code Standards

- **Python**: ≥3.7, 4-space indent, UTF-8；async-first（使用 `asyncio.gather()` 并行获取）
- **Naming**: `lower_snake_case` (functions/vars), `CamelCase` (classes), `UPPER_SNAKE_CASE` (constants)
- **Commits**: Conventional (`feat:`, `fix:`, `refactor:`)
- **详细规范**: 见 AGENTS.md（Thin Adapters、Config-Driven 等）

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Stage2 DeepSeek timeout | `--extraction-backend regex --disable-extract` |
| Tavily extract 422 | 默认回退 DeepSeek 解析 snippets；不稳可用 `--disable-extract` 或 `--extract-topk 1` |
| Tavily repeated 422 | Don't retry Stage2 same day; use Stage2.5 manual injection; check `extract_fallback_to_deepseek` in Stage2 Summary |
| Stage3 completeness <80% | Check macro/monetary/stock_indices nulls, re-inject |
| Report shows N/A | Check gap_monitor, ensure numeric fields |
| Proxy issues | Prefix: `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY ...` |
| SyntaxError on startup | `python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py` |
| KeyError in injection | Check WebSearch JSON has all required fields per schema above |

## Utility Scripts

```bash
# 生成运行审计快照（记录 git 状态、CLI 参数、环境变量）
python scripts/run_snapshot.py --output reports/run_snapshot_${DATE}.json --args "stage2 args..."
```

## Output Files

| Stage | Output | Purpose |
|-------|--------|---------|
| Stage1 | `data/${DATE}_market_data.json` | Raw API data |
| Stage2 | `data/${DATE}_market_data_stage2.json` | Tavily-enhanced data |
| Stage2 | `reports/websearch_results_${DATE}_auto.json` | Search results for injection |
| Stage2 | `reports/gap_monitor_${DATE}.json` | Missing data tracker |
| Stage2 | `reports/quality_metrics_${DATE}.json` | Data quality metrics |
| Stage2 | `logs/observability_${DATE}.json` | Per-indicator timing/source/failure |
| Stage2 | `reports/source_conflicts_${DATE}.json` | Conflict resolution log |
| Stage2 | `reports/policy_evaluation_${DATE}.json` | Policy evaluation results |
| Stage2 | `reports/run_snapshot_${DATE}.json` | Run audit snapshot |
| Stage2+ | `data/${DATE}_market_data_stage2_filled.json` | Yahoo price fallback |
| Stage2.5 | `data/${DATE}_market_data_complete.json` | Injection-completed data |
| Stage3 | `data/${DATE}_pring_result.json` | Pring analysis output |
| Stage4 | `reports/${DATE}背景扫描120.md` | Final report |

## Key Documentation

- **AGENTS.md**: 详细编码规范、日报流程、资金流数据标准、Stage2.5 工作流
- **docs/系统技术文档.md**: 完整技术参考（1600+ 行）
- **src/datasource/models/market_data_contract.py**: 权威数据模型定义
