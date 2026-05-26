# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 沟通约定：与用户的交互和问题说明优先使用中文，命令保持原文。

## Project Overview

统一金融数据集成框架，支持 TuShare、AKShare、InternationalFinance 数据源自动故障转移。集成 Stage2 structured-provider-first + Tavily-first/DeepSeek 网络搜索增强（配置 `EXA_API_KEY` 时支持 Tavily quota/rate/payment failover；非 quota fallback 仍需显式 opt-in）、Pring 六阶段经济周期分析 (V4.0 三层框架)，以及 120 日背景扫描报告自动生成。

**核心数据流**: Stage1 (API采集) → Stage2 (structured-provider-first + Tavily-first 搜索；必要时 Exa quota failover) → Stage2.5 (手工注入补缺) → Stage3 (Pring分析) → Stage4 (报告生成)

> 执行参数与口径以 `AGENTS.md` 为准；本文件保留最小操作指引与高频约束。

## Critical Constraints

- **Tavily 每日限制**: Stage2 默认先尝试 structured-provider；进入 Tavily 后，Tavily search/extract **每日只能运行一次**。遇到 422 会自动回退 DeepSeek 从原始 snippets 抽取；遇到 402/403/429/quota/rate-limit/payment 且有 `EXA_API_KEY` 时同轮切到 `exa_active`，否则转 `manual_required` skeleton。不要重跑 Tavily
- **数据来源约束**: 严禁从历史 `reports/*.md` 中抓取或复用数据；所有数据必须来自 API 实时获取或 stage 计算产出
- **完整度要求**: Stage3 需要 `data_completeness ≥ 80%`，否则报告会有缺失
- **手工补数验证**: 所有手工填写的数值必须通过 WebSearch 验证后再填入，禁止凭记忆填写汇率、指数等高精度数值
- **Exa failover 边界**: Stage2 是 structured-provider-first + Tavily-first；`EXA_API_KEY` 用于 Tavily quota/rate/payment failover。结构化源失败、超时、解析失败或质量 gate 阻断时继续搜索链路；环境/proxy/SOCKS/DNS/TLS 错误和普通 Tavily extract 422 不切 Exa；非 quota fallback 仍需 `--enable-exa-fallback` 或 `STAGE2_ENABLE_EXA_FALLBACK=1`
- **无值强制人工**: `no_value/deepseek_no_value/no_deepseek_key` 必须进入 `manual_required`，在 Stage2.5 产出待补全骨架
- **采集优先级固定**: `TuShare(Stage1) -> Stage2(structured-provider-first + Tavily-first，必要时 Exa quota failover) -> Stage2.5`；排障可用 `--disable-structured-providers` 回到搜索-only 诊断路径，当前流程不使用旧版外部补数链路
- **生产报告禁用边界**: 正式 Stage3/Stage4 禁止 `--allow-fallback`、`--skip-gap-check`、`--allow-fallback-report`，也禁止直接调用 `generate_report()` 生成正式报告。Stage4 默认拒绝 `pring_result.fallback_used=true`；debug flag 只限本地排障
- **fund_flow skip 语义**: 仅剩 ETF/fund_flow 窗口或估算 blocker 时，Stage3 和 Stage4 可同时使用 `--skip-fund-flow-check`；它只过滤 fund_flow 窗口/估算 blocker，不绕过其他 gate 或 audit errors
- **重跑顺序**: 修改 `config/policy_rules.yaml` 或当日 `_manual.json` 后，必须按 Stage2.5 -> Stage3 -> Stage4 重跑，不能只重跑报告
- **source_url 证据**: manual `source_url` 必须直接支持填入的数值、日期/期次和口径；不得用官网首页、品牌入口、占位 URL，或与 `source` 声称平台不一致的 URL

## Quick Start

```bash
# 环境设置
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e . && pip install -e ".[dev]"
cp .env.example .env  # 编辑填入 TUSHARE_TOKEN, TAVILY_API_KEY, DEEPSEEK_API_KEY；默认 DEEPSEEK_MODEL=deepseek-v4-pro、DEEPSEEK_EXTRACT_MAX_TOKENS=900，可覆盖

# 验证安装
python -c "from datasource import get_manager; print('OK')"
datasource-test  # CLI 入口（等价于 python -m datasource.cli test_command）

# 预检（每次运行流水线前必跑；验证三个 API key ≥20字符 + 清代理）
bash run_preflight.sh
```

- `run_preflight.sh` 与 `run_clean.sh` 共享 `scripts/runtime_env.sh`；`.env` 是密钥/配置，`.venv` 是依赖环境，不合并。Ubuntu/WSL Claude Code 启动时若 `.venv` 为空目录，优先设置 `DATASOURCE_AUTO_VENV=1` 让 runtime 调用 `scripts/bootstrap_venv.sh` 自动 bootstrap；不要长期依赖 `ALLOW_SYSTEM_PYTHON=1`。非空坏 venv 或 Windows venv 在 Linux 下仍需删除重建。
- VPN/代理变更后先跑 `bash run_preflight.sh`。默认 `DATASOURCE_NETWORK_MODE=direct` 会清理 `http_proxy/https_proxy/HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/all_proxy` 等主动代理变量并保留 `NO_PROXY/no_proxy`；只有明确需要代理时才设置 `DATASOURCE_NETWORK_MODE=proxy`，SOCKS 代理必须确保 `httpx[socks]`/`socksio` 已安装。
- Preflight 默认 HTTPS 超时为 `PREFLIGHT_CONNECT_TIMEOUT=10`、`PREFLIGHT_MAX_TIME=15`，网络慢时可用环境变量覆盖。
- DNS/HTTPS preflight 失败是运行环境 hard fail，不启动 Stage2，不重跑 Tavily。

### 推荐运行方式

**所有脚本统一通过 `run_clean.sh` 执行**（优先 `.venv/bin/activate`，Windows/Git-Bash 再尝试 `.venv/Scripts/activate`；空 `.venv` 可用 `DATASOURCE_AUTO_VENV=1` 自动 bootstrap；没有 venv 时必须显式 `ALLOW_SYSTEM_PYTHON=1` 才使用系统 Python。仍会 source .env、清理主动代理、PYTHONPATH=./src）：
```bash
bash run_clean.sh python scripts/stage1_data_collector.py --date "$DATE"
bash run_clean.sh python scripts/stage2_unified_enhancer.py --help
bash run_clean.sh python scripts/stage3_pring_analyzer.py --help
```

不要绕过 `run_clean.sh` 直接执行流水线脚本；该包装器负责加载环境、设置 `PYTHONPATH` 并清理代理。

## Testing

```bash
pytest -q                                # 快速测试（conftest.py 自动添加 ROOT/src 到 sys.path）
pytest tests/test_file.py::test_name -v  # 单测
pytest tests/integration/                # 集成测试（enhanced_pring, 120d, background_scan）
python tests/test_datasource.py          # 数据源连通性集成测试
black src/ tests/ scripts/ && flake8 src/ && mypy src/datasource/  # 代码质量
```

**测试文件结构**: 单元测试 `tests/test_*.py`（stage1/2/3、trend_history、policy_rules、fund_flow 等），集成测试 `tests/integration/`，测试夹具 `tests/test_data_sources/`，Stage4 报告生成脚本 `tests/scripts/`。

**重构落地后的关键回归测试**（修改 utils/calculators/pring/missing_items 时必跑）：
- `tests/test_utils_coercion.py` / `tests/test_utils_json_io.py` — 数值/JSON 工具契约
- `tests/test_pring_scoring_golden.py` — Pring 评分 golden 回放（夹具：`tests/fixtures/pring_golden/`）
- `tests/test_monetary_key_registry.py` — 货币政策 key 别名注册表
- `tests/test_missing_items_compat.py` — canonical metadata vs 顶层 list 兼容
- `tests/test_stage25_contract_replay.py` — Stage2.5 注入回放（启用 trend-history 隔离）
- `tests/test_run_paths_consistency.py` — `data/runs/${DATE_NH}` 路径契约

## Daily Report Pipeline

```bash
DATE=$(date +%Y-%m-%d)
DATE_NH=${DATE//-/}
bash run_preflight.sh

# Stage 1: API 数据采集
bash run_clean.sh python scripts/stage1_data_collector.py \
  --date "$DATE" \
  --output data/runs/${DATE_NH}/market_data.json

# Stage 1 后必跑：月度新鲜度检查（防止 TuShare 月度表滞后被误判为"完整"）
bash run_clean.sh python scripts/check_monthly_freshness.py data/runs/${DATE_NH}/market_data.json
# 若输出 STALE/MISSING（典型：cpi/ppi/pmi/m1/m2/tsf），必须经 Stage2/Stage2.5 补齐后才能进入 Stage3

# Stage 2: structured-provider-first + Tavily/DeepSeek 增强（当日 Tavily 只跑1次！）
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data data/runs/${DATE_NH}/market_data.json \
  --output data/runs/${DATE_NH}/market_data_stage2.json \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend deepseek \
  --deepseek-timeout 30 \
  --llm-hard-timeout 35 \
  --deepseek-max-concurrency 3 \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results data/runs/${DATE_NH}/websearch_results_auto.json \
  --log-output logs/runs/${DATE_NH}/stage2_unified_log.json \
  --gap-monitor data/runs/${DATE_NH}/gap_monitor.json

# Stage 2.5: WebSearch 注入补缺（脚本位于项目根目录）
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"

# Audit: manual source_url 证据审计，errors 非空时正式 Stage4 阻断
bash run_clean.sh python scripts/audit_manual_evidence.py \
  --manual-data "data/runs/${DATE_NH}/websearch_results_manual.json" \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --stage2-log "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --output "data/runs/${DATE_NH}/manual_evidence_audit.json"

# Stage 3: Pring 分析（--allow-estimated 让 is_estimated=True 的数据参与评分）
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated

# Audit: Stage3/Stage4 gate 一致性审计，errors 非空时正式 Stage4 阻断
bash run_clean.sh python scripts/audit_pipeline_consistency.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json" \
  --output "data/runs/${DATE_NH}/pipeline_audit.json"

# Stage 4: 报告生成（正式入口）
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md"
# 兼容入口：tests/scripts/generate_simple_report_test.py（保留历史调用）

# 验证：确保无缺口
cat data/runs/${DATE_NH}/gap_monitor.json  # 应为空对象或无 pending/manual_required
```

仅剩 ETF/fund_flow 窗口或估算 blocker 且业务确认可降级展示时，Stage3 和 Stage4 才可同时追加 `--skip-fund-flow-check`；正式报告不要默认加 skip。生产禁止 `--allow-fallback`、`--skip-gap-check`、`--allow-fallback-report`，也不要绕过 Stage4 直接调用 `generate_report()`。

### Stage2 运行模式

| 模式 | 关键参数 |
|------|----------|
| **Default (首次推荐)** | `--extraction-backend deepseek --deepseek-timeout 30 --llm-hard-timeout 35 --deepseek-max-concurrency 3 --queue-concurrency 3` |
| **Fast (仅补缺)** | `--extraction-backend regex --disable-extract` |
| **重试指定缺口** | `--tasks USDCNY,northbound,etf` |
| **资金流后端** | 固定 `--fund-flow-backend tavily`（当前唯一支持） |
| **结构化源排障** | 默认 structured-provider-first；`--disable-structured-providers` 只跑原搜索链路 |
| **Exa failover** | Stage2 搜索链路仍 Tavily-first；有 `EXA_API_KEY` 时 Tavily quota/rate/payment 自动同轮切 Exa，非 quota fallback 才需要 `--enable-exa-fallback` 或 `STAGE2_ENABLE_EXA_FALLBACK=1` |

> 详细参数说明见 AGENTS.md "## 6. Stage2 搜索/抽取规则"

### Stage2/Stage2.5 搜索优化要点

- DeepSeek 抽取采用减负 schema + 证据约束，默认只要求报告写回所需字段；`source_url` 必须来自 snippets。
- Stage2 默认 structured-provider-first：`GC=F/CL=F/BZ=F/HG=F/GSG`、`reverse_repo/mlf/USDCNY/industrial/industrial_sales`、`CN10Y_CDB`、`DXY/bdi`、`etf` 先尝试可信结构化源；同一 key 支持 provider 级顺序兜底，全部失败、超时、解析失败或质量 gate 阻断后才继续 Tavily-first 搜索。当前来源包括 Trading Economics 商品/政策页、Stooq `GSG` CSV、ChinaMoney `USDCNY` JSON、国家统计局详情页；ETF 顺序为 TuShare `etf_share_size` before EastMoney/search，TuShare 仅在 121 个交易日、SSE+SZSE 两个 exchange 的 `total_size` 都完整可解析时释放 gate（`metric_basis=etf_total_size_delta`、`window_evidence=direct_balance_delta`、`source_tier=tier2`、`is_estimated=false`），EastMoney 仍需 full-market direct daily series 验证。
- DeepSeek 默认模型为 `deepseek-v4-pro`，可用 `DEEPSEEK_MODEL` 或命令行参数覆盖；Stage2 抽取输出 token 默认 `DEEPSEEK_EXTRACT_MAX_TOKENS=900`。
- DeepSeek extraction 默认开启 queue，默认 `--queue-concurrency 3 --deepseek-max-concurrency 3`；串行排查时显式传 `--no-use-queue`。
- Stage2 默认直连：Tavily/DeepSeek 都不读取环境代理；只有 `DATASOURCE_NETWORK_MODE=proxy` 时才允许 proxy env。VPN 切换后先跑 `bash run_preflight.sh`。
- Stage2 quote/操作公告搜索看 `time_context_type`：`daily_quote` 不带宏观月度 token，并为官方来源校验提供 `ref_date`；`reverse_repo/mlf` 与商品、DXY、BDI、BCOM/GSG 同属该类。PBoC `reverse_repo` 公告必须匹配 `ref_date`，`mlf` 至少匹配 `ref_date` 所在月份；公告正文和 URL 都解析不出操作日期时，不得回退为官方非估算值。`monthly_period` 才带 `expected_period_tokens`。若 `retrieval_hit` 高但写回低，优先看 `value_evidence_miss`、`deepseek_json_truncated`、`field_retry_merged_count`。
- `search_profiles` 支持 `max_query_candidates` 与 `extract_policy`；`BCOM/GSG/DXY/CN10Y_CDB` 默认限制 3 个 query candidates，并跳过 Tavily extract 直接用 snippets 抽取，降低 422 和 Stage2.5 手工补数压力。
- `USDCNY` 是 quote profile 的受控例外：ChinaMoney/CFETS 官方表格页可走 official extract top1；`official_domains_only` 严格按 hostname 匹配，若没有官方 snippets，会标记 `official_domain_filter_empty` 并阻断 Tavily extract、DeepSeek、regex fallback。
- dated quote profiles 会用 `bad_url_patterns` 和 `value_evidence_miss` 降权/剔除概念页、规格页、annual weights、forecast 等不可写报告页面。
- `source_url` 必须能在 snippets 中找到证据；manual URL 必须直接支持填入值、日期/期次和口径，不能用官网首页、品牌入口、占位 URL 或与 `source` 声称平台不一致的 URL。若不满足或 `value` 缺失，强制 `manual_required=true`。
- Tavily quota/rate/payment 后，若有 `EXA_API_KEY` 会从 `tavily_active` 切到 `exa_active`，重试当前失败任务并让剩余任务走 Exa；没有 Exa 或 Exa 不可用才转 `manual_required` skeleton。不要新增 quota probe 或重跑 Tavily。
- Stage2 summary 中 `task_completed/task_total` 只是 legacy completion；日常判断 Stage2 是否达标优先看 `stage2_effective_hit_rate`，并用 `stage2_effective_success/stage2_effective_failure/stage2_effective_denominator` 审计分子分母。该指标包含 structured-provider 成功 + 搜索抽取成功，不含 `skipped_existing` 与 Stage2.5 manual 注入。质量缺口任务只有写回 `required_output_fields` 后才算成功；structured-provider 只写当前值但缺 `previous_value/change_rate/change_from_120d` 时要继续 fallback 或转 `manual_required`。搜索链路命中率只看 `task_search_success/task_search_failed/search_success_rate_incremental`；`search_success_rate_incremental=0.0` 只表示 Tavily/Exa 搜索链路未写回，不代表 Stage2 总命中率为 0。结构化源看 `task_structured_success`、`structured_provider_attempt_count/structured_provider_success_count/structured_provider_fallback_to_search_count/structured_provider_error_breakdown`。Exa failover 看 `search_backend_final`、`tavily_to_exa_failover_count`、`exa_failover_success/empty/error`、`exa_unavailable`、`exa_error_breakdown`、`exa_error_samples`；其他失败分类结合 `retrieval_diagnostics`、`manual_reason_breakdown`、`field_retry_merged_count/field_retry_missing_fields`。
- Stage2 task planner 会从 Stage2.5/Stage3 质量状态生成 `trigger_reason=quality_gap`、`force_refresh=true` 任务，覆盖 `missing_compare_values`、`estimated_not_allowed`、`fund_flow_window_missing`；这些任务要求 compare/window 字段，不能因已有 current value 跳过。Stage2 extraction 会写回宏观 compare 字段和货币 `change_from_120d`。
- 命中 `low_score_all/单位不匹配/缺少发布机构/no_value` 时会自动触发一次定向 query 重试（补充单位、机构以及任务已有的日期/期次上下文；`daily_quote` 不强行追加宏观月份）。
- Stage2.5 在接收 Stage2 `results` 结构时，会保留 `manual_required/manual_reason` 并生成 `metadata.manual_required` 待补全骨架（含候选 `source_url/query/query_used`，按 `category:indicator_key` 去重）；自动结果转换必须保留 `is_estimated/estimation_method/metric_basis/confidence`，尤其是 `CN10Y_CDB` 这类估算债券。
- Stage2.5 same-value merge 可在 incoming current 与 existing current 相同的情况下合并 `previous_value/change_rate/change_from_120d/value_type/rrr_type/is_estimated/source_url` 等 report-readiness 字段，用于关闭 Stage3 compare/window blockers；但不得用非官方 manual 来源覆盖已有官方 `source_url/source/note`，也不得把已有官方非估算值降级为 `is_estimated=true`。
- official override 仅用于代码内 `official manual override allowlist`：`monetary_policy.mlf`、`forex.USDCNY`、`commodities.BCOM`。只有可信官方 HTTPS URL evidence 才会把显式 `is_estimated=True` 正规化为 `False`，并追加 `manual_official_not_estimated`。
- `reserve_ratio` quality replacement 仅限 Stage2.5 manual payload 显式 `is_estimated=false` 且有单一显式 HTTPS PBoC URL（`pbc.gov.cn`）；可替换估算 fallback，或替换缺 `change_from_120d` 且带“缺少发布机构”诊断的非官方 structured 值；`chinamoney.com.cn` 不释放该 quality override，文本 URL 只能作为一致性证据，多个/conflicting 文本 URL 拒绝。
- `CN10Y_CDB` 使用 `CN10Y plus observed CDB spread` 估算时，Stage2.5 可沿用 `CN10Y` 的 5d/120d bp 变化作为估算变化口径；必须保留 `is_estimated=true` 和 `cn10y_proxy_change_basis`。
- 代码内 `official manual override allowlist` 不同于 `config/policy_rules.yaml` 的 `estimated_allowlist_keys`；后者当前为 `CN10Y_CDB`、`bdi`，用于 Stage3/quality 对 `is_estimated=True` 的估计值评分/告警处理，不是 BCOM/USDCNY/MLF 的 estimated allowlist。
- official override 要求显式 URL 字段是单个字符串 URL；混入说明文字、多个 URL、非 HTTPS、非法端口、untrusted/spoof/conflicting URL 均不触发。ETF/fund_flow 不在代码内 `official manual override allowlist`；普通 manual 来源不会因为不是官方域名而默认改成 estimated/blocked。
- Stage2.5 中 `macro_indicators.change_rate` 统一为百分比口径（`(current-previous)/abs(previous)*100`），分母为 0 时保留缺口并标记质量阻断。
- Stage2.5 manual 从 `data/runs/templates/manual_template.json` 复制起步；官方值默认 `is_estimated=false`。
- `industrial` 使用“1-2月累计同比”时必须显式 `value_type: yoy_month` 和 `yoy_month`。
- `bdi` 的 estimated allowlist 还有二级约束：`trusted_domains/max_age_days/value_range/unit_keywords`。

### Operational Pitfalls（操作陷阱）

**missing_items 双层结构**（2026-04-27 重构后 canonical 已统一）:
- `metadata.missing_items` (dict，按 category 分组) — **canonical 来源**，inject 脚本读取、生成待补全骨架
- 顶层 `missing_items` list — 兼容视图，Stage3 policy gate `redlist` 仍从此读取（`critical_missing_keys: [dxy, bdi, rrr, mlf]`）
- 两者由 `src/datasource/utils/missing_items.py` + `pipeline_quality_state.py` 统一同步；不要手写顶层 list，也不要直接改 `gap_monitor.json`
- 正确做法：修正 Stage2.5 manual/source 数据 → 重跑 Stage2.5（自动同步 metadata/顶层/gap_monitor）→ 重跑 Stage3

**inject 脚本跳过已有值**:
- 若指标已有 `current_value` 且不是 `PLACEHOLDER_SENTINELS = {None, 0, 0.0, 7.13}` 且 `is_stale≠True`，inject 脚本会跳过该条目
- 典型场景：Stage2 DeepSeek 填了值但 `is_estimated=True` → inject 跳过 → Stage3 仍被 gate 约束
- 解法：官方口径用带可信单个 HTTPS `source_url` 的 Stage2.5 manual 重新注入；只有代码内 `official manual override allowlist` 指标（当前 `monetary_policy.mlf`、`forex.USDCNY`、`commodities.BCOM`）可触发 `manual_official_not_estimated` 并把显式 `is_estimated=True` 正规化为 `False`。这不同于 `config/policy_rules.yaml` 的 `estimated_allowlist_keys`（当前 `CN10Y_CDB`、`bdi`），后者只用于 Stage3/quality 对估计值评分/告警处理。显式 URL 字段必须是单个字符串 URL，混入说明文字、多个 URL、非 HTTPS、非法端口、untrusted/spoof/conflicting URL 均不触发；ETF/fund_flow 不在代码内 `official manual override allowlist`，普通 manual 来源不会因为不是官方域名而默认改成 estimated/blocked。

**Stage3 Gate 三路阻断**（需逐一排查，彼此独立）:
1. **policy gate** (`block_stage3=True`)：`redlist` 有 `critical_missing_keys` 中的项 → 修正 Stage2.5 manual/source 数据，重跑 Stage2.5/Stage3
2. **stale_redlist**：`is_stale=True` 的 PMI/TSF/CPI 等关键指标 → 手工注入最新值（含 `date` 字段），Stage2.5 会清除 `is_stale`
3. **compare_gaps** (缺 `previous_value`)：`change_rate` 计算需要 `previous_value`，缺失时 Stage3 阻断 → 补齐 `previous_value`（无论 `--allow-estimated` 是否开启，此检查均不绕过）

**`--allow-estimated` 作用范围**: 仅绕过 `estimated_items`（`is_estimated=True` 的数据进入评分），**不绕过** `compare_gaps`、`stale_redlist` 和 `policy gate`

**fund_flow 估算规则**: `source_url` 不等于窗口真实值。北向/南向/ETF/融资融券只有在结构化来源直接覆盖 5日/120日窗口时才能 `is_estimated=false`；Tier1 域名为 `hkex.com.hk`、`sse.com.cn`、`szse.cn`，Tier2 结构化 path 为 `data.eastmoney.com/hsgt`、`data.eastmoney.com/etf`、`data.eastmoney.com/fund`、`data.eastmoney.com/rzrq`、`tushare.pro/document`；允许的 `window_evidence` 为 `direct_window`、`direct_daily_series`、`direct_balance_delta`。新闻、季度/年度/年内摘要、单日外推、`news_net_flow`、`estimated_net_flow` 一律保持估算并由 gate 阻断或降级展示。`source_tier` 从 URL/domain 推断，不信任 manual JSON 手填值。

**Stage4 MLF 展示**: `policy_name/note/source/manual_reason` 含 `多重价位`、`中标利率`、`参考值`、`口径不适用`、`无统一利率`、`美式招标`、`利率区间` 等 marker 时，当前值显示 `2.00%（参考）`，120 日变化显示 `口径不适用`；普通货币政策当前值两位百分比，变化保持 `pp`。

**gap_monitor 只读诊断**: 不直接手改 `gap_monitor`，也不把手工清空作为正常流程；只为诊断读取该文件，实际修复应补齐/修正源数据后重跑 Stage2.5/Stage3。

**Stage4 production gate**: 正式报告入口是 `scripts/stage4_report_generator.py`，不要直接调用 `generate_report()`。Stage4 会读取 `manual_evidence_audit.json` 与 `pipeline_audit.json`；若 `errors` 非空会阻断。`--allow-fallback-report` 仅本地调试，生产遇到 `fallback_used=true` 要回到 Stage3 修复。若仅剩 ETF/fund_flow 窗口或估算 blocker，Stage3、`audit_pipeline_consistency.py` 和 Stage4 才同步使用 `--skip-fund-flow-check`。

**config/manual 修改后重跑**: 改 `config/policy_rules.yaml` 或当日 `_manual.json` 后，按 Stage2.5 -> Stage3 -> audit -> Stage4 重跑；只重跑 Stage4 会复用旧的 complete/pring/audit 产物。

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

## Architecture Notes

完整 repo map、配置路径、输出文件和 WebSearch schema 以 `AGENTS.md` 为准；`CLAUDE.md` 只保留高频提醒。

### Key Pattern

```python
from datasource import get_manager
manager = get_manager()  # Singleton
response = await manager.get_forex_data("DXY", start, end)  # 返回 DataResponse
```

### Trend History Rules

- 股指 200 交易日 / 外汇商品债券 121 交易日 / 资金流 120 交易日 / 宏观事件 24 条
- Stage1 写入 `is_partial=true`，Stage2.5 最终覆盖
- CN10Y/CN10Y_CDB 禁止 ETF 代理写入；禁止从 `reports/*.md` 反向回填

## Environment Variables

```bash
TUSHARE_TOKEN=xxx      # Required: Stage1
TAVILY_API_KEY=xxx     # Required: Stage2
DEEPSEEK_API_KEY=xxx   # Required: LLM extraction
DEEPSEEK_MODEL=deepseek-v4-pro  # Default; DEEPSEEK_MODEL or CLI args can override
DEEPSEEK_EXTRACT_MAX_TOKENS=900  # Optional: Stage2 extraction JSON token budget
EXA_API_KEY=xxx        # Optional but recommended: Tavily quota/rate/payment failover; non-quota fallback still needs --enable-exa-fallback / STAGE2_ENABLE_EXA_FALLBACK=1
```

## Troubleshooting

| 问题 | 解决方案 |
|------|----------|
| DeepSeek 超时 | 默认 `DEEPSEEK_EXTRACT_MAX_TOKENS=900`；仍不稳用 `--extraction-backend regex --disable-extract` |
| DeepSeek JSON 失败 | `deepseek_json_truncated` 优先调 token 或转 Stage2.5；`deepseek_json_parse_error` 查 prompt/schema 与 snippets |
| Tavily extract 422 | 自动回退 DeepSeek；不会激活全局 Exa failover，仍不稳用 `--disable-extract` |
| USDCNY 官方表格为空 | 看 `official_domain_filter_empty`；不要放宽到非官方 fallback，转 Stage2.5 补可信官方来源 |
| Tavily quota/rate/payment | 有 `EXA_API_KEY` 时同轮切 Exa；看 `search_backend_final`、`tavily_to_exa_failover_count`、`exa_failover_*`、`exa_error_breakdown`。无 Exa 或 `exa_unavailable` 时转 Stage2.5 |
| Stage2 代理/DNS/TLS 错误 | 环境错误不触发 Exa；重跑 `bash run_preflight.sh`，确认 `DATASOURCE_NETWORK_MODE` 和代理设置 |
| Tavily 当日重复 422 | **不要重试 Stage2**；改用 Stage2.5 手工注入 |
| 日志出现 `deepseek_no_value/no_deepseek_key` | 视为 `manual_required`，优先使用 `metadata.manual_required` 骨架补数 |
| Stage3 `block_stage3=True` 但数据已注入 | 检查 `missing_items`、`policy_evaluation.json`、`gap_monitor.json`，补齐/修正 manual JSON 后重跑 Stage2.5/Stage3 |
| Stage3 `compare_gaps` 阻断 | 补齐 `macro_indicators.*.previous_value`（`--allow-estimated` 不绕过此检查） |
| inject 跳过 `is_estimated` 项 | 官方口径用带可信单个 HTTPS `source_url` 的 Stage2.5 manual 重新注入；非官方/ETF/fund_flow 等估算不要手工清掉 gate |
| 股指数据不是今日 | Stage1 在 15:00 CST 前运行时正常，使用前一日收盘；无需处理 |
| 代理/TLS 问题 | `env -u http_proxy -u https_proxy` 前缀 |
| 完整度 <80% | 检查 macro/monetary null 字段，手动补数后重注入 |
| 报告出现 N/A | 检查 `gap_monitor`，确保数值为可解析数字 |
| Stage4 阻断 `manual_evidence_audit` | 检查 manual `source_url` 是否为支持该值的证据 URL，不要用品牌入口、占位 URL 或与 `source` 平台不一致的 URL；修正后重跑 Stage2.5/audit/Stage3/Stage4 |
| Stage4 阻断 `pipeline_audit` | 按 audit errors 修正 complete/pring/gap 状态；仅剩 ETF/fund_flow blocker 时 Stage3、audit、Stage4 同步加 `--skip-fund-flow-check` |
| SyntaxError 启动失败 | `python -m py_compile src/datasource/adapters/*.py src/datasource/utils/*.py` |
| 搜索相关性低 | 调整 `search_profiles.queries/exclude_domains`，或提高 `--low-score-threshold` |

> 完整故障排除表见 AGENTS.md "## 12. Troubleshooting"

**诊断工具**:
- `bash run_clean.sh python scripts/stage2_health_check.py` — Stage2 前置健康检查（验证 Tavily/DeepSeek key、缓存路径可写、基本连通性）
- `bash run_clean.sh python scripts/stage2_low_score_audit.py --date YYYY-MM-DD` — 审计低分仍进入抽取的指标
- `bash run_clean.sh python scripts/audit_manual_evidence.py --manual-data data/runs/${DATE_NH}/websearch_results_manual.json --market-data data/runs/${DATE_NH}/market_data_complete.json --stage2-log logs/runs/${DATE_NH}/stage2_unified_log.json --output data/runs/${DATE_NH}/manual_evidence_audit.json` — 审计 manual/source_url 证据
- `bash run_clean.sh python scripts/audit_pipeline_consistency.py --market-data data/runs/${DATE_NH}/market_data_complete.json --pring-result data/runs/${DATE_NH}/pring_result.json --gap-monitor data/runs/${DATE_NH}/gap_monitor.json --output data/runs/${DATE_NH}/pipeline_audit.json` — 审计 Stage3/Stage4 gate 一致性

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
