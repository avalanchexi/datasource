"""TuShare ETF total-size structured provider."""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence

from datasource.providers.stage2_structured.base import (
    Stage2StructuredProvider,
    StructuredProviderError,
    StructuredResult,
)
from datasource.providers.stage2_structured.source_tiers import (
    classify_structured_source_tier,
)


SOURCE_URL = "https://tushare.pro/document/2"
EXCHANGES = ("SSE", "SZSE")
WINDOW_DATES = 121
ETF_COMPLETENESS_ROW_FLOOR_RATIO = 0.8


class TuShareETFProvider(Stage2StructuredProvider):
    name = "tushare_etf"
    supported_keys = {"etf"}

    def __init__(self, pro=None) -> None:
        self._pro = pro

    async def fetch(self, task, market_payload, reference_date):
        key = str(task.get("indicator_key") or "")
        if key != "etf":
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="unsupported_key",
                message="TuShare ETF provider does not support {0}".format(key),
            )

        try:
            pro = self._get_pro()
        except Exception as exc:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="fetch_error",
                message=str(exc),
                diagnostics={"source_url": SOURCE_URL, "api": "pro_api"},
            )
        diagnostics: Dict[str, Any] = {
            "source_url": SOURCE_URL,
            "window_evidence": "direct_balance_delta",
            "exchange_count": len(EXCHANGES),
        }
        trade_dates = self._fetch_trade_dates(
            pro,
            key,
            reference_date,
            diagnostics,
            min_dates=WINDOW_DATES,
            candidate_dates=WINDOW_DATES + 10,
        )
        records_by_date: Dict[str, Dict[str, Sequence[Mapping[str, Any]]]] = {}
        row_count = 0
        for trade_date in trade_dates:
            records_by_exchange = {}
            for exchange in EXCHANGES:
                records = self._fetch_share_size_records(pro, trade_date, exchange)
                row_count += len(records)
                records_by_exchange[exchange] = records
            records_by_date[trade_date] = records_by_exchange

        max_rows_by_exchange = _max_usable_rows_by_exchange(records_by_date)
        min_rows_by_exchange = _min_usable_rows_by_exchange(records_by_date)
        diagnostics.update(
            {
                "row_count_floor_ratio": ETF_COMPLETENESS_ROW_FLOOR_RATIO,
                "max_usable_rows_by_exchange": dict(max_rows_by_exchange),
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

        latest_trade_date_was_incomplete = bool(trade_dates) and (
            trade_dates[-1] in skipped_incomplete_trade_dates
        )
        usable_trade_dates = list(trade_dates)
        while usable_trade_dates and usable_trade_dates[-1] not in totals_by_date:
            usable_trade_dates.pop()

        complete_date_count = len(totals_by_date)
        window_dates = usable_trade_dates[-WINDOW_DATES:]
        incomplete_window_dates = [
            trade_date for trade_date in window_dates if trade_date not in totals_by_date
        ]

        if len(window_dates) < WINDOW_DATES or incomplete_window_dates:
            blocked_details = first_incomplete_details
            if incomplete_window_dates:
                blocked_details = incomplete_details_by_date[incomplete_window_dates[0]]
            blocked = _policy_blocked_diagnostics(
                diagnostics,
                **blocked_details,
                date_count=len(window_dates),
                candidate_date_count=len(trade_dates),
                complete_date_count=complete_date_count,
                row_count=row_count,
                skipped_incomplete_trade_dates=skipped_incomplete_trade_dates,
                latest_trade_date=trade_dates[-1] if trade_dates else None,
                latest_trade_date_was_incomplete=latest_trade_date_was_incomplete,
                incomplete_window_trade_dates=incomplete_window_dates,
                metric_basis="etf_total_size_delta",
            )
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="policy_gate_blocked",
                message="TuShare ETF share-size window is not a complete continuous window",
                diagnostics=blocked,
            )

        totals = [totals_by_date[trade_date] for trade_date in window_dates]

        recent_5d = round(totals[-1] - totals[-6], 4)
        total_120d = round(totals[-1] - totals[0], 4)
        diagnostics.update(
            {
                "date_count": len(window_dates),
                "candidate_date_count": len(trade_dates),
                "complete_date_count": complete_date_count,
                "row_count": row_count,
                "row_count_floor_ratio": ETF_COMPLETENESS_ROW_FLOOR_RATIO,
                "max_usable_rows_by_exchange": dict(max_rows_by_exchange),
                "min_required_rows_by_exchange": dict(min_rows_by_exchange),
                "latest_trade_date": window_dates[-1],
                "start_trade_date": window_dates[0],
                "metric_basis": "etf_total_size_delta",
                "skipped_incomplete_trade_dates": skipped_incomplete_trade_dates,
                "latest_trade_date_was_incomplete": latest_trade_date_was_incomplete,
            }
        )

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
                "metric_basis": "etf_total_size_delta",
                "window_evidence": "direct_balance_delta",
                "is_estimated": False,
            },
            source="TuShare etf_share_size total-size windows",
            source_url=SOURCE_URL,
            source_tier=classify_structured_source_tier(SOURCE_URL),
            as_of_date=window_dates[-1],
            confidence=0.95,
            diagnostics=diagnostics,
        )

    def _get_pro(self):
        if self._pro is not None:
            return self._pro

        import tushare as ts

        token = os.environ.get("TUSHARE_TOKEN")
        if token:
            return ts.pro_api(token)
        return ts.pro_api()

    def _fetch_trade_dates(
        self,
        pro,
        key: str,
        reference_date: str,
        diagnostics: Mapping[str, Any],
        min_dates: int = WINDOW_DATES,
        candidate_dates: Optional[int] = None,
    ) -> List[str]:
        try:
            reference_dt = _parse_reference_date(reference_date)
        except ValueError:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="invalid_reference_date",
                message="TuShare ETF provider requires YYYY-MM-DD or YYYYMMDD reference_date",
                diagnostics={"source_url": SOURCE_URL, "reference_date": reference_date},
            )
        end_date = reference_dt.strftime("%Y%m%d")
        start_date = (reference_dt - timedelta(days=240)).strftime("%Y%m%d")
        try:
            rows = _records(
                pro.trade_cal(
                    exchange="",
                    start_date=start_date,
                    end_date=end_date,
                    is_open=1,
                )
            )
        except Exception as exc:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="fetch_error",
                message=str(exc),
                diagnostics={
                    "source_url": SOURCE_URL,
                    "api": "trade_cal",
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
        open_dates = sorted(
            {
                str(row.get("cal_date"))
                for row in rows
                if row.get("cal_date") and str(row.get("is_open", 1)) in {"1", "1.0"}
            }
        )
        if len(open_dates) < min_dates:
            blocked = _policy_blocked_diagnostics(
                diagnostics,
                open_date_count=len(open_dates),
                min_date_count=min_dates,
                start_date=start_date,
                end_date=end_date,
            )
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="policy_gate_blocked",
                message="TuShare trade calendar has fewer than required open dates",
                diagnostics=blocked,
            )
        take_count = max(min_dates, candidate_dates or min_dates)
        return open_dates[-take_count:]

    def _fetch_share_size_records(
        self, pro, trade_date: str, exchange: str
    ) -> List[Dict[str, Any]]:
        try:
            data = pro.etf_share_size(trade_date=trade_date, exchange=exchange)
        except TypeError:
            try:
                data = pro.etf_share_size(trade_date=trade_date, market=exchange)
            except Exception as exc:
                raise StructuredProviderError(
                    provider=self.name,
                    indicator_key="etf",
                    reason="fetch_error",
                    message=str(exc),
                    diagnostics={
                        "source_url": SOURCE_URL,
                        "api": "etf_share_size",
                        "trade_date": trade_date,
                        "exchange": exchange,
                    },
                )
        except Exception as exc:
            raise StructuredProviderError(
                provider=self.name,
                indicator_key="etf",
                reason="fetch_error",
                message=str(exc),
                diagnostics={
                    "source_url": SOURCE_URL,
                    "api": "etf_share_size",
                    "trade_date": trade_date,
                    "exchange": exchange,
                },
            )
        return _records(data)


def _records(data: Any) -> List[Dict[str, Any]]:
    if data is None:
        return []
    if hasattr(data, "empty") and bool(data.empty):
        return []
    if hasattr(data, "to_dict"):
        try:
            records = data.to_dict("records")
        except TypeError:
            records = data.to_dict()
        if isinstance(records, list):
            return [dict(row) for row in records if isinstance(row, Mapping)]
        if isinstance(records, Mapping):
            return [dict(records)]
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        return [dict(row) for row in data if isinstance(row, Mapping)]
    if isinstance(data, Mapping):
        return [dict(data)]
    return []


def _parse_reference_date(value: Any) -> datetime:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(text)


def _normalize_trade_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return text


def _record_matches_request(record: Mapping[str, Any], trade_date: str, exchange: str) -> bool:
    row_trade_date = record.get("trade_date")
    if row_trade_date is not None and _normalize_trade_date(row_trade_date) != trade_date:
        return False
    row_exchange = record.get("exchange")
    if row_exchange is not None and str(row_exchange).strip().upper() != exchange:
        return False
    row_market = record.get("market")
    if row_market is not None and str(row_market).strip().upper() != exchange:
        return False
    return True


def _max_usable_rows_by_exchange(
    records_by_date: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]
) -> Dict[str, int]:
    max_counts: Dict[str, int] = {}
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
        max_counts[exchange] = max(counts) if counts else 1
    return max_counts


def _min_usable_rows_by_exchange(
    records_by_date: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]
) -> Dict[str, int]:
    floors: Dict[str, int] = {}
    for exchange, reference_count in _max_usable_rows_by_exchange(
        records_by_date
    ).items():
        floors[exchange] = max(
            1,
            int(math.ceil(reference_count * ETF_COMPLETENESS_ROW_FLOOR_RATIO)),
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
            _usable_total_sizes(
                records_by_exchange.get(exchange, []), trade_date, exchange
            )
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


def _policy_blocked_diagnostics(diagnostics: Mapping[str, Any], **details: Any) -> Dict[str, Any]:
    blocked = dict(diagnostics)
    blocked["terminal_structured_provider_error"] = True
    blocked.update(details)
    return blocked


def _trend(value: float) -> str:
    if value > 0:
        return "流入"
    if value < 0:
        return "流出"
    return "持平"


def build_provider() -> TuShareETFProvider:
    return TuShareETFProvider()
