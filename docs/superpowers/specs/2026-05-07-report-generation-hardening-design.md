# 报告生成运行入口与手工补数模板加固设计

## 背景

2026-05-07 报告生成复盘暴露了两个会重复消耗时间的源头问题。

第一，Stage2 依赖 Tavily 和 DeepSeek 外部网络，但 `run_preflight.sh` 只检查 API key 和代理变量。DNS 或 HTTPS 基本连通性不可用时，失败会推迟到 Stage2 运行阶段，导致同日 Tavily search/extract 机会被浪费，且排障成本高。

第二，Stage2.5 manual JSON 的人工填写规则分散在代码、`AGENTS.md`、`CLAUDE.md` 和经验里。`industrial` 的 `yoy_month/yoy_ytd` 口径、`is_estimated` 的使用边界、BDI allowlist 二级约束都容易在赶报告时被误用，造成多次注入迭代。

复盘后的本机检查还暴露出第三个环境问题：`.env` 存在且可加载，但 `.venv` 目录可能只是空目录；裸 shell 里可能没有 `python`，只有 `python3`。如果 `run_preflight.sh`、`run_clean.sh` 各自处理 `.env/.venv/PYTHONPATH`，会出现 preflight 与真实 Stage 命令使用不同运行环境的漂移。

本设计只覆盖运行入口加固、运行环境 bootstrap 统一和 Stage2.5 manual 模板沉淀，不改变 Stage1 -> Stage2 -> Stage2.5 -> Stage3 -> Stage4 主流程。

## 目标

1. 在 Stage1/Stage2 前更早发现 DNS、TLS、路由类问题。
2. 统一 `.env`、`.venv`、系统 Python fallback、代理清理和 `PYTHONPATH` 处理，避免 preflight 与 Stage 命令环境不一致。
3. 保持 `run_clean.sh` 现有语义，但消除 CRLF 行尾导致的 shell 解析风险，并建立防回归检查。
4. 固化 Stage2.5 manual JSON 模板，降低人工补数时的 schema 和 policy 误用概率。
5. 在 `AGENTS.md` 和 `CLAUDE.md` 中补齐高频操作提醒，避免只靠复盘记忆。
6. 增加聚焦测试，覆盖运行入口和模板结构，不真实调用外部网络。

## 非目标

1. 不新增 Tavily quota probe，不调用 Tavily search/extract 作为 preflight。
2. 不改 Stage2 搜索调度、DeepSeek 抽取、policy gate 或 Stage3 评分逻辑。
3. 不做“最新月份默认值缓存”，避免破坏实时来源证据约束。
4. 不修改历史 `docs/archive/*`，不重写旧版流程文档。
5. 不让模板被流水线自动读取；模板只是人工补数起点。
6. 不把 `.env` 和 `.venv` 合并；两者职责不同，只统一加载入口。

## 设计概览

采用“早失败 + 明模板 + 小测试”的方案。

新增一个轻量 runtime bootstrap helper，统一 `.env`、Python 环境、代理和 `PYTHONPATH` 处理。`run_preflight.sh` 复用该 helper，并在正式流水线前验证 DNS 和 HTTPS 基本连通性。`run_clean.sh` 继续作为统一入口，但把重复环境加载逻辑委托给 helper，同时修正行尾并保持当前虚拟环境选择行为。

`data/runs/templates/manual_template.json` 提供可复制的 Stage2.5 manual schema 示例，并用 `_rules`、`_note` 等字段记录人工规则。文档只更新 `AGENTS.md` 和 `CLAUDE.md` 的当前权威/高频部分。

## 运行入口设计

### Runtime bootstrap helper

新增：

```text
scripts/runtime_env.sh
```

职责：

1. 定位 repo root 并切换到根目录。
2. 检查 `.env` 存在并加载。
3. 清理 `http_proxy/https_proxy/HTTP_PROXY/HTTPS_PROXY`，保留 `no_proxy/NO_PROXY`。
4. 解析 Python 运行环境。
5. 统一补齐 `PYTHONPATH=./src`，保留已有外部 `PYTHONPATH` 并把 `./src` 放在前面。

Python 环境解析规则：

1. 如果 `.venv/bin/activate` 存在，source 它，并设置 `DATASOURCE_PYTHON=python`。
2. 如果是 Windows native bash，且 `.venv/Scripts/activate` 存在，source 它，并设置 `DATASOURCE_PYTHON=python`。
3. 如果 `.venv` 目录存在但没有任何可用 activate 文件，默认视为坏环境，输出明确错误：`.venv exists but no usable activate script found`。
4. 如果没有可用 venv，只有显式 `ALLOW_SYSTEM_PYTHON=1` 时允许系统 Python fallback。
5. fallback 优先选择 `python3`，其次才是 `python`，并设置 `DATASOURCE_PYTHON` 为实际命令。
6. 如果没有 venv 且未设置 `ALLOW_SYSTEM_PYTHON=1`，保持当前 hard fail 行为。

`run_clean.sh` 和 `run_preflight.sh` 都 source 这个 helper。这样 preflight 用到的 Python fallback、代理清理和 Stage 命令保持一致。

### `run_preflight.sh`

脚本执行顺序调整为：

1. source `scripts/runtime_env.sh`。
2. 检查 `TAVILY_API_KEY`、`DEEPSEEK_API_KEY`、`TUSHARE_TOKEN` 非空且长度不短。
3. 对 `api.tavily.com`、DeepSeek host、`api.tushare.pro` 做 DNS 解析。
4. 对 Tavily、DeepSeek、TuShare base URL 做非业务型 HTTPS 连通性检查。
5. 输出 key 存在性摘要、Python 环境摘要和 proxy cleared 状态。

DNS 解析优先使用 `getent hosts <host>`。如果当前系统没有 `getent`，降级为：

```bash
"$DATASOURCE_PYTHON" - "$host" <<'PY'
import socket, sys
socket.getaddrinfo(sys.argv[1], 443)
PY
```

HTTPS 连通性优先使用 `curl`，设置短超时并只判断是否拿到 HTTP 响应：

```bash
code="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 8 "$url" || printf '000')"
test "$code" != "000"
```

如果 `curl` 不存在，降级用 Python 标准库发起 `HEAD` 请求。失败时脚本非零退出，并明确打印失败 host 或 URL。

DeepSeek URL 使用 `DEEPSEEK_BASE_URL`，未设置时默认为 `https://api.deepseek.com`。Tavily URL 使用 `https://api.tavily.com`。TuShare URL 使用 `https://api.tushare.pro`。这些检查只验证 DNS/TLS/路由可达，不发送 search/chat 请求，不消耗搜索额度。

DNS 异常是运行环境 hard fail。`run_preflight.sh` 任一 host 解析失败时直接退出，不进入 Stage1/Stage2。Stage2 若在运行中捕获 DNS 类异常，应记录 `tavily_unavailable_reason=dns_resolution_failed` 或对应外部服务原因，剩余外部任务转 `manual_required` skeleton，并停止继续发起 Tavily/DeepSeek 请求；这属于边界说明，不在本次实现中重写 Stage2 调度。

### `run_clean.sh`

`run_clean.sh` 的外部行为保持不变，但内部改为 source `scripts/runtime_env.sh`：

1. 优先 `.venv/bin/activate`。
2. Windows native bash 下允许 `.venv/Scripts/activate`。
3. 无 venv 时，只有显式 `ALLOW_SYSTEM_PYTHON=1` 才使用系统 Python。
4. 始终 source `.env`、清理代理、补齐 `PYTHONPATH=./src`。

实现层同时做 LF 行尾正规化，不引入自动 `dos2unix` 依赖。测试会读取仓库里的 `run_clean.sh` 原文件，断言不包含 `\r\n`。

### `.env.example`

同步清理 `.env.example`：

1. `TUSHARE_TOKEN` 改为占位符，不在模板中保存看似真实的 token。
2. 增加 `EXA_API_KEY=` optional 示例，与现有文档保持一致。
3. 移除或注释弱化 `PYTHONPATH=.`，说明 `run_clean.sh`/runtime helper 会统一设置 `PYTHONPATH=./src`。

## Manual 模板设计

新增文件：

```text
data/runs/templates/manual_template.json
```

模板是有效 JSON。由于 JSON 不支持注释，使用 `_rules`、`_note`、`_example_only` 字段承载说明。Stage2.5 按已知 category 读取数据，未知顶层字段必须被忽略；测试会确认模板可解析且说明字段不会影响注入器读取。

模板覆盖高频补数字段：

1. `macro_indicators.industrial`
2. `macro_indicators.bdi`
3. `forex.USDCNY`
4. `bonds.CN10Y_CDB`
5. `commodities.BCOM`
6. `fund_flow.northbound/southbound/etf`

### `industrial` 示例规则

`industrial` 示例必须显式包含：

```json
{
  "current_value": 6.3,
  "yoy_month": 6.3,
  "value_type": "yoy_month"
}
```

模板说明要写清楚：如果使用国家统计局“1-2月累计同比”作为流水线当前值，仍必须显式写 `value_type: "yoy_month"` 和 `yoy_month`。否则注入器会根据“累计”等 marker 将值归为 `yoy_ytd`，而 Stage3 当前仍以 `current_value = yoy_month` 为硬约束，最终会触发 `current_value is missing`。

### `is_estimated` 规则

模板默认把官方发布值、官方中间价、交易所/指数商实时值写成：

```json
"is_estimated": false
```

只有以下情况写 `true`：

1. 利差估算。
2. 公式推导。
3. ETF 或代理序列替代。
4. 缺口外推。
5. 明确非官方近似值。

`CN10Y_CDB` 如果用利差估算，示例保留 `is_estimated: true`、`estimation_method` 和 `source_url`。如果未来能取得可信官方或中债来源的直接值，可写 `is_estimated: false`。

### BDI 二级约束

模板中 `bdi` 示例写明：即使 `bdi` 在 `estimated_allowlist_keys` 内，仍必须满足 `config/policy_rules.yaml` 的 `bdi_estimated_allow_conditions`：

1. `source_url` 域名属于可信域名列表。
2. 日期不超过 `max_age_days=2`。
3. 点位在合理 `value_range` 内。
4. 单位包含“点”、“point”或“points”。

模板示例使用 `source_url` 字段承载单个 URL，不把说明文字和 URL 混在同一个字段里。

## 文档设计

### `AGENTS.md`

更新当前权威流程说明：

1. Preflight 增加 DNS 和 HTTPS 基本连通性检查，失败时不要启动 Stage2。
2. `.env` 与 `.venv` 职责不同；统一通过 runtime helper 加载，不手工散落 source。
3. `run_clean.sh` 要求 LF 行尾；若遇到 shell 解析异常，优先检查 CRLF。
4. Stage2.5 manual 注入处引用 `data/runs/templates/manual_template.json`。
5. `industrial` 增加 `value_type/yoy_month` 特别提醒。
6. `--allow-estimated` 说明补充：只允许 policy allowlist 中的估算项参与评分，不是全局放行。
7. BDI allowlist 的二级约束写成显式条目。

### `CLAUDE.md`

更新快速提醒：

1. 运行日报前先跑 `bash run_preflight.sh`，失败时不要启动 Stage2。
2. `.env` 是密钥/配置，`.venv` 是依赖环境，二者不合并；使用 `run_clean.sh`/`run_preflight.sh` 的统一 bootstrap。
3. Stage2.5 manual 官方值默认 `is_estimated=false`。
4. `industrial` 1-2 月累计同比注入必须写 `value_type: yoy_month` 和 `yoy_month`。
5. BDI 即使 allowlisted，也受 `max_age_days/trusted_domains/value_range/unit_keywords` 约束。

## 测试设计

### `tests/test_run_clean.py`

增加 runtime 和行尾防回归断言：

1. 直接读取仓库根目录 `run_clean.sh` 的 bytes。
2. 断言不包含 `b"\r\n"`。
3. 保留现有 Windows venv 和 system fallback 测试。
4. 增加 `.venv` 空目录存在但无 activate 时 hard fail 的测试。

### `tests/test_run_preflight.py`

用临时目录和 fake PATH 测试脚本行为，不访问真实网络：

1. 缺 `.env` 时非零退出。
2. key 缺失或过短时非零退出。
3. fake `getent` 返回失败时，脚本在 DNS 阶段非零退出并打印 host。
4. fake `curl` 返回失败时，脚本在 HTTPS 阶段非零退出并打印 URL。
5. fake `getent` 和 fake `curl` 都成功时，脚本返回 0。
6. 无 `python` 但有 `python3` 且 `ALLOW_SYSTEM_PYTHON=1` 时，Python fallback 可用。

测试通过复制 `run_preflight.sh` 到临时 repo，并写入最小 `.env`，避免污染真实环境。

### `tests/test_runtime_env.py`

覆盖 shared helper：

1. 缺 `.env` 时失败。
2. `.venv/bin/activate` 优先。
3. Windows native bash 下 `.venv/Scripts/activate` 可用。
4. 空 `.venv` 目录 hard fail。
5. `ALLOW_SYSTEM_PYTHON=1` 时选择 `python3` fallback。
6. `PYTHONPATH` 最终包含 `./src` 且保留外部原值。

### `tests/test_manual_template.py`

验证模板结构：

1. JSON 可解析。
2. 包含 `_rules` 和主要 category。
3. `macro_indicators.industrial` 含 `current_value`、`yoy_month`、`value_type: "yoy_month"`。
4. `bdi` 规则文本包含 `max_age_days`、`trusted_domains`、`value_range`、`unit_keywords`。
5. 所有带数值的示例有 `source_url`，或在 `source`/`note` 中包含 URL。
6. 官方示例项没有默认 `is_estimated: true`。

## 验收标准

1. `bash run_preflight.sh` 在 DNS 或 HTTPS 不通时提前失败，并指出失败 host 或 URL。
2. `run_clean.sh` 和 `run_preflight.sh` 使用同一个 runtime helper；空 `.venv` 不再被误认为有效环境。
3. `file run_clean.sh` 不再显示 `CRLF line terminators`。
4. `.env.example` 不包含真实 token，且 optional `EXA_API_KEY` 与文档一致。
5. `data/runs/templates/manual_template.json` 可作为 Stage2.5 manual JSON 起点，且不会误导用户把官方手工值标成估算。
6. `AGENTS.md` 和 `CLAUDE.md` 能让操作者在不读源码的情况下理解 runtime、DNS hard fail、`industrial`、`is_estimated`、BDI 二级约束。
7. 聚焦测试通过：

```bash
bash run_clean.sh python -m pytest tests/test_runtime_env.py tests/test_run_clean.py tests/test_run_preflight.py tests/test_manual_template.py -q
```

## 风险与处理

`api.tavily.com/` 或 `api.deepseek.com/` 对 `HEAD` 或根路径可能返回 401、404、405。preflight 不要求 2xx，只要 TLS 握手和 HTTP 响应成功即可视为基础连通。实现使用 HTTP code 判断，把 `000` 作为失败，其余 code 作为网络可达。

部分环境没有 `getent` 或 `curl`。设计要求两者都有 Python fallback，保证 Windows/Git-Bash/WSL 环境可用。由于当前本机可能没有 `python` 命令，fallback 必须通过 runtime helper 的 `DATASOURCE_PYTHON` 调用，不直接写死 `python`。

模板中的 `_rules` 字段可能被误复制到最终 manual JSON。Stage2.5 必须忽略未知顶层字段；`tests/test_manual_template.py` 需要覆盖这一点，避免模板说明字段导致注入失败。
