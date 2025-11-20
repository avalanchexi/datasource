# Stage 2 Unified Debug TODOs

> 目的：基于 2025-11-20 联调结果（Tavily 请求超时、未补数）补齐网络、观测与复跑能力。当前代码骨架位于 `scripts/stage2_unified_enhancer.py`、`src/datasource/adapters/tavily_client.py`、`src/datasource/engines/stage2_task_planner.py` 等。

## 现状摘要（2025-11-20）
- Tavily 调用因外网超时未返回，9 个任务均 pending，`stage_task_log.jsonl` 仅有 error 占位；gap_monitor 未清空。
- CLI 缺少代理配置、retry、request_id/耗时日志；无法区分“未执行”与“执行失败”。
- 资金流向仅标记“异常零值-需核查”，未触发 MCP 复跑提示。
（已更新：代理回退兼容、重试与日志增强落地，重新跑后 9 任务成功 6，缺口可补；gap_monitor 现仅记录未完成项。剩余主要待办见下。）

## 网络与环境
- [x] `scripts/setup_stage2_search_env.py` 增加代理探测（HTTP/HTTPS_PROXY、NO_PROXY）输出。
- [x] `scripts/stage2_unified_enhancer.py` 支持 `--http-proxy/--https-proxy`（高于 env），透传给 `AsyncTavilyClient`。  
  *代码指引*: tavily_client 初始化新增 proxies；enhancer argparse 增加参数并下传。
- [x] Tavily 客户端增加 connect/read timeout 可调。  
  *代码指引*: `src/datasource/adapters/tavily_client.py`。

## 任务执行与重跑
- [x] 为搜索任务添加 retry（默认 2 次），失败标记 `manual_required`（gap monitor 合并待补）。  
  *代码指引*: `_execute_tasks` in `stage2_unified_enhancer.py`。
- [x] CLI 增加 `--resume-from-task-file` / `--tasks <id1,id2>`，支持只重跑特定任务。  
  *代码指引*: `Stage2TaskPlanner` + enhancer 参数解析。
- [ ] fund_flow 任务：若 MCP 返回零值，状态置 `manual_required` 并提示运行 `scripts/utility/background_scan_120d_generator.py`。  
  *代码指引*: `_flag_fund_flow_anomalies`。

## 观测与日志
- [x] `stage_task_log.jsonl` 追加 `request_id`/HTTP status/耗时(ms)/`attempt_index`。  
  *代码指引*: `_execute_tasks` & Tavily 客户端返回结构。
- [x] `reports/websearch_results_auto.json` 拆分 per-task (`reports/websearch_results/{task_id}.json`)，summary 记录 proxy/失败。  
  *代码指引*: enhancer 写文件逻辑。
- [ ] CLI 结束时打印人类可读表格并统计平均耗时、缓存命中率（当前仅基础表格）。  
  *代码指引*: main() 尾部 summary。

## CLI 体验
- [x] 缺少密钥时报错退出；新增 `--dry-run`。  
  *代码指引*: main() 参数检查。
- [x] gap_monitor 仍有未完成任务时返回非零 exit code。  
- [ ] 友好提示 `.env` 路径/示例命令（文案待补）。

## 测试
- [ ] httpx mock：模拟超时/代理错误，验证 retry & manual_required 落盘。  
  *测试文件*: 新增 `tests/test_stage2_network_failures.py`。
- [ ] TaskPlanner 单测补充 phase 过滤、去重、fund_flow 跳过。  
  *测试文件*: `tests/test_stage2_unified.py` 可扩展。
- [ ] 集成测试：使用 Tavily stub，确认 request_id/attempt 写入 `websearch_results` 与 `stage_task_log.jsonl`。  
  *测试文件*: `tests/test_stage2_unified_pipeline.py` 扩展。

## Fund Flow 专项（规划见 stage2_fund_flow_plan.md）
- [x] CLI 增加 `--fund-flow-backend {mcp,tavily,hybrid}`，默认 tavily。
- [x] Planner/Executor 按 backend 控制执行/回写；低置信度记 manual_required。
- [x] 数值/单位/方向校验，低置信度或无“亿”单位标记 manual_required。
- [x] gap_monitor 只保留未完成/manual fund_flow；task_log 记录 backend。
- [ ] 文档/README 更新命令示例与合规说明；新增测试覆盖三种 backend。

## 文档
- [ ] `docs/stage2_unified_runbook.md` 增“代理与网络调试”章节，示例 WSL 永久代理设置与 Key 加载顺序。
- [ ] README Stage2 示例下补充 “缺口重跑 (--resume) / 查看 logs/stage_task_log.jsonl” 提示。
