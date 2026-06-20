# PR-E2 Manual Fallback Policies Design

## Goal

Add a provenance-only policy registry for Stage2.5 manual fallback skeletons so recurring manual gaps start with trusted source families, without changing Stage2.5 injector enforcement or pre-filling market values.

## Scope

- Add `config/manual_fallback_policies.json` with 10 policy keys:
  - `commodities.BCOM`
  - `commodities.GSG`
  - `forex.USDCNY`
  - `bonds.CN10Y_CDB`
  - `macro_indicators.industrial`
  - `macro_indicators.industrial_sales`
  - `macro_indicators.bdi`
  - `monetary_policy.reserve_ratio`
  - `monetary_policy.reverse_repo`
  - `monetary_policy.mlf`
- Add a stdlib JSON loader with schema checks:
  - required `category/key/source/source_url_template/is_estimated`
  - unique `category:key`
  - HTTPS `source_url_template`
  - no numeric manual fields in policy entries
- Extend `scripts/tools/manual_template_from_gap_monitor.py` to prefill only provenance fields for entries already present in a gap-derived manual skeleton.
- Keep numeric fields such as `current_value`, `previous_value`, `change_rate`, `current_price`, `current_rate`, `current_yield`, `recent_5d`, and `total_120d` as `null`.
- Add docs/template pointers.

## Non-Goals

- No changes to `scripts/stage2_5_injector.py`.
- No changes to `src/datasource/engines/stage2_5/` enforcement, merge, override, or quality gate behavior.
- No new official override allowlist entries.
- No automatic value extraction or current-value prefill.

## Guardrails

- `mlf`, `USDCNY`, and `BCOM` policy domains must stay aligned with `OFFICIAL_MANUAL_SOURCES`.
- `reserve_ratio` must use a PBoC HTTPS template and `is_estimated=false`, matching `TRUSTED_MONETARY_MANUAL_QUALITY_DOMAINS`.
- `CN10Y_CDB` and `bdi` remain estimated where current policy gates expect estimated/allowlisted behavior.
