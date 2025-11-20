#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取缺失数据脚本 - 汇率、债券收益率、资金流向
用于补充120日背景扫描报告的N/A项目
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import pandas as pd

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

# Import after path setup
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False


class MissingDataCollector:
    """缺失数据收集器"""

    def __init__(self, end_date: str = "2025-09-16"):
        self.end_date = end_date
        self.start_date_5d = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        self.start_date_120d = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=130)).strftime("%Y-%m-%d")

    def safe_akshare_call(self, func_name: str, *args, **kwargs) -> Optional[pd.DataFrame]:
        """安全调用AKShare函数"""
        if not AKSHARE_AVAILABLE:
            print(f"AKShare不可用，跳过 {func_name}")
            return None

        try:
            func = getattr(ak, func_name)
            result = func(*args, **kwargs)
            print(f"[成功] {func_name} 调用成功，数据形状: {result.shape if isinstance(result, pd.DataFrame) else type(result)}")
            return result
        except Exception as e:
            print(f"[失败] {func_name} 调用失败: {e}")
            return None

    def get_forex_data(self) -> Dict[str, Any]:
        """获取汇率数据"""
        print("=== 获取汇率数据 ===")
        forex_data = {}

        # 1. 获取人民币汇率数据
        print("1. 尝试获取人民币汇率...")

        # 尝试多种AKShare汇率获取方法
        methods_to_try = [
            ("currency_boc_sina", {}),  # 新浪汇率
            ("currency_yahoo", {"symbol": "USDCNY=X"}),  # 雅虎汇率
            ("fx_pair_oanda", {"symbol": "USD_CNY"}),  # Oanda外汇
        ]

        for method, params in methods_to_try:
            print(f"  尝试方法: {method}")
            data = self.safe_akshare_call(method, **params)
            if data is not None and not data.empty:
                print(f"  成功获取数据: {data.shape}")
                forex_data['usd_cny_method'] = method
                forex_data['usd_cny_data'] = data
                break

        # 2. 获取美元指数
        print("2. 尝试获取美元指数DXY...")
        dxy_methods = [
            ("index_investing", {"symbol": "DXY", "country": "united states"}),
            ("currency_usd_index", {}),
        ]

        for method, params in dxy_methods:
            print(f"  尝试方法: {method}")
            data = self.safe_akshare_call(method, **params)
            if data is not None and not data.empty:
                forex_data['dxy_method'] = method
                forex_data['dxy_data'] = data
                break

        return forex_data

    def get_bond_data(self) -> Dict[str, Any]:
        """获取债券收益率数据"""
        print("\n=== 获取债券收益率数据 ===")
        bond_data = {}

        # 1. 获取中国国债收益率
        print("1. 尝试获取中国国债收益率...")
        china_methods = [
            ("bond_zh_us_rate", {}),  # 中美国债收益率
            ("macro_china_bond_public", {}),  # 中国债券收益率
            ("bond_china_yield", {}),  # 债券收益率曲线
        ]

        for method, params in china_methods:
            print(f"  尝试方法: {method}")
            data = self.safe_akshare_call(method, **params)
            if data is not None and not data.empty:
                bond_data['china_method'] = method
                bond_data['china_data'] = data
                break

        # 2. 获取美国国债收益率
        print("2. 尝试获取美国国债收益率...")
        us_methods = [
            ("bond_zh_us_rate", {}),  # 中美国债收益率（包含美国数据）
            ("rate_us_10", {}),  # 美国10年期国债
        ]

        for method, params in us_methods:
            print(f"  尝试方法: {method}")
            data = self.safe_akshare_call(method, **params)
            if data is not None and not data.empty:
                bond_data['us_method'] = method
                bond_data['us_data'] = data
                break

        return bond_data

    def get_capital_flow_data(self) -> Dict[str, Any]:
        """获取资金流向数据"""
        print("\n=== 获取资金流向数据 ===")
        flow_data = {}

        # 1. 获取北向资金
        print("1. 尝试获取北向资金流向...")
        north_methods = [
            ("stock_hk_fund_flow_em", {}),  # 港股资金流向
            ("stock_hsgt_fund_flow_summary_em", {}),  # 沪深港通资金流向汇总
            ("tool_trade_date_hist_sina", {}),  # 交易日历
        ]

        for method, params in north_methods:
            print(f"  尝试方法: {method}")
            data = self.safe_akshare_call(method, **params)
            if data is not None and not data.empty:
                flow_data['north_method'] = method
                flow_data['north_data'] = data
                break

        # 2. 获取融资融券数据
        print("2. 尝试获取融资融券数据...")
        margin_methods = [
            ("stock_margin_underlying_info_sse", {}),  # 上交所融资融券标的
            ("stock_margin_detail_sse", {}),  # 融资融券明细
        ]

        for method, params in margin_methods:
            print(f"  尝试方法: {method}")
            data = self.safe_akshare_call(method, **params)
            if data is not None and not data.empty:
                flow_data['margin_method'] = method
                flow_data['margin_data'] = data
                break

        return flow_data

    def calculate_changes(self, data: pd.DataFrame, date_col: str, value_col: str) -> Dict[str, float]:
        """计算5日和120日变化"""
        if data.empty or date_col not in data.columns or value_col not in data.columns:
            return {'change_5d': None, 'change_120d': None}

        try:
            # 确保日期列是datetime类型
            data[date_col] = pd.to_datetime(data[date_col])
            data = data.sort_values(date_col)

            end_date_dt = datetime.strptime(self.end_date, "%Y-%m-%d")

            # 获取最新值
            latest_data = data[data[date_col] <= end_date_dt].tail(1)
            if latest_data.empty:
                return {'change_5d': None, 'change_120d': None}

            latest_value = latest_data[value_col].iloc[0]

            # 计算5日变化
            date_5d = end_date_dt - timedelta(days=7)
            data_5d = data[data[date_col] <= date_5d].tail(1)
            change_5d = None
            if not data_5d.empty:
                value_5d = data_5d[value_col].iloc[0]
                change_5d = ((latest_value / value_5d) - 1) * 100 if value_5d != 0 else None

            # 计算120日变化
            date_120d = end_date_dt - timedelta(days=130)
            data_120d = data[data[date_col] <= date_120d].tail(1)
            change_120d = None
            if not data_120d.empty:
                value_120d = data_120d[value_col].iloc[0]
                change_120d = ((latest_value / value_120d) - 1) * 100 if value_120d != 0 else None

            return {
                'latest_value': latest_value,
                'change_5d': round(change_5d, 1) if change_5d else None,
                'change_120d': round(change_120d, 1) if change_120d else None
            }

        except Exception as e:
            print(f"计算变化时出错: {e}")
            return {'change_5d': None, 'change_120d': None}

    def generate_summary_report(self, forex_data: Dict, bond_data: Dict, flow_data: Dict) -> str:
        """生成汇总报告"""
        report = f"""
# 缺失数据获取结果报告 ({self.end_date})

## 汇率数据获取结果
"""

        if 'usd_cny_data' in forex_data:
            report += f"- [成功] USD/CNY 汇率数据获取成功 (方法: {forex_data.get('usd_cny_method', 'unknown')})\n"
            data = forex_data['usd_cny_data']
            if not data.empty:
                report += f"  - 数据条数: {len(data)}\n"
                report += f"  - 数据列: {list(data.columns)[:5]}...\n"
        else:
            report += "- [失败] USD/CNY 汇率数据获取失败\n"

        if 'dxy_data' in forex_data:
            report += f"- [成功] 美元指数(DXY) 数据获取成功 (方法: {forex_data.get('dxy_method', 'unknown')})\n"
        else:
            report += "- [失败] 美元指数(DXY) 数据获取失败\n"

        report += "\n## 债券收益率数据获取结果\n"

        if 'china_data' in bond_data:
            report += f"- [成功] 中国债券收益率数据获取成功 (方法: {bond_data.get('china_method', 'unknown')})\n"
        else:
            report += "- [失败] 中国债券收益率数据获取失败\n"

        if 'us_data' in bond_data:
            report += f"- [成功] 美国债券收益率数据获取成功 (方法: {bond_data.get('us_method', 'unknown')})\n"
        else:
            report += "- [失败] 美国债券收益率数据获取失败\n"

        report += "\n## 资金流向数据获取结果\n"

        if 'north_data' in flow_data:
            report += f"- [成功] 北向资金数据获取成功 (方法: {flow_data.get('north_method', 'unknown')})\n"
        else:
            report += "- [失败] 北向资金数据获取失败\n"

        if 'margin_data' in flow_data:
            report += f"- [成功] 融资融券数据获取成功 (方法: {flow_data.get('margin_method', 'unknown')})\n"
        else:
            report += "- [失败] 融资融券数据获取失败\n"

        report += f"""
## 技术说明

- **测试时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
- **数据窗口**: {self.start_date_120d} 至 {self.end_date}
- **AKShare可用**: {AKSHARE_AVAILABLE}
- **TuShare可用**: {TUSHARE_AVAILABLE}

## 建议

基于测试结果，建议采用以下策略填充缺失数据：
1. 对于成功获取的数据，计算相应的5日和120日变化
2. 对于获取失败的数据，使用Web搜索或手动填入近似值
3. 在报告中标注数据来源和获取方法的可靠性
"""
        return report


async def main():
    """主函数"""
    print("开始获取缺失数据...")

    collector = MissingDataCollector()

    # 获取各类数据
    forex_data = collector.get_forex_data()
    bond_data = collector.get_bond_data()
    flow_data = collector.get_capital_flow_data()

    # 生成报告
    summary = collector.generate_summary_report(forex_data, bond_data, flow_data)

    # 保存结果
    os.makedirs("reports", exist_ok=True)
    report_file = f"reports/missing_data_collection_{collector.end_date.replace('-', '')}.md"

    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(summary)

    print(f"\n缺失数据收集报告已生成: {report_file}")
    print("=" * 50)
    print(summary)

    return {
        'forex_data': forex_data,
        'bond_data': bond_data,
        'flow_data': flow_data,
        'summary_file': report_file
    }


if __name__ == "__main__":
    result = asyncio.run(main())