# CHANGELOG

## 已完成

- 新增 `run_paths.py`，集中管理运行日输出目录
- Stage1 默认输出切到 `data/runs/YYYYMMDD/`
- Stage2 默认任务文件、自动搜索结果、gap monitor、质量指标、策略评估、运行快照切到 `data/runs/YYYYMMDD/`
- Stage2 默认运行日志、observability、task log 切到 `logs/runs/YYYYMMDD/`
- Stage2 Tavily cache 默认切到 `data/cache/tavily_cache.sqlite`
- Stage2.5 注入后的 gap/quality/policy/observability 刷新切到新目录
- Stage3 默认读取 `data/runs/YYYYMMDD/gap_monitor.json` 与 `policy_evaluation.json`
- Stage3 运行日志切到 `logs/runs/YYYYMMDD/pring_stage3_log.json`
- Stage4 默认报告输出保持 `reports/YYYY-MM-DD-背景扫描120.md`
- `simple_report` 写回的 quality gate / report observability 切到新目录
- `scripts/temp/*` 与 `scripts/archive_unused/*` 已统一迁入 `scripts/archive/`

## 同步更新范围

- 主链路脚本
- 辅助脚本
- 测试包装脚本
- 文档与说明
