# AI报告生成标准流程 V3.3+

> **注意**: 本文档描述的是已归档的V3.3流程，不是当前执行路径。
> 当前权威流程请以 [../AGENTS.md](../AGENTS.md) / [../README.md](../README.md) 的 Stage1 → Stage2 unified → Stage2.5 → Stage3 → Stage4 为准。

**文档版本**: V3.3+ (归档参考)
**验证日期**: 2025-11-24
**归档日期**: 2025-12-09
**验证状态**: ✅ PASS (100% completeness after Stage2/Stage2.5 补数, 85% confidence)

---

## 概述

本文档描述了已验证的6阶段AI报告生成标准流程，用于生成A股背景扫描120日报告。

### 核心特点

- **6个标准阶段**: 本节为归档流程；当前请使用 Stage1 → Stage2 unified → Stage2.5 → Stage3 → Stage4
- **数据完整性**: 95% (验证结果)
- **执行时间**: 5-6分钟
- **输出质量**: 4.8KB, 9 sections, Markdown格式
- **Pring置信度**: 60% (参考判断法)

---

## 阶段说明

### Stage 1: API数据收集 (30-60秒，交易日感知版)

**脚本**: `scripts/stage1_data_collector.py`

**命令**:
```bash
python scripts/stage1_data_collector.py \
  --date 2025-11-24 \
  --output data/20251124_market_data.json
```

**输出**:
- 文件: `data/YYYYMMDD_market_data.json`
- 大小: ~15KB
- 数据完整性: 25-42%（休市自动回退最近开市日；fx_daily/moneyflow_hsgt 回溯最近5个开市日）

**数据覆盖**:
- ✅ 股票指数 (4/5): 沪深300, 创业板指, 深证成指, 上证指数
- ✅ 外汇 (3/3): USD/CNY, USD/CNH, DXY
- ✅ 债券 (1/3): US10Y
- ⚠️ 商品 (1/6): 仅GSG
- ⚠️ 宏观指标 (0/5): 全部占位符
- ⚠️ 货币政策 (0/5): 全部占位符
- ⚠️ 资金流向 (0/4, 默认tavily): 全部占位符

**验证**:
```bash
python -c "import json; data=json.load(open('data/20251114_market_data.json', encoding='utf-8')); print(f'Completeness: {data[\"metadata\"][\"data_completeness\"]:.1%}')"
```

---

### Stage 2a: MCP Essential增强（已归档，不执行）

**脚本**: `scripts/legacy/stage2a_mcp_enhancer.py` [ARCHIVED，不推荐]

**当前替代命令**:
```bash
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data data/runs/${DATE_NH}/market_data.json \
  --output data/runs/${DATE_NH}/market_data_stage2.json \
  --phase all --execute-search \
  --fund-flow-backend tavily
```

**输出**:
- 旧 Stage2a 不再作为输出来源
- Stage2 unified 输出: `data/runs/${DATE_NH}/market_data_stage2.json`
- 缺口通过 Stage2.5 manual/WebSearch JSON 注入到 `market_data_complete.json`

**增强目标**:
- 债券收益率 (2): CN10Y, CN10Y_CDB
- 商品价格 (5): COMEX黄金, WTI, Brent, COMEX铜, BCOM

**注意事项**:
- ⚠️ 不要使用旧 MCP flow
- ✅ 当前主路径是 Stage2 unified + Stage2.5 注入

---

### AI补全: WebSearch数据补全 + 注入 (2-3分钟) **CRITICAL**

这是整个流程中最关键的步骤，决定了最终报告的数据完整性。

#### Step 1: 执行WebSearch查询 (14个)

使用WebSearch工具并行执行以下查询：

**宏观指标 (5个)**:
1. PPI: `中国PPI 工业生产者出厂价格指数 2025年10月 国家统计局 最新数据`
2. PMI: `中国PMI 制造业采购经理指数 2025年10月 国家统计局 最新数据`
3. Industrial: `中国工业增加值 2025年10月 同比增长 国家统计局`
4. BDI: `Baltic Dry Index BDI 2025年11月14日 最新`
5. CPI: `中国CPI 居民消费价格指数 2025年10月 国家统计局`

**货币政策 (5个)**:
6. RRR: `中国人民银行 存款准备金率 2025年最新 调整`
7. Reverse Repo: `中国人民银行 公开市场业务 7天逆回购利率 2025年11月`
8. MLF: `中国人民银行 MLF 中期借贷便利 1年期利率 2025年最新`
9. TSF: `中国社会融资规模增速 2025年10月 央行 最新数据`
10. M2: `中国M2货币供应量 同比增速 2025年10月 央行`

**资金流向 (4个, 默认tavily)**:
11. Northbound: `北向资金 2025年11月14日 净流入 近5日 累计 东方财富`
12. Southbound: `南向资金 2025年11月14日 净流入 近5日 东方财富 同花顺`
13. ETF: `A股ETF资金流向 2025年11月 近5日 净流入 东方财富`
14. Margin: `融资融券余额 2025年11月最新 近5日 变化 上交所 深交所`

#### Step 2: 创建WebSearch结果JSON

基于WebSearch查询结果，创建 `data/websearch_results_YYYYMMDD.json`:

```json
{
  "collection_date": "2025-11-14",
  "collection_time": "2025-11-14T10:45:00",
  "data_source": "Stage2.5 manual/WebSearch",
  "macro_indicators": {
    "ppi": {
      "indicator_name": "PPI",
      "current_value": -2.1,
      "previous_value": -2.3,
      "change_rate": 0.2,
      "unit": "%",
      "date": "2025-10-31",
      "source": "国家统计局",
      "is_estimated": false,
      "note": "2025年10月环比上涨0.1%，为年内首次上涨；同比下降2.1%，降幅比上月收窄0.2个百分点"
    },
    ...
  },
  "monetary_policy": { ... },
  "fund_flow": { ... },
  "bonds": { ... },  // 可选，Stage2 unified 仍有缺口时补
  "commodities": [ ... ]  // 可选，Stage2 unified 仍有缺口时补
}
```

**完整模板参考**: `data/websearch_results_20251114_test.json`

#### Step 3: 运行数据注入脚本

```bash
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"
```

**输出**:
```
[STEP 1] 注入宏观指标数据...
  [OK] PPI: -2.1%
  [OK] PMI: 49.0点
  [OK] 工业增加值: 6.5%
  [OK] BDI指数: 2104.0点
  [OK] CPI: 0.2%

[STEP 2] 注入货币政策数据...
  [OK] 存款准备金率: 6.2%
  [OK] 7天逆回购利率: 1.4%
  [OK] MLF利率: 2.0%
  [OK] TSF社融增速: 8.5%
  [OK] M2增速: 8.2%

[STEP 3] 注入资金流向数据（默认 tavily，失败可人工）...
  [OK] northbound: recent_5d=约140亿元, total_120d=约1800亿元
  [OK] southbound: recent_5d=约55亿港元净流出, total_120d=约4800亿港元
  [OK] etf: recent_5d=约18亿元净流入, total_120d=约650亿元
  [OK] margin: recent_5d=-8.49亿元, total_120d=约5500亿元

[STEP 4] 注入债券收益率数据...
  [OK] 中国10年期国债: 1.81%
  [OK] 中国10年期国开债: 1.876%

[STEP 5] 注入商品价格数据...
  [OK] COMEX黄金: $/oz4231.40 (YTD +64.85%)
  [OK] WTI原油: $/barrel59.10 (YTD -11.69%)
  [OK] Brent原油: $/barrel63.57 (YTD -19.79%)
  [OK] COMEX铜: $/lb5.13 (YTD +26.24%)
  [OK] BCOM指数: 点110.51 (YTD +5.38%)

[SUCCESS] 数据注入完成！
  - 注入数据项: 21
  - 数据完整性: 95.0%
```

**验证**:
```bash
python -c "import json; data=json.load(open('data/20251114_market_data_complete.json', encoding='utf-8')); print(f'Completeness: {data[\"metadata\"][\"data_completeness\"]:.1%}'); print('Macro:', {k: v.get('current_value') for k,v in data['macro_indicators'].items()})"
```

**标准化说明**:
- 注入脚本会把资金流向 `recent_5d` / `total_120d` 统一转换为“亿元”浮点，并自动推断 `trend` 与 `source`（`Tavily WebSearch+DeepSeek` 或 `异常零值-需核查`），`note` 中保留原始文本。
- 宏观与货币字段会去掉 `%`、千分符等字符，同时把 `source` 规范化为 Stage2.5 manual/WebSearch 来源，并将 `is_estimated` 置为 `False`。

---

### 当前 Stage3: Pring三层框架分析 (15-25秒)

**脚本**: `scripts/stage3_pring_analyzer.py`

> 归档说明：旧 root 脚本 `run_pring_analysis.py` 仅作为历史入口记录，不推荐在当前流水线中使用。

**命令**:
```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated
```

**输出**:
```
[INFO] 输入文件: data\20251114_market_data_complete.json
[INFO] 输出文件: data\20251114_pring_result.json

[STEP 1] 读取市场数据...
  - 数据完整性: 100.0%
  - 宏观指标: 5/5
  - 货币政策: 5/5

[STEP 2] 初始化Pring分析器...
[STEP 3] 执行Pring三层框架分析...
  - Layer 1: 库存周期分析 (PPI/PMI/Industrial/BDI/CPI)
  - Layer 2: 货币周期叠加 (RRR/Reverse Repo/MLF/TSF/M2)
  - Layer 3: Pring六阶段最终判定

[STEP 4] 保存分析结果...

[SUCCESS] Pring分析完成！
  - 最终阶段: 第Ⅵ阶段
  - 置信度: 60.0%
  - Layer 1: 被动去库
  - Layer 2: 边际宽松
  - 输出文件: data\20251114_pring_result.json
```

**输出文件结构**:
```json
{
  "metadata": {
    "analysis_date": "2025-11-14",
    "data_completeness": 0.95,
    "analysis_method": "Reference-based Judgment",
    "confidence_level": 0.6
  },
  "layer_1_inventory_cycle": {
    "cycle_stage": "被动去库",
    "commodity_bias": "压制商品",
    "fundamental_score": 30.0
  },
  "layer_2_monetary_cycle": {
    "cycle_stage": "边际宽松",
    "equity_bias": "支撑权益",
    "bond_bias": "债券承压",
    "monetary_score": 65.0
  },
  "layer_3_pring_final": {
    "base_stage": "第Ⅵ阶段",
    "final_stage": "第Ⅵ阶段"
  },
  "final_stage": "第Ⅵ阶段",
  "confidence": 0.6,
  "recommendation": "当前处于经济周期第Ⅵ阶段，建议配置：权益资产(60%)>现金/债券(30%)>大宗商品(10%)..."
}
```

---

### 当前 Stage4: Markdown报告生成 (10-15秒)

**脚本**: `scripts/stage4_report_generator.py`

> 归档说明：旧 root 脚本 `generate_simple_report.py` 仅作为历史入口记录，不推荐在当前流水线中直接执行。

**命令**:
```bash
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md"
```

**输出**:
```
[SUCCESS] 报告生成完成！
  - 输出文件: reports\20251124背景扫描120.md
  - 报告日期: 2025-11-10（示例回退至最近开市日）
  - 数据完整性: 100.0%
  - Pring阶段: 第Ⅱ阶段
  - 置信度: 85.0%
```

**报告结构** (9个章节):
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

### 验证: 数据完整性验证 (5秒)

**检查项目**:

1. **文件大小检查**:
```bash
powershell -Command "(Get-Item 'reports\20251114背景扫描120.md').Length"
# 期望输出: 4800-5000 bytes
```

2. **章节数量检查**:
```bash
# 期望: 9个章节
grep -c "^## " reports/20251114背景扫描120.md
```

3. **数据完整性检查**:
```bash
# 检查报告头部元数据
head -n 5 reports/20251114背景扫描120.md
# 应包含: **数据完整性**: 95.0%
```

4. **Pring阶段检查**:
```bash
# 检查核心结论部分
grep "Pring六阶段判定" reports/20251114背景扫描120.md
# 应显示: **Pring六阶段判定**: 第Ⅵ阶段
# 不应显示: 分析失败
```

5. **表格数据检查**:
```bash
# 检查宏观指标表格
grep -A 7 "## 六、宏观经济指标" reports/20251114背景扫描120.md
# 不应有N/A值
```

**验证通过标准**:
- ✅ 文件大小: 4.5-5.5KB
- ✅ 章节数量: 9
- ✅ 数据完整性: 95%
- ✅ Pring阶段: 非"分析失败"
- ✅ 宏观/货币表格: 无N/A

---

## 故障排查

### 问题1: Stage 2a/MCP 旧流程如何处理

**现象**:
```
[WARN] stage2a_mcp_enhancer.py 已归档
```

**解决方案**:
- 不要继续执行旧 Stage2a/MCP flow
- 改用 `scripts/stage2_unified_enhancer.py`
- 剩余缺口写入 `websearch_results_manual.json` 后通过 `scripts/stage2_5_injector.py` 注入

### 问题2: WebSearch数据注入失败

**现象**:
```
UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'
```

**解决方案**:
- 检查Windows控制台编码设置
- 使用当前 `scripts/stage2_5_injector.py` 注入；旧 `inject_websearch_data.py` 已归档，不推荐

### 问题3: Pring分析显示"分析失败"

**可能原因**:
1. AI补全步骤被跳过
2. WebSearch数据不完整
3. 字段名称不匹配

**解决方案**:
```bash
# 检查数据完整性
python -c "import json; data=json.load(open('data/YYYYMMDD_market_data_complete.json', encoding='utf-8')); print({k: v.get('current_value') for k,v in data['macro_indicators'].items()})"

# 应输出: {'ppi': -2.1, 'pmi': 49.0, 'industrial': 6.5, 'bdi': 2104.0, 'cpi': 0.2}
# 如果有None值，需要重新执行AI补全步骤
```

### 问题4: 报告缺少数据

**检查点**:
1. 检查`market_data_complete.json`的data_completeness字段
2. 检查WebSearch结果JSON是否包含所有14项数据
3. 检查inject脚本是否显示"21 items injected"

---

## 完整执行示例 (2025-11-24)

```bash
# Stage 1
python scripts/stage1_data_collector.py --date 2025-11-24 --output data/20251124_market_data.json
# ✅ Output: ~18KB, 40% completeness（休市自动回退）

# Stage 2 unified
bash run_clean.sh python scripts/stage2_unified_enhancer.py --market-data data/runs/20251124/market_data.json --output data/runs/20251124/market_data_stage2.json --phase all --execute-search --fund-flow-backend tavily
# ✅ Output: market_data_stage2.json

# AI补全 (Manual WebSearch + Injection)
# 1. Execute 14 WebSearch queries
# 2. Create websearch_results_20251114.json
# 3. Inject data
bash run_clean.sh python scripts/stage2_5_injector.py data/runs/20251124/market_data_stage2.json data/runs/20251124/websearch_results_manual.json data/runs/20251124/market_data_complete.json
# ✅ Output: 21 items injected, 100.0% completeness

# Stage 3
bash run_clean.sh python scripts/stage3_pring_analyzer.py --market-data data/runs/20251124/market_data_complete.json --output data/runs/20251124/pring_result.json --allow-estimated
# ✅ Output: Stage=第Ⅱ阶段, Confidence=85%

# Stage 4
bash run_clean.sh python scripts/stage4_report_generator.py --market-data data/runs/20251124/market_data_complete.json --pring-result data/runs/20251124/pring_result.json --output reports/2025-11-24-背景扫描120.md
# ✅ Output: 9 sections, no N/A, completeness 100%

# 验证
powershell -Command "(Get-Item 'reports\20251114背景扫描120.md').Length"
# ✅ Output: 4849 bytes
```

---

## 附录

### A. 脚本状态

| 脚本 | 状态 | 说明 |
|------|------|------|
| `stage1_data_collector.py` | ✅ ACTIVE | API数据收集 |
| `scripts/legacy/stage2a_mcp_enhancer.py` | ⚠️ ARCHIVED | 旧 MCP flow，不推荐 |
| `scripts/stage2_5_injector.py` | ✅ RECOMMENDED | Stage2.5 WebSearch/manual 数据注入 |
| `run_pring_analysis.py` | ⚠️ LEGACY / 不推荐 | 旧 root Pring 分析入口 |
| `generate_simple_report.py` | ⚠️ LEGACY / 不推荐 | 旧 root 报告生成入口 |
| `scripts/stage3_pring_analyzer.py` | ✅ RECOMMENDED | 当前 Stage3 Pring 分析主入口（含DR007领先指标） |
| `scripts/stage4_report_generator.py` | ✅ RECOMMENDED | 当前 Stage4 报告生成主入口 |

### B. 数据文件命名

| 阶段 | 文件名 | 说明 |
|------|--------|------|
| Stage 1 | `YYYYMMDD_market_data.json` | API原始数据 |
| Stage 2 | `data/runs/YYYYMMDD/market_data_stage2.json` | Stage2 unified 增强数据 |
| AI补全 | `websearch_results_YYYYMMDD.json` | WebSearch结果 |
| AI补全 | `YYYYMMDD_market_data_complete.json` | 完整数据 |
| Stage 2 | `YYYYMMDD_pring_result.json` | Pring分析结果 |
| Stage 3 | `YYYYMMDD背景扫描120.md` | 最终报告 |

### C. 参考资源

- **CLAUDE.md**: 完整技术文档
- **docs/Stage2数据获取设计分析.md**: 历史问题分析
- **data/websearch_results_20251114_test.json**: WebSearch结果模板
- **inject_websearch_data.py**: LEGACY/已归档数据注入脚本源码，不推荐；当前使用 `scripts/stage2_5_injector.py`
- **run_pring_analysis.py**: LEGACY/已归档Pring分析脚本源码，不推荐；当前使用 `scripts/stage3_pring_analyzer.py`
- **generate_simple_report.py**: LEGACY/已归档报告生成脚本源码，不推荐；当前使用 `scripts/stage4_report_generator.py`

---

**文档结束**
