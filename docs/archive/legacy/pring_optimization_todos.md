# Pring 优化 TODO 追踪（2025-11-18）

> 依据 `docs/pring优化需求.md`，用于标记三层优化执行进度。

## 全局目标
- [ ] Pring 三层分析与资产配置结果对齐行业最佳实践（东方财富/中信建投等公开资料）。
- [ ] Stage3/Stage4 仅使用真实可追溯数据，替换所有占位或估算数值（含 `7.13`）。
- [ ] 报告形成“指标收集 → 三层分析 → 资产建议”闭环，缺失项明确提示。

## Stage1 数据采集
- [x] `monetary_policy_config` 接入 TuShare `cn_m`（doc_id=242），补齐 M0/M1/M2，写入 `MarketDataContract`。
- [x] `macro_indicator_config` 增加 GDP（TuShare `cn_gdp` doc_id=270）及工业企业营收/制造业销售字段。
- [x] 通过 `cn_pmi` 获取 PMI 新订单/生产等分项，并在 Stage1 产物中暴露。
- [x] CPI/PPI 改为通过 TuShare `cn_cpi`、`cn_ppi` 拉取，避免 WebSearch 占位。
- [x] Stage1 采集失败时记录 `null/N/A` 而非 `0`，并同步到 `missing_items`。
- [x] 更新 `websearch_results_*.json` 模板与 `inject_websearch_data_test.py`，支持新增字段注入与测试。
- [x] 验证 `collect_macro_indicators` / `collect_monetary_policy` 在 TuShare 返回实值时写入 `source='TuShare ...'`，仅失败时标记“需 WebSearch”。（`scripts/stage1_data_collector.py` 现在仅在 TuShare 真失败后才记录缺口）
- [ ] 【Doc#2落地】梳理 `cn_cpi/cn_pmi/cn_ppi` 在 Stage1 的字段映射与重试机制（字段映射已上线，仍需补 UT+错误日志），确认 token 积分不足或字段缺失时输出明确日志，并在 UT 中覆盖。
- [x] 【资金流自动化】将 TuShare `margin` 数据接入 `fund_flow.margin`（近5/120日余额变化），减少 WebSearch 补录工作。
- [x] 【成交/ETF替代】集成 `daily_info` 作为 ETF 资金热度的过渡来源，并在报告第九节注明“基于成交额估算”。
- [x] 【WebClient 模板】整理 `pro.cn_pmi/cn_cpi/margin` 等 WebClient 生成的调用片段，新增 `docs/tushare_webclient_snippets.md`，供离线 CLI 粘贴使用。

## Stage2 行情补齐
- [x] 使用 MCP WebFetch 或 `scripts/fill_market_data_from_yahoo.py` 覆盖 `market_data_stage2.json` 中的 7.13 等旧占位。
- [x] 无法联网时记录缺口提示，禁止写入常数；日志需提示待 WebSearch/手工补录项。
- [x] 运行脚本前准备 `yfinance` 依赖，确保商品/债券行情能自动刷新。
- [x] `fill_market_data_from_yahoo.py` 增加限速/指数回退，失败重试记录写入 Stage2 日志，便于排查 429/网络波动。
- [x] 构建本地 CSV 缓存层（最近 N 日）并在 Stage2 输出中记录“命中缓存/实时拉取”状态，确保报告链路兼容。
- [x] 若 Yahoo 多次失败，自动降级使用 MCP WebFetch 或在 `metadata.stage2_notes` 中提示“需 WebSearch/手工补数”。
- [x] Stage2 输出新增“行情缺口监控”统计：残留 `None/0/7.13` 的品类数量，供报警 & 验收。
- [x] 在 Pipeline/脚本中增加检测：若未运行 WebSearch 注入(`ai_websearch_enhanced` 标记缺失)，Stage3/Stage4 提示“需先执行 inject_websearch_data_*”。（`scripts/stage3_pring_analyzer.py` 未检测到标记时直接报错）

## Stage3 PringAnalyzer
- [x] 废弃旧版“三阶段”粗判逻辑，统一沿用“库存→货币→六阶段”三层架构，所有脚本/报告以该流程输出。
- [x] `calculate_inventory_cycle_score()` 加入 PMI 新订单/生产、GDP、工业营收等指标，并在 `score_details` 中输出。
- [x] `calculate_monetary_cycle_score()` 纳入 M1 或 M1/M2 剪刀差，与 RRR/逆回购/TSF/M2/DR007 共同构成 100 分。
- [x] `apply_monetary_correction()` 同步考虑 M1/M2 与 DR007 双信号，`leading_indicator` 输出两者并记录理由。
- [x] Stage3 结果 JSON 中为新增指标生成可直接引用的文字描述，供 Stage4 第八章使用。

## Stage4 报告
- [x] `generate_simple_report.py` 缺值时展示 `N/A（待 WebSearch）`，防止误导。
- [x] 第八章（Pring 三层分析）引用 Stage3 新增指标描述，强调 DR007 + M1/M2 领先信号。
- [x] 报告第八章引入“库存层/货币层”详细文字，自动引用 Stage3 的 `score_details` & leading indicator 说明，旧版简要描述废弃。

## 工具与依赖
- [x] 在文档或脚本帮助中写明运行 `scripts/fill_market_data_from_yahoo.py` 需要 `yfinance/pandas`，并提供安装指引。
- [x] 实时行情统一走 MCP WebFetch/WebSearch；禁止对这类数据使用 AKShare 回退。
- [x] 确认 `.env`、`indices_config.py` 中无硬编码常量，所有行为通过配置管理。

## 验收 Checklist (2025-11-19 验收)

### ❌ Checklist 1: Stage1→Stage2 产物无 `7.13` 或"占位符"
**状态**: 失败

**问题**: 5个数据文件中仍存在 `7.13` 占位值
- `data/20251118_market_data_complete.json`
- `data/20251118_market_data_enhanced.json`
- `data/20251117_market_data_complete.json`
- `data/20251117_market_data_stage2.json`
- `data/20251117_market_data_enhanced.json`

**受影响字段** (共7个):
| 类别 | 字段 | 当前值 |
|------|------|--------|
| 商品 | COMEX黄金 current_price | 7.13 |
| 商品 | WTI原油 current_price | 7.13 |
| 商品 | Brent原油 current_price | 7.13 |
| 商品 | COMEX铜 current_price | 7.13 |
| 商品 | BCOM指数 current_price | 7.13 |
| 债券 | 中国10年期国债 current_yield | 7.13 |
| 债券 | 中国10年期国开债 current_yield | 7.13 |

**修复方案**:
- [ ] 运行 `scripts/fill_market_data_from_yahoo.py` 替换商品/债券 7.13 值
- [ ] 或通过 MCP WebFetch 获取实时行情覆盖

---

### ✅ Checklist 2: Stage3 layer_1/layer_2 包含 M1、PMI新订单、DR007领先修正
**状态**: 通过

**已实现功能**:
- [x] M1增速 (`_score_m1_growth`) - 权重 10分
- [x] M1-M2剪刀差 (`_score_m1_m2_spread`) - 权重 5分
- [x] PMI新订单 (`pmi_new_orders_data`) - 权重 10分
- [x] DR007领先修正 (`_apply_leading_indicator_adjustment`)
- [x] `_evaluate_leading_indicator()` 同时考虑 DR007 + M1/M2 双信号

**代码位置**: `src/datasource/calculators/pring_analyzer.py`

---

### ⚠️ Checklist 3: Stage4 报告第八章引用真实数据并附带来源标注
**状态**: 基本通过（依赖 Checklist 1 收尾）

**通过项**:
- [x] Layer 1/Layer 2 诊断摘要自动引用 `score_details`、`leading_summary`（含 DR007 + M1/M2 信号）
- [x] Pring 第八章展示库存/货币文字与 DR007 领先说明
- [x] 数据来源附录保留 stage2_notes 与实时来源

**剩余阻塞**:
- [ ] 商品/债券仍因 7.13 缺口显示 `N/A（待 WebSearch）`，需 Checklist 1 完成后复检

---

### ✅ Checklist 4: 文档中清除"编码问题/占位符"类说明
**状态**: 通过

**检查结果**:
- [x] CLAUDE.md 中的 "placeholders" 为描述性说明，可接受
- [x] scripts 中的 "占位符" 为代码日志/注释，用于提示需MCP补充，符合设计
- [x] 未发现需要清除的编码问题说明

---

## 验收总结

| Checklist 项 | 状态 | 说明 |
|--------------|------|------|
| 1. 数据无7.13 | ❌ 失败 | 历史 `market_data_stage2` 中商品/债券仍含7个 7.13 占位 |
| 2. Stage3 M1/PMI/DR007 | ✅ 通过 | 代码输出库存/货币层文字，leading summary 生效 |
| 3. Stage4 真实数据来源 | ⚠️ 待复检 | 模板已更新，需待 Checklist 1 清库后确认最终报告 |
| 4. 文档清理 | ✅ 通过 | 无需清理 |

## 待修复项 (按优先级)

### 高优先级
- [ ] 替换商品/债券 7.13 占位值（运行 `fill_market_data_from_yahoo.py` 或 MCP WebFetch）

### 中优先级
- [ ] 运行 Stage4 报告一次（金/债补齐后）验证 `N/A` 均仅出现在真实缺口处

## 2025-11-19 报告补救 TODO

> 依据 2025-11-19 报告复盘（见 `docs/pring优化需求.md` 第 5 节）。

- [ ] **Stage1 TuShare 回归测试**：排查 `cn_cpi`、`cn_ppi`、`cn_pmi` 请求链路（含 token、频控、字段映射），补上失败重试与日志，重新生成 `data/DATE_market_data.json` 验证 CPI/工业增加值/PMI 分项落地且 `missing_items.macro_indicators` 自动清空。
- [ ] **Stage2 覆盖策略修正**：调整 `stage2a_mcp_enhancer.py` / `inject_websearch_data_test.py`，让 MCP/Yahoo 成功值覆盖 Stage1，失败则保留原值并阻断流程；对商品/债券缺值触发硬失败而非“提醒”。
- [ ] **资金流向映射补全**：在 WebSearch 注入脚本中新增 `etf_flow`→`fund_flow.etf`、`margin_trading`→`fund_flow.margin` 的字段转换，确保近 5 日/近 120 日金额与来源写入，并实现异常零值标记。
- [ ] **货币政策字段合并**：为 `reverse_repo`、`mlf`、`tsf` 增加正式的覆盖逻辑，避免同时出现 `_rate`/`_growth` 与旧 key；更新报告渲染前的字段去重校验。
- [ ] **Metadata 自动刷新**：补数脚本在成功写入数据后同步更新 `metadata.missing_items`、`stage2_gap_monitor` 与 `data_completeness`，防止 `ai_websearch_enhanced=True` 却仍提示“待获取”。
