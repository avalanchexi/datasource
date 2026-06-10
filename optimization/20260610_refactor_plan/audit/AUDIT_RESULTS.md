# 批次 0 功能有效性审计结果

- 口径:coverage >= 20% 记为 runtime_used(启发式,边缘值人工复核)
- 运行时证据仅来自离线回放 Stage2.5 -> Stage3 -> Stage4 report;Stage1/Stage2 专属模块最高只能定为 reachable_not_run
- 局限:importlib/动态导入静态不可见

## 总览

| 档位 | 模块数 |
|---|---|
| runtime_used | 39 |
| imported_only | 4 |
| reachable_not_run | 16 |
| unreachable | 34 |

## 1.2 疑似清单定档

| 模块 | 档位 | coverage | 被谁引用 |
|---|---|---|---|
| datasource.mcp_adapter | unreachable | 0.0% | (无) |
| datasource.utils.mcp_tools | unreachable | 0.0% | datasource.utils.data_completion |
| datasource.utils.yahoo_finance | imported_only | 17.0% | datasource.adapters.international_finance_adapter, datasource.calculators.fund_flow_calculator, datasource.utils.data_completion |
| datasource.utils.dns_patch | runtime_used | 21.3% | datasource, datasource.utils.tushare_patch |
| datasource.utils.tushare_patch | runtime_used | 41.7% | datasource.adapters.tushare_adapter |
| datasource.engines.data_engine | unreachable | 0.0% | datasource.generators.report_generator |
| datasource.cache.memory_cache | runtime_used | 53.1% | datasource.adapters.international_finance_adapter, datasource.adapters.tavily_client, datasource.adapters.tushare_adapter, scripts/stage2_unified_enhancer.py |
| datasource.cache.sqlite_cache | reachable_not_run | 0.0% | scripts/stage2_unified_enhancer.py |
| datasource.analyzers.long_term_analyzer | unreachable | 0.0% | datasource.analyzers |
| datasource.comparators.international_comparator | unreachable | 0.0% | datasource.comparators |
| datasource.mappers.industry_rotation_mapper | unreachable | 0.0% | datasource.mappers |
| datasource.warnings.systemic_risk_monitor | unreachable | 0.0% | datasource.warnings |
| datasource.generators.report_generator | unreachable | 0.0% | (无) |
| datasource.generators.simple_report | runtime_used | 59.8% | scripts/stage4_report_generator.py |

## unreachable 全列表

- `datasource.agents`(src/datasource/agents/__init__.py)— 引用方: 无引用
- `datasource.agents.background_scan`(src/datasource/agents/background_scan/__init__.py)— 引用方: 无引用
- `datasource.agents.background_scan.agent`(src/datasource/agents/background_scan/agent.py)— 引用方: datasource.agents, datasource.agents.background_scan
- `datasource.agents.background_scan.config`(src/datasource/agents/background_scan/config.py)— 引用方: datasource.agents.background_scan, datasource.agents.background_scan.agent
- `datasource.analyzers`(src/datasource/analyzers/__init__.py)— 引用方: 无引用
- `datasource.analyzers.long_term_analyzer`(src/datasource/analyzers/long_term_analyzer.py)— 引用方: datasource.analyzers
- `datasource.calculators.bond_calculator`(src/datasource/calculators/bond_calculator.py)— 引用方: datasource.engines.data_engine
- `datasource.calculators.economic_cycle_analyzer`(src/datasource/calculators/economic_cycle_analyzer.py)— 引用方: 无引用
- `datasource.calculators.fund_flow_calculator`(src/datasource/calculators/fund_flow_calculator.py)— 引用方: datasource.engines.data_engine
- `datasource.comparators`(src/datasource/comparators/__init__.py)— 引用方: 无引用
- `datasource.comparators.international_comparator`(src/datasource/comparators/international_comparator.py)— 引用方: datasource.comparators
- `datasource.engines.data_engine`(src/datasource/engines/data_engine.py)— 引用方: datasource.generators.report_generator
- `datasource.generators.report_generator`(src/datasource/generators/report_generator.py)— 引用方: 无引用
- `datasource.mappers`(src/datasource/mappers/__init__.py)— 引用方: datasource.mappers.industry_rotation_mapper
- `datasource.mappers.industry_rotation_mapper`(src/datasource/mappers/industry_rotation_mapper.py)— 引用方: datasource.mappers
- `datasource.mcp_adapter`(src/datasource/mcp_adapter.py)— 引用方: 无引用
- `datasource.models.pring_result_contract`(src/datasource/models/pring_result_contract.py)— 引用方: 无引用
- `datasource.providers.stage2_structured.cdb_estimator`(src/datasource/providers/stage2_structured/cdb_estimator.py)— 引用方: 无引用
- `datasource.providers.stage2_structured.chinabond`(src/datasource/providers/stage2_structured/chinabond.py)— 引用方: datasource.providers.stage2_structured.cdb_estimator
- `datasource.providers.stage2_structured.eastmoney_etf`(src/datasource/providers/stage2_structured/eastmoney_etf.py)— 引用方: 无引用
- `datasource.providers.stage2_structured.http_fetcher`(src/datasource/providers/stage2_structured/http_fetcher.py)— 引用方: datasource.providers.stage2_structured.chinabond, datasource.providers.stage2_structured.eastmoney_etf, datasource.providers.stage2_structured.market_quote_pages
- `datasource.providers.stage2_structured.market_quote_pages`(src/datasource/providers/stage2_structured/market_quote_pages.py)— 引用方: 无引用
- `datasource.providers.stage2_structured.official_china`(src/datasource/providers/stage2_structured/official_china.py)— 引用方: 无引用
- `datasource.providers.stage2_structured.source_tiers`(src/datasource/providers/stage2_structured/source_tiers.py)— 引用方: datasource.providers.stage2_structured.cdb_estimator, datasource.providers.stage2_structured.chinabond, datasource.providers.stage2_structured.eastmoney_etf
- `datasource.providers.stage2_structured.stooq`(src/datasource/providers/stage2_structured/stooq.py)— 引用方: 无引用
- `datasource.providers.stage2_structured.trading_economics`(src/datasource/providers/stage2_structured/trading_economics.py)— 引用方: 无引用
- `datasource.providers.stage2_structured.tushare_etf`(src/datasource/providers/stage2_structured/tushare_etf.py)— 引用方: 无引用
- `datasource.providers.stage2_structured.yahoo_finance`(src/datasource/providers/stage2_structured/yahoo_finance.py)— 引用方: 无引用
- `datasource.trackers`(src/datasource/trackers/__init__.py)— 引用方: 无引用
- `datasource.trackers.policy_tracker`(src/datasource/trackers/policy_tracker.py)— 引用方: datasource.trackers
- `datasource.utils.data_completion`(src/datasource/utils/data_completion.py)— 引用方: 无引用
- `datasource.utils.mcp_tools`(src/datasource/utils/mcp_tools.py)— 引用方: datasource.utils.data_completion
- `datasource.warnings`(src/datasource/warnings/__init__.py)— 引用方: 无引用
- `datasource.warnings.systemic_risk_monitor`(src/datasource/warnings/systemic_risk_monitor.py)— 引用方: datasource.warnings

## imported_only 全列表

- `datasource.adapters.international_finance_adapter`(src/datasource/adapters/international_finance_adapter.py)— 引用方: datasource, datasource.manager
- `datasource.utils.missing_items`(src/datasource/utils/missing_items.py)— 引用方: scripts/stage2_5_injector.py, scripts/stage2_unified_enhancer.py, scripts/stage3_pring_analyzer.py
- `datasource.utils.source_trust`(src/datasource/utils/source_trust.py)— 引用方: scripts/stage2_5_injector.py, scripts/stage2_unified_enhancer.py
- `datasource.utils.yahoo_finance`(src/datasource/utils/yahoo_finance.py)— 引用方: datasource.adapters.international_finance_adapter, datasource.calculators.fund_flow_calculator, datasource.utils.data_completion

## reachable_not_run 全列表

- `datasource.adapters.exa_client`(src/datasource/adapters/exa_client.py)— 引用方: scripts/stage2_unified_enhancer.py
- `datasource.adapters.tavily_client`(src/datasource/adapters/tavily_client.py)— 引用方: scripts/stage2_unified_enhancer.py
- `datasource.cache.sqlite_cache`(src/datasource/cache/sqlite_cache.py)— 引用方: scripts/stage2_unified_enhancer.py
- `datasource.calculators.technical_indicators`(src/datasource/calculators/technical_indicators.py)— 引用方: datasource.analyzers.long_term_analyzer, datasource.calculators.economic_cycle_analyzer, datasource.comparators.international_comparator
- `datasource.config.search_profiles`(src/datasource/config/search_profiles.py)— 引用方: datasource.engines.stage2_task_planner, scripts/check_stage2_inputs.py
- `datasource.engines.deepseek_reasoner`(src/datasource/engines/deepseek_reasoner.py)— 引用方: datasource.engines.stage2_lc_pipeline, scripts/stage2_unified_enhancer.py
- `datasource.engines.stage2_lc_pipeline`(src/datasource/engines/stage2_lc_pipeline.py)— 引用方: scripts/stage2_unified_enhancer.py
- `datasource.engines.stage2_task_planner`(src/datasource/engines/stage2_task_planner.py)— 引用方: scripts/stage2_unified_enhancer.py
- `datasource.providers.stage2_structured`(src/datasource/providers/stage2_structured/__init__.py)— 引用方: scripts/stage2_unified_enhancer.py
- `datasource.providers.stage2_structured.base`(src/datasource/providers/stage2_structured/base.py)— 引用方: datasource.providers.stage2_structured, datasource.providers.stage2_structured.cdb_estimator, datasource.providers.stage2_structured.chinabond
- `datasource.providers.stage2_structured.registry`(src/datasource/providers/stage2_structured/registry.py)— 引用方: datasource.providers.stage2_structured
- `datasource.utils.json_io`(src/datasource/utils/json_io.py)— 引用方: scripts/backfill_fund_flow_series.py, scripts/recap_consistency_check.py, scripts/stage2_low_score_audit.py
- `datasource.utils.observability`(src/datasource/utils/observability.py)— 引用方: scripts/stage2_unified_enhancer.py
- `datasource.utils.run_snapshot`(src/datasource/utils/run_snapshot.py)— 引用方: scripts/stage2_unified_enhancer.py
- `datasource.utils.source_conflicts`(src/datasource/utils/source_conflicts.py)— 引用方: scripts/stage2_unified_enhancer.py
- `datasource.utils.source_priority`(src/datasource/utils/source_priority.py)— 引用方: datasource.utils.source_conflicts
