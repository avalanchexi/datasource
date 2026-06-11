#!/usr/bin/env python3
"""
增强版市场扫描数据获取脚本 (重构版)
基于 AKShare 和 TuShare 数据源，计算技术指标
整合了原 market_scan_data.py 的功能，使用统一配置管理
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from datasource import get_manager, initialize_default_manager
from datasource.config import A_SHARE_INDICES, TECHNICAL_PARAMS, get_display_name, get_symbol_by_name


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


class EnhancedMarketScanner:
    """增强版市场扫描器 - 重构并整合原有功能"""
    
    def __init__(self):
        self.analyzer = TechnicalAnalyzer()
        self.manager = None
        
    async def initialize(self):
        """初始化数据源管理器"""
        self.manager = await initialize_default_manager()
        return self.manager is not None
        
    async def get_enhanced_stock_data(self, market: str = "A股") -> Dict[str, Any]:
        """获取增强版股指数据 - 使用统一配置"""
        if not self.manager:
            await self.initialize()
            
        end_date = datetime.now().strftime("%Y-%m-%d")
        # 扩大历史数据获取范围以计算MA200
        start_date = (datetime.now() - timedelta(days=300)).strftime("%Y-%m-%d")
        start_date_5 = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        
        indices_data = {}
        
        # 从配置获取指数映射 (替代硬编码)
        if market == "A股":
            indices_config = A_SHARE_INDICES
        else:
            raise ValueError(f"暂不支持市场: {market}")
        
        print(f"开始扫描{market}市场指数...")
        print(f"配置的指数数量: {len(indices_config)}")
        
        for name, config in indices_config.items():
            try:
                symbol = config['symbol']
                display_name = config['display_name']
                print(f"正在获取 {display_name} 数据...")
            
            # 获取长期历史数据用于技术指标计算
            data_long = await manager.get_index_daily(code, start_date, end_date)
            # 获取近期数据用于计算涨跌幅
            data_5d = await manager.get_index_daily(code, start_date_5, end_date)
            
            if not data_long.error and not data_5d.error:
                df_long = data_long.data
                df_5d = data_5d.data
                
                if len(df_long) > 0 and len(df_5d) > 0:
                    # 基本价格数据
                    latest_price = df_long.iloc[-1]['close']
                    
                    # 计算涨跌幅
                    if len(df_long) >= 30:
                        price_30d_ago = df_long.iloc[-30]['close']
                        change_30d = (latest_price - price_30d_ago) / price_30d_ago * 100
                    else:
                        change_30d = None
                        
                    if len(df_5d) >= 5:
                        price_5d_ago = df_5d.iloc[-5]['close']
                        change_5d = (latest_price - price_5d_ago) / price_5d_ago * 100
                    else:
                        change_5d = None
                    
                    # 计算技术指标
                    ma20, ma50, ma200, ma20_slope, ma50_slope, volatility_30d = calculate_technical_indicators(df_long)
                    
                    # 计算趋势评分
                    trend_score, trend_label = calculate_trend_score(
                        latest_price, change_30d, ma50, ma200, ma20_slope
                    )
                    
                    # 格式化结果
                    indices_data[name] = {
                        "近5日%": f"{change_5d:.2f}%" if change_5d is not None else "N/A",
                        "近30日%": f"{change_30d:.2f}%" if change_30d is not None else "N/A",
                        ">MA50?": "是" if (ma50 and latest_price > ma50) else ("否" if ma50 else "N/A（数据不足）"),
                        ">MA200?": "是" if (ma200 and latest_price > ma200) else ("否" if ma200 else "N/A（数据不足）"),
                        "MA20斜率": "↑" if (ma20_slope and ma20_slope > 0) else ("↓" if ma20_slope else "N/A"),
                        "MA50斜率": "↑" if (ma50_slope and ma50_slope > 0) else ("↓" if ma50_slope else "N/A"),
                        "30日年化波动%": f"{volatility_30d:.1f}%" if volatility_30d else "N/A",
                        "趋势评分": trend_score,
                        "趋势标签": f"{trend_label}（评分{trend_score:+d}）"
                    }
                    
                    print(f"{name} 数据获取成功")
                    
        except Exception as e:
            print(f"获取 {name} 数据时出错: {e}")
            indices_data[name] = {
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
    
    return indices_data


def generate_enhanced_table_markdown(indices_data):
    """生成增强版股票综述表格的Markdown"""
    
    markdown = """### 1）股票综述（A股主要指数）

> 注：技术指标基于AKShare/TuShare历史数据本地计算。MA50需要50个交易日样本，MA200需要200个交易日样本。数据不足时标注N/A。

| 标的 | 近5日% | 近30日% | >MA50? | >MA200? | MA20斜率 | MA50斜率 | 30日年化波动% | 趋势评分 | 趋势标签 |
|------|--------|---------|--------|---------|----------|----------|---------------|----------|----------|
"""
    
    for name, data in indices_data.items():
        code_mapping = {
            "上证指数": "000001", "深证成指": "399001", "创业板指": "399006",
            "沪深300": "000300", "上证50": "000016", "中证500": "000905"
        }
        code = code_mapping.get(name, "")
        
        row = f"| {name}（{code}） | {data['近5日%']} | {data['近30日%']} | {data['>MA50?']} | {data['>MA200?']} | {data['MA20斜率']} | {data['MA50斜率']} | {data['30日年化波动%']} | {data['趋势评分']:+d} | {data['趋势标签']} |\n"
        markdown += row
    
    markdown += """
*注：基于AKShare/TuShare数据计算。趋势评分范围-2至+2：近30日涨幅>1%(+1)，收盘>MA50(+1)，MA50>MA200(+1)，MA20斜率为正(+1)，反之扣分。*

**计算说明**：
- **MA斜率**：基于最近5个交易日的移动平均线变化方向
- **年化波动率**：近30个交易日收益率标准差×√252×100%
- **趋势评分**：综合价格位置、均线关系、短期动量的量化评分

"""
    
    return markdown


async def main():
    """主函数"""
    print("开始获取增强版市场扫描数据...")
    
    try:
        # 初始化管理器
        manager = await initialize_default_manager()
        print("数据源管理器初始化成功")
        
        # 检查数据源可用性
        availability = await manager.check_availability()
        print(f"数据源可用性: {availability}")
        
        # 获取增强版股指数据
        print("\n获取股指技术指标数据...")
        indices_data = await get_enhanced_stock_data()
        
        # 生成表格
        table_markdown = generate_enhanced_table_markdown(indices_data)
        
        print("\n=== 增强版股指数据汇总 ===")
        print(table_markdown)
        
        # 保存到文件
        with open("enhanced_stock_table.md", "w", encoding="utf-8") as f:
            f.write(table_markdown)
            
        print("增强版表格已保存到 enhanced_stock_table.md")
        
        return indices_data
        
    except Exception as e:
        print(f"执行过程中出现错误: {e}")
        return {}


if __name__ == "__main__":
    asyncio.run(main())