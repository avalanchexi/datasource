#!/usr/bin/env python3
"""
数据源使用示例
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

# 添加项目根路径下的 src 目录
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource import get_manager, initialize_default_manager, DataSourceType


async def example_basic_usage():
    """基本使用示例"""
    print("=== 基本使用示例 ===")
    
    # 获取管理器实例
    manager = get_manager()
    
    # 检查状态
    status = manager.get_status()
    print(f"管理器状态: {status}")
    
    # 检查数据源可用性
    availability = await manager.check_availability()
    print(f"数据源可用性: {availability}")
    
    # 获取股票基本信息
    print("\n获取股票基本信息...")
    basic_info = await manager.get_stock_basic()
    if basic_info.error:
        print(f"错误: {basic_info.error}")
    else:
        print(f"成功从 {basic_info.source} 获取数据")
        print(f"数据行数: {len(basic_info.data)}")


async def example_stock_data():
    """股票数据获取示例"""
    print("\n=== 股票数据获取示例 ===")
    
    manager = await initialize_default_manager()
    
    # 设置日期范围
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    # 获取平安银行(000001)的日线数据
    print(f"\n获取平安银行日线数据 ({start_date} 到 {end_date})")
    daily_data = await manager.get_stock_daily("000001", start_date, end_date)
    
    if daily_data.error:
        print(f"错误: {daily_data.error}")
    else:
        print(f"成功从 {daily_data.source} 获取数据")
        print(f"数据行数: {len(daily_data.data)}")
        print("\n最新几日数据:")
        print(daily_data.data.head())
    
    # 获取实时数据
    print("\n获取股票实时数据...")
    realtime_data = await manager.get_stock_realtime(["000001", "000002", "000858"])
    
    if realtime_data.error:
        print(f"错误: {realtime_data.error}")
    else:
        print(f"成功从 {realtime_data.source} 获取数据")
        print(f"数据行数: {len(realtime_data.data)}")
        print("\n实时数据:")
        print(realtime_data.data.head())


async def example_index_data():
    """指数数据获取示例"""
    print("\n=== 指数数据获取示例 ===")
    
    manager = get_manager()
    
    # 设置日期范围
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    # 获取上证指数数据
    print(f"\n获取上证指数数据 ({start_date} 到 {end_date})")
    index_data = await manager.get_index_daily("000001", start_date, end_date)
    
    if index_data.error:
        print(f"错误: {index_data.error}")
    else:
        print(f"成功从 {index_data.source} 获取数据")
        print(f"数据行数: {len(index_data.data)}")
        print("\n最新指数数据:")
        print(index_data.data.head())


async def example_batch_operations():
    """批量操作示例"""
    print("\n=== 批量操作示例 ===")
    
    manager = get_manager()
    
    # 设置日期范围
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    # 批量获取多只股票的数据
    symbols = ["000001", "000002", "000858", "600000", "600036"]
    print(f"\n批量获取股票数据: {symbols}")
    
    batch_results = await manager.batch_get_stock_daily(symbols, start_date, end_date)
    
    for symbol, response in batch_results.items():
        if response.error:
            print(f"股票 {symbol}: 获取失败 - {response.error}")
        else:
            print(f"股票 {symbol}: 获取成功，{len(response.data)} 条数据，来源 {response.source}")


async def example_custom_configuration():
    """自定义配置示例"""
    print("\n=== 自定义配置示例 ===")
    
    # 创建自定义管理器
    from datasource import DataSourceManager
    custom_manager = DataSourceManager()
    
    # 添加数据源with自定义配置
    tushare_config = {
        "rate_limit": 3,
        "cache_ttl": 300,
        "timeout": 30
    }
    
    custom_manager.add_data_source(DataSourceType.TUSHARE, tushare_config)
    
    # 设置 TuShare 为主数据源
    custom_manager.set_primary_source("tushare")
    
    print("自定义管理器配置完成")
    print(f"状态: {custom_manager.get_status()}")
    
    # 测试可用性
    availability = await custom_manager.check_availability()
    print(f"数据源可用性: {availability}")


async def example_error_handling():
    """错误处理示例"""
    print("\n=== 错误处理示例 ===")
    
    manager = get_manager()
    
    # 尝试获取不存在的股票数据
    print("尝试获取无效股票代码的数据...")
    invalid_response = await manager.get_stock_daily("INVALID", "2023-01-01", "2023-01-02")
    
    if invalid_response.error:
        print(f"预期的错误: {invalid_response.error}")
        print(f"尝试的数据源: {invalid_response.metadata.get('attempted_sources', [])}")
    
    # 尝试获取过久远的数据
    print("\n尝试获取很久以前的数据...")
    old_response = await manager.get_stock_daily("000001", "1990-01-01", "1990-01-02")
    
    if old_response.error:
        print(f"可能的错误: {old_response.error}")
    else:
        print(f"成功获取历史数据: {len(old_response.data)} 条记录")


async def main():
    """主函数"""
    print("数据源使用示例")
    print("=" * 50)
    
    try:
        # 运行所有示例
        await example_basic_usage()
        await example_stock_data()
        await example_index_data()
        await example_batch_operations()
        await example_custom_configuration()
        await example_error_handling()
        
        print("\n" + "=" * 50)
        print("所有示例执行完成！")
        
    except Exception as e:
        print(f"示例执行过程中发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
