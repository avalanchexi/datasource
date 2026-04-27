#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性脚本：通过 TuShare 拉取中国10年期国债近3个月日收益率数据，
使用 Plotly 生成可交互 HTML 图表。

用法:
    bash run_clean.sh python scripts/cn10y_interactive_chart.py
    # 生成后用浏览器打开 reports/cn10y_3m_chart_interactive.html

输出: reports/cn10y_3m_chart_interactive.html
"""

import os
import sys
from datetime import datetime, timedelta

import pandas as pd

# 加载 .env
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

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    print("错误: 未安装 plotly，请执行 pip install plotly")
    sys.exit(1)


def fetch_cn10y(start_date: str, end_date: str) -> pd.DataFrame:
    """通过 TuShare yc_cb 获取 CN10Y 日收益率数据。"""
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


def build_interactive_chart(df: pd.DataFrame, output_path: str) -> None:
    """使用 Plotly 生成可交互折线图并保存为独立 HTML。"""

    # 计算移动均线
    df = df.copy()
    df["ma5"] = df["yield_pct"].rolling(5).mean()
    df["ma20"] = df["yield_pct"].rolling(20).mean()

    # 关键点
    idx_max = df["yield_pct"].idxmax()
    idx_min = df["yield_pct"].idxmin()
    latest = df.iloc[-1]
    high_val = df.loc[idx_max]
    low_val = df.loc[idx_min]

    start_str = df["date"].iloc[0].strftime("%Y-%m-%d")
    end_str = df["date"].iloc[-1].strftime("%Y-%m-%d")

    # ── 布局：主图 + 变化柱状图（子图） ──────────────────────────────────────
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.06,
        subplot_titles=("", "日变化（bp）"),
    )

    # 主折线
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["yield_pct"],
            name="CN10Y 收益率",
            mode="lines",
            line=dict(color="#1f6fbf", width=2),
            hovertemplate=(
                "<b>%{x|%Y-%m-%d}</b><br>"
                "收益率: <b>%{y:.3f}%</b><extra></extra>"
            ),
            fill="tozeroy",
            fillcolor="rgba(31,111,191,0.07)",
        ),
        row=1, col=1,
    )

    # 5 日均线
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["ma5"],
            name="5日均线",
            mode="lines",
            line=dict(color="#ff7f0e", width=1.5, dash="dot"),
            hovertemplate=(
                "<b>%{x|%Y-%m-%d}</b><br>"
                "5日均线: <b>%{y:.3f}%</b><extra></extra>"
            ),
        ),
        row=1, col=1,
    )

    # 20 日均线
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["ma20"],
            name="20日均线",
            mode="lines",
            line=dict(color="#9467bd", width=1.5, dash="dash"),
            hovertemplate=(
                "<b>%{x|%Y-%m-%d}</b><br>"
                "20日均线: <b>%{y:.3f}%</b><extra></extra>"
            ),
        ),
        row=1, col=1,
    )

    # 最高/最低/最新标注
    annotations = [
        dict(
            x=high_val["date"], y=high_val["yield_pct"],
            text=f"最高<br>{high_val['yield_pct']:.3f}%",
            showarrow=True, arrowhead=2, arrowcolor="#d62728",
            font=dict(color="#d62728", size=11, family="SimHei, Arial"),
            bgcolor="rgba(255,255,255,0.85)", bordercolor="#d62728",
            ax=0, ay=-40,
        ),
        dict(
            x=low_val["date"], y=low_val["yield_pct"],
            text=f"最低<br>{low_val['yield_pct']:.3f}%",
            showarrow=True, arrowhead=2, arrowcolor="#2ca02c",
            font=dict(color="#2ca02c", size=11, family="SimHei, Arial"),
            bgcolor="rgba(255,255,255,0.85)", bordercolor="#2ca02c",
            ax=0, ay=40,
        ),
        dict(
            x=latest["date"], y=latest["yield_pct"],
            text=f"最新<br>{latest['yield_pct']:.3f}%",
            showarrow=True, arrowhead=2, arrowcolor="#ff7f0e",
            font=dict(color="#ff7f0e", size=11, family="SimHei, Arial"),
            bgcolor="rgba(255,255,255,0.85)", bordercolor="#ff7f0e",
            ax=30, ay=-30,
        ),
    ]

    # 日变化柱状图（bp = 当日 - 前日）
    df["daily_chg_bp"] = df["yield_pct"].diff() * 100
    bar_colors = [
        "#d62728" if v >= 0 else "#2ca02c"
        for v in df["daily_chg_bp"].fillna(0)
    ]
    fig.add_trace(
        go.Bar(
            x=df["date"],
            y=df["daily_chg_bp"],
            name="日变化(bp)",
            marker_color=bar_colors,
            hovertemplate=(
                "<b>%{x|%Y-%m-%d}</b><br>"
                "变化: <b>%{y:+.2f} bp</b><extra></extra>"
            ),
        ),
        row=2, col=1,
    )

    # ── 布局配置 ─────────────────────────────────────────────────────────────
    range_chg = latest["yield_pct"] - df["yield_pct"].iloc[0]
    fig.update_layout(
        title=dict(
            text=(
                f"中国10年期国债收益率走势（{start_str} — {end_str}）<br>"
                f"<sup>最新 {latest['yield_pct']:.3f}%　"
                f"区间变动 {range_chg:+.3f}%　"
                f"共 {len(df)} 个交易日</sup>"
            ),
            font=dict(size=17, family="SimHei, Microsoft YaHei, Arial"),
            x=0.5,
        ),
        annotations=annotations,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01,
            xanchor="right", x=1,
            font=dict(family="SimHei, Arial", size=12),
        ),
        hovermode="x unified",
        height=620,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=60, r=40, t=110, b=60),
        font=dict(family="SimHei, Microsoft YaHei, Arial", size=12),
    )

    # X 轴（共享）
    fig.update_xaxes(
        showgrid=True, gridcolor="#eeeeee",
        tickformat="%m-%d",
        rangeslider=dict(visible=True, thickness=0.06),
        row=2, col=1,
    )
    fig.update_xaxes(showgrid=True, gridcolor="#eeeeee", row=1, col=1)

    # Y 轴
    fig.update_yaxes(
        title_text="收益率（%）",
        showgrid=True, gridcolor="#eeeeee",
        tickformat=".3f",
        row=1, col=1,
    )
    fig.update_yaxes(
        title_text="bp",
        showgrid=True, gridcolor="#eeeeee",
        zeroline=True, zerolinecolor="#cccccc",
        row=2, col=1,
    )

    # 数据来源注释
    fig.add_annotation(
        text="数据来源: TuShare yc_cb (ts_code=1001.CB, curve_type=0, curve_term=10)",
        xref="paper", yref="paper",
        x=1, y=-0.12, showarrow=False,
        font=dict(size=9, color="gray"),
        xanchor="right",
    )

    # 保存
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.write_html(
        output_path,
        include_plotlyjs="cdn",   # 引用 CDN，文件体积小
        full_html=True,
    )
    print(f"交互图表已保存: {output_path}")


def main() -> None:
    today = datetime.today()
    three_months_ago = today - timedelta(days=92)

    start_date = three_months_ago.strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")

    df = fetch_cn10y(start_date, end_date)

    print("\n── 统计摘要 ──────────────────────────")
    print(f"  数据区间: {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}")
    print(f"  交易日数: {len(df)} 天")
    print(f"  最新收益率: {df['yield_pct'].iloc[-1]:.3f}%")
    print(f"  区间最高:  {df['yield_pct'].max():.3f}%  ({df.loc[df['yield_pct'].idxmax(), 'date'].date()})")
    print(f"  区间最低:  {df['yield_pct'].min():.3f}%  ({df.loc[df['yield_pct'].idxmin(), 'date'].date()})")
    print(f"  区间变动:  {df['yield_pct'].iloc[-1] - df['yield_pct'].iloc[0]:+.3f}%")
    print("──────────────────────────────────────\n")

    output_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "reports", "cn10y_3m_chart_interactive.html")
    )
    build_interactive_chart(df, output_path)


if __name__ == "__main__":
    main()
