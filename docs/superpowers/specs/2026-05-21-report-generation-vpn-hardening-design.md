# 报告生成 VPN 隔离与质量诊断加固设计

## 背景

2026-05-21 报告生成复盘暴露了三个源头问题。

第一，运行环境会受宿主 VPN 变更影响。当前 runtime 只清理 `http_proxy/https_proxy/HTTP_PROXY/HTTPS_PROXY`，没有清理 `ALL_PROXY/all_proxy`。当 WSL2 环境保留 `ALL_PROXY=socks5h://...` 且 Python 环境缺少 SOCKS 支持时，Stage2 会在 Tavily/DeepSeek 调用前后批量失败，错误为 `Using SOCKS proxy, but the 'socksio' package is not installed`。这类错误不应进入 38 个任务逐个失败的调度路径。

第二，Claude Code 在补数和生成报告过程中遇到的主要摩擦来自质量 gate 的可解释性不足，以及估算值处理边界不够清晰。部分官方来源抽取结果被标为估算，Stage2.5 既有值跳过不透明，fund_flow 窗口证据规则需要更明确地暴露，Stage3/Stage4 阻断信息过长，报告侧对半估算数据缺少可审计的降级展示路径。

第三，在 Ubuntu/WSL 中使用 Claude Code 时，空 `.venv` 会反复触发启动错误或要求显式 `ALLOW_SYSTEM_PYTHON=1`。这符合当前文档的严格规则，但不适合交互式代理工作流。空 `.venv` 本质上是“尚未初始化”，应当和“非空但损坏或 Windows/Linux 混用的 venv”分开处理。

本设计延续已有 superpowers 设计：

1. `2026-05-07-report-generation-hardening-design.md` 的 runtime bootstrap 和 preflight 方向。
2. `2026-04-28-daily-pipeline-hardening-design.md` 的 Stage2 fast-switch、`--allow-estimated` 边界。
3. `2026-05-19-gate-report-consistency-design.md` 的 fund_flow 严格窗口证据 gate。

## 目标

1. 默认报告流水线不受 VPN 环境变量漂移影响。
2. 在 preflight 或 Stage2 早期识别代理环境错误，避免同轮任务批量失败。
3. Ubuntu/WSL 中空 `.venv` 可一次性自愈，避免 Claude Code 每次启动都卡在同一个环境错误。
4. 让 Stage2 官方来源抽取结果在证据充分时自动写为非估算，减少 Stage2.5 元数据返工。
5. 让 Stage2.5 对跳过、覆盖、元数据更新和 fund_flow 强制估算的原因给出结构化反馈。
6. 让 Stage3/Stage4 gate 错误按来源分块输出，便于一次性修复。
7. 报告可展示非核心估算值，但必须显式标注估算属性，不能通过伪造 `is_estimated=false` 过 gate。
8. 同步更新 `AGENTS.md`、`CLAUDE.md`、manual template 和聚焦测试。

## 非目标

1. 不放松 fund_flow 的 Tier1/Tier2 + direct window 证据要求。
2. 不让 `--allow-estimated` 绕过 `estimated_not_allowed`、缺失值、compare gaps、stale redlist 或 policy gate。
3. 不新增 Tavily quota probe，也不在 preflight 发送 Tavily search/extract 请求。
4. 不把所有手工补数默认视为可信非估算。
5. 不重写 Stage1 -> Stage2 -> Stage2.5 -> Stage3 -> Stage4 主流程。
6. 不把代理模式设为默认；代理只能显式启用。

## 方案概览

采用“默认直连 + 空 venv 自愈 + 显式代理 + 结构化诊断 + 降级展示”的方案。

运行环境层默认清空所有主动代理变量，并让 HTTP client 不读取环境代理。只有用户显式设置代理模式或传代理参数时，才允许走代理；SOCKS 代理必须先验证依赖存在。空 `.venv` 视为可初始化状态，runtime 可在受控模式下一次性创建并安装依赖；非空但不可用的 venv 仍然 hard fail。

数据链路层保持质量 gate 严格，但提高可解释性：Stage2 官方来源可自动正规化为非估算；Stage2.5 清楚报告跳过和覆盖原因；Stage3/Stage4 分块输出 blocker；Stage4 可以展示估算值提醒，但核心评分仍由 policy 控制。

## 运行环境与 VPN 隔离

### Runtime 默认直连

修改 `scripts/runtime_env.sh`：

1. 继续保留 `no_proxy/NO_PROXY`。
2. 清理主动代理变量：

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
```

修改 `run_clean.sh`：

```bash
exec env \
  -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  -u ALL_PROXY -u all_proxy \
  PYTHONPATH="$PYTHONPATH" "$@"
```

这样即使用户切换 VPN 后 shell 中残留 `ALL_PROXY`，默认流水线也不会继承。

### 显式代理模式

新增环境变量：

```text
DATASOURCE_NETWORK_MODE=direct|proxy
```

默认值为 `direct`。

`direct` 模式：

1. runtime 和 `run_clean.sh` 清理 6 个代理变量。
2. Stage2 HTTP client 使用 `trust_env=False`。
3. preflight 若发现任何主动代理变量仍存在，直接失败并打印变量名。

`proxy` 模式：

1. 允许用户通过 `--http-proxy/--https-proxy` 或环境变量显式传代理。
2. 若代理 URL 以 `socks://`、`socks5://`、`socks5h://` 开头，preflight 必须检测 Python 环境具备 SOCKS 支持。
3. 若缺少 SOCKS 支持，preflight 失败，提示安装 `httpx[socks]` 或切回 direct 模式。

### HTTP client 不信任环境代理

修改 `src/datasource/adapters/tavily_client.py`：

1. `AsyncTavilyClient` 增加 `trust_env: bool = False`。
2. 构造 `httpx.AsyncClient(..., trust_env=self.trust_env)`。
3. 只有 Stage2 显式代理模式才传 `trust_env=True` 或显式 `proxies`。

DeepSeek/OpenAI client 如使用 `httpx` 或 SDK 默认环境代理，也应按同一原则禁用环境代理或只接受显式 proxy 参数。

### Stage2 环境错误 fast-fail

Stage2 捕获以下错误时，不继续逐个任务重试：

1. `Using SOCKS proxy, but the 'socksio' package is not installed`
2. `ProxyError`
3. 明确由代理配置导致的 connect failure

处理结果：

1. `summary.tavily_unavailable_reason = environment_proxy_error`
2. `retrieval_diagnostics` 写入代理错误摘要。
3. 剩余外部任务写 `manual_required` skeleton。
4. 不继续发起 Tavily search/extract 或 DeepSeek 抽取。

## Ubuntu/Claude Code 空 venv 自愈

### 现状

当前 `scripts/runtime_env.sh` 将空 `.venv` 视同“没有可用 venv”，随后除非显式设置 `ALLOW_SYSTEM_PYTHON=1`，否则 hard fail。这个规则能避免静默使用错误 Python，但在 Ubuntu/WSL 的 Claude Code 会话里，如果工作区被初始化出一个空 `.venv`，每次启动都会重复报错。

### 目标行为

区分三类 venv 状态：

| 状态 | 行为 |
|------|------|
| `.venv` 不存在 | 保持当前规则：默认 hard fail；显式 `ALLOW_SYSTEM_PYTHON=1` 可用系统 Python |
| `.venv` 为空目录 | 允许一次性自动初始化 `.venv`，初始化成功后使用 venv Python |
| `.venv` 非空但不可用 | 继续 hard fail，提示删除并重建，避免 Windows/Linux venv 混用 |

### 自动初始化条件

新增环境变量：

```text
DATASOURCE_AUTO_VENV=1
```

建议在 Claude Code/Ubuntu 工作流中默认设置，或由 `run_clean.sh` 在交互式 shell 中对空 `.venv` 自动启用。生产和 CI 可以显式设置 `DATASOURCE_AUTO_VENV=0` 保持严格模式。

当 `.venv` 是空目录且 `DATASOURCE_AUTO_VENV=1` 时，runtime 执行一次：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
```

若用户设置：

```text
DATASOURCE_INSTALL_DEV=1
```

再执行：

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

### 防重复与失败处理

初始化成功后写入：

```text
.venv/.datasource_bootstrapped
```

stamp 内容包含 Python 版本、`requirements.txt` hash 和 `setup.py` mtime。后续启动只要 stamp 与依赖文件匹配，不再安装依赖。

初始化失败时：

1. 打印失败步骤。
2. 保留 `.venv` 目录但写入 `.venv/.datasource_bootstrap_failed`。
3. 下次启动看到 failed stamp 时，提示用户删除空/半成品 `.venv` 或重新运行 bootstrap；不反复静默重试 pip。

### 独立入口

新增脚本：

```text
scripts/bootstrap_venv.sh
```

职责：

1. 只处理 `.venv` 创建和依赖安装。
2. 不加载 `.env`，不触发 Tavily/DeepSeek/TuShare。
3. 可被 `runtime_env.sh` 调用，也可由用户手动执行。

`run_preflight.sh` 和 `run_clean.sh` 只调用统一 runtime helper，不各自复制 venv 初始化逻辑。

## Stage2 官方来源估算正规化

新增共享 helper，例如：

```text
src/datasource/utils/source_trust.py
```

职责：

1. 判断 `source_url` 域名是否属于官方来源。
2. 判断 URL 是否来自 snippets，而非模型幻觉。
3. 判断抽取值是否具备目标日期或期次证据。
4. 判断单位和值类型是否匹配指标 profile。

初始官方域名集合：

1. `stats.gov.cn`
2. `data.stats.gov.cn`
3. `pbc.gov.cn`
4. `chinamoney.com.cn`
5. `cfets.com.cn`
6. 交易所或指数商官方域名按已有 profile 逐步加入。

Stage2 写回时，以下条件同时满足才设置 `is_estimated=false`：

1. `source_url` 来自 snippets。
2. `source_url` 域名命中官方来源。
3. 日期、期次或 daily quote reference 与任务期望匹配。
4. 抽取值和单位可解析，且不触发 value evidence miss。

fund_flow 不套用此规则。资金流真实窗口值仍必须通过 `source_tier`、`window_evidence`、`metric_basis` 三项 gate。

## Stage2 超时降级

DeepSeek 抽取增加本轮 circuit breaker。

触发条件：

1. 连续超时达到阈值，例如 3 次。
2. 或本轮已完成抽取中 timeout rate 超过阈值，例如 50%。

触发后：

1. 后续任务不再等待 DeepSeek。
2. 可 regex 提取的任务走 regex。
3. 不可 regex 提取的任务直接写 manual skeleton。
4. summary 写入 `deepseek_circuit_breaker_triggered=true`、`deepseek_timeout_rate`、`fallback_mode`。

该策略减少等待时间，不降低证据要求。

## Stage2.5 注入反馈与覆盖规则

### 注入 summary

Stage2.5 输出增加结构化统计：

1. `injected`
2. `metadata_updated`
3. `skipped_existing`
4. `skipped_no_parseable_value`
5. `forced_override`
6. `fund_flow_forced_estimated`

每个明细包含：

```json
{
  "category": "macro_indicators",
  "key": "cpi",
  "reason": "existing_value_equal_metadata_updated",
  "existing_value": 1.2,
  "incoming_value": 1.2
}
```

### 元数据覆盖

若 manual payload 与已有数值相同，但提供了更完整或更可信的 `source_url/date/as_of_date/report_period/is_estimated/note/confidence`，允许更新元数据，不要求 `--force-override`。

若 incoming value 与 existing value 不同：

1. 默认跳过并打印冲突。
2. 只有 `--force-override` 才覆盖。
3. 覆盖时记录 `forced_override` 明细。

### fund_flow 反馈

fund_flow 被强制设置为 `is_estimated=true` 时，输出完整诊断：

```json
{
  "category": "fund_flow",
  "key": "etf",
  "reason": "fund_flow_window_not_direct",
  "source_tier": "tier3",
  "window_evidence": "news_summary",
  "metric_basis": "estimated_net_flow"
}
```

manual template 和文档必须列出：

1. Tier1 域名：`hkex.com.hk`、`sse.com.cn`、`szse.cn`。
2. Tier2 path：`data.eastmoney.com/hsgt`、`/etf`、`/fund`、`/rzrq`。
3. 允许的 `window_evidence`：`direct_window`、`direct_daily_series`、`direct_balance_delta`。
4. 禁止放行的 `metric_basis`：`news_net_flow`、`estimated_net_flow`。
5. 弱证据关键词：季度、年度、年内、单日、外推等。

## Stage3 与 Stage4 gate 输出

新增共享 formatter，例如：

```text
src/datasource/utils/gate_formatting.py
```

Stage3 阻断信息按块输出：

```text
Stage3 阻断，以下问题需修复：

[policy gate]
- fund_flow.etf estimated_not_allowed source_tier=tier3 window_evidence=news_summary metric_basis=estimated_net_flow

[unified_quality]
- macro_indicators.cpi estimated_not_allowed
- commodities.BCOM missing_compare_values

[completeness]
- data_completeness=0.762 (<0.8)

[gap_monitor]
- pending: CN10Y_CDB
- manual_required: USDCNY

[stage2 flag]
- metadata.ai_websearch_enhanced missing
```

Stage4 使用同一 formatter。这样报告生成失败时，用户能直接看到应该修哪个 category/key/reason。

## 报告渲染与估算展示

### 股票指数

根本修复在 Stage2.5：指数类 payload 必须写入 `stock_indices`，不能落入 `macro_indicators`。

Stage4 可增加旧产物兼容：

1. 当 `stock_indices` 为空或缺少关键指数时，从 `macro_indicators` 中识别 `000001`、`399001`、`399006`、`000300`、`000016`。
2. 仅用于展示兼容。
3. 报告备注来源为 `macro_indicators_compat_backfill`，避免误认为原生股指结构。

### 商品和外汇变化率

Stage2.5 manual 若提供 `previous_price`、`previous_value`、`previous_date` 或 120 日 base 值，应优先用这些字段重算：

1. `daily_change`
2. `change_120d`
3. `change_5d` 或对应窗口变化

若使用 trend_history 近邻值，应写入 base date/source/confidence。报告侧在低置信时显示 `—（异常）` 或 `(低置信)`，不能混用旧前值和新现值。

### 估算值分级

报告增加估算分级提醒：

1. `official`：官方来源、非估算。
2. `structured`：结构化可信来源、非估算。
3. `manual_estimated`：人工估算。
4. `derived`：公式推导或代理序列。

核心评分继续遵守 policy gate。非核心估算值可展示，但必须标注 `(估)`，并在估算值提醒中列出来源和方法。

## 文档更新

更新 `AGENTS.md`：

1. 说明默认 `DATASOURCE_NETWORK_MODE=direct`。
2. 说明 VPN 变更后 preflight 必须重新跑。
3. 补齐 6 个代理变量清理规则。
4. 说明 Ubuntu/Claude Code 空 `.venv` 的 `DATASOURCE_AUTO_VENV=1` 自愈流程。
5. 补齐 fund_flow pass/fail 清单。
6. 明确 `--allow-estimated` 不绕过 policy gate。

更新 `CLAUDE.md`：

1. 高频提醒中加入 VPN/代理排障。
2. 高频提醒中加入空 `.venv` 处理：优先让 runtime bootstrap，一次性初始化后不再使用 `ALLOW_SYSTEM_PYTHON=1` 作为常态。
3. 注入跳过时说明优先看 Stage2.5 summary。
4. 将 fund_flow tier/path/window evidence 清单放入操作陷阱。
5. 修正 CLI help 易误解处的转述。

更新 `data/runs/templates/manual_template.json`：

1. 增加 fund_flow direct window 示例。
2. 增加估算 fund_flow 被阻断示例。
3. 增加官方来源非估算宏观/货币示例。

## 测试计划

新增或更新聚焦测试：

1. `tests/test_runtime_env.py`：验证 `ALL_PROXY/all_proxy` 被清理，`NO_PROXY` 保留。
2. `tests/test_runtime_env.py`：验证空 `.venv` + `DATASOURCE_AUTO_VENV=1` 会调用 bootstrap；非空坏 venv 仍 hard fail。
3. `tests/test_bootstrap_venv.py`：验证 bootstrap 成功写 stamp，失败写 failed stamp，不触发外部 API。
4. `tests/test_run_clean.py` 或现有 shell 测试：验证 `run_clean.sh` 执行命令时清理 6 个代理变量。
5. preflight 测试：direct 模式发现主动代理变量时失败；proxy 模式 SOCKS 缺依赖时失败。
6. `tests/test_tavily_client.py`：验证默认 `trust_env=False`。
7. Stage2 proxy error 测试：SOCKS 缺依赖错误触发 `environment_proxy_error` fast-fail。
8. Stage2 官方来源测试：官方 URL + 期次匹配写 `is_estimated=false`；非官方或期次不匹配不自动正规化。
9. Stage2.5 注入测试：相同值可更新元数据；不同值无 `--force-override` 时跳过并记录原因。
10. fund_flow 测试：Tier1/Tier2 direct window 保持非估算；新闻摘要/外推强制估算并输出诊断。
11. Stage3/Stage4 formatter 测试：多个 gate 分块输出。
12. simple report 测试：指数兼容回填、商品 previous value 重算、估算值提醒展示。

## 推进顺序

1. 先实现空 `.venv` 自愈 bootstrap，消除 Ubuntu/Claude Code 启动摩擦。
2. 再实现 VPN/代理隔离和 preflight hard fail。
3. 再实现 Stage2 环境错误 fast-fail。
4. 再实现官方来源估算正规化和 DeepSeek timeout circuit breaker。
5. 再实现 Stage2.5 summary、元数据覆盖和 fund_flow 诊断输出。
6. 再实现 Stage3/Stage4 formatter。
7. 最后实现报告渲染兼容和估算值分级展示。
8. 同步文档与 manual template。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 自动初始化 venv 触发耗时 pip install | 只对空 `.venv` 且 `DATASOURCE_AUTO_VENV=1` 生效，成功后用 stamp 防重复 |
| 半初始化 venv 反复重试 | 失败写 failed stamp，下次明确提示人工清理或重跑 bootstrap |
| 用户确实需要代理访问外网 | 提供显式 `DATASOURCE_NETWORK_MODE=proxy` 和代理参数，不让隐式 VPN 变量生效 |
| 官方域名自动非估算误判 | 必须同时满足 URL、期次、单位和值证据；fund_flow 排除在外 |
| 元数据覆盖掩盖数值冲突 | 仅同值允许无 force 元数据覆盖；不同值仍需 `--force-override` |
| 报告展示估算值被误读 | 所有估算展示加 `(估)` 和估算提醒，核心评分仍由 policy gate 控制 |
| Stage2 circuit breaker 跳过可恢复任务 | 只在连续超时或高超时率触发，并在 summary 中记录降级原因 |

## 验收标准

1. 设置 `ALL_PROXY=socks5h://127.0.0.1:7890` 后，默认 `bash run_preflight.sh` 或 `bash run_clean.sh ...` 不再让 Stage2 继承该变量。
2. Ubuntu/WSL 中空 `.venv` 在 `DATASOURCE_AUTO_VENV=1` 下会一次性创建并安装依赖，后续 Claude Code 启动不再重复报空 venv。
3. 非空坏 `.venv` 仍 hard fail，并提示删除重建。
4. direct 模式下 Tavily/DeepSeek HTTP client 不读取环境代理。
5. SOCKS 代理缺依赖时，preflight 或 Stage2 早期给出 `environment_proxy_error`，不出现 38 个任务逐个失败。
6. 官方宏观/货币来源在证据充分时写为 `is_estimated=false`。
7. Stage2.5 对跳过、元数据更新、强制覆盖、fund_flow 强制估算都有明细输出。
8. Stage3/Stage4 阻断信息按 gate 分块，每个 blocker 独立成行。
9. 报告中估算数据显式标注，不能通过手工伪造非估算来通过质量 gate。
10. 新增聚焦测试通过，且不真实调用 Tavily、DeepSeek 或 TuShare。
