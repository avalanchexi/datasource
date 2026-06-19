# TODOS

## Infrastructure

### PipelineStateContract Manifest State Machine

**What:** Introduce a `run_manifest.json` / `PipelineStateContract` state model as the single source for `missing_items`, `manual_required`, `is_stale`, `is_estimated`, and `gap_monitor`-derived gates.

**Why:** The current refactor will converge on `metadata` as the canonical source while keeping top-level `missing_items` and `gap_monitor` compatibility views. A manifest-level state machine is the cleaner long-term endpoint, but it is larger than the current PR3 migration.

**Context:** The 2026-04-27 engineering review chose a gradual migration: first build a canonical key registry, keep compatibility reads, and derive legacy state views. Revisit the larger 2026-04-08 manifest/state-machine design after PR3 has landed and Stage2.5 -> Stage3 -> Stage4 fixture replay is stable.

**Effort:** L
**Priority:** P2
**Depends on:** PR3 canonical key registry and missing-items migration; deterministic fixture replay for Stage2.5 -> Stage3 -> Stage4.

### Pre-commit Quality Gate

**What:** Add `.pre-commit-config.yaml` for the existing quality commands, including `black`, `flake8`, and `mypy src/datasource/` or their exact project-approved equivalents.

**Why:** Quality commands are documented in AGENTS.md and CLAUDE.md, but they are still manual. Automating them reduces missed checks without mixing tooling changes into behavior-preserving utility extraction.

**Context:** The 2026-04-27 engineering review split pre-commit out of PR1 because the current worktree is large and dirty. First introduction should avoid all-repo formatting churn; prefer scoped hooks or an initial no-format validation mode before widening.

**Effort:** S
**Priority:** P2
**Depends on:** PR1 semantic utils extraction landing separately.

## Completed

- [x] PR-C5 Stage2.5 split: extracted `trend_backfill`, `entry_mergers`, `core`, and `cli`; repointed monkeypatches to owning modules; added re-export identity and qualified-patch reach characterization.
- [x] PR-C6 Stage1 entry slim: relocated the Stage1 collector into `src/datasource/engines/stage1/collector.py` and kept `scripts/stage1_data_collector.py` as a thin entrypoint.
- [x] PR-C7 C terminal cleanup: removed the remaining batch-B path shims, thinned `scripts/stage2_unified_enhancer.py` and `scripts/stage2_5_injector.py` to <=30-line entrypoints, repointed tests/imports/monkeypatches to canonical `engines`/`utils` modules, and completed full validation.
- [x] PR-D1 run directory contract: moved configured scratch outputs outside `data/runs`, added atomic JSON/text writes, and introduced run-dir audit coverage.
- [x] PR-D2 pre-write contract validation: aligned market/Pring contracts with real outputs and hard-fails Stage1/2/2.5/3 main JSON writes before disk, with `--no-validate-output` / `DATASOURCE_NO_VALIDATE_OUTPUT=1` as the documented escape hatch.
- [x] PR-E3 reserve-ratio source hardening: removed Trading Economics `cash-reserve-ratio` fallback, leaving `reserve_ratio` structured dispatch on PBoC `official_china` only, blocked the same wrong-caliber URL in search/validation, and added BCOM fixed-quote regression guards.
