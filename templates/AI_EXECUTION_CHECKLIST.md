# AI执行背景扫描报告检查清单

**版本**: V4.0 - 与CLAUDE.md/AGENTS.md流水线一致
**更新日期**: 2025-12-09

---

## 执行总览

### 用户指令
```
执行背景扫描报告生成：YYYY-MM-DD
```

### 执行计划
- **数据窗口**: 120个自然日
- **预期时间**: 3-5分钟
- **输出文件**: `reports/YYYY-MM-DD-背景扫描120.md`

---

## 阶段执行检查清单

### Stage 1: API数据收集 (30-40s)

**命令**:
```bash
DATE=YYYY-MM-DD
DATE_NH=${DATE//-/}
bash run_clean.sh python scripts/stage1_data_collector.py \
  --date "$DATE" \
  --output "data/runs/${DATE_NH}/market_data.json"
```

**检查点**:
- [ ] 输出文件 `data/runs/${DATE_NH}/market_data.json` 存在
- [ ] A股指数数据（000001, 000300, 000016, 399001, 399006, 000905）
- [ ] 美股指数数据（SPX, DJI, IXIC）
- [ ] 基础汇率/债券占位符已创建

---

### Stage 2: structured-provider-first + Tavily/DeepSeek增强 (90-150s)

**命令**:
```bash
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
```

**快速模式（可选，30-60s）**:
```bash
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/${DATE_NH}/market_data.json" \
  --output "data/runs/${DATE_NH}/market_data_stage2.json" \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --extraction-backend regex --disable-extract \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results "data/runs/${DATE_NH}/websearch_results_auto.json" \
  --log-output "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json"
```

**检查点**:
- [ ] 输出文件 `data/runs/${DATE_NH}/market_data_stage2.json` 存在
- [ ] `data/runs/${DATE_NH}/websearch_results_auto.json` 生成
- [ ] 检查 `data/runs/${DATE_NH}/gap_monitor.json` 是否有缺口
- [ ] 优先查看 `stage2_effective_hit_rate`；结构化源同一 key 会顺序兜底，排障时可追加 `--disable-structured-providers`

---

### Stage 2+ (可选): 价格兜底

旧 Yahoo fallback 已归档至 `archive/py_unused/legacy/`，不属于当前 Stage1-4 流程。价格/债券缺口优先通过 Stage2 structured-provider-first、Stage2 搜索链路或 Stage2.5 manual/WebSearch 注入处理。

---

### Stage 2.5: WebSearch注入

**命令**:
```bash
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"
```

**检查点**:
- [ ] `data/runs/${DATE_NH}/websearch_results_manual.json` 已按缺口补充
- [ ] `data/runs/${DATE_NH}/market_data_complete.json` 生成
- [ ] 注入数据项 > 0
- [ ] `metadata.data_completeness` >= 0.8

---

### Stage 3: Pring分析 (15-25s)

**命令**:
```bash
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated \
  --skip-fund-flow-check
```

**检查点**:
- [ ] `data/runs/${DATE_NH}/pring_result.json` 生成
- [ ] Pring阶段已判定（Stage I-VI）
- [ ] 库存周期评分已计算

---

### Stage 4: 报告生成 (10-15s)

**命令**:
```bash
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md" \
  --allow-fund-flow-downgrade
```

**检查点**:
- [ ] `reports/${DATE}-背景扫描120.md` 生成
- [ ] 文件大小约 4800-5200 bytes

---

### 验证

**命令**:
```bash
cat "data/runs/${DATE_NH}/gap_monitor.json"  # 应无 pending_tasks/manual_required
test -s "reports/${DATE}-背景扫描120.md"
```

**最终检查**:
- [ ] `gap_monitor` 为空或只有少量非关键缺口
- [ ] 报告中无 "N/A（待 WebSearch）"
- [ ] 9个标准章节齐全

---

## 报告结构验证

**必需章节**:
- [ ] 核心结论
- [ ] 股票市场
- [ ] 商品与黄金
- [ ] 债券市场
- [ ] 外汇市场
- [ ] 宏观经济指标
- [ ] 货币政策
- [ ] Pring三层框架
- [ ] 资金流向

---

## 数据质量标准

### WebSearch JSON格式（关键）

| 类别 | 必填字段 | 示例 |
|------|---------|------|
| commodities | `symbol`, `name`, `current_price`, `unit` | `{"symbol": "GC=F", "current_price": 2650.5}` |
| forex | `pair`, `name`, `current_rate` | `{"pair": "USDCNY", "current_rate": 7.248}` |
| bonds | `symbol`, `name`, `current_yield` | `{"symbol": "US10Y", "current_yield": 4.18}` |
| fund_flow | `recent_5d`, `total_120d`, `trend`, `source` | `{"recent_5d": 85.6, "total_120d": 1250.0}` |

**注意**: 数值字段必须为可解析数字，不能是描述性文本。

---

## 常见问题处理

| 问题 | 解决方案 |
|------|----------|
| Stage2超时 | 使用 `--extraction-backend regex --disable-extract` |
| structured provider 排障 | 添加 `--disable-structured-providers` 只跑原搜索链路 |
| Tavily 422错误 | 添加 `--disable-extract` |
| 数据完整度<80% | 检查并补充 macro/monetary 字段 |
| 报告显示N/A | 检查 gap_monitor，确保数值字段 |

---

## 执行完成确认

- [ ] 所有Stage完成
- [ ] gap_monitor为空
- [ ] 报告文件存在且大小正常
- [ ] 无N/A值

**AI执行状态**: ✅ **成功完成**
