#!/usr/bin/env python3
"""Rewrite background scan tables using TuShare Pro data.

This helper avoids依赖AKShare网络，在可用的TuShare Pro环境下直接计算
主要指数与商品基准(原油/金属/BCOM)的关键指标，并将结果写入既有 Markdown 报告。用途：

- 当默认流水线因AKShare超时而回落到离线缓存时，想要生成纯TuShare
  数据口径的报告用于对比或复核。
- 需要将默认 `reports/{date}背景扫描120.md` 中的股指及ETF表格替换成
  TuShare Pro 统计结果，并输出新的 Markdown 文件。

示例：

```
export $(grep -v '^#' .env | xargs -d '\n')
python scripts/utility/tushare_pro_report_patch.py \
    --date 2025-09-28 \
    --base-report reports/20250928背景扫描120.md \
    --output reports/20250928tusharepro.md
```

"""
from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple, Callable

import numpy as np
import pandas as pd
import akshare as ak
from contextlib import contextmanager

try:
    # 优先加载真实包，如不可用则提示用户
    import tushare as ts
except Exception as exc:  # pragma: no cover - 环境问题不进入测试
    raise SystemExit(
        "无法导入 tushare，请先安装官方 TuShare 包：\n"
        "    pip install tushare"
    ) from exc

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 若未安装，继续使用环境变量
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class MetricResult:
    name: str
    latest_price: Optional[float]
    change_1d_pct: Optional[float]
    change_5d_pct: Optional[float]
    change_120d_pct: Optional[float]
    above_ma50: Optional[bool]
    above_ma200: Optional[bool]
    ma50_slope: Optional[float]
    volatility_30d_pct: Optional[float]
    trend_score: Optional[int]
    trend_label: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rewrite background scan tables with TuShare Pro data")
    parser.add_argument("--date", required=True, help="统计截止日期 (YYYY-MM-DD 或 YYYYMMDD)")
    parser.add_argument(
        "--base-report",
        help="已有报告路径，默认 reports/{date}背景扫描120.md",
    )
    parser.add_argument(
        "--output",
        help="输出 Markdown 路径，默认 reports/{date}tusharepro.md",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=500,
        help="历史抓取窗口（交易日），默认500用于支撑MA与波动率计算",
    )
    return parser.parse_args()


@contextmanager
def without_proxies():
    proxy_keys = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]
    backup = {key: os.environ.get(key) for key in proxy_keys}
    for key in proxy_keys:
        if key in os.environ:
            os.environ.pop(key)
    try:
        yield
    finally:
        for key, value in backup.items():
            if value is not None:
                os.environ[key] = value


def fetch_with_no_proxy(func, *args, **kwargs):
    with without_proxies():
        return func(*args, **kwargs)


def ensure_env_loaded() -> None:
    if load_dotenv is None:
        return
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file)


def normalize_date(date_str: str) -> Tuple[str, str]:
    try:
        if len(date_str) == 8 and date_str.isdigit():
            dt = datetime.strptime(date_str, "%Y%m%d")
        else:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit(f"无法解析日期: {date_str}") from exc
    return dt.strftime("%Y%m%d"), dt.strftime("%Y-%m-%d")


def compute_metrics(df: pd.DataFrame) -> Optional[MetricResult]:
    if df is None or df.empty:
        return None

    df = df.copy()
    date_col = "trade_date" if "trade_date" in df.columns else "date"
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).sort_values(date_col)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])

    closes = df["close"]
    latest = closes.iloc[-1]

    def pct_change(period: int) -> Optional[float]:
        if len(closes) <= period:
            return None
        return (latest / closes.iloc[-(period + 1)] - 1) * 100

    change_1d = pct_change(1)
    change_5d = pct_change(5)
    change_120d = pct_change(120)

    ma20 = closes.rolling(20).mean()
    ma50 = closes.rolling(50).mean()
    ma200 = closes.rolling(200).mean()

    def slope(series: pd.Series) -> Optional[float]:
        tail = series.dropna().tail(10)
        if len(tail) < 2:
            return None
        x = np.arange(len(tail))
        return float(np.polyfit(x, tail.values, 1)[0])

    ma50_slope = slope(ma50)

    returns = closes.pct_change().dropna()
    volatility = None
    if len(returns) >= 30:
        volatility = float(returns.tail(30).std() * np.sqrt(252) * 100)

    score = 0
    if change_120d is not None:
        if change_120d >= 5:
            score += 1
        elif change_120d <= -5:
            score -= 1

    if not pd.isna(ma50.iloc[-1]):
        score += 1 if latest > ma50.iloc[-1] else -1

    if not pd.isna(ma200.iloc[-1]):
        score += 1 if ma50.iloc[-1] > ma200.iloc[-1] else -1

    ma20_slope = slope(ma20)
    if ma20_slope is not None:
        score += 1 if ma20_slope > 0 else -1

    score = max(-2, min(2, score))
    if score >= 1:
        label = "牛"
    elif score <= -1:
        label = "熊"
    else:
        label = "中性"

    return MetricResult(
        name="",
        latest_price=float(round(latest, 2)),
        change_1d_pct=float(round(change_1d, 1)) if change_1d is not None else None,
        change_5d_pct=float(round(change_5d, 1)) if change_5d is not None else None,
        change_120d_pct=float(round(change_120d, 1)) if change_120d is not None else None,
        above_ma50=bool(latest > ma50.iloc[-1]) if not pd.isna(ma50.iloc[-1]) else None,
        above_ma200=bool(latest > ma200.iloc[-1]) if not pd.isna(ma200.iloc[-1]) else None,
        ma50_slope=float(round(ma50_slope, 4)) if ma50_slope is not None else None,
        volatility_30d_pct=float(round(volatility, 1)) if volatility is not None else None,
        trend_score=int(score),
        trend_label=label,
    )


def standardize_commodity_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize commodity dataframe to have trade_date/close columns."""
    normalized = df.copy()

    rename_map = {
        '日期': 'trade_date',
        'date': 'trade_date',
        'Date': 'trade_date',
        '时间': 'trade_date',
        '交易日期': 'trade_date',
        '收盘': 'close',
        'close': 'close',
        'Close': 'close',
        '结算价': 'close',
        '最新价': 'close',
        '价格': 'close',
        '开盘': 'open',
        'open': 'open',
        '最高': 'high',
        'high': 'high',
        '最低': 'low',
        'low': 'low'
    }

    normalized = normalized.rename(columns={k: v for k, v in rename_map.items() if k in normalized.columns})

    if 'trade_date' not in normalized.columns:
        first_col = normalized.columns[0]
        normalized = normalized.rename(columns={first_col: 'trade_date'})

    normalized['trade_date'] = pd.to_datetime(normalized['trade_date'], errors='coerce')
    normalized = normalized.dropna(subset=['trade_date']).sort_values('trade_date')

    if 'close' not in normalized.columns:
        candidate_cols = [
            col for col in normalized.columns
            if col != 'trade_date' and any(token in str(col).lower() for token in ['close', 'settle', 'price', 'last'])
        ]
        if candidate_cols:
            normalized['close'] = pd.to_numeric(normalized[candidate_cols[0]], errors='coerce')
        else:
            numeric_cols = normalized.select_dtypes(include=[float, int]).columns.tolist()
            if numeric_cols:
                normalized['close'] = pd.to_numeric(normalized[numeric_cols[0]], errors='coerce')

    normalized['close'] = pd.to_numeric(normalized['close'], errors='coerce')
    normalized = normalized.dropna(subset=['close'])

    return normalized


def fetch_commodity_dataframe(symbol: str, fetch_type: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """Fetch commodity data from AKShare and trim to window."""
    try:
        if fetch_type == 'futures_foreign':
            raw = fetch_with_no_proxy(ak.futures_foreign_hist, symbol=symbol)
        elif fetch_type == 'us_etf':
            raw = fetch_with_no_proxy(ak.stock_us_daily, symbol=symbol, adjust="")
        else:
            raise ValueError(f"未知的商品数据源类型: {fetch_type}")
    except Exception as exc:  # pragma: no cover - 外部网络依赖
        print(f"⚠️ AKShare获取{symbol}数据失败: {exc}")
        return None

    if raw is None or raw.empty:
        return None

    normalized = standardize_commodity_dataframe(raw)
    if normalized.empty:
        return None

    start_dt = datetime.strptime(start_date, "%Y%m%d") - timedelta(days=260)
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    filtered = normalized[(normalized['trade_date'] >= start_dt) & (normalized['trade_date'] <= end_dt)]

    return filtered.reset_index(drop=True)


def format_pct(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.1f}%"


def format_points(value: Optional[float]) -> str:
    return f"{value:.2f}" if value is not None else "N/A"


def format_bool(flag: Optional[bool]) -> str:
    if flag is None:
        return "N/A"
    return "是" if flag else "否"


def format_slope(value: Optional[float]) -> str:
    return f"{value:+.4f}" if value is not None else "N/A"


def format_volatility(value: Optional[float]) -> str:
    return f"{value:.1f}%" if value is not None else "N/A"


def format_score(value: Optional[int]) -> str:
    return f"{value:+d}" if value is not None else "0"


def fetch_tushare_metrics(end_date_yyyymmdd: str, window_days: int) -> Dict[str, Tuple[str, Optional[MetricResult]]]:
    pro = ts.pro_api()
    start_date = (datetime.strptime(end_date_yyyymmdd, "%Y%m%d") - timedelta(days=window_days)).strftime("%Y%m%d")

    index_codes = {
        "000001": ("上证指数", "000001.SH"),
        "000016": ("上证50", "000016.SH"),
        "399001": ("深证成指", "399001.SZ"),
        "399006": ("创业板指", "399006.SZ"),
    }

    global_codes = {
        "^GSPC": ("标普500", "SPX"),
        "^IXIC": ("纳斯达克", "IXIC"),
    }

    metrics: Dict[str, Tuple[str, Optional[MetricResult]]] = {}

    for symbol, (name, ts_code) in index_codes.items():
        df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date_yyyymmdd)
        result = compute_metrics(df)
        if result:
            result.name = name
        metrics[symbol] = (name, result)

    for symbol, (name, ts_code) in global_codes.items():
        df = pro.index_global(ts_code=ts_code, start_date=start_date, end_date=end_date_yyyymmdd)
        result = compute_metrics(df)
        if result:
            result.name = name
        metrics[symbol] = (name, result)

    commodity_targets = {
        "CL": {"name": "WTI原油(美元/桶)", "fetch": "futures_foreign"},
        "OIL": {"name": "Brent原油(美元/桶)", "fetch": "futures_foreign"},
        "HG": {"name": "COMEX铜(美元/磅)", "fetch": "futures_foreign"},
        "XAU": {"name": "现货黄金(XAUUSD)", "fetch": "futures_foreign"},
        "GSG": {"name": "BCOM商品指数(GSG代理)", "fetch": "us_etf"},
    }

    for symbol, cfg in commodity_targets.items():
        df = fetch_commodity_dataframe(symbol, cfg.get("fetch", "futures_foreign"), start_date, end_date_yyyymmdd)
        result = compute_metrics(df) if df is not None else None
        if result:
            result.name = cfg['name']
        metrics[symbol] = (cfg['name'], result)

    return metrics


def build_index_table(metrics: Dict[str, Tuple[str, Optional[MetricResult]]]) -> str:
    header = (
        "| 指数 | 收盘点数 | 当日涨幅% | 近5日% | 近120日% | >MA50? | >MA200? | MA50斜率 | 30日波动率% | 趋势评分 | 趋势标签 |\n"
        "|------|----------|-----------|--------|----------|--------|---------|----------|-------------|----------|----------|"
    )

    order = ["000001", "000016", "399001", "399006", "^GSPC", "^IXIC"]
    rows: Iterable[str] = []
    result_rows = []
    for symbol in order:
        name, result = metrics.get(symbol, (symbol, None))
        if result is None:
            row = f"| {name} | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
        else:
            row = (
                f"| {name} | {format_points(result.latest_price)} | {format_pct(result.change_1d_pct)} | "
                f"{format_pct(result.change_5d_pct)} | {format_pct(result.change_120d_pct)} | "
                f"{format_bool(result.above_ma50)} | {format_bool(result.above_ma200)} | "
                f"{format_slope(result.ma50_slope)} | {format_volatility(result.volatility_30d_pct)} | "
                f"{format_score(result.trend_score)} | {result.trend_label} |"
            )
        result_rows.append(row)
    return header + "\n" + "\n".join(result_rows)


def build_commodity_table(metrics: Dict[str, Tuple[str, Optional[MetricResult]]]) -> str:
    header = (
        "| 品种 | 收盘价 | 当日涨幅% | 近5日% | 近120日% | >MA50? | >MA200? | MA50斜率 | 30日波动率% | 趋势评分 | 趋势标签 |\n"
        "|------|--------|-----------|--------|----------|--------|---------|----------|-------------|----------|----------|"
    )

    target_names = {
        "WTI原油(美元/桶)",
        "Brent原油(美元/桶)",
        "COMEX铜(美元/磅)",
        "现货黄金(XAUUSD)",
        "BCOM商品指数(GSG代理)",
    }
    rows = []
    preferred_order = ["CL", "OIL", "HG", "XAU", "GSG"]
    for symbol in preferred_order:
        name, result = metrics.get(symbol, (symbol, None))
        if name not in target_names:
            continue
        if result is None:
            row = f"| {name} | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
        else:
            row = (
                f"| {name} | {format_points(result.latest_price)} | {format_pct(result.change_1d_pct)} | "
                f"{format_pct(result.change_5d_pct)} | {format_pct(result.change_120d_pct)} | "
                f"{format_bool(result.above_ma50)} | {format_bool(result.above_ma200)} | "
                f"{format_slope(result.ma50_slope)} | {format_volatility(result.volatility_30d_pct)} | "
                f"{format_score(result.trend_score)} | {result.trend_label} |"
            )
        rows.append(row)
    return header + "\n" + "\n".join(rows)


def parse_signed_float(raw: str, unit: str = "") -> Optional[float]:
    if raw is None:
        return None
    text = raw.strip()
    if not text or text.startswith("N/A"):
        return None
    # Remove unit markers
    for token in ["%", "亿元", "bp", unit, "(数据源故障)"]:
        text = text.replace(token, "")
    sign = -1.0 if "-" in text else 1.0
    text = text.replace("+", "").replace("-", "")
    if not text:
        return None
    try:
        return sign * float(text)
    except ValueError:
        return None


def describe_percent(value: Optional[float], horizon: str) -> str:
    if value is None:
        return f"{horizon}变动缺失"
    direction = "下跌" if value < 0 else "上涨" if value > 0 else "持平"
    return f"{horizon}{direction}{abs(value):.1f}%"


def describe_flow(value: Optional[float], horizon: str) -> str:
    if value is None:
        return f"{horizon}数据缺失"
    direction = "净流入" if value > 0 else "净流出" if value < 0 else "持平"
    return f"{horizon}{direction}{abs(value):.1f}亿元"


def analyze_forex(change_5d: Optional[float], change_120d: Optional[float]) -> str:
    short_desc = describe_percent(change_5d, "近5日")
    long_desc = describe_percent(change_120d, "120日")
    if change_5d is None or change_120d is None:
        tail = "数据待补充，暂难判断持续方向"
    elif change_5d * change_120d < 0:
        tail = "短中期方向分化，需关注趋势确认"
    elif change_5d > 0:
        tail = "多周期抬升，贬值压力有所累积"
    elif change_5d < 0:
        tail = "多周期回落，阶段性压力缓解"
    else:
        tail = "走势平稳"
    return f"{short_desc}，{long_desc}，{tail}"


def analyze_flow(flow_5d: Optional[float], flow_120d: Optional[float]) -> str:
    short_desc = describe_flow(flow_5d, "近5日")
    long_desc = describe_flow(flow_120d, "120日")
    if flow_5d is None or flow_120d is None:
        tail = "数据待补充，以免误判资金节奏"
    elif flow_5d > 0 and flow_120d > 0:
        tail = "短中期均为净流入，风险偏好提升"
    elif flow_5d < 0 and flow_120d < 0:
        tail = "持续净流出，资金偏谨慎"
    elif flow_5d > 0:
        tail = "短期回流但长期仍偏弱"
    else:
        tail = "短期承压但中期仍有支撑"
    return f"{short_desc}，{long_desc}，{tail}"


def rewrite_table_with_builder(
    content: str,
    pattern: str,
    builder: Callable[[str], str],
) -> str:
    match = re.search(pattern, content, flags=re.S)
    if not match:
        return content
    original = match.group(0)
    replacement = builder(original)
    return content[: match.start()] + replacement + content[match.end():]


def rebuild_forex_table(table_text: str) -> str:
    lines = [line for line in table_text.strip().split("\n") if line.strip()]
    if len(lines) < 3:
        return table_text

    header = lines[:2]
    rewritten = header.copy()

    for line in lines[2:]:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) < 5:
            rewritten.append(line)
            continue
        currency, change_5d_str, change_120d_str, trend, _ = cells
        change_5d = parse_signed_float(change_5d_str)
        change_120d = parse_signed_float(change_120d_str)
        remark = analyze_forex(change_5d, change_120d)
        rewritten.append(
            f"| {currency} | {change_5d_str} | {change_120d_str} | {trend} | {remark} |"
        )
    return "\n".join(rewritten)


def rebuild_capital_flow_table(table_text: str) -> str:
    lines = [line for line in table_text.strip().split("\n") if line.strip()]
    if len(lines) < 3:
        return table_text

    header = lines[:2]
    rewritten = header.copy()

    for line in lines[2:]:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) < 5:
            rewritten.append(line)
            continue
        name, flow_5d_str, flow_120d_str, trend, _ = cells
        flow_5d = parse_signed_float(flow_5d_str)
        flow_120d = parse_signed_float(flow_120d_str)
        remark = analyze_flow(flow_5d, flow_120d)
        rewritten.append(
            f"| {name} | {flow_5d_str} | {flow_120d_str} | {trend} | {remark} |"
        )
    return "\n".join(rewritten)


def rewrite_tables(base_report: Path, output_report: Path, index_table: str, commodity_table: str) -> None:
    content = base_report.read_text(encoding="utf-8")

    index_pattern = r"\| 指数 \|.*?\| 趋势标签 \|\n\|------.*?(?=\n\n)"
    content = re.sub(index_pattern, index_table, content, flags=re.S)

    commodity_pattern = r"\| 品种 \|.*?\| 趋势标签 \|\n\|------.*?(?=\n\n)"
    content = re.sub(commodity_pattern, commodity_table, content, flags=re.S)

    forex_pattern = r"\| 汇率对 \|.*?\| 备注 \|\n\|------.*?(?=\n\n)"
    content = rewrite_table_with_builder(content, forex_pattern, rebuild_forex_table)

    capital_flow_pattern = r"\| 资金类型 \|.*?\| 备注 \|\n\|----------.*?(?=\n\n)"
    content = rewrite_table_with_builder(content, capital_flow_pattern, rebuild_capital_flow_table)

    content = content.replace(
        "**数据说明**: A股数据基于AKShare数据源，美股数据通过网络可信数据源补充，计算窗口为120个自然日。",
        "**数据说明**: A股与美股数据由TuShare Pro获取，商品行情通过AKShare外盘期货/ETF接口补齐，统一计算窗口为120个自然日。"
    )

    content = content.replace(
        "**代理说明**: 使用商品相关ETF代理大宗商品走势，518880为黄金ETF，159930为能源ETF，515220为有色金属ETF。",
        "**代理说明**: 商品基准采用AKShare外盘期货(WTI/Brent/COMEX铜/现货黄金)与GSG ETF代理BCOM指数，必要时在备注中标注“ETF代理BCOM”。"
    )

    output_report.write_text(content, encoding="utf-8")


def main() -> None:
    args = parse_args()
    ensure_env_loaded()

    end_date_compact, end_date_display = normalize_date(args.date)

    base_path = Path(args.base_report) if args.base_report else PROJECT_ROOT / "reports" / f"{end_date_compact}背景扫描120.md"
    if not base_path.exists():
        raise SystemExit(f"未找到基础报告: {base_path}")

    output_path = Path(args.output) if args.output else PROJECT_ROOT / "reports" / f"{end_date_compact}tusharepro.md"

    metrics = fetch_tushare_metrics(end_date_compact, args.window_days)
    index_table = build_index_table(metrics)
    commodity_table = build_commodity_table(metrics)

    rewrite_tables(base_path, output_path, index_table, commodity_table)

    print(f"TuShare Pro 数据写入完成: {output_path}")


if __name__ == "__main__":
    main()
