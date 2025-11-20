# Stage 2a WebSearch降级机制说明

**版本**: V3.3增强版
**更新时间**: 2025-11-12
**优化目标**: 提高数据获取成功率和系统鲁棒性

---

## 一、功能概述

`stage2a_mcp_enhancer.py` 现已增强为具备**智能降级机制**的数据增强器。当MCP工具调用异常时，系统会自动降级到WebSearch，并通过**预配置的可信数据源**获取数据。

### 核心特性

1. **MCP优先策略**: 首次尝试使用MCP工具（WebFetch/WebSearch）获取数据
2. **自动降级**: MCP失败时自动切换到WebSearch备用方案
3. **可信数据源**: 预配置高质量金融数据源（Investing.com, 东方财富, 新浪财经等）
4. **提示词生成**: 自动生成结构化WebSearch提示词，包含搜索关键词和数据源
5. **日志追踪**: 完整记录降级过程，便于审计和调试

---

## 二、支持的数据类型

### 2.1 债券数据

| 代码 | 名称 | 可信数据源 |
|------|------|------------|
| CN10Y | 中国10年期国债 | 中国债券信息网 (yield.chinabond.com.cn)<br>cn.investing.com<br>eastmoney.com |
| CN10Y_CDB | 中国10年期国开债 | 中国债券信息网<br>cn.investing.com<br>eastmoney.com |

### 2.2 商品数据

| 代码 | 名称 | 可信数据源 |
|------|------|------------|
| GC=F | COMEX黄金 | cn.investing.com COMEX黄金期货<br>finance.sina.com.cn<br>eastmoney.com |
| CL=F | WTI原油 | cn.investing.com WTI原油期货<br>finance.sina.com.cn<br>eastmoney.com |
| BZ=F | Brent原油 | cn.investing.com Brent原油期货<br>finance.sina.com.cn<br>eastmoney.com |
| HG=F | COMEX铜 | cn.investing.com COMEX铜期货<br>finance.sina.com.cn<br>eastmoney.com |
| BCOM | BCOM指数 | bloomberg.com<br>cn.investing.com<br>finance.yahoo.com |

---

## 三、工作流程

```
┌─────────────────────────────────────────────────────────┐
│           Stage 2a 数据增强流程 (V3.3)                  │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │  扫描占位符数据       │
                 │  (债券+商品)         │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │  生成MCP提示词        │
                 │  (logs/mcp_prompts)  │
                 └──────────┬───────────┘
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │        逐项处理数据填充               │
        └───────┬───────────────────────────────┘
                │
                ▼
        ┌──────────────────┐
        │  尝试MCP获取      │
        │  (WebFetch/Search)│
        └──────┬─────────────┘
               │
               ├─── MCP成功 ───┐
               │                 ▼
               │          ┌────────────┐
               │          │  应用数据   │
               │          │  记录来源   │
               │          └────────────┘
               │
               └─── MCP失败 ───┐
                                ▼
                        ┌──────────────────────┐
                        │  WebSearch降级        │
                        │  (自动触发)          │
                        └──────┬───────────────┘
                               │
                               ▼
                        ┌──────────────────────┐
                        │  生成WebSearch提示词  │
                        │  - 搜索关键词         │
                        │  - 可信数据源列表     │
                        │  - 数据格式要求       │
                        └──────┬───────────────┘
                               │
                               ▼
                        ┌──────────────────────┐
                        │  保存到日志文件       │
                        │  (websearch_prompts)  │
                        └──────────────────────┘
```

---

## 四、使用方法

### 4.1 正常执行（无异常）

```bash
# Accurate模式 (推荐)
python scripts/background_scan_unified.py \
    --date 2025-11-12 \
    --output reports/20251112背景扫描120_Accurate.md \
    --enable-mcp
```

**预期输出**:
```
[3/5] 填充债券数据...
  [INFO] 需要获取债券数据: 2 项
    [OK] CN10Y - MCP获取成功
    [OK] CN10Y_CDB - MCP获取成功

[4/5] 填充商品数据...
  [INFO] 需要获取商品数据: 5 项
    [OK] GC=F - MCP获取成功
    [OK] CL=F - MCP获取成功
    ...
```

### 4.2 MCP异常时（自动降级）

当MCP工具不可用或异常时：

```bash
# 同样的命令
python scripts/background_scan_unified.py \
    --date 2025-11-12 \
    --output reports/20251112背景扫描120_Accurate.md \
    --enable-mcp
```

**预期输出（降级模式）**:
```
[3/5] 填充债券数据...
  [INFO] 需要获取债券数据: 2 项
    [MCP失败] CN10Y: Connection timeout
    [降级] 尝试WebSearch获取 CN10Y
    [WebSearch降级] 中国10年期国债 - 使用可信数据源
    [提示] 请手动执行WebSearch: 中国10年期国债收益率 最新 债券
    [提示] 可信数据源: 中国债券信息网 yield.chinabond.com.cn, cn.investing.com 中国10年期国债, eastmoney.com 中国10年国债收益率

[4/5] 填充商品数据...
  [INFO] 需要获取商品数据: 5 项
    [MCP失败] GC=F: WebFetch error
    [降级] 尝试WebSearch获取 GC=F
    [WebSearch降级] COMEX黄金 - 使用可信数据源
    [提示] 请手动执行WebSearch: COMEX黄金期货 最新价格 实时行情
    [提示] 可信数据源: cn.investing.com COMEX黄金期货, finance.sina.com.cn 黄金期货, eastmoney.com COMEX黄金

======================================================================
增强完成:
  - 处理项数: 7
  - 错误数: 2
  - WebSearch降级: 7 项
  - 生成提示词: 7 个

  [提示] WebSearch提示词已保存到日志文件
  [提示] 可查看日志获取详细的搜索关键词和数据源
======================================================================
```

### 4.4 手动结果回写（可选）

当 WebSearch 已由人工或外部工具执行完毕时，可通过 --websearch-results 参数一次性将结果写回 MarketDataContract，避免 Stage 2 再次抓取宏观/货币/大宗数据：

`ash
python scripts/stage2a_mcp_enhancer.py     --market-data data/20251112_stage1_fixed_test.json     --output data/20251112_stage1_manual_enhanced.json     --websearch-results data/websearch_results_20251112.json     --log-output logs/stage2a_20251112_manual_log.json
`

websearch_results_*.json 结构示例如下：

`json
{
  "macro_indicators": {
    "ppi": {
      "current_value": -2.5,
      "previous_value": -2.9,
      "change_rate": 0.4,
      "unit": "%",
      "date": "2025-10-31",
      "source": "stats.gov.cn"
    }
  },
  "monetary_policy": {
    "m2": {
      "current_value": 8.7,
      "change_from_120d": 0.3,
      "unit": "%",
      "date": "2025-10-31",
      "source": "pbc.gov.cn"
    }
  },
  "bonds": {
    "CN10Y": {
      "current_yield": 2.59,
      "change_5d_bp": -3.1,
      "change_120d_bp": -22.4,
      "trend": "下行",
      "source": "yield.chinabond.com.cn"
    }
  },
  "commodities": {
    "GC=F": {
      "current_price": 2378.6,
      "unit": "$\/oz",
      "daily_change": 0.62,
      "ytd_change": 13.5,
      "trend": "偏强",
      "source": "investing.com",
      "timestamp": "2025-11-12T14:30:00"
    }
  }
}
`

写入逻辑：

1. 支持 macro_indicators、monetary_policy、onds、commodities 四大类字段，并自动将 is_estimated=False。
2. metadata.missing_items 会同步清理，data_completeness 重新计算，Stage 2 可直接复用填充完毕的 JSON。
3. enhancement_log 中会新增 manual_results_file 与 manual_updates，方便追溯每一次手工补数。


---

## 五、配置扩展

如需添加新的可信数据源，编辑 `stage2a_mcp_enhancer.py` 的 `trusted_sources` 配置：

```python
self.trusted_sources = {
    'bonds': {
        'CN10Y': {
            'name': '中国10年期国债',
            'sources': [
                '中国债券信息网 yield.chinabond.com.cn',
                'cn.investing.com 中国10年期国债',
                'eastmoney.com 中国10年国债收益率',
                # 添加新数据源
                'your_new_source.com 中国国债'
            ],
            'keywords': '中国10年期国债收益率 最新 债券'
        }
    }
}
```

---

## 六、优势与限制

### ✅ 优势

1. **提高成功率**: MCP失败时不会完全放弃，而是尝试备用方案
2. **数据源可靠**: 预配置的数据源均为业内权威平台
3. **透明可追溯**: 完整记录降级过程和数据来源
4. **灵活扩展**: 易于添加新的可信数据源
5. **用户友好**: 提供清晰的提示词和操作指引

### ⚠️ 限制

1. **手动介入**: WebSearch降级后仍需手动执行搜索（未来可接入自动化WebSearch API）
2. **提示词依赖**: 生成的提示词质量依赖于预配置的搜索关键词
3. **数据格式**: 降级获取的数据可能需要手动格式化

---

## 七、未来增强

1. **自动WebSearch执行**: 集成自动化WebSearch API（如SerpAPI, Google Custom Search）
2. **智能提示词优化**: 根据数据源特点自动生成最优搜索策略
3. **数据验证**: 降级获取的数据自动校验完整性和合理性
4. **多级降级**: WebSearch失败后继续降级到更多备用方案（如TuShare 历史数据），AKShare 通道已停用

---

## 八、故障排查

### 问题1: MCP工具不可用

**表现**: 所有数据项都触发WebSearch降级

**原因**: MCP工具未启动或配置错误

**解决**:
```bash
# 检查MCP配置
echo $MCP_SERVER_URL

# 确认MCP服务可达
curl http://your-mcp-server/health
```

### 问题2: 降级提示词未生成

**表现**: 降级触发但日志中无websearch_prompts字段

**原因**: 数据源配置中缺少对应symbol

**解决**: 检查 `trusted_sources` 配置，确保包含需要的symbol

### 问题3: 数据完整度仍然低

**表现**: 即使降级成功，数据完整度未提升

**原因**: 降级只生成提示词，未实际获取数据

**解决**: 根据提示词手动执行WebSearch，将结果填充到market_data.json

---

## 九、最佳实践

1. **优先使用MCP**: 确保MCP工具正常工作，降级仅作为备用
2. **定期更新数据源**: 监控可信数据源的可用性，及时更新配置
3. **保存降级日志**: 降级日志有助于分析MCP工具的稳定性
4. **验证降级数据**: 手动填充的数据应进行二次验证
5. **监控成功率**: 统计MCP成功率和降级频率，优化配置

---

**文档维护者**: Claude Code
**反馈渠道**: GitHub Issues / Project Documentation
