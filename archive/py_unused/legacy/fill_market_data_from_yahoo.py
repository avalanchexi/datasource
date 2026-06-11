#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【已禁用】历史 Yahoo Finance/ETF 代理诊断脚本。

禁止用本脚本直接生成最终 `market_data_complete.json`。若事故排查中
得到可用数据，必须转换为 Stage2.5 manual/WebSearch JSON 后通过
`scripts/stage2_5_injector.py` 注入。

示例:
    PYTHONPATH=. python3 scripts/legacy/fill_market_data_from_yahoo.py \
        --input data/runs/20251117/market_data_stage2.json \
        --output data/runs/20251117/legacy_yahoo_diagnostic.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


COMMODITY_TICKERS: Dict[str, Dict[str, str]] = {
    "GC=F": {"ticker": "GC=F", "name": "COMEX黄金", "unit": "$/oz"},
    "CL=F": {"ticker": "CL=F", "name": "WTI原油", "unit": "$/barrel"},
    "BZ=F": {"ticker": "BZ=F", "name": "Brent原油", "unit": "$/barrel"},
    "HG=F": {"ticker": "HG=F", "name": "COMEX铜", "unit": "$/lb"},
    "BCOM": {"ticker": "BCOM", "name": "BCOM指数", "unit": "点"},
    "GSG": {"ticker": "GSG", "name": "GSG ETF", "unit": "$"},
}

BOND_TICKERS: Dict[str, Dict[str, str]] = {
    "US10Y": {
        "ticker": "^TNX",
        "name": "美国10年期国债收益率",
        "unit": "%",
        "type": "yield",
    },
    "CN10Y": {
        "ticker": "511010.SS",  # 上证10年国债ETF
        "name": "中国10年期国债（ETF代理）",
        "unit": "%",
        "type": "etf_proxy",
        "note": "采用511010.SS收盘价估算，仅供方向参考",
    },
    "CN10Y_CDB": {
        "ticker": "019649.SZ",  # 国开10Y ETF
        "name": "中国10年期国开债（ETF代理）",
        "unit": "%",
        "type": "etf_proxy",
        "note": "采用019649.SZ收盘价估算，仅供方向参考",
    },
}

REQUEST_INTERVAL = 1.0  # seconds
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0
CACHE_DIR = Path("data/cache/yahoo")
CACHE_TTL_DAYS = 3
_LAST_REQUEST_TS = 0.0
YAHOO_DISABLED = True  # 全局开关：禁止访问 Yahoo 接口


def _is_placeholder_value(value: Any) -> bool:
    if value in (None, "", "N/A"):
        return True
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return True
    if abs(numeric) < 1e-9:
        return True
    return abs(numeric - 7.13) < 1e-3


def _cache_path(ticker: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{ticker.replace('/', '_')}.json"


def _load_cache(ticker: str) -> Optional[List[Dict[str, float]]]:
    path = _cache_path(ticker)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload.get("fetched_at"))
        if datetime.now() - fetched_at > timedelta(days=CACHE_TTL_DAYS):
            return None
        rows = payload.get("rows", [])
        parsed = [
            {"date": datetime.fromisoformat(item["date"]), "close": float(item["close"])}
            for item in rows
        ]
        print(f"  [Cache] 命中 {ticker} 历史行情缓存")
        return parsed
    except Exception:
        return None


def _save_cache(ticker: str, rows: List[Dict[str, float]]) -> None:
    payload = {
        "fetched_at": datetime.now().isoformat(),
        "rows": [{"date": r["date"].isoformat(), "close": r["close"]} for r in rows],
    }
    path = _cache_path(ticker)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _respect_rate_limit() -> None:
    global _LAST_REQUEST_TS
    elapsed = time.time() - _LAST_REQUEST_TS
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)


def _download_history(ticker: str, days: int = 400) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
    if YAHOO_DISABLED:
        raise RuntimeError("Yahoo Finance access disabled by policy")
    cached = _load_cache(ticker)
    if cached:
        return cached, {"source": "cache", "retries": 0}

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=days)
    url = (
        f"https://query1.finance.yahoo.com/v7/finance/download/{ticker}"
        f"?period1={int(start.timestamp())}"
        f"&period2={int(end.timestamp())}"
        f"&interval=1d&events=history&includeAdjustedClose=true"
    )

    backoff = REQUEST_INTERVAL
    for attempt in range(1, MAX_RETRIES + 1):
        _respect_rate_limit()
        resp = requests.get(url, timeout=20)
        globals()["_LAST_REQUEST_TS"] = time.time()
        if resp.status_code == 200:
            reader = csv.DictReader(io.StringIO(resp.text))
            rows: List[Dict[str, float]] = []
            for row in reader:
                close_val = row.get("Close")
                date_val = row.get("Date")
                if not close_val or not date_val or close_val in ("null", "None"):
                    continue
                try:
                    close = float(close_val)
                    date = datetime.strptime(date_val, "%Y-%m-%d")
                except ValueError:
                    continue
                rows.append({"date": date, "close": close})
            if not rows:
                raise ValueError(f"{ticker} 无有效历史数据")
            meta = {"source": "network", "retries": attempt - 1}
            _save_cache(ticker, rows)
            return rows, meta

        if resp.status_code == 429 or resp.status_code >= 500:
            wait = backoff * (BACKOFF_FACTOR ** (attempt - 1))
            print(f"  [WARN] {ticker} 请求失败({resp.status_code})，{wait:.1f}s 后重试...")
            time.sleep(wait)
            continue

        raise ValueError(f"{ticker} 请求失败: {resp.status_code}")

    raise ValueError(f"{ticker} 请求连续失败 (429/网络异常)")


def _calc_pct_change(latest: float, previous: Optional[float]) -> Optional[float]:
    if previous in (None, 0):
        return None
    return (latest / previous - 1.0) * 100


def _calc_basis_points(latest: float, previous: Optional[float]) -> Optional[float]:
    if previous is None:
        return None
    return (latest - previous) * 100


def _latest_and_reference(series: List[Dict[str, float]], offset: int) -> tuple[float, Optional[float]]:
    latest = float(series[-1]["close"])
    ref = float(series[-offset - 1]["close"]) if len(series) > offset else None
    return latest, ref


class MarketDataFiller:
    def __init__(self, input_path: Path, output_path: Path) -> None:
        self.input_path = input_path
        self.output_path = output_path
        self.payload = json.loads(input_path.read_text(encoding="utf-8"))
        self.fetch_records: List[Dict[str, Any]] = []

    def fill(self) -> None:
        self._fill_commodities()
        self._fill_bonds()
        self.payload["metadata"]["generation_time"] = datetime.now().isoformat()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(self.payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] 商品/债券数据更新完成 → {self.output_path}")

    def _fill_commodities(self) -> None:
        commodities: List[Dict[str, str]] = self.payload.get("commodities", [])
        if not commodities:
            return

        print("\n[Commodity] 使用 Yahoo Finance 获取实时价格")
        start_of_year = datetime(datetime.now().year, 1, 2)

        for row in commodities:
            symbol = row.get("symbol")
            target = COMMODITY_TICKERS.get(symbol)
            if not target:
                continue
            if not _is_placeholder_value(row.get("current_price")):
                continue
            ticker = target["ticker"]
            try:
                history, meta = _download_history(ticker)
                self._record_fetch(ticker, meta)
                latest, prev = _latest_and_reference(history, 1)
                ytd_rows = [item for item in history if item["date"] >= start_of_year]
                ytd_base = ytd_rows[0]["close"] if ytd_rows else None

                row["current_price"] = round(latest, 4)
                row["daily_change"] = round(_calc_pct_change(latest, prev) or 0.0, 2)
                row["ytd_change"] = round(_calc_pct_change(latest, ytd_base) or 0.0, 2)
                row["trend"] = "上涨" if row["daily_change"] >= 0 else "下跌"
                row["unit"] = target["unit"]
                row["source"] = f"Yahoo Finance ({ticker})"
                row["timestamp"] = datetime.now().isoformat()
                row.pop("note", None)
                print(f"  [OK] {target['name']}: {row['current_price']} {row['unit']}, 日变动 {row['daily_change']:+.2f}%")
            except Exception as err:
                row["current_price"] = None
                row["daily_change"] = None
                row["ytd_change"] = None
                row["trend"] = "N/A"
                row["source"] = f"N/A ({err})"
                row["timestamp"] = datetime.now().isoformat()
                print(f"  [WARN] {target['name']} 获取失败: {err}")

    def _fill_bonds(self) -> None:
        bonds: List[Dict[str, str]] = self.payload.get("bonds", [])
        if not bonds:
            return

        print("\n[Bond] 更新国债收益率/ETF代理")
        for row in bonds:
            symbol = row.get("symbol")
            target = BOND_TICKERS.get(symbol)
            if not target:
                continue
            if not _is_placeholder_value(row.get("current_yield")):
                continue
            ticker = target["ticker"]
            try:
                history, meta = _download_history(ticker)
                self._record_fetch(ticker, meta)
                latest, prev_5d = _latest_and_reference(history, 5)
                _, prev_120d = _latest_and_reference(history, 120)

                if target["type"] == "yield":
                    row["current_yield"] = round(latest, 4)
                else:  # ETF proxy
                    row["current_yield"] = round(latest, 4)
                    row["note"] = target.get("note")

                row["change_5d_bp"] = round(_calc_basis_points(latest, prev_5d) or 0.0, 2)
                row["change_120d_bp"] = round(_calc_basis_points(latest, prev_120d) or 0.0, 2)
                row["trend"] = "收益率上行" if row["change_5d_bp"] > 0 else "收益率下行"
                row["source"] = f"Yahoo Finance ({ticker})"
                row["is_estimated"] = False
                print(f"  [OK] {target['name']}: {row['current_yield']}{target['unit']} (5日Δ {row['change_5d_bp']:+.2f}bp)")
            except Exception as err:
                row["current_yield"] = None
                row["change_5d_bp"] = None
                row["change_120d_bp"] = None
                row["trend"] = "N/A"
                row["source"] = f"N/A ({err})"
                print(f"  [WARN] {target['name']} 获取失败: {err}")

    def _record_fetch(self, ticker: str, meta: Dict[str, Any]) -> None:
        record = {"ticker": ticker}
        record.update(meta)
        self.fetch_records.append(record)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="【已禁用】使用Yahoo Finance填充Stage2商品/债券数据（接口被禁用，脚本仅保留占位）"
    )
    parser.add_argument("--input", required=True, help="Stage2输出文件 (market_data_stage2.json)")
    parser.add_argument("--output", required=True, help="legacy 诊断输出文件，不得作为最终 complete 数据")
    return parser.parse_args()


def main() -> None:
    # 确保不会再触发 Yahoo API 访问
    raise RuntimeError(
        "fill_market_data_from_yahoo.py 已停用：禁止访问 Yahoo Finance。"
        "请改用 Stage2.5 manual/WebSearch JSON 注入后再生成报告。"
    )


if __name__ == "__main__":
    main()
