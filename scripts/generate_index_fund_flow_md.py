"""Generate 2025 monthly fund flow report for major CSI indices using AKShare and TuShare."""
from __future__ import annotations

import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import inspect

import pandas as pd
import matplotlib

matplotlib.use("Agg")  # ensure headless rendering
import matplotlib.pyplot as plt


try:
    import akshare as ak  # type: ignore
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise ImportError(
        "akshare is required. Install with `pip install akshare`."
    ) from exc

try:
    import tushare as ts  # type: ignore
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise ImportError(
        "tushare is required. Install with `pip install tushare`."
    ) from exc

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = lambda *_, **__: None  # type: ignore


YEAR = 2025
START_DATE = f"{YEAR}0101"
END_DATE = f"{YEAR}1231"
OUTPUT_DIR = Path("reports")
OUTPUT_IMAGE = OUTPUT_DIR / "index_fund_flow_2025.png"
OUTPUT_MD = OUTPUT_DIR / "index_fund_flow_2025.md"

INDEX_CONFIG = {
    "沪深300": {
        "akshare_symbol": "沪深300",
        "tushare_code": "000300.SH",
    },
    "中证500": {
        "akshare_symbol": "中证500",
        "tushare_code": "000905.SH",
    },
    "中证1000": {
        "akshare_symbol": "中证1000",
        "tushare_code": "000852.SH",
    },
}

AKSHARE_METHODS: Tuple[Tuple[str, Dict[str, object]], ...] = (
    ("stock_market_fund_flow_hist", {"market": "沪深京"}),
    ("stock_index_fund_flow", {}),
    ("stock_zh_index_fund_flow", {}),
)

DATE_COLUMNS = ("trade_date", "日期", "date", "日期时间", "时间")
NET_COLUMNS_PRIORITIZED = (
    "主力净流入",
    "净流入",
    "资金净流入",
    "净额",
    "net_amount",
    "net_mf_amount",
    "net_buy",
    "money_net",
)


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("fund_flow")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def select_column(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    normalized = {col.lower(): col for col in columns}
    for candidate in candidates:
        if candidate in columns:
            return candidate
        lowered = candidate.lower()
        if lowered in normalized:
            return normalized[lowered]
    return None


def normalize_daily_series(df: pd.DataFrame, year: int, *, source: str) -> pd.Series:
    if df is None or df.empty:
        raise ValueError(f"{source} 返回空数据")

    date_col = select_column(df.columns, DATE_COLUMNS)
    if not date_col:
        raise ValueError(f"{source} 数据缺少日期列: {df.columns.tolist()}")

    net_col = select_column(df.columns, NET_COLUMNS_PRIORITIZED)
    if not net_col:
        raise ValueError(f"{source} 数据缺少资金流向列: {df.columns.tolist()}")

    frame = df.copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col])
    frame = frame[(frame[date_col].dt.year == year)]
    if frame.empty:
        raise ValueError(f"{source} 未获取到 {year} 年的数据")

    values = pd.to_numeric(frame[net_col], errors="coerce")
    series = pd.Series(values.values, index=frame[date_col])
    series = series.dropna()

    if series.empty:
        raise ValueError(f"{source} 资金流向列全部为空")

    # 标准化单位为亿元（若原始值以元或万元为单位则自动转换）
    median_abs = series.abs().median()
    if median_abs > 1e8 * 10:  # values likely in元
        series = series / 1e8
    elif median_abs > 1e4 * 10:  # values likely in万元
        series = series / 1e4 / 1e4

    series.name = net_col
    return series


def aggregate_monthly(series: pd.Series) -> pd.Series:
    monthly = series.groupby(series.index.to_period("M")).sum().sort_index()
    monthly.index = monthly.index.astype(str)
    monthly.name = "net_inflow"
    return monthly


def fetch_akshare_monthly(index_name: str, logger: logging.Logger) -> pd.Series:
    last_error: Optional[Exception] = None
    for method_name, extra_params in AKSHARE_METHODS:
        func = getattr(ak, method_name, None)
        if func is None:
            continue
        params = dict(extra_params)
        try:
            signature = inspect.signature(func)  # type: ignore[arg-type]
        except (TypeError, ValueError):  # pragma: no cover - C extensions
            signature = None
        if signature:
            parameters = signature.parameters
            if "symbol" in parameters:
                params.setdefault("symbol", index_name)
            elif "index" in parameters:
                params.setdefault("index", index_name)
            elif "code" in parameters:
                params.setdefault("code", index_name)
        else:
            params.setdefault("symbol", index_name)
        try:
            logger.info("AKShare %s 拉取 %s", method_name, index_name)
            df = func(**params)  # type: ignore[call-arg]
            series = normalize_daily_series(df, YEAR, source=f"AKShare::{method_name}")
            monthly = aggregate_monthly(series)
            return monthly.rename("akshare_net")
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc
            logger.warning("AKShare %s 失败: %s", method_name, exc)
            continue
    raise RuntimeError(f"AKShare 无法获取 {index_name} 数据: {last_error}")


def init_tushare(logger: logging.Logger):
    load_dotenv()
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("未配置 TUSHARE_TOKEN。请在 .env 中设置或导出环境变量。")
    try:
        ts.set_token(token)
        return ts.pro_api(token)
    except Exception as exc:  # pragma: no cover - network dependent
        logger.error("初始化 TuShare 失败: %s", exc)
        raise


def fetch_tushare_monthly(ts_code: str, pro, logger: logging.Logger) -> pd.Series:
    try:
        df = pro.index_moneyflow(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE)
    except Exception as exc:  # pragma: no cover - network dependent
        logger.error("TuShare index_moneyflow 失败: %s", exc)
        raise
    series = normalize_daily_series(df, YEAR, source="TuShare::index_moneyflow")
    monthly = aggregate_monthly(series)
    return monthly.rename("tushare_net")


def build_combined_table(data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    for index_name, df in data.items():
        table = df.copy()
        table = table.reset_index().rename(columns={"index": "month"})
        table.insert(1, "index", index_name)
        rows.append(table)
    combined = pd.concat(rows, ignore_index=True)
    combined = combined.sort_values(["index", "month"])
    return combined


def render_plot(pivoted: pd.DataFrame, output_path: Path) -> None:
    ax = pivoted.plot(kind="barh", figsize=(12, 7))
    ax.set_xlabel("资金净流入 (亿元)")
    ax.set_ylabel("月份")
    ax.set_title("2025年主要指数月度资金流向 (AKShare & TuShare 均值)")
    ax.grid(True, axis="x", linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def write_markdown(
    combined_table: pd.DataFrame,
    pivot_table: pd.DataFrame,
    errors: Dict[str, str],
    output_md: Path,
    image_path: Path,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with output_md.open("w", encoding="utf-8") as fh:
        fh.write("# 2025年指数资金流向横道图\n\n")
        fh.write("数据源：AKShare 指数资金流接口 + TuShare `index_moneyflow`，按月累计净流入，统一换算为亿元。\n\n")
        if image_path.exists():
            fh.write(f"![2025年指数资金流向横道图]({image_path.name})\n\n")
        fh.write("## 月度资金净流入明细 (亿元)\n\n")
        fh.write(combined_table.round(2).to_markdown(index=False))
        fh.write("\n\n")
        fh.write("## 横道图数据透视表 (亿元)\n\n")
        fh.write(pivot_table.round(2).to_markdown())
        fh.write("\n\n")
        if errors:
            fh.write("## 异常说明\n\n")
            for key, message in errors.items():
                fh.write(f"- {key}: {message}\n")
            fh.write("\n")
        fh.write("## 生成信息\n\n")
        fh.write(f"- 生成时间：{now}\n")
        fh.write("- 生成脚本：`python scripts/generate_index_fund_flow_md.py`\n")
        fh.write("- 输出图表：`reports/" + image_path.name + "`\n")


def main() -> None:  # pragma: no cover - script entry point
    logger = setup_logger()

    ensure_output_dir(OUTPUT_DIR)

    pro = init_tushare(logger)

    combined_data: Dict[str, pd.DataFrame] = {}
    errors: Dict[str, str] = {}

    for index_name, meta in INDEX_CONFIG.items():
        logger.info("处理 %s", index_name)
        ak_monthly: Optional[pd.Series] = None
        ts_monthly: Optional[pd.Series] = None
        try:
            ak_monthly = fetch_akshare_monthly(meta["akshare_symbol"], logger)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.error("AKShare 获取 %s 失败: %s", index_name, exc)
            errors[f"AKShare:{index_name}"] = str(exc)
        try:
            ts_monthly = fetch_tushare_monthly(meta["tushare_code"], pro, logger)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.error("TuShare 获取 %s 失败: %s", index_name, exc)
            errors[f"TuShare:{index_name}"] = str(exc)

        if ak_monthly is None and ts_monthly is None:
            logger.warning("%s 无法获取任何数据", index_name)
            continue

        df = pd.concat(filter(None, [ak_monthly, ts_monthly]), axis=1)
        if "akshare_net" in df and "tushare_net" in df:
            df["avg_net"] = df[["akshare_net", "tushare_net"]].mean(axis=1)
        else:
            df["avg_net"] = df.max(axis=1)
        combined_data[index_name] = df

    if not combined_data:
        raise SystemExit("未能获取任何指数的资金流数据。")

    combined_table = build_combined_table(combined_data)

    pivot_table = (
        combined_table
        .pivot_table(index="month", columns="index", values="avg_net", aggfunc="first")
        .reindex(sorted(combined_table["month"].unique()))
    )

    render_plot(pivot_table, OUTPUT_IMAGE)
    write_markdown(combined_table, pivot_table, errors, OUTPUT_MD, OUTPUT_IMAGE)
    logger.info("生成完成: %s", OUTPUT_MD)


if __name__ == "__main__":
    main()
