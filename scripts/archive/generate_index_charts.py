#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成沪深300、中证500、中证1000指数收盘价和成交量折线图
"""

import os
import sys
import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

# 添加项目根目录到路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource import get_manager

# 设置matplotlib中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

class IndexChartGenerator:
    """指数图表生成器"""

    def __init__(self):
        self.manager = get_manager()
        self.indices = {
            "沪深300": "000300",
            "中证500": "000905",
            "中证1000": "000852"
        }
        self.colors = {
            "沪深300": "#1f77b4",
            "中证500": "#ff7f0e",
            "中证1000": "#2ca02c"
        }

    async def fetch_index_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取指数数据"""
        response = await self.manager.get_index_daily(symbol, start_date, end_date)
        if response.error:
            print(f"获取 {symbol} 数据失败: {response.error}")
            return pd.DataFrame()
        return response.data

    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """准备数据"""
        if df.empty:
            return df

        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        return df

    def generate_price_chart(self, data_dict: dict):
        """生成收盘价折线图"""
        fig, ax = plt.subplots(figsize=(14, 8))

        # 绘制收盘价折线
        for name, df in data_dict.items():
            if df.empty:
                continue

            ax.plot(df['date'], df['close'],
                   label=name,
                   color=self.colors[name],
                   linewidth=2,
                   alpha=0.8)

        # 设置标题和标签
        ax.set_title('沪深300、中证500、中证1000指数收盘价走势图（近6个月）',
                    fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('收盘价（点）', fontsize=12)

        # 设置日期格式
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

        # 添加网格
        ax.grid(True, alpha=0.3)

        # 添加图例
        ax.legend(loc='upper left', fontsize=11)

        # 设置布局
        plt.tight_layout()

        # 保存图表
        chart_path = os.path.join(project_root, 'reports', 'index_price_chart.png')
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        print(f"收盘价图表已保存: {chart_path}")

        plt.close()
        return chart_path

    def generate_volume_chart(self, data_dict: dict):
        """生成成交量折线图"""
        fig, ax = plt.subplots(figsize=(14, 8))

        # 绘制成交量折线
        for name, df in data_dict.items():
            if df.empty or 'volume' not in df.columns:
                continue

            # 将成交量转换为万手
            volume_wan = df['volume'] / 10000

            ax.plot(df['date'], volume_wan,
                   label=name,
                   color=self.colors[name],
                   linewidth=2,
                   alpha=0.8)

        # 设置标题和标签
        ax.set_title('沪深300、中证500、中证1000指数成交量走势图（近6个月）',
                    fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('成交量（万手）', fontsize=12)

        # 设置日期格式
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

        # 添加网格
        ax.grid(True, alpha=0.3)

        # 添加图例
        ax.legend(loc='upper left', fontsize=11)

        # 设置布局
        plt.tight_layout()

        # 保存图表
        chart_path = os.path.join(project_root, 'reports', 'index_volume_chart.png')
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        print(f"成交量图表已保存: {chart_path}")

        plt.close()
        return chart_path

    def generate_combined_chart(self, data_dict: dict):
        """生成组合图表（价格+成交量）"""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 12),
                                      gridspec_kw={'height_ratios': [2, 1]})

        # 上图：收盘价
        for name, df in data_dict.items():
            if df.empty:
                continue

            ax1.plot(df['date'], df['close'],
                    label=name,
                    color=self.colors[name],
                    linewidth=2,
                    alpha=0.8)

        ax1.set_title('沪深300、中证500、中证1000指数走势图（近6个月）',
                     fontsize=16, fontweight='bold', pad=20)
        ax1.set_ylabel('收盘价（点）', fontsize=12)
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='upper left', fontsize=11)

        # 下图：成交量
        for name, df in data_dict.items():
            if df.empty or 'volume' not in df.columns:
                continue

            volume_wan = df['volume'] / 10000
            ax2.plot(df['date'], volume_wan,
                    label=name,
                    color=self.colors[name],
                    linewidth=2,
                    alpha=0.8)

        ax2.set_xlabel('日期', fontsize=12)
        ax2.set_ylabel('成交量（万手）', fontsize=12)
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper left', fontsize=11)

        # 设置日期格式（两个子图）
        for ax in [ax1, ax2]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

        # 设置布局
        plt.tight_layout()

        # 保存图表
        chart_path = os.path.join(project_root, 'reports', 'index_combined_chart.png')
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        print(f"组合图表已保存: {chart_path}")

        plt.close()
        return chart_path

    async def run_chart_generation(self):
        """执行图表生成"""
        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)  # 近6个月

        start_str = start_date.strftime('%Y%m%d')
        end_str = end_date.strftime('%Y%m%d')

        print(f"正在获取指数数据 ({start_str} - {end_str})...")

        # 获取数据
        data_dict = {}
        for name, symbol in self.indices.items():
            print(f"获取 {name} ({symbol}) 数据...")
            df = await self.fetch_index_data(symbol, start_str, end_str)
            if not df.empty:
                df = self.prepare_data(df)
                data_dict[name] = df
                print(f"[OK] {name}: 获取 {len(df)} 条记录")
            else:
                print(f"[FAIL] {name}: 数据获取失败")

        if not data_dict:
            print("未能获取任何指数数据，程序退出")
            return

        # 确保reports目录存在
        os.makedirs(os.path.join(project_root, 'reports'), exist_ok=True)

        # 生成图表
        print("\n正在生成图表...")

        price_chart = self.generate_price_chart(data_dict)
        volume_chart = self.generate_volume_chart(data_dict)
        combined_chart = self.generate_combined_chart(data_dict)

        print(f"\n[SUCCESS] 所有图表生成完成:")
        print(f"- 收盘价图表: {price_chart}")
        print(f"- 成交量图表: {volume_chart}")
        print(f"- 组合图表: {combined_chart}")

        return [price_chart, volume_chart, combined_chart]

async def main():
    """主函数"""
    generator = IndexChartGenerator()
    await generator.run_chart_generation()

if __name__ == "__main__":
    asyncio.run(main())