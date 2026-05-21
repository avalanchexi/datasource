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

2. Required keys in `.env`: `TUSHARE_TOKEN`, `TAVILY_API_KEY`, `DEEPSEEK_API_KEY`。DeepSeek 默认模型为 `deepseek-v4-pro`，可用 `.env` 的 `DEEPSEEK_MODEL` 或命令行参数覆盖；Stage2 抽取 JSON 输出 token 默认 `DEEPSEEK_EXTRACT_MAX_TOKENS=900`，可用同名环境变量调高或调低（非法值回落到 900，最低 300）。Optional: `EXA_API_KEY`（默认关闭、显式 opt-in，当前不进入日常路径；若后续启用，需已安装 `exa-py`，且 Stage2 需传 `--enable-exa-fallback` 或设置 `STAGE2_ENABLE_EXA_FALLBACK=1`）。

3. Sanity:
   ```bash
   python -c "from datasource import get_manager; print('OK')"
   datasource-test
   ```

4. Preflight（Stage1 前必跑）:
   ```bash
   bash run_preflight.sh
   ```
   脚本会校验三个 API key 长度并清理主动代理变量。终端重开或 VPN 变更后先重跑。
   默认网络模式为 `DATASOURCE_NETWORK_MODE=direct`：`run_preflight.sh`/`run_clean.sh`/`runtime_env.sh` 会清理 `http_proxy/https_proxy/HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/all_proxy`，保留 `no_proxy/NO_PROXY`。只有明确需要代理时才设置 `DATASOURCE_NETWORK_MODE=proxy`；SOCKS 代理需要 `httpx[socks]`/`socksio`，否则 preflight hard fail。
   `run_preflight.sh` 会复用 `scripts/runtime_env.sh`，统一加载 `.env`、选择 `.venv` 或显式系统 Python fallback、清理代理并设置 `PYTHONPATH=./src`。Preflight 会检查 `api.tavily.com`、`api.deepseek.com`、`api.tushare.pro` 的 DNS 与 HTTPS 基础连通性；任一失败均为运行环境 hard fail，不进入 Stage1/Stage2。默认 HTTPS 超时为 `PREFLIGHT_CONNECT_TIMEOUT=10`、`PREFLIGHT_MAX_TIME=15`，网络慢时可用环境变量覆盖。

5. 推荐统一入口:
   ```bash
   bash run_clean.sh python scripts/stage2_unified_enhancer.py --help
   bash run_clean.sh python scripts/stage3_pring_analyzer.py --help
   ```
   `run_clean.sh` 会优先激活 `.venv/bin/activate`，Windows/Git-Bash 环境再尝试 `.venv/Scripts/activate`；Ubuntu/WSL 中 `.venv` 是空目录时，可设置 `DATASOURCE_AUTO_VENV=1` 让 `scripts/bootstrap_venv.sh` 一次性创建并安装依赖。没有 venv 且未启用自动 bootstrap 时，必须显式设置 `ALLOW_SYSTEM_PYTHON=1` 才能使用系统 Python，不会静默 fallback。非空但不可用的 `.venv` 仍视为坏环境并 hard fail，应删除重建。fallback 仍会 source `.env`、清理代理，并设置 `PYTHONPATH=./src`（已有外部 `PYTHONPATH` 时保留并补齐 `./src`）。

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
  --deepseek-timeout 30 \
  --llm-hard-timeout 35 \
  --deepseek-max-concurrency 3 \
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
  --deepseek-max-concurrency 0 \
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
- 手工补数优先从 `data/runs/templates/manual_template.json` 复制对应 category 示例到当日 `websearch_results_manual.json`，再替换数值、日期和 `source_url`。
- 官方发布值、官方中间价、交易所/指数商实时值默认 `is_estimated=false`；只有利差估算、公式推导、代理序列、外推或明确近似值才写 `is_estimated=true`。
- `macro_indicators.industrial` 若使用“1-2月累计同比”等来源作为流水线当前值，必须显式写 `value_type: "yoy_month"` 和 `yoy_month`，否则会被识别为 `yoy_ytd` 并导致 `current_value` 缺失。
- `bdi` 即使在 `estimated_allowlist_keys` 内，仍受 `bdi_estimated_allow_conditions` 约束：`trusted_domains`、`max_age_days`、`value_range`、`unit_keywords` 均需通过。
- 默认允许覆盖 `is_stale=True` 的宏观/货币字段；仅补空值可加 `--no-override-stale`，应急强制覆盖可加 `--force-override`。
- official manual override 仅适用于代码内 `official manual override allowlist` 中的指标：`monetary_policy.mlf`、`forex.USDCNY`、`commodities.BCOM`。这些指标在 `_manual.json` 显式 `is_estimated=True` 时，只有提供可信官方 HTTPS `source_url` 证据才会正规化为 `is_estimated=False`，并追加 `manual_official_not_estimated`。
- 代码内 `official manual override allowlist` 不同于 `config/policy_rules.yaml` 的 `estimated_allowlist_keys`；后者当前为 `CN10Y_CDB`、`bdi`，用于 Stage3/quality 对 `is_estimated=True` 的估计值评分/告警处理，不是 official override 白名单。
- official override 要求显式 URL 字段是单个字符串 URL；混入说明文字、多个 URL、非 HTTPS、非法端口、untrusted/spoof/conflicting URL 都不能触发 override。ETF/fund_flow 不在代码内 `official manual override allowlist`，估算仍受 gate 约束。
- 普通 manual 来源不要因为不是官方域名就默认改成 estimated 或 blocked；是否 official override 只影响显式估算值能否被正规化。
- fund_flow 的 `source_url` 只证明来源存在，不自动证明 5日/120日窗口真实可用。只有 Tier1/Tier2 结构化来源、`window_evidence` 为 `direct_window`、`direct_daily_series` 或 `direct_balance_delta`，且 `metric_basis` 不是 `news_net_flow`/`estimated_net_flow` 时，才允许 `is_estimated=false`。
- fund_flow gate 的 `source_tier` 从 `source_url` 域名推断；manual JSON 中手工填写的 `source_tier`/`claimed_source_tier` 仅可作为诊断说明，不能释放 gate。
- fund_flow Tier1 域名：`hkex.com.hk`、`sse.com.cn`、`szse.cn`；Tier2 结构化 path：`data.eastmoney.com/hsgt`、`data.eastmoney.com/etf`、`data.eastmoney.com/fund`、`data.eastmoney.com/rzrq`。其他新闻、研报、季度/年度摘要和单日描述属于 Tier3，不能把外推窗口标成非估算。
- fund_flow 手工补数若使用 `news_net_flow`、`estimated_net_flow`、单日外推、季度/年度/年内摘要、外推或无法证明目标窗口，Stage2.5 会强制 `is_estimated=true` 并写入 `estimated_not_allowed` blocker；不得为了通过 gate 手工改成 `false`。
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
- `search_profiles` 支持 `query_families`、`queries`、`field_queries`、`exclude_domains`、`max_query_candidates`、`extract_policy`；Stage2 记录 `query_used/query_family_used/query_attempts`。
- Stage2 query context 区分 `daily_quote` 与 `monthly_period`：日频 quote 类任务（商品、DXY、BDI、BCOM/GSG 等）使用 `closing_date/ref_date` 模板，不继承宏观 `expected_period_tokens`；月度宏观/政策任务才使用 `expected_period/report_period` 期次 token。
- PMI 等中文宏观指标优先使用 `site:stats.gov.cn` 与国家统计局中文 query；商品期货、BCOM/GSG、DXY、BDI 等日频 quote profile 优先使用带日期/收盘/报价语义的 query，避免纯 `latest` 或概念性页面。
- Stage2 候选排序以报告可写值为目标：可信域名、关键词和 issuer 命中后，还要优先包含目标单位、日期/期次和可解析数字的片段；概念页、规格页、fact card、annual weights、forecast/analysis 等通过 `bad_url_patterns` 或 `value_evidence_miss` 降级或剔除。
- DeepSeek extraction 默认开启 queue：`--use-queue --queue-concurrency 3 --deepseek-max-concurrency 3`；默认抽取输出 token 为 `DEEPSEEK_EXTRACT_MAX_TOKENS=900`；需要串行排查时显式传 `--no-use-queue`。
- `BCOM/GSG/DXY/CN10Y_CDB` 等实时报价高缺口 profile 默认 `max_query_candidates=3`，并跳过 Tavily extract，直接将 Tavily search snippets 交给 DeepSeek 减负 schema 抽取，以减少 422 冷却和 Stage2.5 补数压力。
- `USDCNY` 是受控例外：可对 ChinaMoney/CFETS 官方表格页走 official extract top1；`official_domains_only` 严格按 hostname 匹配，若没有官方 snippets，会标记 `official_domain_filter_empty` 并阻断 Tavily extract、DeepSeek、regex fallback。
- 多 query 选优按后过滤质量，而不是原始 `score_max`：先做域名、时效、关键词、发布机构、期次过滤，再选 `usable_count` 更高的 query，并统计 `post_filter_query_switch_count`。
- 全部结果 `score_max < low_score_threshold`（默认 0.2）则跳过抽取，标记 `manual_required`，统计 `low_score_drop`。
- Tavily extract 422 默认回退 DeepSeek 从 snippets 抽取；同指标连续 422 可按指标冷却（`extract_cooldown_count`），不会全局停用其他指标 extract。仍不稳时用 `--disable-extract` 或 `--extract-topk 1`。
- Tavily search/extract 遇到 quota/rate limit 后，本轮立即 fast-switch 为 `manual_required` skeleton；不新增 quota probe，不重跑当日 Tavily。排查看 summary 的 `tavily_unavailable_reason=quota_or_rate_limit`、`retrieval_diagnostics`、`manual_reason_breakdown`。
- Exa fallback 当前默认关闭，保证 Tavily-first 命中率调优不被备用搜索源污染；需要启用时必须显式传 `--enable-exa-fallback` 或设置 `STAGE2_ENABLE_EXA_FALLBACK=1`。
- 资金流缺 `recent_5d/total_120d` 时，优先按 `field_queries` 仅补缺字段，并统计 `field_retry_count/field_retry_merged_count/field_retry_missing_fields`。
- DeepSeek 抽取 schema 已减负，默认只要求报告写回所需字段；JSON 解析失败区分 `deepseek_json_truncated` 与 `deepseek_json_parse_error`，避免把模型输出截断误判为网页无数据。`source_url` 必须来自 snippets，否则强制 `manual_required`。
- 命中 `low_score_all/单位不匹配/缺少发布机构/no_value` 时追加一次定向检索，补充单位、发布机构以及任务已有的日期/期次上下文；`daily_quote` 不强行追加宏观月份 token。
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
- `metric_basis=net_flow_sum` 仅用于目标窗口内日频净流入求和；`balance_delta` 用于余额类窗口差值；`news_net_flow` 和 `estimated_net_flow` 均不能作为真实窗口值通过 gate。
- ETF 全市场资金流目前没有稳定官方开放入口；新闻或季度报告可作为备注和估算依据，但默认 `is_estimated=true`。
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
- `fund_flow.etf`: Stage1 可用 TuShare `etf_share_size.total_size` 计算全市场规模窗口变化，`metric_basis=etf_total_size_delta`；该口径是 ETF 规模 delta，不等同于新闻口径净流入。若 TuShare 不可得、窗口不完整或质量阻断，继续 Stage2/Stage2.5 补数。
- `DXY`: Stage1 可探测 TuShare `fx_obasic` 的 `FX_BASKET`/`USDOLLAR.FXCM` 并用 `fx_daily` 取数；报告必须标注为 TuShare `USDOLLAR` proxy，不得写成 ICE DXY。若不可得或不完整，继续 Stage2/Stage2.5。
- `USDCNH`: `fx_daily` 优先使用 `ts_code=USDCNH.FXCM`；`USDCNH` 常返回空。
- `CN10Y`: 优先 `yc_cb(ts_code=1001.CB, curve_type=0, curve_term=10)`；若空则回退 `curve_type=1`。
- `CN10Y_CDB`: 当前无稳定 TuShare 直采口径，仍需 WebSearch/手工注入；若为利差估算需保留 `is_estimated=True`。
- 不得静默用近似 TuShare 接口替换 `commodities.GC=F/CL=F/BZ=F/HG=F`、`commodities.BCOM`、`commodities.GSG`、`bonds.CN10Y_CDB`、`macro_indicators.industrial`、`macro_indicators.industrial_sales`、`macro_indicators.bdi`、`monetary_policy.reserve_ratio`、`monetary_policy.reverse_repo`、`monetary_policy.mlf`；无稳定口径时应进入 Stage2/Stage2.5 或保留质量阻断。
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

Stage2 summary 口径：`task_completed/task_total` 仅表示 legacy completion；真实命中率看 `task_search_success/task_search_failed/search_success_rate_incremental`，并结合 `retrieval_diagnostics`、`manual_reason_breakdown` 判断失败来源；已有值跳过看 `task_skipped_existing`，quota/rate limit 看 `tavily_unavailable_reason=quota_or_rate_limit`。若 `retrieval_hit` 高但写回低，优先看 `value_evidence_miss`、`deepseek_json_truncated/deepseek_json_parse_error`、`field_retry_merged_count`、`field_retry_missing_fields`。

## 12. Troubleshooting
| 问题 | 原因 | 解决方案 |
|------|------|----------|
| Preflight DNS 失败 | DNS/WSL/容器网络不可达 | 修复 `/etc/resolv.conf` 或宿主网络后重跑 `bash run_preflight.sh`；不要启动 Stage2 |
| `.venv` 目录存在但不可用 | 空目录或 Windows/Linux venv 混用 | 空 `.venv` 视同无 venv，可显式 `ALLOW_SYSTEM_PYTHON=1` fallback；非空但无可用 activate/python 时删除并重建 `.venv` |
| Stage2 DeepSeek 持续超时 | API 响应慢、并发过高或输出预算不合适 | 默认使用 `--deepseek-timeout 30 --llm-hard-timeout 35` 与 `DEEPSEEK_EXTRACT_MAX_TOKENS=900`；仍持续超时时改用 `--extraction-backend regex --disable-extract`，或串行关键指标 |
| DeepSeek 返回 JSON 失败 | 输出截断或格式错误 | 看 `manual_reason`：`deepseek_json_truncated` 先适度调高 `DEEPSEEK_EXTRACT_MAX_TOKENS` 或转 Stage2.5；`deepseek_json_parse_error` 优先查 prompt/schema 与 source snippets |
| Tavily extract 422 | API 参数/限制 | 默认回退 DeepSeek；仍不稳用 `--disable-extract` 或 `--extract-topk 1` |
| USDCNY 官方表格未抽取 | official-only snippets 为空或 hostname 不匹配 | 看 `official_domain_filter_empty`；不要放宽到非官方 fallback，转 Stage2.5 补可信官方来源 |
| Tavily quota/rate limit | Tavily 额度或频率限制 | 同轮 fast-switch 为 `manual_required` skeleton；不要新增 quota probe 或重跑当日 Tavily，查看 `tavily_unavailable_reason=quota_or_rate_limit`、`retrieval_diagnostics`、`manual_reason_breakdown` 后转 Stage2.5 补数 |
| 当日 Stage2 已失败 | Tavily 不应重复消耗 | 转 Stage2.5 manual JSON 补数并注入 |
| 搜索相关性低 | `score_max < low_score_threshold` | 调整 `search_profiles.queries/exclude_domains`，必要时转人工补数 |
| 搜索命中但不可写报告 | 命中概念页/规格页/预测页，或缺目标日期/单位/数值证据 | 查 `value_evidence_miss` 与 `bad_url_patterns`，补 dated quote query 或转 Stage2.5 |
| 宏观/货币显示旧月份 | TuShare 月度表滞后，`is_stale=true` | 跑 `check_monthly_freshness.py data/runs/${DATE_NH}/market_data.json`，再 Stage2/Stage2.5 覆盖 stale 字段 |
| Stage3 完整度 <80% | 关键字段为 null | 检查 macro/monetary/stock_indices，补数后重注入 |
| Stage3 `block_stage3=True` 但数据已注入 | policy gate 仍有 redlist 或顶层缺口 | 检查 `missing_items`、`policy_evaluation.json`、`gap_monitor.json`，补齐后重跑 Stage2.5/Stage3 |
| Stage3 `compare_gaps` 阻断 | 缺 `previous_value` | 补齐对应 `previous_value`；`--allow-estimated` 不绕过 |
| `industrial current_value is missing` | manual JSON 中“累计”文本触发 `yoy_ytd`，但未显式 `yoy_month` | 按模板补 `value_type: "yoy_month"`、`yoy_month`、`current_value` 后重跑 Stage2.5 |
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
