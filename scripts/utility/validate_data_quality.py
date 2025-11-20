#!/usr/bin/env python3
"""
数据质量验证脚本 - V1.3.2
用于验证背景扫描报告的数据质量和API选择正确性
"""

import asyncio
import sys
import os
import argparse
from datetime import datetime, timedelta

# 设置路径以便导入项目模块
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource import get_manager


class DataQualityValidator:
    """数据质量验证器"""

    def __init__(self):
        self.manager = None

    async def initialize(self):
        """初始化数据管理器"""
        self.manager = get_manager()
        print("数据质量验证器 V1.3.2")
        print("=" * 50)

    def validate_index_value(self, symbol: str, price: float) -> bool:
        """验证指数点数合理性"""
        reasonable_ranges = {
            '000001': (2500, 4500),    # 上证指数
            '000016': (2000, 4000),    # 上证50
            '399001': (8000, 16000),   # 深证成指
            '399006': (1500, 4000),    # 创业板指
        }

        if symbol in reasonable_ranges:
            min_val, max_val = reasonable_ranges[symbol]
            if min_val <= price <= max_val:
                print(f"OK {symbol}: {price:.2f}点 (合理范围)")
                return True
            else:
                print(f"ERR {symbol}: {price:.2f}点 (超出合理范围 {min_val}-{max_val})")
                return False
        else:
            if price <= 0:
                print(f"ERR {symbol}: {price:.2f} (价格异常)")
                return False
            elif price < 0.1:
                print(f"WARN {symbol}: {price:.2f} (价格偏低)")
                return True
            else:
                print(f"OK {symbol}: {price:.2f} (数据正常)")
                return True

    def get_expected_api(self, symbol: str) -> str:
        """获取预期使用的API"""
        if symbol.startswith(('000', '399')):
            return "get_index_daily"
        elif symbol.startswith('^'):
            return "get_index_daily"
        elif symbol.replace('.SH', '').replace('.SZ', '').isdigit():
            return "get_fund_daily"
        else:
            return "get_stock_daily"

    async def validate_api_selection(self, symbol: str, test_date: str) -> dict:
        """验证API选择是否正确"""
        expected_api = self.get_expected_api(symbol)
        results = {}

        print(f"\n测试 {symbol} (期望API: {expected_api})")

        try:
            if expected_api == "get_index_daily":
                response = await self.manager.get_index_daily(symbol, test_date, test_date)
                api_used = "get_index_daily"
            elif expected_api == "get_fund_daily":
                response = await self.manager.get_fund_daily(symbol, test_date, test_date)
                api_used = "get_fund_daily"
            else:
                response = await self.manager.get_stock_daily(symbol, test_date, test_date)
                api_used = "get_stock_daily"

            if response.error:
                print(f"   X API调用失败: {response.error}")
                results = {
                    'success': False,
                    'api_used': api_used,
                    'error': response.error,
                    'price': None,
                    'data_quality': False
                }
            else:
                latest = response.data.iloc[-1]
                price = latest['close']
                data_quality = self.validate_index_value(symbol, price)

                results = {
                    'success': True,
                    'api_used': api_used,
                    'error': None,
                    'price': price,
                    'data_quality': data_quality,
                    'data_source': response.source
                }

                print(f"   数据来源: {response.source}")
                print(f"   收盘价: {price:.2f}")

        except Exception as e:
            print(f"   X 异常: {str(e)}")
            results = {
                'success': False,
                'api_used': api_used,
                'error': str(e),
                'price': None,
                'data_quality': False
            }

        return results

    async def run_comprehensive_validation(self, test_date: str = None):
        """运行综合验证"""
        if test_date is None:
            test_date = datetime.now().strftime("%Y-%m-%d")

        print(f"测试日期: {test_date}\n")

        # 测试指数和代表性标的
        test_symbols = {
            # A股指数 (应使用 get_index_daily)
            '000001': '上证指数',
            '000016': '上证50',
            '399001': '深证成指',
            '399006': '创业板指',
            # 全球指数 (优先使用 get_index_daily + Fallback)
            '^GSPC': '标普500',
            '^IXIC': '纳斯达克',
        }

        all_results = {}
        passed_count = 0
        total_count = 0

        for symbol, name in test_symbols.items():
            total_count += 1
            results = await self.validate_api_selection(symbol, test_date)
            all_results[symbol] = results

            if results['success'] and results['data_quality']:
                passed_count += 1

        # 生成验证报告
        print("\n" + "=" * 50)
        print("验证报告")
        print("=" * 50)

        print(f"总测试项目: {total_count}")
        print(f"通过项目: {passed_count}")
        print(f"成功率: {passed_count/total_count*100:.1f}%")

        # 详细问题分析
        failed_items = []
        for symbol, results in all_results.items():
            if not (results['success'] and results['data_quality']):
                failed_items.append((symbol, results))

        if failed_items:
            print(f"\n警告: 发现 {len(failed_items)} 个问题:")
            for symbol, results in failed_items:
                print(f"   {symbol}: {results.get('error', '数据质量异常')}")
        else:
            print("\n所有验证项目都通过！V1.3.2修复生效")

        return all_results

    async def validate_specific_symbol(self, symbol: str, test_date: str = None):
        """验证特定标的"""
        if test_date is None:
            test_date = datetime.now().strftime("%Y-%m-%d")

        print(f"单项验证: {symbol}")
        return await self.validate_api_selection(symbol, test_date)


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='数据质量验证脚本 V1.3.2')
    parser.add_argument('--symbol', type=str, help='验证特定标的 (如 000001)')
    parser.add_argument('--date', type=str, help='测试日期 (格式: YYYY-MM-DD)')
    parser.add_argument('--comprehensive', action='store_true', help='运行综合验证')

    args = parser.parse_args()

    validator = DataQualityValidator()
    await validator.initialize()

    try:
        if args.symbol:
            # 单项验证
            results = await validator.validate_specific_symbol(args.symbol, args.date)
            print("\n结果:", results)
        else:
            # 综合验证 (默认)
            results = await validator.run_comprehensive_validation(args.date)

    except Exception as e:
        print(f"X 验证过程中发生错误: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
