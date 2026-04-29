# AGENTS Playbook

> 沟通约定：与用户/同事的交互和问题说明优先使用中文，命令保持原文。

## 0. 文档职责
- `AGENTS.md` 是本仓库的权威操作手册，覆盖流水线、数据口径、校验规则、排障和代码规范。
- `CLAUDE.md` 只保留 Claude Code 的快速索引和高频提醒；若两者冲突，以 `AGENTS.md` 为准，并同步修正 `CLAUDE.md`。
- 更新本文件时只记录可复用流程、规则和长期口径，不写当日临时数值或一次性结论。
- 生成日报/背景扫描报告前，先列出 3-5 步 plan，覆盖 Stage2.5 补数、Stage3 分析、Report 输出和收尾校验。仅重跑已齐全数据的报告时，可明确说明“任务简单，按既定流程直接执行”。

## 1. Repo Map
- Core: `src/datasource/`（adapters, managers, calculators, engines, cache helpers, utils）。
- Config: `src/datasource/config/indices_config.py`, `src/datasource/config/search_profiles.py`, root `config/`（`quality_thresholds.json`, `policy_rules.yaml`）。
- Data: `data/runs/YYYYMMDD/`（单次运行产物），`data/trend_history/`（趋势历史滚动窗口，非 SQLite），`data/cache/tavily_cache.sqlite`。
- Logs: `logs/runs/YYYYMMDD/observability.json`。
- Tests: `tests/`，fixtures in `tests/test_data_sources/`，helpers in `tests/test_datasource.py`。
- Templates: `templates/`；generated reports: `reports/`（合并前需复核）。
- Long jobs: `scripts/`（含 `trend_history_scan.py`, `trend_history_backfill.py`, `run_snapshot.py`）；历史/低频脚本放 `scripts/legacy/` 或 `scripts/archive/`。
- Diagnostics: `scripts/stage2_health_check.py`, `scripts/stage2_low_score_audit.py`, `scripts/compare_stage2_runs.py`。

## 2. 不可破坏约束
- 严禁从历史 `reports/*.md` 抓取或复用数据；报告只能来自 TuShare、Tavily/AI WebSearch 实时获取结果或各 stage 计算产出。
- `trend_history` 禁止从 `reports/*.md` 反向回填；只允许 Stage1/Stage2.5 写入或 TuShare 回补。
- 当日 Stage2 Tavily search/extract 只跑 1 次。失败、422 或低分后不要反复消耗 Tavily，缺口转 Stage2.5 `_manual.json` 注入。
- 采集优先级固定：TuShare(Stage1) -> Stage2(Tavily+DeepSeek) -> Stage2.5(manual/WebSearch 注入)。旧版 Yahoo/AKShare 外部补数链路仅作为 legacy 应急。
- 手工填写的数值必须有实时来源证据；`_manual.json` 中凡填写数值的条目必须带 `source_url`，或在 `source`/`note` 中包含 URL。
- `0/None`、窗口值缺失、`no_value/deepseek_no_value/no_deepseek_key` 一律进入 `manual_required`；零值标记为 `异常零值-需核查`。
- Stage3 的 `--allow-estimated` 只允许 `is_estimated=True` 数据参与评分，不绕过 `compare_gaps`、`stale_redlist` 或 policy gate。

## 3. Setup & Health Check
1. Create env:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -e .
   pip install -e ".[dev]"
   cp .env.example .env
   ```
   Windows activate: `.venv\Scripts\activate`。

2. Required keys in `.env`: `TUSHARE_TOKEN`, `TAVILY_API_KEY`, `DEEPSEEK_API_KEY`。DeepSeek 默认模型为 `deepseek-v4-pro`，可用 `.env` 的 `DEEPSEEK_MODEL` 或命令行参数覆盖。Optional: `EXA_API_KEY`（默认关闭、显式 opt-in，当前不进入日常路径；若后续启用，需已安装 `exa-py`，且 Stage2 需传 `--enable-exa-fallback` 或设置 `STAGE2_ENABLE_EXA_FALLBACK=1`）。

3. Sanity:
   ```bash
   python -c "from datasource import get_manager; print('OK')"
   datasource-test
   ```

4. Preflight（Stage1 前必跑）:
   ```bash
   bash run_preflight.sh
   ```
   脚本会校验三个 API key 长度并清空 `http_proxy/https_proxy/HTTP_PROXY/HTTPS_PROXY`。终端重开后先重跑。

5. 推荐统一入口:
   ```bash
   bash run_clean.sh python scripts/stage2_unified_enhancer.py --help
   bash run_clean.sh python scripts/stage3_pring_analyzer.py --help
   ```
   `run_clean.sh` 会优先激活 `.venv/bin/activate`，Windows/Git-Bash 环境再尝试 `.venv/Scripts/activate`；没有 venv 时必须显式设置 `ALLOW_SYSTEM_PYTHON=1` 才能使用系统 Python，不会静默 fallback。fallback 仍会 source `.env`、清理代理，并设置 `PYTHONPATH=./src`（已有外部 `PYTHONPATH` 时保留并补齐 `./src`）。

6. Optional checks:
   ```bash
   bash run_clean.sh python scripts/stage2_health_check.py
   python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py
   ```

## 4. Style, Tests, PR
- Python >=3.7, 4-space indent, UTF-8。
- Prefer async with `DataSourceManager`; adapters 保持薄，业务逻辑放 engines/calculators/utils。
- `lower_snake_case` for modules/vars/functions; `CamelCase` classes; constants `UPPER_SNAKE_CASE`。
- 配置优先放 `indices_config.py`, `search_profiles.py`, `config/*.yaml/json`；只为非显然意图写注释。
- Smoke: `pytest -q` 或 `datasource-test`。
- Focused: `python tests/test_datasource.py`, `python tests/simple_test.py`, `python tests/test_na_filling.py`。
- 质量命令：`black src/ tests/ scripts/`, `flake8 src/`, `mypy src/datasource/...`；如跳过需说明原因。
- Commit 使用 Conventional Commits: `feat:`, `fix:`, `refactor:`，一个 commit 一个逻辑变化。
- Review 若 `HEAD` 相对基线无代码差异，结论必须写明“无可审查代码差异、无可执行问题”，不得臆造问题。若 review 识别出流程或口径问题，需同步更新本文件对应章节。

## 5. Stage1 -> Stage4 Daily Run
推荐全部命令通过 `bash run_clean.sh ...` 执行。

```bash
DATE=$(date +%Y-%m-%d)
DATE_NH=${DATE//-/}
bash run_preflight.sh
```

### 5.1 Trend History 预检
```bash
bash run_clean.sh python scripts/trend_history_scan.py --date "$DATE"
```
- 默认输出：`reports/trend_history_gap_${DATE_NH}.json`。
- 缺口较大时，优先做 TuShare 可得数据回补：
  ```bash
  bash run_clean.sh python scripts/trend_history_backfill.py --start "YYYY-MM-DD" --end "YYYY-MM-DD"
  ```

### 5.2 Stage1 API 采集
```bash
bash run_clean.sh python scripts/stage1_data_collector.py \
  --date "$DATE" \
  --output "data/runs/${DATE_NH}/market_data.json"
```
- 商品行情不走 Yahoo/Investing 兜底；北向/南向/ETF 资金流写占位符，后续必补。
- Stage1 后必须跑月度新鲜度检查：
  ```bash
  bash run_clean.sh python scripts/check_monthly_freshness.py \
    "data/runs/${DATE_NH}/market_data.json"
  ```
- 若输出 `STALE/MISSING`（典型：`cpi/ppi/pmi/m1/m2/tsf`），必须继续 Stage2/Stage2.5 覆盖，未清零不得进入 Stage3。

### 5.3 Stage2 Tavily+DeepSeek 增强
首次运行推荐精度优先；同日只跑一次 Tavily。

```bash
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/${DATE_NH}/market_data.json" \
  --output "data/runs/${DATE_NH}/market_data_stage2.json" \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend deepseek \
  --deepseek-timeout 12 \
  --llm-hard-timeout 12 \
  --deepseek-max-concurrency 1 \
  --queue-retry-limit 0 \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results "data/runs/${DATE_NH}/websearch_results_auto.json" \
  --log-output "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json"
```

仅补缺时可走快速模式，通常要配合 `--tasks`：
```bash
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/${DATE_NH}/market_data.json" \
  --output "data/runs/${DATE_NH}/market_data_stage2.json" \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend regex \
  --disable-extract \
  --deepseek-timeout 8 \
  --deepseek-max-concurrency 1 \
  --queue-retry-limit 0 \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results "data/runs/${DATE_NH}/websearch_results_auto.json" \
  --log-output "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json"
```

### 5.4 Stage2.5 WebSearch/manual 注入
将实时搜索结果写入 `data/runs/${DATE_NH}/websearch_results_manual.json`，再执行：

```bash
# Stage2.5 -> Stage3 -> Stage4 使用统一 run path contract
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"
```

- 输入也可用 Stage2 自动结果 `websearch_results_auto.json`；脚本会自动转换 `results` 结构，并保留 `manual_required/manual_reason` 生成 `metadata.manual_required` 骨架。
- 默认允许覆盖 `is_stale=True` 的宏观/货币字段；仅补空值可加 `--no-override-stale`，应急强制覆盖可加 `--force-override`。
- official manual override 仅适用于代码内 `official manual override allowlist` 中的指标：`monetary_policy.mlf`、`forex.USDCNY`、`commodities.BCOM`。这些指标在 `_manual.json` 显式 `is_estimated=True` 时，只有提供可信官方 HTTPS `source_url` 证据才会正规化为 `is_estimated=False`，并追加 `manual_official_not_estimated`。
- 代码内 `official manual override allowlist` 不同于 `config/policy_rules.yaml` 的 `estimated_allowlist_keys`；后者当前为 `CN10Y_CDB`、`bdi`，用于 Stage3/quality 对 `is_estimated=True` 的估计值评分/告警处理，不是 official override 白名单。
- official override 要求显式 URL 字段是单个字符串 URL；混入说明文字、多个 URL、非 HTTPS、非法端口、untrusted/spoof/conflicting URL 都不能触发 override。ETF/fund_flow 不在代码内 `official manual override allowlist`，估算仍受 gate 约束。
- 普通 manual 来源不要因为不是官方域名就默认改成 estimated 或 blocked；是否 official override 只影响显式估算值能否被正规化。
- 注入成功后会刷新 `data/runs/${DATE_NH}/quality_metrics.json`、写入 trend_history，并清理 `metadata.missing_items` 与顶层 `missing_items`。
- 若终端显示“注入数据项: 0”，说明结果无可解析数值或文件为空，应改用手工 schema 版 `_manual.json`。

### 5.5 Stage3 Pring 分析
```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated
```

### 5.6 Stage4 Report
```bash
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md"
```

### 5.7 收尾校验
- `data/runs/${DATE_NH}/gap_monitor.json` 无 `pending_tasks/manual_required`。
- 报告内无 `N/A（待 WebSearch）`、`无数据`。
- 关键月度字段 `is_stale=False`。
- 估计值清单可接受且有来源说明。
- `metadata.data_completeness >= 0.8`：
  ```bash
  python -c "
import json
p='data/runs/${DATE_NH}/market_data_complete.json'
d=json.load(open(p, encoding='utf-8'))
comp=d.get('metadata',{}).get('data_completeness',0)
print(f'数据完整度: {comp*100:.1f}%')
if comp < 0.8:
    nulls=[f'{cat}.{k}' for cat in ['macro_indicators','monetary_policy','stock_indices']
           for k,v in d.get(cat,{}).items()
           if isinstance(v,dict) and v.get('current_value') is None]
    print('WARNING: Null字段需补充:', nulls)
"
  ```

## 6. Stage2 搜索/抽取规则
- Stage2 Unified 中 fund flow 与 forex 统一使用 `tavily`；`--fund-flow-backend` 当前仅支持 `tavily`。
- Real-time search params: `language=chinese`, `topic=news`, `time_range=day`, `max_results<=8`, `search_depth=advanced`；宏观/低时效指标用 `time_range=year/month`, `max_results<=6`, `search_depth=basic`。
- `search_profiles` 支持 `query_families`、`queries`、`field_queries`、`exclude_domains`；Stage2 记录 `query_used/query_family_used/query_attempts`。
- 多 query 选优按后过滤质量，而不是原始 `score_max`：先做域名、时效、关键词、发布机构、期次过滤，再选 `usable_count` 更高的 query，并统计 `post_filter_query_switch_count`。
- 全部结果 `score_max < low_score_threshold`（默认 0.2）则跳过抽取，标记 `manual_required`，统计 `low_score_drop`。
- Tavily extract 422 默认回退 DeepSeek 从 snippets 抽取；同指标连续 422 可按指标冷却（`extract_cooldown_count`），不会全局停用其他指标 extract。仍不稳时用 `--disable-extract` 或 `--extract-topk 1`。
- Tavily search/extract 遇到 quota/rate limit 后，本轮立即 fast-switch 为 `manual_required` skeleton；不新增 quota probe，不重跑当日 Tavily。排查看 summary 的 `tavily_unavailable_reason=quota_or_rate_limit`、`retrieval_diagnostics`、`manual_reason_breakdown`。
- Exa fallback 当前默认关闭，保证 Tavily-first 命中率调优不被备用搜索源污染；需要启用时必须显式传 `--enable-exa-fallback` 或设置 `STAGE2_ENABLE_EXA_FALLBACK=1`。
- 资金流缺 `recent_5d/total_120d` 时，优先按 `field_queries` 仅补缺字段，并统计 `field_retry_count`。
- DeepSeek 强 schema：`value/unit/source_url/as_of_date/report_period/confidence/manual_required/manual_reason`；fund flow 额外返回 `recent_5d/total_120d/trend`。`source_url` 必须来自 snippets，否则强制 `manual_required`。
- 命中 `low_score_all/单位不匹配/缺少发布机构/no_value` 时追加一次“单位+发布机构+月份”定向检索。
- LangChain 默认禁用；实验时必须显式传 `--allow-langchain` 并自备依赖。
- 低分审计：
  ```bash
  bash run_clean.sh python scripts/stage2_low_score_audit.py \
    --date YYYY-MM-DD \
    --output "data/runs/${DATE_NH}/low_score_audit.json"
  ```

## 7. WebSearch JSON Schema
`scripts/stage2_5_injector.py` 要求以下必填字段；数值字段必须可解析为数字，不能是“波动”“净流入”等描述性文本。

| 类别 | 必填字段 | 示例 |
|------|----------|------|
| commodities | `symbol`, `name`, `current_price`, `unit` | `{"symbol": "GC=F", "name": "COMEX黄金", "current_price": 2650.5, "unit": "$/oz", "source_url": "https://..."}` |
| forex | `pair`, `name`, `current_rate` | `{"pair": "USDCNY", "name": "USD/CNY在岸", "current_rate": 7.248, "source_url": "https://..."}` |
| bonds | `symbol`, `name`, `current_yield` | `{"symbol": "US10Y", "name": "美国10年期国债", "current_yield": 4.18, "source_url": "https://..."}` |
| fund_flow | `recent_5d`, `total_120d`, `trend`, `source` | `{"recent_5d": 85.6, "total_120d": 1250.0, "trend": "流入", "source": "tavily+deepseek", "source_url": "https://..."}` |

## 8. Fund Flow Data Standard
- 北向、南向、ETF、融资融券：禁止 AKShare 直接写最终值；仅允许 TuShare 可得字段、WebSearch 实时来源或 Stage2.5 手工补数。
- 异常检测：任一 `0/None` 或窗口值缺失，都标记 `manual_required` 并进入 Stage2.5。
- 来源标注：`tavily+deepseek`、`待人工补数(Stage2 manual_required)`、`异常零值-需核查`。
- Stage2 资金流定向命令：
  ```bash
  bash run_clean.sh python scripts/stage2_unified_enhancer.py \
    --market-data "data/runs/${DATE_NH}/market_data.json" \
    --output "data/runs/${DATE_NH}/market_data_stage2.json" \
    --phase all --execute-search \
    --fund-flow-backend tavily \
    --tasks northbound,southbound,etf \
    --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
    --websearch-results "data/runs/${DATE_NH}/websearch_results_auto.json" \
    --log-output "logs/runs/${DATE_NH}/stage2_unified_log.json" \
    --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json"
  ```
- Data shape:
  ```python
  {
      "recent_5d": 123.45,
      "total_120d": 456.78,
      "trend": "流入",
      "source": "tavily+deepseek",
      "note": "来源:东方财富网",
      "source_url": "https://...",
  }
  ```

## 9. Trend History
- 目录结构：`data/trend_history/min/series/{category}/{symbol}.json`、`data/trend_history/min/events/{indicator}.json`。
- 窗口规则：股指 200 交易日；外汇/商品/债券 121 交易日；资金流 120 交易日；宏观/政策事件 24 条。
- 写入策略：Stage1 部分写入（`is_partial=true`），Stage2.5 最终覆盖。
- 交易日对齐依赖 TuShare `trade_cal`；缺口过大需手工补或标记估计值。
- 写入防护：过滤低质量标记（如“数值超出合理区间”“异常零值”“regex_only且缺少发布机构”）；CN10Y/CN10Y_CDB 禁止 ETF 代理写入；回补脚本跳过 `bond_etf_proxy` 来源；不使用“真实范围”作硬性校验标准。

## 10. 数据口径
- TuShare first: Stage1 优先采 TuShare 可得字段（宏观、股指日线、两融余额等）。
- Stage2 Tavily second: TuShare 不可得或缺失字段统一走 Stage2。
- Stage2.5 last resort: 用 `data/runs/${DATE_NH}/websearch_results_manual.json` 或手工 `_manual.json` 注入。
- Market fallback: legacy-only path，必要时运行 `scripts/legacy/fill_market_data_from_yahoo.py`，再通过 Stage2.5 注入补 commodities/bonds/forex 缺口。
- `USDCNH`: `fx_daily` 优先使用 `ts_code=USDCNH.FXCM`；`USDCNH` 常返回空。
- `CN10Y`: 优先 `yc_cb(ts_code=1001.CB, curve_type=0, curve_term=10)`；若空则回退 `curve_type=1`。
- `CN10Y_CDB`: 当前无稳定 TuShare 直采口径，仍需 WebSearch/手工注入；若为利差估算需保留 `is_estimated=True`。
- 债券日期列展示“最近可用日期”，优先 `as_of_date/date/report_period`，不强制等于报告日。Stage1/Stage2 写入债券收益率时不得清空已存在日期字段。
- 宏观 `change_rate` 统一为百分比：`(current-previous)/abs(previous)*100`；分母为 0 时标记 `reason=change_rate_pct_div_by_zero` 并进入质量阻断。
- Stage4 MLF 展示：当 `policy_name`、`note`、`source` 或 `manual_reason` 中出现 `多重价位`、`中标利率`、`参考值`、`口径不适用`、`无统一利率`、`美式招标`、`利率区间` 等 marker 时，当前值显示为类似 `2.00%（参考）`，120 日变化显示 `口径不适用`；普通货币政策当前值保持两位百分比，变化保持 `pp`。

## 11. 运行产物
| Stage | Output | Purpose |
|-------|--------|---------|
| Stage1 | `data/runs/${DATE_NH}/market_data.json` | 原始 API 数据 |
| Stage2 | `data/runs/${DATE_NH}/market_data_stage2.json` | 增强后数据 |
| Stage2 | `data/runs/${DATE_NH}/websearch_results_auto.json` | Tavily 搜索结果 |
| Stage2 | `data/runs/${DATE_NH}/gap_monitor.json` | 缺口追踪 |
| Stage2 | `data/runs/${DATE_NH}/quality_metrics.json` | 质量指标 |
| Stage2 | `data/runs/${DATE_NH}/source_conflicts.json` | 冲突解决 |
| Stage2 | `data/runs/${DATE_NH}/policy_evaluation.json` | 策略评估 |
| Stage2 | `data/runs/${DATE_NH}/run_snapshot.json` | 运行快照/审计 |
| Stage2 | `logs/runs/${DATE_NH}/observability.json` | 指标级耗时/来源/失败类型 |
| Stage2.5 | `data/runs/${DATE_NH}/market_data_complete.json` | 注入完成后数据 |
| Stage3 | `data/runs/${DATE_NH}/pring_result.json` | Pring 分析输出 |
| Stage4 | `reports/${DATE}-背景扫描120.md` | 最终报告 |

Stage2 summary 口径：`task_completed/task_total` 仅表示 legacy completion；真实命中率看 `task_search_success/task_search_failed/search_success_rate_incremental`，并结合 `retrieval_diagnostics`、`manual_reason_breakdown` 判断失败来源；已有值跳过看 `task_skipped_existing`，quota/rate limit 看 `tavily_unavailable_reason=quota_or_rate_limit`。

## 12. Troubleshooting
| 问题 | 原因 | 解决方案 |
|------|------|----------|
| Stage2 DeepSeek 持续超时 | API 响应慢或网络问题 | `--extraction-backend regex --disable-extract`，降低 `--deepseek-timeout`，或串行关键指标 |
| Tavily extract 422 | API 参数/限制 | 默认回退 DeepSeek；仍不稳用 `--disable-extract` 或 `--extract-topk 1` |
| Tavily quota/rate limit | Tavily 额度或频率限制 | 同轮 fast-switch 为 `manual_required` skeleton；不要新增 quota probe 或重跑当日 Tavily，查看 `tavily_unavailable_reason=quota_or_rate_limit`、`retrieval_diagnostics`、`manual_reason_breakdown` 后转 Stage2.5 补数 |
| 当日 Stage2 已失败 | Tavily 不应重复消耗 | 转 Stage2.5 manual JSON 补数并注入 |
| 搜索相关性低 | `score_max < low_score_threshold` | 调整 `search_profiles.queries/exclude_domains`，必要时转人工补数 |
| 宏观/货币显示旧月份 | TuShare 月度表滞后，`is_stale=true` | 跑 `check_monthly_freshness.py data/runs/${DATE_NH}/market_data.json`，再 Stage2/Stage2.5 覆盖 stale 字段 |
| Stage3 完整度 <80% | 关键字段为 null | 检查 macro/monetary/stock_indices，补数后重注入 |
| Stage3 `block_stage3=True` 但数据已注入 | policy gate 仍有 redlist 或顶层缺口 | 检查 `missing_items`、`policy_evaluation.json`、`gap_monitor.json`，补齐后重跑 Stage2.5/Stage3 |
| Stage3 `compare_gaps` 阻断 | 缺 `previous_value` | 补齐对应 `previous_value`；`--allow-estimated` 不绕过 |
| 注入时报 `KeyError: 'symbol'` | WebSearch JSON 缺必填字段 | 按 WebSearch JSON Schema 补全 |
| 报告出现 N/A | 数据未注入或格式错误 | 查 `gap_monitor.json`，确认数字字段为可解析值 |
| 报告债券日期列为 N/A | 缺 `date/as_of_date/report_period` 或旧口径 | 重跑 Stage1->Stage4，确认 `bonds[].date/as_of_date` 已写入 |
| 代理/TLS 问题 | 环境代理污染或证书异常 | 优先 `run_clean.sh`；开发环境才可用 `TAVILY_VERIFY=false`，生产需有效 CA 或 `TAVILY_CA_BUNDLE` |
| SyntaxError 启动失败 | 代码语法错误 | `python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py` |


# Codex + gstack

Codex CLI should invoke gstack skills only through `$` syntax. When the user writes
`$qa`, `$ship`, `$review`, `$browse`, `$plan-*`, `$design-*`, or `$gstack-*`, treat
it as a request to run the matching `SKILL.md` workflow.

Find the skill in `.agents/skills/gstack/`, `gstack-source/`,
`~/.claude/skills/gstack/`, or `~/.codex/skills/gstack/`. Read it first, follow its
sequence, and translate Claude tools to Codex equivalents: shell for `Bash`, `rg`
and file reads for `Read/Glob/Grep`, `apply_patch` for edits, concise text
questions for `AskUserQuestion`, and available browser/gstack tooling for `$B`.
# Codex + gstack

Codex MUST run gstack skills only when the user uses `$skill` syntax, e.g. `$qa`,
`$ship`, `$review`, `$browse`, `$plan-eng-review`, or `$gstack-qa`.

On `$skill`, Codex MUST stop normal execution, locate the matching `SKILL.md`,
read it first, and follow its workflow step by step. Do not improvise or summarize
the skill instead of executing it.

Resolve skill names by adding `gstack-` when needed: `$qa` -> `gstack-qa`,
`$gstack-qa` -> `gstack-qa`.

Search in this order:
1. `gstack-source/.agents/skills/<skill>/SKILL.md`
2. `.agents/skills/<skill>/SKILL.md`
3. `gstack-source/<name-without-gstack-prefix>/SKILL.md`
4. `~/.claude/skills/gstack/<name-without-gstack-prefix>/SKILL.md`
5. `~/.codex/skills/gstack/<skill>/SKILL.md`

Map Claude tools to Codex tools: `Bash` -> shell, `Read/Glob/Grep` -> file reads
and `rg`, `Write/Edit` -> `apply_patch`, `AskUserQuestion` -> a concise question,
`$B` -> available browser/gstack tooling.

If no matching `SKILL.md` exists, stop and report the missing skill path.

