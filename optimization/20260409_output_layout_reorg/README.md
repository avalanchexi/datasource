# 2026-04-09 Output Layout Reorg

本目录记录本次“输出路径统一 + 脚本归档”改造的落地情况。

目标：

- 机器产物统一落到 `data/runs/YYYYMMDD/`
- 运行日志统一落到 `logs/runs/YYYYMMDD/`
- Markdown 报告继续平铺在 `reports/`
- `reports/` 不再承载机器 JSON
- `scripts/temp/` 与 `scripts/archive_unused/` 统一并入 `scripts/archive/`

本次新增公共路径模块：

- `src/datasource/utils/run_paths.py`

主链路约定：

- Stage1: `data/runs/YYYYMMDD/market_data.json`
- Stage2: `data/runs/YYYYMMDD/market_data_stage2.json`
- Stage2.5: `data/runs/YYYYMMDD/market_data_complete.json`
- Stage3: `data/runs/YYYYMMDD/pring_result.json`
- Stage4: `reports/YYYY-MM-DD-背景扫描120.md`
