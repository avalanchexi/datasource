# 报告生成问题记录（2025-11-20）

## 执行步骤
- `PYTHONPATH=src python3 scripts/stage3_pring_analyzer.py`
- `PYTHONPATH=.:src python3 scripts/stage4_report_generator.py`

## 发现的问题
- Stage4 默认 `PYTHONPATH` 未包含仓库根目录，直接运行报 `ModuleNotFoundError: generate_simple_report`，需临时设定 `PYTHONPATH=.:src`。
- 数据完整性仍低（约 23.8%）：商品行情 (CL/BZ/HG/BCOM/GSG) 与部分宏观指标（工业增加值、工业营收、BDI、逆回购、MLF、RRR）缺失，Stage3 以默认评分或警告处理。
- 资金流向数据为手工填充（tavily+deepseek 标记），需后续用 MCP/Tavily 实值替换以提升可信度。

## 处理与建议
- 已通过设置 `PYTHONPATH=.:src` 生成当日报告 `reports/background_scan_120.md`，报告日期 2025-11-20。
- 建议后续：
  1) 用 `--fund-flow-backend mcp` 跑一次 Stage2 或手工输入真实资金流，再重跑 Stage3/4。
  2) 重跑 Stage2（tavily）补齐商品与宏观缺口，检查 `gap_monitor` 必须为空后再生成报告。
  3) 如需避免每次手动设置路径，可在 Stage4 脚本内添加 `sys.path.append('.')` 或更新运行手册注明 `PYTHONPATH=.:src`。
