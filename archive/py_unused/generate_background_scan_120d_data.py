#!/usr/bin/env python3
"""
生成 120日背景扫描 数据面板（JSON）

- 指标覆盖：近5日%、近120日%、MA50、MA200、斜率、波动(年化%)、评分、信号
- 数据源：优先 `manager.get_index_daily`；透传 source 与 timestamp
"""

import os
import sys
import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# 将 src 加入路径
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from datasource import get_manager
from datasource.calculators.technical_indicators import TechnicalIndicatorCalculator


DEFAULT_SYMBOLS = [
    "000001",  # 上证指数
    "000300",  # 沪深300
    "000905",  # 中证500
    "399001",  # 深证成指
    "399006",  # 创业板指
]


def _standardize_price_df(df: pd.DataFrame) -> pd.DataFrame:
    """尽力标准化价格DataFrame到包含 close 列、按日期排序"""
    if df is None or df.empty:
        return pd.DataFrame()

    column_mapping = {
        "收盘": "close",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "close": "close",
        "open": "open",
        "high": "high",
        "low": "low",
        "volume": "volume",
    }

    for old, new in column_mapping.items():
        if old in df.columns:
            df = df.rename(columns={old: new})

    if "close" not in df.columns:
        # 兜底：尝试猜测价格列
        price_cols = [
            c
            for c in df.columns
            if any(k in c.lower() for k in ["close", "price", "收盘", "价格"])
        ]
        if price_cols:
            df["close"] = df[price_cols[0]]
        else:
            return pd.DataFrame()

    # 排序
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])  # type: ignore
        df = df.sort_values("date")
    elif df.index.name == "date" or "date" in str(df.index.dtype):
        df = df.sort_index()

    return df


async def _fetch_index_df(manager, symbol: str, days: int = 420) -> Dict[str, Any]:
    """获取指数日线数据，默认抓取更长缓冲天数以确保120d指标可计算"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    resp = await manager.get_index_daily(symbol, start_date, end_date)
    result: Dict[str, Any] = {
        "symbol": symbol,
        "data_source": resp.source,
        "last_update": resp.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if resp.error or resp.data is None or resp.data.empty:
        result.update(
            {
                "error": resp.error or "数据为空",
                "na_reason": "数据源不可用或无历史数据",
                "df": None,
            }
        )
        return result

    df = _standardize_price_df(resp.data)
    if df.empty:
        result.update({"error": "无法标准化价格数据", "na_reason": "无法识别收盘价列", "df": None})
    else:
        result["df"] = df
    return result


def _compute_metrics(df: pd.DataFrame, tech: TechnicalIndicatorCalculator) -> Dict[str, Any]:
    """根据收盘价计算所需指标"""
    close = df["close"].astype(float)

    # MA
    ma50_series = tech.calculate_ma(close, 50)
    ma200_series = tech.calculate_ma(close, 200)
    ma50 = float(ma50_series.iloc[-1]) if len(ma50_series) else None
    ma200 = float(ma200_series.iloc[-1]) if len(ma200_series) else None

    # 斜率
    slope_ma50_10 = (
        float(tech.calculate_ma_slope(ma50_series, periods=10)) if len(ma50_series) >= 10 else None
    )
    slope_ma200_20 = (
        float(tech.calculate_ma_slope(ma200_series, periods=20)) if len(ma200_series) >= 20 else None
    )

    # 波动（30日年化）
    volatility_30d_annualized_pct = float(tech.calculate_volatility(close, window=30))

    # 涨跌幅
    change_5d_pct = (
        float(tech.calculate_price_change(close, 5)) if len(close) >= 6 else None
    )
    change_120d_pct = (
        float(tech.calculate_price_change(close, 120)) if len(close) >= 121 else None
    )

    # 评分/信号（复用现有逻辑，含 MA20/5/10 等）
    try:
        trend = tech.calculate_trend_score(pd.DataFrame({"close": close}))
        trend_score = int(trend.get("trend_score", 50))
        trend_label = str(trend.get("trend_label", "中性"))
    except Exception:
        trend_score, trend_label = 50, "中性"

    return {
        "last_close": float(close.iloc[-1]),
        "change_5d_pct": change_5d_pct,
        "change_120d_pct": change_120d_pct,
        "ma50": ma50,
        "ma200": ma200,
        "slope_ma50_10": slope_ma50_10,
        "slope_ma200_20": slope_ma200_20,
        "volatility_30d_annualized_pct": volatility_30d_annualized_pct,
        "trend_score": trend_score,
        "trend_label": trend_label,
    }


async def build_120d_panel(symbols: List[str], analysis_date: Optional[str] = None) -> Dict[str, Any]:
    manager = get_manager()
    tech = TechnicalIndicatorCalculator()

    tasks = [_fetch_index_df(manager, s, days=420) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    panel_rows: List[Dict[str, Any]] = []
    sources: List[str] = []
    na_reasons: List[str] = []

    for item in results:
        if isinstance(item, Exception):
            na_reasons.append(str(item))
            continue

        symbol = item.get("symbol")
        source = item.get("data_source")
        sources.append(source)

        if item.get("df") is None:
            panel_rows.append(
                {
                    "symbol": symbol,
                    "metrics": None,
                    "data_source": source,
                    "last_update": item.get("last_update"),
                    "na_reason": item.get("na_reason", item.get("error", "未知原因")),
                }
            )
            if item.get("na_reason"):
                na_reasons.append(item["na_reason"])  # type: ignore
            continue

        df = item["df"]
        metrics = _compute_metrics(df, tech)
        panel_rows.append(
            {
                "symbol": symbol,
                "metrics": metrics,
                "data_source": source,
                "last_update": item.get("last_update"),
            }
        )

    analysis_date = analysis_date or datetime.now().strftime("%Y-%m-%d")
    panel: Dict[str, Any] = {
        "analysis_date": analysis_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbols": symbols,
        "panel": panel_rows,
        "footnotes": {
            "sources": sorted(list({s for s in sources if s})),
            "units": {
                "change_*_pct": "%",
                "volatility_30d_annualized_pct": "%",
                "ma": "price",
                "slope": "price/period",
            },
            "methodology": [
                "近5日/近120日涨跌幅基于收盘价计算",
                "波动为近30日滚动年化，252日年化天数",
                "MA 与斜率以价格为单位，斜率为线性回归拟合斜率",
            ],
            "proxy_notes": [
                "如官方利率曲线缺失，用债券/利率相关ETF价格反推bp",
                "海外指数或资金流缺失时以ETF价量/份额近似，并注明估算",
            ],
            "na_summary": sorted(list({r for r in na_reasons if r})),
        },
    }

    return panel


def _dump_json(obj: Any, path: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _parse_args(argv: Optional[List[str]] = None):
    import argparse

    parser = argparse.ArgumentParser(description="生成120日背景扫描数据面板(JSON)")
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="指数代码，默认覆盖A股主要指数",
        default=DEFAULT_SYMBOLS,
    )
    parser.add_argument(
        "--date", help="分析日期(YYYY-MM-DD)，仅标注用途", default=None
    )
    parser.add_argument(
        "--output",
        help="输出JSON路径，默认 reports/YYYYMMDD_120d_panel.json",
        default=None,
    )
    return parser.parse_args(argv)


async def _amain():
    args = _parse_args()
    panel = await build_120d_panel(args.symbols, args.date)
    if args.output:
        output = args.output
    else:
        output = os.path.join(
            PROJECT_ROOT,
            "reports",
            f"{datetime.now().strftime('%Y%m%d')}_120d_panel.json",
        )
    _dump_json(panel, output)
    print(f"✅ 已生成 120日数据面板: {output}")
    # 便于提示词模板直接嵌入
    print("\n—— 以下为 PANEL_JSON 片段（截断显示）——")
    snippet = json.dumps(panel["panel"][:2], ensure_ascii=False, indent=2)
    print(snippet[:1200])


def main():
    asyncio.run(_amain())


if __name__ == "__main__":
    main()

