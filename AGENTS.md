# AGENTS Playbook

> 沟通约定：与用户/同事的交互和问题说明优先使用中文，命令保持原文。

## Repo Map (keep code here)
- Core: `src/datasource/` (adapters, managers, calculators, engines, cache helpers, utils).
- Config: `src/datasource/config/indices_config.py`, root `config/`（含 `quality_thresholds.json`、`policy_rules.yaml`）。
- Data: `data/trend_history/`（趋势历史滚动窗口，非 SQLite）。
- Tests: `tests/` with fixtures in `tests/test_data_sources/`; helpers in `tests/test_datasource.py`.
- Templates: `templates/`; generated reports: `reports/` (review before merge).
- Long jobs: `scripts/`（含 `trend_history_scan.py`、`trend_history_backfill.py`、`run_snapshot.py`，notably `scripts/utility/background_scan_120d_generator.py`）; demos in `examples/`.
- Diagnostics: `scripts/stage2_low_score_audit.py`（基于 `logs/observability_*.json` 统计低分仍进入抽取的指标清单与比例）。

## Setup & Health Check
1) `python -m venv .venv` → activate (`.venv\Scripts\activate` on Win, `source .venv/bin/activate` on *nix).
2) Install: `pip install -r requirements.txt` → `pip install -e .` → `pip install -e ".[dev]"`.
3) Defaults: `cp .env.example .env` (contains TuShare token, rate limits, cache toggles).
   - 可选：配置 `EXA_API_KEY`（已安装 exa-py 时，Tavily 失败任务自动使用 Exa 兜底）
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

5.1) **统一运行入口（推荐）**：`bash run_clean.sh <command> [args...]`
   - 自动执行：`source .venv/bin/activate`、`source .env`、清理 `http_proxy/https_proxy`，并设置 `PYTHONPATH=./src`（若外部已设置则沿用）。
   - 示例：
   ```bash
   bash run_clean.sh python scripts/stage2_unified_enhancer.py --help
   bash run_clean.sh python scripts/stage3_pring_analyzer.py --help
   ```

6) **Health Check（可选，建议在 Stage2 前跑）**：`PYTHONPATH=./src python3 scripts/stage2_health_check.py`
   - 校验 Tavily/DeepSeek 密钥、缓存路径可写、基础连通性（HEAD Ping）。失败即退出；需代理时先设置环境变量再跑。
7) **代码语法预检（可选）**
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

## Review 完成后更新
- 若 `HEAD` 相对基线无代码差异，review 结论必须明确写为“无可审查代码差异、无可执行问题”，不得臆造问题。
- review 识别出流程或口径问题后，需同步更新本文件对应章节（Stage 命令、字段口径、校验规则、排障建议）。
- 更新 `AGENTS.md` 时仅记录可复用流程与规则，不写当日临时数值或一次性结论。

## 数据来源约束
- 运行各 stage 及生成报告时严禁从历史 `reports/*.md` 中抓取或复用数据；所有数据必须来自 TuShare、Tavily/AI WebSearch 实时获取或各 stage 的计算产出。
- trend_history 禁止从 `reports/*.md` 反向回填（仅允许 Stage1/Stage2.5 写入或 TuShare 回补）。

## Trend History（非 SQLite）
- 目录结构：`data/trend_history/min/series/{category}/{symbol}.json`、`data/trend_history/min/events/{indicator}.json`
- 窗口规则：股指 200 交易日；外汇/商品/债券 121 交易日；资金流 120 交易日；宏观/政策事件 24 条（用于提升 120d 对比可用性）
- 写入策略：Stage1 部分写入（`is_partial=true`），Stage2.5 最终写入覆盖
- 交易日对齐：依赖 TuShare `trade_cal`；缺口过大需手工补或标记估计值
- 写入防护：过滤低质量标记（如“数值超出合理区间”“异常零值”“regex_only且缺少发布机构”）；CN10Y/CN10Y_CDB 禁止 ETF 代理写入；回补脚本跳过 `bond_etf_proxy` 来源；不使用“真实范围”作硬性校验标准

## Fund Flow Data Standard (V2.3，Stage2/Stage2.5 主路径)
**Background Scan Generator（历史脚本）**: `scripts/utility/background_scan_120d_generator.py`（主流程可跳过）

**Priority**
1. TuShare 能直接获取的指标优先 TuShare（Stage1）。
2. TuShare 不可得或缺失时，统一走 Stage2 Tavily+DeepSeek（`--fund-flow-backend tavily`）。
3. Stage2 仍缺值时，统一走 Stage2.5 手工注入。
4. 异常检测：任一 `0/None` 或窗口值缺失都需标记 `manual_required` 并进入 Stage2.5。

**Must-do checks**
- 北向/南向/ETF/融资融券: 禁止 AKShare 直接写最终值；仅允许 WebSearch 实时来源或 Stage2.5 手工补数。
- Zero/missing values: mark as `异常零值-需核查`; log raw source in `note`.
- Annotate sources: `tavily+deepseek` / `待人工补数(Stage2 manual_required)` / `异常零值-需核查`.
- Stage2 CLI: `python scripts/stage2_unified_enhancer.py --fund-flow-backend tavily --tasks northbound,southbound,etf --execute-search`
  - 固定 `tavily`：search + extraction 回填 `recent_5d/total_120d`，source=`tavily+deepseek`。

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
    'source': 'tavily+deepseek' or '待人工补数(Stage2 manual_required)' or '异常零值-需核查',
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
| fund_flow | `recent_5d`, `total_120d`, `trend`, `source` | `{"recent_5d": 85.6, "total_120d": 1250.0, "trend": "流入", "source": "tavily+deepseek"}` |

**注意**：`recent_5d`/`total_120d` 必须是可解析的数字，不能是描述性文本（如“波动”“净流入”）。
`_manual.json` 中凡填写了数值的条目必须带 `source_url`（或在 `source/note` 含 URL），否则注入脚本会报错。

## Stage1 → Stage3 Daily Run
- **0) Preflight（必跑）**：`bash run_preflight.sh`，校验 `.env` 中 `TAVILY_API_KEY/DEEPSEEK_API_KEY/TUSHARE_TOKEN` 且清空代理；失败直接终止。
- 设置日期：`DATE=$(date +%Y-%m-%d)`；`DATE_NH=${DATE//-/}`。
- Activate: `source .venv/bin/activate && source .env`。
- **0.5) trend_history 缺口扫描（建议）**：
  ```bash
  PYTHONPATH=./src python3 scripts/trend_history_scan.py --date "$DATE"
  ```
  - 默认输出：`reports/trend_history_gap_${DATE_NH}.json`
  - 若缺口较大，优先先做 `trend_history_backfill.py` 再跑 Stage1。

- **0.6) trend_history 首次回补（可选，TuShare 可得的数据）**：
  ```bash
  PYTHONPATH=./src python3 scripts/trend_history_backfill.py --start "YYYY-MM-DD" --end "YYYY-MM-DD"
  ```
  - 仅回补 TuShare 可得的股指/外汇/债券日序列；WebSearch-only 指标需日同步累积。
- **Stage1**（采集原始数据，建议直连禁代理）：
  ```bash
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  PYTHONPATH=./src python3 scripts/stage1_data_collector.py \
    --date "$DATE" \
    --output "data/${DATE_NH}_market_data.json"
  ```
  - 商品行情不走 Yahoo/Investing 兜底；北向/南向/ETF 资金流写占位符，后续必补。

- **Stage2** Tavily 增强（推荐速度优先配置；同日只跑 1 次 Tavily，失败转 Stage2.5 补数）：
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
  - 若代理导致 TLS/证书报错，优先直连：在命令前加 `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY`；需要高精度时去掉 `--disable-extract` 让 DeepSeek 抽取生效。
  - 若需更高精度：改为 `--extraction-backend deepseek --deepseek-model deepseek-chat --deepseek-timeout 8 --llm-hard-timeout 10 --deepseek-max-concurrency 1`；langchain 默认禁用，如需实验必须加 `--allow-langchain`。
  - Tavily extract 422 频发时：系统会自动回退到 DeepSeek 从原始 snippets 抽取，并在 Stage2 Summary 计数 `extract_fallback_to_deepseek`；如仍不稳，改用 `--disable-extract` 或收紧 `--extract-topk 1` 以避免 422 软拒绝；当日不要重复跑 Stage2，缺口改用 Stage2.5 `_manual.json` 注入。
  - LangChain 默认禁用；如需实验，必须显式传 `--allow-langchain`（自备依赖）。
  - 仅重试资金流：加 `--tasks northbound,southbound,etf`；失败落 `gap_monitor`，转 Stage2.5。

- **Stage2 优化命令（避免 Tavily extract 422，强制 DeepSeek 解析 snippets；同日只跑一次 Tavily）**：
  ```bash
  PYTHONPATH=./src python scripts/stage2_unified_enhancer.py \
    --market-data data/${DATE_NH}_market_data.json \
    --output data/${DATE_NH}_market_data_stage2.json \
    --phase all --execute-search \
    --fund-flow-backend tavily \
    --extraction-backend deepseek \
    --disable-extract \
    --deepseek-timeout 8 \
    --deepseek-max-concurrency 1 \
    --queue-retry-limit 0 \
    --cache-backend sqlite --cache-path reports/tavily_cache.sqlite \
    --websearch-results reports/websearch_results_${DATE_NH}_auto.json \
    --log-output logs/stage2_unified_log_${DATE_NH}_rerun.json \
    --gap-monitor reports/gap_monitor_${DATE_NH}_rerun.json
  ```
  - 适用：Tavily extract 多次 422 或需快速验证搜索相关性；禁用 Tavily extract，直接用 DeepSeek/regex 处理 snippets。
  - 可选：如需更高并发可加 `--use-queue --queue-concurrency 3`；若只补资金流，加 `--tasks northbound,southbound,etf`。

- **Stage2.5 WebSearch 手工注入（补缺口）**：
  - 汇总实时搜索写入 `reports/websearch_results_${DATE_NH}_manual.json`（遵循 fund_flow/commodities/forex/bonds 结构与来源标注）。
  ```bash
  PYTHONPATH=./src python inject_websearch_data_test.py \
    data/${DATE_NH}_market_data_stage2.json \
    reports/websearch_results_${DATE_NH}_manual.json \
    data/${DATE_NH}_market_data_complete.json
  ```
  - 成功后 `metadata.missing_items`、`reports/gap_monitor_${DATE_NH}.json` 应为空；零值标记 `异常零值-需核查`。
  - 若输入是 Stage2 自动结果（`results` 数组），脚本会自动转换为 schema，并保留 `manual_required/manual_reason` 生成 `metadata.manual_required` 待补全骨架（含候选 `source_url/query/query_used`）。
  - `metadata.manual_required` 按 `category:indicator_key` 去重，避免人工项重复。
  - 注入后会刷新 `reports/quality_metrics_${DATE_NH}.json` 并写入 trend_history。
  - 注入结束会自动输出 `is_estimated=True` 的字段清单（`_post_injection_validation()`），便于定位仍需补数的指标。
  - （可选）如需自动结果：将 `_manual.json` 换成 `_auto.json`，手工编辑后反复注入。
  - 手工补数应尽量填入真实数字；避免保留 0/None 占位（脚本会将 0 视为缺口）。如仍缺，标注 `异常零值-需核查`，并在 note 写明来源与时间。

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

- **收尾校验**：确认 `reports/gap_monitor_${DATE_NH}.json` 为空，报告内无 “N/A（待 WebSearch）”，并检查 `is_estimated=True`（宏观/货币政策/债券）。

## Stage2 额外产出（自动落盘）
- `reports/quality_metrics_${DATE}.json`（质量指标）与 `reports/quality_trend.csv`（可选累积）
- `logs/observability_${DATE}.json`（指标级耗时/来源/失败类型）
- `reports/source_conflicts_${DATE}.json`（冲突解决）
- `reports/policy_evaluation_${DATE}.json`（策略评估结果）
- `reports/run_snapshot_${DATE}.json`（运行快照/审计）

### 报告生成时的 Plan 要求
- 生成日报/背景扫描报告前，先列出 3–5 步的 plan（覆盖 Stage2.5 补数、Stage3 分析、Report 输出等），不得使用单步 plan。
- 若任务非常简单（如仅重跑生成已齐全数据的报告），可注明“任务简单，按既定流程直接执行”，但需在回复中显式说明未使用 plan 的理由。

### 报告生成快捷流程（2025-12-09 更新）
- Stage2 产出的 `reports/websearch_results_${DATE}_auto.json`（含 `results` 数组）可直接喂给 `inject_websearch_data_test.py`，脚本会自动转换为 schema 并注入；若终端打印 “注入数据项: 0”，说明结果无可解析数值或文件为空，需改用手工 schema 版 `_manual.json`。
- fund_flow 仍需真实数字：即便 Tavily 抽取 422 已回退 DeepSeek，如仍无值请手工填 `recent_5d/total_120d/trend/source` 后再注入，确保 `metadata.data_completeness≥0.8` 且 `gap_monitor` 为空。
- 注入成功后再跑 Stage3 与生成报告命令，避免报告出现 “N/A（待 WebSearch）/无数据”。

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

可选检查：估计值与缺口标记
```bash
python -c "
import json
d = json.load(open('data/${DATE_NH}_market_data_complete.json'))
est = []
for sec in ['macro_indicators', 'monetary_policy']:
    for k, v in d.get(sec, {}).items():
        if isinstance(v, dict) and v.get('is_estimated'):
            name = v.get('indicator_name') or v.get('policy_name') or k
            est.append(f'{sec}.{name}')
for b in d.get('bonds', []):
    if isinstance(b, dict) and b.get('is_estimated'):
        name = b.get('name') or b.get('symbol') or ''
        est.append('bonds.' + name)
print('is_estimated:', est)
print('metadata.missing_items:', d.get('metadata', {}).get('missing_items'))
"
```

## Tavily Mode（2026-02 update）
- Stage2 Unified 中 fund flow & forex 统一使用 `tavily`。
- `--fund-flow-backend` 当前仅支持 `tavily`。
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

## Stage2 搜索/抽取保护（2026-01 更新）
- `search_profiles` 支持 `queries`（多语言/多 query 轮询，取 score_max 最优）与 `exclude_domains`（过滤低相关来源）；记录 `query_used/query_attempts`。
- 低分保护：全部结果 `score_max < low_score_threshold`（默认 0.2）则跳过抽取并标记 `manual_required`，统计 `low_score_drop`。
- Tavily extract 422：默认回退到 DeepSeek 从原始 snippets 抽取，并在 Summary 记录 `extract_fallback_to_deepseek`；若同指标连续 422，可用 `--auto-disable-extract-on-422` + `--extract-422-threshold` + `--extract-422-cooldown-sec`（默认 300s）对该指标短窗冷却。
- 观测日志新增 `score_min/score_p50/score_p95/score_max`、过滤/跳过原因字段（`score_filtered_drop/domain_filtered_drop/extraction_skipped_reason`）。
- 低分审计脚本：
  ```bash
  PYTHONPATH=./src python3 scripts/stage2_low_score_audit.py \
    --date YYYY-MM-DD \
    --output reports/low_score_audit_${DATE_NH}.json
  ```

## Stage2 抽取/校验优化（2026-01-28+）
- **结构化数值提取**：对 USDCNY/USDCNH/DXY/CN10Y/政策利率（RRR/MLF/逆回购）以及 northbound/southbound 增加结构化抽取，优先抓取带关键字/单位/精度的数值，过滤 1.00/9.0 等非报价数字。
- **DeepSeek 强 schema + 证据约束（2026-02-09）**：抽取统一返回 `value/unit/source_url/as_of_date/report_period/confidence/manual_required/manual_reason`；资金流额外返回 `recent_5d/total_120d/trend`。`source_url` 必须来自 snippets，否则强制 `manual_required`。
- **无值强制人工（2026-02-09）**：`no_value/deepseek_no_value/no_deepseek_key` 不再默默跳过，统一进入 `manual_required` 并记录 `manual_reason`。
- **定向二次 query（2026-02-09）**：命中 `low_score_all/单位不匹配/缺少发布机构/no_value` 时自动追加一次“单位+发布机构+月份”定向检索，降低 `skip_no_value`。
- **政策利率发布机构校验放宽**：当来源为 `tradingeconomics.com/ceicdata.com/chinamoney.com.cn/cls.cn` 时放宽 issuer 强校验，避免“缺发布机构”导致 manual。
- **北向/南向月度口径**：查询口径调整为月度/累计，并尝试从 HKEX 月度统计页提取“净流入/净流出 + 单位”。
- **排噪提醒**：USDCNY/USDCNH 避免 xe/x-rates 类 1 USD 兑换页面导致的 1.00 数值干扰。
- **regex-only 加强（2026-02-05+）**：工业增加值/工业企业营收改为“关键词 + 同比/增长”模式；regex-only 未命中时，`industrial/industrial_sales/reverse_repo/mlf` 不再走通用 fallback，直接标记 manual_required，避免误数值写入。
- **日期回填（2026-02-05+）**：抽取结果若包含 `report_period/as_of_date`，Stage2 会写回 `date` 字段，保证 trend_history 事件序列可落盘，减少 “no_previous_value”。
- **MLF 查询模板优化（2026-02-05+）**：优先中文央行公告式查询（如“人民银行 中期借贷便利 操作公告 1年期 中标利率 最新”），降低主查询 0 结果概率。
- 相关实现：`scripts/stage2_unified_enhancer.py`（`_extract_structured_value/_extract_flow_value/_refine_extraction_value`），`src/datasource/config/search_profiles.py`（query/domains/issuer_aliases）。

## Stage2 Performance / Timeout Tips (2025-12-04)
- Disable bad proxies first: prefix command with `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY` or pass `--http-proxy '' --https-proxy ''`.
- Trim long tail: keep `--fund-flow-backend tavily` and run `--tasks northbound,southbound,etf` for targeted retries，再通过 Stage2.5 补数。
- Turbo no-LLM: `--extraction-backend regex --queue-concurrency 6 --deepseek-max-concurrency 0 --deepseek-timeout 8 --queue-retry-limit 0` (faster, slightly less accurate).
- With LLM: `--deepseek-timeout 8 --queue-concurrency 5 --deepseek-max-concurrency 4 --queue-retry-limit 0`; consider two-pass `--phase essential` then `--phase assets`.
- Reduce Tavily extract load: set `top_for_extract = snippets[:2]` or `extract_depth="basic"` for commodities/forex to avoid 422/timeout.
- 低分任务保护：`--low-score-threshold 0.2`；连续 422 用 `--auto-disable-extract-on-422 --extract-422-cooldown-sec 300` 限定单指标冷却。
- 中文高频指标（USDCNY/USDCNH/CN10Y/CN10Y_CDB/北向/南向/ETF/两融/BDI）：已在 search_profiles 增补 stats.gov.cn / ce.cn / people.com.cn / cfets.com.cn / data.eastmoney.com / balticexchange.com，优先使用这些域名，避免匹配到英文新闻无数值。
- Reuse cache: keep `reports/tavily_cache.sqlite`; second run only gaps; watch `cache_hit_rate`.

### Stage2 性能瓶颈与快速模式
- 常见瓶颈：Tavily extract 422（现已自动回退 DeepSeek）；DeepSeek 请求超时（单指标可耗时 30–40s）；并发受限或串行导致总耗时上升。
- Tavily 调用策略：**当日 Stage2 只跑 1 次 tavily search/extract**，失败或 422 不要重复跑 Stage2；改用 Stage2.5 WebSearch/manual JSON（`reports/websearch_results_${DATE}_manual.json`）补数，再注入→Stage3；`--resume-from-task-file` 仅用于跨天/中断恢复。
- 快速绕行：`--extraction-backend regex --disable-extract --queue-retry-limit 0 --deepseek-max-concurrency 0`，资金流仍用 tavily，整体 30–60s 完成。
- 需要方向/高精度时再移除上述两参数启用 DeepSeek（3–5 分钟），并适当调低 `--deepseek-timeout/--deepseek-max-concurrency`。

## Proxy & Connectivity
- Prefer no global proxy in production; if needed, set in `.env` then `source .env`. If skipping proxy, prefix commands with `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY`.
- Stage2 proxy precedence: CLI `--http-proxy/--https-proxy` overrides env; when globally disabled, omit these flags.

## TLS / 证书
- Tavily 客户端支持 `TAVILY_VERIFY=false` 关闭校验（仅开发环境）；生产必须提供有效 CA，可通过 `TAVILY_CA_BUNDLE=/path/to/ca.pem` 指定。
- 仍推荐优先直连：`env -u http_proxy -u https_proxy ...`。关闭校验会有日志警告，谨慎使用。
- Quick direct check:
```bash
python - <<'PY'
import httpx
print(httpx.get('https://api.tavily.com', timeout=5, proxies=None).status_code)
PY
```
If proxy required, pass `proxies` explicitly in the check.

## Data Priority (forex/fund flow/market)
- TuShare first: Stage1 先采 TuShare 可得字段。
- Stage2 Tavily second: TuShare 不可得或缺失字段统一走 Stage2（`--fund-flow-backend tavily`）。
- Stage2.5 manual last resort: 用 `reports/websearch_results_${DATE}.json` 或手工 `_manual.json` + `inject_websearch_data_test.py` 完成补数回写。
- Market fallback: after Stage2 run `scripts/fill_market_data_from_yahoo.py`, then WebSearch injection to fill commodities/bonds/forex gaps.

## TuShare 直采口径（2026-02-09）
- `USDCNH`：`fx_daily` 需优先使用 `ts_code=USDCNH.FXCM`；`USDCNH` 常返回空数据。
- `CN10Y`：优先 `yc_cb(ts_code=1001.CB, curve_type=0, curve_term=10)`；若空则回退 `curve_type=1`。
- `CN10Y_CDB`：当前无稳定 TuShare 直采口径，仍需 WebSearch/手工注入；若为利差估算需保留 `is_estimated=True`。

## Troubleshooting 速查表
| 问题 | 原因 | 解决方案 |
|------|------|----------|
| Stage2 DeepSeek 持续超时 | API 响应慢或网络问题 | `--extraction-backend regex --disable-extract`，或降低 `--deepseek-timeout` 并串行关键指标 |
| Tavily extract 422 | API 参数/限制 | 默认回退 DeepSeek 解析 snippets；仍不稳用 `--disable-extract` 或缩小 `--extract-topk` |
| 搜索相关性低（低分全体） | 结果 `score_max < low_score_threshold` | 调整 `search_profiles.queries/exclude_domains`，必要时提高阈值并转人工补数 |
| Stage3 完整度 <80% 报错 | 关键字段为 null | 检查 macro/monetary/stock_indices，手动补数据后重注入 |
| 注入时 KeyError: 'symbol' | WebSearch JSON 缺必填字段 | 参照 WebSearch JSON Schema 补全字段 |
| 报告出现 N/A | 数据未注入或格式错误 | 查 gap_monitor，确认数字字段为可解析数值 |
| SyntaxError 启动失败 | 代码语法错误 | `python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py` |
