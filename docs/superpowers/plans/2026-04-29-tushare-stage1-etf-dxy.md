# TuShare Stage1 ETF And DXY Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the two highest-value candidates, ETF fund-flow windows and DXY, as far upstream as Stage1 TuShare when the official TuShare interfaces provide a usable or explicitly labeled proxy, while preserving Stage2.5 as the兜底 layer for anything Stage1 and Stage2 still cannot obtain or validate.

**Architecture:** Keep the existing Stage1 -> Stage2 -> Stage2.5 contract: Stage1 tries official/structured sources first, Stage2 searches and extracts remaining gaps, and Stage2.5 only fills unresolved gaps after those two stages fail, return incomplete windows, or fail quality gates. Add an official TuShare `etf_share_size` path for `fund_flow.etf`, add a guarded FXCM `FX_BASKET` probe for `forex.DXY`, and leave commodities, CN10Y_CDB, industrial data, MLF, reverse repo, and RRR on Stage2/Stage2.5 because TuShare does not provide the same report口径. Tests must prove Stage2 tasks disappear only when Stage1 produces complete same-contract values, and Stage2.5 remains available whenever Stage1/Stage2 cannot produce report-ready data.

**Tech Stack:** Python, pandas, pytest, existing `MarketDataCollector`, TuShare Pro, PowerShell on Windows.

---

## Official TuShare Interfaces Used

Use these official docs while implementing:

- ETF share/size: https://tushare.pro/document/2?doc_id=408
- FX base info: https://tushare.pro/document/2?doc_id=178
- FX daily: https://tushare.pro/document/2?doc_id=179
- Futures daily reference for non-goal wording: https://tushare.pro/document/2?doc_id=138

Important contract decisions:

- `etf_share_size.total_size` is in 万元. Convert to 亿元 with `/ 10000.0`.
- ETF recent windows use total all-market ETF size deltas, not article-based estimated net inflow. `metric_basis` must be `etf_total_size_delta`.
- DXY from TuShare is an FXCM `FX_BASKET` proxy such as `USDOLLAR.FXCM`, not necessarily ICE DXY. The report name/source must expose this when Stage1 uses it.
- Stage2.5 remains the兜底 path. It is triggered when Stage1 has no value, Stage1 only has partial windows, Stage2 fails search/extract/writeback, source evidence is insufficient, or unified quality state still reports `manual_required` / `quality_blockers`.
- Do not replace overseas commodity contracts, BCOM, GSG, CN10Y_CDB, industrial indicators, RRR, reverse repo, or MLF with approximate TuShare data in this plan.

## File Structure

Modify these files:

- `scripts/stage1_data_collector.py`
  - Add `_fetch_etf_flow_from_tushare_share_size`.
  - Add `_fetch_etf_total_size_on_date`.
  - Replace `_fetch_etf_flow_proxy` usage with the new official ETF size path first, retaining the daily_info proxy only as an explicitly estimated fallback if the existing fallback is still wanted.
  - Extend `_fetch_fx_from_tushare` to support guarded `DXY` discovery through `fx_obasic(classify="FX_BASKET")`.
- `src/datasource/models/market_data_contract.py`
  - Add optional `is_estimated` and `note` to `FundFlowData`.
  - Add optional `as_of_date` and `note` to `ForexData` so Stage1 DXY can preserve口径 without relying only on the display name.
- `src/datasource/generators/simple_report.py`
  - Keep the existing forex table compact, but show the explicit DXY proxy name if supplied by Stage1.
  - Include fund-flow estimated items in the appendix estimate warning.
- `AGENTS.md`
  - Record the long-term data口径: ETF can use `etf_share_size` total-size deltas; DXY TuShare path is an FXCM proxy; the remaining Stage2.5 classes are not to be silently replaced by TuShare proxies.
- `CLAUDE.md`
  - Keep the quick index in sync if it has Stage1/Stage2 reminders.

Modify tests:

- `tests/test_stage1_data_collector.py`
  - Add ETF size aggregation tests.
  - Add DXY `fx_obasic -> fx_daily` tests.
- `tests/test_stage2_unified.py`
  - Add task-planner assertions that complete Stage1 ETF/DXY values are skipped.
- `tests/test_simple_report_integration.py`
  - Add report text assertion for ETF official size-delta source and DXY proxy label.

Do not modify:

- `scripts/stage2_5_injector.py`
- `src/datasource/config/search_profiles.py`
- `src/datasource/adapters/tavily_client.py`

## Task 1: Add Stage1 ETF Share-Size Tests

**Files:**
- Modify: `tests/test_stage1_data_collector.py`
- Later modify: `scripts/stage1_data_collector.py`

- [ ] **Step 1: Add failing ETF total-size helper tests**

Append these tests near the other `MarketDataCollector` Stage1 tests:

```python
def test_fetch_etf_total_size_on_date_sums_sse_and_szse(monkeypatch):
    class _Pro:
        def etf_share_size(self, **kwargs):
            if kwargs["exchange"] == "SSE":
                return pd.DataFrame(
                    {
                        "trade_date": [kwargs["trade_date"], kwargs["trade_date"]],
                        "ts_code": ["510300.SH", "588000.SH"],
                        "total_size": [1200000.0, 300000.0],
                    }
                )
            if kwargs["exchange"] == "SZSE":
                return pd.DataFrame(
                    {
                        "trade_date": [kwargs["trade_date"]],
                        "ts_code": ["159919.SZ"],
                        "total_size": [500000.0],
                    }
                )
            return pd.DataFrame()

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-29")

    total = asyncio.run(collector._fetch_etf_total_size_on_date("20260428"))

    assert total == pytest.approx(200.0)
```

```python
def test_fetch_etf_flow_from_share_size_builds_5d_and_120d_windows(monkeypatch):
    class _Pro:
        def trade_cal(self, **_kwargs):
            dates = [f"2026{i:04d}" for i in range(1, 122)]
            return pd.DataFrame({"cal_date": dates, "is_open": [1] * len(dates)})

        def etf_share_size(self, **kwargs):
            trade_date = kwargs["trade_date"]
            exchange = kwargs["exchange"]
            totals_by_date = {
                "20260001": 8000000.0,
                "20260116": 9500000.0,
                "20260121": 10000000.0,
            }
            total = totals_by_date.get(trade_date, 0.0)
            if exchange == "SSE":
                value = total * 0.6
            elif exchange == "SZSE":
                value = total * 0.4
            else:
                value = 0.0
            return pd.DataFrame(
                {
                    "trade_date": [trade_date],
                    "ts_code": [f"ETF.{exchange}"],
                    "total_size": [value],
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-01-21")

    flow = asyncio.run(collector._fetch_etf_flow_from_tushare_share_size())

    assert flow is not None
    assert flow.type == "etf"
    assert flow.recent_5d == pytest.approx(50.0)
    assert flow.total_120d == pytest.approx(200.0)
    assert flow.trend == "流入"
    assert flow.source == "TuShare etf_share_size"
    assert flow.metric_basis == "etf_total_size_delta"
    assert flow.is_estimated is False
    assert "total_size" in flow.note
    assert "20260121" in flow.note
```

- [ ] **Step 2: Run the ETF tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_stage1_data_collector.py::test_fetch_etf_total_size_on_date_sums_sse_and_szse tests/test_stage1_data_collector.py::test_fetch_etf_flow_from_share_size_builds_5d_and_120d_windows -q
```

Expected:

```text
FAILED ... AttributeError: 'MarketDataCollector' object has no attribute '_fetch_etf_total_size_on_date'
FAILED ... AttributeError: 'MarketDataCollector' object has no attribute '_fetch_etf_flow_from_tushare_share_size'
```

- [ ] **Step 3: Commit the failing tests**

Run:

```powershell
git add tests/test_stage1_data_collector.py
git commit -m "test: cover tushare etf share size flow"
```

Expected:

```text
[codex/... test: cover tushare etf share size flow]
```

## Task 2: Implement Stage1 ETF `etf_share_size` Flow

**Files:**
- Modify: `scripts/stage1_data_collector.py`
- Modify: `src/datasource/models/market_data_contract.py`
- Test: `tests/test_stage1_data_collector.py`

- [ ] **Step 1: Add optional fund-flow fields to the contract model**

In `src/datasource/models/market_data_contract.py`, update `FundFlowData`:

```python
class FundFlowData(BaseModel):
    """资金流向数据"""

    type: str  # northbound/southbound/etf/margin
    recent_5d: Optional[float] = None
    total_120d: Optional[float] = None
    trend: str
    source: str
    source_url: Optional[str] = None
    metric_basis: Optional[str] = None
    note: Optional[str] = None
    stage_task_id: Optional[str] = None
    is_estimated: bool = False
```

- [ ] **Step 2: Add ETF total-size helper**

In `scripts/stage1_data_collector.py`, add this method near `_fetch_etf_flow_proxy`:

```python
    async def _fetch_etf_total_size_on_date(self, trade_date: str) -> Optional[float]:
        """Fetch all-market ETF total_size for one trade date, converted from 万元 to 亿元."""
        try:
            import tushare as ts

            token = os.getenv("TUSHARE_TOKEN")
            pro = ts.pro_api(token) if token else ts.pro_api()
            totals: List[float] = []
            for exchange in ("SSE", "SZSE"):
                try:
                    df = pro.etf_share_size(trade_date=trade_date, exchange=exchange)
                except Exception as exc:  # noqa: BLE001
                    print(f"    [WARN] etf_share_size {exchange} {trade_date} failed: {exc}")
                    continue
                if df is None or getattr(df, "empty", True):
                    continue
                frame = df.copy()
                frame.columns = [str(col).lower() for col in frame.columns]
                if "total_size" not in frame.columns:
                    continue
                frame["total_size"] = pd.to_numeric(frame["total_size"], errors="coerce")
                valid = frame.dropna(subset=["total_size"])
                if valid.empty:
                    continue
                totals.append(float(valid["total_size"].sum()) / 10000.0)
            if not totals:
                return None
            return round(sum(totals), 2)
        except Exception as exc:  # noqa: BLE001
            print(f"    [WARN] etf_share_size unavailable for {trade_date}: {exc}")
            return None
```

- [ ] **Step 3: Add ETF flow helper**

Add this method below `_fetch_etf_total_size_on_date`:

```python
    async def _fetch_etf_flow_from_tushare_share_size(self) -> Optional[FundFlowData]:
        """Use TuShare etf_share_size total_size deltas for ETF fund-flow windows."""
        open_dates = self._get_recent_open_dates(count=121)
        if len(open_dates) < 6:
            return None

        latest_date = open_dates[-1]
        base_5d_date = open_dates[-6]
        base_120d_date = open_dates[0] if len(open_dates) >= 121 else None

        latest_total = await self._fetch_etf_total_size_on_date(latest_date)
        if latest_total is None:
            return None

        base_5d_total = await self._fetch_etf_total_size_on_date(base_5d_date)
        base_120d_total = (
            await self._fetch_etf_total_size_on_date(base_120d_date)
            if base_120d_date
            else None
        )

        recent_5d = round(latest_total - base_5d_total, 2) if base_5d_total is not None else None
        total_120d = round(latest_total - base_120d_total, 2) if base_120d_total is not None else None
        if recent_5d is None and total_120d is None:
            return None

        note_parts = [
            "TuShare etf_share_size total_size规模变化推导ETF资金动向",
            "单位:亿元",
            f"latest_date:{latest_date}",
            f"latest_total_size:{latest_total:.2f}",
            f"base_5d_date:{base_5d_date}",
        ]
        if base_5d_total is not None:
            note_parts.append(f"base_5d_total_size:{base_5d_total:.2f}")
        if base_120d_date:
            note_parts.append(f"base_120d_date:{base_120d_date}")
        if base_120d_total is not None:
            note_parts.append(f"base_120d_total_size:{base_120d_total:.2f}")

        return FundFlowData(
            type="etf",
            recent_5d=recent_5d,
            total_120d=total_120d,
            trend=self._infer_trend(recent_5d),
            source="TuShare etf_share_size",
            metric_basis="etf_total_size_delta",
            note="; ".join(note_parts),
            is_estimated=False,
        )
```

- [ ] **Step 4: Integrate the official ETF helper before the old proxy**

In `collect_fund_flow`, replace the current ETF block:

```python
        # 2) 日度成交统计（daily_info）估算ETF热度
        etf_entry = await self._fetch_etf_flow_proxy()
```

with:

```python
        # 2) TuShare ETF份额规模 -> fund_flow.etf
        etf_entry = await self._fetch_etf_flow_from_tushare_share_size()
        if etf_entry:
            fund_flow_dict["etf"] = etf_entry
            pending_missing = [item for item in pending_missing if item["key"] != "etf"]
            print("  [OK] ETF资金流已通过TuShare etf_share_size规模变化推导")
        else:
            print("  [WARN] TuShare etf_share_size暂未返回完整窗口，ETF仍记为缺口")
```

Remove the old `_fetch_etf_flow_proxy` call from `collect_fund_flow`. Leave `_fetch_etf_flow_proxy` and `_get_daily_turnover_amount` in place for now only if other tests still import them; do not call the proxy from the daily pipeline.

- [ ] **Step 5: Run the ETF tests**

Run:

```powershell
python -m pytest tests/test_stage1_data_collector.py::test_fetch_etf_total_size_on_date_sums_sse_and_szse tests/test_stage1_data_collector.py::test_fetch_etf_flow_from_share_size_builds_5d_and_120d_windows -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Run fund-flow regression tests**

Run:

```powershell
python -m pytest tests/test_fund_flow_pipeline.py tests/test_stage1_data_collector.py -q
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit ETF implementation**

Run:

```powershell
git add scripts/stage1_data_collector.py src/datasource/models/market_data_contract.py tests/test_stage1_data_collector.py
git commit -m "feat: derive etf flow from tushare share size"
```

Expected:

```text
[codex/... feat: derive etf flow from tushare share size]
```

## Task 3: Add DXY TuShare Probe Tests

**Files:**
- Modify: `tests/test_stage1_data_collector.py`
- Later modify: `scripts/stage1_data_collector.py`
- Later modify: `src/datasource/models/market_data_contract.py`

- [ ] **Step 1: Add failing DXY discovery test**

Append this test to `tests/test_stage1_data_collector.py`:

```python
def test_fetch_fx_from_tushare_discovers_dxy_fx_basket(monkeypatch):
    class _Pro:
        def fx_obasic(self, **kwargs):
            assert kwargs.get("classify") == "FX_BASKET"
            return pd.DataFrame(
                {
                    "ts_code": ["USDOLLAR.FXCM"],
                    "name": ["美元篮子"],
                    "classify": ["FX_BASKET"],
                }
            )

        def fx_daily(self, **kwargs):
            assert kwargs.get("ts_code") == "USDOLLAR.FXCM"
            return pd.DataFrame(
                {
                    "ts_code": ["USDOLLAR.FXCM"] * 3,
                    "trade_date": ["20260423", "20260424", "20260428"],
                    "bid_close": [98.0, 98.5, 99.0],
                    "ask_close": [98.1, 98.6, 99.1],
                }
            )

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-29")

    result = asyncio.run(collector._fetch_fx_from_tushare("DXY", "DXY美元指数"))

    assert result is not None
    assert result.pair == "DXY"
    assert result.name == "DXY美元指数(TuShare USDOLLAR代理)"
    assert result.current_rate == pytest.approx(99.0)
    assert result.daily_change == pytest.approx((99.0 / 98.5 - 1.0) * 100.0)
    assert result.change_120d == pytest.approx((99.0 / 98.0 - 1.0) * 100.0)
    assert result.source == "TuShare fx_daily(USDOLLAR.FXCM, FX_BASKET proxy)"
    assert result.as_of_date == "2026-04-28"
    assert "不等同ICE DXY" in result.note
```

- [ ] **Step 2: Add failing DXY fallback test**

Append this test:

```python
def test_fetch_fx_from_tushare_dxy_returns_none_without_usdollar(monkeypatch):
    class _Pro:
        def fx_obasic(self, **_kwargs):
            return pd.DataFrame({"ts_code": ["EURBASKET.FXCM"], "classify": ["FX_BASKET"]})

        def fx_daily(self, **_kwargs):
            raise AssertionError("fx_daily should not be called without a USDOLLAR candidate")

    class _Tushare:
        def __init__(self, pro):
            self.pro = pro

        def pro_api(self, *_args, **_kwargs):
            return self.pro

    monkeypatch.setitem(sys.modules, "tushare", _Tushare(_Pro()))
    monkeypatch.setattr("scripts.stage1_data_collector.get_manager", lambda: _FakeManager())
    collector = MarketDataCollector("2026-04-29")

    result = asyncio.run(collector._fetch_fx_from_tushare("DXY", "DXY美元指数"))

    assert result is None
```

- [ ] **Step 3: Run DXY tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_stage1_data_collector.py::test_fetch_fx_from_tushare_discovers_dxy_fx_basket tests/test_stage1_data_collector.py::test_fetch_fx_from_tushare_dxy_returns_none_without_usdollar -q
```

Expected:

```text
FAILED ... assert None is not None
```

- [ ] **Step 4: Commit failing DXY tests**

Run:

```powershell
git add tests/test_stage1_data_collector.py
git commit -m "test: cover tushare dxy fx basket probe"
```

Expected:

```text
[codex/... test: cover tushare dxy fx basket probe]
```

## Task 4: Implement Guarded DXY `fx_obasic -> fx_daily`

**Files:**
- Modify: `scripts/stage1_data_collector.py`
- Modify: `src/datasource/models/market_data_contract.py`
- Test: `tests/test_stage1_data_collector.py`

- [ ] **Step 1: Add optional forex metadata fields**

In `src/datasource/models/market_data_contract.py`, update `ForexData`:

```python
class ForexData(BaseModel):
    """汇率数据"""
    pair: str
    name: str
    current_rate: float
    daily_change: Optional[float] = None
    change_120d: Optional[float] = None
    trend: str
    source: str
    source_url: Optional[str] = None
    as_of_date: Optional[str] = None
    note: Optional[str] = None
```

- [ ] **Step 2: Add DXY code discovery helper**

In `scripts/stage1_data_collector.py`, add this method above `_fetch_fx_from_tushare`:

```python
    def _discover_dxy_fxcm_code(self, pro: Any) -> Optional[str]:
        """Find the FXCM USD dollar basket code exposed by TuShare fx_obasic."""
        try:
            df = pro.fx_obasic(classify="FX_BASKET", exchange="FXCM")
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] TuShare fx_obasic FX_BASKET failed: {exc}")
            return None
        if df is None or getattr(df, "empty", True):
            return None
        frame = df.copy()
        frame.columns = [str(col).lower() for col in frame.columns]
        if "ts_code" not in frame.columns:
            return None
        for raw in frame["ts_code"].dropna().astype(str):
            code = raw.strip()
            if "USDOLLAR" in code.upper():
                return code
        return None
```

- [ ] **Step 3: Extend `_fetch_fx_from_tushare` for DXY**

Replace the early symbol guard and candidate setup in `_fetch_fx_from_tushare` with this block:

```python
            ts_code_candidates = []
            is_dxy_proxy = False
            if symbol == "USDCNH":
                ts_code_candidates = ["USDCNH", "USDCNH.FXCM"]
            elif symbol == "USDCNY":
                ts_code_candidates = ["USDCNY", "USDCNY.FXCM"]
            elif symbol == "DXY":
                dxy_code = self._discover_dxy_fxcm_code(pro)
                if not dxy_code:
                    return None
                ts_code_candidates = [dxy_code]
                is_dxy_proxy = True
            else:
                return None
```

Keep the existing `fx_daily` loop and rate calculations. Replace the final `return ForexData(...)` with:

```python
            trade_date = str(latest_row.get("trade_date") or "")
            as_of_date = (
                f"{trade_date[0:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
                if len(trade_date) == 8
                else None
            )
            display_name = name
            source_label = f"TuShare fx_daily({selected_code or symbol})"
            note = None
            if is_dxy_proxy:
                display_name = "DXY美元指数(TuShare USDOLLAR代理)"
                source_label = f"TuShare fx_daily({selected_code}, FX_BASKET proxy)"
                note = "TuShare FXCM USDOLLAR外汇篮子代理，不等同ICE DXY；仅在Stage1可稳定取数时替代Stage2.5手工DXY。"

            return ForexData(
                pair=symbol,
                name=display_name,
                current_rate=float(latest_rate),
                daily_change=float(daily_change),
                change_120d=float(change_120d),
                trend=trend,
                source=source_label,
                as_of_date=as_of_date,
                note=note,
            )
```

- [ ] **Step 4: Run DXY tests**

Run:

```powershell
python -m pytest tests/test_stage1_data_collector.py::test_fetch_fx_from_tushare_discovers_dxy_fx_basket tests/test_stage1_data_collector.py::test_fetch_fx_from_tushare_dxy_returns_none_without_usdollar -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Run Stage1 test suite**

Run:

```powershell
python -m pytest tests/test_stage1_data_collector.py tests/test_fund_flow_pipeline.py -q
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit DXY implementation**

Run:

```powershell
git add scripts/stage1_data_collector.py src/datasource/models/market_data_contract.py tests/test_stage1_data_collector.py
git commit -m "feat: probe dxy via tushare fx basket"
```

Expected:

```text
[codex/... feat: probe dxy via tushare fx basket]
```

## Task 5: Preserve Stage2 Skip Behavior And Report Evidence

**Files:**
- Modify: `tests/test_stage2_unified.py`
- Modify: `tests/test_simple_report_integration.py`
- Modify: `src/datasource/generators/simple_report.py`

- [ ] **Step 1: Add Stage2 planner skip tests**

Append to `tests/test_stage2_unified.py`:

```python
def test_task_planner_skips_complete_tushare_etf_flow(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-29"},
        "fund_flow": {
            "etf": {
                "type": "etf",
                "recent_5d": 50.0,
                "total_120d": 200.0,
                "trend": "流入",
                "source": "TuShare etf_share_size",
                "metric_basis": "etf_total_size_delta",
                "is_estimated": False,
            }
        },
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")

    tasks = planner.build_tasks(payload)

    assert [task for task in tasks if task["indicator_key"] == "etf"] == []
```

```python
def test_task_planner_skips_complete_tushare_dxy_proxy(tmp_path: Path):
    payload = {
        "metadata": {"date": "2026-04-29"},
        "forex": [
            {
                "pair": "DXY",
                "name": "DXY美元指数(TuShare USDOLLAR代理)",
                "current_rate": 99.0,
                "daily_change": 0.5,
                "change_120d": 1.0,
                "trend": "震荡",
                "source": "TuShare fx_daily(USDOLLAR.FXCM, FX_BASKET proxy)",
                "note": "TuShare FXCM USDOLLAR外汇篮子代理，不等同ICE DXY",
            }
        ],
        "missing_items": [],
    }
    planner = Stage2TaskPlanner(task_file=tmp_path / "tasks.jsonl")

    tasks = planner.build_tasks(payload)

    assert [task for task in tasks if task["indicator_key"] == "DXY"] == []
```

- [ ] **Step 2: Run skip tests**

Run:

```powershell
python -m pytest tests/test_stage2_unified.py::test_task_planner_skips_complete_tushare_etf_flow tests/test_stage2_unified.py::test_task_planner_skips_complete_tushare_dxy_proxy -q
```

Expected:

```text
2 passed
```

- [ ] **Step 3: Add report assertion for fund-flow estimated warning**

In `tests/test_simple_report_integration.py`, add a test that constructs a minimal report payload with `fund_flow.etf.is_estimated=True` and verifies the appendix warning includes ETF:

```python
def test_simple_report_warns_on_estimated_fund_flow_items(tmp_path, monkeypatch):
    from datasource.generators.simple_report import generate_simple_report

    market_data = _minimal_market_data()
    market_data["fund_flow"]["etf"] = {
        "type": "etf",
        "recent_5d": -150.0,
        "total_120d": -3600.0,
        "trend": "流出",
        "source": "websearch_manual",
        "note": "manual estimate",
        "is_estimated": True,
    }
    pring_result = _minimal_pring_result()
    output = tmp_path / "report.md"

    generate_simple_report(market_data, pring_result, output)

    text = output.read_text(encoding="utf-8")
    assert "估计值提醒" in text
    assert "资金流:ETF资金流" in text
```

If `_minimal_market_data` or `_minimal_pring_result` do not exist, create local helper functions in the test file with complete valid stock, commodity, bond, forex, macro, monetary, and fund-flow fields. Do not use empty sections because `generate_simple_report` expects report-ready payloads.

- [ ] **Step 4: Update estimated item collection in `simple_report.py`**

In `_collect_estimated_items`, add fund-flow handling:

```python
        flow_labels = {
            "northbound": "北向资金",
            "southbound": "南向资金",
            "etf": "ETF资金流",
            "margin": "融资融券",
        }
        for key, flow in (market_data.get("fund_flow") or {}).items():
            if isinstance(flow, dict) and flow.get("is_estimated"):
                name = flow_labels.get(key, str(key))
                items.append(f"资金流:{name}")
```

- [ ] **Step 5: Add report assertion for DXY proxy label**

Append a test to `tests/test_simple_report_integration.py`:

```python
def test_simple_report_preserves_tushare_dxy_proxy_label(tmp_path):
    from datasource.generators.simple_report import generate_simple_report

    market_data = _minimal_market_data()
    for item in market_data["forex"]:
        if item["pair"] == "DXY":
            item["name"] = "DXY美元指数(TuShare USDOLLAR代理)"
            item["source"] = "TuShare fx_daily(USDOLLAR.FXCM, FX_BASKET proxy)"
            item["note"] = "TuShare FXCM USDOLLAR外汇篮子代理，不等同ICE DXY"
    pring_result = _minimal_pring_result()
    output = tmp_path / "report.md"

    generate_simple_report(market_data, pring_result, output)

    text = output.read_text(encoding="utf-8")
    assert "DXY美元指数(TuShare USDOLLAR代理)" in text
```

- [ ] **Step 6: Run report and planner tests**

Run:

```powershell
python -m pytest tests/test_stage2_unified.py tests/test_simple_report_integration.py -q
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit report/planner safeguards**

Run:

```powershell
git add tests/test_stage2_unified.py tests/test_simple_report_integration.py src/datasource/generators/simple_report.py
git commit -m "test: guard tushare stage1 report evidence"
```

Expected:

```text
[codex/... test: guard tushare stage1 report evidence]
```

## Task 6: Document TuShare Coverage Boundaries

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `AGENTS.md` data口径**

Add this under the existing TuShare/Data口径 section:

```markdown
- `fund_flow.etf`: Stage1 优先使用 TuShare `etf_share_size` 的沪深 ETF `total_size` 全市场规模变化推导近5日/近120日窗口，`metric_basis=etf_total_size_delta`，来源标注 `TuShare etf_share_size`。该口径是规模变化，不是新闻口径的净申购估算；若接口不可用或窗口不足，继续进入 Stage2/Stage2.5。
- `DXY`: Stage1 可探测 TuShare `fx_obasic(classify=FX_BASKET)` 中的 `USDOLLAR.FXCM` 并用 `fx_daily` 取值；报告名称必须标明 `TuShare USDOLLAR代理`，不得静默当作 ICE DXY。同日若无法稳定获取，继续 Stage2/Stage2.5。
- 以下指标不得仅因 TuShare 有相似接口而替换现有 Stage2/Stage2.5 口径：海外商品 `GC=F/CL=F/BZ=F/HG=F`、`BCOM`、`GSG`、`CN10Y_CDB`、`industrial`、`industrial_sales`、`bdi`、`reserve_ratio`、`reverse_repo`、`mlf`。
```

- [ ] **Step 2: Sync `CLAUDE.md` quick reminder**

If `CLAUDE.md` contains Stage1/Stage2 data口径 reminders, add this concise bullet:

```markdown
- Stage1 TuShare 可新增 `fund_flow.etf` 的 `etf_share_size` 规模变化口径，以及 DXY 的 `USDOLLAR.FXCM` 代理探测；其它 Stage2.5 指标不得用相似 TuShare 口径静默替代。
```

If `CLAUDE.md` has no comparable section, do not create a new long section; keep `AGENTS.md` authoritative.

- [ ] **Step 3: Run doc grep**

Run:

```powershell
Select-String -LiteralPath AGENTS.md,CLAUDE.md -Pattern 'etf_share_size|USDOLLAR|CN10Y_CDB|reverse_repo|MLF'
```

Expected:

```text
AGENTS.md:... etf_share_size
AGENTS.md:... USDOLLAR
AGENTS.md:... CN10Y_CDB
```

- [ ] **Step 4: Commit docs**

Run:

```powershell
git add AGENTS.md CLAUDE.md
git commit -m "docs: clarify tushare stage1 coverage"
```

Expected:

```text
[codex/... docs: clarify tushare stage1 coverage]
```

## Task 7: End-To-End Validation

**Files:**
- No new code files.
- Use current daily pipeline scripts.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m pytest tests/test_stage1_data_collector.py tests/test_fund_flow_pipeline.py tests/test_stage2_unified.py tests/test_simple_report_integration.py -q
```

Expected:

```text
passed
```

- [ ] **Step 2: Run syntax check**

Run:

```powershell
python -m py_compile scripts/stage1_data_collector.py src/datasource/models/market_data_contract.py src/datasource/generators/simple_report.py
```

Expected:

```text
<no output>
```

- [ ] **Step 3: Run Stage1 for a sandbox date only if TuShare key is available**

Run:

```powershell
bash run_clean.sh python scripts/stage1_data_collector.py --date "2026-04-29" --output "data/runs/20260429/market_data_tushare_stage1_probe.json"
```

Expected if `TUSHARE_TOKEN` has ETF permission:

```text
[OK] ETF资金流已通过TuShare etf_share_size规模变化推导
```

Expected if permission is missing:

```text
[WARN] TuShare etf_share_size暂未返回完整窗口，ETF仍记为缺口
```

The missing-permission case is acceptable. It must not break Stage1 or remove the Stage2/Stage2.5 fallback.

- [ ] **Step 4: Inspect the sandbox Stage1 output**

Run:

```powershell
$p = Get-Content -Raw -Encoding UTF8 -LiteralPath 'data\runs\20260429\market_data_tushare_stage1_probe.json' | ConvertFrom-Json
$p.fund_flow.etf | ConvertTo-Json -Depth 5
$p.forex | Where-Object { $_.pair -eq 'DXY' } | ConvertTo-Json -Depth 5
```

Expected for ETF success:

```text
"source": "TuShare etf_share_size"
"metric_basis": "etf_total_size_delta"
"is_estimated": false
```

Expected for DXY success:

```text
"name": "DXY美元指数(TuShare USDOLLAR代理)"
"source": "TuShare fx_daily(USDOLLAR.FXCM, FX_BASKET proxy)"
```

- [ ] **Step 5: Check whitespace**

Run:

```powershell
git diff --check
```

Expected:

```text
<no output>
```

- [ ] **Step 6: Final commit if validation edits were needed**

If validation required fixes, commit them:

```powershell
git add scripts/stage1_data_collector.py src/datasource/models/market_data_contract.py src/datasource/generators/simple_report.py tests/test_stage1_data_collector.py tests/test_stage2_unified.py tests/test_simple_report_integration.py AGENTS.md CLAUDE.md
git commit -m "fix: stabilize tushare stage1 probes"
```

Expected:

```text
[codex/... fix: stabilize tushare stage1 probes]
```

## Scope Boundaries

This plan intentionally does not implement these replacements:

- `GC=F`, `CL=F`, `BZ=F`, `HG=F`: TuShare futures daily is a different contract universe from the report's overseas futures symbols.
- `BCOM`: TuShare南华指数 is not Bloomberg Commodity Index.
- `GSG`: TuShare does not provide the same iShares GSCI ETF quote.
- `CN10Y_CDB`: existing TuShare `yc_cb` path covers国债曲线; it does not provide a stable 10Y国开债 curve口径.
- `industrial` and `industrial_sales`: keep NBS WebSearch/Stage2.5.
- `bdi`: keep WebSearch/Stage2.5.
- `reserve_ratio`, `reverse_repo`, and `mlf`: keep PBoC/CEIC/WebSearch口径; TuShare repo or interest-rate data is not the same policy-rate contract.

Stage2.5 positioning:

- Stage2.5 is the final fallback for data that Stage1 and Stage2 did not obtain, did not obtain completely, or obtained but failed policy/quality validation.
- Moving ETF and DXY upstream does not remove their Stage2.5 fallback. If `etf_share_size` lacks permission, has insufficient trade-date windows, or returns malformed values, `fund_flow.etf` must remain a Stage2/Stage2.5 gap.
- If TuShare cannot discover a stable `USDOLLAR.FXCM` basket or `fx_daily` returns no usable rows, DXY must remain a Stage2/Stage2.5 gap.
- Stage2.5 should not be used to overwrite valid Stage1/Stage2 data unless the value is stale, incomplete, or explicitly blocked by quality policy.

## Self-Review

Spec coverage:

- ETF Stage1 migration plus Stage2.5 fallback preservation is covered by Tasks 1, 2, 5, and 7.
- DXY TuShare probe plus Stage2.5 fallback preservation is covered by Tasks 3, 4, 5, and 7.
- The "do not replace non-equivalent口径" requirement is covered by Task 6 and the Scope Boundaries section.
- Report evidence is covered by Task 5.

Placeholder scan:

- The plan contains no `TBD`, no `TODO`, no "implement later", and no unexplained "add tests" step.
- Every code-edit step includes concrete code.

Type consistency:

- `FundFlowData.is_estimated` is defined before tests assert it.
- `ForexData.as_of_date` and `ForexData.note` are defined before DXY tests assert them.
- ETF `metric_basis` is consistently `etf_total_size_delta`.
- DXY source label is consistently `TuShare fx_daily(USDOLLAR.FXCM, FX_BASKET proxy)`.
