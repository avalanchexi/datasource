# D2 Minor Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove three D2 merge-time minor issues without changing the contract validation behavior.

**Architecture:** Keep the existing contract models and tests in place. Add focused coverage for clean-checkout fixture fallback, replace the one v1-style amount validator with a small v2-first compatibility decorator, and clean only the lint failures in `src/datasource/models/base.py`.

**Tech Stack:** Python, pytest, flake8, Pydantic v1/v2 compatibility, existing `run_clean.sh` project runner.

---

## File Structure

- Modify `tests/test_contract_validation.py`
  - Adds one fixture fallback characterization test.
  - Adds one warning regression test that fails while `FundFlowData` uses v1-style `@validator`.
- Modify `src/datasource/models/market_data_contract.py`
  - Replaces direct `validator` import with a Pydantic v2-first compatibility decorator.
  - Changes only the decorator on `FundFlowData._coerce_amount()`.
- Modify `src/datasource/models/base.py`
  - Formatting-only lint cleanup: imports, trailing whitespace, long signatures.

## Task 1: Add Contract Hardening Tests

**Files:**
- Modify: `tests/test_contract_validation.py`

- [ ] **Step 1: Add imports for reload and warning capture**

At the top of `tests/test_contract_validation.py`, replace:

```python
import json
from copy import deepcopy
from pathlib import Path
```

with:

```python
import importlib
import json
import warnings
from copy import deepcopy
from pathlib import Path
```

- [ ] **Step 2: Add fixture fallback and validator warning tests**

Insert these tests after the existing `assert PR` block and before `_load_json()`:

```python
def test_discover_fixtures_falls_back_to_tracked_golden_when_runs_missing():
    paths = _discover_fixtures(
        "data/runs/20990101/no-such-contract-fixture.json",
        GOLDEN_MARKET_DATA,
    )

    assert paths == [GOLDEN_MARKET_DATA]


def test_market_data_contract_import_has_no_v1_validator_warning():
    import datasource.models.market_data_contract as market_contract

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(market_contract)

    validator_warnings = [
        warning
        for warning in caught
        if (
            "Pydantic V1 style `@validator` validators are deprecated"
            in str(warning.message)
        )
    ]
    assert validator_warnings == []
```

- [ ] **Step 3: Run tests to verify the warning regression fails first**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_contract_validation.py::test_discover_fixtures_falls_back_to_tracked_golden_when_runs_missing \
  tests/test_contract_validation.py::test_market_data_contract_import_has_no_v1_validator_warning
```

Expected before implementation:

- `test_discover_fixtures_falls_back_to_tracked_golden_when_runs_missing` passes.
- `test_market_data_contract_import_has_no_v1_validator_warning` fails because `market_data_contract.py` still uses v1-style `@validator`.

## Task 2: Replace FundFlowData Validator With V2-First Compatibility

**Files:**
- Modify: `src/datasource/models/market_data_contract.py`
- Test: `tests/test_contract_validation.py`
- Test: `tests/test_fund_flow_pipeline.py`

- [ ] **Step 1: Replace the Pydantic import**

In `src/datasource/models/market_data_contract.py`, replace:

```python
from pydantic import BaseModel, Field, validator
```

with:

```python
try:
    from pydantic import BaseModel, Field, field_validator
except ImportError:
    from pydantic import BaseModel, Field, validator as _pydantic_validator

    def _amount_field_validator(*fields: str):
        return _pydantic_validator(*fields, pre=True)
else:
    def _amount_field_validator(*fields: str):
        return field_validator(*fields, mode="before")
```

- [ ] **Step 2: Replace the amount coercion decorator**

In `FundFlowData`, replace:

```python
    @validator('recent_5d', 'total_120d', pre=True)
    def _coerce_amount(cls, value: Optional[Any]) -> Optional[float]:
        return cls._parse_amount(value)
```

with:

```python
    @_amount_field_validator('recent_5d', 'total_120d')
    def _coerce_amount(cls, value: Optional[Any]) -> Optional[float]:
        return cls._parse_amount(value)
```

- [ ] **Step 3: Run validator-focused tests**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_contract_validation.py::test_market_data_contract_import_has_no_v1_validator_warning \
  tests/test_fund_flow_pipeline.py::FundFlowPipelineTest::test_pydantic_model_accepts_string_amounts
```

Expected: both tests pass. The second test confirms amount string coercion still works after the decorator change.

- [ ] **Step 4: Run the full contract validation test file**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_contract_validation.py
```

Expected: all tests in `tests/test_contract_validation.py` pass. Remaining class-based Pydantic `Config` warnings are allowed by the design non-goals.

## Task 3: Clean `models/base.py` Flake8 Debt

**Files:**
- Modify: `src/datasource/models/base.py`

- [ ] **Step 1: Verify the lint failure before editing**

Run:

```bash
bash run_clean.sh python -m flake8 src/datasource/models/
```

Expected before implementation: failure in `src/datasource/models/base.py` for `F401`, `W291`, `W293`, and `E501`.

- [ ] **Step 2: Replace imports with the lint-clean import block**

At the top of `src/datasource/models/base.py`, replace:

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
import pandas as pd
from pydantic import BaseModel, Field
```

with:

```python
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, Field
```

- [ ] **Step 3: Replace the affected `BaseDataSource` method signatures**

In `src/datasource/models/base.py`, keep the same method names and bodies, but use this formatting for the long signatures:

```python
    @abstractmethod
    async def get_stock_daily(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        **kwargs,
    ) -> DataResponse:
        """获取股票日线数据"""
        pass

    async def get_fund_daily(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        **kwargs,
    ) -> DataResponse:
        """获取基金/ETF日线数据，默认回退至股票日线接口"""
        return await self.get_stock_daily(
            symbol,
            start_date,
            end_date,
            **kwargs,
        )

    @abstractmethod
    async def get_index_daily(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        **kwargs,
    ) -> DataResponse:
        """获取指数日线数据"""
        pass
```

- [ ] **Step 4: Remove whitespace-only blank lines and trailing spaces**

Ensure these lines contain no trailing spaces:

```python
    error: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True
```

Ensure the blank lines between methods are empty, not space-filled.

- [ ] **Step 5: Run model lint**

Run:

```bash
bash run_clean.sh python -m flake8 src/datasource/models/
```

Expected: exit code 0.

## Task 4: Final Verification and Commit

**Files:**
- Modify: `tests/test_contract_validation.py`
- Modify: `src/datasource/models/market_data_contract.py`
- Modify: `src/datasource/models/base.py`

- [ ] **Step 1: Run hardening-specific validation**

Run:

```bash
bash run_clean.sh python -m flake8 src/datasource/models/
bash run_clean.sh python -m pytest -q tests/test_contract_validation.py
bash run_clean.sh python -m pytest -q \
  tests/test_contract_validation.py \
  tests/test_stage_validation_wiring.py \
  tests/test_stage3_guard.py
```

Expected:

- flake8 exits 0;
- `tests/test_contract_validation.py` passes;
- the D2 validation wiring and Stage3 guard tests pass.

- [ ] **Step 2: Run full suite**

Run:

```bash
bash run_clean.sh python -m pytest -q
```

Expected: full suite passes. If an environmental issue blocks the full suite, capture the command, exit status, and relevant error lines before proceeding.

- [ ] **Step 3: Inspect the final diff**

Run:

```bash
git diff --stat main...HEAD
git diff -- src/datasource/models/base.py src/datasource/models/market_data_contract.py tests/test_contract_validation.py
```

Expected: only the planned lint cleanup, validator compatibility change, and fixture/warning tests appear beyond existing D2 changes.

- [ ] **Step 4: Commit the hardening changes**

Run:

```bash
git add \
  src/datasource/models/base.py \
  src/datasource/models/market_data_contract.py \
  tests/test_contract_validation.py
git commit -m "fix: harden D2 contract validation minors"
```

Expected: one commit containing only the three planned hardening changes.

## Self-Review

- Spec coverage: all three goals from `docs/superpowers/specs/2026-06-19-d2-minor-hardening-design.md` are covered by Tasks 1-4.
- Placeholder scan: this plan contains no unfinished markers or unspecified implementation steps.
- Type consistency: `FundFlowData._coerce_amount()` retains the existing `cls, value` signature and continues to return `Optional[float]`.
