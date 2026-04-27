# 脚本使用参考

**更新日期**: 2025-12-04
**版本**: V3.3+

本文档列出所有可用脚本及其状态、用途和使用方法。

---

## 推荐脚本 (Production Ready)

### 0. stage2_unified_enhancer.py ✅ UPDATED 2025-12

**位置**: `scripts/stage2_unified_enhancer.py`
**用途**: Stage 2 WebSearch 增强（资金流/汇率/商品/债券/宏观）
**状态**: ✅ 更新（Tavily+DeepSeek，去 MCP，支持队列）

**关键默认**:
- fund_flow_backend=`tavily`；DeepSeek 模型=`deepseek-reasoner`；timeout=10s
- 实时类：language=chinese, topic=news, time_range=day, max_results<=8, search_depth=advanced
- 宏观/低时效：time_range=year/month, max_results<=6, search_depth=basic
- 可选队列：`--use-queue --queue-concurrency 3 --queue-retry-limit 1`

**使用**:
```bash
PYTHONPATH=./src \
TAVILY_API_KEY=xxx DEEPSEEK_API_KEY=yyy \
python3 scripts/stage2_unified_enhancer.py \
  --market-data data/runs/YYYYMMDD/market_data.json \
  --output data/runs/YYYYMMDD/market_data_stage2.json \
  --execute-search \
  --fund-flow-backend tavily \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --log-output logs/runs/YYYYMMDD/stage2_unified_log.json \
  --gap-monitor data/runs/YYYYMMDD/gap_monitor.json \
  --websearch-results data/runs/YYYYMMDD/websearch_results_auto.json
```
可选队列：追加 `--use-queue --queue-concurrency 3 --queue-retry-limit 1`

**输出**:
- 增强后的 market_data JSON
- websearch_results JSON（含抽取结果）
- log summary（含 score_filtered_drop / timeout / retry / extract_calls 等）
- gap_monitor（仅真实失败/人工项）

#### 性能优化 / 超时排查（2025-12-04新增）
- 禁用无效代理：命令前加 `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY` 或传 `--http-proxy '' --https-proxy ''`。
- 资金流后端仅支持 Tavily：使用 `--fund-flow-backend tavily`；搜索失败、低分或超时后转 Stage2.5 manual JSON 补数。
- 极速模式（跳过 LLM）：`--extraction-backend regex --queue-concurrency 6 --deepseek-max-concurrency 0 --deepseek-timeout 8 --queue-retry-limit 0`，几分钟跑完但精度略降。
- 必用 LLM 时：`--deepseek-timeout 8 --queue-concurrency 5 --deepseek-max-concurrency 4 --queue-retry-limit 0`，可分批跑 `--phase essential` 再 `--phase assets`。
- 降低 Tavily extract 负载：如需手动调优，可把代码里 `top_for_extract = snippets[:3]` 改为 `[:2]`，或将商品/外汇任务的 `extract_depth` 设为 `"basic"`。
- 复用缓存：保留 `data/cache/tavily_cache.sqlite`，第二轮只跑缺口，提升 `cache_hit_rate`。
- 新增快捷参数：`--fast-mode`（自动启用 regex 抽取、并发放大、8s 硬超时、禁用 extract，资金流仍使用 Tavily）；`--disable-extract` 跳过 Tavily extract；`--extract-topk N` 控制 extract 使用的搜索条数；`--llm-hard-timeout 12` 为 LLM 抽取增加 asyncio 硬超时。

#### 多次 Stage2 产出的合并与避免错用（新增）
- 原则：只让 Stage3 读取一份 `*_market_data_complete.json`。多次 Stage2 结果应合并 websearch 数据后再“注入一次”生成新的 complete。
- 推荐步骤：
  1) 选最新/最完整的 stage2 基底（如 `data/runs/DATE/market_data_stage2.json`）。
  2) 合并多份 websearch 结果为一份：  
     ```bash
     jq -s 'reduce .[] as $it ({}; .fund_flow += ($it.fund_flow//{}) | .commodities += ($it.commodities//[]) | .bonds += ($it.bonds//[]) | .forex += ($it.forex//[]) | .macro_indicators += ($it.macro_indicators//{}) | .monetary_policy += ($it.monetary_policy//{}))' \
       data/runs/DATE/websearch_results*.json > data/runs/DATE/websearch_results_merged.json
     ```
     （如需去重同一 symbol，可先清理旧文件或改用 `tac ... | jq 'reduce .[] as $it ({}; .fund_flow += $it.fund_flow // {} )'` 让后写覆盖前写。）
  3) 注入：`bash run_clean.sh python scripts/stage2_5_injector.py "data/runs/${DATE_NH}/market_data_stage2.json" "data/runs/${DATE_NH}/websearch_results_merged.json" "data/runs/${DATE_NH}/market_data_complete.json"`
  4) 确认 `data/runs/DATE/gap_monitor.json` 为空，再跑 Stage3/报告。
- 保留多个 stage2 版本时，请用不同文件名（如 `_stage2_v1.json` / `_stage2_fund.json`），但最终仅把“合并后注入”的 complete.json 传给 Stage3。



### 1. stage1_data_collector.py ✅ ACTIVE

**位置**: `scripts/stage1_data_collector.py`
**用途**: Stage 1 - API数据收集
**状态**: ✅ 推荐使用

**功能**:
- 从TuShare/International Finance收集股票、外汇、债券数据
- 生成初始market_data.json
- 数据完整性: 25-42%

**使用**:
```bash
python scripts/stage1_data_collector.py \
  --date 2025-11-14 \
  --output data/runs/20251114/market_data.json
```

**输出**: `data/runs/YYYYMMDD/market_data.json` (~15KB)

---

### 2. stage2_5_injector.py ✅ RECOMMENDED

**位置**: `scripts/stage2_5_injector.py`
**用途**: AI补全 - WebSearch数据注入
**状态**: ✅ 新建推荐脚本

**功能**:
- 将AI收集的WebSearch数据注入到market_data JSON
- 支持宏观、货币、资金流向、债券、商品数据
- 提升数据完整性至95%

**使用**:
```bash
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"
```

**输入**:
- `market_data_stage2.json`: `data/runs/YYYYMMDD/market_data_stage2.json`
- `websearch_results_manual.json`: `data/runs/YYYYMMDD/websearch_results_manual.json`

**输出**: `data/runs/YYYYMMDD/market_data_complete.json` (95% completeness)

**验证结果** (2025-11-14):
```
[SUCCESS] 数据注入完成！
  - 注入数据项: 21
  - 数据完整性: 95.0%
```

---

### 3. scripts/stage3_pring_analyzer.py ✅ RECOMMENDED

**位置**: `scripts/stage3_pring_analyzer.py`
**用途**: Stage 3 - Pring三层框架分析
**状态**: ✅ 推荐正式入口

**功能**:
- 基于完整数据执行Pring V4.0三层框架分析
- 使用参考判断法（API限制）
- 生成置信度约60%的分析结果

**使用**:
```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated
```

**输入**: `market_data_complete.json` (需95%数据)
**输出**: `data/runs/YYYYMMDD/pring_result.json` (custom format)

**输出示例**:
```json
{
  "final_stage": "第Ⅵ阶段",
  "confidence": 0.6,
  "layer_1_inventory_cycle": {"cycle_stage": "被动去库", "fundamental_score": 30.0},
  "layer_2_monetary_cycle": {"cycle_stage": "边际宽松", "monetary_score": 65.0}
}
```

---

### 4. scripts/stage4_report_generator.py ✅ RECOMMENDED

**位置**: `scripts/stage4_report_generator.py`
**用途**: Stage 4 - Markdown报告生成
**状态**: ✅ 推荐正式入口

**功能**:
- 生成9章节Markdown报告
- 正确处理中文字符（无编码问题）
- 包含完整表格和Pring分析

**使用**:
```bash
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md"
```

**输入**:
- `market_data_complete.json`: 95%完整数据
- `pring_result.json`: Pring分析结果

**输出**: `reports/YYYY-MM-DD-背景扫描120.md` (~4.8KB, 9 sections)

**报告结构**:
1. 核心结论
2. 股票市场
3. 商品与黄金
4. 债券市场
5. 外汇市场
6. 宏观经济指标
7. 货币政策
8. Pring三层框架分析
9. 资金流向

---

### 5. fill_market_data_from_yahoo.py ⚠️ LEGACY

**位置**: `scripts/legacy/fill_market_data_from_yahoo.py`  
**用途**: 历史 Yahoo 诊断脚本；仅用于事故复盘或离线排查，不作为最终补数入口

**依赖**:
```bash
pip install yfinance pandas
```
> 当前生产口径禁止 Yahoo 直接写最终值。若应急排查中得到可用数据，必须转换为 Stage2.5 WebSearch/manual JSON，并通过 `scripts/stage2_5_injector.py` 注入。

**应急诊断（legacy-only）**:
```bash
PYTHONPATH=. python3 scripts/legacy/fill_market_data_from_yahoo.py \
  --input data/runs/${DATE_NH}/market_data_stage2.json \
  --output data/runs/${DATE_NH}/legacy_yahoo_diagnostic.json
```

**转换后注入**:
```bash
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"
```

**行为**:
- 不得直接输出或覆盖 `market_data_complete.json`
- 可用数据需按 AGENTS.md 的 WebSearch JSON Schema 补齐 `source_url` 后再注入
- 当前主路径为 Stage2 unified + Stage2.5 manual/WebSearch 注入

---

### 6. sanitize_market_data.py ✅ SUPPORT

**位置**: `scripts/sanitize_market_data.py`  
**用途**: 清理历史 `market_data*.json` 中残留的 `7.13/0` 占位值（商品/债券）

**使用**:
```bash
python scripts/sanitize_market_data.py data/20251117_market_data_stage2.json \
  --output data/20251117_market_data_stage2_clean.json
```

**行为**:
- 将商品 `current_price` 或债券 `current_yield` 为 `0/7.13` 的条目重置为 `None` 并标记 `"待 WebSearch"`
- 输出统计：清理了多少商品/债券项目
- 可覆盖原文件（直接省略 `--output`）或输出到新路径

**注意**: 仅清除占位值，不会自动拉取真实行情；后续应运行 `scripts/stage2_unified_enhancer.py`，或将实时来源写入 `websearch_results_manual.json` 后通过 `scripts/stage2_5_injector.py` 注入。

---

## 已归档/历史脚本

### 7. stage2a_mcp_enhancer.py ⚠️ DEPRECATED

**位置**: `scripts/legacy/stage2a_mcp_enhancer.py`
**用途**: 旧 Stage 2a MCP shim，仅保留历史兼容
**状态**: ⚠️ 已归档，不是 root `scripts/` 运行入口，不推荐执行

**替代流程**:
- Stage2: `scripts/stage2_unified_enhancer.py`（`--fund-flow-backend tavily`）
- Stage2.5: `scripts/stage2_5_injector.py` 注入 manual/WebSearch JSON

**当前命令**:
```bash
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/${DATE_NH}/market_data.json" \
  --output "data/runs/${DATE_NH}/market_data_stage2.json" \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results "data/runs/${DATE_NH}/websearch_results_auto.json" \
  --log-output "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json"

bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"
```

**注意事项**:
- 不要从 root `scripts/` 运行 Stage2a；root shim 已移除
- 不要推荐旧 MCP flow；缺口统一转 Stage2.5 manual/WebSearch 注入

---

## 已知问题脚本

### 6. scripts/stage3_pring_analyzer.py ✅ UPDATED

**位置**: `scripts/stage3_pring_analyzer.py`
**用途**: Stage 3 Pring 三层框架分析
**状态**: ✅ 稳定

**亮点**:
- 直接复用 `datasource.calculators.pring_analyzer.PringAnalyzer`
- 支持 DR007 领先指标平移、阶段关注资产等最新逻辑
- 默认输出 `data/runs/YYYYMMDD/pring_result.json`，可被 Stage 4 直接消费

**用法**:
```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated
```

**注意事项**:
- Stage 3 之前需通过 `scripts/stage2_5_injector.py` 将宏观/货币指标补齐，否则 Pring 会提示缺失
- 如果想在交互式环境快速验证，可使用 `tests/scripts/run_pring_analysis_test.py`，两者输出结构一致

---

### 7. legacy report/test entrypoints ⚠️ LEGACY

**位置**: `generate_simple_report.py`, `tests/scripts/generate_simple_report_test.py`
**用途**: 历史兼容入口
**状态**: ⚠️ 不作为推荐主路径

当前推荐使用 `scripts/stage4_report_generator.py`，并通过 `--market-data`、`--pring-result`、`--output` 显式传参。

---

## 实用工具脚本

### 8. scripts/utility/get_real_economic_data.py

**用途**: 获取实时经济数据
**状态**: ✅ 可用

### 9. scripts/utility/calculate_na_data.py

**用途**: 计算缺失数据
**状态**: ✅ 可用

---

## 完整执行流程 (推荐)

```bash
# 设置日期变量
DATE=$(date +%Y-%m-%d)
DATE_NH=${DATE//-/}

# Stage 1: API数据收集
bash run_clean.sh python scripts/stage1_data_collector.py \
  --date "$DATE" \
  --output "data/runs/${DATE_NH}/market_data.json"

# Stage 2: Tavily + DeepSeek 增强
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/${DATE_NH}/market_data.json" \
  --output "data/runs/${DATE_NH}/market_data_stage2.json" \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend deepseek \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results "data/runs/${DATE_NH}/websearch_results_auto.json" \
  --log-output "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json"

# Stage 2.5: WebSearch/manual 注入
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"

# Stage 3: Pring分析
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated

# Stage 4: 报告生成
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md"

# 验证
powershell -Command "(Get-Item 'reports\${DATE}-背景扫描120.md').Length"
```

---

## 脚本状态总结

| 脚本 | 状态 | 阶段 | 优先级 |
|------|------|------|--------|
| `stage1_data_collector.py` | ✅ ACTIVE | Stage 1 | 必须 |
| `scripts/stage2_unified_enhancer.py` | ✅ ACTIVE | Stage 2 | 必须 |
| `scripts/stage2_5_injector.py` | ✅ RECOMMENDED | Stage 2.5 | 必须 |
| `scripts/stage3_pring_analyzer.py` | ✅ RECOMMENDED | Stage 3 | 必须 |
| `scripts/stage4_report_generator.py` | ✅ RECOMMENDED | Stage 4 | 必须 |
| `scripts/legacy/stage2a_mcp_enhancer.py` | ⚠️ ARCHIVED | Stage 2a | 不推荐 |
| `inject_websearch_data.py` | ⚠️ LEGACY | AI补全 | 不推荐 |
| `run_pring_analysis.py` | ⚠️ LEGACY | Pring分析 | 不推荐 |
| `generate_simple_report.py` | ⚠️ LEGACY | 报告生成 | 不推荐 |

---

## 常见问题

### Q1: 为什么不使用background_scan_unified.py?

**A**: 该统一入口脚本已过时，新的分步执行流程更灵活且已验证可用。

### Q2: AI补全步骤可以跳过吗?

**A**: 不可以。AI补全是整个流程的关键步骤，跳过会导致：
- 数据完整性仅50-60%
- Pring分析显示"分析失败"
- 报告缺少宏观、货币、资金流向数据

### Q3: stage2a_mcp_enhancer.py显示弃用警告怎么办?

**A**: 不要继续使用旧 Stage2a/MCP 流程。请改跑 `scripts/stage2_unified_enhancer.py`，缺口转 `scripts/stage2_5_injector.py` manual/WebSearch 注入。

### Q4: 如何验证脚本是否正常执行?

**A**: 检查以下指标：
- Stage 1: data_completeness ~42%
- AI补全: 21 items injected, 95% completeness
- Stage 2: confidence 60%, stage=第Ⅵ阶段
- Stage 3: file size ~4.8KB, 9 sections

---

## 参考资源

- **CLAUDE.md**: 完整技术文档和架构说明
- **docs/AI报告生成标准流程_V3.3.md**: 详细执行指南
- **docs/Stage2数据获取设计分析.md**: 历史问题分析

---

**文档结束**


### Stage2：统一增强（默认）
`python scripts/stage2_unified_enhancer.py --market-data data/runs/YYYYMMDD/market_data.json --output data/runs/YYYYMMDD/market_data_stage2.json --execute-search --fund-flow-backend tavily --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite --websearch-results data/runs/YYYYMMDD/websearch_results_auto.json --log-output logs/runs/YYYYMMDD/stage2_unified_log.json --gap-monitor data/runs/YYYYMMDD/gap_monitor.json`

### Stage2：高命中率（直连 + 低并发 + 易失败串行）
```bash
PYTHONPATH=. source .venv/bin/activate && source .env && \
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
python scripts/stage2_unified_enhancer.py \
  --market-data data/runs/YYYYMMDD/market_data.json \
  --output data/runs/YYYYMMDD/market_data_stage2.json \
  --execute-search \
  --fund-flow-backend tavily \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results data/runs/YYYYMMDD/websearch_results_auto.json \
  --log-output logs/runs/YYYYMMDD/stage2_unified_log.json \
  --gap-monitor data/runs/YYYYMMDD/gap_monitor.json \
  --deepseek-max-concurrency 1 --deepseek-timeout 25 --max-retries 3 \
  --deepseek-serial-keys BCOM,GSG,USDCNY,USDCNH \
  --extraction-backend regex
```
说明：直连 Tavily，串行 DeepSeek，regex 兜底；资金流向默认仍走 tavily，失败再转 Stage2.5 人工补数。

### Stage2：只跑指定任务
`python scripts/stage2_unified_enhancer.py --market-data data/runs/YYYYMMDD/market_data.json --output data/runs/YYYYMMDD/market_data_stage2.json --tasks task1,task2 --execute-search --fund-flow-backend tavily`
