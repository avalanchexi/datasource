#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
沪深300、中证500、中证1000指数近半年走势统计脚本
生成按日呈现的趋势分析报告
"""

import os
import sys
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List

# 添加项目根目录到路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource import get_manager
from datasource.config.indices_config import A_SHARE_INDICES

class IndexTrendAnalyzer:
    """指数趋势分析器"""

    def __init__(self):
        self.manager = get_manager()
        self.indices = {
            "沪深300": "000300",
            "中证500": "000905",
            "中证1000": "000852"
        }

    async def fetch_index_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取指数数据"""
        response = await self.manager.get_index_daily(symbol, start_date, end_date)
        if response.error:
            print(f"获取 {symbol} 数据失败: {response.error}")
            return pd.DataFrame()
        return response.data

    def calculate_daily_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算日度指标"""
        if df.empty:
            return df

        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')

        # 计算日度变化
        df['price_change'] = df['close'].diff()
        df['price_change_pct'] = df['close'].pct_change() * 100

        # 计算累计收益率
        df['cumulative_return'] = ((df['close'] / df['close'].iloc[0]) - 1) * 100

        # 计算移动平均
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()

        # 计算相对强弱
        df['relative_to_ma5'] = ((df['close'] / df['ma5']) - 1) * 100
        df['relative_to_ma20'] = ((df['close'] / df['ma20']) - 1) * 100

        # 成交量相关计算
        if 'volume' in df.columns:
            # 成交量变化
            df['volume_change'] = df['volume'].diff()
            df['volume_change_pct'] = df['volume'].pct_change() * 100

            # 成交量移动平均
            df['volume_ma5'] = df['volume'].rolling(window=5).mean()
            df['volume_ma20'] = df['volume'].rolling(window=20).mean()

            # 量价关系
            df['volume_relative_to_ma5'] = ((df['volume'] / df['volume_ma5']) - 1) * 100
            df['volume_relative_to_ma20'] = ((df['volume'] / df['volume_ma20']) - 1) * 100

        return df

    def generate_trend_summary(self, data_dict: Dict[str, pd.DataFrame]) -> Dict:
        """生成趋势总结"""
        summary = {}

        for name, df in data_dict.items():
            if df.empty:
                continue

            latest = df.iloc[-1]
            first = df.iloc[0]

            base_summary = {
                'period_return': ((latest['close'] / first['close']) - 1) * 100,
                'max_price': df['close'].max(),
                'min_price': df['close'].min(),
                'max_daily_gain': df['price_change_pct'].max(),
                'max_daily_loss': df['price_change_pct'].min(),
                'volatility': df['price_change_pct'].std(),
                'positive_days': (df['price_change_pct'] > 0).sum(),
                'negative_days': (df['price_change_pct'] < 0).sum(),
                'total_days': len(df),
                'current_price': latest['close'],
                'latest_date': latest['date'].strftime('%Y-%m-%d')
            }

            # 添加成交量相关统计
            if 'volume' in df.columns:
                base_summary.update({
                    'avg_volume': df['volume'].mean(),
                    'max_volume': df['volume'].max(),
                    'min_volume': df['volume'].min(),
                    'current_volume': latest['volume'],
                    'volume_volatility': df['volume_change_pct'].std() if 'volume_change_pct' in df.columns else None,
                    'avg_volume_ma5': df['volume_ma5'].mean() if 'volume_ma5' in df.columns else None,
                    'avg_volume_ma20': df['volume_ma20'].mean() if 'volume_ma20' in df.columns else None
                })

            summary[name] = base_summary

        return summary

    def generate_markdown_report(self, data_dict: Dict[str, pd.DataFrame], summary: Dict) -> str:
        """生成Markdown报告"""

        report_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        md_content = f"""# 沪深300、中证500、中证1000指数近半年走势分析报告

**生成时间**: {report_date}
**分析周期**: 近6个月 ({summary[list(summary.keys())[0]]['latest_date']} 回溯180天)

## 📊 总体表现概览

| 指数 | 期间收益率 | 当前点位 | 最高点位 | 最低点位 | 波动率 | 上涨天数 | 下跌天数 |
|------|------------|----------|----------|----------|--------|----------|----------|
"""

        for name, stats in summary.items():
            md_content += f"| {name} | {stats['period_return']:.2f}% | {stats['current_price']:.2f} | {stats['max_price']:.2f} | {stats['min_price']:.2f} | {stats['volatility']:.2f}% | {stats['positive_days']} | {stats['negative_days']} |\n"

        # 添加成交量概览表
        has_volume = any('avg_volume' in stats for stats in summary.values())
        if has_volume:
            md_content += "\n## 📈 成交量概览\n\n"
            md_content += "| 指数 | 当前成交量 | 平均成交量 | 最大成交量 | 最小成交量 | 成交量波动率 |\n"
            md_content += "|------|------------|------------|------------|------------|----------|\n"

            for name, stats in summary.items():
                if 'avg_volume' in stats:
                    current_vol = stats.get('current_volume', 0)
                    avg_vol = stats.get('avg_volume', 0)
                    max_vol = stats.get('max_volume', 0)
                    min_vol = stats.get('min_volume', 0)
                    vol_volatility = stats.get('volume_volatility', 0) or 0

                    md_content += f"| {name} | {current_vol/10000:.0f}万 | {avg_vol/10000:.0f}万 | {max_vol/10000:.0f}万 | {min_vol/10000:.0f}万 | {vol_volatility:.2f}% |\n"

        md_content += "\n## 📈 详细走势分析\n\n"

        for name, df in data_dict.items():
            if df.empty:
                continue

            stats = summary[name]
            md_content += f"### {name}\n\n"
            md_content += f"**期间表现**: {stats['period_return']:.2f}%\n"
            md_content += f"**最大单日涨幅**: {stats['max_daily_gain']:.2f}%\n"
            md_content += f"**最大单日跌幅**: {stats['max_daily_loss']:.2f}%\n"
            md_content += f"**胜率**: {(stats['positive_days'] / stats['total_days'] * 100):.1f}%\n\n"

            # 近期表现
            recent_data = df.tail(10)
            md_content += "**近10个交易日表现**:\n\n"

            # 根据是否有成交量数据决定表格列
            if 'volume' in df.columns:
                md_content += "| 日期 | 收盘价 | 日涨跌 | 日涨跌% | 累计收益% | 成交量(万) | 量变% | 相对MA5 | 相对MA20 |\n"
                md_content += "|------|--------|--------|---------|----------|-----------|-------|---------|----------|\n"

                for _, row in recent_data.iterrows():
                    volume_str = f"{row['volume']/10000:.0f}" if pd.notna(row['volume']) else "-"
                    volume_change_str = f"{row['volume_change_pct']:.1f}%" if pd.notna(row.get('volume_change_pct', None)) else "-"

                    md_content += f"| {row['date'].strftime('%m-%d')} | {row['close']:.2f} | "
                    md_content += f"{row['price_change']:.2f} | {row['price_change_pct']:.2f}% | "
                    md_content += f"{row['cumulative_return']:.2f}% | {volume_str} | {volume_change_str} | "
                    md_content += f"{row['relative_to_ma5']:.2f}% | {row['relative_to_ma20']:.2f}% |\n"
            else:
                md_content += "| 日期 | 收盘价 | 日涨跌 | 日涨跌% | 累计收益% | 相对MA5 | 相对MA20 |\n"
                md_content += "|------|--------|--------|---------|----------|---------|----------|\n"

                for _, row in recent_data.iterrows():
                    md_content += f"| {row['date'].strftime('%m-%d')} | {row['close']:.2f} | "
                    md_content += f"{row['price_change']:.2f} | {row['price_change_pct']:.2f}% | "
                    md_content += f"{row['cumulative_return']:.2f}% | "
                    md_content += f"{row['relative_to_ma5']:.2f}% | {row['relative_to_ma20']:.2f}% |\n"

            md_content += "\n"

        # 添加每月统计
        md_content += "## 📅 月度表现统计\n\n"

        for name, df in data_dict.items():
            if df.empty:
                continue

            df_copy = df.copy()
            df_copy['month'] = df_copy['date'].dt.to_period('M')

            # 准备聚合字典
            agg_dict = {
                'close': ['first', 'last'],
                'price_change_pct': ['sum', 'std']
            }

            # 如果有成交量数据，添加到聚合中
            if 'volume' in df_copy.columns:
                agg_dict['volume'] = ['mean', 'sum']

            monthly_stats = df_copy.groupby('month').agg(agg_dict).round(2)

            md_content += f"### {name} 月度表现\n\n"

            # 根据是否有成交量数据决定表格列
            if 'volume' in df_copy.columns:
                md_content += "| 月份 | 月初价格 | 月末价格 | 月度收益% | 月度波动% | 平均成交量(万) | 总成交量(万) |\n"
                md_content += "|------|----------|----------|-----------|-----------|--------------|--------------|\n"
            else:
                md_content += "| 月份 | 月初价格 | 月末价格 | 月度收益% | 月度波动% |\n"
                md_content += "|------|----------|----------|-----------|-----------|\n"

            for month in monthly_stats.index:
                first_price = monthly_stats.loc[month, ('close', 'first')]
                last_price = monthly_stats.loc[month, ('close', 'last')]
                monthly_return = ((last_price / first_price) - 1) * 100
                monthly_vol = monthly_stats.loc[month, ('price_change_pct', 'std')]

                if 'volume' in df_copy.columns:
                    avg_volume = monthly_stats.loc[month, ('volume', 'mean')]
                    total_volume = monthly_stats.loc[month, ('volume', 'sum')]
                    md_content += f"| {month} | {first_price:.2f} | {last_price:.2f} | {monthly_return:.2f}% | {monthly_vol:.2f}% | {avg_volume/10000:.0f} | {total_volume/10000:.0f} |\n"
                else:
                    md_content += f"| {month} | {first_price:.2f} | {last_price:.2f} | {monthly_return:.2f}% | {monthly_vol:.2f}% |\n"

            md_content += "\n"

        # 添加风险分析
        md_content += "## ⚠️ 风险分析\n\n"

        for name, stats in summary.items():
            risk_level = "低" if stats['volatility'] < 15 else "中" if stats['volatility'] < 25 else "高"
            md_content += f"- **{name}**: 波动率 {stats['volatility']:.2f}% (风险等级: {risk_level})\n"

        md_content += "\n## 💡 投资建议\n\n"

        # 根据表现给出建议
        best_performer = max(summary.keys(), key=lambda x: summary[x]['period_return'])
        worst_performer = min(summary.keys(), key=lambda x: summary[x]['period_return'])

        md_content += f"- **最佳表现**: {best_performer} (收益率: {summary[best_performer]['period_return']:.2f}%)\n"
        md_content += f"- **表现最弱**: {worst_performer} (收益率: {summary[worst_performer]['period_return']:.2f}%)\n\n"

        md_content += "**风险提示**: 本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。\n\n"
        md_content += f"---\n*报告生成时间: {report_date}*\n"

        return md_content

    async def run_analysis(self):
        """执行分析"""
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
                df = self.calculate_daily_metrics(df)
                data_dict[name] = df
                print(f"[OK] {name}: 获取 {len(df)} 条记录")
            else:
                print(f"[FAIL] {name}: 数据获取失败")

        if not data_dict:
            print("未能获取任何指数数据，程序退出")
            return

        # 生成总结
        summary = self.generate_trend_summary(data_dict)

        # 生成报告
        md_content = self.generate_markdown_report(data_dict, summary)

        # 保存文件
        report_filename = f"index_trend_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path = os.path.join(project_root, 'reports', report_filename)

        # 确保reports目录存在
        os.makedirs(os.path.dirname(report_path), exist_ok=True)

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        print(f"\n[SUCCESS] 分析报告已生成: {report_path}")
        return report_path

async def main():
    """主函数"""
    analyzer = IndexTrendAnalyzer()
    await analyzer.run_analysis()

if __name__ == "__main__":
    asyncio.run(main())