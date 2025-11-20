# 资金流向数据API可用性验证报告

**验证日期**: 2025-10-22
**验证范围**: AKShare、TuShare官方API
**验证方法**: 官方文档查询 + 实际代码测试

---

## 一、官方文档验证结果

### 1. AKShare官方文档

**文档来源**: https://akshare.akfamily.xyz/data/stock/stock.html

#### 北向资金（沪深港通）✅

**可用API**:
- `stock_hsgt_hist_em(symbol='北向资金')` - 北向资金历史数据
- `stock_hsgt_hist_em(symbol='南向资金')` - 南向资金历史数据
- `stock_hsgt_fund_flow_summary_em()` - 资金流向汇总
- `stock_hsgt_hold_stock_em()` - 持股排名
- `stock_hsgt_stock_statistics_em()` - 个股统计

**数据源**: 东方财富网 (data.eastmoney.com/hsgt/)

#### 融资融券✅

**可用API**:
- `stock_margin_sse(start_date, end_date)` - 上交所融资融券汇总
  - 参数: start_date='20010106', end_date='20230922'
  - 返回字段: 信用交易日期, 融资余额, 融资买入额, 融券余额等

- `stock_margin_szse(date)` - 深交所融资融券明细
  - 参数: date='20240411'
  - 返回: 单日明细数据

**数据源**: 上海证券交易所、深圳证券交易所官网

#### ETF资金流向❓

**状态**: AKShare官方文档未明确提供ETF资金流向专用API
**替代方案**: 使用MCP WebSearch获取ETF资金流数据

---

### 2. TuShare官方文档

**文档来源**: https://tushare.pro/document/2

#### 沪深港通资金流向✅

**接口名称**: `moneyflow_hsgt`

**官方说明**:
- **数据更新**: 每天18-20点完成当日更新
- **积分要求**: 2000积分起，5000积分可达到"每分钟500次提取"
- **数据限制**: 每次最多返回300条记录，总量不限制

**输入参数**:
```python
pro.moneyflow_hsgt(
    trade_date='20180125',  # 或使用
    start_date='20180125',
    end_date='20180808'
)
```

**输出字段**:
- 港股通（上海/深圳）
- 沪股通、深股通（百万元）
- 北向资金、南向资金（百万元）

**当前限制**: ⚠️ 测试token积分不足，无法调用

#### 融资融券交易汇总✅

**接口名称**: `margin`

**官方说明**:
- **积分要求**: 2000积分
- **数据来源**: 从证券交易所网站直接获取
- **单次限制**: 最多4000行数据

**输入参数**:
```python
pro.margin(
    trade_date='20181010',  # 或使用
    start_date='20180101',
    end_date='20181010',
    exchange_id='SSE'  # SSE/SZSE/BSE
)
```

**输出字段**:
- 融资余额 (rzye)
- 融资买入额 (rzmre)
- 融资偿还额 (rzche)
- 融券余额 (rqye)
- 融券卖出量 (rqmcl)

**当前限制**: ⚠️ 测试token积分不足，无法调用

---

## 二、实际测试结果

### 测试环境
- Python 3.13.3
- AKShare 最新版
- TuShare Pro (token已配置但积分不足)

### 测试结果汇总

| 数据类型 | AKShare | TuShare | 推荐数据源 | 状态 |
|---------|---------|---------|----------|------|
| 北向资金 | ✅ 2538条记录 | ⚠️ 积分不足 | **AKShare** | 可用 |
| 南向资金 | ✅ 2499条记录 | ⚠️ 积分不足 | **AKShare** | 可用 |
| 融资融券(沪) | ✅ 可用 | ⚠️ 积分不足 | **AKShare** | 可用 |
| 融资融券(深) | ✅ 可用 | ⚠️ 积分不足 | **AKShare** | 可用 |
| ETF资金流 | ❓ 未找到 | ❓ 未确认 | **MCP WebSearch** | 需网络搜索 |

### 详细测试记录

#### 1. 北向资金（AKShare）✅
```python
df = ak.stock_hsgt_hist_em(symbol='北向资金')
# 结果: 2538条记录
# 日期范围: 2014-11-17 至 2025-10-21
# 字段: 日期, 当日成交净买额, 沪股通净流入, 深股通净流入, 历史累计净流入
```

#### 2. 南向资金（AKShare）✅
```python
df = ak.stock_hsgt_hist_em(symbol='南向资金')
# 结果: 2499条记录
# 数据完整可用
```

#### 3. 融资融券（AKShare）✅
```python
# 上交所
df = ak.stock_margin_sse(start_date='20251001', end_date='20251021')
# 结果: 9条记录（10月1-21日工作日）

# 深交所
df = ak.stock_margin_szse(date='20251021')
# 结果: 1条记录（单日明细）
```

#### 4. TuShare测试 ⚠️
```python
# 测试结果: "权限不够，请确认"
# 原因: 当前token积分不足2000分
# 建议: 继续使用AKShare作为主数据源
```

---

## 三、数据质量评估

### AKShare数据质量

#### 优势
1. ✅ **无积分限制**: 完全免费，无需积分
2. ✅ **数据完整**: 北向资金从2014年11月开始，覆盖10年+
3. ✅ **更新及时**: 测试时最新数据到2025-10-21
4. ✅ **调用简单**: 单函数调用即可获取全部历史
5. ✅ **稳定可靠**: 东方财富网数据源，权威可信

#### 劣势
1. ❌ **ETF资金流缺失**: 未提供专门的ETF资金流向API
2. ⚠️ **融资融券分散**: 需要分别调用沪深两个交易所

### TuShare数据质量

#### 优势
1. ✅ **数据权威**: 直接从交易所获取
2. ✅ **接口统一**: 融资融券可以通过exchange_id统一查询

#### 劣势
1. ❌ **积分门槛**: 需要2000+积分
2. ❌ **调用限制**: 每次最多300/4000条，需要循环
3. ❌ **当前不可用**: 测试token积分不足

---

## 四、推荐实施方案

### 方案A: AKShare + MCP混合方案（推荐）✅

**数据源分配**:
1. **北向资金**: AKShare `stock_hsgt_hist_em(symbol='北向资金')`
2. **南向资金**: AKShare `stock_hsgt_hist_em(symbol='南向资金')`
3. **融资融券**: AKShare `stock_margin_sse()` + `stock_margin_szse()`
4. **ETF资金流**: MCP WebSearch（东方财富网、证券时报等）

**优势**:
- ✅ 完全免费，无积分限制
- ✅ 数据完整，覆盖10年+
- ✅ 技术成熟，已在其他部分验证
- ✅ 符合"不使用推测数据"原则

**实施难度**: 低（API已验证可用）

### 方案B: TuShare方案（备选）⚠️

**前提条件**: 升级TuShare token积分至2000+

**数据源分配**:
1. **北向资金**: TuShare `moneyflow_hsgt()`
2. **融资融券**: TuShare `margin()`
3. **ETF资金流**: MCP WebSearch

**优势**:
- ✅ 数据权威性更高
- ✅ 接口更规范

**劣势**:
- ❌ 需要积分升级（成本/时间）
- ❌ 调用次数限制
- ❌ 需要处理分页逻辑

**实施难度**: 中（需积分升级）

---

## 五、实施建议

### 立即可执行（方案A）

#### 1. 扩展AKShare适配器
在 `src/datasource/adapters/akshare_adapter.py` 中新增方法:

```python
async def get_hsgt_flow(self, symbol: str = '北向资金', **kwargs) -> DataResponse:
    """获取沪深港通资金流向

    Args:
        symbol: '北向资金' 或 '南向资金'
    """
    cache_key_str = cache_key("hsgt_flow", symbol, **kwargs)
    data = await self._execute_with_cache_and_rate_limit(
        ak.stock_hsgt_hist_em, cache_key_str, symbol=symbol
    )
    return DataResponse(data=data, source=self.name, metadata={...})

async def get_margin_summary(self, start_date: str, end_date: str,
                             exchange: str = 'both', **kwargs) -> DataResponse:
    """获取融资融券汇总数据

    Args:
        exchange: 'sse', 'szse', 或 'both'
    """
    if exchange in ['sse', 'both']:
        sse_data = await self._execute_with_cache_and_rate_limit(
            ak.stock_margin_sse, ...,
            start_date=start_date, end_date=end_date
        )
    # 合并沪深数据...
```

#### 2. 更新报告生成器
在 `scripts/utility/background_scan_120d_generator.py` 中集成:

```python
async def collect_fund_flow_data(self) -> Dict[str, Any]:
    """收集资金流向数据"""

    # 北向资金
    north_response = await self.manager.get_hsgt_flow(symbol='北向资金')

    # 南向资金
    south_response = await self.manager.get_hsgt_flow(symbol='南向资金')

    # 融资融券
    margin_response = await self.manager.get_margin_summary(
        start_date=self.start_date,
        end_date=self.end_date,
        exchange='both'
    )

    # ETF资金流 - 使用MCP WebSearch
    etf_flow = await self.get_etf_flow_from_web()

    return {...}
```

#### 3. 数据验证规则
- ✅ 使用官方API数据（AKShare）
- ✅ 对比MCP WebSearch数据进行交叉验证
- ❌ 不使用估算、推测、历史平均等模拟数据
- ❌ 数据缺失时明确标注"N/A"或"数据获取中"

---

## 六、总结

### 核心结论

1. **AKShare完全满足需求**: 北向资金、南向资金、融资融券三大数据源已验证可用
2. **无需依赖TuShare**: 当前token积分不足，AKShare可完全替代
3. **ETF需MCP补充**: 使用WebSearch获取，符合V2.1 MCP增强规范
4. **数据真实可靠**: 所有数据来自官方API，无推测成分

### 下一步行动

1. ✅ **立即执行**: 扩展AKShare适配器（1-2小时）
2. ✅ **集成报告器**: 更新120日背景扫描生成器（1小时）
3. ✅ **测试验证**: 生成完整报告并验证数据（30分钟）
4. 📝 **文档更新**: 更新CLAUDE.md和技术文档

---

**报告结论**: ✅ 方案A（AKShare + MCP混合）可立即实施，数据质量有保障，符合"不使用推测数据"原则。
