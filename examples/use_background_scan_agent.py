#!/usr/bin/env python3
"""
BackgroundScan120Agent 使用示例
演示如何使用120日背景扫描智能代理
"""

import asyncio
import sys
import os
from datetime import datetime

# 添加项目路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))


async def basic_usage_example():
    """基本使用示例"""
    print("=== 基本使用示例 ===")
    
    try:
        from datasource.agents.background_scan import BackgroundScan120Agent, BackgroundScanConfig
        
        # 创建默认配置
        config = BackgroundScanConfig()
        
        # 创建代理实例
        agent = BackgroundScan120Agent(config)
        
        # 生成报告
        print("正在生成120日背景扫描报告...")
        report_path = await agent.generate_report("2025-09-15")
        
        print(f"报告生成成功: {report_path}")
        return True
        
    except Exception as e:
        print(f"基本使用示例失败: {e}")
        return False


async def custom_config_example():
    """自定义配置示例"""
    print("\n=== 自定义配置示例 ===")
    
    try:
        from datasource.agents.background_scan import BackgroundScan120Agent, BackgroundScanConfig
        
        # 创建自定义配置
        config = BackgroundScanConfig(
            scan_period_days=90,  # 改为90日扫描
            primary_data_source="tushare",  # AKShare已停用，统一走TuShare+MCP
            report_title="90日市场扫描报告"
        )
        
        # 自定义输出路径
        config.paths["output_dir"] = "reports/custom"
        
        # 创建代理
        agent = BackgroundScan120Agent(config)
        
        print("正在生成自定义配置的报告...")
        report_path = await agent.generate_report("2025-09-15")
        
        print(f"自定义报告生成成功: {report_path}")
        return True
        
    except Exception as e:
        print(f"自定义配置示例失败: {e}")
        return False


async def data_analysis_example():
    """数据分析示例"""
    print("\n=== 数据分析示例 ===")
    
    try:
        from datasource.agents.background_scan import BackgroundScan120Agent, BackgroundScanConfig
        
        config = BackgroundScanConfig()
        agent = BackgroundScan120Agent(config)
        
        # 仅收集和分析数据，不生成完整报告
        print("正在收集市场数据...")
        market_data = await agent.collect_market_data("2025-09-15")
        
        print("正在进行普林格分析...")
        pring_analysis = agent.analyze_pring_stage()
        
        # 显示分析结果
        print("\n--- 数据收集结果 ---")
        print(f"A股指数数据: {len(market_data['a_share_indices'])}个")
        print(f"商品数据: {len(market_data['commodities'])}个")
        print(f"汇率数据: {len(market_data['currencies'])}个")
        print(f"债券数据: {len(market_data['bonds'])}个")
        
        print("\n--- 普林格分析结果 ---")
        print(f"当前阶段: {pring_analysis.get('current_stage', 'N/A')}")
        print(f"置信度: {pring_analysis.get('confidence', 'N/A')}")
        print(f"债券信号: {pring_analysis.get('bond_signal', 'N/A')}")
        print(f"股票信号: {pring_analysis.get('stock_signal', 'N/A')}")
        print(f"商品信号: {pring_analysis.get('commodity_signal', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"数据分析示例失败: {e}")
        return False


async def batch_generation_example():
    """批量生成示例"""
    print("\n=== 批量生成示例 ===")
    
    try:
        from datasource.agents.background_scan import BackgroundScan120Agent, BackgroundScanConfig
        
        config = BackgroundScanConfig()
        agent = BackgroundScan120Agent(config)
        
        # 生成多个日期的报告
        dates = ["2025-09-13", "2025-09-14", "2025-09-15"]
        
        for date in dates:
            print(f"正在生成 {date} 的报告...")
            report_path = await agent.generate_report(date)
            print(f"  -> {report_path}")
        
        print("批量生成完成")
        return True
        
    except Exception as e:
        print(f"批量生成示例失败: {e}")
        return False


async def main():
    """主函数"""
    print("BackgroundScan120Agent 使用示例")
    print("=" * 50)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 运行所有示例
    examples = [
        ("基本使用", basic_usage_example),
        ("自定义配置", custom_config_example),
        ("数据分析", data_analysis_example),
        ("批量生成", batch_generation_example)
    ]
    
    results = []
    
    for example_name, example_func in examples:
        print(f"\n正在运行: {example_name}")
        try:
            result = await example_func()
            results.append((example_name, result))
        except Exception as e:
            print(f"示例 {example_name} 执行异常: {e}")
            results.append((example_name, False))
    
    # 结果汇总
    print("\n" + "=" * 50)
    print("示例执行结果汇总")
    print("=" * 50)
    
    success_count = 0
    for example_name, result in results:
        status = "成功" if result else "失败"
        print(f"{example_name}: {status}")
        if result:
            success_count += 1
    
    print(f"\n总计: {success_count}/{len(results)} 个示例执行成功")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return 0 if success_count == len(results) else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n示例执行被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n示例执行异常: {e}")
        sys.exit(1)
