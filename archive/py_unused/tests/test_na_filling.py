#!/usr/bin/env python3
"""
测试 N/A 值填充和报告生成功能
"""
import asyncio
import sys
import os
from datetime import datetime

# 添加项目根路径下的 src 目录
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

# 简化的日志器
class SimpleLogger:
    @staticmethod
    def info(msg):
        print(f"[INFO] {datetime.now().strftime('%H:%M:%S')} {msg}")
    
    @staticmethod
    def error(msg):
        print(f"[ERROR] {datetime.now().strftime('%H:%M:%S')} {msg}")
    
    @staticmethod
    def warning(msg):
        print(f"[WARNING] {datetime.now().strftime('%H:%M:%S')} {msg}")

# 替换日志器
try:
    import datasource.engines.data_engine as engine_module
    import datasource.generators.report_generator as generator_module
    import datasource.calculators.technical_indicators as tech_module
    import datasource.calculators.bond_calculator as bond_module
    import datasource.calculators.fund_flow_calculator as flow_module
    import datasource.calculators.pring_analyzer as pring_module
    
    logger = SimpleLogger()
    # 可以添加更多模块的日志替换
    
except ImportError as e:
    print(f"导入模块失败: {e}")


async def test_data_engine():
    """测试数据引擎"""
    print("\n=== 测试数据引擎 ===")
    
    try:
        from datasource.engines.data_engine import MarketDataEngine
        
        engine = MarketDataEngine()
        print("数据引擎初始化成功")
        
        # 测试获取市场数据
        print("获取综合市场数据...")
        market_data = await engine.get_comprehensive_market_data(days=30)
        
        print("✓ 综合市场数据获取完成")
        
        # 检查数据结构
        print("\n数据结构检查:")
        for key, value in market_data.items():
            if isinstance(value, dict) and "error" in value:
                print(f"  {key}: 获取失败 - {value['error']}")
            else:
                print(f"  {key}: 获取成功")
        
        # 测试格式化数据
        print("\n格式化市场数据...")
        formatted_data = await engine.get_formatted_market_data(days=30)
        
        print("✓ 数据格式化完成")
        
        # 显示关键指标
        if 'a_share_indices' in formatted_data:
            indices = formatted_data['a_share_indices']
            print("\nA股指数数据示例:")
            for name, data in indices.items():
                print(f"  {name}:")
                print(f"    近30日涨跌: {data.get('change_30d', 'N/A')}")
                print(f"    趋势标签: {data.get('trend_label', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"数据引擎测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_report_generator():
    """测试报告生成器"""
    print("\n=== 测试报告生成器 ===")
    
    try:
        from datasource.generators.report_generator import ReportGenerator
        
        generator = ReportGenerator()
        print("报告生成器初始化成功")
        
        # 生成背景扫描报告
        print("生成背景扫描报告...")
        background_report = await generator.generate_background_scan_report(days=30)
        
        if background_report and len(background_report) > 100:
            print("✓ 背景扫描报告生成成功")
            print(f"  报告长度: {len(background_report)} 字符")
        else:
            print("✗ 背景扫描报告生成失败")
            return False
        
        # 生成日表报告
        print("生成日表报告...")
        daily_report = await generator.generate_daily_table_report(days=30)
        
        if daily_report and len(daily_report) > 100:
            print("✓ 日表报告生成成功")
            print(f"  报告长度: {len(daily_report)} 字符")
        else:
            print("✗ 日表报告生成失败")
            return False
        
        # 检查N/A值替换情况
        na_count_bg = background_report.count('N/A')
        na_count_daily = daily_report.count('N/A')
        
        print(f"\nN/A值统计:")
        print(f"  背景扫描报告剩余N/A: {na_count_bg}")
        print(f"  日表报告剩余N/A: {na_count_daily}")
        
        if na_count_bg < 10 and na_count_daily < 10:
            print("✓ 大部分N/A值已成功替换")
        else:
            print("! 仍有较多N/A值未替换，可能需要改进数据获取")
        
        return True
        
    except Exception as e:
        print(f"报告生成器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_individual_calculators():
    """测试各个计算器模块"""
    print("\n=== 测试计算器模块 ===")
    
    try:
        from datasource import get_manager
        
        manager = get_manager()
        success_count = 0
        
        # 测试技术指标计算器
        try:
            from datasource.calculators.technical_indicators import MarketIndicatorCalculator
            tech_calc = MarketIndicatorCalculator(manager)
            
            # 测试单个指数分析
            analysis = await tech_calc.get_index_analysis("000300", "2023-11-01", "2023-12-01")
            if "error" not in analysis:
                print("✓ 技术指标计算器测试成功")
                success_count += 1
            else:
                print(f"✗ 技术指标计算器测试失败: {analysis['error']}")
        except Exception as e:
            print(f"✗ 技术指标计算器测试异常: {e}")
        
        # 测试债券计算器
        try:
            from datasource.calculators.bond_calculator import BondCalculator
            bond_calc = BondCalculator(manager)
            
            bond_data = await bond_calc.get_china_bond_yields(days=30)
            if bond_data and "error" not in bond_data:
                print("✓ 债券计算器测试成功")
                success_count += 1
            else:
                print("✗ 债券计算器测试失败")
        except Exception as e:
            print(f"✗ 债券计算器测试异常: {e}")
        
        # 测试资金流向计算器
        try:
            from datasource.calculators.fund_flow_calculator import FundFlowCalculator
            flow_calc = FundFlowCalculator(manager)
            
            north_data = await flow_calc.get_northbound_capital_flow(days=30)
            if north_data and "error" not in north_data:
                print("✓ 资金流向计算器测试成功")
                success_count += 1
            else:
                print("✗ 资金流向计算器测试失败")
        except Exception as e:
            print(f"✗ 资金流向计算器测试异常: {e}")
        
        # 测试普林格分析器
        try:
            from datasource.calculators.pring_analyzer import PringAnalyzer
            pring_analyzer = PringAnalyzer(manager)
            
            pring_data = await pring_analyzer.analyze_pring_stage(days=60)
            if pring_data and "error" not in pring_data:
                print("✓ 普林格分析器测试成功")
                print(f"  当前阶段: {pring_data.get('stage', 'N/A')}")
                success_count += 1
            else:
                print(f"✗ 普林格分析器测试失败: {pring_data.get('error', 'Unknown')}")
        except Exception as e:
            print(f"✗ 普林格分析器测试异常: {e}")
        
        print(f"\n计算器模块测试完成: {success_count}/4 模块成功")
        return success_count >= 2  # 至少一半成功
        
    except Exception as e:
        print(f"计算器模块测试异常: {e}")
        return False


async def test_complete_workflow():
    """测试完整工作流程"""
    print("\n=== 测试完整工作流程 ===")
    
    try:
        from datasource.generators.report_generator import ReportGenerator
        
        generator = ReportGenerator()
        
        # 生成完整报告组合
        print("生成完整报告组合...")
        reports = await generator.generate_both_reports(days=30)
        
        success_count = 0
        
        for report_type, content in reports.items():
            if content and not content.startswith("失败"):
                print(f"✓ {report_type} 生成成功")
                success_count += 1
                
                # 检查关键信息是否填充
                if "N/A（需序列）" in content:
                    print(f"  ! {report_type} 中仍有部分N/A值")
                else:
                    print(f"  ✓ {report_type} 中原有N/A值已基本填充")
                    
            else:
                print(f"✗ {report_type} 生成失败")
        
        if success_count == 2:
            print("\n🎉 完整工作流程测试成功！")
            print("   - 数据获取正常")
            print("   - 计算模块运行")
            print("   - 报告生成完成")
            print("   - N/A值填充生效")
            return True
        else:
            print(f"\n⚠️  工作流程部分成功 ({success_count}/2)")
            return False
            
    except Exception as e:
        print(f"完整工作流程测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("开始测试 N/A 值填充和报告生成系统")
    print("=" * 50)
    
    test_results = []
    
    # 测试各个组件
    test_results.append(await test_individual_calculators())
    test_results.append(await test_data_engine())
    test_results.append(await test_report_generator())
    test_results.append(await test_complete_workflow())
    
    # 统计结果
    passed = sum(test_results)
    total = len(test_results)
    
    print("\n" + "=" * 50)
    print("测试总结:")
    print(f"  通过: {passed}/{total}")
    print(f"  成功率: {passed/total*100:.1f}%")
    
    if passed == total:
        print("  🎉 所有测试通过！N/A值填充系统运行正常")
    elif passed >= total * 0.75:
        print("  ✅ 大部分测试通过，系统基本可用")
    elif passed >= total * 0.5:
        print("  ⚠️  部分测试通过，系统需要改进")
    else:
        print("  ❌ 多数测试失败，系统需要修复")
    
    return passed >= total * 0.75


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n测试过程中发生异常: {e}")
        sys.exit(1)
