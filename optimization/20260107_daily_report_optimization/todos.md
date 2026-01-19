# 日报复盘优化 TODO（2026-01-07）

## 0. 需求确认
- [x] 明确质量指标口径（完整度/时效性/波动合理性/来源权威性）
- [x] 确认输出落库位置与命名规则（reports/logs/data）
- [x] 明确趋势存储形态（不使用 SQLite 的最小滚动窗口结构）
- [x] 明确“120日”为交易日还是自然日（默认交易日）
- [x] 明确最小存储窗口规则（股指200交易日/其余121/资金流120/宏观事件6-12条）
- [x] 确认是否允许新增依赖（默认不新增）

## 0.5 复盘事实校验（防模板化误报）
- [x] 定义“复盘事实来源矩阵”（成功率/阻断原因/估计值/缺口均绑定当天文件）→ `optimization/20260107_daily_report_optimization/复盘模板.md`
- [x] 复盘模板必须输出证据文件路径（如 logs/stage2_unified_log.json、reports/*）→ `optimization/20260107_daily_report_optimization/复盘模板.md`
- [x] 若当日文件缺失（如 policy_evaluation_${DATE}.json），禁止写“阻断结论”→ 模板强制“文件不存在写未触发”
- [x] 新增可选脚本：复盘前对照当日日志/数据做一致性校验（`scripts/recap_consistency_check.py`）

## 1. 趋势数据存储（trend_history）
- [x] 设计目录结构 `data/trend_history/min/{series,events}` 与字段口径（按 symbol 拆文件）
- [x] 实现写入函数（按 `date+symbol` 幂等覆盖）
- [x] 实现窗口裁剪（股指200交易日/其余121/资金流120）
- [x] 实现事件序列存储（宏观/政策最近6-12条）
- [x] 实现禁止从 `reports/*.md` 反向回填的校验
- [x] 单位/口径标准化（资金流亿元、收益率%、外汇收盘价）
- [x] 在 `src/datasource/utils/data_completion.py` 引入 trend_history 补算（change_5d/120d 缺失时优先使用）
- [x] 写入防护：过滤低质量标记、跳过 CN10Y/CN10Y_CDB ETF 代理

## 2. 趋势数据同步与挂载点
- [x] 新增 `scripts/trend_history_scan.py`（Stage1 前扫描缺口，输出 gap 报告）
- [x] Stage1 后部分写入（TuShare可得日频，标记 `is_partial=true`）
- [x] Stage2.5 后最终写入（`inject_websearch_data_test.py` 输出后，标记 `is_partial=false`）
- [x] 交易日历对齐（TuShare `trade_cal`），缺口阈值处理（<100 交易日）
- [x] 首次回补策略（TuShare 可批量回补近1年，WebSearch-only 需日同步累积）

## 1. 数据质量指标体系
- [x] 定义指标字段与阈值（按品类）
- [x] 实现质量指标汇总产出 `reports/quality_metrics_${DATE}.json`
- [x] 可选追加 `reports/quality_trend.csv`（便于时间序列对比）

## 2. 可观测性日志
- [x] 设计 observability 事件结构（指标级耗时/来源/失败类型）
- [x] 在 Stage2/Stage2.5 流程落日志 `logs/observability_${DATE}.json`
- [x] 关键失败类型枚举（422/timeout/empty/parse_error）

## 3. 策略自动化（Policy-as-Code）
- [x] 新增规则配置 `config/policy_rules.yaml`
- [x] 422 自动降级规则（extract → regex）
- [x] 关键缺口红名单规则（阻断 Stage3）
- [x] 异常零值二次搜索/标记规则

## 4. 来源分级与冲突日志
- [x] 建立来源权重表（官方/主流/其他）
- [x] 冲突解决逻辑（按权重择优）
- [x] 输出 `reports/source_conflicts_${DATE}.json`

## 5. 可重复运行与审计
- [x] 运行快照 `reports/run_snapshot_${DATE}.json`
- [x] 记录 CLI/环境摘要/Git 状态/依赖版本
- [x] 屏蔽敏感字段（API keys）

## 6. 校验与回归
- [x] 新增最小单测（字段校验/规则触发/冲突日志/趋势写入与裁剪）
- [x] 增强搜索抽取校验（域名路径过滤/合理区间/关键词命中）
- [ ] 小流量回归：Stage2 → Stage2.5 → Stage3 → Report
- [ ] 复盘一次 422 场景验证自动降级

## 7. WebSearch 待补清单（2026-01-06）
> 说明：TuShare 无法覆盖或当前抽取不可靠的指标，需 WebSearch/MCP 兜底补齐。
- [x] 外汇：USDCNY（在岸）（Tavily→Yahoo 429，改用 Stooq CSV 回补 120 交易日）
- [x] 外汇：USDCNH（离岸）（USDCNY 代理填充，CNH 历史源缺失，标记估计）
- [x] 外汇：DXY（美元指数）（Yahoo Finance chart API `DX-Y.NYB` 取 120 交易日）
- [x] 商品：GC=F（黄金）（Stooq XAUUSD 现货代理，120 交易日）
- [x] 商品：CL=F（WTI）（EIA WTI Spot 日度代理，120 交易日）
- [x] 商品：BZ=F（布伦特）（EIA Brent Spot 日度代理，120 交易日）
- [x] 商品：HG=F（铜）（Yahoo Finance chart API `HG=F` 120 交易日）
- [x] 商品：BCOM（彭博商品指数）（Yahoo Finance chart API `^BCOM` 120 交易日）
- [x] 商品：GSG（商品ETF）（Stooq `gsg.us` 120 交易日）
- [x] 债券：CN10Y（中债10Y）（Yahoo 511010.SS ETF 代理，120 交易日，标记估计）
- [x] 债券：CN10Y_CDB（国开10Y）（Yahoo 511520.SS 政金债ETF 代理，120 交易日，标记估计）
- [x] 宏观：BDI（波罗的海干散货指数）（Yahoo BDRY ETF 代理，120 交易日，标记估计）
- [x] 货币政策：RRR（存款准备金率）
- [x] 货币政策：MLF（1Y）
- [x] 货币政策：Reverse Repo（7D逆回购）
- [x] 资金流向：northbound（北向，日度序列回算 + 新闻当日值覆盖）
- [x] 资金流向：southbound（南向，同花顺日度序列）
- [ ] 资金流向：etf（A股ETF）

## 8. trend_history 缺口（2026-01-06）
> 检查规则：目标日需覆盖 2026-01-06，且窗口满足（stock_indices=200，其余=121，fund_flow=120）
- [ ] macro_indicators/bdi.json：缺少 2026-01-06（last=2026-01-05）
- [ ] commodities/GC=F.json：len 120 < 121
- [ ] commodities/GSG.json：len 120 < 121
- [ ] forex/USDCNY.json：len 120 < 121
- [ ] forex/USDCNH.json：len 120 < 121
- [x] fund_flow/margin_recent_5d.json：len 120 OK
- [x] fund_flow/margin_total_120d.json：len 120 OK

## 9. events 缺口（近 120 日发布）
> 检查规则：events 文件需包含近 120 日内发布记录
- [x] gdp.json：已补齐近 8 季度（含 2025-09-30）

## 10. events 缺口（需补 120 日事件序列）
> 规则：events 文件少于 120 条且对应 daily series 已存在 → 用 series 回填 events
- [x] BZ=F.json（已由 series 回填 120 日）
- [x] CL=F.json（已由 series 回填 120 日）
- [x] HG=F.json（已由 series 回填 120 日）
- [x] CN10Y_CDB.json（已由 series 回填 120 日）

## 11. trend_history 单条记录（需补齐近 120 日内发布）
> 规则：events/series 仅 1 条记录，需要补齐近 120 日内发布记录
- [x] series/fund_flow/margin_recent_5d.json（已补齐 120 条）
- [x] series/fund_flow/margin_total_120d.json（已补齐 120 条）
- [x] events/cpi.json（已补齐 >1 条）
- [x] events/dr007.json（已补齐 >1 条）
- [x] events/gdp.json（已补齐 >1 条）
- [x] events/industrial.json（已补齐 >1 条）
- [x] events/industrial_sales.json（已补齐 >1 条）
- [x] events/m0.json（已补齐 >1 条）
- [x] events/m1.json（已补齐 >1 条）
- [x] events/m2.json（已补齐 >1 条）
- [x] events/pmi.json（已补齐 >1 条）
- [x] events/pmi_new_orders.json（已补齐 >1 条）
- [x] events/pmi_production.json（已补齐 >1 条）
- [x] events/ppi.json（已补齐 >1 条）
- [x] events/reverse_repo.json（已补齐 >1 条）
- [x] events/rrr.json（已补齐 >1 条）
- [x] events/tsf.json（已补齐 >1 条）

## 12. 复盘一致性改进（2025-12-22 经验）
- [x] 注入后清理 `metadata.missing_items`，避免“补齐但仍显示缺口”
- [x] 报告附录输出 `is_estimated=True` 提醒（宏观/货币政策/债券）
- [ ] 复盘生成自动化：从当日日志/数据抽取成功率、阻断原因与估计值清单

## 13. 资产层面 50 字结论（DeepSeek）
- [x] 明确输入摘要字段与优先级（非 TuShare：commodities/forex/bonds/fund_flow）
- [x] 实现趋势推断与结构化摘要生成（缺字段可降级）
- [x] 接入 DeepSeek 生成 <=50 字结论（超长截断）
- [x] 失败兜底模板（超时/空输出/异常）
- [x] 报告生成时写入“资产层面结论”段落
- [x] observability 记录输入摘要、输出文本、耗时、失败原因
- [x] 单测：长度限制/失败降级/缺字段不报错

## 14. 2026-01-12 报告问题修复（trend_history 回读/前值补充/质量闸）
- [x] Stage1 回读 trend_history：对 bonds/forex/commodities/stock_indices 缺失 change_120d(_bp) 的数据补算并回填（`scripts/stage1_data_collector.py`）
- [x] Stage2.5 注入后全量补算：扩展 `inject_websearch_data_test.py`，对所有指标执行 trend_history 缺失回填（开关 `--backfill-trend`，默认开启）
- [x] 宏观/货币政策前值规则：手动注入 JSON 增加 `previous_value` 或 `change_rate` 提示；缺前值时按规则估计并标注 `is_estimated=true`
- [x] 货币政策事件序列补齐：新增/补齐 `data/trend_history/min/events/monetary_policy/*.json`
- [x] 预报告质量闸：报告生成前校验关键字段，缺失则标红并输出“需补数原因”（`generate_simple_report*` 或 `tests/scripts/generate_simple_report_test.py`）
- [x] 失败归因枚举统一：`trend_history_missing/no_previous_value/source_latest_only/manual_incomplete` 写入 `reports/gap_monitor_*.json` 与 `logs/observability_*.json`
- [x] 回归用例：US10Y/CN10Y/CN10Y_CDB 有 121+ 交易日数据时报告不得出现 N/A；宏观/政策缺前值必须标注估计与原因

## 15. 报告缺口补数流程落地（文档/模板/回归）
- [x] 需求文档补充“补数流程（报告生成前置）”与示例
- [x] 提供 WebSearch 手工补数 JSON 模板（含 bonds/macro/monetary 示例）
- [x] 可选脚本：解析 `gap_monitor_${DATE}.json` 输出补数清单（待补字段/推荐来源）
- [x] 回归验证：补数 → 注入 → 报告，`data_quality_issues=0` 且报告无 N/A

## 16. Stage2 Tavily 命中率提升（2026-01-07）
- [x] 复盘日志：统计 `score<阈值` 却仍进入抽取的指标清单与比例（基于 `logs/observability_*.json`）
- [x] `search_profiles` 调整：报价类补充双语 query/ticker，`topic` 从 news 放宽，按指标细化 `days/max_age_days`
- [x] 白名单重排：区分“行情页优先 + 新闻兜底”，避免只命中文章页
- [x] 低相关保护：全部低分时直接 `manual_required` 并写原因（新增 `low_score_drop` 统计）
- [x] 422 降级策略改为“按指标/短窗口”而非全局关闭 extract
- [x] issuer 校验放宽：有数值时只提示不强制失败；补充 USDCNH/MLF/逆回购别名
- [x] observability 补充：记录 `score_min/score_p50/score_p95` 与过滤原因
- [x] 多 query 兜底：同一指标支持 2–3 条 query，行情页优先 → 官方公告 → 新闻兜底
- [x] 支持 `exclude_domains`：报价类屏蔽泛新闻/软广告站点（search_profiles + Tavily client）
- [x] Query 结构标准化模板：中文名 + ticker + price/quote/level + 单位

## 17. 120日变化派生（方案1：Stage2.5 注入后派生）
- [x] 在 `inject_websearch_data_test.py` 增加“注入后派生 120 日变化”的步骤（写入 `market_data_complete.json`）。
- [x] 债券类：从 `trend_history` 的 121 交易日序列首尾计算 `change_120d_bp`（CN10Y/CN10Y_CDB 优先验证）。
- [x] 政策类：事件序列回看 120 日内前值补 `change_from_120d`；无前值则标注 `no_previous_value` 并写明“无前值可比”。
- [x] `gap_monitor`/`observability` 记录派生失败原因（如 `trend_history_missing/no_previous_value`）。
- [x] 参考 `reference_date` 回看窗口，剔除同日记录，避免当日写入污染基准。
- [x] 派生失败不再写 0，占位改为 `None` 并写入 `reason=...`。
- [x] 回归验证：注入 → Stage3 → 报告，CN10Y/CN10Y_CDB/RRR 的 120 日变化不再出现 N/A。
  - 2026-01-15：已通过（报告中 CN10Y/CN10Y_CDB/RRR 120日变化无 N/A/无(估)；逆回购 120日变化已补齐无(估)）。
- [x] 需求文档补充国开债（CN10Y_CDB）计算页（数据源/窗口边界/公式/结果/估计标记）。
