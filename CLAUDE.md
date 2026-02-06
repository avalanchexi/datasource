# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 沟通约定：与用户的交互和问题说明优先使用中文，命令保持原文。

## Project Overview

统一金融数据集成框架，支持 TuShare、AKShare、InternationalFinance 数据源自动故障转移。集成 Tavily+DeepSeek 网络搜索增强（Exa 作为 Tavily 422/失败兜底）、Pring 六阶段经济周期分析 (V4.0 三层框架)，以及 120 日背景扫描报告自动生成。

**核心数据流**: Stage1 (API采集) → Stage2 (Tavily+DeepSeek增强) → Stage2.5 (手工注入补缺) → Stage3 (Pring分析) → Stage4 (报告生成)

## Critical Constraints

- **Tavily 每日限制**: Stage2 Tavily search/extract **每日只能运行一次**。遇到 422 会自动回退 DeepSeek 从原始 snippets 抽取，但仍不要重试 Stage2；缺口改用 Stage2.5 手工注入补数
- **数据来源约束**: 严禁从历史 `reports/*.md` 中抓取或复用数据；所有数据必须来自 API 实时获取或 stage 计算产出
- **完整度要求**: Stage3 需要 `data_completeness ≥ 80%`，否则报告会有缺失
- **手工补数验证**: 所有手工填写的数值必须通过 WebSearch 验证后再填入，禁止凭记忆填写汇率、指数等高精度数值
- **Exa 自动兜底**: 当 `EXA_API_KEY` 已配置时，Tavily 422/5xx/空结果会自动触发 Exa fallback

## Quick Start

```bash
# 环境设置
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e . && pip install -e ".[dev]"
cp .env.example .env  # 编辑填入 TUSHARE_TOKEN, TAVILY_API_KEY, DEEPSEEK_API_KEY

# 验证安装
python -c "from datasource import get_manager; print('OK')"

# 预检（每次运行流水线前必跑）
bash run_preflight.sh
```

## Testing

```bash
pytest -q                                # 快速测试
pytest tests/test_file.py::test_name -v  # 单测
python tests/test_datasource.py          # 集成测试
black src/ tests/ scripts/ && flake8 src/ && mypy src/datasource/  # 代码质量
```

## Daily Report Pipeline

```bash
DATE=$(date +%Y%m%d)
source .venv/bin/activate && source .env

# Stage 1: API 数据采集
python scripts/stage1_data_collector.py --date $DATE --output data/${DATE}_market_data.json

# Stage 2: Tavily+DeepSeek 增强（当日只跑1次！）
PYTHONPATH=. python scripts/stage2_unified_enhancer.py \
  --market-data data/${DATE}_market_data.json \
  --output data/${DATE}_market_data_stage2.json \
  --execute-search --fund-flow-backend tavily \
  --cache-backend sqlite --cache-path reports/tavily_cache.sqlite \
  --websearch-results reports/websearch_results_${DATE}_auto.json \
  --gap-monitor reports/gap_monitor_${DATE}.json

# Stage 2.5: WebSearch 注入补缺
python inject_websearch_data_test.py \
  data/${DATE}_market_data_stage2.json \
  reports/websearch_results_${DATE}_auto.json \
  data/${DATE}_market_data_complete.json

# Stage 3: Pring 分析
PYTHONPATH=. python scripts/stage3_pring_analyzer.py \
  --market-data data/${DATE}_market_data_complete.json \
  --output data/${DATE}_pring_result.json \
  --allow-estimated

# Stage 4: 报告生成
PYTHONPATH=. python tests/scripts/generate_simple_report_test.py \
  data/${DATE}_market_data_complete.json \
  data/${DATE}_pring_result.json \
  reports/${DATE}背景扫描120.md

# 验证：确保无缺口
cat reports/gap_monitor_${DATE}.json  # 应为 [] 或 {}
```

### Stage2 运行模式

| 模式 | 关键参数 |
|------|----------|
| **Fast (regex)** | `--extraction-backend regex --disable-extract` |
| **Precision (DeepSeek)** | `--extraction-backend deepseek --deepseek-timeout 12` |
| **重试指定缺口** | `--tasks USDCNY,northbound,etf` |
| **Exa fallback** | 自动（需 `EXA_API_KEY`），Tavily 422/5xx 时触发 |

> 详细参数说明见 AGENTS.md "Stage2 Performance / Timeout Tips"

### 注入后完整度检查

```bash
python -c "
import json
d = json.load(open('data/${DATE}_market_data_complete.json'))
comp = d.get('metadata',{}).get('data_completeness', 0)
print(f'数据完整度: {comp*100:.1f}%')
if comp < 0.8:
    nulls = [f'{cat}.{k}' for cat in ['macro_indicators','monetary_policy','stock_indices']
             for k,v in d.get(cat,{}).items() if isinstance(v,dict) and v.get('current_value') is None]
    print(f'WARNING: 需补充字段: {nulls}')
"
```

## Architecture

```
src/datasource/
├── adapters/        # 数据源适配器 (TuShare, Tavily, Exa, InternationalFinance)
├── engines/         # 处理引擎 (deepseek_reasoner, stage2_task_planner)
├── calculators/     # 计算模块 (pring_analyzer, fund_flow)
├── models/          # Pydantic 数据契约
├── config/          # 配置 (indices_config.py, search_profiles.py)
├── generators/      # 报告生成器 (simple_report)
├── cache/           # 缓存 (memory_cache, sqlite_cache)
├── utils/           # 工具 (trend_history_store, quality_metrics, observability)
└── manager.py       # DataSourceManager 单例入口
```

**关键文件**:
- `src/datasource/models/market_data_contract.py`: 数据契约定义（WebSearch JSON 必须匹配此 schema）
- `src/datasource/config/search_profiles.py`: Tavily 搜索配置（query/域名/阈值）
- `config/policy_rules.yaml`: 策略规则（422 阈值、关键缺失字段）

**关键数据路径**:
- `data/trend_history/min/series/{category}/{symbol}.json`: 滚动时序数据
- `data/trend_history/min/events/{indicator}.json`: 宏观事件序列
- `reports/tavily_cache.sqlite`: Tavily 搜索缓存（跨日复用）
- `logs/observability_*.json`: Stage2 指标级耗时/来源统计

### Key Patterns

```python
from datasource import get_manager
manager = get_manager()  # Singleton
response = await manager.get_forex_data("DXY", start, end)  # 返回 DataResponse
```

### Trend History Rules

- 股指 200 交易日 / 外汇商品债券 121 交易日 / 资金流 120 交易日 / 宏观事件 6–12 条
- Stage1 写入 `is_partial=true`，Stage2.5 最终覆盖
- CN10Y/CN10Y_CDB 禁止 ETF 代理写入；禁止从 `reports/*.md` 反向回填

## WebSearch JSON Schema

所有字段必须包含**可解析的数字**，不能是描述性文本。

| Category | Required Fields | Example |
|----------|----------------|---------|
| commodities | `symbol`, `name`, `current_price`, `unit` | `{"symbol": "GC=F", "current_price": 2650.5, "unit": "$/oz"}` |
| forex | `pair`, `name`, `current_rate` | `{"pair": "USDCNY", "current_rate": 7.248}` |
| bonds | `symbol`, `name`, `current_yield` | `{"symbol": "US10Y", "current_yield": 4.18}` |
| fund_flow | `recent_5d`, `total_120d`, `trend`, `source` | `{"recent_5d": 85.6, "total_120d": 1250.0, "trend": "流入"}` |

**Critical**: `recent_5d`/`total_120d` 必须是数字（非"波动"/"净流入"）。

## Data Coverage

**TuShare 可得** (Stage1):
- 宏观: GDP, CPI, PPI, PMI, M0/M1/M2, 社融
- 股指日线、两融余额

**必须 WebSearch** (Stage2/2.5):
- 外汇: DXY（美元指数）, USDCNY/USDCNH
- 债券: CN10Y, CN10Y_CDB, US10Y
- 商品: BDI（波罗的海干散货指数）
- 资金流: 北向/南向/ETF
- 宏观: 工业增加值、工业营收

## Environment Variables

```bash
TUSHARE_TOKEN=xxx      # Required: Stage1
TAVILY_API_KEY=xxx     # Required: Stage2
DEEPSEEK_API_KEY=xxx   # Required: LLM extraction
EXA_API_KEY=xxx        # Optional: Tavily fallback
```

## Troubleshooting

| 问题 | 解决方案 |
|------|----------|
| DeepSeek 超时 | `--extraction-backend regex --disable-extract` |
| Tavily extract 422 | 自动回退 DeepSeek；仍不稳用 `--disable-extract` |
| Tavily 当日重复 422 | **不要重试 Stage2**；改用 Stage2.5 手工注入 |
| 代理/TLS 问题 | `env -u http_proxy -u https_proxy` 前缀 |
| 完整度 <80% | 检查 macro/monetary null 字段，手动补数后重注入 |
| 报告出现 N/A | 检查 `gap_monitor`，确保数值为可解析数字 |

> 完整故障排除表见 AGENTS.md "Troubleshooting 速查表"

## Output Files

| Stage | Output | Purpose |
|-------|--------|---------|
| Stage1 | `data/${DATE}_market_data.json` | 原始 API 数据 |
| Stage2 | `data/${DATE}_market_data_stage2.json` | 增强后数据 |
| Stage2 | `reports/gap_monitor_${DATE}.json` | 缺失数据追踪 |
| Stage2 | `reports/websearch_results_${DATE}_auto.json` | Tavily 搜索结果 |
| Stage2 | `logs/observability_${DATE}.json` | 指标级耗时/失败统计 |
| Stage2 | `reports/quality_metrics_${DATE}.json` | 数据质量评估 |
| Stage2.5 | `data/${DATE}_market_data_complete.json` | 注入完成后数据 |
| Stage3 | `data/${DATE}_pring_result.json` | Pring 分析输出 |
| Stage4 | `reports/${DATE}背景扫描120.md` | 最终报告 |

## Code Standards

- **Python**: ≥3.7, 4-space indent, UTF-8, async-first
- **Naming**: `lower_snake_case` (functions/vars), `CamelCase` (classes)
- **Commits**: Conventional (`feat:`, `fix:`, `refactor:`)
- **详细规范**: 见 AGENTS.md

## Key Documentation

- **AGENTS.md**: 详细编码规范、资金流数据标准、Stage2.5 工作流、性能调优
- **docs/系统技术文档.md**: 完整技术参考（含 Pring 六阶段分析原理）
