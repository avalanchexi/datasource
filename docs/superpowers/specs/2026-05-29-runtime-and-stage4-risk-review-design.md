# Runtime Probe and Stage4 Risk Review Design

## Purpose

This change reduces two recurring sources of wasted time in the daily report workflow:

- Starting the pipeline from the wrong shell/runtime channel, especially Windows Git/MSYS bash against a Linux/WSL virtual environment.
- Letting report-generation risks hide inside normal Stage2.5 or Stage3 diagnostics when a report can still be generated but needs explicit human review.

The design keeps the existing Stage1 -> Stage4 data pipeline unchanged. It adds an early local environment probe, documents the execution-channel rule, records a machine-specific memory, and adds a Stage4 pre-report risk review that reports issues without mutating data.

## Scope

In scope:

- Add a local shell and venv probe before `run_preflight.sh`.
- Update `AGENTS.md` and `CLAUDE.md` so cold sessions start with execution-channel validation.
- Record a repository and machine specific memory for the current WSL venv setup.
- Add a read-only Stage4 risk review script for BCOM, CN10Y_CDB, ETF/fund-flow estimates, and missing source evidence.

Out of scope:

- Changing Stage1, Stage2, Stage2.5, Stage3, or Stage4 scoring semantics.
- Relaxing the Tavily once-per-day rule.
- Reclassifying estimated values as non-estimated.
- Adding network checks to the local environment probe.
- Automatically modifying `market_data_complete.json`, `gap_monitor.json`, or report markdown.

## Components

### `scripts/env_probe.sh`

`env_probe.sh` is a local-only startup probe. It runs before `run_preflight.sh` and does not read API keys or contact external services.

It reports one of three statuses:

- `OK`: current shell, venv layout, and Python executable are compatible.
- `USE_WSL`: the current shell is Windows native bash/MSYS/CYGWIN while the repository or venv layout indicates WSL/Linux should be used.
- `BROKEN_ENV`: venv or Python is missing, non-empty but unusable, or otherwise inconsistent.

The script checks:

- `uname -s` for `Linux`, `MINGW*`, `MSYS*`, or `CYGWIN*`.
- Whether `.venv/bin/activate` or `.venv/Scripts/activate` exists.
- Whether the selected Python executable can run `python -c "import sys; print(sys.executable)"`.
- Whether the repository path looks like WSL (`/mnt/...`) while the shell is Windows native bash.

When it returns `USE_WSL`, it prints a concrete PowerShell command shape:

```powershell
C:\Windows\System32\bash.exe -lc "cd /mnt/d/cursor/datasource && bash run_preflight.sh"
```

### Documentation

`AGENTS.md` remains the authoritative playbook. Its setup section should add a step 0:

```bash
bash scripts/env_probe.sh
bash run_preflight.sh
```

The guidance should state that `env_probe.sh` checks only local execution readiness, while `run_preflight.sh` still owns API key, proxy, DNS, and HTTPS checks.

`CLAUDE.md` should keep the quick reminder short:

- Confirm the execution channel before preflight.
- On the current machine, this repository uses a Linux/WSL venv.
- If Claude Code hits Git/MSYS `dofork ... errno 11`, switch to WSL instead of retrying the pipeline.

### Memory

Record one machine and repository scoped memory:

`/mnt/d/cursor/datasource` currently has a Linux/WSL `.venv` layout. If Claude Code's default Bash is Git/MSYS and emits `dofork ... errno 11`, use `C:\Windows\System32\bash.exe` to enter WSL and run repository scripts there. Do not repeatedly retry the pipeline or kill shell processes as the primary fix.

This memory is intentionally scoped to the current machine and repository. It should not remove the repository's Windows venv compatibility.

### `scripts/stage4_risk_review.py`

`stage4_risk_review.py` is a read-only review tool run before Stage4 report generation. It reads:

- `data/runs/${DATE_NH}/market_data_complete.json`
- `data/runs/${DATE_NH}/gap_monitor.json`, if present
- `data/runs/${DATE_NH}/quality_metrics.json`, if present

It writes a derived review artifact without modifying source inputs:

- `data/runs/${DATE_NH}/stage4_risk_review.json`

The output groups findings by severity:

- `blocker`: issues that should stop formal report generation unless explicitly resolved, such as key values with missing source evidence or obvious BCOM scope mismatch.
- `review_required`: report can continue only after human review, such as CN10Y_CDB spread estimates or fund-flow downgrade disclosures.
- `info`: non-blocking disclosures, such as already documented estimated values or same-value merge metadata.

## Risk Review Rules

### BCOM

For `commodities.BCOM`, the review checks source and note fields for plain Bloomberg Commodity Index evidence.

It flags `blocker` when evidence appears to reference incompatible scope, including:

- `BCOMTR`
- `Total Return`
- ETF or fund products
- Single commodity or sub-index pages

If no incompatible scope is detected but the source is still manually supplied or otherwise hard to verify, it flags `review_required`.

### CN10Y_CDB

For `bonds.CN10Y_CDB`, estimated values are allowed only as reviewable disclosures.

If `is_estimated=true`, the item should include `estimation_method`, `note`, or equivalent text describing the spread basis. Missing explanation is `review_required`.

### Fund Flow

For `fund_flow.*`, the review highlights:

- `is_estimated=true`
- `metric_basis` equal to `news_net_flow` or `estimated_net_flow`
- missing or weak window evidence
- use of Stage4 fund-flow downgrade

These normally produce `review_required`, not `blocker`, when the formal downgrade path is being used and source evidence exists.

### Source Evidence

Any data item with a report-facing numeric value but no `source_url` is flagged.

Critical items become `blocker`; non-critical items become `review_required`. The first implementation should keep this critical-key list small and aligned with existing policy-gate concepts rather than inventing broad new blocking semantics.

## Data Flow

Daily workflow after the change:

1. Run `bash scripts/env_probe.sh`.
2. If status is `OK`, run `bash run_preflight.sh`.
3. Run Stage1, Stage2, Stage2.5, and Stage3 using the existing commands.
4. Run `bash run_clean.sh python scripts/stage4_risk_review.py --date YYYY-MM-DD`.
5. Review `stage4_risk_review.json`.
6. Run Stage4 report generation with the existing flags.

The probe does not replace preflight. The risk review does not replace Stage3 or Stage4 gates.

## Error Handling

`env_probe.sh` should fail closed:

- Shell and venv mismatch returns non-zero with `USE_WSL`.
- Missing or broken venv returns non-zero with `BROKEN_ENV`.
- Valid WSL/Linux venv returns zero with `OK`.

`stage4_risk_review.py` should also fail closed for malformed required input:

- Missing `market_data_complete.json` is an error.
- Missing optional `gap_monitor.json` or `quality_metrics.json` is allowed and recorded in output metadata.
- Invalid JSON in required input is an error.
- Findings are deterministic and do not depend on network calls.

## Testing

Minimum verification:

- `bash scripts/env_probe.sh` returns `OK` in the current WSL environment.
- `bash scripts/env_probe.sh` prints the selected shell, venv layout, and Python executable.
- `bash run_clean.sh python scripts/stage4_risk_review.py --date YYYY-MM-DD` writes a JSON file for an existing run.
- A malformed or missing required market-data file returns a clear error.
- BCOM, CN10Y_CDB, and fund-flow review rules are covered by focused tests or fixture-based smoke cases.

## Rollout

Implement in this order:

1. Add `scripts/env_probe.sh`.
2. Update `AGENTS.md` and `CLAUDE.md`.
3. Add `scripts/stage4_risk_review.py`.
4. Add minimal tests or smoke validation.
5. Record the scoped memory after implementation.

The first usable version can be conservative. It is better to surface a small set of high-confidence review items than to create noisy broad blocking rules.
