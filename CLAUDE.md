# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 沟通约定：与用户的交互和问题说明优先使用中文，命令保持原文。

## Project Overview

统一金融数据集成框架，支持 TuShare、AKShare、InternationalFinance 数据源自动故障转移。集成 Tavily+DeepSeek 网络搜索增强（Exa 默认关闭、仅显式 opt-in，当前不进入日常路径）、Pring 六阶段经济周期分析 (V4.0 三层框架)，以及 120 日背景扫描报告自动生成。

**核心数据流**: Stage1 (API采集) → Stage2 (Tavily+DeepSeek增强) → Stage2.5 (手工注入补缺) → Stage3 (Pring分析) → Stage4 (报告生成)

> 执行参数与口径以 `AGENTS.md` 为准；本文件保留最小操作指引与高频约束。

## Critical Constraints

- **Tavily 每日限制**: Stage2 Tavily search/extract **每日只能运行一次**。遇到 422 会自动回退 DeepSeek 从原始 snippets 抽取；遇到 quota/rate limit 会同轮 fast-switch 为 `manual_required` skeleton。不要重跑 Tavily，查看 `tavily_unavailable_reason`、`retrieval_diagnostics`、`manual_reason_breakdown` 后转 Stage2.5 补数
- **数据来源约束**: 严禁从历史 `reports/*.md` 中抓取或复用数据；所有数据必须来自 API 实时获取或 stage 计算产出
- **完整度要求**: Stage3 需要 `data_completeness ≥ 80%`，否则报告会有缺失
- **手工补数验证**: 所有手工填写的数值必须通过 WebSearch 验证后再填入，禁止凭记忆填写汇率、指数等高精度数值
- **Exa 默认关闭**: 当前先走 Tavily-first 提升命中率，Exa 不进入日常路径；只有传 `--enable-exa-fallback` 或设置 `STAGE2_ENABLE_EXA_FALLBACK=1` 时才使用
- **无值强制人工**: `no_value/deepseek_no_value/no_deepseek_key` 必须进入 `manual_required`，在 Stage2.5 产出待补全骨架
- **采集优先级固定**: `TuShare(Stage1) -> Stage2(Tavily) -> Stage2.5`，当前流程不使用旧版外部补数链路

## Quick Start

```bash
# 环境设置
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e . && pip install -e ".[dev]"
cp .env.example .env  # 编辑填入 TUSHARE_TOKEN, TAVILY_API_KEY, DEEPSEEK_API_KEY；默认 DEEPSEEK_MODEL=deepseek-v4-pro，可覆盖

# 验证安装
python -c "from datasource import get_manager; print('OK')"
datasource-test  # CLI 入口（等价于 python -m datasource.cli test_command）

# 预检（每次运行流水线前必跑；验证三个 API key ≥20字符 + 清代理）
bash run_preflight.sh
```

### 推荐运行方式

**所有脚本统一通过 `run_clean.sh` 执行**（优先 `.venv/bin/activate`，Windows/Git-Bash 再尝试 `.venv/Scripts/activate`；没有 venv 时必须显式 `ALLOW_SYSTEM_PYTHON=1` 才使用系统 Python。仍会 source .env、unset 代理、PYTHONPATH=./src）：
```bash
bash run_clean.sh python scripts/stage1_data_collector.py --date 2025-06-01
bash run_clean.sh python scripts/stage2_unified_enhancer.py --help
bash run_clean.sh python scripts/stage3_pring_analyzer.py --help
```

若不用包装器，需手动设置：`source .venv/bin/activate && source .env`，并在命令前加 `PYTHONPATH=./src`（Stage1/2）或 `PYTHONPATH=.`（Stage3/4）。代理干扰时前缀 `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY`。

## Testing

```bash
pytest -q                                # 快速测试（conftest.py 自动添加 ROOT/src 到 sys.path）
pytest tests/test_file.py::test_name -v  # 单测
pytest tests/integration/                # 集成测试（enhanced_pring, 120d, background_scan）
python tests/test_datasource.py          # 数据源连通性集成测试
black src/ tests/ scripts/ && flake8 src/ && mypy src/datasource/  # 代码质量
```

**测试文件结构**: 单元测试 `tests/test_*.py`（stage1/2/3、trend_history、policy_rules、fund_flow 等），集成测试 `tests/integration/`，测试夹具 `tests/test_data_sources/`，Stage4 报告生成脚本 `tests/scripts/`。

## Daily Report Pipeline

```bash
DATE=$(date +%Y-%m-%d)
DATE_NH=${DATE//-/}
source .venv/bin/activate && source .env

# Stage 1: API 数据采集
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
PYTHONPATH=./src python scripts/stage1_data_collector.py \
  --date "$DATE" \
  --output data/runs/${DATE_NH}/market_data.json

# Stage 1 后必跑：月度新鲜度检查（防止 TuShare 月度表滞后被误判为"完整"）
PYTHONPATH=./src python scripts/check_monthly_freshness.py data/runs/${DATE_NH}/market_data.json
# 若输出 STALE/MISSING（典型：cpi/ppi/pmi/m1/m2/tsf），必须经 Stage2/Stage2.5 补齐后才能进入 Stage3

# Stage 2: Tavily+DeepSeek 增强（当日只跑1次！）
PYTHONPATH=./src python scripts/stage2_unified_enhancer.py \
  --market-data data/runs/${DATE_NH}/market_data.json \
  --output data/runs/${DATE_NH}/market_data_stage2.json \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend deepseek \
  --deepseek-timeout 12 \
  --llm-hard-timeout 12 \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results data/runs/${DATE_NH}/websearch_results_auto.json \
  --log-output logs/runs/${DATE_NH}/stage2_unified_log.json \
  --gap-monitor data/runs/${DATE_NH}/gap_monitor.json

# Stage 2.5: WebSearch 注入补缺（脚本位于项目根目录）
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"

# Stage 3: Pring 分析（--allow-estimated 让 is_estimated=True 的数据参与评分）
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated

# Stage 4: 报告生成（正式入口）
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md"
# 兼容入口：tests/scripts/generate_simple_report_test.py（保留历史调用）

# 验证：确保无缺口
cat data/runs/${DATE_NH}/gap_monitor.json  # 应为空对象或无 pending/manual_required
```

### Stage2 运行模式

| 模式 | 关键参数 |
|------|----------|
| **Default (首次推荐)** | `--extraction-backend deepseek --deepseek-timeout 12` |
| **Fast (仅补缺)** | `--extraction-backend regex --disable-extract` |
| **重试指定缺口** | `--tasks USDCNY,northbound,etf` |
| **资金流后端** | 固定 `--fund-flow-backend tavily`（当前唯一支持） |
| **Exa fallback** | 默认关闭；需 `EXA_API_KEY` 且显式传 `--enable-exa-fallback` 或 `STAGE2_ENABLE_EXA_FALLBACK=1` |

> 详细参数说明见 AGENTS.md "Stage2 Performance / Timeout Tips"

### Stage2/Stage2.5 搜索优化要点

- DeepSeek 抽取采用”强 schema + 证据约束”，最少输出：`value/unit/source_url/as_of_date/report_period/confidence/manual_required/manual_reason`；fund_flow 还需 `recent_5d/total_120d/trend`。
- DeepSeek 默认模型为 `deepseek-v4-pro`，可用 `DEEPSEEK_MODEL` 或命令行参数覆盖。
- `source_url` 必须能在 snippets 中找到证据；若不满足或 `value` 缺失，强制 `manual_required=true`。
- Tavily quota/rate limit 后同轮 fast-switch 到 `manual_required` skeleton；不要新增 quota probe 或重跑 Tavily，查看 `tavily_unavailable_reason=quota_or_rate_limit`、`retrieval_diagnostics`、`manual_reason_breakdown`。
- 命中 `low_score_all/单位不匹配/缺少发布机构/no_value` 时会自动触发一次定向 query 重试（补充单位、机构、月份）。
- Stage2.5 在接收 Stage2 `results` 结构时，会保留 `manual_required/manual_reason` 并生成 `metadata.manual_required` 待补全骨架（含候选 `source_url/query/query_used`，按 `category:indicator_key` 去重）。
- Stage2.5 中 `macro_indicators.change_rate` 统一为百分比口径（`(current-previous)/abs(previous)*100`），分母为 0 时保留缺口并标记质量阻断。

### Operational Pitfalls（操作陷阱）

**missing_items 双层结构**（两处独立，必须分别处理）:
- `metadata.missing_items` (dict，按 category 分组) → inject 脚本读取、生成待补全骨架
- 顶层 `missing_items` list → Stage3 policy gate 的 `redlist` 来源（`critical_missing_keys: [dxy, bdi, rrr, mlf]`）
- inject 脚本注入成功后仅更新 `metadata.missing_items`；若需清除 Stage3 gate 阻断，须同时手动删除顶层 list 中对应条目

**inject 脚本跳过已有值**:
- 若指标已有 `current_value` 且不是 `PLACEHOLDER_SENTINELS = {None, 0, 0.0, 7.13}` 且 `is_stale≠True`，inject 脚本会跳过该条目
- 典型场景：Stage2 DeepSeek 填了值但 `is_estimated=True` → inject 跳过 → Stage3 仍被 gate 约束
- 解法：官方口径用带可信单个 HTTPS `source_url` 的 Stage2.5 manual 重新注入；只有 official allowlist 指标（代码为准，当前 `monetary_policy.mlf`、`forex.USDCNY`、`commodities.BCOM`）可触发 `manual_official_not_estimated` 并把显式 `is_estimated=True` 正规化为 `False`。非官方来源、ETF/fund_flow 等估算不要手工清掉 gate。

**Stage3 Gate 三路阻断**（需逐一排查，彼此独立）:
1. **policy gate** (`block_stage3=True`)：`redlist` 有 `critical_missing_keys` 中的项 → 修顶层 `missing_items` + 重新运行 `evaluate_policy()`
2. **stale_redlist**：`is_stale=True` 的 PMI/TSF/CPI 等关键指标 → 手工注入最新值（含 `date` 字段），Stage2.5 会清除 `is_stale`
3. **compare_gaps** (缺 `previous_value`)：`change_rate` 计算需要 `previous_value`，缺失时 Stage3 阻断 → 补齐 `previous_value`（无论 `--allow-estimated` 是否开启，此检查均不绕过）

**`--allow-estimated` 作用范围**: 仅绕过 `estimated_items`（`is_estimated=True` 的数据进入评分），**不绕过** `compare_gaps`、`stale_redlist` 和 `policy gate`

**Stage4 MLF 展示**: `policy_name/note/source/manual_reason` 含 `多重价位`、`中标利率`、`参考值`、`口径不适用`、`无统一利率`、`美式招标`、`利率区间` 等 marker 时，当前值显示 `2.00%（参考）`，120 日变化显示 `口径不适用`；普通货币政策当前值两位百分比，变化保持 `pp`。

**gap_monitor 手动清除**（Stage3 还读此文件）:
```bash
python3 -c “
import json
gm=json.load(open('data/runs/${DATE_NH}/gap_monitor.json'))
gm['manual_required']=[]
json.dump(gm,open('data/runs/${DATE_NH}/gap_monitor.json','w'),ensure_ascii=False,indent=2)
“
```

**TuShare 股指日内时间差**: Stage1 在 15:00 CST 前运行时，当日收盘价尚未生成，Stage1 返回前一交易日数据 — 属预期行为，下午收盘后无需重跑 Stage1

**CN10Y_CDB 常态缺口**: `gap_monitor.data_quality_issues` 中该条目 `reason=estimated_not_allowed` 属常态（无稳定 TuShare 口径），需 WebSearch 手工注入 `current_yield`

**monetary_policy 键名别名**（`_manual.json` 中可用，注入时自动映射）:
- `reverse_repo_7d` → `reverse_repo`
- `mlf_rate` → `mlf`
- `tsf_growth` → `tsf`
- `rrr` → `reserve_ratio`（内部存储键）

### 注入后完整度检查

```bash
python -c "
import json
d = json.load(open('data/runs/${DATE_NH}/market_data_complete.json'))
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
├── calculators/     # 计算模块 (pring_analyzer, fund_flow, technical_indicators)
├── models/          # Pydantic 数据契约
├── config/          # 配置 (indices_config.py, search_profiles.py)
├── generators/      # 报告生成器 (simple_report)
├── cache/           # 缓存 (memory_cache, sqlite_cache)
├── utils/           # 工具 (trend_history_store, quality_metrics, observability)
├── agents/          # AI 代理 (background_scan with config/templates)
├── analyzers/       # 长期分析、国际对比、行业轮动、政策追踪、风险监控等
└── manager.py       # DataSourceManager 单例入口

standalone/          # 独立分析脚本（不依赖主流水线，自包含）；也用于存放独立运行时产出的数据文件（市场数据、Pring结果 JSON）
scripts/archive/     # 已归档的一次性/低频脚本
```

**关键文件**:
- `src/datasource/models/market_data_contract.py`: Pydantic 数据契约（StockIndex/Commodity/Forex/Bond/FundFlow/Macro/MonetaryPolicy）；FundFlowData 内置 `_parse_amount()` 处理万亿/千亿/亿单位转换；BondYieldData 含 `date/as_of_date/report_period` 三字段，报告展示"最近可用日期"（优先级 as_of_date > date > report_period）
- `src/datasource/config/search_profiles.py`: Tavily 搜索配置（query/域名/阈值），26KB
- `src/datasource/config/indices_config.py`: 技术指标映射配置，32KB
- `src/datasource/engines/deepseek_reasoner.py`: DeepSeek LLM 抽取引擎
- `src/datasource/engines/stage2_task_planner.py`: Stage2 任务分解与调度

**配置文件**:
- `config/policy_rules.yaml`: 策略规则 — `extract_422_threshold: 1`, `low_score_threshold: 0.2`, `critical_missing_keys: [dxy, bdi, rrr, mlf]`, `min_trading_days: 100`
- `config/quality_thresholds.json`: 数据质量阈值 — 波动率(商品10%/外汇2%/股指8%)、债券50bp、过期时间(商品外汇1h/债券6h/宏观720h)

**关键数据路径**:
- `data/trend_history/min/series/{category}/{symbol}.json`: 滚动时序数据
- `data/trend_history/min/events/{indicator}.json`: 宏观事件序列
- `data/cache/tavily_cache.sqlite`: Tavily 搜索缓存（跨日复用）
- `logs/runs/YYYYMMDD/observability.json`: Stage2 指标级耗时/来源统计（score_filtered_drop, cache_hit_rate, avg_elapsed_ms 等）

### Key Patterns

```python
from datasource import get_manager
manager = get_manager()  # Singleton
response = await manager.get_forex_data("DXY", start, end)  # 返回 DataResponse
```

### Trend History Rules

- 股指 200 交易日 / 外汇商品债券 121 交易日 / 资金流 120 交易日 / 宏观事件 24 条
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
`_manual.json` 中凡填写了数值的条目必须提供 `source_url`（或在 `source/note` 中附 URL）。

## Data Coverage

**TuShare 可得** (Stage1):
- 宏观: GDP, CPI, PPI, PMI, M0/M1/M2, 社融
- 股指日线、两融余额

**TuShare 直采口径注意**:
- `USDCNH`: `fx_daily` 需用 `ts_code=USDCNH.FXCM`（`USDCNH` 常返回空）
- `CN10Y`: 优先 `yc_cb(ts_code=1001.CB, curve_type=0, curve_term=10)`；空则回退 `curve_type=1`
- `CN10Y_CDB`: 无稳定 TuShare 口径，需 WebSearch/手工注入；利差估算保留 `is_estimated=True`

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
DEEPSEEK_MODEL=deepseek-v4-pro  # Default; DEEPSEEK_MODEL or CLI args can override
EXA_API_KEY=xxx        # Optional, default off; requires --enable-exa-fallback / STAGE2_ENABLE_EXA_FALLBACK=1
```

## Troubleshooting

| 问题 | 解决方案 |
|------|----------|
| DeepSeek 超时 | `--extraction-backend regex --disable-extract` |
| Tavily extract 422 | 自动回退 DeepSeek；仍不稳用 `--disable-extract` |
| Tavily 当日重复 422 | **不要重试 Stage2**；改用 Stage2.5 手工注入 |
| 日志出现 `deepseek_no_value/no_deepseek_key` | 视为 `manual_required`，优先使用 `metadata.manual_required` 骨架补数 |
| Stage3 `block_stage3=True` 但数据已注入 | 检查顶层 `missing_items` list（inject 只更新 `metadata.missing_items`）；手动删除顶层对应条目后重跑 `evaluate_policy()` |
| Stage3 `compare_gaps` 阻断 | 补齐 `macro_indicators.*.previous_value`（`--allow-estimated` 不绕过此检查） |
| inject 跳过 `is_estimated` 项 | 官方口径用带可信单个 HTTPS `source_url` 的 Stage2.5 manual 重新注入；非官方/ETF/fund_flow 等估算不要手工清掉 gate |
| 股指数据不是今日 | Stage1 在 15:00 CST 前运行时正常，使用前一日收盘；无需处理 |
| 代理/TLS 问题 | `env -u http_proxy -u https_proxy` 前缀 |
| 完整度 <80% | 检查 macro/monetary null 字段，手动补数后重注入 |
| 报告出现 N/A | 检查 `gap_monitor`，确保数值为可解析数字 |
| SyntaxError 启动失败 | `python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py` |
| 搜索相关性低 | 调整 `search_profiles.queries/exclude_domains`，或提高 `--low-score-threshold` |

> 完整故障排除表见 AGENTS.md "Troubleshooting 速查表"

**诊断工具**:
- `bash run_clean.sh python scripts/stage2_health_check.py` — Stage2 前置健康检查（验证 Tavily/DeepSeek key、缓存路径可写、基本连通性）
- `bash run_clean.sh python scripts/stage2_low_score_audit.py --date YYYY-MM-DD` — 审计低分仍进入抽取的指标

## Output Files

| Stage | Output | Purpose |
|-------|--------|---------|
| Stage1 | `data/runs/${DATE_NH}/market_data.json` | 原始 API 数据 |
| Stage2 | `data/runs/${DATE_NH}/market_data_stage2.json` | 增强后数据 |
| Stage2 | `data/runs/${DATE_NH}/gap_monitor.json` | 缺失数据追踪 |
| Stage2 | `data/runs/${DATE_NH}/websearch_results_auto.json` | Tavily 搜索结果 |
| Stage2 | `logs/runs/${DATE_NH}/observability.json` | 指标级耗时/失败统计 |
| Stage2 | `data/runs/${DATE_NH}/quality_metrics.json` | 数据质量评估 |
| Stage2.5 | `data/runs/${DATE_NH}/market_data_complete.json` | 注入完成后数据 |
| Stage3 | `data/runs/${DATE_NH}/pring_result.json` | Pring 分析输出 |
| Stage4 | `reports/${DATE}-背景扫描120.md` | 最终报告（脚本：`scripts/stage4_report_generator.py`；`tests/scripts/generate_simple_report_test.py` 为兼容入口） |

## Code Standards

- **Python**: ≥3.7, 4-space indent, UTF-8, async-first
- **Naming**: `lower_snake_case` (functions/vars), `CamelCase` (classes)
- **Commits**: Conventional (`feat:`, `fix:`, `refactor:`)
- **PR 提交**: 需通过 `.github/pull_request_template.md` 检查清单（pytest、AGENTS.md 合规、black/flake8、夹具更新）
- **详细规范**: 见 AGENTS.md

## Key Documentation

- **AGENTS.md**: 详细编码规范、资金流数据标准、Stage2.5 工作流、性能调优
- **SCRIPTS.md**: 脚本参考文档（各 stage 脚本参数与用法）
- **docs/系统技术文档.md**: 完整技术参考（含 Pring 六阶段分析原理）
