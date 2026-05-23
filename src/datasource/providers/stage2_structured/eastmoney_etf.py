"""EastMoney ETF fund-flow structured provider."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.http_fetcher import (
    fetch_json as default_fetch_json,
)
from datasource.providers.stage2_structured.source_tiers import (
    classify_structured_source_tier,
)


FetchJson = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Dict[str, Any]]]


API_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
SOURCE_URL = "https://data.eastmoney.com/etf/"
MIN_DAILY_ROWS = 120


class EastMoneyETFProvider(Stage2StructuredProvider):
    name = "eastmoney_etf"
    supported_keys = {"etf"}

    def __init__(self, fetch_json: FetchJson = default_fetch_json) -> None:
        self._fetch_json = fetch_json

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        if key != "etf":
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="unsupported_key",
                message="EastMoney ETF provider does not support {0}".format(key),
            )

        params = {
            "secid": "90.BKETF",
            "klt": "101",
            "fqt": "1",
            "lmt": "120",
            "end": reference_date.replace("-", ""),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
        try:
            data = await self._fetch_json(API_URL, params)
        except StructuredProviderError:
            raise
        except Exception as exc:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="fetch_error",
                message=str(exc),
                diagnostics={
                    "api_url": API_URL,
                    "params": params,
                    "source_url": SOURCE_URL,
                },
            )

        rows = _extract_rows(data)
        usable_rows, malformed_count = _parse_daily_rows(rows)
        row_count = len(usable_rows)
        diagnostics = {
            "api_url": API_URL,
            "params": params,
            "source_url": SOURCE_URL,
            "row_count": row_count,
            "raw_row_count": len(rows),
            "malformed_row_count": malformed_count,
            "evidence": "direct_daily_series",
        }

        if row_count == 0:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="parse_error",
                message="EastMoney ETF response did not contain usable daily net-flow rows",
                diagnostics=diagnostics,
            )

        if row_count < MIN_DAILY_ROWS:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="policy_gate_blocked",
                message="EastMoney ETF direct daily series has fewer than 120 usable rows",
                diagnostics=diagnostics,
            )

        latest_120 = usable_rows[-MIN_DAILY_ROWS:]
        recent_5d = round(sum(value for _, value in latest_120[-5:]), 4)
        total_120d = round(sum(value for _, value in latest_120), 4)
        as_of_date = latest_120[-1][0]

        return StructuredResult(
            provider=self.name,
            indicator_key=key,
            category="fund_flow",
            payload={
                "value": recent_5d,
                "recent_5d": recent_5d,
                "total_120d": total_120d,
                "trend": _trend(recent_5d),
                "unit": "亿元",
                "metric_basis": "net_flow_sum",
                "window_evidence": "direct_daily_series",
                "is_estimated": False,
            },
            source="EastMoney ETF direct daily series",
            source_url=SOURCE_URL,
            source_tier=classify_structured_source_tier(SOURCE_URL),
            as_of_date=as_of_date,
            confidence=0.9,
            diagnostics=diagnostics,
        )


def _extract_rows(data: Mapping[str, Any]) -> List[Any]:
    payload = data.get("data") if isinstance(data, Mapping) else None
    if isinstance(payload, Mapping):
        rows = payload.get("klines")
        if isinstance(rows, list):
            return rows
    rows = data.get("klines") if isinstance(data, Mapping) else None
    if isinstance(rows, list):
        return rows
    return []


def _parse_daily_rows(rows: Iterable[Any]) -> Tuple[List[Tuple[str, float]], int]:
    usable_rows = []
    malformed_count = 0
    for row in rows:
        parsed = _parse_daily_row(row)
        if parsed is None:
            malformed_count += 1
            continue
        usable_rows.append(parsed)
    return usable_rows, malformed_count


def _parse_daily_row(row: Any) -> Optional[Tuple[str, float]]:
    if isinstance(row, Mapping):
        date = row.get("date") or row.get("trade_date")
        net_flow = row.get("net_flow")
        if date is None or net_flow is None:
            return None
        try:
            return str(date), float(str(net_flow).replace(",", ""))
        except (TypeError, ValueError):
            return None

    if isinstance(row, str):
        # EastMoney kline strings do not expose field names. Avoid guessing which
        # numeric column is net flow, because close/volume/amount fields may be present.
        parts = [part.strip() for part in row.split(",")]
        if len(parts) >= 2 and parts[0]:
            return None

    return None


def _trend(value: float) -> str:
    if value > 0:
        return "流入"
    if value < 0:
        return "流出"
    return "持平"


def build_provider() -> EastMoneyETFProvider:
    return EastMoneyETFProvider()
