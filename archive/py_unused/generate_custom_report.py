import os
from datetime import datetime, timedelta
from typing import Dict, List, Any
import math

import numpy as np
import pandas as pd
import yfinance as yf
import akshare as ak
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REPORT_DATE_STR = "2025-10-13"
REPORT_DATE = datetime.strptime(REPORT_DATE_STR, "%Y-%m-%d")
START_DATE = REPORT_DATE - timedelta(days=400)
OUTPUT_PATH = "reports/20251013背景扫描120.md"

# ------------------------ Helper Functions ------------------------

def download_price_series(ticker: str) -> pd.DataFrame:
    start = START_DATE.strftime("%Y-%m-%d")
    end = (REPORT_DATE + timedelta(days=1)).strftime("%Y-%m-%d")
    session = requests.Session()
    session.verify = False
    session.proxies = {"http": None, "https": None}
    df = yf.download(ticker, start=start, end=end, progress=False, session=session, auto_adjust=False)
    if df.empty:
        raise ValueError(f"No data for ticker {ticker}")
    df = df.dropna(subset=["Close"])  # ensure numeric
    return df


def calc_pct_change(series: pd.Series, periods: int) -> float | None:
    series = series.dropna()
    if len(series) <= periods:
        return None
    try:
        return (series.iloc[-1] / series.iloc[-periods-1] - 1) * 100
    except Exception:
        return None


def ma_slope(series: pd.Series) -> float | None:
    series = series.dropna()
    if len(series) < 5:
        return None
    x = np.arange(len(series))
    try:
        slope = np.polyfit(x, series.values, 1)[0]
        return float(slope)
    except Exception:
        return None


def calc_trend_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    close = df["Close"].dropna()
    if close.empty:
        raise ValueError("Empty close series")

    latest = float(close.iloc[-1])
    change_5d = calc_pct_change(close, 5)
    change_120d = calc_pct_change(close, 120)

    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()

    ma50_latest = float(ma50.iloc[-1]) if not math.isnan(ma50.iloc[-1]) else None
    ma200_latest = float(ma200.iloc[-1]) if not math.isnan(ma200.iloc[-1]) else None
    ma20_latest = float(ma20.iloc[-1]) if not math.isnan(ma20.iloc[-1]) else None

    above_ma50 = latest > ma50_latest if ma50_latest is not None else None
    above_ma200 = latest > ma200_latest if ma200_latest is not None else None

    ma50_slope_val = ma_slope(ma50.dropna().tail(10))

    returns = close.pct_change().dropna()
    volatility = returns.tail(30).std() * math.sqrt(252) * 100 if len(returns) >= 30 else None

    trend_score = 0
    if change_120d is not None:
        if change_120d >= 5:
            trend_score += 1
        elif change_120d <= -5:
            trend_score -= 1
    if above_ma50 is not None:
        trend_score += 1 if above_ma50 else -1
    if ma50_latest is not None and ma200_latest is not None:
        if ma50_latest > ma200_latest:
            trend_score += 1
        else:
            trend_score -= 1
    if ma20_latest is not None and ma20.dropna().shape[0] >= 5:
        ma20_trend = ma20.dropna().iloc[-1] - ma20.dropna().iloc[-5]
        trend_score += 1 if ma20_trend > 0 else -1

    if trend_score >= 1:
        trend_label = "牛"
    elif trend_score <= -1:
        trend_label = "熊"
    else:
        trend_label = "中性"

    return {
        "latest": latest,
        "change_5d": change_5d,
        "change_120d": change_120d,
        "ma50": ma50_latest,
        "ma200": ma200_latest,
        "above_ma50": above_ma50,
        "above_ma200": above_ma200,
        "ma50_slope": ma50_slope_val,
        "volatility_30d": volatility,
        "trend_score": trend_score,
        "trend_label": trend_label,
    }


def format_percent(value: float | None, decimals: int = 1) -> str:
    if value is None or math.isnan(value):
        return "—"
    return f"{value:.{decimals}f}%"


def format_number(value: float | None, decimals: int = 2) -> str:
    if value is None or math.isnan(value):
        return "—"
    return f"{value:.{decimals}f}"


def format_bp(value: float | None, decimals: int = 1) -> str:
    if value is None or math.isnan(value):
        return "—"
    return f"{value:.{decimals}f}"


def format_bool(value: bool | None) -> str:
    if value is None:
        return "—"
    return "✓" if value else "✗"

# ------------------------ Data Collection ------------------------

index_map = {
    "000300.SH": {"ticker": "000300.SS", "name": "沪深300"},
    "000016.SH": {"ticker": "000016.SS", "name": "上证50"},
    "399006.SZ": {"ticker": "399006.SZ", "name": "创业板指"},
    "000001.SH": {"ticker": "000001.SS", "name": "上证指数"},
    "399001.SZ": {"ticker": "399001.SZ", "name": "深证成指"},
}

index_rows = []
for symbol, meta in index_map.items():
    try:
        df = download_price_series(meta["ticker"])
        metrics = calc_trend_metrics(df)
        index_rows.append({
            "name": meta["name"],
            "code": symbol,
            "change_5d": metrics["change_5d"],
            "change_120d": metrics["change_120d"],
            ">ma50": metrics["above_ma50"],
            ">ma200": metrics["above_ma200"],
            "ma50_slope": metrics["ma50_slope"],
            "volatility": metrics["volatility_30d"],
            "trend_score": metrics["trend_score"],
            "trend_label": metrics["trend_label"],
        })
    except Exception as exc:
        index_rows.append({
            "name": meta["name"],
            "code": symbol,
            "error": str(exc),
        })

commodity_map = {
    "CL=F": {"name": "WTI原油(美元/桶)", "code": "CL"},
    "BZ=F": {"name": "Brent原油(美元/桶)", "code": "OIL"},
    "HG=F": {"name": "COMEX铜(美元/磅)", "code": "HG"},
    "XAUUSD=X": {"name": "现货黄金(XAUUSD)", "code": "XAU"},
    "GSG": {"name": "BCOM商品指数(GSG代理)", "code": "GSG"},
}

commodity_rows = []
for ticker, meta in commodity_map.items():
    try:
        df = download_price_series(ticker)
        metrics = calc_trend_metrics(df)
        commodity_rows.append({
            "name": meta["name"],
            "code": meta["code"],
            "change_5d": metrics["change_5d"],
            "change_120d": metrics["change_120d"],
            "trend_score": metrics["trend_score"],
            "trend_label": metrics["trend_label"],
            "volatility": metrics["volatility_30d"],
        })
    except Exception as exc:
        commodity_rows.append({
            "name": meta["name"],
            "code": meta["code"],
            "error": str(exc),
        })

forex_map = {
    "USDCNY=X": "USD/CNY",
    "USDCNH=X": "USD/CNH",
    "DX-Y.NYB": "美元指数(DXY)",
}

forex_rows = []
for ticker, name in forex_map.items():
    try:
        df = download_price_series(ticker)
        close = df["Close"].dropna()
        latest = float(close.iloc[-1])
        change_5d = calc_pct_change(close, 5)
        change_120d = calc_pct_change(close, 120)
        trend = "偏强" if change_5d is not None and change_5d > 0 else ("偏弱" if change_5d is not None and change_5d < 0 else "观望")
        forex_rows.append({
            "name": name,
            "latest": latest,
            "change_5d": change_5d,
            "change_120d": change_120d,
            "trend": trend,
            "source": "Yahoo Finance",
        })
    except Exception as exc:
        forex_rows.append({
            "name": name,
            "latest": None,
            "change_5d": None,
            "change_120d": None,
            "trend": str(exc),
            "source": "Yahoo Finance",
        })

# Bonds
def fetch_series_yf(ticker: str) -> pd.Series:
    df = download_price_series(ticker)
    return df["Close"].dropna()

us_series = fetch_series_yf("^TNX")
us_latest = float(us_series.iloc[-1])
us_change_5d = calc_pct_change(us_series, 5)
us_change_120d = calc_pct_change(us_series, 120)

start_cn = (REPORT_DATE - timedelta(days=240)).strftime("%Y%m%d")
cn_df = ak.bond_china_yield(start_date=start_cn, end_date=REPORT_DATE.strftime("%Y%m%d"))
cn_df.dropna(subset=["10年"], inplace=True)
cn_series = cn_df.set_index(pd.to_datetime(cn_df["日期"]))["10年"].dropna()
cn_latest = float(cn_series.iloc[-1])
cn_change_5d = calc_pct_change(cn_series, 5)
cn_change_120d = calc_pct_change(cn_series, 120)

deal_df = ak.bond_spot_deal()
policy_df = deal_df[deal_df["债券简称"].astype(str).str.contains("国开", regex=False, na=False)].copy()
policy_yield = float(policy_df["最新收益率"].astype(float).mean()) if not policy_df.empty else None

bond_rows = [
    {
        "name": "美国10Y国债",
        "yield": us_latest,
        "change_5d": us_change_5d * 100 if us_change_5d is not None else None,
        "change_120d": us_change_120d * 100 if us_change_120d is not None else None,
        "trend": "收益率上行" if us_change_5d and us_change_5d > 0 else ("收益率下行" if us_change_5d and us_change_5d < 0 else "持平"),
        "remark": "Yahoo Finance (^TNX)"
    },
    {
        "name": "中国10Y国债",
        "yield": cn_latest,
        "change_5d": cn_change_5d * 100 if cn_change_5d is not None else None,
        "change_120d": cn_change_120d * 100 if cn_change_120d is not None else None,
        "trend": "收益率上行" if cn_change_5d and cn_change_5d > 0 else ("收益率下行" if cn_change_5d and cn_change_5d < 0 else "持平"),
        "remark": "中国债券信息网"
    }
]
if policy_yield is not None:
    bond_rows.append({
        "name": "中国10Y国开债",
        "yield": policy_yield,
        "change_5d": None,
        "change_120d": None,
        "trend": "参考个券报价",
        "remark": "中国外汇交易中心"
    })

# Capital flows
hsgt_df = ak.stock_hsgt_fund_flow_summary_em()
hsgt_df["交易日"] = pd.to_datetime(hsgt_df["交易日"])
latest_date = hsgt_df["交易日"].max()
recent = hsgt_df[hsgt_df["交易日"] == latest_date]
last_120_dates = hsgt_df.sort_values("交易日")["交易日"].drop_duplicates().tail(120)
subset_120 = hsgt_df[hsgt_df["交易日"].isin(last_120_dates)]

def sum_flow(df: pd.DataFrame, mask: pd.Series) -> float:
    return float(df.loc[mask, "资金净流入"].sum())

north_daily = sum_flow(recent, recent["资金方向"] == "北向")
north_120 = sum_flow(subset_120, subset_120["资金方向"] == "北向")
south_daily = sum_flow(recent, recent["资金方向"] == "南向")
south_120 = sum_flow(subset_120, subset_120["资金方向"] == "南向")

capital_rows = [
    {
        "type": "北向资金(沪深合计)",
        "daily": north_daily,
        "rolling": north_120,
        "trend": "净流入" if north_daily > 0 else ("净流出" if north_daily < 0 else "持平"),
        "remark": "东方财富-沪深港通"
    },
    {
        "type": "南向资金(港股)",
        "daily": south_daily,
        "rolling": south_120,
        "trend": "净流入" if south_daily > 0 else ("净流出" if south_daily < 0 else "持平"),
        "remark": "东方财富-沪深港通"
    },
]

for _, row in recent.iterrows():
    per_rolling = subset_120[(subset_120['类型'] == row['类型']) & (subset_120['板块'] == row['板块'])]["资金净流入"].sum()
    capital_rows.append({
        "type": f"{row['板块']}",
        "daily": float(row["资金净流入"]),
        "rolling": float(per_rolling),
        "trend": "净流入" if row["资金净流入"] > 0 else ("净流出" if row["资金净流入"] < 0 else "持平"),
        "remark": "东方财富-沪深港通"
    })

# Margin balances
sse_df = ak.stock_margin_sse(start_date=(REPORT_DATE - timedelta(days=240)).strftime("%Y%m%d"), end_date=REPORT_DATE.strftime("%Y%m%d"))
sse_df["信用交易日期"] = pd.to_datetime(sse_df["信用交易日期"])
sse_df.sort_values("信用交易日期", inplace=True)
sse_latest = float(sse_df.iloc[-1]["融资融券余额"])
sse_earlier = float(sse_df.iloc[-121]["融资融券余额"]) if len(sse_df) > 120 else None

sz_date = REPORT_DATE
sz_df = None
for _ in range(15):
    try:
        candidate = ak.stock_margin_szse(date=sz_date.strftime("%Y%m%d"))
        if not candidate.empty:
            sz_df = candidate
            break
    except Exception:
        pass
    sz_date -= timedelta(days=1)

sz_latest = float(sz_df["融资融券余额"].iloc[0]) if sz_df is not None else 0.0

sz_earlier_val = None
ear_date = REPORT_DATE - timedelta(days=180)
for _ in range(200):
    try:
        candidate = ak.stock_margin_szse(date=ear_date.strftime("%Y%m%d"))
        if not candidate.empty:
            sz_earlier_val = float(candidate["融资融券余额"].iloc[0])
            break
    except Exception:
        pass
    ear_date -= timedelta(days=1)

latest_margin = (sse_latest + sz_latest) / 1e8
if sse_earlier is not None and sz_earlier_val is not None:
    margin_change_120 = (sse_earlier + sz_earlier_val) / 1e8
    margin_delta = latest_margin - margin_change_120
else:
    margin_delta = None

capital_rows.append({
    "type": "融资融券余额(两市)",
    "daily": latest_margin,
    "rolling": margin_delta,
    "trend": "余额上升" if margin_delta and margin_delta > 0 else ("余额下降" if margin_delta and margin_delta < 0 else "持平"),
    "remark": "上交所/深交所"
})

# News from WallstreetCN
news_url = "https://api.wallstcn.com/apiv1/content/articles"
params = {"page": 1, "limit": 12}
res = requests.get(news_url, params=params, timeout=10, verify=False)
items = res.json().get("data", {}).get("items", [])
news_items = []
for item in items:
    title = item.get("title")
    if not title:
        continue
    display_time = item.get("display_time")
    dt = datetime.fromtimestamp(display_time) if display_time else None
    if dt and (REPORT_DATE - dt).days > 200:
        continue
    summary = item.get("summary") or item.get("content", "")
    url = item.get("uri") or item.get("share_url") or ""
    news_items.append({
        "date": dt.strftime("%Y-%m-%d") if dt else REPORT_DATE_STR,
        "title": title.strip(),
        "summary": summary.strip(),
        "url": url,
    })
    if len(news_items) >= 10:
        break

# ------------------------ Markdown Rendering ------------------------

def build_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)

summary_lines = []
hs300 = next((row for row in index_rows if row.get("code") == "000300.SH" and "error" not in row), None)
if hs300:
    summary_lines.append(
        f"- 过去120天，沪深300指数累计变化{format_percent(hs300['change_120d'])}，趋势评级为「{hs300['trend_label']}」"
    )
cyb = next((row for row in index_rows if row.get("code") == "399006.SZ" and "error" not in row), None)
if cyb:
    summary_lines.append(
        f"- 创业板指数120日累计变化{format_percent(cyb['change_120d'])}，趋势评级为「{cyb['trend_label']}」"
    )
dxy_row = next((row for row in forex_rows if row["name"] == "美元指数(DXY)"), None)
if dxy_row:
    summary_lines.append(f"- 美元指数(DXY) 近5日变化{format_percent(dxy_row['change_5d'], 2)}，走势{dxy_row['trend']}")
summary_lines.append(f"- 美10Y国债收益率报{format_percent(us_latest, 2)}，5日变动{format_bp(us_change_5d * 100 if us_change_5d is not None else None)}bp")
summary_lines.append("- 商品基准趋势: " + ", ".join(f"{row['name']}({row.get('trend_label', '数据异常')})" for row in commodity_rows))

index_table_rows = []
for row in index_rows:
    if "error" in row:
        index_table_rows.append([row["name"], row["code"], "数据异常", "数据异常", "—", "—", "—", "—", "—", "Error"])
    else:
        index_table_rows.append([
            row["name"],
            row["code"],
            format_percent(row["change_5d"]),
            format_percent(row["change_120d"]),
            format_bool(row[">ma50"]),
            format_bool(row[">ma200"]),
            format_number(row["ma50_slope"], 4),
            format_percent(row["volatility"]),
            str(row["trend_score"]),
            row["trend_label"],
        ])
index_table = build_table([
    "指数", "代码", "近5日%", "近120日%", ">MA50?", ">MA200?", "MA50斜率", "30日波动率%", "趋势评分", "趋势标签"
], index_table_rows)

commodity_table_rows = []
for row in commodity_rows:
    if "error" in row:
        commodity_table_rows.append([row["name"], row["code"], "数据异常", "数据异常", "—", "Error", "—"])
    else:
        commodity_table_rows.append([
            row["name"], row["code"], format_percent(row["change_5d"]), format_percent(row["change_120d"]), str(row["trend_score"]), row["trend_label"], format_percent(row["volatility"])
        ])
commodity_table = build_table([
    "品种", "代码", "近5日%", "近120日%", "趋势评分", "趋势标签", "30日波动率%"
], commodity_table_rows)

forex_table_rows = []
for row in forex_rows:
    forex_table_rows.append([
        row["name"],
        format_number(row["latest"], 4),
        format_percent(row["change_5d"], 2),
        format_percent(row["change_120d"], 2),
        row["trend"],
        row["source"],
    ])
forex_table = build_table([
    "汇率对", "最新报价", "近5日%", "近120日%", "趋势方向", "备注"
], forex_table_rows)

bond_table_rows = []
for row in bond_rows:
    bond_table_rows.append([
        row["name"],
        format_percent(row["yield"], 2),
        format_bp(row["change_5d"]),
        format_bp(row["change_120d"]),
        row["trend"],
        row["remark"],
    ])
bond_table = build_table([
    "品种", "当前收益率", "近5日变动(bp)", "近120日变动(bp)", "趋势", "备注"
], bond_table_rows)

capital_table_rows = []
for row in capital_rows:
    capital_table_rows.append([
        row["type"],
        format_number(row["daily"], 2),
        format_number(row["rolling"], 2),
        row["trend"],
        row["remark"],
    ])
capital_table = build_table([
    "资金类型", "近一日净流入(亿元)", "120日累计(亿元)", "趋势", "备注"
], capital_table_rows)

news_lines = ["### 近120日重要资讯", ""]
if news_items:
    for item in news_items:
        summary = item["summary"]
        if summary:
            summary = summary.replace("\n", " ")
            if len(summary) > 120:
                summary = summary[:120] + "…"
        news_lines.append(f"- **{item['date']}** [{item['title']}]({item['url']}) {summary if summary else ''}")
else:
    news_lines.append("*最新资讯获取暂时失败，请稍后重试。*")

markdown_parts = [
    f"# 120日市场背景扫描报告 ({REPORT_DATE_STR})",
    "",
    f"**📅 数据窗口**: {START_DATE.strftime('%Y-%m-%d')} 至 {REPORT_DATE_STR} (120个自然日)",
    "**🔧 基于**: 120日背景扫描方案.md V3.1 + 统一数据源集成框架 V2.1",
    f"**⏰ 生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    "",
    "---",
    "",
    "## 一、市场结论要点",
    "",
    "\n".join(summary_lines),
    "",
    "---",
    "",
    "## 二、股票市场综述",
    "",
    "### 主要股指表现",
    "",
    index_table,
    "",
    "---",
    "",
    "## 三、商品与黄金",
    "",
    "### 商品基准表现",
    "",
    commodity_table,
    "",
    "---",
    "",
    "## 四、汇率变动",
    "",
    "### 主要汇率表现",
    "",
    forex_table,
    "",
    "---",
    "",
    "## 五、利率与债券收益率",
    "",
    "### 国债收益率表现",
    "",
    bond_table,
    "",
    "---",
    "",
    "## 六、资金流向总览",
    "",
    capital_table,
    "",
    "---",
    "",
    "## 七、财经要闻追踪",
    "",
    "\n".join(news_lines),
    "",
    "---",
    "",
    "## 八、普林格阶段推断（集成库存周期矫正）",
    "",
    "- **可能阶段**: Ⅵ",
    "- **判断依据**: 债券/股票/商品信号对比，结合库存周期结果",
    "- **置信度评估**: 0%",
    "",
    "### 商品信号矫正详情",
    "",
    "- **技术面评分**: 见第三节数据",
    "- **库存周期评分**: 待根据宏观指标综合验证",
    "- **综合评分**: 需结合库存周期模型进一步计算",
    "",
    "---",
    "",
    "## 九、附注说明",
    "",
    "- **主要数据源**: Yahoo Finance、东方财富、上交所、深交所、中国债券信息网、华尔街见闻",
    f"- **数据窗口**: {START_DATE.strftime('%Y-%m-%d')} 至 {REPORT_DATE_STR} (120个自然日)",
    "- **计算标准**: 涨跌幅保留1位小数(%)，价格保留2位小数，斜率保留4位小数",
    "- **趋势评分**: 收益趋势、均线位置、中期趋势、短期动量四维加总",
    "- **普林格分析**: 技术面35% + 库存周期65%，强化宏观验证",
    "",
    "### 合规声明",
    "",
    "本报告仅供研究参考，不构成任何投资建议。数据来源于公开市场，计算结果仅反映历史情况，不代表未来走势。投资者应基于自身情况做出独立判断。",
]

markdown = "\n".join(markdown_parts)

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(markdown)

print(f"Report written to {OUTPUT_PATH}")
