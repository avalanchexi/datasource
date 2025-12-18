# TODOs (后续优化清单)

- [x] 代码护栏：在 Stage2 入口加入 alias 映射（`industrial_output`→`industrial`），待决定是否长期保留。
- [x] 预检脚本：新增 Stage2 前置检查（无旧键、必填字段齐全、missing_items 与 profiles 对齐），可做为 Make 目标。
- [x] Stage2 回归（2025-12-11，regex/disable_extract）：22 任务均有 Tavily 结果；fund_flow 三项仍被判定 manual_required（需 Stage2.5 补数）。
- [ ] 跑通全链路回归：Stage1→Stage2.5 注入→Stage3，验证 `data_completeness≥0.8`、`gap_monitor` 为空、报告无 N/A。
- [ ] 可选域名微调：USDCNH 视需要补 `hkma.gov.hk`；DR007 若需更强覆盖可设 `search_depth=advanced`；BDI 如要更紧时效可改 `time_range="week"`.
- [ ] 中期收敛：历史数据已清空；若确认无旧键流入，可视情况移除 alias 逻辑、保持定期清理/归档策略。
- [ ] P0 SSL/TLS：tavily_client 增加 `verify`/自定义 CA 开关（默认验证，开发可关闭），文档同步风险提示。
- [ ] P1 注入完整性：commodities/bonds/forex 默认补 change_5d/change_120d=0.0；macro 注入后 `current_value` 为空直接报错；`industrial_sales` 映射到 `macro_indicators`。
- [ ] P1 缺口兜底：Stage2 对 `industrial_sales`、northbound/southbound/etf 空值创建占位并要求手工填真实数。
- [ ] P2 TuShare 稳定性：`index_daily`、`moneyflow_hsgt` 增加 3 次重试 + fallback（yfinance/国开行估值），失败写入 note。
- [ ] P3 数据源兜底：暂不扩展，维持仅用 TuShare；若未来恢复多源，另开任务评估。
