import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

TARGET_DATE = "2025-10-11"
DATA_SOURCE = "Yahoo Finance"

os.environ["SSL_CERT_FILE"] = "C:/temp/cacert.pem"
os.environ["REQUESTS_CA_BUNDLE"] = "C:/temp/cacert.pem"
os.environ["CURL_CA_BUNDLE"] = "C:/temp/cacert.pem"

end_dt = datetime.strptime(TARGET_DATE, "%Y-%m-%d")
start_dt = end_dt - timedelta(days=260)

HEADERS = {
    "indices": ["\u6307\u6570", "\u6536\u76d8\u4ef7", "\u8fd15\u65e5%", "\u8fd1120\u65e5%"],
    "commodities": ["\u54c1\u79cd", "\u6536\u76d8\u4ef7", "\u8fd15\u65e5%", "\u8fd1120\u65e5%"],
    "forex": ["\u6c47\u7387\u5bf9", "\u6700\u65b0\u4ef7", "\u8fd15\u65e5%", "\u8fd1120\u65e5%"],
    "bonds": ["\u54c1\u79cd", "\u5f53\u524d\u6536\u76ca\u7387%", "\u8fd15\u65e5\u53d8\u52a8(bp)", "\u8fd1120\u65e5\u53d8\u52a8(bp)"]
}

INDEX_MAP = {
    "000001.SS": "\u4e0a\u8bc1\u6307\u6570",
    "399001.SZ": "\u6df1\u8bc1\u6210\u6307",
    "399006.SZ": "\u521b\u4e1a\u677f\u6307",
    "^GSPC": "\u6807\u666e500",
    "^IXIC": "\u7eb3\u65af\u8fbe\u514b\u7efc\u5408"
}

COMMODITY_MAP = {
    "CL=F": "WTI\u539f\u6cb9",
    "BZ=F": "\u5e03\u4f26\u7279\u539f\u6cb9",
    "HG=F": "COMEX\u94dc",
    "GC=F": "COMEX\u9ec4\u91d1",
    "GSG": "BCOM\u5546\u54c1\u6307\u6570(GSG)"
}

FOREX_MAP = {
    "USDCNY=X": "USD/CNY",
    "USDCNH=X": "USD/CNH",
    "DX-Y.NYB": "\u7f8e\u5143\u6307\u6570(DXY)"
}

BOND_MAP = {
    "^TNX": "\u7f8e\u56fd10Y\u56fd\u503a\u6536\u76ca\u7387"
}

def download_series(ticker: str) -> pd.DataFrame | None:
    df = yf.download(
        ticker,
        start=start_dt.strftime("%Y-%m-%d"),
        end=(end_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
        progress=False,
        auto_adjust=False,
    )
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        if "Close" in df.columns.get_level_values(0):
            df = df.xs("Close", axis=1, level=0)
        else:
            df = df.droplevel(0, axis=1)
    else:
        df = df[["Close"]]
    if isinstance(df, pd.Series):
        df = df.to_frame("Close")
    if df.shape[1] > 1:
        df = df.iloc[:, :1]
    df.columns = ["Close"]
    df = df.dropna()
    df.index = pd.to_datetime(df.index)
    df = df[df.index <= end_dt]
    if df.empty:
        return None
    return df

def pct_change(df: pd.DataFrame, days: int) -> float | None:
    if len(df) <= days:
        return None
    latest = df.iloc[-1]["Close"]
    past = df.iloc[-1 - days]["Close"]
    return (latest / past - 1) * 100

def format_pct(val: float | None, digits: int = 2) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{digits}f}%"

def format_value(val: float | None, digits: int = 2) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{digits}f}"

def build_rows(ticker_map: dict[str, str], formatter) -> list[list[str]]:
    rows: list[list[str]] = []
    for ticker, name in ticker_map.items():
        df = download_series(ticker)
        if df is None:
            rows.append([name, "N/A", "N/A", "N/A"])
            continue
        latest = df.iloc[-1]["Close"]
        rows.append(
            [
                name,
                formatter(latest),
                format_pct(pct_change(df, 5)),
                format_pct(pct_change(df, 120)),
            ]
        )
    return rows

def build_bond_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for ticker, name in BOND_MAP.items():
        df = download_series(ticker)
        if df is None:
            rows.append([name, "N/A", "N/A", "N/A"])
            continue
        latest = df.iloc[-1]["Close"]
        change5 = pct_change(df, 5)
        change120 = pct_change(df, 120)
        def to_bp(val: float | None) -> float | None:
            if val is None:
                return None
            return val * 100
        rows.append(
            [
                name,
                format_value(latest, digits=3),
                format_value(to_bp(change5), digits=1),
                format_value(to_bp(change120), digits=1),
            ]
        )
    return rows

def table_to_markdown(header_key: str, rows: list[list[str]]) -> str:
    header = HEADERS[header_key]
    md_lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for row in rows:
        md_lines.append("| " + " | ".join(row) + " |")
    return "\n".join(md_lines)

sections = {
    "indices": build_rows(INDEX_MAP, lambda v: format_value(v)),
    "commodities": build_rows(COMMODITY_MAP, lambda v: format_value(v)),
    "forex": build_rows(FOREX_MAP, lambda v: format_value(v, digits=4)),
    "bonds": build_bond_rows(),
}

lines_md: list[str] = []
lines_md.append("# 120日市场背景扫描报告（网络数据版）")
lines_md.append("")
lines_md.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
lines_md.append(f"**数据截至**: {TARGET_DATE}  ")
lines_md.append(f"**数据来源**: {DATA_SOURCE}")
lines_md.append("\n---\n")

lines_md.append("## 一、主要股指表现")
lines_md.append("")
lines_md.append(table_to_markdown("indices", sections["indices"]))
lines_md.append("")

lines_md.append("## 二、大宗商品表现")
lines_md.append("")
lines_md.append(table_to_markdown("commodities", sections["commodities"]))
lines_md.append("")

lines_md.append("## 三、主要汇率变动")
lines_md.append("")
lines_md.append(table_to_markdown("forex", sections["forex"]))
lines_md.append("")
lines_md.append("*说明: USD/CNH 的历史公开数据有限, 未能计算完整的 120 日对比。*")
lines_md.append("")

lines_md.append("## 四、国债收益率")
lines_md.append("")
lines_md.append(table_to_markdown("bonds", sections["bonds"]))
lines_md.append("")
lines_md.append("*说明: 当前仅能通过公开渠道获取美国10年期国债收益率; 中国10年期数据暂无可靠免费接口。*")
lines_md.append("")

output_path = Path("reports/20251011背景扫描cx_V2.md")
output_path.write_text("\n".join(lines_md), encoding="utf-8")
print(f"Report written to {output_path}")
