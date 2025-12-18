# search_profiles.py 优化（2025-12-11）

## 背景
- 结合 Tavily 官方最佳实践（search/extract），在查询阶段通过更细的时间窗口与自动参数调优提升命中率。
- 用户提供的 ChatGPT 链接无法直接访问，如有额外要求请补充要点。

## 已做调整
- Tavily 参数层：新增 `days` 透传，实时类默认 2 天；资金流/两融 1 天；LC pipeline 兼容旧版 SDK（不支持 days 自动重试）。
- 自动参数：实时类默认 `auto_parameters=True`；资金流四项继续手动参数并加 `max_results=6`、`chunks_per_source=3`。
- 域名与别名清洗：将“金十数据”改为 `jin10.com`；USDCNH 去除 CFETS/wise，新增 HKEX/Reuters；US10Y 改用 `cn.reuters.com`+东财；DXY 增补 `eastmoney.com`/`jin10.com` 且添加“洲际交易所”别名；HG=F 补充“芝商所”。
- 时效与频率：商品/指数 `max_age_days` 由 2→3（跨周末容错）；GDP `time_range` 统一为 `quarter`；7天逆回购关闭 `auto_parameters`。
- 冗余清理：删除 `industrial_output` 配置及相关 essential/warning 列表引用，仅保留 `industrial` 一处。

## 建议验证
1) `python -m py_compile src/datasource/config/search_profiles.py src/datasource/engines/stage2_task_planner.py src/datasource/engines/stage2_lc_pipeline.py`
2) 按常规流程跑一次 Stage2（可选 `--tasks northbound,southbound,etf,margin`），观察 websearch_results 是否减少过期链接。
3) 如 Tavily SDK 过旧，确认日志无 TypeError（回退逻辑应生效）；如需强制关闭 days，可在 profile 中设为 None。

## 待确认
- 若需进一步按照 ChatGPT 分析文档细化（例如删除 industrial_output 冗余、追加其他财经媒体域名），可再补充需求后微调。
