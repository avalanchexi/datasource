# Stage2 资金流向方案（MCP 主通道 + Tavily 复核可选）

## 背景
- AGENTS 要求北向/南向/ETF/融资融券必须走 MCP WebSearch；若缺失或零值需标记“异常零值-需核查”。
- 当前实施（临时）：直接用 Tavily 填写 fund_flow，违背合规且缺少方向/单位校验。
- 目标：恢复 MCP 为主，允许 Tavily 作为复核或应急 fallback，并完善日志、校验与开关。

## 目标
1) 兼容三种模式：tavily（默认）、mcp、hybrid；默认用 Tavily 补数以便离线/无 MCP 场景可用，保留 mcp/hybrid 作为合规或复核选项。
2) 提供 CLI 开关 `--fund-flow-backend {mcp,tavily,hybrid}`，默认 tavily。
3) 数值与方向校验：提取必须包含“亿/亿元”，并基于关键词判定流入/流出符号；低置信度或无单位标记 manual_required。
4) gap_monitor 仅记录未完成/manual_required 任务；fund_flow 失败时提示人工或 MCP 脚本。
5) 审计：task_log 记录 backend/attempt/elapsed/request_id，websearch_results 分片保留原始片段，note 记录复核/异常。

## 待办（TODO）
- [x] 与“统一 JSON”方案对齐：Stage1/Stage2 共用 `market_data.json`，写入时原子写并做时间戳备份（现 `_dump_json(..., backup=True)` 双备份 .bak + 时间戳）。
- [x] CLI：新增 `--fund-flow-backend {mcp,tavily,hybrid}`，默认 tavily；将参数传递给 task planner / executor。
- [x] Planner：fund_flow 任务带上 backend；mcp 模式跳过 Tavily，hybrid/tavily 模式执行搜索。
- [x] Executor：支持 fund_flow 分支：
    - mcp 模式：跳过搜索并写 task_log，标记 manual_required，gap_monitor 记录。
    - hybrid 模式：标记 MCP 未实现，附 note，随后 Tavily 搜索；保留 manual_required。
    - tavily 模式：直接以 Tavily 抽取落地 recent_5d/total_120d/source="tavily+deepseek"。
- [x] 数值解析与方向：对 fund_flow 提取结果做单位检查（需含 “亿”），识别“净流入/净流出/买入/卖出”，0 值或方向缺失→ manual_required。
- [x] gap_monitor：仅 pending/manual 列表；fund_flow 在 mcp 模式必列，在 tavily/hybrid 成功时清除占位并标异常零值。
- [x] 日志：task_log 增加 fund_flow_backend/attempt_index/elapsed_ms；websearch_results 分片保留 raw_results。
- [ ] 文档：更新 runbook/README/AGENTS 补充 fund_flow backend 说明与命令示例。
- [ ] 测试：新增用例覆盖 mcp/tavily/hybrid 三种模式、单位校验和 manual_required 分支；更新现有集成测试断言。
