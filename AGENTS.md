# AGENTS Playbook

> 沟通约定：与用户/同事的交互和问题说明优先使用中文，命令保持原文。

## Repo Map (keep code here)
- Core: `src/datasource/` (adapters, managers, calculators, engines, cache helpers, utils).
- Config: `src/datasource/config/indices_config.py`, root `config/`.
- Tests: `tests/` with fixtures in `tests/test_data_sources/`; helpers in `tests/test_datasource.py`.
- Templates: `templates/`; generated reports: `reports/` (review before merge).
- Long jobs: `scripts/` (notably `scripts/utility/background_scan_120d_generator.py`); demos in `examples/`.

## Setup & Health Check
1) `python -m venv .venv` → activate (`.venv\Scripts\activate` on Win, `source .venv/bin/activate` on *nix).
2) Install: `pip install -r requirements.txt` → `pip install -e .` → `pip install -e ".[dev]"`.
3) Defaults: `cp .env.example .env` (contains TuShare token, rate limits, cache toggles).
4) Sanity: `python -c "from datasource import get_manager; print('OK')"`.
5) **Preflight（在 Stage1 前执行，校验密钥并清空代理）**
   ```bash
   # run_preflight.sh
   set -euo pipefail
   set -a; source .env; set +a

   for k in TAVILY_API_KEY DEEPSEEK_API_KEY TUSHARE_TOKEN; do
     v=${!k-}
     [ -n "$v" ] && [ ${#v} -ge 20 ] || { echo "Missing/short $k"; exit 1; }
   done

   unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
   env | grep -E '^(TAVILY_API_KEY|DEEPSEEK_API_KEY|TUSHARE_TOKEN)='
   env | grep -Ei 'proxy' || echo "Proxy cleared"
   ```
   使用方式：`bash run_preflight.sh && <后续 Stage1/Stage2… 命令>`；若终端重开，请先跑一次再执行流水线。

6) **Health Check（可选，建议在 Stage2 前跑）**：`PYTHONPATH=./src python3 scripts/stage2_health_check.py`
   - 校验 Tavily/DeepSeek 密钥、缓存路径可写、基础连通性（HEAD Ping）。失败即退出；需代理时先设置环境变量再跑。
6) **代码语法预检（可选）**
   ```bash
   python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py
   # 如有 SyntaxError，先修复再执行流水线
   ```

## Style & Naming
- Python ≥3.7, 4-space indent, UTF-8.
- Prefer async with `DataSourceManager`; keep adapters thin, move logic to engines/calculators.
- `lower_snake_case` for modules/vars/functions; `CamelCase` classes; constants UPPER_SNAKE_CASE.
- Configure via `indices_config.py`; comment only for non-obvious intent.

## Testing Shortlist
- Smoke: `datasource-test` (CLI) or `pytest -q`.
- Focused: `python tests/test_datasource.py`, `python tests/simple_test.py`, `python tests/test_na_filling.py`.
- Name new tests by behavior (e.g., `test_background_scan_handles_timeout`); fixtures deterministic in `tests/test_data_sources/`.

## Commits & PRs
- Conventional commits: `feat:`, `fix:`, `refactor:` (one logical change each).
- PRs: state scope, link issues, list commands run, show before/after for templates/reports.
- Run `black src/ tests/ scripts/`, `flake8 src/`, `mypy src/datasource/...`; note any skips.

## 数据来源约束
- 运行各 stage 及生成报告时严禁从历史 `reports/*.md` 中抓取或复用数据；所有数据必须来自 TuShare、Tavily/AI WebSearch 实时获取或各 stage 的计算产出。

## Fund Flow Data Standard (V2.1 MCP增强)
**Background Scan Generator**: `scripts/utility/background_scan_120d_generator.py`

**Priority**
1. MCP WebSearch only: real-time data from 东方财富网 / 同花顺 / 每日经济新闻等。
2. Anomaly detect: any 0/None triggers immediate second WebSearch.

**Must-do checks**
- 北向/南向/ETF/融资融券: use MCP WebSearch only; AKShare forbidden.
- Zero/missing values: mark as `异常零值-需核查`; log raw source in `note`.
- Annotate sources: `MCP WebSearch实时获取` or `异常零值-需核查`.
- Stage2 CLI: `python scripts/stage2_unified_enhancer.py --fund-flow-backend {mcp|tavily|hybrid} --tasks northbound,southbound,etf --execute-search`
  - `tavily`: searches, fills `recent_5d/total_120d`, source `tavily+deepseek`.
  - `mcp`: skip search, record pending in `gap_monitor` for MCP/manual injection.
  - `hybrid`: MCP → Tavily fallback; failures/zeros flagged `manual_required`.

**Code touchpoints**
- `BackgroundScan120DGeneratorFixed._get_fund_flow_websearch()` (≈ lines 318-359)
- `BackgroundScan120DGeneratorFixed.collect_fund_flow_data()` (≈ lines 361-545)
- `BackgroundScan120DGeneratorFixed.generate_fund_flow_table()` (≈ lines 648-728)

**Data shape**
```python
{
    'recent_5d': 123.45,       # 近5日流向(亿元)
    'total_120d': 456.78,      # 近120日累计(亿元)
    'trend': '流入' or '流出',
    'source': 'MCP WebSearch实时获取' or '异常零值-需核查',
    'note': '来源:东方财富网',  # optional
}
```

**Tests to hit**
- WebSearch priority logic
- Zero-value anomaly handling
- Source annotation in reports
- ETF fund flow data is real (no placeholders)

## WebSearch JSON Schema 必填字段
注入脚本 `inject_websearch_data_test.py` 要求以下必填字段：

| 类别 | 必填字段 | 示例 |
|------|----------|------|
| commodities | `symbol`, `name`, `current_price`, `unit` | `{"symbol": "GC=F", "name": "COMEX黄金", "current_price": 2650.5, "unit": "$/oz"}` |
| forex | `pair`, `name`, `current_rate` | `{"pair": "USDCNY", "name": "USD/CNY在岸", "current_rate": 7.248}` |
| bonds | `symbol`, `name`, `current_yield` | `{"symbol": "US10Y", "name": "美国10年期国债", "current_yield": 4.18}` |
| fund_flow | `recent_5d`, `total_120d`, `trend`, `source` | `{"recent_5d": 85.6, "total_120d": 1250.0, "trend": "流入", "source": "MCP WebSearch实时获取"}` |

**注意**：`recent_5d`/`total_120d` 必须是可解析的数字，不能是描述性文本（如“波动”“净流入”）。

## Stage1 → Stage3 Daily Run
- **0) Preflight（必跑）**：`bash run_preflight.sh`，校验 `.env` 中 `TAVILY_API_KEY/DEEPSEEK_API_KEY/TUSHARE_TOKEN` 且清空代理；失败直接终止。
- 设置日期：`DATE=$(date +%Y-%m-%d)`；`DATE_NH=${DATE//-/}`。
- Activate: `source .venv/bin/activate && source .env`。
- **Stage1**（采集原始数据，建议直连禁代理）：
  ```bash
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  PYTHONPATH=./src python3 scripts/stage1_data_collector.py \
    --date "$DATE" \
    --output "data/${DATE_NH}_market_data.json"
  ```
  - 商品行情不走 Yahoo/Investing 兜底；北向/南向/ETF 资金流写占位符，后续必补。

- **Stage2** Tavily 增强（推荐速度优先配置）：
  ```bash
  PYTHONPATH=./src python scripts/stage2_unified_enhancer.py \
    --market-data data/${DATE_NH}_market_data.json \
    --output data/${DATE_NH}_market_data_stage2.json \
    --phase all --execute-search \
    --fund-flow-backend tavily \
    --extraction-backend regex \
    --disable-extract \
    --deepseek-timeout 8 \
    --llm-hard-timeout 10 \
    --deepseek-max-concurrency 1 \
    --queue-retry-limit 0 \
    --cache-backend sqlite --cache-path reports/tavily_cache.sqlite \
    --websearch-results reports/websearch_results_${DATE_NH}_auto.json \
    --log-output logs/stage2_unified_log_${DATE_NH}.json \
    --gap-monitor reports/gap_monitor_${DATE_NH}.json
  ```
  - 使用 `--extraction-backend regex --disable-extract` 跳过 DeepSeek/Tavily extract，30–60 秒完成。
  - 若需更高精度：改为 `--extraction-backend deepseek --deepseek-model deepseek-chat --deepseek-timeout 8 --llm-hard-timeout 10 --deepseek-max-concurrency 1`；langchain 默认禁用，如需实验必须加 `--allow-langchain`。
  - Tavily extract 422 频发时：用 `--disable-extract` 或收紧 `--extract-topk 1`，可先 search-only，避免 422 软拒绝。
  - LangChain 默认禁用；如需实验，必须显式传 `--allow-langchain`（自备依赖）。
  - 仅重试资金流：加 `--tasks northbound,southbound,etf`；失败落 `gap_monitor`，转 Stage2.5。

- **Stage2.5 WebSearch 手工注入（补缺口）**：
  - 汇总实时搜索写入 `reports/websearch_results_${DATE_NH}_manual.json`（遵循 fund_flow/commodities/forex/bonds 结构与来源标注）。
  ```bash
  PYTHONPATH=. python inject_websearch_data_test.py \
    data/${DATE_NH}_market_data_stage2.json \
    reports/websearch_results_${DATE_NH}_manual.json \
    data/${DATE_NH}_market_data_complete.json
  ```
  - 成功后 `metadata.missing_items`、`reports/gap_monitor_${DATE_NH}.json` 应为空；零值标记 `异常零值-需核查`。
  - （可选）如需自动结果：将 `_manual.json` 换成 `_auto.json`，手工编辑后反复注入。

- **Stage3** Pring 分析：
  ```bash
  PYTHONPATH=. python scripts/stage3_pring_analyzer.py \
    --market-data data/${DATE_NH}_market_data_complete.json \
    --output data/${DATE_NH}_pring_result.json \
    --allow-estimated
  ```

- **Report** 生成：
  ```bash
  PYTHONPATH=. python tests/scripts/generate_simple_report_test.py \
    data/${DATE_NH}_market_data_complete.json \
    data/${DATE_NH}_pring_result.json \
    reports/${DATE}-背景扫描120.md
  ```

- **收尾校验**：确认 `reports/gap_monitor_${DATE_NH}.json` 为空，报告内无 “N/A（待 WebSearch）”。

### 报告生成时的 Plan 要求
- 生成日报/背景扫描报告前，先列出 3–5 步的 plan（覆盖 Stage2.5 补数、Stage3 分析、Report 输出等），不得使用单步 plan。
- 若任务非常简单（如仅重跑生成已齐全数据的报告），可注明“任务简单，按既定流程直接执行”，但需在回复中显式说明未使用 plan 的理由。

### Stage3 estimated fallback
- Add `--allow-estimated` to Stage3 to let `is_estimated=True` data score; values must be non-null.
- Prefer authoritative data; None/0 still treated as missing.
- Related code: `scripts/stage3_pring_analyzer.py`, `src/datasource/calculators/pring_analyzer.py` (`allow_estimated`).

### Stage2.5 injection auto-clean
- Script: `inject_websearch_data_test.py`.
- Successful injection clears `metadata.missing_items` and top-level `missing_items` to prevent repeated blocking.
- When real numbers filled for `stock_indices/forex/bonds/commodities/fund_flow`, gaps drop automatically.
- Macro metrics missing `previous_value` are back-filled with `current_value - change_rate`; if no change_rate, fallback `previous_value=current_value` to reduce “N/A”.

### Stage2.5 注入后完整度检查
注入完成后执行，确保数据完整度 ≥80%：
```bash
python -c "
import json
d = json.load(open('data/${DATE_NH}_market_data_complete.json'))
comp = d.get('metadata',{}).get('data_completeness', 0)
print(f'数据完整度: {comp*100:.1f}%')
if comp < 0.8:
    nulls = []
    for cat in ['macro_indicators', 'monetary_policy', 'stock_indices']:
        for k,v in d.get(cat,{}).items():
            if isinstance(v, dict) and v.get('current_value') is None:
                nulls.append(f'{cat}.{k}')
    print(f'WARNING: Null字段需补充: {nulls}')
"
```
若完整度不足，需手动补数据后重新注入。

## Tavily / MCP Modes (2025-12 update)
- Fund flow & forex default to Tavily; `fund-flow-backend` default `tavily`. `hybrid` = Tavily fallback from MCP; no automatic MCP channel.
- Required keys: `.env` sets `TAVILY_API_KEY`, `DEEPSEEK_API_KEY`; prefer `PYTHONPATH=./src` when running.
- DeepSeek default model `deepseek-reasoner`, timeout 12s; `--use-queue` enables `asyncio.Queue` extraction.
- Real-time search params: `language=chinese`, `topic=news`, `time_range=day`, `max_results<=8`, `search_depth=advanced`; macro/low-timeliness: `time_range=year/month`, `max_results<=6`, `search_depth=basic`.
- Example:
  ```bash
  PYTHONPATH=./src python3 scripts/stage2_unified_enhancer.py \
    --market-data data/${DATE}_market_data.json \
    --output data/${DATE}_market_data_stage2.json \
    --execute-search --fund-flow-backend tavily \
    --log-output logs/stage2_unified_log_${DATE}.json \
    --gap-monitor reports/gap_monitor_${DATE}.json \
    --websearch-results reports/websearch_results_${DATE}.json
  ```
  Optional queue: `--use-queue --queue-concurrency 3 --queue-retry-limit 2`.

## Stage2 Performance / Timeout Tips (2025-12-04)
- Disable bad proxies first: prefix command with `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY` or pass `--http-proxy '' --https-proxy ''`.
- Trim long tail (fund flow manual/MCP): `--fund-flow-backend mcp` or `--fund-flow-backend hybrid` so northbound/southbound/etf skip live search.
- Turbo no-LLM: `--extraction-backend regex --queue-concurrency 6 --deepseek-max-concurrency 0 --deepseek-timeout 8 --queue-retry-limit 0` (faster, slightly less accurate).
- With LLM: `--deepseek-timeout 8 --queue-concurrency 5 --deepseek-max-concurrency 4 --queue-retry-limit 0`; consider two-pass `--phase essential` then `--phase assets`.
- Reduce Tavily extract load: set `top_for_extract = snippets[:2]` or `extract_depth="basic"` for commodities/forex to avoid 422/timeout.
- Reuse cache: keep `reports/tavily_cache.sqlite`; second run only gaps; watch `cache_hit_rate`.

### Stage2 性能瓶颈与快速模式
- 常见瓶颈：Tavily extract 422；DeepSeek 请求超时（单指标可耗时 30–40s）；并发受限或串行导致总耗时上升。
- 快速绕行：`--extraction-backend regex --disable-extract --queue-retry-limit 0 --deepseek-max-concurrency 0`，资金流仍用 tavily，整体 30–60s 完成。
- 需要方向/高精度时再移除上述两参数启用 DeepSeek（3–5 分钟），并适当调低 `--deepseek-timeout/--deepseek-max-concurrency`。

## Proxy & Connectivity
- Prefer no global proxy in production; if needed, set in `.env` then `source .env`. If skipping proxy, prefix commands with `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY`.
- Stage2 proxy precedence: CLI `--http-proxy/--https-proxy` overrides env; when globally disabled, omit these flags.
- Quick direct check:
```bash
python - <<'PY'
import httpx
print(httpx.get('https://api.tavily.com', timeout=5, proxies=None).status_code)
PY
```
If proxy required, pass `proxies` explicitly in the check.

## Data Priority (forex/fund flow/market)
- MCP first when available: `fund_flow_backend=mcp` or `forex_backend=mcp` skips online search and marks pending for MCP injection.
- Tavily second: `hybrid` = MCP then Tavily; `tavily` = direct Tavily.
- WebSearch JSON last resort: use `data/websearch_results_${DATE}.json` + `inject_websearch_data_test.py` for forex/fund_flow/macro/currency/commodities/bonds write-back.
- Market fallback: after Stage2 run `scripts/fill_market_data_from_yahoo.py`, then WebSearch injection to fill commodities/bonds/forex gaps.

## Troubleshooting 速查表
| 问题 | 原因 | 解决方案 |
|------|------|----------|
| Stage2 DeepSeek 持续超时 | API 响应慢或网络问题 | `--extraction-backend regex --disable-extract`，或降低 `--deepseek-timeout` 并串行关键指标 |
| Tavily extract 422 | API 参数/限制 | 加 `--disable-extract`；或缩小 `--extract-topk` |
| Stage3 完整度 <80% 报错 | 关键字段为 null | 检查 macro/monetary/stock_indices，手动补数据后重注入 |
| 注入时 KeyError: 'symbol' | WebSearch JSON 缺必填字段 | 参照 WebSearch JSON Schema 补全字段 |
| 报告出现 N/A | 数据未注入或格式错误 | 查 gap_monitor，确认数字字段为可解析数值 |
| SyntaxError 启动失败 | 代码语法错误 | `python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py` |
