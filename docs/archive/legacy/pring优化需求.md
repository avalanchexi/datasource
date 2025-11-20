# Pring 框架优化需求说明（2025-11-18）

## 1. 目标
- 使项目内的 Pring 三层分析与资产配置结果与行业最佳实践保持一致（参见东方财富、中信建投等公开资料）。
- 替换残留的占位/估算数据，确保 Stage3/Stage4 只消化真实可追溯数据源。
- 补全报告中缺失的关键指标，形成“指标收集 → 三层分析 → 资产建议”闭环。

## 2. 数据指标覆盖差距
| 指标类别 | 参考资料要求 | 当前实现 | 缺口/行动 |
| --- | --- | --- | --- |
| 货币先行：M1、DR007、M2 | M1/M2 剪刀差、DR007 领先信号 | DR007、M2 已有；**M1 缺失** | Stage1 `monetary_policy_config` 新增 M1，TuShare `cn_m` 同时提供 M0/M1/M2（doc_id=242） |
| 信用：TSF、社融增速 | TSF/Yoy | 已有 | 无 |
| 增长同步：GDP、工业增加值、制造业销售 | 工业增加值有；**GDP/销售缺失** | Stage1 `macro_indicator_config` 增加 GDP（TuShare `cn_gdp` doc_id=270）、工业企业营收/PMI 新订单 |
| 价格/通胀：PPI、CPI | 需实时数据 | 目前走 WebSearch | Stage1 可调用 TuShare `cn_ppi`、`cn_cpi`，基础数据无需 WebSearch |
| 领先指标：PMI 新订单、BCI/OECD | **PMI分项缺失** | `cn_pmi` 可直接获取新订单/生产等分项；BCI/OECD CLI 仍需外部源 |
| 资产行情：债券/商品 | 文章要求实时行情 | 结构存在仍含 7.13 | 使用 `fill_market_data_from_yahoo.py` 或 MCP WebFetch 覆盖；禁止手工常数 |

### 2.1 现有结构差异
- **Stage1 采集**：`stock_indices`、`bonds`、`commodities` 结构完备，但当 TuShare/MCP 不可用时只写 `0.0`/`None` 并记录 `missing_items`；DR007/M2/TSF 可自动获取，M1/GDP/PMI 新订单不存在。  
- **Stage2/MCP Enhancer**：`scripts/mcp_data_enhancer.py` 仅在获取成功后覆盖真实值；失败时记录 WebSearch 提示。由于早期手工补数曾写入 7.13，占位值会在 `market_data_stage2.json` 中保留，必须通过 WebSearch 注入或新脚本覆盖。  
- **Stage3 PringAnalyzer**：库存/货币层得分主要依赖 PPI、PMI、工业增加值、CPI、TSF、M2、RRR、逆回购，缺少文章强调的 M1、PMI 新订单、GDP；DR007 领先修正已启用。  
- **Stage4 报告**：`generate_simple_report.py` 会直接渲染传入 JSON，不再自造占位数据；一旦上游仍是 7.13/N/A，报告中就会照原样显示，容易误导读者。  
- **工具/脚本**：`scripts/fill_market_data_from_yahoo.py` 可用来覆盖 Stage2 中的商品/债券伪值，但依赖 `yfinance`，需在可联网环境安装后运行。

## 3. 代码层面需调整
1. **Stage1 数据采集**
   - `scripts/stage1_data_collector.py`：新增 M1（TuShare `cn_m`）、GDP (`cn_gdp`)、PMI 新订单/生产分项 (`cn_pmi`) 的采集逻辑，并写入 `MarketDataContract`。
   - 更新 `websearch_results_*.json` 模板与 `inject_websearch_data_test.py`，确保上述字段可通过 WebSearch 注入。

2. **Stage2 / 行情补齐**
   - 优先使用 MCP WebFetch 或 `scripts/fill_market_data_from_yahoo.py` 替换商品/债券 7.13 僵值；无法联网时也要记录缺口，禁止写死常数。
   - 日志中明确缺失字段，提醒 WebSearch/手工补录。

3. **Stage3 PringAnalyzer 重构**
   - `calculate_inventory_cycle_score()`：纳入 PMI 新订单/生产、GDP/工业营收等指标，更新 `score_details`。
   - `calculate_monetary_cycle_score()`：加入 M1 或 M1/M2 剪刀差，与 RRR/逆回购/TSF/M2/DR007 一起组成 100 分评分。
   - `apply_monetary_correction()`：根据 M1/M2 + DR007 信号调整阶段；`leading_indicator` 输出 DR007 与 M1/M2 双信号，并记录在结果 JSON。
   - **三层框架说明**：Stage3 统一采用「库存周期（Layer 1）→货币周期（Layer 2）→六阶段识别（Layer 3）」的链式结构，旧有“三阶段”粗略判定方法已废弃，后续所有报告/脚本仅维护该三层方案。
   - **Pipeline Guard**：Stage3 CLI (`scripts/stage3_pring_analyzer.py`) 必须检测 `metadata.ai_websearch_enhanced`，若缺失或为 False 立即报错，提示先运行 Stage2.5 WebSearch 注入再继续。

4. **Stage4 报告**
   - `generate_simple_report.py` 中的“宏观指标/货币政策”表格自动遍历 JSON，只要 Stage1/2 写入新字段便会展示；缺值时以 `N/A（待 WebSearch）` 提示。
   - 第八章引用 `pring_result` 的文字说明，需在 Stage3 输出中加入对新指标的描述，以便报告呈现。

5. **依赖替换 / 数据抓取**
   - 已新增 `scripts/fill_market_data_from_yahoo.py`，用于替换 7.13 等旧占位；依赖 `yfinance`/`pandas`。在正式环境安装依赖或提供离线 CSV 后运行。
   - 运行 `scripts/fill_market_data_from_yahoo.py` 前，需执行 `pip install yfinance pandas` 并确保可访问 Yahoo Finance；如被限流需回退至 MCP WebFetch/WebSearch。
   - 若无法联网，可改用 MCP WebFetch（Claude 环境）或 WebSearch 注入真实行情。
   - 商品/债券等实时行情必须通过 MCP WebFetch/WebSearch 或 Yahoo fallback 获取，**禁止**回退 AKShare/手工常数；脚本需在日志中记录任何手工补录提示。
   - 历史 `market_data*.json` 若仍残留 7.13/0 占位，可运行 `scripts/sanitize_market_data.py data/xxx_market_data.json --output ...` 先重置为 `null`，再执行 Stage2 回填。
   - Stage1 若成功从 TuShare 获取宏观/货币数据，必须立刻覆盖占位字段并记录 `source='TuShare ...'`；仅当 TuShare 返回空/报错时，才在 `missing_items` 中标记“需 WebSearch”，以便 Stage2.5 明确补数范围。
   - Stage2.5 WebSearch（`inject_websearch_data_test.py`）是硬性步骤：只有将 14 个指标写入 `market_data_complete.json` 后，Stage3/Stage4 才算“已补数”；跳过该步骤的产物视为不合格。

6. **配置约束**
   - `.env`、`indices_config.py` 等配置文件严禁保留 7.13 等硬编码占位，所有参数须由配置/脚本动态控制；变更配置前需在文档记录来源。

## 4. 验收标准
- Stage1 → Stage2 产物中不再出现 `7.13`、`占位符` 字样，缺失项统一为 `null`/`N/A`。
- Stage3 输出的 `layer_1/layer_2` 分析包含 M1、PMI 新订单等补充指标描述。
- Stage4 报告的“八、Pring三层框架分析”引用真实数据（带来源，DR007 领先信号生效）。
- SCRIPTS/CLaude/文档中不再标注 Stage3/Stage4 “编码问题”或“占位符”。

若需进一步拆分任务，请在此文档基础上创建 issue 或 TODO。***

## 5. 2025-11-19 报告回溯新增需求

> 来源：2025-11-19 报告《20251119背景扫描120.md》与同批 JSON 产物（`data/20251119_market_data*.json`）的复盘。所有问题均在 CLAUDE 流程中复现，需在 2025-11-21 前完成修复。

1. **Stage1 TuShare 采集必须确保 CPI/工业增加值/PMI 分项写入成功**
   - 现状：`cn_cpi`、`cn_ppi`、`cn_pmi` 已配置，但 `data/20251119_market_data.json` 中对应字段仍为 `null`/`待TuShare获取`，导致报告第六节出现多条 `N/A（待 WebSearch）`，库存层诊断提示“PMI新订单缺失”。
   - 需求：回溯 `scripts/stage1_data_collector.py`、环境变量与调度脚本，保证 TuShare 请求异常会自动重试并在失败后记录具名错误；验证成功后在 `metadata.missing_items` 中移除已补齐字段。

2. **Stage2 不得覆盖 Stage1 已有行情，且需对商品/债券缺口执行强制补齐**
   - 现状：Stage1 提供的 GSG ETF 实时报价在 Stage2/Stage2.5 被写成 “请求失败” 并清空，`data_completeness` 也从 0.43 降到 0.40，`stage2_gap_monitor` 仍报 commodities=6、bonds=3。
   - 需求：`stage2a_mcp_enhancer.py` 与 `inject_websearch_data_test.py` 在落地数据时必须采用 “成功才覆盖、失败保留” 策略，并在商品/债券任一字段仍为 `None` 时阻断流水线，提示先补齐 MCP WebSearch 结果或运行 `fill_market_data_from_yahoo.py`。

3. **资金流向 WebSearch 映射需覆盖 ETF 与融资融券**
   - 现状：`data/websearch_results_20251119.json` 已抓到 `etf_flow` 与 `margin_trading`，但 `market_data_complete.json` 的 `fund_flow.etf/margin` 仍是空值，报告第九章继续显示 N/A。
   - 需求：更新 `inject_websearch_data_test.py` 的字段映射，确保 `recent_week`/`balance` 转换为 `recent_5d`、`total_120d` 或记录“异常零值-需核查”，并同步写入 `source` 与 `note`。

4. **货币政策字段需要去重合并，避免报告双列冲突**
   - 现状：WebSearch 注入新增了 `reverse_repo_7d`、`mlf_rate`、`tsf_growth` 等 key，原有 `reverse_repo`、`mlf` 仍保留空值，导致报告第七节同一指标出现 “N/A” 与真实数值两行。
   - 需求：在注入阶段直接覆盖原字段或在生成报告前执行字段合并，确保 `monetary_policy` 下每个政策工具只有一个标准化 key。

5. **补数后需同步刷新 metadata 标记**
   - 现状：即便商品与北向/南向数据已写入，`metadata.missing_items` 与 `stage2_notes` 仍把它们视为缺失，影响自动验收脚本判断。
   - 需求：补数脚本在成功落地数据与来源后，必须移除相应的 missing item，并更新 `stage2_gap_monitor` 指标；若 `ai_websearch_enhanced=True`，则 `data_completeness` 不得倒退。

## 6. TuShare 指标覆盖扩展（Doc #2 & WebClient）

| Stage1 指标 | TuShare 接口 / 文档 | 扩展动作 | 备注 |
| --- | --- | --- | --- |
| CPI | `cn_cpi`（doc_id=228）覆盖全国/城市/农村 CPI 当月值及同比/环比。citeturn1search0 | Stage1 直接调用 `pro.cn_cpi` 写入 `macro_indicators['cpi']`；失败时记录具体错误并在 `missing_items` 注明。 | 600 积分即可用，填完可删掉“待 WebSearch”占位。 |
| PMI 总值+分项 | `cn_pmi`（doc_id=325）一次返回制造业、非制造业及生产/新订单等分项。citeturn1search3 | 将 `pmi010400` 映射到“PMI生产”，`pmi010500` 映射到“PMI新订单”，同步记录来源，Pring Layer1 用于库存评分。 | 需要 2000 积分，token 权限不足时需提示。 |
| PPI | `cn_ppi`（doc_id=245）含总指数与生产/生活资料分项，同比/环比。citeturn1search4 | 目前只拿总值，接下来扩展 `ppi_yoy`, `ppi_cg_yoy` 等字段，供库存周期差值计算。 | 与 CPI 一样均可用 TuShare 覆盖。 |
| 融资融券（资金流） | `margin`（doc_id=58）提供融资余额、融券余量等。citeturn3search3 | Stage1 用该接口计算近 5/120 日余额变化，直接填 `fund_flow['margin']`，降低 WebSearch 负担。 | 北向/南向/ETF 仍需 MCP；两融可全自动。 |
| 市场成交/ETF 热度 | `daily_info`（doc_id=215）返回沪深当日成交额、涨跌家数。citeturn3search4 | 若暂无 ETF 专用 API，可用此接口估算 ETF 申赎净额，并在报告备注“基于成交额估算”。 | 后续若发现 `fund_share` 等接口再替换。 |
| WebClient 模板 | WebClient（需浏览器登录）可生成接口调用脚本。citeturn2search7 | 在可联网浏览器中生成 `pro.cn_pmi`, `pro.cn_cpi` 等模板，整理到 `docs/tushare_webclient_snippets.md`，供离线 CLI 粘贴使用。 | CLI 无 GUI 时也能套用模板。 |

执行要求：
1. `scripts/stage1_data_collector.py` 在 `macro_indicator_config` / `monetary_policy_config` 中补齐上述 TuShare 字段，并在日志里输出 doc_id 以便排障。
2. `.env.example` 增加 “Stage1 需 ≥2000 TuShare 积分，否则自动降级 WebSearch” 的注释，防止误用低权限 Token。
3. 新增 UT：模拟 `cn_cpi/cn_pmi/margin` 响应，断言 `metadata.missing_items` 被清空；CI 将此用例列为必须通过。
