# D2 Minor Hardening Design

## Context

PR-D2 adds pre-write contract validation for Stage1, Stage2, Stage2.5, and
Stage3 outputs. Review found no blocking issues, but identified three minor
sources of merge-time noise:

- `flake8 src/datasource/models/` still fails on existing lint debt in
  `src/datasource/models/base.py`.
- Contract tests emit a Pydantic v1 `@validator` deprecation warning from
  `FundFlowData`.
- Fixture discovery should remain deterministic when a clean checkout has no
  local `data/runs/` artifacts.

This hardening keeps D2's validation behavior unchanged while removing or
pinning those minor issues before merge.

## Goals

- Make `flake8 src/datasource/models/` pass for the model package.
- Replace the `FundFlowData` amount validator with a Pydantic v2-first pattern
  while preserving Pydantic v1 compatibility.
- Add a focused test proving contract fixture discovery falls back to tracked
  golden fixtures when `data/runs/` has no matches.

## Non-Goals

- Do not change contract strictness or the `extra=ignore` decision.
- Do not migrate every model `Config` class to Pydantic v2 `ConfigDict`.
- Do not change `FundFlowData._parse_amount()` semantics.
- Do not edit tracked fixture JSON contents.
- Do not expand the work into repository-wide lint cleanup.

## Design

### Model lint cleanup

`src/datasource/models/base.py` will receive formatting-only cleanup:

- remove the unused `Union` import;
- remove trailing whitespace and whitespace-only blank lines;
- split long method signatures and long calls to satisfy flake8 line limits.

The public fields, method names, return types, and runtime behavior remain the
same.

### Pydantic validator compatibility

`src/datasource/models/market_data_contract.py` will import a validator
decorator using a v2-first compatibility branch:

- use `field_validator(..., mode="before")` when available;
- fall back to `validator(..., pre=True)` under Pydantic v1.

`FundFlowData._coerce_amount()` will continue delegating to `_parse_amount()`.
Existing tests continue to define the accepted parsing behavior for numeric
values, `N/A`, `亿`, `千亿`, `万亿`, and positive text marked as outflow.

### Fixture fallback coverage

`tests/test_contract_validation.py` will add a pure unit test for
`_discover_fixtures()`. The test will pass a pattern with no matches and a
tracked golden fixture path, then assert the fallback is returned. This avoids
depending on the developer machine's local `data/runs/` contents.

## Error Handling

No new runtime error path is introduced. If tracked golden fixtures are missing,
the existing import-time assertions in `tests/test_contract_validation.py`
continue to fail loudly instead of silently creating zero-parameter test cases.

## Verification

Run these commands in the D2 worktree:

```bash
bash run_clean.sh python -m flake8 src/datasource/models/
bash run_clean.sh python -m pytest -q tests/test_contract_validation.py
bash run_clean.sh python -m pytest -q \
  tests/test_contract_validation.py \
  tests/test_stage_validation_wiring.py \
  tests/test_stage3_guard.py
bash run_clean.sh python -m pytest -q
```

The first three commands are required for this hardening. The final full suite
is required before claiming D2 is merge-ready unless an environment issue is
reported explicitly.
