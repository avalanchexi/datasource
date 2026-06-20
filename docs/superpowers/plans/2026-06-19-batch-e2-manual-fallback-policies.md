# PR-E2 Manual Fallback Policies Plan

## Tasks

1. Baseline and isolate worktree from `main`.
2. Add `config/manual_fallback_policies.json` and `datasource.utils.manual_fallback_policies`.
3. Add schema/consistency tests for the 10 policy keys, numeric-field bans, official manual domains, and reserve-ratio PBoC rules.
4. Extend `scripts/tools/manual_template_from_gap_monitor.py` with `_prefill_entry` and `_apply_policies`.
5. Add prefill tests proving numeric fields remain `null` and provenance fields are populated.
6. Add template/runbook pointers.
7. Verify targeted tests, py_compile, JSON validity, and Stage2.5 injector zero diff.

## Validation

```bash
bash run_clean.sh python -m pytest -q tests/test_manual_fallback_policies.py tests/test_manual_template.py
bash run_clean.sh python -m py_compile src/datasource/utils/manual_fallback_policies.py scripts/tools/manual_template_from_gap_monitor.py
bash run_clean.sh python -m json.tool config/manual_fallback_policies.json >/tmp/manual_fallback_policies.json
git diff --name-only -- scripts/stage2_5_injector.py src/datasource/engines/stage2_5
```

Expected:

- Targeted tests pass.
- JSON and Python compile checks pass.
- Stage2.5 injector and engine files show no diff.
