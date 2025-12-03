# Stage3 Pring 改造 TODO 跟踪

> 依据：docs/stage3pring分析优化.md（v0.1, 2025-11-23）
> 说明：完成一项将状态改为 `[x]` 并简要记录提交/验证方式。

## 任务清单
1. [x] 启动前数据完整性前置检查
   - 读取 market_data_complete.json 的 metadata/missing_items/data_completeness
   - 若缺口或 completeness < 阈值，提示“先执行 Stage2/Stage2.5 WebSearch/补数”并退出（提供示例命令）
   - 保持与 gap_monitor 校验一致，生成友好错误信息和日志记录

2. [x] 数据守卫与完整性收紧
   - 实值计分，移除 websearch_queries 计数
   - 禁用模拟/占位返回；阈值默认 0.8 可配置
   - 校验 ai_websearch_enhanced / gap_monitor 未清则阻断

3. [x] CLI 增强
   - 新增参数：--days --min-completeness --allow-fallback --gap-monitor --skip-gap-check --legacy-stage-rules
   - 默认值：days=120, min-completeness=0.8, allow-fallback=false

4. [x] 宏观六阶段判定与一致性约束
   - 实现 determine_macro_stage（三向向量匹配 1–6）
   - 扩展 _enforce_stage_consistency，结合宏观/库存/货币限制极端阶段
   - 保留 legacy 回滚

5. [x] 阶段打分与领先指标调整
   - 加权打分：inventory 0.35 / monetary 0.35 / asset 0.30（可配置）
   - 领先指标冲突置 flat；仅微调置信度/±1 档

6. [x] 输出契约对齐
   - 输出完整字段：asset_signals, asset_allocation_pct, leading_indicator/summary, pending_websearch, data_completeness, fallback_used
   - metadata 增加 ai_websearch_enhanced, gap_monitor_cleared, min_completeness, weights_version；保留旧键
   - 更新 PringResultContract 扩展字段（pending_websearch/data_completeness/fallback_used/leading_indicator/weights_version）

7. [x] 日志与可观测性
   - 生成 reports/pring_stage3_log.json（单次覆盖，含 completeness/stage/data_sources/runtime 等）
   - stdout 精简为读取→校验→阶段→置信度

8. [x] 依赖链更新
   - background_scan_unified.py 调用已对齐新参数
   - Stage4 报告脚本改用 datasource.generators.simple_report
   - 简化报告生成迁移到 src/datasource/generators/simple_report.py，测试包装保留

9. [ ] 测试矩阵落地
   - UT：缺宏观/缺货币阻断；资产信号冲突收敛；领先指标冲突 flat；--days 90 覆盖（已新增宏观/权重/冲突 UT，仍需 --days 90 与 legacy 对比）
   - 集成：样本A（Ⅲ±1, conf≥0.6）；样本B（缺 M1/M2 阻断）；样本C（legacy 对比）（已添加简易报告集成 A/B/C，仍需基于真实数据验证）
   - MR 附回测权重表与结果对比

10. [ ] 性能与禁网确认
   - 确保 Stage3 无外部请求；耗时≤5s；日志记录 runtime

## 记录规范
- 完成项请注明：提交哈希/PR 链接、验证命令、样本数据或测试用例。
- 如需拆分子任务，可在对应条目下追加子弹。 
