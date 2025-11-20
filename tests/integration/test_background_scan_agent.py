#!/usr/bin/env python3
"""
BackgroundScan120Agent 测试脚本
验证子代理的基本功能
"""

import asyncio
import sys
import os
from datetime import datetime

# 添加项目根目录到Python路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))


async def test_basic_functionality():
    """测试基本功能"""
    print("=" * 60)
    print("🧪 BackgroundScan120Agent 基本功能测试")
    print("=" * 60)
    
    try:
        # 导入代理类
        from datasource.agents.background_scan import BackgroundScan120Agent, BackgroundScanConfig
        
        print("✅ 成功导入BackgroundScan120Agent")
        
        # 创建配置
        config = BackgroundScanConfig()
        print(f"✅ 配置创建成功: {config.scan_period_days}天扫描窗口")
        
        # 创建代理实例
        agent = BackgroundScan120Agent(config)
        print("✅ 代理实例创建成功")
        
        # 测试配置功能
        start_date, end_date = config.get_date_range("2025-09-15")
        print(f"✅ 日期范围计算: {start_date} 至 {end_date}")
        
        # 测试符号列表
        symbols = config.get_all_symbols()
        print(f"✅ 标的列表: {len(symbols)}个股票代码")
        
        # 测试文件名生成
        filename = config.get_output_filename("2025-09-15")
        print(f"✅ 输出文件名: {filename}")
        
        return True
        
    except Exception as e:
        print(f"❌ 基本功能测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_data_collection():
    """测试数据收集功能"""
    print("\n" + "=" * 60)
    print("🧪 数据收集功能测试")
    print("=" * 60)
    
    try:
        from datasource.agents.background_scan import BackgroundScan120Agent, BackgroundScanConfig
        
        config = BackgroundScanConfig()
        agent = BackgroundScan120Agent(config)
        
        # 模拟数据收集
        print("正在测试数据收集...")
        market_data = await agent.collect_market_data("2025-09-15")
        
        print("✅ 数据收集成功")
        print(f"- A股指数: {len(market_data['a_share_indices'])}个")
        print(f"- 商品: {len(market_data['commodities'])}个")
        print(f"- 汇率: {len(market_data['currencies'])}个")
        print(f"- 债券: {len(market_data['bonds'])}个")
        
        # 检查数据内容
        for name, data in list(market_data['a_share_indices'].items())[:2]:
            print(f"- {name}: {data.get('trend_label', 'N/A')}趋势")
        
        return True
        
    except Exception as e:
        print(f"❌ 数据收集测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_pring_analysis():
    """测试普林格分析功能"""
    print("\n" + "=" * 60)
    print("🧪 普林格分析功能测试")
    print("=" * 60)
    
    try:
        from datasource.agents.background_scan import BackgroundScan120Agent, BackgroundScanConfig
        
        config = BackgroundScanConfig()
        agent = BackgroundScan120Agent(config)
        
        # 先收集数据
        await agent.collect_market_data("2025-09-15")
        
        # 测试普林格分析
        print("正在测试普林格分析...")
        pring_result = agent.analyze_pring_stage()
        
        print("✅ 普林格分析完成")
        print(f"- 当前阶段: {pring_result.get('current_stage', 'N/A')}")
        print(f"- 置信度: {pring_result.get('confidence', 'N/A')}")
        print(f"- 债券信号: {pring_result.get('bond_signal', 'N/A')}")
        print(f"- 股票信号: {pring_result.get('stock_signal', 'N/A')}")
        print(f"- 商品信号: {pring_result.get('commodity_signal', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"❌ 普林格分析测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_report_generation():
    """测试报告生成功能"""
    print("\n" + "=" * 60)
    print("🧪 报告生成功能测试")
    print("=" * 60)
    
    try:
        from datasource.agents.background_scan import BackgroundScan120Agent, BackgroundScanConfig
        
        config = BackgroundScanConfig()
        agent = BackgroundScan120Agent(config)
        
        print("正在测试完整报告生成...")
        report_path = await agent.generate_report("2025-09-15")
        
        print("✅ 报告生成成功")
        print(f"- 文件路径: {report_path}")
        
        # 检查文件是否存在
        if os.path.exists(report_path):
            file_size = os.path.getsize(report_path)
            print(f"- 文件大小: {file_size} 字节")
            
            # 读取前几行检查内容
            with open(report_path, 'r', encoding='utf-8') as f:
                first_lines = [f.readline().strip() for _ in range(3)]
            print(f"- 文件开头: {first_lines[0]}")
        else:
            print("❌ 报告文件未生成")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ 报告生成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 运行所有测试
    tests = [
        ("基本功能", test_basic_functionality),
        ("数据收集", test_data_collection),
        ("普林格分析", test_pring_analysis),
        ("报告生成", test_report_generation)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n正在运行: {test_name}测试...")
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"测试 {test_name} 异常: {e}")
            results.append((test_name, False))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("🎯 测试结果汇总")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\n总计: {passed}/{total} 个测试通过")
    
    if passed == total:
        print("🎉 所有测试通过! BackgroundScan120Agent 功能正常")
        return 0
    else:
        print("⚠️  部分测试失败，请检查具体错误信息")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        print(f"\n结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n测试异常退出: {e}")
        sys.exit(1)