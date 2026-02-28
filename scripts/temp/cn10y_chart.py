#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性脚本：通过 TuShare 拉取中国10年期国债近3个月日收益率数据，生成折线图。

用法:
    bash run_clean.sh python scripts/cn10y_chart.py
    # 或
    source .venv/bin/activate && source .env && python scripts/cn10y_chart.py

输出: reports/cn10y_3m_chart.png
"""

import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 加载 .env（若存在）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

try:
    import tushare as ts
except ImportError:
    print("错误: 未安装 tushare，请执行 pip install tushare")
    sys.exit(1)

# ── 中文字体配置（WSL/Linux：直接加载 Windows SimHei） ──────────────────────
import matplotlib.font_manager as fm

_WIN_FONTS = [
    "/mnt/c/Windows/Fonts/simhei.ttf",
    "/mnt/c/Windows/Fonts/msyh.ttc",
    "/mnt/c/Windows/Fonts/simsun.ttc",
]
_cn_font = None
for _path in _WIN_FONTS:
    if os.path.exists(_path):
        fm.fontManager.addfont(_path)
        _cn_font = fm.FontProperties(fname=_path).get_name()
        break

if _cn_font:
    plt.rcParams["font.sans-serif"] = [_cn_font, "DejaVu Sans"]
else:
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def fetch_cn10y(start_date: str, end_date: str) -> pd.DataFrame:
    """
    通过 TuShare yc_cb 接口获取中国10年期国债收益率日数据。

    优先使用 curve_type="0"（官方国债曲线），若返回空则回退 curve_type="1"。

    Args:
        start_date: "YYYYMMDD" 格式开始日期
        end_date:   "YYYYMMDD" 格式结束日期

    Returns:
        DataFrame，列: date (datetime), yield_pct (float, %)
    """
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN 环境变量")
        sys.exit(1)

    pro = ts.pro_api(token)

    print(f"正在拉取 CN10Y 数据: {start_date} → {end_date} ...")
    raw_df = pro.yc_cb(
        start_date=start_date,
        end_date=end_date,
        ts_code="1001.CB",
        curve_type="0",
        curve_term="10",
    )

    if raw_df is None or raw_df.empty:
        print("curve_type=0 返回空，回退到 curve_type=1 ...")
        raw_df = pro.yc_cb(
            start_date=start_date,
            end_date=end_date,
            ts_code="1001.CB",
            curve_type="1",
            curve_term="10",
        )

    if raw_df is None or raw_df.empty:
        print("错误: TuShare yc_cb 返回空数据，请检查 token 积分或日期范围")
        sys.exit(1)

    df = raw_df.copy()
    df["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    df["yield_pct"] = pd.to_numeric(df["yield"], errors="coerce")
    df = df[df["date"].notna() & df["yield_pct"].notna()]
    df = (
        df[["date", "yield_pct"]]
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )

    print(f"获取数据: {len(df)} 条交易日记录")
    return df


def plot_cn10y(df: pd.DataFrame, output_path: str) -> None:
    """生成10年期国债收益率折线图并保存。"""
    fig, ax = plt.subplots(figsize=(14, 7))

    # 主折线
    ax.plot(
        df["date"],
        df["yield_pct"],
        color="#1f6fbf",
        linewidth=2,
        alpha=0.9,
        label="CN10Y 收益率",
        zorder=3,
    )

    # 填充区域（增加视觉层次）
    ax.fill_between(df["date"], df["yield_pct"], alpha=0.08, color="#1f6fbf")

    # 标注最高、最低、最新三个关键点
    idx_max = df["yield_pct"].idxmax()
    idx_min = df["yield_pct"].idxmin()
    latest = df.iloc[-1]
    high_val = df.loc[idx_max]
    low_val = df.loc[idx_min]

    for row, label, color in [
        (high_val, f"最高\n{high_val['yield_pct']:.3f}%", "#d62728"),
        (low_val,  f"最低\n{low_val['yield_pct']:.3f}%",  "#2ca02c"),
        (latest,   f"最新\n{latest['yield_pct']:.3f}%",   "#ff7f0e"),
    ]:
        ax.annotate(
            label,
            xy=(row["date"], row["yield_pct"]),
            xytext=(0, 18),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color=color,
            fontweight="bold",
            arrowprops=dict(arrowstyle="-|>", color=color, lw=1.2),
        )
        ax.scatter(row["date"], row["yield_pct"], color=color, s=60, zorder=5)

    # 轴标题
    start_str = df["date"].iloc[0].strftime("%Y-%m-%d")
    end_str = df["date"].iloc[-1].strftime("%Y-%m-%d")
    ax.set_title(
        f"中国10年期国债收益率走势（{start_str} — {end_str}）",
        fontsize=15,
        fontweight="bold",
        pad=16,
    )
    ax.set_xlabel("日期", fontsize=12)
    ax.set_ylabel("收益率（%）", fontsize=12)

    # X 轴日期格式（每两周一刻度）
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=9)

    # Y 轴区间留边距
    y_range = df["yield_pct"].max() - df["yield_pct"].min()
    margin = max(y_range * 0.15, 0.03)
    ax.set_ylim(df["yield_pct"].min() - margin, df["yield_pct"].max() + margin)

    ax.grid(True, alpha=0.3, linestyle="--")
    ax.legend(loc="upper right", fontsize=11)

    # 数据来源水印
    fig.text(
        0.99, 0.01,
        "数据来源: TuShare yc_cb (ts_code=1001.CB, curve_term=10)",
        ha="right", va="bottom", fontsize=8, color="gray"
    )

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"图表已保存: {output_path}")


def main() -> None:
    today = datetime.today()
    three_months_ago = today - timedelta(days=92)  # ~3 个自然月

    start_date = three_months_ago.strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")

    df = fetch_cn10y(start_date, end_date)

    # 打印统计摘要
    print("\n── 统计摘要 ──────────────────────────")
    print(f"  数据区间: {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}")
    print(f"  交易日数: {len(df)} 天")
    print(f"  最新收益率: {df['yield_pct'].iloc[-1]:.3f}%")
    print(f"  区间最高:  {df['yield_pct'].max():.3f}%  ({df.loc[df['yield_pct'].idxmax(), 'date'].date()})")
    print(f"  区间最低:  {df['yield_pct'].min():.3f}%  ({df.loc[df['yield_pct'].idxmin(), 'date'].date()})")
    print(f"  区间变动:  {df['yield_pct'].iloc[-1] - df['yield_pct'].iloc[0]:+.3f}%")
    print("──────────────────────────────────────\n")

    output_path = os.path.join(
        os.path.dirname(__file__), "..", "reports", "cn10y_3m_chart.png"
    )
    plot_cn10y(df, os.path.abspath(output_path))


if __name__ == "__main__":
    main()
