#!/usr/bin/env python3
"""
120日背景扫描代理 - 主执行脚本
基于BackgroundScan120Agent的自动化报告生成工具
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到Python路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='120日背景扫描报告生成器')
    parser.add_argument('--date', type=str, default=None, 
                       help='结束日期 (YYYY-MM-DD格式)，默认为今天')
    parser.add_argument('--output', type=str, default=None,
                       help='输出文件路径，默认为reports目录')
    parser.add_argument('--symbols', type=str, default=None,
                       help='股票代码列表，用逗号分隔')
    parser.add_argument('--verbose', action='store_true',
                       help='显示详细信息')
    
    args = parser.parse_args()
    
    print("🚀 120日背景扫描代理启动")
    print("=" * 50)
    
    try:
        # 导入代理类
        from datasource.agents.background_scan import BackgroundScan120Agent, BackgroundScanConfig
        
        # 创建配置和代理实例
        config = BackgroundScanConfig()
        agent = BackgroundScan120Agent(config)
        
        # 生成报告
        print(f"正在生成报告 (目标日期: {args.date or '今天'})...")
        report_path = await agent.generate_report(end_date=args.date)
        
        print(f"✅ 报告生成成功!")
        print(f"📄 文件位置: {report_path}")
        
        return 0
        
    except Exception as e:
        print(f"❌ 报告生成失败: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n操作被用户中断")
        sys.exit(1)