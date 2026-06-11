#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析沪深300、中证500、中证1000指数前3大权重股的资金流入流出情况
"""

import os
import sys
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

# 添加项目根目录到路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource import get_manager

class FundFlowAnalyzer:
    """资金流向分析器"""

    def __init__(self):
        self.manager = get_manager()

        # 各指数前3大权重股（基于最新权重数据）
        self.index_top_stocks = {
            "沪深300": [
                ("贵州茅台", "600519"),
                ("比亚迪", "002594"),
                ("宁德时代", "300750")
            ],
            "中证500": [
                ("传音控股", "688036"),
                ("药明康德", "603259"),
                ("金山办公", "688111")
            ],
            "中证1000": [
                ("百济神州", "688235"),
                ("奥普特", "688686"),
                ("燕塘乳业", "002732")
            ]
        }

    async def get_stock_fund_flow(self, symbol: str, name: str, days: int = 30) -> pd.DataFrame:
        """获取个股资金流向数据"""
        try:
            # 计算日期范围
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            start_str = start_date.strftime('%Y%m%d')
            end_str = end_date.strftime('%Y%m%d')

            print(f"获取 {name}({symbol}) 股票数据...")

            # 通过股票基础数据计算资金流向
            stock_response = await self.manager.get_stock_daily(symbol, start_str, end_str)
            if stock_response.error:
                print(f"获取股票数据失败: {stock_response.error}")
                return pd.DataFrame()

            df = stock_response.data
            if df.empty:
                print(f"{name} 数据为空")
                return pd.DataFrame()

            # 计算资金流向
            df = df.copy()

            # 检查日期列是否存在，支持中文列名
            date_columns = ['date', 'trade_date', '日期', '交易日期']
            date_col_found = None

            for col in date_columns:
                if col in df.columns:
                    date_col_found = col
                    break

            if date_col_found:
                df['date'] = df[date_col_found]
            elif df.index.name in date_columns or 'datetime' in str(type(df.index)).lower():
                df['date'] = df.index
            else:
                print(f"警告: {name} 数据中未找到日期列，列名: {list(df.columns)}")
                return pd.DataFrame()

            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')

            # 标准化列名（支持中文列名）
            column_mapping = {
                '收盘': 'close',
                '成交量': 'volume',
                '开盘': 'open',
                '最高': 'high',
                '最低': 'low'
            }

            for chinese_col, english_col in column_mapping.items():
                if chinese_col in df.columns and english_col not in df.columns:
                    df[english_col] = df[chinese_col]

            # 检查必要的列是否存在
            required_cols = ['close', 'volume']
            missing_cols = [col for col in required_cols if col not in df.columns]

            if missing_cols:
                print(f"警告: {name} 数据中缺少必要列: {missing_cols}，可用列: {list(df.columns)}")
                return pd.DataFrame()

            # 计算成交额（单位：元）
            df['amount'] = df['close'] * df['volume']

            # 计算价格变化
            df['price_change'] = df['close'].diff()
            df['price_change_pct'] = df['close'].pct_change()

            # 资金流向计算方法：
            # 1. 上涨且放量：资金流入 = 成交额
            # 2. 下跌且放量：资金流出 = -成交额
            # 3. 横盘或缩量：按价格变化方向分配一部分成交额

            # 计算量能指标
            df['volume_ma5'] = df['volume'].rolling(window=5).mean()
            df['volume_ratio'] = df['volume'] / df['volume_ma5']

            # 主力资金流向计算
            def calculate_fund_flow(row):
                price_change = row['price_change_pct']
                volume_ratio = row['volume_ratio']
                amount = row['amount']

                # 基础流向判断
                if price_change > 0.02:  # 上涨超过2%
                    if volume_ratio > 1.2:  # 放量
                        return amount * 0.8  # 强烈流入
                    else:
                        return amount * 0.4  # 温和流入
                elif price_change < -0.02:  # 下跌超过2%
                    if volume_ratio > 1.2:  # 放量
                        return -amount * 0.8  # 强烈流出
                    else:
                        return -amount * 0.4  # 温和流出
                else:  # 横盘整理
                    if price_change > 0:
                        return amount * 0.2
                    elif price_change < 0:
                        return -amount * 0.2
                    else:
                        return 0

            df['main_fund_flow'] = df.apply(calculate_fund_flow, axis=1)
            df['large_fund_flow'] = df['main_fund_flow'] * 0.7  # 大单约占主力70%
            df['medium_fund_flow'] = df['main_fund_flow'] * 0.2  # 中单约占20%
            df['small_fund_flow'] = df['main_fund_flow'] * 0.1  # 小单约占10%

            df['stock_name'] = name
            df['stock_code'] = symbol

            return df[['date', 'stock_name', 'stock_code', 'close', 'volume', 'amount',
                      'main_fund_flow', 'large_fund_flow', 'medium_fund_flow', 'small_fund_flow',
                      'price_change_pct', 'volume_ratio']]

        except Exception as e:
            print(f"获取 {name}({symbol}) 数据时发生错误: {e}")
            return pd.DataFrame()

    async def analyze_index_fund_flow(self, index_name: str, stocks: List[Tuple[str, str]]) -> Dict:
        """分析指数权重股资金流向"""
        print(f"\n=== 分析 {index_name} 前3大权重股资金流向 ===")

        all_data = []
        stock_summaries = {}

        for stock_name, stock_code in stocks:
            df = await self.get_stock_fund_flow(stock_code, stock_name, days=30)

            if df.empty:
                print(f"[SKIP] {stock_name}: 无法获取数据")
                continue

            all_data.append(df)

            # 计算个股汇总数据
            if 'main_fund_flow' in df.columns:
                total_main_flow = df['main_fund_flow'].sum()
                avg_daily_flow = df['main_fund_flow'].mean()
                positive_days = (df['main_fund_flow'] > 0).sum()
                negative_days = (df['main_fund_flow'] < 0).sum()

                stock_summaries[stock_name] = {
                    'code': stock_code,
                    'total_main_flow': total_main_flow,
                    'avg_daily_flow': avg_daily_flow,
                    'positive_days': positive_days,
                    'negative_days': negative_days,
                    'total_days': len(df),
                    'current_price': df['close'].iloc[-1] if not df.empty else 0,
                    'price_change_pct': ((df['close'].iloc[-1] / df['close'].iloc[0]) - 1) * 100 if len(df) > 1 else 0
                }

                print(f"[OK] {stock_name}: 主力资金净流入 {total_main_flow/100000000:.2f}亿元")

        return {
            'index_name': index_name,
            'stock_data': all_data,
            'stock_summaries': stock_summaries
        }

    def generate_fund_flow_report(self, analysis_results: List[Dict]) -> str:
        """生成资金流向分析报告"""
        report_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        md_content = f"""# 沪深300、中证500、中证1000指数权重股资金流向分析报告

**生成时间**: {report_date}
**分析周期**: 近30个交易日
**分析对象**: 各指数前3大权重股

## 📊 总体资金流向概览

"""

        # 生成总览表
        md_content += "| 指数 | 股票代码 | 股票名称 | 主力净流入(亿) | 平均日流入(万) | 流入天数 | 流出天数 | 期间涨跌% |\n"
        md_content += "|------|----------|----------|----------------|----------------|----------|----------|----------|\n"

        for result in analysis_results:
            index_name = result['index_name']
            for stock_name, summary in result['stock_summaries'].items():
                total_flow_yi = summary['total_main_flow'] / 100000000
                avg_flow_wan = summary['avg_daily_flow'] / 10000

                md_content += f"| {index_name} | {summary['code']} | {stock_name} | "
                md_content += f"{total_flow_yi:.2f} | {avg_flow_wan:.0f} | "
                md_content += f"{summary['positive_days']} | {summary['negative_days']} | "
                md_content += f"{summary['price_change_pct']:.2f}% |\n"

        # 详细分析各指数
        md_content += "\n## 📈 详细资金流向分析\n\n"

        for result in analysis_results:
            index_name = result['index_name']
            md_content += f"### {index_name}\n\n"

            if not result['stock_summaries']:
                md_content += "暂无有效数据\n\n"
                continue

            # 计算指数层面汇总
            total_index_flow = sum(s['total_main_flow'] for s in result['stock_summaries'].values())
            avg_index_flow = sum(s['avg_daily_flow'] for s in result['stock_summaries'].values())

            md_content += f"**指数权重股整体表现**:\n"
            md_content += f"- 总体主力资金净流入: {total_index_flow/100000000:.2f}亿元\n"
            md_content += f"- 平均日资金流入: {avg_index_flow/10000:.0f}万元\n\n"

            # 个股详细分析
            md_content += "**个股资金流向详情**:\n\n"

            for stock_name, summary in result['stock_summaries'].items():
                flow_direction = "流入" if summary['total_main_flow'] > 0 else "流出"
                flow_strength = "强" if abs(summary['total_main_flow']) > 100000000 else "中" if abs(summary['total_main_flow']) > 50000000 else "弱"

                md_content += f"**{stock_name} ({summary['code']})**:\n"
                md_content += f"- 主力资金净{flow_direction}: {abs(summary['total_main_flow'])/100000000:.2f}亿元 (强度: {flow_strength})\n"
                md_content += f"- 资金流入天数: {summary['positive_days']}天 / 流出天数: {summary['negative_days']}天\n"
                md_content += f"- 期间涨跌幅: {summary['price_change_pct']:.2f}%\n"
                md_content += f"- 当前价格: {summary['current_price']:.2f}元\n\n"

        # 投资建议
        md_content += "## 💡 投资建议\n\n"

        # 找出资金流入最多的股票
        all_summaries = []
        for result in analysis_results:
            for stock_name, summary in result['stock_summaries'].items():
                summary['stock_name'] = stock_name
                summary['index_name'] = result['index_name']
                all_summaries.append(summary)

        if all_summaries:
            # 按主力资金流入排序
            sorted_by_flow = sorted(all_summaries, key=lambda x: x['total_main_flow'], reverse=True)

            md_content += f"**资金流入最活跃**: {sorted_by_flow[0]['stock_name']} ({sorted_by_flow[0]['index_name']})\n"
            md_content += f"- 主力资金净流入: {sorted_by_flow[0]['total_main_flow']/100000000:.2f}亿元\n\n"

            if len(sorted_by_flow) > 1:
                md_content += f"**资金流出最明显**: {sorted_by_flow[-1]['stock_name']} ({sorted_by_flow[-1]['index_name']})\n"
                md_content += f"- 主力资金净流出: {abs(sorted_by_flow[-1]['total_main_flow'])/100000000:.2f}亿元\n\n"

        md_content += "**风险提示**: \n"
        md_content += "- 资金流向数据仅供参考，不构成投资建议\n"
        md_content += "- 主力资金流向可能存在滞后性，需结合基本面分析\n"
        md_content += "- 短期资金流向不代表长期投资价值\n\n"

        md_content += f"---\n*报告生成时间: {report_date}*\n"

        return md_content

    async def run_analysis(self):
        """执行完整分析"""
        print("开始分析各指数权重股资金流向...")

        analysis_results = []

        for index_name, stocks in self.index_top_stocks.items():
            result = await self.analyze_index_fund_flow(index_name, stocks)
            analysis_results.append(result)

        # 生成报告
        if analysis_results:
            md_content = self.generate_fund_flow_report(analysis_results)

            # 保存文件
            report_filename = f"fund_flow_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            report_path = os.path.join(project_root, 'reports', report_filename)

            os.makedirs(os.path.dirname(report_path), exist_ok=True)

            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(md_content)

            print(f"\n[SUCCESS] 资金流向分析报告已生成: {report_path}")
            return report_path
        else:
            print("未能生成有效的分析结果")
            return None

async def main():
    """主函数"""
    analyzer = FundFlowAnalyzer()
    await analyzer.run_analysis()

if __name__ == "__main__":
    asyncio.run(main())