#!/usr/bin/env python3
"""
运行 N/A 值填充和报告生成
"""
import asyncio
import sys
import os
from datetime import datetime
import argparse

# 添加项目根路径下的 src 目录
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))


async def generate_reports(days: int = 30, report_type: str = "both"):
    """
    生成报告
    
    Args:
        days: 数据天数
        report_type: 报告类型 ("background", "daily", "both")
    """
    print(f"开始生成报告（{days}天数据）...")
    
    try:
        from datasource.generators.report_generator import ReportGenerator
        
        generator = ReportGenerator()
        
        if report_type == "background":
            print("生成背景扫描报告...")
            report = await generator.generate_background_scan_report(days)
            print(f"报告已生成，长度: {len(report)} 字符")
            
        elif report_type == "daily":
            print("生成日表报告...")
            report = await generator.generate_daily_table_report(days)
            print(f"报告已生成，长度: {len(report)} 字符")
            
        elif report_type == "both":
            print("生成两个报告...")
            reports = await generator.generate_both_reports(days)
            
            for name, content in reports.items():
                if content and not content.startswith("失败"):
                    print(f"✓ {name} 报告生成成功，长度: {len(content)} 字符")
                else:
                    print(f"✗ {name} 报告生成失败: {content}")
        
        print("\n报告生成完成！")
        print(f"输出目录: {os.path.join(os.getcwd(), 'reports')}")
        
    except Exception as e:
        print(f"生成报告时发生错误: {e}")
        import traceback
        traceback.print_exc()


async def check_data_availability():
    """检查数据可用性"""
    print("检查数据源可用性...")
    
    try:
        from datasource import get_manager
        
        manager = get_manager()
        availability = await manager.check_availability()
        
        print("数据源可用性:")
        for source, status in availability.items():
            status_text = "✓ 可用" if status else "✗ 不可用"
            print(f"  {source}: {status_text}")
        
        available_count = sum(availability.values())
        total_count = len(availability)
        
        print(f"\n可用数据源: {available_count}/{total_count}")
        
        if available_count > 0:
            print("✓ 至少有一个数据源可用，可以继续")
            return True
        else:
            print("✗ 没有可用的数据源")
            return False
            
    except Exception as e:
        print(f"检查数据可用性时发生错误: {e}")
        return False


async def show_na_filling_demo():
    """展示 N/A 值填充效果"""
    print("演示 N/A 值填充效果...")
    
    try:
        from datasource.engines.data_engine import MarketDataEngine
        
        engine = MarketDataEngine()
        
        # 获取格式化数据
        data = await engine.get_formatted_market_data(days=30)
        
        print("\n=== A股指数数据填充效果 ===")
        if 'a_share_indices' in data:
            for name, info in data['a_share_indices'].items():
                print(f"\n{name}:")
                print(f"  近30日涨跌: {info.get('change_30d', 'N/A')}")
                print(f"  MA50位置: {info.get('above_ma50', 'N/A')}")
                print(f"  MA200位置: {info.get('above_ma200', 'N/A')}")
                print(f"  30日波动率: {info.get('volatility_30d', 'N/A')}")
                print(f"  趋势标签: {info.get('trend_label', 'N/A')}")
        
        print("\n=== 普林格六阶段分析 ===")
        if 'pring_analysis' in data:
            pring = data['pring_analysis']
            print(f"当前阶段: {pring.get('current_stage', 'N/A')}")
            print(f"置信度: {pring.get('confidence', 'N/A')}")
            print(f"债券信号: {pring.get('bond_signal', 'N/A')}")
            print(f"股票信号: {pring.get('stock_signal', 'N/A')}")
            print(f"商品信号: {pring.get('commodity_signal', 'N/A')}")
        
        print("\n=== 资金流向数据 ===")
        if 'capital_flows' in data:
            flows = data['capital_flows']
            print(f"北向资金(5日): {flows.get('northbound_5d', 'N/A')}")
            print(f"北向资金(30日): {flows.get('northbound_30d', 'N/A')}")
            print(f"南向资金(5日): {flows.get('southbound_5d', 'N/A')}")
            print(f"南向资金(30日): {flows.get('southbound_30d', 'N/A')}")
        
        print("\n✓ N/A 值填充演示完成")
        
    except Exception as e:
        print(f"N/A填充演示失败: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='N/A值填充和报告生成工具')
    parser.add_argument('--days', type=int, default=30, help='数据获取天数（默认30天）')
    parser.add_argument('--type', choices=['background', 'daily', 'both'], default='both', 
                       help='报告类型（默认生成两个报告）')
    parser.add_argument('--check', action='store_true', help='只检查数据源可用性')
    parser.add_argument('--demo', action='store_true', help='演示N/A值填充效果')
    
    args = parser.parse_args()
    
    print("🚀 N/A值填充和报告生成系统")
    print("=" * 40)
    
    async def run():
        # 检查数据源可用性
        if not await check_data_availability():
            print("⚠️  数据源不可用，但仍可继续（会使用模拟数据）")
        
        if args.check:
            return
        
        if args.demo:
            await show_na_filling_demo()
            return
        
        # 生成报告
        await generate_reports(args.days, args.type)
    
    try:
        asyncio.run(run())
        print("\n✅ 操作完成")
    except KeyboardInterrupt:
        print("\n操作被用户中断")
    except Exception as e:
        print(f"\n❌ 操作失败: {e}")


if __name__ == "__main__":
    main()
