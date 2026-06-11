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
- Long jobs: `scripts/`（含 `trend_history_scan.py`, `trend_history_backfill.py`, `run_snapshot.py`）；历史/低频脚本已归档至 `archive/py_unused/legacy/`，当前保留但不属于 Stage1-4 主流程的手工辅助脚本见 `scripts/utility/`；`scripts/archive/` 为归档/手工分析脚本，不跑正常 Stage1-4。
- Diagnostics: `scripts/stage2_health_check.py`, `scripts/stage2_low_score_audit.py`, `scripts/compare_stage2_runs.py`。

## 2. 不可破坏约束
- 严禁从历史 `reports/*.md` 抓取或复用数据；报告只能来自 TuShare、Tavily/AI WebSearch 实时获取结果或各 stage 计算产出。
- `trend_history` 禁止从 `reports/*.md` 反向回填；只允许 Stage1/Stage2.5 写入或 TuShare 回补。
- 当日 Stage2 Tavily search/extract 只跑 1 次。Stage2 默认先跑 structured-provider；结构化源失败、超时、解析失败或质量 gate 阻断后才进入 Tavily-first 搜索。Tavily quota/rate/payment 类失败且配置 `EXA_API_KEY` 时可同轮切换 Exa；422、低分或网络类错误不要反复消耗 Tavily，缺口转 Stage2.5 `_manual.json` 注入。
- 采集优先级固定：TuShare(Stage1) -> Stage2(structured-provider-first + Tavily-first，必要时 Exa quota failover + DeepSeek/regex) -> Stage2.5(manual/WebSearch 注入)。排障可传 `--disable-structured-providers` 只跑原搜索链路；旧版 Yahoo/AKShare 外部补数链路已归档，仅作历史应急参考，不在当前流程执行。
- Stage2.5、Stage3、Stage4 会对 `data/runs/YYYYMMDD/.run.lock` 加写锁；同一日期不得并行运行这些写产物阶段。遇到 live owner 锁时先确认/停止并行会话，不手动删除；只有 stale/dead pid 或 stale corrupt lock 才允许自动回收。
- BCOM/GSG 等美股/海外收盘类 daily quote 的搜索 `closing_date` 使用报告日前最近一个已完成交易日候选；结构化 quote 页面的 `as_of_date` 必须来自日期行或 labelled close 附近的显式页面日期，不能把周末/节假日的 `reference_date - 1` 伪造成收盘日期。报告 `ref_date` 仍保持当日报告日；不要用“今日”概念页或盘中快照替代目标收盘。
- 手工填写的数值必须有实时来源证据；`_manual.json` 中凡填写数值的条目必须带 `source_url`，或在 `source`/`note` 中包含 URL。
- `0/None`、窗口值缺失、`no_value/deepseek_no_value/no_deepseek_key` 一律进入 `manual_required`；零值标记为 `异常零值-需核查`。
- forex 的 `daily_change/change_120d=0.0` 只有在 snippets/结构化字段明确证明无变化或直接窗口计算时才保留；仅有当前汇率、`no_value`、`no_deepseek_key`、`no change_120d value` 等占位/缺值短语时必须清洗为待补 compare 字段并进入 Stage2.5。
- Stage3 的 `--allow-estimated` 只允许 `is_estimated=True` 数据参与评分，不绕过 `compare_gaps`、`stale_redlist` 或 policy gate。

## 3. Setup & Health Check
0. Shell/venv 探活（任何 Stage1/Stage2 前先跑）:
   ```bash
   bash scripts/env_probe.sh
   ```
   `env_probe.sh` 只检查本地执行通道，不读取 API key、不访问外网、不替代 preflight。若输出 `OK`，继续 `bash run_preflight.sh`；若输出 `USE_WSL`，说明当前 shell 与仓库/venv 布局错配，应切到 `C:\Windows\System32\bash.exe` 进入 WSL 后再执行项目脚本；若输出同时包含 `dofork` 和 `errno 11` 的 Git/MSYS bash 错误时，不要反复重跑流水线或优先杀进程，先切 WSL。

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

2. Required keys in `.env`: `TUSHARE_TOKEN`, `TAVILY_API_KEY`, `DEEPSEEK_API_KEY`。DeepSeek 默认模型为 `deepseek-v4-pro`，可用 `.env` 的 `DEEPSEEK_MODEL` 或命令行参数覆盖；Stage2 抽取 JSON 输出 token 默认 `DEEPSEEK_EXTRACT_MAX_TOKENS=900`，可用同名环境变量调高或调低（非法值回落到 900，最低 300）。Optional but recommended: `EXA_API_KEY`，用于 Tavily 返回 402/403/429/quota/rate-limit/payment 时的同轮 failover；非 quota 类 Exa fallback 仍需显式传 `--enable-exa-fallback` 或设置 `STAGE2_ENABLE_EXA_FALLBACK=1`。

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
- Focused: `python tests/test_datasource.py`, `python tests/simple_test.py`。
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

### 5.3 Stage2 structured-provider-first + Tavily/DeepSeek 增强
首次运行推荐精度优先；Stage2 默认先尝试可信结构化源，随后再走 Tavily-first 搜索链路；同日只跑一次 Tavily。

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

- structured-provider-first 覆盖：`GC=F/CL=F/BZ=F/HG=F/GSG`、`reverse_repo/mlf/USDCNY/industrial/industrial_sales`、`CN10Y_CDB`、`DXY/bdi`、`etf` 会先尝试可信结构化源；同一 key 支持 provider 级顺序兜底，全部失败后才进入搜索。
- 当前结构化来源：商品期货优先 Trading Economics，`BCOM/GSG` 可用已验证 quote 页面收盘价，`GSG` 也可用 Stooq CSV 市价，`USDCNY` 使用 ChinaMoney JSON，工业/工业营收 follow 国家统计局详情页，逆回购/RRR 可用央行/Trading Economics，ETF 先尝试 TuShare `etf_share_size`，再走 EastMoney/search。
- 结构化源失败、超时、解析失败或质量 gate 阻断时，继续 Tavily-first 搜索；Tavily quota/rate/payment 不可用时进入 Exa failover。
- 排障可追加 `--disable-structured-providers`，只跑原 Tavily/Exa/DeepSeek 搜索链路。
- Stage2 真实命中率优先看 `stage2_effective_hit_rate`；它包含 structured-provider 成功和搜索抽取成功，不包含 `skipped_existing`，也不包含 Stage2.5 manual 注入。

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

- 输入也可用 Stage2 自动结果 `websearch_results_auto.json`；脚本会自动转换 `results` 结构，并保留 `manual_required/manual_reason` 生成 `metadata.manual_required` 骨架；自动结果转换必须保留 `is_estimated/estimation_method/metric_basis/confidence`，尤其是 `CN10Y_CDB` 这类估算债券，避免估算值被转换成非估算值。
- 手工补数优先从 `data/runs/templates/manual_template.json` 复制对应 category 示例到当日 `websearch_results_manual.json`，再替换数值、日期和 `source_url`。
- 官方发布值、官方中间价、交易所/指数商实时值默认 `is_estimated=false`；只有利差估算、公式推导、代理序列、外推或明确近似值才写 `is_estimated=true`。
- Stage2.5 same-value merge 可在 incoming `current_value` 与 existing `current_value` 相同的情况下合并 `previous_value`、`change_rate`、`change_from_120d`、`value_type`、`rrr_type`、`is_estimated`、`source_url` 等 report-readiness 字段，用于关闭 Stage3 compare/window blockers；这不计入 Stage2 真实命中率。
- `reserve_ratio` quality replacement 仅限 Stage2.5 manual payload 显式 `is_estimated=false`，且提供单一显式 HTTPS PBoC URL（`pbc.gov.cn`）。可替换估算 fallback，或替换缺 `change_from_120d` 且带“缺少发布机构”诊断的非官方 structured 值；`chinamoney.com.cn` 不释放 `reserve_ratio` quality override；文本 URL 只能作为一致性证据，多个或 conflicting 文本 URL 均拒绝。
- `macro_indicators.industrial` 若使用“1-2月累计同比”等来源作为流水线当前值，必须显式写 `value_type: "yoy_month"` 和 `yoy_month`，否则会被识别为 `yoy_ytd` 并导致 `current_value` 缺失。
- `bdi` 即使在 `estimated_allowlist_keys` 内，仍受 `bdi_estimated_allow_conditions` 约束：`trusted_domains`、`max_age_days`、`value_range`、`unit_keywords` 均需通过。
- 默认允许覆盖 `is_stale=True` 的宏观/货币字段；仅补空值可加 `--no-override-stale`，应急强制覆盖可加 `--force-override`。
- Stage2.5 同值补 `previous_value/change_rate/change_from_120d` 等报告字段时，不得用非官方 manual 来源覆盖已有官方 `source_url/source/note`，也不得把已有官方非估算值降级为 `is_estimated=true`；只补缺的对比字段和可信估算标记。
- official manual override 仅适用于代码内 `official manual override allowlist` 中的指标：`monetary_policy.mlf`、`forex.USDCNY`、`commodities.BCOM`。这些指标在 `_manual.json` 显式 `is_estimated=True` 时，只有提供可信官方 HTTPS `source_url` 证据才会正规化为 `is_estimated=False`，并追加 `manual_official_not_estimated`。
- 代码内 `official manual override allowlist` 不同于 `config/policy_rules.yaml` 的 `estimated_allowlist_keys`；后者当前为 `CN10Y_CDB`、`bdi`，用于 Stage3/quality 对 `is_estimated=True` 的估计值评分/告警处理，不是 official override 白名单。
- official override 要求显式 URL 字段是单个字符串 URL；混入说明文字、多个 URL、非 HTTPS、非法端口、untrusted/spoof/conflicting URL 都不能触发 override。ETF/fund_flow 不在代码内 `official manual override allowlist`，估算仍受 gate 约束。
- 普通 manual 来源不要因为不是官方域名就默认改成 estimated 或 blocked；是否 official override 只影响显式估算值能否被正规化。
- fund_flow 的 `source_url` 只证明来源存在，不自动证明 5日/120日窗口真实可用。只有 Tier1/Tier2 结构化来源、`window_evidence` 为 `direct_window`、`direct_daily_series` 或 `direct_balance_delta`，且 `metric_basis` 不是 `news_net_flow`/`estimated_net_flow` 时，才允许 `is_estimated=false`。
- fund_flow gate 的 `source_tier` 从 `source_url` 域名推断；manual JSON 中手工填写的 `source_tier`/`claimed_source_tier` 仅可作为诊断说明，不能释放 gate。
- fund_flow Tier1 域名：`hkex.com.hk`、`sse.com.cn`、`szse.cn`；Tier2 结构化 path：`data.eastmoney.com/hsgt`、`data.eastmoney.com/etf`、`data.eastmoney.com/fund`、`data.eastmoney.com/rzrq`、`tushare.pro/document`。其他新闻、研报、季度/年度摘要和单日描述属于 Tier3，不能把外推窗口标成非估算。
- fund_flow 手工补数若使用 `news_net_flow`、`estimated_net_flow`、单日外推、季度/年度/年内摘要、外推或无法证明目标窗口，Stage2.5 会强制 `is_estimated=true` 并写入 `estimated_not_allowed` blocker；不得为了通过 gate 手工改成 `false`。
- `--allow-fund-flow-downgrade` 仅用于 Stage4 正式报告中的 fund_flow 降级：它只过滤 fund_flow 的窗口缺失和估算阻断，不会修改 `market_data_complete.json`，也不得把 ETF 新闻外推、季度/年度摘要、单日外推、`news_net_flow` 或 `estimated_net_flow` 改成 `is_estimated=false`。非 fund_flow 阻断、缺 source_url、fallback Pring、日期不匹配仍必须失败。
- 注入成功后会刷新 `data/runs/${DATE_NH}/quality_metrics.json`、写入 trend_history，并清理 `metadata.missing_items` 与顶层 `missing_items`。
- 若终端显示“注入数据项: 0”，说明结果无可解析数值或文件为空，应改用手工 schema 版 `_manual.json`。
- 若 Stage2.5/Stage3/Stage4 启动时报 `.run.lock` 被占用，先读取锁内 `owner/pid/hostname/created_at` 判断来源；live pid 表示另一个会话正在写同日产物，应停止或等待该会话，不能手动删锁后并行写。

### 5.5 Stage3 Pring 分析
```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated \
  --skip-fund-flow-check
```

### 5.6 Stage4 Report
```bash
bash run_clean.sh python scripts/stage4_risk_review.py \
  --date "$DATE" \
  --allow-fund-flow-downgrade
```
- Stage4 前建议运行 `stage4_risk_review.py` 生成 `data/runs/${DATE_NH}/stage4_risk_review.json`。该脚本只读复核，不修改数据，也不会自动阻断正式报告生成；生成前应检查 `blocker`/`review_required`，`blocker` 应处理或有意识豁免，`review_required` 用于披露和口径复核。

```bash
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md" \
  --allow-fund-flow-downgrade
```

### 5.7 收尾校验
- `data/runs/${DATE_NH}/gap_monitor.json` 无 `pending_tasks/manual_required`。
- 报告内无 `N/A（待 WebSearch）`、`无数据`。
- 关键月度字段 `is_stale=False`。
- 估计值清单可接受且有来源说明。
- `data/runs/${DATE_NH}/.run.lock` 不存在；若存在，确认其中 pid 已死亡或 stale 后再重跑写产物阶段。
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
- Stage2 Unified 默认 structured-provider-first：对 `GC=F/CL=F/BZ=F/HG=F/GSG`、`reverse_repo/mlf/USDCNY/industrial/industrial_sales`、`CN10Y_CDB`、`DXY/bdi`、`etf` 先尝试可信结构化源；同一 key 的多个 provider 会顺序兜底，结构化源全部失败、超时、解析失败或质量 gate 阻断时继续 Tavily-first 搜索；Tavily quota/rate/payment 类失败且配置 `EXA_API_KEY` 时可同轮切到 Exa，`--fund-flow-backend` 参数仍使用 `tavily`。
- 排障可传 `--disable-structured-providers` 只跑原 Tavily/Exa/DeepSeek 搜索链路。
- Stage2 真实命中率优先看 `stage2_effective_hit_rate`；该指标包含 structured-provider 成功和搜索抽取成功，不包含 `skipped_existing`，也不包含 Stage2.5 manual 注入。搜索链路命中率仍可看 `task_search_success/task_search_failed/search_success_rate_incremental`。
- Stage2 task planner 已 quality-gap aware：会从 Stage2.5/Stage3 质量状态生成 `trigger_reason=quality_gap`、`force_refresh=true` 的任务，覆盖 `missing_compare_values`、`estimated_not_allowed`、`fund_flow_window_missing`。这些任务要求 compare/window 字段，不能因已有 `current_value` 跳过。
- Stage2 extraction 会写回宏观 compare 字段和货币 `change_from_120d`，用于补齐报告可读性和关闭 Stage3 compare/window blockers。
- Real-time search params: `language=chinese`, `topic=news`, `time_range=day`, `max_results<=8`, `search_depth=advanced`；宏观/低时效指标用 `time_range=year/month`, `max_results<=6`, `search_depth=basic`。
- `search_profiles` 支持 `query_families`、`queries`、`field_queries`、`exclude_domains`、`max_query_candidates`、`extract_policy`；Stage2 记录 `query_used/query_family_used/query_attempts`。
- Stage2 query context 区分 `daily_quote` 与 `monthly_period`：日频 quote/操作公告类任务（商品、DXY、BDI、BCOM/GSG、`reverse_repo`、`mlf` 等）使用 `closing_date/ref_date` 模板，不继承宏观 `expected_period_tokens`；其中 `BCOM/GSG` 的 `closing_date` 指向报告日前最近一个已完成交易日候选，结构化 provider 会优先匹配候选日期行；labelled close 只有在页面附近有显式日期时才写 `as_of_date`，否则保留 value 但不伪造日期戳；`ref_date` 仍为报告日期；月度宏观/政策任务才使用 `expected_period/report_period` 期次 token。
- PMI 等中文宏观指标优先使用 `site:stats.gov.cn` 与国家统计局中文 query；商品期货、BCOM/GSG、DXY、BDI 等日频 quote profile 优先使用带日期/收盘/报价语义的 query，避免纯 `latest` 或概念性页面。
- Stage2 候选排序以报告可写值为目标：可信域名、关键词和 issuer 命中后，还要优先包含目标单位、日期/期次和可解析数字的片段；概念页、规格页、fact card、annual weights、forecast/analysis 等通过 `bad_url_patterns` 或 `value_evidence_miss` 降级或剔除。
- DeepSeek extraction 默认开启 queue：`--use-queue --queue-concurrency 3 --deepseek-max-concurrency 3`；默认抽取输出 token 为 `DEEPSEEK_EXTRACT_MAX_TOKENS=900`；需要串行排查时显式传 `--no-use-queue`。
- Stage2 网络默认直连：Tavily 与 DeepSeek 客户端都不读取环境代理（`trust_env=false`），`run_clean.sh` 还会清理 `http_proxy/https_proxy/ALL_PROXY`。只有显式设置 `DATASOURCE_NETWORK_MODE=proxy` 时，Stage2 才允许客户端读取环境代理；常规 VPN 切换后先重跑 `bash run_preflight.sh`。
- `BCOM/GSG/DXY/CN10Y_CDB` 等实时报价高缺口 profile 默认 `max_query_candidates=3`，并跳过 Tavily extract，直接将 Tavily search snippets 交给 DeepSeek 减负 schema 抽取，以减少 422 冷却和 Stage2.5 补数压力。
- `BCOM` Stage2 search may use Investing Bloomberg Commodity historical-data pages when the snippet proves the plain Bloomberg Commodity Index close/last price, date, numeric value and source URL. `BCOMTR`/Total Return、`BCOMX`、`GSCI/GSG`、methodology、weights、sub-index 页面仍必须拒绝。
- `mlf` 的 PBoC 多重价位公告可由 Stage2 官方结构化源写成非估算参考值：`current_value=2.00`、`is_estimated=false`，但必须通过 PBoC URL gate、公告月份匹配任务月份，且 note 必须包含“多重价位中标/无统一利率/展示参考值”等显式 marker；plain `利率招标` 不能单独释放官方参考口径。
- `CN10Y_CDB` 在 ChinaBond 直采和搜索均失败时，可使用显式 `CN10Y + observed CDB spread` 估算兜底；estimator 必须有明确 spread provenance（`task.cdb_spread_bp` 或 `metadata.cn10y_cdb_spread_bp`），无 provenance 时 fail closed；输出必须保留 `is_estimated=true`、`estimation_method`、ChinaBond 或等效 `source_url`，只能因为 `estimated_allowlist_keys` 中包含 `CN10Y_CDB` 才释放 estimated gate。
- `USDCNY` 是受控例外：可对 ChinaMoney/CFETS 官方表格页走 official extract top1；`official_domains_only` 严格按 hostname 匹配，若没有官方 snippets，会标记 `official_domain_filter_empty` 并阻断 Tavily extract、DeepSeek、regex fallback。
- 多 query 选优按后过滤质量，而不是原始 `score_max`：先做域名、时效、关键词、发布机构、期次过滤，再选 `usable_count` 更高的 query，并统计 `post_filter_query_switch_count`。
- 全部结果 `score_max < low_score_threshold`（默认 0.2）则跳过抽取，标记 `manual_required`，统计 `low_score_drop`。
- Tavily extract 422 默认回退 DeepSeek 从 snippets 抽取；同指标连续 422 可按指标冷却（`extract_cooldown_count`），不会全局停用其他指标 extract，也不会激活全局 Exa failover。仍不稳时用 `--disable-extract` 或 `--extract-topk 1`。
- Tavily search/extract 遇到 quota/rate limit/payment/plan limit 后（含 HTTP `402/403/429/432/433`），本轮立即切换搜索后端状态：有 Exa 时 `tavily_active -> exa_active` 并由 Exa 接管当前与后续任务；无 Exa 或 Exa 失败时写 `manual_required` skeleton。不新增 quota probe，不重跑当日 Tavily。排查看 summary 的 `tavily_unavailable_reason=quota_or_rate_limit`、`tavily_limit_error_count`、`tavily_error_samples`、`retrieval_diagnostics`、`manual_reason_breakdown`。
- 环境/proxy/SOCKS/DNS/TLS 等运行环境错误不触发 Exa failover；先修复 preflight、代理或证书问题。非 quota 类 Exa fallback 仍为显式 opt-in，只在传 `--enable-exa-fallback` 或设置 `STAGE2_ENABLE_EXA_FALLBACK=1` 时启用。
- 资金流缺 `recent_5d/total_120d` 时，优先按 `field_queries` 仅补缺字段，并统计 `field_retry_count/field_retry_merged_count/field_retry_missing_fields`。
- ETF structured provider 顺序为 TuShare `etf_share_size` before EastMoney/search。TuShare 成功条件是存在一个 latest complete 的 121 交易日窗口，且窗口内 SSE+SZSE 两个 exchange 的 `total_size` 都完整可解析，每个交易所当日可用行数还必须通过候选窗口内的自适应完整性下限，防止 API partial/truncated response 只返回少量 ETF 时误判完整；若报告日窗口不完整，可回退到最近完整窗口并记录窗口日期，输出 `metric_basis=etf_total_size_delta`、`window_evidence=direct_balance_delta`、`source_tier=tier2`、`is_estimated=false`。找不到完整窗口、窗口内部缺口或部分返回时 fail closed。EastMoney 仍只有已验证全市场 `direct_daily_series` 时才可释放 gate。
- Stage2 forex 写回会清洗无证据的 `daily_change/change_120d=0.0`；保留真实 0 需要 `direct_daily_series/direct_window/trend_history`、合法 base date/base price/source_url、或明确 `no change/无变化` 证据。清洗后会写 `compare_fields_pending` 并在 post-writeback 转 `manual_required=missing_compare_values`。
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
| fund_flow | `recent_5d`, `total_120d`, `trend`, `source` | `{"recent_5d": 85.6, "total_120d": 1250.0, "trend": "流入", "source": "tavily+deepseek 或 exa+deepseek", "source_url": "https://..."}` |

## 8. Fund Flow Data Standard
- 北向、南向、ETF、融资融券：禁止 AKShare 直接写最终值；仅允许 TuShare 可得字段、WebSearch 实时来源或 Stage2.5 手工补数。
- 异常检测：任一 `0/None` 或窗口值缺失，都标记 `manual_required` 并进入 Stage2.5。
- 来源标注：`tavily+deepseek`、`exa+deepseek`、`待人工补数(Stage2 manual_required)`、`异常零值-需核查`。
- Exa quota failover 覆盖 fund_flow，但 fund_flow gate 不变：`source_tier`、`window_evidence`、`metric_basis`、`is_estimated`、`estimated_not_allowed` 仍按原规则判定。
- `metric_basis=net_flow_sum` 仅用于目标窗口内日频净流入求和；`balance_delta` 用于余额类窗口差值；`news_net_flow` 和 `estimated_net_flow` 均不能作为真实窗口值通过 gate。
- ETF 全市场资金流可由 TuShare `etf_share_size` latest complete 窗口释放 gate：121 个交易日、SSE+SZSE 两个 exchange 的 `total_size` 都完整可解析，且每个交易所当日可用行数通过候选窗口内的自适应完整性下限时，按 `metric_basis=etf_total_size_delta`、`window_evidence=direct_balance_delta`、`source_tier=tier2`、`is_estimated=false` 写入。该口径是 ETF 规模 delta，不等同于新闻净流入；partial/truncated response、窗口内部缺口、新闻、季度报告和 EastMoney 未验证全市场窗口时仍默认 `is_estimated=true`，不能释放非估算 gate。
- `fund_flow.etf` 搜索 fallback 必须过滤 `data.eastmoney.com/stockdata/*`、个股页、单只 ETF 页和新闻页；这些页面应记录 `search_result_scope_mismatch`，不得释放 `fund_flow_window_missing`。
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
      "source": "tavily+deepseek 或 exa+deepseek",
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
- Stage2 structured/search second: TuShare 不可得或缺失字段统一走 Stage2；已知官方或结构化指标先尝试 structured-provider，失败后再走 Tavily-first 搜索与 Exa quota failover。
- Stage2.5 last resort: 用 `data/runs/${DATE_NH}/websearch_results_manual.json` 或手工 `_manual.json` 注入。
- Market fallback: legacy-only path 已归档至 `archive/py_unused/legacy/fill_market_data_from_yahoo.py`，仅作历史应急参考，不在当前流程执行；当前缺口仍通过 Stage2.5 注入补 commodities/bonds/forex 缺口。
- `fund_flow.etf`: Stage1/Stage2 均可用 TuShare `etf_share_size.total_size` 计算全市场规模窗口变化，`metric_basis=etf_total_size_delta`、`window_evidence=direct_balance_delta`；latest complete 121 交易日窗口中 SSE+SZSE 两个 exchange 的 `total_size` 都完整可解析，且每个交易所当日可用行数通过候选窗口内的自适应完整性下限时，才可作为非估算 Tier2 结构化窗口值。该口径是 ETF 规模 delta，不等同于新闻口径净流入。若 TuShare 不可得、窗口不完整、partial/truncated response、窗口内部缺口或质量阻断，继续 Stage2 搜索或 Stage2.5 补数，并保持 estimated 或 fail closed。
- `reverse_repo` 的 PBoC 结构化公告必须匹配任务 `ref_date`；`mlf` 至少匹配 `ref_date` 所在月份。公告正文和 URL 都解析不出操作日期，或期次不匹配时，不得回退为官方非估算值。
- `DXY`: Stage1 可探测 TuShare `fx_obasic` 的 `FX_BASKET`/`USDOLLAR.FXCM` 并用 `fx_daily` 取数；报告必须标注为 TuShare `USDOLLAR` proxy，不得写成 ICE DXY。若不可得或不完整，继续 Stage2/Stage2.5。
- `USDCNH`: `fx_daily` 优先使用 `ts_code=USDCNH.FXCM`；`USDCNH` 常返回空。
- `CN10Y`: 优先 `yc_cb(ts_code=1001.CB, curve_type=0, curve_term=10)`；若空则回退 `curve_type=1`。
- `CN10Y_CDB`: 当前无稳定 TuShare 直采口径，仍需 WebSearch/手工注入；若为利差估算需保留 `is_estimated=True`。
- `CN10Y_CDB` 若使用 `CN10Y plus observed CDB spread` 估算当前值，Stage2.5 可沿用同日 `CN10Y` 的 `change_5d_bp/change_120d_bp` 作为估算变化口径，并保留 `is_estimated=True` 与 `cn10y_proxy_change_basis` 说明。
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

Stage2 summary 口径：`task_completed/task_total` 仅表示 legacy completion；日常判断 Stage2 是否达标优先看 `stage2_effective_hit_rate`，并用 `stage2_effective_success/stage2_effective_failure/stage2_effective_denominator` 审计分子分母。`stage2_effective_hit_rate` 包含 structured-provider 成功 + 搜索抽取成功，不含 `skipped_existing` 与 Stage2.5 manual 注入。质量缺口任务（`trigger_reason=quality_gap`）只有写回 `required_output_fields` 后才算 Stage2 成功；structured-provider 只写当前值但缺 `previous_value/change_rate/change_from_120d` 时，应继续 fallback 到搜索/抽取或转 `manual_required`，不得虚增命中率。搜索链路命中率只看 `task_search_success/task_search_failed/search_success_rate_incremental`；`search_success_rate_incremental=0.0` 只表示 Tavily/Exa 搜索链路未写回，不代表 Stage2 总命中率为 0，需同时看 `task_structured_success`、`structured_provider_success_count`。结构化源排障看 `structured_provider_attempt_count/structured_provider_success_count/structured_provider_fallback_to_search_count/structured_provider_error_breakdown`、`retrieval_diagnostics`、`manual_reason_breakdown`；已有值跳过看 `task_skipped_existing`，quota/rate/payment failover 看 `search_backend_final`、`tavily_to_exa_failover`、`tavily_to_exa_failover_count`、`exa_failover_success`、`exa_failover_empty`、`exa_failover_error`、`exa_unavailable`、`exa_error_breakdown`、`exa_error_samples`，同时保留查看 `tavily_unavailable_reason=quota_or_rate_limit`。若 `retrieval_hit` 高但写回低，优先看 `value_evidence_miss`、`deepseek_json_truncated/deepseek_json_parse_error`、`field_retry_merged_count`、`field_retry_missing_fields`。

## 12. Troubleshooting
| 问题 | 原因 | 解决方案 |
|------|------|----------|
| Preflight DNS 失败 | DNS/WSL/容器网络不可达 | 修复 `/etc/resolv.conf` 或宿主网络后重跑 `bash run_preflight.sh`；不要启动 Stage2 |
| `.venv` 目录存在但不可用 | 空目录或 Windows/Linux venv 混用 | 空 `.venv` 视同无 venv，可显式 `ALLOW_SYSTEM_PYTHON=1` fallback；非空但无可用 activate/python 时删除并重建 `.venv` |
| Stage2 DeepSeek 持续超时 | API 响应慢、并发过高或输出预算不合适 | 默认使用 `--deepseek-timeout 30 --llm-hard-timeout 35` 与 `DEEPSEEK_EXTRACT_MAX_TOKENS=900`；仍持续超时时改用 `--extraction-backend regex --disable-extract`，或串行关键指标 |
| DeepSeek 返回 JSON 失败 | 输出截断或格式错误 | 看 `manual_reason`：`deepseek_json_truncated` 先适度调高 `DEEPSEEK_EXTRACT_MAX_TOKENS` 或转 Stage2.5；`deepseek_json_parse_error` 优先查 prompt/schema 与 source snippets |
| Tavily extract 422 | API 参数/限制 | 默认回退 DeepSeek；不会激活全局 Exa failover，仍不稳用 `--disable-extract` 或 `--extract-topk 1` |
| USDCNY 官方表格未抽取 | official-only snippets 为空或 hostname 不匹配 | 看 `official_domain_filter_empty`；不要放宽到非官方 fallback，转 Stage2.5 补可信官方来源 |
| Tavily quota/rate/payment/plan limit | Tavily 额度、频率、计费或计划限制，常见 HTTP `402/403/429/432/433` | 有 Exa 时同轮切换到 `exa_active` 接管当前与后续任务；无 Exa 或 Exa 失败时写 `manual_required` skeleton。不要新增 quota probe 或重跑当日 Tavily，查看 `tavily_unavailable_reason=quota_or_rate_limit`、`tavily_limit_error_count`、`tavily_error_samples`、`retrieval_diagnostics`、`manual_reason_breakdown` 后决定是否转 Stage2.5 补数 |
| Stage2.5/Stage3/Stage4 提示 `.run.lock` 被占用 | 同日另一会话正在写产物，或前次异常退出留下锁 | 查看 `data/runs/${DATE_NH}/.run.lock` 的 `owner/pid/hostname/created_at`；live pid 先确认并停止/等待原会话，不手动删除。只有 stale/dead pid 或 stale corrupt lock 可由锁机制自动回收 |
| Stage2 出现 SOCKS/代理/DNS/TLS 错误 | 未通过 `run_clean.sh` 启动、显式 proxy mode、宿主 VPN 改写代理环境、DNS 或证书异常 | 这类环境错误不触发 Exa failover。默认用 `bash run_clean.sh ...` 直连运行；确认未设置 `DATASOURCE_NETWORK_MODE=proxy`，再重跑 `bash run_preflight.sh`。需要代理时只用显式 proxy mode，并确认环境代理可连通 |
| 当日 Stage2 已失败 | Tavily 不应重复消耗 | 转 Stage2.5 manual JSON 补数并注入 |
| 搜索相关性低 | `score_max < low_score_threshold` | 调整 `search_profiles.queries/exclude_domains`，必要时转人工补数 |
| 搜索命中但不可写报告 | 命中概念页/规格页/预测页，或缺目标日期/单位/数值证据 | 查 `value_evidence_miss` 与 `bad_url_patterns`，补 dated quote query 或转 Stage2.5 |
| 宏观/货币显示旧月份 | TuShare 月度表滞后，`is_stale=true` | 跑 `check_monthly_freshness.py data/runs/${DATE_NH}/market_data.json`，再 Stage2/Stage2.5 覆盖 stale 字段 |
| Stage3 完整度 <80% | 关键字段为 null | 检查 macro/monetary/stock_indices，补数后重注入 |
| Stage3 `block_stage3=True` 但数据已注入 | policy gate 仍有 redlist 或顶层缺口 | 检查 `missing_items`、`policy_evaluation.json`、`gap_monitor.json`，补齐后重跑 Stage2.5/Stage3 |
| Stage3 `compare_gaps` 阻断 | 缺 `previous_value` | 补齐对应 `previous_value`；`--allow-estimated` 不绕过 |
| forex `change_120d/daily_change` 为 0 | 可能是结构化源只写当前汇率留下的占位 | 看 Stage2 `manual_reason=missing_compare_values` 与 `compare_fields_pending`；只有直接窗口/基准价/明确无变化证据才保留 0，否则用 Stage2.5 manual 或 trend_history backfill 补齐 |
| `industrial current_value is missing` | manual JSON 中“累计”文本触发 `yoy_ytd`，但未显式 `yoy_month` | 按模板补 `value_type: "yoy_month"`、`yoy_month`、`current_value` 后重跑 Stage2.5 |
| 注入时报 `KeyError: 'symbol'` | WebSearch JSON 缺必填字段 | 按 WebSearch JSON Schema 补全 |
| 报告出现 N/A | 数据未注入或格式错误 | 查 `gap_monitor.json`，确认数字字段为可解析值 |
| 报告债券日期列为 N/A | 缺 `date/as_of_date/report_period` 或旧口径 | 重跑 Stage1->Stage4，确认 `bonds[].date/as_of_date` 已写入 |
| 代理/TLS 问题 | 环境代理污染或证书异常 | 优先 `run_clean.sh`；开发环境才可用 `TAVILY_VERIFY=false`，生产需有效 CA 或 `TAVILY_CA_BUNDLE` |
| SyntaxError 启动失败 | 代码语法错误 | `python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py` |


## 13. 重构执行协议(2026-06,批次 0/A 起生效;canonical 详版见 optimization/20260610_refactor_plan/REFACTOR_PLAN.md §11)

**Worktree 置备(执行任何重构 plan 的第一步):**
- 本仓库 `.gitignore` 忽略 `.env`、`.venv/`、`data/`、`logs/`、`reports/` —— **新建 worktree 中这些全部不存在**,必须置备:`cp .env` + `mkdir logs reports .venv` + `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V`(空 `.venv` 触发 `scripts/bootstrap_venv.sh`,`DATASOURCE_INSTALL_DEV=1` 带上 pytest)+ 按 plan 声明复制 data 夹具(绝对路径只允许指向主 checkout 只读源)。
- 置备后必跑 baseline `pytest -q`,失败即停-回报,不开工。

**执行纪律(反扩散,批次 A 复盘落地):**
- plan 中任何 "Expected 空输出" 的命令出现输出 → **停止并回报**,不要即兴处理。
- 文档修复只允许出现在 plan 对应任务的原子 commit 内;不得自行新增计划外 commit。
- 行为冻结区(official manual override allowlist、fund_flow 估算 gate、forex 零值防占位、Stage3 三路 gate)diff 只允许 import/路径变化。
- 完成后留在 `codex/<topic>` 分支,**不自行 merge、不删 worktree**;回报须含逐项偏差清单(数量与内容如实,评审方会独立验证)。
- 合入默认 **squash**(消除中间态断链 commit);合入与 worktree/分支清理是评审方动作。

**归档区规则:**
- `archive/py_unused/` 只进不出:**严禁 import 其中任何模块**;新归档按来源保留子目录(`root/`、`legacy/`、`datasource/<原相对路径>`、`tests/`、`examples/`)。
- 批次 0 审计口径:`unreachable` 仅证明"流水线入口静态不可达",**不等于可删**;删除/归档前必须对路径和 dotted module 跑 `rg` 复核 `tests/ examples/ scripts/ docs/ optimization/`。审计产物:`optimization/20260610_refactor_plan/audit/used_unused.json`。
- MCP 链路(`src/datasource/mcp_adapter.py`、`src/datasource/utils/mcp_tools.py`)经审计 unreachable 但**刻意保留**:`tests/test_fund_flow_pipeline.py` 混合测试依赖,归档延期,不要顺手删。

**质量基建现状:**
- `pytest.ini`:默认只收集 `tests/`(`testpaths`),`archive/`、`.worktrees/` 等不被收集;`optimization/20260610_refactor_plan/audit/` 的工具测试需显式路径运行。
- **文档契约测试**:runbook(README/SCRIPTS/两份手册/checklist)中的命令示例被 `tests/test_manual_template.py`、`tests/test_stage4_docs.py` 断言 —— 修改任何文档中的命令示例后必跑这两个测试。
- `.pre-commit-config.yaml` 存在(仅 compileall,经 `run_clean.sh` 包装,opt-in 不强制);flake8 钩子刻意延期 —— `src/` 现存约 3500 处存量违规,待专门 lint 清理批后再挂。
- `run_clean.sh` 每次调用自动清理 `logs/` 下 30 天以上旧文件。

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
