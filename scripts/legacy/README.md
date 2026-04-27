# Legacy Scripts

Scripts in this directory are retained for historical reference and emergency
diagnostics only. They are not active daily pipeline entrypoints.

Use the current daily pipeline instead:

1. Stage1: `scripts/stage1_data_collector.py` -> `data/runs/${DATE_NH}/market_data.json`
2. Stage2: `scripts/stage2_unified_enhancer.py` -> `data/runs/${DATE_NH}/market_data_stage2.json`
   - `--fund-flow-backend tavily` is the only active fund-flow backend.
3. Stage2.5: `scripts/stage2_5_injector.py` -> `data/runs/${DATE_NH}/market_data_complete.json`
4. Stage3: `scripts/stage3_pring_analyzer.py` -> `data/runs/${DATE_NH}/pring_result.json`
5. Stage4: `scripts/stage4_report_generator.py` -> `reports/${DATE}-背景扫描120.md`

`fill_market_data_from_yahoo.py` is a legacy-only emergency fallback. It must
not write final market values directly. If it is used during an incident, any
usable data must be converted into the Stage2.5 WebSearch/manual injection
schema and injected through `scripts/stage2_5_injector.py`, following
`AGENTS.md`.

Older MCP and background-scan scripts in this directory, including
`background_scan_120d.py`, `background_scan_unified.py`,
`run_background_scan_pipeline.py`, `mcp_data_enhancer.py`, and
`stage2_mcp_enhancer.py`, are deprecated. Their active replacement is
Stage2 unified enhancement plus Stage2.5 injection.
