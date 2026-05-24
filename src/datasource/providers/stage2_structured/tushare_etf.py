"""TuShare ETF total-size structured provider."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Sequence

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
        trade_dates = self._fetch_trade_dates(pro, key, reference_date, diagnostics)
        totals = []
        row_count = 0
        for trade_date in trade_dates:
            total_wan = 0.0
            for exchange in EXCHANGES:
                records = self._fetch_share_size_records(pro, trade_date, exchange)
                row_count += len(records)
                usable = []
                for record in records:
                    total_size = record.get("total_size")
                    if total_size is None:
                        continue
                    try:
                        value = float(total_size)
                    except (TypeError, ValueError):
                        continue
                    if value > 0:
                        usable.append(value)
                if not usable:
                    blocked = dict(diagnostics)
                    blocked.update(
                        {
                            "missing_trade_date": trade_date,
                            "missing_exchange": exchange,
                            "date_count": len(trade_dates),
                            "row_count": row_count,
                        }
                    )
                    raise StructuredProviderError(
                        provider=self.name,
                        indicator_key=key,
                        reason="policy_gate_blocked",
                        message="TuShare ETF share-size window is missing exchange data",
                        diagnostics=blocked,
                    )
                total_wan += sum(usable)
            totals.append(total_wan / 10000.0)

        recent_5d = round(totals[-1] - totals[-6], 4)
        total_120d = round(totals[-1] - totals[0], 4)
        diagnostics.update(
            {
                "date_count": len(trade_dates),
                "row_count": row_count,
                "latest_trade_date": trade_dates[-1],
                "start_trade_date": trade_dates[0],
                "metric_basis": "etf_total_size_delta",
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
            as_of_date=trade_dates[-1],
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
    ) -> List[str]:
        end_date = reference_date.replace("-", "")
        start_date = (
            datetime.strptime(reference_date, "%Y-%m-%d") - timedelta(days=240)
        ).strftime("%Y%m%d")
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
        if len(open_dates) < WINDOW_DATES:
            blocked = dict(diagnostics)
            blocked.update(
                {
                    "open_date_count": len(open_dates),
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )
            raise StructuredProviderError(
                provider=self.name,
                indicator_key=key,
                reason="policy_gate_blocked",
                message="TuShare trade calendar has fewer than 121 open dates",
                diagnostics=blocked,
            )
        return open_dates[-WINDOW_DATES:]

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


def _trend(value: float) -> str:
    if value > 0:
        return "流入"
    if value < 0:
        return "流出"
    return "持平"


def build_provider() -> TuShareETFProvider:
    return TuShareETFProvider()
