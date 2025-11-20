# Stage 2 Pring分析数据获取设计分析

**分析时间**: 2025-11-13
**分析对象**: V3.3架构中Stage 2宏观经济数据的获取机制

---

## 一、设计预期 vs 实际实现

### 📋 设计预期（架构文档）

根据V3.3架构设计，Stage 2（Pring分析）所需的宏观经济数据应按以下流程获取：

```
Stage 1: 数据收集
├─ 创建宏观指标占位符（macro_indicators）
├─ 创建货币政策占位符（monetary_policy）
├─ 标记 is_estimated=True
└─ 记录 search_query（WebSearch查询字符串）

           ↓

Stage 2: Pring分析
├─ 检测 is_estimated=True 的占位符
├─ 调用 MCP WebSearch 填充实际数据
├─ 解析搜索结果提取数值
├─ 验证数据有效性
├─ 更新 market_data 并标记 is_estimated=False
└─ 执行 Pring 三层框架分析
```

### ⚠️ 实际实现状态

**关键发现**: Stage 2的WebSearch填充逻辑**尚未实现**，仅有框架代码和TODO注释。

---

## 二、代码实现细节分析

### Stage 1: 数据收集器 (`stage1_data_collector.py`)

**文件位置**: `scripts/stage1_data_collector.py`
**方法**: `collect_macro_indicators()` (Line 638-729)

#### 实现逻辑

```python
async def collect_macro_indicators(self) -> Dict[str, MacroIndicatorData]:
    """
    收集宏观经济指标 - Pring第一层(库存周期)必需数据

    数据项: PPI, PMI, 工业增加值, BDI, CPI
    数据来源: 100% MCP WebSearch (国家统计局、央行等权威来源)
    """
    macro_dict = {}

    # 宏观指标配置 - 全部需要WebSearch
    indicators = [
        {
            'key': 'ppi',
            'name': 'PPI',
            'search_query': '中国PPI 工业生产者出厂价格指数 国家统计局 最新数据',
            'source_hint': 'stats.gov.cn',
            'unit': '%',
            'weight': 30
        },
        # ... 其他4个指标配置
    ]

    for indicator in indicators:
        # 创建WebSearch占位符
        macro_dict[indicator['key']] = MacroIndicatorData(
            indicator_name=indicator['name'],
            current_value=None,          # ⚠️ 值为None
            previous_value=None,
            change_rate=None,
            unit=indicator['unit'],
            date=self.end_date,
            source=f'待MCP WebSearch获取({indicator["source_hint"]})',
            is_estimated=True            # ⚠️ 标记为估算值
        )

        # 记录缺失数据
        self._record_missing(
            'macro_indicators',
            indicator['key'],
            indicator['name'],
            'TuShare/本地无数据，需MCP WebSearch',
            search_query=indicator['search_query'],  # 保存查询字符串
            source_hint=indicator['source_hint']
        )

    return macro_dict
```

**货币政策数据** (`collect_monetary_policy()`, Line 731-780):
- 同样的逻辑：创建占位符 + 标记`is_estimated=True` + 记录search_query
- 包含4个指标: RRR(存准率), reverse_repo(7天逆回购), TSF(社融), M2(货币供应量)

**关键特征**:
- ✅ **仅创建占位符**，不实际获取数据
- ✅ 保存完整的`search_query`供后续使用
- ✅ 标记`is_estimated=True`用于Stage 2检测
- ⚠️ 所有数值字段为`None`

---

### Stage 2: Pring分析器 (`stage2_pring_analyzer_standalone.py`)

**文件位置**: `scripts/stage2_pring_analyzer_standalone.py`
**核心方法**: `enhance_market_data_with_websearch()` (Line 69-104)

#### 设计架构

```python
async def analyze(self) -> PringResultContract:
    """执行Pring三层框架分析"""

    # ============ Phase 3: WebSearch数据增强 ============
    await self.enhance_market_data_with_websearch()  # Line 464

    # 保存增强后的市场数据
    enhanced_data_path = self.market_data_path.parent / \
        self.market_data_path.name.replace('.json', '_enhanced.json')

    with open(enhanced_data_path, 'w', encoding='utf-8') as f:
        json.dump(self.market_data.model_dump(), f, ensure_ascii=False, indent=2)

    # ============ 执行Pring分析 ============
    pring_result = await self.pring_analyzer.analyze_pring_stage(250)
    # ...
```

#### WebSearch增强流程

```python
async def enhance_market_data_with_websearch(self) -> None:
    """使用WebSearch增强市场数据 - Phase 3实现"""

    # 1. 检测需要填充的占位符
    placeholders = self._detect_websearch_placeholders()  # Line 79

    if not placeholders:
        print("[INFO] 未检测到需要填充的WebSearch占位符")
        return

    # 2. 填充宏观指标
    macro_placeholders = [p for p in placeholders if p['category'] == 'macro_indicators']
    if macro_placeholders:
        for placeholder in macro_placeholders:
            await self._fill_macro_indicator(placeholder)  # Line 92

    # 3. 填充货币政策
    monetary_placeholders = [p for p in placeholders if p['category'] == 'monetary_policy']
    if monetary_placeholders:
        for placeholder in monetary_placeholders:
            await self._fill_monetary_policy(placeholder)  # Line 98
```

#### 占位符检测逻辑

```python
def _detect_websearch_placeholders(self) -> list:
    """检测需要填充的WebSearch占位符"""
    placeholders = []

    # 检测宏观指标占位符
    for key, indicator in self.market_data.macro_indicators.items():
        if indicator.is_estimated:  # ✅ 检测Stage 1设置的标记
            placeholders.append({
                'category': 'macro_indicators',
                'key': key,
                'name': indicator.indicator_name,
                'unit': indicator.unit,
                'source': indicator.source
            })

    # 检测货币政策占位符（同理）
    for key, policy in self.market_data.monetary_policy.items():
        if policy.is_estimated:
            placeholders.append({...})

    return placeholders
```

#### ⚠️ 关键问题：填充逻辑未实现

**文件位置**: `stage2_pring_analyzer_standalone.py` Line 398-453

```python
async def _fill_macro_indicator(self, placeholder: Dict) -> None:
    """填充单个宏观指标数据 - Phase 3.5完整实现"""
    key = placeholder['key']
    name = placeholder['name']
    unit = placeholder['unit']

    print(f"  填充 {name}...")

    # 1. 构建WebSearch查询
    query = self._build_websearch_query(placeholder)
    print(f"    [Query] {query}")

    # 2. ⚠️⚠️⚠️ 关键问题：WebSearch调用被注释掉 ⚠️⚠️⚠️
    print(f"    [INFO] 请使用WebSearch工具查询: {query}")
    print(f"    [INFO] 查询完成后,数据将被解析并填充")

    # TODO: 实际WebSearch调用需要在Claude Code环境中手动触发
    # 这里预留接口供后续集成
    # ==================== 被注释的代码 ====================
    # search_result = await self._call_mcp_websearch(query)
    # if search_result:
    #     parsed_data = self._parse_macro_indicator(search_result, key)
    #     if parsed_data and self._validate_indicator_data(parsed_data, key, unit):
    #         # 更新数据
    #         self.market_data.macro_indicators[key].current_value = parsed_data['current_value']
    #         self.market_data.macro_indicators[key].is_estimated = False
    #         print(f"    [OK] {name} = {parsed_data['current_value']}{unit}")
    # ======================================================

    print(f"    [PENDING] {name} - 等待WebSearch结果手动填充")
    # ⚠️ 实际效果：什么都不做，数据仍然是None
```

**货币政策填充** (`_fill_monetary_policy()`, Line 427-453):
- 完全相同的问题：WebSearch调用代码被注释
- 只打印信息，不实际填充数据

---

## 三、为什么WebSearch调用未实现？

### 代码注释说明

```python
# TODO: 实际WebSearch调用需要在Claude Code环境中手动触发
# 这里预留接口供后续集成
```

### 可能的原因分析

1. **MCP工具调用机制限制**
   在纯Python脚本中无法直接调用MCP WebSearch工具（需要Claude Code环境）

2. **架构演进阶段**
   Stage 2的WebSearch集成仍处于"Phase 3.5"开发阶段，框架已搭建但实现未完成

3. **依赖外部触发**
   设计上可能期望由orchestrator（如background_scan_unified）在Stage 2执行前先调用WebSearch

4. **数据解析器已就绪**
   虽然调用逻辑缺失，但数据解析逻辑已实现：
   - `_parse_macro_indicator()` (Line 182-281)
   - `_parse_monetary_policy()` (Line 283-379)
   - `_validate_indicator_data()` 验证逻辑

---

## 四、当前数据流实际状态

### 实际执行流程

```
用户命令:
python scripts/background_scan_unified.py --date 2025-11-12 --output reports/20251112.md --enable-full-mcp

           ↓

[Stage 1] 数据收集 (✅ 成功)
├─ 股票指数: 100% 成功 (TuShare API)
├─ 商品数据: 部分成功 (InternationalFinance API)
├─ 汇率数据: 100% 成功 (InternationalFinance API)
├─ 宏观指标: 0% 成功 → 创建9个占位符 (is_estimated=True, value=None)
└─ 输出: market_data.json (38%数据完整度)

           ↓

[Stage 2a] MCP Essential增强 (⚠️ 部分成功)
├─ 债券收益率: WebSearch填充尝试 (部分失败)
└─ 商品价格: WebSearch填充尝试 (部分失败)
├─ 输出: market_data_enhanced.json (65-75%数据完整度)
└─ 宏观指标仍然是None (未处理)

           ↓

[Stage 2] Pring分析 (⚠️ 降级执行)
├─ 调用 enhance_market_data_with_websearch()
│   ├─ 检测到9个占位符 (✅)
│   ├─ 构建WebSearch查询 (✅)
│   ├─ 打印查询信息 (✅)
│   └─ ⚠️ 跳过实际WebSearch调用 (TODO注释)
│   └─ ⚠️ 宏观指标仍然是None
│
├─ 调用 PringAnalyzer.analyze_pring_stage(250)
│   ├─ 第一层（库存周期）: 5个指标全部None → 评分失败 (0/60分)
│   ├─ 第二层（货币周期）: 4个指标全部None → 评分失败 (0/100分)
│   ├─ 第三层（Pring信号）: 仅股票信号可用 (1/3)
│   └─ V2.1严格模式: 禁止使用模拟数据
│
└─ 输出: pring_result.json (stage="分析失败", confidence=0.0)

           ↓

[Stage 3] 报告生成 (✅ 结构完整)
├─ 读取 market_data_enhanced.json
├─ 读取 pring_result.json
├─ 生成9章结构完整的Markdown
├─ 第八章: 使用参考判定 (60%置信度) + 数据缺失说明
└─ 输出: 20251112背景扫描120.md (65-75%数据完整度)
```

### 数据完整度对比

| 数据类别 | Stage 1输出 | Stage 2a输出 | Stage 2分析所需 | 实际可用 |
|---------|------------|-------------|----------------|---------|
| **宏观指标** | 0% (5个None) | 0% (未处理) | 100% (5个值) | ❌ 0% |
| **货币政策** | 0% (4个None) | 0% (未处理) | 100% (4个值) | ❌ 0% |
| **股票数据** | 100% | 100% | 100% | ✅ 100% |
| **商品数据** | 17% | 50-83% | 100% | ⚠️ 50-83% |
| **债券数据** | 33% | 33-67% | 100% | ⚠️ 33-67% |

---

## 五、为何Stage 2a没有填充宏观数据？

### Stage 2a职责定义

**文件**: `scripts/stage2a_mcp_enhancer.py`
**设计职责**: Essential MCP增强（债券 + 商品）

```python
# Stage 2a职责范围（有意设计）
ENHANCEMENT_TARGETS = [
    '债券收益率': ['CN10Y', 'CN10Y_CDB', 'US10Y'],
    '商品价格': ['COMEX黄金', 'WTI原油', 'Brent原油', 'COMEX铜', 'BCOM指数', 'GSG ETF']
]

# ⚠️ 明确不包含宏观指标
EXCLUDED_FROM_STAGE2A = [
    '宏观经济指标': ['PPI', 'PMI', 'Industrial', 'BDI', 'CPI'],
    '货币政策': ['RRR', 'reverse_repo', 'TSF', 'M2']
]
```

**设计原因**:
1. **优先级排序**: 债券+商品对Pring第三层（技术信号）至关重要
2. **MCP预算控制**: Stage 2a执行5-9次MCP调用，聚焦最关键数据
3. **职责分离**: 宏观数据由Stage 2自身的WebSearch增强逻辑负责

---

## 六、解决方案设计

### 方案1: 激活Stage 2的WebSearch调用 ⭐ 推荐

**实施步骤**:

1. **取消注释WebSearch调用代码** (`stage2_pring_analyzer_standalone.py`)

```python
async def _fill_macro_indicator(self, placeholder: Dict) -> None:
    """填充单个宏观指标数据"""
    key = placeholder['key']
    name = placeholder['name']

    # 1. 构建查询
    query = self._build_websearch_query(placeholder)

    # 2. ✅ 激活WebSearch调用
    try:
        from claude_code import WebSearch  # 假设的MCP工具导入
        search_result = await WebSearch(query=query)

        if search_result:
            parsed_data = self._parse_macro_indicator(search_result, key)
            if parsed_data:
                # 更新数据
                self.market_data.macro_indicators[key].current_value = parsed_data['current_value']
                self.market_data.macro_indicators[key].previous_value = parsed_data.get('previous_value')
                self.market_data.macro_indicators[key].change_rate = parsed_data.get('change_rate')
                self.market_data.macro_indicators[key].date = parsed_data['date']
                self.market_data.macro_indicators[key].is_estimated = False
                self.market_data.macro_indicators[key].source = 'MCP WebSearch实时获取'
                print(f"    [OK] {name} = {parsed_data['current_value']}{unit}")
                return
    except Exception as e:
        print(f"    [ERROR] WebSearch失败: {e}")

    print(f"    [PENDING] {name} - WebSearch失败，保持占位符")
```

2. **处理MCP工具调用限制**

```python
# 在background_scan_unified中添加WebSearch session检查
async def _run_stage2_with_mcp_retry(self):
    """执行Stage 2并处理MCP限制"""
    try:
        await self._run_stage2()
    except MCPSessionLimitError:
        print("[WARNING] WebSearch session限制，使用降级模式")
        print("[INFO] 建议稍后重试或手动补充宏观数据")
        # 继续执行但记录限制
```

**优势**:
- ✅ 符合原始设计意图
- ✅ 数据解析逻辑已就绪
- ✅ 无需修改架构

**挑战**:
- ⚠️ MCP工具调用在纯Python脚本中的技术可行性
- ⚠️ WebSearch session限制管理

---

### 方案2: 将宏观数据纳入Stage 2a职责

**实施步骤**:

1. **扩展Stage 2a职责范围** (`stage2a_mcp_enhancer.py`)

```python
# 新增宏观指标增强逻辑
async def enhance_macro_indicators(self, market_data: MarketDataContract) -> Dict:
    """增强宏观经济指标"""
    enhanced_count = 0

    for key, indicator in market_data.macro_indicators.items():
        if indicator.is_estimated and indicator.current_value is None:
            query = self._build_macro_query(key, indicator.indicator_name)
            result = await self._mcp_websearch(query)

            if result:
                parsed = self._parse_macro_result(result, key)
                if parsed:
                    indicator.current_value = parsed['value']
                    indicator.is_estimated = False
                    enhanced_count += 1

    return {'enhanced_count': enhanced_count, 'total': 5}
```

2. **重命名Stage 2a** → **Stage 2a: MCP Complete Enhancement**

**优势**:
- ✅ MCP调用集中管理
- ✅ 避免Stage 2依赖MCP环境
- ✅ 更清晰的职责划分

**挑战**:
- ⚠️ Stage 2a执行时间增加（3分钟 → 5-6分钟）
- ⚠️ MCP调用次数增加（5-9次 → 14-18次）

---

### 方案3: 创建Stage 1.5专门处理宏观数据 ⭐ 架构最清晰

**新架构**:

```
Stage 1: API数据收集 (30-40s)
  └─ 创建所有占位符

         ↓

Stage 1.5: 宏观数据MCP增强 (60-90s) ← 新增
  └─ 专门填充9个宏观指标

         ↓

Stage 2a: 市场数据MCP增强 (60-90s)
  └─ 债券 + 商品价格

         ↓

Stage 2: Pring分析 (15-25s)
  └─ 使用完整数据执行分析

         ↓

Stage 3: 报告生成 (10-15s)
```

**实施步骤**:

创建 `scripts/stage1_5_macro_enhancer.py`:

```python
class MacroDataEnhancer:
    """专门的宏观经济数据增强器"""

    async def enhance(self, market_data_path: str) -> Dict:
        # 1. 加载market_data.json
        market_data = MarketDataContract.load(market_data_path)

        # 2. 检测宏观指标占位符
        macro_placeholders = [
            k for k, v in market_data.macro_indicators.items()
            if v.is_estimated
        ]

        # 3. 批量MCP WebSearch填充
        for key in macro_placeholders:
            await self._fill_indicator(market_data, key)

        # 4. 检测货币政策占位符
        monetary_placeholders = [
            k for k, v in market_data.monetary_policy.items()
            if v.is_estimated
        ]

        # 5. 批量MCP WebSearch填充
        for key in monetary_placeholders:
            await self._fill_policy(market_data, key)

        # 6. 保存增强结果
        market_data.save(market_data_path)

        return {
            'macro_filled': len(macro_placeholders),
            'monetary_filled': len(monetary_placeholders)
        }
```

**优势**:
- ✅ 职责最清晰（专门处理宏观数据）
- ✅ 独立可测试
- ✅ 失败不影响其他Stage
- ✅ 可选执行（Fast模式跳过）

**执行模式调整**:

```python
# Fast Mode (3 stages): 1 → 2 → 3
# Accurate Mode (5 stages): 1 → 1.5 → 2a → 2 → 3  ← 推荐
# Full Mode (6 stages): 1 → 1.5 → 2a → 2 → 3 → 4
```

---

## 七、短期应急方案（当前可用）

### 手动补充宏观数据

**步骤1**: 访问官方数据源

| 指标 | 官方来源 | URL |
|------|---------|-----|
| PPI | 国家统计局 | https://data.stats.gov.cn/ |
| PMI | 国家统计局 | https://data.stats.gov.cn/ |
| Industrial | 国家统计局 | https://data.stats.gov.cn/ |
| CPI | 国家统计局 | https://data.stats.gov.cn/ |
| BDI | Investing.com | https://www.investing.com/indices/baltic-dry |
| RRR | 央行官网 | http://www.pbc.gov.cn/ |
| 逆回购 | 央行公开市场 | http://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/index.html |
| TSF | 央行统计 | http://www.pbc.gov.cn/diaochatongjisi/116219/index.html |
| M2 | 央行统计 | http://www.pbc.gov.cn/diaochatongjisi/116219/index.html |

**步骤2**: 手动修改JSON文件

```bash
# 编辑market_data.json
code data/20251112_market_data_final_enhanced.json
```

```json
{
  "macro_indicators": {
    "ppi": {
      "indicator_name": "PPI",
      "current_value": -2.8,        // 手动填入实际值
      "previous_value": -2.7,
      "change_rate": -0.1,
      "unit": "%",
      "date": "2025-10-31",
      "source": "国家统计局手动获取",
      "is_estimated": false          // 改为false
    },
    "pmi": {
      "indicator_name": "PMI",
      "current_value": 50.1,         // 手动填入
      "unit": "点",
      "is_estimated": false
    }
    // ... 其余7个指标
  }
}
```

**步骤3**: 重新运行Stage 2

```bash
python scripts/stage2_pring_analyzer_standalone.py \
  --input data/20251112_market_data_final_enhanced.json \
  --output data/20251112_pring_result.json
```

**步骤4**: 重新生成报告

```bash
python scripts/stage3_report_generator.py \
  --market-data data/20251112_market_data_final_enhanced.json \
  --pring-result data/20251112_pring_result.json \
  --output reports/20251112背景扫描120_完整版.md
```

---

## 八、总结

### 🔍 问题根源

**Stage 2设计预期**: 自动检测占位符 → 调用WebSearch → 填充数据 → 执行Pring分析

**实际实现状态**: 检测占位符 ✅ → ~~调用WebSearch~~ ❌ (TODO注释) → 数据仍然None → Pring分析失败

### 📊 影响范围

| 受影响组件 | 影响程度 | 表现 |
|-----------|---------|------|
| 第一层（库存周期）| 100% | 5个指标全部None，评分0/60 |
| 第二层（货币周期）| 100% | 4个指标全部None，评分0/100 |
| 第三层（Pring信号）| 67% | 债券/商品信号缺失，仅股票可用 |
| 最终Pring判定 | 100% | 输出"分析失败"，置信度0% |
| 报告生成 | 30% | 第八章降级为参考判定（60%置信度） |

### ✅ 推荐解决方案

**长期方案**: **方案3 - 创建Stage 1.5** (架构最清晰，职责最明确)

**中期方案**: **方案1 - 激活Stage 2的WebSearch** (最快实现，符合原设计)

**短期应急**: **手动补充JSON** (当前立即可用，3-5分钟完成)

### 🚀 实施优先级

1. **立即**: 使用手动补充方案完成11月12日报告
2. **本周**: 实施方案1，激活Stage 2的WebSearch调用逻辑
3. **下周**: 评估MCP调用限制，必要时切换至方案3

---

**分析完成时间**: 2025-11-13
**下一步行动**: 等待用户选择解决方案后实施
