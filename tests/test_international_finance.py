#!/usr/bin/env python3
"""
测试国际金融数据适配器
验证汇率、国债收益率数据获取功能
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta

# 添加项目根路径下的 src 目录
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource import get_manager
from datasource.utils.yahoo_finance import (
    validate_international_finance_support,
    batch_get_background_scan_forex,
    batch_get_background_scan_bonds
)


async def test_forex_data():
    """测试汇率数据获取"""
    print("\n=== 测试汇率数据获取 ===")

    manager = get_manager()
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # 测试主要汇率
    forex_symbols = ["DXY", "USDCNY", "USDCNH"]

    for symbol in forex_symbols:
        print(f"\n测试 {symbol}...")
        try:
            response = await manager.get_forex_data(symbol, start_date, end_date)
            if response.error:
                print(f"  ❌ 失败: {response.error}")
            else:
                print(f"  ✅ 成功: 获取 {len(response.data)} 条数据")
                print(f"  📊 数据源: {response.source}")
                if response.metadata:
                    print(f"  🔍 元数据: {response.metadata.get('data_source', 'N/A')}")
        except Exception as e:
            print(f"  💥 异常: {e}")


async def test_bond_yield_data():
    """测试国债收益率数据获取"""
    print("\n=== 测试国债收益率数据获取 ===")

    manager = get_manager()
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # 测试主要国债
    bond_symbols = ["US10Y", "CN10Y", "CN10Y_CDB"]

    for symbol in bond_symbols:
        print(f"\n测试 {symbol}...")
        try:
            response = await manager.get_bond_yield_data(symbol, start_date, end_date)
            if response.error:
                print(f"  ❌ 失败: {response.error}")
            else:
                print(f"  ✅ 成功: 获取 {len(response.data)} 条数据")
                print(f"  📊 数据源: {response.source}")
                if response.metadata:
                    print(f"  🔍 元数据: {response.metadata.get('data_source', 'N/A')}")
                    if 'calculation_method' in response.metadata:
                        print(f"  🧮 计算方法: {response.metadata['calculation_method']}")
        except Exception as e:
            print(f"  💥 异常: {e}")


async def test_background_scan_120d():
    """测试120背景扫描完整数据获取"""
    print("\n=== 测试120背景扫描完整数据获取 ===")

    manager = get_manager()
    end_date = "2023-09-19"
    start_date = "2023-05-22"  # 120天前

    print(f"测试日期范围: {start_date} 到 {end_date}")

    try:
        results = await manager.batch_get_background_scan_120d_data(start_date, end_date)

        print(f"\n📊 总共获取 {len(results)} 个数据项:")

        # 统计各类数据
        forex_count = sum(1 for k in results.keys() if k.startswith('forex_'))
        bond_count = sum(1 for k in results.keys() if k.startswith('bond_'))
        stock_count = sum(1 for k in results.keys() if k.startswith('stock_'))
        commodity_count = sum(1 for k in results.keys() if k.startswith('commodity_'))

        print(f"  💱 汇率数据: {forex_count} 项")
        print(f"  🏛️ 国债数据: {bond_count} 项")
        print(f"  📈 股票数据: {stock_count} 项")
        print(f"  🥇 商品数据: {commodity_count} 项")

        # 检查关键数据
        required_items = [
            "forex_DXY", "forex_USDCNY", "forex_USDCNH",
            "bond_US10Y", "bond_CN10Y", "bond_CN10Y_CDB"
        ]

        print(f"\n🎯 关键数据项检查:")
        for item in required_items:
            if item in results:
                response = results[item]
                if response.error:
                    print(f"  ❌ {item}: {response.error}")
                else:
                    print(f"  ✅ {item}: {len(response.data) if response.data is not None else 0} 条数据")
            else:
                print(f"  ⚠️ {item}: 未找到")

    except Exception as e:
        print(f"💥 批量获取异常: {e}")


def test_yahoo_finance_support():
    """测试Yahoo Finance支持情况"""
    print("\n=== 测试Yahoo Finance支持情况 ===")

    try:
        support_status = validate_international_finance_support()

        print("📊 汇率数据支持:")
        for symbol, supported in support_status["forex_symbols"].items():
            status = "✅" if supported else "❌"
            print(f"  {status} {symbol}")

        print("\n🏛️ 国债收益率数据支持:")
        for symbol, supported in support_status["bond_yield_symbols"].items():
            status = "✅" if supported else "❌"
            print(f"  {status} {symbol}")

        overall_status = "✅" if support_status["overall_support"] else "❌"
        print(f"\n🎯 整体支持状态: {overall_status}")

    except Exception as e:
        print(f"💥 支持检查异常: {e}")


async def test_batch_yahoo_functions():
    """测试批量Yahoo Finance函数"""
    print("\n=== 测试批量Yahoo Finance函数 ===")

    end_date = "2023-09-19"
    start_date = "2023-09-01"

    print("测试批量汇率数据获取...")
    try:
        forex_results = batch_get_background_scan_forex(start_date, end_date)
        print(f"  📊 汇率数据: {len(forex_results)} 项")
        for symbol, result in forex_results.items():
            if "error" in result:
                print(f"    ❌ {symbol}: {result['error']}")
            else:
                print(f"    ✅ {symbol}: 成功")
    except Exception as e:
        print(f"  💥 汇率批量获取异常: {e}")

    print("\n测试批量国债数据获取...")
    try:
        bond_results = batch_get_background_scan_bonds(start_date, end_date)
        print(f"  🏛️ 国债数据: {len(bond_results)} 项")
        for symbol, result in bond_results.items():
            if "error" in result:
                print(f"    ❌ {symbol}: {result['error']}")
            else:
                print(f"    ✅ {symbol}: 成功")
    except Exception as e:
        print(f"  💥 国债批量获取异常: {e}")


async def main():
    """主测试函数"""
    print("🚀 开始测试国际金融数据适配器...")

    # 测试基础支持
    test_yahoo_finance_support()

    # 测试批量Yahoo函数
    await test_batch_yahoo_functions()

    # 测试数据源管理器集成
    await test_forex_data()
    await test_bond_yield_data()

    # 测试完整120背景扫描
    await test_background_scan_120d()

    print("\n🎉 测试完成!")


if __name__ == "__main__":
    asyncio.run(main())