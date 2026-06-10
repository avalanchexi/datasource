# Stage2 Structured Review Followups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two remaining review risks from `codex/daily-pipeline-guards`: fail closed on partial TuShare ETF daily rows, and stop market quote pages from stamping weekend or holiday dates onto BCOM/GSG closes.

**Architecture:** Keep the fixes inside Stage2 structured providers. `tushare_etf.py` becomes a two-pass validator that infers per-exchange row-count floors from the fetched candidate window before releasing a `direct_balance_delta` ETF value; `market_quote_pages.py` uses a bounded previous-business-day candidate list and explicit page dates for labelled closes. Tests live in the existing structured-provider test file, and docs only clarify reusable operating rules.

**Tech Stack:** Python 3.10, pytest, pandas test fixtures, existing `src/datasource/providers/stage2_structured/*` providers, `AGENTS.md`, and `CLAUDE.md`.

---

## Scope Check

This plan implements the two actionable review findings:

- H1: TuShare `etf_share_size` can return a non-empty but truncated per-exchange list for one trade date. That must not become `is_estimated=False`.
- M1: BCOM/GSG quote pages currently derive `as_of_date` from `reference_date - 1 calendar day`. That is wrong on Mondays and around market holidays.

This plan does not implement these lower-priority followups:

- `reserve_ratio` update-date rendering as `N/A`: separate report-table display issue.
- Changing ETF unit labels: the current contract remains `total_size / 10000 -> 亿元` until TuShare field semantics are separately verified against source documentation and historical examples.
- Changing run-lock stale handling: the six-hour corrupt/fresh fail-closed behavior is accepted as an operational tradeoff.

Execution addendum from review:

- The ETF row-count floor was tightened from the original median-based plan to a high-water rule: `ceil(max_observed_usable_rows * 0.8)`. This keeps legitimate one-row aggregate responses valid while preventing a majority of partial rows from lowering the floor.
- Final review found that Stage2 search query `closing_date` still used calendar-day lag. The implemented branch added a planner fix so `closing_date_lag_days=1` skips weekends for daily quote search candidates.

## File Structure

- Modify: `tests/test_stage2_structured_providers.py`
  - Add one partial-row TuShare fixture.
  - Add ETF tests for internal partial rows blocking and trailing partial rows rolling back to the latest complete window.
  - Add quote-page tests for Monday/weekend BCOM date-row matching and labelled GSG closes using explicit page dates.

- Modify: `src/datasource/providers/stage2_structured/tushare_etf.py`
  - Fetch all candidate-date exchange records before calculating totals.
  - Infer adaptive minimum usable row counts per exchange using the maximum observed positive count and an 80% floor.
  - Treat any date below its per-exchange floor as incomplete, with diagnostics that distinguish `missing_exchange_rows` from `partial_exchange_rows`.

- Modify: `src/datasource/providers/stage2_structured/market_quote_pages.py`
  - Replace single `reference_date - 1` logic with a bounded previous-business-day candidate list.
  - Let date-row parsing scan those candidates in order.
  - Let labelled-close parsing use an explicit nearby page date when present; otherwise omit `as_of_date` and mark the basis in diagnostics.

- Modify: `AGENTS.md`
  - Clarify that TuShare ETF completeness includes per-exchange row-count consistency, not only non-empty exchange responses.
  - Clarify that BCOM/GSG `closing_date` and structured quote `as_of_date` use the previous completed trading weekday candidate and explicit page evidence.

- Modify: `CLAUDE.md`
  - Mirror the AGENTS quick reminders so Claude Code does not reintroduce the weaker rules.

- Modify: `src/datasource/engines/stage2_task_planner.py`
  - Apply `closing_date_lag_days` as completed-business-day lag rather than calendar-day lag for daily quote search candidates.

---

### Task 1: Fail Closed On Partial TuShare ETF Rows

**Files:**
- Modify: `tests/test_stage2_structured_providers.py:49-105`
- Modify: `tests/test_stage2_structured_providers.py:448-565`
- Modify: `src/datasource/providers/stage2_structured/tushare_etf.py:5-7`
- Modify: `src/datasource/providers/stage2_structured/tushare_etf.py:19-21`
- Modify: `src/datasource/providers/stage2_structured/tushare_etf.py:64-85`
- Modify: `src/datasource/providers/stage2_structured/tushare_etf.py:129-140`
- Modify: `src/datasource/providers/stage2_structured/tushare_etf.py:337-379`

- [ ] **Step 1: Add the partial-row TuShare fixture**

Insert this class immediately after `FakeTuShareETFProInternalMissing` in `tests/test_stage2_structured_providers.py`:

```python
class FakeTuShareETFProPartialRows(FakeTuShareETFPro):
    def __init__(
        self,
        partial_trade_date,
        partial_exchange="SSE",
        trade_date_count=131,
    ):
        super().__init__(trade_date_count=trade_date_count)
        self.partial_trade_date = partial_trade_date
        self.partial_exchange = partial_exchange

    def etf_share_size(self, trade_date, exchange=None, market=None):
        exchange_value = exchange or market
        index = self.trade_dates.index(trade_date)
        total_size_wan = (1000.0 + index) * 10000.0 / 2.0
        row_count = 1 if (
            trade_date == self.partial_trade_date
            and exchange_value == self.partial_exchange
        ) else 4
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "exchange": exchange_value,
                    "ts_code": "{0}.{1:03d}".format(exchange_value, row_index),
                    "total_size": total_size_wan / row_count,
                }
                for row_index in range(row_count)
            ]
        )
```

- [ ] **Step 2: Add the failing internal-partial-row test**

Append this test after `test_tushare_etf_provider_fails_closed_when_internal_exchange_date_missing`:

```python
@pytest.mark.asyncio
async def test_tushare_etf_provider_fails_closed_when_exchange_rows_are_partial():
    partial_trade_date = _trade_dates(131)[20]
    provider = TuShareETFProvider(
        pro=FakeTuShareETFProPartialRows(partial_trade_date=partial_trade_date)
    )

    with pytest.raises(StructuredProviderError) as exc_info:
        await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-24")

    diagnostics = exc_info.value.diagnostics
    assert exc_info.value.reason == "policy_gate_blocked"
    assert diagnostics["missing_trade_date"] == partial_trade_date
    assert diagnostics["missing_exchange"] == "SSE"
    assert diagnostics["incomplete_reason"] == "partial_exchange_rows"
    assert diagnostics["usable_row_count"] == 1
    assert diagnostics["min_required_row_count"] == 4
    assert diagnostics["usable_row_count_by_exchange"]["SSE"] == 1
    assert diagnostics["usable_row_count_by_exchange"]["SZSE"] == 4
    assert diagnostics["min_required_rows_by_exchange"]["SSE"] == 4
    assert diagnostics["skipped_incomplete_trade_dates"] == [partial_trade_date]
    assert diagnostics["terminal_structured_provider_error"] is True
```

- [ ] **Step 3: Add the failing trailing-partial-row rollback test**

Append this test after the internal-partial-row test:

```python
@pytest.mark.asyncio
async def test_tushare_etf_provider_rolls_back_when_latest_exchange_rows_are_partial():
    latest_trade_date = _trade_dates(131)[-1]
    provider = TuShareETFProvider(
        pro=FakeTuShareETFProPartialRows(partial_trade_date=latest_trade_date)
    )

    result = await provider.fetch({"indicator_key": "etf"}, {}, "2026-05-24")

    extraction = result.to_extraction()
    assert extraction["is_estimated"] is False
    assert extraction["metric_basis"] == "etf_total_size_delta"
    assert extraction["total_120d"] == pytest.approx(120.0)
    assert extraction["as_of_date"] == _trade_dates(131)[-2]
    assert extraction["diagnostics"]["latest_trade_date_was_incomplete"] is True
    assert extraction["diagnostics"]["skipped_incomplete_trade_dates"] == [
        latest_trade_date
    ]
    assert extraction["diagnostics"]["min_required_rows_by_exchange"]["SSE"] == 4
    assert extraction["diagnostics"]["min_required_rows_by_exchange"]["SZSE"] == 4
    assert extraction["diagnostics"]["complete_date_count"] == 130
```

- [ ] **Step 4: Run the new ETF tests and verify they fail**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_fails_closed_when_exchange_rows_are_partial \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_rolls_back_when_latest_exchange_rows_are_partial
```

Expected: both tests fail. The internal partial test currently does not raise, and the trailing partial test currently includes the partial latest date in the window.

- [ ] **Step 5: Add imports and the row-count floor constant**

In `src/datasource/providers/stage2_structured/tushare_etf.py`, replace the imports at the top with:

```python
import math
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence
```

Then add this constant below `WINDOW_DATES = 121`:

```python
ETF_COMPLETENESS_ROW_FLOOR_RATIO = 0.8
```

- [ ] **Step 6: Convert ETF fetching to a two-pass validation flow**

Replace the block from `totals_by_date: Dict[str, float] = {}` through `totals_by_date[trade_date] = total_wan / 10000.0` in `src/datasource/providers/stage2_structured/tushare_etf.py` with:

```python
        records_by_date: Dict[str, Dict[str, Sequence[Mapping[str, Any]]]] = {}
        row_count = 0
        for trade_date in trade_dates:
            records_by_exchange = {}
            for exchange in EXCHANGES:
                records = self._fetch_share_size_records(pro, trade_date, exchange)
                row_count += len(records)
                records_by_exchange[exchange] = records
            records_by_date[trade_date] = records_by_exchange

        min_rows_by_exchange = _min_usable_rows_by_exchange(records_by_date)
        diagnostics.update(
            {
                "row_count_floor_ratio": ETF_COMPLETENESS_ROW_FLOOR_RATIO,
                "min_required_rows_by_exchange": dict(min_rows_by_exchange),
            }
        )

        totals_by_date: Dict[str, float] = {}
        skipped_incomplete_trade_dates = []
        incomplete_details_by_date: Dict[str, Dict[str, Any]] = {}
        first_incomplete_details: Dict[str, Any] = {}
        for trade_date in trade_dates:
            records_by_exchange = records_by_date[trade_date]
            total_wan = _date_total_from_records(
                records_by_exchange,
                trade_date,
                min_rows_by_exchange=min_rows_by_exchange,
            )
            if total_wan is None:
                skipped_incomplete_trade_dates.append(trade_date)
                incomplete_details = _incomplete_date_diagnostics(
                    records_by_exchange,
                    trade_date,
                    min_rows_by_exchange=min_rows_by_exchange,
                )
                incomplete_details_by_date[trade_date] = incomplete_details
                if not first_incomplete_details:
                    first_incomplete_details = incomplete_details
                continue
            totals_by_date[trade_date] = total_wan / 10000.0
```

- [ ] **Step 7: Include row-count floors in success diagnostics**

Inside the existing `diagnostics.update({...})` success block in `src/datasource/providers/stage2_structured/tushare_etf.py`, add these two fields:

```python
                "row_count_floor_ratio": ETF_COMPLETENESS_ROW_FLOOR_RATIO,
                "min_required_rows_by_exchange": dict(min_rows_by_exchange),
```

The success diagnostics block should now include both fields alongside `date_count`, `candidate_date_count`, `complete_date_count`, `row_count`, `latest_trade_date`, and `start_trade_date`.

- [ ] **Step 8: Replace the ETF completeness helper functions**

Replace `_date_total_from_records`, `_usable_total_sizes`, and `_incomplete_date_diagnostics` in `src/datasource/providers/stage2_structured/tushare_etf.py` with:

```python
def _min_usable_rows_by_exchange(
    records_by_date: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]
) -> Dict[str, int]:
    floors: Dict[str, int] = {}
    for exchange in EXCHANGES:
        counts = []
        for trade_date, records_by_exchange in records_by_date.items():
            count = len(
                _usable_total_sizes(
                    records_by_exchange.get(exchange, []), trade_date, exchange
                )
            )
            if count > 0:
                counts.append(count)
        if not counts:
            floors[exchange] = 1
            continue
        max_count = max(counts)
        floors[exchange] = max(
            1,
            int(math.ceil(max_count * ETF_COMPLETENESS_ROW_FLOOR_RATIO)),
        )
    return floors


def _date_total_from_records(
    records_by_exchange: Mapping[str, Sequence[Mapping[str, Any]]],
    trade_date: str,
    min_rows_by_exchange: Optional[Mapping[str, int]] = None,
) -> Optional[float]:
    total = 0.0
    for exchange in EXCHANGES:
        usable = _usable_total_sizes(
            records_by_exchange.get(exchange, []), trade_date, exchange
        )
        min_rows = int((min_rows_by_exchange or {}).get(exchange, 1))
        if len(usable) < max(1, min_rows):
            return None
        total += sum(usable)
    return total


def _usable_total_sizes(
    records: Sequence[Mapping[str, Any]], trade_date: str, exchange: str
) -> List[float]:
    usable = []
    for record in records:
        if not _record_matches_request(record, trade_date, exchange):
            continue
        total_size = record.get("total_size")
        if total_size is None:
            continue
        try:
            value = float(total_size)
        except (TypeError, ValueError):
            continue
        if value > 0:
            usable.append(value)
    return usable


def _incomplete_date_diagnostics(
    records_by_exchange: Mapping[str, Sequence[Mapping[str, Any]]],
    trade_date: str,
    min_rows_by_exchange: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    usable_counts = {
        exchange: len(
            _usable_total_sizes(records_by_exchange.get(exchange, []), trade_date, exchange)
        )
        for exchange in EXCHANGES
    }
    required_counts = {
        exchange: max(1, int((min_rows_by_exchange or {}).get(exchange, 1)))
        for exchange in EXCHANGES
    }
    for exchange in EXCHANGES:
        usable_count = usable_counts[exchange]
        required_count = required_counts[exchange]
        if usable_count <= 0:
            return {
                "missing_trade_date": trade_date,
                "missing_exchange": exchange,
                "incomplete_reason": "missing_exchange_rows",
                "usable_row_count": usable_count,
                "min_required_row_count": required_count,
                "usable_row_count_by_exchange": usable_counts,
                "min_required_rows_by_exchange": required_counts,
            }
        if usable_count < required_count:
            return {
                "missing_trade_date": trade_date,
                "missing_exchange": exchange,
                "incomplete_reason": "partial_exchange_rows",
                "usable_row_count": usable_count,
                "min_required_row_count": required_count,
                "usable_row_count_by_exchange": usable_counts,
                "min_required_rows_by_exchange": required_counts,
            }
    return {
        "missing_trade_date": trade_date,
        "usable_row_count_by_exchange": usable_counts,
        "min_required_rows_by_exchange": required_counts,
    }
```

- [ ] **Step 9: Run ETF provider tests**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_computes_total_size_delta_windows \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_uses_latest_complete_window_when_reference_date_incomplete \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_fails_closed_when_internal_exchange_date_missing \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_fails_closed_when_exchange_rows_are_partial \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_rolls_back_when_latest_exchange_rows_are_partial \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_fails_closed_when_exchange_missing \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_skips_wrong_trade_date_rows_and_fails_closed \
  tests/test_stage2_structured_providers.py::test_tushare_etf_provider_skips_wrong_exchange_rows_and_fails_closed
```

Expected: all selected tests pass.

- [ ] **Step 10: Commit Task 1**

Run:

```bash
git add src/datasource/providers/stage2_structured/tushare_etf.py tests/test_stage2_structured_providers.py
git commit -m "fix: fail closed on partial tushare etf rows"
```

---

### Task 2: Use Trading-Date Evidence For BCOM/GSG Quote Pages

**Files:**
- Modify: `tests/test_stage2_structured_providers.py:310-395`
- Modify: `src/datasource/providers/stage2_structured/market_quote_pages.py:5-8`
- Modify: `src/datasource/providers/stage2_structured/market_quote_pages.py:85-121`
- Modify: `src/datasource/providers/stage2_structured/market_quote_pages.py:177-248`

- [ ] **Step 1: Add the failing Monday BCOM date-row test**

Append this test after `test_market_quote_page_provider_parses_bcom_investing_close`:

```python
@pytest.mark.asyncio
async def test_market_quote_page_provider_uses_previous_weekday_for_monday_bcom_close():
    html = """
    <html><body>
      <h1>Bloomberg Commodity Historical Data</h1>
      <table>
        <tr><td>Jun 12, 2026</td><td>129.5000</td><td>130.9746</td></tr>
      </table>
    </body></html>
    """

    async def fetch_text(url, params=None):
        assert "bloomberg-commodity-historical-data" in url
        return html

    provider = MarketQuotePageProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "BCOM"}, {}, "2026-06-15")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(129.5)
    assert extraction["as_of_date"] == "2026-06-12"
    assert extraction["diagnostics"]["candidate_close_dates"][:3] == [
        "2026-06-12",
        "2026-06-11",
        "2026-06-10",
    ]
    assert extraction["diagnostics"]["as_of_date_basis"] == "date_row"
```

- [ ] **Step 2: Add the failing labelled-close explicit-date test**

Append this test after `test_market_quote_page_provider_parses_gsg_stockanalysis_close`:

```python
@pytest.mark.asyncio
async def test_market_quote_page_provider_uses_explicit_page_date_for_labelled_gsg_close():
    html = """
    <html><body>
      <h1>iShares S&P GSCI Commodity-Indexed Trust</h1>
      <div>Previous Close 31.24</div>
      <div>Market data as of Jun 12, 2026</div>
    </body></html>
    """

    async def fetch_text(url, params=None):
        assert "stockanalysis.com/etf/gsg" in url
        return html

    provider = MarketQuotePageProvider(fetch_text=fetch_text)
    result = await provider.fetch({"indicator_key": "GSG"}, {}, "2026-06-16")

    extraction = result.to_extraction()
    assert extraction["value"] == pytest.approx(31.24)
    assert extraction["as_of_date"] == "2026-06-12"
    assert extraction["diagnostics"]["as_of_date_basis"] == "labelled_close_with_date"
    assert "2026-06-12" in extraction["diagnostics"]["candidate_close_dates"]
```

- [ ] **Step 3: Run the new quote tests and verify they fail**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_structured_providers.py::test_market_quote_page_provider_uses_previous_weekday_for_monday_bcom_close \
  tests/test_stage2_structured_providers.py::test_market_quote_page_provider_uses_explicit_page_date_for_labelled_gsg_close
```

Expected: the BCOM test fails with `missing_value` because the provider looks for Sunday `Jun 14, 2026`; the GSG test fails because the labelled parser stamps `2026-06-15` instead of the explicit page date.

- [ ] **Step 4: Update market quote imports and parse tuple type**

In `src/datasource/providers/stage2_structured/market_quote_pages.py`, replace the import and type alias section with:

```python
import html
import re
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
```

Then add this type alias below `FetchText`:

```python
QuoteParseResult = Tuple[float, Optional[str], str, str]
```

- [ ] **Step 5: Replace fetch-date handling and diagnostics**

In `MarketQuotePageProvider.fetch`, replace:

```python
        expected_close_date = self._expected_close_date(reference_date)
        parsed = self._parse_close_value(
            text,
            expected_close_date,
            str(config.get("parse_strategy") or "date_row_first"),
        )
```

with:

```python
        candidate_close_dates = self._candidate_close_dates(reference_date)
        expected_close_date = candidate_close_dates[0] if candidate_close_dates else None
        parsed = self._parse_close_value(
            text,
            candidate_close_dates,
            str(config.get("parse_strategy") or "date_row_first"),
        )
```

In the `missing_value` diagnostics dict, add the candidate list:

```python
                    "candidate_close_dates": candidate_close_dates,
```

Then replace:

```python
        value, as_of_date, evidence_text = parsed
```

with:

```python
        value, as_of_date, evidence_text, as_of_date_basis = parsed
```

Finally, replace the `diagnostics={...}` block in the `StructuredResult` with:

```python
            diagnostics={
                "label": config["label"],
                "price_basis": config["price_basis"],
                "expected_close_date": expected_close_date,
                "candidate_close_dates": candidate_close_dates,
                "as_of_date_basis": as_of_date_basis,
                "evidence_text": evidence_text,
            },
```

- [ ] **Step 6: Replace expected-date and parser methods**

Replace `_expected_close_date`, `_parse_close_value`, `_parse_date_row_close_value`, and `_parse_labelled_close_value` in `src/datasource/providers/stage2_structured/market_quote_pages.py` with:

```python
    @staticmethod
    def _candidate_close_dates(reference_date: str, lookback_days: int = 10) -> List[str]:
        ref_date = datetime.strptime(reference_date, "%Y-%m-%d").date()
        candidates: List[str] = []
        cursor = ref_date - timedelta(days=1)
        while (ref_date - cursor).days <= lookback_days:
            if cursor.weekday() < 5:
                candidates.append(cursor.isoformat())
            cursor -= timedelta(days=1)
        return candidates

    @staticmethod
    def _expected_close_date(reference_date: str) -> str:
        candidates = MarketQuotePageProvider._candidate_close_dates(reference_date)
        return candidates[0]

    @classmethod
    def _parse_close_value(
        cls,
        text: str,
        candidate_close_dates: Sequence[str],
        parse_strategy: str = "date_row_first",
    ) -> Optional[QuoteParseResult]:
        parsers = {
            "date_row_first": (
                cls._parse_date_row_close_value,
                cls._parse_labelled_close_value,
            ),
            "labelled_close_first": (
                cls._parse_labelled_close_value,
                cls._parse_date_row_close_value,
            ),
        }.get(
            parse_strategy,
            (
                cls._parse_date_row_close_value,
                cls._parse_labelled_close_value,
            ),
        )
        for parser in parsers:
            parsed = parser(text, candidate_close_dates)
            if parsed is not None:
                return parsed
        return None

    @classmethod
    def _parse_date_row_close_value(
        cls,
        text: str,
        candidate_close_dates: Sequence[str],
    ) -> Optional[QuoteParseResult]:
        for close_date in candidate_close_dates:
            date_label = cls._date_label(close_date)
            date_pattern = re.escape(date_label).replace(r"\ ", r"\s+")
            date_match = re.search(
                r"({0})(?P<tail>.{{0,240}})".format(date_pattern),
                text,
                flags=re.IGNORECASE,
            )
            if date_match:
                tail = date_match.group("tail")
                value = cls._first_number(tail)
                if value is not None:
                    evidence = "{0}{1}".format(date_match.group(1), tail[:80]).strip()
                    return value, close_date, evidence, "date_row"
        return None

    @classmethod
    def _parse_labelled_close_value(
        cls,
        text: str,
        candidate_close_dates: Sequence[str],
    ) -> Optional[QuoteParseResult]:
        close_match = re.search(
            r"\b(?:previous\s+close|close)\s+([0-9][0-9,]*(?:\.\d+)?)\b",
            text,
            flags=re.IGNORECASE,
        )
        if close_match:
            evidence_start = max(0, close_match.start() - 80)
            evidence_end = min(len(text), close_match.end() + 160)
            evidence = text[evidence_start:evidence_end].strip()
            explicit_date = cls._nearest_candidate_date(
                text,
                close_match.start(),
                close_match.end(),
                candidate_close_dates,
            )
            basis = "labelled_close_with_date" if explicit_date else "labelled_close_without_date"
            return cls._parse_number(close_match.group(1)), explicit_date, evidence, basis
        return None
```

- [ ] **Step 7: Add explicit-date extraction helpers**

Add these methods below `_date_label` in `src/datasource/providers/stage2_structured/market_quote_pages.py`:

```python
    @classmethod
    def _nearest_candidate_date(
        cls,
        text: str,
        match_start: int,
        match_end: int,
        candidate_close_dates: Sequence[str],
    ) -> Optional[str]:
        candidate_set = set(candidate_close_dates)
        evidence_start = max(0, match_start - 160)
        evidence_end = min(len(text), match_end + 240)
        window = text[evidence_start:evidence_end]
        for match in re.finditer(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
            r"\s+\d{1,2},\s+\d{4}\b",
            window,
            flags=re.IGNORECASE,
        ):
            parsed = cls._parse_us_date_label(match.group(0))
            if parsed and parsed in candidate_set:
                return parsed
        return None

    @staticmethod
    def _parse_us_date_label(value: str) -> Optional[str]:
        text = " ".join(str(value or "").strip().split())
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        return None
```

- [ ] **Step 8: Add `Sequence` import**

Because the new parser methods accept `Sequence[str]`, update the typing import in `src/datasource/providers/stage2_structured/market_quote_pages.py` to:

```python
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple
```

- [ ] **Step 9: Run quote provider tests**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_stage2_structured_providers.py::test_market_quote_page_provider_parses_bcom_investing_close \
  tests/test_stage2_structured_providers.py::test_market_quote_page_provider_uses_previous_weekday_for_monday_bcom_close \
  tests/test_stage2_structured_providers.py::test_market_quote_page_provider_parses_gsg_stockanalysis_close \
  tests/test_stage2_structured_providers.py::test_market_quote_page_provider_uses_explicit_page_date_for_labelled_gsg_close \
  tests/test_stage2_structured_providers.py::test_market_quote_page_provider_prefers_gsg_labelled_close \
  tests/test_stage2_structured_providers.py::test_market_quote_page_provider_rejects_bcom_total_return_page
```

Expected: all selected tests pass. Existing Tuesday-style BCOM/GSG tests must keep returning `2026-06-09`.

- [ ] **Step 10: Commit Task 2**

Run:

```bash
git add src/datasource/providers/stage2_structured/market_quote_pages.py tests/test_stage2_structured_providers.py
git commit -m "fix: derive market quote as-of dates from trading evidence"
```

---

### Task 3: Document The Hardened Data Contracts

**Files:**
- Modify: `AGENTS.md:27`
- Modify: `AGENTS.md:256-272`
- Modify: `AGENTS.md:300`
- Modify: `AGENTS.md:339`
- Modify: `CLAUDE.md:130-135`

- [ ] **Step 1: Update AGENTS daily quote rule**

In `AGENTS.md`, replace the bullet that starts with `- BCOM/GSG 等美股/海外收盘类 daily quote` with:

```markdown
- BCOM/GSG 等美股/海外收盘类 daily quote 的搜索 `closing_date` 使用报告日前最近一个已完成交易日候选；结构化 quote 页面的 `as_of_date` 必须来自日期行或 labelled close 附近的显式页面日期，不能把周末/节假日的 `reference_date - 1` 伪造成收盘日期。报告 `ref_date` 仍保持当日报告日；不要用“今日”概念页或盘中快照替代目标收盘。
```

- [ ] **Step 2: Update AGENTS Stage2 query-context rule**

In `AGENTS.md`, replace the sentence in the Stage2 query-context bullet that says ``其中 `BCOM/GSG` 的 `closing_date` 默认落后一日以指向已完成收盘`` with:

```markdown
其中 `BCOM/GSG` 的 `closing_date` 指向报告日前最近一个已完成交易日候选，结构化 provider 会优先匹配候选日期行；labelled close 只有在页面附近有显式日期时才写 `as_of_date`，否则保留 value 但不伪造日期戳
```

- [ ] **Step 3: Update AGENTS ETF structured-provider rule**

In `AGENTS.md`, replace the ETF provider bullet under Stage2 rules with:

```markdown
- ETF structured provider 顺序为 TuShare `etf_share_size` before EastMoney/search。TuShare 成功条件是存在一个 latest complete 的 121 交易日窗口，且窗口内 SSE+SZSE 两个 exchange 的 `total_size` 都完整可解析；完整性不仅要求每个交易所非空，还要求每个交易所当日可用行数不低于候选窗口内该交易所正数行数中位数的保守下限，防止 API 截断/分页只返回少量 ETF 时被误判为完整。若报告日窗口不完整，可回退到最近完整窗口并记录窗口日期；窗口内部缺口或部分返回必须 fail closed。输出 `metric_basis=etf_total_size_delta`、`window_evidence=direct_balance_delta`、`source_tier=tier2`、`is_estimated=false`。EastMoney 仍只有已验证全市场 `direct_daily_series` 时才可释放 gate。
```

- [ ] **Step 4: Update AGENTS fund-flow and data-contract ETF rules**

In `AGENTS.md`, replace the `ETF 全市场资金流可由 TuShare` bullet and the `fund_flow.etf` bullet with these versions:

```markdown
- ETF 全市场资金流可由 TuShare `etf_share_size` latest complete 窗口释放 gate：121 个交易日、SSE+SZSE 两个 exchange 的 `total_size` 都完整可解析，且每个交易所当日行数通过候选窗口内的自适应完整性下限时，按 `metric_basis=etf_total_size_delta`、`window_evidence=direct_balance_delta`、`source_tier=tier2`、`is_estimated=false` 写入。该口径是 ETF 规模 delta，不等同于新闻净流入；新闻、季度报告、部分返回、分页截断和 EastMoney 未验证全市场窗口时仍默认 `is_estimated=true` 或 fail closed。
```

```markdown
- `fund_flow.etf`: Stage1/Stage2 均可用 TuShare `etf_share_size.total_size` 计算全市场规模窗口变化，`metric_basis=etf_total_size_delta`、`window_evidence=direct_balance_delta`；latest complete 121 交易日窗口中 SSE+SZSE 两个 exchange 的 `total_size` 都完整可解析，且每交易所行数通过自适应完整性下限时，可作为非估算 Tier2 结构化窗口值。该口径是 ETF 规模 delta，不等同于新闻口径净流入。若 TuShare 不可得、窗口不完整、行数疑似截断或质量阻断，继续 Stage2 搜索或 Stage2.5 补数。
```

- [ ] **Step 5: Update CLAUDE quick reminders**

In `CLAUDE.md`, update the Stage2 feedback-loop and structured-provider bullets so they contain these exact sentences:

```markdown
BCOM/GSG structured quote pages must not stamp `reference_date - 1` onto results when that date is a weekend or holiday; date-row parsing should use previous completed trading-day candidates, and labelled close results should use an explicit nearby page date or omit `as_of_date`.
```

```markdown
TuShare ETF `etf_share_size` gate requires a latest complete 121-trading-day window with SSE+SZSE present and per-exchange usable row counts above the adaptive completeness floor; non-empty but partial/truncated exchange responses are incomplete and must fail closed unless they are only trailing dates outside the rolled-back window.
```

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: clarify structured quote and etf completeness rules"
```

---

### Task 4: Run Focused Verification

**Files:**
- Verify: `tests/test_stage2_structured_providers.py`
- Verify: `tests/test_stage2_unified.py`
- Verify: `tests/test_daily_writer_locks.py`
- Verify: `tests/test_run_lock.py`

- [ ] **Step 1: Run the full structured-provider test file**

Run:

```bash
bash run_clean.sh python -m pytest -q tests/test_stage2_structured_providers.py
```

Expected: all tests in `tests/test_stage2_structured_providers.py` pass.

- [ ] **Step 2: Run the reviewer’s high-risk suite**

Run:

```bash
bash run_clean.sh python -m pytest -q \
  tests/test_run_lock.py \
  tests/test_daily_writer_locks.py \
  tests/test_stage2_structured_providers.py \
  tests/test_stage2_unified.py
```

Expected: all selected tests pass, with the existing skip count unchanged except for any test additions in `test_stage2_structured_providers.py`.

- [ ] **Step 3: Check the final diff**

Run:

```bash
git diff --stat HEAD~3..HEAD
git diff --check HEAD~3..HEAD
```

Expected: `git diff --check` prints no whitespace errors. The diff only touches:

```text
AGENTS.md
CLAUDE.md
src/datasource/providers/stage2_structured/market_quote_pages.py
src/datasource/providers/stage2_structured/tushare_etf.py
tests/test_stage2_structured_providers.py
```

- [ ] **Step 4: Summarize residual risk before merging**

Use this exact merge note:

```markdown
Implemented the review followups for Stage2 structured providers:

- TuShare ETF windows now fail closed when a trade date has non-empty but partial per-exchange rows; trailing incomplete dates can still roll back to the latest complete 121-trading-day window.
- BCOM/GSG quote pages now derive as-of dates from previous completed trading-day candidates and explicit page dates instead of `reference_date - 1`.
- AGENTS/CLAUDE now document the hardened completeness and quote-date contracts.

Residual risks:
- ETF `total_size` unit semantics remain the existing `total_size / 10000 -> 亿元` contract and should be checked separately against TuShare field documentation.
- `reserve_ratio` update-date rendering remains a separate report-display followup.
```

- [ ] **Step 5: Commit verification note if project convention requires it**

Do not create a commit for verification output unless this branch normally records verification artifacts. If no verification artifact is required, leave the working tree clean after Task 3 and include the verification commands in the final handoff.

---

## Self-Review

Spec coverage:

- H1 is covered by Task 1 tests and implementation. The new guard detects partial-but-non-empty exchange responses and keeps latest-date rollback behavior.
- M1 is covered by Task 2 tests and implementation. Date-row parsing uses previous weekday candidates, and labelled close uses explicit page dates instead of calendar-day assumptions.
- Documentation drift is covered by Task 3. Both AGENTS and CLAUDE get the long-term operating rules.
- Low-priority review notes are explicitly scoped out with residual-risk text in Task 4.

Placeholder scan:

- The plan contains no placeholder markers, no empty implementation steps, and no references to undefined functions without defining them in the relevant task.

Type consistency:

- `QuoteParseResult` is defined before use.
- `candidate_close_dates` is a `Sequence[str]` in parser methods and a `List[str]` in fetch diagnostics.
- ETF helper names match across fetch, diagnostics, and tests: `_min_usable_rows_by_exchange`, `min_required_rows_by_exchange`, `usable_row_count_by_exchange`, `partial_exchange_rows`.
