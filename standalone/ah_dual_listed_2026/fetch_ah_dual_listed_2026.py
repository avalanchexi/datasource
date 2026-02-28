#!/usr/bin/env python3
"""Fetch A+H dual-listed companies and 2026 market data.

Outputs:
1) dual_listed_companies.csv
2) ah_2026_daily_data.csv
3) ah_2026_summary.csv
4) hsgt_2026_flow_daily.csv
5) hsgt_2026_flow_summary.json
6) ah_2026_report.md
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from html import unescape
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

import pandas as pd
import tushare as ts

DATE_START = "20260101"
DATE_END = "20261231"


@dataclass
class RunConfig:
    output_dir: Path
    token: Optional[str]
    token_env: str
    start_date: str
    end_date: str
    list_source: str
    top_percent: float
    md_only: bool
    limit: int
    sleep_sec: float


def _require_token(token: Optional[str], token_env: str) -> str:
    resolved = token or os.getenv(token_env)
    if not resolved:
        raise RuntimeError(
            f"TuShare token missing. Pass --token or set environment variable {token_env}."
        )
    return resolved


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None


def _compute_return_pct(first_close: Optional[float], last_close: Optional[float]) -> Optional[float]:
    if first_close in (None, 0) or last_close is None:
        return None
    return (last_close - first_close) / abs(first_close) * 100.0


def _normalize_hk_ts_code(hk_code: Any) -> Optional[str]:
    if hk_code is None:
        return None
    text = str(hk_code).strip()
    if not text or text.lower() == "nan":
        return None
    if text.endswith(".HK"):
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    return f"{digits.zfill(5)}.HK"


def _normalize_cn_name(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    out = text.strip().upper()
    out = out.replace("Ａ", "A").replace("Ｂ", "B")
    out = re.sub(r"[\s\-—_·\.,，。()（）\[\]【】]+", "", out)
    for token in ("股份有限公司", "有限公司", "股份", "集团", "控股"):
        out = out.replace(token, "")
    if out.endswith(("A", "B")):
        out = out[:-1]
    if out.startswith("ST"):
        out = out[2:]
    if out.startswith("*ST"):
        out = out[3:]
    return out


def _normalize_en_name(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    out = text.lower()
    out = re.sub(r"[^a-z0-9]+", " ", out)
    drop = {
        "co",
        "company",
        "ltd",
        "limited",
        "inc",
        "corp",
        "corporation",
        "holdings",
        "holding",
        "group",
        "plc",
        "the",
    }
    tokens = [t for t in out.split() if t and t not in drop]
    return " ".join(tokens)


def _clean_html_text(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    out = re.sub(r"<.*?>", "", text)
    out = unescape(out)
    return out.strip()


def _fmt_num(value: Any, digits: int = 2) -> str:
    num = _safe_float(value)
    if num is None:
        return "-"
    return f"{num:.{digits}f}"


def _fmt_pct(value: Any) -> str:
    num = _safe_float(value)
    if num is None:
        return "-"
    return f"{num:.2f}%"


def fetch_dual_listed_from_stk_ah_comparison(
    pro: Any, start_date: str, end_date: str
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Primary path: use stk_ah_comparison as canonical A/H mapping."""
    df = pro.stk_ah_comparison(start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        raise RuntimeError("stk_ah_comparison returned empty data.")

    work = df.copy()
    if "trade_date" in work.columns:
        work["trade_date"] = work["trade_date"].astype(str)
        latest_trade_date = str(work["trade_date"].max())
        work = work[work["trade_date"] == latest_trade_date].copy()
    else:
        latest_trade_date = None

    if "ts_code" not in work.columns or "hk_code" not in work.columns:
        raise RuntimeError("stk_ah_comparison missing required columns: ts_code/hk_code.")

    work["hk_ts_code"] = work["hk_code"].map(_normalize_hk_ts_code)
    work = work[work["ts_code"].notna() & work["hk_ts_code"].notna()].copy()
    work = work.drop_duplicates(subset=["ts_code"]).reset_index(drop=True)

    basic_fields = "ts_code,name,area,industry,market,list_date"
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields=basic_fields)
    if stock_basic is not None and not stock_basic.empty:
        merged = work.merge(stock_basic, on="ts_code", how="left", suffixes=("", "_a"))
    else:
        merged = work.copy()

    if "name_a" in merged.columns:
        merged["name"] = merged["name_a"].fillna(merged.get("name"))
    if "name" not in merged.columns:
        merged["name"] = None
    if "hk_name" not in merged.columns:
        merged["hk_name"] = None
    if "industry" not in merged.columns:
        merged["industry"] = None
    if "area" not in merged.columns:
        merged["area"] = None
    if "market" not in merged.columns:
        merged["market"] = None
    if "list_date" not in merged.columns:
        merged["list_date"] = None

    out_cols = [
        "ts_code",
        "hk_ts_code",
        "name",
        "hk_name",
        "area",
        "industry",
        "market",
        "list_date",
    ]
    dual = merged[out_cols].copy()
    dual = dual.sort_values(by=["ts_code"]).reset_index(drop=True)
    meta = {
        "method": "stk_ah_comparison",
        "latest_trade_date": latest_trade_date,
        "row_count": int(len(dual)),
    }
    return dual, meta


def _enrich_with_basic_info(pro: Any, dual_df: pd.DataFrame) -> pd.DataFrame:
    if dual_df is None or dual_df.empty:
        return pd.DataFrame(
            columns=["ts_code", "hk_ts_code", "name", "hk_name", "area", "industry", "market", "list_date"]
        )

    out = dual_df.copy()
    a_fields = "ts_code,name,area,industry,market,list_date"
    h_fields = "ts_code,name,list_date"
    a_df = pro.stock_basic(exchange="", list_status="L", fields=a_fields)
    h_df = pro.hk_basic(list_status="L", fields=h_fields)

    if a_df is not None and not a_df.empty:
        a_df = a_df.rename(
            columns={
                "name": "a_name",
                "area": "a_area",
                "industry": "a_industry",
                "market": "a_market",
                "list_date": "a_list_date",
            }
        )
        out = out.merge(a_df, on="ts_code", how="left")
        if "name" not in out.columns:
            out["name"] = None
        out["name"] = out["name"].fillna(out.get("a_name"))
        if "area" not in out.columns:
            out["area"] = out.get("a_area")
        else:
            out["area"] = out["area"].fillna(out.get("a_area"))
        if "industry" not in out.columns:
            out["industry"] = out.get("a_industry")
        else:
            out["industry"] = out["industry"].fillna(out.get("a_industry"))
        if "market" not in out.columns:
            out["market"] = out.get("a_market")
        else:
            out["market"] = out["market"].fillna(out.get("a_market"))
        if "list_date" not in out.columns:
            out["list_date"] = out.get("a_list_date")
        else:
            out["list_date"] = out["list_date"].fillna(out.get("a_list_date"))

    if h_df is not None and not h_df.empty:
        h_df = h_df.rename(columns={"ts_code": "hk_ts_code", "name": "h_name", "list_date": "hk_list_date"})
        out = out.merge(h_df[["hk_ts_code", "h_name", "hk_list_date"]], on="hk_ts_code", how="left")
        if "hk_name" not in out.columns:
            out["hk_name"] = out.get("h_name")
        else:
            out["hk_name"] = out["hk_name"].fillna(out.get("h_name"))

    for col in ("name", "hk_name", "area", "industry", "market", "list_date"):
        if col not in out.columns:
            out[col] = None

    keep = ["ts_code", "hk_ts_code", "name", "hk_name", "area", "industry", "market", "list_date"]
    out = out[keep].drop_duplicates(subset=["ts_code"]).sort_values("ts_code").reset_index(drop=True)
    return out


def fetch_dual_listed_from_websearch_aastocks(pro: Any) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """WebSearch path: scrape AASTOCKS A/H table and enrich with TuShare basic info."""
    url = "https://www.aastocks.com/sc/stocks/market/ah.aspx"
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        },
    )
    with urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    update_match = re.search(r'<meta name="aa-update" content="([^"]+)"', html)
    update_time = update_match.group(1) if update_match else None

    rows = re.findall(r'<tr class="ahdata">(.*?)</tr>', html, flags=re.S)
    records: List[Dict[str, Any]] = []
    for row in rows:
        name_match = re.search(
            r'<td class="ahstock[^"]*">.*?<span class=\'float_l\'>(.*?)</span>',
            row,
            flags=re.S,
        )
        hk_match = re.search(r"title='(\d{5}\.HK)'", row)
        a_match = re.search(r"title='(\d{6}\.(?:SH|SZ))'", row)
        if not hk_match or not a_match:
            continue
        records.append(
            {
                "ts_code": a_match.group(1),
                "hk_ts_code": hk_match.group(1),
                "name": _clean_html_text(name_match.group(1)) if name_match else None,
            }
        )

    if not records:
        raise RuntimeError("websearch source returned no A/H mapping rows.")

    raw = pd.DataFrame(records).drop_duplicates(subset=["ts_code"]).reset_index(drop=True)
    dual = _enrich_with_basic_info(pro, raw)

    meta = {
        "method": "websearch_aastocks",
        "source_url": url,
        "source_update_time": update_time,
        "row_count": int(len(dual)),
    }
    return dual, meta


def fetch_dual_listed_from_name_match(pro: Any) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Fallback path: stock_basic + hk_basic exact normalized name matching."""
    a_fields = "ts_code,name,fullname,enname,area,industry,market,list_date"
    h_fields = "ts_code,name,fullname,enname,market,list_date"
    a_df = pro.stock_basic(exchange="", list_status="L", fields=a_fields)
    h_df = pro.hk_basic(list_status="L", fields=h_fields)

    if a_df is None or a_df.empty:
        raise RuntimeError("fallback failed: stock_basic empty.")
    if h_df is None or h_df.empty:
        raise RuntimeError("fallback failed: hk_basic empty.")

    a_work = a_df.copy()
    h_work = h_df.copy()

    for frame in (a_work, h_work):
        frame["k_cn_short"] = frame.get("name", "").map(_normalize_cn_name)
        frame["k_cn_full"] = frame.get("fullname", "").map(_normalize_cn_name)
        frame["k_en"] = frame.get("enname", "").map(_normalize_en_name)

    hk_by_cn_full: Dict[str, List[pd.Series]] = {}
    hk_by_en: Dict[str, List[pd.Series]] = {}
    hk_by_cn_short: Dict[str, List[pd.Series]] = {}
    for _, h_row in h_work.iterrows():
        cn_full = str(h_row.get("k_cn_full") or "")
        en_key = str(h_row.get("k_en") or "")
        cn_short = str(h_row.get("k_cn_short") or "")
        if cn_full:
            hk_by_cn_full.setdefault(cn_full, []).append(h_row)
        if en_key:
            hk_by_en.setdefault(en_key, []).append(h_row)
        if cn_short:
            hk_by_cn_short.setdefault(cn_short, []).append(h_row)

    records: List[Dict[str, Any]] = []
    for _, a_row in a_work.iterrows():
        candidates: Dict[str, pd.Series] = {}
        for key, index_map in (
            (str(a_row.get("k_cn_full") or ""), hk_by_cn_full),
            (str(a_row.get("k_en") or ""), hk_by_en),
            (str(a_row.get("k_cn_short") or ""), hk_by_cn_short),
        ):
            if not key:
                continue
            for c in index_map.get(key, []):
                candidates[str(c["ts_code"])] = c

        if len(candidates) != 1:
            continue
        h_row = next(iter(candidates.values()))
        records.append(
            {
                "ts_code": a_row.get("ts_code"),
                "hk_ts_code": h_row.get("ts_code"),
                "name": a_row.get("name"),
                "hk_name": h_row.get("name"),
                "area": a_row.get("area"),
                "industry": a_row.get("industry"),
                "market": a_row.get("market"),
                "list_date": a_row.get("list_date"),
            }
        )

    if not records:
        raise RuntimeError("fallback failed: no A/H pairs matched by name.")

    dual = pd.DataFrame(records).drop_duplicates(subset=["ts_code"]).sort_values("ts_code")
    meta = {
        "method": "name_match_fallback",
        "row_count": int(len(dual)),
        "match_rule": "normalized fullname/enname, then short name exact match",
    }
    return dual.reset_index(drop=True), meta


def fetch_dual_listed_companies(
    pro: Any, start_date: str, end_date: str, list_source: str = "auto"
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Resolve A+H company list with source strategy.

    list_source:
    - auto: stk_ah_comparison -> websearch_aastocks -> name_match_fallback
    - stk_ah: only use stk_ah_comparison
    - websearch: only use websearch_aastocks
    - name_match: only use name_match_fallback
    """
    list_source = (list_source or "auto").strip().lower()
    errors: List[str] = []

    if list_source == "stk_ah":
        return fetch_dual_listed_from_stk_ah_comparison(pro, start_date, end_date)
    if list_source == "websearch":
        return fetch_dual_listed_from_websearch_aastocks(pro)
    if list_source == "name_match":
        return fetch_dual_listed_from_name_match(pro)

    try:
        return fetch_dual_listed_from_stk_ah_comparison(pro, start_date, end_date)
    except Exception as exc:
        errors.append(f"stk_ah_comparison failed: {exc}")

    try:
        dual, meta = fetch_dual_listed_from_websearch_aastocks(pro)
        meta["fallback_reason"] = "; ".join(errors)
        return dual, meta
    except Exception as exc:
        errors.append(f"websearch_aastocks failed: {exc}")

    dual, meta = fetch_dual_listed_from_name_match(pro)
    meta["fallback_reason"] = "; ".join(errors)
    return dual, meta


def _resolve_recent_open_trade_dates(pro: Any, end_date: str) -> List[str]:
    try:
        end_dt_cfg = datetime.strptime(end_date, "%Y%m%d")
        end_dt = min(end_dt_cfg, datetime.now())
        start_dt = end_dt - timedelta(days=90)
        cal = pro.trade_cal(
            exchange="",
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=end_dt.strftime("%Y%m%d"),
        )
        if cal is None or cal.empty:
            return []
        work = cal.copy()
        work["cal_date"] = work["cal_date"].astype(str)
        open_dates = work[work["is_open"] == 1]["cal_date"].tolist()
        if not open_dates:
            return []
        return sorted(open_dates, reverse=True)
    except Exception:
        return []


def _select_head_companies_by_total_mv(
    pro: Any, dual: pd.DataFrame, end_date: str, top_percent: float
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Select head companies by A-share total market value."""
    if dual is None or dual.empty:
        return dual, {"enabled": False, "reason": "empty_dual_list"}

    pct = float(top_percent)
    if pct >= 100:
        return dual, {"enabled": False, "reason": "top_percent>=100"}

    pick_n = max(1, int(math.ceil(len(dual) * pct / 100.0)))
    trade_dates = _resolve_recent_open_trade_dates(pro, end_date)
    if not trade_dates:
        selected = dual.head(pick_n).copy()
        return selected, {
            "enabled": True,
            "mode": "fallback_head",
            "top_percent": pct,
            "selected_count": int(len(selected)),
            "universe_count": int(len(dual)),
            "reason": "no_recent_open_trade_date",
        }

    daily_basic = None
    trade_date_used = None
    last_error = None
    for trade_date in trade_dates[:20]:
        try:
            daily_basic = pro.daily_basic(
                trade_date=trade_date,
                fields="ts_code,total_mv,circ_mv",
            )
            if daily_basic is not None and not daily_basic.empty:
                trade_date_used = trade_date
                break
        except Exception as exc:
            last_error = str(exc)
            continue

    if daily_basic is None or daily_basic.empty or trade_date_used is None:
        selected = dual.head(pick_n).copy()
        return selected, {
            "enabled": True,
            "mode": "fallback_head",
            "top_percent": pct,
            "selected_count": int(len(selected)),
            "universe_count": int(len(dual)),
            "reason": f"daily_basic_not_available_recently:{last_error or 'empty'}",
            "trade_date": trade_dates[0] if trade_dates else None,
        }

    mv_df = daily_basic.copy()
    if "total_mv" in mv_df.columns:
        mv_df["total_mv"] = pd.to_numeric(mv_df["total_mv"], errors="coerce")
    else:
        mv_df["total_mv"] = None
    if "circ_mv" in mv_df.columns:
        mv_df["circ_mv"] = pd.to_numeric(mv_df["circ_mv"], errors="coerce")
    else:
        mv_df["circ_mv"] = None

    merged = dual.merge(
        mv_df[["ts_code", "total_mv", "circ_mv"]],
        on="ts_code",
        how="left",
    )
    with_mv = merged[merged["total_mv"].notna()].copy()
    no_mv = merged[merged["total_mv"].isna()].copy()
    with_mv = with_mv.sort_values("total_mv", ascending=False)

    selected = with_mv.head(pick_n).copy()
    if len(selected) < pick_n and not no_mv.empty:
        selected = pd.concat([selected, no_mv.head(pick_n - len(selected))], ignore_index=True)
    selected = selected.drop(columns=["total_mv", "circ_mv"], errors="ignore")

    return selected.reset_index(drop=True), {
        "enabled": True,
        "mode": "total_mv",
        "top_percent": pct,
        "selected_count": int(len(selected)),
        "universe_count": int(len(dual)),
        "trade_date": trade_date_used,
        "mv_coverage_count": int(len(with_mv)),
    }


def fetch_a_daily(pro: Any, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        return pd.DataFrame()
    keep_cols = [
        "trade_date",
        "ts_code",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
    ]
    existing = [c for c in keep_cols if c in df.columns]
    out = df[existing].copy()
    out = out.sort_values("trade_date")
    return out


def fetch_h_daily(pro: Any, hk_ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        df = pro.hk_daily(ts_code=hk_ts_code, start_date=start_date, end_date=end_date)
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    keep_cols = [
        "trade_date",
        "ts_code",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
    ]
    existing = [c for c in keep_cols if c in df.columns]
    out = df[existing].copy()
    out = out.sort_values("trade_date")
    return out


def fetch_a_moneyflow(pro: Any, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        df = pro.moneyflow(ts_code=ts_code, start_date=start_date, end_date=end_date)
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    keep_cols = [
        "trade_date",
        "ts_code",
        "net_mf_vol",
        "net_mf_amount",
        "buy_sm_amount",
        "sell_sm_amount",
        "buy_md_amount",
        "sell_md_amount",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
    ]
    existing = [c for c in keep_cols if c in df.columns]
    out = df[existing].copy()
    out = out.sort_values("trade_date")
    return out


def summarize_company(
    company_row: pd.Series,
    a_daily: pd.DataFrame,
    h_daily: pd.DataFrame,
    a_flow: pd.DataFrame,
) -> Dict[str, Any]:
    a_first_close = _safe_float(a_daily["close"].iloc[0]) if not a_daily.empty else None
    a_last_close = _safe_float(a_daily["close"].iloc[-1]) if not a_daily.empty else None
    h_first_close = _safe_float(h_daily["close"].iloc[0]) if not h_daily.empty else None
    h_last_close = _safe_float(h_daily["close"].iloc[-1]) if not h_daily.empty else None

    net_flow = None
    inflow_days = 0
    outflow_days = 0
    gross_inflow = None
    gross_outflow = None
    if not a_flow.empty and "net_mf_amount" in a_flow.columns:
        net_series = pd.to_numeric(a_flow["net_mf_amount"], errors="coerce").dropna()
        if not net_series.empty:
            net_flow = float(net_series.sum())
            inflow = net_series[net_series > 0]
            outflow = net_series[net_series < 0]
            inflow_days = int((net_series > 0).sum())
            outflow_days = int((net_series < 0).sum())
            gross_inflow = float(inflow.sum()) if not inflow.empty else 0.0
            gross_outflow = float((-outflow).sum()) if not outflow.empty else 0.0

    return {
        "company_name": company_row.get("name"),
        "a_ts_code": company_row.get("ts_code"),
        "h_ts_code": company_row.get("hk_ts_code"),
        "industry": company_row.get("industry"),
        "a_trade_days_2026": int(len(a_daily)),
        "h_trade_days_2026": int(len(h_daily)),
        "a_first_close": a_first_close,
        "a_last_close": a_last_close,
        "a_return_pct_2026": _compute_return_pct(a_first_close, a_last_close),
        "h_first_close": h_first_close,
        "h_last_close": h_last_close,
        "h_return_pct_2026": _compute_return_pct(h_first_close, h_last_close),
        "a_net_flow_amount_2026_wan": net_flow,
        "a_gross_inflow_2026_wan": gross_inflow,
        "a_gross_outflow_2026_wan": gross_outflow,
        "a_inflow_days_2026": inflow_days,
        "a_outflow_days_2026": outflow_days,
    }


def build_daily_panel(
    company_row: pd.Series,
    a_daily: pd.DataFrame,
    h_daily: pd.DataFrame,
    a_flow: pd.DataFrame,
) -> pd.DataFrame:
    a_part = pd.DataFrame()
    if not a_daily.empty:
        a_part = a_daily.rename(
            columns={
                "ts_code": "a_ts_code",
                "open": "a_open",
                "high": "a_high",
                "low": "a_low",
                "close": "a_close",
                "vol": "a_vol",
                "amount": "a_amount",
            }
        )

    h_part = pd.DataFrame()
    if not h_daily.empty:
        h_part = h_daily.rename(
            columns={
                "ts_code": "h_ts_code",
                "open": "h_open",
                "high": "h_high",
                "low": "h_low",
                "close": "h_close",
                "vol": "h_vol",
                "amount": "h_amount",
            }
        )

    flow_part = pd.DataFrame()
    if not a_flow.empty:
        flow_part = a_flow.rename(
            columns={
                "ts_code": "a_ts_code",
                "net_mf_vol": "a_net_mf_vol",
                "net_mf_amount": "a_net_mf_amount",
            }
        )

    merged = pd.DataFrame({"trade_date": []})
    if not a_part.empty:
        merged = a_part
    if not h_part.empty:
        merged = h_part if merged.empty else merged.merge(h_part, on="trade_date", how="outer")
    if not flow_part.empty:
        merged = flow_part if merged.empty else merged.merge(flow_part, on=["trade_date", "a_ts_code"], how="outer")

    if merged.empty:
        return merged

    merged["company_name"] = company_row.get("name")
    if "a_ts_code" not in merged.columns:
        merged["a_ts_code"] = None
    if "h_ts_code" not in merged.columns:
        merged["h_ts_code"] = None
    merged["a_ts_code"] = merged["a_ts_code"].fillna(company_row.get("ts_code"))
    merged["h_ts_code"] = merged["h_ts_code"].fillna(company_row.get("hk_ts_code"))
    merged["trade_date"] = merged["trade_date"].astype(str)
    merged = merged.sort_values("trade_date")

    if "a_net_mf_amount" in merged.columns:
        flow_num = pd.to_numeric(merged["a_net_mf_amount"], errors="coerce")
        merged["a_flow_direction"] = flow_num.map(
            lambda x: "inflow" if pd.notna(x) and x > 0 else "outflow" if pd.notna(x) and x < 0 else "flat"
        )

    return merged


def fetch_hsgt_flow_2026(pro: Any, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        df = pro.moneyflow_hsgt(start_date=start_date, end_date=end_date)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    keep_cols = [c for c in ["trade_date", "north_money", "south_money"] if c in df.columns]
    out = df[keep_cols].copy()
    out["trade_date"] = out["trade_date"].astype(str)
    out = out.sort_values("trade_date")
    return out


def summarize_hsgt(hsgt_daily: pd.DataFrame) -> Dict[str, Any]:
    if hsgt_daily.empty:
        return {
            "trade_days": 0,
            "north_total_yi": None,
            "south_total_yi": None,
            "north_inflow_days": 0,
            "north_outflow_days": 0,
            "south_inflow_days": 0,
            "south_outflow_days": 0,
            "unit_note": "TuShare moneyflow_hsgt raw fields are usually in ten-thousand CNY; script converts to yi CNY.",
        }

    north = pd.to_numeric(hsgt_daily.get("north_money"), errors="coerce").dropna()
    south = pd.to_numeric(hsgt_daily.get("south_money"), errors="coerce").dropna()

    unit_divisor = 10000.0
    return {
        "trade_days": int(len(hsgt_daily)),
        "north_total_yi": float(north.sum() / unit_divisor) if not north.empty else None,
        "south_total_yi": float(south.sum() / unit_divisor) if not south.empty else None,
        "north_inflow_days": int((north > 0).sum()) if not north.empty else 0,
        "north_outflow_days": int((north < 0).sum()) if not north.empty else 0,
        "south_inflow_days": int((south > 0).sum()) if not south.empty else 0,
        "south_outflow_days": int((south < 0).sum()) if not south.empty else 0,
        "unit_note": "north_money/south_money converted from ten-thousand CNY to yi CNY.",
    }


def write_markdown_report(
    report_path: Path,
    dual: pd.DataFrame,
    summary_df: pd.DataFrame,
    hsgt_summary: Dict[str, Any],
    list_meta: Dict[str, Any],
    config: RunConfig,
) -> None:
    lines: List[str] = []
    lines.append("# A+H 两地上市公司 2026 数据报告")
    lines.append("")
    lines.append("## 1. 任务概览")
    lines.append("")
    lines.append(f"- 时间区间: {config.start_date} ~ {config.end_date}")
    lines.append(f"- 名单来源策略: `{config.list_source}`")
    lines.append(f"- 实际名单来源: `{list_meta.get('method', 'unknown')}`")
    lines.append(f"- 头部筛选比例: {config.top_percent:.2f}%")
    if list_meta.get("latest_trade_date"):
        lines.append(f"- `stk_ah_comparison` 最新交易日: {list_meta.get('latest_trade_date')}")
    if list_meta.get("source_url"):
        lines.append(f"- WebSearch 来源: {list_meta.get('source_url')}")
    if list_meta.get("source_update_time"):
        lines.append(f"- WebSearch 源更新时间: {list_meta.get('source_update_time')}")
    if list_meta.get("fallback_reason"):
        lines.append(f"- 触发降级原因: {list_meta.get('fallback_reason')}")
    head_meta = list_meta.get("head_filter") or {}
    if head_meta.get("enabled"):
        lines.append(
            f"- 头部筛选结果: {head_meta.get('selected_count', 0)}/{head_meta.get('universe_count', 0)} "
            f"(mode={head_meta.get('mode')}, trade_date={head_meta.get('trade_date', '-')})"
        )
        if head_meta.get("reason"):
            lines.append(f"- 头部筛选备注: {head_meta.get('reason')}")
    lines.append(f"- 两地上市公司数量: {len(dual)}")
    lines.append("")

    lines.append("## 2. 北向/南向资金（TuShare moneyflow_hsgt）")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---:|")
    lines.append(f"| 交易日数量 | {hsgt_summary.get('trade_days', 0)} |")
    lines.append(f"| 北向资金累计（亿元） | {_fmt_num(hsgt_summary.get('north_total_yi'))} |")
    lines.append(f"| 南向资金累计（亿元） | {_fmt_num(hsgt_summary.get('south_total_yi'))} |")
    lines.append(f"| 北向流入天数 | {hsgt_summary.get('north_inflow_days', 0)} |")
    lines.append(f"| 北向流出天数 | {hsgt_summary.get('north_outflow_days', 0)} |")
    lines.append(f"| 南向流入天数 | {hsgt_summary.get('south_inflow_days', 0)} |")
    lines.append(f"| 南向流出天数 | {hsgt_summary.get('south_outflow_days', 0)} |")
    if hsgt_summary.get("unit_note"):
        lines.append(f"| 口径说明 | {hsgt_summary.get('unit_note')} |")
    lines.append("")

    lines.append("## 3. 两地上市公司 2026 汇总")
    lines.append("")
    lines.append("| 公司 | A代码 | H代码 | A涨跌幅 | H涨跌幅 | A净流(万元) | A流入天数 | A流出天数 |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    if summary_df.empty:
        lines.append("| - | - | - | - | - | - | - | - |")
    else:
        show_df = summary_df.sort_values("company_name")
        for _, row in show_df.iterrows():
            lines.append(
                "| {company} | {a} | {h} | {a_ret} | {h_ret} | {flow} | {in_days} | {out_days} |".format(
                    company=str(row.get("company_name") or "-"),
                    a=str(row.get("a_ts_code") or "-"),
                    h=str(row.get("h_ts_code") or "-"),
                    a_ret=_fmt_pct(row.get("a_return_pct_2026")),
                    h_ret=_fmt_pct(row.get("h_return_pct_2026")),
                    flow=_fmt_num(row.get("a_net_flow_amount_2026_wan")),
                    in_days=int(row.get("a_inflow_days_2026") or 0),
                    out_days=int(row.get("a_outflow_days_2026") or 0),
                )
            )
    lines.append("")

    lines.append("## 4. 两地上市名单")
    lines.append("")
    lines.append("| 公司 | A代码 | H代码 | 行业 | 地区 | 上市板块 |")
    lines.append("|---|---|---|---|---|---|")
    if dual.empty:
        lines.append("| - | - | - | - | - | - |")
    else:
        show_dual = dual.sort_values("ts_code")
        for _, row in show_dual.iterrows():
            lines.append(
                "| {name} | {a} | {h} | {industry} | {area} | {market} |".format(
                    name=str(row.get("name") or row.get("hk_name") or "-"),
                    a=str(row.get("ts_code") or "-"),
                    h=str(row.get("hk_ts_code") or "-"),
                    industry=str(row.get("industry") or "-"),
                    area=str(row.get("area") or "-"),
                    market=str(row.get("market") or "-"),
                )
            )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(config: RunConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    token = _require_token(config.token, config.token_env)
    pro = ts.pro_api(token)

    dual, list_meta = fetch_dual_listed_companies(
        pro=pro,
        start_date=config.start_date,
        end_date=config.end_date,
        list_source=config.list_source,
    )
    dual, head_meta = _select_head_companies_by_total_mv(
        pro=pro,
        dual=dual,
        end_date=config.end_date,
        top_percent=config.top_percent,
    )
    list_meta["head_filter"] = head_meta
    if config.limit > 0:
        dual = dual.head(config.limit).copy()

    summary_rows: List[Dict[str, Any]] = []
    daily_frames: List[pd.DataFrame] = []
    total = len(dual)

    for i, (_, row) in enumerate(dual.iterrows(), start=1):
        a_code = str(row["ts_code"])
        h_code = str(row["hk_ts_code"])
        name = str(row.get("name", "UNKNOWN"))
        print(f"[{i}/{total}] fetching {name} ({a_code} / {h_code})")

        a_daily = fetch_a_daily(pro, a_code, config.start_date, config.end_date)
        h_daily = fetch_h_daily(pro, h_code, config.start_date, config.end_date)
        a_flow = fetch_a_moneyflow(pro, a_code, config.start_date, config.end_date)

        summary_rows.append(summarize_company(row, a_daily, h_daily, a_flow))
        if not config.md_only:
            daily_panel = build_daily_panel(row, a_daily, h_daily, a_flow)
            if not daily_panel.empty:
                daily_frames.append(daily_panel)

        if config.sleep_sec > 0:
            time.sleep(config.sleep_sec)

    dual_path = config.output_dir / "dual_listed_companies.csv"
    summary_path = config.output_dir / "ah_2026_summary.csv"
    daily_path = config.output_dir / "ah_2026_daily_data.csv"
    hsgt_daily_path = config.output_dir / "hsgt_2026_flow_daily.csv"
    hsgt_summary_path = config.output_dir / "hsgt_2026_flow_summary.json"
    meta_path = config.output_dir / "dual_list_source_meta.json"
    report_md_path = config.output_dir / "ah_2026_report.md"

    summary_df = pd.DataFrame(summary_rows)
    hsgt_daily = fetch_hsgt_flow_2026(pro, config.start_date, config.end_date)
    hsgt_summary = summarize_hsgt(hsgt_daily)
    write_markdown_report(
        report_path=report_md_path,
        dual=dual,
        summary_df=summary_df,
        hsgt_summary=hsgt_summary,
        list_meta=list_meta,
        config=config,
    )

    if config.md_only:
        print("")
        print("Done.")
        print(f"- markdown report: {report_md_path}")
        return

    dual.to_csv(dual_path, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    if daily_frames:
        pd.concat(daily_frames, ignore_index=True).to_csv(daily_path, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame().to_csv(daily_path, index=False, encoding="utf-8-sig")

    hsgt_daily.to_csv(hsgt_daily_path, index=False, encoding="utf-8-sig")
    with hsgt_summary_path.open("w", encoding="utf-8") as fh:
        json.dump(hsgt_summary, fh, ensure_ascii=False, indent=2)
    with meta_path.open("w", encoding="utf-8") as fh:
        json.dump(list_meta, fh, ensure_ascii=False, indent=2)

    print("")
    print("Done.")
    print(f"- list source meta: {meta_path}")
    print(f"- dual list: {dual_path}")
    print(f"- summary: {summary_path}")
    print(f"- daily panel: {daily_path}")
    print(f"- hsgt daily flow: {hsgt_daily_path}")
    print(f"- hsgt summary flow: {hsgt_summary_path}")
    print(f"- markdown report: {report_md_path}")


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description="Fetch A+H dual-listed companies and 2026 data from TuShare."
    )
    parser.add_argument(
        "--output-dir",
        default="standalone/ah_dual_listed_2026/output",
        help="Output directory for csv/json files.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="TuShare token. If missing, read from --token-env.",
    )
    parser.add_argument(
        "--token-env",
        default="TUSHARE_TOKEN",
        help="Environment variable name to read TuShare token.",
    )
    parser.add_argument(
        "--start-date",
        default=DATE_START,
        help="Start date in YYYYMMDD format.",
    )
    parser.add_argument(
        "--end-date",
        default=DATE_END,
        help="End date in YYYYMMDD format.",
    )
    parser.add_argument(
        "--list-source",
        default="auto",
        choices=["auto", "stk_ah", "websearch", "name_match"],
        help="How to build A/H company list.",
    )
    parser.add_argument(
        "--top-percent",
        type=float,
        default=10.0,
        help="Select head companies by total_mv percentile (0, 100].",
    )
    parser.add_argument(
        "--md-only",
        action="store_true",
        help="Only output markdown report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process first N dual-listed companies; 0 means all.",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=0.15,
        help="Sleep seconds between companies to reduce API pressure.",
    )
    args = parser.parse_args()
    top_percent = float(args.top_percent)
    if top_percent <= 0 or top_percent > 100:
        parser.error("--top-percent must be in (0, 100].")
    return RunConfig(
        output_dir=Path(args.output_dir),
        token=args.token,
        token_env=args.token_env,
        start_date=args.start_date,
        end_date=args.end_date,
        list_source=args.list_source,
        top_percent=top_percent,
        md_only=bool(args.md_only),
        limit=args.limit,
        sleep_sec=args.sleep_sec,
    )


if __name__ == "__main__":
    run(parse_args())
