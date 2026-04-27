# TODOs For This Refactor Plan

These are deferred from the 2026-04-27 engineering review. They are intentionally outside the first implementation sequence.

## Infrastructure

### PipelineStateContract Manifest State Machine

**What:** Introduce a `run_manifest.json` / `PipelineStateContract` state model as the single source for `missing_items`, `manual_required`, `is_stale`, `is_estimated`, and `gap_monitor`-derived gates.

**Why:** The current refactor will converge on `metadata` as the canonical source while keeping top-level `missing_items` and `gap_monitor` compatibility views. A manifest-level state machine is the cleaner long-term endpoint, but it is larger than the current PR3 migration.

**Context:** The engineering review chose a gradual migration: first build a canonical key registry, keep compatibility reads, and derive legacy state views. Revisit the larger 2026-04-08 manifest/state-machine design after PR3 has landed and Stage2.5 -> Stage3 -> Stage4 fixture replay is stable.

**Effort:** L
**Priority:** P2
**Depends on:** PR3 canonical key registry and missing-items migration; deterministic fixture replay for Stage2.5 -> Stage3 -> Stage4.

### Pre-commit Quality Gate

**What:** Add `.pre-commit-config.yaml` for the existing quality commands, including `black`, `flake8`, and `mypy src/datasource/` or their exact project-approved equivalents.

**Why:** Quality commands are documented in AGENTS.md and CLAUDE.md, but they are still manual. Automating them reduces missed checks without mixing tooling changes into behavior-preserving utility extraction.

**Context:** The engineering review split pre-commit out of PR1 because the current worktree is large and dirty. First introduction should avoid all-repo formatting churn; prefer scoped hooks or an initial no-format validation mode before widening.

**Effort:** S
**Priority:** P2
**Depends on:** PR1 semantic utils extraction landing separately.

## Data Pipeline

### Split Stage2 And Stage2.5 Large Scripts

**What:** Split `scripts/stage2_unified_enhancer.py` and `scripts/stage2_5_injector.py` into smaller modules around search, extraction, injection, quality gates, and trend_history backfill.

**Why:** These scripts are over 3000 lines each, making reviews and regression analysis expensive. The split should happen only after the key contracts and replay tests exist.

**Context:** The engineering review deferred this from the current PR set. The right order is: semantic utils extraction, Pring golden tests, canonical key registry and missing-items compatibility, test-safe trend_history fixture replay, then module split.

**Effort:** L
**Priority:** P2
**Depends on:** PR1 semantic utils extraction; PR3 canonical key registry; test-safe trend_history fixture replay.
