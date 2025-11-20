#!/usr/bin/env python3
"""
简化的数据源测试脚本
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

# 添加项目根路径下的 src 目录
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))


class SimpleLogger:
    """简化的日志器"""
    @staticmethod
    def info(msg):
        print(f"[INFO] {msg}")
    
    @staticmethod
    def error(msg):
        print(f"[ERROR] {msg}")
    
    @staticmethod
    def warning(msg):
        print(f"[WARNING] {msg}")
    
    @staticmethod
    def debug(msg):
        print(f"[DEBUG] {msg}")


# 替换 loguru
import datasource.adapters.akshare_adapter as akshare_module
import datasource.adapters.tushare_adapter as tushare_module
import datasource.manager as manager_module

# 用简化的日志器替换
logger = SimpleLogger()
akshare_module.logger = logger
tushare_module.logger = logger
manager_module.logger = logger


async def simple_test():
    """简单测试"""
    try:
        print("开始数据源测试...")
        
        # 测试 AKShare
        print("\n=== 测试 AKShare ===")
        from datasource.adapters.akshare_adapter import AKShareAdapter
        
        akshare = AKShareAdapter()
        available = await akshare.is_available()
        print(f"AKShare 可用性: {available}")
        
        if available:
            # 测试获取股票基本信息
            response = await akshare.get_stock_basic()
            if response.error:
                print(f"获取股票基本信息失败: {response.error}")
            else:
                print(f"成功获取股票基本信息，数据行数: {len(response.data) if response.data is not None else 0}")
        
        # 测试 TuShare
        print("\n=== 测试 TuShare ===")
        from datasource.adapters.tushare_adapter import TuShareAdapter
        
        tushare = TuShareAdapter()
        available = await tushare.is_available()
        print(f"TuShare 可用性: {available}")
        
        if available:
            # 测试获取股票基本信息
            response = await tushare.get_stock_basic()
            if response.error:
                print(f"获取股票基本信息失败: {response.error}")
            else:
                print(f"成功获取股票基本信息，数据行数: {len(response.data) if response.data is not None else 0}")
        
        # 测试管理器
        print("\n=== 测试管理器 ===")
        from datasource import get_manager
        
        manager = get_manager()
        status = manager.get_status()
        print(f"管理器状态: {status}")
        
        # 检查可用性
        availability = await manager.check_availability()
        print(f"数据源可用性: {availability}")
        
        # 如果有可用的数据源，测试获取数据
        if any(availability.values()):
            print("\n测试获取股票基本信息...")
            response = await manager.get_stock_basic()
            if response.error:
                print(f"获取失败: {response.error}")
            else:
                print(f"获取成功，数据源: {response.source}")
                if response.data is not None:
                    print(f"数据行数: {len(response.data)}")
                    print(f"数据列: {list(response.data.columns)[:5]}...")  # 只显示前5列
            
            # 测试股票日线数据
            print("\n测试获取股票日线数据...")
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            
            response = await manager.get_stock_daily("000001", start_date, end_date)
            if response.error:
                print(f"获取失败: {response.error}")
            else:
                print(f"获取成功，数据源: {response.source}")
                if response.data is not None:
                    print(f"数据行数: {len(response.data)}")
                    print(f"数据列: {list(response.data.columns)[:5]}...")
        
        print("\n测试完成！")
        return True
        
    except Exception as e:
        print(f"测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(simple_test())
    if success:
        print("测试通过！")
    else:
        print("测试失败！")
