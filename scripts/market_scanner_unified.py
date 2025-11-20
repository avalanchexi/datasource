#!/usr/bin/env python3
"""
统一市场扫描器 (重构版)
整合并重构了原有的市场扫描功能，使用统一配置管理
替代 enhanced_market_scan.py 和 market_scan_data.py
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple
import json

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from datasource import get_manager, initialize_default_manager
from datasource.config import (
    A_SHARE_INDICES, US_INDICES, HK_INDICES, 
    TECHNICAL_PARAMS, REPORT_CONFIG,
    get_display_name, get_symbol_by_name
)


class TechnicalAnalyzer:
    """技术分析器 - 基于统一配置的技术指标计算"""
    
    def __init__(self):
        self.params = TECHNICAL_PARAMS
        
    def calculate_technical_indicators(self, df: pd.DataFrame) -> Tuple[Optional[float], ...]:
        """计算技术指标 - 使用配置化参数"""
        if df is None or len(df) == 0:
            return (None,) * 6
        
        try:
            # 确保数据按日期排序
            df = df.sort_values('trade_date') if 'trade_date' in df.columns else df.sort_index()
            
            # 从配置获取MA参数
            ma_periods = self.params['moving_averages']
            ma20_period = ma_periods['short'][2]  # 20
            ma50_period = ma_periods['medium'][0]  # 50  
            ma200_period = ma_periods['long'][0]   # 200
            
            # 计算移动平均线
            df[f'MA{ma20_period}'] = df['close'].rolling(window=ma20_period).mean()
            df[f'MA{ma50_period}'] = df['close'].rolling(window=ma50_period).mean() 
            df[f'MA{ma200_period}'] = df['close'].rolling(window=ma200_period).mean()
            
            # 获取最新数据
            current_price = df['close'].iloc[-1]
            ma20_current = df[f'MA{ma20_period}'].iloc[-1] if len(df) >= ma20_period else None
            ma50_current = df[f'MA{ma50_period}'].iloc[-1] if len(df) >= ma50_period else None
            ma200_current = df[f'MA{ma200_period}'].iloc[-1] if len(df) >= ma200_period else None
            
            # 计算MA斜率（从配置获取周期）
            slope_periods = self.params['trend_scoring']['ma_slope_periods']
            ma20_slope = None
            ma50_slope = None
            
            if len(df) >= ma20_period + slope_periods:
                ma20_slope = (df[f'MA{ma20_period}'].iloc[-1] - 
                             df[f'MA{ma20_period}'].iloc[-(slope_periods+1)]) / slope_periods
            if len(df) >= ma50_period + slope_periods:
                ma50_slope = (df[f'MA{ma50_period}'].iloc[-1] - 
                             df[f'MA{ma50_period}'].iloc[-(slope_periods+1)]) / slope_periods
                
            # 计算波动率（从配置获取参数）
            vol_params = self.params['volatility']
            volatility_30d = None
            
            if len(df) >= vol_params['window']:
                returns = df['close'].pct_change().dropna()
                if len(returns) >= vol_params['window']:
                    volatility_30d = (returns.tail(vol_params['window']).std() * 
                                    np.sqrt(vol_params['annualization_factor']) * 100)
                
            return ma20_current, ma50_current, ma200_current, ma20_slope, ma50_slope, volatility_30d
            
        except Exception as e:
            print(f"计算技术指标时出错: {e}")
            return (None,) * 6

    def calculate_trend_score(self, current_price: float, ret_30d: float, ma50: float, 
                             ma200: float, ma20_slope: float) -> Tuple[int, str]:
        """计算趋势评分 - 基于配置的评分系统"""
        scoring_params = self.params['trend_scoring']
        threshold = scoring_params['price_change_threshold']
        score_range = scoring_params['score_range']
        
        score = 0
        
        # 近30日收益基于配置阈值
        if ret_30d and ret_30d >= threshold:
            score += 1
        elif ret_30d and ret_30d <= -threshold:
            score -= 1
            
        # 收盘高于MA50 (+1分)
        if ma50 and current_price > ma50:
            score += 1
        elif ma50 and current_price < ma50:
            score -= 1
            
        # MA50 > MA200 (+1分)
        if ma50 and ma200:
            if ma50 > ma200:
                score += 1
            else:
                score -= 1
                
        # MA20斜率为正 (+1分)
        if ma20_slope:
            if ma20_slope > 0:
                score += 1
            else:
                score -= 1
        
        # 截断到配置的范围
        score = max(score_range[0], min(score_range[1], score))
        
        # 生成标签
        if score >= 1:
            label = "牛"
        elif score <= -1:
            label = "熊"
        else:
            label = "中性"
            
        return score, label


class UnifiedMarketScanner:
    """统一市场扫描器 - 整合并重构原有功能"""
    
    def __init__(self):
        self.analyzer = TechnicalAnalyzer()
        self.manager = None
        
    async def initialize(self):
        """初始化数据源管理器"""
        try:
            self.manager = await initialize_default_manager()
            availability = await self.manager.check_availability()
            print(f"数据源可用性: {availability}")
            return self.manager is not None
        except Exception as e:
            print(f"初始化失败: {e}")
            return False
        
    async def scan_indices(self, market: str = "A股", days: int = 300) -> Dict[str, Any]:
        """扫描指定市场的指数 - 统一入口"""
        if not self.manager:
            if not await self.initialize():
                return {"error": "数据源初始化失败"}
            
        # 根据市场选择配置
        market_configs = {
            "A股": A_SHARE_INDICES,
            "美股": US_INDICES, 
            "港股": HK_INDICES
        }
        
        if market not in market_configs:
            return {"error": f"不支持的市场: {market}"}
            
        indices_config = market_configs[market]
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        start_date_5 = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        
        indices_data = {}
        
        print(f"开始扫描{market}市场指数...")
        print(f"配置的指数数量: {len(indices_config)}")
        
        for name, config in indices_config.items():
            try:
                symbol = config['symbol']
                display_name = config['display_name']
                print(f"正在获取 {display_name} 数据...")
                
                # 获取长期历史数据用于技术指标计算
                data_long = await self.manager.get_index_daily(symbol, start_date, end_date)
                # 获取近期数据用于计算涨跌幅
                data_5d = await self.manager.get_index_daily(symbol, start_date_5, end_date)
                
                if not data_long.error and not data_5d.error:
                    df_long = data_long.data
                    df_5d = data_5d.data
                    
                    if len(df_long) > 0 and len(df_5d) > 0:
                        # 基本价格数据
                        latest_price = df_long.iloc[-1]['close']
                        
                        # 计算涨跌幅
                        change_30d = None
                        if len(df_long) >= 30:
                            price_30d_ago = df_long.iloc[-30]['close']
                            change_30d = (latest_price - price_30d_ago) / price_30d_ago * 100
                            
                        change_5d = None
                        if len(df_5d) >= 5:
                            price_5d_ago = df_5d.iloc[-5]['close']
                            change_5d = (latest_price - price_5d_ago) / price_5d_ago * 100
                        
                        # 计算技术指标
                        ma20, ma50, ma200, ma20_slope, ma50_slope, volatility_30d = (
                            self.analyzer.calculate_technical_indicators(df_long)
                        )
                        
                        # 计算趋势评分
                        trend_score, trend_label = self.analyzer.calculate_trend_score(
                            latest_price, change_30d, ma50, ma200, ma20_slope
                        )
                        
                        # 格式化结果
                        indices_data[name] = {
                            "symbol": symbol,
                            "display_name": display_name,
                            "current_price": latest_price,
                            "change_5d": change_5d,
                            "change_30d": change_30d,
                            "近5日%": f"{change_5d:.2f}%" if change_5d is not None else "N/A",
                            "近30日%": f"{change_30d:.2f}%" if change_30d is not None else "N/A",
                            ">MA50?": "是" if (ma50 and latest_price > ma50) else ("否" if ma50 else "N/A（数据不足）"),
                            ">MA200?": "是" if (ma200 and latest_price > ma200) else ("否" if ma200 else "N/A（数据不足）"),
                            "MA20斜率": "↑" if (ma20_slope and ma20_slope > 0) else ("↓" if ma20_slope and ma20_slope < 0 else "→"),
                            "MA50斜率": "↑" if (ma50_slope and ma50_slope > 0) else ("↓" if ma50_slope and ma50_slope < 0 else "→"),
                            "30日年化波动%": f"{volatility_30d:.1f}%" if volatility_30d else "N/A",
                            "趋势评分": trend_score,
                            "趋势标签": f"{trend_label}（评分{trend_score:+d}）",
                            "ma_values": {
                                "ma20": ma20,
                                "ma50": ma50,
                                "ma200": ma200
                            },
                            "technical_raw": {
                                "ma20_slope": ma20_slope,
                                "ma50_slope": ma50_slope, 
                                "volatility_30d": volatility_30d
                            }
                        }
                        
                        print(f"{display_name} 数据获取成功")
                    else:
                        indices_data[name] = self._create_error_entry(name, config, "数据为空")
                else:
                    error_msg = data_long.error or data_5d.error
                    indices_data[name] = self._create_error_entry(name, config, f"获取失败: {error_msg}")
                    
            except Exception as e:
                print(f"获取 {name} 数据时出错: {e}")
                indices_data[name] = self._create_error_entry(name, config, f"异常: {str(e)}")
        
        return {
            "market": market,
            "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_period": f"{days}天",
            "indices_count": len(indices_config),
            "successful_count": len([v for v in indices_data.values() if "error" not in v]),
            "indices_data": indices_data
        }
    
    def _create_error_entry(self, name: str, config: Dict, error_msg: str) -> Dict[str, Any]:
        """创建错误条目"""
        return {
            "symbol": config.get('symbol', 'N/A'),
            "display_name": config.get('display_name', name),
            "error": error_msg,
            "近5日%": "N/A",
            "近30日%": "N/A",
            ">MA50?": "N/A（获取失败）",
            ">MA200?": "N/A（获取失败）",
            "MA20斜率": "N/A",
            "MA50斜率": "N/A", 
            "30日年化波动%": "N/A",
            "趋势评分": 0,
            "趋势标签": "N/A（数据获取失败）"
        }

    def generate_markdown_table(self, scan_result: Dict[str, Any]) -> str:
        """生成Markdown表格"""
        if "error" in scan_result:
            return f"# 扫描失败\n\n错误: {scan_result['error']}"
            
        market = scan_result['market']
        scan_time = scan_result['scan_time']
        indices_data = scan_result['indices_data']
        
        markdown = f"""# {market}市场扫描报告
        
**扫描时间**: {scan_time}  
**数据周期**: {scan_result['data_period']}  
**成功率**: {scan_result['successful_count']}/{scan_result['indices_count']}

## 技术指标汇总

| 标的 | 近5日% | 近30日% | >MA50? | >MA200? | MA20斜率 | MA50斜率 | 30日年化波动% | 趋势评分 | 趋势标签 |
|------|--------|---------|--------|---------|----------|----------|---------------|----------|----------|
"""
        
        for name, data in indices_data.items():
            if "error" in data:
                row = f"| {data['display_name']} | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 0 | {data['error'][:30]}... |\n"
            else:
                row = (f"| {data['display_name']} | {data['近5日%']} | {data['近30日%']} | "
                      f"{data['>MA50?']} | {data['>MA200?']} | {data['MA20斜率']} | {data['MA50斜率']} | "
                      f"{data['30日年化波动%']} | {data['趋势评分']:+d} | {data['趋势标签']} |\n")
            markdown += row
        
        markdown += f"""
## 计算说明

- **趋势评分**: 基于4个维度的量化评分 (-2 到 +2)
  - 近30日涨幅 > {TECHNICAL_PARAMS['trend_scoring']['price_change_threshold']}% (+1分)
  - 收盘价 > MA50 (+1分)  
  - MA50 > MA200 (+1分)
  - MA20斜率为正 (+1分)

- **技术指标**: 基于{scan_result['data_period']}历史数据本地计算
- **数据来源**: AKShare/TuShare双重备份
- **更新频率**: 实时扫描

---
*报告生成时间: {scan_time} | 框架版本: 统一市场扫描器v2.0*
"""
        
        return markdown

    async def save_scan_results(self, scan_result: Dict[str, Any], 
                               output_formats: list = ['json', 'markdown']) -> Dict[str, str]:
        """保存扫描结果到多种格式"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        market = scan_result.get('market', 'unknown')
        
        saved_files = {}
        
        # 保存JSON格式
        if 'json' in output_formats:
            json_file = f"market_scan_{market}_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(scan_result, f, ensure_ascii=False, indent=2, default=str)
            saved_files['json'] = json_file
            
        # 保存Markdown格式
        if 'markdown' in output_formats:
            md_file = f"market_scan_{market}_{timestamp}.md"
            markdown_content = self.generate_markdown_table(scan_result)
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            saved_files['markdown'] = md_file
            
        return saved_files


async def main():
    """主函数 - 演示统一市场扫描器的使用"""
    print("🚀 统一市场扫描器启动")
    print("=" * 50)
    
    scanner = UnifiedMarketScanner()
    
    # 扫描A股市场
    print("\n📊 扫描A股市场...")
    a_share_result = await scanner.scan_indices("A股", days=300)
    
    if "error" not in a_share_result:
        print(f"A股扫描完成: {a_share_result['successful_count']}/{a_share_result['indices_count']} 成功")
        
        # 保存结果
        saved_files = await scanner.save_scan_results(a_share_result, ['json', 'markdown'])
        print(f"📁 结果已保存:")
        for format_type, filename in saved_files.items():
            print(f"  - {format_type.upper()}: {filename}")
            
        # 显示部分结果
        print("\n📈 部分扫描结果:")
        for name, data in list(a_share_result['indices_data'].items())[:3]:
            if "error" not in data:
                print(f"  {data['display_name']}: {data['近30日%']} | {data['趋势标签']}")
            else:
                print(f"  {data['display_name']}: {data['error']}")
    else:
        print(f"❌ A股扫描失败: {a_share_result['error']}")
    
    # 生成表格预览
    if "error" not in a_share_result:
        print("\n📋 Markdown表格预览:")
        table_preview = scanner.generate_markdown_table(a_share_result)
        # 显示前20行
        preview_lines = table_preview.split('\n')[:20]
        print('\n'.join(preview_lines))
        if len(table_preview.split('\n')) > 20:
            print("... (更多内容请查看保存的文件)")
    
    print("\n✅ 扫描完成")
    return a_share_result


if __name__ == "__main__":
    asyncio.run(main())