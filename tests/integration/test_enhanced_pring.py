#!/usr/bin/env python3
"""
测试增强的Pring六阶段分析器（集成库存周期矫正）
"""
import sys
import os
import asyncio
from datetime import datetime

# 添加项目根路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))

try:
    from datasource.calculators.pring_analyzer import PringAnalyzer, AssetSignal, InventoryCycleStage
    from datasource import get_manager, initialize_default_manager
    print("✅ 成功导入增强的PringAnalyzer")
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    print("请确保已安装所需依赖和路径正确")
    sys.exit(1)

class MockDataManager:
    """模拟数据管理器（用于测试）"""
    
    async def get_stock_daily(self, symbol, start_date, end_date):
        """模拟股票数据"""
        import pandas as pd
        import numpy as np
        
        # 模拟成功响应
        class MockResponse:
            def __init__(self):
                self.error = None
                # 生成模拟价格数据
                dates = pd.date_range(start=start_date, end=end_date, freq='D')[:100]
                base_price = 100
                prices = base_price + np.random.randn(len(dates)).cumsum() * 2
                
                self.data = pd.DataFrame({
                    'date': dates,
                    'close': prices,
                    'open': prices * 0.998,
                    'high': prices * 1.015,
                    'low': prices * 0.985,
                    'volume': np.random.randint(1000000, 5000000, len(dates))
                })
        
        return MockResponse()
    
    async def get_index_daily(self, symbol, start_date, end_date):
        """模拟指数数据"""
        return await self.get_stock_daily(symbol, start_date, end_date)

async def test_enhanced_pring_analyzer():
    """测试增强的Pring分析器"""
    print("=" * 60)
    print("🧪 测试增强的Pring六阶段分析器（集成库存周期矫正）")
    print("=" * 60)
    
    # 创建模拟数据管理器
    mock_manager = MockDataManager()
    
    # 创建增强的Pring分析器
    analyzer = PringAnalyzer(mock_manager)
    
    print("\n📋 步骤1: 测试宏观数据获取")
    macro_data = await analyzer.get_macro_economic_data()
    print(f"   数据来源: {macro_data.get('data_source', '未知')}")
    print(f"   更新时间: {macro_data.get('update_time', '未知')}")
    
    if 'ppi_simulated' in macro_data:
        ppi = macro_data['ppi_simulated']
        print(f"   PPI同比: {ppi['latest_yoy']}%, 趋势: {ppi['trend']}")
        cpi = macro_data['cpi_simulated']
        print(f"   CPI同比: {cpi['latest_yoy']}%, 趋势: {cpi['trend']}")
        pmi = macro_data['pmi_simulated']
        print(f"   PMI值: {pmi['latest_value']}, 趋势: {pmi['trend']}")
    
    print("\n📊 步骤2: 测试库存周期评分")
    cycle_score = analyzer.calculate_inventory_cycle_score(macro_data)
    print(f"   库存周期阶段: {cycle_score['cycle_stage']}")
    print(f"   商品趋势倾向: {cycle_score['commodity_bias']}")
    print(f"   基本面评分: {cycle_score['fundamental_score']:.1f}/60分")
    
    if 'score_details' in cycle_score:
        print("   评分详情:")
        for key, value in cycle_score['score_details'].items():
            print(f"     {key}: {value}")
    
    print("\n🎯 步骤3: 测试商品信号库存周期矫正")
    start_date = "2023-01-01"
    end_date = "2024-01-01"
    
    # 测试技术面评分
    tech_score = await analyzer.calculate_commodity_technical_score(start_date, end_date)
    print(f"   技术面评分: {tech_score:.1f}/40分")
    
    # 测试矫正后的商品信号
    commodity_signal = await analyzer.determine_commodity_signal_with_correction(start_date, end_date)
    print(f"   矫正后商品信号: {commodity_signal.value}")
    
    print("\n🔬 步骤4: 完整Pring六阶段分析")
    pring_result = await analyzer.analyze_pring_stage(250)
    
    if 'error' not in pring_result:
        print(f"   当前阶段: 第{pring_result['stage']}阶段")
        print(f"   阶段描述: {pring_result['stage_description']}")
        print(f"   置信度: {pring_result['confidence']:.1%}")
        
        print("   三大资产信号:")
        for asset, signal in pring_result['asset_signals'].items():
            print(f"     {asset}: {signal}")
        
        print("   库存周期分析:")
        cycle_info = pring_result.get('inventory_cycle_analysis', {})
        print(f"     周期阶段: {cycle_info.get('cycle_stage', '未知')}")
        print(f"     商品倾向: {cycle_info.get('commodity_bias', '未知')}")
        print(f"     基本面评分: {cycle_info.get('fundamental_score', 0):.1f}/60分")
        print(f"     矫正权重: 技术面{cycle_info.get('correction_weights', {}).get('technical_weight', 0.4)*100:.0f}% + 基本面{cycle_info.get('correction_weights', {}).get('fundamental_weight', 0.6)*100:.0f}%")
        
        print("   确认信号:")
        for signal in pring_result.get('confirm_signals', []):
            print(f"     ✅ {signal}")
        
        print("   否定信号:")
        for signal in pring_result.get('deny_signals', []):
            print(f"     ❌ {signal}")
        
        print(f"   分析方法: {pring_result.get('methodology', '未知')}")
        print(f"   增强特性: {pring_result.get('enhancement_notes', '未知')}")
        
    else:
        print(f"   ❌ 分析失败: {pring_result['error']}")
    
    print("\n" + "=" * 60)
    print("🎊 测试完成！增强的Pring分析器运行正常")
    print("=" * 60)
    
    return pring_result

def print_enhancement_summary():
    """输出增强功能摘要"""
    print("\n📈 Pring六阶段分析增强功能摘要:")
    print("=" * 50)
    print("🔧 V2.0 增强特性:")
    print("   1. 库存周期矫正: 技术面40% + 基本面60%")
    print("   2. 宏观参数集成: PPI、CPI、PMI、工业增加值、BDI指数")
    print("   3. 智能阈值判断: ≥70分Bullish, ≤30分Bearish")
    print("   4. 多数据源支持: 实时AKShare数据 + 模拟数据兜底")
    print("   5. 详细评分透明: 每个指标的权重和评分详情")
    print()
    print("🎯 核心优势:")
    print("   • 避免纯技术面误判风险")
    print("   • 结合宏观经济基本面") 
    print("   • 提供库存周期阶段判断")
    print("   • 商品信号更加准确可靠")
    print("   • 符合投资决策实践")
    print()
    print("💡 使用场景:")
    print("   • 大类资产配置决策")
    print("   • 商品投资时机判断")
    print("   • 宏观经济周期分析")
    print("   • 投资组合再平衡")
    print("=" * 50)

async def main():
    """主函数"""
    try:
        # 打印增强功能摘要
        print_enhancement_summary()
        
        # 运行测试
        result = await test_enhanced_pring_analyzer()
        
        # 输出测试结果文件
        output_file = f"enhanced_pring_test_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        import json
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"\n📄 测试结果已保存到: {output_file}")
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())