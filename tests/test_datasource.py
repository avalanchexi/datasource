#!/usr/bin/env python3
"""
数据源集成测试脚本
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta
from loguru import logger

# 添加项目根路径下的 src 目录
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

from datasource import initialize_default_manager, DataSourceType


async def test_data_sources():
    """测试数据源集成功能"""
    logger.info("开始测试数据源集成功能...")
    
    try:
        # 初始化管理器
        manager = await initialize_default_manager()
        logger.info(f"管理器状态: {manager.get_status()}")
        
        # 检查数据源可用性
        availability = await manager.check_availability()
        logger.info(f"数据源可用性: {availability}")
        
        # 如果没有可用的数据源，退出测试
        if not any(availability.values()):
            logger.error("没有可用的数据源，请检查网络连接和配置")
            return False
        
        # 测试股票基本信息
        logger.info("\n=== 测试股票基本信息 ===")
        basic_response = await manager.get_stock_basic()
        if basic_response.error:
            logger.error(f"获取股票基本信息失败: {basic_response.error}")
        else:
            logger.info(f"成功获取股票基本信息，数据源: {basic_response.source}")
            if basic_response.data is not None:
                logger.info(f"数据行数: {len(basic_response.data)}")
                logger.info(f"数据列: {list(basic_response.data.columns)}")
                logger.info(f"前5行数据:\n{basic_response.data.head()}")
        
        # 测试股票日线数据
        logger.info("\n=== 测试股票日线数据 ===")
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        daily_response = await manager.get_stock_daily("000001", start_date, end_date)
        if daily_response.error:
            logger.error(f"获取股票日线数据失败: {daily_response.error}")
        else:
            logger.info(f"成功获取股票日线数据，数据源: {daily_response.source}")
            if daily_response.data is not None:
                logger.info(f"数据行数: {len(daily_response.data)}")
                logger.info(f"数据列: {list(daily_response.data.columns)}")
                logger.info(f"最新数据:\n{daily_response.data.head()}")
        
        # 测试股票实时数据
        logger.info("\n=== 测试股票实时数据 ===")
        realtime_response = await manager.get_stock_realtime(["000001", "000002", "000858"])
        if realtime_response.error:
            logger.error(f"获取股票实时数据失败: {realtime_response.error}")
        else:
            logger.info(f"成功获取股票实时数据，数据源: {realtime_response.source}")
            if realtime_response.data is not None:
                logger.info(f"数据行数: {len(realtime_response.data)}")
                logger.info(f"数据列: {list(realtime_response.data.columns)}")
                logger.info(f"实时数据:\n{realtime_response.data.head()}")
        
        # 测试指数数据
        logger.info("\n=== 测试指数日线数据 ===")
        index_response = await manager.get_index_daily("000001", start_date, end_date)
        if index_response.error:
            logger.error(f"获取指数数据失败: {index_response.error}")
        else:
            logger.info(f"成功获取指数数据，数据源: {index_response.source}")
            if index_response.data is not None:
                logger.info(f"数据行数: {len(index_response.data)}")
                logger.info(f"数据列: {list(index_response.data.columns)}")
                logger.info(f"指数数据:\n{index_response.data.head()}")
        
        # 测试财务数据
        logger.info("\n=== 测试财务数据 ===")
        financial_response = await manager.get_financial_data("000001")
        if financial_response.error:
            logger.error(f"获取财务数据失败: {financial_response.error}")
        else:
            logger.info(f"成功获取财务数据，数据源: {financial_response.source}")
            if financial_response.data is not None:
                logger.info(f"数据行数: {len(financial_response.data)}")
                logger.info(f"数据列: {list(financial_response.data.columns)}")
                logger.info(f"财务数据:\n{financial_response.data.head()}")
        
        # 测试批量获取
        logger.info("\n=== 测试批量获取股票数据 ===")
        batch_results = await manager.batch_get_stock_daily(
            ["000001", "000002"], start_date, end_date
        )
        
        for symbol, response in batch_results.items():
            if response.error:
                logger.error(f"股票 {symbol} 数据获取失败: {response.error}")
            else:
                logger.info(f"股票 {symbol} 数据获取成功，数据源: {response.source}")
                if response.data is not None:
                    logger.info(f"股票 {symbol} 数据行数: {len(response.data)}")
        
        logger.info("\n=== 数据源集成测试完成 ===")
        return True
        
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_individual_sources():
    """测试单个数据源"""
    logger.info("\n=== 测试单个数据源 ===")
    
    from datasource.adapters.tushare_adapter import TuShareAdapter

    # 测试 TuShare
    logger.info("测试 TuShare 适配器...")
    tushare = TuShareAdapter()
    tushare_available = await tushare.is_available()
    logger.info(f"TuShare 可用性: {tushare_available}")
    
    if tushare_available:
        response = await tushare.get_stock_basic()
        if response.error:
            logger.error(f"TuShare 测试失败: {response.error}")
        else:
            logger.info(f"TuShare 测试成功，获取到 {len(response.data) if response.data is not None else 0} 条数据")


async def main():
    """主函数"""
    logger.info("开始数据源集成测试")
    
    # 配置日志
    logger.add("test_datasource.log", rotation="1 day", retention="7 days", level="DEBUG")
    
    # 测试单个数据源
    await test_individual_sources()
    
    # 测试集成功能
    success = await test_data_sources()
    
    if success:
        logger.info("所有测试通过！")
        return 0
    else:
        logger.error("测试失败！")
        return 1


if __name__ == "__main__":
    # 运行测试
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
