# AI背景扫描报告执行完整手册

**版本**: V4.2 数据完整性保障版
**更新时间**: 2025-12-09
**适用场景**: 历史背景扫描生成器参考，不作为当前日报执行手册
**文档定位**: 已归档手册；当前权威流程以 `AGENTS.md` 为准

> 当前生产流水线为 Stage1 → Stage2 unified（structured-provider-first + Tavily-first 搜索，必要时 Exa quota failover）→ Stage2.5 → Stage3 → Stage4。
> `scripts/utility/background_scan_120d_generator.py` 仅保留历史/手工分析用途，不作为报告主入口或补数入口。
> 当前补数优先级为 TuShare(Stage1) → Stage2 structured-provider-first + Tavily/DeepSeek → Stage2.5 WebSearch/manual 注入；具体参数和质量 gate 以 `AGENTS.md` 为准。

**版本历程**:
- V2.1 (2025-10-22): MCP增强，资金流向优化，异常零值检测
- V4.1 (2025-11-07): Pring数据完整性保障，三阶段验证机制

**合并说明**: 本文档整合的是历史用户指南和AI技术手册；当前执行请改用 `AGENTS.md` / `README.md` 的 Stage1 -> Stage4。

---

# 📚 目录

## 第一部分：用户指南
- [快速开始](#用户快速开始)
- [执行流程概览](#ai执行流程概览)
- [报告产出内容](#报告产出内容)
- [使用场景示例](#使用场景示例)
- [V2.1特色功能](#v21-ai执行特色-mcp增强)
- [常见问题](#技术支持)

## 第二部分：AI执行技术手册
- [快速启动指令](#ai快速启动指令)
- [标准Todo List模板](#标准todo-list模板)
- [阶段1-5详细执行](#阶段执行详情)
- [质量验证清单](#v21-mcp验证清单)
- [执行要点总结](#执行要点总结)

---

# 第一部分：用户指南

## 🎯 用户快速开始

### 一键启动命令

当您需要生成某日的背景扫描报告时，只需向AI发送：

```
执行背景扫描报告生成：YYYYMMDD
```

**示例**：
- `执行背景扫描报告生成：20250918`
- `执行背景扫描报告生成：20251225`
- `执行背景扫描报告生成：20260315`

归档说明：这类旧指令曾触发 V2.1/MCP 5阶段流程；当前不再按该流程自动执行。当前请按 `AGENTS.md` 运行 Stage1 → Stage2 unified → Stage2.5 → Stage3 → Stage4。

---

## 📋 AI执行流程概览

### 🔄 当前 Stage1 -> Stage4 流水线

| 阶段 | 脚本 | 时间 | 主要任务 | 输出 |
|------|------|------|----------|------|
| 1️⃣ | `scripts/stage1_data_collector.py` | 30-40s | API数据收集（TuShare first） | `market_data.json` |
| 2️⃣ | `scripts/stage2_unified_enhancer.py` | 90-150s | structured-provider-first + Tavily/DeepSeek 增强（forex/bonds/commodities/fund_flow） | `market_data_stage2.json` |
| 2+️⃣ | `scripts/stage2_5_injector.py` | 10-20s | WebSearch结果注入（补完缺口） | `market_data_complete.json` |
| 3️⃣ | `scripts/stage3_pring_analyzer.py` | 15-25s | Pring三层框架分析 | `pring_result.json` |
| 4️⃣ | `scripts/stage4_report_generator.py` | 10-15s | Markdown报告生成 | `DATE背景扫描120.md` |

**当前总时间**: 3-5分钟 | **数据完整度**: 85-95% | **自动化程度**: 高

> **注意**: 如需更快速度，Stage2可使用 `--extraction-backend regex --disable-extract`（30-60s完成）；如需排查结构化源，可追加 `--disable-structured-providers` 只跑原搜索链路。

---

## 📊 报告产出内容

### 📈 历史数据覆盖范围（V2.1/V2.2记录）

> 本节保留历史覆盖口径。当前实际覆盖与缺口处理以 Stage1/Stage2 输出、`gap_monitor.json` 和 Stage2.5 manual 注入为准。

**股票市场** (历史 V2.1 增强口径)：
- **A股**: 沪深300、上证50、创业板指、深证成指、上证指数 (传统API)
- **美股**: 标普500、纳斯达克 (WebFetch Yahoo Finance) ✨新增
- 技术指标：MA20/50/200、趋势评分、波动率

**商品与黄金**：
- 黄金ETF(518880)、能源ETF(159930)、有色ETF(515220)
- 价格走势、技术分析、趋势判断；当前按 Stage1/Stage2/Stage2.5 产物验证，不再使用 MCP 作为当前执行入口

**汇率变化** (历史 V2.1 MCP 获取口径)：
- USD/CNY、USD/CNH、美元指数(DXY)
- **100% WebFetch实时获取**，延迟≤5分钟 ✨增强
- 实时汇率、变动幅度、趋势方向

**债券收益率** (V2.1 MCP混合)：
- 中国10年期国债、美国10年期国债、中国10年期国开债
- **MCP混合获取，准确性90%+** ✨增强
- 当前收益率、变动基点、趋势方向

**资金流向** (V2.2 历史 MCP WebSearch Only)：
- **北向/南向/ETF/融资融券**: 历史口径曾使用 MCP WebSearch；当前按 Stage2.5 manual JSON 注入
- **异常零值处理**: 任一值=0 时自动标记“异常零值-需核查”，并触发二次 WebSearch 复核
- **数据时效性**: WebSearch≤5分钟
- **智能容错**: 所有占位符都由 WebSearch 注入脚本自动解析为浮点+来源标签

**财经要闻** (V2.1 WebSearch实时)：
- **WebSearch获取8-12条最新资讯** ✨增强
- 时效性提升80%，涵盖当日重要动态
- 央行政策、市场动态、国际金融

### 🔍 核心分析框架

**普林格六阶段判断** (V4.1数据完整性保障)：
- 集成库存周期矫正机制
- 技术面分析(35%) + 库存周期分析(65%)
- 避免纯技术面误判
- **V4.1新增**: 三阶段数据验证（Collection → Validation → Analysis）
- **质量门槛**: 数据完整性 ≥ 60%才执行分析
- **透明报告**: 数据不足时生成专门的数据质量报告

**趋势评分系统**：
- -2至+2评分体系
- 综合收益趋势、均线位置、中期趋势、短期动量

---

## 🎮 使用场景示例

### 场景1: 定期市场回顾
```
用户: 执行背景扫描报告生成：20251215
AI: 🎯 开始执行20251215背景扫描报告生成
    ✅ 阶段1完成：环境验证通过
    ✅ 阶段2完成：数据收集完成，获取8个指数数据
    ✅ 阶段3完成：补充汇率、债券、资金流向数据
    ✅ 阶段4完成：报告优化，添加12条财经要闻
    ✅ 阶段5完成：质量验证通过

    📊 报告生成完成！
    📁 文件路径: reports/20251215背景扫描120.md
    📈 核心发现: 沪深300年内+38.5%，美联储降息周期，商品信号neutral
```

### 场景2: 重要时点分析
```
用户: 执行背景扫描报告生成：20250301
AI: [执行5阶段流程...]
    📊 报告生成完成！
    📈 核心发现: 春节后市场回暖，两会前政策预期升温，资金回流明显
```

### 场景3: 季度末总结
```
用户: 执行背景扫描报告生成：20251231
AI: [执行5阶段流程...]
    📊 报告生成完成！
    📈 核心发现: 全年回顾，Q4表现，跨年资金配置特征
```

---

## 📂 文件输出结构

### 生成文件
```
reports/
├── 20250918背景扫描120.md     # 主报告文件
├── 20251225背景扫描120.md     # 其他日期报告
└── ...
```

### 报告章节结构
```markdown
# 120日市场背景扫描报告 (YYYY-MM-DD)

## 一、市场结论要点 (3-6条核心观点)
## 二、股票市场综述 (完整表格+技术分析)
## 三、商品与黄金 (商品ETF表现+趋势)
## 四、汇率变化 (主要汇率+变动分析)
## 五、利率与债券收益率 (收益率表格+趋势)
## 六、资金流向综述 (资金流动+规模统计)
## 七、财经要闻 (8-12条重要新闻)
## 八、普林格阶段推断 (六阶段+库存周期矫正)
## 九、附注说明 (方法说明+数据源+合规声明)
```

---

## 🔧 V2.1 AI执行特色 (MCP增强，历史记录)

> 本节仅解释 V2.1 历史设计，不是当前执行指令。当前日报不自动运行旧 MCP/generator flow；按 `AGENTS.md` 使用 TuShare(Stage1) → Stage2 structured-provider-first + Tavily/DeepSeek → Stage2.5 WebSearch/manual 注入。

### 历史 MCP服务智能数据补充
- **历史策略**：WebFetch直接API调用，WebSearch智能识别；当前不作为优先级口径
- **历史实时数据获取**：无缓存延迟，数据时效性≤5分钟
- **历史智能故障转移**：传统API失败<5秒切换MCP工具
- **历史多源验证**：MCP数据与传统数据交叉验证确保准确性
- **历史资金流向增强** (V2.1新增)：北向/南向/ETF资金流曾优先使用WebSearch，当前资金流缺口应进入 Stage2.5 manual_required 并注入

### V2.1质量保证机制升级
- **MCP数据源标注**：自动标注"WebFetch直接获取"、"WebSearch补充"
- **数据追溯性**：所有MCP数据来源完整记录，可验证
- **格式标准化**：自动统一数值格式（百分比、基点、价格等）
- **结构完整性**：验证9个标准章节全部存在
- **MCP使用统计**：自动生成MCP工具使用报告和效果评估
- **合规性检查**：确保包含必要的风险提示和免责声明

### V2.1透明可追溯升级
- **Todo实时追踪**：每个阶段进度实时可见
- **MCP数据源完整记录**：WebFetch/WebSearch获取过程透明化
- **执行日志增强**：详细记录AI执行过程、MCP工具使用和决策
- **交叉验证报告**：MCP数据与传统数据对比结果

---

## 🛠️ V2.1 MCP增强错误检测与自动修复机制（历史记录）

> 本节记录旧 V2.1/MCP 设计，不是当前自动修复或补数流程。

### 🔍 错误分类系统

**配置模型错误**:
- **检测**: Pydantic字段验证失败
- **修复**: 自动声明缺失字段，如InternationalFinanceConfig的forex_pairs字段
- **验证**: 配置对象创建成功测试

**数据源接口错误** (V2.2 MCP增强):
- **检测**: TuShare接口方法不存在或网络异常
- **历史修复**: 旧 V2.2 曾使用传统API → MCP工具(WebFetch/WebSearch) → 手动补全
- **当前修复**: 记录缺口到 `gap_monitor.json`，再通过 Stage2.5 manual/WebSearch JSON 注入
- **验证**: 检查 `source_url`、期次和 `manual_required` 是否清零

**抽象方法实现错误**:
- **检测**: 抽象基类方法缺失实现
- **修复**: 自动添加必需的抽象方法实现
- **验证**: 数据源实例化成功测试

**初始化参数错误**:
- **检测**: 构造函数参数数量不匹配
- **修复**: 更新参数传递方式，如RateLimiter单参数初始化
- **验证**: 对象初始化无异常测试

**数据源故障转移错误** (V2.2 MCP容错升级):
- **检测**: 传统API不可用
- **历史修复**: 旧 V2.2 曾激活 WebFetch/WebSearch 替代方案
- **当前修复**: Stage2 unified 失败后转 Stage2.5 manual JSON，不直接调用旧 MCP 流程
- **验证**: 检查 Stage2.5 注入输出和 Stage3 policy gate

### 🔄 V2.1 MCP增强自动修复工作流（历史）

```
执行报告生成 → 错误检测 → 发现错误?
   ↓是                      ↓否
错误分类 → 应用修复策略 → MCP容错激活 → 修复验证 → 修复成功? → 记录修复日志 → 正常流程继续
                              ↓                    ↓否
                        Stage2.5 manual JSON   注入后继续
                              ↓
                        数据质量验证
↓
生成报告 → 生成修复汇总 + MCP使用统计
```

### 📊 V2.1 MCP增强修复成功率统计（历史）

基于V2.1优化和MCP集成测试：
- **配置错误修复率**: 100% (1/1)
- **传统API接口错误修复率**: 100% (1/1)
- **MCP工具故障转移成功率**: 95%+ (WebFetch/WebSearch双重保障)
- **抽象方法错误修复率**: 100% (1/1)
- **参数错误修复率**: 100% (1/1)
- **数据完整性保证成功率**: 90%+ (MCP补充后N/A值<5%)
- **V2.1综合修复成功率**: 95%+ (MCP容错显著提升)

### 📋 V2.1修复文档自动生成（历史）

每次执行后自动生成:
- **修复汇总文档**: `{date}修复总结.md` - 详细修复过程和验证结果
- **错误分析文档**: `{date}报错汇总分析.md` - 错误分类和根本原因分析
- **MCP使用统计报告**: `{date}_MCP使用统计.md` - MCP工具使用效果评估 ✨新增
- **数据质量对比报告**: MCP数据与传统数据交叉验证结果 ✨新增
- **CLAUDE.md更新**: 在"Common Issues and Solutions"章节标记已修复问题

### 🎯 V2.1 MCP增强执行保证（历史）

- **零失败容忍**: 遇到已知错误自动修复 + MCP智能容错，确保报告生成成功
- **数据完整性保证**: MCP工具确保汇率、美股、债券数据100%覆盖
- **实时性保证**: WebFetch/WebSearch确保数据时效性≤5分钟
- **透明化修复**: 所有修复过程 + MCP使用过程完整记录，用户可追溯验证
- **智能故障转移**: <5秒快速切换，无缝用户体验
- **预防性检查**: 执行前自动检测潜在问题，提前修复
- **持续学习**: 新错误类型自动归类，MCP使用经验积累优化

---

## ⚠️ 注意事项

### V2.1数据获取优化与限制（历史）
- **历史 MCP数据时效性**: 旧流程曾记录 WebFetch 延迟≤5分钟
- **网络依赖性**: MCP工具依赖网络，但具备多源故障转移能力
- **数据完整性保证**: MCP工具确保汇率、美股、债券数据100%覆盖
- **智能故障转移**: 传统API失败<5秒切换MCP工具，用户无感知
- **历史自动容错机制**: 旧流程曾使用 WebFetch/WebSearch 多网站轮询；当前缺口转 Stage2.5 manual JSON 注入
- **质量交叉验证**: MCP数据与传统数据对比，异常自动标注
- **透明可追溯**: 完整记录MCP工具使用过程和数据来源

### 报告使用声明
- **仅供研究参考**：不构成投资建议
- **数据准确性**：基于公开数据，不保证完全准确
- **投资风险**：市场有风险，投资需谨慎

### V2.1最佳实践建议
- **日期选择**: 选择交易日作为目标日期（避免周末节假日）
- **定期生成**: 利用MCP实时数据优势，可更频繁生成报告跟踪市场变化
- **数据验证**: 关注MCP使用统计报告，了解数据获取质量
- **多元分析**: 结合MCP补充的美股、汇率数据，进行更全面的国际市场分析
- **质量监控**: 查看数据质量对比报告，确保MCP数据准确性

---

## 🚀 高级功能

### 批量生成（规划中）
```
执行背景扫描报告生成：20250918,20251018,20251118
```

### 自定义配置（规划中）
```
执行背景扫描报告生成：20250918 --窗口=90天 --重点=科技股
```

### 对比分析（规划中）
```
对比背景扫描报告：20250918 vs 20250818
```

---

## 📞 技术支持

### V2.1常见问题 (MCP增强)

**Q: AI执行失败怎么办？**
A: V2.1具备MCP增强的自动错误检测和修复机制，传统API失败时<5秒切换MCP工具，自动生成详细修复文档和MCP使用统计

**Q: 报告数据不完整怎么办？**
A: V2.1启用智能故障转移(传统API → MCP工具 → 降级方案)，MCP确保汇率、美股、债券数据100%覆盖，并提供完整数据来源追溯

**Q: 可以修改报告内容吗？**
A: 生成的Markdown文件可以手动编辑和补充

**Q: 如何查看MCP工具使用情况？**
A: V2.1自动生成MCP使用统计报告(如20250926_MCP使用统计.md)和数据质量对比报告，完整记录MCP工具使用效果

**Q: MCP数据准确性如何保证？**
A: V2.1具备MCP数据与传统数据交叉验证机制，异常数据自动标注，数据来源完整可追溯，准确性达90%+

**Q: WebFetch/WebSearch失败怎么办？**
A: 当前不再按 V2.1 MCP 容错链路手工切换工具。检查 `gap_monitor.json`，把缺口写入 `data/runs/${DATE_NH}/websearch_results_manual.json`，再通过 `scripts/stage2_5_injector.py` 注入。

**Q: 如何查看修复过程？**
A: 系统自动生成修复汇总文档和错误分析文档，V2.1新增MCP使用统计，提供完整的修复和数据获取过程记录

**Q: 遇到新类型错误怎么办？**
A: V2.1系统会记录新错误类型，更新错误分类系统，优化MCP容错策略，并在后续版本中增加相应的自动修复策略

### V2.1获得帮助
- 查看执行日志了解详细过程
- 检查Todo列表了解当前进度
- **查看MCP使用统计报告**了解数据获取详情 ✨新增
- **查看数据质量对比报告**了解MCP数据准确性 ✨新增
- 查看报告中的数据源说明和MCP工具标注

---

## 🎯 开始使用

**当前执行入口**：按 `AGENTS.md` 设置日期并运行 Stage1 -> Stage4
```
DATE=2025-09-26
DATE_NH=20250926
```

归档说明：旧 V2.1 MCP增强完整流程不再作为当前自动执行路径。

### 🚀 V2.1版本亮点

- **数据完整性**: 汇率、美股、债券数据100%覆盖
- **实时性强**: WebFetch/WebSearch数据延迟≤5分钟
- **智能容错**: <5秒故障转移，用户无感知
- **质量保证**: Stage2 structured-provider-first + Tavily/DeepSeek 搜索抽取，必要时人工校验，支持队列限流，准确性取决于结构化源、搜索与抽取质量
- **透明追溯**: 完整记录MCP工具使用和数据来源

---
---

# 第二部分：AI执行技术手册

**贡献须知**: 新增脚本或流程前，请先阅读 [AGENTS.md](../AGENTS.md) 获取目录结构与测试规范。

---

## 🎯 AI快速启动指令（三阶段，资金流搜索默认 tavily）

```
执行背景扫描报告生成：YYYYMMDD
```

**示例**: `执行背景扫描报告生成：20251124`

AI 将自动按照当前 Stage1→Stage2→Stage2.5→Stage3→Stage4 流程执行；Stage2 默认 structured-provider-first，资金流搜索 backend=tavily，遇失败可标人工。

---

## 🏗️ V3.1 解耦架构：三阶段Pipeline (2025-11-10新增)

### 架构概览

V3.1引入了**模块化三阶段流水线架构**，将原有的单体报告生成器解耦为三个独立可测试的Stage，提升了系统的可维护性、可扩展性和可测试性。

```
┌─────────────────────────────────────────────────────────────┐
│                    V3.1 三阶段架构                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [Stage 1]              [Stage 2]              [Stage 3]    │
│  数据收集器    →JSON→   Pring分析器    →JSON→   报告生成器   │
│  Data Collector        Analyzer            Generator       │
│                                                              │
│  ├─ 股票指数            ├─ 库存周期层          ├─ Markdown模板│
│  ├─ 商品数据            ├─ 货币周期层          ├─ 9个标准章节 │
│  ├─ 汇率数据            ├─ Pring六阶段         ├─ 数据格式化 │
│  ├─ 债券数据            └─ 置信度计算          └─ 合规声明   │
│  ├─ 资金流向                                                │
│  └─ 财经新闻                                                │
│                                                              │
│  输出: market_data.json → 输出: pring_result.json → 输出: 报告.md │
└─────────────────────────────────────────────────────────────┘
```

### 核心优势

| 优势维度 | V2.1单体架构 | V3.1解耦架构 | 改进 |
|---------|------------|------------|-----|
| **职责分离** | 1577行单文件 | 3个独立Stage | ✅ 职责清晰 |
| **可测试性** | 端到端测试 | 每Stage独立测试 | ✅ 易于调试 |
| **可扩展性** | 修改影响全局 | 修改局限于单Stage | ✅ 低耦合 |
| **中间结果** | 不可检查 | JSON标准化 | ✅ 可追溯 |
| **向后兼容** | N/A | 100%兼容旧接口 | ✅ 无缝切换 |

### 三阶段详解

#### 📊 Stage 1: 数据收集器 (Data Collector)

**职责**: 纯数据收集，无业务逻辑

**文件**: `scripts/stage1_data_collector.py` (650行)

**输出**: `market_data_contract.json` - 包含股票指数、商品、汇率、债券、资金流向、财经新闻

**使用方式**:
```bash
python scripts/stage1_data_collector.py \
    --date 2025-11-10 \
  --output "data/runs/${DATE_NH}/market_data.json"
```

**核心特性**:
- ✅ 使用Pydantic模型严格验证数据结构
- ✅ 当前口径：Stage1 TuShare first，Stage2 使用 structured-provider-first + Tavily/DeepSeek，Stage2.5 处理 manual_required 缺口
- ✅ 计算技术指标 (MA20/50/200, 波动率, 趋势评分)
- ✅ 为缺失数据创建 manual_required/占位符，后续通过 Stage2.5 注入

#### 🔮 当前 Stage 3: Pring分析器

**职责**: 独立的Pring三层框架分析

**文件**: `scripts/stage3_pring_analyzer.py`

**输入**: `data/runs/${DATE_NH}/market_data_complete.json`

**输出**: `data/runs/${DATE_NH}/pring_result.json` - 包含三层周期分析结果和Pring六阶段判定

**使用方式**:
```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated
```

**核心特性**:
- ✅ 完全独立运行，不依赖数据收集逻辑
- ✅ 实现完整的V4.0三层框架分析
- ✅ 库存周期 → 货币周期 → Pring六阶段判定
- ✅ 输出标准化JSON，可供其他系统使用

#### 📝 当前 Stage 4: 报告生成器

**职责**: 纯模板化报告生成，零计算逻辑

**文件**: `scripts/stage4_report_generator.py`

**输入**:
- `data/runs/${DATE_NH}/market_data_complete.json`
- `data/runs/${DATE_NH}/pring_result.json`

**输出**: `reports/YYYY-MM-DD-背景扫描120.md`

**使用方式**:
```bash
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md"
```

**核心特性**:
- ✅ 100%模板化，无任何数据计算
- ✅ 9个标准章节生成
- ✅ 自动格式化数值 (百分比、基点、价格)
- ✅ 当前数据源标注（TuShare、Stage2 structured-provider、Tavily/Exa+DeepSeek、Stage2.5 manual/WebSearch）

### 归档统一入口 (Unified Entry Point)

V3.1 曾提供 `scripts/background_scan_unified.py` 作为兼容入口；该入口已归档，不作为当前日报主入口或补数入口。当前统一按 `AGENTS.md` 的 Stage1 → Stage2 unified → Stage2.5 → Stage3 → Stage4 执行：

```bash
bash run_clean.sh python scripts/stage1_data_collector.py \
  --date "$DATE" \
  --output "data/runs/${DATE_NH}/market_data.json"

bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/${DATE_NH}/market_data.json" \
  --output "data/runs/${DATE_NH}/market_data_stage2.json" \
  --phase all --execute-search \
  --fund-flow-backend tavily

bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"

bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated

bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md"
```

### AI执行建议

**推荐使用当前分 Stage 流程**，不要运行旧 `background_scan_unified.py`。

**使用分Stage执行** (高级调试场景):
- 🔍 需要检查中间数据质量
- 🐛 Stage 2 Pring分析结果需要验证
- 🧪 需要单独测试某个Stage
- 📊 需要保留JSON用于其他分析工具

### V3.1 vs V2.1对比

| 特性 | V2.1 单体架构 | V3.1 解耦架构 |
|------|-------------|-------------|
| 代码行数 | 1577行 | Stage1(650) + Stage2(320) + Stage3(450) = 1420行 |
| 单一文件 | ✅ 1个 | ❌ 3个Stage + 1个统一入口 |
| 可独立测试 | ❌ 只能端到端 | ✅ 每个Stage可单独测试 |
| 中间结果检查 | ❌ 不支持 | ✅ JSON标准化输出 |
| 向后兼容 | N/A | ✅ 100% |
| 扩展新功能 | ❌ 影响全局 | ✅ 修改单个Stage |
| 调试难度 | ⚠️ 较高 | ✅ 低 (定位到具体Stage) |
| 执行时间 | ~3分钟 | ~3分钟 (无性能损失) |

### 迁移指南

**从V2.1迁移到V3.1**:

旧方式 `scripts/utility/background_scan_120d_generator.py` 为 V2.1 历史/manual only 入口，已归档且不推荐，不作为补数入口或日报主入口。

```bash
# 当前方式：按 AGENTS.md 运行 Stage1 -> Stage4
bash run_clean.sh python scripts/stage1_data_collector.py --date "$DATE" --output "data/runs/${DATE_NH}/market_data.json"
bash run_clean.sh python scripts/stage2_unified_enhancer.py --market-data "data/runs/${DATE_NH}/market_data.json" --output "data/runs/${DATE_NH}/market_data_stage2.json" --phase all --execute-search --fund-flow-backend tavily
bash run_clean.sh python scripts/stage2_5_injector.py "data/runs/${DATE_NH}/market_data_stage2.json" "data/runs/${DATE_NH}/websearch_results_manual.json" "data/runs/${DATE_NH}/market_data_complete.json"
bash run_clean.sh python scripts/stage3_pring_analyzer.py --market-data "data/runs/${DATE_NH}/market_data_complete.json" --output "data/runs/${DATE_NH}/pring_result.json" --allow-estimated
bash run_clean.sh python scripts/stage4_report_generator.py --market-data "data/runs/${DATE_NH}/market_data_complete.json" --pring-result "data/runs/${DATE_NH}/pring_result.json" --output "reports/${DATE}-背景扫描120.md"
```

**高级用法**:
```bash
# 保留中间JSON用于检查：当前分 Stage 流程默认保留 data/runs/${DATE_NH}/ 下的中间文件

# 检查数据质量
cat data/runs/${DATE_NH}/market_data_complete.json | jq '.metadata.data_completeness'
cat data/runs/${DATE_NH}/pring_result.json | jq '.final_stage, .confidence'
```

### 技术实现细节

**核心改进**:
1. ✅ 修复了 `TechnicalIndicatorCalculator.add_moving_averages()` 不存在的问题
   - 改用正确的 `calculate_trend_score()` 方法
2. ✅ 移除所有emoji字符，支持Windows GBK编码
3. ✅ 统一模块导入路径 (`technical_indicators.py`)

**已验证功能**:
- ✅ Stage 1数据收集: 4/5股票指数成功
- ✅ Stage 2 Pring分析: 三层框架完整输出
- ✅ Stage 3报告生成: 9个章节全部生成
- ✅ 总执行时间: 174秒 (2.9分钟)

**详细文档**:
- 实施文档: `docs/Phase2_V3.1解耦架构实施完成_20251110.md`
- 测试报告: `docs/Phase2_V3.1解耦架构测试完成_20251110.md`

---

## 🔒 V4.1 Pring数据完整性保障机制 (2025-11-07新增)

### 核心改进

V4.1引入了Pring周期判断的**三阶段数据验证机制**，从根本上解决了基于不完整数据产生误导性分析的问题。

#### 问题背景

在V4.0版本中发现：当货币周期数据（M2/逆回购/MLF/降准/TSF）全部缺失时，系统仍会执行Pring分析并输出"第Ⅱ阶段(置信度90%)"的判断结果，导致：
- ❌ 用户不知道数据缺失
- ❌ 基于0分货币评分做出判断
- ❌ 90%置信度误导用户决策

#### V4.1解决方案

**三阶段数据处理流程**：

```
[阶段1] 数据收集 (Collection)
  ├─ 收集库存周期数据 (PPI/PMI/工业增加值/CPI)
  ├─ 收集货币周期数据 (M2/逆回购/MLF/降准/TSF)
  └─ 收集Pring资产信号 (债券/股票/商品)
         ↓
[阶段2] 数据完整性验证 (Validation)
  ├─ 第一层(库存周期): 检查4项指标 → 计算完整性%
  ├─ 第二层(货币周期): 检查5项指标 → 计算完整性%
  ├─ 第三层(Pring信号): 检查3项资产 → 计算完整性%
  └─ 总体完整性 = (三层平均)
         ↓
    数据完整性 ≥ 60%？
         ↓ 是                    ↓ 否
[阶段3] 执行分析           返回"数据不足"错误
  ├─ 库存周期分析           ├─ stage: "数据不足"
  ├─ 货币周期叠加           ├─ confidence: 0.0
  └─ Pring阶段判定          └─ data_completeness报告
```

### 数据质量标准

| 完整性评分 | 质量等级 | 系统行为 |
|-----------|---------|---------|
| 100% | 优秀 (EXCELLENT) | 正常执行，无警告 |
| 80-99% | 良好 (GOOD) | 正常执行，无警告 |
| 60-79% | 可接受 (ACCEPTABLE) | 执行分析，发出警告 |
| 40-59% | 较差 (POOR) | ❌ 拒绝执行 |
| < 40% | 严重不足 (CRITICAL) | ❌ 拒绝执行 |

**最低质量门槛**: 60%

### 报告呈现增强

#### 场景1: 数据完整 (≥60%)

正常生成Pring分析章节，包含三层详细分析结果。

#### 场景2: 数据不足 (<60%)

生成专门的数据质量报告：

```markdown
### [WARNING] 分析状态：数据不足

**V4.1数据完整性验证**: 系统检测到数据不足，为确保分析可靠性，已拒绝执行Pring周期判断。

### 数据完整性报告

| 层级 | 完整性 | 最低要求 | 状态 |
|------|--------|---------|------|
| 第一层(库存周期) | 0.0% | 60% | [FAIL] |
| 第二层(货币周期) | 0.0% | 60% | [FAIL] |
| 第三层(Pring信号) | 0.0% | 60% | [FAIL] |
| **总体** | **0.0%** | **60%** | **[CRITICAL] 严重不足** |

### 详细错误信息
\```
数据完整性不足 (0.0% < 60%)，无法可靠执行Pring分析！
  第一层: 0%
  第二层: 0%
  第三层: 0%
\```

### 改进建议
1. 检查数据源连接状态
2. 查看数据收集日志，定位缺失数据项
3. 考虑使用WebSearch补充货币周期数据
4. 待数据完整后重新生成报告
```

### AI执行要点

**在执行Pring分析时**:
1. ✅ 系统自动进行三阶段数据验证
2. ✅ 控制台输出详细的[OK]/[MISSING]状态
3. ✅ 数据不足时自动生成专门报告
4. ✅ 无需AI手动干预，完全自动化

**数据完整性输出示例**:
```
[阶段2] 数据完整性验证...
  第一层(库存周期): 4/4项 (100%)
    [OK] PPI数据
    [OK] PMI数据
    [OK] 工业增加值
    [OK] CPI数据
  第二层(货币周期): 0/5项 (0%)
    [MISSING] M2增速
    [MISSING] 7天逆回购
    [MISSING] MLF利率
    [MISSING] 存准率变化
    [MISSING] TSF增速
  第三层(Pring信号): 3/3项 (100%)
    [OK] 债券信号
    [OK] 股票信号
    [OK] 商品信号

  总体数据完整性: 66.7%
  [WARNING] 数据完整性良好但不完美，分析结果可能受影响

[阶段3] 执行三层框架分析...
```

### 技术实现细节

**核心文件**:
- `src/datasource/calculators/pring_analyzer.py` (Lines 1201-1320): 三阶段数据验证
- `scripts/stage3_pring_analyzer.py`: 当前 Stage3 Pring 分析入口
- `scripts/stage4_report_generator.py`: 当前 Stage4 报告生成入口
- `scripts/utility/background_scan_120d_generator.py`: 历史/manual only 生成器，已归档且不推荐作为日报主入口

**验证逻辑**:
```python
# 第一层验证
layer1_checks = {
    "PPI数据": macro_data.get('ppi') is not None and len(...) > 0,
    "PMI数据": macro_data.get('pmi') is not None and len(...) > 0,
    "工业增加值": macro_data.get('industrial_value') is not None,
    "CPI数据": macro_data.get('cpi') is not None and len(...) > 0,
}
layer1_completeness = sum(layer1_checks.values()) / len(layer1_checks) * 100

# 第二层、第三层类似...

overall_completeness = (layer1 + layer2 + layer3) / 3

if overall_completeness < 60.0:
    return {"stage": "数据不足", "error": "...", "data_completeness": {...}}
```

### V4.1核心价值

**对用户**:
- ✅ 透明度: 明确知道哪些数据可用、哪些缺失
- ✅ 可信度: 基于数据质量的置信度评估
- ✅ 决策支持: 可根据数据完整性报告调整决策权重

**对系统**:
- ✅ 健壮性: 阻止在数据不足时产生误导性分析
- ✅ 可维护性: 清晰的数据依赖关系和验证逻辑
- ✅ 质量保证: 强制性的数据质量检查

### 详细文档

完整技术文档请参阅:
- `docs/V4.1优化总结-数据完整性保障.md` - 详细的优化说明和整合指南
- `docs/V4.1验证测试报告.md` - 完整的测试结果和验证
- `docs/Pring数据完整性保障方案.md` - 完整的解决方案设计

---

## 📋 标准Todo List模板

### 初始Todo List（5个主要阶段）

```json
[
  {"content": "PHASE_1: 环境准备与验证", "status": "pending", "activeForm": "环境准备与验证中"},
  {"content": "PHASE_2: Stage1/Stage2 数据收集与增强", "status": "pending", "activeForm": "Stage1/Stage2 数据收集与增强中"},
  {"content": "PHASE_3: Stage2.5 manual_required 补数与注入", "status": "pending", "activeForm": "Stage2.5 manual_required 补数与注入中"},
  {"content": "PHASE_4: Stage3/Stage4 分析与报告生成", "status": "pending", "activeForm": "Stage3/Stage4 分析与报告生成中"},
  {"content": "PHASE_5: 数据质量验证与交付", "status": "pending", "activeForm": "数据质量验证与交付中"}
]
```

---

## 阶段执行详情

## 🔄 阶段1: 环境准备与验证

### Todo子任务
- [ ] 创建Todo任务列表
- [ ] 验证项目目录结构
- [ ] 检查.env环境配置
- [ ] 测试数据源连接（TuShare + Stage2 structured providers + Tavily/DeepSeek）
- [ ] 验证 `scripts/stage2_unified_enhancer.py` 与 `scripts/stage2_5_injector.py` 可用
- [ ] 确认Python依赖完整

### 验证清单
- [ ] `.env`文件存在且配置正确
- [ ] `scripts/stage1_data_collector.py`、`scripts/stage2_unified_enhancer.py`、`scripts/stage2_5_injector.py`、`scripts/stage3_pring_analyzer.py`、`scripts/stage4_report_generator.py`存在
- [ ] TuShare数据源连接正常
- [ ] Tavily/DeepSeek key 可用；Stage2 structured provider 或搜索链路若失败，缺口进入 Stage2.5 manual_required

### AI执行指令

```bash
# 检查环境配置
ls -la .env
cat .env

# 验证当前核心脚本存在
ls scripts/stage1_data_collector.py scripts/stage2_unified_enhancer.py scripts/stage2_5_injector.py scripts/stage3_pring_analyzer.py scripts/stage4_report_generator.py

# 测试数据源连接
python -c "from datasource import get_manager; print('DataSource OK')"

# 当前：验证核心数据源策略
python -c "
import asyncio
from datasource import get_manager

async def validate_strict_data_policy():
    manager = get_manager()

    print('=== V2.2 严格数据源验证 ===')
    print('1. 测试TuShare数据源连接...')
    response = await manager.get_stock_daily('000001', '2025-09-26', '2025-09-26')
    tushare_status = '✅ 正常' if not response.error else f'❌ 异常: {response.error}'
    print(f'   TuShare状态: {tushare_status}')

    print('2. Stage2/Stage2.5策略检查...')
    print('   当前策略: Stage2 structured-provider-first + Tavily/DeepSeek，失败后进入 Stage2.5 manual_required')

    print('=== 当前数据源策略确认 ===')
    print('✅ 已启用严格数据源管理')
    print('✅ 优先级: TuShare -> Stage2 structured-provider-first + Tavily/DeepSeek -> Stage2.5 manual injection')
    print('✅ 已配置 Stage2.5 manual_required 补数机制')

asyncio.run(validate_strict_data_policy())
"
```

### 完成标志
✅ 所有验证清单通过，TuShare/Stage2 structured-provider/Tavily/DeepSeek 或 Stage2.5 manual 补数路径已准备

**预计时间**: 8分钟

---

## 📊 阶段2: 历史混合数据收集与MCP增强（已归档）

> 本节为 V2.1 历史说明。当前执行不要按本节手工切换 WebFetch/MCP；请使用 Stage2 unified 和 Stage2.5 注入。

### Todo子任务
- [ ] 计算120日数据窗口（end_date - 120天）
- [ ] 执行数据收集脚本
- [ ] 使用传统API获取A股数据
- [ ] 当前改用 Stage2 unified / Stage2.5 manual 路径处理美股、汇率、债券、商品缺口
- [ ] 生成初始报告框架

### 数据收集范围

**A股指数** (传统API):
- 沪深300 (000300)
- 上证50 (000016)
- 创业板指 (399006)
- 深证成指 (399001)
- 上证指数 (000001)

**美股指数** (历史 MCP WebFetch):
- 标普500 (S&P 500)
- 纳斯达克 (NASDAQ)

**商品期货** (历史 MCP WebSearch):
- COMEX黄金 (GC=F)
- WTI原油 (CL=F)
- Brent原油 (BZ=F)
- COMEX铜 (HG=F)
- BCOM指数
- GSG ETF

**汇率** (历史 MCP WebFetch):
- USD/CNY
- USD/CNH
- 美元指数(DXY)

**债券收益率** (历史 MCP混合):
- 中国10Y国债
- 美国10Y国债
- 中国10Y国开债

**资金流向** (V2.2 历史 MCP WebSearch Only):
- 北向资金 (历史 MCP WebSearch + 异常零值检测)
- 南向资金 (历史 MCP WebSearch + 异常零值检测)
- 融资融券余额 (历史 MCP WebSearch)
- ETF资金流 (历史 MCP WebSearch)

### AI执行指令

```bash
# 当前推荐：按 AGENTS.md 的 Stage1 -> Stage4 执行
bash run_preflight.sh
bash run_clean.sh python scripts/stage2_unified_enhancer.py --help
bash run_clean.sh python scripts/stage2_5_injector.py --help
```

### 完成标志
✅ 生成 `reports/${DATE}-背景扫描120.md`，且 `gap_monitor.json` 无 pending/manual_required，资金流向通过 Stage2.5 注入或 Stage2 unified 校验

**预计时间**: 12分钟

---

## 🔍 阶段3: 智能数据补充与资产明细完整性保证

> 当前补数入口是 `websearch_results_manual.json` + `scripts/stage2_5_injector.py`；以下 WebSearch/WebFetch 清单是历史 V2.1 操作口径，不作为当前直接执行清单。

### Todo子任务
- [ ] 扫描报告中的N/A值
- [ ] 使用 Stage2 `gap_monitor.json` 定位商品期货缺口
- [ ] 使用 Stage2.5 manual JSON 补充汇率/债券收益率
- [ ] 使用 Stage4 输入数据生成财经要闻/报告内容
- [ ] 验证资产明细完整性
- [ ] 验证资金流向数据完整性

### 数据补充策略

**商品数据优先级（当前 Stage2/Stage2.5 口径）**:
1. Stage2 structured provider：Trading Economics 商品页，`GSG` 使用 Stooq CSV 市价
2. Tavily/Exa + DeepSeek/regex 搜索抽取
3. Stage2.5 manual/WebSearch 注入
4. Bloomberg/CME/iShares 等可信来源仅作为搜索或 manual 证据，不直接绕过注入链路

**汇率数据优先级（当前 Stage2/Stage2.5 口径）**:
1. Stage2 structured provider：`USDCNY` 使用 ChinaMoney JSON，`DXY` 使用 Trading Economics
2. Tavily/Exa + DeepSeek/regex 搜索抽取
3. Stage2.5 manual/WebSearch 注入

**财经要闻来源**:
1. Bloomberg
2. CNBC
3. South China Morning Post
4. Trading Economics
5. IMF/World Bank

**资金流向数据来源** (V2.1新增):
1. 东方财富网 (data.eastmoney.com/hsgt/)
2. 同花顺 (data.10jqka.com.cn)
3. 每日经济新闻 (nbd.com.cn)
4. Wind金融终端
5. Choice金融终端

### AI执行指令

*流水线脚本会自动调用数据补充，仅在手动执行时需要：*

```bash
python scripts/utility/calculate_na_data.py
python scripts/utility/data_completion_checker.py
```

### 完成标志
✅ 所有N/A值补充完毕，商品标的=6个，财经要闻≥8条，资金流向数据完整

**预计时间**: 8分钟

---

## ✨ 阶段4: 历史MCP增强报告优化与完善（已归档）

> 当前报告生成入口是 `scripts/stage4_report_generator.py`，数据来源标注来自 Stage1/Stage2/Stage2.5 产物。

### Todo子任务
- [ ] 更新市场结论要点（3-6条）
- [ ] 完善所有数据说明
- [ ] 检查 Stage1/Stage2/Stage2.5 数据源标注
- [ ] 优化表格格式
- [ ] 验证数据时效性
- [ ] 检查数据源引用
- [ ] 验证资金流向章节完整性

### 优化重点

1. **数据说明**: 当前标注 TuShare、Stage2 structured-provider、Tavily+DeepSeek、Stage2.5 manual/WebSearch 及具体 source_url；MCP 标注仅保留为历史口径
2. **市场结论**: 基于完整数据生成3-6条核心观点
3. **财经要闻**: 按类别组织（中国市场/美国及全球/大宗商品）
4. **时效性**: 确保数据时点标注准确
5. **资金流向**: 标注数据来源（Stage2 structured-provider/Tavily/DeepSeek、Stage2.5 manual source_url、异常零值-需核查）

### 完成标志
✅ 报告结构完整，当前数据源标注清晰，格式规范，资金流向章节数据完整

**预计时间**: 6分钟

---

## ✅ 阶段5: 当前数据质量验证与交付

### Todo子任务
- [ ] 检查9个章节完整性
- [ ] **验证所有表格无"-"、"N/A"、异常"0"值**
- [ ] **发现数据缺失时,检查并优化Python源代码**
- [ ] 验证商品标的数量（≥6个）
- [ ] 验证 TuShare、Stage2 structured-provider、Tavily/Exa+DeepSeek、Stage2.5 manual/WebSearch 数据源标注
- [ ] 验证数值格式规范
- [ ] 验证合规声明
- [ ] 验证资金流向数据
- [ ] 生成执行总结

### 🔍 PHASE 5.1: 报告数据完整性扫描

**关键优化**: 当报告表格中存在"-"、"N/A"、异常"0"值时,必须执行以下流程:

#### 📋 数据缺失检测步骤

1. **扫描报告表格**
   ```bash
   # 使用Read工具读取生成的报告
   Read reports/YYYY-MM-DD-背景扫描120cc.md
   ```

2. **识别问题数据**
   - **"-"**: 完全缺失的数据项
   - **"N/A"**: 未获取的数据项
   - **异常"0"或"0.00"**: 不合理的零值(如北向资金连续120日为0.00)
   - **"待补充"、"数据获取中"**: 占位符文本

3. **定位问题根源**

   **当前表格/数据缺口 → 检查入口映射**:

   | 问题类别 | 当前检查文件/脚本 | 处理原则 |
   |---------|------------------|----------|
   | 股票指数/交易日数据 | `scripts/stage1_data_collector.py`、`src/datasource/adapters/` | 先确认 TuShare/适配器输出和交易日回退 |
   | 商品/债券/外汇缺口 | `scripts/stage2_unified_enhancer.py`、`src/datasource/config/search_profiles.py`、`data/runs/${DATE_NH}/gap_monitor.json` | Stage2 搜索后仍缺失则进入 Stage2.5 |
   | 宏观/货币 stale 或空值 | `scripts/check_monthly_freshness.py`、`gap_monitor.json`、`websearch_results_manual.json` | 补实时来源后用 Stage2.5 注入 |
   | 资金流向 0/None/窗口缺失 | `gap_monitor.json`、`websearch_results_manual.json`、`scripts/stage2_5_injector.py` | 标记 manual_required，禁止用旧 generator 或 Yahoo 直接写最终值 |
   | 报告 N/A/格式问题 | `scripts/stage4_report_generator.py`、`templates/` | 用 complete JSON 和 pring_result 重新生成 |

#### 🔧 PHASE 5.2: 当前检查、补数与重跑路径

> 历史说明：旧 `scripts/utility/background_scan_120d_generator.py` 的 MCP 修改/重跑教程已归档，不再作为补数入口或日报生成器。检测到缺口时，不应向该单体脚本添加 MCP 获取逻辑。

1. **检查缺口与质量门**
   ```bash
   cat "data/runs/${DATE_NH}/gap_monitor.json"
   cat "data/runs/${DATE_NH}/quality_metrics.json"
   bash run_clean.sh python scripts/check_monthly_freshness.py "data/runs/${DATE_NH}/market_data.json"
   ```

2. **补齐 manual_required 数据**
   - 使用实时来源整理 `data/runs/${DATE_NH}/websearch_results_manual.json`
   - 数值字段必须可解析为数字；填写数值时必须带 `source_url` 或在 `source`/`note` 中包含 URL
   - 资金流、宏观/货币 stale、0/None 值均通过 Stage2.5 注入，不通过历史 generator 改代码补数

3. **重新注入、分析、生成报告**
   ```bash
   bash run_clean.sh python scripts/stage2_5_injector.py \
     "data/runs/${DATE_NH}/market_data_stage2.json" \
     "data/runs/${DATE_NH}/websearch_results_manual.json" \
     "data/runs/${DATE_NH}/market_data_complete.json"

   bash run_clean.sh python scripts/stage3_pring_analyzer.py \
     --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
     --output "data/runs/${DATE_NH}/pring_result.json" \
     --allow-estimated

   bash run_clean.sh python scripts/stage4_report_generator.py \
     --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
     --pring-result "data/runs/${DATE_NH}/pring_result.json" \
     --output "reports/${DATE}-背景扫描120.md"
   ```

#### 🎯 PHASE 5.3: 优化验证循环

**迭代优化流程**:

```
报告数据扫描 → 发现"-/N/A/0"?
    ↓ 是                    ↓ 否
定位Python源码 → 代码优化 → 重新生成 → 验证改进 → 通过? → 进入标准验证清单
    ↑                                        ↓ 否
    └────────────── 继续迭代优化 ←──────────┘
```

**最多迭代次数**: 3次
**每次迭代时间**: 8-12分钟
**优化成功率目标**: 使"-/N/A/0"值减少≥80%

---

### V2.1 MCP验证清单

#### 结构完整性
- [ ] 一、市场结论要点（3-6条）
- [ ] 二、股票市场综述（A股5个+美股2个指数）
- [ ] 三、商品与黄金（6个品种完整）
- [ ] 四、汇率变化（3个汇率对）
- [ ] 五、利率与债券收益率（3个品种）
- [ ] 六、资金流向综述（4类资金）
- [ ] 七、财经要闻（8-12条）
- [ ] 八、普林格阶段推断
- [ ] 九、附注说明

#### 数据完整性
- [ ] 股票指数表格: 5个A股指数完整
- [ ] 美股指数: 标普500+纳斯达克（按当前 Stage2/Stage2.5 来源标注）
- [ ] 商品期货表格: 6个品种无"-"
  - COMEX黄金
  - WTI原油
  - Brent原油
  - COMEX铜
  - BCOM指数
  - GSG ETF
- [ ] 汇率表格: 3个汇率对无"-"
  - USD/CNY
  - USD/CNH
  - 美元指数(DXY)
- [ ] 债券表格: 3个品种数据完整
  - 中国10Y国债
  - 美国10Y国债
  - 中国10Y国开债
- [ ] 资金流向: 4类资金数据完整，0/None/窗口缺失均进入 Stage2.5 manual_required
  - 北向资金（Stage2 Tavily/DeepSeek 或 Stage2.5 manual 注入）
  - 南向资金（Stage2 Tavily/DeepSeek 或 Stage2.5 manual 注入）
  - ETF资金流（Stage2 structured-provider/Tavily/DeepSeek 或 Stage2.5 manual 注入；TuShare `etf_share_size` 完整窗口可释放 gate，EastMoney 仍需 full-market direct daily series 验证）
  - 融资融券余额（TuShare 可得字段或 Stage2.5 manual 注入）

#### 当前数据质量
- [ ] 商品数据: 标注 Stage2 structured-provider/Tavily/DeepSeek 或 Stage2.5 `source_url`
- [ ] 汇率数据: 标注 Stage2 structured-provider/Tavily/DeepSeek 或 Stage2.5 `source_url`
- [ ] 债券数据: 标注 Stage2 structured-provider/Tavily/DeepSeek 或 Stage2.5 `source_url`
- [ ] 财经要闻: 标注来源网站与发布时间
- [ ] 资金流向: 标注 `source_url`，异常零值标记为 `异常零值-需核查`
- [ ] 资讯来源: 标注具体网站（Trading Economics, Bloomberg等）
- [ ] 数据时效: 标注实际 `as_of_date` / `report_period`

#### 格式规范
- [ ] 百分比: 保留1位小数（+12.8%）
- [ ] 基点: 使用bp单位（-11bp）
- [ ] MA斜率: 保留4位小数（+10.3321）
- [ ] 价格: 货币符号+数值（$58.46/桶）
- [ ] 点位: 数值+单位（106.22点）
- [ ] 资金流向: 亿元单位，正负号（+100.50亿）

#### 合规性
- [ ] 包含数据来源说明
- [ ] 包含时点标注
- [ ] 包含合规声明
- [ ] 包含免责声明

### 🔄 PHASE 5 完整执行流程

```
开始PHASE 5
    ↓
扫描报告数据完整性 (PHASE 5.1)
    ↓
发现"-/N/A/0"值?
    ↓ 是                      ↓ 否
定位Python源码问题 (PHASE 5.2)   ↓
    ↓                           ↓
代码优化与修复                   ↓
    ↓                           ↓
重新生成报告                     ↓
    ↓                           ↓
验证改进效果 ──→ 未通过 → 继续迭代(最多3次)
    ↓ 通过                      ↓
    └─────────────┬─────────────┘
                  ↓
执行标准验证清单 (PHASE 5.3)
    ↓
所有验证通过?
    ↓ 是              ↓ 否
生成执行总结        标注未解决问题
    ↓                  ↓
    └─────┬─────────┘
          ↓
    交付最终报告
```

### 完成标志
✅ 所有验证清单通过,报告数据完整性≥95%,资金流向数据完整准确
✅ Python代码优化(如有必要)已完成并验证
✅ 生成最终报告和执行总结

**预计时间**:
- 无代码优化: 6分钟
- 包含1次代码优化: 15-20分钟
- 包含2-3次代码优化: 25-35分钟

---

### 📝 PHASE 5 执行实例

#### 实例1: 美股数据缺失问题

**步骤1: 扫描报告发现问题**
```markdown
# reports/20251030背景扫描120cc.md (第30-31行)
| S&P 500 | - | - | - | - | - | - | - | 待补充 |
| NASDAQ | - | - | - | - | - | - | - | 待补充 |
```

**步骤2: 定位当前数据缺口**
```bash
# AI执行
cat data/runs/${DATE_NH}/gap_monitor.json
cat data/runs/${DATE_NH}/quality_metrics.json

# 发现问题:对应字段进入 pending_tasks/manual_required
```

**步骤3: 诊断问题**
- **问题**: 函数只收集A股指数,未实现美股数据获取
- **影响**: 报告第二章股票市场综述缺失国际市场对比
- **优先级**: 高(影响报告完整性)

**步骤4: 当前补数路径**
```bash
# 将实时来源写入 Stage2.5 manual JSON，然后注入
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"
```

**步骤5: 重新生成验证**
```bash
# 重新执行当前 Stage3/Stage4
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated

bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md"

# 验证结果
Read reports/${DATE}-背景扫描120.md

# 确认改进:S&P 500和NASDAQ数据已填充
```

---

#### 实例2: 北向资金异常零值问题

**步骤1: 扫描报告发现问题**
```markdown
# reports/20251030背景扫描120cc.md (第105-106行)
| 北向资金 | +0.00 | +0.00 | 近期转为流入 | MCP WebSearch |
| 南向资金 | +0.00 | +0.00 | 保持流入 | MCP WebSearch |
```

**步骤2: 分析问题性质**
- **异常判断**: 北向/南向资金连续120日为0.00不符合市场实际
- **可能原因1**: WebSearch结果为空或被异常零值策略拦截
- **可能原因2**: 官方渠道未公布当日数据，需要人工补录

**步骤3: 补数入口**
```bash
# 不修改历史 generator；将实时来源写入 Stage2.5 manual JSON
notepad data/runs/${DATE_NH}/websearch_results_manual.json
```

**步骤4: 优化策略选择**
- **策略选择**: Stage2.5 manual/WebSearch 注入
- **实施方案**: 对 `recent_5d` / `total_120d` / `trend` 写入可解析数值，并提供 `source_url`

**步骤5: 注入**
```bash
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"
```

**步骤6: 验证改进**
```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated
```

---

#### 实例3: 中国10Y国开债数据缺失

**步骤1: 发现问题**
```markdown
| 中国10Y国开债 | - | - | - | - | 数据待完善 |
```

**步骤2: 诊断**
- **问题**: CDB债券收益率数据未实现
- **原因**: ChinaBond官网数据需要特定解析,WebSearch难以直接获取

**步骤3: 选择当前估算值标注路径**
```json
{
  "bonds": [
    {
      "symbol": "CN10Y_CDB",
      "name": "中国10年期国开债",
      "current_yield": 1.95,
      "source_url": "https://...",
      "is_estimated": true,
      "note": "估算值，需说明估算方法和实时来源证据"
    }
  ]
}
```

**步骤4: 验证结果**
```markdown
| 中国10Y国开债 | 2.00%估 | -3bp估 | -15bp估 | 下行 | 估算值(CDB债券通常比国债高20-30bp) |
```

---

### 🎯 PHASE 5 最佳实践

1. **当前补数入口**: 外部数据缺口先走 Stage2 unified；仍缺失时写入 Stage2.5 manual/WebSearch JSON 后注入
2. **异常零值必查**: 资金流向出现连续零值,必须验证数据合理性
3. **估算值明确标注**: 确实无法获取的数据,使用估算值并明确标注"估"
4. **迭代优化控制**: 最多3次迭代,每次针对不同类型的数据缺失
5. **代码修改测试**: 每次修改后立即重新生成报告验证改进效果
6. **保留执行记录**: 记录所有代码修改和优化决策,便于后续审计

---

## ⏱️ 总预期时间

**V2.1完整执行时间**: 35-70分钟(取决于是否需要代码优化)

**标准执行**(无代码优化):
- 阶段1: 8分钟
- 阶段2: 12分钟
- 阶段3: 8分钟
- 阶段4: 6分钟
- 阶段5: 6分钟
- **总计**: 40分钟

**包含代码优化执行**:
- 阶段1: 8分钟
- 阶段2: 12分钟
- 阶段3: 8分钟
- 阶段4: 6分钟
- 阶段5: 15-35分钟(含1-3次代码优化迭代)
- **总计**: 49-69分钟

---

## 📦 最终交付物

1. **主报告**: `reports/YYYY-MM-DD-背景扫描120cc.md`
2. **原始报告**: `reports/YYYY-MM-DD-背景扫描120_raw.md`
3. **执行日志**: Todo列表完成记录
4. **数据源汇总**: TuShare、Stage2 structured-provider、Tavily/Exa+DeepSeek、Stage2.5 manual/WebSearch sources
5. **核心发现**: 3-6条市场核心观点

---

## 🔧 故障处理

### 常见问题及解决方案

**问题1: Stage1/API 连接失败**
- 解决: 记录缺口，继续 Stage2 unified；仍缺失时进入 Stage2.5 manual/WebSearch JSON 注入
- 标注: `tavily+deepseek` 或 Stage2.5 `source_url`

**问题2: 历史 WebFetch/WebSearch 口径失败**
- 解决: 不再手工切换旧 MCP 工具；检查 `gap_monitor.json`，将缺口写入 Stage2.5 manual/WebSearch JSON 后注入
- 备用: 在 `websearch_results_manual.json` 中保留 `source_url` 与期次说明

**问题3: 数据格式异常**
- 解决: 人工校验并重新获取
- 标注: 数据来源和获取方式

**问题4: N/A值无法补充**
- 解决: 标注"数据源受限"
- 说明: 在数据说明中详细解释

**问题5: 资金流向数据获取失败**
- 解决: 标记 `manual_required`，写入 `websearch_results_manual.json` 后通过 `scripts/stage2_5_injector.py` 注入
- 标注: 数据来源、URL 和获取方式

---

## 📝 执行示例

### 用户输入
```
执行背景扫描报告生成：20251014
```

### AI执行流程
```
[10:00] 🎯 开始执行20251014背景扫描报告生成 (V2.1 MCP增强版)
[10:01] ✅ 阶段1完成：环境验证通过
[10:03] 📊 阶段2进行中：收集市场数据...
[10:15] ✅ 阶段2完成：获取A股5个+美股2个指数+资金流向数据
[10:16] 🔍 阶段3进行中：使用WebSearch补充商品期货数据...
[10:24] ✅ 阶段3完成：补充6个商品、3个汇率、3个债券、10条财经要闻
[10:25] ✨ 阶段4进行中：优化报告格式和数据说明...
[10:31] ✅ 阶段4完成：MCP数据标注完整
[10:32] ✅ 阶段5进行中：验证报告质量...
[10:38] ✅ 阶段5完成：所有验证清单通过

📊 报告生成完成！
📁 文件路径: reports/20251014背景扫描120cc.md
📈 核心发现:
  - 沪深300指数120日涨+17.2%，趋势评级「牛」
  - 商品信号Bearish(29.4分)，库存周期「被动补库存」
  - COMEX黄金年内涨+56.09%，创历史新高
  - 北向资金120日流入+1250亿，南向资金流出-320亿
```

---

## 🎯 执行要点总结

### 核心执行要点

1. **Always Create Todo List First** - 在PHASE_1立即创建5阶段Todo
2. **数据源优先级** - 当前按 TuShare(Stage1) → Stage2 structured-provider-first + Tavily/DeepSeek → Stage2.5 WebSearch/manual 注入执行
3. **实时标注来源** - Stage2.5 手工补数必须带 `source_url` 或在 `source`/`note` 中包含 URL
4. **完整性验证** - 阶段5严格检查验证清单
5. **格式规范** - 百分比、基点、斜率、价格格式统一
6. **透明可追溯** - 数据来源、时点、方法完整记录
7. **资金流向完整** - 北向/南向/ETF/融资融券按当前 gate 处理：TuShare 可得字段、Stage2 structured-provider/Tavily/DeepSeek 或 Stage2.5 manual/WebSearch 注入；ETF 的 TuShare `etf_share_size` 完整窗口可释放 gate，EastMoney 仍需 full-market direct daily series 验证，0/None/窗口缺失进入 manual_required
8. **智能容错机制** - WebSearch失败记录提示，等待人工补数（AKShare 通道已停用）
9. **Pring数据验证** - 自动三阶段验证，数据不足时拒绝执行 (V4.1新增) ⭐
10. **数据质量透明** - Pring章节自动显示数据完整性状态 (V4.1新增) ⭐

### V4.1 Pring分析执行要点 ⭐新增

**自动化验证**:
- ✅ 系统自动进行三阶段数据验证
- ✅ 无需AI手动检查数据完整性
- ✅ 数据不足时自动生成专门报告
- ✅ 所有验证信息输出到控制台

**AI关注重点**:
1. **观察控制台输出**: 注意[OK]/[MISSING]状态标记
2. **识别数据质量警告**: 看到[WARNING]时记录到Todo
3. **验证报告章节**: 确认Pring章节正确呈现（正常分析或数据不足报告）
4. **不要手动干预**: V4.1验证机制完全自动化，AI不需要手动判断数据是否充分

---

## 🚀 V2.1版本优势（历史记录）

> 本节仅保留历史背景，不是当前执行建议。当前补数优先级以 AGENTS.md 为准。

### 历史 MCP服务集成核心优势

**1. 数据获取能力增强**
- 历史方案曾使用 WebFetch 直接调用 Yahoo Finance API
- 历史方案曾使用 WebSearch 智能识别权威财经网站
- 实时性强，无API密钥维护负担

**2. 数据完整性保证**
- 汇率数据: 100%通过MCP获取
- 美股指数: 历史口径曾通过 WebFetch 获取
- 债券收益率: MCP混合获取，准确性90%+
- 资金流向: MCP WebSearch Only + 异常零值检测 (V2.2增强)
  - 北向/南向/ETF/融资融券: WebSearch实时获取 + 零值复核
  - 数据时效性: WebSearch≤5分钟
- 财经要闻: WebSearch获取8-12条最新资讯

**3. 智能故障转移**
- 传统API失败时零延迟切换MCP工具
- 多数据源验证，异常数据自动标注
- MCP工具故障时平滑降级到传统方案

**4. 透明可追溯**
- 所有MCP数据来源完整记录
- 自动生成MCP使用统计报告
- 数据获取方法和验证过程透明化

---

## 🔒 V4.1版本增强 (2025-11-07) ⭐最新

### Pring数据完整性保障

**核心改进**:
V4.1在V2.1 MCP增强基础上，针对Pring周期判断引入**三阶段数据验证机制**，从根本上解决了基于不完整数据产生误导性分析的问题。

**1. 三阶段数据处理**
```
Collection (收集) → Validation (验证) → Analysis (分析)
```
- 在执行Pring分析前强制验证数据完整性
- 逐层检查：库存周期(4项) + 货币周期(5项) + Pring信号(3项)
- 自动计算总体数据完整性百分比

**2. 质量门槛机制**
- **最低标准**: 60%数据完整性
- **行为规则**:
  - ≥ 80%: 正常执行，无警告
  - 60-79%: 执行分析，发出警告
  - < 60%: ❌ 拒绝执行，生成数据质量报告

**3. 透明报告呈现**
- **数据完整时**: 正常生成Pring分析章节
- **数据不足时**: 自动生成专门的数据质量报告
  - 显示详细的数据完整性表格
  - 标注每层每项的[PASS]/[FAIL]状态
  - 提供明确的改进建议

**4. 自动化验证**
- ✅ AI完全自动执行，无需手动干预
- ✅ 控制台实时输出[OK]/[MISSING]状态
- ✅ 验证结果自动记录到报告
- ✅ 100%兼容Windows GBK编码

### V4.1 vs V2.1对比

| 方面 | V2.1 | V4.1 |
|------|------|------|
| **数据获取** | ✅ MCP增强 | ✅ 继承V2.1 |
| **资金流向** | ✅ 异常零值检测 | ✅ 继承V2.1 |
| **Pring分析** | ⚠️ 无数据验证 | ✅ 三阶段验证 ⭐ |
| **质量门槛** | ❌ 无门槛 | ✅ 60%最低要求 ⭐ |
| **数据透明度** | 🟡 部分透明 | ✅ 完全透明 ⭐ |
| **报告呈现** | ⚠️ N/A填充 | ✅ 专门质量报告 ⭐ |

### V4.1核心价值

**防止误导性分析**:
- V2.1问题: 货币周期数据0%完整性时，仍输出"第Ⅱ阶段(置信度90%)"
- V4.1解决: 检测到数据不足，拒绝执行，生成数据质量报告

**提升决策质量**:
- 用户清楚了解数据完整性状况
- 基于数据质量调整投资决策权重
- 避免"垃圾输入，垃圾输出"(GIGO)问题

**技术实现**:
- 代码位置: `src/datasource/calculators/pring_analyzer.py:1201-1320`
- 报告生成: `scripts/stage4_report_generator.py`
- 历史/manual only: `scripts/utility/background_scan_120d_generator.py` 已归档且不推荐作为当前日报主入口
- 详细文档: `docs/V4.1优化总结-数据完整性保障.md`

---

**📌 重要提醒**:
- 本文档为 V2.1/V3.1 历史归档参考；当前执行以 `AGENTS.md` 为准
- AI执行时应遵循 `AGENTS.md` 的 Stage1 → Stage2 unified → Stage2.5 → Stage3 → Stage4
- Todo List在执行过程中实时更新状态
- 当前验证以 `gap_monitor.json`、`quality_metrics.json`、Stage3 policy gate 和报告 N/A 检查为准
- Stage2.5 手工补数必须记录 `source_url` 或在 `source`/`note` 中包含 URL
- 资金流向数据应标注来源；异常零值标记为 `异常零值-需核查`

---

**📋 本手册仅保留历史用户指南和AI执行手册内容，用于回溯旧流程**
**🤖 当前执行请使用 AGENTS.md 中的 Stage1 → Stage4 流水线**
**⚡ 旧 V2.1/MCP 一键生成口径已归档，不作为当前日报生成路径**
