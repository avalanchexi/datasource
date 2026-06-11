import pandas as pd
import numpy as np
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
import asyncio


class BondCalculator:
    """债券收益率计算器"""
    
    def __init__(self, data_manager):
        self.data_manager = data_manager
    
    async def get_china_bond_yields(self, days: int = 30) -> Dict:
        """
        获取中国债券收益率数据
        
        Args:
            days: 获取天数
            
        Returns:
            债券收益率分析结果
        """
        try:
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            # 尝试获取国债ETF数据作为代理
            bond_etfs = {
                "国债ETF": "511010",  # 5年期国债ETF
                "十年国债": "019649",  # 十年期国债
                "国开债": "019950"     # 国开债代理
            }
            
            results = {}
            
            for name, symbol in bond_etfs.items():
                try:
                    # 尝试获取债券数据
                    response = await self.data_manager.get_stock_daily(symbol, start_date, end_date)
                    
                    if response.error or response.data is None or response.data.empty:
                        results[name] = {
                            "error": f"无法获取{name}数据: {response.error}",
                            "symbol": symbol
                        }
                        continue
                    
                    df = response.data.copy()
                    
                    # 标准化列名
                    column_mapping = {
                        '收盘': 'close',
                        'close': 'close',
                        '开盘': 'open',
                        'open': 'open'
                    }
                    
                    for old_col, new_col in column_mapping.items():
                        if old_col in df.columns:
                            df = df.rename(columns={old_col: new_col})
                    
                    if 'close' not in df.columns:
                        price_cols = [col for col in df.columns if any(keyword in col.lower() 
                                     for keyword in ['price', 'close', '收盘', '价格'])]
                        if price_cols:
                            df['close'] = df[price_cols[0]]
                        else:
                            results[name] = {
                                "error": f"无法找到{name}价格数据",
                                "symbol": symbol
                            }
                            continue
                    
                    # 计算债券价格变化（价格上涨对应收益率下降）
                    prices = df['close'].astype(float)
                    
                    if len(prices) < 2:
                        results[name] = {
                            "error": f"{name}数据不足",
                            "symbol": symbol
                        }
                        continue
                    
                    # 计算价格变化
                    current_price = prices.iloc[-1]
                    
                    # 5日变化
                    if len(prices) >= 6:
                        price_5d_ago = prices.iloc[-6]
                        price_change_5d = ((current_price - price_5d_ago) / price_5d_ago) * 100
                        # 价格上涨对应收益率下降，所以取负值
                        yield_change_5d_bp = -price_change_5d * 100  # 转换为bp
                    else:
                        yield_change_5d_bp = None
                    
                    # 30日变化
                    if len(prices) >= 31:
                        price_30d_ago = prices.iloc[-31]
                        price_change_30d = ((current_price - price_30d_ago) / price_30d_ago) * 100
                        yield_change_30d_bp = -price_change_30d * 100
                    else:
                        yield_change_30d_bp = None
                    
                    results[name] = {
                        "symbol": symbol,
                        "current_price": current_price,
                        "yield_change_5d_bp": yield_change_5d_bp,
                        "yield_change_30d_bp": yield_change_30d_bp,
                        "data_source": response.source,
                        "calculation_method": "基于债券ETF价格反推收益率变化",
                        "last_update": response.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    
                except Exception as e:
                    results[name] = {
                        "error": f"计算{name}收益率时发生错误: {str(e)}",
                        "symbol": symbol
                    }
            
            return results
            
        except Exception as e:
            return {
                "error": f"获取债券数据时发生错误: {str(e)}"
            }
    
    def estimate_china_10y_yield(self, bond_etf_price: float, base_yield: float = 2.5) -> float:
        """
        根据债券ETF价格估算10年期国债收益率
        
        Args:
            bond_etf_price: 债券ETF价格
            base_yield: 基准收益率
            
        Returns:
            估算的收益率
        """
        # 简化的久期模型：价格变化1%约对应收益率变化10bp（对于10年期债券）
        price_change_from_par = (bond_etf_price - 100) / 100  # 假设面值为100
        yield_adjustment = -price_change_from_par * 0.1  # 10年期债券的修正久期约为10
        
        estimated_yield = base_yield + yield_adjustment
        return estimated_yield


class YieldCurveAnalyzer:
    """收益率曲线分析器"""
    
    def __init__(self, data_manager):
        self.data_manager = data_manager
        self.bond_calculator = BondCalculator(data_manager)
    
    async def analyze_yield_curve_trend(self, days: int = 30) -> Dict:
        """
        分析收益率曲线趋势
        
        Args:
            days: 分析天数
            
        Returns:
            收益率曲线趋势分析
        """
        try:
            # 获取不同期限债券数据
            bond_data = await self.bond_calculator.get_china_bond_yields(days)
            
            # 分析趋势
            trend_signals = []
            
            for name, data in bond_data.items():
                if "error" in data:
                    continue
                
                if data.get("yield_change_30d_bp"):
                    if data["yield_change_30d_bp"] < -10:  # 收益率下降超过10bp
                        trend_signals.append("债券牛市")
                    elif data["yield_change_30d_bp"] > 10:   # 收益率上升超过10bp
                        trend_signals.append("债券熊市")
                    else:
                        trend_signals.append("债券震荡")
            
            # 综合判断
            if not trend_signals:
                overall_trend = "数据不足"
            elif trend_signals.count("债券牛市") > len(trend_signals) / 2:
                overall_trend = "债券牛市"
            elif trend_signals.count("债券熊市") > len(trend_signals) / 2:
                overall_trend = "债券熊市"
            else:
                overall_trend = "债券震荡"
            
            return {
                "overall_trend": overall_trend,
                "trend_signals": trend_signals,
                "bond_data": bond_data,
                "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "pring_signal": "Bullish" if overall_trend == "债券牛市" else 
                               ("Bearish" if overall_trend == "债券熊市" else "Neutral")
            }
            
        except Exception as e:
            return {
                "error": f"分析收益率曲线趋势时发生错误: {str(e)}",
                "overall_trend": "分析失败"
            }